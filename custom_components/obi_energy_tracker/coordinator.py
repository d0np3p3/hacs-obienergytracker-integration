"""Data update coordinator for Obi EnergyTracker."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from aiohttp import ClientError

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ObiEnergyTrackerAPI
from .const import DOMAIN, LIVE_METER_HOURS
from .statistics import async_backfill_statistics

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=5)
DAYS_OF_HISTORY = 7


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

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from API endpoint."""
        try:
            meter = await self.api.async_get_meter_data(hours=LIVE_METER_HOURS)
            _LOGGER.debug("Meter data: %s", meter)

            end_date = datetime.now(timezone.utc)
            hourly_data = await self.api.async_get_hourly_data(
                start_date=end_date,
                num_days=DAYS_OF_HISTORY,
            )

            _LOGGER.debug(
                "Hourly data fetched: %s",
                "available" if hourly_data else "none",
            )

            latest_meter = self._extract_latest_meter(meter)
            if latest_meter is not None:
                self._last_meter_value = latest_meter["value"]
                self._last_meter_time = latest_meter["time"]

            _LOGGER.info(
                "Successfully fetched data: meter=%s, hourly_days=%d",
                "available" if meter else "none",
                DAYS_OF_HISTORY,
            )

        # aiohttp raises ClientError, which is not an OSError, so catching only
        # the latter would let network failures escape UpdateFailed and rob the
        # coordinator of its retry handling.
        except (OSError, ClientError) as err:
            _LOGGER.error("Failed to update data: %s", err)
            raise UpdateFailed(f"Failed to update data: {err}") from err

        # Replay anything the recorder missed while polling was failing. A
        # backfill problem must not take the live reading down with it.
        try:
            await async_backfill_statistics(self.hass, self.api)
        except (OSError, ClientError) as err:
            _LOGGER.warning("Could not backfill meter statistics: %s", err)

        return {
            "hourly": hourly_data,
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
