"""Data update coordinator for Obi EnergyTracker."""
from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta
import logging
from typing import Any

from aiohttp import ClientError

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import ObiEnergyTrackerAPI
from .const import (
    DOMAIN,
    LIVE_METER_HOURS,
    LIVE_RECONNECT_DELAY,
    LIVE_RECONNECT_MAX,
    LIVE_STALE_AFTER,
    UPLOAD_INTERVAL_LIVE,
    UPLOAD_INTERVAL_NORMAL,
)
from .statistics import async_backfill_statistics

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=5)


class ObiEnergyTrackerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Data update coordinator for Obi EnergyTracker."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: ObiEnergyTrackerAPI,
        config_entry: Any,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
            config_entry=config_entry,
        )
        self.api = api
        self._last_meter_value: float | None = None
        self._last_meter_time: str | None = None

        # Live state arrives out of band over the websocket, so it is kept
        # beside the polled payload rather than inside it -- writing it into
        # self.data would reset the polling timer on every pushed frame.
        self.live: dict[str, float] = {}
        self.live_last_message: datetime | None = None
        self.live_mode = False
        self._live_task: asyncio.Task[None] | None = None
        self._live_stop = asyncio.Event()
        self._backfill_task: asyncio.Task[None] | None = None

    def _schedule_backfill(self) -> None:
        """Run the statistics backfill outside the update cycle."""
        if self._backfill_task is not None and not self._backfill_task.done():
            # Still working through a long gap; a second pass would re-request
            # the same windows.
            return

        self._backfill_task = self.config_entry.async_create_background_task(
            self.hass, self._async_backfill(), f"{DOMAIN}_backfill"
        )

    async def _async_backfill(self) -> None:
        """Import missing statistics, keeping failures away from the sensor."""
        try:
            await async_backfill_statistics(self.hass, self.api)
        except asyncio.CancelledError:
            raise
        except (OSError, ClientError) as err:
            _LOGGER.warning("Could not backfill meter statistics: %s", err)

    @property
    def live_stale(self) -> bool:
        """Return whether the push channel has gone quiet."""
        if self.live_last_message is None:
            return True
        age = (dt_util.utcnow() - self.live_last_message).total_seconds()
        return age > LIVE_STALE_AFTER

    def async_start_live(self) -> None:
        """Begin consuming the live websocket."""
        if self._live_task is not None:
            return
        self._live_stop.clear()
        self._live_task = self.config_entry.async_create_background_task(
            self.hass, self._async_live_loop(), f"{DOMAIN}_live"
        )

    async def async_stop_live(self) -> None:
        """Stop background work and restore the normal upload interval."""
        self._live_stop.set()

        for task in (self._live_task, self._backfill_task):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._live_task = None
        self._backfill_task = None

        if self.live_mode:
            await self.api.async_set_upload_interval(UPLOAD_INTERVAL_NORMAL)
            self.live_mode = False

    async def async_set_live_mode(self, enabled: bool) -> bool:
        """Switch the reader between two-second and five-minute reporting."""
        interval = UPLOAD_INTERVAL_LIVE if enabled else UPLOAD_INTERVAL_NORMAL

        if not await self.api.async_set_upload_interval(interval):
            return False

        self.live_mode = enabled
        self.async_update_listeners()
        return True

    async def _async_live_loop(self) -> None:
        """Hold the websocket open, reconnecting until asked to stop."""
        delay = LIVE_RECONNECT_DELAY

        while not self._live_stop.is_set():
            received = False

            try:
                async for measurements in self.api.async_live_messages():
                    if self._live_stop.is_set():
                        break
                    received = True
                    self.live.update(measurements)
                    self.live_last_message = dt_util.utcnow()
                    self.async_update_listeners()
            except asyncio.CancelledError:
                raise
            except (OSError, ClientError) as err:
                _LOGGER.debug("Live websocket dropped: %s", err)
            except Exception:  # noqa: BLE001 - undocumented protocol
                _LOGGER.exception("Unexpected error on the live websocket")

            if self._live_stop.is_set():
                break

            if received:
                # The socket works; treat this as an ordinary drop.
                delay = LIVE_RECONNECT_DELAY
            else:
                delay = min(delay * 2, LIVE_RECONNECT_MAX)
                _LOGGER.debug("No live frames received, retrying in %ds", delay)

            # Wait before reconnecting, but wake immediately on shutdown.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._live_stop.wait(), timeout=delay)

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from API endpoint."""
        try:
            meter = await self.api.async_get_meter_data(hours=LIVE_METER_HOURS)
            _LOGGER.debug("Meter data: %s", meter)

            latest_meter = self._extract_latest_meter(meter)
            if latest_meter is not None:
                self._last_meter_value = latest_meter["value"]
                self._last_meter_time = latest_meter["time"]

            _LOGGER.debug(
                "Fetched meter data: %s", "available" if meter else "none"
            )

        # aiohttp raises ClientError, which is not an OSError, so catching only
        # the latter would let network failures escape UpdateFailed and rob the
        # coordinator of its retry handling.
        except (OSError, ClientError) as err:
            _LOGGER.error("Failed to update data: %s", err)
            raise UpdateFailed(f"Failed to update data: {err}") from err

        # Replay anything the recorder missed while polling was failing. This
        # runs detached: closing a month-long gap costs dozens of requests, and
        # awaiting it here held config entry setup for half a minute on the
        # first refresh.
        self._schedule_backfill()

        return {
            "meter": meter,
            "last_meter_value": self._last_meter_value,
            "last_meter_time": self._last_meter_time,
        }

    def _extract_latest_meter(self, meter_data: Any) -> dict[str, Any] | None:
        """Extract the latest valid meter reading."""
        if not meter_data or not isinstance(meter_data, list):
            return None

        for item in reversed(meter_data):
            if not isinstance(item, dict):
                continue

            if "value" not in item or "time" not in item:
                continue

            return {
                "value": float(item["value"]),
                "time": item["time"],
            }

        return None
