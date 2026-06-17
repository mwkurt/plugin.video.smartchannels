# Smart TV Channels — Changelog

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
