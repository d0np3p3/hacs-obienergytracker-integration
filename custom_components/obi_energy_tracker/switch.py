"""Switch platform for Obi EnergyTracker."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ObiEnergyTrackerConfigEntry
from .const import DOMAIN
from .coordinator import ObiEnergyTrackerCoordinator

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ObiEnergyTrackerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switches from a config entry."""
    async_add_entities([ObiLiveModeSwitch(config_entry.runtime_data)])


class ObiLiveModeSwitch(
    CoordinatorEntity[ObiEnergyTrackerCoordinator],
    SwitchEntity,
):
    """Toggle two-second reporting on the meter reader.

    Off by default and reset on unload: the reader is battery powered, and the
    app only asks for this cadence while its live view is open.
    """

    _attr_has_entity_name = True
    _attr_name = "Live Mode"
    _attr_unique_id = "obi_energytracker_live_mode"
    _attr_icon = "mdi:flash"

    def __init__(self, coordinator: ObiEnergyTrackerCoordinator) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)

        self._attr_device_info = {
            "identifiers": {(DOMAIN, "obi_energy_tracker")},
            "name": "Obi EnergyTracker",
            "manufacturer": "Obi",
        }

    @property
    def is_on(self) -> bool:
        """Return whether the reader is on the fast interval."""
        return self.coordinator.live_mode

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Ask the reader to report every two seconds."""
        if not await self.coordinator.async_set_live_mode(True):
            _LOGGER.warning("Could not enable live mode")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Return the reader to its normal reporting interval."""
        if not await self.coordinator.async_set_live_mode(False):
            _LOGGER.warning("Could not disable live mode")
