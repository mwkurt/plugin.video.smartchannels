# plugin.video.smartchannels
## Smart TV Channels for Kodi 21 (Omega) / Kodi 22 (Piers)

Create smart TV-style channels from your local Kodi video library. Channels
play episodes and movies in configurable rotation with persistent queue and
state across Kodi restarts, resume from exact playback position, and support
multi-client shared storage (e.g. multiple NVIDIA Shields sharing the same NAS).

---

## Channel Types

### TV Channel
Rotates through one or more TV shows in round-robin or random order.
- **Round Robin** — shows play in strict rotation, one or more episodes per turn
- **Random** — episodes from each show in random order with no-repeat tracking
- **Episodes Per Slot** — each show can contribute N consecutive episodes per
  turn (e.g. Show A=2, Show B=1 → AA, B, AA, B …)
- **Custom starting point** — choose a specific episode (or Surprise Me!) for
  each show at channel creation
- **Manual rotation order** — drag shows into the order you want

### Movie Channel
Plays movies sequentially or shuffled with full cycle tracking.
- Filter by Genre, Year, MPAA rating, Studio, or Rating
- Recycle or play once (exhausts when all movies are played)

### Serial Channel
Plays shows in strict broadcast order — Show A all the way through, then
Show B from the beginning. No rotation. Designed for watching a series
from start to finish before moving on.
- Recycle or play once (channel auto-deletes when all shows are exhausted)

### Folder Channel
Plays all video files from a local folder path, in order or shuffled.
Useful for bumpers, intros, commercials, or any content not in the Kodi
library.

### Auto-Create Channels
Automatically generates genre-based TV channels from your library. The
wizard detects genres present in your library and creates one or more
channels populated with shows matching those genres.

---

## Key Features

### Carousel Mode (Pseudo-Live)
TV and Movie channels can be set to Carousel mode, which advances the
queue on a wall-clock timer (default: 20 minutes). When you open a
Carousel channel, you pick up wherever the clock currently sits — just
like a broadcast channel. Configurable interval and pop count.

### Interleave
Insert content from a second channel into a TV channel's playback at a
configurable frequency. For example: play a movie from CH-MOV every 4
episodes of your TV channel.
- **Silent interleave** — the interleaved item plays but the OSD shows
  the TV channel name and the item is hidden from the upcoming list.
  Ideal for bumpers, commercials, or folder content you want invisible.
- **Multiple interleave sources** — add more than one interleave source,
  each with its own frequency and silent setting.

### Side Panel
The main channel list opens as a two-pane side panel:
- **Left pane** — your channel list
- **Right pane** — the upcoming queue for the selected channel (7 items,
  silent interleave items hidden)
- Arrow right to enter the right pane and select any upcoming item to
  start playback from that point
- Full context menu on any channel: Channel Info, Play, Reset, Edit,
  Delete, Toggle Visibility, Manage Interleave, View Exclusions
- Show Hidden Channels toggle in Settings

### Coming Up Next
An overlay appears near the end of each episode showing the title of
the next item in the queue.

### Exact Resume
Stop mid-episode and the addon saves your exact position. Next time you
open the channel, a resume dialog offers to continue from where you left
off or start over. Position is polled every 60 seconds and saved to
state.json.

### Recycle vs Play Once
- **Recycle=True** — channel loops forever
- **Recycle=False** — channel exhausts when all content is played.
  Serial channels with Recycle=False auto-delete on exhaustion.

### View Exclusions (Movie Channels)
See and manage which movies have been excluded from a movie channel's
rotation.

### Backup & Restore
Export all channel definitions and state to a zip file. Restore from
any previous backup. Useful before major changes or when migrating to
a new device.

---

## Multi-Client / Shared Storage

The addon supports MySQL-backed shared Kodi libraries served over
NFS/SMB from a NAS. Queue files and state.json can be stored on shared
storage so multiple clients (e.g. two NVIDIA Shields) share the same
channel positions. Configure the shared path in Settings → Network.

---

## Architecture

### Module Ownership (never violated)
- `service.py` — ALL playback callbacks, state advancement, skip
  detection, resume, queue top-up, carousel ticks, exhaustion handling
- `player.py` — ONLY `start_channel()` and `_write_now_playing()`
- `channel_manager.py` — queue building, state read/write, library
  access, CRUD operations
