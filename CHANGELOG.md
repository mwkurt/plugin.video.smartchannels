## 3.1.38
- Fix: Season 0 / Specials could not be added as exceptions in the channel wizard's Add Exceptions dialog. Root cause: `e.get("season")` returns `0` for Season 0, which is falsy in Python, so the list comprehensions in `build_episode_filter` and `build_episode_exclusions` (dialogs.py) silently excluded all Season 0 episodes. Fixed both occurrences: `if e.get("season")` → `if e.get("season") is not None`.
- Fix: Channel Icon Folder and Backup Path settings could not be cleared or typed into freely because they used Kodi's `type="folder"` widget, which has no delete/clear affordance. Changed both settings to `type="text"` so the user can edit or clear the path directly, and added a companion `[Browse...]` action button for each (new string #32913) that opens Kodi's native folder-picker dialog and writes the chosen path back to the setting. New router actions `browse_icon_folder` and `browse_backup_path` handle the picker; both registered in addon.py dispatch table.

## 3.1.37
- Fix: Coming Up Next overlay incorrectly appeared when a non-SmartChannels player (e.g. IPTV/NextPVR) started playback while no SmartChannels channel was playing. Root cause: now_playing.json was never cleared on stop, so onAVStarted mis-identified the foreign playback as an active SmartChannels session, loaded the old queue, started the position poll, and CUN fired against stale queue data. Fix: added SmartPlayer.clear_now_playing() in player.py (sets active_channel_id to None in the local now_playing.json). Called from onPlayBackStopped in service.py, before any stop-reason guard, so it fires unconditionally on every stop.

