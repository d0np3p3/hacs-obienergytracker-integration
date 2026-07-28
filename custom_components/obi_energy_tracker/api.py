"""API client for Obi EnergyTracker."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Any

from aiohttp import ClientError, ClientSession, WSMsgType
import jwt

from .const import LIVE_DATA_URL

_LOGGER = logging.getLogger(__name__)

# API endpoints
LOGIN_URL = "https://www.obi.de/regi/auth/api/public/login"
ENERGY_TRACKING_URL = "https://energy-tracking-backend.prod-eks.dbs.obi.solutions"

# The heyOBI app sends a fixed key alongside the bearer token. Requests are
# answered without it, but not necessarily with the same completeness, so the
# app's headers are mirrored as closely as possible.
# Key identified by the Karo-X/obi_energy project.
API_KEY = "Rh57q3vtOPYTf6FtArVN1boy2AyEiIqaGEmnMks7"

# The bearer token is a JWT the app re-requests roughly hourly. Nothing in the
# response states its lifetime, so it is renewed well before the hour is out
# rather than waiting for the first 401.
TOKEN_MAX_AGE = timedelta(minutes=55)

_MAX_RETRIES = 3
_RETRY_DELAY = 1  # seconds; doubled on each subsequent attempt

# Measurements carried by live websocket frames.
_LIVE_FIELDS = frozenset({"power", "rssi", "battery"})

# Raw frames to log per connection before falling silent.
_LIVE_FRAMES_TO_LOG = 3


def _iter_json_objects(raw: str) -> list[Any]:
    """Decode a frame that may carry several JSON documents back to back."""
    decoder = json.JSONDecoder()
    objects: list[Any] = []
    index = 0
    length = len(raw)

    while index < length:
        while index < length and raw[index].isspace():
            index += 1
        if index >= length:
            break
        try:
            obj, index = decoder.raw_decode(raw, index)
        except ValueError:
            break
        objects.append(obj)

    return objects


def _extract_live_fields(message: Any) -> dict[str, float]:
    """Pull known measurements out of a frame whose exact shape is unverified.

    The live protocol is undocumented and nests its payload differently across
    app versions -- sometimes as a dict, sometimes as an embedded JSON string.
    Rather than hard-code one layout and silently yield nothing when it shifts,
    walk the whole structure and take the first value found for each field.
    """
    found: dict[str, float] = {}
    pending: list[Any] = [message]

    while pending:
        node = pending.pop()

        if isinstance(node, str):
            stripped = node.lstrip()
            if not stripped.startswith(("{", "[")):
                continue
            try:
                node = json.loads(stripped)
            except ValueError:
                continue

        if isinstance(node, dict):
            for key, value in node.items():
                if (
                    key.lower() in _LIVE_FIELDS
                    and isinstance(value, (int, float))
                    and not isinstance(value, bool)
                ):
                    found.setdefault(key.lower(), float(value))
                else:
                    pending.append(value)
        elif isinstance(node, list):
            pending.extend(node)

    return found


def _numeric_keys(message: Any) -> set[str]:
    """Every key in a frame carrying a plain number.

    Used only for diagnostics: when a device reports a measurement under a name
    this client does not know, the name shows up here and can be added, rather
    than the value silently going missing.
    """
    keys: set[str] = set()
    pending: list[Any] = [message]

    while pending:
        node = pending.pop()

        if isinstance(node, str):
            stripped = node.lstrip()
            if not stripped.startswith(("{", "[")):
                continue
            try:
                node = json.loads(stripped)
            except ValueError:
                continue

        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    keys.add(key)
                else:
                    pending.append(value)
        elif isinstance(node, list):
            pending.extend(node)

    return keys


class ObiEnergyTrackerAPI:
    """API client for Obi EnergyTracker."""

    def __init__(
        self,
        session: ClientSession,
        email: str,
        password: str,
        country: str = "DE",
        bridge_id: str | None = None,
        device_id: str | None = None,
    ) -> None:
        """Initialize the API client."""
        self.session = session
        self.email = email
        self.password = password
        self.country = country
        self.token: str | None = None
        self._token_obtained_at: datetime | None = None
        self._live_frames_logged = 0
        self._live_seen: set[frozenset[str]] = set()
        self._live_unknown_keys: set[str] = set()
        self.bridge_id = bridge_id
        self.device_id = device_id

    async def async_login(self) -> bool:
        """Authenticate with the Obi EnergyTracker API."""
        try:
            payload = {
                "email": self.email,
                "password": self.password,
                "country": self.country,
            }

            headers = {
                "Accept-Encoding": "gzip",
                "Connection": "Keep-Alive",
                "Content-Type": "application/json",
                "x-app-type": "b2c",
                "x-obi-locale": "de-DE",
                "User-Agent": "heyOBI APP / Android Phone 30",
            }

            async with self.session.post(
                LOGIN_URL, json=payload, headers=headers
            ) as response:
                if response.status != 200:
                    _LOGGER.error(
                        "Login failed with status %d",
                        response.status,
                    )
                    return False

                data = await response.json()
                self.token = data.get("token")

                if not self.token:
                    _LOGGER.error("No token received from login response")
                    return False

                self._token_obtained_at = datetime.now(timezone.utc)
                _LOGGER.debug("Successfully authenticated with Obi EnergyTracker")
                return True
        except (OSError, ClientError) as err:
            _LOGGER.error("Login error: %s", err)
            return False

    async def async_ensure_token(self) -> bool:
        """Return a usable token, renewing it once it approaches expiry.

        Without this the integration authenticated once at setup and then held a
        token forever: every later call came back 401, was reported as "no data"
        and left the sensor serving a cached value indefinitely.
        """
        if self.token and self._token_obtained_at is not None:
            if datetime.now(timezone.utc) - self._token_obtained_at < TOKEN_MAX_AGE:
                return True
            _LOGGER.debug("Bearer token is due for renewal")

        return await self.async_login()

    async def async_get_bridge_info(self) -> dict[str, str] | None:
        """Get bridge and device IDs from user profile."""
        if not self.token:
            return None

        try:
            # Decode JWT to get userId
            decoded_token = jwt.decode(self.token, options={"verify_signature": False})
            user_id = decoded_token.get("accountId")

            if not user_id:
                _LOGGER.error("No accountId found in token")
                return None

            url = f"{ENERGY_TRACKING_URL}/users/{user_id}"
            headers = {
                "Accept": "application/vnd.obi.companion.energy-tracking.user.v1+json",
                "Accept-Encoding": "gzip",
                "User-Agent": "app_client",
                "Authorization": f"Bearer {self.token}",
                "Connection": "Keep-Alive",
            }

            async with self.session.get(url, headers=headers) as response:
                if response.status != 200:
                    _LOGGER.error("Failed to get user info: %d", response.status)
                    return None

                data = await response.json()
                bridge = data.get("bridge")
                if not bridge:
                    _LOGGER.error("No bridge found in user info")
                    return None

                self.bridge_id = bridge.get("id")
                sensors = bridge.get("sensors", [])
                if sensors:
                    self.device_id = sensors[0].get("id")

                if not self.bridge_id or not self.device_id:
                    _LOGGER.error("Could not find bridge_id or device_id")
                    return None

                return {
                    "bridge_id": self.bridge_id,
                    "device_id": self.device_id,
                }
        except (jwt.DecodeError, OSError, ClientError) as err:
            _LOGGER.error("Error getting bridge info: %s", err)
            return None

    async def async_get_hourly_data(
        self,
        start_date: datetime | None = None,
        num_days: int = 1,
    ) -> dict[str, Any] | None:
        """Get hourly energy data for multiple days.

        Args:
            start_date: Start date for data retrieval (defaults to today)
            num_days: Number of days to fetch (default 1)

        Returns:
            Dictionary containing hourly energy data
        """
        if not self.token or not self.bridge_id or not self.device_id:
            return None

        if start_date is None:
            start_date = datetime.now(timezone.utc)

        duration_hours = num_days * 24

        # ``start_date`` marks the *end* of the requested history. Anchoring the
        # interval there and adding the duration would ask the API for a window
        # reaching into the future, so step back by the full duration first.
        duration_end = start_date.astimezone(timezone.utc).replace(
            minute=0,
            second=0,
            microsecond=0,
        )
        duration_start = duration_end - timedelta(hours=duration_hours)

        start_str = duration_start.strftime("%Y-%m-%dT%H:%M:%SZ")
        duration_str = f"{start_str}/PT{duration_hours}H"

        _LOGGER.debug("Hourly duration string: %s", duration_str)

        url = (
            f"{ENERGY_TRACKING_URL}/historical-data/"
            f"{self.bridge_id}/{self.device_id}/hourly"
        )
        params = {
            "duration": duration_str,
            "measures": "energy,negative_energy",
        }
        return await self._async_get_json(
            url, params, "hourly data", accepted_empty=(400,)
        )

    async def async_get_meter_data(
        self,
        start: datetime | None = None,
        hours: int = 24,
    ) -> Any | None:
        """Get meter reading data (Zählerstand) for a time window.

        Args:
            start: Beginning of the window; defaults to ``hours`` ago.
            hours: Length of the window in hours.

        Returns:
            The decoded API payload -- a list of ``{"time", "value"}`` records.
        """
        if not self.token or not self.bridge_id or not self.device_id:
            return None

        if start is None:
            start = datetime.now(timezone.utc) - timedelta(hours=hours)

        # The API expects UTC. Building the string from a naive local timestamp
        # while suffixing "Z" would shift the window by the host's UTC offset.
        start_time = start.astimezone(timezone.utc)
        start_time_str = start_time.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        duration_str = f"{start_time_str}/PT{hours}H"

        _LOGGER.debug("Meter duration string: %s", duration_str)

        url = (
            f"{ENERGY_TRACKING_URL}/historical-data/"
            f"{self.bridge_id}/{self.device_id}/meter"
        )
        params = {
            "duration": duration_str,
            "measures": "energy",
        }
        return await self._async_get_json(url, params, "meter data")

    async def _async_get_json(
        self,
        url: str,
        params: dict[str, str],
        description: str,
        accepted_empty: tuple[int, ...] = (),
    ) -> Any | None:
        """GET and decode JSON, renewing a rejected token and retrying."""
        for attempt in range(_MAX_RETRIES):
            if not await self.async_ensure_token():
                return None

            try:
                async with self.session.get(
                    url, params=params, headers=self._get_auth_headers()
                ) as response:
                    if response.status == 200:
                        return await response.json()

                    if response.status == 401:
                        # Rejected ahead of the assumed lifetime; drop it and
                        # let the next pass log in again.
                        _LOGGER.debug("Token rejected for %s, renewing", description)
                        self.token = None
                        self._token_obtained_at = None
                        continue

                    if response.status in accepted_empty:
                        _LOGGER.debug(
                            "No %s for this window (%d)", description, response.status
                        )
                        return None

                    _LOGGER.warning(
                        "Failed to get %s: %d (attempt %d/%d)",
                        description, response.status, attempt + 1, _MAX_RETRIES,
                    )
            except (OSError, ClientError) as err:
                _LOGGER.warning(
                    "Error getting %s (attempt %d/%d): %s",
                    description, attempt + 1, _MAX_RETRIES, err,
                )

            if attempt < _MAX_RETRIES - 1:
                await asyncio.sleep(_RETRY_DELAY * (2**attempt))

        return None

    async def async_set_upload_interval(self, seconds: int) -> bool:
        """Ask the bridge how often the reader should report."""
        if not self.device_id or not await self.async_ensure_token():
            return False

        url = f"{ENERGY_TRACKING_URL}/sensors/{self.device_id}"
        headers = self._get_auth_headers()
        headers["Accept"] = (
            "application/vnd.obi.companion.energy-tracking.sensor.v1+json"
        )
        headers["Content-Type"] = "application/json"

        try:
            async with self.session.patch(
                url,
                json={"id": self.device_id, "uploadInterval": seconds},
                headers=headers,
            ) as response:
                if response.status in (200, 204):
                    _LOGGER.debug("Upload interval set to %ds", seconds)
                    return True
                _LOGGER.warning(
                    "Could not set upload interval to %ds: %d", seconds, response.status
                )
                return False
        except (OSError, ClientError) as err:
            _LOGGER.warning("Error setting upload interval: %s", err)
            return False

    async def async_live_messages(self) -> AsyncIterator[dict[str, float]]:
        """Yield live measurements for as long as the websocket stays up."""
        if not self.bridge_id or not self.device_id:
            return
        if not await self.async_ensure_token():
            return

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "*/*",
            "Accept-Language": "de-DE,de;q=0.9",
            "User-Agent": "app_client",
            "x-api-key": API_KEY,
            "X-Platform": "iOS",
            "X-Lib-Version": "26.6.9",
        }

        async with self.session.ws_connect(
            LIVE_DATA_URL,
            params={"bridgeId": self.bridge_id, "sensorId": self.device_id},
            headers=headers,
            heartbeat=30,
            timeout=30,
            compress=15,
        ) as socket:
            _LOGGER.debug("Live websocket connected")

            async for frame in socket:
                if frame.type is not WSMsgType.TEXT:
                    if frame.type in (WSMsgType.CLOSED, WSMsgType.ERROR):
                        break
                    continue

                # The payload layout is undocumented. Dump the opening frames
                # verbatim so a shape that yields nothing can be diagnosed from
                # a log alone; at the two-second cadence anything beyond a
                # handful would just flood the log.
                if self._live_frames_logged < _LIVE_FRAMES_TO_LOG:
                    self._live_frames_logged += 1
                    _LOGGER.debug(
                        "Live frame %d/%d: %s",
                        self._live_frames_logged,
                        _LIVE_FRAMES_TO_LOG,
                        frame.data,
                    )

                for message in _iter_json_objects(frame.data):
                    measurements = _extract_live_fields(message)

                    # Devices differ in what they report and how often. Logging
                    # only the opening frames would miss a measurement that
                    # arrives on a slower cycle than power, so log the first
                    # frame to carry each new combination as well.
                    combination = frozenset(measurements)
                    if combination and combination not in self._live_seen:
                        self._live_seen.add(combination)
                        _LOGGER.debug(
                            "Live frame carrying %s: %s",
                            sorted(combination) or "nothing",
                            frame.data,
                        )

                    # Names this client does not know are the likeliest reason a
                    # measurement never shows up, so report them once.
                    unknown = {
                        key
                        for key in _numeric_keys(message)
                        if key.lower() not in _LIVE_FIELDS
                    } - self._live_unknown_keys
                    if unknown:
                        self._live_unknown_keys |= unknown
                        _LOGGER.debug(
                            "Live frame has unrecognised numeric fields: %s",
                            sorted(unknown),
                        )

                    if measurements:
                        yield measurements
                    elif self._live_frames_logged <= _LIVE_FRAMES_TO_LOG:
                        # Parsed cleanly but held nothing recognisable -- the
                        # exact failure the tolerant parser is meant to survive.
                        _LOGGER.debug(
                            "Live frame carried no known measurement: %s", message
                        )

    def _get_auth_headers(self) -> dict[str, str]:
        """Get headers with authorization token."""
        accept_header = (
            "application/vnd.obi.companion.energy-tracking.historical-record.v1+json"
        )
        return {
            "Accept": accept_header,
            "Accept-Encoding": "gzip",
            "User-Agent": "app_client",
            "Authorization": f"Bearer {self.token}",
            "x-api-key": API_KEY,
            # Historical windows are re-requested with shifting bounds while
            # backfilling; a cached response would silently repeat the previous
            # window's records.
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Connection": "Keep-Alive",
        }