- `library.py` — the ONLY file that calls `executeJSONRPC`
- `utils/paths.py` — canonical path and JSON utilities

### File Layout
```
plugin.video.smartchannels/
├── addon.py                      Entry point; dispatches URL actions
├── addon.xml                     Kodi manifest
├── service.py                    Always-on background service
└── resources/
    ├── settings.xml              Addon settings schema
    ├── language/
    │   └── resource.language.en_gb/
    │       └── strings.po        All localised strings (457 strings)
    ├── skins/
    │   ├── skin.estuary/         Side panel XML (Estuary)
    │   ├── Default/              Side panel XML (Default)
    │   └── skin.confluence/      Side panel XML (Confluence)
    └── lib/
        ├── channel_manager.py    CRUD, state, queue building, top-up
        ├── library.py            Kodi JSON-RPC wrapper
        ├── player.py             start_channel() only
        ├── router.py             URL action → controller
        ├── carousel.py           Carousel tick logic
        ├── serial.py             Serial channel queue builder
        ├── state.py              State key helpers
        ├── coming_up_next.py     CUN overlay
        ├── channels/
        │   ├── tv.py             TV queue builder
        │   ├── movies.py         Movie queue builder
        │   ├── folder.py         Folder queue builder
        │   ├── serial.py         Serial queue builder
        │   ├── interleave.py     Interleave weaving logic
        │   └── base.py           Shared base class
        ├── ui/
        │   ├── channels.py       Channel listing, wizards, dialogs
        │   ├── side_panel.py     Side panel window controller
        │   ├── auto_channels.py  Auto-Create wizard
        │   └── dialogs.py        Shared dialog helpers
        └── utils/
            ├── paths.py          Path and JSON utilities
            ├── logger.py         Logging helpers
            └── extra_folders.py  Folder scanning utilities
```

### Data Files (addon profile folder)
| File | Purpose |
|------|---------|
| `channels.json` | All channel definitions |
| `state.json` | Per-channel playback pointers, resume positions, carousel clocks |
| `queue_<id>.json` | Current episode/movie queue per channel |
| `now_playing.json` | Active channel pointer (written by player.py) |
| `local_library.json` | Local cache of Kodi library (TV shows, movies) |

---

## Settings

| Category | Key Settings |
|----------|-------------|
| Channels | Create New Channel, Auto-Create Channels, Open Smart Channels |
| Playback | Episodes Per Slot default, queue size default |
| Cache | Library cache age, Refresh Library Cache |
| Network | Shared storage path for multi-client setups |
| Resume | Enable/disable resume, poll interval, ask or auto-resume |
| Advanced | Show Hidden Channels, Side Panel toggle, Delete All Addon Data |
| Backup & Restore | Backup Addon Data, Restore Addon Data |
| Coming Up Next | Enable/disable, timing |

---

## Installation

1. Zip the `plugin.video.smartchannels/` folder (uncompressed, no
   `__pycache__` directories).
2. In Kodi: **Add-ons → Install from zip file** → select your zip.
3. Or copy the folder directly to
   `~/.kodi/addons/plugin.video.smartchannels/`.
4. Enable the addon and navigate to **Video Add-ons → Smart TV Channels**.
5. Go to **Settings → Cache → Refresh Library Cache** before creating
   your first channel.

---

## Known Limitations

- **Editing a channel that is currently playing on another device.**
  The edit saves correctly but the playing device won't pick up the
  change until it stops and reopens the channel. Avoid editing a channel
  that is actively playing on another client if you need the change
  immediately.
- **Double-silent at top-up join boundary.** When two top-ups fire in
  rapid succession on a channel with silent folder interleave, two
  silent items may appear back-to-back at the join. Playback is
  unaffected; it is cosmetic only.
- **Movie channel filter persistence.** Filter type and value (Genre,
  Year, etc.) are not currently displayed in Channel Info or
  pre-selected when editing a movie channel. The filter is applied
  correctly at creation — this is a display/edit convenience issue only.
- **Channel logos.** Not yet implemented. Planned for the next revision.

---

## Version

Current stable release: **1.1.6f**
Compatible with: Kodi 21 (Omega), Kodi 22 (Piers)
