"""Button entities for Lithe Audio — reboot (and Micro Subwoofer save)."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_PRODUCT, DATA_COORDINATOR, DOMAIN, caps
from .coordinator import LitheAudioCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: LitheAudioCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    product = entry.data[CONF_PRODUCT]

    entities: list[ButtonEntity] = []
    if caps(product)["subwoofer_controls"]:
        entities.append(LitheSubwooferSaveButton(coordinator, entry))
    entities.append(LitheRebootButton(coordinator, entry))
    async_add_entities(entities)


class _LitheBaseButton(CoordinatorEntity[LitheAudioCoordinator], ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: LitheAudioCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._client = coordinator.client

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry.data["host"])})

    @property
    def available(self) -> bool:
        return self._client.state.connected

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


class LitheSubwooferSaveButton(_LitheBaseButton):
    """Commit every custom Micro Subwoofer setting as one user action."""

    _attr_name = "Subwoofer — Save Changes"
    _attr_icon = "mdi:content-save"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = (
            f"{entry.data['host']}_{entry.entry_id}_sub_save"
        )

    @property
    def available(self) -> bool:
        return self._client.state.connected and self._client.state.sub_profile == 2

    async def async_press(self) -> None:
        state = self._client.state
        await self._client.async_save_subwoofer_custom(
            gain=state.sub_gain if state.sub_gain is not None else 50,
            crossover=(
                state.sub_crossover if state.sub_crossover is not None else 0
            ),
            phase=state.sub_phase if state.sub_phase is not None else 0,
            lowpass=state.sub_lowpass if state.sub_lowpass is not None else 1,
        )


class LitheRebootButton(_LitheBaseButton):
    _attr_name = "Actions — Reboot"
    _attr_icon = "mdi:restart"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = None

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.data['host']}_{entry.entry_id}_reboot"

    async def async_press(self) -> None:
        await self._client.async_reboot()
