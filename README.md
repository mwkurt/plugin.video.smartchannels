# plugin.video.smartchannels
## Smart TV Channels for Kodi 21 (Omega) / Kodi 22 (Piers)

Create smart TV-style channels from your Kodi library and music collection.
Channels play continuously with persistent queue management, resume from
exact playback position, and full support for multi-client shared storage
(e.g. multiple NVIDIA Shields sharing the same NAS and MySQL library).

---

## Channel Types

### TV Channel
Rotates through one or more TV shows in round-robin or random order.
- **Round Robin** — shows play in strict rotation, one or more episodes per turn
- **Random** — episodes from each show in random order with no-repeat tracking
- **Episodes Per Slot** — each show can contribute N consecutive episodes per
  turn (e.g. Show A=2, Show B=1 → AA, B, AA, B …)
- **Per-show playback order** — each show in a channel can independently be
  set to sequential or random
- **Per-show episode filters** — filter which episodes of a show are eligible
  for a channel (e.g. only certain seasons or rating ranges)
- **Episode exclusions** — exclude specific episodes from a show
- **Custom starting point** — choose a specific episode (or Surprise Me!) for
  each show at channel creation
- **Manual rotation order** — arrange shows in the order you want

### Movie Channel
Plays movies sequentially or shuffled with full cycle tracking.
- **All Movies** — every movie in your library
- **Select Specific Movies** — hand-pick a list of titles
- **Filter rules** — filter by Genre, Year, MPAA rating, Studio, or Rating
  using multiple AND/OR rules applied dynamically at every queue build
- **Recycle or play once** — loop the full catalogue or exhaust and stop
- **Resume** — stop mid-movie and resume exactly where you left off

### Serial Channel
Plays shows in strict broadcast order — Show A all the way through, then
Show B from the beginning. No rotation. Designed for watching a series
from start to finish before moving on.
- Recycle or play once (channel auto-deletes when all shows are exhausted)

### Folder Channel
Plays all video files from a local or network folder path, in order or
shuffled. Useful for bumpers, intros, commercials, or any content not in
the Kodi library. Durations are captured on first playback and stored in
companion NFO files.
- **Recycle or play once** — loop the folder or stop after one pass

### Audio Channel
Library-based music channel with full filter support.
- **Filter by Artist** — pick one or more artists, then select which albums
  to include and optionally exclude individual songs
- **Filter by Genre** — play all music of a given genre
- **Filter by Album** — play a specific album
- **No filter** — play your entire music library
- **Playback order:**
  - *Random* — pure shuffle, songs may repeat between top-ups
  - *Random (no repeats)* — all songs play once before any repeat; cycle
    tracked persistently in state.json
  - *Balanced* — equal airtime per artist (artist-interleaved shuffle)
  - *Album Order* — sorted by albumartist → album → disc → track
  - *Shuffle Albums* — albums shuffled but tracks within each album in order
- Audio channels always recycle — they loop continuously

### Party Mode Channel
Points at any folder of audio files and plays them in random order.
Works with MP3, FLAC, M4A, AAC, OGG, WAV, and other common formats.
No library required — points directly at a folder on disk or NAS.
Files that match songs in your Kodi music library receive full metadata
automatically.
- **Playback order:** Random or Random (no repeats — all files play once
  per cycle)
- Party channels always recycle

### Auto-Create Channels
Automatically generates channels from your library using a multi-step wizard:
- **Content type** — TV only, Movies only, or Both
- **Group by** — Genre, Decade, Genre + Decade, or Studio/Network
- **Minimum items** — exclude channels below a content threshold
- **Interleave** — weave movies into TV channels at a configurable frequency
- **Preview** — multiselect screen to confirm which channels to create

---

## Key Features

### Channel Icons
Assign custom icons to channels two ways:
- **Auto-match** — set a Channel Icon Folder in Settings. Any image whose
  name matches a channel name is automatically used as that channel's icon.
- **Manual** — right-click any channel → Set Channel Icon → browse for any
  image file.

