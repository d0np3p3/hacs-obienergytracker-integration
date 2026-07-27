"""API client for Obi EnergyTracker."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from aiohttp import ClientError, ClientSession
import jwt

_LOGGER = logging.getLogger(__name__)

# API endpoints
LOGIN_URL = "https://www.obi.de/regi/auth/api/public/login"
ENERGY_TRACKING_URL = "https://energy-tracking-backend.prod-eks.dbs.obi.solutions"

# The heyOBI app sends a fixed key alongside the bearer token. Requests are
# answered without it, but not necessarily with the same completeness, so the
# app's headers are mirrored as closely as possible.
# Key identified by the Karo-X/obi_energy project.
API_KEY = "Rh57q3vtOPYTf6FtArVN1boy2AyEiIqaGEmnMks7"

_MAX_RETRIES = 3
_RETRY_DELAY = 1  # seconds; doubled on each subsequent attempt


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

                _LOGGER.debug("Successfully authenticated with Obi EnergyTracker")
                return True
        except (OSError, ClientError) as err:
            _LOGGER.error("Login error: %s", err)
            return False

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
        headers = self._get_auth_headers()

        for attempt in range(_MAX_RETRIES):
            try:
                async with self.session.get(
                    url, params=params, headers=headers
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    if response.status == 400:
                        _LOGGER.debug(
                            "Hourly data unavailable for duration %s (400)", duration_str
                        )
                        return None
                    _LOGGER.warning(
                        "Failed to get hourly data: %d (attempt %d/%d)",
                        response.status, attempt + 1, _MAX_RETRIES,
                    )
            except (OSError, ClientError) as err:
                _LOGGER.warning(
                    "Error getting hourly data (attempt %d/%d): %s",
                    attempt + 1, _MAX_RETRIES, err,
                )
            if attempt < _MAX_RETRIES - 1:
                await asyncio.sleep(_RETRY_DELAY * (2 ** attempt))
        return None

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
        headers = self._get_auth_headers()

        for attempt in range(_MAX_RETRIES):
            try:
                async with self.session.get(
                    url, params=params, headers=headers
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    _LOGGER.warning(
                        "Failed to get meter data: %d (attempt %d/%d)",
                        response.status, attempt + 1, _MAX_RETRIES,
                    )
            except (OSError, ClientError) as err:
                _LOGGER.warning(
                    "Error getting meter data (attempt %d/%d): %s",
                    attempt + 1, _MAX_RETRIES, err,
                )
            if attempt < _MAX_RETRIES - 1:
                await asyncio.sleep(_RETRY_DELAY * (2 ** attempt))
        return None

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
