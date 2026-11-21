"""Lithe Audio media player entity (slim build).

Shows what the speaker is playing whatever the source (Spotify Connect,
AirPlay, Cast or a URL), with transport, volume, EQ (sound mode) and URL /
media-source playback. Multi-room groups, favourites, chimes, Spotify and
Music Assistant browsing bridges are not part of this build.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from homeassistant.components import media_source
from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    RepeatMode,
)
from homeassistant.components.media_player.browse_media import (
    async_process_play_media_url,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_PRODUCT, DATA_COORDINATOR, DOMAIN, MB_SOURCE, PRODUCT_MICRO,
    PRODUCT_NAMES, PRODUCT_SOURCES, SOURCES, SUB_DSP_PROFILE,
    SUB_DSP_SET_FIELD, SUB_PROFILE_OPTIONS,
)
from .coordinator import LitheAudioCoordinator

_LOGGER = logging.getLogger(__name__)

# Media content types we accept for play_media
_PLAYABLE_TYPES = {
    MediaType.MUSIC, MediaType.URL,
    "audio/mp3", "audio/mpeg", "audio/wav", "audio/x-wav",
    "audio/aac", "audio/flac", "audio/ogg", "audio/x-mpegurl",
}


_LOGO_PATH = Path(__file__).parent / "brand" / "icon@2x.png"


def _read_logo() -> bytes | None:
    """Read the bundled Lithe logo (runs in the executor)."""
    try:
        return _LOGO_PATH.read_bytes()
    except OSError:
        return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: LitheAudioCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities([LitheAudioMediaPlayer(coordinator, entry)])


class LitheAudioMediaPlayer(CoordinatorEntity[LitheAudioCoordinator], MediaPlayerEntity):
    """Lithe Audio speaker media player entity."""

    def __init__(self, coordinator: LitheAudioCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._product = entry.data[CONF_PRODUCT]
        self._client = coordinator.client

        self._attr_unique_id = f"{entry.data['host']}_{entry.entry_id}_player"
        entry_name = entry.title.rsplit(" (", 1)[0].strip()
        live_name = (self._client.state.name or "").strip()
        generic_names = set(PRODUCT_NAMES.values()) | {"A Player"}
        self._attr_has_entity_name = False
        self._attr_name = (
            entry_name
            if entry_name and entry_name not in generic_names
            else live_name
            if live_name and live_name not in generic_names
            else entry_name or PRODUCT_NAMES.get(self._product, "Lithe Audio")
        )

        # Sources that can actually be selected from Home Assistant. Spotify,
        # AirPlay and Cast are started from the phone/app; they still show as
        # the current source when active.
        src_ids = PRODUCT_SOURCES.get(self._product, list(SOURCES.keys()))
        self._source_list = ["No Source"]
        if 13 in src_ids:
            self._source_list.append("Aux")

        # Grace timer for available property — set in available() the
        # first time we see state.connected=True
        self._last_seen_connected: float = 0.0

    @property
    def device_info(self) -> DeviceInfo:
        state = self._client.state
        entry_name = self._entry.title.rsplit(" (", 1)[0].strip()
        generic_names = set(PRODUCT_NAMES.values())
        device_name = (
            entry_name
            if entry_name and entry_name not in generic_names
            else state.name or entry_name
            or PRODUCT_NAMES.get(self._product, "Lithe Audio")
        )
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.data["host"])},
            # Discovery knows the LS9's advertised identity even when its
            # legacy LUCI name is the unhelpful default "A Player". Keep that
            # identity as the HA device name and expose the hardware family in
            # `model` below.
            name=device_name,
            manufacturer="Lithe Audio",
            model=state.model or PRODUCT_NAMES.get(self._product),
            sw_version=state.firmware or None,
            # Bare http:// to the speaker IP — most reliable URL across
            # firmware versions (the Cast eureka_info endpoint isn't always
            # exposed). Some users may need to use the Lithe app instead.
            configuration_url=f"http://{self._client.host}",
        )

    # ── Feature flags ──────────────────────────────────────────────────────

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        flags = (
            MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.PAUSE
            | MediaPlayerEntityFeature.STOP
            | MediaPlayerEntityFeature.NEXT_TRACK
            | MediaPlayerEntityFeature.PREVIOUS_TRACK
            | MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_STEP
            | MediaPlayerEntityFeature.VOLUME_MUTE
            | MediaPlayerEntityFeature.SELECT_SOURCE
            | MediaPlayerEntityFeature.PLAY_MEDIA
            | MediaPlayerEntityFeature.BROWSE_MEDIA
            | MediaPlayerEntityFeature.MEDIA_ANNOUNCE
            | MediaPlayerEntityFeature.SHUFFLE_SET
            | MediaPlayerEntityFeature.REPEAT_SET
            | MediaPlayerEntityFeature.SELECT_SOUND_MODE
        )
        # SEEK only when source is not a live stream
        if not self._client.state.is_live:
            flags |= MediaPlayerEntityFeature.SEEK
        return flags

    # ── State properties ───────────────────────────────────────────────────

    @property
    def state(self) -> MediaPlayerState:
        if not self._client.state.connected:
            return MediaPlayerState.OFF
        return {
            "playing":    MediaPlayerState.PLAYING,
            "paused":     MediaPlayerState.PAUSED,
            "stopped":    MediaPlayerState.IDLE,
            "connecting": MediaPlayerState.BUFFERING,
            "buffering":  MediaPlayerState.BUFFERING,
        }.get(self._client.state.play_state, MediaPlayerState.IDLE)

    @property
    def available(self) -> bool:
        """Speaker availability with brief disconnect grace.

        We treat the speaker as available if either:
          - the LUCI socket is currently connected, OR
          - we've been disconnected for less than 90 seconds (grace
            period to ride out brief network blips and the coordinator's
            reconnect attempts without flapping the UI to Unavailable).

        Once 90 seconds pass without successful reconnection we surface
        the Unavailable state so the user knows there's a real problem.
        """
        if self._client.state.connected:
            # Note the moment we became connected for the grace timer
            self._last_seen_connected = self.hass.loop.time() if self.hass else 0.0
            return True
        # Disconnected — check grace window
        try:
            now = self.hass.loop.time()
            last_seen = getattr(self, "_last_seen_connected", 0.0)
            if last_seen and (now - last_seen) < 90.0:
                return True
        except Exception:
            pass
        return False

    @property
    def volume_level(self) -> float:
        return self._client.state.volume / 100.0

    @property
    def is_volume_muted(self) -> bool | None:
        # Local Lithe mute is deliberately implemented as volume zero because
        # MB#40 MUTE/UNMUTE is unreliable on current LS9 and LS10 firmware.
        return self._client.state.volume == 0

    @property
    def source(self) -> str | None:
        source_name = self._client.state.source_name
        return "Aux" if source_name == "AUX In" else source_name

    @property
    def source_list(self) -> list[str]:
        base = list(self._source_list)
        # Keep an externally-owned current source (Spotify, AirPlay, Cast)
        # visible even though it can't be started from here.
        current = self.source
        if current and current not in base:
            base.insert(0, current)
        return base

    @property
    def media_title(self) -> str | None:
        s = self._client.state
        if s.display_title:
            return s.display_title
        # Prefer the real title from MB#42, fall back to the file name of the
        # URL we last asked the speaker to play.
        if s.title:
            return s.title
        url = s.last_played_url
        if url:
            try:
                fname = urlparse(url).path.rsplit("/", 1)[-1] or url
                if "." in fname:
                    fname = fname.rsplit(".", 1)[0]
                return fname or None
            except Exception:
                return url
        return None

    @property
    def media_artist(self) -> str | None:
        s = self._client.state
        return s.display_artist or s.artist or None

    @property
    def media_album_name(self) -> str | None:
        return self._client.state.album or None

    @property
    def media_image_url(self) -> str | None:
        # Current track artwork only. With no artwork, async_get_media_image
        # serves the bundled Lithe logo through HA's image proxy instead.
        return self._client.state.artwork_url or None

    @property
    def media_image_hash(self) -> str | None:
        """Change the HA image cache key whenever track metadata changes."""
        s = self._client.state
        if not s.artwork_url:
            return "lithe_logo"
        identity = "\0".join((
            self.media_image_url or "", s.title, s.artist, s.album,
            str(s.artwork_revision),
        ))
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]

    @property
    def media_image_remotely_accessible(self) -> bool:
        """Let clients fetch public artwork directly, but proxy speaker URLs."""
        url = self._client.state.artwork_url
        if not url:
            return False  # the logo is served by HA, not by a public URL
        return urlparse(url).hostname != self._client.host

    async def async_get_media_image(self) -> tuple[bytes | None, str | None]:
        """Return track artwork, or the Lithe logo when there is none."""
        if self._client.state.artwork_url:
            return await super().async_get_media_image()
        return await self.hass.async_add_executor_job(_read_logo), "image/png"

    @property
    def media_duration(self) -> int | None:
        d = self._client.state.duration_ms
        return d // 1000 if d else None

    @property
    def media_position(self) -> float | None:
        """Return position without discarding MB#49 millisecond precision.

        Home Assistant extrapolates this value from
        ``media_position_updated_at`` while playback is active. Flooring each
        speaker push to a whole second repeatedly moved that clock backwards.
        """
        p = self._client.state.position_ms
        if p or self._client.state.play_state == "playing":
            return self._client.state.position_seconds
        return None

    @property
    def media_position_updated_at(self):
        """When position was last fetched. Lets HA extrapolate live position."""
        ts = self._client.state.position_updated_at
        if not ts:
            return None
        from datetime import datetime, timezone
        return datetime.fromtimestamp(ts, tz=timezone.utc)

    @property
    def media_content_type(self) -> MediaType:
        return MediaType.MUSIC

    @property
    def shuffle(self) -> bool:
        return self._client.state.shuffle

    @property
    def repeat(self) -> RepeatMode:
        m = (self._client.state.repeat or "off").lower()
        return {
            "off": RepeatMode.OFF,
            "all": RepeatMode.ALL,
            "one": RepeatMode.ONE,
        }.get(m, RepeatMode.OFF)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self._client.state
        return {
            "product":         PRODUCT_NAMES.get(self._product, self._product),
            "firmware":        s.firmware,
            "mac_address":     s.mac,
            "wifi_band":       s.wifi_band,
            "source_id":       s.source_id,
            "source_name":     s.source_name,
            "is_live":         s.is_live,
            "last_played_url": s.last_played_url,
            "volume_percent":  s.volume,
        }

    # ── Commands ───────────────────────────────────────────────────────────

    async def async_set_volume_level(self, volume: float) -> None:
        await self._client.async_set_volume(round(volume * 100))

    async def async_mute_volume(self, mute: bool) -> None:
        await self._client.async_mute(mute)

    async def async_media_play(self) -> None:
        # Use RESUME if previously paused, else PLAY
        if self._client.state.play_state == "paused":
            await self._client.async_resume()
        else:
            await self._client.async_play()

    async def async_media_pause(self) -> None:
        await self._client.async_pause()

    async def async_media_stop(self) -> None:
        await self._client.async_stop()

    async def async_media_next_track(self) -> None:
        await self._client.async_next_track()

    async def async_media_previous_track(self) -> None:
        await self._client.async_prev_track()

    async def async_media_seek(self, position: float) -> None:
        await self._client.async_seek(int(position * 1000))

    async def async_set_shuffle(self, shuffle: bool) -> None:
        await self._client.async_set_shuffle(shuffle)

    async def async_set_repeat(self, repeat: RepeatMode) -> None:
        await self._client.async_set_repeat(repeat)

    @property
    def sound_mode(self) -> str | None:
        """Current EQ preset, exposed as a Denon-style sound_mode."""
        if self._product == PRODUCT_MICRO:
            idx = getattr(self._client.state, "sub_profile", None)
            if idx is not None and 0 <= idx < len(SUB_PROFILE_OPTIONS):
                return SUB_PROFILE_OPTIONS[idx]
            return None
        from .const import EQ_PRESETS
        idx = getattr(self._client.state, "dsp_eq", None)
        if idx is not None and 0 <= idx < len(EQ_PRESETS):
            return EQ_PRESETS[idx]
        return None

    @property
    def sound_mode_list(self) -> list[str] | None:
        if self._product == PRODUCT_MICRO:
            return list(SUB_PROFILE_OPTIONS)
        from .const import EQ_PRESETS
        return list(EQ_PRESETS)

    async def async_select_sound_mode(self, sound_mode: str) -> None:
        """Set EQ preset by friendly name (Denon-style sound_mode)."""
        if self._product == PRODUCT_MICRO:
            if sound_mode not in SUB_PROFILE_OPTIONS:
                _LOGGER.warning(
                    "select_sound_mode: unknown Micro profile %r",
                    sound_mode,
                )
                return
            await self._client.async_dsp_command(
                SUB_DSP_PROFILE,
                SUB_PROFILE_OPTIONS.index(sound_mode),
                SUB_DSP_SET_FIELD,
            )
            return
        from .const import EQ_PRESETS, DSP_EQ
        if sound_mode not in EQ_PRESETS:
            _LOGGER.warning(
                "select_sound_mode: unknown mode %r (available: %s)",
                sound_mode, EQ_PRESETS,
            )
            return
        idx = EQ_PRESETS.index(sound_mode)
        _LOGGER.info("select_sound_mode: %s (idx=%d)", sound_mode, idx)
        await self._client.async_dsp_command(DSP_EQ, idx)

    async def async_select_source(self, source: str) -> None:
        """Release the audio path (No Source) or switch to the AUX input."""
        if source == self._client.state.source_name:
            return
        if source == "No Source":
            await self._client._send(0x02, MB_SOURCE, "0")  # noqa: SLF001
            await asyncio.sleep(0.3)
            await self._client._send(0x01, MB_SOURCE, "")  # noqa: SLF001
            return
        if source == "Aux" and "Aux" in self._source_list:
            await self._client._send(0x02, MB_SOURCE, "13")  # noqa: SLF001
            await asyncio.sleep(0.3)
            await self._client._send(0x01, MB_SOURCE, "")  # noqa: SLF001
            return
        _LOGGER.warning(
            "select_source: %r can't be started from Home Assistant "
            "(start it from the phone/app)", source,
        )

    async def async_play_media(
        self, media_type: str, media_id: str, **kwargs: Any
    ) -> None:
        """Play an HTTP URL or a media-source item (TTS, radio, My Media).

        With ``announce=True`` the optional ``extra.volume`` (0-100) is applied
        first. The speaker treats a URL as a source change, so whatever was
        playing (Spotify Connect, AirPlay, Cast) stops and is not resumed.
        """
        if media_source.is_media_source_id(media_id):
            try:
                resolved = await media_source.async_resolve_media(
                    self.hass, media_id, self.entity_id,
                )
            except Exception as err:
                _LOGGER.error("Failed to resolve media source %s: %s", media_id, err)
                return
            # Make relative URLs (e.g. TTS) absolute so the speaker can fetch them.
            media_id = async_process_play_media_url(self.hass, resolved.url)
            media_type = media_type or MediaType.MUSIC

        if not (
            media_type in _PLAYABLE_TYPES
            or media_id.startswith(("http://", "https://"))
        ):
            _LOGGER.warning("Unsupported play_media: type=%s id=%s", media_type, media_id)
            return

        extra: dict = kwargs.get("extra") or {}
        if kwargs.get("announce") and extra.get("volume") is not None:
            try:
                volume = max(0, min(100, int(extra["volume"])))
                await self._client.async_set_volume(volume)
            except (TypeError, ValueError):
                _LOGGER.warning("Ignoring invalid announce volume %r", extra["volume"])

        await self._client.async_play_url(
            media_id,
            title=str(extra.get("title") or "").strip() or None,
            artist=str(extra.get("artist") or "").strip() or None,
        )

    async def async_browse_media(
        self,
        media_content_type: MediaType | str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Browse Home Assistant media sources (radio, TTS, My Media)."""
        return await media_source.async_browse_media(
            self.hass,
            media_content_id,
            content_filter=lambda item: item.media_content_type.startswith("audio/"),
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