### Carousel Mode (Pseudo-Live)
TV and Movie channels can be set to Carousel mode, which advances the queue
on a wall-clock timer (default: 20 minutes). When you open a Carousel
channel, you pick up wherever the clock currently sits — just like a real
broadcast channel.

### Interleave
Insert content from a second channel into a TV channel's playback at a
configurable frequency. Silent interleave hides the interleaved item from
the OSD and upcoming list — ideal for bumpers or commercials.

### Channel Scheduling
Schedule a source channel's content to play on a target channel at a
recurring day and time — like real broadcast programming blocks.
- **Soft-start** — waits for the current item to finish naturally before
  inserting the block; never cuts mid-episode
- **Block insertion** — source items are prepended to the target queue;
  regular content resumes automatically after the block completes
- **Soft-stop** — optional wall-clock time after which the block ends early,
  even if the full item count has not been consumed
- **Source channel advance** — items consumed by a block are marked played
  on the source channel, exactly as if watched there directly
- **Recurrence** — Daily, Weekdays, Weekends, a specific day of the week,
  or Once
- **Once with date** — once-only schedules can target a specific future date
  (DD/MM/YYYY) rather than the next occurrence
- **Conflict detection** — prevents overlapping schedules on the same target
  and prevents a source channel appearing in more than one schedule at a time
- **Schedule Wizard** — step-by-step: name, target channel, source channel,
  day, start time, item count, optional soft-stop time, confirm summary
- **Manage Schedules** — Settings → Manage Schedules; lists all schedules
  with active/inactive status; per-schedule: Edit, Toggle, Delete

### Side Panel
The main channel list opens as a two-pane side panel:
- **Left pane** — channel list with icon and name
- **Right pane** — upcoming queue for the selected channel with artwork,
  title, episode info, and duration
- Arrow right to enter the right pane and start playback from any item
- Full context menu: Channel Info, Play, Reset, Edit, Delete, Toggle
  Visibility, Move Up, Move Down, Manage Interleave, View Exclusions,
  Set Channel Icon, Add Schedule

### Lower Third Ticker
A broadcast-style ticker strip runs along the bottom of the Side Panel,
advertising upcoming content across all your channels. Rotates through
next-item entries and show promos every 8 seconds. Phrase templates are
fully user-editable via `ticker_phrases.txt` in the addon data folder —
one phrase per line, with `{show}` and `{channel}` tokens substituted
at runtime.

### Coming Up Next
An overlay appears near the end of each item showing the title, episode
info (for TV), artist and album (for audio), and the artwork of the next
item in the queue. Separate settings for video and audio channels: lead
time before end, display duration, minimum item length.

### Channel Logo Overlay
Displays the channel icon briefly when each new item starts — like a real
broadcast channel bug. Configurable corner position, size, opacity, screen
margin, and display duration (default 5 seconds). Auto-dismisses without
blocking any input.

### Duration Cache
Every queue item carries an accurate duration in seconds.
- **TV and Movie channels** — durations read from companion NFO files
  (written by Sonarr/Radarr). Items with no readable NFO are skipped;
  a "Missing Durations" entry appears on the channel context menu listing
  all skipped items.
- **Folder channels** — uses a user-configured default duration until the
  file has been played once, then captures the real duration and writes a
  companion NFO automatically.
- **Duration display** — shown inline in the Side Panel right pane:
  "S03E04 · 23 min", "1990 · 1 hr 58 min", "3:42".

### Songs Cache
The full music library is cached locally on first startup in a background
thread (paginated for speed — typically 2–3 minutes for large libraries).
Audio and Party channel creation is instant after the initial build. The
cache refreshes automatically after a music library scan completes, or
manually via Settings → Cache → Rebuild Songs Cache.

### Exact Resume
Stop mid-item and the addon saves your exact position (polled every 60
seconds by default). Next time you open the channel, a resume dialog
offers to continue from where you left off — or start from the beginning.

### Recycle vs Play Once
- **Recycle=True** — channel loops forever (applies to all channel types
  where this setting is available)
- **Recycle=False** — channel exhausts when all content is played; an
  exhaustion dialog offers to delete the channel, reset it, or do nothing

