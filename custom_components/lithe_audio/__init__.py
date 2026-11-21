"""Lithe Audio integration for Home Assistant."""
from __future__ import annotations

import logging
import socket as _sock

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_CERT_PATH, CONF_HOST, CONF_KEY_PATH,
    CONF_PORT, CONF_PRODUCT, CONF_USE_TLS, DATA_COORDINATOR, DOMAIN,
    DSP_BALANCE, DSP_BASS_FIELD, DSP_EQ, DSP_EQ_BANDS, DSP_LOUDNESS,
    DSP_MID_FIELD, DSP_NIGHTMODE, DSP_OUTPUT, DSP_TREBLE_FIELD,
    EQ_PRESETS, LS9_PRODUCTS, OUT_OPTIONS, PRODUCT_NAMES,
    capability_product_from_state, caps,
)
from .coordinator import LitheAudioCoordinator
from .lithe_client import LitheClient, LitheClientLS9

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.MEDIA_PLAYER,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.SENSOR,
]


def _detect_local_ip() -> str:
    try:
        s = _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _infer_product(entry_data: dict) -> str:
    """Guess a product ID from legacy/incomplete config-entry data.

    Used when migrating entries created by older versions that didn't
    persist `product`. Defaults err on the conservative side.
    """
    from .const import (
        PRODUCT_MICRO, PRODUCT_PRO, PRODUCT_PRO2, PRODUCT_V2, PRODUCT_V3,
        PRODUCT_IO1,
    )
    # Sometimes older entries stored a 'platform' string instead
    plat = (entry_data.get("platform") or "").upper()
    title_hint = (entry_data.get("title") or entry_data.get("name") or "").upper()
    cert_present = bool(entry_data.get(CONF_CERT_PATH)) or entry_data.get(CONF_USE_TLS)

    # Title-based hint first
    if "PRO2" in title_hint or "PRO 2" in title_hint:  return PRODUCT_PRO2
    if "V3" in title_hint:                              return PRODUCT_V3
    if "IO1" in title_hint:                             return PRODUCT_IO1
    if "MICRO" in title_hint:                           return PRODUCT_MICRO
    if "V2" in title_hint:                              return PRODUCT_V2
    if "PRO" in title_hint:                             return PRODUCT_PRO

    # Platform-based fallback
    if plat == "LS10" or cert_present:                  return PRODUCT_PRO2
    return PRODUCT_V2


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Lithe Audio from a config entry."""
    domain_data = hass.data.setdefault(DOMAIN, {})

    # Version banner — helps diagnose partial-install issues. Run this once
    # per integration load rather than once for every configured speaker.
    def _read_install_info() -> tuple[str, list[str]]:
        """Read manifest version + check critical files for staleness.

        Runs in executor to avoid blocking the event loop with sync I/O.
        Returns (version, list_of_stale_files).
        """
        import json as _json
        from pathlib import Path as _Path
        _here = _Path(__file__).parent
        _version = "unknown"
        _mpath = _here / "manifest.json"
        if _mpath.exists():
            try:
                with open(_mpath) as _f:
                    _version = _json.load(_f).get("version", "unknown")
            except Exception:
                pass
        # Critical-file freshness check via known markers in current code
        _expected_markers = {
            "lithe_client.py": '"id": "home-assistant"',
            "switch.py": "LitheHighPassProtectionSwitch",
            "number.py": "LitheLoudnessNumber",
            "media_player.py": "_EXCLUDED_SOURCES",
        }
        _stale: list[str] = []
        for _fname, _marker in _expected_markers.items():
            _fpath = _here / _fname
            try:
                _text = _fpath.read_text(encoding="utf-8", errors="ignore")
                if _marker not in _text:
                    _stale.append(_fname)
            except Exception:
                pass
        return _version, _stale

    if not domain_data.get("_install_info_logged"):
        domain_data["_install_info_logged"] = True
        try:
            _version, _stale = await hass.async_add_executor_job(_read_install_info)
            _LOGGER.info(
                "Lithe Audio integration starting (manifest version %s)",
                _version,
            )
            for _fname in _stale:
                _LOGGER.error(
                    "PARTIAL INSTALL DETECTED: %s is STALE (missing marker). "
                    "Delete /config/custom_components/lithe_audio/ entirely "
                    "and reinstall v%s. Bug reports from a partial install "
                    "won't be reproducible.",
                    _fname, _version,
                )
        except Exception:
            pass

    # Migration: entries created by older versions may not have `product`.
    if CONF_PRODUCT not in entry.data:
        inferred = _infer_product({**entry.data, "title": entry.title})
        _LOGGER.warning(
            "Lithe Audio entry %s has no '%s' key — migrating with inferred value '%s'. "
            "Delete and re-add the entry if this is wrong.",
            entry.title, CONF_PRODUCT, inferred,
        )
        new_data = {**entry.data, CONF_PRODUCT: inferred}
        hass.config_entries.async_update_entry(entry, data=new_data)

    # Cleanup only obsolete standalone proxy devices. Cast group proxy
    # entities are current again and power the stock Join picker.
    try:
        from homeassistant.helpers import device_registry as dr
        dev_reg = dr.async_get(hass)
        # Remove stale standalone proxy DEVICES (v1.1.98 leftovers)
        for dev in list(dev_reg.devices):
            for domain, ident in dev.identifiers:
                if domain == DOMAIN and isinstance(ident, str) and ident.startswith("cast_proxy_"):
                    dev_reg.async_remove_device(dev.id)
                    _LOGGER.info("Removed stale Cast proxy device: %s", dev.name or dev.id)
                    break
    except Exception as e:
        _LOGGER.debug("Cast proxy cleanup skipped: %s", e)

    product = entry.data[CONF_PRODUCT]
    host    = entry.data[CONF_HOST]
    port    = entry.data.get(CONF_PORT, 7777)
    use_tls = entry.data.get(CONF_USE_TLS, product not in LS9_PRODUCTS)
    cert    = entry.data.get(CONF_CERT_PATH) or None
    key     = entry.data.get(CONF_KEY_PATH) or None

    # Fall back to bundled certs if a TLS product has no cert path
    if use_tls and not (cert and key):
        from .const import BUNDLED_CERT_KEY, BUNDLED_CERT_PEM
        cert = cert or BUNDLED_CERT_PEM
        key  = key  or BUNDLED_CERT_KEY

    local_ip = await hass.async_add_executor_job(_detect_local_ip)

    ClientCls = LitheClientLS9 if product in LS9_PRODUCTS else LitheClient
    client = ClientCls(host, port, use_tls, cert, key, local_ip)
    client.product = product
    # Favourites are not part of this build: skip favourites polling.
    client.supports_favourites = False

    coordinator = LitheAudioCoordinator(hass, client, entry.entry_id)
    await coordinator.async_config_entry_first_refresh()

    # Older releases used the generic product label as the device-registry
    # name. Preserve explicit user renames, but migrate integration-owned
    # generic names to the real discovery/config-entry identity. This keeps
    # e.g. "LitheAudio LWF1V2266D74" as the page heading while the separate
    # model field remains "WiFi Speaker V2".
    try:
        from homeassistant.helpers import device_registry as dr

        entry_name = entry.title.rsplit(" (", 1)[0].strip()
        if entry_name and entry_name not in set(PRODUCT_NAMES.values()):
            device_registry = dr.async_get(hass)
            get_by_identifier = getattr(
                device_registry, "async_get_device_by_identifier", None
            )
            device = (
                get_by_identifier((DOMAIN, host))
                if get_by_identifier is not None
                else device_registry.async_get_device(
                    identifiers={(DOMAIN, host)}
                )
            )
            if (
                device is not None
                and not getattr(device, "name_by_user", None)
                and device.name != entry_name
            ):
                device_registry.async_update_device(device.id, name=entry_name)
                _LOGGER.info(
                    "Updated speaker device name from %r to %r",
                    device.name,
                    entry_name,
                )
    except Exception as err:
        _LOGGER.debug("Device-name migration skipped for %s: %s", host, err)

    # Prefer specific model-number/variant fields, then use the product that
    # the client derived from all live LUCI model messages. Some firmware sends
    # numeric zeroes for Model_num/ModelVariant, so ignoring detected_product
    # leaves a WiFi v3 permanently configured with PRO 2-only controls.
    capability_product = capability_product_from_state(
        client.state.model_number,
        client.state.model_variant,
        client.state.detected_product,
    )
    if capability_product and capability_product != product:
        same_transport_family = (
            (product in LS9_PRODUCTS) == (capability_product in LS9_PRODUCTS)
        )
        if same_transport_family:
            _LOGGER.warning(
                "Speaker %s reports model variant %r / %r (%s); replacing configured "
                "product %s before capability setup",
                host,
                client.state.model_number,
                client.state.model_variant,
                PRODUCT_NAMES.get(capability_product, capability_product),
                PRODUCT_NAMES.get(product, product),
            )
            hass.config_entries.async_update_entry(
                entry,
                data={**entry.data, CONF_PRODUCT: capability_product},
            )
            product = capability_product
            client.product = product
        else:
            _LOGGER.error(
                "Speaker %s reports model variant %r but it conflicts with the active "
                "LUCI transport; keeping configured product %s",
                host,
                client.state.model_variant or client.state.model_number,
                product,
            )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        DATA_COORDINATOR: coordinator,
    }

    # Remove entities superseded by the slot selector/save button workflow.
    # Product-specific cleanup below also removes controls left in the entity
    # registry by older releases when the current model does not support them.
    registry = er.async_get(hass)
    for registry_entry in list(registry.entities.values()):
        if (
            registry_entry.platform == DOMAIN
            and str(registry_entry.unique_id).startswith("lithe_cast_proxy_")
        ):
            registry.async_remove(registry_entry.entity_id)
    obsolete_unique_ids = [
        ("select", f"{host}_{entry.entry_id}_tuning"),
        *(
            ("button", f"{host}_{entry.entry_id}_save_fav_{slot}")
            for slot in range(1, 11)
        ),
    ]
    product_caps = caps(product)
    if not product_caps["highpass_select"]:
        obsolete_unique_ids.append(
            ("select", f"{host}_{entry.entry_id}_highpass")
        )
    if not product_caps["eq_select"]:
        obsolete_unique_ids.extend([
            ("select", f"{host}_{entry.entry_id}_eq"),
            ("number", f"{host}_{entry.entry_id}_treble"),
            ("number", f"{host}_{entry.entry_id}_mid"),
            ("number", f"{host}_{entry.entry_id}_bass"),
        ])
    if not product_caps["output_select"]:
        obsolete_unique_ids.append(
            ("select", f"{host}_{entry.entry_id}_output")
        )
    if not product_caps["balance_number"]:
        obsolete_unique_ids.append(
            ("number", f"{host}_{entry.entry_id}_balance")
        )
    if not product_caps["tuning_switch"]:
        obsolete_unique_ids.append(
            ("switch", f"{host}_{entry.entry_id}_tuning")
        )
    if not product_caps["loudness_number"]:
        obsolete_unique_ids.append(
            ("number", f"{host}_{entry.entry_id}_loudness")
        )
    if not product_caps["loudness_switch"]:
        obsolete_unique_ids.append(
            ("switch", f"{host}_{entry.entry_id}_loudness_sw")
        )
    if not product_caps["nightmode_switch"]:
        obsolete_unique_ids.append(
            ("switch", f"{host}_{entry.entry_id}_nightmode")
        )
    # Bluetooth control is not part of this build; remove the old switch.
    obsolete_unique_ids.append(
        ("switch", f"{host}_{entry.entry_id}_bluetooth")
    )
    obsolete_unique_ids.extend([
        ("select", f"{host}_{entry.entry_id}_cast_group"),
        ("select", f"{host}_{entry.entry_id}_spotify_target"),
    ])
    # Alarms are not part of this build.
    obsolete_unique_ids.append(
        ("sensor", f"{host}_{entry.entry_id}_next_alarm")
    )
    # The factory-reset button is too easy to press by accident; removed.
    obsolete_unique_ids.append(
        ("button", f"{host}_{entry.entry_id}_factory_reset")
    )
    # Favourites are not part of this build.
    obsolete_unique_ids.extend([
        ("button", f"{host}_{entry.entry_id}_heart_save"),
        ("select", f"{host}_{entry.entry_id}_fav_save_slot"),
        ("text", f"{host}_{entry.entry_id}_fav_save_name"),
        *(
            ("button", f"{host}_{entry.entry_id}_play_fav_{slot}")
            for slot in range(1, 11)
        ),
        *(
            ("text", f"{host}_{entry.entry_id}_fav_name_{slot}")
            for slot in range(1, 11)
        ),
    ])
    if not product_caps["subwoofer_controls"]:
        obsolete_unique_ids.extend([
            ("select", f"{host}_{entry.entry_id}_sub_profile"),
            ("number", f"{host}_{entry.entry_id}_sub_gain"),
            ("select", f"{host}_{entry.entry_id}_sub_crossover"),
            ("select", f"{host}_{entry.entry_id}_sub_phase"),
            ("switch", f"{host}_{entry.entry_id}_sub_lowpass"),
            ("button", f"{host}_{entry.entry_id}_sub_save"),
        ])
    # Built-in chimes are not part of this build (V3 firmware has no chime
    # files and answers every MB#80 request with NI).
    obsolete_unique_ids.extend(
        ("button", f"{host}_{entry.entry_id}_chime_{slot}")
        for slot in range(1, 16)
    )
    for entity_domain, unique_id in obsolete_unique_ids:
        entity_id = registry.async_get_entity_id(
            entity_domain, DOMAIN, unique_id
        )
        if entity_id:
            registry.async_remove(entity_id)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        bucket = hass.data.get(DOMAIN, {})
        entry_data = bucket.pop(entry.entry_id, None)
        if entry_data:
            coordinator: LitheAudioCoordinator = entry_data[DATA_COORDINATOR]
            await coordinator.async_shutdown()

        # If this was the last config entry, remove the shared services too
        has_other_entries = any(
            isinstance(v, dict) and DATA_COORDINATOR in v
            for v in bucket.values()
        )
        if not has_other_entries:
            for svc in _SERVICES:
                if hass.services.has_service(DOMAIN, svc):
                    hass.services.async_remove(DOMAIN, svc)
    return unload_ok


# ── Service dispatch ────────────────────────────────────────────────────────

def _resolve_coordinators(hass: HomeAssistant, call: ServiceCall) -> list[LitheAudioCoordinator]:
    """Resolve a service call's targets to coordinator instances.

    Looks at entity_id (single or list) on the call data and matches each one
    to the integration's entry that owns it.
    """
    bucket = hass.data.get(DOMAIN, {})
    if not bucket:
        return []

    raw = call.data.get("entity_id")
    if isinstance(raw, str):
        targets = [raw]
    elif isinstance(raw, list):
        targets = list(raw)
    else:
        targets = []

    coordinators: list[LitheAudioCoordinator] = []
    seen: set[str] = set()

    if targets:
        ent_reg = er.async_get(hass)
        for eid in targets:
            ent = ent_reg.async_get(eid)
            if not ent or not ent.config_entry_id:
                continue
            entry_data = bucket.get(ent.config_entry_id)
            if entry_data and entry_data[DATA_COORDINATOR] not in coordinators:
                coordinators.append(entry_data[DATA_COORDINATOR])
                seen.add(ent.config_entry_id)
        if coordinators:
            return coordinators

    # Fallback: every configured speaker
    for entry_id, entry_data in bucket.items():
        if not isinstance(entry_data, dict) or DATA_COORDINATOR not in entry_data:
            continue
        if entry_id in seen:
            continue
        coordinators.append(entry_data[DATA_COORDINATOR])
    return coordinators


_SERVICES = (
    "play_url", "set_name", "reboot",
    "set_dsp_eq", "set_dsp_eq_band", "set_dsp_output",
    "set_dsp_nightmode", "set_dsp_balance", "set_dsp_loudness",
)


def _register_services(hass: HomeAssistant) -> None:
    """Register the Lithe Audio service actions."""

    if hass.services.has_service(DOMAIN, "play_url"):
        return  # Already registered for another entry

    async def _for_each(call: ServiceCall, fn) -> None:
        coords = _resolve_coordinators(hass, call)
        if not coords:
            raise HomeAssistantError("No Lithe Audio speaker matched the service target")
        for coord in coords:
            try:
                await fn(coord.client)
            except Exception as e:
                _LOGGER.error("%s failed on %s: %s", call.service, coord.client.host, e)

    async def svc_play_url(call: ServiceCall) -> None:
        url = str(call.data.get("url", "")).strip()
        if not url:
            return
        title = str(call.data.get("title", "") or "").strip() or None
        await _for_each(
            call, lambda c: c.async_play_url(url, title=title)
        )

    async def svc_set_name(call: ServiceCall) -> None:
        name = str(call.data.get("name", "")).strip()
        if not name:
            return
        await _for_each(call, lambda c: c.async_set_name(name))

    async def svc_reboot(call: ServiceCall) -> None:
        await _for_each(call, lambda c: c.async_reboot())

    async def svc_set_eq(call: ServiceCall) -> None:
        preset = call.data.get("preset", "Normal")
        idx = EQ_PRESETS.index(preset) if preset in EQ_PRESETS else 0
        await _for_each(call, lambda c: c.async_dsp_command(DSP_EQ, idx))

    async def svc_set_output(call: ServiceCall) -> None:
        mode = call.data.get("mode", "Stereo")
        idx = OUT_OPTIONS.index(mode) if mode in OUT_OPTIONS else 0
        await _for_each(call, lambda c: c.async_dsp_command(DSP_OUTPUT, idx))

    async def svc_set_nightmode(call: ServiceCall) -> None:
        val = 1 if call.data.get("enabled") else 0
        await _for_each(call, lambda c: c.async_dsp_command(DSP_NIGHTMODE, val))

    async def svc_set_eq_band(call: ServiceCall) -> None:
        fields = {
            "Bass": DSP_BASS_FIELD,
            "Mid": DSP_MID_FIELD,
            "Treble": DSP_TREBLE_FIELD,
        }
        field = fields.get(call.data.get("band", "Bass"), DSP_BASS_FIELD)
        val = max(-5, min(5, int(call.data.get("value", 0))))
        await _for_each(
            call, lambda c: c.async_dsp_command(DSP_EQ_BANDS, val, field)
        )

    async def svc_set_balance(call: ServiceCall) -> None:
        val = max(-6, min(6, int(call.data.get("balance", 0))))
        await _for_each(call, lambda c: c.async_dsp_command(DSP_BALANCE, val))

    async def svc_set_loudness(call: ServiceCall) -> None:
        val = 1 if call.data.get("enabled") else 0
        await _for_each(call, lambda c: c.async_dsp_command(DSP_LOUDNESS, val))

    hass.services.async_register(DOMAIN, "play_url",          svc_play_url)
    hass.services.async_register(DOMAIN, "set_name",          svc_set_name)
    hass.services.async_register(DOMAIN, "reboot",            svc_reboot)
    hass.services.async_register(DOMAIN, "set_dsp_eq",        svc_set_eq)
    hass.services.async_register(DOMAIN, "set_dsp_eq_band",   svc_set_eq_band)
    hass.services.async_register(DOMAIN, "set_dsp_output",    svc_set_output)
    hass.services.async_register(DOMAIN, "set_dsp_nightmode", svc_set_nightmode)
    hass.services.async_register(DOMAIN, "set_dsp_balance",   svc_set_balance)
    hass.services.async_register(DOMAIN, "set_dsp_loudness",  svc_set_loudness)
