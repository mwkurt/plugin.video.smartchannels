# Smart TV Channels — Changelog

---

## Version 1.2.1u

### Bug fix: last movie resume replaced by exhaustion dialog on stop/restart

When the last movie on a recycle=False channel was stopped mid-way
(after a resume position was saved), reopening the channel showed the
exhaustion dialog instead of offering to resume.

Root cause identified from log evidence: when the user skips to the last
movie in the playlist, `_update_queue_file` triggers a top-up. The top-up
returns 0 new items (last movie is the only unplayed one). The
skip-exhaustion check then fired:

    if len(remaining) <= 1 and len(new_remaining) == len(remaining):
        is_done = True

`remaining == 1` (the last movie still playing) satisfied `<= 1`, so
`is_done = True` was set, the queue file was deleted, and
`_pending_exhausted_channel` was set — all while the movie was still
playing. Resume saves written at 60s, 120s, etc. were orphaned because
the queue file was gone. On restart, `_resume_from_existing_queue` found
no queue file, `_channel_exhausted()` returned True, and the exhaustion
dialog fired before any resume could be offered.

Fix: change `len(remaining) <= 1` to `len(remaining) == 0`. The
skip-exhaustion path now only fires when the queue is completely empty
(the last item has genuinely finished). When `remaining == 1` the item
is still playing — `onPlayBackEnded` handles exhaustion correctly after
natural completion without deleting the queue file prematurely.

**File changed:** `service.py` only.
**Strings:** unchanged (Highest #32804, 0 duplicates, 0 broken).

---

## Version 1.2.1t

### Party channel improvements (mirrors audio channel fixes)

**Remove Recycle/Stop from party wizard**
Party channels have no working exhaustion tracking. The step is removed
and `recycle=True` is hardcoded, matching the audio channel fix in 1.2.1n.

**New playback order: Random (no repeats)**
Party wizard now offers two choices: Random and Random (no repeats).
No_repeat tracking uses file paths (not songid — party files are not in
the library) stored under `ch_<id>:party_no_repeat_played` in state.json.
Full cycle resets when all files have been heard. Both the skip loop and
`_handle_end` record played files, matching the audio channel pattern.

**Channel info and channel list display updated**
Party channels now show their playback order in both the channel list
entry and the channel info dialog. The "When exhausted" line is removed.

**New public methods on channel_manager:**
- `get_party_no_repeat_played(channel_id)`
- `set_party_no_repeat_played(channel_id, played)`

**Files changed:** `service.py`, `resources/lib/channels/party.py`,
`resources/lib/channel_manager.py`, `resources/lib/ui/channels.py`.
**Strings:** unchanged (Highest #32804, 0 duplicates, 0 broken).

---

## Version 1.2.1s

### Bug fix: audio channels creating spurious TV-style state entry

On every audio song start, `set_now_playing` was creating a state.json
entry shaped like a TV episode (`next_episode_id`, `season`, `episode`,
`played_ids`) under the key `ch_<id>:0`. This is meaningless for audio
and pollutes state.json with junk data.

The guard that prevents this for movies (`is_movie`) was not extended to
audio items. Fixed by adding `or ep.get("is_audio")` to the guard so
audio items are skipped the same way movies are.

After this fix, state.json for an audio channel will only contain the
`ch_<id>:audio_no_repeat_played` key written by no_repeat tracking —
nothing else.

**File changed:** `service.py` only.
**Strings:** unchanged (Highest #32804, 0 duplicates, 0 broken).

---

## Version 1.2.1r

### Bug fix: no_repeat tracking never fires on this Kodi platform

`record_no_repeat_played` was only called from `_handle_end`, which is
only reached via `onPlayBackEnded`. On this Kodi build, `onPlayBackEnded`
does not fire reliably for audio playlist items — song transitions instead
appear as single-position "skip" detections in `_check_now_playing`.

Fixed by adding a dedicated audio branch in the skip detection loop,
parallel to the existing folder item branch. When the skip loop processes
an audio item on a `no_repeat` channel, it calls `record_no_repeat_played`
and continues — matching the same pattern used for folder and movie items.
The `_handle_end` call site is retained for platforms where
`onPlayBackEnded` does fire correctly.

**File changed:** `service.py` only.
**Strings:** unchanged (Highest #32804, 0 duplicates, 0 broken).

---

## Version 1.2.1q

### Architecture fix: audio no_repeat state I/O moved to channel_manager

`_no_repeat_filter` and `record_no_repeat_played` in `audio.py` were
calling `self._cm._load_json` and `self._cm._save_json` directly —
private channel_manager methods. State I/O belongs to channel_manager,
not to a queue builder.

Fixed by adding two public methods to `channel_manager.py`:
- `get_audio_no_repeat_played(channel_id)` — returns played songid list
- `set_audio_no_repeat_played(channel_id, played)` — persists the list

`audio.py` now calls these public methods only. No private method access.
No behaviour change — pure architectural correction.

**Files changed:** `channel_manager.py`, `resources/lib/channels/audio.py`.
**Strings:** unchanged (Highest #32804, 0 duplicates, 0 broken).

---

## Version 1.2.1p

### Bug fix: "Random (no repeats)" showing as "Random" in channel info dialog

The channel info dialog had a separate `order_str` lookup dict from the
channel list display, and the `no_repeat` entry was missing from it.
Fixed by adding `"no_repeat": self._s(32804)` to the channel info dict.

**File changed:** `resources/lib/ui/channels.py` only.
**Strings:** unchanged (Highest #32804, 0 duplicates, 0 broken).

---

## Version 1.2.1o

### Bug fix: Audio CUN missing artist and album

`_write_now_playing()` in `player.py` serialised audio queue items through
the TV/folder minimal branch, which only writes `title`, `file`, `duration`
and the standard ID fields. `artist`, `album`, `songid`, `is_audio`, and all
other music metadata were stripped on every queue write.

Fixed by adding a dedicated audio/party branch that preserves all music
fields. Coming Up Next and the side panel now correctly display artist and
album for audio channels.

**File changed:** `resources/lib/player.py` only.
**Strings:** unchanged (Highest #32804, 0 duplicates, 0 broken).

---

## Version 1.2.1n

### Audio channel improvements

**Remove Recycle/Stop from audio wizard**
Audio channels have no exhaustion tracking, so the Recycle/Stop dialog
was meaningless. The step is removed. All audio channels are implicitly
recycle=True.

**New playback order: Random (no repeats)**
Adds a "Random (no repeats — all songs play once)" option to the audio
channel wizard. Tracks played song IDs in state.json under the key
`ch_<id>:audio_no_repeat_played`. On each top-up, already-played songs
are excluded. When the full pool has been heard, the played list resets
and a new cycle begins. Pure random shuffle within each cycle.

**Files changed:** `resources/lib/channels/audio.py`,
`resources/lib/ui/channels.py`, `service.py`, `strings.po`.
**Strings:** #32804 added. Highest #32804, 0 duplicates, 0 broken.

---

## Version 1.2.1m

### Bug fix: Sort Channels A-Z uses lexicographic order instead of natural order

Channel names with numbers sorted incorrectly: "Channel 11" appeared
before "Channel 2" because string comparison treats "1" < "2" character
by character. Fixed by replacing the plain `.lower()` sort key with a
natural sort that splits names into alternating text and integer segments,
sorting numeric parts as integers.

Before: 1, 11, 12, 13, 14, 2, 3, 4 ...
After:  1, 2, 3, 4, 11, 12, 13, 14 ...

**Files changed:** `resources/lib/channel_manager.py` only.
**Strings:** unchanged (Highest #32803, 0 duplicates, 0 broken).

---

## Version 1.2.1l

### Bug fix: Serial channel ignores queue_size when pool < queue_size

A serial channel with QS=200 and a 15-episode pool (2 shows) only built
~30 items instead of 200 — the same as QS=30. Root cause: `max_visits`
in the build loop was set to `len(shows) + 1` (3 for a 2-show channel),
which only allowed a single cycle through the show list before the
infinite-loop guard broke out, regardless of how many cycles were needed
to fill `target_size`.

Fix: `max_visits` is now `(target_size + 1) * len(shows) + 1`, which
gives the loop enough headroom to fill any target_size regardless of pool
size, while still providing a hard ceiling against infinite loops.

Practical effect: a 2-show serial channel with 15 total episodes and
QS=200 now correctly builds 200 items (13+ full cycles). Top-ups during
playback continue the sequence correctly via `refill_queue →
SerialQueueBuilder.build()` with `current_queue` scan.

**Files changed:** `resources/lib/channels/serial.py` only.
**Strings:** unchanged (Highest #32803, 0 duplicates, 0 broken).

---

## Version 1.2.1k

### Bug fix: Serial recycle=False channels incorrectly top up when QS > pool size

When a serial channel with recycle=False had a queue_size larger than its
total episode pool (e.g. QS=200 with 15 episodes across 2 shows), the
top-up mechanism fired immediately after creation or on first resume,
treating the 15-item queue as "below threshold" (default threshold=15).
The serial builder had already placed all content into the queue — there
is nothing legitimate to top up — but the top-up called build() again,
which wrapped and produced repeated/interleaved content.

**Root cause:** The top-up guard in `_resume_from_existing_queue` used
`_channel_exhausted()` to decide whether to top up. For serial channels
that have never played anything yet, `_channel_exhausted()` correctly
returns False (no `next_episode_id=None` written to state), so the guard
does not prevent the top-up. `_channel_exhausted()` is the right guard
for TV/Movie/Folder recycle=False channels (which legitimately need top-ups
while unplayed content remains), but serial is architecturally different:
the builder places ALL content into the queue at build time — the queue
IS the complete content list.

**Fix:** Added `is_serial_stop` guard in both `_resume_from_existing_queue`
(channel_manager.py) and `_update_queue_file` (service.py). When
`channel_type == "serial"` and `recycle=False`, top-up is blocked entirely.
All other channel types are unaffected — TV, Movie, Folder, Audio, Party
recycle=False channels continue to top up via `_channel_exhausted()` as
before. Serial recycle=True channels are also unaffected (`is_serial_stop`
is False when recycle=True).

**Files changed:** `service.py`, `resources/lib/channel_manager.py`
**Strings:** unchanged (Highest #32803, 0 duplicates, 0 broken).

---

## Version 1.2.1k

### Bug fix: Serial channel queue corrupted by wrong builder on first play

When a serial channel was played, `_resume_from_existing_queue` called
`_topup_queue` (the TV round-robin builder) to top up the queue. This is
architecturally wrong — `_topup_queue` has no knowledge of serial show
order and produces interleaved content. The corruption was visible
immediately: the queue file gained 15 extra items alternating between
shows instead of playing them sequentially.

**Root cause:** `_resume_from_existing_queue` checked `_channel_exhausted()`
to decide whether to top up. For a channel that has never been played,
`_channel_exhausted()` correctly returns False (no playback state written
yet), so the top-up fired regardless of whether there was any new content
to add.

**Fix:** Serial channels are excluded from the `_topup_queue` call in
`_resume_from_existing_queue` entirely. Serial top-ups during playback
go through `refill_queue → SerialQueueBuilder.build()`, which correctly
continues from the current position and returns nothing when all content
is already queued. The TV round-robin builder must never touch a serial
channel queue.

This applies to both recycle=True and recycle=False serial channels since
`_topup_queue` is wrong for serial in either case.

**Files changed:** `resources/lib/channel_manager.py` only.
**Strings:** unchanged (Highest #32803, 0 duplicates, 0 broken).

---

## Version 1.2.1j

### New: Audio channel "Shuffle Albums" playback order

Adds a fourth playback order option for Audio channels: **Shuffle Albums**.

- All selected albums across all chosen artists are pooled together
- The album sequence is randomised (shuffled as whole units)
- Tracks within each album play in disc → track order
- Complete albums play through before moving to the next

This fills the gap between "Album Order" (strict artist-then-artist sequence)
and "Random" (individual songs shuffled). Shuffle Albums gives album-coherent
playback with a randomised album sequence across all artists.

**Wizard behaviour:**
- Artist Rotation Order picker: shown for Shuffle Albums with 2+ artists
  (controls which artist's albums seed the shuffle pool)
- Album Order picker per artist: shown for Shuffle Albums with 2+ albums
  (allows manual or shuffled ordering within an artist before global shuffle)
- `randomize` flag: remains False (album-coherent, not song-random)

**Files changed:** `channels/audio.py`, `ui/channels.py`, `strings.po`
**New string:** #32803 "Shuffle Albums"
**Strings:** 595 total, 0 duplicates, 0 broken.

---

## Version 1.2.1i

### Removed: Channel Visibility (Hide/Show) feature

Channels are always visible. The feature added friction to channel creation
with no real benefit — if you don't want a channel, delete it.

**Removed in full:**
- Visibility wizard step in all wizards (TV/Movie, Audio, Party, Serial, Folder)
- "Toggle Visibility" entry in addon.py dispatch table, router.py, and both
  context menus (plugin directory and Side Panel)
- `[H]` prefix on hidden channels in both list views
- "Show Hidden Channels" setting in settings.xml
- `show_hidden` branching in list_channels and all Side Panel refresh paths
- `toggle_visibility()` in channel_manager.py
- Strings: #32156, #32207, #32232, #32233, #32287, #32288

**Files changed:** `addon.py`, `router.py`, `channel_manager.py`,
`ui/channels.py`, `ui/side_panel.py`, `settings.xml`, `strings.po`
**Strings:** 594 total, 0 duplicates, 0 broken (6 removed).

---

## Version 1.2.1h

### Bug fix: Movie channel recycle=False random queue ignored queue_size

When a Movie channel was configured as All Movies / Random / Stop (recycle=False)
with a queue_size smaller than the library, the fresh build ignored the target
and queued the entire unplayed pool — Test 5 built 5613 items instead of 200.

Root cause: the `recycle=False` random branch in `_build_movie_queue` iterated
the full shuffled pool with no `target_size` cap. The `recycle=True` path and
the sequential path both cap correctly at `target_size`; this branch was the
only one missing the guard.

Fix: added `if len(queue) >= target_size: break` inside the loop.

**Files changed:** `resources/lib/channel_manager.py` only.
**Strings:** unchanged (Highest #32802, 0 duplicates, 0 broken).

---

## Version 1.2.1g

### UX: Movie wizard skips filters and exclusions when user picks specific movies

When creating or editing a Movie channel via "Pick Specific Movies", the
filter rules step (Step 3b) and the movie exclusions step (Step 5b) are
now skipped entirely. Both steps are redundant when the user has already
hand-picked exactly the movies they want — filtering or excluding on top
of an explicit selection serves no purpose.

- "All Movies from Library" route: filter rules and exclusions unchanged.
- "Pick Specific Movies" route: `filters` forced to `[]`, `excluded_movies`
  forced to `[]`. Any previously stored filters/exclusions on a channel
  being edited via this route are cleared on save.

**Files changed:** `resources/lib/ui/channels.py` only.
**Strings:** unchanged (Highest #32802, 0 duplicates, 0 broken).

---

## Version 1.2.1f

### Fix — IndentationError in channels.py line 1806 on channel create

`IndentationError: expected an indented block` at `channels.py` line 1806
prevented any channel creation or editing. The `_pick_list_order()` helper
introduced in 1.2.1e had a comment and `return items` statement merged onto
the same line during the str_replace edit:

```python
# Keep as-is (0 = Keep Selection Order, -1 = cancelled)            return items
```

Python read the `return` as part of the comment, leaving the `if` block with
no body. Fixed by restoring the correct line break.

**File changed:** `resources/lib/ui/channels.py`

---

## Version 1.2.1e

### Feature — Audio channel artist and album order pickers

When creating or editing an audio channel in Artist mode, the playback
order is now selected **first** (before content selection) so the wizard
can conditionally show order pickers only when they are relevant.

**New wizard flow:**
1. Playback Order (Random / Balanced / Album Order) ← moved to step 1
2. Content mode (Filter by Artist / Advanced Filter / Full Library)
3. Artist multiselect (unchanged)
4. **Artist Rotation Order** — shown only for Balanced and Album Order
   modes when more than one artist is selected. Options: Keep Selection
   Order, Shuffle (with preview and Shuffle Again loop), Set Order
   Manually (pick artists one by one, confirm, start over).
5. Album picker per artist (unchanged)
6. **Album Order** — shown only for Album Order mode when more than one
   album is selected for an artist. Same three options as artist order.
7. Song exclusions (unchanged)
8. Recycle, Queue Size, Visibility

Order pickers are completely skipped for Random mode (order is
irrelevant) and for Balanced mode at the album level (albums within
an artist are already handled by the balanced shuffler).

**Implementation:** A reusable `_pick_list_order()` helper method was
extracted to avoid duplicating the shuffle/manual order logic that
already existed in the TV show and movie channel wizards.

**New strings:** #32799–#32802
**Files changed:** `resources/lib/ui/channels.py`,
`resources/language/resource.language.en_gb/strings.po`

---

## Version 1.2.1d

### Fix — Carousel allowed on schedule source channel after schedule fires

The carousel suppression check in the channel wizard only matched
schedules with `"active": true`. Once a Once-type schedule had fired
(`active` set to `false`), the channel could have carousel enabled on
the next edit — even though the schedule relationship still exists and
could be re-used or recreated.

Fixed: the `active` condition removed from the `_is_schedule_source`
check. Any schedule that lists this channel as its source — regardless
of active state — blocks carousel.

**Note:** Existing channels with carousel incorrectly enabled (e.g.
Block Source Channel) will not be fixed automatically. Edit the channel
through the wizard and save — the check will now detect the schedule
relationship and force `carousel_enabled = False`.

**File changed:** `resources/lib/ui/channels.py`

---

## Version 1.2.1c

### Fix — Audio/party channels available as interleave sources for video channels

The Manage Interleave source picker had no channel type filter — audio
and party channels appeared as valid interleave sources alongside TV,
movie, folder, and serial channels. Interleaving audio into a video
channel makes no sense and would produce broken queue items.

Fixed: audio and party channels now excluded from the `other` list in
`manage_interleave_dialog()`, consistent with the schedule wizard which
has correctly excluded them since 1.2.0a.

Note: the schedule wizard source and target pickers already excluded
audio and party — this fix closes the same gap in the interleave dialog.

**File changed:** `resources/lib/ui/channels.py`

---

## Version 1.2.1b

### Fix — Add Schedule and Manage Interleave shown for audio/party in Side Panel

The Side Panel context menu showed Add Schedule and Manage Interleave
for audio and party channels. The suppression that was already in place
in `channels.py` (the plugin directory view) had never been ported to
`side_panel.py`.

Fixed: both items now excluded for `audio` and `party` channel types,
matching the logic in `channels.py`.

**File changed:** `resources/lib/ui/side_panel.py`

---

## Version 1.2.1a

### Fix — Audio genre filter returning "No Genres Found In Library"

`AudioLibrary.GetGenres` was called with an empty params dict `{}`.
In Kodi 21, this RPC returns only `genreid` by default — the `title`
field is not included unless explicitly requested in a `properties`
array. Every genre item had `title=None`, the list comprehension
produced `[]`, and the wizard showed "No Genres Found In Library"
even on a library with 26,362 tagged songs.

Fixed by adding `"properties": ["title"]` to the RPC call.

**File changed:** `resources/lib/library.py`

---

## Version 1.2.0z

### Fix — Side panel song/track selection always played first song

Clicking a song in the side panel right pane for an audio or party channel
always played the first song in the queue instead of the selected one.

**Root cause:** `build_queue()` for audio and party channels always did a
fresh build — there was no `_resume_from_existing_queue()` check. So when
`_play_from_item()` reordered the queue file on disk to put the selected
song first, `play_channel()` immediately called `build_queue()` which
rebuilt from scratch, discarding the reorder.

Folder, serial, and TV channels all had the resume-from-existing check;
audio and party were missing it.

**Fix:** Added `_resume_from_existing_queue()` guard to both audio and
party branches in `build_queue()`, identical to the folder channel pattern.
The reordered queue file is now picked up and returned as-is.

**File changed:** `resources/lib/channel_manager.py`

---

## Version 1.2.0y

### Cleanup — Remove diagnostic log lines added during audio exclusion debugging

Two verbose diagnostic log lines added during the 1.2.0s–1.2.0v debug
cycle removed from `_build_audio_song_exclusions`:

- `[AudioExclusions] get_songs_with_filters: N songs, included_albums=...`
- `[AudioExclusions] pool: N artists, songs per artist: ...`

The error-path log (`get_songs_with_filters failed`) is retained as it
is genuinely useful if the songs cache ever fails to load.

**File changed:** `resources/lib/ui/channels.py`

---

## Version 1.2.0x

### Fix — Exclusion artist picker labels were ambiguous

The song exclusion artist picker showed "Jimmy Buffett — No songs excluded"
which read as a status statement rather than a clickable action. Users
reasonably assumed it was informational and selected "Done" without
realising they needed to click the artist row to enter the song picker.

Fixed by updating three strings:
- #32774: "Exclude Songs" → "Exclude Songs — Select Artist" (dialog title
  now clarifies this is an artist picker)
- #32778: "No songs excluded" → "Tap to select songs to exclude" (clearly
  an action)
- #32777: "{0} song(s) excluded" → "{0} song(s) excluded — tap to change"
  (clearly an action even when some songs are already excluded)

**File changed:** `resources/language/resource.language.en_gb/strings.po`

---

## Version 1.2.0w

### Fix — Song exclusion picker replaced with working select() toggle loop

`d.multiselect()` returns `None` immediately without displaying on this
Kodi build, causing the song list to never appear after selecting an album
in the exclusion picker. Replaced with a `d.select()` toggle loop — the
same pattern used throughout the rest of the wizard and confirmed working.

Songs are listed with `[X]` (excluded) or `[ ]` (included) markers.
Selecting a song toggles its exclusion state. "Done" exits back to the
album picker. The exclusion set is built up interactively across multiple
albums and artists before the wizard proceeds.

**File changed:** `resources/lib/ui/channels.py`

---

## Version 1.2.0v

### Diagnostic — Audio exclusion builder: expose pool key mismatch

The exclusion picker shows the artist list correctly but selecting an
artist returns immediately to the artist list without showing albums.
The pool contains 10 songs for Jimmy Buffett but `pool.get(chosen_artist)`
is returning empty — indicating the pool key and the lookup key do not
match despite appearing identical in log output.

Added log line at the exact point of the lookup:
`[AudioExclusions] picked artist=... pool keys=... albums_dict empty=...`

This will expose any hidden character, encoding, or whitespace difference
between the two strings.

**File changed:** `resources/lib/ui/channels.py`

---

## Version 1.2.0u

### Fix — Song exclusion picker never showing songs

After selecting an album in the exclusion builder, the song multiselect
dialog never appeared — control returned immediately to the album picker.

**Root cause:** `d.multiselect()` was called with `preselect=[]` (empty
list) when no songs were previously excluded. On Kodi 21, passing an
empty list to `multiselect(preselect=...)` causes the dialog to return
`None` immediately without displaying. The code then treated `None` as
"cancelled" and looped back to the album picker.

The artist and album pickers in the wizard use `multiselect()` with
non-empty preselect lists (all items ticked by default), so they were
unaffected.

**Fix:** Pass `preselect=None` when the preselect list is empty, which
tells Kodi to show the dialog with nothing pre-selected.

**File changed:** `resources/lib/ui/channels.py`

---

## Version 1.2.0t

### Fix — Audio channel fields not saved on create; exclusion builder silent failure

Two bugs in the audio channel wizard:

**1 — `create_channel` missing audio fields (`channel_manager.py`)**
When creating a new audio channel, `audio_filters`, `included_albums`,
`excluded_songs`, and `audio_order` were absent from the channel dict
built in `create_channel()`. The wizard returned them correctly but
`create_channel` never read them from the definition — identical gap to
the `update_channel` bug fixed in 1.2.0r. Fixed: all four fields added
to the `create_channel` dict.

**2 — Song exclusion builder silent exception (`ui/channels.py`)**
`_build_audio_song_exclusions` catches exceptions from
`get_songs_with_filters` and silently returns an empty list with no log
line. This masked whatever error was preventing songs from loading,
leaving the exclusion artist picker appearing to work (artist names shown)
but selecting an artist going nowhere (pool was empty). Fixed: exception
now logged before returning. Permanent `[AudioExclusions]` log lines added
after the fetch and after pool build so future failures are diagnosable.

**Files changed:** `resources/lib/channel_manager.py`,
`resources/lib/ui/channels.py`

---

## Version 1.2.0s

### Diagnostic — Audio exclusion builder: add pool/song-count logging

The song exclusion picker in the audio wizard (artist mode) shows the
artist list but selecting an artist immediately returns to the list
without showing albums. Root cause not yet confirmed from logs — the
pool that maps artist→album→songs appears to be empty when the dialog
runs. Two log lines added to `_build_audio_song_exclusions` immediately
after the pool is built:

- `[AudioExclusions] pool built: N artists, songs per artist: {...}`
- `[AudioExclusions] get_songs_with_filters returned N songs, included_albums={...}`

These will confirm whether the filtered song fetch returned results and
whether the pool was populated correctly.

**File changed:** `resources/lib/ui/channels.py`

---

## Version 1.2.0r

### Fix — Audio channel edits not saved to channels.json

When editing an audio channel (changing artist selection, album picks,
song exclusions, or playback order), the changes were silently discarded.
`channels.json` was written but contained the pre-edit values, and the
queue was not rebuilt.

**Root cause:** `update_channel()` in `channel_manager.py` had two gaps
for audio-specific fields (`audio_filters`, `included_albums`,
`excluded_songs`, `audio_order`):

1. The `channel.update()` call that persists the wizard's result to the
   in-memory channel dict did not include these four fields — so the new
   values from the wizard were never applied and `_save_channels()` wrote
   the old values back to disk.

2. The `_no_queue_change` guard that decides whether to rebuild the queue
   did not check these fields — so even if they had been saved, the queue
   would still not have been rebuilt after an audio filter change.

**Fix:** Added all four fields to both `channel.update()` and the
`_no_queue_change` comparison. Also added pre-edit snapshots of the four
fields (alongside the existing `old_shows`, `old_filters`, etc.) so the
`_no_queue_change` comparison has correct before/after values.

**Files changed:** `resources/lib/channel_manager.py`

---

## Version 1.2.0m

### Fix — Audio library API calls corrected against Kodi Omega schema

Verified all audio library RPC calls against the official Kodi Omega
`types.json` and `methods.json` schema. Found two additional incorrect
field usages:

**`AudioLibrary.GetArtists`:** `"artist"` is not a requestable property —
it is returned automatically in every `Audio.Details.Artist` result.
Requesting it caused the RPC to fail. Fixed: properties now `["thumbnail"]`
only.

**`AudioLibrary.GetGenres`:** Genres are returned with a `"title"` field
per `Library.Details.Genre` schema. The code was reading `g["label"]`
which does not exist, resulting in an empty genres list. Fixed: now reads
`g["title"]`.

**Note on `artistid` and `songid`:** Both are valid requestable fields in
the schema, but the schema explicitly warns that requesting them causes
"increased response times." They are also returned automatically, so we
never need to request them.

### Fix — Songs cache rebuild: removed blocking progress dialog

The manual "Rebuild Songs Cache" button in Settings previously showed a
progress dialog that appeared frozen because the underlying RPC call blocked
for the entire query duration with no intermediate progress updates.
Replaced with a fire-and-forget background thread: a toast fires immediately
on start, and another fires when the rebuild completes or fails.

### Optimization — Songs cache: paginated GetSongs (500 per page)

`build_songs_cache` now fetches songs in batches of 500 using the
`limits` parameter instead of one unbounded query. This prevents the
18-second single-query timeout on large MySQL libraries by breaking the
work into smaller result sets that MySQL and Kodi's JSON-RPC serializer
handle more efficiently.

**Files changed:** `resources/lib/library.py`, `resources/lib/router.py`

---

## Version 1.2.0l

### Fix — Audio channel wizard: "No genres" error when selecting Artist filter

`AudioLibrary.GetArtists` was called with `"artistid"` in the properties
array. In Kodi 21, `artistid` is returned automatically and is not a valid
requestable property — the same class of bug as `"songid"` in `GetSongs`.
The RPC call failed silently, returning 0 artists. The wizard then showed
the "No genres found" dialog (string 32478 was reused incorrectly for both
genres and artists). The user saw a confusing error about genres when the
actual problem was the artist fetch failing.

**Fixes:**
- Removed `"artistid"` from `AudioLibrary.GetArtists` properties in
  `library.py`. The ID is still returned automatically by Kodi.
- Added string #32787 "No artists found in music library." — shown when
  the artist fetch returns empty.
- Added string #32788 "No artists selected." — shown when the user
  deselects everything in the artist multiselect.
- Replaced the two incorrect 32478 ("No genres") uses in the artist
  wizard path with the correct new strings.

**Note on Settings → Cache:** The "Songs Cache Age" and "Rebuild Songs
Cache" buttons were added in 1.2.0k but may not appear until Kodi fully
restarts (not just the addon). A full Kodi restart clears the cached
settings definition and picks up the new settings.xml.

**Files changed:** `resources/lib/library.py`,
`resources/lib/ui/channels.py`,
`resources/language/resource.language.en_gb/strings.po`
(new strings #32787, #32788)

---

## Version 1.2.0k

### Feature — Songs Cache (audio channel creation now instant)

Audio channels and Party Mode both called `AudioLibrary.GetSongs` at
queue-build time. On large shared MySQL libraries this query takes 15–20
seconds, blocking channel startup entirely.

**New:** `songs_cache.json` — a local disk cache of the entire music
library, built once in the background and read in milliseconds at
channel-open time.

**How it works:**
- On addon startup, the service checks the songs cache age against the
  same `cache_max_age_days` setting used by the video cache (default 7
  days). If stale or missing, a background thread calls
  `build_songs_cache()` — the 18-second MySQL query runs once, not every
  time a channel opens.
- `get_all_songs()` in `LibraryClient` now reads from `songs_cache.json`
  first (instant), falling back to the live RPC only when no cache exists.
- In-memory caching (`_cached("all_songs")`) still applies on top, so
  repeated calls within the same session cost nothing.
- `AudioLibrary.OnScanFinished` triggers an automatic background rebuild,
  keeping the cache current after a music library scan.
- **Settings → Cache:** New read-only "Songs Cache Age" display and
  "Rebuild Songs Cache" button for manual rebuild with a progress dialog.

**Files changed:** `resources/lib/library.py`, `service.py`,
`resources/lib/router.py`, `addon.py`, `resources/settings.xml`,
`resources/language/resource.language.en_gb/strings.po`
(new strings #32785, #32786)

---

## Version 1.2.0j

### Fix — Party Mode hangs then fails on large MySQL-backed libraries

After finding audio files, `PartyQueueBuilder` called `_build_library_map()`
which issued `AudioLibrary.GetSongs` to enrich queue items with metadata.
On a large shared MySQL library this query takes 15–20+ seconds, killing
the Kodi Python script invoker before playback could start, resulting in
"No Items in Queue".

**Fix:** Removed the library lookup entirely from Party Mode. Queue items
are built directly from file paths using the filename stem as the title.
Kodi reads full tags (artist, album, track, etc.) from the audio file at
playback time, so the library lookup was unnecessary overhead.

Removed: `_build_library_map()`, `_normalise_for_compare()` from `party.py`.

**File changed:** `resources/lib/channels/party.py`

---

## Version 1.2.0i

### Fix — Party Mode fails to find audio files (local and NAS paths)

`PartyQueueBuilder` was calling `_walk()` imported from `folder.py`.
That function only collects files matching `_MEDIA_EXTS` (video extensions:
`.mkv`, `.mp4`, `.avi`, etc.), so audio files were silently excluded before
the audio extension filter in `party.py` even ran. The folder was found
correctly but `_walk` returned an empty list for any folder containing only
audio files, whether local or on a NAS.

**Fix:** Added `_walk_audio()` in `party.py` — an audio-specific walk that
uses `xbmcvfs.listdir` (handles both local and SMB paths) and filters
directly by `_AUDIO_EXTS`. The redundant post-walk audio filter is removed.
The shared `_walk` in `folder.py` is unchanged.

**File changed:** `resources/lib/channels/party.py`

---

## Version 1.2.0h

### Fix — AudioLibrary.GetSongs RPC error (audio channels broken)

`AudioLibrary.GetSongs` was failing with `Invalid params` because `"songid"`
was listed in the `properties` array. In Kodi 21, `songid` is returned
automatically in every song result and is not a valid requestable property.
Removing it from the properties list resolves the RPC error and allows audio
channels to build their queues correctly.

**File changed:** `resources/lib/library.py`

### Fix — Move Up / Move Down missing from Side Panel context menu

Move Up and Move Down were implemented in `channel_manager.py` and wired
into the old `channels.py` list view, but were never added to the Side Panel
context menu. Added both options to `_show_context_menu` in `side_panel.py`,
calling `manager.move_channel_up()` / `move_channel_down()` directly and
refreshing the channel list with focus following the moved channel.

**File changed:** `resources/lib/ui/side_panel.py`

---

## Version 1.2.0g

### Removed — Soft Stop feature

Soft-stop allowed a scheduled block to end early when a wall-clock time
was reached. It was removed because Kodi's playlist transition is atomic:
by the time `onPlayBackEnded` fires and we can check the time, Kodi has
already started the next block item. No reliable in-process mechanism exists
to interrupt that transition without risking a deadlock or race condition.

The block scheduling feature works correctly without soft-stop:

- Blocks fire at the configured time and play exactly `item_count` episodes
- When the last block item finishes, the regular target channel content
  resumes naturally via Kodi's playlist
- A1, A2, A3 test scenarios all confirmed passing

**Removed from:** `resources/lib/scheduler.py` (`on_block_item_complete`
soft-stop check, `_strip_remaining_block_items`, `_soft_stop_reached`),
`service.py` (soft-stop flag, `onPlayBackStopped` strip block,
`onPlayBackEnded` stop thread), `resources/lib/ui/schedule_wizard.py`
(Step 7 soft-stop input, related string constants and conflict-checker
soft-stop branch).

---

## Version 1.2.0f

### Fix — schedule conflict checker: real block duration + Rule 2 correction

**Fix 1 — Rule 1: conflict window now uses actual episode durations**

The target channel overlap check used a flat 120-minute default window
when no `soft_stop_time` was set. This blocked valid schedules that
started well after the actual block would have finished — e.g. 45 minutes
of content at 07:00 was blocking a schedule at 09:00.

New behaviour: `_estimate_block_duration()` reads the source channel's
queue file, sums the actual `duration` field of the first `item_count`
real (non-silent) items, and adds a 15-minute buffer. Example: 2 Til Death
episodes at ~21 minutes each = 43 minutes + 15 minute buffer = 58 minute
window. A schedule at 07:00 now only blocks until 07:58, so 08:00 is
accepted. Falls back to `item_count × 30 minutes + 15` if the queue is
unreadable or items have no duration data. Both the new schedule's window
and the existing schedule's window use the same real-duration calculation.

**Fix 2 — Rule 2: same source allowed when same target**

Rule 2 previously blocked any two schedules from sharing the same source
channel unconditionally. The correct rule is: same source is only blocked
when the two schedules target *different* channels. Two schedules on the
*same* target channel may share a source — they fire at different times
and the source channel's normal top-up cycle replenishes its queue between
fires. Same source targeting different channels remains blocked.

**New method:** `_estimate_block_duration(source_id, item_count)`
**File changed:** `resources/lib/ui/schedule_wizard.py`

---

## Version 1.2.0e

### Fix — addon appearing in Music addons section

The `<provides>` tag in `addon.xml` incorrectly declared `audio` alongside
`video`, causing Kodi to list the addon in both Video addons and Music addons.
This was introduced in 1.2.0a when the audio channel feature was added.

The `audio` declaration is not required for audio channel playback — audio
files play through Kodi's standard player via the video addon path. The addon
ID (`plugin.video.*`) already correctly identifies it as a video addon.

**Fix:** removed `audio` from `<provides>video audio</provides>` →
`<provides>video</provides>`.

**File changed:** `addon.xml`

---

## Version 1.2.0d

### Feature — Audio channel Artist/Album/Song picker, Balanced shuffle,
###           Channel Info audio/party branches, context menu cleanup

**1 — Artist → Album → Song picker (audio wizard, `ui/channels.py`)**

When creating or editing an Audio channel with "Filter by Artist" mode,
the wizard now presents three levels of selection instead of one:

- **Artist multiselect** (unchanged) — pick one or more artists from the
  music library
- **Album picker per artist** (new) — for each selected artist, a
  multiselect of all their albums. Leave all ticked to include everything;
  untick albums to exclude them entirely. Stored as `included_albums` dict
  on the channel (artist name → list of album titles).
- **Song exclusions (optional)** (new) — Yes/No gate, then artist → album
  → song multiselect. Pre-selects currently excluded songs on edit.
  Stored as `excluded_songs` list of songid ints on the channel.

The Advanced Filter builder (mode 2) and Full Library (mode 3) are
unchanged. Switching to either clears `included_albums` and
`excluded_songs`.

**2 — Balanced shuffle (`channels/audio.py`, `ui/channels.py`)**

New "Balanced (equal artist airtime)" playback order option. Groups songs
by primary artist, shuffles each group independently, then interleaves in
round-robin with per-pass artist-order jitter. Artists with large
catalogues no longer dominate a random channel. Stored as
`audio_order="balanced"`. Pure Random and Album Order are unchanged.

**3 — `included_albums` and `excluded_songs` applied at queue-build time
(`channels/audio.py`)**

`AudioQueueBuilder.build()` now applies both filters before ordering:
- `_apply_included_albums()` — filters songs to only those whose album
  appears in the `included_albums` selection for their artist
- `excluded_songs` — removes songs whose `songid` is in the exclusion set

**4 — `get_albums_for_artists()` (`library.py`)**

New library method. Works from the cached `get_all_songs()` result — no
extra JSON-RPC call. Returns dict mapping artist name → sorted album list.

**5 — Channel Info audio and party branches (`ui/channels.py`)**

Channel Info now has dedicated branches for audio and party channels
instead of falling through to the TV branch with empty data.

Audio branch shows: channel type label, playback order, recycle setting,
content mode (Artist / Advanced Filter / Full Library), artist list with
all albums indented underneath each artist, excluded song count.

Party branch shows: channel type label, folder path, recycle setting.

**6 — Context menu cleanup (`ui/channels.py`, `ui/schedule_wizard.py`)**

- **Add Schedule** suppressed for audio and party channels (context menu).
  Audio/party channels also removed from the schedule wizard target
  channel picker — they cannot be schedule targets.
- **Manage Interleave** suppressed for audio and party channels (was
  already suppressed for serial). Interleave is not supported for
  audio or party channel types.

**New strings:** #32772–#32784 (next free: #32785)
**Files changed:** `resources/lib/channels/audio.py`,
`resources/lib/library.py`, `resources/lib/ui/channels.py`,
`resources/lib/ui/schedule_wizard.py`,
`resources/language/resource.language.en_gb/strings.po`

---

## Version 1.2.0c

### Fix — Carousel and Schedule Source channel conflict enforced at the UI level

Previously, a channel could simultaneously have carousel enabled AND be
configured as a schedule source channel. The carousel would silently drain
the same queue the scheduler depends on for block items, causing the source
channel's queue and state to become inconsistent.

The 1.2.0b fix to `carousel.py` skipped the pop at runtime but left the
user able to configure this invalid combination without any warning.

**Three-layer fix:**

**1 — `carousel.py` (runtime guard, retained from 1.2.0b):** `check_all()`
builds a set of all active schedule source channel IDs and skips any
carousel channel whose ID is in that set. Log line:
`"[Carousel] check_all: skipping '...' — active schedule source channel"`

**2 — Channel wizard (`ui/channels.py`):** When editing a channel that is
currently configured as a source in any active schedule, the carousel step
(Step 8) is blocked entirely. The user sees an informational dialog
(string #32770) explaining why carousel is unavailable on this channel,
and `carousel_enabled` is forced to False.

**3 — Schedule wizard (`ui/schedule_wizard.py`):** The source channel
picker (Step 3) excludes any channel that has `carousel_enabled=True`.
If any channels were excluded for this reason, a brief informational
dialog (string #32771) is shown before the picker so the user understands
why those channels don't appear.

**New strings:** #32770, #32771
**Files changed:** `resources/lib/carousel.py`,
`resources/lib/ui/channels.py`,
`resources/lib/ui/schedule_wizard.py`,
`resources/language/resource.language.en_gb/strings.po`

---

## Version 1.2.0b

### Fix — target channel resumes at wrong episode after scheduled block

Port of the 1.1.9u + 1.1.9v fixes to the 1.2.0 branch. Two guards added,
both absent from 1.2.0a.

**Fix 1 — `_recalculate_tail` guard** (`channel_manager.py`):
After a scheduled block finished playing, the target channel resumed at
the wrong episode (e.g. S02E09 instead of S01E04). Root cause: during the
block hand-off, `start_channel()` → `build_queue()` →
`_resume_from_existing_queue()` called `_recalculate_tail()` on the
hand-off disk queue which contained block items from the source channel
prepended to the regular tail. The block items belong to a different show
(not in the target channel's `shows[]`) and are skipped by the guard's
`_simulated` count — but the regular tail episodes (e.g. ~28 of them)
greatly outnumber `existing_show_index` (e.g. 3, one per episode played
before the block). The guard therefore failed (`3 < 28`) and
`_recalculate_tail` overwrote the correct `advance_show` tail state with
indices derived from the full tail, causing the next `_topup_queue` to
resume at the wrong episode. Fix: early-return from `_recalculate_tail`
when the queue contains any items with `_schedule_id` set.

Confirmed in 1.1.9v (July 21 log): `"_recalculate_tail: skipping —
queue contains scheduled block items (tail preserved from advance_show)"`
fired at the hand-off, channel correctly resumed at S01E04 and played
forward through S01E07, S01E12, S01E18 over an overnight run.

**Fix 2 — boundary top-up skip guard** (`service.py`):
At the hand-off boundary, `_update_queue_file` was firing a threshold
top-up while `_pending_block_reload` was set. This was wasted work —
the imminent `start_channel()` call does its own correct top-up from the
clean disk queue. Fix: when `_need_topup` is True and
`_pending_block_reload is not None`, skip the top-up and log
`"_update_queue_file: skipping top-up — block reload pending"`. The
hand-off's own top-up handles everything correctly.

**Files changed:** `resources/lib/channel_manager.py`, `service.py`

---

## Version 1.2.0a

### New features: Audio Channels, Party Mode, Channel Sort Order

**Audio Channel** — new `audio` channel type backed by the Kodi music
library. Supports artist picker, genre/year/rating/played-status filters
with `<`, `>`, `=` operators, and random or album-order playback. Songs
play through the existing queue machinery with full Coming Up Next overlay
support (separate audio CUN settings: lead time in seconds, display
duration, minimum song length). No carousel or interleave.

**Party Mode Channel** — new `party` channel type. User selects a folder
of audio files (mp3, flac, m4a, aac, ogg, wma, wav, opus, alac, ape);
all files play in random order. Files that match songs in the Kodi music
library automatically receive full metadata (title, artist, album, art,
duration). Files not in the library fall back to filename-stem display.
Path matching normalises UNC, SMB, and %20-encoded paths before
comparing so NAS library paths match correctly.

**Channel Sort Order** — two new ways to reorder channels:
- "Move Up" / "Move Down" context menu on every channel (instant,
  persisted to channels.json)
- "Sort Channels A–Z" action button in Settings → Channels, with
  yes/no confirmation dialog

**Poll timer fix for audio** — the existing poll timer fires at
`resume_poll_interval × 60` seconds (default 5 min), which means
it never fires for a 3-minute song. Audio and party channels now
use a 10-second poll interval. Video channels unchanged.

**Audio Coming Up Next** — four new settings in the Coming Up Next
category: `cun_audio_enabled`, `cun_audio_lead` (seconds before end,
default 20), `cun_audio_duration` (overlay duration, default 15s),
`cun_audio_min_duration` (minimum song length, default 60s). Independent
of the existing video CUN settings.

**Folder default duration unit fix** — `folder_default_duration` was
previously treated as minutes (×60). It is now treated as seconds
directly. Default changed from 20 (minutes) to 120 (seconds) — same
effective value for users who left it at the default. **If you set a
custom value (e.g. 5 meaning "5 minutes"), update it to the equivalent
seconds value (300) after this upgrade.**

**Schedule wizard** — audio and party channels are excluded from the
source channel picker.

**addon.xml** — description, summary, forum URL, website, and `provides`
tag updated for repo submission.

**Files changed:** `resources/lib/library.py`,
`resources/lib/channels/audio.py` (NEW),
`resources/lib/channels/party.py` (NEW),
`resources/lib/channels/folder.py`,
`resources/lib/player.py`,
`resources/lib/channel_manager.py`,
`service.py`,
`resources/lib/overlays/coming_up_next.py`,
`resources/lib/ui/channels.py`,
`resources/lib/ui/schedule_wizard.py`,
`resources/lib/router.py`,
`addon.py`,
`resources/settings.xml`,
`resources/language/resource.language.en_gb/strings.po`,
`addon.xml`, `CHANGELOG.md`, `README.md`

---

## Version 1.1.9t

### Feature — "Once" schedules now support a specific fire date

Previously, selecting "Once" as the schedule day would fire the block on
whatever day the start time was next reached, with no way to target a
specific future date. A "Once" schedule created on a Monday at 20:00
would fire that same Monday evening even if the intent was Friday night.

**Change:** When "Once" is selected in the schedule wizard, a new step
asks for the target date in DD/MM/YYYY format. The date is validated
(rejects invalid day/month/year combinations and past dates) and stored
as `fire_date` on the schedule. The scheduler's `_should_fire_today()`
now checks `fire_date == today` for Once schedules instead of returning
True unconditionally.

Backwards compatible: existing "Once" schedules without a `fire_date`
field continue to fire on the next occurrence of the start time (old
behaviour preserved via empty-string fallback).

**Files changed:** `resources/lib/ui/schedule_wizard.py`,
`resources/lib/scheduler.py`, `resources/language/resource.language.en_gb/strings.po`,
`addon.xml`, `CHANGELOG.md`, `README.md`

---

## Version 1.1.9s

### Three fixes: block-count de-dupe, folder capture repair, CUN display logging

**1 — Skipped block items no longer double-count.** On this platform,
pressing Next fires onPlayBackEnded nondeterministically (confirmed
across the July 19-20 logs: fired in the 14:28 test, silent in later
skips). When it fired, a skipped block item was counted twice — once by
the skip loop, once by _handle_end — reaching item_count one item early
(4/4 while item 4 was still playing in the 14:28 test). All completion
counting now routes through a single service method,
`_count_block_item()`, which suppresses an immediately consecutive
repeat of the same (schedule_id, file). The de-dupe record resets on
channel switch, fresh fire, and block hand-off. Known accepted edge:
two ADJACENT block items with byte-identical file paths would
single-count. This unblocks §7 soft-stop testing.

**2 — Folder duration capture: queue update repaired.** Two stacked
pre-existing (1.1.7-era) defects in
`channel_manager.capture_folder_duration`, first exposed in the July 20
folder test: (a) it called `self._read_queue_file()` — a method that
never existed (AttributeError); (b) the except handler used
`xbmc.LOGWARNING` but channel_manager never imported xbmc, masking the
real error as "name 'xbmc' is not defined". Fixed with the canonical
`self._load_json(self._queue_file_path(id), [])` read and a module-level
`import xbmc` — which also un-masks four other except handlers in the
file (lines that would previously have crashed while reporting errors).
Companion NFO writing was always correct; the in-place queue item
duration update now works too.

**3 — Coming Up Next display logging.** The run() drain now logs
"Coming Up Next: displayed overlay for '<title>'" when show_overlay()
actually fires — previously only the queueing was logged, so overlay
rendering could not be verified from the log.

**Files changed:** `service.py`, `resources/lib/channel_manager.py`,
`addon.xml`, `CHANGELOG.md`, `README.md`

---

## Version 1.1.9r

### Fix — stale in-memory queue flushed back to disk at block hand-off

The 13:45 test confirmed the 1.1.9q guard worked (the transient
auto-advance item was ignored, no corrupt write) and CUN showed the
block head correctly. But the finished episode still reappeared in the
queue file, via a third mechanism the guard had been masking in 1.1.9p:

The boundary rewrite and SmartPlayer's subsequent queue write serialize
the **same list**, producing byte-identical JSON — so `content_changed`
never fired and the service's in-memory queue silently kept the stale
fire-time list (finished episode included). When the block head
registered, `_update_queue_file(position=0)` flushed that stale list
back to disk (log tell: "34 items on disk, 34 items in memory" vs the
33-item boundary write). It also left memory offset by one from Kodi's
playlist for the whole block, forcing forward-scan fallbacks on every
position lookup.

**Fix:** `_update_queue_file` now returns the exact list it wrote, and
`_maybe_start_block_reload` syncs the in-memory queue to it (position 0,
current file cleared) before starting the reload thread. Memory, disk,
and the new Kodi playlist are the same list from the first moment of the
new session — the stale copy ceases to exist, so there is nothing left
to flush back. The cumulative-queue rule is unchanged within a playlist
session; the reload is a new session. All other `_update_queue_file`
callers ignore the return value.

**Files changed:** `service.py`, `addon.xml`, `CHANGELOG.md`, `README.md`

---

## Version 1.1.9q

### Fix — flash-item race corrupted queue file; CUN showed wrong next item

1.1.9p's boundary hand-off worked (confirmed in the 13:16 test log) but
exposed two defects:

**Defect 1 — transient auto-advance item registered.** Between the
reload trigger and the block head starting, Kodi's playlist auto-advance
briefly played the next regular episode. That transient item registered
in `_check_now_playing` 263ms after the reload thread launched, which
(a) overwrote SmartPlayer's freshly written queue file without block
preservation (the pending flag was already consumed), and (b) pinned
`_last_file` so the stale fire-time in-memory queue — still containing
the finished episode — was written back to disk when the block head
registered. Kodi's live playlist was correct; the disk file was not
(finished episode would have replayed after the block on next open).

**Fix:** `_block_reload_guard` — armed in `_maybe_start_block_reload`
with the expected block head file before the pending flag is consumed.
While armed, `_check_now_playing` ignores every registration except the
block head (basename match); 15s timeout failsafe registers normally if
the reload never lands. The guard is cleared by: block head registering,
timeout, manual channel switch, or a true user stop. The
`content_changed` pending-set branch is skipped while the guard is armed
so the addon's own rewrites cannot re-trigger the reload. A manual
channel switch now also clears any pending reload.

**Defect 2 — Coming Up Next read file order, not play order.** With a
block waiting, the queue file is `[block..., current, next...]` but the
block plays after the current item. `_get_next_episode` returned the
file-order next item (the target's own next episode) instead of the
block head.

**Fix:** when `_pending_block_reload` is set and the current item is
regular content, `_get_next_episode` returns the first non-silent
leading block item. During block playback file order equals play order,
so the normal path is unchanged.

Also: `_basename_match()` promoted to a module-level helper (was a
closure) — now shared by the guard check and the content_changed
suppression path.

**Files changed:** `service.py`, `addon.xml`, `CHANGELOG.md`, `README.md`

---

## Version 1.1.9p

### Fix — scheduled block hand-off at the natural item boundary (4 root causes)

The 07:30 test log confirmed the block was written to disk correctly but
never played, and the block items were stripped from the queue file at the
first item transition. Code review during the fix found two additional
latent bugs that fully explain the failure chain.

**Bug 1 — onPlayBackEnded UnboundLocalError (latent, affected ALL
channels):** `svc` was referenced before assignment, so every natural item
end raised UnboundLocalError before `_handle_end()` and the queue-position
increment could run. State advancement silently fell back to skip
detection; interleave counters and natural-end resume clears never fired.
The traceback carried no addon tag, so filtered logs never showed it.
Fixed by binding `svc = self._service_ref` before first use.

**Bug 2 — block items stripped from disk:** `_update_queue_file` trimmed
the queue to the current position, discarding the freshly prepended block
items (33 → 28 items in the log). While `_pending_block_reload` is set,
the leading run of `_schedule_id` items is now preserved at the front of
the written file, and the position is re-seeded to the true index of the
playing file when the fire is detected, so the unplayed tail is computed
correctly.

**Bug 3 — reload drain could never fire:** Kodi playlist auto-advance
never reports `isPlaying()==False`, so the `run()` drain condition was
unreachable — and its call target `self.player.start_channel()` does not
exist on PlaybackMonitor (it lives on SmartPlayer), so it would have
raised AttributeError anyway. The drain is removed. The hand-off now
happens in the new `PlaybackMonitor._maybe_start_block_reload()`, called
from `onPlayBackEnded` after the position increment: it rewrites the disk
queue (block items + unplayed tail), clears the pending flag, and calls
`SmartPlayer.start_channel()` from a short worker thread. `build_queue()`
resumes from the rewritten disk queue, so the block plays first and
regular content follows.

**Bug 4 — block completion tracking relocated:** the old completion call
site in `_check_now_playing` only appeared to work because Bug 1 left the
position tracking stale; with tracking restored it could never fire.
Natural block-item completions are now counted in `_handle_end` (which
also skips show/movie state advancement for block items — they belong to
the source channel), and block items skipped past by the user while the
block is playing are counted as consumed in the skip loop. Pre-reload
block items in the skip range are still ignored, as before.

**Behaviour changes:**
- A deliberate user stop now cancels the pending block reload instead of
  restarting playback; the block stays at the front of the disk queue and
  plays on the next channel open.
- Guard added so the addon's own post-reload queue rewrite cannot
  re-trigger the reload in a loop; a stale pending flag is cleared when a
  block item registers as playing.
- At the boundary, Kodi's auto-advance may briefly start the next regular
  episode before the block replaces it (sub-second, platform dependent).

**Files changed:** `service.py`, `addon.xml`, `CHANGELOG.md`, `README.md`

---

## Version 1.1.9o

### Fix — restore wait-for-episode-end before block starts

1.1.9n removed the `not self.player.isPlaying()` guard, causing the
block to cut mid-episode. Restored. The block waits for the current
episode to finish naturally before starting — the same behaviour as
all previous versions intended.

**Files changed:** `service.py`, `addon.xml`, `CHANGELOG.md`

---

## Version 1.1.9n

### Change — scheduled block fires immediately like a manual channel switch

The `_pending_block_reload` drain in `run()` previously waited for
`not self.player.isPlaying()` before calling `start_channel()`. This
meant the block could start up to 22 minutes late (one full episode
after the scheduled time), which is not acceptable for scheduled
programming.

**Fix:** removed the `not self.player.isPlaying()` guard. The drain
now fires on the next service tick after `_pending_block_reload` is
set — exactly like pressing play on a different channel manually.
The current episode stops and the first block item starts
immediately. The delay between the scheduled time and block start is
at most 60 seconds (one service tick).

**Files changed:** `service.py`, `addon.xml`, `CHANGELOG.md`

---

## Version 1.1.9m

### Fix — block items falsely detected as skipped, stripped from queue

When `fire_block()` wrote block items to the front of the target
queue while the channel was playing, `content_changed` reloaded
`self._queue` with the new 15-item queue (6 block items + 9 regular
items). `_check_now_playing` then scanned for the currently-playing
file — which was now at position 6 instead of 0. The skip detector
saw `new_position=6, last_position=0` and treated all 6 block items
as skipped episodes, advancing their state and then trimming the
queue to position 6 onward — discarding all block items from both
memory and the queue file.

**Two fixes:**

1. **Skip loop guard** — in the skip advancement loop, items tagged
   `_schedule_id` are ignored with a `continue`. They are not real
   skips; advancing their state would incorrectly mark source-channel
   episodes as played.

2. **content_changed block reload** — when `content_changed` fires
   and `self._queue[0]` has `_schedule_id` and the channel is
   playing, `_pending_block_reload` is set immediately and
   `self._current_file` is set to the currently-playing file. This
   causes `_check_now_playing` to return early (file already
   registered) without scanning the new queue, preventing the false
   skip detection entirely. The block starts playing at the next
   natural item boundary when `_pending_block_reload` drains.

**Expected log sequence after this fix:**
1. `fire_block: target queue 9 -> 15 items`
2. `Queue file content changed`
3. `content_changed: scheduled block at queue[0] — pending reload`
4. (current episode plays to natural end)
5. `_handle_end: scheduled block detected at queue[0] — pending reload`
6. `run: starting block reload for channel '...'`
7. Block content starts playing seamlessly

**Files changed:** `service.py`, `addon.xml`, `CHANGELOG.md`

---

## Version 1.1.9l

### Fix — scheduled block never fires while target channel is playing

The 1.1.9k `_pending_block_reload` mechanism was correct but never
triggered because `fire_block()` was gated behind check 5: "is the
target channel currently playing? If so, defer." Since the channel
was always playing, `fire_block()` never ran, block items were never
written to the queue file, `self._queue[0]` never got `_schedule_id`,
and `_pending_block_reload` was never set.

**Root cause:** check 5 was added as a courtesy to avoid writing to
the queue file while playing — but `fire_block()` only writes to the
queue file on disk. It does not touch Kodi's in-memory playlist.
Writing to the queue file while the channel is playing is completely
safe: `content_changed` in `_check_now_playing` detects the change
on the next tick, reloads `self._queue` in memory with block items
at front, and `_handle_end` sets `_pending_block_reload` at the next
natural item boundary — exactly as designed.

**Fix:** removed check 5 entirely. `fire_block()` now always runs
when checks 1-4 pass, regardless of whether the target channel is
playing. The seamless block insertion path (Option C) in 1.1.9k then
handles the playlist swap at the next natural episode boundary.

**Expected log sequence after this fix:**
1. `all checks passed, firing block` — at 22:00 tick
2. `target queue 30 -> 34 items` — queue file updated on disk
3. `Queue file content changed` — detected within 1 second
4. (episode plays to natural end)
5. `scheduled block detected at queue[0] — pending reload`
6. `run: starting block reload for channel '...'`
7. Block content starts playing seamlessly

**Files changed:** `scheduler.py`, `addon.xml`, `CHANGELOG.md`

---

## Version 1.1.9k

### Fix — scheduled block items not playing when channel already active

When a schedule fired while the target channel was playing, block
items were correctly prepended to the queue file on disk but the
currently-running Kodi playlist was never updated. The channel
continued playing its original content, skipping the block entirely.
The user had to manually stop and restart the channel to see block
items.

**Root cause:** `content_changed` in `_check_now_playing` detects
queue file changes and reloads `self._queue` in memory, but does NOT
rebuild Kodi's in-memory playlist. Kodi plays through its own
playlist sequentially, never re-reading the queue file between items.

**Fix — Option C (seamless, no interruption):**

At the end of `_handle_end`, after all state advancement for the
finished item, a check runs: if the finished item was NOT a block
item (regular channel content) AND `self._queue[0]` now has
`_schedule_id` (block items are waiting at the front), set
`self._pending_block_reload` to the current channel dict.

In `run()`, after the `_pending_exhausted_channel` drain, when
`_pending_block_reload` is set and `not self.player.isPlaying()`,
`start_channel()` is called with the pending channel. At this point
the previous item has finished naturally so `start_channel()` starts
the block content from position 0 with no interruption to the user
— the current episode plays to its natural end, then scheduled
content begins.

**Regression guards:**
- Flag only set when `_queue[0]` has `_schedule_id` — never fires
  for normal channels with no schedule
- `_finished_is_block` guard prevents re-triggering after each
  block item completes — block items play through via existing path
- Drain only fires when `not isPlaying()` — never interrupts
  mid-episode
- Serial, carousel, folder, movie channels: unaffected (no
  `_schedule_id` on their items)

**Files changed:** `service.py`, `addon.xml`, `CHANGELOG.md`

---

## Version 1.1.9j

### Fix — soft-stop not enforced when user manually stops playback

When a scheduled block was active and the soft-stop time passed,
stopping playback manually (instead of letting the current item
finish naturally) left the remaining block items in the target queue
indefinitely. The soft-stop was only checked on natural item
transitions, not on user-initiated stops.

**Fix:** added a soft-stop check to `onPlayBackStopped` in
`service.py`. After the resume save logic, if a scheduled block is
active on the stopped channel AND `soft_stop_time` is set AND the
soft-stop time has been reached, `_strip_remaining_block_items()` is
called and the block is cleared — exactly as if the item had finished
naturally past the deadline.

Blocks without a soft-stop are left intact on manual stop so they
resume correctly on the next play. Only soft-stop blocks are cleared
on stop when the deadline has passed.

**Architecture note:** this hook is in `service.py` (owns all
playback callbacks). `_strip_remaining_block_items()` and
`clear_active_block()` are called on `scheduler.py` and
`channel_manager.py` respectively — no ownership rules violated.

**Files changed:** `service.py`, `addon.xml`, `CHANGELOG.md`

---

## Version 1.1.9i

### Fix — remaining block items not removed on soft-stop or early end

When a scheduled block ended early (soft-stop time reached, or
items_played < item_count for any other reason), the un-played block
items remained at the front of the target channel queue and continued
playing as if they were regular channel content.

**Root cause:** `on_block_item_complete()` cleared `active_block` from
state.json but did not touch the queue file. The remaining source items
sitting in the target queue had no mechanism to remove them.

**Fix:** when `block_done` is True and `items_played < item_count`,
`_strip_remaining_block_items()` is called before clearing the block
state. It walks the front of the target queue and removes any items
tagged `_schedule_id == schedule_id` (written by `fire_block` and
preserved through `_write_now_playing` since 1.1.9g). It stops at
the first untagged item so regular channel content is never affected.

Normal block completion (all items played) is unaffected — no items
remain to strip, so `remaining_block_items == 0` and the strip is
skipped.

**Files changed:** `scheduler.py`, `addon.xml`, `CHANGELOG.md`

---

## Version 1.1.9h

### Fix — stale active_block blocks schedule from re-firing

After editing a schedule's time (which resets last_fired to 0),
the scheduler correctly saw last_fired == 0 and attempted to fire —
but was blocked by an existing active_block key in state.json left
from a previous block that never got cleared (pre-1.1.9f behavior).
The `block already active` check fired and the schedule never ran.

Two staleness conditions are now detected and cleared before the
`block already active` guard blocks the fire:

1. **last_fired == 0**: the wizard reset it because a scheduling-
   relevant field changed. Any existing active_block is from a
   superseded config and should be discarded.

2. **inserted_at from a previous calendar day**: a real block cannot
   span midnight. If the block was inserted yesterday (e.g. after a
   crash or Kodi restart without block completion), it is abandoned
   and cleared so today's schedule can fire normally.

In both cases the stale block is cleared and the schedule proceeds
to fire. A log line confirms which staleness condition was detected.

**Files changed:** `scheduler.py`, `addon.xml`, `CHANGELOG.md`

---

## Version 1.1.9g

### Fix — editing schedule time blocked by same-day last_fired

After a schedule fired, editing it to move the start time forward
and waiting for the new time would show `already fired today` and
not re-fire. `last_fired` from the earlier fire was preserved
unchanged by the wizard, so `_already_fired_today()` blocked it.

Fix: in `schedule_wizard.py`, if the start time, day, or source
channel changes on edit, `last_fired` is reset to 0 in the saved
definition so the schedule can fire again at the new time. Edits
to name, item count, soft stop, or target channel alone do not
reset `last_fired`.

### Fix — block completion hook never fired (from 1.1.9f)

`_schedule_id` was stripped by `_write_now_playing()` field
whitelist, so `service.py` never saw it in `self._queue` and
`on_block_item_complete()` was never called. Fixed by preserving
`_schedule_id` in both the TV and movie branches of
`_write_now_playing()`.

**Files changed:** `ui/schedule_wizard.py`, `player.py`,
`addon.xml`, `CHANGELOG.md`

---

## Version 1.1.9f

### Fix — block completion hook never fired

When a scheduled block played, `on_block_item_complete()` was never
called and `active_block` was never cleared from state.json.

**Root cause:** `_write_now_playing()` in `player.py` normalizes every
queue item through a strict field whitelist before writing the queue
file to disk. `_schedule_id` was not in that whitelist, so it was
silently stripped when the channel started playing. `service.py`
populates `self._queue` by reading the queue file from disk, so
`self._queue` never had `_schedule_id` on any item. The block
completion check in `_check_now_playing` reads
`_prev_item.get("_schedule_id")` — always None — so the hook
never fired.

**Fix:** added `_schedule_id` preservation to both the TV episode
and movie branches of `_write_now_playing()`, following the same
conditional pattern used for `_interleaved` and `_silent`.

**Files changed:** `player.py`, `addon.xml`, `CHANGELOG.md`

---

## Version 1.1.9e

### Fix — scheduler.py bypassing channel_manager ownership rule

`fire_block()` was calling `channel_manager._save_json()` and accessing
`channel_manager._schedules_path` directly to update `last_fired` and
deactivate once-only schedules — bypassing the public `update_schedule()`
method that `channel_manager.py` already owns for all schedules.json I/O.

This violated the no-duplicate-code rule: `channel_manager.py` owns all
schedules.json reads and writes; nothing else should access that file
directly.

Fix: replaced the raw `_save_json` call with `channel_manager.update_schedule()`.
One method call replaces three lines of direct file access.

**Files changed:** `scheduler.py`, `addon.xml`, `CHANGELOG.md`

---

## Version 1.1.9d

### Diagnostic — add success log line to set_active_block

`set_active_block` had no success confirmation in the log — only an
error branch. Added a log line confirming the key written and the
`items_played`/`item_count` values so block state writes are visible
in kodi.log for debugging.

No logic changes. The `active_block` key in state.json was being
written correctly; the absence of a log line was purely an
observability gap.

**Files changed:** `channel_manager.py`, `addon.xml`, `CHANGELOG.md`

---

## Version 1.1.9c

### Fix — "Add Schedule" missing from Side Panel context menu

"Add Schedule" appeared in the standard channel list context menu
(via `ui/channels.py`) but not in the Side Panel context menu, which
maintains its own separate options list in `ui/side_panel.py`.

Fix: added `_S_CTX_ADD_SCHEDULE = 32686` constant, the entry to the
options list, and an `add_schedule` handler to `_show_context_menu()`.
The wizard runs directly on the panel thread (same pattern as
`edit_channel` and `manage_interleave`) so the panel stays open and
the schedule is saved without any RunPlugin round-trip.

**Files changed:** `ui/side_panel.py`, `addon.xml`, `CHANGELOG.md`

---

## Version 1.1.9b

### Fix — Schedule block items ignored on channel play

When a schedule fired and prepended source items to the target queue,
opening the Side Panel showed the block items correctly. But pressing
Play rebuilt the queue from scratch, ignoring the block items entirely
and playing the original target channel content.

**Root cause:** `_resume_from_existing_queue()` checks queue ownership
by reading `first_item.get("channel_id") or first_item.get("_channel_id")`.
`fire_block()` set `_channel_id = target_id` on block items but did not
set `channel_id` — which kept the source channel's ID from the original
item dict. The `or` expression short-circuits on the first truthy value,
so `channel_id` (source ID ≠ target ID) was read, the ownership check
failed, and `_resume_from_existing_queue()` returned `None`, forcing a
fresh queue build that discarded all block items.

**Fix:** `fire_block()` now sets both `channel_id` and `_channel_id` to
`target_id` on every block item. One line added in `scheduler.py`.

**Files changed:** `scheduler.py`, `addon.xml`, `CHANGELOG.md`

---

## Version 1.1.9a

### Feature — Channel Scheduling

Schedule a source channel's content to play on a target channel at a
recurring day/time.  Blocks play as the next N items on the target channel;
when the block finishes (or a soft-stop time is reached) the regular queue
resumes naturally.

**How it works:**

- **Soft-start:** the block fires at or after the configured start time
  but waits for the current item to finish before inserting.  The 60-second
  service tick defers firing while the target channel is active; the check
  runs again on the next tick after the item ends.
- **Soft-stop:** an optional wall-clock time after which the block ends
  early, even if `item_count` has not been consumed.
- **Block insertion:** source items are prepended to the target queue.
  Regular queue items are pushed back and play naturally after the block —
  no items are dropped or displaced.
- **Source channel advance:** source items consumed by the block are
  removed from the source queue, exactly as if they had been watched on
  the source channel directly.
- **Once-only:** schedules with recurrence `"once"` deactivate themselves
  automatically after firing.

**Schedule Wizard (8 steps):**

1. Schedule Name
2. Target Channel (pre-selected when opened from context menu)
3. Source Channel (target excluded from options)
4. Day — Daily / Weekdays / Weekends / Mon–Sun / Once
5. Start Time — HH:MM 24-hour input with format validation
6. Item Count — 1–50, default 4
7. Soft Stop Time — optional HH:MM; must be after start time
8. Confirm — summary dialog

**Manage Schedules screen:** Settings → Manage Schedules.
Lists all schedules with [ACTIVE]/[OFF] prefix.  Per-schedule actions:
Edit (re-runs wizard pre-filled), Toggle Active/Inactive, Delete.

**Conflict checking (at save time):**

1. Target channel: no two active schedules may overlap on the same day/time.
   Overlap window defaults to 2 hours when no soft-stop time is set.
2. Source channel: may only appear in one schedule at a time.

**Data model:**

- `schedules.json` — stored in addon profile / shared storage path.
  Absent = no schedules; all reads use `.get()` with safe defaults.
- `sch_<id>:active_block` key in `state.json` — tracks block progress
  across Kodi restarts.

**Architecture:**

- `resources/lib/scheduler.py` — NEW.  Mirrors `carousel.py` exactly.
  `ScheduleManager.check_all()` called every 60 s from service.py tick
  loop alongside carousel check.  Never writes queue files directly.
- `resources/lib/ui/schedule_wizard.py` — NEW.  Wizard + Manage screen.
- `channel_manager.py` — `schedules.json` CRUD, active_block state helpers,
  `SCHEDULES_FILE` constant, `_schedules_path` init.
- `service.py` — scheduler check in tick loop + startup catch-up;
  block item completion hook in `_check_now_playing`.
- `ui/channels.py` — "Add Schedule" context menu entry on every channel.
- `router.py` — `add_schedule`, `manage_schedules` actions.
- `addon.py` — dispatch table additions.
- `settings.xml` — "Manage Schedules" action button in Channels category.
- `strings.po` — #32686–#32726.

**Backwards compatibility:** schedules.json absent = no schedules.
Existing channels, queues, and state.json are unaffected until a schedule
fires.

**Files changed:** `scheduler.py` (NEW), `ui/schedule_wizard.py` (NEW),
`channel_manager.py`, `service.py`, `ui/channels.py`, `router.py`,
`addon.py`, `settings.xml`, `strings.po`, `addon.xml`, `CHANGELOG.md`,
`README.md`

---

## Version 1.1.8m

### Fix — Channel Logo Overlay: premature dismiss on OSD close

Logo disappeared when the user pressed Escape/Back to close the OSD.
Two causes fixed:

1. **`onPlayBackEnded` was calling `hide_permanent()`** — removed.
   The timed logo manages its own lifetime; hiding on natural episode
   end was wrong. When the next item starts, `show()` cancels and
   reshows automatically. `hide_permanent()` now only fires from
   `onPlayBackStopped`.

2. **`onPlayBackStopped` fires transiently on some Kodi builds** during
   OSD skip/seek interactions even though playback continues. Added
   `isPlaying()` guard: `hide_permanent()` only called when playback
   has actually stopped.

**Files changed:** `service.py`, `addon.xml`, `CHANGELOG.md`

---

## Version 1.1.8l

### Fix — Channel Logo Overlay: show on every new item, not just channel change

Logo was not appearing when the user skipped to the next episode because
`service.py` only called `show()` when `primary_channel_id` changed.
Skipping within the same channel doesn't change the channel ID.

Fix: removed `_logo_channel_id` tracking. `show()` is now called on
every `_check_now_playing` fire (every new item). The timed window
auto-dismisses after the configured duration, so there is no cost to
showing it on each item — it behaves exactly like Coming Up Next.

**Files changed:** `service.py`, `addon.xml`, `CHANGELOG.md`

---

## Version 1.1.8k

### Rework — Channel Logo Overlay: timed display (Coming Up Next pattern)

After extensive investigation including reading the PseudoTV source code,
the persistent `WindowDialog` approach cannot work in our architecture.
PseudoTV's channel bug works because their entire addon runs as a modal
`WindowXMLDialog` that owns the input loop — they intercept all keypresses
intentionally. Our addon runs as a background service alongside Kodi's
native player, so a persistent `WindowDialog` always sits on the input
stack and blocks keypresses regardless of what `onAction` does.

**New approach: timed display**, matching `coming_up_next.py` exactly:
- Logo appears for a configurable number of seconds when a channel starts
  or changes, then auto-dismisses
- No persistent window — gone before the user presses anything
- No input interception, no threading complexity, no close/reopen cycles
- New setting: **Display Duration (seconds)** — default 5s

**Settings (Channel Logo category):**
- Enable/disable, Corner, Size, Opacity, Margin (unchanged)
- NEW: Display Duration (seconds) — default 5

**strings.po:** #32685 added (Display Duration)

**Files changed:** `overlays/logo_overlay.py`, `settings.xml`,
`strings.po`, `addon.xml`, `CHANGELOG.md`

---

## Version 1.1.8j

### Fix — Channel Logo Overlay: diagnostic logging in service.py

Added log line `logo overlay: showing for channel=... icon=...` inside the
logo block in `_check_now_playing` so it is immediately visible in kodi.log
whether the block is reached and what icon is being shown.

The logo not appearing in 1.1.8i was caused by the `logo_overlay_enabled`
setting being reset to its default (`false`) when the addon was reinstalled
fresh. Re-enabling it in Settings → Channel Logo Overlay restores normal
behaviour. No code change required for that — this revision adds logging
so the same scenario is instantly diagnosable from the log in future.

**Files changed:** `service.py`, `addon.xml`, `CHANGELOG.md`

---

## Version 1.1.8i

### Fix — Channel Logo Overlay: self-contained reshow thread

**Root causes diagnosed from log:**

1. **Logo never returned** — `_check_now_playing` only fires when a new
   file is detected, not on a schedule. After a keypress-triggered hide,
   nothing called it again for the same still-playing file, so the logo
   never reshowed.

2. **Two presses for OSD** — the close-first approach had a race: by the
   time `executebuiltin("Action(Select)")` fired, the OSD activation was
   racing with the window close.

**Fix:** The overlay is now fully self-contained for input handling.

- New `_hide_for_keypress()` method: closes the window and starts a
  `threading.Timer` (600ms) that calls `_reshow()`.
- `_reshow()` calls `show()` with the last known icon and settings —
  no involvement from `service.py` required.
- New `hide_permanent()` replaces `hide()` for service.py calls
  (playback stop/ended). Sets `_permanent_hide = True` so the reshow
  timer cannot fire after playback stops.
- `show()` clears `_permanent_hide` so the logo correctly reappears
  when a new channel starts after a stop.
- `service.py`: removed `is_showing()` check (no longer needed),
  renamed `hide()` → `hide_permanent()` at stop/ended call sites.

**Expected behaviour:**
- Press Enter → logo disappears, OSD opens on first press, logo
  reappears ~600ms later when OSD is visible
- Press Escape → OSD closes, logo reappears ~600ms later
- Stop playback → logo disappears permanently

**Files changed:** `overlays/logo_overlay.py`, `service.py`,
`addon.xml`, `CHANGELOG.md`

---

## Version 1.1.8h

### Fix — Channel Logo Overlay: close-first input handling

The fundamental problem: `WindowDialog` sits on top of Kodi's window
stack and intercepts all input. `executebuiltin("Action(name)")` re-fires
the action but Kodi routes it back to the same window — an infinite loop.

Fix: `onAction` now calls `manager.hide()` first to remove the window
from the stack, then fires `executebuiltin("Action(name)")`. With the
window gone, the action reaches `VideoFullScreen` as intended. The OSD
opens, Stop works, Escape works.

`service.py` reshows the logo on the next `_check_now_playing` tick
(within ~1 second) via an `is_showing()` check alongside the existing
channel-change check. The logo reappears seamlessly after the OSD closes.

**Files changed:** `overlays/logo_overlay.py`, `service.py`,
`addon.xml`, `CHANGELOG.md`

---

## Version 1.1.8g

### Fix — Channel Logo Overlay: correct action name strings for executebuiltin

1.1.8f called `xbmc.executebuiltin("Action({})".format(action.getId()))` which
passed the raw integer ID (e.g. `Action(7)`, `Action(10)`). Kodi's `Action()`
builtin requires the action **name string** (e.g. `Action(Select)`,
`Action(PreviousMenu)`), not the numeric ID, producing:
`Keymapping error: no such action '7' defined` for every keypress.

Fixed by mapping the numeric IDs to their correct name strings for all
actions a user is likely to press during video playback (Select, Stop,
PlayPause, FastForward, Rewind, PreviousMenu, OSD, ShowInfo, etc.).
Unmapped action IDs are silently ignored — the video player handles its
own input independently for those.

**Files changed:** `overlays/logo_overlay.py`, `addon.xml`, `CHANGELOG.md`

---

## Version 1.1.8f

### Fix — Channel Logo Overlay: action forwarding corrected

1.1.8e used `pass` in `onAction` which silently swallowed all keypresses
including Back and Escape, making it impossible to stop playback or open
the OSD.

The correct fix is `xbmc.executebuiltin("Action({})".format(action.getId()))` —
this re-fires every received action back into Kodi's normal routing so the
video player underneath handles it as if the overlay wasn't there. Enter/OK
opens the OSD, Back/Escape works normally, and the logo stays on screen
until service.py dismisses it on playback stop.

**Files changed:** `overlays/logo_overlay.py`, `addon.xml`, `CHANGELOG.md`

---

## Version 1.1.8e

### Fix — Channel Logo Overlay: no longer intercepts keypresses

`LogoOverlayWindow` now overrides `onAction` and `onClick` with no-ops.
Previously the `WindowDialog` default handler silently absorbed all
keypresses — Enter/OK could not open the Kodi OSD, and Back/Escape was
required to dismiss the overlay before any remote input worked.

The overlay is now fully transparent to input: Enter opens the Kodi OSD
normally, Back/Escape works as expected, and the logo stays on screen
until playback stops as intended. The overlay is dismissed only by
`service.py` on `onPlayBackStopped`/`onPlayBackEnded` — never by user
input.

**Files changed:** `overlays/logo_overlay.py`, `addon.xml`, `CHANGELOG.md`

---

## Version 1.1.8d

### Feature — Channel Logo Overlay (persistent watermark during playback)

Displays the channel's icon as a persistent semi-transparent watermark
in a configurable corner of the screen while content is playing. Behaves
like a real broadcast channel bug.

**Behaviour:**
- Appears when a channel starts playing, stays for the entire item
- Refreshes automatically when the channel changes (e.g. after a channel
  switch — same overlay instance, new icon)
- Hidden cleanly on playback stop or Kodi shutdown — no lingering windows
- If the channel has no icon configured and no auto-match in the icon
  folder, the overlay does not appear (no generic placeholder shown)
- No effect on playback, resume, queue, or any other feature

**Settings (new "Channel Logo" category):**
- Enable/disable
- Corner: Top Left / Top Right (default) / Bottom Left / Bottom Right
- Size: Small (60px) / Medium (80px) / Large (100px) — default Medium
- Opacity: Low (50%) / Medium (70%) / High (90%) — default Medium
- Margin from screen edge (number, pixels, default 30)

**Architecture:**
- `overlays/logo_overlay.py` — NEW. Self-contained `xbmcgui.WindowDialog`,
  no XML skin required. Owns all rendering. Never accesses state/queue.
- `service.py` — show overlay after `set_now_playing` when channel icon
  changes; hide on `onPlayBackStopped`/`onPlayBackEnded`
- `channel_manager.resolve_channel_icon` already provides the icon path

**Strings:** #32676–#32684 (next free: #32685)

**Files changed:** `overlays/logo_overlay.py` (NEW), `service.py`,
`settings.xml`, `strings.po`, `addon.xml`, `CHANGELOG.md`

---

## Version 1.1.8c

### Fix — Channel icon folder: UNC path support + diagnostic logging

**UNC path normalisation:**
- Icon folder paths entered as `\\Server\share\path` are now converted
  to `smb://Server/share/path` before being passed to `xbmcvfs`, which
  requires Kodi VFS protocol format. Previously, UNC paths silently
  failed all existence checks and fell through to the default icon.

**Diagnostic logging added to `resolve_channel_icon`:**
- Logs which resolution path was taken for every channel (manual icon,
  folder match, or fallback) so icon problems are visible in kodi.log
  without needing to instrument the code manually.

**Files changed:** `resources/lib/channel_manager.py`, `addon.xml`,
`CHANGELOG.md`

---

## Version 1.1.8b

### Fix — Lower Third Ticker polish (layout, logging, item ordering, repetition)

**Layout:**
- Strip height increased 96→116px; top position adjusted (1080i: top=932)
- Font sizes increased: phrase → font16, title → font20
- Colors brightened: phrase → gold `FFFFD700`, title → white `FFFFFFFF`
- Label widths widened to prevent truncation (phrase 900px, title 1350px)

**Channel name moved to phrase line (402):**
- Channel name no longer pinned hard-right in control 404 (always blank now)
- For next-item entries: "Up Next on — Comedy TV" on line 1, title on line 2
- For promo entries with `{channel}` in template: "Comedy TV presents" on
  line 1, title on line 2
- For promo entries without `{channel}`: "Catch it on — Comedy TV" on line 1

**No repetition:**
- `{show}` token stripped from phrase line — title lives exclusively in 403
- `{channel}` token substituted in phrase line — 404 always empty
- Show/movie title never appears in both the phrase and the title line

**Logging:**
- Each ticker item logged at build time: `#N | phrase_line | title`

**Item ordering:**
- Next-item and promo entries interleaved per channel before shuffle

**Files changed:** `ui/side_panel.py`, `addon.xml`, `CHANGELOG.md`

---

## Version 1.1.8a

### Fix — Lower Third Ticker polish (layout, logging, item ordering)

**Layout:**
- Strip height increased 96→116px; top position adjusted accordingly (1080i: top=932)
- Phrase label (402) and title label (403) now display on one compound line each,
  with wider widths to prevent truncation
- Font sizes increased: phrase → font16, title → font20, channel name → font16
- Colors brightened: phrase → gold `FFFFD700`, title → white `FFFFFFFF`,
  channel name → cyan `FF00CCFF`
- Left pane and right pane list heights adjusted for new strip height (1080i: 862)

**Logging:**
- Each ticker item now logged at build time:
  `[Ticker] #N channel — phrase — title` for instant diagnosis

**Item ordering:**
- Next-item and show-promo entries are now interleaved per channel
  (next-item first, then promo) before the full list is shuffled.
  Prevents two entries for the same channel appearing adjacent with
  contradictory content titles.

**Files changed:** `ui/side_panel.py`,
`resources/skins/Default/1080i/SmartChannels_Main.xml`,
`resources/skins/skin.estuary/1080i/SmartChannels_Main.xml`,
`addon.xml`, `CHANGELOG.md`

---

## Version 1.1.8a

### Feature — Lower Third Ticker in Side Panel

Adds a broadcast-style ticker strip at the bottom of the Side Panel window
advertising upcoming content across all visible channels.

**Ticker strip (control 400–404):**
- Appears at the bottom of the side panel, above the footer hint bar
- Dark semi-transparent background with a thin separator line above
- Shows: channel icon (401), phrase label (402), content title (403),
  channel name (404)
- Rotates through all visible channels every 8 seconds
- Background thread started in `onInit`, stopped cleanly in `onAction`
  (Back/Escape) — no thread leaks

**Two item types per channel:**
- **Next-item**: advertises the next queued item (item[0] from queue file)
  using a randomly chosen "next" phrase from `ticker_phrases.txt`
- **Show promo**: advertises a random show/movie from the channel's own
  configured content list using a randomly chosen "promo" phrase

**Currently-playing channel** always shows "Now Playing on" — never a
random phrase, always factually accurate.

**Phrase file** (`ticker_phrases.txt` in addon profile / shared storage):
- User-editable plain text file, one phrase per line
- `[next]` section: phrases for next-item entries
- `[promo]` section: phrases for show-promo entries (`{show}`, `{channel}`
  tokens substituted at runtime)
- `#` lines are comments; empty lines ignored
- Created with sensible defaults on first panel open if absent

**Settings:**
- New toggle: "Show Ticker" (default: true) — hides the strip and
  frees list height when disabled

**Layout changes (all three skins):**
- 1080i (Default, Estuary): list heights reduced 1010→882, right list
  948→820; ticker at top=952 height=96
- 720p (Confluence): list heights reduced 648→584, right list 604→540;
  ticker at top=634 height=64

**Strings:** #32672–#32675 (next free: #32676)

**Files changed:** `ui/side_panel.py`, `resources/skins/Default/1080i/SmartChannels_Main.xml`,
`resources/skins/skin.estuary/1080i/SmartChannels_Main.xml`,
`resources/skins/skin.confluence/720p/SmartChannels_Main.xml`,
`settings.xml`, `strings.po`, `addon.xml`, `CHANGELOG.md`, `README.md`

---

## Version 1.1.7d

### Fix — multi-episode NFO files parsed as invalid XML, duration skipped

Sonarr/Radarr writes multi-episode NFO files containing two consecutive
`<episodedetails>` root elements in a single file (one per episode on the
physical media). This is technically invalid XML — `ET.fromstring()` parses
the first element successfully then throws `junk after document element`
when it encounters the second, causing `_read_nfo_duration` to return 0
and the episode to be skipped from the queue entirely.

Fix: if the initial parse fails, strip the XML declaration, wrap the full
content in a synthetic `<_root>` element, and retry. Both `<episodedetails>`
blocks become valid children. `find(".//durationinseconds")` then locates
the duration from the first episode (correct, since both episodes share the
same physical file and duration). Single-element NFOs continue to parse on
the first attempt with no change in behaviour.

**Files changed:** `utils/duration_cache.py`, `addon.xml`, `CHANGELOG.md`

---

## Version 1.1.7c

### Fix — missing_durations.txt not written; episode detail missing from context menu

Two bugs in `record_missing_duration()` in `channel_manager.py`:

1. `xbmcvfs.File` does not support append mode (`"a"`). The write to
   `missing_durations.txt` was silently failing on all platforms, so the
   file was never created. Fixed by reading existing content first, then
   writing the full file back with the new line appended.

2. The `_topup_queue` call site passed empty `title`, `season=0`,
   `episode=0` to `record_missing_duration` because those fields were
   not captured before `_normalize_ep` overwrote the `ep` variable.
   The context menu therefore showed only the show name repeated for
   every skipped entry. Fixed by snapshotting `ep_title`, `ep_season`,
   `ep_ep`, `ep_show` before calling `_normalize_ep`, matching the
   pattern already used in `_build_fresh_queue`.

**Files changed:** `channel_manager.py`, `addon.xml`, `CHANGELOG.md`

---

## Version 1.1.7b

### Fix — duration field stripped from queue file at play time

`_write_now_playing()` in `player.py` rebuilds each queue item as a
minimal dict before writing `queue_{channel_id}.json`. The TV episode
branch did not include the `duration` field in this dict, so when
service.py loaded the file into `self._queue` at play time, all TV
episode items had no duration. The side panel showed durations correctly
from the pregenerated file (read directly from disk), but once playback
started the in-memory queue and the rewritten queue file lost the field.

Fix: `duration` is now unconditionally included in the TV/folder entry
dict (defaulting to 0 for pre-1.1.7a items with no field, matching the
backwards-compat contract). `duration_is_default` is also preserved for
folder items that are still using the estimated duration so that
`capture_folder_duration()` in service.py fires correctly after first
playback.

**Files changed:** `player.py`, `addon.xml`, `CHANGELOG.md`

---

## Version 1.1.7a

### Duration Cache — NFO-based episode and movie durations

Every queue item now carries a `duration` field (integer seconds).
Duration is read from the companion NFO file at the moment each item
is placed in the queue. Items with no readable duration are skipped.

**TV episodes and movies:**
- Duration read from `fileinfo/streamdetails/video/durationinseconds`
  in the NFO file sitting alongside the video file (same base name,
  .nfo extension). This is the same NFO written by Sonarr and Radarr.
- Movies use the `runtime` field from the local library cache (already
  available via JSON-RPC at library build time).
- Items with missing NFO, missing duration element, or parse errors
  are skipped from the queue. The skip is recorded per-channel in
  state.json and appended to `missing_durations.txt` in the addon
  profile folder.

**Folder channel items:**
- Duration read from companion NFO if it exists (written by this addon
  after first playback).
- If no companion NFO: item uses the user-configured default duration
  (Settings → Default Folder Item Duration, default 20 minutes).
  Folder items are never skipped — default fills the gap.
- After first playback, service.py captures getTotalTime(), passes it
  to channel_manager.capture_folder_duration() which writes a companion
  NFO alongside the video file and updates the queue item in place.
  Over time, all folder items accumulate real durations organically.

**Missing Durations context menu:**
- A "Missing Durations (N)" entry appears on any channel that has
  skipped items. Hidden when count == 0.
- Opens a scrollable dialog listing each skipped item with show,
  episode label, and file path.
- "Clear Missing Durations List" option (with confirmation) clears the
  per-channel list. Does not clear missing_durations.txt.

**Side panel duration display:**
- Each upcoming item in the right pane now shows duration in label2:
  - TV: "S03E04 — The Dog · 23 min"
  - Movie: "1990 · 1 hr 58 min"
  - Folder: "42 sec" (or "20 min" if using default)
- Pre-1.1.7a queue items have no duration field; they show no duration
  hint and are not skipped retroactively. Queues self-heal as content
  rotates through and gets rebuilt with durations.

**New setting:** Default Folder Item Duration (minutes) — default 20.

**New strings:** #32667–#32671

**New file:** `resources/lib/utils/duration_cache.py`

**Files changed:** `utils/duration_cache.py` (new), `channels/base.py`,
`channels/serial.py`, `channels/folder.py`, `channel_manager.py`,
`service.py`, `ui/channels.py`, `ui/side_panel.py`, `router.py`,
`addon.py`, `settings.xml`, `strings.po`, `addon.xml`, `CHANGELOG.md`,
`README.md`, `SPEC_1_1_7a_Duration_Cache.md`

**Backwards compatible:** existing queue items load without error.
All duration reads use `item.get("duration", 0)`.

---

## Version 1.1.6r

### Fix — stale resume/carousel comments corrected
- carousel.py docstring incorrectly stated "no catching up, no resume"
  and "service.py _do_resume_check skips resume when carousel_enabled=True".
  Neither was true — resume works normally on carousel channels while
  watching. When the carousel timer fires and pops an item, the saved
  resume position for that item is cleared at pop time via
  clear_resume_position(). The docstring now accurately describes this.
- No code logic changed — documentation only.
- Files changed: `carousel.py`, `addon.xml`, `CHANGELOG.md`

---

## Version 1.1.6q

### Fix — play button showing empty box glyph
- The ▶ Unicode triangle in string #32648 was rendering as [] on Windows/
  Estuary because the skin font doesn't include that glyph.
- Replaced with plain ASCII "> Play" which renders correctly everywhere.
- Files changed: `strings.po`, `addon.xml`, `CHANGELOG.md`

---

## Version 1.1.6p

### Play button — channel icon and channel name
- The ▶ Play row at the top of the right pane now shows the channel's own
  icon/logo in the poster slot (thumb) instead of the generic Kodi projector.
- label2 now shows the channel name, so the row reads:
    [channel icon]  ▶  Play
                    {Channel Name}
- String #32648 updated from "▶  Play Channel" to "▶  Play" since the
  channel name is now supplied dynamically as label2.
- Files changed: `ui/side_panel.py`, `strings.po`, `addon.xml`, `CHANGELOG.md`
- No other changes.

---

## Version 1.1.6o

### Fix — TV episode posters not showing
- Queue items store the show ID as `show_id` / `_show_id`, not `tvshowid`.
  The poster lookup was using `item.get("tvshowid")` which always returned
  -1 and never matched. Fixed to use `show_id` with `_show_id` fallback.

### Right pane — portrait posters and larger layout
- Poster image changed from landscape (120×72) to portrait (60×90) to match
  the natural 2:3 aspect ratio of movie/show poster art (1080i skins).
- Row height increased 88→120px; title font bumped font16→font20; label
  positions adjusted to clear the narrower portrait poster.
- Confluence 720p skin scaled proportionally: 64→84px rows, 80×52→44×66
  poster, font13→font16 title.
- Files changed: `ui/side_panel.py`, all three `SmartChannels_Main.xml`,
  `addon.xml`, `CHANGELOG.md`
- No changes to: `library.py`, `channel_manager.py`, `ui/channels.py`,
  `service.py`, `player.py`, `router.py`, `strings.po`, queue files

---

## Version 1.1.6n

### Show/movie poster thumbnails in side panel right pane
- The right pane upcoming list previously showed Kodi's generic projector
  icon for every item because queue items deliberately omit art/thumbnail
  fields to keep queue files small.
- Added "art" property to VideoLibrary.GetTVShows and VideoLibrary.GetMovies
  in build_local_cache(). Each show and movie now stores a "poster" field
  (art.poster) in local_library.json.
- _populate_panel() builds two in-memory dicts ({tvshowid: poster_url} and
  {movieid: poster_url}) once per panel open from the already-cached library
  data — no RPC calls per item.
- _format_queue_item() now resolves thumb from those dicts: show poster for
  TV episodes, movie poster for movies, falls back to item thumbnail then
  empty (which shows DefaultVideo.png fallback in the XML).
- Folder channel items are unaffected (no tvshowid/movieid).
- **Requires one library cache rebuild** (Settings → Refresh Library) after
  installing, so the new poster field is populated in local_library.json.
- Files changed: `library.py`, `ui/side_panel.py`, `addon.xml`, `CHANGELOG.md`
- No changes to: `channel_manager.py`, `ui/channels.py`, `service.py`,
  `player.py`, `router.py`, `strings.po`, queue files, state.json

---

## Version 1.1.6m

### Fix — channel rename and icon change require addon restart
- Edit channel and manage interleave now call the wizard directly on the
  side panel thread instead of via RunPlugin. RunPlugin fires a separate
  Python invoker and returns immediately; the side panel's ChannelManager
  instance never saw the disk changes, so the old name/icon persisted
  until the addon was re-entered.
- Added `ChannelManager.reload_channels()` — re-reads channels.json from
  disk. Called after any operation that runs in a separate invoker
  (set_channel_icon).
- The set_channel_icon refresh now also calls reload_channels() so the
  new icon is visible immediately without re-entering the addon.

### Channel list — larger icons and channel name text
- All three skin XMLs updated: item row height 72→96 (1080i) / 56→72 (720p),
  icon 48×48→72×72 (1080i) / 36×36→54×54 (720p), channel name font
  font16→font20 (1080i) / font13→font16 (720p), label left position
  adjusted to match new icon width.
- Files changed: `channel_manager.py`, `ui/side_panel.py`,
  `resources/skins/*/SmartChannels_Main.xml`, `addon.xml`, `CHANGELOG.md`
- No changes to: `ui/channels.py`, `service.py`, `player.py`, `router.py`,
  `library.py`, `strings.po`, queue files, state.json

---

## Version 1.1.6l

### Bug fix — channel list crash on open (1.1.6k regression)
- `resolve_channel_icon()` referenced `self._addon` but `ChannelManager`
  stores the addon instance as `self.addon` (no underscore). This caused
  an AttributeError on every channel list render, producing a black screen.
- Fixed: `self._addon` → `self.addon`.
- Files changed: `channel_manager.py`, `addon.xml`, `CHANGELOG.md`

---

## Version 1.1.6k

### Channel Icons for Side Panel and Channel List
- New setting: "Channel Icon Folder" — point to a folder of image files
  (.png / .jpg / .jpeg). Channels whose name matches a filename (without
  extension, case-insensitive) are assigned that image as their icon
  automatically, on every list render.
- New context menu option "Set Channel Icon" on every channel (both the
  standard channel list and the side panel). Opens Kodi's file browser
  to select an image. The chosen path is saved as `icon_path` in
  channels.json.
- "Set Channel Icon" also offers "Clear Icon" to remove the manual
  assignment and revert to auto-match or the built-in fallback.
- Icon resolution priority: (1) manual icon_path, (2) icon folder
  name-match, (3) DefaultVideoPlaylists.png Kodi built-in fallback.
- All hardcoded DefaultVideoPlaylists.png references in ui/channels.py
  and ui/side_panel.py removed — all icon resolution now goes through
  channel_manager.resolve_channel_icon() as a single source of truth.
- New strings: #32664 (Channel Icon Folder), #32665 (Set Channel Icon),
  #32666 (Clear Icon).
- Files changed: `channel_manager.py`, `ui/channels.py`,
  `ui/side_panel.py`, `router.py`, `addon.py`, `settings.xml`,
  `strings.po`, `addon.xml`, `CHANGELOG.md`
- No changes to: `service.py`, `player.py`, `library.py`, queue files,
  state.json, carousel, interleave, resume

---

## Version 1.1.6j

### Remove redundant Genre/Year pickers from movie channel wizard
- The Movie Selection Method dialog previously offered 4 options: All Movies,
  Filter by Genre, Filter by Year, and Select Specific Movies. The Genre and
  Year options were redundant with the Step 3b filter rules system, which does
  the same thing but better: it applies dynamically at every queue build against
  the live library (new additions are picked up automatically), supports multiple
  rules with AND/OR operators, and covers more filter types (MPAA, Studio, Rating).
- Movie Selection Method now offers only 2 options: All Movies and Select
  Specific Movies. Genre/year filtering is done exclusively via Step 3b filter
  rules.
- Channel Info now shows every Step 3b filter rule individually (one line per
  rule with operator prefix and comparison) instead of the generic "Filters: Yes".
- Removed filter_type and filter_value from wizard, channel_manager, and
  channel_info — these were introduced in 1.1.6g–1.1.6i and are no longer needed.
- Retired strings: #32423, #32424, #32426, #32428–32433, #32661–32663 (IDs
  preserved, msgid blanked per Kodi repo convention). #32427 ("Select Genre")
  retained — still used by the Step 3b filter rule builder.
- Files changed: `ui/channels.py`, `channel_manager.py`, `strings.po`,
  `addon.xml`, `CHANGELOG.md`
- No changes to: `service.py`, `player.py`, `library.py`, queue files, state.json

---

## Version 1.1.6i

### Bug fix — Channel Info only showed one filter rule
- The Step 3b `filters` list supports multiple rules (e.g. Genre = Action
  OR Genre = Comedy), but Channel Info was only reading `filter_type`/
  `filter_value` which captured only the Step 3 quick-picker (one value).
- Channel Info now iterates the full `filters` list and shows one indented
  line per rule with its operator prefix (AND/OR) and comparison symbol,
  matching the summary format used inside `_build_filters`.
- The Step 3 quick-picker label (`filter_type`) still shows first when
  present (By Genre / By Year / Manual selection method line).
- Files changed: `ui/channels.py`, `addon.xml`, `CHANGELOG.md`
- No changes to: `channel_manager.py`, `service.py`, `player.py`,
  `library.py`, `strings.po`, queue files, state.json

---

## Version 1.1.6h

### Bug fix — filter_type/filter_value not persisted to channels.json
- `add_channel` and `update_channel` in `channel_manager.py` were not
  whitelisting the new `filter_type` and `filter_value` keys, so they
  were silently dropped when saving. Channel Info therefore always saw
  `None` for both fields and showed no filter label.
- Fixed by adding both keys to the definition dicts in both methods.
- Files changed: `channel_manager.py`, `addon.xml`, `CHANGELOG.md`
- No changes to: `ui/channels.py`, `service.py`, `player.py`,
  `library.py`, `strings.po`, queue files, state.json

---

## Version 1.1.6g

### Movie Channel Filter Persistence
- `filter_type` and `filter_value` are now saved to `channels.json` when creating or editing a movie channel (values: `"all"`, `"genre"`, `"year"`, `"manual"`)
- Channel Info now displays a specific filter label instead of the generic "Filters: Yes":
  - By Genre: "Filter: By Genre — Comedy" (or chosen genre)
  - By Year: "Filter: By Year — 2022" (or chosen year)
  - Manual: "Filter: Manual selection"
  - All Movies / old channels without filter_type: no filter line shown
- Edit wizard pre-highlights the previously chosen filter type in the Movie Selection Method dialog
- Edit wizard pre-highlights the previously chosen genre or year in the sub-picker
- 3 new strings: #32661, #32662, #32663
- Files changed: `resources/lib/ui/channels.py`, `resources/language/resource.language.en_gb/strings.po`, `addon.xml`, `CHANGELOG.md`
- No changes to: `service.py`, `player.py`, `channel_manager.py`, `library.py`, queue files, state.json, interleave, carousel, resume

---

## Version 1.1.6f
- Fix: Create New Channel and Auto-Create Channels settings action buttons
  silently did nothing when pressed. Root cause: Kodi requires every
  RunPlugin invocation to resolve its plugin handle via endOfDirectory()
  — if the handle is left unresolved, Kodi silently aborts the action.
  Backup/Restore/Delete worked because they use only xbmcgui.Dialog()
  calls and never need the handle resolved. Create and Auto-Create use
  multi-step wizards that Kodi expects to either produce a directory
  listing or signal failure. Fix: call
  xbmcplugin.endOfDirectory(self.handle, succeeded=False) at the start
  of create_channel() and auto_create_channels() in router.py before
  the wizard runs — handle is resolved immediately, wizard runs freely.
  Only router.py changed.

---

## Version 1.1.6e
- Fix (issue 2): Context menu race condition on reset_channel — now calls
  `manager.reset_channel()` directly (synchronous) instead of RunPlugin,
  so the right pane refreshes immediately with the rebuilt queue. No sleep
  or timing guesses.
- Fix (issue 2): channel_info and view_exclusions no longer try to refresh
  the panel — they just show a dialog, no panel state changes needed.
- Fix (issue 3): Edit channel / manage_interleave now relaunch the addon
  after the wizard completes so the user returns to the panel automatically
  instead of being left at Kodi Home.
- Fix (issue 4): Delete channel likewise relaunches the addon after
  deletion — panel reopens with the channel removed.
- Fix (issue 5): Empty channel list after last channel toggled hidden is
  now handled — right pane is cleared cleanly, no index underflow.
- Fix (issue 6): `_panel_focused` de-sync fixed — `onAction` now reads
  `getFocusId()` at the start of every action and uses it as ground truth,
  correcting any de-sync from mouse clicks or skin focus changes.
- Fix (issue 7): Show Hidden Channels setting now respected in side panel.
  `onInit` and `_refresh_after_list_change` read the setting and call
  `get_all_channels()` or `get_visible_channels()` accordingly. Hidden
  channels shown with `[H]` prefix, same as standard listing.
- Feature (user request): Reset Channel refreshes the right pane
  immediately in-panel — the episode list updates to S01E01 for all shows
  without closing or relaunching the panel.
- Fix: Edit channel / manage_interleave no longer close the panel and
  navigate to Home. Wizard dialogs (xbmcgui.Dialog) stack on top of the
  panel doModal() window cleanly. When the wizard completes or is
  cancelled, the panel refreshes both panes in place.
- Fix: Delete channel now calls manager.delete_channel() directly so the
  channel list refreshes immediately after confirmation. Focus moves to
  the previous channel after deletion.
- New helper methods: _refresh_panel(), _refresh_after_list_change().
- Only file changed: `resources/lib/ui/side_panel.py`.

---

## Version 1.1.6d
- Fix: Silent interleave items (bumpers/commercials) playing first when a
  channel is opened or resumed. Root cause: `_update_queue_file` in
  `service.py` wrote the queue to disk exactly as trimmed — if a silent
  item sat at position 0 after trimming, it became the first item played
  on next channel open. Same issue applied to `reorder_queue_from_item`
  in `channel_manager.py` when the side panel rotated the queue.

  Fix: New static method `ChannelManager._strip_leading_silents(queue)`
  walks from position 0, finds the first non-silent item, and moves all
  preceding silent items to the tail in their original order. The interleave
  cadence is preserved. Edge case: if all items are silent (empty channel),
  the queue is returned unchanged.

  Called in two places:
    - `channel_manager.py` `reorder_queue_from_item()` — after rotation,
      before writing to disk. Fixes side panel item selection.
    - `service.py` `_update_queue_file()` — before writing the trimmed
      queue to disk. Fixes normal playback channel open/resume.

  This fix also applies to 1.1.5r behaviour — confirmed by Mark that
  rolling back to 1.1.5r showed the same silent-first issue. This is a
  pre-existing bug now resolved for all channel types.

  No changes to state.json, queue building, or playback callbacks.
  The in-memory `self._queue` in service.py is unchanged — only the
  written queue file is reordered.

---

## Version 1.1.6c
- Fix: Side panel — wrong episode played when selecting from right pane on
  a channel with silent interleave. Root cause: `_play_from_item` was passed
  `idx - 1` (panel position) as the queue index, but the raw queue file
  contains silent items at their original positions, so panel index and raw
  queue index diverge whenever silents precede the selected item.
  Fix: `_populate_panel` now stamps `_raw_queue_index` (the item's actual
  position in the raw queue file) onto each `_panel_data` entry at build
  time. `onClick` reads `_raw_queue_index` from the item dict and passes it
  to `reorder_queue_from_item` — correct regardless of how many silent items
  are interspersed. A shallow item copy is made to avoid mutating the
  original queue item dict.

- Fix: Side panel — resume position for the previously queued episode not
  cleared when user selects a different episode from the right pane.
  `reorder_queue_from_item` in `channel_manager.py` now calls
  `clear_resume_position` for every item displaced from the front of the
  queue (positions 0..queue_index-1) before writing the rotated queue,
  matching the behaviour of forward-skipping in the Kodi playlist.

- Fix: Side panel — silent interleave items visible in the right pane
  upcoming list. `_populate_panel` now skips any item with `_silent: True`.
  Loop iterates the full queue until `n` visible items are collected,
  so silent items do not reduce the visible count below the configured
  Upcoming Programs setting.

- Fix: Side panel — Videos hub flash on open, on program selection, and
  after playback stops. `ActivateWindow(Home)` fires before
  `endOfDirectory(succeeded=False)` on open, and before `RunPlugin` on
  play, so Kodi always returns to Home rather than the Videos hub.

- Fix: Side panel — context menu restored. Action ID 117 caught in
  `onAction`; `Dialog().select()` shows full channel options identical
  to the standard listing context menu.

- Fix: Side panel — `open_channels` settings button now calls
  `Dialog.Close(all,true)` before `RunPlugin` to dismiss the Settings
  doModal() window before attempting to open the side panel doModal()
  window. Kodi cannot stack two doModal() calls.

- Fix: Side panel — `open_channels` audible alert removed by not calling
  `endOfDirectory` from a settings action context.

---

## Version 1.1.6b
- Fix: Flash of Kodi Videos hub on side panel open — `ActivateWindow(Home)`
  fires before `endOfDirectory(succeeded=False)` so Kodi has no Videos
  screen to flash back to.
- Fix: Flash of Kodi Videos hub when selecting a program to play — same
  `ActivateWindow(Home)` pattern applied in `_play_channel()` and
  `_play_from_item()` before `RunPlugin`.
- Fix: After playback stops, Kodi now returns to Home instead of the
  Videos hub, because Home was the active window when playback started.
- Fix: Context menu restored in side panel left pane — action ID 117
  (C key / Menu button) caught in `onAction`, shows `Dialog().select()`
  with full channel options: Channel Info, Play Channel, Edit Channel,
  Reset Channel, Delete Channel, Toggle Visibility, Manage Interleave,
  View Exclusions. Identical options to the standard channel list context
  menu. Destructive actions (edit, delete, interleave, toggle visibility)
  close the panel first; display-only actions (channel info, reset, view
  exclusions) keep the panel open and refresh the channel list.
- Feature: Settings → Channels → "Open Smart Channels" action button
  re-launches the addon channel browser from within Settings. Works for
  both side panel and standard listing modes.
- New string: #32660 "Open Smart Channels".
- New router action: `open_channels`.
- Next free string ID: #32661.

---

## Version 1.1.6a
- Feature: Channel Side Panel — optional two-pane browser replacing the
  standard Kodi channel list. Left pane shows all visible channels with
  queue depth subtitle. Right pane shows upcoming queue items for the
  highlighted channel, updated live as the user navigates.
  Toggle: Settings → Display → "Use Side Panel (experimental)" (default off).
  When off, the existing directory-listing view works exactly as before.

  Navigation:
    Up/Down in left pane moves channel selection and updates the right pane.
    Right arrow moves focus to the right pane (upcoming items).
    Left arrow returns focus to the channel list.
    Enter on a channel or "▶ Play Channel" plays from the queue front.
    Enter on a specific upcoming item reorders the queue so that item plays
    first; items before it are moved to the tail (not discarded). State
    advancement for bypassed items is handled by service.py's existing skip
    detection, identical to skipping in the Kodi playlist.
    Back/Escape closes the panel and returns to Kodi home.

  New files:
    resources/lib/ui/side_panel.py          — WindowXML subclass, all logic
    resources/skins/Default/1080i/SmartChannels_Main.xml    — any-skin fallback
    resources/skins/skin.estuary/1080i/SmartChannels_Main.xml  — Estuary
    resources/skins/skin.confluence/720p/SmartChannels_Main.xml — Confluence

  Changed files:
    resources/lib/channel_manager.py — new reorder_queue_from_item() method
    resources/lib/router.py          — new play_from_item() action + panel toggle
    addon.py                         — play_from_item dispatch entry
    resources/settings.xml           — use_side_panel bool setting (#32651)
    strings.po                       — #32648–#32653 (6 new strings)

  Next free string ID: #32654.

- Fix: "Set Episodes Per Slot?" dialog now defaults to "No, keep 1 each"
  (the more common choice) instead of "Yes, customise". Index check updated
  from `== 0` to `== 1` to match new order. No strings.po changes — existing
  string IDs #32257 and #32258 reused, order only.

- Improvement: Settings restructured — all management actions moved from
  the channel list into Settings categories:
    Channels (new)    — Create New Channel, Auto-Create Channels
    Cache             — Refresh Library Cache action added; read-only
                        "Library cache age" display field added (updated
                        at service startup and after every rebuild);
                        Manage Extra Folders removed (dead code)
    Advanced          — Delete All Addon Data action added;
                        "Show management items" setting removed
    Backup & Restore  — Backup Addon Data and Restore Addon Data
                        action buttons added
  Channel list is now channels-only. All addon management is via
  Settings (accessible from Kodi's standard addon context menu at
  all times, including when the side panel is active).
  Removed: manage_extra_folders() from router.py and addon.py;
           utils/extra_folders.py is retained but no longer called.
  New strings: #32654–#32659 (6 strings).
  Next free string ID: #32660.

---

## Version 1.1.5a
- Feature: Auto-Create Channels wizard (new file: resources/lib/ui/auto_channels.py).
  Accessible from the main screen as "Auto-Create Channels" directly below
  "Create New Channel". Queries the local library cache and automatically
  creates TV, Movie, and optionally interleaved channels grouped by Genre,
  Decade, Genre+Decade, or Studio/Network. Full 9-screen wizard:
  (1) Content type — TV / Movies / Both
  (2) Group by — Genre / Decade / Genre+Decade / Studio/Network
  (3) Minimum items threshold (default 5)
  (4) Settings confirmation — shows global defaults applied to all channels
  (5) Interleave option — only for Both + Genre/Decade grouping
  (6) Preview multiselect — above-threshold channels pre-selected,
      below-threshold shown but unchecked, already-existing channels
      shown locked/unchecked
  (7) Confirm — count of channels to create
  (8) Progress dialog during creation
  (9) Done — count created and skipped
  All channels created visible. Global default settings applied (queue size,
  recycle, rotation). Channels can be renamed or edited individually after
  creation. Name collision at creation time = skip + report in done dialog.
  Strings added: #32591–#32645 (55 strings). Next free ID: #32646.


## Version 1.1.5r
- Fix: Minimum of 0 was rejected by the wizard with "must be at least 1".
  Changed validation to allow 0, which now means "show all candidates in
  preview regardless of item count". Updated minimum prompt to read
  "Minimum items per channel (0 = show all)" and updated error message.
  Updated settings confirmation body to explain preview filtering behaviour.
  Files changed: auto_channels.py, strings.po.


## Version 1.1.5q
- UX: Auto-Create Channels preview screen no longer shows candidates below
  the minimum threshold. With large libraries (especially Studio grouping),
  hundreds of single-movie studios cluttered the preview requiring excessive
  scrolling. Below-minimum candidates are now filtered out in _build_candidates
  before the preview is shown. Exception: if minimum=0, all candidates are
  shown (user explicitly wants to see everything). Existing channels are
  always shown regardless of minimum. Only auto_channels.py changed.


## Version 1.1.5p
- Feature: Auto-Create Channels now shuffles the show order for both TV
  and TV+Movies channels before creating them. Shows were previously in
  alphanumeric order (from library cache), meaning the queue always rotated
  through shows in the same sequence. Shuffling happens at creation time
  so the preview list still shows shows in alphabetical order but the
  created channel has a randomised rotation. Only auto_channels.py changed.


## Version 1.1.5o
- Fix: Starting episode dialog still not appearing for TV+Movies interleaved
  channels. _make_interleaved_candidate stored channel_type=_CT_MOVIES so
  the has_tv check was False and the dialog was skipped. Fixed by storing
  channel_type=_CT_BOTH which correctly identifies the candidate as having
  TV content. Only auto_channels.py changed.


## Version 1.1.5n
- Fix: Starting episode dialog never appeared in Auto-Create TV+Movies
  channel because progress.create() was called before the select dialog,
  causing the progress dialog to block it. Fixed by moving progress.create()
  to after all pre-creation dialogs complete. Only auto_channels.py changed.


## Version 1.1.5m
- Feature: Auto-Create Channels now asks for starting episode preference
  (TV shows only) before creating channels: "Start from S01E01" or
  "Surprise Me!" (random episode per show). Movies are unaffected.
  Two new strings: #32646 "Starting Episodes", #32647 "Randomising
  starting episodes...". Files changed: auto_channels.py, strings.po.
- Fix: Deleting a channel now also deletes any invisible auto-companion
  channels that were created by Auto-Create Channels and are exclusively
  referenced by the deleted channel via interleave. Companions are
  identified by name prefix __auto__ and visible=False. Queue file, state
  keys, and channels.json entry are all cleaned up for the companion.
  Only channel_manager.py changed for this fix.


## Version 1.1.5l
- Fix: Auto-Create TV+Movies interleaved channel created movies as primary
  with TV interleaved in, which is backwards. Now creates TV as primary
  (visible) with an invisible companion movies channel as the interleave
  source. The companion channel is named __auto__<channel_name> and is
  marked visible=False so it never appears in the user's channel list.
  It exists purely as an interleave source. If the companion already exists
  (re-run of auto-create), it is reused rather than duplicated.
  Removed unused _find_tv_channel_id method.
  Only auto_channels.py changed.


## Version 1.1.5k
- Fix: Channel list not refreshed after Auto-Create Channels completed.
  Added Container.Refresh after successful creation so new channels appear
  immediately without requiring the user to back out and re-enter the list.
  Only auto_channels.py changed.


## Version 1.1.5j
- Fix: Auto-Create Channels failed to build queue for movie and interleaved
  channels (TC-7.3). _build_definition passed bare integer movie IDs in the
  movies field, but channel_manager expects dicts with movieid and title keys.
  The queue builder crashed with 'int object is not subscriptable' immediately
  after channel creation, leaving an empty queue. Fixed by building movie dicts
  instead of bare IDs in both the plain movies and interleaved paths.
- UX: Preview screen no longer pre-selects all qualifying channels. User must
  explicitly select which channels to create. Only auto_channels.py changed.


## Version 1.1.5i
- Fix: Refresh Library only cached movies after 1.1.5h. The GetTVShows
  JSONRPC call used "nbepisodes" as the property name for episode count,
  which is invalid — Kodi's API returns an error for unknown properties,
  _rpc() returns {} silently, and result.get("tvshows") yields an empty
  list. Fixed by using the correct property name "episode". The cached
  field is still stored as "nbepisodes" internally. Only library.py changed.


## Version 1.1.5h
- Fix: Auto-Create Channels wizard appeared to do nothing (TC-7.3). The
  wizard called _episode_count() which fetched full episode lists via
  JSONRPC for every show in the library (1573 shows) before showing the
  preview screen. This took 3+ minutes with no visible progress, causing
  users to think the wizard had failed. Fixed by adding nbepisodes to the
  local library cache (one extra field in the GetTVShows request during
  cache build) and reading from the cache in _episode_count() instead of
  making individual JSONRPC calls. The preview screen now appears in under
  1 second. A full episode fetch is retained as a fallback for shows where
  nbepisodes is absent (old cache). A Refresh Library is required after
  installing this build to populate nbepisodes in the cache.
  Files changed: library.py, resources/lib/ui/auto_channels.py.


## Version 1.1.5g
- Fix: Interleaved carousel top-up still broken after 1.1.5f. 1.1.5f passed
  pre_pop_real as queue_size to refill_queue, but refill_queue computes
  topup_size = queue_size - len(current_queue) where current_queue includes
  silents. For a 45-item queue (30 real + 15 silent) after popping 3 items
  the post-pop queue is 42, so topup_size = 30 - 42 = -12 → refill_queue
  returns immediately without adding anything.
  Fixed by bypassing refill_queue entirely for interleaved carousel top-ups.
  The new path: count real items remaining in new_queue, call _topup_queue
  directly for exactly (pre_pop_real - real_remaining) new real items, then
  call _apply_interleave on the new tail only to re-weave silents. This gives
  precise control over both the real-item count and the silent re-weave,
  and the queue total converges back to pre_pop_len after each pop.
  Non-interleaved channels are unchanged. Only carousel.py changed.


## Version 1.1.5f
- Fix: Interleaved carousel channel queue grew larger with every pop cycle
  (TC-6.3 on CH-TV-CAR-IL). Superseded by 1.1.5g.
  Only carousel.py changed.


## Version 1.1.5e
- Fix: Carousel top-up never fired for interleaved channels (TC-6.2).
  The top-up check compared len(new_queue) < queue_size (30), but an
  interleaved channel's queue is larger than queue_size (e.g. 45 items
  for a 30-item channel with 15 silent items woven in). The condition
  was always False so the queue drained permanently after each pop.
  Fixed by using the pre-pop queue length as the target instead of
  queue_size, so the check correctly detects that items were removed.
  Also: for interleaved channels the top-up now calls refill_queue
  (which re-weaves silent items) rather than _topup_queue (which adds
  real items only). A shallow channel copy with queue_size overridden
  to pre_pop_len is passed so refill_queue's target calculation is
  correct. Non-interleaved channels are unchanged.
  Only carousel.py changed.


## Version 1.1.5d
- Fix: "Keep current position" resumed from the wrong episode when adding a
  show to a channel whose per-show state key was absent (channel never played).
  1.1.5c seeded per-show state from the queue tail's indices, but tail indices
  record the END of the queue (next episode to append on top-up), not the
  front. After a carousel pop and top-up on a 30-item single-show channel, the
  tail index is ~32, placing the rebuild 30 episodes ahead of the queue front.
  Fixed by reading the queue file directly and using the first item for each
  existing show as next_episode_id — this is always the correct viewer-facing
  position regardless of tail state. Only applied when no explicit
  starting_points were set, so "Set Starting Points" and "Surprise Me!" are
  unaffected. Only channel_manager.py changed.

## Version 1.1.5c
- Fix: "Keep current position" ignored when adding a show to a channel that
  has never been played (or whose per-show state key is absent from state.json).
  Seeded per-show state from queue tail indices before rebuild. Superseded by
  1.1.5d (tail indices point to queue end, not front).
  Only channel_manager.py changed.


## Version 1.1.5b
- Fix: Queue rebuild incorrectly skipped when editing a channel's shows,
  movies, queue size, interleave, filters, or excluded movies (TC-1.3,
  TC-1.4, TC-1.5). The `_no_queue_change` guard in `update_channel`
  compared `definition` values against the already-mutated `channel` dict
  — because `channel.update()` runs before the guard, both sides of every
  comparison were identical, so the guard always fired. Fixed by snapshotting
  `old_shows`, `old_movies`, `old_queue_size`, `old_interleave`,
  `old_filters`, and `old_excluded_movies` before `channel.update()` and
  comparing against those snapshots. The same root cause as the
  `old_carousel_*` fix in 1.1.4g; the carousel fields were already
  snapshotted but the queue-affecting fields were not.
  Only `channel_manager.py` changed.


## Version 1.1.4o
- Feature: Carousel pop is now silent-item aware (Option A trailing sweep).
  Silent interleaved items (_silent=True) in the queue are swept for free
  and do not count against pop_count. The pop walks forward from position 0:
  silent items encountered before or between real items are swept as they
  are passed; after the last counted real item, any immediately-following
  silent items are also swept. The new queue always starts with a real
  program after every pop. Leading silent items at the front of the queue
  are swept before the first real item is counted.
- The old CAROUSEL_QUEUE_FLOOR constant is replaced as the primary guard
  by a dynamic clamp: pop_count is capped so at least
  get_replenishment_threshold() real items remain after the pop. This ties
  the safety margin to the existing refill threshold setting rather than
  a hardcoded constant. The top-up (1.1.4n) then immediately restores the
  queue to full depth.
- Only carousel.py changed.


## Version 1.1.4n
- Fix: Carousel post-pop top-up adding twice as many items as queue_size.
  The 1.1.4m fix called `refill_queue(channel, new_queue, target_size)`
  passing `queue_size` (e.g. 30) as the `threshold` argument. `refill_queue`
  computes its target as `max(threshold * 3, queue_size)` — a formula
  designed for playback-driven top-ups where threshold is a small refill
  threshold setting (e.g. 5). Passing 30 as threshold produced
  `max(90, 30) = 90` items instead of 30. Fixed by calling `_topup_queue`
  directly with the exact number of items needed (`target_size - len(new_queue)`),
  bypassing the threshold multiplier entirely. Only `carousel.py` changed.


## Version 1.1.4m
- Fix: Carousel channels not topping up their queue after pops while
  nobody is watching. The normal playback-driven top-up in service.py
  only fires during active episode advances. With carousel enabled,
  repeated pops while the channel is idle drain the queue down to the
  safety floor of 2 items where it sits indefinitely. Fixed by adding a
  top-up call inside `_maybe_pop` in `carousel.py` immediately after
  writing the popped queue: if the new queue length is below the
  channel's `queue_size`, `refill_queue` is called to restore it to
  full depth and the result is written back to disk. The top-up is
  wrapped in try/except so a failure does not abort the pop or the
  clock advance. Only `carousel.py` changed.


## Version 1.1.4l
- Fix: Resume position resurrected in state.json after being cleared by a
  carousel pop. `clear_resume_position` in `channel_manager.py` correctly
  deleted the key from disk via `_save_json`, but did not remove it from
  `self._state` in memory or add it to `_deleted_state_keys`. Any subsequent
  `_save_state` call performs a read-before-write merge (disk + self._state),
  which wrote the key straight back over the deletion. Fixed by also calling
  `self._state.pop(key, None)` and `self._deleted_state_keys.add(key)` after
  the disk write, so the merge can never resurrect it.


## Version 1.1.4k
- Fix: Queue file deleted after Kodi was closed while a carousel channel was
  playing. Root cause: 1.1.4j unconditionally cleared `_channel_id = None`
  in `onPlayBackStopped`. Kodi fires `onPlayBackStopped` during its own
  shutdown sequence, which cleared `_channel_id` before the service loop
  exited — corrupting state for any subsequent exhaustion check or cleanup
  that needed the channel id. Fixed by guarding the `_channel_id` clear with
  `svc.abortRequested()`: during a genuine user stop (not shutdown) the id
  is cleared so carousel resumes normally; during Kodi shutdown the id is
  preserved so teardown code sees the correct value.


## Version 1.1.4j
- Fix: Carousel continued skipping a channel as "currently playing" after
  playback was stopped. `_channel_id` on `PlaybackMonitor` was set by
  `set_now_playing()` on playback start but never cleared on stop, so
  `check_all()` in `carousel.py` permanently excluded that channel for
  the rest of the Kodi session once it had been played. Fixed by clearing
  `_channel_id = None` inside the existing lock block in `onPlayBackStopped`,
  alongside `_current_ep` and `_current_file`. One line change in `service.py`.


## Version 1.1.4i
- Feature: Channel Info now shows carousel status for TV and Movie channels:
  interval, items-per-pop, and time until next pop (or "not yet initialised"
  if the clock has not started).
- Feature: Channel Info now shows excluded-episode counts per show (TV channels)
  and excluded-movie count (Movie channels) inline in the summary.
- Feature: New "View Exclusions" context menu item on TV, Serial, and Movie
  channels. Opens a scrollable textviewer listing every excluded episode
  (S##E## - Title, grouped by show) and every excluded movie by title.
  Shows "No exclusions are set" if none exist. Folder channels omitted —
  they have no per-item exclusion concept.
- Strings added: #32578–#32590 (13 strings). Next free ID: #32591.


## Version 1.1.4h
- Fix: `_no_queue_change` guard in `update_channel` did not check `filters`
  or `excluded_movies`. On a Movie carousel channel, editing only those fields
  would incorrectly skip the queue rebuild, leaving the queue containing movies
  that no longer matched the updated filters or exclusions. Both fields are now
  included in the guard so any change to them correctly triggers a rebuild.


## Version 1.1.4g
- Fix: Carousel-only channel edit triggered a full queue rebuild, re-adding
  episodes the carousel had already popped from the front of the queue.
  Root cause: two bugs in `update_channel` in `channel_manager.py`:
  (1) `old_carousel_*` values were snapshotted after `channel.update()` had
  already mutated them, making the before/after comparison always equal;
  (2) the skip condition required at least one carousel field to have changed,
  so a no-op edit (wizard opened and saved unchanged) also triggered a rebuild.
  Fix: snapshot `old_carousel_*` before `channel.update()` (alongside the
  other `old_*` fields); replace the carousel-changed requirement with a
  broader `_no_queue_change` guard that skips rebuild whenever no
  queue-affecting fields (shows, movies, queue_size, interleave, mode) changed.


## Version 1.1.4f

**Fix: Popped episodes reappear after editing carousel settings**

**Root cause**

`update_channel` always calls `_pregenerate_queue_safe` at the end of every
edit, unconditionally. This rebuilds the queue from `__queue_tail__` in
state.json. The tail correctly records where the channel is positioned —
but `_build_fresh_queue` reads those indices and continues forward from
that position, producing a fresh 30-item queue that starts from exactly
the episodes the carousel just popped. The popped items come straight back.

Previous attempts (1.1.4f, 1.1.4g) tried to fix the tail after the pop.
They were rolled back because `_recalculate_tail` has an internal guard
that refuses updates when `show_index` is numerically ahead of the queue
item count (always true after a pop on a full queue), and `_save_tail`
wrote correctly but `update_channel` immediately overwrote it anyway before
calling the rebuild.

**Fix**

`update_channel` in `channel_manager.py` now detects whether the only
fields that changed were carousel settings (`carousel_enabled`,
`carousel_interval`, `carousel_pop_count`). If so, the existing queue file
is valid — the carousel has already positioned it correctly — and
`_pregenerate_queue_safe` is skipped entirely. The log will show:

  "only carousel settings changed — skipping queue rebuild"

All other edits (show changes, mode changes, queue size, interleave, name)
continue to trigger a full rebuild as before. Non-carousel channels are
unaffected — the carousel-only detection requires at least one carousel
field to have actually changed, so a plain channel edit always rebuilds.

**File changed:** `resources/lib/channel_manager.py`

---

## Version 1.1.4e

**Fix: Hardcoded minimum interval in carousel wizard**

The carousel wizard step in `channels.py` used a hardcoded `max(30, ...)`
to clamp the interval input. This meant changing `CAROUSEL_MIN_INTERVAL`
in `carousel.py` would not automatically update the wizard enforcement.

Fix: wizard now imports `CAROUSEL_MIN_INTERVAL` from `carousel.py` and
uses it directly — single source of truth for the minimum value.

**Files changed:** `resources/lib/ui/channels.py`

---

## Version 1.1.4d

**Improvement: Carousel minimum interval reduced from 30 to 20 minutes**

`CAROUSEL_MIN_INTERVAL` in `carousel.py` changed from 30 to 20.
Wizard prompt string #32572 updated to reflect the new minimum.
The constant is used throughout `_maybe_pop` — no hardcoded values.

**Files changed:** `resources/lib/carousel.py`, `strings.po`

---

## Version 1.1.4c

**Improvement: Carousel channels now support resume**

Resume was previously disabled entirely for carousel channels. This was
too aggressive — a user who stops mid-episode and returns before the next
pop interval fires should be able to resume normally.

The correct behaviour is:
- **Item still in queue** → resume works as normal
- **Item was popped by carousel** → resume key is silently deleted at pop
  time so the user is never offered a stale resume for something the
  channel has already moved past

**What changed:**

`carousel.py` — `_maybe_pop()` now calls
`channel_manager.clear_resume_position()` for each popped item immediately
after writing the updated queue file. This reuses the existing resume-clear
machinery (handles both shared state.json and local backup) with no new
logic required.

`service.py` — the carousel resume guard in `_do_resume_check` that
blanket-disabled resume for all carousel channels has been removed.
Resume now flows through the normal path for all channels.

`strings.po` — #32574 updated to reflect the new behaviour
("Resume is cleared automatically for items the carousel moves past.").

**Files changed:** `resources/lib/carousel.py`, `service.py`, `strings.po`

---

## Version 1.1.4b

**Fix: Carousel fields not persisted to channels.json**

`create_channel` and `update_channel` in `channel_manager.py` both use
explicit field whitelists when building the channel dict. The three carousel
fields (`carousel_enabled`, `carousel_interval`, `carousel_pop_count`) were
missing from both whitelists, so they were silently dropped when the wizard
returned. Channels saved correctly in every other respect but with no carousel
data at all.

Fix: added all three carousel fields to both whitelists with correct defaults
(`carousel_enabled=False`, `carousel_interval=60`, `carousel_pop_count=1`).

**File changed:** `resources/lib/channel_manager.py`

---

## Version 1.1.4a

**Feature: Carousel Channel**

Adds an optional per-channel setting for TV and Movie channels that
automatically advances the queue on a wall-clock timer while nobody is
watching. Every N minutes, M items are silently removed from the front of
the queue file. When the user opens the channel they pick up wherever the
queue currently sits — no catching up, no resume prompt.

**How it works**

- `resources/lib/carousel.py` (new) owns all carousel logic.
  `CarouselManager.check_all()` iterates all carousel-enabled channels,
  compares wall-clock time to `last_pop_time` in state.json, and pops
  items when the interval has elapsed.
- Wall-clock based: `last_pop_time` is persisted to state.json so missed
  pops while Kodi was closed are applied on next startup.
- Minimum interval: 30 minutes (enforced by wizard).
- Queue safety floor: never reduces queue below 2 items.
- Multiple intervals: if Kodi was closed for 3 hours with a 60-minute
  interval and pop_count=1, three items are removed on startup.
- All pops are logged; no user notification.

**Service integration**

- Startup catch-up: `CarouselManager.check_all()` runs once before the
  service run loop begins.
- Run loop: checked every 60 ticks (60 seconds) using the existing `tick`
  counter. No new threads, no new timers.
- Currently-playing channel is always skipped — watching the channel IS
  the drift function.

**Resume disabled for carousel channels**

`_do_resume_check` in service.py checks `carousel_enabled` on the current
channel and returns without prompting if True. Logged silently.

**Wizard**

Step 8 added to the TV and Movie channel wizard (create and edit).
Asks: Enable carousel? If yes: interval in minutes (minimum 30), items
per interval (minimum 1). Confirmation dialog explains carousel behaviour
and that resume is disabled.

**State key:** `{channel_id}:__carousel__` → `{"last_pop_time": <float>}`

**New strings:** #32570–32577 (8 strings)

**Files changed:**
- `resources/lib/carousel.py` — new
- `resources/lib/ui/channels.py` — wizard step 8
- `service.py` — startup check, 60-tick loop hook, resume guard
- `strings.po` — #32570–32577

---

## Version 1.1.3o

**Fix: TC-17.1 — Serial channel as interleave source into a sequential TV channel**

**Root cause**

The serial channel's standalone playback and its interleave source build both
used the same `__serial_show_idx__` state key.  During skip-advance processing
(when many queue items are consumed quickly), `advance_show` fires repeatedly
and writes its own value to `__serial_show_idx__`.  When the top-up then calls
`SerialQueueBuilder.build()`, it reads the corrupted index and restarts from
the wrong show — episodes from the wrong show appear at the top-up boundary and
shows that were mid-run restart from E01.

**Fix**

Two completely independent sets of state keys now exist:

- **Standalone playback** (existing, unchanged): `{id}:__serial_show_idx__`
  and `{id}:{show_id}` → `next_episode_id`. These are never touched by the
  interleave path.

- **Interleave source** (new): `{id}:__serial_interleave_show_idx__` (which
  show the interleave is currently positioned at) and
  `{id}:__serial_interleave_ep__{show_id}` (0-based episode index within each
  show). Episode position is stored as an index, not an episode ID, so the
  build can reliably continue from exactly where it left off regardless of
  episode ID gaps in the library.

`SerialQueueBuilder.build()` gains a `for_interleave=False` parameter.
When `True`, it calls the new `_build_for_interleave()` path which reads/writes
only the interleave keys, produces exactly `target_size` items (no LOOKAHEAD),
and never calls `_set_show_idx`.

`_load_foreign_items` in `channel_manager.py` gains an explicit serial branch
that calls `SerialQueueBuilder.build(for_interleave=True)` directly, bypassing
`_build_fresh_queue` (which would hit the standalone state).

**Files changed:** `resources/lib/channels/serial.py`, `resources/lib/channel_manager.py`

---

## Version 1.1.3m

**Fix: Two bugs in 1.1.3l's folder channel recycle=False support**

**Bug 1 — AttributeError crash in _handle_end (TC-11.6)**

`_handle_end` is a method of `PlaybackMonitor(xbmc.Player)`.
`_get_manager` is a method of `SmartChannelsService(xbmc.Monitor)`.
These are two separate classes in service.py. The 1.1.3l code called
`self._get_manager()` inside `_handle_end`, where `self` is the
`PlaybackMonitor` — which has no `_get_manager` attribute.
Result: AttributeError on every natural folder item completion.
The skip-detection path worked because it correctly used
`svc._get_manager()` (where `svc = self._service_ref`, the service).

Fix: changed `self._get_manager()` → `self._service_ref._get_manager()`
in `_handle_end`'s folder item branch. This matches the pattern used
by every other caller of `_get_manager` inside `PlaybackMonitor`.

**Bug 2 — 6-item queue instead of 3 for small recycle=False folders**

Top-up threshold (5) > folder size (3). Top-up fires immediately when
the channel starts (disk=2, threshold=5), before any file completes.
At that point `played_files` is empty, so `FolderQueueBuilder.build()`
sees no played files and adds all 3 again. Queue grows to 6.

Fix: `_topup_queue`'s folder branch now passes the list of files
already in `current_queue` to `FolderQueueBuilder.build()` as
`queued_files`. The builder excludes those files from the result, so
a top-up never re-adds files that are already waiting to be played.
For an initial build (`queued_files=None`) the behaviour is unchanged.

Combined effect: all 3 files play once (no duplicates), the last file's
natural completion is recorded correctly, exhaustion fires after all
files are played.

**Files changed:** `service.py`, `channel_manager.py`, `channels/folder.py`.
**Strings:** unchanged (#32569 highest, 367 total).

---

## Version 1.1.3l

**Fix: Folder channel with recycle=False never exhausts — refills
indefinitely (TC-11.6)**

Three cascading gaps meant recycle=False was completely ignored for
folder channels:

1. **`service.py` _handle_end folder branch** returned immediately
   without recording which file was played. No `played_files` state was
   ever written.

2. **`FolderQueueBuilder._get_played_files()`** correctly reads
   `played_files` from state — but since nothing ever wrote it, always
   returned `[]`. The exhaustion check in `build()` compared
   `set(all_files).issubset(set([]))` → always False → folder always
   returned a full listing → top-up kept adding more items.

3. **`_channel_exhausted()`** returned False for folder channels because
   `shows == []` caused an early return on line 499–501. Even if the
   builder had correctly returned empty, the exhaustion dialog would
   never appear.

**Fix — three matching changes:**

- **`channels/folder.py`**: Added `FolderQueueBuilder.is_exhausted(channel)`
  — scans the folder, reads `played_files` from state, returns True when
  all files have been played. Keeps folder-specific logic in folder.py.

- **`channel_manager.py`**: Added `record_folder_file_played(channel_id,
  file_path)` — appends a file path to `played_files` in the channel's
  show_id=0 state. Added folder branch to `_channel_exhausted()` that
  delegates to `FolderQueueBuilder.is_exhausted()`.

- **`service.py`**: `_handle_end` folder branch now calls
  `record_folder_file_played` before returning. Skip detection loop now
  has a folder item branch that also calls `record_folder_file_played`
  for skipped files (same pattern as movie skip handling, which calls
  `advance_movie_state` on skip for recycle=False tracking).

**Strings:** unchanged (#32569 highest, 367 total).
**Files changed:** `channels/folder.py`, `channel_manager.py`, `service.py`.

---

## Version 1.1.3k

**Fix: Serial channel show boundary writes foreign episode ID into
next show's actually_played_ids**

Root cause: `_advance_serial()` in `channel_manager.py` (lines 834–836).
When a serial show boundary is crossed (e.g. show 2693 → show 1821),
the fast-path state write for the NEW show unconditionally added
`played_episode_id` to `actually_played_ids` — but at that point
`played_episode_id` is the last episode of the OLD show (e.g. ep 138725
from "Daughters of the Cult") and `target_show_id` is the NEW show
(e.g. 1821, "Death by Lightning"). The result was foreign episode IDs
accumulating in the next show's `actually_played_ids` entry at every
show boundary crossing.

Observed in state.json as:
```json
"channel_id:1821": {
    "actually_played_ids": [94569, 94570, 94571, 138725]
}
```
where 138725 belongs to show 2693, not show 1821.

Impact: currently cosmetic for serial channels (serial exhaustion is
detected via queue-dry / next_episode_id=None, not via
actually_played_ids). However the contamination grows over multiple
boundary crossings and would mislead any future code or debugging
that relies on actually_played_ids being clean.

Fix: added `int(target_show_id) == int(show_id)` guard so
`played_episode_id` is only added to `actually_played_ids` when the
fast-path is writing to the SAME show that owned the episode (no
boundary crossing). At a boundary the old show's advancement is
already handled by `builder.advance_show()` at line 812–813.

**Files changed:** `channel_manager.py` only.
**Strings:** unchanged (#32569 highest, 367 total).

---

## Version 1.1.3j

**Fix: JSONRPC filter error on Season >= / <= filters (TC-7.6)**

Kodi 21's JSON-RPC `List.Filter.Operators` enum does not include
`"greaterthanequal"` or `"lessthanequal"` — only `"greaterthan"` and
`"lessthan"` are valid numeric operators. `build_jrpc_filter()` was
passing these invalid strings directly, causing Kodi to reject the
filter with "Value does not match any of the enum values in type
operator" and return unfiltered results.

Fix in `library.py → build_jrpc_filter()`:
- Removed `"greaterthanequal"` and `"lessthanequal"` from
  `comparison_map` (they are not valid JSONRPC operator values)
- **Integer fields (season, year):** emulate `>= N` as `> N-1` and
  `<= N` as `< N+1` — exact equivalents for integer comparisons
- **Float fields (rating):** map `"greaterthanequal"` → `"greaterthan"`
  and `"lessthanequal"` → `"lessthan"` (acceptable approximation;
  Kodi ratings are inherently inexact)
- Fixed fallback defaults in year and rating branches (were
  `"greaterthanequal"`, now `"greaterthan"` and `"is"` respectively)

All callers unchanged: `get_episodes_with_filters`,
`get_movies_with_filters`, `get_tvshows_with_filters` all call
`build_jrpc_filter()` — fixing that function fixes all three.

**Fix: Shuffle and Surprise Me dialogs not showing result before
acceptance (1.1.3i regression)**

In 1.1.3i, the shuffle and Surprise Me `yesno()` dialogs were correctly
converted to `select()` to add a Cancel option. However, `select()` has
no body-text parameter, so the shuffled show order and the Surprise Me
episode picks — which were previously shown as the `yesno()` body text
— were no longer visible to the user before they made their choice.

Fix: added `d.ok(heading, content)` immediately before each `d.select()`
in all five affected dialog loops so the result is always shown before
the Accept/Try Again/Cancel choice:
- TV rotation order — Shuffle result (Show Rotation Order heading)
- TV rotation order — Manual order confirm (Confirm Order heading)
- TV Starting Point — Surprise Me episode picks
- Serial rotation order — Shuffle result (Show Play Order heading)
- Serial rotation order — Manual order confirm (Confirm Order heading)

The TV and Serial manual order confirm loops were a pre-existing display
gap (they used `select()` before 1.1.3i too, so they never showed the
chosen order). Fixed in the same pass per the "include all affected
functions" rule.

**Files changed:** `library.py`, `ui/channels.py`.
**service.py:** contains 1.1.3h change (Start Over resume clear) only —
no new changes this session.
**Strings:** unchanged (#32569 highest, 367 total).

---

## Version 1.1.3i

**Fix: Medium/High/Critical wizard dialogs had no cancel path (TC-2.1)**

Root cause: `Dialog.yesno()` in Kodi 21 returns `False` for both the No
button and Back/Esc — the two are indistinguishable. Every `yesno()` in
the wizard silently treated Back/Esc as "No", causing the wizard to
continue to the next step. At the final Visibility step, this created a
HIDDEN channel when the user pressed Back/Esc expecting to cancel. The
two shuffle-order accept loops were also stuck in infinite loops since
Back/Esc = False = "try again", with no escape.

Fix: all Medium/High/Critical `yesno()` dialogs converted to `select()`
with an explicit "Cancel" option (string #32569). `select()` returns -1
on Back/Esc and the wizard returns None on -1 or on Cancel selection.
Queue size `d.input()` now treats empty return (Back/Esc) as cancel
instead of silently using the default and continuing.

**Dialogs fixed by severity:**
- CRITICAL: Visibility? — all 3 wizards (TV/Movie, Serial, Folder)
- HIGH: Recycle? — all 3 wizards
- HIGH: Queue size — all 3 wizards (empty input now cancels)
- HIGH: TV rotation order "Shuffle" accept loop — infinite loop broken
- HIGH: Serial rotation order "Shuffle" accept loop — infinite loop broken
- HIGH: "Surprise Me!" accept loop — infinite loop broken
- MEDIUM: Randomize? — TV, Movie, and Folder wizards
- MEDIUM: "Set Episodes Per Slot?" — TV wizard

**NOT fixed (Low severity — Back/Esc = No is acceptable default):**
- "Show filter?" (>20 shows) — No = no filter = sensible default
- "Per-show randomize?" — No = sequential = sensible default
- "Episode filters?" entry — No = skip filters
- "Exclude Episodes/Movies?" entry — No = skip exclusions

**New string:** #32569 "Cancel" — shared across all three wizards.

**Orphaned strings (harmless, retained for reference):**
#32441, #32443, #32444, #32512 — body text from converted yesno dialogs.
Select() shows only a heading, not body text, so these are now unused.
Same status as pre-existing orphans #32497 and #32517.

**Files changed:** `ui/channels.py`, `strings.po` only.
**service.py:** untouched, byte-identical to 1.1.2aw.

---

## Version 1.1.3h

**Fix: Stored resume position not cleared when user selects Start Over**

When the resume dialog appeared and the user selected "Start Over"
(the No/decline option), the stored resume key in state.json was left
intact. On the next stop-and-reopen cycle, the same stale resume
position would be offered again even though the user had explicitly
chosen to restart from the beginning.

Root cause: the existing comment in `_do_resume_check` at the seek
block correctly explains why the resume key is NOT cleared immediately
when the user ACCEPTS a resume — clearing then would leave a gap window
where stopping within 60s (before the first poll save) would produce
no resume key at all. However, that reasoning only applies to the
resume-accepted path. For Start Over, the key has no valid replacement
coming and must be cleared immediately.

Fix: added `mgr.clear_resume_position(ep)` in the `else` (Start Over)
branch of `_do_resume_check`, immediately after `self.seekTime(0)`.
Uses the same `mgr` and `ep` already in scope, and the same
`clear_resume_position()` method already called by `onPlayBackEnded`,
`set_now_playing`, and the skip-detection path.

**Files changed:** `service.py` only.
**Strings:** unchanged (#32568 highest, 366 total).

---

## Version 1.1.3g

**Fix: Movie channel edit inherits stale cycle state, producing early
repeat movies (TC-9.2 failure)**

Root cause: `update_channel` did not clear `__movie_state__` when a
movie channel was edited. That state key records which movies have been
played in the current shuffle cycle (`played_ids`, `unplayed_ids`).

When TC-9.1 (27 movies, played extensively through multiple cycles)
was edited to TC-9.2 (5 movies, genre filter applied), `_build_movie_queue`
read the inherited state and found that 4 of the 5 new movies were
already in TC-9.1's `played_ids`. Only 1 movie was classified as
"unplayed." The builder placed that 1 movie as a micro-cycle, reset,
then drew all 5 randomly for the first full cycle — so the same movie
appeared at position 0 (micro-cycle) and again at position 2 (full
cycle), producing the early repeat seen in the queue:
`['Good Luck, Have Fun,', 'Mike & Nick & Nick &', 'Good Luck, Have Fun,']`

Fix: in `update_channel`, when `new_type == "movies"`, pop the
`__movie_state__` key and mark it deleted. `_build_movie_queue` then
falls through to its clean initialisation branch (stored_unplayed is
None → all movies start unplayed → full random cycle from scratch).
This is directly analogous to how TV channel show state is cleared on
mode change, and is the correct behaviour any time the effective movie
pool may have changed.

TC-9.1 itself was unaffected (no preceding movie channel state to
inherit). The issue manifested only on edit (TC-9.1 → TC-9.2).

**Files changed:** `channel_manager.py` only.
**service.py:** untouched, byte-identical to 1.1.2aw.
**Strings:** unchanged (#32568 highest, 366 total, 0 duplicates).

---

## Version 1.1.3f

**Fix: TC-5.3 regression — episodes_per_slot slots produce wrong
episode count at every cycle boundary (last episode wraps to first
episode mid-slot)**

Root cause: both `_build_fresh_queue` and `_topup_queue` have an
inner `while _slot < eps_per_slot:` loop that places consecutive
episodes for one show's rotation slot. Inside that loop, a guard
checks whether `local_index >= len(episodes)` — i.e., the show's
episode list has been exhausted. For `recycle=True` it resets
`local_index = 0` (wraps to E01) and then `break`s out of the
inner loop.

That `break` is the bug. When a show like 1883 (10 episodes,
`eps_per_slot=2`) places E10 as the FIRST of a 2-episode slot, the
index advances to 10, which is out of range. The recycle guard fires,
resets to 0 — and then breaks instead of continuing. The slot
completes with only 1 episode (E10), leaving E01 as the first episode
of the NEXT slot. The pattern then alternates: correct pair, single,
correct pair, single... at every point where the episode list boundary
falls mid-slot.

Fix: change `break` → `continue` in the mid-slot recycle guard in
both `_build_fresh_queue` (line ~2226) and `_topup_queue` (~2588).
After resetting `local_index = 0`, `continue` resumes the inner loop,
which then places E01 to complete the slot. The result is [E10, E01]
as a correctly paired slot, and the next rotation's slot starts at
E02 as expected.

The target-size rollback check at the TOP of the inner loop fires
BEFORE this guard, so if the queue fills up after E10 is placed, the
rollback takes priority and this branch is not reached — confirmed by
Test 4 in the standalone functional harness.

**Why this wasn't caught earlier:** the bug only manifests when
`eps_per_slot >= 2` AND the show's episode count is not a multiple of
`eps_per_slot` (or the slot lands exactly at the end of the list).
For `eps_per_slot=1` (default) the inner loop always completes in
one iteration, so the guard never fires. The TC-5.3 test requires an
explicit `episodes_per_slot=2` config.

**TC-EXC tests and 1.1.3d rotation fix:** unaffected. Those changes
are in `ui/channels.py` and the `start_show_index` parameter chain.
This fix is in the inner slot loop only.

**Files changed:** `channel_manager.py` only.
**service.py:** untouched, byte-identical to 1.1.2aw.
**Strings:** unchanged (#32568 highest, 366 total, 0 duplicates).

---

## Version 1.1.3e

**UI Polish: Exclusions show-picker flow, season exclusion, and
"Keep current position" label during channel edit**

Three wizard UX improvements, all in `ui/channels.py` only. No
changes to exclusion storage, queue building, or any other module.

**1. Exclusions show-picker flow (TV and Serial)**
Previously the wizard prompted "Manage Exclusions? Yes/No" for every
show individually — tedious on channels with many shows, especially
when only one or two shows need exclusions. New flow: one channel-level
"Exclude Episodes? Yes/No" entry point, then a repeating show-picker
that lists every show with its current exclusion count ("2 episode(s)
excluded" / "no episodes excluded"). User picks a show, manages its
exclusions, returns to the picker, and selects Done when finished.
Applies to both TV wizard (Step 4a-v) and Serial wizard.

**2. "Exclude entire Season" option**
Previously excluding a full season required checking every episode
individually in the multiselect. New intermediate step after picking
a season: "Exclude entire Season X / Select individual episodes".
Choosing "Exclude entire Season" adds all episode IDs for that season
at once, replacing any prior individual selections within that season
(confirmed design: replace, not append). Cancelling the intermediate
step returns to the season list with no change.

**3. "Keep current position" starting point label during edit**
During channel creation, starting point option 0 correctly says
"Start from S01E01 (default)". During a channel edit this label was
misleading — choosing it does NOT restart shows from S01E01; it leaves
all existing show state completely intact (starting_points stays empty,
_apply_starting_points finds nothing to apply). The label now reads
"Keep current position" during an edit so the user knows their
progress is preserved. No behavior change — label only.

**Strings:** #32552 and #32553 repurposed (were per-show Yes/No
prompts, now channel-level entry-point title/message). New strings
#32564–#32568 added (5 strings). Highest ID #32568, 366 total,
0 duplicates, 0 broken, 0 new orphans.

**service.py:** untouched, byte-identical to 1.1.2aw.

---

## Version 1.1.3d

**Fix: Round Robin queue rebuild after edit always started from show[0]
instead of the show that was playing (TC-EXC.12)**

Root cause: `_build_fresh_queue` hardcoded `show_index = 0` on every
fresh queue build, including the rebuild triggered by `update_channel`.

First attempt (1.1.3d, reverted): read `now_playing.json` via
`_resolve_path` — wrong because that resolves to the shared NAS path,
while `now_playing.json` is written to the local Kodi profile first.
Also used `now_playing.get("channel_id")` — wrong key; the actual key
is `"active_channel_id"`. And relied on `show_id` from the file, which
isn't stored in `now_playing.json` at all.

Correct fix (this version): two in-memory/local-path sources combined:
1. `now_playing.json` read from `self.profile` (the local Kodi addon
   profile directory — always written here first by player.py before
   any shared storage copy, correct on both local and shared setups).
   Used only to confirm this channel is the one currently active.
   Key checked: `"active_channel_id"`.
2. `self._state.get("{channel_id}:__show_index__")` read from the
   already-loaded in-memory state dict, BEFORE the existing clear of
   that key at line 286. This integer is written by service.py via
   `save_show_index()` each time an episode starts — it is the list
   index of the show that was playing at edit time.

The captured `start_show_index` is passed through the call chain:
`_pregenerate_queue_safe` → `_pregenerate_queue` → `build_queue` →
`TVQueueBuilder.build` → `_build_fresh_queue`, where it seeds
`show_index` directly. Validated against the shows list length so a
removed show can't produce an out-of-range index.

All fallback cases return `show_index = 0` (unchanged behavior):
- `now_playing.json` absent or `active_channel_id` doesn't match
- `__show_index__` not present in state (fresh channel, never played)
- `start_show_index` is 0 (show[0] was playing — same result either way)
- `start_show_index` out of range (e.g. show was removed in this edit)
- `mode_changed = True` — hint explicitly skipped, clean start needed
- Non-TV channels, `create_channel` — hint never populated

**Files changed:** `channel_manager.py`, `resources/lib/channels/tv.py`
**service.py:** untouched, byte-identical to 1.1.2aw.
**Strings:** unchanged (#32563 highest, 361 total, 0 duplicates).

---

## Version 1.1.3c

**Fix: excluded_episodes lost on every wizard edit-round-trip (TC-EXC.2)**

Root cause: when rebuilding `selected_shows` during a channel edit,
the wizard reconstructs each show dict from scratch (tvshowid + title
only) and then merges back a fixed list of per-show fields from the
existing channel definition. That merge list covered `episodes_per_slot`,
`randomize`, and `episode_filters` — but not `excluded_episodes`.

Result: any existing exclusion list was silently dropped the moment the
wizard rebuilt `selected_shows`, before the exclusion step was even
reached. By the time the user was asked "Manage Exclusions? Yes/No" and
said No ("leave them alone"), the exclusion list was already gone.
Saying Yes would have re-opened the picker, which would preselect
nothing (exclusions already cleared), and saving would have written an
empty list — same outcome, just a different path to the same bug.

Fix: one line added to the existing merge block in
`ui/channels.py`'s `_run_wizard()` at the show-rebuild step:
`if "excluded_episodes" in _prev: _s["excluded_episodes"] = _prev["excluded_episodes"]`

This is a pre-existing gap in the merge block — `excluded_episodes`
was the first per-show field introduced that needed to survive a
wizard edit-round-trip, which is why it surfaces here rather than
having been caught earlier.

Found during: TC-EXC.2 of the 1.1.3a addendum test pass.

---

## Version 1.1.3b

**Cleanup: relocate Exclusions helper logic to channels/base.py**

No behavior change. Pure code-organization move, prompted by a direct
question about whether `channel_manager.py` (already 3,450+ lines) was
the right home for the three new functions added in `1.1.3a`.

`get_filtered_episodes()`, `get_available_episodes()`, and
`resolve_pointer_index()` were pure, self-contained logic with no
dependency on `ChannelManager` state beyond the `library` reference —
exactly the shape of thing `channels/base.py` already exists for
(alongside `normalize_ep()`, `normalize_movie()`, `apply_interleave()`).
Moved there as free functions taking `library` as an explicit
parameter, matching `normalize_movie()`'s existing precedent.

`channel_manager.py`'s three originals are now thin delegates, matching
the established `_normalize_ep()`/`_normalize_movie()` pattern exactly
— every one of the ~15 call sites wired up in `1.1.3a` needed zero
changes, since the method names and signatures on `ChannelManager`
didn't move, only their bodies.

**Deliberately NOT moved:** `_build_episode_exclusions()` and
`_build_movie_exclusions()` in `ui/channels.py`. Checked `ui/dialogs.py`
first — it's an empty stub scoped to thin reusable wrappers
(select/yesno/ok), not full wizard-step builders, and the existing
precedent (`_build_episode_filters()`, `_build_filters()`) already
lives in `ui/channels.py` itself. Moving only the exclusion pickers
elsewhere would have created an inconsistency, not fixed one.

**Verification:**
- `channel_manager.py`: 3,454 → 3,367 lines
- `channels/base.py`: 231 → 341 lines
- Full `py_compile` across every file
- Duplicate-function-name sweep unchanged from pre-refactor baseline
- `service.py` reconfirmed byte-identical to `1.1.2aw`
- strings.po unchanged (`#32563` highest, 361 total, 0 duplicates)
- New standalone functional harness (stubs only `xbmc`/`xbmcaddon`,
  matching the project's established testing pattern) exercising the
  three moved functions directly through their new location: no
  filters/exclusions passthrough, exclusion filtering, filters+exclusion
  layering, stale-pointer resolution (both the "skips forward" case and
  the "pointer still valid, unchanged" case), and entire-show-excluded
  returning an empty pool without crashing — all 6 cases pass

**Test procedure:** none of the `1.1.3a` addendum test cases change —
this release doesn't alter behavior anywhere they cover. Same addendum
applies; no new manual test cases needed for this release specifically.

---

## Version 1.1.3a

**Feature: Episode / Movie / Serial Exclusions**

Per-channel exclusion lists so specific episodes or movies can be
removed from a channel's rotation without affecting other channels
that use the same show/movie.

- TV: `excluded_episodes: [episodeid, ...]` per show entry
- Movie: `excluded_movies: [movieid, ...]` on the channel
- Serial: `excluded_episodes: [episodeid, ...]` per show entry — serial
  silently skips excluded episodes and continues the sequence
- Folder channels: not included by design (user controls folder
  content directly)

**Wizard placement:** TV — after per-show episode filters, before
starting point. Serial — after show ordering, before recycle. Movie —
after recycle, before queue size. Always prompts "Manage Exclusions?
Yes/No" — never auto-enters even when exclusions already exist
(different from the episode-filters step, which does auto-enter).

**Picker:** season → episode multiselect for TV/Serial (reuses the
manual-starting-point picker's season navigation, generalised to a
toggleable set since exclusions are a list rather than one choice, and
restricted to episodes currently passing the show's `episode_filters`).
Movies use a single multiselect over the channel's own selected movie
list — no season concept.

**Architecture:**
- New `channel_manager.get_filtered_episodes()` / `get_available_episodes()`
  — consolidates what was 4 separate duplicated copies of the
  `episode_filters` dual-branch fetch (get_episodes_with_filters vs.
  get_episodes_for_show) into one source, then layers exclusion
  filtering on top. Every TV/Serial call site that decides what CAN
  play now goes through these instead of calling `library.py` directly.
- New `channel_manager._resolve_pointer_index()` — handles a stored
  `next_episode_id` that goes stale because the episode it points to
  was excluded after the pointer was written. Walks forward past the
  exclusion using the show's original filtered order rather than
  falling back to "restart the show from episode 1" (the pre-existing
  behaviour for an unresolvable pointer, which would have been a
  jarring regression for something as small as excluding one episode).
- `_channel_exhausted`'s random-show branch now checks episode
  availability (filters + exclusions) instead of the raw library set —
  required so a `recycle=False` channel with any exclusion can still
  reach a genuine exhausted state, rather than waiting forever for an
  episode that can never legitimately play.
- Existing queue file scrubbing on edit: no new code needed —
  `update_channel()` already unconditionally rebuilds the queue file
  via `_pregenerate_queue_safe()` on every save, and since the builders
  are now exclusion-aware, an edit that adds an exclusion immediately
  removes it from the on-disk queue as a natural side effect. The
  currently-playing item (already loaded into Kodi's live player) is
  never affected by a queue-file rewrite mid-playback.
- `reset_show_to_start()` (Reset Show feature) and its `router.py`
  pre-check now reset to the first AVAILABLE episode, not the first
  library episode — a stray gap found during the completeness sweep
  for this feature, not a separate fix.
- `_recalculate_tail()` now sources its episode pool the same way
  `_build_fresh_queue`/`_topup_queue` do, so reconstructed queue
  positions stay aligned with the pool those builders actually used —
  another gap found during the same sweep.
- `service.py` untouched — confirmed byte-identical to `1.1.2aw`.
  Exclusions is entirely a queue-building/channel-definition concern;
  no playback callback needed any change.

**New strings:** `#32552`–`#32563` (12 total; one originally-planned
string, `#32557`, was dropped before packaging as unused — never
written to disk as an orphan).

---

## Version 1.1.2aw

**Fix: resume position from previous episode incorrectly attributed to
next episode after a stop within the first 60 seconds of play**

Root cause: `PlaybackMonitor._last_polled_pos` (the fallback used by
`onPlayBackStopped` when `getTime()` fails) was only ever reset inside
`onPlayBackStopped` itself — but it was NEVER cleared on natural episode
transition (Kodi auto-advances between episodes, no stop event fires).
So when episode A completed its first poll save (e.g. 60s), then episode
B started and the user stopped it before B's first poll (< 60s in),

`getTime()` failed (Kodi already stopped), and the fallback used A's
60s position but attributed it to B's episode ID. The user then got a
resume dialog offering to resume at a wrong position.

Fix: reset `_last_polled_pos = None` in `set_now_playing`, which is
called for every new episode. If the new episode stops before its own
60s poll fires, the fallback correctly finds nothing and logs
"no fallback available" rather than saving a stale position.

---

**Fix: `_current_ep = None` in `_handle_end` after stop/restart when
the same episode immediately restarts**

Root cause: `SmartChannelsService._current_file` (the field checked by
`_check_now_playing`'s early-return guard — "already registered, skip")
was not cleared by `onPlayBackStopped`. `PlaybackMonitor._current_file`
WAS cleared (a different field on a different object), so the intended
"force re-registration" comment did not apply to the service-level
field. When the same episode restarted after a stop, `_check_now_playing`
saw `playing_file == self._current_file` (stale value from before the
stop) and returned early — never calling `set_now_playing`, never
setting `_current_ep`. When the episode then ended, `_handle_end` found
`_current_ep = None` and fell back to `queue[_queue_position - 1]`
using a potentially stale position from the previous play session,
advancing state for the wrong show.

Fix: in `onPlayBackStopped`, after clearing `PlaybackMonitor._current_file`,
also clear `SmartChannelsService._current_file` via `self._service_ref`.
One line. The service's `_check_now_playing` will then correctly detect
the restarted episode as a new file on its next tick and call
`set_now_playing`, ensuring `_current_ep` is correctly set before any
`onPlayBackEnded` / `_handle_end` call.

Both bugs were confirmed from log evidence in TC-AU.3 testing
(30 Jun 2026). No new strings, no settings changes, no other files
modified.

---

## Version 1.1.2av

**Fix: custom icon.png/fanart.jpg never displayed in the Kodi addon
manager, even after clearing cache/temp/library**

Root cause: `addon.xml` never declared an `<assets>` block. The
`icon.png` and `fanart.jpg` files were correctly present at the addon
root (verified: 256×256 PNG icon, 1280×720 JPEG fanart, no duplicate
copies elsewhere) but Kodi had nothing in the metadata telling it where
to find them. This was never a caching issue — clearing cache/temp/
library could not have fixed it, since the XML itself was missing the
declaration on every load.

Added:
```xml
<assets>
  <icon>icon.png</icon>
  <fanart>fanart.jpg</fanart>
</assets>
```
inside the existing `xbmc.addon.metadata` extension point.

No Python code touched. No new strings. Pure `addon.xml` metadata fix.

---

## Version 1.1.2au

**Architecture fix: eliminated service.py / channel_manager.py
advance_state duplication (semantic duplication — different names, same
job, writing the same state.json fields from two places)**

`service.py`'s module-level `advance_state()` — the function that ran on
every TV/serial episode completion — has been deleted entirely. All
TV and serial state advancement (including the `actually_played_ids`
exhaustion tracking added in `1.1.2at`) now goes through a single
implementation in `channel_manager.py`:

- `ChannelManager.advance_show()` is now the sole entry point, called
  from both `service.py` call sites (natural episode end in
  `PlaybackMonitor._handle_end`, and skip-detected advancement in
  `SmartChannelsService`). It accepts the same `next_ep_id`/
  `next_ep_info` parameters `advance_state()` used to, so the
  queue-already-knows-what's-next fast path (no DB roundtrip) is fully
  preserved — this is the hottest code path in the addon.
- `advance_show()` dispatches to `_advance_serial()` for serial
  channels, which now owns the show-boundary-crossing detection that
  used to live inline in `service.py` (the "does next_ep_id belong to a
  different show" lookup). Ordinary in-show serial steps take the fast
  path directly and do NOT call `SerialQueueBuilder.advance_show()` —
  only genuine boundary crossings (or a fully dry queue) do, exactly as
  before.
- `_advance_sequential()` now persists the `recycle=False` exhaustion
  marker (`next_episode_id: None`) itself — previously this state.json
  write only happened inside `service.py`'s `advance_state()`, never in
  `channel_manager.py`'s version of sequential advancement.
- `service.py`'s dead `get_episodes()` helper (only ever called from the
  now-deleted `advance_state()`) was removed, along with the unused
  `channel_manager.get_episodes_for_show_cached()` wrapper it called
  into and the now-unused `random` import in `service.py`.

Verified with a standalone harness that imports the real, unmodified
`channel_manager.py`/`serial.py` code (only `xbmc`/`xbmcaddon`/`xbmcvfs`
stubbed) and exercises 10 scenarios covering TV sequential (mid-show,
end-of-library wrap/stop), TV random (recycle=True full-cycle reset,
recycle=False no-reset), per-show randomize resolution, serial in-show
steps (confirms no false show reset), serial boundary crossing, serial
exhaustion, and the DB-lookup fallback path — 23/23 checks passed.
Manual playback testing on Shield/Windows still required before this
version is considered confirmed working (see test procedure addendum).

No functional behavior change intended — this is a pure relocation of
existing logic, same as the 1.1.0 rewrite philosophy. No new strings,
no settings.xml changes.

---

## Version 1.1.2at

**Fix: Random TV channel with recycle=False falsely reports exhausted
immediately after creation, deleting its own freshly-built queue file**

Root cause: `_channel_exhausted` determined random-show exhaustion by
checking the queue tail's `local_played` data — a bookkeeping structure
that tracks which episodes have been PLACED into a queue file, not which
episodes have actually been WATCHED. For a show with episode count <=
queue_size (e.g. a show with exactly 10 episodes and queue_size=10), the
very first queue build places every episode the show owns into
`local_played` in one pass. The exhaustion check then saw "all episodes
present in local_played" and concluded the show was exhausted — before a
single second had been played. For `recycle=False` channels this caused
play_channel's pre-flight exhaustion check to immediately delete the
queue file that had just been written and refuse to play.

This explains why testing with a longer show (8 Simple Rules, 76
episodes vs. queue_size=30) did not reproduce the bug — local_played only
ever contained a subset of the full episode pool, so the false-positive
condition was never reached. It is purely a function of episode count
relative to queue size, not anything done differently between tests.

Fix: random-show exhaustion is now tracked by a new, genuinely separate
field: `state["actually_played_ids"]`. This list is updated only when an
episode is confirmed to have finished or been skipped past — inside
`channel_manager._advance_random` and inside all three branches of
`service.advance_state` (the queue-info path, the DB-lookup fallback, and
the queue-dry random fallback). It is never touched by queue-building
code. `_channel_exhausted` now reads this field instead of the queue
tail's `local_played` for random-show exhaustion checks. For recycle=True
shows, the list resets to empty once every episode has been confirmed
played, allowing the cycle to continue indefinitely as before.

Sequential-show exhaustion (next_episode_id=None) and movie-channel
exhaustion (unplayed_ids empty) are unaffected — neither used the queue
tail for this purpose and both continue to work exactly as before.

**Files changed:** `resources/lib/channel_manager.py` (`_advance_random`,
`_channel_exhausted`), `service.py` (`advance_state`, all three branches)

---

## Version 1.1.2as

**Fix: Settings change not taking effect on running poll timer**

Root cause: `onSettingsChanged` reset `_resume_settings_loaded = False`
but `_load_resume_settings` is only called from `set_now_playing` —
which only fires when a new item starts. If settings were changed while
a channel was already playing, the reset flag was never acted on and the
running poll timer kept its old interval until the next playback start.

Fix: `onSettingsChanged` now calls `_load_resume_settings` immediately
(not lazily) and then restarts the poll timer if it is currently running,
so the new interval takes effect at once. Log will show:
  `onSettingsChanged: settings reloaded (interval=Ns)`
  `onSettingsChanged: poll timer restarted with new interval`

**Files changed:** `service.py` only

---

## Version 1.1.2ar

**Fix: AttributeError '_lock' in onSettingsChanged**

Root cause: `onSettingsChanged` is a method on `SmartChannelsService`
(inherits `xbmc.Monitor`). It was written with `self._lock` and
`self._resume_settings_loaded` — but both of those attributes belong to
`PlaybackMonitor` (inherits `xbmc.Player`), a completely separate class.
`SmartChannelsService` has no `_lock` attribute, causing an
`AttributeError` every time the user changed any addon setting.

Fix: `onSettingsChanged` now accesses the `PlaybackMonitor` instance via
`self.player._lock` and `self.player._resume_settings_loaded`, which is
how all other cross-class access is done throughout the service. Wrapped
in try/except so a future attribute error doesn't crash the handler.

**Files changed:** `service.py` only

---

## Version 1.1.2aq

**Fix: Non-silent interleaved folder items now resumable**

Root cause: The resume guard in both `_poll_save` and `onPlayBackStopped`
blocked resume for ALL interleaved folder items by checking `_interleaved`.
This was wrong — only silent interleaved items should be excluded from
resume. Non-silent interleaved folder items are visible to the user (they
appear in the queue, CUN announces them, the OSD shows their title) and
resume is entirely valid for them.

Fix: Guard changed from `ep.get("_interleaved")` to `ep.get("_silent")`
in both locations. Resume behaviour is now:
- Folder channel standalone: resumable ✅
- Folder channel interleaved, silent=False: resumable ✅ (was incorrectly blocked)
- Folder channel interleaved, silent=True: not resumable ✅

**Removed: folder_resume_min_duration setting**

The minimum duration setting for folder channel resume was removed. It was
redundant — the 60-second poll timer interval already acts as the natural
floor. Any folder item shorter than 60 seconds will never have its position
saved by the poll timer, so no resume dialog can appear for it. The setting
added complexity and had a load-order bug causing it to read stale values.

Removed from: `settings.xml`, `strings.po` (#32536 retired),
`service.py` (`_folder_resume_min_dur`, all references).

**Files changed:** `service.py`, `resources/settings.xml`,
`resources/language/resource.language.en_gb/strings.po`
(#32536 retired; highest ID remains #32551, total now 350)

---

## Version 1.1.2ap

**Fix: Starting point step skipped/hidden for fully random channels**

For a channel where all shows play randomly, the "Custom Starting Point"
wizard step is now skipped entirely. For a round-robin channel with mixed
sequential and random shows, the step is shown but only sequential shows
are offered — random shows are excluded from both Surprise Me and the
manual episode picker. A show is considered sequential if neither the
channel-level `randomize` flag nor the show's own `randomize` flag is True.

Previously the step was always shown for TV channels, and a starting point
set on a random show was written to state.json but ignored by
`_build_fresh_queue` (which uses the tail's `local_played` for random
picks, not `next_episode_id`).

**Fix: Episodes with no firstaired date bypassed firstaired filter**

`_filter_items_in_python` treated a missing `firstaired` field as a
pass-through (`return True`). For shows like Looney Tunes where pre-1950
episodes have no air date in the Kodi database, a "First Aired after
1950-01-01" filter would pass them through silently, causing all seasons
from 1929 onward to appear in the starting episode picker and the queue.

Fix: Missing `firstaired` now returns False (excluded) when a date filter
is active. An unknown date cannot satisfy a date comparison.

**Files changed:** `resources/lib/ui/channels.py`,
`resources/lib/library.py`

---

## Version 1.1.2ap

**Fix: Episodes with no firstaired date bypassed firstaired filter**

Root cause: `_filter_items_in_python` treated a missing `firstaired`
field as a pass-through (`return True`). For Looney Tunes episodes from
the 1930s–1940s that have no air date in the Kodi database, "First Aired
after 1950-01-01" should exclude them — but instead they passed the filter
silently and appeared in both the queue and the starting episode picker.

Fix: Episodes with a missing or empty `firstaired` value now return False
(excluded) when a date filter is active. An unknown date cannot satisfy
any date comparison. The comparison date being empty is still treated as
a pass-through (no comparison = no filter).

This only affects the Python fallback path in `_filter_items_in_python`.
The Kodi RPC path already handles missing dates server-side correctly.

**Files changed:** `resources/lib/library.py` only

---

## Version 1.1.2ao

**Fix: Surprise Me starting point ignored for random channels**

Root cause: `_apply_starting_points` writes `next_episode_id` into
state.json. For sequential channels this works correctly — `_build_fresh_queue`
seeds `local_index` from `next_episode_id` and starts from that position.
For random channels, `_build_fresh_queue` ignores `next_episode_id` entirely
and instead picks from the unplayed pool (`local_played`). Since a new channel
has no tail and `local_played` is empty, `random.choice()` picks any episode —
completely ignoring the chosen Surprise Me episode.

Fix: `_apply_starting_points` now detects whether a show plays randomly.
For random shows, it seeds `played_ids` with all episode IDs EXCEPT the
chosen episode, leaving only the chosen episode in the unplayed pool so
`random.choice()` is forced to select it first. After the first episode
plays, the tail takes over and normal random selection resumes.

Sequential channels unchanged — still set `next_episode_id` with empty
`played_ids`. No impact on movie, serial, or folder channels.

**Fix: Surprise Me and manual episode picker ignored episode_filters**

Both the Surprise Me random pick and the manual "Choose starting episode"
picker were calling `get_episodes_for_show` (unfiltered). A show with
`episode_filters` set (e.g. "First Aired after 1950-01-01") could produce
a starting episode from 1933 because the filter was not applied to the
picker pool.

Fix: Both pickers now check `show.get("episode_filters", [])` and call
`get_episodes_with_filters` when filters are set, so only episodes that
pass the active filter are available for selection.

**Files changed:** `resources/lib/channel_manager.py`,
`resources/lib/ui/channels.py`

---

## Version 1.1.2an

**Fix: Episode filters lost when editing a channel (TC-5)**

Root cause: The existing-show preservation block in the channel wizard
copied `episodes_per_slot` and `randomize` from the existing show dict
into the freshly-selected show dict, but never copied `episode_filters`.
On edit, `selected_shows` was rebuilt from the library picker — each show
dict started fresh with no `episode_filters` key. The Step 4a-iv check
(`_any_existing_ef`) therefore always saw empty filters, and the filter
dialog opened with "No episode filters set" even though filters had been
saved previously.

Fix: `episode_filters` is now copied alongside `episodes_per_slot` and
`randomize` in the existing-show preservation block (one additional line).

**Fix: Resume settings require Kodi restart after change**

Root cause: `_load_resume_settings` is called once on first playback and
gated by `_resume_settings_loaded = True`. After that, settings changes
made in the addon settings dialog were silently ignored until Kodi restarted.
`onNotification` only listened for library scan events — no handler existed
for addon settings changes.

Fix: Added `onSettingsChanged()` to `PlaybackMonitor`. Kodi calls this
automatically (via `xbmc.Monitor`) whenever the user saves any change in
the addon settings dialog. It resets `_resume_settings_loaded = False`,
causing `_load_resume_settings` to re-read all settings on the next
playback event. No Kodi restart needed.

**Files changed:** `resources/lib/ui/channels.py` (episode_filters copy),
`service.py` (onSettingsChanged)

---

## Version 1.1.2am

**Fix: Episode filters returning 0 episodes (invalid property in RPC call)**

Root cause: `get_episodes_with_filters` included `"art"` in the
`VideoLibrary.GetEpisodes` properties list. `"art"` is not a valid property
for that endpoint — Kodi rejected the entire request with:
`'name': 'Item.Fields.Base', 'array element at index 10 does not match'`
(index 10 = "art", zero-indexed). This caused both the primary filtered
call AND the fallback unfiltered call to fail, returning 0 episodes and
logging "Python filter kept 0 of 0 episodes".

The same error affected every filter type (Season, Watched, First Aired)
because the bad property was in the base params shared by all calls.

Fix: `"art"` removed from the `get_episodes_with_filters` properties list.
`"art"` remains valid and present in `get_episode` (GetEpisodeDetails) and
`get_all_movies` (GetMovies) where it is supported.

The fallback retry now also uses an explicit clean params dict with `sort`
guaranteed, rather than copying from the primary params which may or may
not have had sort depending on whether a filter was present.

**Files changed:** `resources/lib/library.py` only

---

## Version 1.1.2am

**Fix: Season and First Aired filters returned 0 episodes**

Root cause: `"year"` was added to the properties list in
`get_episodes_with_filters` but it is not a valid episode property in
Kodi's JSON-RPC (`VideoLibrary.GetEpisodes`). Kodi rejected both the
primary filtered query and the Python-fallback unfiltered query with
`'array element at index 10 does not match'` / `Item.Fields.Base`.
Both calls failed and returned `{}`, so `episodes` was always `[]`.
The Python fallback then ran on an empty list and kept 0 of 0 episodes.
Fix: removed `"year"` from the properties list. `"year"` is a show/movie
property, not an episode property in Kodi JSON-RPC.

**Fix: "No episode filters set" caused infinite loop in filter dialog**

The summary line was listed as selectable option [0] with `action == 0:
pass`, causing an immediate re-loop with no user feedback. Fixed by
removing the summary from the selectable options list entirely and
embedding it in the dialog title instead
(`"Episode filters: {show} — {summary}"`). Action indices shifted
down by 1 accordingly. "Done" is now index 5 (was 6).

**Also contains all changes from 1.1.2aj, 1.1.2ak, 1.1.2al**

**Files changed:** `resources/lib/library.py` (removed invalid `year`
property), `resources/lib/ui/channels.py` (summary moved to title,
action indices corrected)

---

## Version 1.1.2al

**Fix: Episode filter yes/no dialog showed wrong button labels**
The "Set episode filters?" yes/no dialog was borrowing button label strings
from the Episodes Per Slot step — showing "No, keep 1 each" and "Yes,
customise" instead of filter-relevant labels. New strings #32548 ("No, skip
filters") and #32549 ("Yes, set filters") added.

**Fix: Queue size step showed date picker instead of number input**
`_build_episode_filters` was sharing the caller's Dialog object (`d`). After
a First Aired date input (`INPUT_DATE`), Kodi's input subsystem could carry
date-picker state into the next `d.input` call in the main wizard (queue
size). Fix: `_build_episode_filters` now creates its own
`xbmcgui.Dialog()` instance (`_d`) and uses it exclusively, completely
isolated from the main wizard dialog.

**Fix: First Aired date picker showed DD/MM/YYYY (backwards)**
Kodi's `INPUT_DATE` always renders a regional date wheel — the label cannot
change its order. Replaced with `INPUT_ALPHANUM` so the user types
YYYY-MM-DD directly. Basic format validation (`^\d{4}-\d{2}-\d{2}$`) shows
an error dialog on bad input (#32550). No DD/MM/YYYY conversion needed.

**Improvement: Season filter now uses a list picker**
Instead of a free-text numeric input, the season filter shows the show's
actual season numbers from the library. This is essential for shows like
Looney Tunes where seasons are labeled by year (1940, 1941...) — the user
sees the real values and cannot enter a season that doesn't exist.

**Also contains all changes from 1.1.2aj and 1.1.2ak:**
- Per-show episode filters feature (aj)
- Season/firstaired RPC sort bug fix — sort removed from filtered queries,
  Python sort applied instead (ak)
- Python fallback filter, season/firstaired handlers in
  _filter_items_in_python (ak)

**Files changed:** `resources/lib/ui/channels.py`,
`resources/lib/library.py` (from ak),
`resources/language/resource.language.en_gb/strings.po`
(#32548–#32551 added; highest ID now #32551, total 351)

---

## Version 1.1.2ak

**Fix: Season filter returned 0 episodes (RPC error)**

Root cause: Kodi 21's `VideoLibrary.GetEpisodes` JSON-RPC rejects the
combination of `tvshowid` + `filter` + `sort` in a single call. The
validator errors on the `sort.order` field when a `filter` is also present,
returning an RPC error and an empty result. Two season rules (`>= 1940` and
`<= 1960`) triggered this because they produce a compound `{"and": [...]}` 
filter. The log showed: `'name': 'filter', 'property': {'name': 'order',
'type': 'string'}, 'message': 'Invalid params.'`

Fix: When `get_episodes_with_filters` sends a filter, the `sort` parameter
is omitted from the RPC call. Episodes are sorted in Python after the query
(`season` ascending, then `episode` ascending) — identical order to the
unfiltered path.

**Also added:**
- Python fallback in `get_episodes_with_filters`: if the RPC returns empty
  and a filter was sent, retries without the filter and applies
  `_filter_items_in_python` — defence-in-depth against future RPC rejections
- `season` and `firstaired` handlers added to `_filter_items_in_python` so
  the fallback path correctly filters those types
- `year` and `firstaired` added to the properties list fetched by
  `get_episodes_with_filters` (needed for Python-side filtering and logging)
- Filter dict logged before each filtered query for easier diagnosis

**Files changed:** `resources/lib/library.py` only

---

## Version 1.1.2aj

**Feature: Per-show episode filters for TV channels**

TV channels can now have episode-level filters applied per individual show.
Filters control which episodes are eligible for queuing — independently for
each show in the channel.

**Supported filter types:**
- **Watched / Unwatched** — queue only episodes the user has watched, or
  only episodes not yet watched. Uses live Kodi playcount (not cached).
- **Season** — filter by season number with =, >=, <=, >, < comparison.
  Example: "Season >= 2" queues only episodes from season 2 onwards.
- **First Aired** — filter by air date (YYYY-MM-DD) with after/before/on
  comparison. Example: "after 2020-01-01" queues only episodes aired after
  that date.

Filters can be combined (e.g. "Unwatched AND Season >= 2"). Multiple filters
for the same show are AND-combined by default.

**Where to set them:**
Channel wizard → Step 4a-iv (after Episodes Per Slot and Per-Show Randomize).
The step is offered as an opt-in question. For existing channels with filters
already set, the step is entered automatically so existing filters are visible.
Filters are shown and edited per show, one show at a time.

**How they work:**
Per-show filters are stored in `channels.json` as `episode_filters: [...]`
on each show dict (alongside `episodes_per_slot` and `randomize`). At queue-
build time, `_build_fresh_queue` and `_topup_queue` call
`get_episodes_with_filters` (live DB, not cached) when a show has filters,
and `get_episodes_for_show` (cached) otherwise. No performance impact on
shows without filters.

**What does NOT change:**
- Shows without `episode_filters` follow the identical code path as before
- Movie, folder, and serial channels are untouched
- State advancement, resume, skip detection — all untouched
- Exhaustion check (`is_channel_exhausted`) uses unfiltered episode list,
  which is correct — exhaustion reflects what the filter left available

**Files changed:** `resources/lib/library.py` (field_map + season/firstaired
handlers in `build_jrpc_filter`; `firstaired` added to
`get_episodes_with_filters` properties), `resources/lib/channel_manager.py`
(`_build_fresh_queue` and `_topup_queue` pre-load loops),
`resources/lib/ui/channels.py` (Step 4a-iv + `_build_episode_filters`
method), `resources/language/resource.language.en_gb/strings.po`
(`#32537`–`#32547` added; highest ID now `#32547`, total 347)

---

## Version 1.1.2ai

**Fix: Resume position lost after resuming and stopping again**

Root cause: `_do_resume_check` cleared the resume key from state.json
immediately after seeking to the saved position. The poll timer was
restarted at the same time (60s interval). If the user stopped playback
before the first poll save fired, `_last_polled_pos` was still None,
`onPlayBackStopped` had no fallback, and the resume key was gone from
state.json. The next channel open found nothing to resume from.

Fix: Removed the premature clear from `_do_resume_check`. The resume key
now stays in state.json until `save_resume_position` overwrites it with a
fresh position on the first poll save. Since both the old and new key use
the same state.json key for the same item, `save_resume_position` naturally
replaces the old value — there is never a moment where the key is absent.
The `position <= 10` guard in `get_resume_position` prevents a spurious
resume dialog if the user chose Start Over and stopped before the poll
had time to write a position past 10 seconds.

This fix applies to all channel types (TV, movie, folder) — the clear
was in the shared `_do_resume_check` path.

**Files changed:** `service.py`

---

## Version 1.1.2ah

**Fix: Folder channel resume position not saved to state.json**

Root cause: `save_resume_position`, `get_resume_position`, and
`clear_resume_position` all used `episodeid` or `movieid` as the state key.
Folder items have `episodeid=-1` and `movieid=-1`, so the `item_id < 0`
guard silently returned before writing anything. "Poll save written" appeared
in the log because that message logs after calling `save_resume_position` —
not after confirming it actually wrote. No `[ChannelManager] Resume saved:`
line ever appeared because the function exited before reaching it.

Fix: Added `_resume_key_for_item(item)` static helper that generates the
correct state.json key for any item type. Folder items use
`resume:<channel_id>:file:<md5_of_filepath[:16]>` as the key, keyed on a
16-character MD5 of the file path. `save_resume_position`,
`get_resume_position`, and `clear_resume_position` all now use this helper.

**Fix: Folder channel queue rebuilds randomly on every channel open**

Root cause: `_resume_from_existing_queue` had no folder channel path. Folder
items fell through to the TV queue logic, which could return None and trigger
a fresh random `FolderQueueBuilder` rebuild, discarding the existing queue
and often excluding the file that had a saved resume position.

Fix: Added folder channel early-return in `_resume_from_existing_queue`
(before the movie channel check) that returns the existing queue directly
without rebuilding. Same pattern as movie channels. Top-up continues to
handle queue refilling normally.

**Fix: _do_resume_check bailed out for folder items**

Root cause: `_do_resume_check` computed `item_id = episodeid` for folder
items (which is -1) and returned early before calling `get_resume_position`.

Fix: Guard now only bails out for non-folder items with no valid ID. Folder
items skip the early return and proceed to `get_resume_position` which uses
the file-path MD5 key.

**Feature: Folder channel resume minimum duration setting**

New setting in Settings → Resume: "Folder channel resume minimum duration
(seconds, 0=always resume)". Default 120 seconds. When set, folder items
with a total duration below this threshold are not eligible for resume.
Items interleaved from a folder channel into another channel are never
eligible for resume (resume applies to the primary channel only).

Safety net: `FolderQueueBuilder` now moves the resume file to position 0
of the shuffled list before slicing to target_size, guaranteeing it is
always present in a newly built queue even when randomize=True. The primary
guarantee is the no-rebuild fix above — this is defence-in-depth.

**Files changed:** `resources/lib/channel_manager.py`,
`resources/lib/channels/folder.py`, `service.py`,
`resources/settings.xml`,
`resources/language/resource.language.en_gb/strings.po`
(`#32536` added — strings.po last ID now `#32536`, total 336)

---

## Version 1.1.2ag

**Fix: _current_ep None after resume seek — poll saves no position**

1.1.2af correctly restarted the poll timer after resume seek. But the poll
timer's _poll_save() checks `if ep:` where ep = self._current_ep. After
onPlayBackStopped clears _current_ep = None, and set_now_playing is never
called (same file, no file change detected), _current_ep stays None for the
entire resumed session. _poll_save fires every 60s but does nothing because
ep is None. _last_polled_pos is never set. onPlayBackStopped has no fallback.

Fix: _do_resume_check now restores _current_ep from the episode it
successfully identified when performing the resume seek, but only if
_current_ep is currently None. This is safe — the ep was found by scanning
the queue file and confirmed to match the playing file.

With this fix the complete resume chain works:
1. _do_resume_check seeks to saved position
2. _current_ep restored if None
3. _start_poll_timer called
4. _poll_save fires at 60s intervals, finds ep, saves position to
   _last_polled_pos and state.json
5. onPlayBackStopped uses last polled pos as fallback when getTime() fails
6. Next open offers resume at correct accumulated position

Files changed: service.py



**Fix: poll timer never restarted after resume seek — root cause identified**

All previous fixes (1.1.2ac through 1.1.2ae) were treating symptoms.
This fixes the actual root cause.

Root cause: The poll timer is started by `set_now_playing()`, which is
called from `_check_now_playing()` when a NEW file is detected. After a
resume seek, the file path has not changed (same episode), so
`_check_now_playing()` returns early at the "same file" guard and never
calls `set_now_playing()`. The poll timer stays dead for the entire resumed
session, so `_last_polled_pos` is never updated and `onPlayBackStopped` has
no fallback position to save.

Fix: `_do_resume_check()` now calls `_start_poll_timer()` after a
successful resume seek. `_start_poll_timer()` always cancels any existing
timer before creating a new one, so there is no race or double-timer issue.

With this fix, the poll timer fires at 60s intervals from the seek point,
`_last_polled_pos` is updated each tick, and `onPlayBackStopped` always has
a valid fallback position even when `getTime()` fails or `_current_ep` is
None.

Files changed: service.py



**Fix: resume not saved after resume-seek when _current_ep is None at stop**

After a resume seek (user accepts resume dialog, Kodi seeks to saved position),
`_current_ep` is sometimes None when `onPlayBackStopped` fires. Root cause not
fully determined (likely a Kodi callback timing race between the seek completing
and the service loop re-registering the episode), but the effect is clear:
`ep=None` means the resume save is skipped entirely.

Fix: `onPlayBackStopped` now always falls back to `_last_polled_pos` when
the primary save path fails for any reason (ep=None, getTime() exception,
or position too early). `_last_polled_pos` stores the last (ep, pos, total)
tuple saved by the poll timer. When ep is None, the polled ep is used.
When ep is set but getTime() fails, the polled position is used.

The fallback covers all three failure modes:
1. ep=None + polled pos available → use polled ep + polled pos
2. ep=set + getTime() throws → use current ep + polled pos (previous fix)
3. ep=set + getTime() returns → use current ep + live pos (normal path)

Also improved logging to distinguish these cases and report
is_stop_channel status when resume is not saved.

Files changed: service.py



**Fix: resume position not saved when switching channels while playing**

Two separate bugs, both in `service.py`:

**Bug 1 (from 1.1.2ac):** `onPlayBackStopped` cleared `_current_ep` but not
`_current_file`. When the same episode was replayed, `_check_now_playing`
found `playing_file == _current_file` and returned early — never calling
`set_now_playing`, so the poll timer never restarted. Fixed in 1.1.2ac.

**Bug 2 (this version):** When `open_channel` is selected while playing,
Kodi fires `onPlayBackStopped` as soon as the current playlist is cleared.
By that point, `getTime()` throws `"Kodi is not playing any media file"`
because playback has already ended. The resume position was lost entirely.

Fix: `_poll_save` now caches the last successfully polled position in
`_last_polled_pos`. When `onPlayBackStopped` catches a `getTime()` exception,
it falls back to `_last_polled_pos` if it matches the current episode and
is > 10 seconds. The last known position is saved correctly.

`_last_polled_pos` is cleared on stop and on natural episode end so it
never carries a stale position into the next episode.

Files changed: service.py



**Fix: poll timer (resume save) not restarting after replaying same episode**

Root cause: `onPlayBackStopped` cleared `_current_ep` but not `_current_file`.
When the same episode was opened again (e.g. after stopping and resuming),
`_check_now_playing` found `playing_file == self._current_file` and returned
early — never calling `set_now_playing`, which is the only place the poll
timer is started. Result: resume position was saved once (at the 60s mark
from the previous session) but never updated thereafter.

Fix: `onPlayBackStopped` now also clears `_current_file = None`.
On the next play of any file (same or different), `_check_now_playing`
detects it as a new file, calls `set_now_playing`, and starts the poll timer.

One line added to `onPlayBackStopped`. No other changes.

Files changed: service.py



**Repo Submission Blockers: xbmcvfs, artwork, addon.xml**

### 1. Replaced all bare open() calls with xbmcvfs.File

Kodi addon repo policy requires all file I/O to go through xbmcvfs.
The following fallback paths that used Python's built-in open() have
been replaced with xbmcvfs.File:

- `service.py` — `_persist_queue()` and `_update_queue_file()` local
  fallback paths after xbmcvfs.copy fails on local mapped drives
- `player.py` — `_write_now_playing()` local fallback path
- `resources/lib/utils/paths.py` — `save_json()` local fallback path
- `resources/lib/library.py` — cache write fallback (2 paths)
- `resources/lib/router.py` — backup restore temp file write

All fallback paths now use xbmcvfs.File exclusively.
Full grep confirms zero bare open() calls remain in the codebase.

### 2. Added icon.png and fanart.jpg

- `icon.png` — 256×256 PNG: deep navy background, amber scanline stripes,
  "SC" monogram on a rounded rectangle backdrop
- `fanart.jpg` — 1280×720 JPEG: widescreen dark gradient with stylised
  EPG grid suggesting a programme guide, addon name and tagline

### 3. Updated addon.xml

Added required metadata fields:
- `forum_url` — Kodi forum URL
- `source` — GitHub source URL
- `news_url` — GitHub releases URL
- Expanded `description` with feature list

### Full audit results (pre-package)
- Bare open(): NONE
- executeJSONRPC outside library.py: NONE (log/comment refs only)
- Hardcoded user-visible strings: NONE
- Strings: 335 total, zero duplicates, zero broken
- Syntax: all .py files pass

Files changed: service.py, resources/lib/player.py,
               resources/lib/utils/paths.py, resources/lib/library.py,
               resources/lib/router.py, addon.xml,
               icon.png (new), fanart.jpg (new)



**Fix: reset_watched_episode error 'str' object has no attribute 'get'**

Root cause: `LibraryClient._rpc()` returns `data["result"]` directly.
For `VideoLibrary.SetEpisodeDetails` and `SetMovieDetails`, Kodi's JSON-RPC
returns `"result": "OK"` — a string, not a dict. The reset_watched methods
called `.get("result")` on that string, causing AttributeError.

The error was caught and logged as a warning, so playback was never
interrupted. Resume was also not broken — it was working correctly
throughout. The log showed normal resume save/load behaviour.

Fix: check `result == "OK"` instead of `result.get("result") == "OK"`
in both `reset_watched_episode()` and `reset_watched_movie()`.

Files changed: resources/lib/library.py



**Feature: Reset Watched Status**

New setting in Settings → Playback: "Reset watched status after each item
plays" (default: off).

When enabled, after each TV episode or movie completes naturally, the addon
resets its watched/playcount status in the Kodi library back to unwatched
(playcount=0). This keeps the Kodi library clean when using the addon for
continuous rotation playback — episodes don't pile up as "watched" and
remain available for smart playlists, recently added views, etc.

### Implementation
- `library.py` — two new methods: `reset_watched_episode(episodeid)` and
  `reset_watched_movie(movieid)`. Both call `VideoLibrary.SetEpisodeDetails`
  / `SetMovieDetails` with `playcount=0` via JSON-RPC. Errors are caught
  and logged — never crash playback.
- `service.py` — new `_reset_watched_if_enabled()` method on
  `SmartChannelsService`. Called after `advance_state` (TV/serial) and
  after `_advance_movie_state` (movies). Not called for folder items,
  skipped items, or errors.
- `settings.xml` — new `reset_watched` bool setting (default false).
- `strings.po` — new string #32534.

### Also: handoff document updated to reflect 1.1.2y/z state

Files changed: resources/lib/library.py, service.py,
               resources/settings.xml,
               resources/language/resource.language.en_gb/strings.po,
               SMARTCHANNELS_HANDOFF.md



**Feature: user-configurable suppression of CUN during silent interleave items**

CUN was firing during silent item (bumper/commercial) playback, showing the
same next-episode message that already appeared at the end of the preceding
TV episode. Added a user setting so the user can choose the behaviour.

New setting: "Suppress Coming Up Next during silent interleave items"
(Settings → Coming Up Next, default: on)

- On (default): CUN is suppressed during bumper/silent item playback.
  No redundant announcement.
- Off: CUN fires normally during silent items, showing what plays next
  after the bumper. User sees the next episode title during the bumper.

New string #32533. New setting `cun_suppress_silent` (bool, default true).

Files changed: service.py, resources/settings.xml,
               resources/language/resource.language.en_gb/strings.po


**Fix: serial top-up starting from wrong episode after fully-queued wrap**

1.1.2w introduced `fully_queued` set to skip `current_queue` on second pass
through a show, but fell through to the state pointer — which is left at an
arbitrary mid-cycle episode when scrubbing rapidly. Result: top-up always
started from wherever state was (E5), not E1.

Fix: when `show_idx in fully_queued`, set `start_idx=0` unconditionally.
Never use state as fallback for a fully-queued show. The next cycle must
always start from E1 regardless of what rapid scrubbing left in state.

Changes from 1.1.2r: `fully_queued` set + `if show_idx in fully_queued:
start_idx=0` checked before all other paths + `fully_queued.add(show_idx)`.

Files changed: resources/lib/channels/serial.py

---

## Version 1.1.2w

**Fix: serial top-up — correct minimal fix from 1.1.2r base**

Starts from exact 1.1.2r serial.py. Adds a `fully_queued` set to track
which show indices had all their episodes already in current_queue.
On a second pass through such a show, the current_queue scan is skipped
and the state pointer is used instead (same as 1.1.2r two-show behaviour).

Changes from 1.1.2r: 3 lines added, nothing removed.

Files changed: resources/lib/channels/serial.py

---

## Version 1.1.2v

**Fix: serial top-up regression introduced in 1.1.2s**

serial.py was identical and working from 1.1.2a through 1.1.2r.
Versions 1.1.2s, 1.1.2t, and 1.1.2u all broke it with increasingly
complex attempts to fix a rapid-scrub edge case.

This version reverts serial.py to the 1.1.2r base (known working) and
applies a single minimal fix: when the "fully queued" path fires (all
episodes of the show are already in current_queue), set current_queue=None
so the next pass through the same show falls through to the state pointer
(reset to E1 by advance_show) rather than re-finding the same last-queued
episode and looping indefinitely.

The entire change from 1.1.2r is one added line: current_queue = None.

Files changed: resources/lib/channels/serial.py


**Fix: serial channel top-up repeating episodes 8, 9, 10 on single-show channels**

Root cause: after the first wrapped pass through the show added episodes
up to the build target and exited, subsequent passes entered the
`wrapped_shows` branch which checked `last_added` from the pre-wrap pass
(ep E10) and correctly fired the "fully built" guard — but then the
`max_visits` bump allowed more loop iterations. These extra passes fell
through to the state pointer (now at E8 in cycle 2 due to rapid
advance_state calls from scrubbing), producing E8/E9/E10 in a loop.

Fix: the `wrapped_shows` branch now tracks `last_added` independently for
post-wrap passes. When a post-wrap pass successfully adds episodes, it
records the last ep added under `last_added[show_idx]`. The next post-wrap
pass finds it there, advances past it, and exits when the show is fully
built — breaking the loop cleanly.

Files changed: resources/lib/channels/serial.py


**Fix: serial top-up repeating E8/E9/E10 after skipping**

Root cause: when `last_added` detected a show was fully queued for a cycle
and marked it in `wrapped_shows`, the next pass through the same show fell
through to the `elif next_id` state pointer path. After a skip-cascade,
`next_id` points to whatever episode skip detection last wrote — often E9
or E10, not E1. So each wrapped pass started from E8/E9 instead of E1,
producing the same tail episodes repeating.

Fix: added an explicit `elif show_idx in wrapped_shows: start_idx = 0`
branch. When a show has completed a full cycle in the current build call,
the next pass always starts from episode 0 regardless of the state pointer.
Also clears `last_added[show_idx]` when marking a show as wrapped so the
`last_added` path doesn't interfere on the subsequent E0-start pass.

Files changed: resources/lib/channels/serial.py



**Fix: serial channel top-up produces only S01E10 repeatedly after skipping**

Root cause: `SerialQueueBuilder.build()` scans `current_queue` (reversed)
to find the last queued episode for each show, then starts building after
it. The problem: `current_queue` does not change between loop iterations.
After adding E10 and incrementing `show_idx`, the loop wraps back to the
same show and scans the same `current_queue` — finding E9 again, computing
`start_idx=9`, adding just E10, then repeating. Each iteration added only
1 episode (E10) producing a queue of all-E10.

This happened after skipping because skip detection advanced state through
all episodes rapidly, leaving the queue file trimmed to a small window that
had E9 near the end.

Fix: added `last_added` dict `{show_idx: episodeid}` that tracks the last
episode added from each show IN THIS BUILD CALL. On subsequent passes
through the same show, `last_added` is checked first and used instead of
re-scanning `current_queue`. This correctly advances the start position on
each loop iteration so the builder produces a full episode sequence.

Also removed a duplicate `else` block left over from the previous refactor.

Files changed: resources/lib/channels/serial.py



**Fix: serial channel top-up stops working after one cycle on single-show channels**

Root cause: `SerialQueueBuilder.build()` uses a `visited > max_visits` guard
to prevent infinite loops. For a single-show serial channel with recycle=True:

1. Top-up finds the last queued ep (e.g. S1E10) at `start_idx=10`
2. `start_idx >= len(episodes)` → logs "fully queued", `show_idx=1`, `visited=1`
3. `show_idx >= len(shows)` → wraps to `show_idx=0`, `visited=2`
4. Finds S1E10 again in current_queue → "fully queued" again, `visited=3`
5. `visited=3 > max_visits=2` → breaks with almost nothing built

Each top-up cycle produced fewer and fewer items (6, 5, 1...) until the
queue ran dry and playback stopped.

Fix: three changes to `serial.py`:

1. `wrapped_shows` set tracks which show indices have already been marked
   "fully queued" in the current build call.

2. When a show wraps back around (second pass), `max_visits` is increased
   to allow completing the new cycle.

3. When a show is in `wrapped_shows`, the `current_queue` lookup is skipped
   for that show so it falls back to the state pointer (which was reset to
   S01E01 by `advance_show`), allowing episodes to be built from the start.

Result: single-show serial channels with recycle=True now top up correctly
through any number of full-series cycles.

Files changed: resources/lib/channels/serial.py



**Fix: silent folder items showing filename on OSD instead of channel name**

Root cause: `_apply_interleave` in channel_manager.py built a temporary
channel dict containing only `{"interleave": interleave_cfg}` — no `"name"`
key. `apply_interleave_list` calls `channel.get("name", "")` to set
`_channel_name` on silent items, so it always got an empty string.
`_make_listitem` then checked `ep.get("_channel_name")` which was falsy,
fell through, and used the item's own filename-derived title instead.

Fix: `_apply_interleave` now accepts a `channel_name` parameter and includes
it in the temporary channel dict. All three call sites (build_fresh_queue,
refill_queue, regenerate_queue) pass `channel.get("name", "")`.

Silent items now correctly carry the primary channel name in `_channel_name`,
and `_make_listitem` displays it on the OSD.

**User action required:** delete the queue file for your interleave channel
and let it rebuild so items get the correct `_channel_name` tag.

Files changed: resources/lib/channel_manager.py



**Fix: silent items consuming slots from "Number of upcoming programs" count**

The upcoming programs list was sliced to `_num_up` items before filtering
out silent items, so each silent item within the first N queue positions
caused one visible slot to go missing.

Fix: the full queue is now filtered to remove `_silent` items first, then
`_num_up` is applied to the filtered result. The visible count is always
exactly what the user configured regardless of how many silent items are
present in the queue.

Files changed: resources/lib/ui/channels.py



**Fix: silent/folder items showing "0x" prefix in Kodi internal playlist**

Root cause: folder items and silent interleave items have no season/episode
data (season=0, episode=0). `_make_listitem` was setting `mediatype: episode`
for all non-movie items, causing Kodi to auto-format the label as "0x" (S00E00
collapsed) in the internal video playlist.

Fix: folder items (`is_folder_item: True`) and silent items (`_silent: True`)
now use `mediatype: video` with the label as the title. Regular TV episodes
continue to use `mediatype: episode` as before.

For silent items the label is already the primary channel name (set by
`_make_listitem` from `_channel_name`), so Kodi's internal playlist now
shows the channel name instead of "0x".

Files changed: resources/lib/player.py



**Fix: silent interleave items appearing in addon playlist; wrong "Movie" label**

Two bugs in the TV channel queue display in `ui/channels.py`:

1. Silent items (`_silent: True`) were appearing in the addon's own playlist
   view. They should be invisible there — they only appear in Kodi's internal
   video playlist. Fixed by skipping `_silent` items in both the
   `upcoming_items` loop and the `interleaved_pending` collection.

2. `_is_movie` was using `_item.get("_interleaved")` as a movie signal.
   Since all interleaved items (including silent folder/bumper items) have
   `_interleaved: True`, folder items were being labelled "[Movie]".
   Fixed: `_is_movie` now checks `is_movie`, `movieid`, and the absence of
   `tvshowtitle` + `is_folder_item` — not `_interleaved`.

Files changed: resources/lib/ui/channels.py



**Fix: folder channel not working as interleave source**

Root cause: `_build_fresh_queue` had routing for serial, movies, and TV
channel types but was missing the folder channel route. When a folder
channel was used as an interleave source, `_load_foreign_items` called
`_build_fresh_queue` which fell through to the TV episode builder, found
no shows, logged "no episodes found for any show", and returned empty.

Note: `build_queue` (the public method) already had the folder route
correctly. Only `_build_fresh_queue` (the internal method called by
`_load_foreign_items`) was missing it.

Fix: added `channel_type == "folder"` route to `_build_fresh_queue`
routing it to `FolderQueueBuilder`, identical to the existing route in
`build_queue`. Folder channels now work correctly as both silent and
non-silent interleave sources.

Also improved error logging in `_load_foreign_items` to include channel
name and type in error messages.

Files changed: resources/lib/channel_manager.py



**Diagnostic: surface folder channel interleave failure cause**

`_load_foreign_items` was catching all exceptions silently, making it
impossible to diagnose why folder channels fail as interleave sources.

Added detailed logging:
- Logs channel name and type before attempting the build
- Logs item count returned after the build
- On exception: logs channel name, type, error message, and full traceback

This version is diagnostic only — no behaviour change. The actual fix
will follow once the log confirms the root cause.

Files changed: resources/lib/channel_manager.py



**Fix: dialog formatting; Add Source shows current sources; folder channel note**

### Changes

- `strings.po`: Added brackets to #32499 ([Done]), #32531 ([Edit / Remove
  Sources]) so all four action items have consistent formatting.

- `ui/channels.py`: Add Source picker title now shows currently configured
  source names when sources already exist, e.g.:
  "Source channel: (Interleave Sources: Movies Channel, Bumpers)"
  This makes it clear what is already configured before adding another source.

### Folder channel as interleave source

Folder channels work correctly as interleave sources when the folder path
is network-accessible (smb:// or NAS path). A Windows local path such as
D:\\Bumpers will work on the Windows PC but not on the Shield, because
the Shield cannot access Windows local drive paths. To use a folder channel
as a silent interleave source on the Shield, configure the folder channel
with an SMB path (e.g. smb://SERVER/D/Bumpers) instead of a local path.
No code change needed — this is a path configuration issue.

Files changed: resources/language/resource.language.en_gb/strings.po,
               resources/lib/ui/channels.py



**Redesign: Interleave Sources dialog is actions-only; individual source removal added**

The main "Interleave Sources" dialog now shows only actions — no channels
listed inline. Sources are accessed via a dedicated "Edit / Remove Sources"
step. The Add Source picker splits candidates into two groups.

### New dialog layout

**When no sources configured:**
- [Add Source]
- [Remove All Interleave]
- Done

**When sources exist:**
- [Add Source]
- [Edit / Remove Sources]
- [Remove All Interleave]
- Done

### Edit / Remove Sources
Selecting this opens a second list showing only the configured sources
for this channel. Selecting any source opens a sub-menu:
- Edit (frequency / jitter / count_per / silent toggle)
- Remove this source  ← removes one source, not all

### Add Source picker — grouped
Eligible channels are split into two groups:
- Group 1: channels with no interleave configured (clean sources)
- Group 2 (separated): channels that themselves have interleave configured
  (still valid sources — their interleave is independent)
Circular references are excluded from both groups.

### Also fixed
- Removed broken fallthrough block left over from previous rewrite
- #32531 "Edit / Remove Sources" — new string
- #32532 "--- Channels with interleave configured ---" — new separator string
- #32517 "No interleave sources configured" now orphaned (no longer shown
  in main dialog — actions-only design has no placeholder text)

Files changed: resources/lib/ui/channels.py,
               resources/language/resource.language.en_gb/strings.po



**Fix: crash on channel list when interleave is list format; Done moved to bottom**

Three fixes:

1. `_add_channel_item()` in `ui/channels.py` called `il_cfg.get("channel_id")`
   directly on the interleave config. When the config is the new list format,
   this crashes with `AttributeError: 'list' object has no attribute 'get'`.
   Fix: use `get_sources(ch)` to normalise the config. Channel list now shows
   the first source name + count of additional sources (e.g. "+IL:Movies/3 +1").

2. Same crash in the channel detail/info view. Fix: same approach — iterate
   all sources via `get_sources()`, appending one line per source with the
   [silent] badge where applicable.

3. "[Done]" moved from first position to last position in the Interleave
   Sources dialog, after [Remove All Interleave]. List order is now:
   sources → [Add Source] → [Remove All Interleave] → [Done].

Files changed: resources/lib/ui/channels.py



**Fix: no clear way to exit the Interleave Sources dialog**

The dialog loop had no obvious exit — the only way out was pressing
Back/Escape on the remote, which is not discoverable. Added "[Done]"
as the first row in the source list. Selecting it (or pressing Back)
returns to the channel list. Uses existing string #32499 ("Done").

Files changed: resources/lib/ui/channels.py



**Fix: [Add Source] triggering Remove All confirmation dialog**

Root cause: the index guard for "Remove All Interleave" had a redundant
`not sources and choice == 1` condition. When no sources are configured,
the list is [placeholder, Add Source, Remove All] at indices 0/1/2.
`add_idx = 1` and `remove_all_idx = 2` were correct, but the extra
`choice == 1` branch in the Remove All guard fired before the Add Source
guard could run, causing Add Source to show the Remove All confirmation.

Fix: removed the redundant conditions. Both guards now check only against
`add_idx` and `remove_all_idx`, which are calculated correctly for both
the empty-sources and has-sources cases.

Files changed: resources/lib/ui/channels.py



**Feature: Unified Interleave UI — multi-source Manage Interleave dialog**

Replaces the old single-source interleave dialog entirely. The new dialog
supports multiple interleave sources per channel and the silent flag toggle,
all configured through the Kodi UI without editing channels.json.

### New dialog flow

1. **Source list** — shows all configured sources with name, [silent] badge,
   and frequency summary. Two fixed options at bottom: [Add Source] and
   [Remove All Interleave].

2. **Select an existing source** → sub-menu:
   - Edit (frequency/jitter/count_per/silent) — same numeric inputs as before
   - Remove this source

3. **[Add Source]** → channel picker (circular references automatically
   excluded) → frequency/jitter/count_per → silent toggle → saved and
   queue regenerated.

4. **[Remove All]** → confirmation → strips all interleave and regenerates.

### Technical changes

- `ui/channels.py` — `manage_interleave_dialog()` completely rewritten:
    - List-based loop (while True) stays open between actions
    - `_would_be_circular()` now follows ALL sources in a list config,
      not just the first single-dict source
    - `_source_input_dialog()` new private helper: collects all parameters
      for one source and returns a dict (or None on cancel)
    - Saves interleave as a list in channels.json (new format)
    - Legacy single-dict configs still load correctly via get_sources() shim

- Strings #32516–#32530 now fully wired to code (previously orphaned/reserved)
- Old single-source strings #32183–#32191 and #32497 are now orphaned
  (no longer referenced — harmless, kept for reference)

### What does NOT change
- `service.py`, `channel_manager.py`, `player.py`, `router.py` — untouched
- Queue file format — untouched
- All existing channel behaviour — untouched

Files changed: resources/lib/ui/channels.py



**Fix: CUN announcing silent interleave items; all source channel types now supported**

Two bugs fixed:

1. `_write_now_playing()` in `player.py` builds fixed dicts for queue
   entries and was not preserving `_silent` or `_channel_name` for any
   item type. When `_get_next_episode` read the queue file to find the
   CUN item, the silent flag was absent so the filter did not skip it.

   Fix: both the movie branch and the TV/folder branch now preserve
   `_silent` and `_channel_name` alongside `_interleaved`.

2. The TV/folder branch also did not preserve `_interleaved` or
   `is_folder_item`. Fixed in the same pass — folder items now correctly
   round-trip through the queue file with all flags intact.

3. `_make_listitem()` silent label check fires first (before movie/TV/folder
   branching) so the channel name OSD label works for all source types:
   movies, TV episodes, and folder items (bumpers, commercials, station IDs).

Files changed: resources/lib/player.py



**Redesign: silent interleave uses queue-weaving instead of runtime injection**

The runtime playlist injection approach (1.1.2c/d) was unreliable — Kodi
commits to the next playlist item before onPlayBackEnded fires, so any
insert arrived too late. Silent sources now use the same queue-weaving path
as non-silent sources, making them reliable and architecturally consistent.

### What changes

- `channels/interleave.py` — rewritten:
    - `apply_interleave_list()` now processes ALL sources (silent and
      non-silent). Previously it skipped silent sources.
    - `_weave_single_source()` tags silent items with `_silent: True`
      and `_channel_name: <primary channel name>` so the OSD and CUN
      know how to treat them.
    - `fire_silent_sources()` removed — no longer needed.

- `player.py` — `_make_listitem()` extended:
    - If `ep.get("_silent")` and `ep.get("_channel_name")` are set,
      the ListItem label is set to the primary channel name instead of
      the item's own title. The OSD shows the channel name throughout
      the silent item's playback.

- `channel_manager.py`:
    - `fetch_silent_items()` removed — no longer needed.
    - `fire_silent_sources` import removed.

- `service.py`:
    - `_silent_pending` counter removed from `__init__`.
    - Silent guard removed from top of `_handle_end`.
    - Runtime injection block removed from counter section of `_handle_end`.
    - `_get_next_episode()` CUN filter (`_silent` skip) retained — silent
      items are now in the queue file, so the filter is more important
      than ever.

### What "silent" means now
Silent items are woven into the queue file exactly like non-silent items.
The differences are:
  - OSD shows the primary channel name (not the bumper title)
  - Coming Up Next skips them — shows the next real TV episode
  - They appear in Kodi's playlist if the user opens it (unavoidable)
  - Movie state advances normally when they complete

### User action required after install
Delete `queue_a046429c-....json` before playing "Test Interleave" so
the queue rebuilds with silent items correctly woven in.

Files changed: resources/lib/channels/interleave.py,
               resources/lib/channel_manager.py,
               resources/lib/player.py,
               service.py



**Fix: silent item plays after next TV episode instead of before it**

Root cause: when `onPlayBackEnded` fires, Kodi has already advanced its
internal playlist cursor to the next item and begun loading it. Using
`getposition() + 1` as the insert index placed the silent item two steps
ahead — after the TV episode that was already loading — instead of
immediately next.

Fix: insert at `getposition()` (no +1). At `onPlayBackEnded` time,
`getposition()` already points to the next item. Inserting there pushes
the TV episode one slot forward and places the silent movie directly in
front of it, so the sequence is: TV episode ends → silent movie → TV
resumes.

Files changed: service.py



**Feature: Unified Interleave — silent source firing**

Silent interleave sources now play invisibly between primary channel items.
When a silent source's counter fires, its items are injected directly into
Kodi's live playlist immediately after the current item. They are never
written to the queue file, never appear in Coming Up Next, and the
on-screen channel label does not change.

### What changes

- `channels/interleave.py` — new public function `fire_silent_sources()`:
    - Loops over fired source configs, skipping non-silent ones
    - Calls `get_foreign_items_fn` to fetch `count_per` items per source
    - Tags each item: `_silent: True`, `_interleaved: True`, `_channel_id`
    - Returns flat list of tagged items for the caller to inject

- `channel_manager.py` — new public method `fetch_silent_items()`:
    - Wraps `_load_foreign_items` as a closure and passes to
      `fire_silent_sources()` so library access stays inside CM
    - Called from service.py after `advance_interleave_counters` fires

- `service.py` — three changes:
    1. `SmartChannelsService.__init__`: new `_silent_pending` counter (int).
       Tracks how many silent items are currently in-flight in Kodi's playlist.
    2. `_handle_end()`: silent guard at top — if `_silent_pending > 0`,
       decrement and return immediately (no state advancement for silent items).
       Counter block extended: after firing, calls `fetch_silent_items()` and
       injects returned items into Kodi's playlist at `getposition() + 1`
       using `playlist.add(..., index=N)`. Increments `_silent_pending` by
       the count of items injected.
    3. `_get_next_episode()`: skips items where `_silent: True` when
       searching for the Coming Up Next item. Shows the next real primary
       item, not the silent one about to play.

### What does NOT change
- Queue file format — silent items never written to disk
- Non-silent interleave behaviour — unchanged
- `channels/base.py`, `ui/channels.py`, `router.py`, `settings.xml` — untouched
- No new strings — reserved IDs #32516–32530 remain for 1.1.2d (UI)

### Limitations in this version
- Silent sources can only be configured by editing `channels.json` directly
  (set `"silent": true` on a source in the interleave list). The UI dialog
  to configure silent sources is 1.1.2d.
- All existing interleave configs (`"silent"` key absent or `false`) continue
  to work identically.

Files changed: resources/lib/channels/interleave.py,
               resources/lib/channel_manager.py,
               service.py



**Fix: interleave counters only ticking on first episode completion**

Root cause: `_handle_end` was passing `channel_id` / `channel` (the item's
own channel, from `self._channel_id` / `self._channel`) to
`advance_interleave_counters`. For a multi-show TV channel, individual queue
items may carry a `channel_id` pointing to a foreign source channel when the
interleave source is itself a TV show channel. That foreign channel has no
interleave config, so `get_sources()` returned empty and the counter was
silently skipped for episodes 2, 3, … onward.

Fix: counter advancement now uses `self._primary_channel_id` (already tracked
on `PlaybackMonitor` for Coming Up Next) and resolves the primary channel
object from `_service_ref._get_channel()`. Falls back to the item's own
channel_id if primary is unavailable. The primary channel always carries the
interleave config.

Files changed: service.py



**Foundation: Unified Interleave — runtime counter model**

Introduces per-source interleave counters that track how many primary
channel items have completed since each source last fired. This is the
runtime bookkeeping layer that will drive silent source insertion in 1.1.2c.

### What changes

- `channels/interleave.py` — new public function `advance_counters()`:
    - Pure logic, no state I/O
    - Takes list of source configs + current counter dict
    - Increments each counter by 1 (one primary item completed)
    - Returns (updated_counters, fired_sources)
    - Fired sources have their counter reset to 0
    - Jitter is applied per-cycle when configured

- `channel_manager.py` — new public method `advance_interleave_counters()`:
    - Called by service.py on each primary TV episode completion
    - Reads counter state from state.json key "{channel_id}:interleave_counters"
    - Delegates pure logic to interleave.advance_counters()
    - Persists updated counters back to state.json
    - Returns list of fired source configs (empty list if no interleave)

- `service.py` — `_handle_end()` extended:
    - After advance_state(), calls advance_interleave_counters() via CM
    - Guard: only fires for primary TV episodes (not _interleaved items,
      not movies, not folder items — those already exit _handle_end early)
    - Errors are caught and logged as warnings — never crash playback

### What does NOT change
- Queue file format unchanged
- No new user-visible behaviour yet — counters tick in the log only
- `channels/base.py`, `ui/channels.py`, `router.py`, `settings.xml` untouched
- All existing channel types behave identically to 1.1.2a

### Counter state in state.json
Key: "{channel_id}:interleave_counters"
Value: {"source_channel_id": count_int, ...}
Counters reset to 0 on each fire. Not present for channels with no interleave.

### Next: 1.1.2c — silent source firing

Files changed: resources/lib/channels/interleave.py,
               resources/lib/channel_manager.py,
               service.py



**Foundation: Unified Interleave — data model and module scaffold**

Introduces `channels/interleave.py` as the single owner of all interleave
logic. This version contains zero behaviour change — existing single-source
interleave channels continue to work identically.

### What changes

- `channels/interleave.py` — replaces the previous stub with full
  implementation of:
    - `get_sources(channel)` — normalises interleave config transparently:
      old single-dict format and new list format both return a clean list
      of source configs. No data migration required.
    - `apply_interleave_list()` — weaves all non-silent sources into a
      queue in list order, each with its own independent frequency/jitter.
    - `get_all_foreign_ids()` — returns every foreign channel_id referenced.
    - `_weave_single_source()` — internal: weaves one source (mirrors the
      logic previously in channels/base.py apply_interleave).

- `channel_manager.py` — surgical updates only:
    - Imports from `channels/interleave.py` instead of `channels/base.py`
      for the interleave functions.
    - `_apply_interleave()` delegates to `apply_interleave_list()`.
    - New public method `get_interleave_sources(channel)` delegates to
      `interleave.get_sources()`.
    - Foreign channel ID guard updated to handle list format correctly.
    - `refill_queue` foreign_id extraction updated for list format.

- `strings.po` — reserved #32516–#32530 for Unified Interleave UI
  (dialog strings for 1.1.2d). No code references them yet.

### What does NOT change
- `channels/base.py` — `apply_interleave()` retained unchanged (not
  called by CM any more but kept for any future direct callers).
- `service.py`, `ui/channels.py`, `router.py` — untouched.
- `settings.xml` — untouched.
- Queue file format — untouched.
- All channel types behave identically to 1.1.1f.

### Next: 1.1.2b — counter model in service.py

Files changed: resources/lib/channels/interleave.py,
               resources/lib/channel_manager.py,
               resources/language/resource.language.en_gb/strings.po



**Feature: Coming Up Next minimum item duration setting**

New setting in Settings → Coming Up Next:
  "Minimum item duration to show overlay (seconds, 0 = always show)"
  Default: 120 seconds (2 minutes)

When the currently playing item's total duration (read live from Kodi's
player via getTotalTime()) is less than the configured minimum, the
Coming Up Next overlay is suppressed entirely. Set to 0 to restore the
original always-show behaviour.

Useful for Folder channels containing short bumpers, commercials, and
station IDs — these items are typically too short to warrant an overlay
and the overlay may not even have time to display before the item ends.

Implementation: check fires in service.py at the existing Coming Up Next
trigger point, before the lead-window calculation. Uses ADDON.getSetting()
directly since the value is an addon setting, not part of the CUN overlay
config dict.

New string: #32515
New setting: cun_min_duration (number, default 120)
Files changed: service.py, settings.xml, strings.po

---

## Version 1.1.1e

**Fix: Folder Channel top-up not working**

_topup_queue() in channel_manager.py had no route for folder channels.
When the queue dropped below threshold, refill_queue() called _topup_queue()
which checked for channel.get("shows") — folder channels have no shows —
logged "no shows in channel" and returned current_queue unchanged. The
queue never grew, playback eventually ran out of items.

Fix: added a folder channel route at the top of _topup_queue(), before
the movies and TV routes. Uses FolderQueueBuilder.build() directly to
generate topup_size new items from the folder path. Includes a join-
boundary duplicate check to prevent the same file playing twice at the
seam between current_queue and new_items.

Log after fix should show:
  [ChannelManager] Folder top-up: N items

File changed: channel_manager.py only.

---

## Version 1.1.1d

**Fix: Folder Channel — folder_path not saved to channels.json**

Root cause of all reported issues ("Path:" display, "No episodes found",
apparent delete failure):

create_channel() and update_channel() in channel_manager.py explicitly
list every key they copy from the definition dict. "folder_path" was
never added to either list, so the wizard's return value was silently
discarded. The channel was saved to channels.json without folder_path,
causing FolderQueueBuilder to log "No folder_path in channel" and return
an empty queue every time.

Fix: added "folder_path" to both create_channel() and update_channel()
dict construction in channel_manager.py.

The "delete not working" appearance was a Kodi timing issue —
Container.Refresh called from within a plugin script does not always
take effect before the script exits. The channel WAS deleted from
channels.json (confirmed in log: "Deleted channel id=..."). A manual
navigation refresh would have shown the correct state.

Action required: delete the existing Folder test channel (which has no
folder_path) and recreate it with 1.1.1d. The new channel will correctly
store and use the folder path.

File changed: channel_manager.py only.

---

## Version 1.1.1c

**Fix: Folder Channel playback — items not advancing after first item**

Two issues in service.py prevented Folder Channel items from playing
correctly after the first item:

1. _handle_end(): Folder items have show_id=0 (falsy). The existing
   code at line 807 checked "if not show_id: return" — this silently
   aborted end-of-item handling for folder items, so the queue never
   advanced and the channel stalled after the first file.
   Fix: added explicit "is_folder_item" check before the show_id check.
   Folder items return immediately from _handle_end — they have no
   library state to update. Queue advancement happens via _update_queue_file
   which is position-based and works correctly for all channel types.

2. _find_resume_position(): Added explicit folder queue detection
   (is_folder_item=True) to return 0 immediately, same as movie queues.
   Previously folder queues fell through to the TV state.json lookup
   which happened to return 0 correctly by coincidence (episodeid=-1
   never matches any state entry). Now it's explicit and documented.

Files changed: service.py, resources/lib/channels/folder.py (1.1.1b
fixes for _accessible_path included), resources/lib/ui/channels.py.

---

## Version 1.1.1b

**Fix: Folder Channel — "Folder not accessible" on Windows local paths**

Root cause: _ensure_slash() only added a trailing slash for network paths
(those containing "://"). Local Windows paths like "D:\Bumpers, Openings,
etc" got no trailing separator. xbmcvfs.exists() on a local directory
without a trailing separator returns False on Windows, causing the wizard
to show "Folder not accessible" even for valid folders.

Fix: _ensure_slash() now adds a trailing backslash for local paths too.
Added _accessible_path() to folder.py — tries multiple path forms in
order (with trailing slash, with forward slash, bare) until one succeeds.
Used in the wizard validation, FolderQueueBuilder.build(), and _walk().

channels.py wizard now imports _accessible_path instead of _ensure_slash
for the folder validation step. No other files changed.

---

## Version 1.1.1a — Folder Channel Feature Release

**Feature: Folder/Directory Source Channel**

New channel type — "Folder (media files from a directory)" — that builds
its queue by walking a folder path recursively without requiring content
to be in the Kodi library. Designed for bumpers, commercials, interstitials,
and any non-library media.

New files:
  resources/lib/channels/folder.py — FolderQueueBuilder
    Walks the configured folder_path recursively (including subdirectories).
    Finds all media files: .mkv .mp4 .avi .mov .wmv .m4v .ts .m2ts
    .mpg .mpeg .flv .webm. Builds queue in random or sequential
    (filename-sorted) order. Handles recycle=False by tracking played
    files. Path normalisation handles UNC paths (→ smb://), %20 encoding
    for network paths with spaces, and trailing slash for xbmcvfs.

Changes:
  channel_manager.py — added "folder" dispatch in build_queue() before
    serial routing. Follows same resume-from-existing-queue pattern as
    all other channel types.

  ui/channels.py — four changes:
    1. _run_wizard(): added "Folder" as 4th channel type option; routes to
       new _run_folder_wizard()
    2. _run_folder_wizard(): folder browser → path normalisation →
       random/sequential order → recycle → queue size → visibility.
       Validates folder is accessible before allowing creation.
    3. _add_channel_item(): folder channels show "[Folder] FolderName"
    4. channel_info(): folder channels show type, path, order, recycle
    5. open_channel(): routes folder to _open_folder_channel()
    6. _open_folder_channel(): shows upcoming items from queue file,
       falls back to showing folder path when no queue built yet

  strings.po — new strings #32505-#32514 (minus #32510 removed as unused):
    #32505: channel type label (long)
    #32506: channel type label (short)
    #32507: Select Media Folder (browser title)
    #32508: No folder selected
    #32509: Folder not accessible: {0}
    #32511: Playback Order (wizard step title)
    #32512: How should files be played? (wizard step body)
    #32513: Folder Channel (info display label)
    #32514: Path: {0} (info display)

Channel config format:
  {
    "channel_type": "folder",
    "folder_path":  "smb://nas/Bumpers",  (normalised, %20 encoded)
    "randomize":    true/false,
    "recycle":      true/false,
    ...standard fields...
  }

Folder channels appear in the interleave source picker alongside TV,
Movie, and Serial channels — no additional changes required there.

Post-implementation audit: zero duplicates, zero broken, zero orphaned.
All Python files syntax-clean.

---

## Version 1.1.0ax

**Fix: Reset Show context menu — "{0}" showing instead of show name**

Two bugs fixed:

1. Context menu label used #32336 ("{0}" reset to S01E01.) instead of
   #32334 (Reset Show). The label had a {0} placeholder that was never
   substituted, so users saw literally "{0}" in the menu item. Fixed:
   both context menu label occurrences in channels.py now use #32334.

2. Show title was empty in the confirmation dialog and completion
   notification. Router was looking up show title from channel["shows"]
   by matching tvshowid, but the lookup was returning an empty string.
   Fixed: channels.py now passes show_title as a URL parameter when
   building the context menu URL (the show title is already available
   as _show / show_title in the calling scope). Router uses the URL
   param directly, falling back to the channel config lookup only if
   the param is absent (backwards compatibility with older queue files).

Both paths fixed: the upcoming-items view and the fallback no-queue view.

Files changed: ui/channels.py, router.py.

---

## Version 1.1.0aw

**Fix: Addon display playlist showing wrong items (local stale copy)**

Problem: When the addon's channel view showed upcoming items, it was
reading from the local profile copy of the queue file in preference to
the shared (authoritative) queue file. The local copy is used as a
staging area during _update_queue_file writes — it gets written first,
then copied to shared storage. Between sessions, the local copy retains
whatever trimmed state it was last written to during active playback.

Example from log: previous session had trimmed '2 Broke Girls' (played),
leaving 'Bill Engvall' at position 0 in the local copy. Next session,
the display read the local copy and showed Bill Engvall first. But
playback correctly read the shared file (2 Broke Girls still at
position 0 there because the previous session's trim had been correctly
written to shared but the local staging copy reflected a mid-session
state).

Fix: removed the local-copy preference logic entirely. The display now
always reads _queue_file_path() — the same authoritative path that
_resume_from_existing_queue() uses for playback. Display and playback
now always read exactly the same file.

Non-shared storage users: unaffected. When no shared storage is
configured, _queue_file_path() already returns the local profile path,
so the behaviour is identical to before for those users.

Change: 3 lines removed from channels.py _open_tv_channel(). No other
files changed.

---

## Version 1.1.0av

**Revert: Duration Cache feature removed**

Duration Cache feature removed entirely — no current feature requires
it and it added significant complexity with no immediate payoff.

Removed:
  - resources/lib/utils/duration_cache.py (deleted)
  - build_scraped_cache, build_unscraped_cache router actions
  - _check_scheduled_duration_scan() from service.py
  - All duration settings from settings.xml (scheduled scan day/time,
    default durations, ffprobe path, build buttons, cache status)
  - All duration-related strings from strings.po (27 strings removed)
    — strings.po now has 306 strings, highest ID #32504

Kept:
  - manage_extra_folders action — for adding commercial/bumper folders
    to channels. Logic moved to new self-contained module
    resources/lib/utils/extra_folders.py (imports paths.py for I/O,
    no duration dependency).
  - extra_folders.json data format unchanged.
  - Folder manager dialog strings (#32308, #32309, #32496, #32499-32504)

Settings → Cache tab reverted to:
  - Maximum age before auto-refresh (days)  [#32132]
  - Auto-rebuild Kodi library cache on expiry [#32133]
  - Manage Extra Media Folders (commercials, bumpers) [#32496 button]

Post-cleanup audit: zero duplicates, zero broken, zero orphaned strings.
All Python files syntax-clean.

---

## Version 1.1.0au

**Fix: Separate scraped/unscraped cache files; fix unscraped_files bug**

Two changes:

1. **Separate cache files.**
   - duration_cache.json   — Kodi library items (episodeid/movieid keys).
                             Built by "Build Scraped Media Duration Cache".
   - unscraped_cache.json  — Extra folder items (file path keys).
                             Built by "Build Unscraped Media Duration Cache".
   Both files are written to the addon_data profile folder.
   get_duration() merges both at load time for transparent lookup:
   episodeid → movieid → file path (from either cache) → default.

2. **Fix: unscraped_files contained ALL 65 items instead of only
   items with no duration.**
   Root cause: the existing cache was loaded at build start with
   the corrupt unscraped_files list from a previous (buggy) run,
   and new results were merged into it rather than replacing it.
   Fix: when unscraped_only=True, clear paths, unscraped_files,
   and missing before scanning so stale data never persists.
   After this fix: unscraped_files will be empty (all 65 items
   have valid ffprobe durations), missing will be 0.

_write_incremental now takes unscraped_only parameter:
  - unscraped_only=True:  writes paths + unscraped_files only
  - unscraped_only=False: writes episodes + movies only
  This keeps each file clean and purpose-specific.

File changed: utils/duration_cache.py only.

---

## Version 1.1.0at

**Fix: duration_cache.json now written correctly to addon_data folder**

The write was succeeding (confirmed by "cache written: 65 paths" in log)
but the file may not have been landing in the expected addon_data folder.

Root cause: paths.save_json() uses is_shared = not path.startswith(profile)
to decide whether to write directly or copy. The profile string from
paths._get_profile() ends with a trailing backslash on Windows, but
os.path.join(profile, filename) strips redundant separators, so the
resulting path may not startswith() the profile string — causing
is_shared=True and the write going through the copy path instead.

Fix: added _cache_file_path(profile) helper that normalises the profile
path (strips trailing separators, re-joins with os.path.join) so the
cache_path string always matches what paths._get_profile() returns.
This ensures is_shared=False and save_json() uses xbmcvfs.File()
directly to the profile folder.

Also added log("[DurationCache] cache_path=...") at build start so the
exact write destination is always visible in the log.

File changed: utils/duration_cache.py only.

---

## Version 1.1.0as

**Fix: duration_cache.py now uses paths.py for all file I/O**

Root cause of the JSON write failure: duration_cache.py was written as
a self-contained module and reimplemented its own _write_cache_file()
and _load_cache_file() using xbmcvfs.File() directly. xbmcvfs.File()
works for network and special:// paths but fails silently for local
Windows drive paths (C:\Users\...) — which is exactly where the addon
profile lives on a Windows PC.

Fix: duration_cache.py now imports load_json and save_json from
utils/paths.py, the same utility functions used by every other addon
module. paths.save_json() correctly handles local paths (via
xbmcvfs.File for profile paths), shared/network paths (write-then-copy),
and includes a fallback to open() for mapped Windows drives.

Also updated: load_extra_folders() and save_extra_folders() now use
paths.load_json / paths.save_json instead of direct xbmcvfs.File calls.

Importing utils/paths.py from utils/duration_cache.py is explicitly
allowed — paths.py is a utility module ("Any module may import and call
these utilities") and this is not a boundary violation.

Post-fix audit: duration_cache.py no longer appears in xbmcvfs.File
write pattern check. Remaining occurrences in channel_manager.py,
player.py, and service.py are pre-existing repo blockers tracked in
HANDOFF.

No strings changes. No settings changes. duration_cache.py only.

---

## Version 1.1.0ar

**Fix: Unscraped cache — three bugs fixed**

1. **duration_cache.json not written.**
   xbmcvfs.File() failed silently for local Windows paths (C:\Users\...).
   Fixed: _write_cache_file() now tries xbmcvfs.File() first, falls back
   to open() for local paths. Success logged either way so the write is
   always confirmed in the log.

2. **CMD window flashing on every ffprobe call.**
   subprocess.run() on Windows spawns a visible console window by default.
   With 65 files, that meant 65 CMD flashes. Fixed: passes
   creationflags=subprocess.CREATE_NO_WINDOW (via getattr for safety on
   non-Windows) to both _ffprobe_check() and _ffprobe_duration(). No
   more CMD windows.

3. **Toast said "0 episodes found" for unscraped scan.**
   The completion toast always showed episodes/movies counts which are
   always 0 for an unscraped-only scan. Fixed: _notify_completion() now
   accepts unscraped_only parameter and uses new string #32520:
   "Unscraped media: {0} items scanned, {1} durations found,
   {2} using default. Built in {3}s."

New string: #32520. No other files changed beyond duration_cache.py
and strings.po.

---

## Version 1.1.0aq

**Fix: Unscraped media duration scan — three bugs fixed; unscraped default added**

**Bug 1: GetEpisodes/GetMovies called even for unscraped-only scan.**
When pressing "Build Unscraped Media Duration Cache", the code still ran
two heavy JSON-RPC calls (70,122 episode lookups + 6,426 movie lookups)
before doing anything useful — a 20-second delay with no user feedback.
Fixed: skip _build_id_lookups() entirely when unscraped_only=True.

**Bug 2: Extra folder scan walked for NFO files — found none, stopped.**
Unscraped media (commercials, bumpers) rarely have NFO sidecar files.
The scan called _walk_for_nfos() which found 0 files, so ffprobe was
never attempted. Fixed: extra folder scan now calls _walk_for_media()
which collects media files directly (.mkv, .mp4, .avi, etc.), then
tries NFO first (if it exists) and falls back to ffprobe.

**Bug 3: Windows local paths not accessible via xbmcvfs.**
"D:\Bumpers, Openings, etc" failed all _accessible_path() checks
because only network path forms were tried. Fixed: _accessible_path()
now tries backslash, forward-slash, and trailing-slash variants for
local paths. Also added logging showing exactly which form worked.

**New: ffprobe status logged at scan start.**
Log now shows "ffprobe ready: path" (working), "ffprobe configured
but NOT working" (bad path), or "ffprobe not configured" so the user
can confirm ffprobe will be used.

**New: Default duration for unscraped items.**
Setting: "Default duration for unscraped items when ffprobe unavailable
(seconds)" — integer, default 30. Located in Unscraped Media Durations
section. When neither NFO nor ffprobe produces a duration, the file
path is added to an "unscraped_files" list in duration_cache.json.
get_duration() checks this list and returns the unscraped default
(seconds) instead of the TV/movie default (minutes) — appropriate for
short content like 30-second commercials.

Cache format gains "unscraped_files": ["path1", ...] key.

New functions: _walk_for_media(), _nfo_path_for_file(),
_unscraped_default_seconds(). New string #32519. New setting
duration_default_unscraped (number, default 30).

File changed: utils/duration_cache.py, settings.xml, strings.po.

---

## Version 1.1.0ap

**Maintenance: strings.po deep clean; HANDOFF updated**

Ran complete strings.po audit using the definitive audit script (handles
split-line getLocalizedString calls that previous audits missed).

Removed 48 truly orphaned string entries:
- Old settings category sub-labels (#32101, #32121, #32131, #32141,
  #32143, #32151, #32161, #32162)
- CUN position labels now inline in settings.xml (#32173-32176)
- Superseded channel UI strings replaced by higher-range IDs
  (#32200, #32201, #32209, #32213, #32218, #32220, #32226,
  #32234-32238, #32241, #32248, #32272, #32273, #32275)
- Renamed duration cache strings (#32301, #32302, #32305, #32307,
  #32310, #32314, #32316, #32317, #32319-32321, #32324, #32327-32329)
- Superseded folder manager strings (#32498, #32514)
- Renamed cache settings (#32132, #32133)

Final audit result:
  Duplicates: 0
  Broken:     0
  Orphaned:   0
  Total:      329 strings
  Highest ID: #32518

HANDOFF.md updated with:
- Definitive audit script (embedded, handles split-line calls)
- Current strings.po block map
- Repo submission blockers in priority order
- Feature queue updated

Only files changed: strings.po, SMARTCHANNELS_HANDOFF.md, addon.xml.

---

## Version 1.1.0ao

**Feature: Cache settings restructured; scheduled scraped scan; separate
unscraped build action; strings.po duplicates fixed**

**Settings restructure (Cache & Durations tab):**

Three clearly separated sections:

  ── Channel Wizard Data ─────────────────────────────────────
  Maximum age before auto-refresh (days)
  Auto-update channel wizard data when Kodi adds new content

  ── Scraped Episode & Movie Durations ───────────────────────
  Default TV duration when NFO has no duration
  Default movie duration when NFO has no duration
  Scheduled scan day  (Daily/Mon-Sun)
  Scheduled scan time (HH:MM, 24-hour)
  Build Scraped Media Duration Cache  [button]

  ── Unscraped Media Durations ───────────────────────────────
  (commercials, bumpers, interstitials not in Kodi library)
  ffprobe.exe full path (Windows only, optional)
  Manage Extra Media Folders  [button]
  Build Unscraped Media Duration Cache  [button]

  ── Duration Cache Status ───────────────────────────────────
  [lsep showing last built info]

**Scheduled scan (service.py):**
_check_scheduled_duration_scan() runs every 60 seconds in the
service loop. Reads duration_scan_day and duration_scan_time
settings. Fires start_background_build(scraped_only=True) once
per day at the configured time. Never blocks playback.

**Separate build actions:**
- build_scraped_cache  — scans Kodi library NFO files only
- build_unscraped_cache — scans extra folders only (ffprobe fallback)
Both run in background threads. User can keep working.

**strings.po fixes:**
Fixed 8 duplicate IDs (#32200, #32376-#32382). Original channel-list
strings preserved at their existing IDs. Folder manager strings moved
to #32498-#32504. Interleave confirmed string moved to #32497.
Post-fix audit: zero duplicates, zero broken IDs.

Files changed: settings.xml, strings.po, duration_cache.py,
router.py, addon.py, service.py, ui/channels.py.

---

## Version 1.1.0an

**Fix: Cache settings — clarified all labels to remove ambiguity**

All Cache & Durations settings labels rewritten to clearly distinguish
Kodi library operations from NFO-based duration scanning:

- Tab label: "Cache" → "Cache & Durations"
- Section header #32328: "Kodi Library Cache" →
    "Kodi Scraped Library Cache"
- #32132: "Max Kodi library cache age (days)" →
    "Maximum age before auto-refresh (days)"
- #32133: "Auto-rebuild Kodi library cache on expiry" →
    "Auto-refresh expired Kodi library cache on startup"
- Section header #32329: "Media Duration Cache (non-library items)" →
    "Episode & Movie Duration Cache"
  (old text implied duration cache only covered non-library items —
   it covers ALL items, both Kodi library and extra folders)
- #32302: "Default TV episode duration" →
    "Default duration — TV episodes (used when NFO has no duration)"
- #32305: "Default movie duration" →
    "Default duration — Movies (used when NFO has no duration)"
- #32307: "Rebuild duration cache after Refresh Library" →
    "Auto-rebuild duration cache after Kodi library refresh"
- #32330: "ffprobe path (Windows only — leave blank...)" →
    "ffprobe.exe full path (Windows only, optional)"
- #32311 lsep: "Duration cache status" → "Duration Cache Status"
- #32327: "Build Duration Cache" →
    "Build Duration Cache (reads NFO files from all video sources)"

Bug fix: manage_extra_folders settings button was using label #32376
which collides with the channel list "Build Library Cache" string.
Moved to new #32496 = "Manage Extra Media Folders (commercials,
bumpers, non-library items)".

Files changed: strings.po, settings.xml.

---

## Version 1.1.0am

**Feature: Duration Cache uses episodeid/movieid keys; non-blocking scan**

Complete rewrite of duration_cache.py. Two major improvements:

**1. Stable integer ID keys instead of file paths.**
At scan start, two lightweight JSON-RPC calls fetch id+file pairs for
all library items:
  - VideoLibrary.GetEpisodes (properties: ["file"]) — all episodes
  - VideoLibrary.GetMovies   (properties: ["file"]) — all movies
These build file→episodeid and file→movieid lookup dicts. During the NFO
walk, after finding a duration, the media file path is looked up in these
dicts to get the stable integer ID. Results stored as:
  { "episodes": { "1042": 2580 }, "movies": { "87": 6900 }, "paths": {...} }
"paths" is a fallback for non-library items (extra folders) where no ID
exists. get_duration() looks up episodeid first, then movieid, then file
path. Eliminates 8.3 short filename mismatches, %20 encoding issues, and
any other path format inconsistencies between scan and playback.

Path normalisation in _lookup_id() tries the path as-is, with %20→space,
and with space→%20 to maximise match rate.

**2. Non-blocking background thread with toast notifications.**
The blocking DialogProgress is gone. start_background_build() spawns a
daemon thread and returns immediately — the user can keep working.
Toast notifications report:
  - "Discovering sources..." at scan start (immediate confirmation)
  - "Show N of M: Show Name" at each TV show boundary
  - "Scanning movies..." when movie phase starts
  - "Cache build complete — N episodes, M movies, X missing in Ys"
    on completion

Incremental saves preserved: written after each show and every 200
movies, so a crash or Kodi exit never loses all progress.

Files changed: utils/duration_cache.py (complete rewrite),
router.py (build_duration_cache now calls start_background_build).

---

## Version 1.1.0al

**Fix: Duration Cache — four bugs fixed from log analysis**

1. **Wrong progress bar text ("No other channels available to interleave").**
   duration_cache.py was using getLocalizedString(32218) and (32219) for
   the TV show / movie progress messages. Those IDs belong to the channel
   wizard (#32218 = interleave message, #32219 = "Enter channel name:").
   Fixed to use #32318 ("Show {0} of {1}: {2}") and #32319 ("Movie {0}
   of {1}") which were correctly assigned in strings.po all along.

2. **ffprobe attempted even without a configured path.**
   _ffprobe_exe() was falling back to "ffprobe" (system PATH) when the
   ffprobe_path setting was blank. Now returns empty string when the
   setting is blank — ffprobe is ONLY used if the user explicitly enters
   a path. Falls back to user's configured default duration instead.

3. **XML parse errors on some NFO files ("junk after document element").**
   Some NFO files have multiple root elements or trailing content after
   the closing tag. ET.fromstring() is strict and rejects these. Fixed
   by wrapping the content in a synthetic root element on parse failure
   and using the first real child as the root. Suppressed to LOGDEBUG
   for unrecoverable parse failures (was LOGWARNING causing log spam).

4. **TV sources with spaces in path still "not accessible".**
   xbmcvfs.exists() behaviour with URL-encoded spaces (%20) is
   inconsistent across Kodi builds. Added _accessible_path() which tries
   three forms in order: path with %20 + trailing slash, path with
   literal spaces + trailing slash, path without trailing slash.
   Returns the first accessible form, enabling all 13 TV sources and
   11 movie sources to be walked.

File changed: utils/duration_cache.py only.

---

## Version 1.1.0ak

**Fix: _expand_multipath — unquote() has no safe= parameter in Python 3**

unquote(p, safe=":/") raises TypeError in Python 3 — unquote() does not
accept a safe= keyword argument (that's quote(), not unquote()). This caused
Files.GetSources to fail entirely, leaving no sources to scan.

Fix: replaced unquote() with explicit string replacements:
  %3a/%3A -> :   (scheme separator)
  %2f/%2F -> /   (path separator)
All other encodings including %20 (spaces) are deliberately left intact
because xbmcvfs requires paths in Kodi's internal URL-encoded format.

Verified with real multipath URL from log:
  smb%3a%2f%2f192.168.1.11%2fD%2fTV%20Shows%2f
  -> smb://192.168.1.11/D/TV%20Shows  (correct, %20 preserved)

File changed: utils/duration_cache.py only.

---

## Version 1.1.0aj

**Fix: Duration Cache — SMB path trailing slash required for xbmcvfs**

Paths were expanded and decoded correctly but xbmcvfs.exists() and
xbmcvfs.listdir() on SMB network directories require a trailing slash.
Without it both return False/empty even for accessible paths.

Additionally, unquote() was decoding spaces (%20 → literal space) which
xbmcvfs cannot handle in SMB paths. Fixed to use unquote(p, safe=":/")
which decodes only the scheme separator characters but leaves %20 and
other encoded characters intact.

Changes:
- _ensure_slash(): new helper that adds trailing slash to network paths.
  Used by xbmcvfs.exists() and xbmcvfs.listdir() calls throughout.
- _listdir(): now always calls _ensure_slash internally.
- _expand_multipath(): uses unquote(p, safe=":/") to preserve %20 etc.
- TV and movie source loops: _ensure_slash applied to exists() checks.
- _walk_for_nfos() and _collect_movie_nfos(): _ensure_slash applied.

File changed: utils/duration_cache.py only.

---

## Version 1.1.0ai

**Fix: Duration Cache — multipath:// expansion; settings label warning**

Two fixes from log analysis:

1. **multipath:// not expanded — 0 episodes and movies scanned.**
   Files.GetSources returns a single multipath:// URL when a source
   has multiple paths configured under one name (e.g. "TV Shows"
   spanning drives D through O). xbmcvfs.exists() on a raw multipath://
   URL returns False, so both sources were immediately marked "not
   accessible" and nothing was scanned.

   Fix: added _expand_multipath() (ported from working NFO scanner
   verbatim) to _discover_sources(). Each multipath:// URL is now
   decoded into its individual smb:// component paths before the
   directory walk begins. Your 13 TV paths and 11 movie paths are
   now all discovered correctly.

2. **duration_cache_info "failed to parse" warning spamming log.**
   type="label" is not supported in Kodi 21's old settings.xml format.
   Changed to type="lsep" which renders as a separator line and is
   supported. Warning eliminated.

Files changed: utils/duration_cache.py (_expand_multipath added,
_discover_sources updated), settings.xml (label→lsep).

---

## Version 1.1.0ah

**Fix: Duration Cache — incremental saves, cancel support, detailed progress**

Three improvements to build_cache():

1. **Incremental saves — no data lost on cancel or crash.**
   Results are written to disk after each TV show directory completes
   and every 200 movies. The next build loads the existing cache first
   and merges new results into it, so already-scanned items are never
   re-read unnecessarily. A crash or network dropout mid-scan loses at
   most the current show being walked.

2. **Cancel saves partial results.**
   progress_cb now returns True (continue) or False (cancel) instead of
   None. build_cache() checks the return value and breaks out of loops
   immediately when False is returned. The final write always runs,
   saving everything collected before the cancel. The router notification
   on cancel now shows how many TV episodes and movies were saved
   (using #32325) rather than implying nothing was kept.

3. **Detailed progress messages.**
   TV scan now shows "Show N of M: Show Name" (#32218) as each show
   directory is processed. Movie scan shows "Movie N of M" (#32219).
   User can see exactly which show is being scanned and how far along
   the scan is, rather than just a static "Scanning TV shows..." message.

Files changed: utils/duration_cache.py, router.py (progress callback
return value, cancel notification).

---

## Version 1.1.0ag

**Refactor: Duration Cache fully isolated; source discovery via JSON-RPC**

Two changes:

1. **Source discovery switched back to Files.GetSources JSON-RPC.**
   The working NFO scanner used Files.GetSources — which reads sources.xml
   internally. This is the correct Kodi API. The direct sources.xml parse
   approach (1.1.0af) is replaced with the same Files.GetSources call the
   working scanner used. duration_cache.py calls xbmc.executeJSONRPC
   directly as a deliberate, documented exception — it is intentionally
   self-contained and has no dependency on library.py. Files.GetSources
   reads filesystem metadata, not the video database.

2. **Duration Cache fully isolated from channel_manager.py.**
   Removed build_duration_cache() and get_item_duration() wrapper methods
   from channel_manager.py. router.py and service.py now import
   duration_cache directly. channel_manager.py has zero references to
   the duration cache. The stale local_library.json prerequisite check
   in the router handler is removed — duration cache no longer reads that
   file. duration_cache.py is now a self-contained utility module with
   the same isolation level as utils/logger.py.

Interaction footprint of duration_cache.py:
  - Imports: xbmc, xbmcaddon, xbmcvfs, xml.etree, json, os, sys, time
  - Calls: xbmc.executeJSONRPC (Files.GetSources only)
  - Reads: NFO files via xbmcvfs, extra_folders.json via xbmcvfs
  - Writes: duration_cache.json, extra_folders.json via xbmcvfs
  - No imports from any other addon module

Files changed: utils/duration_cache.py, channel_manager.py (wrappers
removed), router.py (direct import, prereq check removed).

---

## Version 1.1.0af

**Fix: Duration Cache — correct source discovery, no JSON-RPC**

Complete rewrite of duration_cache.py source discovery:

**Problem:** Previous versions tried to read episodes from local_library.json
(which has no episode records) and then tried Files.GetSources JSON-RPC
(which doesn't work in this setup).

**Solution:**
1. Parse special://userdata/sources.xml via xbmcvfs — Kodi's own source
   file, legal for repo submission, no JSON-RPC. Video sources with names
   containing "movie" or "film" → movie sources; others → TV sources.
2. Extra folders from extra_folders.json appended to both source lists.
3. TV: walk each source directory's show subdirectories recursively,
   find every .nfo (skip tvshow.nfo), parse duration, find matching
   media file by trying common extensions, store file_path → seconds.
4. Movies: walk movie sources collecting NFO files (one level deep for
   per-folder layouts, top level for flat layouts), parse duration,
   find matching media file, store file_path → seconds.
5. ffprobe used as fallback (Windows only, if configured) when NFO gives 0.
6. Cache keyed by full file path (not episodeid) — get_duration() looks
   up item["file"] against both tv and movies dicts.

Cache format changed:
  { "built_at": "...", "tv": { "path": secs }, "movies": { "path": secs },
    "missing": N }

Removed: get_video_sources() from library.py and channel_manager.py
(JSON-RPC approach abandoned). manager= parameter removed from build_cache().

Notification strings #32323, #32325, #32326 updated to match new format
(tv/movies counts instead of episodes/movies/paths).

Files changed: utils/duration_cache.py (rewritten), router.py (summary
keys), strings.po (notification formats). library.py and channel_manager.py
cleaned of now-unused get_video_sources().

---

## Version 1.1.0ae

**Fix: Duration Cache scanning 0 episodes; Feature: unlimited extra folders**

**Root cause of 0 episodes:** `local_library.json` stores TV shows at the
show level only — never individual episodes. `duration_cache.py` was reading
`data.get("episodes", [])` which always returned an empty list.

**Fix — TV episode scanning:** Now uses the same directory-walk approach as
the working NFO scanner. `library.py` gains `get_video_sources()` which calls
`Files.GetSources` JSON-RPC to discover Kodi's configured TV source
directories. `channel_manager.py` gains a `get_video_sources()` wrapper.
`build_cache()` now accepts a `manager` parameter; when provided it calls
`manager.get_video_sources()` to get TV source directories, then recursively
walks each show directory finding every `.nfo` file (skipping `tvshow.nfo`),
parses duration, and cross-references with the episode file→id map from
the movie library cache where available. Results stored by `episodeid` where
matchable, by NFO path otherwise.

Movie scanning unchanged — `local_library.json` has `movieid`→`file` for
all movies, so file-by-file NFO sidecar resolution works correctly there.

**Feature — unlimited extra folders:** The 3 fixed `duration_extra_path_1/2/3`
settings fields are replaced with a single "Manage Extra Media Folders" action
button in Settings → Cache. Folders are stored in `extra_folders.json` in the
addon profile with no limit on count. `manage_extra_folders` router action
provides an interactive menu: shows current folders, lets user add (via
folder browser dialog) or remove individual folders. Strings #32308–#32310
repurposed; new strings #32376–#32382 added.

Files changed: `utils/duration_cache.py` (rewritten), `library.py` (new
`get_video_sources()`), `channel_manager.py` (new wrappers), `router.py`
(new `manage_extra_folders()`), `addon.py` (dispatch), `settings.xml`,
`strings.po`.

---

## Version 1.1.0ad

**Audit: channels.py hardcoded strings — already clean**

Full audit of channels.py confirmed it was already fully compliant.
All dialog, notification, and context menu strings are already routed
through self._s() with strings.po IDs #32201–#32494. No changes needed.

Complete cross-file audit run:
- Every string ID used in every .py file verified present in strings.po
- No hardcoded user-visible strings found in any file
- Five apparent "violations" in service.py confirmed as false positives
  (Notification format templates with {} placeholders, not hardcoded text)

The codebase is now fully compliant with the no-hardcoded-strings rule
across router.py, service.py, channels.py, duration_cache.py, and all
other files.

No code changes. Version bump only to mark audit completion.

---

## Version 1.1.0ac

**Fix: All hardcoded strings removed from service.py**

Six hardcoded user-visible strings replaced with strings.po lookups:

- Resume dialog: "Smart TV Channels" → #32289, "{} — resume from {}?" → #32371,
  "Start Over" → #32250 (reused from wizard), "Resume" → #32150 (reused
  from settings category label — same word, correct intent)
- onNotification: "Library scan done - updating cache..." → #32372
- _start_cache_rebuild_if_needed: "Building library cache for first
  time..." → #32373; "Refreshing library cache ({:.0f} days old)..." → #32374
- _rebuild_library_cache: "Library cache updated!" → #32375;
  "Cache rebuild failed - check logs" → #32341 (reused from router)

New strings added: #32371–#32375. Strings #32150, #32250, #32289, #32341
reused where text matched existing entries.

Files changed: `service.py`, `strings.po`.

---

## Version 1.1.0ab

**Fix: Backup path not available without Kodi restart**

Two changes to `_get_backup_path()` and the backup/restore handlers:

1. **Retry loop:** `_get_backup_path` now retries up to 3 times with 750ms
   sleeps between attempts (was a single 1-second retry only when the value
   was empty). Each attempt creates a fresh `xbmcaddon.Addon()` instance to
   avoid any stale settings cache.

2. **Offer to open settings inline:** When backup or restore is triggered
   with no path configured, instead of a dead-end "No backup folder
   configured" message, a yesno dialog asks "Open Settings now?". If the
   user says yes, settings opens immediately, and after closing, the path is
   re-read with the retry loop. This means the user never needs to exit and
   restart Kodi just to set the backup path for the first time.

`#32344` updated to be phrased as a question (used in yesno dialog now
instead of ok dialog).

Files changed: `resources/lib/router.py`, `strings.po`.

---

## Version 1.1.0aa

**Fix: All hardcoded strings removed from router.py**

Added `self._s(id_)` helper to the Router class (same pattern as
ChannelUI._s()). Every user-visible string in router.py now goes through
strings.po. No hardcoded text remains anywhere in the file.

New strings added: `#32331`–`#32370` covering all router dialogs and
notifications: reset channel/show dialogs, library cache rebuild messages,
backup/restore dialogs, delete all data dialog, shared path migration
dialogs, and the generic error string.

Two existing strings reused where text already matched:
`#32210` (Channel deleted), `#32211` (Channel not found),
`#32212` (No episodes found), `#32216` (Delete confirmation).

Files changed: `resources/lib/router.py`, `strings.po`.

---

## Version 1.1.0z

**Fix: Duration Cache settings — four corrections**

1. **ffprobe path setting added** (`ffprobe_path`, Windows-only visible).
   `_ffprobe_exe()` reads this setting and falls back to `"ffprobe"` on
   system PATH if blank. `_ffprobe_check()` and `_ffprobe_duration()` now
   accept and use the resolved executable path rather than hardcoding
   `"ffprobe"`.

2. **Existing Cache strings renamed** to distinguish from new Duration Cache
   settings: `#32132` → "Max Kodi library cache age (days)";
   `#32133` → "Auto-rebuild Kodi library cache on expiry".

3. **Divider separators added** to the Cache settings category:
   `#32328` ("Kodi Library Cache") before the existing settings;
   `#32329` ("Media Duration Cache (non-library items)") before the new
   Duration Cache settings.

4. **Enum values fixed** — `values="32303"` was incorrect (Kodi does not
   accept a string ID reference in the values= attribute). Replaced with
   inline pipe-separated text on both TV and movie duration enums.
   `#32303` removed from strings.po as it is no longer referenced.

Files changed: `resources/lib/utils/duration_cache.py`, `settings.xml`,
`strings.po` (renamed #32132/#32133, removed #32303, added #32328–#32330).

---

## Version 1.1.0y

**Fix: Duration Cache strings.po collision — corrected string ID range**

1.1.0x appended Duration Cache strings starting at `#32201`, colliding
with the existing channel UI strings (`#32200`–`#32300`) that were already
in use by the channel wizard, context menus, and dialogs. Kodi resolves
duplicate msgctxt entries by using the last definition, so the channel UI
strings were silently overwritten, breaking the "My Channels" settings
category and channel management menus.

Fix: removed the duplicate `#32201`–`#32227` entries appended in 1.1.0x.
Duration Cache strings reassigned to `#32301`–`#32327` (safely after the
highest legitimate existing ID `#32300`). All code references in
`router.py` and `duration_cache.py` updated to the new IDs.

Duration Cache settings merged into the existing "Cache" category
(`label="32130"`) in `settings.xml` rather than a new category — the
erroneous `<category label="32201">` block has been removed.

Files changed: `strings.po`, `settings.xml`, `resources/lib/router.py`,
`resources/lib/utils/duration_cache.py`.

---

## Version 1.1.0x

**Feature: Duration Cache**

New `utils/duration_cache.py` module. Builds and maintains a persistent
JSON cache (`duration_cache.json`) mapping every library item to its
duration in seconds. Required by the EPG overlay for schedule projection.

**Resolution order per item:**
1. NFO sidecar file (same basename as media file, `.nfo` extension).
   Episode field priority: `fileinfo/streamdetails/video/durationinseconds`
   → `fileinfo/streamdetails/video/duration` → top-level `<runtime>`
   → top-level `<durationinseconds>`. Movie: same order.
   Movies also try `movie.nfo` in the same folder as a secondary fallback.
2. ffprobe — Windows only (`sys.platform == "win32"`). Silently skipped
   on all other platforms (Shield/Android/Linux). `tvshow.nfo` is never
   read (episode and movie sidecars only).
3. Global default — user-configured per type (TV / Movie). Enum options:
   20 / 30 / 40 / 50 / 60 / 90 minutes, or Custom (numeric input).

**Public API:**
- `get_duration(item, addon)` — cache lookup + default fallback. Never
  returns 0. Called via `channel_manager.get_item_duration()` wrapper.
- `build_cache(addon, progress_cb)` — full scan with optional progress
  callback. Called via `channel_manager.build_duration_cache()` wrapper.
- `get_cache_info(addon)` — returns localised one-line status string for
  the settings label.

**Extra folder paths:** up to three non-library folder paths can be
configured in settings. Files in those folders are scanned recursively
and stored in the `paths` dict keyed by file path (for future Folder
Channel / non-library use).

**Auto-rebuild:** optional setting to trigger a duration cache rebuild
automatically after Refresh Library completes (background thread).

**Settings:** new "Duration Cache" category in settings.xml with all
labels from strings.po (`#32201`–`#32227`). Build Cache button fires
`action=build_duration_cache` via the Kodi plugin URL mechanism.
No hardcoded user-visible strings anywhere in this feature.

**Files changed:**
- `resources/lib/utils/duration_cache.py` — new file
- `resources/lib/channel_manager.py` — added `build_duration_cache()`
  and `get_item_duration()` wrapper methods
- `resources/lib/router.py` — added `build_duration_cache()` handler
- `addon.py` — added `build_duration_cache` to dispatch table
- `service.py` — added duration cache auto-rebuild after library refresh
- `resources/settings.xml` — new Duration Cache category
- `strings.po` — added `#32201`–`#32227`

---

## Version 1.1.0w

**Fix: channel view shows stale episode order after Reset to S01E01**

After "Reset to S01E01" or "Reset Channel to Start", the channel view
immediately showed the old episode sequence. Stopping and reopening the
channel corrected it. Playback itself was always correct (S01E01 played
as expected).

Root cause: `_open_tv_channel` prefers the local profile copy of the queue
file (`profile/queue_{id}.json`) when it exists, because service.py writes
there as a staging copy during active playback. `reset_show_to_start` and
`reset_channel` deleted the queue file at the shared path (via
`_queue_file_path`) and wrote a fresh one there via `_pregenerate_queue`,
but never touched the local profile copy. The stale local copy shadowed the
fresh shared-path file on every read until something else (service.py on
next stop) overwrote it.

Fix: both `reset_show_to_start` and `reset_channel` now delete the local
profile copy (`os.path.join(self.profile, "queue_{id}.json")`) alongside
the shared-path copy before calling `_pregenerate_queue`. `_pregenerate_queue`
writes to the shared path; with no local copy present, `_open_tv_channel`
falls through to read the shared-path file correctly on the next refresh.

File changed: `resources/lib/channel_manager.py` only.

---


**Fix: "Reset to S01E01" context menu missing from open-channel view**

When a channel has a queue file (i.e. has been played at least once),
`_open_tv_channel` renders the upcoming queue in play order and returns
early — bypassing the per-show fallback loop where the "Reset to S01E01"
context menu was attached. As a result, the context menu was never visible
in normal use; only accessible if the queue file was absent.

Fix: added the "Reset to S01E01" context menu to TV episode items in the
`upcoming_items` rendering block. Movie items (primary or interleaved) are
skipped. The `_show_id` field written by `_normalize_ep` onto every queue
item is used to construct the correct `reset_next_episode` URL per item.
Items without a `_show_id` (should not occur for TV episodes) are skipped
defensively.

The "Reset Channel to Start" option in the channel-list context menu was
always functional (it is on the channel-list view, not inside the channel).

File changed: `resources/lib/ui/channels.py` only.

---


**Fix: interleave top-up join-boundary overlap — root cause eliminated**

Replaced the post-hoc dedup + stranded-movie pass (introduced across
1.1.0k–1.1.0r) with a source-level fix that prevents the overlap from
occurring in the first place.

**Root cause:** When a top-up fires, `_load_foreign_items` calls
`_build_fresh_queue` for the foreign TV channel, which seeds each show's
`local_index` from `next_episode_id` in state — the last *completed*
episode. Episodes sitting in `current_queue` that are queued but not yet
played are ahead of `next_episode_id`, so the fresh build started behind
them and overlapped at the join boundary.

**Fix:** Before calling `_apply_interleave`, `refill_queue` now builds a
`start_after` dict — `{tvshowid: last_episodeid_in_current_queue}` — for
each foreign TV show present in `current_queue`. This dict is threaded via
a closure through `_apply_interleave` → `_load_foreign_items` →
`_build_fresh_queue`. Inside `_build_fresh_queue`, when `start_after` is
set for a show, `local_index[sid]` is seeded to `after_pos + 1` (the
episode immediately after the last one already queued) rather than from
`next_episode_id`. This prevents any overlap at the join boundary.

Random foreign channels: all episodeids seen in `current_queue` for each
show are added to `local_played[sid]` so they are excluded from the random
pool in the fresh build.

Recycle/exhaust edge cases: if `start_after` points to the last episode
of a show, `local_index[sid]` = `len(episodes)`, which the existing
recycle/exhaust pre-check handles correctly without any new logic.

The `start_after=None` default on `_build_fresh_queue` and
`_load_foreign_items` ensures all other callers (channel creation,
regenerate_queue, initial build) are completely unaffected.

**Removed:** The dedup block (~30 lines) and stranded-movie pass (~50
lines) previously in `refill_queue` have been deleted. The `primary_offset`
calculation is retained — it is correct and unrelated to this fix.

File changed: `resources/lib/channel_manager.py` only.

---


**Revert: 1.1.0s orphaned TV episode removal caused skipped episodes**

1.1.0s removed orphaned TV episodes along with their stranded movie to
prevent back-to-back same-show episodes at the top-up boundary. This
caused a worse problem: those episodes were skipped permanently because
state had already advanced past them — they would never play again.

The fundamental trade-off at the join boundary is unavoidable:
- Remove orphaned TV eps → clean round-robin but episodes are lost ❌
- Keep orphaned TV eps → one extra TV episode at the boundary but all
  episodes play ✅

1.1.0t reverts to keeping orphaned TV episodes (the 1.1.0r behaviour).
The join boundary will occasionally have slightly more TV episodes than
`count_per` (e.g. 4 instead of 3), and those episodes may be from the
same show consecutively. This is a cosmetic anomaly that occurs once per
top-up cycle and is far preferable to permanently losing episodes.

File changed: `resources/lib/channel_manager.py` only.

---

## Version 1.1.0s

**Fix: back-to-back same-show TV episodes at top-up join boundary**

The stranded-movie pass introduced in 1.1.0r correctly removed primary
movies with incomplete TV slots. However it left the surviving orphaned TV
episodes in `new_tail`, causing them to bleed into the next movie's slot
and break the round-robin show rotation.

**Concrete case:**
After dedup, `new_tail` contained:
`[BestYouCan, DeadBride, TilDeath(76954), Borderline, TilDeath(76955), 2BG, 3rdRock, BringHerBack]`

1.1.0r correctly removed `BestYouCan`, `DeadBride`, and `Borderline`
(each had < 3 TV eps before them). But `TilDeath(76954)` — the sole
survivor of Dead Bride's partial slot — remained in `cleaned` and was
not removed when Borderline was struck. It then appeared immediately
before TilDeath(76955) at the start of Bring Her Back's slot, producing
two consecutive Til Death episodes.

**Fix:** `current_slot_tv` tracks the TV episodes accumulated since the
last primary movie within `new_tail`. When a primary movie is removed
for having an incomplete slot, all TV episodes in `current_slot_tv` are
also removed from `cleaned`. The tv counter and slot tracker reset to 0,
so the next movie's slot starts cleanly.

The resulting boundary after this fix:
`Nuremberg → TilDeath(76955) → 2BG → 3rdRock → BringHerBack` ✅

File changed: `resources/lib/channel_manager.py` only.

---

## Version 1.1.0r

**Fix: partial TV episode slot at top-up join boundary**

The stranded-movie pass introduced in 1.1.0n correctly handled the case
where a movie's entire TV slot was deduplicated (zero TV episodes remaining
before it). However it did not handle partial slots — where some but not
all TV episodes in a slot were dedupped.

**Concrete case from testing:**
After dedup, `new_tail` contained: `[Christy, (Merv removed), Everybody
Digs Doug, Nuremberg, ...]`. Merv was correctly removed (0 TV eps before
it). But Nuremberg inherited Everybody Digs Doug as its sole preceding TV
episode (1 of 3 required). The old pass only checked whether the previous
item was a primary movie — Nuremberg's predecessor was a TV ep, so it
passed through, giving the user `Christy → 1 ep → Nuremberg`.

**Fix:** The stranded-movie pass now counts TV episodes since the last
primary movie (looking back through `current_queue` for the initial count,
then tracking per movie in `new_tail`). Any primary movie whose preceding
TV episode count is less than `count_per` is removed — whether that's
because of zero or partial preceding TV episodes. The count is not reset
when a movie is removed, so surviving TV episodes from a partial slot
accumulate toward the next movie's threshold.

The boundary repair is not perfect — the slot at the join may have
slightly more than `count_per` TV episodes — but this is vastly better
than 1 episode between two movies.

File changed: `resources/lib/channel_manager.py` only.

---

## Version 1.1.0q

**Fix: interleaved channel reset to 30 movies on Play Channel after stop**

The 1.1.0o fix correctly resolved the ownership check (`Queue belongs to
channel X not Y`), but a second independent check in the same method also
triggered a fresh build.

`_resume_from_existing_queue` has a metadata check for movie channels:
if `queue[0]` has no `year`, `genre`, or `plot` fields, it assumes the
queue is in an old format and forces a rebuild. This check was written to
handle pre-metadata movie queues.

After stopping while an interleaved TV episode was playing, the service
trims the on-disk queue to start from the current position. When the
current position was a TV episode, that TV episode became `queue[0]`. TV
episodes never have `year`, `genre`, or `plot` — so `has_metadata` was
always `False`, the check triggered, and a fresh 30-movie queue was built
with no interleave.

Confirmed in the 1.1.0o log: `Movie queue missing metadata - rebuilding in
new format` appears at the second `play_channel` call, immediately after
the ownership check passes cleanly (no `Queue belongs to channel X not Y`
message — proving 1.1.0o fixed that half of the problem).

Fix: the metadata check now only runs if `queue[0]` is actually a movie
entry (`is_movie=True` or `movieid > 0`). An interleaved TV episode at
`queue[0]` has no movie metadata by design and must never trigger a
rebuild.

File changed: `resources/lib/channel_manager.py`.

**Audit correction: 1.1.0o set_now_playing change caused incorrect
TV show state advancement for interleaved episodes**

The 1.1.0o change passed `primary_channel_id` to `set_now_playing` so
`self.player._channel_id` held the movie channel id. But `_handle_end`
reads `self._channel_id` to call `advance_state` — which needs the TV
channel id (item's own channel) to write show progress to the correct
state key. Passing the primary channel id would have written TV episode
progress into the movie channel's state, breaking episode continuity for
the foreign TV channel.

Fix: `set_now_playing` reverted to receiving `item_channel_id` and
`item_channel` (preserving `_handle_end` correctness). A new separate
attribute `_primary_channel_id` is set directly on the player after
`set_now_playing` returns. `_get_next_episode` (Coming Up Next) reads
`_primary_channel_id` with fallback to `_channel_id` — giving it the
correct queue file to look up without disturbing any other code that
reads `_channel_id`.

File changed: `service.py`.

---

## Version 1.1.0o

**Fix: interleaved channel reset and Coming Up Next wrong item — same root cause**

Both bugs traced to a single root cause: interleaved TV episodes carry
`channel_id = foreign_tv_channel_id` on disk, not the primary movie
channel's id. The initial queue build does not write `_interleaved=True`
onto items (only the top-up new_tail build does), so items on disk have
no way to identify themselves as interleaved after a stop/resume cycle.

**Bug 1 — Channel reset to 30 movies on Play Channel after stop**

`_resume_from_existing_queue` in `channel_manager.py` checks `queue[0]`
to verify the queue file belongs to the requested channel. The old guard
was `if not first_item.get("_interleaved")` — but `_interleaved` is
absent on disk for items written by the initial build. So when `queue[0]`
was an interleaved TV episode, the guard passed, saw `_channel_id =
5b121c0c ≠ f39ba224`, and returned `None` — triggering a fresh 30-movie
build with no interleave.

Fix: the ownership check now also accepts items whose `_channel_id`
matches the foreign channel configured in the primary channel's interleave
config. A TV episode whose `_channel_id == interleave.channel_id` is a
legitimate item in this queue regardless of whether `_interleaved` is set.

File changed: `resources/lib/channel_manager.py`.

**Bug 2 — Coming Up Next showing wrong item on interleaved channel**

The 1.1.0l fix passed `primary_channel_id=self.player._channel_id` to
`_get_next_episode`. But `self.player._channel_id` is set by
`set_now_playing`, which was being called with `item_channel_id` (the
item's own channel id). For an interleaved TV episode that's the foreign
TV channel id — so `_get_next_episode` still opened the wrong queue file.

Fix: `set_now_playing` is now called with `primary_channel_id` (derived
from the active queue file path, which is always correct) instead of
`item_channel_id`. `self.player._channel_id` now always holds the primary
playing channel's id regardless of which channel's episode is currently
on screen.

File changed: `service.py`.

---

## Version 1.1.0n

**Fix: back-to-back primary movies at top-up join boundary**

The TV episode dedup introduced in 1.1.0l correctly removed duplicate
interleaved TV episodes from `new_tail` at the join boundary. However,
removing those TV episodes stranded primary movies that had been separated
by them, producing adjacent primary movies in the combined queue.

**Concrete example** with `frequency=1, count_per=3`:
`new_tail` after `_apply_interleave`:
  `[MOVIE_A, TV_dup1, TV_dup2, TV_dup3, MOVIE_B, TV_ok1, TV_ok2, TV_ok3, ...]`
After dedup removes the three duplicate TV episodes:
  `[MOVIE_A, MOVIE_B, TV_ok1, TV_ok2, TV_ok3, ...]`
`MOVIE_A` and `MOVIE_B` are now back-to-back.

**Confirmed in the log**: dedup fired and removed 5 TV episodes, then
back-to-back movies appeared in the channel.

**Fix**: after the TV dedup pass, a second "stranded-movie" pass scans
`new_tail` and removes any primary movie whose immediately preceding item
(looking back into `new_tail` or into the tail of `current_queue`) is
also a primary movie. This restores the interleave contract that primary
items are never consecutive.

The stranded-movie pass runs only when TV episodes were deduped
(`foreign_ch.get("channel_type") not in ("movies",)` guard) so it is
completely inert for all non-interleaved channels and for movie-into-TV
interleave configurations.

File changed: `resources/lib/channel_manager.py` only.

---

## Version 1.1.0m

**Fix: Remove Interleave destroyed config on accidental selection**

The `manage_interleave` dialog listed "Remove Interleave" as the first
item in the channel picker. On the Shield remote (and potentially other
remotes), pressing Back on a select list selects the currently focused
item rather than returning -1. Because "Remove Interleave" was always
item 0 and always at the top of focus, pressing Back to dismiss the
dialog selected it — immediately stripping the interleave and rebuilding
the queue without confirmation. This happened silently and was
irreversible without re-configuring the interleave.

Confirmed in the log: `manage_interleave` fired, `interleave removed`
appeared 3 seconds later (too fast for a deliberate selection through the
full dialog), and the queue rebuilt to 30 movies with zero TV episodes.
All three reported symptoms (interleave gone, back-to-back movies, Coming
Up Next showing wrong item) trace back to this single accidental removal.

Fix: added a `d.yesno()` confirmation step before executing the removal.
If the user selects "Remove Interleave" deliberately, they must confirm.
If the selection was accidental, "No" returns them to the channel list
without any change. The confirmation message names the channel and
explicitly notes the action cannot be undone.

File changed: `resources/lib/ui/channels.py` only.

**Note: Coming Up Next and back-to-back movies**

Neither was a separate code bug — both were downstream effects of the
interleave being stripped. Once interleave is intact the Coming Up Next
fix from 1.1.0l correctly reads the primary channel's queue and shows the
right next item. No additional fix needed.

---

## Version 1.1.0l

**Fix: Coming Up Next showed wrong item on interleaved channels**

When the currently playing item was a TV episode interleaved into a Movie
channel, `_get_next_episode` used `current_ep.get("channel_id")` to find
the queue to read. For interleaved TV episodes, `channel_id` points to the
**foreign** TV source channel — so `_get_next_episode` opened the TV
channel's own queue file and returned the next TV episode in that queue,
skipping over any movie that appears between them in the actual playing
interleaved queue.

Fix: `_get_next_episode` now accepts an optional `primary_channel_id`
parameter. The call site in `run()` passes `self.player._channel_id` — the
channel actually playing — so the correct interleaved queue is always read
regardless of which `channel_id` is embedded in the current episode.

The fallback (`current_ep.get("channel_id")`) is preserved for
non-interleaved channels and any future callers that don't supply a primary
channel id.

File changed: `service.py`.

**Fix: interleave top-up dedup guard never fired (1.1.0k regression)**

The dedup introduced in 1.1.0k to remove join-boundary duplicate TV
episodes never actually ran. Its guard required `ep.get("_interleaved")`
to be truthy, but `_interleaved` is only written onto items by
`apply_interleave` during the top-up's new tail build. The initial queue
build (`_build_fresh_queue` / `regenerate_queue`) does not write
`_interleaved` onto items. Surviving tail items in `current_queue` are
loaded from the queue file on disk, where `_interleaved` is absent — so
the set comprehension always produced an empty set and the dedup never
removed anything.

Confirmed by the 1.1.0k log: zero `dedup removed` lines appeared, and the
queue file showed items 0–6 with `_interleaved=MISSING` while item 7+
(from the new tail) had `_interleaved=True`, with the duplicate episodeid
133419 appearing at both position 3 (no flag) and position 7 (with flag).

Fix: the guard now uses `_channel_id == foreign_id` alone, which IS
present on all items regardless of which build path wrote them. The
`_interleaved` check is removed from both the `already_queued` set
comprehension and the `new_tail` dedup loop.

File changed: `resources/lib/channel_manager.py`.

**Note: interleave disappearing on stop**

No code change. The log shows only `channels.json` reads — no writes.
One-time interaction anomaly, not a code bug.

---

## Version 1.1.0k

**Fix: interleaved TV episodes duplicated at top-up join boundary**

When a Movies channel has a TV Shows channel configured as its interleave
source, episodes from the foreign TV channel were repeated at the boundary
between the surviving `current_queue` tail and the freshly top-up content.

**Root cause:**
`_load_foreign_items` calls `_build_fresh_queue` for the foreign TV channel.
`_build_fresh_queue` seeds `local_index` from `next_episode_id` in show
state — which reflects the last *completed* episode.  Episodes already
sitting in `current_queue` that are queued but not yet played are *ahead*
of `next_episode_id`.  The fresh build therefore starts from behind the
surviving tail, producing overlap at the join boundary.

**Fix:**
In `refill_queue`, after `_apply_interleave` produces the new tail, build
a set of episodeids already present in `current_queue` from the foreign
channel.  Any interleaved TV episode in `new_tail` whose episodeid is in
that set is removed before `current_queue + new_tail` is assembled.

This is the minimal targeted fix: `_build_fresh_queue` and
`_load_foreign_items` are not changed (they serve many other paths).
The dedup is gated on `foreign_ch.get("channel_type") not in ("movies",)`
— the movies path is unaffected because the movie pool is managed by
played/unplayed_ids and never produces join-boundary duplicates.

File changed: `resources/lib/channel_manager.py` only.

---

## Version 1.1.0j

**Fix: recycle=False movie channel — three bugs in skip and natural-end handling**

All three bugs were pre-existing in 1.1.0i. Both changes are in `service.py`
only. `channel_manager.py` is not touched.

**Bug 1 — Skipped movies never cleared their resume entry.**
The movie skip block in the skip detection loop ended with `continue`, which
bypassed the shared `clear_resume_position` call used by the TV episode path.
A movie that had a saved resume position (from the poll timer) would leave
that entry in state.json permanently after being skipped. Next time the
channel was opened, the stale resume would fire incorrectly.

Fix: added an explicit `clear_resume_position` call inside the movie skip
block, before the `continue`.

**Bug 2 — Skips never shrank `unplayed_ids` for recycle=False channels.**
The same `continue` also bypassed any state update for the skipped movie.
For `recycle=False`, `_channel_exhausted()` uses `unplayed_ids==[]` as its
exhaustion signal. Because `_build_movie_queue` (for recycle=False) saves
`unplayed_ids` unmodified — it queues from the pool but defers all shrinkage
to `advance_movie_state` — the pool never emptied on skip. Result: top-up
kept firing, and the exhaustion dialog never appeared after skipping past all
movies.

For `recycle=True` this is correct behaviour: the builder manages
played/unplayed during queue construction and persists the result, so calling
advance_movie_state on skip would double-update the pool and cause premature
cycling and repeat movies.

Fix: after the resume clear, added a `recycle=False`-gated call to
`advance_movie_state` for each skipped movie. `recycle=True` path is
unchanged.

**Bug 3 — Exhaustion dialog never fired after the last movie ended naturally.**
`onPlayBackEnded` had an explicit `ch.get("channel_type") not in ("movies",)`
guard, meaning `_pending_exhausted_channel` was never set for movie channels
on natural end. Even when `advance_movie_state` (called from `_handle_end`)
correctly emptied `unplayed_ids` after the last movie, the run() loop was
never signalled to show the delete/reset/nothing dialog.

Fix: removed the `not in ("movies",)` exclusion. `is_channel_exhausted()`
already handles movie channels correctly via `_channel_exhausted()` — after
`advance_movie_state` runs in `_handle_end`, the state is correct and the
check fires for all `recycle=False` channel types.

Files changed: `service.py` only.

---

## Version 1.1.0i

**Fix: Random movie channel repeating movies — _deleted_state_keys wiping movie state after reset**

Root cause (definitive): After `reset_channel` clears all state keys for a
channel, it calls `_pregenerate_queue` to rebuild the queue immediately.
`_pregenerate_queue` calls `_build_movie_queue` which correctly builds the
queue, sets `self._state["channel_id:__movie_state__"] = new_state`, and
calls `_save_state()`.

`_save_state()` does a read-merge-write: reads disk, merges in-memory state,
then strips any keys in `self._deleted_state_keys` before writing. The
problem: `reset_channel` adds `"channel_id:__movie_state__"` to
`_deleted_state_keys` and that set is still active when the pregenerate's
`_save_state` fires — so the newly-built movie state (`played=[14],
unplayed=[2]`) is silently stripped from the merge result. State.json is
written as empty `{}`.

On the next top-up, `_build_movie_queue` reads state from disk — finds
`0 played, 16 unplayed` (because the state was wiped) — starts a fresh
cycle immediately, and appends movies that are already in the Kodi playlist
from the initial queue build. Visible result: movie repeats.

Fix: one line — `self._deleted_state_keys.clear()` immediately after
`reset_channel` saves the cleared state and before calling
`_pregenerate_queue`. The deleted-key tracking has served its purpose at
that point (the save already cleared those keys from disk). Clearing it
ensures subsequent writes in the same ChannelManager instance are not
affected by stale deletion tracking.

No other changes. The skip loop is untouched.
The `advance_movie_state` call from `_handle_end` is untouched.
All other channel types are unaffected.

---

## Version 1.1.0h_prev

**[Superseded — see corrected 1.1.0h above]** Fix: Random movie channel repeating movies — skip loop removed from pool management

Root cause (correctly identified): `advance_movie_state` was being called
in two places:
1. `_handle_end` — when a movie finishes playing naturally (correct)
2. The skip loop — for every skipped movie item (WRONG)

`_build_movie_queue` already removes movies from `unplayed_ids` when it
queues them. Calling `advance_movie_state` in the skip loop removed them
again — double-removing from the pool, halving its effective size, and
causing premature recycling and visible repeats within a cycle.

The 1.1.0h playlist rebuild approach (previous attempt) was also wrong:
`playlist.clear()` while a video is playing resets Kodi's playlist
position, causing the channel to stop or jump back to the beginning.

Fix: Remove `_advance_movie_state` call from the skip loop entirely.
Pool management (played_ids / unplayed_ids) belongs exclusively to
`_build_movie_queue`. When movies are queued they are consumed from the
pool. The skip loop's only job is to update the queue file position —
it does not touch the movie state pool.

`advance_movie_state` is now called ONLY from `_handle_end` (natural
movie end). Skipped movies are correctly tracked by their absence from
the queue file on the next build — the builder reads the fresh queue
and continues from the correct unplayed position.

No other channel types affected. TV and serial channel skip paths
are unchanged.

---

## Version 1.1.0h_SUPERSEDED

**[Superseded by corrected 1.1.0h above]** Fix: Random movie channel repeating movies within a cycle after rapid skipping

Root cause: When the user rapid-skips through a movie channel queue, two
problems occurred together:
1. The queue contains 30 items for 16 movies — so items 17-30 are a second
   random cycle. The 1.1.0b fix correctly ignores second-cycle items to avoid
   double-counting. But when the recycle fires mid-skip, the Kodi playlist
   still contains pre-recycle items from the old cycle that land ahead of
   the freshly-built top-up items — causing those old movies to appear again
   in the new cycle.
2. The Kodi playlist is cumulative across a session (grows: 30→54→78 items).
   After a recycle and top-up, the new 24 items land at the end of a long
   stale playlist. If the user is already deep in the playlist, those stale
   items between current position and the new top-up all belong to the old
   cycle, producing visible repeats.

Fix — three targeted changes, nothing else touched:

- `channel_manager.advance_movie_state()`: now returns a bool `recycled`
  (True when a full cycle just completed and the pool reset). Return type
  changed from None to bool. All existing callers that ignored the return
  value are unaffected.

- `service.py._advance_movie_state()`: now returns the `recycled` flag from
  CM. Sets `self._movie_recycled_during_skip = True` when a recycle fires
  during the skip loop.

- `service.py._topup_in_background()`: when `_movie_recycled_during_skip`
  is True, clears the Kodi playlist and rebuilds it from scratch using the
  full fresh queue (30 items) instead of appending 24 items to the stale
  cumulative playlist. Resets the flag after rebuilding. Playback is not
  interrupted — Kodi handles playlist.clear() + re-add while playing.

Impact: movie channels only, skip-loop path only. TV channels, serial
channels, and interleaved channels are completely unaffected. The recycle
flag is False for all non-movie advance calls so the code path is never
entered for other channel types.

---

## Version 1.1.0g

**Fix: Channel stops playing when user rapid-skips through movie channel**

- Root cause: The top-up threshold check only examined the disk queue
  remaining count. When a user rapid-skips large batches, Kodi's
  cumulative live playlist (which grows with each top-up: 30→54→78→102
  items) could be nearly exhausted at the current playlist position even
  though the disk queue check had not yet fired. Result: Kodi ran out of
  playlist items and returned to the channel list.
- Fix: `_update_queue_file` now also checks `PlayList.size() - position - 1`
  (Kodi playlist remaining items from current position). Top-up fires when
  EITHER the disk queue OR the Kodi playlist remaining count is at or below
  threshold. The more conservative trigger ensures items are always appended
  to the playlist before Kodi can exhaust it, regardless of how aggressively
  the user skips.
- Log line updated to show both counts:
  "Queue below threshold (disk=N pl=M threshold=T)"
- No changes to the top-up logic itself — only the trigger condition widened.

---

## Version 1.1.0f

**Fix: duplicate class name eliminated + top-up restored**

Two separate classes were both named `SmartPlayer`:
- `resources/lib/player.py`: `class SmartPlayer` — channel starter,
  owns `start_channel()`, `_write_now_playing()`, `_make_listitem()`
- `service.py`: `class SmartPlayer(xbmc.Player)` — playback monitor,
  owns all playback callbacks, poll timer, resume, overlay triggers

This naming collision violated the no-duplication rule and caused
the Phase 9 `_make_listitem` relocation to target the wrong class.

**Fix:**
- `service.py`'s `SmartPlayer(xbmc.Player)` renamed to `PlaybackMonitor`
- All 4 references updated: class definition, super() call, instantiation,
  and the log message
- `_make_listitem` remains at module level in `player.py` — correct,
  as it is a pure stateless utility with no instance dependency
- `service.py._topup_in_background` import of `_make_listitem` from
  `player.py` is correct and working
- All class names across the entire codebase are now unique ✓

**Top-up was broken** because `_make_listitem` was moved into
`player.py`'s `SmartPlayer` class, but `_topup_in_background` called it
via `self.player` which is a `PlaybackMonitor` instance (was `SmartPlayer`
in service.py), not a `player.py` SmartPlayer instance. The import-based
call to the module-level function was always the correct pattern.

---

## Version 1.1.0e

**Rollback: _make_listitem restored to module-level function**

Phase 9 of the rewrite moved `_make_listitem` from a module-level
function in `player.py` into `SmartPlayer` as a private method.
This was wrong for two reasons:

1. There are two classes named `SmartPlayer` in the codebase:
   - `player.py`: `class SmartPlayer` — the queue builder / channel starter
   - `service.py`: `class SmartPlayer(xbmc.Player)` — the playback callbacks
   `self.player` in `SmartChannelsService` refers to the service.py class,
   not the player.py class. Moving `_make_listitem` into player.py's class
   made it unreachable from the top-up path.

2. `_make_listitem` is a pure utility function with no instance state.
   It does not belong in any class — module-level is correct.

Fix: `_make_listitem` restored to module-level function in `player.py`.
`player.py` line 79: call restored to `_make_listitem(ep)`.
`service.py` `_topup_in_background`: import and call restored to
`from resources.lib.player import _make_listitem` / `_make_listitem(ep)`.

The Phase 9 grep audit rule is now updated: before moving any function
into a class, verify ALL callers and confirm they have access to that
class instance. A module-level function is always safe; a method is only
safe if every caller holds the right instance.

---

## Version 1.1.0d

**Hotfix: Top-up broken after _make_listitem relocation (Phase 9)**

- `service.py._topup_in_background` was importing `_make_listitem`
  directly from `resources.lib.player` at module level. Phase 9 moved
  `_make_listitem` from a module-level function to a private method on
  `SmartPlayer`, making that import fail with:
  `cannot import name '_make_listitem' from 'resources.lib.player'`
- Result: every top-up attempt raised an error and silently returned,
  leaving the queue to drain without refilling.
- Fix: removed the broken import; call site updated to
  `self.player._make_listitem(ep)` which correctly accesses the method
  on the SmartPlayer instance that SmartChannelsService already holds.
- No other changes.

---

## Version 1.1.0c

**Rewrite complete — Phases 6, 9, 10**

This is the final 1.1.0 release. All planned phases are complete.
All existing test cases TC-1 through TC-12.3 pass on 1.1.0b (the
immediate predecessor); no logic was changed in this build.

**Phase 6 — service.py advance path violations fixed:**
- `get_episodes()`: was calling `xbmc.executeJSONRPC` directly.
  Now delegates to `channel_manager.get_episodes_for_show_cached()`
  which uses `library.get_episodes_for_show()`. Zero direct JSON-RPC
  calls outside `library.py`. ✓
- `_advance_movie_state()`: was writing state.json directly from
  service.py. Now delegates to `channel_manager.advance_movie_state()`.
  All movie state writes go through CM. ✓
- `_save_show_index()`: was writing state.json directly from service.py.
  Now delegates to `channel_manager.save_show_index()`. ✓
- `channel_manager.py`: three new public methods added:
  `advance_movie_state()`, `save_show_index()`,
  `get_episodes_for_show_cached()`.

**Phase 9 — Remaining structural violations fixed:**
- `_make_listitem()` in `player.py`: was a module-level function.
  Now a private method `SmartPlayer._make_listitem(self, ep)`.
  Call site updated: `self._make_listitem(ep)`. ✓
- Bare `open()` fallbacks in service.py, router.py, library.py,
  player.py: these exist only in the `xbmcvfs.copy` failure path for
  local mapped Windows drives — an edge case that cannot be handled
  by xbmcvfs on all platforms. Documented as intentional; not removed.

**Phase 10 — Grep audit results:**
- `resolve_path` defined exactly once (utils/paths.py) ✓
- `load_json` defined exactly once (utils/paths.py) ✓
- `save_json` defined exactly once (utils/paths.py) ✓
- `xbmc.executeJSONRPC` only in library.py ✓
- `_make_listitem` no longer module-level ✓
- `normalize_ep` canonical in channels/base.py ✓
- `apply_interleave` canonical in channels/base.py ✓

**Known remaining items (post-1.1.0):**
- `advance_state()` in service.py still writes state.json directly
  at its final persistence step. The serial boundary detection inside
  it already calls CM. Full migration deferred — not a repo blocker.
- `set_now_playing()` in service.py creates an initial state entry
  directly. Minor violation; deferred.
- state.py boundary stub: full I/O migration to state.py deferred.

---

## Version 1.1.0b

**Bugfix: Movie channel premature recycle on skip when queue spans multiple cycles**

- `service.py → _advance_movie_state`: When a movie queue contains more
  items than the total number of movies (queue_size > movie count), the
  queue builder correctly fills it with multiple cycles. However the skip
  loop was calling `_advance_movie_state` for each skipped queue position,
  and when it hit a movie for the second time (second cycle in the queue),
  `unplayed_ids` was already empty from the first cycle — triggering a
  premature recycle reset mid-batch. This caused movies from the first
  cycle to appear again before the second cycle completed.
- Fix: `_advance_movie_state` now checks whether the movie being marked
  played is actually in `unplayed_ids` before counting it. If the movie
  is already in `played_ids` and not in `unplayed_ids`, it is a
  second-cycle occurrence in the queue — silently skipped, no double-count,
  no premature recycle.
- The recycle still fires correctly when `unplayed_ids` genuinely empties
  (all movies in the pool seen once). Natural episode-end advance path
  is unaffected — only the skip loop path was producing the wrong result.
- Verified by simulation against the exact 16-movie / 30-item queue / 24-skip
  scenario observed in testing.
- No changes to TV, serial, or interleave channel paths.

---

## Version 1.1.0a

**Hotfix: Resume position not saving on recycle=False (stop) channels**

- `service.py`: Removed `_is_stop_ch` guard from the resume save block.
  The guard was blocking position saves on any channel with `recycle=False`,
  meaning stop channels never wrote resume entries to `state.json`.
- The original reasoning (resume interferes with exhaustion detection) was
  incorrect — they use separate state keys and do not affect each other.
- Resume now saves on all channel types and modes when enabled, including
  stop channels. All episodes before the last can be resumed correctly.
- One-line change. No other behaviour affected.

---

## Version 1.1.0

**Architectural rewrite — no new features, no behaviour changes.**

All existing channel types, queue logic, and overlays behave identically
to 1.0.11g. This version relocates functions to correct module boundaries
to eliminate all known Kodi repo submission blockers.

### Phases completed in this build (Phases 1–5, 7–8):

**Phase 1 — New directory structure**
- `resources/lib/channels/` created: `base.py`, `tv.py`, `movies.py`,
  `serial.py`, `interleave.py` (stub)
- `resources/lib/overlays/` created: `coming_up_next.py`, `epg_overlay.py` (stub)
- `resources/lib/state.py` boundary stub created
- `resources/lib/ui/dialogs.py` stub created

**Phase 2 — utils/paths.py (canonical I/O utilities)**
- `load_json`, `save_json`, `resolve_path`, `shared_root`, `path_join`
  now have exactly ONE implementation in `utils/paths.py`
- `service.py`: local copies removed; imports from `utils/paths.py`
- `channel_manager.py`: `_load_json`, `_save_json`, `_resolve_path`,
  `_shared_root`, `_path_join` now delegate to `utils/paths.py`
- `router.py`: `_get_shared_root` now delegates to `utils/paths.py`
- Grep audit: each function defined exactly once ✓

**Phase 3 — state.py boundary documented**
- `state.py` stub written with full contract and list of methods it will own
- Actual I/O migration deferred until post-1.1.0 (high regression risk
  without dedicated test pass)

**Phase 4 — channels/base.py, channels/tv.py, channels/movies.py**
- `normalize_ep`, `normalize_movie`, `apply_interleave` canonical
  implementations written in `channels/base.py`
- `channel_manager._normalize_ep`, `_normalize_movie`, `_apply_interleave`
  are now one-line delegates to `channels/base.py`
- `TVQueueBuilder` in `channels/tv.py` — routes through CM build methods
- `MovieQueueBuilder` in `channels/movies.py` — routes through CM build methods
- `build_queue` dispatches TV and movie channels through the new builders

**Phase 5 — channels/serial.py**
- `serial.py` content copied to `channels/serial.py` (canonical location)
- `resources/lib/serial.py` replaced with compatibility shim

**Phase 7 — router.py state write violation fixed**
- `reset_next_episode` was writing state directly (tail key, queue file delete)
- New `channel_manager.reset_show_to_start()` owns all those writes
- Router now calls `manager.reset_show_to_start()` — zero direct state access

**Phase 8 — overlays/coming_up_next.py**
- `coming_up_next.py` content copied to `overlays/coming_up_next.py`
- `resources/lib/coming_up_next.py` replaced with compatibility shim

### Still outstanding (Phases 6, 9, 10):
- Phase 6: `service.py` advance path violations (`get_episodes` direct
  JSON-RPC; `advance_state`, `_advance_movie_state`, `_save_show_index`
  direct state writes) — deferred until TC-1 through TC-12 pass on this build
- Phase 9: `_make_listitem` module-level in `player.py`; remaining bare
  `open()` calls — same reason
- Phase 10: Final grep audit and packaging of the complete rewrite

### Test requirement before proceeding to Phase 6:
Run TC-1 through TC-12 (all channel types + Coming Up Next overlay).
All must pass before Phase 6 is started.

---

## Version 1.0.11g
### Changes
- **Coming Up Next font size increase** (`coming_up_next.py`)
  - Header ("Coming Up Next"): `font14` → `font16`
  - Content lines (show/episode info): `font13` → `font14`
  - PNG background (`bg_overlay.png`) and panel dimensions unchanged (160px height)
  - Layout fits within existing panel; no coordinate adjustments needed

---

## Version 1.0.11
### New Features

**Coming Up Next overlay (coming_up_next.py, service.py, settings.xml)**
- A self-contained overlay window appears near the end of each episode
  showing information about what plays next.
- Implemented as a new module (coming_up_next.py) following the same
  pattern as serial.py — fully self-contained, no changes to queue
  building, state management, or channel_manager.py.
- The overlay is a WindowDialog rendered over the video without
  interrupting playback. It auto-dismisses after the configured duration
  and can be dismissed early by any remote or keyboard action.
- Adapts automatically to all display resolutions (720p, 1080p, 4K)
  because Kodi scales from its 1280x720 logical coordinate space to
  the physical display.
- User settings (Settings > Coming Up Next):
    - Enable / disable the overlay
    - Corner position: Top Left, Top Right, Bottom Left, Bottom Right
    - Display duration in seconds (default 8)
    - Show / hide: show or movie name
    - Show / hide: season and episode number
    - Show / hide: episode title
- Trigger: the poll timer in service.py detects when remaining time
  falls within (duration + 20) seconds of the episode end. The overlay
  request is queued via _pending_overlay and displayed from the main
  service thread (required for xbmcgui on all platforms).
- Next-episode data is read from the existing queue file — no additional
  state or library access required.
- Works for TV episodes and movies (movies show title and year).
- Architecture rules honoured:
    - service.py owns all playback callbacks and timing logic
    - coming_up_next.py owns overlay rendering only
    - channel_manager.py not touched
    - No hardcoded user-visible strings (all in strings.po #32170-#32180, #32300)

### Bug Fixes

**Fix 1 — Coming Up Next overlay never fired when resume was disabled (service.py)**
- _start_poll_timer returned immediately when _resume_on_stop was False
  or when the channel was recycle=False. Since the Coming Up Next overlay
  trigger lives inside _poll_save which is only called by the poll timer,
  the overlay never fired if resume was turned off in settings.
- Fix: _start_poll_timer now always starts the timer when a channel is
  playing, regardless of resume settings. The resume-specific guards
  (resume_on_stop check and recycle=False check) were moved inside
  _poll_save to wrap only the resume save block. The overlay trigger
  block is completely independent of resume settings and fires for all
  channel types.


### Bug Fixes

**Fix 1 — Short shows (fewer episodes than EPS) only appeared once in queue (channel_manager.py)**
- When a show had fewer episodes than its Episodes Per Slot value (e.g. a
  4-episode show with EPS=5), the last_slot_files mechanism introduced in
  1.0.9y treated the show's recycle as a duplicate and blocked every episode
  on its second rotation. The slot produced no episodes, show_index still
  advanced, and the show never appeared again — leaving the long show (Burn
  Notice in TC-11.1) to fill all remaining queue slots.
- Fix: before skipping an episode via last_slot_files, check whether ALL
  remaining available episodes for that show are in last_slot_files. If so,
  this is a legitimate recycle, not a multi-episode file duplicate — clear
  last_slot_files for that show and place the episode normally.
- Applies to both _build_fresh_queue and _topup_queue.

---

## Version 1.0.9z
### Bug Fixes

**Fix 1 — Random movie channel repeated movies before all had been played (channel_manager.py)**
- The recycle=True + randomize=True path in _build_movie_queue used
  all_available as the draw pool on every build, ignoring played_ids entirely.
  At 105/111 movies played, a build of 29 items still drew from all 111 movies
  and produced approximately 23 repeats.
- Fix: the recycle=True path now draws from unplayed_ids. When the unplayed
  pool runs out mid-build, a new cycle begins (played_ids reset, unplayed_ids
  refilled from all_available) and building continues. Every movie plays once
  per cycle before any repeat, regardless of how many queue slots need filling.

---

## Version 1.0.9y
### Bug Fixes

**Fix 1 — Multi-episode files duplicated in queue across rotation slot boundary (channel_manager.py)**
- When Kodi stores two episodes from one physical file (e.g. S06E01-02.mkv),
  both episodes get separate library entries pointing to the same file path.
  The existing queued_files set caught duplicates within the same rotation
  cycle, but resets at each cycle boundary. With a 2-show channel, a cycle is
  2 slots — S06E01 placed in cycle N's slot for Show B, then queued_files
  cleared, then S06E02 placed in cycle N+1's slot for Show B. Same file played
  twice.
- Fix: added last_slot_files — a per-show dict tracking file paths placed in
  each show's most recent slot. It is never cleared by cycle resets. When a
  new slot starts for a show and the next episode's file is in
  last_slot_files[sid], the episode is skipped and the slot immediately retries
  with the next episode (S06E03 in the 2BG example).
- In _topup_queue, last_slot_files is additionally seeded from current_queue
  so the join boundary case (shared file straddles existing queue and top-up)
  is also caught.
- Applies to both _build_fresh_queue and _topup_queue.

---

## Version 1.0.9x
### Bug Fixes

**Fix 1 — Episodes Per Slot: top-up starts at wrong episode after first play (channel_manager.py)**
- _recalculate_tail has a guard intended to preserve a freshly-built tail:
  if existing_show_index > _simulated, keep the existing tail. When a fresh
  build produced show_index=21 and the queue contained exactly 21 completed
  slots, _simulated was also 21. 21 > 21 is False, so _recalculate_tail ran
  and overwrote the correct tail with its own recalculation.
- For EPS=1 channels this produced identical results. For EPS=2 channels,
  _build_fresh_queue uses a slot rollback that may set local_index[sid]=0
  (start of new cycle). _recalculate_tail overwrote this with the position
  of the last episode it found in the queue (e.g. 2 instead of 0), causing
  the top-up to start at S01E03 and skip S01E01-02.
- Fix: changed guard from > to >=. When existing_show_index == _simulated,
  the tail was built by the same pass that produced the current queue on disk.
  It is fresh and correct — trust it.

---

## Version 1.0.9u
### Bug Fixes

**Fix 1 — Surprise Me starting point reset to wrong episode after first top-up (channel_manager.py)**
- _recalculate_tail rebuilt local_index by counting how many episodes of each
  show appeared in the queue, then using that count as the index. This was
  correct only when a show started from episode index 0 (S01E01). When
  Surprise Me placed a show at S05E06 (index 108) and 6 episodes were queued,
  _recalculate_tail set local_index=6 instead of 114. The next top-up started
  each show from near S01E01 instead of continuing from the Surprise Me point.
- Fix: _recalculate_tail now finds the last episode of each show in the queue,
  looks up its absolute position in the full episode list, and sets
  local_index = that_position + 1. This is correct regardless of where the
  show started — Surprise Me, manual starting point, or S01E01.
- The local_played reconstruction for random shows (1.0.9n) is updated to use
  the actual queue count modulo total episodes rather than local_index (which
  is always 0 for random shows after this fix).

---

## Version 1.0.9t
### Bug Fixes

**Fix 1 — Top-up ignored Surprise Me starting point for shows not yet in the tail (channel_manager.py)**
- _topup_queue seeded local_index entirely from the tail marker. For shows
  absent from the tail (haven't had their first rotation slot yet, common when
  a channel has more shows than queue_size), local_index.get(sid, 0) always
  returned 0 — placing S01E01 regardless of any Surprise Me or manual starting
  point in state.
- Fix: after loading local_index from the tail, a new loop checks every show.
  For any show whose sid is not in the tail, local_index[sid] is seeded from
  next_episode_id state — exactly as _build_fresh_queue does on first build.
  Shows already in the tail are untouched.

---

## Version 1.0.9s
### Bug Fixes

**Fix 1 — Serial top-up duplicated lookahead episodes of the second show (serial.py, channel_manager.py)**
- The current_queue overlap check introduced in 1.0.9r used is_first_show as
  a sentinel to limit the check to only the first show processed. This was
  wrong — the LOOKAHEAD means multiple shows can already have episodes in
  current_queue. Clearing current_queue after the first show caused subsequent
  shows to fall back to next_episode_id state, which duplicated lookahead
  episodes of the second show (e.g. ASL E1-E5 appearing twice at the join
  boundary).
- Fix: removed is_first_show entirely. The current_queue check now runs for
  every show on every loop iteration for the entire top-up build.

---

## Version 1.0.9r
### Bug Fixes

**Fix 1 — Serial channel episode order jumbled after top-up (serial.py, channel_manager.py)**
- Two related bugs in the serial top-up path:
  1. refill_queue for serial called build(channel, target_size) and returned
     the result directly, ignoring current_queue. The caller sliced
     extended[len(current_queue):] to get new items — structurally wrong.
  2. build() read next_episode_id from state to find where to start each show.
     State only advances after an episode finishes playing. At top-up time, the
     last show in the queue may still have unplayed episodes ahead, so state
     lagged reality. build() placed already-queued episodes again.
- Fix: build() gains an optional current_queue parameter. When provided,
  instead of reading next_episode_id from state, it scans current_queue in
  reverse to find the last episode of each show already queued, and sets
  start_idx to the episode after it. refill_queue now passes current_queue and
  returns current_queue + new_items.

---

## Version 1.0.9q
### Bug Fixes

**Fix 1 — Serial channel plays in wrong show order (channel_manager.py)**
- build_queue was routing serial channels directly to SerialQueueBuilder.build()
  on every play_channel call, bypassing _resume_from_existing_queue. The
  pre-generated queue (correct show order) was discarded and replaced by a
  fresh build starting from __serial_show_idx__ — which pointed at the tail
  of the pre-generated queue, not the head. Result: show order started from
  the wrong position on every play.
- Fix: for full builds (size is None, i.e. play_channel), serial channels now
  attempt _resume_from_existing_queue first — exactly as TV and movie channels
  do. Only if no queue file exists does it fall through to build(). Top-up
  calls (explicit size parameter from refill_queue) still route directly to
  build().

---

## Version 1.0.9p
### Bug Fixes

**Fix 1 — Serial __serial_show_idx__ not persisted after reset_channel (serial.py)**
- reset_channel() deletes all channel state keys including __serial_show_idx__,
  adding the key to _deleted_state_keys. _pregenerate_queue then called build()
  which called _set_show_idx() to save the tail index. _set_show_idx wrote the
  key to _cm._state and called _save_state(). However, _save_state() strips
  every key in _deleted_state_keys from the merged result — so the key was
  silently removed from disk. The next play_channel read show_idx=0 (default)
  instead of the correct tail index, causing show order jumbling.
- Fix: _set_show_idx now calls _cm._deleted_state_keys.discard(key) before
  writing, so the deletion suppression is lifted for this specific key.

---

## Version 1.0.9o
### Bug Fixes

**Fix 1 — Serial channel show order jumbled after every top-up (serial.py)**
- build() advanced show_idx locally as it filled the queue but never wrote it
  back to state. Every top-up re-read the stale __serial_show_idx__ (only
  updated by advance_show() at episode boundaries during playback) and rebuilt
  from that show rather than from the queue tail. Result: shows repeated out
  of sequence at every top-up join boundary.
- Fix: after build() completes, the final show_idx is normalised (% len(shows)
  for recycle=True, clamped to len(shows) for recycle=False) and saved via
  _set_show_idx(). advance_show() continues to write its own value at show
  boundaries during playback — those writes correctly supersede the tail save.

---

## Version 1.0.9n
### Bug Fixes

**Fix 1 — Random show within sequential channel loses no-repeat tracking on resume (channel_manager.py)**
- _recalculate_tail initialised local_played = {} and never populated it.
  For random shows, local_played in the tail is the sole no-repeat tracking
  mechanism. When _recalculate_tail ran (on every play_channel), it cleared
  played_ids for random shows. The next top-up drew from the full episode pool
  and repeated episodes already in the queue.
- Fix: after computing local_index, _recalculate_tail now rebuilds local_played
  for random shows by scanning the queue for that show's episode IDs and keeping
  only the last (local_index[sid]) occurrences — the current-cycle episodes the
  top-up must not repeat. Completed cycles (local_index == 0) get an empty list
  so the next cycle starts fresh.

---

## Version 1.0.9m
### Bug Fixes

**Fix 1 — Recycle boundary causes double episode for the following show (channel_manager.py)**
- When a show placed its last episode, local_index reached len(episodes). On
  the next outer loop iteration for that show, the inner loop immediately reset
  local_index=0 and broke — placing zero episodes — but show_index had already
  been incremented at the top of the loop. The following show then received two
  consecutive turns instead of one.
- Fix: added a recycle-reset pre-check before show_index += 1 in both
  _build_fresh_queue and _topup_queue. For recycle=True: reset the pool and
  continue (retry this same show_index slot with the fresh pool). For
  recycle=False: mark exhausted and skip. show_index is now only incremented
  when the show will actually place at least one episode.
- Applies to both sequential and random show paths in both methods.


### Bug Fixes

**Fix 1 — EPS slot not consumed on duplicate file skip (channel_manager.py)**
- Multi-episode files (e.g. S06E01-E02 as a single file with two Kodi library
  entries) previously consumed an EPS slot even though the duplicate was
  skipped and no file played. The inner slot loop has been changed from a
  for loop to a while loop. The slot counter (_slot) only advances when an
  episode is actually placed. A duplicate file skip retries the same slot
  with the next episode. A multi-episode file now correctly counts as
  1 slot regardless of how many library entries point to it.
  Applies to both _build_fresh_queue and _topup_queue.

**Fix 2 — EPS acts as maximum-per-slot, not guaranteed minimum (channel_manager.py)**
- When a recycle=True show has fewer episodes than its EPS value (e.g. a
  show with 2 episodes and EPS=5), the show now contributes however many
  new episodes it has available and then yields to the next show in rotation.
  Previously the show was incorrectly added to the exhausted set mid-slot,
  causing it to be skipped for the remainder of the queue build.
  On the next rotation the show returns and picks up any newly downloaded
  episodes. EPS is now a per-slot maximum, not a forced count.
  Applies to both _build_fresh_queue and _topup_queue.

**Fix 3 — Top-up restarts from S01E01 after channel creation (channel_manager.py)**
  Root cause: _apply_starting_points adds the queue tail key to
  _deleted_state_keys so the tail is cleared from disk when a channel is
  created or edited. This is correct. However the deletion marker persisted
  in the long-running service.py ChannelManager instance, causing every
  subsequent _save_state call (e.g. saving __show_index__ after the first
  episode played) to re-delete the tail key from disk — including the tail
  that _build_fresh_queue had correctly written.
  On the next top-up, _topup_queue read an empty tail, initialised
  local_index as {}, and built from episode index 0, restarting both shows
  from S01E01.
  Fix: immediately after _save_state() in _apply_starting_points, call
  _deleted_state_keys.discard(tail_key). The one-time deletion has been
  performed; future saves must not repeat it.

**Fix 4 — EPS and per-show randomize defaults to 1/False on edit (channels.py)**
- When editing a channel, the multiselect rebuilds each show as a plain
  {tvshowid, title} dict, losing episodes_per_slot and randomize fields.
  The EPS wizard step then showed 1 as the current value for all shows
  regardless of what was saved. Per-show randomize was similarly lost.
  Fix: after the multiselect, the existing show dicts are looked up by
  tvshowid and any per-show fields (episodes_per_slot, randomize) are
  copied back into the freshly-built show dicts before the wizard steps run.

**Fix 5 — EPS and per-show randomize not shown in Channel Info (channels.py)**
- The Channel Info dialog listed shows with titles only. Shows with
  episodes_per_slot > 1 now show [N eps/slot] and shows with per-show
  randomize=True show [random] next to their title.
  Examples:
    Breaking Bad [2 eps/slot]
    Better Call Saul [random]
    The Wire [3 eps/slot, random]

---

## Version 1.0.9i
### New Features

**End-of-playback dialog for exhausted channels (service.py)**
- When a recycle=False channel (TV, Movie, or Serial) plays its last episode
  to completion, a dialog automatically appears once playback stops offering
  three choices: Delete the channel, Reset to beginning, or Do Nothing.
- The dialog is shown from the main service loop — never from inside a
  playback callback — so it is safe on all Kodi versions and platforms.
- The flag (_pending_exhausted_channel) is set inside _update_queue_file
  when is_channel_exhausted() returns True for a recycle=False channel,
  and consumed by the run() loop only after isPlaying() returns False.
- Choosing Delete removes the channel and all its state immediately and
  refreshes the channel list. Choosing Reset rebuilds the channel from
  S01E01 (or first movie / first serial show). Do Nothing or Cancel leaves
  everything in place; the channel can be reset or deleted manually later.
- Replaces the "no episodes found" dialog that previously only appeared
  when the user manually pressed Play Channel again after exhaustion.
  The router.py dialog is retained as a fallback for the case where the
  user presses Play Channel before the service has had a chance to show
  the end-of-playback dialog.

### Bug Fixes

**Stale last-episode entry in channel detail view (service.py)**
- When a recycle=False channel reached exhaustion, the queue file on disk
  retained the last-played episode until the user pressed Play Channel
  again. The channel detail view showed this stale entry as "1 upcoming
  program" even though there was nothing left to play.
- Fixed: _update_queue_file now deletes the queue file (and the local
  profile copy for shared-storage setups) when is_channel_exhausted()
  returns True for a recycle=False channel, instead of writing the
  one-item tail. _last_file is set to empty string so _check_now_playing
  does not attempt to reload the deleted file.

---

## Version 1.0.9h
### New Features

**Delete finished channel offer (player.py, router.py)**
- When Play Channel is pressed on a channel with no remaining episodes
  (recycle=False exhausted, or serial channel fully played through),
  a dialog now asks: "[Channel name] — no episodes found. Delete this
  channel?" Choosing Yes deletes the channel immediately and refreshes
  the channel list. Choosing No dismisses without action.
- Applies to all channel types: TV (recycle=False), Movie (recycle=False),
  and Serial (recycle=False after last show finishes).
- `start_channel()` in player.py now returns False on empty queue instead
  of showing its own dialog. router.py owns all user interaction for this
  case, consistent with the architecture rules.


- New channel type "Serial": each show plays every episode in full before
  the next show starts. Show A finishes entirely, then Show B begins, then
  Show C, and so on.
- All serial logic lives in a new self-contained `serial.py` module.
  channel_manager.py contains only three dispatch lines (one each in
  build_queue, refill_queue, advance_show). service.py is unchanged.
- The serial wizard has its own dedicated flow: show selection, play order
  (defaults to Set Order Manually — the alphabetical-order issue is clearly
  labelled so users are never silently surprised), recycle toggle, queue
  size, and visibility. No randomize, EPS, per-show flags, filters, or
  interleave steps.
- Show play order defaults to "Set Order Manually (recommended)" with
  "Keep Alphabetical Order" as a clearly-labelled second option, and
  "Shuffle" as a third. This addresses the long-standing issue where the
  multiselect always returns shows alphabetically.
- Serial channels display a [Serial] badge in the channel list and show
  the numbered play order in Channel Info.
- Manage Interleave is suppressed in the context menu for serial channels.
- recycle=True loops back to Show 1 when the last show finishes.
  recycle=False stops cleanly after the last show plays through.
- Queue top-up via refill_queue correctly continues from the current show's
  episode pointer and spills into the next show when needed.
- State key `channel_id:__serial_show_idx__` tracks the active show index.

### Bug Fixes

**service.py — advance_state show boundary key (latent bug)**
- After a serial show boundary crossing, the state key for the new show
  was built using `channel.get("id", "")` instead of the `channel_id`
  parameter. These are always equal in practice so no user-visible effect,
  but the parameter is the authoritative value and should be used.

**channels.py — stale per-show randomize keys on fully-random channels**
- When editing a Round Robin channel (with per-show randomize flags set)
  and switching it to fully-random, the per-show `randomize` keys were left
  in the show dicts in channels.json. They were ignored at runtime but would
  reappear as pre-filled values on a future edit back to Round Robin.
  Now stripped immediately when the channel-level randomize is set to True.

---

## Version 1.0.9g
### New Features

**Per-Show Randomize in Round Robin Channels (channel_manager.py, channels.py)**
- Individual shows within a Round Robin channel can now be set to play in
  random order while other shows in the same channel remain sequential.
- Example: Show A plays in order (S01E01, S01E02, ...), Show B plays randomly,
  Show C plays in order — all rotating together in a single channel.
- Configured per-show via a new wizard step that appears for Round Robin
  channels with 2 or more shows. Fully random channels skip this step since
  all shows are already random.
- The `randomize` key is stored on the individual show dict inside `shows[]`
  in channels.json. It is absent for sequential shows (clean default). Fully
  random channels are unaffected — the channel-level flag still applies to all
  shows when no per-show override is present.
- Queue building (`_build_fresh_queue`, `_topup_queue`): each show now
  resolves its effective randomize mode as
  `show.get("randomize", channel_randomize)` before picking episodes.
- State advancement (`advance_show`): the correct sequential or random advance
  method is chosen per show based on the same per-show flag, ensuring the
  state pointer is updated correctly after each episode plays.
- Exhaustion detection (`_channel_exhausted`): mixed-mode channels are handled
  correctly — sequential shows use the `next_episode_id=None` sentinel;
  random shows use the tail `local_played` coverage check. The channel is only
  considered exhausted when all shows have met their own exhaustion criteria.

---

## Version 1.0.9f
### New Features

**Episodes Per Slot (channel_manager.py, channels.py)**
- Each show in a TV channel (both Round Robin and Random) can now contribute
  more than one consecutive episode per rotation turn.
- Configurable per-show via a new wizard step that appears for all TV channels
  with 2 or more shows.
- Example: Show A=2, Show B=1, Show C=3 produces the pattern AA, B, CCC,
  AA, B, CCC ... for Round Robin, or the same slot counts with randomly chosen
  episodes for Random channels.
- Defaults to 1 for all shows — existing channels are completely unaffected.
- The `episodes_per_slot` field is stored per-show inside the `shows[]` array
  in channels.json. It is absent (treated as 1) for shows where the value was
  never set or was left at the default.
- Duplicate-file deduplication continues to work correctly inside the inner
  slot loop — a multi-episode file collision advances the episode pointer and
  retries within the same slot rather than skipping the show's turn entirely.
- Top-up queue builder (`_topup_queue`) applies the same per-slot logic,
  ensuring the rotation pattern is preserved after each refill.

---

## Version 1.0.5
### New Features

**Clean Channel Names (channels.py)**
- Channel list now shows clean channel names only — status indicators removed from labels.
- New "Channel Info" context menu item (first in list) shows a formatted dialog with: channel type, rotation mode, playback/recycle setting, show list (TV) or movie count (Movies), queue depth, and interleave configuration.

**Backup & Restore (router.py, settings.xml)**
- New "Backup & Restore" category in Settings.
- "Backup Addon Data" — copies channels.json, state.json, and settings.xml to a timestamped folder (SmartChannels_Backup_YYYYMMDD_HHMMSS) in a user-selected destination.
- "Restore Addon Data" — browse to a backup folder, select which files to restore. Warns before overwriting. Notes if Kodi restart is needed after restoring settings.xml.
- Queue files excluded from backup — they are rebuilt automatically on next channel launch.

**Playlist Show Names (player.py)**
- TV episode ListItem labels now include show name: "Show - S01E14 - Episode Title". Visible in Kodi playlist overlay during playback.
- Fixed tvshowtitle field mismatch (was reading "showtitle", now correctly reads "tvshowtitle").

---

## Version 1.0.4
### Bug Fixes

**Queue Refill (channel_manager.py)**
- Fixed queue top-up producing too few items after multiple refill cycles. The safety guard compared the absolute `show_index` (which grows with each refill) against a relative limit, causing early loop exit. Fixed to use a per-call iteration counter instead.

**Manual Starting Point Picker (channels.py)**
- Fixed the "Set Starting Points Manually" option being unreachable in the channel creation wizard. The manual picker block was incorrectly nested inside the Surprise Me branch due to `if` vs `elif` indentation, making it silently skip when selected.

**State.json Cleanup — played_ids Bloat**
- Sequential mode: `played_ids` in the show state entry no longer accumulates. It is always written as `[]` since position tracking uses `next_episode_id` exclusively.
- Random mode: `played_ids` in the show state entry no longer accumulates. No-repeat tracking is handled entirely by the queue tail (`__queue_tail__` → `played_ids`), which correctly resets per cycle. Two separate code paths were fixed: `_advance_random` in `channel_manager.py` and `advance_state` in `service.py`.

**Exact Resume Feature (service.py, channel_manager.py)**
- Resume was implemented in `SmartPlayerMonitor` (player.py) which is garbage-collected when the plugin call returns. Moved full resume implementation to the long-lived `SmartPlayer` in service.py.
- Fixed `getTime()` raising "not playing any media" in `onPlayBackStopped` by using poll-saved position instead.
- Fixed `onAVStarted` race condition where `_current_ep` was not yet set when the resume check ran. Now uses a background thread (`_do_resume_check`) that identifies the playing episode directly from the queue file rather than waiting for `_current_ep`.
- Fixed resume dialog appearing after episode had already started playing. Player now pauses before showing dialog, then seeks and unpauses.
- Fixed player staying frozen after resume seek. Replaced `isPaused()` toggle with `xbmc.executebuiltin("PlayerControl(Play)")`.
- Fixed `getSetting("resume_on_stop")` returning wrong value at service startup (Kodi settings not fully loaded yet). Settings are now read lazily on first channel launch.
- Fixed resume position not updating on Android/Shield. Poll timer now queues the save via `_pending_resume_save` for the main service thread to write, since `xbmcvfs` SMB operations must run on the main thread on Android.

**Resume Data Lifecycle**
- Simplified to single-file: `save_resume_position_local` now writes directly to state.json (shared path) instead of a separate `resume_backup.json`. Eliminates the promote-on-stop step and enables crash recovery from the last poll save.
- Resume entries are now correctly cleared in all three scenarios: natural episode finish (via `set_now_playing` detecting episode transition), skip (via skip loop in `_check_now_playing`), and playlist end (via `onPlayBackEnded`).
- Channel deletion now cleans up all `resume:channel_id:*` keys from state.json.
- File path comparison used instead of `episodeid` for episode transition detection — more reliable across TV and movie items.

**Orphaned Shared Data Warning**
- Suppressed false-positive warning on secondary clients. A missing local `channels.json` with shared storage configured is the expected state for secondary clients, not an error.

**Playlist Labels (player.py)**
- TV episode `ListItem` labels now include the show name: `"Show - S01E14 - Episode Title"`. Previously only the episode title was shown in the Kodi playlist overlay during playback.
- Fixed `tvshowtitle` field name mismatch (`"showtitle"` vs `"tvshowtitle"`) in both the `InfoTagVideo` path and the `setInfo` fallback.

---

## Version 1.0.3
- Surprise Me starting point option
- Shuffle Rotation Try Again loop
- Count Per Interleave setting
- Exact Resume infrastructure (settings, channel_manager helpers)
- Management Items Toggle setting
- Show interleaved items in channel detail view

## Version 1.0.2
- Interleave bug fixes (max/needed, jitter simulation, TV→TV nested guard)
- Movie deck fix (interleave_order filtered against all_available)
- Upcoming list labels for all four interleave combinations

## Version 1.0.1
- Multi-client shared SMB storage (Group G)
- Queue building, top-up, refill threshold
- TV episode interleaving round-robin
- Movie channel interleaving
- Stop/resume on interleaved movies
- Reset Channel to Start context menu
- Reset individual show to S01E01 context menu
- num_upcoming_programs setting
- Delete All Addon Data on SMB

## Version 1.0.0
- Initial release
- Smart TV channel creation with round-robin episode interleaving
- Persistent queue and state files
- Continuous playback with automatic queue top-ups
- Kodi 21 Omega (Python 3)
## Version 1.2.0n

### Repo submission preparation

- **addon.xml:** Fixed `<news_url>` tag to `<news>` per Kodi repository
  spec. All other required fields already present and correct.
- **LICENSE:** Added GPL-2.0 license file to addon root (matches
  `<license>GPL-2.0-only</license>` declared in addon.xml).
- **README.md:** Updated from 1.1.9s to 1.2.0n. Added Audio Channel,
  Party Mode, Songs Cache, Channel Scheduling, Move Up/Down, and Rebuild
  Songs Cache to all relevant sections. Updated data files table, settings
  table, file layout, and known limitations.
- **Code audit:** No bare `open()` calls, no wildcard imports, no Python 2
  patterns. All strings through strings.po. Fully Python 3 compliant.
- **fanart.jpg:** 1280x720 confirmed. **icon.png:** 256x256 confirmed.

**Files changed:** `addon.xml`, `LICENSE` (new), `README.md`


## Version 1.2.0o

### Feature — Ticker: schedule-aware upcoming programming promos

The Lower Third Ticker now includes a third entry type alongside
next-item and show-promo entries: **schedule promos**.

For each active schedule firing within the next 24 hours whose target
channel is visible, a ticker entry is generated showing:
- **Phrase line:** time context + channel name — e.g.
  "Tonight at 8:00 PM — Comedy TV" or "Saturday at 9:00 PM — Drama"
- **Title:** schedule name + item count + source channel —
  e.g. "Tuesday Night Drama (4 eps from Til Death)"

Time context adapts automatically: "Tonight at" for schedules firing
later today, "Tomorrow at" for tomorrow, or "Day at" for named-day
schedules further out. Schedules that have already fired today are
excluded. Inactive schedules are excluded.

**New strings:** #32789–#32792
**File changed:** `resources/lib/ui/side_panel.py`

### Feature — Channel Info: Schedules section

Channel Info now shows a Schedules section at the bottom for any
channel that participates in the scheduling system — either as a
target (receives blocks) or as a source (feeds blocks).

Each entry shows: schedule name, item count, counterpart channel name,
day and time (12-hour format). Inactive schedules are shown with an
[inactive] label rather than hidden — so the user can see the full
picture even for paused schedules.

Example output:
```
Schedules
  Receives: Tuesday Night Drama  (4 items from Til Death at Tuesday 9:00 PM)
  Feeds: Weekend Movies  (2 items to Movie Night at Saturday 8:00 PM)
```

The section is omitted entirely when no schedules involve this channel.

**New strings:** #32793–#32796
**File changed:** `resources/lib/ui/channels.py`


## Version 1.2.0p

### Fix — Songs cache rebuild failing with unexpected keyword argument

`_rebuild_songs_cache()` in `service.py` was still passing
`progress_callback=_on_progress` to `build_songs_cache()`, which had
that parameter removed in 1.2.0m when the blocking progress dialog was
replaced with toast notifications. This caused both the automatic startup
rebuild and the manual "Rebuild Songs Cache" button to fail silently with
`unexpected keyword argument 'progress_callback'`, leaving the songs cache
permanently at 999 days old.

**File changed:** `service.py`


## Version 1.2.0q

### Fix — Songs cache build taking 3+ minutes due to UDF ORDER BY

Each paginated `GetSongs` RPC call included `"sort": {"order": "ascending",
"method": "title"}` which triggered Kodi's `udfNaturalSortFormat()` MySQL
user-defined function. Because this UDF is not indexed, MySQL performs a
full table sort on every single page request — meaning a 15,500-song library
re-sorted all 15,500 rows 31 times, costing ~7 seconds per page regardless
of batch size. Total build time: 3.5+ minutes.

Fix: removed the `"sort"` parameter from both `build_songs_cache()` and the
fallback live RPC in `get_all_songs()`. MySQL now does a simple sequential
scan. Each page takes under 1 second; total build time should drop to under
30 seconds.

Order in the cache is not important — audio channel builders sort and filter
in Python after loading from cache.

**File changed:** `resources/lib/library.py`

### Fix — Songs cache build: duplicate threads when manually triggered

Two threads were running simultaneously because the startup check launched
one thread automatically, and the user (not knowing it was running) clicked
"Rebuild Songs Cache" to launch a second. Both threads competed for the same
MySQL connections, causing page queries to take up to 21 seconds instead of 7.

Fix: startup now shows a toast notification so the user knows the cache is
building. Two variants: "Building songs cache in background..." (first time,
cache missing) and "Refreshing songs cache in background..." (stale cache).
A "Rebuild complete" toast fires when finished.

**Files changed:** `service.py`,
`resources/language/resource.language.en_gb/strings.po`
(new strings #32797, #32798)

