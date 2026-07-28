"""Sensor platform for Obi EnergyTracker."""
from __future__ import annotations

import logging
from typing import Any

from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfPower,
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
        ObiLivePowerSensor(coordinator),
        ObiLiveBatterySensor(coordinator),
        ObiLiveSignalSensor(coordinator),
        ObiLiveLastMessageSensor(coordinator),
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
    # The API reports whole watt-hours (e.g. 17320752); Home Assistant converts
    # to kWh for display, which is why states read like 17320.752.
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
        """Write state only when the reading actually moved.

        The coordinator polls more often than the meter advances, so writing on
        every refresh fills the recorder with identical rows.
        """
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


class ObiLiveSensorBase(ObiEnergySensorBase):
    """Base for values pushed over the live websocket."""

    _live_key: str

    @property
    def available(self) -> bool:
        """Report unavailable when the value is stale or simply not reported.

        Holding the last pushed number on screen after the socket died would
        misrepresent a stale reading as current. Not every device reports every
        measurement either -- one that never sends a battery level should show
        an unavailable entity rather than an indefinitely unknown one.
        """
        return (
            super().available
            and not self.coordinator.live_stale
            and self._live_key in self.coordinator.live
        )

    @property
    def native_value(self) -> float | None:
        """Return the most recent pushed measurement."""
        return self.coordinator.live.get(self._live_key)


class ObiLivePowerSensor(ObiLiveSensorBase):
    """Instantaneous power draw."""

    _live_key = "power"
    _attr_name = "Live Power"
    _attr_unique_id = "obi_energytracker_live_power"
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT


class ObiLiveBatterySensor(ObiLiveSensorBase):
    """Battery level of the meter reader."""

    _live_key = "battery"
    _attr_name = "Reader Battery"
    _attr_unique_id = "obi_energytracker_live_battery"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC


class ObiLiveSignalSensor(ObiLiveSensorBase):
    """Radio signal strength reported by the reader."""

    _live_key = "rssi"
    _attr_name = "Reader Signal Strength"
    _attr_unique_id = "obi_energytracker_live_rssi"
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC


class ObiLiveLastMessageSensor(ObiEnergySensorBase):
    """When the last live frame arrived."""

    _attr_name = "Last Live Message"
    _attr_unique_id = "obi_energytracker_live_last_message"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> datetime | None:
        """Return the arrival time of the last frame.

        Deliberately stays available while stale -- its whole purpose is to show
        how long the silence has lasted.
        """
        return self.coordinator.live_last_message
