# Lithe Audio — Home Assistant Integration

Direct, local control of Lithe Audio Wi-Fi speakers over the LUCI protocol on port 7777. No cloud, no bridge process, no portal — Home Assistant talks to each speaker directly.

**Latest: 1.4.114** — starts Spotify faster when the correct target is already available and keeps rapid volume changes smooth and stable.

---

## ✨ Features

| | |
|---|---|
| 🎵 **Media playback** | Play/pause, volume, next/prev, shuffle, repeat, position tracking |
| 🟢 **Spotify** | Browse an official HA Spotify account and transfer playback to the selected Lithe speaker |
| 📻 **Browse media** | Favourites + Adhan + Quran + BBC + HA media sources (Radio Browser, TTS, local files) |
| 🎼 **Music Assistant** | Artists, albums, tracks, playlists, radio, podcasts and audiobooks from a connected Music Assistant integration |
| 🕋 **Prayer Scheduler** | Daily Adhan at calculated prayer times for your city — 6 prayers including Sunrise & Sunset |
| ⏰ **Alarms** | Daily / weekly / monthly with per-day toggles, fade-in volume, multi-room targeting |
| 🔊 **Multi-room Groups** | Virtual group entities — play across multiple speakers simultaneously |
| 🎙️ **Chimes & Tannoy** | Up to 14 built-in chimes per model, doorbell ducking, TTS announcements |
| 🎛️ **DSP / EQ** | Bass, mid, treble, balance, loudness, night mode, output mode |
| **Favourites 1-10** | Choose a named slot, edit its save name, then save the current track |
| 🔵 **Bluetooth** | Pair / disconnect / status per speaker |
| 🔧 **Diagnostics** | Firmware, MAC, RSSI, SSID, network mode, uptime sensors |

---

## Supported speakers

| Product | Connection | Chimes | EQ/DSP | Loudness | Bluetooth |
|---|---|---|---|---|---|
| WiFi PRO 2 | Secure local | 14 | EQ, Output, Balance | On/Off + gain | ✅ |
| WiFi Speaker V3 | Secure local | 14 | EQ, Output, Balance | On/Off | ✅ |
| iO1 | Secure local | 10 | EQ, Output, Balance | — | ✅ |
| WiFi Speaker V2 | Local | 0 | — | — | — |
| WiFi PRO | Local | 6 | — | — | — |
| Micro Subwoofer | Local | 0 | — | — | ✅ |

---

## Installation

### HACS

1. HACS → ⋮ → **Custom repositories**
2. Add `https://github.com/LitheAudio-Official/home-assistant-integration` as category **Integration**
3. Search **Lithe Audio**, install, restart HA
4. **Settings → Devices & Services → + Add Integration → Lithe Audio**

### Manual

Copy `custom_components/lithe_audio/` into your HA `config/custom_components/` and restart.

---

## Quick start

After installing, your Lithe speakers appear in **Settings → Devices & Services → Lithe Audio**.

### Spotify

1. Add Home Assistant's official **Spotify** integration and sign in with a
   Spotify Premium account.
2. Start with the Spotify Web Player as the normal playback device. The Lithe
   integration refreshes Spotify's device list and automatically uses an exact
   matching speaker when Spotify has published one.
3. Open the Lithe speaker in **Settings -> Devices & services -> Lithe Audio ->
   Configure -> Spotify playback target**. If the correct speaker is listed,
   select it to save the destination for that speaker.
4. If the speaker is not listed, use the Spotify mobile or desktop app. The
   Spotify app discovers local speakers differently from the Web Player:
   play any track, select the missing Lithe speaker in **Connect to a device**,
   and wait until playback starts. This wakes the speaker and publishes it to
   Spotify's playback-device list.
5. Return to Home Assistant, reopen **Spotify playback target**, and select the
   speaker that has now appeared. Do not select a different speaker merely
   because it has a similar name.
6. Open the Lithe media player, choose **Browse media**, then open the
   **Spotify** account folder.
7. Selecting an album, playlist, episode, or track transfers the Spotify
   session to the matching Lithe speaker and starts playback.

The Web Player can show previously registered or active Spotify Connect
devices while omitting an idle speaker that the mobile app can still discover
locally. If automatic matching cannot find the speaker, Spotify remains on the
Web Player and the integration does not guess another destination. Wake the
missing speaker from the Spotify app, then save it under **Spotify playback
target** as described above. The same wake-up may be needed again if Spotify
removes an idle speaker from its available-device list.

Spotify credentials remain entirely in the official Spotify integration. The
Lithe integration only delegates browse and playback actions to its media
player entity. The integration tries an exact speaker-name match first and
uses the saved **Spotify playback target** when configured. Ambiguous names are
rejected to avoid playing in the wrong room.

### Music Assistant library

The Artists, Albums, Tracks, Playlists, Radio stations, Podcasts and
Audiobooks entries are supplied by Music Assistant. Install both the Music
Assistant server/add-on and its Home Assistant integration, then confirm that
at least one Music Assistant `media_player` entity is enabled and loaded. The
Lithe browser uses that entity's global library; the add-on dashboard alone
does not expose a browse API to Home Assistant.

Click **Configure** (gear icon) for:

```
📅  Prayer Schedule — Location & defaults
🕋  Prayer Schedule — Per-prayer settings
▶️  Test play an Adhan / Quran URL
📋  View today's schedule
⏰  Alarms — view, add, edit
🔊  Multi-room Groups — view, add, edit
🐞  Debug logging (for support)
```

### Multi-room groups

1. Configure → 🔊 Multi-room Groups → ➕ Add new group
2. Name it ("Downstairs"), pick member speakers
3. Save → reload integration
4. New entity: `media_player.lithe_group_downstairs`
5. Control like any media_player — play, volume, source all fan out to members

---

## Services

| Service | Description |
|---|---|
| `lithe_audio.play_chime` | Play built-in chime |
| `lithe_audio.play_url` | Stream any HTTP URL |
| `lithe_audio.play_favourite` | Play saved favourite (1-10) |
| `lithe_audio.play_quran_juz` | Play any of 30 Juz |
| `lithe_audio.play_adhan` | Play Adhan from preset dropdown |
| `lithe_audio.set_volume_preset` | Quick 0/20/40/60/80/100% |
| `lithe_audio.select_source_type` | Switch source by friendly name |
| `lithe_audio.alarm_*` | Alarm management (create/update/delete/toggle/snooze/dismiss) |
| `lithe_audio.group_*` | Group management (create/update/delete) |

---

## Network access

Core speaker control uses the local LUCI protocol on TCP/7777. Optional cloud
access is used only by features you enable: Home Assistant's Spotify
integration, `api.aladhan.com` prayer times, and audio stream URLs you choose.

---

## License

MIT
