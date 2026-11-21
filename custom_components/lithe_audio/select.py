"""Select entities for Lithe Audio DSP selectors."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_PRODUCT,
    DATA_COORDINATOR,
    DOMAIN,
    DSP_EQ,
    DSP_HIGHPASS,
    DSP_OUTPUT,
    DSP_TUNING,
    EQ_PRESETS,
    HP_OPTIONS,
    IO1_EQ_PRESETS,
    OUT_OPTIONS,
    PRODUCT_IO1,
    SUB_CROSSOVER_OPTIONS,
    SUB_DSP_CROSSOVER,
    SUB_DSP_PHASE,
    SUB_DSP_PROFILE,
    SUB_DSP_SET_FIELD,
    SUB_PHASE_OPTIONS,
    SUB_PROFILE_OPTIONS,
    TUNING_OPTIONS,
    audio_control_name,
    caps,
)
from .coordinator import LitheAudioCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: LitheAudioCoordinator = hass.data[DOMAIN][entry.entry_id][
        DATA_COORDINATOR
    ]
    product = entry.data[CONF_PRODUCT]
    c = caps(product)

    entities: list[SelectEntity] = []
    if c["eq_select"]:
        entities.append(LitheEqSelect(coordinator, entry))
    if c["output_select"]:
        entities.append(LitheOutputSelect(coordinator, entry))
    if c["highpass_select"]:
        entities.append(LitheHighPassSelect(coordinator, entry))
    if c["tuning_select"]:
        entities.append(LitheTuningSelect(coordinator, entry))
    if c["subwoofer_controls"]:
        entities.extend((
            LitheSubwooferProfileSelect(coordinator, entry),
            LitheSubwooferCrossoverSelect(coordinator, entry),
            LitheSubwooferPhaseSelect(coordinator, entry),
        ))

    if entities:
        async_add_entities(entities)


class _LitheBaseSelect(CoordinatorEntity[LitheAudioCoordinator], SelectEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: LitheAudioCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._client = coordinator.client
        options = getattr(self, "_attr_options", ())
        self._current: str = options[0] if options else ""

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry.data["host"])})

    @property
    def available(self) -> bool:
        return self._client.state.connected

    @property
    def current_option(self) -> str | None:
        return self._current

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


class LitheSubwooferProfileSelect(_LitheBaseSelect, RestoreEntity):
    """Micro Subwoofer EQ profile."""

    _attr_name = "Subwoofer — EQ Preset"
    _attr_options = SUB_PROFILE_OPTIONS
    _attr_icon = "mdi:equalizer"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = (
            f"{entry.data['host']}_{entry.entry_id}_sub_profile"
        )

    @property
    def current_option(self) -> str:
        value = self._client.state.sub_profile
        if isinstance(value, int) and 0 <= value < len(self._attr_options):
            return self._attr_options[value]
        return self._current

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in self._attr_options:
            self._current = last_state.state
            if self._client.state.sub_profile is None:
                self._client.state.restore_dsp_snapshot({
                    "sub_profile": self._attr_options.index(self._current),
                })

    async def async_select_option(self, option: str) -> None:
        index = self._attr_options.index(option)
        self._current = option
        await self._client.async_dsp_command(
            SUB_DSP_PROFILE, index, SUB_DSP_SET_FIELD
        )
        self.coordinator.async_set_updated_data(self._client.state)


class LitheSubwooferCrossoverSelect(_LitheBaseSelect, RestoreEntity):
    """Micro Subwoofer custom crossover frequency."""

    _attr_name = "Subwoofer — Crossover"
    _attr_options = SUB_CROSSOVER_OPTIONS
    _attr_icon = "mdi:sine-wave"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = (
            f"{entry.data['host']}_{entry.entry_id}_sub_crossover"
        )
        self._current = self._attr_options[0]

    @property
    def available(self) -> bool:
        return self._client.state.connected and self._client.state.sub_profile == 2

    @property
    def current_option(self) -> str:
        value = self._client.state.sub_crossover
        if isinstance(value, int) and 0 <= value < len(self._attr_options):
            return self._attr_options[value]
        return self._current

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in self._attr_options:
            self._current = last_state.state
            if self._client.state.sub_crossover is None:
                self._client.state.restore_dsp_snapshot({
                    "sub_crossover": self._attr_options.index(self._current),
                })

    async def async_select_option(self, option: str) -> None:
        index = self._attr_options.index(option)
        self._current = option
        await self._client.async_dsp_command(
            SUB_DSP_CROSSOVER, index, SUB_DSP_SET_FIELD
        )
        self.async_write_ha_state()


class LitheSubwooferPhaseSelect(_LitheBaseSelect, RestoreEntity):
    """Micro Subwoofer custom phase."""

    _attr_name = "Subwoofer — Phase"
    _attr_options = SUB_PHASE_OPTIONS
    _attr_icon = "mdi:rotate-3d-variant"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.data['host']}_{entry.entry_id}_sub_phase"
        self._current = self._attr_options[0]

    @property
    def available(self) -> bool:
        return self._client.state.connected and self._client.state.sub_profile == 2

    @property
    def current_option(self) -> str:
        value = self._client.state.sub_phase
        if isinstance(value, int) and 0 <= value < len(self._attr_options):
            return self._attr_options[value]
        return self._current

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in self._attr_options:
            self._current = last_state.state
            if self._client.state.sub_phase is None:
                self._client.state.restore_dsp_snapshot({
                    "sub_phase": self._attr_options.index(self._current),
                })

    async def async_select_option(self, option: str) -> None:
        index = self._attr_options.index(option)
        self._current = option
        await self._client.async_dsp_command(
            SUB_DSP_PHASE, index, SUB_DSP_SET_FIELD
        )
        self.async_write_ha_state()


class LitheEqSelect(_LitheBaseSelect, RestoreEntity):
    """EQ Preset selector."""

    _attr_name = audio_control_name(1, "EQ Preset")
    _attr_options = EQ_PRESETS
    _attr_icon = "mdi:equalizer"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_options = (
            IO1_EQ_PRESETS
            if entry.data[CONF_PRODUCT] == PRODUCT_IO1
            else EQ_PRESETS
        )
        self._io1 = entry.data[CONF_PRODUCT] == PRODUCT_IO1
        self._attr_unique_id = f"{entry.data['host']}_{entry.entry_id}_eq"
        self._current = self._attr_options[0]
        self._optimistic_until: float = 0.0

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Never present recorder history as current speaker state. Several
        # LS10 firmware builds omit EQ from startup reports; those controls
        # must remain unavailable until genuine feedback or a successful
        # local command establishes the value.

    @property
    def available(self) -> bool:
        return (
            self._client.state.connected
            and isinstance(self._client.state.dsp_eq, int)
        )

    @property
    def current_option(self) -> str:
        import time
        if time.monotonic() >= self._optimistic_until:
            value = getattr(self._client.state, "dsp_eq", None)
            if isinstance(value, int) and 0 <= value < len(self._attr_options):
                return self._attr_options[value]
        return None

    async def async_select_option(self, option: str) -> None:
        import time
        idx = self._attr_options.index(option) if option in self._attr_options else 0
        self._current = option
        self._optimistic_until = time.monotonic() + 5.0
        if self._io1:
            await self._client.async_io1_preset_command(idx)
        else:
            await self._client.async_dsp_command(DSP_EQ, idx)
        self.async_write_ha_state()


class LitheOutputSelect(_LitheBaseSelect, RestoreEntity):
    """Speaker Output selector."""

    _attr_name = audio_control_name(6, "Speaker Output")
    _attr_options = OUT_OPTIONS
    _attr_icon = "mdi:speaker"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.data['host']}_{entry.entry_id}_output"
        self._current = "Stereo"
        self._optimistic_until: float = 0.0

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in OUT_OPTIONS:
            self._current = last_state.state
            if self._client.state.dsp_output is None:
                self._client.state.restore_dsp_snapshot({
                    "dsp_output": OUT_OPTIONS.index(self._current),
                })

    @property
    def current_option(self) -> str:
        import time
        if time.monotonic() >= self._optimistic_until:
            value = getattr(self._client.state, "dsp_output", None)
            if isinstance(value, int) and 0 <= value < len(OUT_OPTIONS):
                return OUT_OPTIONS[value]
        return self._current

    async def async_select_option(self, option: str) -> None:
        import time
        idx = OUT_OPTIONS.index(option) if option in OUT_OPTIONS else 0
        self._current = option
        self._optimistic_until = time.monotonic() + 5.0
        await self._client.async_dsp_command(DSP_OUTPUT, idx)
        self.async_write_ha_state()


class LitheHighPassSelect(_LitheBaseSelect, RestoreEntity):
    """PRO 2 high-pass frequency selector (MCU HOSTMCUSETTINGS 0x32)."""

    _attr_name = audio_control_name(8, "High Pass Frequency")
    _attr_options = HP_OPTIONS
    _attr_icon = "mdi:filter"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.data['host']}_{entry.entry_id}_highpass"
        self._current = HP_OPTIONS[0]
        self._optimistic_until: float = 0.0

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is None or last_state.state not in HP_OPTIONS:
            return

        # Keep the last speaker-confirmed HA value visible until a new MB#112
        # broadcast arrives. Never write restored UI state back to the speaker
        # during startup.
        self._current = last_state.state
        if self._client.state.dsp_highpass is None:
            self._client.state.restore_dsp_snapshot({
                "dsp_highpass": HP_OPTIONS.index(self._current),
            })

    @property
    def available(self) -> bool:
        # Frequency is meaningful only while open-back/high-pass protection
        # is enabled by the separate High Pass Filter switch.
        return (
            self._client.state.connected
            and self._client.state.dsp_tuning == 1
        )

    @property
    def current_option(self) -> str:
        import time
        if time.monotonic() >= self._optimistic_until:
            value = getattr(self._client.state, "dsp_highpass", None)
            if isinstance(value, int) and 0 <= value < len(HP_OPTIONS):
                return HP_OPTIONS[value]
        return self._current

    async def async_select_option(self, option: str) -> None:
        import time
        idx = HP_OPTIONS.index(option) if option in HP_OPTIONS else 0
        self._current = HP_OPTIONS[idx]
        self._optimistic_until = time.monotonic() + 5.0
        await self._client.async_dsp_command(DSP_HIGHPASS, idx)
        self._client.state.dsp_highpass = idx
        self.coordinator.async_set_updated_data(self._client.state)
        self.async_write_ha_state()


class LitheTuningSelect(_LitheBaseSelect):
    """PRO 2 enclosure/open-back protection selector (MCU 0x0D)."""

    _attr_name = "Audio — Speaker Tuning"
    _attr_options = TUNING_OPTIONS
    _attr_icon = "mdi:tune-variant"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.data['host']}_{entry.entry_id}_tuning"
        self._current = TUNING_OPTIONS[0]
        self._optimistic_until: float = 0.0

    @property
    def current_option(self) -> str:
        import time
        if time.monotonic() >= self._optimistic_until:
            value = getattr(self._client.state, "dsp_tuning", None)
            if isinstance(value, int) and 0 <= value < len(TUNING_OPTIONS):
                return TUNING_OPTIONS[value]
        return self._current

    async def async_select_option(self, option: str) -> None:
        import time
        idx = TUNING_OPTIONS.index(option) if option in TUNING_OPTIONS else 0
        self._current = TUNING_OPTIONS[idx]
        self._optimistic_until = time.monotonic() + 5.0
        await self._client.async_dsp_command(DSP_TUNING, idx)
        self.async_write_ha_state()