## 3.1.36
- Fix: carousel multi-client double-pop guard. In _do_pops (carousel.py), re-read carousel state immediately before committing any writes. If last_pop_time has already reached the target new_last_pop value, another client on shared SMB storage already handled this interval — return without popping. Eliminates the race window where two clients both observe elapsed >= interval within the SMB attribute cache window and both pop the same carousel slot.
- Fix: shared storage path validation failed with "Location not available" when the SMB share name contained a space (e.g. smb://PVR/Users/Public/Smart Channels Share). xbmcvfs.exists() returns False for SMB directory paths unless they end with a trailing slash — without it Kodi's VFS treats the path as a file check. Added _dir_exists() helper in utils/paths.py that appends "/" for network paths before calling xbmcvfs.exists(). Used in resolve_path() and in onSettingsChanged() in service.py (both the mkdirs guard and the failure check).

## 3.1.35
- Feature: when the shared_storage_path setting changes, SmartChannelsMonitor.onSettingsChanged now detects the change and offers to migrate all data files (channels.json, state.json, schedules.json, queue_*.json, now_playing.json, local_library.json, songs_cache.json, missing_durations.txt) to the new location. Covers local→shared, shared→local, and shared→shared transitions. On shared→shared or local→shared, optionally deletes the old files after a successful copy. New strings #32390, #32391, #32392 added. migrate_storage_path(), delete_files_in_root(), and _list_files_in_root() helpers added to utils/paths.py.

## 3.1.34
- Fix: carousel was breaking the interleave pattern on channels with a combo block interleave source. When the carousel popped an interleaved combo slot item and called build_one_slot for its replacement, the returned item was missing _channel_id. On the next carousel pop of that replacement, consumed_cid resolved to the host channel (not the combo source) so is_combo_channel() returned False and it was treated as a primary TV item instead of an interleaved combo slot. Fixed by adding item["_channel_id"] = channel_id in build_one_slot in combo.py. This also fixes the same missing tag for normal playback replacements through _handle_combo_slot in service.py, which uses the same build_one_slot call.

## 3.1.33
- Fix: side panel context menu for Combo Block channels also removed Move Up and Move Down — combo blocks are always hidden so reordering them has no visible effect.
- Fix: interleave wizard frequency input showed "How many items to insert at each slot?" (#32343) as its heading — same string as the subsequent count_per input, causing the user to see the same prompt twice. Fixed: frequency input now uses #32341 "Fixed - insert exactly every N items" for fixed mode and #32342 "Random - insert every N +/- J items" for jitter mode, matching the mode the user just selected. count_per input retains #32343.

## 3.1.32
- Fix: side panel context menu for Combo Block channels included "Set Channel Icon" option. Combo blocks are always hidden and never directly visible to users so an icon serves no purpose. Added "set_channel_icon" to the combo exclusion filter in side_panel.py alongside the existing "play_channel" and "reset_channel" exclusions. Note: the main channel list context menu in router.py already correctly excluded Set Icon for combo blocks via the is_combo guard.

## 3.1.31
- Fix (second attempt): the 3.1.30 fix for combo-block interleave episode skip was in the wrong place. _load_foreign_items is called before the weaver decides how many items to insert — so restoring state there wiped tv_next_ep entirely. Root cause: ComboQueueBuilder.build() fetches all needed items (e.g. 28 for 14 units × eps_per_slot=2), but the weaver may only insert a subset. tv_next_ep was left pointing past all fetched items, not just the inserted ones. Fix: new _sync_combo_state_from_queue() method, called after apply_interleave_list() returns in both regenerate_queue and _build_fresh_tv_queue. Scans the woven queue for the last episode actually inserted per combo TV slot/show, then sets tv_next_ep to the episode after that one. Reverted the _load_foreign_items state save/restore from 3.1.30 as it is no longer needed.

## 3.1.30
- Fix: when a Combo Block is used as an interleave source, _load_foreign_items called ComboQueueBuilder.build() which advanced tv_next_ep and show_slot state keys for all combo slots. This caused the first 1-for-1 replacement to skip episodes equal to the number consumed during the interleave build. For a slot with episodes_per_slot=2 and a 14-unit initial build, tv_next_ep was advanced 28 episodes by the interleave weave, so the first replacement fetched S02E05 instead of S01E15. Fixed by saving all combo:{id}:slot:* state keys before the interleave build and restoring them after — mirroring the existing TV-channel cursor save/restore pattern in _load_foreign_items.

## 3.1.29
- Revert: removed all Container.Refresh / Window.IsActive attempts from carousel pop (3.1.25 through 3.1.28). Both xbmc.getInfoLabel and xbmc.getCondVisibility return empty/unreliable values from the service background thread in Kodi 21 — no viable guard is available from this context. The channel list updates correctly when navigating away and back. Automatic live refresh from a background thread is not achievable via this mechanism.

## 3.1.28
- Fix: carousel Container.Refresh guard was checking Window.IsActive(videos) which is not a valid Kodi window name. Corrected to Window.IsActive(MyVideoNav) — window ID 10025, the video browser/plugin listing window in Kodi Estuary. This is the window that is active when browsing the SmartChannels channel list or episode list.

## 3.1.27
- Fix: carousel Container.Refresh guard was using Container.FolderPath which returns empty string from a background service thread. Replaced with xbmc.getCondVisibility("Window.IsActive(videos)") which is readable from any thread. Fires only when the Kodi video browser window is in the foreground — no-op during playback, home screen, settings, or other addons.

## 3.1.26
- Diagnostic: added log of Container.FolderPath value at carousel pop time to determine why Container.Refresh guard is blocking. Temporary — will be removed once root cause confirmed.

## 3.1.25
- Enhancement: carousel channel episode list now refreshes automatically after a pop when the user is browsing the addon. Container.Refresh fires once per pop cycle (after all pops complete, not per individual pop) guarded by Container.FolderPath containing "plugin.video.smartchannels" — prevents refreshing unrelated addons or Kodi library views.

## 3.1.24
- Fix: interleaved replacement items were not tagged with _interleaved=True and _channel_id, so when that replacement was later consumed or skipped, it was treated as a primary item and replaced from the host channel (wrong type). A movie replacement appended to a TV channel queue had no interleave tags, so skipping it produced a TV episode instead of another movie. Fixed in get_one_replacement: after fetching the replacement from the source channel, copy _interleaved, _channel_id, _silent, and _channel_name from the consumed item onto the replacement before returning it. This ensures every interleaved item in the queue — original or appended — carries the correct tags throughout its lifetime.

## 3.1.23
- Fix: interleaved items (e.g. movies woven into a TV channel) were replaced with a TV episode instead of a replacement from their source channel. get_one_replacement() in channel_manager.py always routed via the host channel type — so a consumed interleaved movie on a TV host channel resolved as "tv" and appended the next TV episode. Fixed: when consumed_item._interleaved is True, look up the source channel via consumed_item._channel_id and route to the correct replacement method (_replacement_movie, _replacement_folder, or _replacement_tv) for that source channel. Non-interleaved primary items are unaffected.
- Strings: #32639 changed from "Minimum items per channel (0 = show all)" to "Minimum episodes per channel (0 = show all)".

## 3.1.22
- UX: renamed "Default Queue Size" (#32014) to "Default Minimum Queue Size" and "Enter target queue size" (#32219) to "Enter minimum queue size" to clarify that for TV channels the queue_size is a floor not a hard cap — the initial build always completes a full show cycle so every show has a slot in rotation, which may exceed the configured minimum.

## 3.1.21
- Revert: the queue size cap for TV channels added in this version was incorrect. The round-robin builder must complete a full show cycle on initial build so every show has an episode in the queue — otherwise shows beyond queue_size would never appear in rotation. The "oversized" initial queue for large genre channels (e.g. 226 shows = 226 items) is correct and intentional. The queue_size setting governs subsequent 1-for-1 replacements and is appropriate for movie/folder/audio channels but not for TV channels with many shows. No code change from 3.1.20 in this release.

## 3.1.20
- Fix: View Missing Durations Log in Settings → Tools had no way to clear the log. Changed from a plain textviewer to a select() dialog offering "View Missing Durations Log" and "Clear Missing Durations List". Clear shows a yesno confirmation (#32228) then deletes missing_durations.txt and shows a notification (#32229). Added #32228 and #32229 to strings.po.

## 3.1.19
- Fix: scheduled block items inserted into a carousel-enabled non-playing channel were being popped by the carousel with a 1-for-1 replacement appended — wrong, they should be popped and discarded with no replacement. The queue shrinks by the block item count as the carousel consumes them, then returns to normal depth once the block is exhausted and regular 1-for-1 resumes. Fix: in carousel.py pop loop, detect _schedule_id on the popped item. If set, skip _apply_replacement, write the shortened queue, call ScheduleManager.on_block_item_complete() for tracking, and continue. Interleaved items (_interleaved=True) never have _schedule_id and are completely unaffected.

## 3.1.18
- Fix: valid ffprobe explicit path showed "not found" error. os.path.isfile() was used without xbmcvfs.translatePath() first — on Windows, paths with certain representations may not resolve correctly through Python's os module. Fixed by calling xbmcvfs.translatePath() on the explicit path before the isfile() check.

## 3.1.17
- Fix: ffprobe scan proceeded even with a bogus explicit path set. find_ffprobe() was falling through to shutil.which() PATH search when the explicit path was invalid — Kodi's bundled FFmpeg on the process PATH was found instead. Fixed: when an explicit path is configured but doesn't exist, return None immediately without PATH fallback so the wizard correctly shows the "not found" error dialog.

## 3.1.16
- Fix: Reset Channel in side panel context menu did nothing. Was calling self._manager.reset_channel() which doesn't exist on ChannelManager — it's a router method. Fixed to call the underlying ChannelManager methods directly: clear_cursor, clear_channel_resume_points, write_channel_queue([]), build_channel_queue, write_channel_queue.
- Fix: Delete Channel in side panel context menu called self._manager.find_combo_owner() which doesn't exist on ChannelManager. Removed the fallback call — get_combo_owner() is sufficient; delete_channel() handles cleanup of owned combos internally.

## 3.1.15
- Fix: carousel replacement could place a duplicate episode of the same show adjacent in the queue. When the carousel pops an episode from the front and appends the next episode of the same show, that next episode may already exist in the queue from the initial build. Fix: in carousel.py, before appending the replacement check whether its episodeid already exists in the current queue. If it does, call get_carousel_replacement() one more time to advance past it.

## 3.1.14
- Fix: side panel context menu Edit Channel and Manage Interleave did nothing. Both were calling non-existent methods on a ChannelUI instance (edit_channel_wizard, manage_interleave_dialog). The correct calls are the standalone functions run_edit_wizard() from ui/channels.py and run() from ui/wizards/interleave.py — the same functions the standard router uses.

## 3.1.13
- Fix: Coming Up Next audio overlay displayed artist as a Python list repr (['Artist Name']) instead of a string. Kodi library returns the artist field as a list; _build_lines in coming_up_next.py treated it as a string. Fixed by joining list items with ", " when artist is a list.

## 3.1.12
- Fix: fire_block() tried to read a queue file for combo block sources, found none (correctly — combo blocks have no queue file by design), then called build_channel_queue() which wrote a 60-item queue file to disk — violating the core architecture rule that combo blocks never have queue files. Fix: when source channel_type is "combo", fire_block() now takes a separate path that calls ComboQueueBuilder.build_one_slot() directly for each slot in round-robin order, using state keys as the position authority. No queue file is read or written for the combo source. The 3.1.11 unit-size multiplier still applies so item_count=1 correctly pulls all slots of one unit.

## 3.1.11
- Fix: combo block schedule source only inserted 1 slot instead of 1 complete unit. fire_block() pulls item_count individual items from the source queue — for a regular channel that's correct, but for a combo source item_count=1 means 1 unit (all slots), not 1 slot. Fix: when source channel_type is "combo", multiply item_count by _combo_unit_size() before the pull loop so 1 unit = all slots are pulled and inserted together. active_block item_count stores len(block_items) (the actual slot count) so on_block_item_complete counts correctly.

## 3.1.10
- Fix: no feedback when creating a recurring schedule with a time that has already passed today. The once-only past-time check showed an error and blocked creation, but recurring schedules had no equivalent check at all — the schedule was created silently and the 3.1.09 code-level fix would defer it to tomorrow without the user knowing. Added an informational ok() dialog using existing string #32783 ("The time {0} has already passed today. The schedule will next fire tomorrow.") for all non-once recurrence types when start_time <= current time. Does not block creation — the schedule is saved and will fire correctly tomorrow.

## 3.1.09
- Fix: new daily/recurring schedules fired immediately on the next tick if the configured time had already passed today. New schedules have last_fired=0, and _already_fired_today() returns False for 0, so all checks passed and fire_block() ran at once. Fix: in schedule_wizard.py, when building the definition for a new (not edit) recurring schedule, if start_time <= current time, set last_fired=time.time() so the schedule is treated as already fired today and waits until tomorrow. If start_time is still in the future today, last_fired stays 0 and the schedule fires correctly at the configured time.

## 3.1.08
- Fix: Coming Up Next corner position and Logo Overlay corner/size/opacity enum settings not selectable. Kodi's type="enum" settings require inline pipe-delimited values in the values= attribute — string ID references are not resolved at runtime. Fixed cun_corner, logo_overlay_corner, logo_overlay_size, and logo_overlay_opacity to use inline values ("Top Left|Top Right|Bottom Left|Bottom Right", "Small|Medium|Large", "Low|Medium|High").

## 3.1.07
- Fix: Coming Up Next overlay showed the first regular episode after the block rather than the next block item during a scheduled block. _get_next_episode always skipped _schedule_id items, so while playing block item 1 of 3 it would skip items 2 and 3 and show the first regular episode. Fix: if the current item is a block item, block items are valid next items. Only skip block items when currently playing regular content (so CUN doesn't preview an upcoming scheduled block during normal playback).

## 3.1.06
- Fix: NameError 'xbmcaddon is not defined' in router.py list_channels() — the side panel branch added in 3.1.01 called xbmcaddon.Addon() but xbmcaddon was never imported in router.py. Fixed by using self.addon which is already available.

## 3.1.05
- Fix: false skip detection on block reload corrupted queue tracking for the entire session after a scheduled block played. When start_channel() rebuilds the Kodi playlist during a block reload, Kodi fires an onAVStarted callback showing a position jump (e.g. file_pos=3 vs _queue_pos=0). The skip detector misread this as the user skipping 3 items and fired 3 unnecessary replacements, then the queue/position state was out of sync for all subsequent episodes ("playing file not in queue — defaulting to 0" for every episode). Fix: _block_reload_pending flag set to True in _maybe_start_block_reload before launching the reload thread. onAVStarted checks this flag when it detects an apparent skip — if set, the skip is suppressed and the flag cleared. Real user skips are unaffected.

## 3.1.04
- Port (Item H): ffprobe batch NFO scanner. utils/ffprobe_scanner.py copied as-is. ui/ffprobe_wizard.py ported with 3.x string IDs (#32904-32911). Tools section added to settings.xml with ffprobe_path text setting (visible always), ffprobe_scan_action (Windows only), and view_missing_durations_global action. Router actions ffprobe_scan and view_missing_durations_global wired up. String #32912 ("Tools") added for category label.
- Port (Item F): Auto-create channels wizard. ui/auto_channels.py ported from 2.x with all 51 string IDs remapped to correct 3.x values. auto_create_channels router stub replaced with full AutoChannelUI delegation. Wizard flow: content type -> group by -> minimum items -> settings confirmation -> interleave -> preview multiselect -> confirm -> progress -> done. Supports Genre, Decade, Genre+Decade, and Studio/Network groupings. Creates invisible companion movie channels for interleaved TV+Movie channels. Surprise Me! starting episodes supported.
- Strings #32904-32912 added to strings.po.

## 3.1.03
- Fix: folder item duration capture never ran in 3.x. capture_folder_duration() existed in channel_manager.py and write_companion_nfo() in duration_cache.py, but service.py never called them. When a folder item finishes playing naturally and it used the default duration (duration_is_default=True), onPlayBackEnded now calls getTotalTime() to get the real duration and passes it to capture_folder_duration(). This writes a companion NFO alongside the video file and updates the queue item in place, so the next queue build uses the real duration instead of the default. Ported from 2.x set_now_playing().

## 3.1.02
- Fix: all string IDs in side_panel.py were 2.x IDs that map to completely different text in 3.x strings.po (fresh-start rewrite at #32000). Every _S_ constant and every inline self._s() call corrected to the proper 3.x ID. 32 string ID corrections in total. No hardcoded strings remain.

## 3.1.01
- Port (Item D): Side Panel. Ported from 2.x with all ticker code removed (controls 400-404 exist in XML but are not driven — reserved for Item K). Queue watcher thread kept intact. Three skin XML files copied (Default/1080i, skin.confluence/720p, skin.estuary/1080i). Side panel branch added to list_channels() in router.py: when use_side_panel=True, opens the WindowXML panel; falls back to standard listing on error.
- Fix (TC-30.17): Reset Show context menu item was missing from the standard episode list view (open_channel in router.py). The backend (reset_next_episode action + reset_show_to_start in channel_manager) already existed. Added li.addContextMenuItems() for TV episode items that have a _show_id, wiring up to the existing action. String #32334 used as label.

## 3.1.00
- Port (Item C): Coming Up Next overlay. Ported from 2.x to resources/lib/overlays/coming_up_next.py. bg_overlay.png copied to overlays/. Path in ControlImage updated to new location. load_settings() extended with min_duration and suppress_silent. CUN trigger added to _poll_position (queues _pending_overlay when time_left <= lead). _get_next_episode() helper added — skips block and silent items. CUN dispatch added to _run_tick_loop main thread. _overlay_shown reset on onAVStarted. _pending_overlay cleared on onPlayBackStopped.
- Port (Item E): Logo overlay. Ported from 2.x to resources/lib/overlays/logo_overlay.py (unchanged — no path adjustments needed). SmartChannelsLogoOverlay instantiated in __init__. Logo shown in onAVStarted worker after resolve_channel_icon(). Logo hidden in onPlayBackStopped.

## 3.0.99
- Fix (Item B): interleave source picker allowed the same channel to be added as a source by multiple host channels. Added get_interleave_source_owner() to channel_manager — scans all channels' interleave sources to find if a given channel is already owned by another. Eligible filter in the picker now excludes channels already serving as a source elsewhere, silently (no new dialog or string — if the list empties, #32330 fires as normal). Combo block one-owner rule was already enforced; this brings regular channels in line.

## 3.0.98
- Fix: scheduled block items replayed every time the channel was stopped and restarted. Two root causes:
  1. active_block state key (format: "sch_<id>:active_block") was deleted on every _save_state() call by the orphan-key pruning loop, which treats any key whose prefix is not a live channel ID as an orphan. Schedule IDs start with "sch_", not a channel UUID. Fix: add "sch_" to the pruning exemption list alongside "resume:", "combo:", and "pending_seek:". This also fixes on_block_item_complete always reporting "no active block".
  2. Block items were never popped from the disk queue as they played. _do_replacement() is correctly skipped for block items, but nothing else removed them from disk. On channel restart, start_channel() reloads from disk and finds the block items still at the front. Fix: when a block item completes in onPlayBackEnded, pop queue[0] from the disk queue before incrementing _queue_pos.

## 3.0.97
- Fix: source channel queue not replenished after fire_block() consumes items from it. fire_block() popped N items from the source queue and wrote it back shorter, but never called get_one_replacement() for each consumed item. Source queue shrank by item_count on every schedule fire. Fix: after writing the shortened source queue, loop through each consumed item and call get_one_replacement() using the original source channel_id (block_items have _channel_id rewritten to target_id, so a clean copy is used for the cursor lookup). Each replacement is appended and the replenished queue written back to disk.

## 3.0.96
- Fix: after a scheduled block plays, the episode that was playing when the block fired replays instead of advancing to the next episode. Root cause: fire_block() prepends block items to the disk queue, so the finished episode moves from index 0 to index N. The block reload path skipped _do_replacement entirely, leaving the finished episode in the disk queue. start_channel() then reloaded it. Fix: new _consume_finished_before_block_reload() helper locates the finished episode in the disk queue by file path, removes it, and appends the correct next episode before the reload — maintaining 1-for-1 while preserving the block items at the front.

## 3.0.95
- Fix: scheduled block still not playing despite 3.0.94 queue sync fix. Root cause: _maybe_start_block_reload was called AFTER _do_replacement in onPlayBackEnded. By the time it synced the queue and called start_channel(), Kodi had already advanced to the next regular item. Fix: check _pending_block_channel before _do_replacement. When a block is pending, skip the replacement entirely and go straight to _maybe_start_block_reload.

## 3.0.94
- Fix: scheduled block never played even though fire_block() wrote items to disk correctly. Root cause: fire_block() prepends block items to the disk queue but self._queue (in memory) never sees them. onPlayBackEnded checks the in-memory queue for _schedule_id to decide whether to take the block path -- it always found regular content and fired _do_replacement instead. Fix: _maybe_start_block_reload now reads the disk queue and syncs self._queue / self._queue_pos before calling start_channel(), so memory, disk, and the new Kodi playlist are all consistent with the block items at the front.
- Fix (from 3.0.93, now included): block reload daemon thread imported SmartChannelsPlayer from player.py -- class is named SmartPlayer. This caused the reload to crash silently on top of the above bug.
- Fix (from 3.0.93, now included): dead combo_tail block in _handle_skip referenced an undefined variable, logging a spurious warning on every skip involving combo items.

## 3.0.93
- Fix: block reload daemon thread imported `SmartChannelsPlayer` from `player.py` — class is named `SmartPlayer`. Import error silently killed the reload; channel never switched to block items after schedule fired.
- Fix: dead `combo_tail` block in `_handle_skip` referenced an undefined variable, causing a warning log on every skip that involved combo items. All replacements (combo and primary) were already correctly handled by the `replacements` list below it; the orphaned block is removed.

## 3.0.68
- Fix: channel info carousel display showed wrong remaining time in duration mode — was using carousel_interval (60 min default) instead of the queue-front item's actual duration. Now reads front item duration from queue and displays correct remaining time.

## 3.0.67
- Fix: interleave.py used len(slots) to calculate combo unit size for items_per_fire and insert_count — now uses _combo_unit_size() which sums eps_per_slot/movies_per_slot across all slots. With eps_per_slot=2 on 3 slots and 1 on the 4th, unit was 4 items instead of 7.

## 3.0.66
- Fix: EPS offered for single-show TV slots (was restricted to 2+ shows only)
- Fix: EPS body text uses correct string for single-show (32275) vs multi-show (32271)
- Fix: EPS added to folder slots (items per slot)
- Fix: slot_count for folder slots in build() and build_one_unit() now reads episodes_per_slot instead of hardcoding 1

## 3.0.65
- Fix: build_combo_tv_slot rewritten to use unit_sequence ([show_idx * eps_per_slot]) with show_slot as position index. Works correctly for both count=1 (1-for-1 replacement via build_one_slot) and count>1 (initial build). With A(eps=2),B(eps=1): sequence=[A,A,B], show_slot advances 1 per episode fetched, giving correct A_ep1,A_ep2,B_ep1,A_ep3,A_ep4,B_ep2... pattern.
- Restored show_slot state persistence — required for 1-for-1 replacement to rotate correctly through shows across successive calls.

## 3.0.64
- Fix: show rotation (show_slot advance) disabled when any show in a TV slot has eps_per_slot > 1 — rotation broke the expected fixed order (A_ep1, A_ep2, B_ep1 every unit). Rotation preserved for original all-eps_per_slot=1 case.

## 3.0.63
- Fix: build_combo_tv_slot round-robin now fetches eps_per_slot consecutive episodes per show per unit turn, giving correct [A_ep1, A_ep2, B_ep1] grouping instead of interleaved [A_ep1, B_ep1, A_ep2]
- Refactor: extracted _fetch_one_ep() helper inside build_combo_tv_slot, eliminating duplicated no-duration-skip logic

## 3.0.62
- Fix: episodes_per_slot now read from show dicts within slot (not slot level) in build() and build_one_unit() — was always returning 1 due to wrong dict lookup
- Fix: _run_slot_wizard random import consolidated to function top (was duplicated in two inline locations)
- Fix: Surprise Me starting point line continuation formatting corrected

## 3.0.61
- Fix: carousel.py _handle_combo_slot_pop rewritten to use build_one_slot (strict 1-for-1, matches service.py) — was using stale tracker-based approach that didn't account for episodes_per_slot/movies_per_slot
- Cleanup: removed dead pending_combo_unit methods from channel_manager.py (get/set/clear) — no longer used by service.py or carousel.py
- Cleanup: removed stale clear_pending_combo_unit call from _handle_skip primary item branch

## 3.0.60
- Fix: replaced private library._filter_items_in_python call in build_combo_movie_slot with public get_movies_with_filters

## 3.0.59
- Combo block wizard: TV slot now offers genre/year filter before show selection (libraries > 20 shows)
- Combo block wizard: TV slot now offers show rotation order (keep/shuffle/manual) for multi-show slots
- Combo block wizard: TV slot now offers episodes per slot for multi-show slots
- Combo block wizard: TV slot now offers per-show starting point (From Beginning / Manual / Surprise Me)
- Combo block wizard: Movie slot now offers pick specific movies as alternative to filters
- Combo block wizard: Movie slot now offers movies per slot
- Backend: build_combo_movie_slot honours explicit movies list; build() honours episodes_per_slot and movies_per_slot per unit; build_one_slot unchanged (strict 1-for-1)
- Backend: _apply_combo_slot_starting_points writes tv_next_ep state on channel create/update

## 3.0.24 (2026-09-06)
- BUG FIX: Skip detection updated Kodi disk queue correctly but did not
  update Kodi active PLAYLIST_VIDEO, leaving it out of sync.
  When user skipped forward N items: disk queue was updated (skipped items
  removed, replacements appended) but Kodi still had the skipped items in
  its playlist and did not have the replacement items.
- Fix: _handle_skip now also updates Kodi PLAYLIST_VIDEO after updating
  the disk queue: removes each skipped item by file path, then adds each
  replacement item to the playlist tail. Kodi playlist now stays in sync
  with the disk queue after a skip.

## 3.0.23 (2026-09-06)
- BUG FIX: Serial channel replacement still appending wrong show.
  Root cause: _replacement_serial used ep_pos from the cursor to decide
  whether to stay on the current show. But ep_pos resets to 0 when a
  recycled second pass is built into the queue, making the replacement
  think E01 is available again and appending it instead of the next
  unqueued episode.
- Fix: _replacement_serial now reads the queue tail as the source of
  truth. It finds the last queued episode of the consumed show, looks
  up its index in the episode list, and appends the next episode after
  it. Only advances to the next show when the last queued episode is
  the show's final episode. This is reliable regardless of cursor state.

## 3.0.22 (2026-09-06)
- BUG FIX: Serial replacement did not handle shows larger than queue size.
  With show1=15eps, queue_size=10: after consuming ep1, the replacement
  would advance to show2 instead of continuing show1 eps 11-15.
- Root cause: _replacement_tv_next_show always advanced show_slot regardless
  of whether the current show had remaining episodes.
- Fix: added _replacement_serial() which checks ep_pos vs total episodes
  for the consumed show. If episodes remain, stays on that show (appends
  next episode). Only advances to the next show when ep_pos reaches the
  end of the episode list. This ensures all episodes of show N play before
  any episode of show N+1, matching 2.x _advance_serial boundary detection.

## 3.0.21 (2026-09-06)
- BUG FIX: Serial channel replacement was staying on the same show instead
  of advancing to the next show in serial order. Root cause: _replacement_tv
  always picked the next episode of the consumed show regardless of playback
  mode. Fix: serial channels now always call _replacement_tv_next_show which
  advances show_slot to the correct next show in sequence.
- BUG FIX: Replacement items had channel_id set to the show ID integer instead
  of the channel UUID. Root cause: _pick_one_ep_no_slot_advance passed
  show.get("tvshowid") to _normalize_ep_fn as the channel_id argument.
  Fix: added channel_id parameter to _pick_one_ep_no_slot_advance and updated
  all callers to pass it through correctly.

## 3.0.20 (2026-09-06)
- Added new string #32227 'No visible channels have been created yet.'
- list_channels now shows #32227 when channels exist but all are hidden
  and Show Hidden Channels is disabled, instead of the generic
  'No channels have been created yet.' (#32226). Guides the user to
  enable Show Hidden Channels in Settings > Advanced.

## 3.0.19 (2026-09-06)
- Fixed AttributeError: Router object has no attribute _get_manager.
  list_channels incorrectly used self._get_manager() which only exists
  on SmartChannelsPlayer in service.py. Fixed to use self.manager
  which is how all other Router methods access channel data.

## 3.0.18 (2026-09-06)
- Fixed TC-P5-10: Show Hidden Channels setting was ignored — list_channels
  always called get_visible_channels() unconditionally. When all channels
  were hidden and Show Hidden Channels was enabled, the channel list showed
  'No channels have been created yet'. Fix: check show_hidden_channels
  setting and call get_all_channels() when enabled, matching 2.x behaviour.

## 3.0.17 (2026-09-06)
- Fixed TC-P5-10: selecting Hide (visible=False) was not suppressing the
  Carousel dialog in TV and Movie channel wizards. The visibility guard
  was missing — ask_carousel was called unconditionally regardless of
  the visible value. Fix: if visible=False, skip ask_carousel entirely
  and default carousel to disabled. Applied to both tv.py and movie.py.

## 3.0.16 (2026-09-06)
- Fixed 4 wrong string IDs in wizard dialogs:
  tv.py line 404: season list labels used #32478 (Choose Episode) instead
    of #32480 (Season {0}) — season picker was showing 'Choose Episode'
    as every season label instead of 'Season 1', 'Season 2' etc.
  tv.py line 429: episode list labels used #32869 (Source type) instead
    of #32693 (S{0}E{1} — {2}) — episode picker showed wrong text.
  dialogs.py line 246: Done item in season picker used #32355 (artifact)
    instead of #32491 (Done).
  dialogs.py line 269: episode label in exclusions inner loop used #32869
    (Source type) instead of #32693 (S{0}E{1} — {2}).

## 3.0.15 (2026-09-06)
- Fixed TC-P5-07: Episode exclusions show picker showed wrong strings.
  Line 299: Done item used #32355 (backslash artifact) instead of #32491 (Done).
  Line 301: Show picker heading used #32589 (Manage Exclusions — {} — {})
  instead of #32596 (Select show to manage exclusions).
- TC-P5-02 through TC-P5-06 confirmed passing from log analysis:
  filter wizard (387/1584 shows matched), shuffle order, manual order,
  episodes per slot (32 items built for 30 requested — correct rounding),
  episode filters (playcount and season filters fired correctly via JRPC).

## 3.0.14 (2026-09-04)
- BUG FIX: Surprise Me! (and manual starting points) ignored — all shows
  started from S01E01 regardless of configured starting_points.
- Root cause: starting_points was saved to channels.json correctly but
  _apply_starting_points() was never implemented in 3.0. The channel
  definition was saved but the cursor ep_pos was never seeded from it,
  so _build_tv_items always started from episode index 0.
- Fix: added _apply_starting_points() to channel_manager.py. For each
  show with a starting point, finds the episode index in the available
  episode list and sets cursor ep_pos[sid] to that index before the
  queue is built. Called from _build_fresh_tv_queue() immediately before
  _build_tv_items() so the queue always starts from the correct episode.

## 3.0.13 (2026-09-04)
- Fixed Surprise Me! starting point dialog showing 'Source type' instead of
  episode label. tv.py was using #32869 ('Source type') instead of
  #32693 ('S{0}E{1} — {2}'). Dialog now correctly shows e.g.
  'Show Name: S01E05 — Episode Title' for each selected show.

## 3.0.12 (2026-09-03)
- Fixed carousel tick error: 'SmartChannelsPlayer has no attribute manager'
  carousel.py was accessing player.manager which no longer exists after the
  3.0.11 refactor. Fixed all 6 occurrences to use player._get_manager().

## 3.0.11 (2026-09-03)
- Fundamental fix: service.py now uses a fresh ChannelManager instance
  on every access, matching the 2.x pattern exactly.
- Root cause of all recent channel-not-found bugs: service.py held a
  single persistent self.manager instance created at startup. Channels
  created by addon.py after startup were never visible to this instance,
  causing get_channel() to return None for any channel created after
  service start.
- Fix: removed persistent self.manager from SmartChannelsPlayer. Added
  _get_manager() method that creates a fresh ChannelManager on each call.
  All 19 self.manager. callsites updated to self._get_manager(). 
- This is exactly how 2.x worked and why it never had this class of bug.
- Also reverted the channel_manager.get_channel() disk-reload patch from
  3.0.10 which was treating the symptom not the cause.

## 3.0.10 (2026-09-03)
- Cleaned up onPlayBackStarted / onAVStarted following 2.x pattern:
  - onPlayBackStarted now does only one thing: reset _stop_reason.
    No channel identification, no getPlayingFile(), no queue position
    tracking. This matches 2.x exactly and avoids all timing issues.
  - All channel identification, queue position tracking, skip detection,
    and position polling now happen in onAVStarted via a background thread.
    By the time onAVStarted fires, Kodi has the file open and
    getPlayingFile() is reliable. Background thread avoids blocking the
    Kodi player callback thread (same pattern as 2.x).
  - This is the correct, stable design that 2.x used successfully.

## 3.0.9 (2026-09-03)
- BUG FIX (regression from 3.0.8): _do_replacement not firing at all
  Root cause: Added xbmc.sleep(200) retry loop inside onPlayBackStarted
  callback. Sleeping inside a Kodi player callback blocks the callback
  thread, preventing channel identification and breaking all replacement.
- Removed the retry loop entirely.
- Fixed the underlying issue properly: when getPlayingFile() fails in
  onPlayBackStarted, default to queue position 0 instead of returning
  early. Position 0 is always correct at the start of playback. Channel
  ID and queue are already set correctly from now_playing.json so
  _do_replacement will fire correctly from onPlayBackEnded.

## 3.0.8 (2026-09-03)
- BUG FIX: Second channel's state cursor being deleted by service.py
  Root cause: _save_state() orphan pruning used self._channels (loaded at
  service start) to determine live channel IDs. Channels created after service
  start were not in self._channels so their state keys were pruned on every
  _do_replacement call. Fix: read live channel IDs from channels.json on disk
  before pruning, and sync self._channels at the same time.

- BUG FIX: _do_replacement not firing when switching to a second channel
  Root cause 1: onPlayBackStarted fires before Kodi is ready to report the
  playing file. getPlayingFile() threw an exception, causing early return
  before self._queue_pos was reset for the new channel. Fix: reset _queue_pos
  to 0 when a channel switch is detected, regardless of file availability.
  Root cause 2: getPlayingFile() failing on first call due to timing.
  Fix: retry up to 3 times with 200ms delay before giving up.

## 3.0.7 (2026-09-03)
- Fixed resume dialog showing raw numbers instead of episode name and time.
  #32400 = '{0} — resume from {1}?' was being passed (mins, secs) as integers.
  Now passes (show - episode title, Xm Ys) so dialog reads correctly e.g.
  'Til Death - Pilot — resume from 14m 32s?'

## 3.0.6 (2026-09-03)
- Fixed resume dialog message showing 'Move Slot Up' instead of
  '{0} — resume from {1}?' — player.py was using #32874 instead of #32400.

## 3.0.5 (2026-09-03)
- Fixed 'Open Smart Channels' setting navigating to episode list instead of
  channel list. Changed ActivateWindow URL from bare plugin root to explicit
  ?action=list_channels so Kodi always opens the channel list view.

## 3.0.4 (2026-09-03)
- Fixed settings.xml action wiring:
  - Open Smart Channels: changed from action=list_channels to action=open_channels
    so it correctly uses ActivateWindow to navigate to channel screen
  - Auto-Create Channels: added auto_create_channels handler and dispatch entry
    (shows placeholder dialog until Phase 6 implementation)
  - Refresh Songs Cache: added refresh_songs_cache handler and dispatch entry
    (triggers background rebuild with toast notification)
- Verified all 10 settings.xml actions correctly wired to dispatch table

## 3.0.3 (2026-09-03)
- BUG FIX: Channel stopped playing after initial queue was exhausted
- Root cause: _do_replacement_inner was correctly updating the disk queue
  but never adding the replacement to Kodi's active PLAYLIST_VIDEO. Kodi
  played through all 12 originally loaded items then stopped — it had no
  knowledge of the items being appended to the disk queue.
- Fix: after appending replacement to disk queue, also call
  kodi_playlist.add() to extend Kodi's active playlist with the same item.
  Playback now continues indefinitely.
- Same fix applied to _handle_combo_slot for combo unit replacements.

## 3.0.2 (2026-09-02)
- BUG FIX: 1-for-1 queue replacement not firing correctly
- Root cause: _do_replacement_inner used self._queue_pos against in-memory queue
  to identify consumed_item, then compared its file path against queue[0] on disk.
  After onPlayBackEnded advanced _queue_pos and onPlayBackStarted reloaded the
  queue from disk, the file comparison always failed so nothing was ever popped
  or appended.
- Fix: always pop queue[0] from disk as the consumed item. queue[0] is always
  the item that just finished — the disk queue is only modified by this function,
  so this is always correct.

## 3.0.1 (2026-09-02)
- Removed Recycle/Stop dialog from TV, Serial, Movie, and Folder channel wizards
- All channels now always recycle (recycle=True hardcoded per design decision)
- Combo Block slots retain their own per-slot Recycle/Stop control (unchanged)
- Removed ask_recycle() import from tv.py, serial.py, movie.py, folder.py

## 3.0.0 — service.py first-run cache build (2026-09-02)
- Added _service_ensure_caches() to service.py startup
- On first install, video library cache and songs cache are now built
  automatically in background threads when the service starts
- No longer requires user to open the addon before caches are ready
- Video cache build: silent background thread, toast on completion
- Songs cache build: silent background thread, toast on start

## 3.0.0 — addon.py first-run cache fix (2026-09-02)
- Fixed three wrong string IDs in addon.py cache build UI
  (32060/32061/32062 -> 32402/32404/32360)
- Added correct 'Refreshing library cache ({0} days old)...' message (#32403)
  for stale cache rebuild vs first-time build (#32402)
- Added _ensure_songs_cache() — builds songs_cache.json on first run
  in background thread with toast notification (#32848/#32849)
- Songs cache now built automatically on fresh install alongside video cache

## 3.0.0 — settings.xml complete rewrite (2026-09-02)
- settings.xml was using completely wrong 2.x string IDs throughout
- Rewrote from scratch with all correct IDs from New_strings.po per spec §18
- All 9 categories now present: Channels, Playback, Cache, Network, Resume,
  Advanced, Backup and Restore, Coming Up Next, Channel Logo Overlay
- All setting labels verified against strings.po — zero missing IDs

## 3.0.0 — Wizard file string verification and fixes (2026-09-02)
- Line-by-line verification of all 8 wizard files against strings.po
- 71 wrong IDs found and fixed across: serial.py, movie.py, audio.py,
  combo.py, interleave.py, tv.py
- folder.py and party.py verified clean
- All fixes applied using exact line content as search target
- All 68 checks confirmed correct by line-number verification

## 3.0.0 — String verification and fixes (2026-09-02)
- Verified all string IDs in router.py, channels.py, dialogs.py by reading
  actual line content against strings.po text — no memory/guesswork
- Fixed 88 wrong IDs identified by line-by-line verification report
- All fixes applied using exact surrounding code as search targets
- All 94 verified callsites confirmed correct by line-number audit

## 3.0.0 — Complete strings remap (2026-09-02)
- Full audit run against New_strings.po — 247 wrong IDs found across 10 files
- All wrong IDs replaced in one complete pass:
  channels.py, dialogs.py, tv.py, serial.py, movie.py, folder.py,
  audio.py, party.py, combo.py, interleave.py, schedule_wizard.py
- schedule_wizard.py constants block fully remapped to correct schedule string IDs
- Final audit confirms zero wrong IDs remaining in entire codebase

## 3.0.0 — router.py string fixes (2026-09-01)
- Applied all router.py string remaps from schematic v4 summary:
  - Context menu labels: Channel Info, Play, Edit, Reset, Delete, Set Icon,
    Toggle Visibility, Add Schedule, Manage Interleave, View Exclusions,
    Missing Durations, Move Up, Move Down
  - open_channel / play_channel error dialogs: channel not found (#32207),
    no episodes (#32208)
  - >> Play Channel item (#32434)
  - Reset Show dialog (#32353/#32354/#32355)
  - set_channel_icon: Set Channel Icon (#32700), Clear Icon (#32701)
  - refresh_library: all progress/notification strings (#32356/#32358/#32359/#32360)
  - backup_data: all heading/message strings (#32362/#32363/#32365/#32367/#32368)
  - restore_data: all heading/message strings (#32369/#32372-#32382)
  - delete_all_data: all strings (#32051/#32384/#32385)
- All getLocalizedString() calls in entire codebase now correct per New_strings_1.po

## 3.0.0 — Non-wizard string fixes (2026-09-01)
- Installed New_strings_1.po (583 strings, highest ID #32903)
- Applied all code fixes from schematic v3 (items A-P):
  - Empty channel list error uses correct heading/message (#32000/#32226)
  - Delete channel confirm uses correct heading/message (#32000/#32211)
  - Audio channel info: type, order, artists, filtered, full-library labels corrected
  - Party channel info: type line corrected (#32801)
  - Combo block info: slot count word (#32871), slot label (#32903),
    Silent/Not Silent labels (#32885/#32886) corrected
  - TV/Serial/Movie/Folder info: Recycle lines removed (all always recycle per design decision)
  - TV/Serial/Movie/Folder info: type and rotation labels use correct IDs
  - Interleave section heading corrected (#32545)
  - Carousel info lines corrected (#32864/#32612/#32614/#32615/#32616)
  - Schedule info lines corrected (#32755/#32845/#32846/#32847)
  - Schedule day labels corrected (#32761-#32769/#32744/#32747)
  - View Exclusions: heading (#32609), missing episode fallback (#32591) corrected
  - View Missing Durations: empty message corrected (#32714)

# SmartChannels 3.0.0 Rewrite — CHANGELOG

## Phase 5c — String placeholder fixes

### Root cause
Two strings.po entries had more `{}` placeholders than the `.format()` calls
supplied arguments for, causing `IndexError` crashes:
- #32166 `"Episode Filters for {} — {}"` — called with 1 arg (show_title);
  the `— {}` was already handled by the outer format call in dialogs.py.
- #32187 `"Season {} — {}"` — called with 1 arg (chosen_season); second `{}`
  was extraneous.

Five additional strings had 0 placeholders where the code expected to
substitute values — won't crash but produce wrong UI text (values silently
dropped):
- #32011: "Select TV Shows" → "Select TV Shows ({} available)"
- #32156: "Set manually" → "Keep current: S{0:02d}E{1:02d}"
- #32163: (filter prompt) → added `{}` for show count
- #32205: "Interleave updated." → "Edit source: {}"
- #32392: "Artist contains:" → "{} contains:"

### Files changed
- `resources/language/resource.language.en_gb/strings.po` — 7 strings fixed



## Phase 5b — String ID Fix (critical)

### Root cause
All wizard files (tv.py, serial.py, movie.py, folder.py, audio.py, party.py,
combo.py, interleave.py, dialogs.py, channels.py, router.py) were using 2.x
string IDs. The 3.0.0 strings.po assigns completely different text to those
IDs, causing all dialogs to show wrong text (e.g. "Create Channel" opened
"Reset Channel" dialog).

### Fix
- All 522 getLocalizedString() calls remapped from 2.x IDs to correct 3.0.0 IDs.
- All hardcoded user-visible strings replaced with getLocalizedString() calls:
  - `"Slot {}  [{}]"` → #32868
  - `"S{:02d}E{:02d} - {}"` (episode label, 3 occurrences) → #32869
  - `"No Exclusions"` → #32276
  - `"All Movies"` → #32055
  - `"Daily"` / `"Once"` → #32451 / #32454
  - `"Movies"` (combo slot label) → #32228
  - `"  (current)"` (interleave mode indicator, 4 occurrences) → #32873
  - `"  episodeid: {}"` / `"  ({} episode IDs)"` → #32871 / #32872
- New strings added to strings.po: #32868–#32873.
- MPAA rating codes ("G", "PG-13", "TV-MA", etc.) retained as code constants —
  these are industry-standard designations, not translatable strings.
- schedule_wizard.py: "Add Schedule"/"Edit Schedule" in module docstring are
  comments, not user-visible code — retained as-is.

---

## Phase 5 — Full Channel UI

### Architecture
- Wizard logic split from monolithic `ui/channels.py` into per-type modules
  under `ui/wizards/`: `tv.py`, `serial.py`, `movie.py`, `folder.py`,
  `audio.py`, `party.py`, `combo.py`, `interleave.py`.
- `ui/dialogs.py` holds shared helpers used by all wizards: `pick_list_order`,
  `build_episode_filters`, `build_episode_exclusions`, `build_movie_exclusions`,
  `build_filters`, `build_audio_song_exclusions`, `ask_recycle`,
  `ask_queue_size`, `ask_visibility`, `ask_carousel`.
- `ui/channels.py` is now a thin dispatcher: create/edit dispatch, channel_info,
  view_exclusions, view_missing_durations, confirm helpers only.

### ui/wizards/tv.py (NEW)
- Full TV round-robin wizard ported from 2.x: show filter, multiselect,
  existing per-show settings preserved on edit, rotation order (keep/shuffle/
  manual), episodes-per-slot, per-show random, episode filters, episode
  exclusions (show-picker loop), starting point (keep/manual/Surprise Me),
  recycle, queue size, visibility, carousel.

### ui/wizards/serial.py (NEW)
- Serial wizard: multiselect, rotation order, episode exclusions, recycle,
  queue size, visibility.

### ui/wizards/movie.py (NEW)
- Movie wizard: all-movies vs pick-specific, filters (all-movies path),
  exclusions, playback order, recycle, queue size, visibility, carousel.

### ui/wizards/folder.py (NEW)
- Folder wizard: browseSingle, accessibility check, order, recycle, queue
  size, visibility.

### ui/wizards/audio.py (NEW)
- Audio wizard with ENH-AUD.01 applied: album picker opens with nothing
  pre-selected; "Select All" item prepended to album list.

### ui/wizards/party.py (NEW)
- Party wizard: browseSingle, order (random/no_repeat), queue size. Always
  visible, always recycles — no visibility or recycle dialogs.

### ui/wizards/combo.py (NEW)
- Combo Block wizard with slot management loop (add/edit/move/remove).
  Slot wizard handles TV (per-show exclusions/order/recycle/silent), movie
  (filters/exclusions/order/recycle), and folder (path/order/recycle/no-repeat)
  source types. Always hidden.

### ui/wizards/interleave.py (NEW)
- Full interleave dialog ported from 2.x: add/edit/remove sources, jitter
  mode, frequency, count_per, silent toggle. Carousel and circular detection
  guards. Combo Block one-owner enforcement.

### ui/schedule_wizard.py (NEW)
- Carried from 2.x unchanged (spec §12, §26 Phase 5).

### resources/lib/scheduler.py (NEW)
- Carried from 2.x unchanged.

### resources/lib/router.py
- Context menu updated to full 2.x set: channel_info, play, edit, reset,
  delete, set_icon, toggle_visibility (TV/Movie/Folder/Serial only), add_schedule
  (non-audio/party), manage_interleave (TV/Movie/Folder), view_exclusions
  (TV/Serial/Movie), view_missing_durations (when entries exist), move_up,
  move_down.
- Added all missing action methods: channel_info, set_channel_icon,
  toggle_channel_visibility, manage_interleave, view_exclusions_action,
  view_missing_durations_action, add_schedule, manage_schedules,
  sort_channels_alpha, open_channels, open_settings, play_from_item,
  reset_next_episode, refresh_library, backup_data, restore_data,
  delete_all_data.

### resources/lib/channel_manager.py
- Added four public methods required by UI layer:
  - `clear_channel_resume_points(channel_id)` — removes all resume: state keys
    for a channel when edit invalidates them.
  - `reset_show_to_start(channel_id, show_id)` — resets one show's cursor
    ep_pos to episode 1 and rebuilds the queue (TC-30.17).
  - `regenerate_queue(channel_id)` — strips interleaved items from current
    queue and re-weaves with updated interleave config, or full rebuild.
  - `reorder_queue_from_item(channel_id, queue_index)` — rotates queue so
    selected item is at position 0 (side-panel play-from-item).

### addon.py
- Dispatch table updated with all 29 Phase 5 actions.

---

## Phase 4 — Minimal Channel UI

Build order revised: UI brought forward so each phase is testable end-to-end.

### addon.py
- Library cache check runs at addon entry point (every open), before any
  action is dispatched. If `local_library.json` is absent, `build_local_cache()`
  runs with a progress dialog and a toast notification on completion.
  Skipped for `play_channel` to avoid blocking mid-playback interactions.
- `manager` constructed once in `main()` and passed to `Router` to avoid
  a second construction.

### resources/lib/router.py
- `Router.__init__` accepts optional pre-built `manager` parameter.

### resources/lib/ui/channels.py (NEW)
- TV channel wizard: type → name → cache check → show multiselect
  (library, preselect on edit) → recycle → queue size → visibility
  (NEVER REMOVE) → carousel.
- Movie channel wizard: type → name → cache check → All Movies /
  Pick Specific (`d.multiselect()`) → playback order → recycle →
  queue size → visibility (NEVER REMOVE) → carousel.
  Step 3 (movie selection) correctly implements spec §6.3 — not deferred.
- `_ask_carousel()`: enforces both carousel guards (schedule source,
  interleave source) before offering the carousel step.
- Context menu: Play, Edit, Delete (with confirmation), Reset (with
  confirmation), Move Up, Move Down.
- Toast notifications for channel created and channel updated.
- Edit path: existing show/movie selections pre-selected;
  per-show settings preserved for shows that remain selected.

### resources/settings.xml
- Added Channels section with `create_channel_action` (RunPlugin, old
  settings format — action as attribute not child element) and
  `channel_icon_folder` (folder type).

### resources/language/resource.language.en_gb/strings.po
- Added strings #32006–#32062 covering all Phase 4 wizard, menu,
  and library cache UI text.

---

## Phase 3 — Carousel Rewrite
- TV channel wizard: name → show multiselect (library, preselect on edit) →
  recycle → queue size → visibility (NEVER REMOVE) → carousel.
- Movie channel wizard: name → playback order → recycle → queue size →
  visibility (NEVER REMOVE) → carousel.
- `_ask_carousel()`: enforces both carousel guards (schedule source,
  interleave source) before offering the carousel step. Handles timed
  (interval + pop count) and duration modes with informational dialogs.
- Context menu: Play, Edit, Delete (with confirmation), Reset (with
  confirmation), Move Up, Move Down.
- Edit path: existing show selections pre-selected; per-show settings
  preserved for shows that remain selected.

### resources/lib/router.py
- Added `create_channel`, `channel_context_menu` action handlers.
- `channel_context_menu`: dispatches Play/Edit/Delete/Reset/Move Up/Move Down.
- `list_channels`: adds "Channel Options" context menu item to every channel
  list item, pointing to `channel_context_menu` action.

### addon.py
- Added `create_channel` and `channel_context_menu` to dispatch table.

### resources/settings.xml
- Added Channels section with `create_channel_action` (RunPlugin) and
  `channel_icon_folder` (path) settings.
- Create Channel now accessible from addon Configure menu.

### resources/language/resource.language.en_gb/strings.po
- Added strings #32006–#32053 covering all Phase 4 wizard and menu text.

---

## Phase 3 — Carousel Rewrite

### resources/lib/carousel.py (NEW)
- Full rewrite per spec §9. No 2.x carousel code carried forward.
- `tick_carousel(player)`: entry point called every 60 s from service.py tick loop.
  Iterates all carousel-enabled channels; fires pop logic if interval elapsed.
- Timed mode: pops `pop_count` items when `elapsed >= interval_sec`.
- Duration mode: pops 1 item when `elapsed >= queue-front item's duration`.
- Each pop fires 1-for-1 replacement (spec §7.3):
  - Primary TV item → `get_carousel_replacement()` (same show). Updates `last_popped_show`.
  - Primary movie/folder/interleaved → `get_one_replacement()`.
  - Combo slot → `_handle_combo_slot_pop()`: increments `pending_combo_unit` tracker;
    appends full replacement unit only when `slots_played == slots_total`.
- `last_pop_time` updated on every pop regardless of item type.
- `last_popped_show` updated ONLY when a primary TV item is popped.
- No sweep logic. No atomic combo unit popping. No adjacent item removal.
- `carousel_live_join` removed per spec Appendix A.
- `channel_can_enable_carousel()`: guard helper for wizard UI (spec §9.4).
- `is_carousel_eligible_source()`: excludes carousel channels from interleave/schedule pickers.

### addon.xml
- Added `<settings version="2"/>` inside `xbmc.addon.metadata`. This was missing,
  causing Kodi to grey out the Configure button in the addon Information menu.
  Settings themselves (playback, network, advanced) were already present in
  settings.xml and are now accessible via Configure.

### service.py
- Import `tick_carousel` from `resources.lib.carousel`.
- `_tick_carousel()`: was `pass # Phase 3`; now calls `tick_carousel(player)` with exception guard.

---

## Phase 2 — Remaining Queue Builders

*(Completed previous session — see handoff document for details.)*

## Phase 1 — Foundation

*(Completed previous session — see handoff document for details.)*

## 3.0.25
- Removed `_in_resume` flag, `onPlayBackResumed`, and `onPlayBackPaused` from service.py
- Skip detection is now purely positional (new_pos > queue_pos), matching 2.x exactly
- `_in_resume` had no 2.x precedent and was incorrectly suppressing all user skips

## 3.0.26
- Fixed _replacement_serial reading stale disk queue: now receives the
  in-memory queue (consumed item already removed) via current_queue param
- Fixed _handle_skip: rebuilds Kodi playlist fully instead of calling
  remove() which was failing silently
- Fixed _handle_skip: each replacement call now receives the growing
  in-memory queue so _replacement_serial sees correct tail state per skip
- Fixed _queue_pos overwrite after _handle_skip (was incorrectly set back
  to pre-skip value; now forced to 0 after skip handling)

## 3.0.27
- _handle_skip: clear saved resume position for every skipped item so
  stale resume dialogs cannot fire when those items reappear in the queue
- delete_channel: now also removes all resume:channel_id:* state keys
  (previously only channel_id:* keys were swept; resume entries survived
  channel deletion)
- reset_channel: now calls clear_channel_resume_points so all saved
  resume positions are wiped when a channel is reset to the beginning

## 3.0.28
- Fixed play_channel in router.py: call setResolvedUrl(succeeded=False)
  before start_channel() so Kodi does not insert the plugin:// action URL
  at playlist position 0. Without this, every channel start triggered a
  false skip detection (was=0 now=1), which fired _handle_skip and rebuilt
  the playlist — making it impossible for the user to navigate the playlist.
  Matches 2.x play_channel exactly.

## 3.0.29
- Added update_now_playing() public method to channel_manager.py — writes
  active_channel_id, channel_name, title, tvshowtitle, season, episode,
  duration, start_time to now_playing.json (local and shared)
- service.py _on_av_started_worker now calls update_now_playing() on every
  episode start so now_playing.json stays current throughout playback,
  not just at channel start

## 3.0.30
- Fixed resume seek: moved seekTime() from player.py (immediately after
  play(), unreliable) to service.py _on_av_started_worker (onAVStarted,
  where file is guaranteed open). player.py now stores seek target via
  channel_manager.set_pending_seek(); service.py executes and clears it
  via pop_pending_seek() in onAVStarted. Matches 2.x _do_resume_check.
- Fixed playlist highlight after skip: replaced clear()+rebuild with
  append-only. Kodi's cursor stays at the user's chosen position. Only
  replacement items are appended to the tail.
- Added set_pending_seek() and pop_pending_seek() to channel_manager.py

## 3.0.31
- Restored removal of played/skipped items from Kodi playlist front
- _do_replacement_inner: after natural episode end, removes consumed item
  from Kodi playlist then appends replacement to tail — playlist stays clean
- _handle_skip: removes each skipped item via remove() then appends
  replacements to tail — preserves Kodi cursor position (highlight) while
  still cleaning up items that were skipped past

## 3.0.32
- Fixed race condition: _do_replacement_inner now writes disk queue BEFORE
  Kodi playlist operations so _on_av_started_worker (background thread)
  always reads a consistent queue state
- Fixed _on_av_started_worker: reuses in-memory self._queue when channel
  unchanged instead of reading from disk — eliminates stale-queue reads
  caused by the race between onAVStarted and the replacement write
- Fixed channel_switched flag capture: computed before self._channel_id
  is reassigned so the disk-read fallback triggers correctly on switch

## 3.0.33
- Added threading.Lock to SmartChannelsPlayer — matches 2.x pattern
- _do_replacement_inner: entire read-pop-replace-write cycle now runs
  under the lock so _on_av_started_worker always sees a consistent
  self._queue — no partial updates visible between threads
- _on_av_started_worker: all shared state access inside the lock;
  releases before calling _handle_skip to avoid deadlock
- _handle_skip: queue write inside the lock
- onPlayBackStopped: state clear inside the lock
- Fixed replacement=None initialisation before if/else to prevent
  NameError when is_combo_channel is True

## 3.0.34
- Fixed episode skip on natural playback: removed kodi_playlist.remove()
  from _do_replacement_inner. Kodi auto-advances its cursor when an episode
  ends naturally — calling remove() on the just-played item then shifts the
  cursor back by one, causing the next episode to be skipped. 2.x never
  removed items from the Kodi playlist during natural playback. Only append.

## 3.0.35
- Fixed serial channel show_slot bug: when a show exhausted, _replacement_tv_next_show
  was picking the exhausted show again (via show_slot % len(shows) landing back on it)
  instead of advancing to the next show. Fix: pass skip_show_id from _replacement_serial
  so _replacement_tv_next_show skips the exhausted show on its first candidate.

## 3.0.36
- Rewrote _replacement_serial to always look at the queue TAIL (not the
  consumed item's show) to determine what comes next. Previously, each
  skip-replacement call looked for "the last item of the consumed show"
  which, with N shows and a skip crossing a boundary, caused each call to
  independently advance to the next show — interleaving shows at the tail.
  Now every call simply asks "what is the last item queued, and what comes
  after it?" — giving correct serial continuation for both natural play
  and multi-item skip replacement.

## 3.0.37
- Fixed serial channel show rotation after boundary crossing: replaced
  show_slot-based next-show selection with position-based selection.
  show_slot is a monotonically increasing counter designed for round-robin
  channels; for serial channels it drifts after multiple boundary crossings
  and skips, causing the wrong show to be picked. Now uses
  (exhausted_show_index + 1) % len(shows) which is always correct regardless
  of how many boundaries have been crossed. show_slot is updated for
  consistency but is no longer the source of truth for serial rotation.

## 3.0.71
### Fixed
- **Critical: combo slot episode repeating forever after first cycle**
  Root cause: `_do_replacement_inner` (service.py), `_do_pops` (carousel.py),
  and `_handle_skip` (service.py) each called `_get_manager()` multiple times
  within a single pop/replace operation. Each call returns a fresh
  `ChannelManager` with its own in-memory state loaded from disk. When
  `ComboQueueBuilder.build_one_slot()` wrote the advanced `tv_next_ep` and
  `show_slot` via its manager instance, the outer manager's subsequent
  `_save_state()` call merged its stale in-memory copy on top, clobbering
  the correct values. On every subsequent replacement the same episode was
  fetched forever.
  Fix: capture ONE `ChannelManager` instance at the top of each operation
  and pass it through to `_handle_combo_slot` / `_handle_combo_slot_pop` /
  `ComboQueueBuilder` — never call `_get_manager()` again mid-operation.
  Affects both natural playback replacement and carousel pop replacement.

## 3.0.72
### Fixed
- **Combo block TV show starting at wrong episode after channel create or interleave add**
  Root cause: the standalone combo block queue is built at channel creation time,
  advancing `tv_next_ep` by however many episodes it consumed. When a TV channel
  subsequently adds that combo as an interleave source (via Manage Interleave) and
  `regenerate_queue` runs, `_load_foreign_items` reads the already-advanced
  `tv_next_ep` and the TV channel's interleave portion starts mid-series. The same
  ordering problem occurs when `_pregenerate_queue_safe` is called on a TV channel
  whose combo source was previously built.
  Fix: added `_reset_combo_interleave_sources()` which clears `show_slot` and
  `tv_next_ep` state keys for every combo TV slot before the TV queue build runs.
  Both `_pregenerate_queue_safe` and `regenerate_queue` now call it before weaving,
  then rebuild each combo's standalone queue *after* the TV queue is written, so the
  standalone queue picks up from where the TV interleave left off. Both queues now
  start from episode 1 and advance in the correct order.

## 3.0.73
### Fixed
- **Carousel fires immediately on first tick after channel creation**
  Root cause: `last_pop_time` defaults to 0 when no carousel state exists.
  The first carousel tick sees `elapsed = now - 0 = ~1.7 billion seconds`,
  which exceeds any item duration or timed interval, causing an immediate pop
  before the user has finished configuring the channel (e.g. adding interleave
  sources). This silently consumed the first queue item, leaving the channel
  starting at episode 2.
  Fix: `create_channel` and `update_channel` now write `last_pop_time = now`
  to the carousel state whenever a carousel-enabled channel is created or
  carousel is enabled for the first time. The first tick will then see
  `elapsed = ~60s` (or the item duration), which is correct behaviour.

## 3.0.74
### Fixed
- **Poll interval minimum clamp removed** — `_get_poll_interval()` previously
  enforced a hard floor of 10 seconds regardless of the setting value.
  The floor is now 1 second (prevents divide-by-zero only). Default remains
  60 s. Users on low-powered devices should raise the value in Settings →
  Resume; users wanting more precise resume accuracy can lower it.

### Ported from 2.x (carousel.py)
- Skip the currently-playing channel — the viewer watching it IS the drift
- Skip active schedule source channels — carousel + scheduler running
  concurrently on the same source queue would double-drain it
- Timed mode: catch-up for multiple missed intervals (Kodi was off for hours)
- Timed mode: `last_pop_time is None` first-run guard — init clock, no
  immediate pop (complements the 3.0.73 fix at channel creation time)
- Duration mode: catch-up loop — pop one item at a time until elapsed <
  current item duration
- Duration mode: `last_pop_time is None` first-run guard
- Abort pop if replacement returns nothing — library temporarily unavailable;
  queue left unchanged on disk, retry next tick
- Clear saved resume position for each popped item
- Channel type guard — only `tv` and `movies` channels are eligible
- NOTE: safety floor (`_QUEUE_FLOOR` / `get_replenishment_threshold`) NOT
  ported — it was a 2.x batch top-up concern. In 3.x every pop immediately
  appends one replacement (1-for-1), so the queue never shrinks.

### Ported from 2.x (service.py)
- `_basename_match()` — fuzzy file-path equality handling smb:// vs UNC vs
  slash differences; used by skip detection
- `_reset_watched_if_enabled()` — resets Kodi watched/playcount after natural
  episode completion when the `reset_watched` setting is on
- `SmartChannelsMonitor.onNotification()` — auto-rebuilds library/songs cache
  when Kodi's VideoLibrary.OnScanFinished or AudioLibrary.OnScanFinished fires
- `SmartChannelsMonitor.onSettingsChanged()` — reloads poll interval and
  restarts the poll timer immediately when settings change mid-session
- `SmartChannelsMonitor` now receives the player instance at construction

### Ported from 2.x (channel_manager.py)
- `_is_network_path()` — detects smb:// / nfs:// network paths
- `_normalise_icon_folder()` — converts Windows UNC paths to smb:// for xbmcvfs
- `get_carousel_elapsed()` — seconds since last carousel pop (for channel info)
- `get_interleave_sources()` — public getter for a channel's interleave sources
- `clear_missing_durations()` — clears per-channel missing duration log from state
- `get_missing_durations_txt_path()` — path to the global missing_durations.txt
- `capture_folder_duration()` — writes companion NFO and updates queue entry
  after a folder item's real duration is captured via getTotalTime()
- `save_resume_position_local()` — alias for save_resume_position (kept for
  call-site compatibility with 2.x-ported code)

## 3.0.75
### Fixed
- **Combo block wizard: folder and movie slot "items per slot" dialog showed wrong text**
  The yes/no heading (#32270) now reads "Items Per Slot?" for all slot types.
  The body (#32275) now reads "This slot currently plays {n} item(s) per turn.
  Set a custom count?" for all slot types, showing the actual current count.
  The numeric input heading (#32274) now reads "Items per slot (current: {n}):"
  for all slot types. Previously #32275 said "1 movie" regardless of slot type
  or current count, and #32274 included an empty show-name placeholder for
  movie and folder slots.

## 3.0.76
### Fixed
- **TV wizard and combo TV slot: wrong or missing wording in episodes-per-show/slot dialogs**

  TV channel wizard:
  - Heading now uses #32276 "Set Episodes Per Show?" (was #32270 "Items Per Slot?" — wrong context)
  - Input heading now uses #32277 "Episodes per show for {0} (current: {1}):" with show title
    correctly passed as {0} (was #32274 which only had one placeholder, silently dropping the title)

  Combo block TV slot:
  - Heading now uses #32268 "Episodes Per Slot?" (was #32270 "Items Per Slot?" — imprecise)
  - Multi-show body now uses #32269 "...per combo unit..." (was #32271 "...per rotation turn..."
    which is TV-channel-specific language, not combo slot language)
  - Input heading now uses #32267 "Episodes per slot for {0} (current: {1}):" with show title
    correctly passed as {0} (was #32274 with one placeholder, silently dropping the title)

  Combo block movie slot and folder slot: unchanged — #32270/#32274/#32275 are correct
  for those contexts ("Items Per Slot?" and generic "item(s)" wording is right).

  Regular movie and folder channel wizards: no per-show/per-slot dialog — unchanged.

## 3.0.77
### Changed
- **Carousel timed mode minimum interval lowered from 20 minutes to 1 minute**
  The 20-minute floor was a 2.x design choice with no technical basis.
  1 minute is the natural resolution of the carousel tick loop (which runs
  every 60 seconds), making it the sensible floor. Short-content channels
  (cartoons, bumpers) can now use intervals appropriate for their runtime.
  Also useful for testing without long waits.
  Changes: `CAROUSEL_MIN_INTERVAL` in carousel.py, clamp in dialogs.py,
  and string #32603 updated to "Pop interval (minutes, minimum 1)".

## 3.0.78
### Fixed
- **Folder slot no_repeat had no effect — episodes repeated immediately**
  Root cause (three layers, broken in 2.x too):
  1. FolderQueueBuilder.build() only read `recycle`, never `no_repeat`.
     The `no_repeat` field was placed into the synthetic channel dict but silently ignored.
  2. record_folder_file_played() was defined but never called — the played_files
     list stayed empty forever so filtering had nothing to filter against.
  3. For combo folder slots, the state key used by FolderQueueBuilder
     ("combo:{id}:slot:{id}") did not match what service.py would have recorded
     against (the combo channel id), so even if recording had fired it would have
     missed.
  Fix:
  - FolderQueueBuilder.build() now reads `no_repeat` separately from `recycle`.
    no_repeat=True filters out played files each build, and on exhaustion clears
    the played list and restarts the cycle (unlike recycle=False which stops permanently).
  - record_folder_file_played() extended to accept None as file_path — clears the
    entire played list for a no_repeat cycle reset.
  - service.py onPlayBackEnded now calls record_folder_file_played() on natural
    completion of any folder item (standalone or combo slot).
  - combo.py _fetch_folder_items now stores the synthetic state id as
    _folder_state_id on each item so service.py records against the correct
    scoped key ("combo:{id}:slot:{id}") that FolderQueueBuilder reads from.

### Fixed
- **Combo block queue files are now blocked from being created**
  In 3.x the standalone combo queue file is never read — combo items are built
  on-demand via build_one_slot (1-for-1) or woven into the TV channel queue
  during build_channel_queue. Writing the file consumed state (show_slot,
  tv_next_ep) before the TV channel interleave build ran, causing wrong starting
  episodes. _pregenerate_queue_safe now returns immediately for combo channels
  after applying starting points. The reset_combos loops in _pregenerate_queue_safe
  and regenerate_queue no longer write queue files either.

### Fixed
- **Already-owned combo blocks appeared in interleave and schedule source pickers**
  Previously a combo block owned by another channel appeared in the picker and was
  only blocked after the user selected it (with a dialog). Now owned combos are
  filtered out of the picker list before it is shown. Combos unowned or already
  owned by the current channel remain visible. The post-selection owner-block
  dialogs (#32878 in interleave, #32834 in schedule) have been removed as they
  are now unreachable.

## 3.0.79
### Fixed
- **delete_channel: 9 gaps in cleanup — orphaned data across all deletion orders**

  Previously delete_channel only removed state keys matching "{channel_id}:*" and
  "resume:{channel_id}:*", and did no cross-channel cleanup at all. Nine gaps:

  1-5. Combo slot state keys orphaned when combo block deleted.
       All "combo:{channel_id}:*" keys (show_slot, tv_next_ep per show,
       movie_state, folder_played, missing_durations) were never matched by the
       old "{channel_id}:*" prefix because they use a different prefix format.
       These accumulated indefinitely in state.json.
       Fix: added "combo:{channel_id}:" as a third cleanup prefix.

  6.   Combo block owner field not cleared when owning TV channel deleted.
       If a TV channel was deleted while it owned a combo block as an interleave
       source, the combo block's owner field still pointed at the deleted channel,
       making it appear "owned" and blocking its use elsewhere.
       Fix: delete_channel now calls clear_combo_owner() for every combo block
       in the deleted channel's interleave sources before removing it.

  7.   Interleave back-references not removed from other channels.
       If channel A was an interleave source for channel B and A was deleted,
       channel B's interleave config still referenced A's ID. The next queue
       build would silently return no items for that source.
       Fix: delete_channel now iterates all other channels and removes the
       deleted channel from their interleave lists, setting interleave=None
       if the list becomes empty.

  8.   Schedules not cleaned up when source or target channel deleted.
       Schedules remained in schedules.json pointing at deleted channels,
       continuing to appear in Manage Schedules and firing against non-existent
       channels.
       Fix: delete_channel now deletes all schedules where the deleted channel
       appears as either source_channel_id or target_channel_id.

  9.   Auto-companion channels not deleted with their parent.
       Invisible __auto__ companion channels created by Auto-Create Channels
       were not recursively deleted when their parent TV channel was deleted.
       Fix: delete_channel recursively calls itself for any __auto__ channel
       found in the deleted channel's interleave sources. (Ported from 2.x;
       applies once auto_channels is active — item F on the work queue.)

## 3.0.80
### Fixed
- **Folder channel wizard missing No Repeat option**
  The spec feature matrix (§5) explicitly marks Folder channels as supporting
  No Repeat, but the wizard never asked for it and the field was never stored.
  Fix: the folder wizard now asks "No Repeat / Repeat" (reusing #32887/#32890/#32897
  already defined for the combo folder slot) after the playback order step.
  The no_repeat field is stored in channels.json via the add_channel whitelist
  and triggers a queue rebuild when changed via edit (update_channel mode_changed).
  FolderQueueBuilder already reads no_repeat from the channel dict (fixed in
  3.0.78), so the full chain — wizard → channels.json → builder → played
  tracking → cycle reset — now works for standalone folder channels.

## 3.0.81
### Changed
- **Combo Block wizard: queue size dialog removed**
  Queue size has no meaning for Combo Blocks in 3.x — no queue file is written
  (fixed in 3.0.78) and items are built on-demand via build_one_slot (1-for-1).
  The ask_queue_size dialog and its early-return guard have been removed from the
  combo wizard. The queue_size field is no longer written to channels.json for new
  combo channels. Existing stored values in channels.json are left in place
  (harmless — never read). The add_channel whitelist retains queue_size for all
  other channel types unchanged.

## 3.0.82
### Fixed
- **Resume poll interval setting label said "minutes" but the value is seconds**
  The code always treated the setting value as seconds (passing it directly to
  threading.Timer). The label incorrectly said "minutes, 0=disabled". 0=disabled
  also never worked — the max(1,...) clamp made 0 become 1.
  Fix: string #32037 now reads "Background polling interval (seconds)".
  The max(1,...) clamp is kept — minimum 1 second, no disable option.
  The poll is extremely cheap (one getTime() call, no disk I/O) so there is
  no performance reason to avoid low values. Default remains 60 seconds.

## 3.0.83
### Changed
- **Combo Block context menu trimmed to appropriate options only**
  Removed from Combo Block context menu: Play Channel, Reset Channel,
  Set Channel Icon, Toggle Visibility, Add Schedule, Move Up, Move Down.
  Combo Blocks are not directly playable, have no queue file to reset,
  are always hidden (Toggle Visibility irrelevant), are interleave/schedule
  sources only (not schedule targets), and do not appear in the visible
  channel list (Move Up/Down irrelevant).
  Remaining Combo Block menu: Channel Info, Edit Channel, Delete Channel.

## 3.0.84
### Fixed
- **Carousel: "clear_resume_position() missing 1 required positional argument: 'item_file'"**
  The carousel _do_pops() call to clear_resume_position() was passing the entire
  popped_item dict as channel_id and omitting item_file entirely. The correct call
  is clear_resume_position(channel_id, popped_item.get("file", "")).
  The error was caught by the except block so carousel pops continued correctly,
  but the resume position was never cleared for carousel-popped items.

## 3.0.85
### Fixed
- **TV channel used as interleave source starts at wrong episode**
  When a TV channel was used as an interleave source for another channel
  (e.g. TV shows interleaved into a Movie channel), the interleave build
  read the TV channel's existing cursor (already advanced by its own queue
  build) instead of starting from episode 1. If the TV channel had built
  its own queue of 32 items (8 episodes per show), the interleave would
  start at S01E09 instead of S01E01.
  Root cause: _load_foreign_items for TV type called get_cursor(foreign_id)
  which returned the already-advanced cursor. The combo block case was
  correctly handled by _reset_combo_interleave_sources (3.0.72) but regular
  TV channels used as sources had no equivalent reset.
  Fix: _load_foreign_items for TV sources now builds from a fresh cursor
  (show_slot=0, ep_pos={}) so the interleave always starts from S01E01.
  The TV channel's own cursor is saved before and restored after so its
  standalone queue is completely unaffected.

## 3.0.86
### Fixed
- **Add Schedule throws TypeError: run() got an unexpected keyword argument 'target_channel_id'**
  router.py was calling wizard.run(target_channel_id=channel_id) but
  ScheduleWizard.run() takes no arguments. The target_channel_id parameter
  already exists on __init__ — it just needed to be passed there instead.

## 3.0.87
### Fixed
- **Add Schedule: first dialog shows "Source{0}" instead of "Schedule Name"**
  _S_SCHEDULE_NAME was mapped to #32774 ("Source: {0}") instead of
  #32731 ("Schedule Name"). The unformatted {0} placeholder rendered
  literally in the dialog heading.

## 3.0.88
### Fixed
- **Schedule wizard: 5 wrong string IDs and 1 missing string**
  A block of _S_ constants in schedule_wizard.py was shifted by one position,
  causing wizard step dialogs to show summary line text instead of their correct
  headings. All five were pointing at the wrong strings:
    _S_ADD_SCHEDULE:  #32773 "Target: {0}"       → #32730 "Add Schedule"
    _S_SELECT_TARGET: #32775 "Day: {0} Time: {1}" → #32732 "Select Target Channel"
    _S_SELECT_SOURCE: #32776 "Items: {0}"         → #32733 "Select Source Channel"
    _S_START_TIME:    #32778 "Fire Date..."        → #32735 "Start Time (HH:MM)"
    _S_NUM_ITEMS:     #32779 "Invalid date..."     → #32736 "Number of Items"
  Additionally _S_PAST_TIME shared #32759 with _S_INVALID_TIME ("Invalid time
  format...") — its own string did not exist. Added #32783 "The time {0} has
  already passed today. The schedule will next fire tomorrow." to strings.po.

## 3.0.89
### Fixed
- **Scheduler never fires — _tick_scheduler was a stub**
  _tick_scheduler() in service.py contained only `pass  # Phase 4`.
  scheduler.py was fully implemented (check_all, fire_block, all predicates)
  but was never called from the tick loop.
  Fix: _tick_scheduler() now calls ScheduleManager().check_all() every 60
  seconds, passing the channel_manager and the currently-playing channel_id
  so the scheduler can evaluate all active schedules and fire blocks whose
  time has been reached.
  Also fixed: scheduler.py fire_block() called topup_channel_queue() which
  was a 2.x batch top-up method that does not exist in 3.x. Replaced with
  build_channel_queue() to rebuild the source queue from scratch if empty.

## 3.0.90
### Fixed
- **Manage Schedules throws AttributeError: 'ScheduleWizard' object has no attribute 'manage'**
  manage_schedules in schedule_wizard.py is a module-level function, not a
  method on ScheduleWizard. router.py was incorrectly instantiating the wizard
  class and calling .manage() on it. Fixed to call the module-level function
  directly: manage_schedules(self.addon, self.manager).

## 3.0.91
### Fixed
- **Manage Schedules shows "No Schedules Defined" after creating a schedule**
  router.py add_schedule() called wizard.run() but discarded the returned
  definition — never calling channel_manager.add_schedule() to persist it.
  The schedule was built and validated by the wizard but never written to
  schedules.json. Fixed to capture the result and call add_schedule() when
  the wizard returns a definition, then refresh the container.

## 3.0.92
### Fixed
- **Scheduled block fires correctly but channel never switches to play block items**
  fire_block() correctly prepended 3 block items to the target channel's
  queue file on disk at 17:00:17, but Kodi's in-memory playlist was unchanged.
  When the playing episode naturally ended at 17:03:43, _do_replacement() read
  the updated queue (now starting with block items) but only popped queue[0]
  for a 1-for-1 replacement — Kodi's playlist was still on original item at
  position 3, causing a false skip detection and the block items were never played.

  Fix — three components ported from 2.x _maybe_start_block_reload /
  _count_block_item / _pending_block_reload:

  1. _pending_block_channel (new instance var on SmartChannelsPlayer):
     Set by _tick_scheduler immediately after fire_block() writes block items
     to the currently-playing channel's queue. Signals that the next natural
     episode boundary should trigger a full channel reload rather than 1-for-1.

  2. _maybe_start_block_reload() (new method):
     Called from onPlayBackEnded after the finished item is processed. If
     _pending_block_channel is set and the finished item was not itself a
     block item, fires start_channel() on a daemon thread (never from the
     callback directly — can deadlock) reloading from disk, which now starts
     with the block items. Kodi's playlist is rebuilt with the block first.

  3. _count_block_item() (new method):
     When a block item completes naturally, counts it via
     ScheduleManager.on_block_item_complete() instead of running 1-for-1
     replacement. Includes consecutive de-dupe guard (_block_count_last) to
     prevent double-counting when onPlayBackEnded fires for a skipped item.

  4. _tick_scheduler() now detects newly-fired blocks by comparing active
     block targets before and after check_all(), and sets
     _pending_block_channel when the target is the currently-playing channel.

  5. _get_active_block_targets() (new helper): returns set of target channel
     IDs that have an active_block in state.json — used by _tick_scheduler
     to detect newly-fired blocks.
