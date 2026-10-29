"""Refresh HA's Spotify Connect device cache before resolving a destination."""
from __future__ import annotations

import asyncio

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er


async def async_refresh_spotify_devices(hass, spotify_entity_id: str, context=None) -> None:
    """Refresh the account's device coordinator, then publish the entity state.

    Updating the Spotify entity alone refreshes playback, not its separate
    five-minute device cache. Resolve the account from the actual target entity
    so another signed-in account cannot supply the destination list.
    """
    entity = er.async_get(hass).async_get(spotify_entity_id)
    entry = (
        hass.config_entries.async_get_entry(entity.config_entry_id)
        if entity is not None and entity.platform == "spotify" and entity.config_entry_id
        else None
    )
    runtime = getattr(entry, "runtime_data", None)
    devices = getattr(runtime, "devices", None)
    refresh = getattr(devices, "async_refresh", None)
    if refresh is None:
        raise HomeAssistantError(
            "Cannot refresh this Spotify account's device list. Check that the "
            "Home Assistant Spotify integration is loaded, then retry."
        )

    try:
        async with asyncio.timeout(20):
            await refresh()
            if not devices.last_update_success:
                raise HomeAssistantError(
                    "Spotify device discovery failed. The cached device list "
                    "was not used; check the Spotify integration and retry."
                )
            # Device coordinator listeners update source_list. Explicitly publish
            # the Spotify entity too before the caller reads its state.
            await hass.services.async_call(
                "homeassistant", "update_entity",
                {"entity_id": spotify_entity_id}, blocking=True, context=context,
            )
    except TimeoutError as err:
        raise HomeAssistantError(
            "Spotify device discovery timed out. Please retry."
        ) from err