### Channel Sort Order
- **Move Up / Move Down** — instant reorder from the context menu on any channel
- **Sort A–Z** — one-tap alphabetical sort from Settings → Channels

### Backup & Restore
Export all channel definitions, schedules, and state to a zip file.
Restore from any previous backup.

---

## Multi-Client / Shared Storage

Supports MySQL-backed shared Kodi libraries over NFS/SMB. Queue files and
state.json can be stored on shared storage so multiple clients share the
same channel positions. Configure the shared path in Settings → Network.

---

## Architecture

### Module Ownership
- `service.py` — ALL playback callbacks, state advancement, skip detection,
  resume, queue top-up, carousel ticks, schedule ticks, exhaustion handling
- `player.py` — ONLY `start_channel()` and `_write_now_playing()`
- `channel_manager.py` — queue building, state read/write, library access,
  CRUD operations, channel icon resolution, schedule CRUD, audio no-repeat
  state, party no-repeat state
- `library.py` — the ONLY file that calls `executeJSONRPC`
- `utils/paths.py` — canonical path and JSON utilities

### File Layout
```
plugin.video.smartchannels/
├── addon.py                      Entry point; dispatches URL actions
├── addon.xml                     Kodi manifest
├── service.py                    Always-on background service
├── LICENSE                       GPL-2.0
└── resources/
    ├── settings.xml              Addon settings schema
    ├── language/
    │   └── resource.language.en_gb/
    │       └── strings.po        All localised strings
    ├── skins/
    │   ├── skin.estuary/         Side panel XML (Estuary 1080i)
    │   ├── Default/              Side panel XML (Default 1080i)
    │   └── skin.confluence/      Side panel XML (Confluence 720p)
    └── lib/
        ├── channel_manager.py    CRUD, state, queue building, top-up
        ├── library.py            Kodi JSON-RPC wrapper + local cache
        ├── player.py             start_channel() only
        ├── router.py             URL action dispatcher
        ├── carousel.py           Carousel tick logic
        ├── scheduler.py          Schedule fire/block/completion logic
        ├── serial.py             Serial channel helpers
        ├── state.py              State key helpers
        ├── coming_up_next.py     Compatibility shim → overlays/
        ├── channels/
        │   ├── tv.py             TV queue builder
        │   ├── movies.py         Movie queue builder
        │   ├── folder.py         Folder queue builder
        │   ├── serial.py         Serial queue builder
        │   ├── audio.py          Audio queue builder + no-repeat tracking
        │   ├── party.py          Party Mode queue builder + no-repeat tracking
        │   ├── interleave.py     Interleave weaving logic
        │   └── base.py           Shared base class
        ├── overlays/
        │   ├── logo_overlay.py   Channel logo overlay
        │   └── coming_up_next.py CUN overlay (canonical)
        ├── ui/
        │   ├── channels.py       Channel listing, wizards, dialogs
        │   ├── side_panel.py     Side panel window controller + ticker
        │   ├── auto_channels.py  Auto-Create wizard
        │   ├── schedule_wizard.py Schedule wizard + Manage Schedules
        │   └── dialogs.py        Shared dialog helpers
        └── utils/
            ├── paths.py          Path and JSON utilities
            ├── logger.py         Logging helpers
            ├── duration_cache.py Duration read/write helpers
            └── extra_folders.py  Folder scanning utilities
```

### Data Files (addon profile folder)
| File | Purpose |
|------|---------|
| `channels.json` | All channel definitions |
| `state.json` | Per-channel playback pointers, resume positions, carousel clocks, schedule block state, audio/party no-repeat played lists |
| `queue_<id>.json` | Current queue per channel |
| `now_playing.json` | Active channel pointer (written by player.py) |
| `schedules.json` | All schedule definitions |
| `ticker_phrases.txt` | User-editable phrase pool for the Lower Third Ticker |
| `local_library.json` | Local cache of Kodi video library (shows + movies) |
| `songs_cache.json` | Local cache of Kodi music library (all songs) |
| `missing_durations.txt` | Log of queue items skipped due to missing NFO duration |

