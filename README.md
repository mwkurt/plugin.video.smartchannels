# plugin.video.smartchannels
## Smart TV Channels for Kodi 21 (Omega)

Create smart TV-style channels from your local Kodi video library. Channels
play TV episodes and movies in configurable rotation with persistent queue and
state across Kodi restarts.

---

## Features

- **Round Robin TV channels** — rotate through multiple shows in order, one or
  more episodes per show per turn
- **Random TV channels** — episodes from each show in random order, no-repeat
  tracking within each cycle
- **Movie channels** — sequential or shuffled movie playback with cycle tracking
- **Episodes Per Slot** — configure each show to contribute N consecutive
  episodes per rotation turn (e.g. Show A=2, Show B=1 → AA, B, AA, B …)
- **Manual show rotation order** — drag each show into position via the wizard
- **Custom starting points** — pick a specific episode (or Surprise Me!) for
  each show when creating a channel
- **Interleave** — insert items from a second channel at a configurable
  frequency (fixed or jittered), with optional count-per-slot
- **Filters** — narrow content by Genre, Year, MPAA, Studio, or Rating with
  AND/OR logic applied in Python against a local library cache
- **Exact resume** — resume from exact playback position after stop or restart
- **Recycle or Play Once** — loop channels forever or stop when content is
  exhausted
- **Shared storage** — SMB/NFS path for multi-client (e.g. NVIDIA Shield)
  setups sharing the same state and queue files
- **Backup & Restore** — export/import channels.json and state.json

---

## File Structure

```
plugin.video.smartchannels/
├── addon.py                   Entry point; parses URL params and dispatches
├── addon.xml                  Kodi manifest (id, version, requires)
├── service.py                 Persistent background service; owns ALL playback events
└── resources/
    ├── settings.xml           Addon settings schema
    ├── language/
    │   └── resource.language.en_gb/
    │       └── strings.po     All localised strings
    └── lib/
        ├── channel_manager.py CRUD, state persistence, queue building
        ├── library.py         Kodi JSON-RPC wrapper (TV shows, episodes, movies)
        ├── player.py          start_channel() and now_playing.json writer only
        ├── router.py          URL action → controller mapping
        └── ui/
            └── channels.py    Channel listing, wizards, interleave dialog
```

---

## Architecture

```
addon.py ──► Router (router.py)
               ├── ChannelUI (ui/channels.py)
               │     └── ChannelManager ── LibraryClient
               └── SmartPlayer (player.py)  [starts playback only]

service.py (always-on background service)
  └── Watches now_playing.json
        ├── advance_state / advance_movie_state
        ├── queue top-up via ChannelManager.refill_queue()
        └── exact resume (poll + seek on onAVStarted)
```

**Ownership rules (never violated):**
- `service.py` owns ALL playback callbacks, state advancement, resume, queue top-up
- `player.py` owns ONLY `start_channel()` and `_write_now_playing()`
- `channel_manager.py` owns queue building, state read/write, library access

---

## Data Files (addon profile folder)

| File               | Purpose                                              |
|--------------------|------------------------------------------------------|
| `channels.json`    | All channel definitions                              |
| `state.json`       | Per-channel playback pointers, resume positions      |
| `queue_<id>.json`  | Current episode/movie queue per channel              |
| `now_playing.json` | Active channel pointer (written by player.py)        |

### Channel definition schema
```json
{
  "id":         "uuid-string",
  "name":       "Evening Drama",
  "channel_type": "tv",
  "shows": [
    {"tvshowid": 42, "title": "Breaking Bad", "episodes_per_slot": 2},
    {"tvshowid": 17, "title": "Better Call Saul"}
  ],
  "randomize":  false,
  "recycle":    true,
  "queue_size": 50,
  "visible":    true,
  "filters":    [],
  "interleave": {"channel_id": "other-uuid", "frequency": 4, "jitter": 0, "count_per": 1}
}
```

---

## Installation

1. Zip the `plugin.video.smartchannels/` folder (uncompressed).
2. In Kodi: **Add-ons → Install from zip file** → select your zip.
3. Or copy the folder directly to `~/.kodi/addons/plugin.video.smartchannels/`.
4. Enable the addon and navigate to **Video Add-ons → Smart TV Channels**.
5. Run **[Build Library Cache]** before creating your first channel.
