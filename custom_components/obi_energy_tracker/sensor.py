"""Sensor platform for Obi EnergyTracker."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ObiEnergyTrackerConfigEntry
from .const import DOMAIN
from .coordinator import ObiEnergyTrackerCoordinator

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ObiEnergyTrackerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors from a config entry."""
    coordinator = config_entry.runtime_data

    sensors = [
        ObiMeterReadingSensor(coordinator),
    ]

    async_add_entities(sensors)


class ObiEnergySensorBase(
    CoordinatorEntity[ObiEnergyTrackerCoordinator],
    SensorEntity,
):
    """Base class for Obi EnergyTracker sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ObiEnergyTrackerCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)

        self._attr_device_info = {
            "identifiers": {(DOMAIN, "obi_energy_tracker")},
            "name": "Obi EnergyTracker",
            "manufacturer": "Obi",
        }

    def _get_latest_meter_value(self) -> float | None:
        """Return latest meter value from current payload."""
        if not self.coordinator.data:
            return None

        meter_data = self.coordinator.data.get("meter")

        if not meter_data or not isinstance(meter_data, list):
            return None

        for item in reversed(meter_data):
            if not isinstance(item, dict):
                continue

            if "value" in item:
                try:
                    return float(item["value"])
                except (TypeError, ValueError):
                    continue

        return None


class ObiMeterReadingSensor(ObiEnergySensorBase):
    """Sensor for meter reading."""

    _attr_name = "Meter Reading"
    _attr_unique_id = "obi_energytracker_meter_reading"
    _attr_native_unit_of_measurement = "Wh"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:lightning-bolt"

    def __init__(self, coordinator: ObiEnergyTrackerCoordinator) -> None:
        """Initialize the meter reading sensor."""
        super().__init__(coordinator)
        self._last_native_value: float | None = None
        self._last_native_value_set = False

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle coordinator updates and suppress duplicate readings."""
        new_value = self.native_value
        if not self._last_native_value_set or new_value != self._last_native_value:
            self._last_native_value_set = True
            self._last_native_value = new_value
            self.async_write_ha_state()

    @property
    def native_value(self) -> float | None:
        """Return the meter reading value."""
        _LOGGER.debug(
            "ObiMeterReadingSensor native_value called. Data: %s",
            self.coordinator.data,
        )

        current_value = self._get_latest_meter_value()

        if current_value is not None:
            return current_value

        if self.coordinator.data:
            last_value = self.coordinator.data.get("last_meter_value")

            if last_value is not None:
                _LOGGER.debug(
                    "Using cached last meter value as fallback: %s",
                    last_value,
                )
                return float(last_value)

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return debug attributes."""
        if not self.coordinator.data:
            return {}

        return {
            "last_meter_value": self.coordinator.data.get(
                "last_meter_value"
            ),
            "last_meter_time": self.coordinator.data.get(
                "last_meter_time"
            ),
            "fallback_active": self._get_latest_meter_value() is None,
        }