---

## Settings

| Category | Key Settings |
|----------|-------------|
| Channels | Create New Channel, Auto-Create Channels, Open Smart Channels, Channel Icon Folder, Sort Channels A–Z, Manage Schedules |
| Playback | Episodes Per Slot default, queue size default |
| Cache | Library cache age, Refresh Library Cache, Songs Cache Age, Rebuild Songs Cache |
| Network | Shared storage path for multi-client setups |
| Resume | Enable/disable resume, poll interval, ask or auto-resume |
| Advanced | Show Hidden Channels, Side Panel toggle, Show Ticker toggle |
| Backup & Restore | Backup Addon Data, Restore Addon Data |
| Coming Up Next | Enable/disable (video), lead time, display duration, min duration; separate settings for audio channels |
| Channel Logo | Enable/disable, corner position, size, opacity, margin, display duration |

---

## Installation

1. In Kodi: **Add-ons → Install from zip file** → select the zip.
2. Or copy the folder directly to `~/.kodi/addons/plugin.video.smartchannels/`
3. Enable the addon and navigate to **Video Add-ons → Smart TV Channels**.
4. Go to **Settings → Cache → Refresh Library Cache** before creating your
   first channel.
5. The songs cache builds automatically in the background on first startup
   if you plan to use Audio or Party Mode channels.

---

## Known Limitations

- **Multiple interleave sources — frequency behaviour with 3+ sources:**
  Interleave weaving is processed sequentially — Source A weaves into the
  raw queue first, then Source B weaves into the result of A, then Source C
  into the result of A+B. Each subsequent source's frequency counter is
  influenced by the previous sources' items. This enables two useful patterns:

  **Clustered break pattern (4/5/6):** frequencies spaced tightly produce a
  broadcast-style commercial break — N episodes, then all interleave sources
  fire in quick succession, then back to episodes.
  ```
  L L L L B C N L L L L B C N
  ```

  **Staggered independent pattern (4/6/8):** frequencies spaced further apart
  distribute sources independently throughout the content.
  ```
  L L L L B L L C L L L L B L N L L L C
  ```

  Recommended maximum: 2–3 interleave sources per channel. Beyond 3, interactions
  become difficult to predict. Keep jitter low when using multiple sources.

- **Audio/Party no-repeat tracking requires a fresh channel** — if you enable
  "Random (no repeats)" on an existing channel created before version 1.2.1o,
  delete and recreate the channel so queue items are written with the correct
  song/file IDs for tracking.

- **Editing a channel that is currently playing on another device** — the
  edit saves correctly but the playing device won't pick up the change until
  it stops and reopens the channel.

- **Double-silent at top-up join boundary** — two silent interleave items
  may appear back-to-back at a queue join. Playback is unaffected.

- **Carousel edit pre-selection** — the edit wizard does not pre-highlight
  Carousel Enabled when editing a carousel channel. The setting is preserved
  correctly on save.

- **Scheduled block boundary flash** — when a scheduled block takes over at
  an episode boundary, Kodi's playlist auto-advance may briefly start the
  next regular episode before the block replaces it. Sub-second and platform
  dependent; no state is corrupted.

- **Deliberate stop cancels a pending block** — if you stop playback before
  the current episode ends after a block has fired, the block items stay at
  the front of the queue and play next time the channel is opened.

- **Folder item duration on first play** — folder items without a companion
  NFO show no duration in the Side Panel until after first playback, when
  the real duration is captured and written.

- **Audio CUN artist/album** — Coming Up Next for audio channels shows artist
  and album from the queue item. Party Mode items sourced from files not in
  the Kodi music library will show only the song title since file-only items
  have no library metadata.

- **`onPlayBackEnded` on audio transitions** — on some Kodi builds, audio
  playlist transitions do not fire `onPlayBackEnded`. The addon detects these
  transitions via its skip-detection path and handles them correctly.

---

## License

GPL-2.0-only. See LICENSE file.

## Version

Current release: **1.2.1u**
Compatible with: Kodi 21 (Omega), Kodi 22 (Piers)

