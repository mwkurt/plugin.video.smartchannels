## 3.1.168
Built on 3.1.167 (rollback target 3.1.167). One fix, from Mark's 11/20 Bedroom report.
**Bug:** when the side panel opened, the highlighted channel did not play on the first Enter: Kodi made its click sound and nothing happened, until Mark moved up or down and back. The 11/20 08:17-08:36 Bedroom log shows `Control 100 in window 13000 has been asked to focus, but it can't` on every open, logged just before `[SidePanel] onInit`. Kodi tries to focus the channel list (the skin's default control) when the window loads, while the list is still empty; the add-on then filled the list and highlighted the start channel but never gave it focus, so Enter had no control to act on.
**Fix** (`resources/lib/ui/side_panel.py` `onInit`): after the channel list is filled and the start channel selected, `self.setFocusId(CTRL_CHANNEL_LIST)` and `_panel_focused = False`. No new function, no other file, string or setting changed. The "can't focus" line will still be logged (Kodi tries before the list exists); it is not the proof.
Not proven by the code alone: the test is pressing Enter at once on the highlighted channel after the panel opens.

## 3.1.167
Built on 3.1.166 (rollback target 3.1.166). One fix, found in the 11/19-11/20 soak logs.
**Bug:** `settings.xml` declared `panel_open_channel_name` (the read-only "Channel list opens on" name shown next to the picker) with an empty `<default>` and no `<allowempty>` constraint. Kodi treats an empty string as invalid for a setting without that constraint, so every read of the add-on's settings logged `error <CSettingString>: error reading the default value of "panel_open_channel_name"` and `unable to read setting "panel_open_channel_name"`. In the 11/19-11/20 logs that was 215,916 of 232,137 lines (Livingroom), 90% (Garage PC), 92% (PVR PC) and 30% (Bedroom), and it was the only setting that did it. Behaviour was not affected; the log was flooded and Kodi would flag it on repo review.
**Fix** (`resources/settings.xml`): added `<constraints><allowempty>true</allowempty></constraints>` to that one setting, the same form the other empty-default string settings already use (`ffprobe_path`, `channel_icon_folder`). No Python, string or other setting changed.
Not proven by the code alone: the test is the log (no `panel_open_channel_name` line after a restart).

## 3.1.166
Built on 3.1.165 (rollback target 3.1.165). One fix, found in Mark's 11/19 14:34 log.
**Bug:** with Use side panel turned off, the plain channel list opened fine; turning the setting back on and opening the add-on again still showed the plain list until Kodi was restarted. The log showed why: after the plain list was built Kodi logged `Saving fileitems [plugin://plugin.video.smartchannels/]` (26 items), and on the next visit `Loading items: 26, directory: plugin://plugin.video.smartchannels/` with no add-on launch (no `action='list_channels'` line), so `list_channels` never read the setting.
**Fix** (`router.py` `list_channels`, the end of the plain list): `endOfDirectory(..., cacheToDisc=False)` so Kodi does not keep the list. One argument; no other code, string or setting changed. The side panel path (`succeeded=False`) and every other listing are untouched.
Not proven by the code alone: the test is the log (no `Saving fileitems` line for the add-on root after the plain list, and `list_channels` runs on every visit).

## 3.1.165
Built on 3.1.164 (rollback target 3.1.163 until 3.1.164 has passed its tests). Several changes in one build at Mark's request. The first two change what the journal keeps; everything else is logging only and can never stop a save, a backup or a playback.
**A. Journal keeps 5 days** (`utils/journal.py`): `JOURNAL_KEEP_DAYS` 14 -> 5 (local and shared folders). The 3-day backup window, the 5 saved logs per device and the Keep-a-journal setting are unchanged.
**B. Journal follows the Log level setting.** New public `logger.is_debug()`. `journal.record()` now drops five bulky events unless Log level is Debug: `state_write`, `chanstate_write`, `clock_verified`, `clock_table`, `memory_behind` (about 41% of the bytes in the 11/17-11/18 journals; none is read by the overnight review). Every other event, including `snapshot`, is written at Warning, Info and Debug as before. `journal_check.py` is unchanged and still works: its section 7 simply has no `state_write` skew line when the build ran at Info.
**C. Backup and journal-copy evidence** (logging only):
- `journal.where(exc)`: the last four frames of an exception as `file.py:line function`. Added to the journal `flush error`, `start-up job error`, `sync error` and `could not add journal files to the backup` lines, so the 'NoneType' object is not callable seen on 11/17-11/18 names the call that failed.
- `files_for_backup()` now reads each journal file inside its own try: one unreadable file is logged by name and the others are still added (before, the first error dropped every file after it). New Info line: `[journal] backup: N journal file(s), M bytes, from <folder> (K older than 3 days left out, F unreadable)`.
- A refused journal copy to the share now logs, on the first failure and every 12th: the file, its local size, whether the share folder and the target file are visible, and the playback context. The recovery line carries the playback context too.
- Backup (`router.backup_data`): new line at the start `backup: started; backup folder <path>; playing=<yes/no>, last playback end <N s ago | none since Kodi started>`; each failed copy attempt adds `zip <bytes>; on the share: visible=<>, <bytes> bytes; <s> since the first try` and the playback context to the existing line (its first part is unchanged); after a successful copy a line says `saved copy is N bytes, the same as the zip that was sent`, or `SIZE MISMATCH` (warning) when they differ. The result and the dialog are not changed by any of this.
- Playback context: `service.py` `_journal_play` (already called from onPlayBackEnded and onPlayBackStopped) calls new `journal.note_playback_end()`, which stores the time in a Home-window property; `journal.playback_context()` reads it. No new playback handler outside service.py.
- No new strings, no new settings.
**D.** `addon.xml` news and `USER_MANUAL.md` (section 18a and the backup paragraph) updated.
- Tests: new test_fix_165 (retention 5 days, the five events gated at Warning/Info and written at Debug, every other event unaffected, `where`, per-file backup isolation and the new Info line, copy-failure detail, backup start/attempt/saved-size lines and unchanged outcome, playback context, only the expected files changed); test_backup_130 passes unchanged.

## 3.1.164
Three changes in one build at Mark's request (a deviation from one-change-at-a-time; they touch separate code). Built on 3.1.163; rollback target 3.1.163. The journal-in-backup diagnostic planned for this build was dropped (Mark: the omissions look like a network issue).
**A. Kodi video-info calls.** The five `ListItem.setInfo()` calls in `router.py` (channel list row, and the Coming Up Next listing for movie, audio, folder file and episode) now use `getVideoInfoTag()` / `getMusicInfoTag()` setters (`setTitle`, `setMediaType`, `setTvShowTitle`, `setSeason`, `setEpisode`, `setYear`, `setPlot`, `setArtist`, `setAlbum`). The three old-style `setInfo` fallbacks in `player.py _make_listitem` are removed (the add-on needs Kodi 21, where the tag calls always exist); if a tag call fails, it is now logged as a warning and the item is still added. No visible change.
**C. Log level setting now works** (`utils/logger.py`, `settings.xml`, strings). Before, the setting only hid Debug lines; "2 = Warning" did nothing, so Info lines were always written. Now: Info (0, default) hides Debug; Debug (1) writes everything; Warning (2) writes only warnings and errors. Any other or empty value behaves as Info. Stored values keep their meaning (0/1/2), so nothing changes for anyone who already set it. The number box became a Warning / Info / Debug spinner (#32997-#32999; #32050 now just "Log level"). The 21 direct `xbmc.log` calls (16 in `utils/paths.py`, 2 in `overlays/coming_up_next.py`, 3 in `overlays/logo_overlay.py`) bypassed the setting; they now call the add-on's `log()` with the same level each had (15 warnings/errors; 4 Info: ComingUpNext shown, LogoOverlay shown and cancelled, save_json succeeded on a retry; 2 that Kodi logs at Debug by default: migrate copied/deleted). Wording change: the `[plugin.video.smartchannels][paths]` prefix is now `[plugin.video.smartchannels] [paths]` (one prefix, from `log()`), and the two overlays' prefix likewise. No `xbmc.log(` call is left outside `utils/logger.py`. Leave on Info for testing: the soak checks read the Info lines.
**D. User manual** (`USER_MANUAL.md`, now the full manual, version 3.1.164): new side panel text (Channels heading, next-item line, Channel list opens on), per-episode Reset Show in both views, Log level and the other new settings, Timing master explained as an optional back-up (off by default; try it only if double pops or missing queue items still appear with the folder lock on; how it differs from the lock, how to set it up, what happens if it is off), default-length rows in Missing Durations, library rebuild after every Kodi scan and the daily update's run-at-once rule, the overlay remote-buttons note, the jitter hint, a corrected Quick Start (steps 2 and 6), new Troubleshooting rows, and Glossary entries.
**B. Setting "Channel list opens on"** (Settings > Advanced, enabled with "Use side panel"). Choices: First channel (default, as before), Last channel played, A specific channel. A button "Choose the channel to open on" and a read-only line showing the chosen channel's name appear below it.
- Last channel played = the last channel `start_channel` started on this device (includes channels started by a schedule). Stored per device in the local `panel_start.json` (not shared, not part of backups); written by new public `channel_manager.remember_last_channel`, called once from `player.start_channel` after play begins (not recorded when the start is refused or the queue is empty).
- `channel_manager.get_panel_start_index(channels)` picks the row; it falls back to the first channel when nothing is recorded, the setting is unreadable, or the recorded channel is deleted or hidden. The side panel selects that row in `onInit` and shows its queue on the right.
- New router action `pick_panel_channel` (dispatch in `addon.py`), strings #32988-#32996. 
- Tests: new test_fix_164 (log level rules at 0/1/2/empty/stray, info tags for every item kind in both files, tag failure handled, setting definitions, start-index rules, start_channel recording rules, panel selection, the choose button, only the fourteen expected files changed).

## 3.1.163
Side panel, built on 3.1.162 (rollback target 3.1.162). Two small changes in one build at Mark's request (a deviation from one-change-at-a-time, both are display only and share the same two files). Files: `side_panel.py`, both `SmartChannels_Main.xml` (Default, skin.estuary), `strings.po`, `addon.xml`.
- New "Channels:" heading (control 302, string #32984) at the top of the channel list, same font and colour as the "Upcoming" heading, with a thin separator under it. The channel list moved down to top 132 (height 800, still 7+ whole rows).
- Each channel row now shows a second line (the list item's label2): `Next: <show> · S3E4 · 42 in queue` for several-show channels; the show name is left out when the channel has one show or the show name equals the channel name; movies show `Next: Title (Year)`; folder files show the file name without extension; audio shows `Artist - Title`; a mixed channel shows each item its own way; an empty queue shows "No items in queue" (existing #32692). New strings #32985 "Next: {0}", #32986 "{0} in queue", #32987 "S{0}E{1}".
- Lines are read through the public `get_channel_queue`. A queue that cannot be read leaves that line blank. Filling stops after 4 seconds total (so a slow share cannot delay opening the panel); remaining rows stay blank and every channel is still listed. When a channel is selected, its line is refreshed from the queue the right pane just read (no second read).
- `_queue_item_kind` classifier added and used by `_format_queue_item` too, so the right pane and the new line agree on what is a movie, folder file or episode; right pane output unchanged.
- Tests: new test_fix_163; other suites unchanged (test_fix_160/161/162 file-set checks fail on newer builds by design).

## 3.1.162
Look-only change to the side panel, built on 3.1.161 (as asked by Mark: bar shorter so it does not reach the episodes, corners rounded). Rollback target 3.1.161. Files: both `SmartChannels_Main.xml` (Default, skin.estuary), two new textures `rounded.png` (48x48, radius 14) and `rounded_small.png` (16x16, radius 5) in each of those two skins' `media` folders, `addon.xml`. No Python, settings or strings changed; Confluence file untouched.
- Channel list: the selected bar is 960 px wide at left 10 (was 1044 wide at left 6), leaving about 86 px before the divider; its corners are rounded with a 14 px radius (`<texture border="14">`, so only the corners stay curved when the bar is stretched). The accent stripe is now a short rounded tab (6 x 70) inside the bar's left edge. Icons moved right to 28 and the text to 128, with a width of 810, so everything stays inside the bar in both the focused and the plain row. The faint wash used while the right pane has focus has the same shape.
- Coming Up Next list: the bar keeps its full width, with the same rounded corners; the tab is 6 x 80 inside its left edge; poster moved to 24 and the text to 96 (width 750) in both row states.
- The textures are white; their colour comes from the tint, so bar colours are unchanged (bar FF0B6CE0, tab FF9FD6FF, wash 3300AAFF).
- Tests: new test_fix_162 (textures resolve, rounded PNGs are valid with transparent corners and opaque white body, border values fit, geometry of both lists, copies identical, only the eight expected files changed). Other suites unchanged.

## 3.1.161
Build on top of 3.1.160 (declared by Mark): the blue selection bar from 3.1.160 did not show. Root cause confirmed from Kodi's source and the add-on's files: the skin files named `black.png` for every bar and background, Kodi looks for a bare texture name in `<skin folder>/media/` (`CGUITextureManager::GetTexturePath`: texture path + `media` + name), and the add-on had no `media` folder at all (Estuary keeps its own `black.png` under `colors/`, not where the name pointed). So none of the 12 coloured layers (full-screen dim, header, both pane backgrounds, divider, separator, focus bars and strips) was ever drawn, in 3.1.160 or before; the yellow text was the only selection cue. Rollback target 3.1.160 (3.1.159 has the same fault). Files: both `SmartChannels_Main.xml` (Default, skin.estuary), new `media/white.png` in each of those two skin folders, `addon.xml`. No Python, settings or strings changed. The Confluence file is untouched (Confluence is not part of Kodi 21).
- The 12 colour layers now name `white.png`, a 4x4 opaque white PNG shipped in the add-on (`resources/skins/Default/media` and `resources/skins/skin.estuary/media`, the folder Kodi opens for that skin); the tints are unchanged (bar FF0B6CE0, strip FF9FD6FF, header FF1A1A2E, panes E5111111 / E50D0D1A, and so on). Kodi multiplies a texture by its tint, so a white texture shows the tint colour as is.
- First time these backgrounds are drawn: the header, both panes, the full-screen dim and the dividers now appear in their written colours.
- Tests: new test_fix_161 (every plain texture name resolves to a file in that skin's media folder, the PNG is valid and solid white, no black.png left, tints and fonts as in 3.1.160, copies identical, only the six expected files changed). All other suites unchanged.

## 3.1.160
Look-only change to the side panel, built on top of 3.1.159 (its overnight soak had not been analysed when this was built). Rollback target 3.1.159. Files: the Default and Estuary `SmartChannels_Main.xml` skin files (identical copies), `addon.xml`. No Python, no settings, no strings changed. The Confluence skin file is untouched (Confluence is not part of Kodi 21).
- Found while preparing: Estuary does not define `font16` or `font20`, which the panel used, so Kodi silently used its default `font13` (30 px) for them; names and subtitles were therefore the same size. The panel now uses fonts Estuary does define (checked against Kodi 21 Omega's Estuary Font.xml, both font sets).
- Channel names: `font40_title` (bold 40 px), subtitles `font27`. Rows 96 to 110 px tall, icons 72 to 84 px.
- Selection: solid bright blue bar (`FF0B6CE0`) with a light-blue strip at its left edge and white text, replacing the translucent blue with yellow text. The bar has a 3 px margin so rows no longer touch.
- Coming Up Next list: titles `font32`, subtitles `font27`, same bar and strip. Header `font37`, "Upcoming" label `font32_title` in a lighter blue, footer text lighter grey.
- Hard-wired (no settings). Other skins use the Default file and fall back to font13 for any font they do not define.
- Tests: new test_fix_160 (skin file checks: valid XML, control ids, fonts all defined in Estuary, no yellow, nothing outside its row, only the expected files changed). Other suites unchanged.

## 3.1.159
Two changes built on top of 3.1.158 (its overnight soak had not been analysed when this was built; Part A of the 3.1.158 test passed). Rollback target 3.1.158. Files: `channels/base.py`, `channel_manager.py`, `ui/channels.py`, `ui/side_panel.py`, `strings.po` (#32716), `addon.xml`. No new settings.
- Change 1, Missing Durations records the default-length guesses: an episode or movie that is queued with the default length (no readable NFO, and Kodi holds no running time, or under 60 s) is now recorded as `default_length` in the channel's Missing Durations list (state.json) and in `missing_durations.txt`, once per file per Kodi session, as the skipped items already were. The item stays in the queue; this is recording only. Nothing is recorded for an NFO duration, a Kodi running time (the `kodi_runtime` fallback) or a Folder item (folder items always take a default). `normalize_ep` / `normalize_movie` return a `QueueItem` (a dict subclass, equal to and saved as the plain dict) whose `duration_source` says `default_setting` when the default was used; each of the 8 queue-building sites calls the one new method `ChannelManager._note_default_length` straight after normalising, which uses the existing `record_missing_duration`. No queue field, state key or saved format changes.
- The Missing Durations lists (channel menu, side panel) show "(default length used)" after such rows; one function (`missing_duration_label` in `ui/channels.py`) now builds the row text for both lists instead of two copies. New string #32716.
- Small fix in the same list: `record_missing_duration` took the show's name from `tvshowtitle`, but a raw Kodi episode calls it `showtitle`, so skipped episodes were listed with the episode title as the show. It now reads `tvshowtitle`, then `showtitle`, then the title.
- Change 2, daily library update: `run_library_upkeep` skips the rebuild of `local_library.json` when the file was rebuilt within the last hour (`UPKEEP_FRESH_SECONDS` = 3600; a file up to 5 minutes in the future is treated as clock skew, further than that is not trusted). The rest of the job (clear lists, repair paths, put back missing shows) runs as before, the day is marked built, and a retry does not rebuild either. The age comes from the existing `LibraryClient.local_cache_age_days()`. Journal `upkeep_done` gains `rebuilt` (true / false); the log says `local_library.json was rebuilt N min ago - not rebuilt again`.
- Tests: new test_fix_159 (47 checks; fails on 3.1.158, passes on 3.1.159). Two older tests changed on purpose: test_duration_fallback B2 now expects the one default-length record (and clears records made while the test world is built); test_library_upkeep gives its test library an old cache age so the job still rebuilds; test_combo_152's stub gets the new no-op method. All other suites give identical results to 3.1.158. 5000-step simulation: 0 violations, hash d161adb926caf8f1 (unchanged).

## 3.1.158
Three small, separate changes built on top of 3.1.157 (soaked one night on 5 devices: 327 draws in order, reload fix working on every device, 15 wraps logged as wraps, no add-on errors). Rollback target 3.1.157. Files: `strings.po`, `side_panel.py`, `channel_manager.py`, `addon.xml`. No new strings, no new settings.
- Change 1, Auto-Create message (strings #32676): the "library not ready" message said to use Refresh Library Cache "from the main screen"; that button is in Settings > Cache. Text only; the code that shows it is unchanged.
- Change 2, side panel Reset Show: `_show_episode_context_menu` reset the show at once, without the confirmation question and without the check that another device is playing the channel, both of which the Kodi list version already has. It now runs the router's existing `reset_next_episode` through RunPlugin (the way the panel's other actions already run), so there is one copy of that code and both views behave the same. The panel refreshes itself within about 10 seconds through its queue watcher. No private method of another module is used.
- Change 3, CURSOR SHRINK and wraps: the second safety check in `_guard_cursors` (positions total halves or worse) fired when one long show wrapped to its first episode (04:36 on 11/15, Test Carousel channel: 220 to 82). It now adds back the positions given up by shows whose wrap was noted a moment before (the 3.1.157 `_RECENT_WRAPS` note) before it compares. Any loss the wraps do not explain still warns and still keeps the old cursor in `cursor_kept_*.json`; so do a fall in the number of shows and an emptied cursor. The check still only logs and keeps a copy; it never changes a cursor.
- Not changed: the journal label fix of 3.1.157 is already covered by test_fix_157 B1 (queue changed between `play_start` and `play_end`; fails on 3.1.156, passes on 3.1.157), so no extra work was needed.
- Tests: new test_fix_158 (26 checks; fails on 3.1.157, passes on 3.1.158). All 39 earlier suites give identical results to 3.1.157. 5000-step simulation: 0 violations, hash d161adb926caf8f1 (unchanged).

## 3.1.157
Two small, separate changes built on top of 3.1.156 (soaked two nights on 5 devices: no lost, repeated or out-of-order episodes in 279 draws; no add-on errors). No failed fix involved; rollback target 3.1.156. Files: `library.py`, `channel_manager.py`, `service.py`, `addon.xml`. No new strings, no new settings.
- Change 1, reload defect (found by reading the 3.1.156 code, not seen as a failure): `refresh_if_cache_changed()` remembered the modified time of `local_library.json` on the LibraryClient object, but the service builds a new ChannelManager (and so a new LibraryClient) on every tick, so every call was a "first look" and the reload never fired. The time last seen is now kept in the module (`_SEEN_CACHE_MTIME`, per path). Effect: when the shared library file is rewritten (the hourly rebuild after a Kodi scan, or the daily upkeep) every device now drops its in-memory library lists within about a minute, as 3.1.156 intended. The log line is `local_library.json changed - library lists reloaded`.
- Change 2a, wrap wording: when a show goes back to its first episode the cursor save used to log `POSITION DROP` at warning level, which looks like a lost position. `_next_candidate_ep` now notes the wrap (`_RECENT_WRAPS`, 120 s) and `_guard_cursors` logs a noted wrap as `wrapped to the first episode` (info). A drop with no wrap noted still logs `POSITION DROP` as before. The journal `position_drop` record is unchanged, so `journal_check` and `soak_check` read the same files.
- Change 2b, journal label: `play_end` / `play_stop` named `queue[position]` at the time of the event; when the carousel had already removed the finished item, that was the next item. `play_start` now remembers its item and the end/stop records use it (used once, then cleared; with nothing remembered the old lookup is used). Journal only; no playback or state code reads it.
- Tests: new test_fix_157 (23 checks; A and B fail on 3.1.156, pass on 3.1.157; C covers the wrap wording and the real wrap site). All 39 earlier suites give identical results to 3.1.156 (test_library_upkeep 43, test_journal 43, test_block_expiry 41). 5000-step simulation: 0 violations, hash d161adb926caf8f1 (unchanged).

## 3.1.156
One feature, built on top of 3.1.155 (confirmed good by Mark): the library-upkeep half of the held 3.1.144. Files: `channel_manager.py` (new section; `skip` argument on two repair methods), `library.py`, `service.py`, `settings.xml`, `strings.po` (#32970, #32971), `USER_MANUAL.md`, `addon.xml`.
- New settings *Update the library automatically every day* (Settings > Cache, default OFF) and *Daily library update time (HH:MM)* (default 04:00). When ON, once a day after that time one device (claim on the shared state, same pattern as the carousel claim) rebuilds `local_library.json`, clears its library lists, runs `repair_queue_paths` and `repair_missing_shows`. Channels played on any device are skipped (journal `upkeep_skipped`), retried every hour, three tries, then left until the next day's run; the rebuild itself happens once per day.
- Every device (setting on or off) checks the modified time of `local_library.json` once a minute and reloads its library lists when it changed.
- `repair_queue_paths(skip=None)` and `repair_missing_shows(skip=None)`: optional set of channel ids to leave out; default behaviour unchanged.
- The job runs on a background thread with its own manager object so the 60 s tick is not blocked. Journal: `upkeep_start`, `upkeep_skipped`, `upkeep_done`.
- Nothing is deleted; cursors, carousel clocks and resume points are not touched. With the setting OFF nothing changes (simulation hash d161adb926caf8f1, 0 violations).
- Tests: test_library_upkeep 43 (37 from the held build, 6 new: path repair keeps woven / block flags, no other file written, upkeep record survives a stale manager's writes, block expiry unaffected); test_block_expiry 41; all other suites identical to 3.1.155.

## 3.1.155
One feature, built on top of 3.1.154 (declared by Mark: re-add the held 3.1.144, one half at a time; this is the block-expiry half, the library-upkeep half follows as its own build). Files: `scheduler.py`, `carousel.py`, `channel_manager.py` (one new section), `service.py`, `settings.xml`, `strings.po` (#32969; #32970 and #32971 stay reserved for library upkeep), `USER_MANUAL.md`, `addon.xml`.
- New setting *Remove scheduled blocks when their time slot ends* (Settings > Channels, default OFF). When ON, an unwatched block item is taken out of the queue when its time slot ends. Slots run one after the other from the schedule's start time, each as long as the item's own running time (an item with no length uses the default TV episode or movie length from the settings). No replacement is added, the item's resume point is cleared, `block_expired` is journalled, and the block counts as played. Done about once a minute under a claim so only one device removes; a channel played on any device is left alone; an unreadable queue is skipped. A block that fired before the upgrade gets its slot at the first pass.
- Carousel: with the setting ON, a channel whose queue starts with a block item is skipped by the carousel and its clock is held at now (like a channel being played), so the carousel neither pops block items nor owes the time afterwards. The guard sits after the playing / other-device / schedule-source checks and before the timing-master check (3.1.146).
- `fire_block` writes the slot start and the item durations into the block record (one helper replaces two identical literals).
- Changed from the held 3.1.144 code: `default_item_seconds` uses the built-in length (30 / 100 minutes) when the default setting is 0; otherwise an item with no length would get a 0-second slot and be removed a minute after the block fired.
- With the setting OFF nothing changes: 5000-step simulation hash d161adb926caf8f1, 0 violations.
- Tests: test_block_expiry 41 checks (22 fail on 3.1.154; K1 and N4 fail with the carousel guard removed): new G3 (default 0), K2b (clock through the manager and the chanstate file), M (timing-master follower), N (end to end on a carousel channel). All 36 other suites identical to 3.1.154.

## 3.1.154
Fixes in the new 3.1.153 action plus one wizard fix, built on top of 3.1.153 (declared by Mark: build on top; root cause of the first two confirmed in simulation; this is the first fix on top of 3.1.153). Files: `channel_manager.py` (`capture_combo_progress`, new `_queued_in_order`), `ui/dialogs.py` (new `keep_existing_show_order`), `ui/wizards/combo.py`, `ui/wizards/tv.py`, `USER_MANUAL.md`, `addon.xml`. No new strings, no new settings.
- Report (Mark, kodi.log + channels.json + queue file): after adding a sequential show to a Combo slot and using Rebuild Queue, Keep Places, the show started at S01E06 and was not at its first episode.
- Cause 1 (confirmed, 6 of 6 simulated runs): the action carried the first queued episode of every sequential Combo show over as its place. If the show was random on the previous build, that first queued episode is a random draw, so after switching the show to sequential the run started at that draw. Fix: the place is carried only when the show's queued episodes follow each other in the show's own episode order (`_queued_in_order`; a single queued item counts as in order). Otherwise the show gets the slot's starting point for it, or, with none, starts at its first episode.
- Cause 2 (confirmed): a sequential Combo show that has a starting point and nothing queued yet started at its first episode in a Rebuild (Reset Channel honoured the starting point), and the top-up pointer was then set back to the starting point so that episode could play twice. Fix: such a show starts at its starting point in a Rebuild, and the pointer follows the queue. Not changed: `regenerate_queue` / Manage Interleave still ignore a Combo show's starting point (older behaviour).
- Wizard (Combo slot edit): the shows came back in library order, not in the slot's order (the manual-order step had to be used to keep it). Existing shows now keep their order and added shows follow. `keep_existing_show_order` in `ui/dialogs.py` is also used by the TV channel wizard in place of its own inline copy (same result; test_eps_prompt_151 and test_wizards_143 unchanged).
- Not explained: the show was stored as sequential in the saved definition and in the queue file Mark sent. Whether it was random at the 13:16 build (before the second edit) cannot be known from the files.
- Tests: new test_fix_154, 26 checks (N random to sequential, O a sequential show keeps its place, P starting point, Q order test, R wizard order); the N and P checks fail on 3.1.153 and pass on 3.1.154. test_keep_places_153 (797/806 checks), test_side_panel_153 17/17, test_combo_152 44/44, test_eps_prompt_151 35/35, test_wizards_143 42/42. All 27 earlier suites with a stored 3.1.153 baseline identical (test_block_expiry differs only in a timestamp and fails by design until 3.1.144 is re-added). 5000-step simulation: 0 violations, hash d161adb926caf8f1.

## 3.1.153
One feature, built on top of 3.1.152 (declared by Mark; no failed fix involved; 3.1.152 confirmed working by Mark). Files: `channel_manager.py`, `router.py`, `addon.py`, `ui/channels.py`, `ui/side_panel.py`, `strings.po` (#32976 to #32979 new; #32969 to #32971 stay reserved for the held 3.1.144), `USER_MANUAL.md`, `addon.xml`. No new settings.
- Request (Mark): after editing a Combo Block that is interleaved into a regular channel, the channel's queue still holds the episodes built from the old slot, so the edit only shows up in items added later. Reset Channel would bring it up to date but sends every show back to S01E01.
- Addition: context-menu item "Rebuild Queue, Keep Places", next to Reset Channel, shown for TV, Movie and Folder channels that have an interleave configured (not for Combo Blocks). It asks for confirmation, then rebuilds the queue: the channel's own shows continue from the head of the queue, interleaved TV shows continue at their next episode, and the sequential shows of every Combo Block TV slot continue at their next-to-play episode. Resume points are kept. Nothing is cleared. Shows added to the Combo Block since start at their beginning; shows removed from it are gone. A Combo slot that takes turns, or plays a unit of several shows together, starts its rotation again from its first show (its episode places are kept). Randomised Combo shows have no place to keep and are redrawn.
- How: `ChannelManager.rebuild_keep_places(channel_id)` notes the first queued episode of each sequential Combo show (`capture_combo_progress`), then runs the existing `regenerate_queue`. `_reset_combo_interleave_sources` puts the noted episodes back instead of leaving the pointers cleared, and `_apply_combo_slot_starting_points` does not overwrite them with the slot's starting points during that rebuild. Both read one attribute (`_combo_resume`) that is set only inside `rebuild_keep_places` and cleared afterwards, so Reset Channel, interleave changes and edits behave exactly as before. Returns False, changing nothing, for a channel with nothing woven in, a Combo Block, an unknown channel, or a queue that cannot be read right now (the user is told).
- The router action refuses the same way Reset does when another device is playing the channel (`_channel_change_blocked`).
- Side panel (added to this same 3.1.153 on Mark's instruction, build on top, after he reported the item missing because he uses the side panel): `ui/side_panel.py` lists the same item right after Reset Channel under the same conditions (TV, Movie or Folder channel with an interleave) and calls the same `ChannelManager.rebuild_keep_places`, with the shared confirmation (`confirm_rebuild_keep_places`) and strings #32976 to #32979; no new strings. Unlike the side panel's other actions it refuses, as the list menu does, when another device is playing the channel (public `channel_lock_holder`, text #32949). Then the panel is refreshed. The side panel's own Reset copy is untouched (it has no other-device check and does not keep interleaved places; not part of this change).
- Not changed: Reset Channel; `regenerate_queue` and the interleave wizard (they still send Combo shows back to their start, as before).
- Checked before building: no private method of another class is called (router and UI call the public `rebuild_keep_places`); no playback callback touched; the only code that clears combo pointers (`_reset_combo_interleave_sources`) was extended, not duplicated; strings #32976 to #32979 were free in this build and in 3.1.144.
- Tests: new test_side_panel_153 (17 checks: entry shown only for TV/Movie/Folder with interleave and placed after Reset; confirm yes/no; manager refusal; other device playing), 17/17. New test_keep_places_153 (about 800 checks per 60 trials: own shows, interleaved Combo shows and the added show; pointers; resume points; refusals); passes on 3.1.153, and the old route (regenerate_queue alone) moved the Combo shows off their place in 63 of 63 cases in the same scenario. All 27 earlier suites with a stored 3.1.152 baseline identical (test_block_expiry differs only in a timestamp and fails by design until 3.1.144 is re-added). test_combo_152 44/44, test_eps_prompt_151 35/35, test_wizards_143 42/42. 5000-step simulation: 0 violations, hash d161adb926caf8f1.

## 3.1.152
Combo Block slot edit, built on top of 3.1.151 (declared by Mark; no failed fix involved; 3.1.151 had not yet been tested on a device when this build was started). Files: `ui/dialogs.py`, `ui/wizards/combo.py`, `ui/wizards/tv.py`, `ui/wizards/movie.py`, `channel_manager.py` (`build_combo_movie_slot`, one block), `USER_MANUAL.md`, `addon.xml`. No new strings (reuses #32961 to #32968 and #32972 to #32975), no new settings.
- Problem found (Mark's question, checked in the code): editing a Combo TV slot rebuilt every show without its `episodes_per_slot` and `episode_filters` (the counts were lost on edit; the Yes/No question defaulted to "No, keep 1 each"), dropped shows the filter does not match (they were not in the list), and had no way to add shows outside the filter. A Combo Movie slot is a filter OR a hand-picked list, so extras outside a filter could not be added at all.
- Combo TV slot: each show now keeps `episodes_per_slot` and `episode_filters` from the old slot. If any show has a number other than 1, the Keep / Change for every show / Set only the new shows list is asked (default Keep, cancel = Keep), as for TV channels. Shows already on the slot stay in the list when the filter does not match them. When a filter narrowed the list, "Also add shows that do not match the filter?" is asked. A slot whose shows are all at 1 still gets the old "Episodes Per Slot?" question. Slots that take turns are unchanged.
- Combo Movie slot (Add Filters mode): after the filters, "Also add movies that do not match the filters?" is asked (list opens straight away with the current extras ticked on a later edit). Extras are saved in the slot's `movies` list with `"pinned": true`, with the filters kept. `build_combo_movie_slot`: when a slot has both filters and a `movies` list, the pool is the filter matches plus those movies (no duplicates); exclusions still apply. A slot with only a hand-picked list, only filters, or neither builds exactly as before. Rolling back to an earlier build: such a slot would build from its extras only (an earlier build uses the list alone), so roll back only if you have not used the extras on a Combo Movie slot.
- No duplicate code: the Keep / Change dialog, the "extra shows" step and the "extra movies" step now live once in `ui/dialogs.py` (`ask_keep_change_episodes`, `ask_extra_shows`, `add_extra_movies`, all public) and are called from the TV wizard and the Combo wizard; the Movie wizard's own copy of the extra-movies function moved there and `movie.py` imports it. Behaviour of the TV and Movie wizards is unchanged (test_eps_prompt_151 35/35, test_wizards_143 42/42).
- Checked before building: no private method of another class is called; no playback code touched; `pinned` on combo slots is read only by `build_combo_movie_slot`.
- Tests: new test_combo_152, 44 checks (J Combo TV slot counts, K Combo TV slot filter/extras, L Combo Movie slot wizard, M build_combo_movie_slot pools). All 27 earlier suites with a stored 3.1.151 baseline identical (test_block_expiry differs only in a timestamp and fails by design until 3.1.144 is re-added: 11 passed, 22 failed, same as before). 5000-step simulation: 0 violations, hash d161adb926caf8f1.
- USER_MANUAL.md: one sentence in section 6.7.

## 3.1.151
One feature, `resources/lib/ui/wizards/tv.py` only, built on top of 3.1.150 (declared by Mark; no failed fix involved). New strings #32972 to #32975 (#32969 to #32971 are reserved for the held 3.1.144). No new settings. Combo Block slots are not changed.
- Request (Mark): editing a TV channel in which some show plays more than 1 episode per turn went through a number box for every show, needing an Enter on each even when nothing was to change.
- Behaviour: when you edit a TV channel with 2 or more shows and at least one show already has a number other than 1, a list "Episodes Per Show" is shown first, with "Keep the current numbers" selected: Keep leaves every show as it is and asks nothing more; "Change them for every show" gives the number box for each show, as before. If shows were added in this edit, a third choice, "Set only the new shows", asks the number box for the new shows only (each starts at 1). Shows added in an edit start at 1 whichever choice is made. Cancelling the list counts as Keep.
- Unchanged: creating a channel; editing a channel whose shows are all at 1 (the "Set Episodes Per Show?" question as before); channels with one show (no step); Combo Block slots.
- Checked before building: the change uses only the dialog and the wizard's own data (no call into another class, nothing private); there is no other copy of this step in the TV wizard (the Combo wizard has its own and was left alone, as asked); strings #32972 to #32975 were free in this build and in 3.1.144.
- Tests: new test_eps_prompt_151, 35 checks (F1-F4 edit without a new show, G1-G5 edit with a new show, H1-H5 unchanged behaviour), 35/35 on 3.1.151; on 3.1.150 the Keep/Change dialog does not exist, so its sections fail there. All other suites are identical to 3.1.150 (see the test procedure).
- USER_MANUAL.md: one line in section 7 under the TV bullets.

## 3.1.150
Re-adds the held 3.1.143 on top of 3.1.149 (declared by Mark: build on top; no failed fix involved). The wizard files and the `_build_movie_queue` block are taken from 3.1.143 unchanged; the wizard files in 3.1.145 to 3.1.149 were identical to 3.1.142, so nothing is merged by hand. `ui/wizards/tv.py`, `ui/wizards/movie.py`, `channel_manager.py` (`_build_movie_queue`, one block), `strings.po` (#32961 to #32968), `USER_MANUAL.md`, `addon.xml`. No new settings.
- Fix, TV wizard: editing a channel built with a filter dropped the shows that the filter does not match (they were not in the list, so they were not ticked, and the save removed them). The shows already on the channel are now always in the list and ticked, in library order, even when the filter does not match them. A channel whose shows all match the filter shows the same list as before.
- Addition, TV: when a filter narrowed the show list, the wizard asks "Also add shows that do not match the filter?" (No by default). Yes opens a list of the shows outside the filter; the ones ticked are added next to the others. Not asked when no filter is in use, when the library has 20 shows or fewer, or when nothing is outside the filter.
- Fix, Movie wizard: "Select Specific Movies" on a channel built with filters ticked every movie, because such a channel keeps the whole library in its movie list and applies the filters when the queue is built. It now ticks only what the channel plays: the movies the filters match, minus the exclusions, plus the ones added by hand. A channel without filters ticks its list as before.
- Addition, Movies: after the filters are set, the wizard asks "Also add movies that do not match the filters?" (No by default). Yes opens a list of the movies the filters do not match; the ones ticked are saved in the channel's movie list with `"pinned": true`. `_build_movie_queue` applies the filters to the other movies only, so pinned movies are not filtered out; exclusions still remove them. A channel that already has pinned movies opens the list straight away with them ticked (unticking removes them). Channels without pinned movies build exactly as before. Rolling back to an earlier build keeps working: the flag is ignored and the extra movies drop out of the pool.
- Checked before building: the wizards call only public library methods (`get_movies_with_filters`, `get_all_tvshows`, `get_tvshows_with_filters`); no private method of another class; strings 32961 to 32968 were free; `pinned` is used nowhere else; combo movie slots (`_fetch_movie_items`) read their own slot list and are not affected.
- Tests: test_wizards_143 (42 checks) now passes 42/42 on 3.1.150 with no change to the test (17 passed, 11 failed on 3.1.149, as expected without the change). All 26 other suites with a stored 3.1.149 baseline give identical results; test_dir_exists_149 24/24, test_write_lock 40/40, test_write_lock_integration 20/20, test_clock_jump 22/22, test_journal_check 9/9; 5000-step simulation hash d161adb926caf8f1 identical.
- USER_MANUAL.md: two lines added in section 7 (create a channel) for the two additions and the corrected tick list; manual version line now 3.1.150.
- Not changed: playback, the carousel, the lock, state, the journal, backup and restore, every other wizard.

## 3.1.149
One fix, `resources/lib/utils/paths.py` only (`_dir_exists`). Built on top of 3.1.148 (declared by Mark; no failed fix involved). No new strings, no new settings.
- Evidence (11/10 to 11/11 soak, PVR PC kodi.log 07:53 on 11/11; Kidsroom log): `load_json failed ...\channel_lock_owned.json: folder not reachable` once a minute, starting 7 s after the add-on started. The file is only written while this device holds a channel lock, so it is normally absent (confirmed on the PVR: the folder is there, the file is not).
- Cause: `load_json_strict` answers "folder not reachable" when the file is missing and `_parent_reachable` says its folder is not there. `_dir_exists` added the trailing separator that `xbmcvfs.exists()` needs to check a folder only for `smb://` paths; its comment said local paths do not need it. A local folder was checked as if it were a file and reported missing.
- Fix: `_dir_exists` now gives local folders the trailing separator too (and returns False for an empty path). SMB behaviour is unchanged.
- Effect: a missing file in an existing local folder returns the default and logs nothing. A folder that is really unreachable still raises `JsonReadError` / logs the warning. `resolve_path` no longer calls `mkdirs` on every use when the shared folder is a local or mapped-drive path that exists.
- Tests: new test_dir_exists_149, 24 checks (D1-D8), including the reported case and the unreachable-folder case; 3 of its checks fail on 3.1.148 (the control). All other suites give results identical to 3.1.148.
- Not changed: playback, the carousel, the lock, state, the journal. Other code that checks a folder with `xbmcvfs.exists()` was not changed (see the test procedure).

## 3.1.148
One change, built on top of 3.1.147 (declared by Mark; no failed fix involved). New `resources/lib/utils/write_lock.py`; `channel_manager.py`, `settings.xml`, `strings.po` (32982, 32983). New setting `write_lock` (Settings > Network, default on).
- Evidence: the share probe (runs 2 to 5, PC and Kidsroom Shield over SMB) measured that renaming a file that exists is exclusive (33 of 33 rounds, about 3 ms), while creating a folder, copying a file or renaming onto a new name is not. A counter updated by read, change, write lost 42 of 80 updates with no lock and 0 of 80 with the rename lock. A lock whose holder died was taken over by exactly one waiter after 15 s. Every double pop since 11/02 came from two devices saving state.json or the claim at the same moment.
- Lock: one file, `mutex.dat`, in the shared folder. A device takes the lock by renaming it to `mutex.held.<device>.<nonce>` and gives it back by renaming it to `mutex.dat`. Waits are at most 2 s (`WRITE_LOCK_WAIT_MS`, `WRITE_LOCK_CLAIM_WAIT_MS`); after that the device writes anyway and journals `lock_fail_open`, so a stuck share cannot freeze playback. A held name unchanged for 120 s belongs to a device that is gone; one waiter takes it by renaming that exact name. Each hold has a new name, so a slow but living holder is never taken. The holder checks its name still exists right after taking the lock and when giving it back (`lock_lost`). Taking it again in the same thread is free. If no lock file exists, `mutex.dat` is created (`lock_created`). Nothing in the module raises.
- Where it is used: `_save_state` (state.json read-merge-write) now runs under the lock (`_save_state_unlocked` holds the unchanged body); `set_carousel_state` takes it once for the channel file and state.json together; `claim_carousel_pop` checks and writes its claim under the lock (`_claim_write`, the old body unchanged apart from returning None for a refusal) and gives it back BEFORE the settle wait, so other devices' saves are not held up for 1.5 s.
- Off: no shared folder, or setting `write_lock` off, means no file of the share is touched and behaviour is identical to 3.1.147.
- Journal: `lock_fail_open` (at most once a minute, with a count), `lock_takeover`, `lock_lost`, `lock_created`, `lock_busy` (a wait over 1 s), `lock_release_failed`, `lock_stats` (hourly: takes, waits, fail-opens, average and maximum wait, maximum hold).
- Tests: new test_write_lock (40 checks, W1-W13) and test_write_lock_integration (20 checks, I1-I8, including 20 rounds of two devices claiming one pop). All earlier suites give results identical to 3.1.147 (test_block_expiry differs only by a timestamp inside a check that fails on 3.1.145 and later by design); simulation hash d161adb926caf8f1 identical.
- Not covered: the channel lock (`claim_channel_lock`) and schedule claims still use read-back; queue files and channels.json are written without the lock. Several simultaneous waiters on a dead lock were tested in memory (W4) but not yet on the real share.
- Install: put an empty file named `mutex.dat` in the shared folder, or let the first device create it. Do not mix 3.1.145 with 3.1.146 or later on one share. Old builds ignore the lock; they are not protected by it.

## 3.1.147
Logging only, built on top of 3.1.146 (declared by Mark; no failed fix involved). `channel_manager.py` only; tests and `journal_check.py` extended. No behaviour change, no new strings, no new settings.
- Problem: the 11/08 to 11/09 night showed carousel clocks that moved forward 2573 to 5228 s on three channels (Galactic Adventures, Real Crime, Hallmark Mysteries) with no pop, claim or play logged near it. A queue copy from before the jump is not available, and a bigger queue would not have helped: the question is which code path moved the clock.
- `chanstate_write` now carries `prev` (the clock this process last read from the channel's file or wrote), `delta`, and `q` / `q_prev` (the queue file's [mtime, size] now and at the previous clock write). A clock that moved while the queue file did not change had no pop behind it.
- New journal line `clock_jump` (and a log warning): the clock moved forward by more than 300 s (`CLOCK_JUMP_SECONDS`), this process won no claim on the channel in the last 120 s (`CLOCK_JUMP_CLAIM_AGE`), and the write is not the hold of a playing channel. Fields: prev, clock, delta, via (call path, six names), claim_age, q, q_prev, queue_changed, device.
- `journal_check.py`: new section 8, every `clock_jump` with its path and `queue_changed`.
- Tests: new test_clock_jump, 22 checks (J1-J8). All other suites identical to 3.1.146 (test_block_expiry, test_library_upkeep, test_wizards_143 belong to the held builds); simulation hash d161adb926caf8f1 identical.
- Not a fix: this names the writer if it happens again; it does not stop an unexplained jump.

## 3.1.146
Two changes on top of 3.1.145, for testing on two devices first. `channel_manager.py`, `carousel.py`, `utils/paths.py`, `settings.xml`, `strings.po` (32980, 32981). New setting `timing_master` (default off).
- Evidence (11/08 to 11/09, four devices on 3.1.145): four double pops in about 16 hours, three of them between Shields only. The clock floor held five times but every device still reads, changes and writes the same `state.json` over a share with no locking, so a whole-file save by one device can still hide another's pop (11/08 20:41: Bedroom and Kidsroom popped Test Channel 4.9 s apart).
- Part A, timing master: with `timing_master` on, a device writes `master.json` (device id and name, time, counter) at most every 50 s from the carousel tick. A device that sees a fresh heartbeat (counter changed within 300 s of its own clock; first sight also within 300 s of the written time) does not pop and does not claim; it still holds the clock of the channel it is playing and still skips channels locked by another device. An unreadable heartbeat keeps the last news for 300 s. No master, a stale one or setting off: every device pops as before. Two masters: the lower device id acts, the other defers and journals `master_conflict` once. Journal: `master_seen`, `master_lost`, `master_back`, `master_conflict`, `follower_skip` (hourly count per channel).
- Part B slice 1, per-channel clock file: the carousel entry of a channel (`last_pop_time`, `last_popped_show`, `pop_claim`) is written to `chanstate_<channel id>.json` first, then `state.json` still gets the same entry (mirror, so 3.1.145 and the diagnostics find it). Reads (claim, settle, verify, watch, tick refresh) take the entry from the channel's own file; a channel with no file yet is read from `state.json` and the first write creates the file. An unreadable file refuses the claim and writes nothing. `delete_channel` removes the file; the file is a data file (migration, Delete All Data). `master.json` is not a data file. Journal: `chanstate_write`.
- Tests: new test_master_clockfile, 59 checks (A1-A11, B1-B9). test_clock_guard and test_diagnostics simulated a wipe by editing `state.json` only; they now make the same edit to the channel's file when it exists (`sync_chan`, no effect on 3.1.145), results 17/17 and 48/48 on both builds. All other suites identical to 3.1.145; the 5000-step simulation hash d161adb926caf8f1 identical (test_block_expiry, test_library_upkeep and test_wizards_143 belong to the held 3.1.143/144 builds and fail on 3.1.145 too).
- Not changed: cursors, positions, resume and queue-position state stay in `state.json` (slices 2 to 4 later). More share reads per carousel tick (one small file per carousel channel).
- Install note: do not mix 3.1.146 and 3.1.145 on the same shared folder without understanding that 3.1.145 ignores `chanstate_` files and `master.json`.

## 3.1.145
One fix, `channel_manager.py` only. Built on 3.1.142 (the installed build); nothing from 3.1.143/144 is included. No new strings, no new settings.
- Evidence (11/06 to 11/07, PC and Shields): the PC repeatedly read an old copy of `state.json` (about 21 to 22 s behind, constant lag) or an empty one, then saved from it. At 09:33:59 on 11/07 the PC read an empty file, then `clock_lowering_write` x5 wrote a carousel clock of 0.0 for Test Channel, although it had seen the Livingroom's clock (1794061543) 40 s earlier. The 3.1.142 guard (`_keep_newer_carousel`) only compares with the copy this save read; when that copy is the old or empty one, nothing is protected.
- Fix: `_keep_seen_clock` in `_save_state`. This process remembers the highest carousel clock it has read or written for each channel (`_clock_seen`, already kept for diagnostics). A save that would write a lower clock (more than 0.5 s) for a channel seen within the last 120 s (`CLOCK_FLOOR_SECONDS`) writes the seen clock instead. Skipped: keys deleted on purpose, channels no longer on the share, and any save that could not read the channel list. Seeing the same clock again renews its 120 s window.
- Journal: `clock_floor` (channel, floor, was, who set the floor, path). Log warning on every correction.
- Tests: new test_clock_floor, 19 checks (old copy, missing entry, deleted on purpose, channel removed, higher clocks untouched, nothing seen yet, journal, inside slack, seen long ago, window renewal); 12 of 17 earlier checks pass on 3.1.142, so the new ones fail without the fix. All earlier suites give identical results to 3.1.142; 5000-step simulation hash d161adb926caf8f1 identical. test_clock_guard and test_double_pop now clear `_clock_seen` in their setup (isolation only).
- Not fixed: why the share hands back old or empty copies. This only stops a clock from being lowered by them.

## 3.1.142
Builds on 3.1.141 (journal and clock repair unchanged and still active). `channel_manager.py`, `carousel.py`, `player.py` (one call), `utils/journal.py`. No new strings, no new settings.
- Evidence (night 11/02 to 11/03, 3.1.141, all four devices, journals and logs): two carousel channels were popped twice for one interval, 8.2 s and 13.6 s apart (Classic Sitcoms 23:31:18 Bedroom then 23:31:26 PC; Hallmark Mysteries 04:07:16 Livingroom then 04:07:29 PC); ledger drift 1517 s and 5019 s, each equal to the first pop's front. The 3.1.141 guard repaired seven lost clocks that night (Bedroom 6, PC 1).
- Causes (from the logs and the code; the two double pops were NOT the same mechanism): (1) Hallmark Mysteries 04:07: the PC's tick began at 04:07:20.7 and read state.json then; the Livingroom's clock write landed after that, but its new queue file was already on the share, so at 04:07:27 the PC compared the old clock from its tick-start copy (elapsed 5039) with the NEW front (5030) and found a pop due. The claim then compared only targets (`shared clock >= my target`): the PC's target was 9 s above the Livingroom's new clock, so it passed. (2) Classic Sitcoms 23:31: the PC's tick began at 23:31:25.0, AFTER the Bedroom's pop and repair, yet its fresh read and its claim read both showed the OLD clock (elapsed 1530 against the new front 1233; the Bedroom's new clock would have made the claim refuse). So the new clock was missing from the share again after the Bedroom's guard stopped looking (about 3.6 s), or the PC was handed an older copy of the file. Who or what did that is NOT proven; the evidence lines below exist to name it. Separately, a refused claim stored the shared entry in memory as if the device had changed it, so its next save of anything wrote that older copy back over the winner's new clock.
- Fix 1: `claim_carousel_pop(channel_id, new_last_pop, based_on)`. `based_on` is the clock the due-check started from; the claim refuses when the shared clock is more than 1 s ahead of it. The refused device now holds the shared entry, so its next check starts from the shared clock. The old two-argument call still works.
- Fix 2: a refused or settled claim takes the shared entry as the device's copy without marking it changed (`_adopt_carousel`), so it is not written back.
- Fix 3: a save never lowers a carousel clock (`_keep_newer_carousel` in `_save_state`): when the file's `last_pop_time` is more than 0.5 s ahead of the one about to be written, the file's entry is kept. Every writer raises the clock, so nothing legitimate is blocked.
- Logging (so the next problem can be proven from the files): journal `claim` for every decision (won, lost, held, already_popped, clock_moved, unreadable) with the clock the check used, the target, the shared clock, the holder, and state.json's mtime and size as the device saw them; `carousel_kept` for every save that would have lowered a clock, with the path (`via`) that tried; `channel_start` now carries the device name (before: blank, in a file of its own); a failed journal copy to the share is logged on the first failure and every 12th (about hourly) with the count, and when it works again (before: once per run, silent after).
- Evidence logging for the lost clock (added before the first install of 3.1.142; logging only, no behaviour change, proven by identical simulation hashes): every save of `state.json` now stamps a `_writer` tag in the file (device, process, code path, save number, time), so whoever lowers a clock can be read from the file itself. New journal lines: `state_write` (what each save read, what it left, the gap between this device's time and the share's file time, the carousel clocks when they changed), `clock_regressed` and `clock_regressed_after` (a clock on the share is lower than one this device saw or wrote, or the entry is gone; the file's `_writer` tag; a second reading 3 s later), `clock_lowering_write` (a save that started from an older copy of the file), `clock_dropped_write`, `stale_read` (the file's time went backwards, which a file cannot do, so the share handed back an older copy), `memory_behind` (this device's remembered clock is older than the share's, the state a due-check uses), `tick_gap` (kind slept / late / wall_clock_set_back: answers whether a device slept), `clock_table` (hourly), `clock_verified` (the repair looked and the clock was fine), `state_unreadable`, `orphans_pruned`, `state_keys_deleted`, `state_write_failed`, `restore`. `clock_rewritten` now also records the writer tag, the file stamp and the entry it found. A failing diagnostic cannot stop a save (test J). The carousel tick calls `watch_carousel_clocks()` once a minute.
- Journal line `pop_batch_short` (carousel, timed or duration): a batch that ended before its `pop_count` items (library briefly down, empty queue) with done / of / reason (no_replacement, queue_unreadable, queue_missing_or_empty, queue_read_ok_now) / whether the clock was set. A queue cannot run out through use, so an empty read means the file was unreadable or missing on the share. Behaviour unchanged. The clock is already at the end of the interval when this happens, so the missing pops are not made up later: queued for the next revision (claude/QUEUE_NEXT_REVISION.md).
- `journal_check.py`: new section 7 (who lowered a clock) names the device and code path for every regression, tells an overwrite from a stale copy of the file, and lists the other evidence.
- `journal_check.py`: new section 6 (claims per device, every `clock_moved`/`lost`/`unreadable` with its numbers, DOUBLE POP = two devices popped one channel within 30 s) and `CLOCK KEPT` lines. Run on the 11/02 journals it finds exactly the two double pops and no other.
- Tests: new test_diagnostics, 48 checks; new test_double_pop, 58 checks (incl. timed mode with 3 items per pop: 3.1.141 popped 9 items where 3 were right when a stale device saw more intervals due) (22 pass and 24 fail on 3.1.141): the Hallmark case, the timed-mode case, the stale writer, legitimate writes, claim journalling, journal copy logging, and three long-lived devices over 250 random rounds with ledger drift 0 s (3.1.141: 43200, 42600, 73200 s). test_clock_guard 17/17, test_collision identical tallies, 5000-step simulation hash d161adb926caf8f1 identical. Suites not available in the build session were not run (listed in TEST_PROCEDURE_3.1.142.md).

## 3.1.141
One fix, `channel_manager.py` and `carousel.py` only. No new strings, no new settings. Builds on 3.1.140 (journal unchanged).
- Evidence (logs and backups of 11/01 to 11/02): twice the carousel clock of a channel was lost (Family Values 01:52:06, 00's Classic TV 03:07:26). All three devices found the same pop due within 3 seconds; the Bedroom Shield won the claim and popped, but the clock it saved (`last_pop_time`) was gone from state.json afterwards, so the next check found the same interval due again and popped once more. The channel then ran one episode ahead of its clock. No episode was lost or repeated. state.json is read, changed and written back whole; a device that read it before the pop was saved and wrote it after put the old clock back without any error. The 3.1.125 guard checks cursor positions only.
- Fix: new public `ChannelManager.verify_carousel_clock(channel_id, expected, last_popped_show)`, called once at the end of `carousel._do_pops` after any pop (regular, interleaved or scheduled block item). It waits 1.2 s, reads state.json strictly, and if `last_pop_time` is below the value the pop set, writes it again (up to 3 tries). A value at or above it is another device's later pop and is left alone; an unreadable state.json writes nothing. Same method as `_verify_cursor_saved`.
- Journal: each repair is recorded as `clock_rewritten` (channel, expected, found, attempt, device); `journal_check.py` lists it as CLOCK OVERWRITTEN. The guard does not hide the cause: the repair lines show how often and on which device the clock is lost.
- Cost: one extra read of state.json, 1.2 s after a carousel pop.
- Tests: new test_clock_guard, 17 checks (nothing wiped; wiped once; wiped twice; another device's later pop left alone; unreadable file; several pops in one call; nothing popped; scheduled block pop); 4 of them fail with the guard switched off. All earlier suites pass unchanged (test_journal 43/43, test_unplayable 67/67, test_collision 300/300, test_delete_all 8/8, test_duration_fallback 51/51, test_show_order 15/15, test_carousel_guard 19/19, test_block_count 7/7, test_block_race 18/18, test_stale_resume 21/21, 5000-step simulation hash d161adb926caf8f1 identical to 3.1.140). pyflakes clean.

## 3.1.140
Evidence build: nothing about playback, queues or positions changes. New setting (string 32960) and one new module, `utils/journal.py`. Builds on 3.1.139.
- Why: the soak of 11/01 to 11/02 could not show why some channels' positions moved more than the queue suggested. A pop line named only the channel and the episode title; the normal "episode finished" draw wrote no line at all; kodi.log keeps one old session; so neither the cause nor the missing stretches could be shown. The developer's requirement: every problem must be provable from the files.
- The draw journal: one JSON line per event, per device, buffered (flush every 10 s or 40 lines) and written to `journals/journal_<device>_<date>_<hour>.jsonl` in the add-on profile, then copied to `<shared folder>/journals/` every 5 minutes and at shutdown. It records: `session_start/end` (version, Kodi build), `channel_start` (first 12 queue items, resume point), `play_start/end/stop` (item, queue position, stop reason), `skip_detected` (the skipped items), `pop` (carousel and episode-finished, with show, season, episode, episode id, queue length) and `append` (what was added), `draw` (show, position before and after, ep_played count, the episode drawn, episodes skipped for a missing length, episodes already queued, the calling path), `cursor` (every position state.json changed, old value and new value, saved or not, the calling path), `cursor_rewritten` (the 3.1.125 guard put a position back), `position_drop`, `wrap`, `cycle_reset`, `skip_queued`, `seed_position`, `build` (queue built, with the episodes) and an hourly `snapshot` of every TV channel's positions and queue.
- The previous session's `kodi.old.log` is copied to `<shared folder>/journals/kodi_old_<device>_<date>_<time>.log` when the service starts (newest 5 per device kept), so a restart no longer destroys the log.
- Backup Addon Data adds the journals of the last 3 days of all devices (entries `journals/...`); Restore leaves them out of its list. Journal files older than 14 days are deleted automatically; Delete All Addon Data deletes them. Setting *Keep a draw journal* (Settings > Advanced, default on) turns it off.
- Hooks (each one call to `journal.record`): `channel_manager.py` (`set_cursor`, `_verify_cursor_saved`, `_guard_cursors`, `_pick_one_ep_no_slot_advance`, `_next_candidate_ep`, `_build_fresh_tv_queue`, new public `journal_snapshot()` and `journal_channel_name()`), `service.py` (playback callbacks, `_do_replacement_inner`, start, hourly tick, shutdown), `carousel.py` (`_do_pops`, `_apply_replacement`), `player.py` (`start_channel`), `router.py` (backup, restore, Delete All). The journal never raises into playback and never changes state.
- Tool for reading it (not part of the add-on): `journal_check.py` takes the journal files, kodi logs and backup zips and prints (1) COVERAGE: the time range of every device, log and journal, every hole with no clean session end marked NOT COVERED; (2) CONTINUITY: every place a show's position was not where the previous event left it, with the two events and the devices involved; wraps are told apart from other drops; (3) pops without an append; (4) totals per channel and path; (5) each backup's positions against the journal.
- Tests: new test_journal, 43 checks (journal file contents, copy to the share, setting off, failing disk, bounded buffer, clean-up rules, old-log copy, backup selection, Delete All, restore list, chain; every draw, cursor change, wrap, skip and snapshot recorded by the manager and consistent with the saved positions; checker finds a position changed by another writer, a pop without append, a 3-hour hole, a snapshot that disagrees, a backup position the journal cannot explain). All earlier suites pass unchanged (test_unplayable 67/67, test_collision 300/300, test_delete_all 8/8, 5000-step simulation hash d161adb926caf8f1 identical to 3.1.139). pyflakes clean on the changed modules.

## 3.1.139
UI only (ui/dialogs.py, ui/wizards/tv.py, serial.py, combo.py). No new strings, no queue or state changes. Builds on 3.1.138.
- Problem (developer, PC 11/01): creating a TV channel with 33 shows and "Random" episodes, the shows always came round in alphabetical order. The "Show Rotation Order" question (keep / shuffle / manual) was only asked on a Round-Robin channel (`if not randomize and len(selected_shows) > 1` in the TV wizard), so a Random channel could not have its shows shuffled.
- Change 1: the question is asked for every TV channel with two or more shows, Round-Robin or Random. Nothing else in the wizard changed: the per-show random question is still asked only on a Round-Robin channel, and the queue builder already used the saved show order, so it needed no change (checked: a Random channel with shows saved as 3, 1, 4, 2 queues them in that order). Existing channels are untouched until edited; in Edit Channel, *Keep Selection Order* keeps the saved order.
- Change 2: the shuffled order and the manual-order summary are shown in a scrolling text list holding every show (new `dialogs.show_order_listing`), instead of an OK box cut at 300 characters, which hid most of a 33-show list. Used by the TV, Serial and Combo Block wizards (the same truncated listing was written out in each). *Set Order Manually* is unchanged.
- Not changed: a fresh random show order every cycle (the order is fixed when the channel is saved; held for later).
- Tests: new test_show_order, 15 checks (Random and Round-Robin both ask; shuffle shows all 33 shows in the list; Keep leaves the order; manual order as picked; one show asks nothing; per-show random question unchanged; helper output); 9 of them fail on 3.1.138. All earlier suites pass unchanged (test_unplayable 67/67, test_collision 300/300, test_duration_fallback 51/51, 5000-step simulation hash d161adb926caf8f1). pyflakes clean on the four changed modules.

## 3.1.138
Two changes, requested together by the developer (rule 9 exception, kept separate in the code and in the tests). New strings 32957 to 32959, two new settings. Builds on 3.1.137, which is unchanged apart from the items below.
- Change 1, an episode whose `.nfo` cannot be read is no longer skipped. Evidence (Livingroom Shield 10/31 19:33:01 to 19:40:47): every `.nfo` check failed for about 8 minutes (12,095 `Duration skip ... no_nfo` lines). Each carousel draw then searched all 76 episodes of the show, found none, cancelled the pop, and still left the show's position one higher: seven attempts moved Haven by seven, so S01E09 to S02E02 were never queued; 276 false missing-duration records were written. The developer's rule: the next episode in order is appended as if nothing were wrong, nothing is searched ahead, the queue stays the same size.
- How: the duration now comes from, in order, the `.nfo`; the running time Kodi holds for the episode (`LibraryClient.get_episodes_for_show` now also asks for `runtime`; a value under 60 s is treated as a wrong unit and ignored); the new default length setting; and only if none of these gives a number is the item skipped, as before. `duration_cache.fallback_duration()` (new) does the choosing, `normalize_ep` and `normalize_movie` call it. A line `Duration fallback: show=... file=... seconds=... source=kodi_runtime|default_setting` is written to the Kodi log whenever it is used. `ChannelManager._default_episode_seconds()` / `_default_movie_seconds()` read the settings and are passed by every `normalize_ep` / `normalize_movie` call in channel_manager.py.
- Applies to every place a queue item is built (new queues, rebuilds, carousel, TV 1-for-1 replacement, interleave, Combo Block), not only the carousel. Effect on existing channels: an episode that has no `.nfo` but does have a running time in Kodi is now queued (before, it was left out and listed under Missing Durations). Such episodes are no longer added to the Missing Durations list; the Kodi log line is the record.
- New settings (Settings > Channels): *Default TV Episode Length (minutes)*, default 30, and *Default Movie Length (minutes)*, default 100; 0 turns the setting off (items with no length are then skipped as before). Movies use it only when Kodi holds no running time for the movie.
- Not changed: the ffprobe folder scan still sees a missing `.nfo` as missing (`get_duration` is untouched); the carousel position is still not restored when a draw returns nothing (now only possible when there is no `.nfo`, no Kodi running time and the default is 0); the Livingroom Shield's `.nfo` read failures themselves are not explained yet.
- Change 2, Studio filter by typed text, for TV Shows and Movies. In the filter builder, choosing Studio and then *contains* or *does not contain* opens a text box (string 32959) instead of the list of studios, so typing "Universal" matches every studio with that word. *is* and *is not* still pick from the list. An empty entry adds no rule. Matching was already case-insensitive and is unchanged (`library._text_matches`, JSON-RPC `contains`), so rules saved by earlier builds work as before. Only `ui/dialogs.py` changed for this.
- Tests: new test_duration_fallback, 51 checks (the chain and its edge cases, a carousel replacement with every `.nfo` unreadable moves the position by exactly one and writes no records, settings reading, Studio text rule for TV and movies, filter matching); it fails on 3.1.137. harness.py: the stand-in `normalize_ep` accepts the new argument. All earlier suites pass unchanged (test_unplayable 67/67, test_collision 300/300, 5000-step simulation hash d161adb926caf8f1 identical to 3.1.137). pyflakes clean on the five changed modules.

## 3.1.137
service.py only (no new strings). Builds on 3.1.136. The developer chose "build on top" (reason: the root cause is confirmed by Kodi's own log line, only the implementation detail was wrong; rule 11 allows one build-on-top). Second change to the full-screen step: if the restarted channel still plays behind the home screen after this build, roll back to 3.1.134 plus the 3.1.135 shutdown fix.
- Evidence (PC 10/31 11:33, cold start from the side panel with a missing first item): the skip, replacement and restart all worked and the next episode played (`onAVStarted`), but all three full-screen attempts were refused by Kodi: `Activate of window '12005' refused because there are active modal dialogs`. Kodi was showing its "One or more items failed to play" message. `System.HasModalDialog` reported False the whole time (`modal_dialog=False` in the diagnostic lines), so 3.1.136 never sent the close.
- Change: each full-screen attempt now always sends `Dialog.Close(all,true)` (waiting for it to finish), pauses 0.25 s, then opens the full-screen window, instead of closing only when `System.HasModalDialog` said a dialog was up. The step still runs only while video is playing and the full-screen window is not showing, within 8 s of an automatic restart, at most 3 times.
- Diagnostics: `_gui_state()` also logs `dialog=<id>` (`xbmcgui.getCurrentWindowDialogId()`), so a dialog that survives the close is visible in the log.
- Not changed: everything else, including the episode-end behaviour confirmed in 3.1.136, the unplayable-item rules, the Stop handling and shutdown.
- Tests: test_unplayable 67/67 (new: the close is sent even when the modal-dialog condition reports False, close comes before the window change, nothing sent when already full screen, diagnostic line carries the dialog id); the new cases fail on 3.1.136. All other suites unchanged and passing; 5000-step sim hash d161adb926caf8f1; test_collision 100/100.

## 3.1.136
service.py only (no new strings). Builds on 3.1.135. The developer chose "build on top" with diagnostics (reason: 3.1.135's full-screen step logged nothing on the 11:12 test, so the cause is not confirmed; this build records what Kodi is showing and tries a stronger fix). First retry of Fix A; if the restarted channel still plays behind the home screen, the log from this build will show why. Rule 11: do not stack a third fix; roll back to 3.1.134 if needed.
- Evidence (PC 10/31 11:12): 3.1.135 skipped the Bugs Bunny item and restarted the channel, but neither `restarted channel brought to full screen` nor any other full-screen line was logged, and the video played behind the home screen. The shutdown fix of 3.1.135 worked (no `script didn't stop in 5 seconds`).
- Diagnostics: new `_gui_state()` logs `window=<id> fullscreen_active=<bool> modal_dialog=<bool> playing=<bool> video=<bool>`. Logged: when the unplayable item is found (`unplayable item: ...`), when the restart returns (`fullscreen: restart done - ...`), and every change of state during the watch (`fullscreen: ...`; unchanged states are not repeated).
- Change: `_show_fullscreen_when_playing` no longer checks once. After playback begins it watches for 8 s (every 0.5 s). Whenever video is playing but the full-screen video window is not showing, it closes a modal dialog if one is up (`Dialog.Close(all,true)`) and opens the full-screen window, at most 3 times (log `restarted channel brought to full screen (attempt N)`). Stops at once if Kodi is closing. Audio is left alone. This also catches the suspected race where Kodi is full screen at first and drops to the home screen a moment later.
- Not changed: everything else, including the unplayable-item rules, the Stop handling, the shutdown cleanup and play-from-item.
- Tests: test_unplayable 61/61 (new: always-on-home gives 3 attempts, full screen then home is caught once, stays full screen sends nothing and logs once, modal dialog closed first, audio untouched, diagnostic lines logged); the new cases fail on 3.1.135. All other suites unchanged and passing; 5000-step sim hash d161adb926caf8f1; test_collision 100/100.

## 3.1.135
service.py, resources/lib/overlays/coming_up_next.py (no new strings). Builds on 3.1.134. Both items come from the developer's logs and test on 10/31 and are resilience fixes that change no existing behaviour (developer's standing instruction: add safe resilience fixes in the same revision).
- 3.1.134 confirmed on the PC (10/31 11:01): the Bugs Bunny Hour Opening failed to open while the draw was running, the Started and Stopped callbacks arrived inside the draw as before, the service did not freeze, the item was logged as UNPLAYABLE, popped, its single-file slot re-queued at the tail, and the channel restarted and played the next episode.
- Fix A, restarted channel behind the home screen. When the unplayable item stopped playback Kodi went back to the home menu; the channel restarted by the service then played behind it. After the restart the service now waits (up to 10 s) for video to begin and, if the full-screen video window is not showing, opens it (`ActivateWindow(fullscreenvideo)`; log `restarted channel brought to full screen`). Nothing is forced for audio, when already full screen, or when playback never began. The restart is also skipped when Kodi is closing.
- Fix B, Kodi waited 5 seconds and killed the service on close (log 11:04:12 -> 11:04:16: `waiting on thread`, `script didn't stop in 5 seconds - let's kill it`). Kodi waits for every Python thread of the service, daemon or not. The position poll is a `threading.Timer` that sleeps for the whole poll interval (default 60 s), so one was always pending while a channel played; nothing cancelled it when Kodi closed. New `SmartChannelsPlayer.shutdown()` (called when the tick loop ends) sets a closing flag, cancels the poll timer, the logo overlay timer and, via the new `coming_up_next.hide_overlay()`, the Coming Up Next timer; `_schedule_poll` does nothing once closing. The thread that was alive at 11:04 is not named in the log; the poll timer is the one that was certainly pending, so this is the most likely cause. If the "didn't stop in 5 seconds" line still appears when closing during playback, send the log.
- Not changed: everything else, including play-from-item, the unplayable-item rules and the 3.1.134 Stop handling.
- Tests: test_unplayable 54/54 (new: full-screen step in five situations, Kodi-closing restart guard, shutdown ends a pending poll timer thread, closes both overlays, survives an overlay error); the full-screen and shutdown cases fail on 3.1.134. All other suites unchanged and passing; 5000-step sim hash d161adb926caf8f1; test_collision 100/100.

## 3.1.134
service.py only (no new strings). Builds on 3.1.133 as a separate fix (a different bug, one fix per revision). Requested by the developer after 3.1.133 noted the risk.
- Problem: an ordinary Stop delivered while `onPlayBackEnded` is inside its replacement draw took `self._lock` on the callback thread. The draw holds that lock and waits in `xbmc.sleep`, which lets Kodi run the next callbacks on the same thread, so the Stop waited for a lock held further down its own stack and the service froze (same mechanism as the 3.1.133 fix; present in 3.1.131 and earlier; not yet seen in a log). Window: about 1.5 s at the end of an item.
- Now the stop path only TRIES the lock without waiting. When it is free (every case seen so far) the channel state is cleared inline and the channel lock released exactly as before. When it is busy the clearing is handed to a worker thread (`_finish_stop_when_free`) which waits for the draw to finish, then clears and releases the channel. A counter (`_play_seq`, raised in `onPlayBackStarted`) lets the worker see that a new playback began meanwhile; it then leaves the state alone. The resume point is saved at once in either case, as before. Log when deferred: `onPlayBackStopped: queue update in progress - stop finished on a worker thread`.
- The three lines that clear the state and release the lock moved into `_clear_channel_state` / `_release_stopped_channel` (same code, no copy left behind).
- Not changed: everything else, including the 3.1.133 unplayable-item handling.
- Known, not changed: `onPlayBackEnded` itself takes the lock for the draw; if a second Ended were delivered inside that draw (an item shorter than about 1.5 s) it would meet the same wait. Not seen in any log.
- Tests: test_unplayable 43/43 (new: user Stop with the lock free is inline and unchanged; with the lock busy it returns, saves the resume point, and the worker clears and frees the channel once the lock is released; a new playback in between is left alone); the three busy-lock cases fail on 3.1.133. All other suites unchanged and passing; 5000-step sim hash d161adb926caf8f1; test_collision 100/100.

## 3.1.133
service.py only (no new strings). Builds on 3.1.132. The developer chose "build on top" (reason: the root cause is confirmed from the log and only the implementation detail of 3.1.132 was wrong). First failed attempt on this bug; if 3.1.133 fails, roll back to 3.1.131 (project rule 11).
- Problem: with 3.1.132 the service froze when a missing file was reached right at the end of the previous episode (PC 10/31 10:27, Bugs Bunny Hour Opening in the Test Channel). The replacement draw in `onPlayBackEnded` waits in `xbmc.sleep`, which lets Kodi run the next callbacks (`onPlayBackStarted`, `onPlayBackStopped`) on the same thread while the draw still holds `self._lock`. The unplayable-item handler then took `self._lock` on that thread: it waited for a lock held further down its own stack. Nothing was logged after 10:27:16 and the carousel stopped. The 3.1.132 test missed it because it called the handlers one after another instead of nested.
- Now `onPlayBackStopped` hands a Stop that follows a start with no AV event to a worker thread (`_stopped_before_start`) and returns at once, so the draw can finish and release the lock. The worker waits for the lock, then runs `_handle_unplayable_open` as before; if the file is present it runs the ordinary stop handling. That handling is moved unchanged into `_process_user_stop`, which `onPlayBackStopped` still calls directly for every other stop.
- Not changed: everything else in 3.1.132 (play-from-item pop and replace, the unplayable-item rules and guards), the ordinary stop, block handling, carousel, state writes.
- Known, not changed here: an ordinary user Stop that arrives inside that same draw window takes the same lock on the callback thread and could freeze the same way (present since before 3.1.131; not seen in a log). Left for a separate revision.
- Tests: test_unplayable 35/35 (new: Stopped and Started delivered while the lock is held, file missing and file present; the Bugs Bunny single-file combo slot is skipped and re-queued at the tail); the deadlock cases fail on 3.1.132. All other suites unchanged and passing; 5000-step sim hash d161adb926caf8f1; test_collision 100/100.

## 3.1.132
service.py, channel_manager.py (no new strings). Builds on 3.1.131. The developer chose a new revision on top of 3.1.131 and restarted the week-long soak. Two changes, both from the 10/30 PC and Shield logs.
- Fix 1, "Play from this item" (side panel and standard list) rotated the queue: every item in front of the pick moved to the tail in its original order and nothing new was drawn. A show with episode 8 queued in front of the pick and episode 9 behind it ended up with 9 first and 8 last (Cloo! 10/30 23:53: Bones S11E09 before E08, Monk E16/E15, SVU E15/E14, Death in Paradise S10E02/S10E01). The Next button never did this; it pops and appends the next episode.
  - New public `ChannelManager.skip_items_with_replacement(channel_id, queue, count)`: pops the first `count` items, clears their resume points, appends one replacement per item (combo slot item: one item of its own slot; scheduled block item: no replacement, returned to the caller to count; everything else through `get_one_replacement`). This is the loop that was inside `service._handle_skip`, moved unchanged, so there is one copy.
  - `reorder_queue_from_item` now calls it: the picked item becomes the front, the passed items are gone and each is replaced at the tail. Passed block items are still counted toward their block. No rotation, so episodes cannot run out of order. The log line is `reorder_queue_from_item: channel=... skipped N item(s) to index N (R replacement(s), B block item(s)): titles`.
  - `service._handle_skip` calls the same helper; its behaviour and log lines are unchanged.
- Fix 2, an item that cannot be opened stopped the channel (PC 10/30 22:12, Shield 23:52: Bones S11E08, the file had been replaced by an upgraded one). Kodi reports this as onPlayBackStarted then onPlayBackStopped, with no onAVStarted and no onPlayBackError. The add-on treated it as a user stop: the channel was cleared, a stale position (about the end of the previous episode) was saved as a resume point, and the same item failed again on the next start.
  - `onPlayBackStarted` records the time and clears the AV flag (and the polled position, so a stale one is never saved against the wrong item); `_on_av_started_worker` sets the flag. `onPlayBackStopped`, when it follows a start with no AV event within 15 s and the stop was not programmatic, calls the new `_handle_unplayable_open`.
  - It looks at the front of the disk queue. Only when that file is absent (`xbmcvfs.exists` false; plugin:// and other non-file paths are never judged) is it treated as unplayable. Then: logged (`UNPLAYABLE item skipped: title show SxxEyy - file not found: path`), popped with its resume point, one replacement appended through `skip_items_with_replacement`, and the channel restarted from the corrected queue on a thread. A block item is counted toward its block.
  - Guards: if the next two queued files are missing as well, the share is assumed unreachable and nothing is skipped (logged); at most 5 items in a row are skipped before the channel is left stopped; a successful start resets the count. If the file is present, the stop is an ordinary user stop as before.
- Not changed: Next-button skipping, the end-of-item replacement, block handling (3.1.131), carousel, schedules, state writes.
- Tests: test_unplayable (new) 29/29; Part A fails on 3.1.131. All earlier suites unchanged and passing on 3.1.132; 5000-step sim hash d161adb926caf8f1; test_collision 100/100.

## 3.1.131
service.py only (no new strings). Builds on 3.1.130. The developer chose "build on top" of 3.1.130 (reason: the hole was understood and small). This is the second change for the lost-block bug; if 3.1.131 fails on hardware, roll back to 3.1.129 (project rule 11) rather than stacking a third fix.
- Problem: 3.1.130 raised `_block_reload_preparing` only inside the block branch of `onPlayBackEnded`, after the handler had already done about 0.9 s of earlier work (clearing the resume point, duration capture, watched reset). A Kodi AV event arriving in that early window was still counted as a user skip. Shown with a new test that fails on 3.1.130.
- Now `onPlayBackEnded` raises the flag first thing when a block is waiting for this channel (`_pending_block_channel` set), runs the handler body (moved unchanged into `_on_playback_ended`) inside `try/finally`, and always clears the flag when it returns, also on an error. The inner block branch still sets it (harmless) in case the block was queued after the first check.
- Not changed: skip detection when no block is waiting or after the handler returns, the 6 pm order of events, block counting, `_handle_skip`, everything else from 3.1.130.
- Known limit: an AV event that Kodi delivers before `onPlayBackEnded` has started at all is not covered; the logs so far show the end handler always running first.
- Tests: test_block_race 18/18 (new early-window, exception and flag-lifetime cases; the early-window case fails on 3.1.130); all other suites unchanged and passing; 5000-step sim hash d161adb926caf8f1.

## 3.1.130
service.py, channel_manager.py, utils/paths.py, router.py (no new strings). Builds on 3.1.129. The developer chose "build on top" after the PC log of 10/28-29 showed a lost block; the other four changes were added at his request in the same build.
- Fix A, scheduled block lost (PC log 10/28 19:01). When a block fires while its channel is playing, the service waits for the episode to end, replaces the finished episode on disk, then reloads the queue with the block in front. That replacement draw now waits about 1.2 s (the position check added in 3.1.125/126), so Kodi could start the next item of its OLD playlist before the reload was ready. `onAVStarted` read that as a user skip: `_handle_skip` counted the 3 block items as skipped, removed them from the queue and cleared the block, so the block never played. At 6 pm the reload was ready 10 ms before the event; at 7 pm it was 200 ms late.
  - Now `onPlayBackEnded` sets `_block_reload_preparing` while it prepares the reload (`try/finally`), and `_on_av_started_worker` does not treat a forward jump as a skip while it is set. If the restart then lands on the expected item, a leftover `_block_reload_pending` flag is cleared.
  - Not changed: skip detection at any other time (a skip while a block is merely waiting is still a skip), the 6 pm order of events, block counting, `_handle_skip`.
- Fix B, leftover channel lock files. `release_channel_lock` deleted only the lock on the share; `save_json` had written it through a same-named working copy in the local folder, which stayed for ever (the 10/18 files). A device closed or killed without releasing also left its share file.
  - `release_channel_lock` now also removes the local working copy (`remove_local_copy`). New `ChannelManager.remove_stale_channel_locks()` removes lock files (local folder and share, listed by the new `paths.channel_lock_files()`) of channels that no longer exist, and locks not refreshed for an hour (`LOCK_SWEEP_SECONDS`; the live-lock limit stays 180 s, so clock differences cannot remove a running lock). Left alone: the lock this device holds, `channel_lock_owned.json`, an unreadable file of an existing channel, and everything when no channel was loaded or channels.json was unreadable. Run by the service at start-up and every 6 hours. Log: `removed leftover channel lock <name>`, `removed N leftover channel lock file(s)`.
- Fix C, Backup now includes `songs_cache.json` (it was missing from the file list). Restore already restores whatever the zip holds.
- Fix D, Backup copy. A copy to the backup share that is refused (PC 10/29 04:46: two refused, then the next worked) is now tried up to three times with a pause; a partly written zip is removed before each try and after the last. Each failed try logs `backup: copy attempt N of 3 failed (backup folder reachable: ...)`.
- Fix E, removing the last interleave from a TV channel. `queue_size` counts interleaved items, so a queue of 10 woven with 6 combo items held 4 episodes; removal kept those 4 (PC 10/28 17:13). `_regenerate_queue_body` now rebuilds a TV (non-serial) channel from the head of its queue to the full size, through the same `_rewind_tv_cursor` / `_regenerate_tv_interleave` path the interleave-on rebuild uses (`apply_interleave_list` returns the items unchanged when no source is left). Movie and Folder channels keep their primary items as before.
- Not included: the Classic Sci-Fi TV loop on Shield .13 (19:04, `no ep for show_id=2166 ... aborting pop`, repeated about once a minute). The Monsters `.nfo` files exist on the share, so the .13's existence check failed for another reason that the log does not show; a back-off would only hide that. Needs a log from the .13 after checking file access.
- Tests (sim/, copied to the project): test_block_race (new) 11/11, 4 fail on 3.1.129; test_lock_sweep (new) 14/14; test_backup_130 (new) 9/9; test_interleave_remove (new) 2006/2006 over 200 random channels, fails on 3.1.129 (queue below queue_size); all earlier tests pass unchanged; the 5000-step sim and the 300-trial edit sequence give the same results and the same hash (d161adb926caf8f1) as 3.1.129.

## 3.1.129
router.py, utils/paths.py, strings.po (one string text changed, #32384), addon.xml, LICENSE.txt (new). Builds on 3.1.128.
- Problem: Delete All Addon Data deleted only channels, state, library cache, now-playing and the queue files. It left schedules.json (so schedules for channels that no longer existed stayed), the saved copies of the state (state.bak*, state.day*), kept positions (cursor_kept_*), channel locks, the song cache and local working copies of shared files.
- Now: `paths.is_data_file(name)` is the one definition of what the add-on writes (the fixed names already listed in `_SHARED_DATA_FILES` plus `queue_*`, `cursor_kept_*`, `state.bak*`, `state.day*`, `channel_lock_*` .json, and their .tmp copies). `delete_all_data` removes every such file from the local folder and the shared folder. Kept: this device's id (`device_id.json`) and settings. The confirmation text (#32384) now lists schedules, saved copies of the state and caches.
- addon.xml for the Kodi repository: `xbmc.python` 3.0.1 (Omega), `<source>` and `<website>` (https://github.com/mwkurt/plugin.video.smartchannels), `<news>` shortened to the latest builds (707 characters, limit 1500). LICENSE.txt added (GNU GPL version 2, matching `<license>GPL-2.0-only</license>`). Not added: `<reuselanguageinvoker>` (the add-on needs a fresh interpreter per call), forum, email.
- USER_MANUAL.md brought up to date (it had stopped at 3.1.118): version 3.1.129; Resume (automatic removal of stale points); Single File slot; Delete All Addon Data; overwritten-position repair and local copy cleanup (shared folder); Backup contents and log line; troubleshooting rows for the Edit Channel 'could not be read / saved' messages and a backup that does not finish.
- Not changed: Backup, Restore, Delete Channel, everything else.
- Tests: test_delete_all (new) 8/8; all earlier tests and 5000-step hashes unchanged.

## 3.1.128
scheduler.py, service.py (no new functions, no new strings). Builds on 3.1.127.
- Problem: the service counts each finished scheduled-block item toward its block, and ignores a count when the same (schedule, file) was counted just before (so an item reported by both the natural end and the skip handler counts once). A block whose items are the same file back to back, for example a Combo Block with a single-file slot (3.1.126) or a one-file Folder slot, was therefore counted once; the block's `active_block` never reached its item count and stayed active (a waiting block stops later schedules for that channel).
- Now: `fire_block` stamps each block item with `_block_seq`, its place in the block (combo and queue source paths), and the dedupe identity is (schedule, file, `_block_seq`). The same item reported twice still counts once; the same file as two different items counts twice. A block fired before this build has no `_block_seq` and is matched by file as before.
- Not changed: how block items are popped, skipped or replaced; the count for blocks of different files.
- Known limit: Skip detection finds the playing item by file, so skipping by two or more items straight onto a second copy of the same file (single-file slot) is handled as a one-item skip. Normal playback is not affected.
- Tests: test_block_count (new) 7/7 (2 fail on 3.1.127); everything else unchanged from 3.1.127, same 5000-step hashes.

## 3.1.127
channel_manager.py, service.py (new functions, no new strings). Builds on 3.1.126.
- Problem: Real Crime kept a resume point (The Murder Tapes S01E01, 30.96 s) from before 10/24 although the episode had left the queue. A resume point is cleared when its episode finishes (`onPlayBackEnded`), is skipped (`_handle_skip`), is popped by the carousel, or when the channel is reset or a key setting changes. An episode can also leave the queue another way: Set Start replaces a show's queued episodes and never cleared their points (a confirmed gap); a lost update on the shared state.json can bring a cleared point back; a stop on one device after another popped the item saves a point for an item no longer queued. Nothing removed such a point, and resume keys are exempt from the clean-up that removes keys of deleted channels. The exact path of the Real Crime point could not be established from the logs available.
- Now: `ChannelManager.remove_stale_resume_points(only_channel=None)` removes resume points whose episode is not in the channel's queue, and points of channels that no longer exist. Run by the service at start-up and every 6 hours, and by `set_show_start` for its channel right after the queue is spliced. Log lines: `removed stale resume point <key>` per key, `removed N stale resume point(s)` from the service.
- Safe-guards: a channel whose queue cannot be read or is empty is left alone; nothing is done when channels.json could not be read or no channel was loaded; the old `resume:<channel>:file:<md5>` keys are not touched; a point for an episode that is still queued (including the one playing) is never removed.
- Not changed: how resume points are saved and cleared when an episode ends, is skipped or popped; Edit Channel's own clearing; Reset Channel.
- Tests: test_stale_resume (new) 21/21 (fails on 3.1.126: no such function); everything else unchanged from 3.1.126 (same results, same 5000-step hashes).

## 3.1.126
channels/combo.py, channels/folder.py, ui/wizards/combo.py, ui/dialogs.py, ui/channels.py, router.py, strings.po (4 new strings, #32953-#32956). Builds on 3.1.125. Two additions at the developer's request, in one build; they do not touch each other.
- Addition 1, Combo Block "Single File" slot. A slot can now be one media file instead of a TV show, movie pool or folder, so a clip outside the library (an ident, a bumper, a short film) plays in its place in the block without needing a folder of its own.
  - Slot wizard: Source type gains **Single File** (#32953). It opens the file browser (#32954); a file on a local drive letter gets the same warning as a folder (#32956: other devices cannot open it); a file that does not exist is refused (#32955). Then the usual Silent question. No random / recycle / count questions: the file plays once per cycle.
  - `ComboQueueBuilder._fetch_file_items` returns the slot's file once per requested item, through the new public `FolderQueueBuilder.item_for_file` (same item format, folder default duration and missing-duration record as a Folder slot). The file may be queued more than once at the same time; that is the intent. Scheduled blocks (`build_unit`) and the 1-for-1 replacement (`build_one_slot`) use the same path.
  - The slot menu and channel details show the file name. Slot state key: `combo:<id>:slot:<slot>` (the played-file record the service already writes for folder items); removed with the channel.
  - Not changed: TV, Movie and Folder slots, the queue layout of a block, silent items, existing combo channels.
- Addition 2, Backup includes `schedules.json`. Backup listed only channels, state, library, now-playing and queue files, so schedules were lost with a restore. Restore already restores every file found in the zip. New log line: `backup: N file(s) copied to <zip>` (or `NOT copied`), so a failed backup shows in the log.
- Not changed: Delete All Data still leaves schedules.json (separate item, not part of this build).
- Tests: test_file_slot (new) 19/19; test_backup_schedules (new) 6/6 (5/6 on 3.1.125, the missing file); everything from 3.1.125 unchanged: test_local_copies 19/19, test_missing_position 39/39, test_carousel_guard 19/19, test_places_kept 22/22, test_consumed_guard 27/27, test_edit_sequence 0 violations, 5000-step simulations same hashes, test_collision same as 3.1.125.

## 3.1.125
channel_manager.py, utils/paths.py, router.py, service.py (new functions, no new strings). Builds on 3.1.124. Two fixes in one build at the developer's request; they do not touch each other, and each has its own test cases.
- Fix 1, lost position. Found 10/28: First Wave and Unforgotten were each one position behind their queue after a night with three devices. state.json is read whole, changed and written whole, with no lock between devices. When device B reads it before device A saves a new position and writes it after, B's copy replaces A's save with the old position and nothing is logged. The queue file is a separate file and keeps the new episode, so the position falls one behind. (3.1.124 stops this from becoming a repeat, so no episode played twice, but the position is wrong until the next draw.)
  - Now: `set_cursor(channel_id, cursor, verify=False)`. The per-episode draws (1-for-1 replacement: `_replacement_tv`, `_replacement_serial`, `_replacement_tv_next_show`; carousel pop: `get_carousel_replacement`) pass `verify=True`. After saving, `_verify_cursor_saved` waits 1.2 s and reads state.json again, up to 3 times. For each show whose position this save changed, if the file shows the OLD value again it writes ours once more. A value that is neither old nor ours is another change and is left alone. Log line when it acts (warning): `cursor of <channel> was overwritten by another device - N position(s) written again`.
  - Not changed: Edit Channel, queue builds, set_show_start, interleave regeneration, repair (they save without verifying, so no waiting inside loops); scheduled-block pops; combo pops; the 3.1.124 guard.
  - Known limit: the check only covers the 3.6 s after the save. In simulation (4 saves by a third device, 1200 trials) one loss in 1200 remained, against 234 in 1200 on 3.1.124. The 3.1.124 guard still stops that remainder from repeating an episode.
- Fix 2, leftover local queue files. A queue file on the shared folder is written through a copy of the same name in the local add-on folder, and the copy was never removed. Deleting a channel removed the shared file only, so its copy stayed in the profile folder (three on the PC, found 10/27), and Backup, which lists both folders, put them in the zip.
  - Now: `utils/paths.remove_local_copy(filename)` and `local_queue_files()` (both do nothing when shared storage is not in use). `delete_channel` removes the local copy (and .tmp) of the deleted channel's queue. `ChannelManager.remove_orphan_local_queues()` runs once at service start and removes local `queue_*.json` copies of channels that are not in channels.json; it does nothing when no channel was loaded or channels.json was unreadable. `known_queue_filenames()` is new. Backup only includes queue files of channels that exist. Log line per file: `removed leftover local queue file queue_<id>.json`.
  - Not changed: the shared folder, queue files of existing channels, local state.json/channels.json copies.
- Tests: test_collision 600 trials x 2 seeds, 4 outside saves: 3.1.124 111 and 123 silent losses, 3.1.125 1 and 0; with no outside saves 300/300 ok. test_local_copies (new) 19/19. test_missing_position 39/39, test_carousel_guard 19/19, test_places_kept 22/22, test_consumed_guard 27/27, test_edit_sequence 12000 replacements 0 violations, test_stale_state same output as 3.1.124; 5000-step simulations (seeds 1, 2) give the same queues and positions as 3.1.124 (hashes d161adb926caf8f1 and 09f6f6a555d4ef87).

## 3.1.124
channel_manager.py and carousel.py (no new functions, no new strings). Builds on 3.1.123.
- Problem: a carousel pop that finds the show's saved position one behind the queue draws the episode it has just popped again. Seen 10/26 on 00's Classic TV: Grounded for Life and Without Motive each played S01E03 twice (the position was 2 while the queue held index 2, one behind since before 10/24). The carousel's own "already in queue" check cannot see it, because the popped episode has already left the queue. The TV 1-for-1 replacement has had the right guard since 3.1.120/121; the carousel draw did not use it.
- Now: `get_carousel_replacement(channel_id, popped_show_id, queue=None, consumed_id=None)` passes the queue (popped item already removed) and the popped episode's id to the same draw the 1-for-1 replacement uses, so an episode already queued or just popped is skipped and the position catches up. The 3.1.123 rule for a show with no saved position also applies to carousel draws now. `carousel._apply_replacement` passes `queue` and the popped item's `episodeid` on both calls. Log line when it acts: `_next_candidate_ep: show <id> - N episode(s) already queued skipped` (it now also tells which carousel pops met a position that was behind).
- Not changed: a carousel draw with correct positions (identical queues and positions to 3.1.123 in 3000-pop and 5000-step runs), scheduled-block pops, combo slot pops, interleaved pops, movie carousels, the 1-for-1 replacement, Edit Channel.
- Known limits: random shows in a carousel now avoid queued/just-popped episodes like the 1-for-1 replacement does. If every episode of a show is queued or just popped (a one- or two-episode show) the draw repeats, as before.
- Tests: test_carousel_guard 19 checks (4 fail on 3.1.123: popped episode drawn again with the position one behind, two behind, and missing); test_missing_position 39/39, test_places_kept 22/22, test_consumed_guard 27/27, test_edit_sequence 16000 replacements 0 violations; sim 5000-step runs equal 3.1.123 (same hashes).

## 3.1.123
channel_manager.py only (no new functions, no new strings). Builds on 3.1.122 (one build-on-top: the cause is confirmed, 3.1.122 did not cover these two gaps).
- Problem (1): a show that is in the queue but has no saved position starts again at its first episode the next time one of its episodes is replaced. Found 10/25 on Dawn's Favs: the saved positions had been lost, and an Edit Channel that re-picked starting episodes for two shows and kept the other two ("Keep the current starting position") wrote positions only for the two picked shows. The first replacement for Midsomer Murders queued S01E01.
- Problem (2): when a channel has no saved cursor, `get_cursor` returned a blank cursor whose position lists were shared by every caller in the same running process. A position written for one channel could appear in the blank cursor of another channel without a cursor. Present in 3.1.121 and 3.1.122.
- Now (1) `_next_candidate_ep` (sequential shows, TV 1-for-1 replacement only): with no saved position, the show continues after its last episode that is in the queue (or was just consumed); with none of those it starts at its first episode as before. Log line: `_next_candidate_ep: show <id> - no saved position, continuing after its last queued episode (index N)`.
- Now (2) `get_cursor` returns an independent copy of the blank cursor.
- Not changed: a show that has a saved position, carousel draws (no queued_ids), random shows, every other path; the 3.1.120/121 queue guards; the 3.1.122 fixes; Edit Channel and its dialogs.
- Known limits: carousel channels are still unprotected (open item 3). If a show with no position had wrapped past its last episode inside the queue, the continuation is taken from the highest-numbered queued episode.
- Tests: test_missing_position 39 checks (8 fail on 3.1.122); test_places_kept 22/22, test_consumed_guard 27/27 unchanged; two 5000-step simulations give the same queues and positions as 3.1.122 (hash equal), 0 violations.

## 3.1.122
channel_manager.py, scheduler.py, player.py, ui/channels.py, strings.po (one new string, #32952). Builds on 3.1.121 (one revision for every condition found in the 10/24 audit; if it fails, roll back to 3.1.121 and apply them one at a time).
- Problem: a shared file that is missing or unreadable for a moment was taken as an empty one, and a rebuild always started every show at its first episode. Found by reading every place that reads or writes positions, then reproduced with a 5000-step simulation of the real code. Cases: (1) state.json missing when a replacement reads it: the show draws from episode 1 and the save replaces the channel's positions with that one show (the Dawn's Favs signature). (2) Edit Channel notes where each show is up to from the queue file; if that read fails, every show restarts. (3) Starting a channel whose queue file looks missing builds a new queue from episode 1 over the real one. (4) A schedule block that cannot read the source queue rebuilt the source channel from episode 1; one that could not read the target queue replaced it with only the block items. (5) The interleave wizard rebuilt a channel from episode 1 when its queue could not be read. (6) Every save wrote the manager's whole old copy of state.json, so a save made while a replacement was running (the carousel clock saves every minute) put other channels' positions back (repeats; the Bones/Monk/Psych pattern). (7) A position past the end of a briefly short episode list wrapped to episode 1.
- Now (1) state.json missing while channels exist counts as unreadable (looked for again after 0.3 s and 1 s; log `... is missing - treated as unreadable`): nothing is drawn or saved from an empty stand-in. If it stays missing for 2 minutes it is taken as gone. A first start with no channels is unchanged.
- Now (2) Edit Channel reads the queue strictly before it saves anything. Unreadable: nothing is changed or saved, Edit Channel shows the new message #32952 (`edit_blocked(channel_id)`, new, public). The same strict read protects `set_show_start` (Select Starting Episodes / Reset Show: returns False, nothing changed), the interleave wizard rebuild (`regenerate_queue`: nothing rebuilt), `repair_missing_shows` (never writes back an empty queue) and a schedule firing (source and target queue; not fired, tried again next tick).
- Now (3) a queue that has to be rebuilt although the channel has been playing continues each show from its saved position instead of its starting episode: new `keep_places` argument of `build_channel_queue`, used by player.start_channel, the schedule's source rebuild, the interleave wizard's rebuild of a missing queue, and Edit Channel when the queue file looks missing. First builds, Reset and an Edit that changes the show list are unchanged (they start from the channel's starting episodes or from the positions captured from the queue, as before).
- Now (4) `_save_state` writes only the keys this manager changed since it last read or wrote state.json; other channels' positions on disk are left alone. If the file is gone at that moment the manager writes everything it holds, as before. It now reports a failed write (it always returned True before), and keys deleted by this manager are forgotten once the delete is saved, so a later write of the same key by another device is no longer removed.
- Now (5) before a position past the end of a show's episode list wraps to episode 1, the list is fetched once more (0.5 s wait); the show wraps only if it is still that short.
- Logging: `POSITION DROP: channel <id8> - N show(s) went back: <show>: <was> -> <now> - saved by <device> via <functions>` whenever a save lowers or removes a show's position (it also appears for a normal wrap, Reset Show and some edits). The soak checker reads it.
- Not changed: how a replacement is chosen, popped and appended (played and skipped items alike), the 3.1.120/3.1.121 queue guards, the carousel, combo, serial, random, movie, folder, audio and party code, service.py, resets (a reset still starts over), the 3.1.111 refusal to save over an unreadable file.
- Known limits: (1) positions are still numbers into the live episode list; a library that gains or loses episodes in the middle of a show moves the place. Only the 1-for-1 replacement re-checks a short list (builds wrap as before). (2) A queue rebuilt because it looked missing continues after the old queue's tail: the old queue's unplayed episodes (up to the queue size) are not played. (3) The interleave wizard shows "queue rebuilt" even when it skipped the rebuild because the queue was unreadable; run it again. (4) Edit Channel is refused for TV channels only, and only when the edit contains a show list (all wizard edits do; an icon change does not). (5) Two devices saving the same channel's positions in the same instant still keep the later one (one device plays a channel at a time). (6) This does not repair positions that are already wrong (for example Dawn's Favs).
- Tests: test_places_kept, 22 checks (each fault above; the same file on 3.1.121 fails 5 of them); test_consumed_guard 27/27 unchanged; 5000-step simulations (3 channels, round-robin, natural ends, skips, edits): normal play gives the same queues and the same positions as 3.1.121 for 5 seeds; with every fault switched on 3.1.121 shows 300+ repeats, restarts and jumps and 3.1.122 shows none, for 3 seeds. The earlier suites (test_queue_agree, test_write_guard, sim_state_protect and the rest) were not available and were not re-run.

## 3.1.121
channel_manager.py (one block in `_next_candidate_ep`). Builds on 3.1.120 (one build-on-top; root cause unchanged).
- Problem: after 3.1.120 the Cloo! soak (10/24, Shield .10) showed one remaining repeat. Bones' saved position was 216 while the queue held E05 (216) and E06 (217). When E05 finished, the replacement was handed the queue with E05 already removed, so the 3.1.120 check ("is the next episode already waiting in the queue?") found nothing queued at 216, drew E05 again and moved the position only to 217. The log had no `already queued skipped` line for Bones; the other eight shows with a position one behind the queue were handled correctly (+2, correct next episode). The 3.1.120 check could only see a position that pointed at an episode still waiting, not at the episode that had just finished.
- Now: for a sequential show, the episode that was just consumed counts as used as well. A position pointing at it (or at it followed by the queued episode) moves on to the show's next unqueued episode and the saved position catches up. Bones' next replacement draws E07 and the position becomes 219 instead of repeating E06.
- Logging only: the `show <id> - N episode(s) already queued skipped` line is now written only when a different episode was drawn, so a show with so few episodes that a repeat is unavoidable (one or two episodes with recycle on) is not logged on every replacement.
- Not changed: only the TV 1-for-1 replacement (`_replacement_tv`) passes the queue and the consumed episode, so carousel, serial, random, combo, interleave and rebuild draws are untouched; random shows still avoid queued and consumed episodes as before; the skip handler (the skipped item is still in the queue it passes, so it was already covered); the 3.1.120 rebuild refusal; service.py, player.py, all other files; no new strings.
- Known limits: (1) an episode that is already queued stays queued. Bones' repeat of E05 already at the end of the Cloo! queue plays once more and then the show is back in order (or remove and re-add Bones in Edit Channel). (2) A position that points at an episode played long ago (positions lost or reset) is not caught; the 3.1.118 CURSOR SHRINK log is the only check there. (3) With recycle off, a position stuck on the consumed last episode still draws it once. (4) The cause of the Bones and Monk positions being short after the 10/22 17:19 starting-episode edit is still unproven.
- Tests: new test_consumed_guard, 27 checks: the Bones case (position on the finished episode, queue with the next one) now draws the following episode and the position catches up; the same case run on 3.1.120 fails 7 of the 27 checks (it reproduces the repeat and the position 217); position one behind the queue (3.1.120 case) unchanged; normal play unchanged; skip path unchanged; one- and two-episode shows with recycle alternate correctly with no log noise; three-episode wrap; wrap with a stale position; draws that pass no queue (carousel and others) unchanged; random shows still avoid queued and consumed; recycle off at the end of a show draws nothing. The earlier suites (test_queue_agree, test_write_guard, sim_state_protect, test_state_guard and the rest) were not available in this session and were not re-run; the change touches none of the code they cover.

## 3.1.120
channel_manager.py, ui/channels.py, strings.po. Builds on 3.1.119.
- Problem: on 10/21 at 20:17 Cloo! was edited while the shared state.json was damaged. Every save was (correctly) refused, but the rebuild carried on: the new queue was written (78 items, two episodes of each of 39 shows) while the new positions were not saved. The positions on disk still counted one queued episode per show. Each 1-for-1 replacement draws "the next episode after the saved position", which was already in the queue, so it drew a repeat: 12 of 12 replacements so far, and the other 27 shows would have followed. The replacement code itself is unchanged since 3.1.102; the gap was in the rebuild, opened when 3.1.111 made saves refuse to write over an unreadable file and the rebuild was not told.
- Now (1) the queue and the positions agree: `set_cursor` returns True/False; `_build_fresh_tv_queue` hands back no queue when the positions could not be saved (log: `positions for '<name>' could not be saved - queue not rebuilt, old queue and positions kept`). The old queue and old positions stay as a matching pair and nothing is written. `rebuild_failed(channel_id)` (new, public) reports it; Edit Channel (ui/channels.py) then shows a message instead of "channel updated" (new string #32951). The flag clears at the start of the next rebuild.
- Now (2) a safety net: when a sequential show's next episode is already waiting in the queue, the replacement skips to the show's next episode and the saved position catches up (log: `show <id> - N episode(s) already queued skipped`). Only the TV 1-for-1 replacement passes the queue to the pick, so carousel, serial, random and combo draws are unchanged. If every episode of a show is queued the first one found is used, as before.
- Not changed: how a normal rebuild or replacement works, resets (a reset is meant to start over), the 3.1.111 refusal to save over an unreadable file, queue writing elsewhere, service.py, player.py.
- Known limit: other channel types (movies, folder) keep their own state with the same kind of write; they are not changed here.
- Tests: new test_queue_agree, 23 checks (normal rebuild unchanged and consistent, rebuild refused with an unreadable state.json and old queue/positions still agree, flag set and cleared, mismatch like Cloo!'s heals itself with no repeats, all-queued / wrap / span-2 / random / no-queue-info cases). All earlier suites pass; pyflakes clean.
- One-time cleanup for Cloo!'s 12 queued repeats: `remove_repeats.py` (separate download, not part of the add-on).

## 3.1.119
utils/paths.py, channel_manager.py. Builds on 3.1.118 (no change to service.py, player.py, carousel.py, scheduler.py, the 1-for-1 replacement or pop logic, or queue building).
- Problem: on 10/21 at about 20:14 a burst of 300+ skipped items (episodes with no duration) each rewrote state.json on the shared folder. One of those writes ran into a busy delete on the share ("Device or resource busy") and left the new content followed by a tail of the old file. The file was valid JSON plus junk, so every device read it as damaged (since 3.1.111, correctly refusing to save over it) and nothing was saved - resume points, positions - until the file was repaired by hand.
- Now (1) verify after write: a `.json` file copied to a shared folder is read back; if it is not complete valid JSON it is deleted and copied again (`paths._verify_shared_write`, `_reads_back`). The read-back is done twice, 150 ms apart, so another device replacing the file at that moment is not mistaken for a bad write. A write that still does not read back counts as failed and goes through the existing 3-attempt retry. Local (non-shared) files are not read back. Cost: one extra read of the file per save to a share.
- Now (2) leftover text: a JSON file that is a complete object followed by leftover text ("Extra data") is read as that object (`paths._parse_json_text`) and logged once per file and length: `<path> has N characters of leftover text after valid JSON - ignored; the next save rewrites the file`. Empty, half-written or non-JSON files still raise and are retried as before, so the 3.1.111 refusal to save over an unreadable file is unchanged.
- Now (3) batched skip records: `record_missing_duration` records each file once per Kodi session and writes in batches: at once when nothing was written in the last 15 seconds (a single skip is not delayed), otherwise when 50 are waiting or by a timer 15 seconds later. One state.json save covers every channel's list and one rewrite of missing_durations.txt covers every line (was one of each per skipped item). If state.json cannot be saved at that moment the entries are kept and written by the next flush. The 200-entry list cap is unchanged; it no longer defeats the once-per-file check.
- New: `ChannelManager.flush_missing_durations` (public), `_flush_missing_later`; `_save_state` now returns True/False (callers that ignore it are unchanged). No new strings.
- Not changed: positions, merging, pruning, the 3.1.118 cursor guard and daily copies, queues, playback, schedules, carousels.
- Known limit: skipped-item records still waiting when Kodi exits are not written (at most 15 seconds' worth); the item is skipped again and recorded on the next start.
- Tests: new test_write_guard (29 checks: bad write repaired by delete and copy, leftover text read and logged once, empty/half-written files still refused, no read-back for local files, two-device replacement during read-back not repaired, 320-skip burst writes at most 8 state.json copies, timer tail, same files again write nothing, cursor and resume survive a batch, entries kept when state.json is unreadable and saved later). sim_state_protect (34/34) now resets the new class-level batching state between cases. All other suites unchanged and passing; pyflakes clean.

## 3.1.118
channel_manager.py, USER_MANUAL.md. Builds on 3.1.117.
- Problem: the 3.1.111 protection stops a channel's positions being lost when state.json cannot be read, and keeps about 24 hours of copies. It does not help when positions are lost some other way, or when the loss is noticed after a day. The Cloo! channel lost the positions of 33 of its 38 shows between 10/14 21:13 and 10/15 04:43 (before 3.1.111); nothing recorded what did it, and the only copy that still held them was an old state.json that happened to be saved by hand.
- Now (1): a daily copy. The first clean save of each day writes `state.day<N>.json` on the shared folder, N cycling through 14 days, so the last 14 days of state exist, one per day. An empty state is never copied. The 3-hour `state.bak` copies are unchanged.
- Now (2): a cursor shrink is recorded. When a save replaces a channel's cursor with one that has half or fewer of its shows (channels of 4 or more shows), or half or fewer of its total positions (when the total was 20 or more), the log gets a `CURSOR SHRINK` warning naming the channel, the old and new sizes and the device that saved it, and the cursor that was replaced is appended to `cursor_kept_<channel id first 8>.json` (the last 5 are kept) with the device and time. The save is not blocked: a reset or edit that clears the cursor removes the key first and is not compared, and one show wrapping round (recycle) is far below the limit. Reported once per change; if the kept file cannot be read it is left alone.
- New: `ChannelManager._guard_cursors`, `_cursor_size`; `_backup_state` writes the daily copy. No new public methods, no change outside channel_manager.py (and the manual's backup paragraph). No strings.
- Not changed: how positions are saved, merged or pruned; queues; playback; the 3.1.111 protections.
- Known limit: the day's copy is written by the first clean save of each day in each running add-on; if that save happens after a loss the same day, that day's copy holds the loss (the previous day's does not).
- Test: test_state_guard, 21 checks: shrink logged and kept, save not blocked, silent on forward play, one show recycling, tiny cursors and a deliberate reset, a stale or empty cursor from another device reported with its device, kept file limited to 5 and left alone when unreadable, daily copy once per day, 14 files at most, empty state never copied, 3-hour copies unchanged. All earlier suites unchanged; pyflakes clean.

## 3.1.117
channel_manager.py, carousel.py. Builds on 3.1.116 (no change to the schedule rules).
- Problem: with two or more devices on the same shared folder, two devices could find the same carousel pop due in the same moment and both pop it. Found in the 3.1.116 logs: 17 items on the Test Target Channel were popped by two devices 1 to 7 seconds apart (for example 'Mouse in Manhattan' at 23:53, 'Freeway Patrol' at 02:35, 'Hare-abian Nights' at 13:54). Both devices removed the same front item and each drew its own replacement episode; the later queue write won, so the other device's replacement was lost while the show's position had moved on. No queue was ever the wrong size (the queue stayed at 56) and no block count went wrong, but an episode of an ordered show could be skipped. The check meant to stop this ("another client popped") read the device's in-memory copy of the state, so it never saw a pop made by another device, and it never fired in any log.
- Now: before a pop the device claims it on the shared file (`ChannelManager.claim_carousel_pop`, new public method): it reads the shared state, refuses if the carousel clock has already reached the value this pop would set or if another device holds a live claim for it (2 minutes), writes its claim, waits 1.5 s, reads the file back and pops only if its claim stands. The device that loses leaves the pop; the next check finds the clock moved on, or pops later. A pop may come a little late, never twice. If the shared state cannot be read, no pop is made that minute.
- The old in-memory check in `_do_pops` is replaced by the claim (no duplicate guard left). One claim covers all the pops of one check.
- Logged: `carousel claim: channel <id> won by <device>`, `refused on <device> - <other device> is popping it`, `lost on <device> - <other device> claimed it in the same moment`, `already popped for this interval`.
- Cost: about 1.5 s extra per pop that is actually due (not on every minute check), on every device including single-device setups.
- Carousel state gains a `pop_claim` entry (device, name, clock value, time, token) in the channel's `:carousel` record; older records without it work as before.
- Not changed: when a pop is due, replacement rules, block pops, schedules, the 3.1.113 hold while playing. No new strings.
- Tests: new test_carousel_claim (23 checks, two devices over one shared folder): single device wins; already popped is refused and nothing is written; a live claim of the other device refuses; a stale claim and a claim for an earlier pop do not block; an overwrite during the wait loses; unreadable state does not pop; the in-memory state is refreshed from the file; empty carousel state; end to end through `_do_pops` with two devices (one pop, one replacement, the second device refused, then no second pop). All earlier tests pass (test_carousel_hold 6/6 included).

## 3.1.116
scheduler.py, channel_manager.py, carousel.py. Logging only - no change in behaviour. Builds on 3.1.115.
- Why: on 10/20 a Shield fired the 06:00 and 11:30 schedules and popped some of the block items while the PC fired 08:00 and popped the rest. Each device's log showed only its own part, so the PC log alone had missing fire lines and missing counts, and the queue file was needed to see which shows a block held.
- Now every line that matters names the device: `(device SHIELD #a1b2)` (friendly name plus the first four characters of the device ID) on `all checks passed, firing block`, `block fired`, `block item complete`, `block complete`, and on each carousel `popping item` line.
- New: the claim result is logged once per schedule and day: `won by <device>`, `refused - already claimed by <device> Ns ago`, or `lost - <device> claimed it in the same moment`. The claim now stores the device name.
- New: a schedule that is due but not fired says why, once per day: waiting because the target channel is being played on another device, because the target queue cannot be read, or because the channel has no queue yet; not firing because another device holds the claim; or `already fired today by <device>` (the fire now records `last_fired_by` in the schedule). A fire that is not recorded logs that the claim was released.
- New: when a block fires, one line per item: `item 3/10: '<title>' - <show or folder item> (slot <id>, <seconds>s)`. This shows which show each Combo Block slot drew, so Taking turns can be checked from the log without the queue file.
- Added `ChannelManager.get_device_label()` (public). No new strings (log text only). Schedule records gain `last_fired_by` and `fire_claim.device_name`; older records without them work as before.
- Not changed: when and where schedules fire, the claim rule, the carousel rules, any queue content.

## 3.1.115
scheduler.py, channel_manager.py, service.py (docstring only), USER_MANUAL.md. Builds on 3.1.113. Build 3.1.114 (30-minute late window) was withdrawn before release and is not part of this line.
- Problem: on 10/18 Kodi was off at 00:30 and 02:30. When the Test Target Channel was played at 08:17 both blocks fired within 3 seconds, the 08:30 block followed at 08:34, and leftovers of the 10/17 18:30 block were still queued: four blocks stacked in one queue. The block counts then went wrong (`sch_abc536d8` counted 3 of 6 before any of its items played). The cause of that miscount is still not confirmed; this change removes the stacking that preceded it.
- New rule - one block at a time per channel. The queue file decides: while ANY item tagged with a schedule id is still in the target channel's queue, every other schedule for that channel is skipped for the day (it counts as that day's fire: `last_fired` and a new `last_skipped` are set, logged once as `skipped today - an earlier scheduled block is still in the queue`). A repeating schedule tries again on its next day. A once-only schedule is switched off (it stays in the list, inactive). The block items sit in the queue untouched until watched, skipped by the user, or - on a carousel channel that is not playing - popped by the carousel (no replacement), after which the next schedule can fire.
- New rule - priority. Schedules due together are taken earliest start time first. After a Kodi-off period the earliest missed schedule fires and the rest are skipped.
- Changed (reverses the 3.1.103 rule) - who fires. The device playing the target channel fires it, as before. When no device is playing it, any running device on the same shared folder may fire it, so the block is ready on time without anyone watching. A device never fires a channel another device is playing (the 3.1.109 channel lock decides). A block that fires while the add-on starts up is subject to the carousel's start-up catch-up on a carousel channel, as agreed.
- New - each schedule fires once. Before building a block the device claims the schedule (`ChannelManager.claim_schedule_fire`): it writes a claim into the schedule record, waits 1.5 s, reads it back, and fires only if its claim stands; a live claim of another device for today (5 minutes) refuses. `last_fired` then keeps every device off for the day. A fire that fails releases its claim (`release_schedule_claim`). Shared storage has no atomic create, so two devices claiming in the same instant are settled by the read-back; in the test exactly one wins.
- Not fired, not marked, tried again next minute: target queue unreadable, or the channel has no queue yet (nothing to prepend to). A leftover `active_block` for the schedule with no block items in the queue is cleared before firing (replaces the old stale-block checks).
- Removed: `_is_block_active` (unused). `service._tick_scheduler` docstring updated; its reload logic is unchanged (reload only when the block went into the channel this device is playing).
- Not changed: fire_block, block reload, the carousel (3.1.113), the wizard's overlap check.
- Tests: test_schedule_rules (21 checks, two devices over one shared folder): fires on an idle channel; earliest first; later skipped (repeating stays active, once-only switched off); remnants of an earlier block block everything; the 00:30/02:30/08:30 case; another device playing; no/unreadable queue; claim won/refused/stale/simultaneous; fired once across devices; failed fire releases claim; leftover active_block cleared; different targets independent. test_reload_detect updated (fake manager gains the new methods; an idle device now fires but queues no reload). Retired: test_sched_gate (the 3.1.103 only-the-playing-device rule) and test_orig (3.1.102 repro). All other sims pass.

## 3.1.113
carousel.py. Builds on 3.1.112.
- Fix: **a carousel channel popped and appended a whole batch of items right after you stopped watching it.** The carousel skips the channel that is playing, but it never reset that channel's carousel clock. When playback stopped, the catch-up loop counted all the time spent watching as time owed. Found from the Test Target Channel on 10/18: stopped at 19:18, and at 19:19 the log read `duration: elapsed=8982s front_duration=437s` and `catch-up popping 16 item(s)`; 16 items left the front of the queue and 16 replacements were added at the tail.
- Now: while a channel is playing, its carousel clock is set to "now" on every carousel check (once a minute), so nothing builds up and the channel behaves like a channel without a carousel. When playback stops the clock counts from that moment. A channel left stopped, or Kodi left off, still catches up as before.
- A channel played on another device and active schedule source channels are still skipped without touching their clock. A playing channel that has no clock yet is left alone (the first-run guard sets it).
- Only carousel.py changed: new private helper `_hold_clock_while_playing`, uses the existing public `get_carousel_state` / `set_carousel_state`. No new strings.
- Up to one minute of the time just before you stop is not covered by the hold, so the first pop can come a little earlier than a full item length after stopping.

## 3.1.112
channel_manager.py. Builds on 3.1.111.
- Fix: **a scheduled block item came back at the end of the queue.** Picking an item in the middle of a channel's queue ("play from this item", from the side panel or the queue list) rotates the queue: every item in front of the pick moves to the tail. Scheduled block items in front of the pick were moved to the tail too, still tagged as block items, so a block item that had not played came back later in the channel. Found from the Test Target Channel queue file: Winsome Witch (schedule sch_a692) was the last item although its block was already finished at the front.
- Now: block items in front of the pick are dropped (no replacement, as for a skip or a carousel pop), their resume point is cleared, and each is counted toward its block so the block still ends correctly. Normal items in front of the pick still rotate to the tail exactly as before.
- Only `reorder_queue_from_item` changed. No new methods, no private calls across modules; counting uses the existing public `ScheduleManager.on_block_item_complete`, as the carousel does. No new strings.
- Not changed: skip, natural end and carousel already drop block items and are untouched.
- Not confirmed from the logs: the logs supplied do not cover the moment the item was moved, so the cause is established from the code and the shape of the queue file. The first test below reproduces it on 3.1.111.
- Open: after its block had counted 6 of 6, the carousel still popped three more items tagged with schedule sch_abc536d8 on 10/18 (Hokum Smokum at 11:02, Science Friction, 1960s). Not yet explained; may be the same cause or two devices firing the same block. Investigate separately.

## 3.1.111
utils/paths.py, channel_manager.py, player.py, strings.po, USER_MANUAL.md. Builds on 3.1.110.
- Fix: **channels went back to S01E01 for every show.** state.json (every channel's position, resume points, schedule blocks) and the queue files live on the shared folder and are rewritten by every device and several threads at once. Kodi replaces a file on a network share by deleting and recreating it, so a reader can briefly see an empty or half-written file (found in the Bedroom log: `load_json failed ... Expecting value: line 1 column 1`, in the middle of three simultaneous writes, and again on 10/13). The add-on treated an unreadable file as "nothing there": a channel's whole position record is one entry in state.json, so one empty read made the next episode drawn for a show come from the start, and saving it replaced the channel's real positions. The same happened when channels.json could not be read during a save (every position was dropped as belonging to a deleted channel), and when a queue file could not be read as a channel started (a new queue was built from the starting points over the real one).
- Four places were worse than the main save: recording a skipped item with no duration (the carousel does this many times an hour), setting a schedule block, clearing one, and deleting a schedule each read the whole of state.json, changed one key and wrote the whole file back. One failed read there erased everything. They now go through the same protected save as everything else.
- How it is fixed: (1) `load_json_strict` (utils/paths.py) tells a missing file from an unreadable one; an empty or half-written read is retried (3 tries, 150 and 400 ms apart), and a share that cannot be reached counts as unreadable, not as empty. `load_json` uses it too, so every read now retries. (2) `_save_state` writes nothing when state.json cannot be read, and skips the deleted-channel clean-up unless channels.json was read and holds at least one channel. (3) A manager that started while state.json was unreadable draws no replacement, builds no queue and saves no cursor until it can read the file (`_ensure_state`). (4) `_save_channels` refuses to write a channel list that started as a stand-in for an unreadable channels.json. (5) New `read_channel_queue` tells an unreadable queue (None) from a missing one ([]); `start_channel` no longer builds a new queue over an unreadable one: it shows string 32950 and does not start. (6) State saves in one process run one at a time. (7) A snapshot of the last good state.json is written to `state.bak0.json` to `state.bak7.json` on the shared folder, at most every 3 hours, rotating, so about 24 hours of earlier copies exist. An empty state is never snapshotted. To restore: close Kodi on every device, copy the newest good snapshot over `state.json`.
- Strings: 32950. 563 strings, no duplicates.
- Not changed: how queues are built, cursors, playback, the channel lock, the files the Backup tool copies (snapshots are not part of it). A rebuild still starts every show at its starting point (that is how a new queue is built).
- Known limits: two devices saving state in the same instant can still overwrite each other's newest key (the later save wins); this no longer erases anything else. A queue file that stays unreadable for several seconds can still be read as empty by the replacement code in service.py; the retry covers the short overwrite gaps seen in the logs.
- Test: sim_state_protect, 34 checks with the real ChannelManager and player: a torn read is retried, unreadable state / channels / queue / share unreachable write nothing, a manager started during an outage draws and saves nothing and recovers, start_channel does not rebuild over an unreadable queue, an empty channel list does not prune, a deleted channel's keys are still pruned, the four direct writers keep every other key, first run still creates the file, snapshot interval and rotation, and two managers saving 80 keys at once. The same checks against 3.1.110 fail. All earlier sims give the same result as on 3.1.110; pyflakes clean.

## 3.1.110
router.py, service.py, strings.po, USER_MANUAL.md. Builds on 3.1.109 (the channel lock).
- Change: a device that was refused a channel now gets the "now available" notification even while it is playing another channel (3.1.109 cancelled the wait as soon as the device played anything). The wait still ends when the notification is shown, when the device plays that channel itself (a successful start from the menu, or the service sees it playing), after 4 hours, or when Kodi restarts.
- New: a channel that another device is playing can no longer be edited, reset, deleted, have its interleave managed, or have a show reset to its start (Reset Show on an episode) from this device. The dialog (string 32949) names the other device; the channel is remembered as waiting, so the same notification arrives when it is free. The device that owns the channel can still change it. All five menu entries use one check, `_channel_change_blocked`, which reuses the 3.1.109 dialog helper (`_channel_busy_elsewhere`, now with a text id).
- Not blocked: moving a channel in the list, icon, visibility, adding a schedule, and the global tools (Repair Queue Paths, Refresh Library, backup / restore / delete all data). A Combo Block channel is never locked (it cannot be played), so editing one that is woven into a channel another device is playing is not blocked.
- Strings: 32949. 562 strings, no duplicates.
- Code: no new modules or lock methods; `service.py` `_tick_channel_lock` now runs the notification check in both the playing and idle cases; no private calls across modules; no playback handlers touched.
- Test: sim_channel_lock extended to 53 checks: wait kept while playing another channel, toast arrives while watching, wait cleared when playing the awaited channel, edit / delete / reset / interleave / reset-show blocked on a held channel (no wizard or manager call made, five dialogs with text 32949, wait noted), all run on a free channel, the owner can still change its own channel. All earlier sims pass; pyflakes clean.

## 3.1.109
channel_manager.py, player.py, router.py, service.py, carousel.py, utils/channel_wait.py (new), strings.po, USER_MANUAL.md. Builds on 3.1.108.
- New: **one device at a time per channel.** When two devices ran the same channel they each popped the shared queue and drew a replacement at every item end, so replacements were drawn twice per item, each device played different episodes, and a scheduled block fired on one device could be deleted by the other (found by simulating two clients against the real service code).
- How: the first device to start a channel owns it by writing a small lock file (`channel_lock_<id>.json`) next to the queue file on the shared storage: device id (random, kept in the local profile), device name (Kodi's friendly name), a counter and a timestamp. A second device that tries to start that channel, from the channel list or from "play from this queue item", gets a dialog naming the other device (string 32946) and nothing plays. The play-from-item check runs before the queue is reordered, so a blocked device cannot change the owner's queue.
- Upkeep (service tick, every 60 s): while a channel is playing the owner refreshes its lock. With nothing playing for two ticks in a row the lock is released (one idle tick is tolerated so a schedule block reload does not drop it). Stopping a channel, switching channel and closing Kodi release it at once. A device holds one lock at a time.
- Crash or power loss: a lock whose timestamp is more than 180 seconds from the checking device's clock (either direction) counts as dead, so the channel can be started again after about 3 minutes. A badly wrong clock makes the lock look dead, which is the old behaviour, never a lockout.
- Notice: a device that was refused a channel gets a notification (string 32947) within about a minute of the channel becoming free. It stops waiting if it starts playing anything, after 4 hours, or when Kodi restarts. The waiting list is kept in a Kodi home-window property (new module utils/channel_wait.py), per device, never on the share.
- Carousel: a carousel channel playing on another device is now skipped by the carousel on this device (before, only the channel this device itself was playing was skipped, so an idle second device kept popping the queue the owner was watching).
- Two devices starting the same channel in the same moment: each writes, waits 0.3 s, reads back; the one that lost is blocked. Best effort.
- Not changed: edit / reset / delete of a locked channel is not blocked yet (planned as 3.1.110); combo channels are not locked (they cannot be played directly); playback callbacks, queue replacement and schedule firing logic.
- Strings: 32946 (dialog), 32947 (notification), 32948 ("another device"). 561 strings, no duplicates.
- Code: lock methods `get_device_id`, `channel_lock_holder`, `owned_lock_channel`, `claim_channel_lock`, `refresh_channel_lock`, `release_channel_lock` in channel_manager.py (the only place that reads or writes lock files); player.py `start_channel` claims the lock before any queue is read or built; no private calls across modules; no playback handlers outside service.py.
- Test: sim_channel_lock (41 checks) with the real ChannelManager, carousel, `_tick_channel_lock`, the router guard and `start_channel` over two device profiles sharing one folder: claim, refusal, refresh and counter, expiry at 181 s, clock far ahead treated as dead, release by owner and non-owner, claim of another channel releasing the first, claim race, carousel skip and run, one and two idle ticks, toast once, waiting cleared by playing, 4 hour expiry, dialog and handle handling, blocked start touches no queue. All earlier sims pass; pyflakes and py_compile clean.

## 3.1.108
channels/interleave.py, channel_manager.py, ui/wizards/combo.py, ui/channels.py, strings.po, USER_MANUAL.md. Builds on 3.1.107 (passed the overnight soak).
- New: a Combo Block TV slot with two or more shows can now **take turns**: one show per cycle instead of every show in every cycle. Choosing it asks for one number, **Episodes per turn**, shared by all the shows. Two shows at 2 per turn play A, A, B, B, A, A, ...; at 1 per turn A, B, A, B, ... Any whole number from 1 works. The existing behaviour (every show every cycle, each with its own count) is unchanged and stays the default; slots saved before this version keep working with no change.
- How: the slot gets two optional fields, `tv_mode` ("turns") and `episodes_per_turn`. In `build_combo_tv_slot` the repeating show sequence for a taking-turns slot gives each show one run of `episodes_per_turn` positions, so the existing per-slot position counter (`show_slot`) moves to the next show after each cycle; nothing else about drawing episodes changes (Random / No Repeat, sequential order, the 3.1.107 queue check). One cycle of the slot is `episodes_per_turn` items, so `slot_item_count` (queue building, interleave weaving, schedule blocks) returns that number instead of the sum of the shows' counts.
- Weave fix-up: when the interleave weaver inserts fewer cycles than it fetched, `_sync_combo_state_from_queue` now also points a taking-turns slot at the turn that follows the last item of the slot actually in the queue (`_sync_turn_position`, in channel_manager.py), so the same show does not play in two cycles in a row after a rebuild.
- UI: a new question in the slot wizard for TV slots with two or more shows (strings 32941 to 32944); on a taking-turns slot the per-show episode counts are not asked and are dropped. The channel's info view shows "Taking turns: N episode(s) per turn" under the slot (string 32945). A slot with one show never asks.
- Not changed: Movie and Folder slots; the TV channel wizard; existing queues (they change only as items are replaced or the channel is rebuilt); a show that has no episodes is skipped on its turn.
- Code: helpers `tv_slot_takes_turns` and `tv_turn_size` and the constant `TV_MODE_TURNS` live in channels/interleave.py next to `slot_item_count` and are imported by the other modules; no duplicated logic, no private calls across modules, no playback handlers touched (service.py and player.py unchanged).
- Test: sim_turns (31 checks) runs the real `build_combo_tv_slot`, `ComboQueueBuilder.build` / `build_unit`, `_sync_turn_position` and the wizard helper with stubbed dialogs: 1 and 2 and 3 shows, 1 to 3 per turn, one call of 8 equals 8 calls of 1, each show advances its own episodes, a show without episodes, a one-show slot with the field set, a full queue build alternating by cycle, the sync fix-up, and the wizard (turns, together, cancel, edit with preselect, blank and 0 input). The together-mode checks give the same results on the 3.1.107 code. All earlier sims pass; pyflakes clean on the whole add-on.

## 3.1.107
channel_manager.py, service.py. Builds on 3.1.106 (passed the overnight soak test).
- Fix: a Combo Block TV slot could draw an episode that was already waiting in the queue. Overnight (3.1.106) "Adventures of Popeye" was drawn at 22:19 and again at 03:16 while the first copy was still queued. The slot kept a saved "drawn this cycle" list per show, and by morning it held only the latest draws (Popeye 4, Yogi 4, Woody 2, against 46 each at 21:13), so queued episodes were no longer protected. The queue was only consulted when a whole cycle wrapped.
- Now: every random TV draw first leaves out the episodes of that show and slot already in the queue, whatever the saved list says; they are drawn only if nothing else is left. The same applies when a cycle wraps inside one build (the new cycle takes unqueued episodes first and counts episodes drawn earlier in the same build as taken), which before could repeat an episode within one build.
- Also: the skip handler (`_handle_skip`) now passes the queue when it replaces a skipped Combo item, as the normal replacement already did. Before, a skip replacement had no queue to check.
- Diagnostic: a log line "cycle wrapped" is written whenever a show's cycle wraps (before the call, or inside one build), so the next soak test shows when the drawn list restarts. The cause of the list being cut down overnight is NOT yet found; this build protects against the duplicate but not the cause.
- Not changed: Movie and Folder slots (their drawn lists were not examined); Sequential TV shows (not random); the 57-versus-56 queue length question (open, see test R3).
- Code: no new strings, no new functions on other modules, no private calls across modules. Helper `_cycle_pool` is local to `build_combo_tv_slot`.
- Test: sim_tv_nodup runs the real `build_combo_tv_slot` with 53 episodes, 20 seeds x 200 draws, with the drawn list wiped every 10 draws. 3.1.106 code: 173 duplicates of queued episodes. 3.1.107: 0. Also: normal running 0; several full cycles 0; 53 draws in one call all distinct; 60 draws in one call wraps cleanly and logs; queue holding every episode still returns an item. Earlier sims (combo block, browse, reload detect, schedule gate) all pass; pyflakes clean.

## 3.1.106
scheduler.py, service.py. Builds on 3.1.105 (3.1.103 to 3.1.105 are all in this build).
- Fix: a scheduled block was added to the queue but never played. The 18:30 test (Combo B, 6 items) built the block correctly (2 TV, folder, 2 Huckleberry, folder) but the playing channel was not reloaded, so Kodi carried on with its old playlist ("Mrs. Ladybug"). The service then took the first block item for the one that had just finished and counted the other five as skipped; all six block items were dropped without playing and the counter stopped at 5/6.
- Cause: after each schedule check the service decided "a block was just fired on the playing channel" by comparing the set of channels that have an active block before and after the check. The Test Target Channel was already in the "before" set because of three blocks left at 2/3 in state.json from the earlier failed run, so nothing looked new and no reload was queued (no "reload pending" line in the log). This comparison was in 3.1.102 and earlier.
- Now: `ScheduleManager.check_all` returns the set of target channels it actually fired a block for, and the service queues the reload from that. A fire counts only when the schedule's `last_fired` changed, so a `fire_block` that gives up (missing channel, empty source) is not reported. Blocks left in state.json no longer matter. The comparison helper `_get_active_block_targets` is removed (it had no other user).
- Not changed: how leftover block counters are cleaned (they are still cleared when their schedule next comes due on a later day); the second-device reload case (two devices playing the same target).
- Code: no new strings; no private calls across modules.
- Test: sim_reload_detect (8 cases, with leftover blocks for the same channel as in the 18:30 test): reload is queued with and without leftovers; not queued when the client plays another channel or nothing, when the schedule already fired today, or when fire_block does nothing; check_all returns the fired targets / an empty set. On the 3.1.105 code the leftover case fails (reload not queued). pyflakes clean on service.py and scheduler.py.

## 3.1.105
channels/folder.py, ui/dialogs.py, ui/wizards/combo.py, ui/wizards/folder.py, strings.po, USER_MANUAL.md. Builds on 3.1.104 (3.1.103 and 3.1.104 not yet hardware-tested; this build contains all three).
- New: choosing a folder on a local drive (D:\Bumpers, W:\...) in the Folder channel wizard or a Combo Block Folder slot now shows a notice. Channels live in shared storage, so every device reads the same path, but a drive letter exists only on the device that has that drive: an Android box gets "Folder not accessible" and an empty slot. The dialog explains this and offers **Keep This Path** (fine when the channel is played on that device only) or **Choose Another** (back to the folder picker). smb://, UNC and other network paths are not asked about.
- Code: new public `is_local_drive_path` (channels/folder.py, next to the other path helpers) and `browse_folder_path` (ui/dialogs.py), which replaces the two copies of the folder picker call in the Folder and Combo wizards. New strings 32938 (notice), 32939 (Keep This Path), 32940 (Choose Another). The Party wizard folder picker is not changed. Existing channels and paths are not touched or checked.
- Test: sim of the picker with a stubbed dialog (smb path no prompt; drive path kept; Choose Another reselects; cancel; Choose Another then cancel) and of `is_local_drive_path` (9 paths). pyflakes clean on the whole add-on.

## 3.1.104
scheduler.py, channels/combo.py, channels/interleave.py, USER_MANUAL.md. Builds on 3.1.103 (3.1.103 not yet hardware-tested).
- Fix: a schedule whose source is a Combo Block built the wrong block. `fire_block` multiplied the item count by the block size and then asked the slots for ONE item each in round-robin (slot 1, 2, 3, 4, 1, 2...), so a slot set to 2 episodes gave 1, and the slot order repeated mid-block. Overnight, Combo B (two-show TV slot, folder, Huckleberry 2 eps, folder) was asked for slot 0, 2, 0 instead of a 6-item block.
- Now: "Number of items" for a Combo Block source is a number of complete blocks. Each block is every slot once, in slot order, with each slot's own count (TV: sum of its shows' episodes per slot; Movies: movies per slot; Folder: items per slot). Combo B, 1 block = 2 TV, 1 folder, 2 Huckleberry, 1 folder = 6 items; 2 blocks = 12, repeating the order.
- A slot that produces nothing (for example a folder this device cannot open) is logged as a warning ("build_unit: slot <id> (<type>) produced no items") and skipped; the rest of the block is still built. The active-block counter uses the real number of items inserted.
- Folder files already chosen earlier in the same block are not drawn again (existing `host_queue` mechanism).
- Code: new public `ComboQueueBuilder.build_unit`. New `slot_item_count` in interleave.py is now the single definition of a slot's per-block count; `combo_unit_size` and `ComboQueueBuilder.build` both use it (the same arithmetic was written out in both). `fire_block` no longer multiplies by the unit size. `build_one_slot` (1-for-1 replacement, carousel) is unchanged. No new strings; no private calls across modules.
- Not changed (separate fix): Windows drive-letter folder paths (D:\, W:\) cannot be opened by Android devices.
- Test: sim of `fire_block` with a stubbed Kodi on Combo B's layout (13 checks: slot order, counts, tags, silent flags, queue after the block, 2 blocks, distinct folder files, one and both folders unreachable). pyflakes clean on scheduler.py, combo.py, interleave.py. `ComboQueueBuilder.build` output unchanged (checked on a 2-slot sample).

## 3.1.103
scheduler.py, service.py, USER_MANUAL.md. Builds on 3.1.102.
- Fix: a schedule fired on any device that had the add-on running, because schedules and queues live in shared storage and every device's service checks every schedule. In the overnight test the Android client, playing a different channel, fired all three Combo Block schedules for the Windows PC's channel. It could not read the PC's Windows folders (W:\Bumpers\...), so the blocks held only TV items, and the PC (the device actually playing the channel) never reloaded for them: the block items were treated as skipped and the block counters stayed at 2/3.
- Now: a schedule fires only on the device that is playing its target channel. `ScheduleManager.check_all` skips every schedule whose target is not the channel passed in as `now_playing_channel_id`, and does nothing when that is empty. The service passes its own channel only while Kodi is really playing (`isPlaying()`), because the channel id can outlive the last item after a natural end. A device playing another channel, or nothing, never fires.
- Behaviour to know: a schedule whose start time has passed fires on the first one-minute check after its target channel starts playing (once per calendar day). Before, it fired at the start time whether or not anyone was watching, leaving the block waiting at the front of the queue. A new schedule created after its time has passed still waits for the next day (unchanged).
- Not changed (separate fixes): the Combo Block build in `fire_block` (it asks each slot for one item in turn, so a Combo with multi-item slots gets the wrong shape); a block fired by one device while a second device also plays the target channel (the second does not reload for it).
- Code: `check_all` now uses its `now_playing_channel_id` argument (it was documented as unused); `_tick_scheduler` derives the playing channel from the player. Module docstring and the manual's Schedules section updated. No new strings.
- Test: sim of `check_all` with a stubbed Kodi (8 cases: only the playing target fires; other channel, None and "" fire nothing; two schedules on one target; inactive, already-fired and not-yet-reached are still skipped). The same test fails 4 of 8 on 3.1.102. pyflakes clean on service.py and scheduler.py.

## 3.1.102
channel_manager.py, service.py. Builds on 3.1.101.
- New: automatic repair of lost show slots. A round-robin TV queue should hold at least one episode of every show on the channel. A show that lost its slot (before 3.1.100, when one episode had no readable duration) never came back. About 60 seconds after Kodi starts, the service now checks every TV channel and adds the next episode of any show missing from its queue. The episode goes after the last regular episode, ahead of any trailing interleaved items. The show's cursor moves on as for any pick. Queue order, other cursors, carousel state and resume points are untouched.
- Skipped: serial, movie, folder, audio, party and combo channels.
- If a show has no playable episode (or the library was not ready), it is logged as a warning and the check runs once more after 5 minutes. Otherwise it runs once per start.
- The queue is read again just before it is written, so two clients starting together do not add the same show twice.
- Log lines: "repair_missing_shows: added '<show>' SxxEyy to '<channel>'" for each add, and a summary "N added, N with no playable episode".
- Not changed: a Kodi playlist already loaded is not edited; a channel that is playing at repair time picks the change up at its next start.
- Fix: "SHARED STORAGE ACTIVE" was logged every time a ChannelManager was created (about 1,300 times a night). It is now logged once per Kodi session, again only if the path changes.
- Code: new public `ChannelManager.repair_missing_shows` and static `_shows_missing_from_queue`; new `_service_repair_missing_shows` in service.py (background thread, stops on Kodi exit). No new strings.
- Test: sim_201 (show added once; before trailing interleaved; only affected channel written; cursor advanced; second run no-op; two-client race; no-episode counted and warned; shared-storage logged once). Sims 186-200 pass (192 fails by design). pyflakes clean.

## 3.1.101
router.py, ui/channels.py, strings.po. Builds on 3.1.100.
- Fix: settings "View Missing Durations Log" with an empty log showed a box whose message was the button's own name. It now says "No missing durations have been recorded." (new string 32715).
- Fix: the per-channel Missing Durations viewer (channel context menu, used when "Use side panel" is off) read the wrong field names (`ep_label`, `file_path`), so entries showed blank episode labels and no file path. It now reads `episode`, `title` and `file`, matching what is stored and what the side panel shows.
- Test: SmartChannels_Test_3.1.101_Missing_Duration_Viewers.md.

## 3.1.100
channel_manager.py only. Builds on 3.1.99.
- Fix: when the next episode of a show could not be given a duration, the one-episode replacement (used after every episode ends, after a skip, and by the carousel) gave up on the whole show. In normal play the queue then lost a slot for good (that show never came back); on a carousel the pop was aborted ("replacement returned nothing"). The episode was also not written to the missing-durations list.
- Now: the unreadable episode is recorded in the missing-durations list (state + missing_durations.txt) and skipped, and the show's next episode is taken, exactly as the queue build already did. The queue keeps its size. Only a show with no playable episode at all (or an exhausted show with recycle off) returns nothing, as before.
- Also: the interleaved-TV replacement now records the episodes it skips.
- Code: `_pick_one_ep_no_slot_advance` is now a short loop over the new `_next_candidate_ep` (the old selection code, unchanged, minus the duration check). All five callers (carousel, TV 1-for-1, serial, next-show) get the fix.
- Seen in the logs: one "Duration skip ... reason=no_nfo" for an episode whose .nfo does exist (durationinseconds 2574). A momentary network-share failure made `xbmcvfs.exists` return False. With this build such a glitch skips that one episode for the cycle and logs it, instead of shrinking the queue or stalling the carousel. Not changed: no retry on the NFO check (it would slow every bulk build over a share).
- Not changed: a carousel whose show has NO playable episode still aborts the pop and retries each minute.
- Test: sim_200 (real picker, stubbed duration reader): good episode; bad episode skipped and recorded once; cursor past it; all-bad returns None, each recorded once; wrap with recycle; recycle off; random shows. Sims 186-199 pass. pyflakes clean.

## 3.1.99
Filter rework (library.py, ui/dialogs.py, ui/channels.py, channel_manager.py one-line rename, strings.po). Builds on 3.1.98.
- New: genre, studio and MPAA filters ask a match type first: is / is not / contains / does not contain. Previously these were effectively "contains" only, so several genre rules just added up.
- New: year and rating filters offer = , != , > , >= , < , <= .
- Change: rule joining. Previously ONE "or" anywhere ORed every rule. Now AND binds tighter than OR: rules joined by AND form a group, groups are joined by OR. Filters with only AND, or only OR, behave as before. Mixed filters with three or more rules change meaning.
- Fix: rating "equals" no longer matches 7.1 for 7.0 (float compare, now rounded to 1 decimal); rating "greater than" is now strict.
- Kodi JSON-RPC has no >= or <=; these are emulated for whole numbers (year, season) and approximated for ratings. The Python fallback is exact.
- Code: `_filter_items_in_python` is now the public `LibraryClient.filter_items`, removing a private cross-module call in channel_manager.py.
- UI: filter summary lines show the full rule (e.g. "Genre is not Comedy", "Year >= 2000").
- Strings: new 32488, 32496, 32497, 32519, 32520; reworded 32499-32501. 32508-32510 and 32514-32516 are now unused (left in place).
- Not changed: artist, album, album artist and play count filters. Saved rules keep working (old comparison values map to the new defaults). TV has no MPAA filter.
- Test: sim_199 (engine, JSON-RPC, summaries, rule builder) and sims 186-198 pass; pyflakes clean.

## 3.1.98
service.py only (`SmartChannelsMonitor.__init__`). Builds on 3.1.97.
- Fix: changing the Shared storage path never showed the "copy your data to the new location?" prompt the first time in a Kodi session. The monitor's "last shared path" started as None, so the first settings change after Kodi started recorded the NEW path as the baseline and returned; only a second change compared old with new. The baseline is now the shared path in force when the service starts, so the first change prompts as designed (local -> shared, shared -> local, shared -> a different share). Changing the setting to the same share in another form (UNC vs smb://) still does not prompt.
- Effect for a client joining a share that already holds channels: the prompt now appears. Answer No: Yes copies the client's local files over the share's `channels.json`, `state.json` and queues.
- Not changed: the migration, the "delete the old files?" question and the dialog texts.
- Test (sim, real SmartChannelsMonitor.onSettingsChanged with stubs): baseline taken at start; first change prompts with the local->shared text; same value again, and the same share in UNC form, do not prompt; back to local prompts with the shared->local text; start with a path already set and unchanged: no prompt. On 3.1.97 the first two fail. Sims 3.1.86-3.1.96 pass. pyflakes clean.

## 3.1.97
Settings only (resources/settings.xml). No Python code, strings or behaviour changes. Builds on 3.1.96.
- Change: the Shared storage path, Backup folder path and Channel icon folder settings are now Kodi folder pickers (`type="path"`, button control) instead of text boxes. Clicking one opens Kodi's folder browser (sources, drives, "Add network location..."). Shared and Backup are marked writable, so only folders Kodi can write to are offered; the icon folder is read-only. Empty is still allowed. The labels are unchanged (#32030, #32057, #32005).
- Existing values carry over unchanged (the setting is still stored as text), and the 3.1.95/3.1.96 path handling still normalises whatever Kodi returns (smb://, drive letters, UNC from an older entry, quotes).
- Not changed: ffprobe path stays a text box. Changing the shared path still raises the "copy your data?" prompt; answer No when joining a share that already holds channels.
- Test: settings.xml parses; all three settings checked for type path / button / format path / writable / allowempty; sims 3.1.86-3.1.96 pass. The picker itself must be checked in Kodi (see the 3.1.97 test).

## 3.1.96
Folder settings (utils/paths.py, channel_manager.py, library.py, utils/ffprobe_scanner.py). Queue repair, backup/restore, playback and service.py are unchanged. Builds on 3.1.95.
- Fix: the Channel icon folder was used as typed, so a Windows network path (`\\Server\k\Icons`) found no icons (the side panel showed the default icon and nothing was logged). It now goes through `normalize_share_path` like the shared and backup folders, files are joined with `path_join`, and a folder that cannot be listed is logged. Setting it to `smb://Server/k/Icons` already worked.
- Fix: the ffprobe path setting accepts a quoted path ("Copy as path"), the folder that holds ffprobe.exe, a path without ".exe", and an smb:// or UNC path. It was "not found" for all of these.
- Fix: the ffprobe folder scan counted every file on a network share as failed, because the scanner would not use an smb:// path. smb:// paths are now converted to `\\server\share\...` for ffprobe (Windows uses its own login for the share; a user name or password in the Kodi path is dropped). NFS paths are still counted as failed. The NFO is still written through Kodi against the original path.
- Code: new public `clean_path_setting()` (removes spaces and quotes around a pasted path) and `smb_to_unc()` in utils/paths.py. `normalize_share_path()` now also strips quotes and keeps a drive root as `C:\` (it used to become `C:`, which means "the current folder").
- Code: `LibraryClient` had its own copy of the UNC-to-smb:// conversion for the shared folder; it now calls `normalize_share_path`. Same result, one implementation.
- Audit result: the four path settings are Channel icon folder, Shared storage path, Backup folder path and ffprobe path; all now use the common helpers. Folder channels, schedules and per-channel icons store paths returned by Kodi's own browse dialog and need no conversion.
- Not changed: the Restore text-encoding issue noted in 3.1.95; `xbmcvfs.exists` on an smb:// folder without a trailing slash in `LibraryClient.__init__` (harmless, it only retries mkdirs).
- No new strings.
- Test (sim, stubbed Kodi modules, real normalize_share_path / smb_to_unc / resolve_channel_icon / find_ffprobe / scan_folder): quotes, UNC, trailing slashes, drive roots; smb to UNC with spaces, credentials and no share path; icon found by exact name and case-insensitively from a UNC or smb:// folder, default when absent, manual icon first; ffprobe given as file, quoted, folder, no extension, missing; a scan of an smb:// folder runs ffprobe on the UNC path and writes the NFO against the smb:// path; nfs:// still failed. Sims 3.1.86-3.1.95 pass. pyflakes clean.

## 3.1.95
Backup / Restore (router.py, utils/paths.py). Queue repair, playback, service.py and the wizards are unchanged. Builds on 3.1.94.
- Fix: Backup failed with "Could not copy backup to: ..." when the Backup folder path was a Windows UNC path (`\\Server\k\Kodi 21.3`). The path was used exactly as typed; only the shared-storage path was converted to `smb://`. Backup and Restore now run the setting through the same conversion, so `\\Server\share\folder`, `//Server/share/folder` and `smb://Server/share/folder` all work. A UNC path is not usable on Android; the converted form is.
- Code: the conversion that lived inside `shared_root()` is now the public `normalize_share_path()` in utils/paths.py, and `shared_root()` calls it (behaviour unchanged). No duplicate code.
- Fix: Backup now creates the backup folder when it does not exist (it used to fail the copy).
- Logging: Backup logs files it could not read, a failed folder create, a failed copy (with source and target) and exceptions; Restore logs a failed folder listing and a failed copy. Nothing was logged before. Dialog texts are unchanged.
- No new strings.
- Not changed: Restore writes files with `zf.read(fn).decode("latin-1")` through a text-mode file; this looks like it double-encodes non-ASCII characters (accented titles) on restore. Left alone for a separate fix (see the notes to the developer).
- Test (sim, stubbed Kodi modules, real backup_data / restore_data / normalize_share_path): UNC, `//`, `smb://`, trailing slashes, drive letter, local path, empty and None; shared_root unchanged for UNC; backup copies to the converted `smb://` path, creates a missing folder, does not recreate an existing one, still reports #32368 when the copy fails; restore lists and copies from the converted path. Sims 3.1.86-3.1.94 pass. pyflakes clean.

## 3.1.94
Library cache and queue repair (library.py, channel_manager.py, router.py, addon.py, settings.xml, strings.po). Playback, replacements, service.py and the wizards are unchanged. Builds on 3.1.93.
- Fix: after episode files were renamed or moved, a channel could stall on the old path (8 Simple Rules S02E12). The episode lists the addon loads from the Kodi library were kept in memory until Kodi restarted, so the service kept queueing and replacing episodes with the old file names even after Kodi had been cleaned and rescanned.
- New: Settings > Cache > "Repair Queue Paths" (#32026, confirmation #32027, result #32028). It first clears the in-memory library lists, then goes through every channel's queue and looks each TV episode up in the library (by episode ID, then by show + season + episode). The file path, title, season/episode, episode ID and multi-episode span are rewritten from the library. Queue order, cursors, carousel state and all other fields are not touched, and a resume position saved under the old path moves to the new path. Only queue files that changed are written.
- An episode the library no longer has is left as it is and counted as "not found" (logged with a warning). Movies, folder and audio entries are not checked.
- `LibraryClient.invalidate_cache()` (public): clears the lists and bumps a Kodi home-window property that every LibraryClient checks before a lookup, so the service (a separate process from the settings action) reloads too. The property exists per Kodi instance, so clearing is per client; the repaired queue files are shared by all clients.
- `ChannelManager.repair_queue_paths()` (public).
- Not changed: the Kodi playlist of a channel that is playing keeps its old paths until that channel is started again. The library must be updated in Kodi first. No automatic detection or skipping of files that fail to open yet (planned).
- Test (sim, real repair_queue_paths / _repair_queue_item / LibraryClient with stubs): renamed file, episode ID changed by a rescan, episode missing, movie entry, already-current entry, resume re-keyed, order and untouched entries identical, only changed queue written, second run changes nothing, a second LibraryClient sees the cache clear. Sims 3.1.86-3.1.93 pass. pyflakes clean, settings.xml and addon.xml parse.

## 3.1.93
Manage Interleave wizard (ui/wizards/interleave.py) and strings.po only. Builds on 3.1.92.
- Fix: Kodi's number pad shows a single heading line, so the extra Combo Block line added in 3.1.92 (and the "(Interleave Sources: N)" tail) never appeared. A Combo Block source now uses its own one-line heading, #32870 "How many complete blocks to insert each time?"; all other sources keep #32343 "How many items to insert at each slot?". The number entered still counts whole blocks.
- Superseded: the 3.1.92 wording of #32870 below.

## 3.1.92
Housekeeping (service.py, channels/interleave.py, scheduler.py, ui/wizards/interleave.py, strings.po, addon.xml, addon root). No queue-building or replacement behaviour changes.
- Fix: `onSettingsChanged` restarted the resume poll with a call that has the wrong arguments (`_start_poll(new_interval, ...)`; `_start_poll` takes a file path). It now restarts the timer with `_schedule_poll()`. (The line only runs when the poll-interval setting changes while the timer is running, so it was not reachable in normal use.)
- Fix: the Manage Interleave prompt "How many items to insert at each slot?" showed the text of #32870 for every source, with a literal "{0}" in it, and the text told users to enter the Combo Block's slot count, which would have inserted that many whole blocks (the number entered counts blocks, not slots). It now appears only for a Combo Block source and #32870 is reworded without a placeholder: "A Combo Block counts as 1 item here, however many slots it has. Leave at 1 to insert one complete block each time."
- Code: `_combo_unit_size` is now public `combo_unit_size` (channels/interleave.py); scheduler.py was importing the private name from another module.
- Removed from the addon root: SMARTCHANNELS_HANDOFF_7.md, SmartChannels_Test_Matrix_3_0_75.md.
- addon.xml: real description, a news entry. Source / website / forum URLs are not set yet (need the repository address).
- Not changed: the `xbmc.python` requirement stays 3.0.0 (not verified against the Kodi 21 documentation); the remaining open items stay on the list.
- Test (sim): wizard run with a stub manager/dialog: Combo source -> prompt carries the new text, no "{0}"; TV / movie sources -> no hint line. Earlier sims (3.1.86-3.1.91) still pass. pyflakes clean, addon.xml parses.

## 3.1.91
Manage Interleave wizard (ui/wizards/interleave.py). Queue building, replacements, service.py and the other wizards are unchanged.
- Change: a Serial TV channel can no longer be chosen as an interleave source. Serial channels are stored as type "tv" with playback_mode "serial", so the source picker (which only excluded Audio, Party and Combo types) offered them, and the interleave code has no support for them (cycle planning, replacements and progress all assume in-order or random shows). The picker now skips them; if nothing else is eligible the existing "no sources available" message appears.
- Workaround for the same effect: a hidden Round Robin TV channel with the show(s) as the source.
- Not changed: a Serial channel already saved as a source stays in the list until removed; the Serial branches in the replacement code are left in place; whether a Serial channel may be an interleave host (the "serial" checks in side_panel.py and router.py never match) is undecided.
- Test (sim, real wizard run with a stub manager/dialog): hidden Serial channel only -> "no sources available" and no picker; hidden Serial + hidden Round Robin -> only Round Robin offered; visible Round Robin and carousel channels still excluded. pyflakes clean.

## 3.1.90
TV queue builder (channel_manager.py `_build_tv_items`, `_fill_slot`). Audio, Party, Combo, service.py and the wizards are unchanged.
- Fix: a show with few episodes dropped out of the rotation. T TV with According to Jim limited to S01E01-S01E04 (recycle on), interleaved into T Movies: after Jim's four episodes were queued he was skipped, while the other shows kept going. Queue showed Jim 4 times, the others 5-6, and rotation slots with no Jim; the one-for-one replacements keep each show's count, so it never evened out. A build asking for 20 episodes returned 22.
- Cause: the build refused to queue the same file twice anywhere in one queue, so when a show recycled (last episode -> first) its first episode was refused. This applied to every TV build (a TV channel's own queue as well as interleaved sources).
- The duplicate-file check now looks only at the show's current pass. When a show wraps back to its first episode a new pass starts, so it is queued again. Multi-episode files are still never queued twice within a pass.
- Replacements were already correct (they wrap), unchanged.
- Existing queues are not changed: Reset (or Manage Interleave on) the channel to rebuild.
- Not changed (planned next, 3.1.91): randomised shows and Serial TV sources in interleave.
- Test (sim, real _build_tv_items / _fill_slot, stub library): 4-episode show + three 100-episode shows, 20 requested -> exactly 20, 5 each, strict order, Jim E1-E4,E1. TV channel size 30: Jim in every round (8 of 32). Multi-episode file not duplicated within a pass. Start at E3 -> E3,E4,E1. Two tiny shows alternate strictly. Serial unchanged. On 3.1.89 the first six fail (22 items, Jim 4) and the two-tiny-shows case does not finish. 3.1.86-3.1.89 sims still pass. pyflakes clean.

## 3.1.89
Interleave progress (channel_manager.py `reset_channel`, `regenerate_queue`, `_load_foreign_items`; new public `capture_interleave_progress`, `begin_interleave_resume`, `end_interleave_resume`). Audio, Party, Combo, service.py and the wizards are unchanged.
- Fix: Reset Channel and Manage Interleave on a host sent every interleaved TV show back to the source's starting episode, losing the episodes already played. They now start each interleaved sequential show at the episode that was next in line in the host's queue. Works for TV, Movie and Folder hosts.
- A show's first interleave still starts at the source's starting episodes (3.1.87/3.1.88). Progress is kept only while the source stays interleaved; a removed and re-added source starts at its starting episodes. A new second source starts at its own starting episodes.
- Not changed (planned 3.1.90): randomised shows and Serial TV sources are skipped by this and may still restart.
- Existing queues are not changed; the next Reset or Manage Interleave uses the queue as it is then.
- Test (sim, real _load_foreign_items / capture_interleave_progress / reset_channel / regenerate_queue with stubs): first queued episode per show captured; rebuild starts shows there; after end, back to starting episodes; second source and shows without progress keep their starting episodes; an episode no longer in the library falls back to the starting episode; random, serial, movie and missing sources skipped; progress cleared even if the build raises. 3.1.87 sims still pass. pyflakes clean.

## 3.1.88
Edit Channel (channel_manager.py `update_channel`). Audio, Party, Combo, service.py and the wizards are unchanged.
- Fix: starting episodes were forgotten for shows you did not touch in a later edit. T TV was set to start at chosen episodes for four shows; the first Reset of the movie channel with T TV interleaved kept them. After a second edit that changed only According to Jim, the saved starting episodes held Jim alone, so the next Resets started the other three shows at S01E01. Cause: Edit saved only the shows picked in that edit, replacing the earlier list.
- Edit now merges: shows picked in this edit override their old entry, the other shows keep the starting episode saved earlier, and entries for shows removed from the channel are dropped.
- Unchanged: the live queue and state after an edit (already correct), Serial/Movie/Folder channels.
- Existing channels: a starting episode already lost stays lost; set it again once in Edit.
- Test (sim, real update_channel with stub): edit one of four shows -> other three keep their starting episode, picked show overrides, empty or missing picks keep all, removed show dropped, new show added, rebuild sees the merged list, Movie channel unaffected, int keys normalised. The same test fails on 3.1.87 (other shows lost). pyflakes clean.

## 3.1.87
Interleaved TV episodes (channel_manager.py `_load_foreign_items`, new `get_interleaved_tv_replacement`, `get_one_replacement`). Audio, Party, Combo, service.py and the wizards are unchanged.
- Fix: replacements for interleaved TV episodes jumped to the wrong episode. T Movies with T TV interleaved: the woven queue held According to Jim S01E01-S01E03, then the replacement for the played Jim episode was S08E08. Cause: the first weave always started every show at S01E01 and ignored the source's starting episodes, while a replacement read the source channel's OWN saved position (T TV had starting episodes set, so its position was at Jim S08E05 and on). The queue used one position when it was built and another when it refilled. Replacements also moved the source channel's own saved position.
- The weave now applies the source's starting episodes (Jim starts at S08E05 when T TV is set to start there), the same way a channel does when it builds its own queue.
- A replacement for an interleaved episode of a sequential show is now the episode after the last queued episode of that show from the same source (the host queue is the authority); when none is queued it is the episode after the one just played. Multi-episode files skip their whole span; at the end of a show it wraps to the first episode when the source recycles, otherwise there is no replacement. The source channel's own saved position is neither read nor changed.
- Unchanged: randomised shows and Serial TV sources keep the previous behaviour (they use the source's own list of played episodes), as does the rare case where the played episode is no longer in the library.
- Not changed (planned next): keeping the interleaved episodes' progress through a Reset or Manage Interleave (a rebuild still starts the shows at the source's starting episodes, not where they had got to).
- Existing queues are not changed: Reset (or Manage Interleave on) the host channel to rebuild them.
- Test (sim, real `_load_foreign_items` / `get_one_replacement` / `get_interleaved_tv_replacement` with a stub library): source with starting episode at index 167 and its own saved position at 171/38/99: weave starts the show at 167; woven episodes plus 400 one-for-one replacements run consecutively for every show (167, 168, 169 ... / 0, 1, 2 ...) and the source's saved position is unchanged. The same test on 3.1.86 fails as reported (0, 1, 2, then 171, 172, 173; 38, 39, 40; 99, 100, 101). Recycle on wraps; recycle off ends; a multi-episode file skips its span; a missing-duration episode is skipped; randomised, serial and missing-episode cases use the previous path. pyflakes clean.

## 3.1.86
Interleave cycle planning (channels/interleave.py `plan_primary_count`, new `source_rotation_size`; channel_manager.py new `build_planned_queue`, `extend_primary_to_cycle`, `build_channel_queue` and `regenerate_queue` for Movie and Folder channels). Audio, Party, Combo, service.py and the wizards are unchanged.
- Fix: a round-robin TV source (several shows) could be woven in with a half-finished round. T Movies (10 movies, T TV with 4 shows every 2, jitter 1) came out as Jim, 3rd Rock, 2 Broke Girls, 8 Simple Rules, Jim, 3rd Rock and ended on a movie. A replacement always comes from the same show as the item it replaces, so the unbalanced shape never evened out: Jim and 3rd Rock would play twice as often as the other two for as long as the channel ran.
- The planner now also requires every round-robin TV source to have given a whole number of rounds of its shows (4 shows -> 4, 8, 12 episodes), on top of "the queue ends right after an interleaved group". The queue may be longer than the queue size, never shorter. Folder, movie, combo-block and serial-TV sources count as one show, so their results are unchanged (T Host with a 2-item combo block, size 10, is still exactly 10 items).
- Movie and Folder channels: a fresh build now plans the number of its own items (queue size is the minimum) so the queue ends on a whole cycle; one seed drives both the plan and the weave. Manage Interleave on a Movie or Folder channel keeps the items already in the queue and adds more of the channel's own items where the cycle needs them (new public `extend_primary_to_cycle`), then weaves with the same seed.
- TV channels use the same planner, so a TV host with a multi-show TV source is fixed too. The build can take a few more passes over the episode lists in that case (sim worst case 17).
- Not changed (planned next): interleaved TV episodes still start at S01E01 on every build; the source's starting episodes and progress are not used yet.
- Test (sim, real planner / weaver / build_planned_queue / extend_primary_to_cycle / _build_planned_tv_items with stub library): Movie and Folder host x 2-5 show TV source x 6 frequency/jitter/count settings x 60 builds each: every queue has >= 10 own items, ends on an episode, whole rounds, every show equal; T Movies case (4 shows, every 2 +/-1) -> 4/8/12.. episodes ending on an episode; TV-host planner 400 seeds all whole rounds on a cycle end (3.1.85 planner: 131 of 300 not); T Host combo sizes 9/10/11 -> 10/10/15; two TV sources; Manage Interleave extension keeps the original 10 movies; 150 random TV-host setups (1-4 host shows, 2-5 source shows) whole host rotation + whole source rounds. pyflakes clean.

## 3.1.85
Movie and Folder channels with interleave (channel_manager.py `build_channel_queue`; new `weave_interleave_sources`). TV, Audio, Party, Combo, service.py and the wizards are unchanged in behaviour.
- Fix: resetting a Movie or Folder channel (or any edit that rebuilds its queue) dropped every interleaved item. Only TV channels wove their interleave sources into a fresh queue; Movie and Folder channels got interleave only through Manage Interleave, and lost it again on the next reset. T Movies (Comedy movies, T TV episodes every 2, jitter 1): after Reset only movies remained.
- A fresh Movie or Folder queue now has its interleave sources woven in, for every source type (TV episodes, folder items, movies, combo blocks). Queue size still counts only the channel's own items, so queue size 10 gives 10 movies plus the interleaved items on top, as Manage Interleave already did. Jitter gaps are rolled again on each build.
- The weave and combo-state sync now live in one function, `weave_interleave_sources`, used by the TV build and by the new Movie/Folder path (no duplicate code). The TV build behaves as before and still passes its jitter seed.
- The combo-pointer reset before a create/edit rebuild (`_pregenerate_queue_safe`) now also covers Movie and Folder channels, as it does for TV.
- Not changed (planned next): interleaved TV episodes still restart from S01E01 on every build (the source's starting episodes and progress are not used yet).
- Test (sim, real build_channel_queue / weave_interleave_sources / weaver with stub builders): Movie and Folder host, no interleave -> 10 plain items; Every 3 -> 10 own items + 3 interleaved (gaps 3,3,3); jitter 2+/-1, 500 builds each -> 10 own items, every gap 1-3; missing source -> plain queue; empty queue unchanged; TV seed passed to the weaver.

## 3.1.84
TV channels with interleave added through Manage Interleave (channel_manager.py `regenerate_queue`; new `_build_planned_tv_items`, `_rewind_tv_cursor`, `_regenerate_tv_interleave`). Includes 3.1.83 (jitter). Audio, Movie, Folder, Party, Combo, service.py and the wizards are unchanged.
- Fix: adding or changing a combo block / interleave on an existing TV channel kept the old episodes and only wove blocks into them, so queue_size and the cycle end were ignored. Test Channel (3 shows, queue size 10, a 5-item combo block every 3 episodes) got 12 episodes + 4 blocks = 32 items instead of 2 cycles = 16 items (the 12 episodes came from the old queue, which was built before the block existed).
- Manage Interleave now rebuilds the primary episodes from the head of the current queue through the same planner as a new queue (queue_size counts every item, a minimum, always ends on a whole interleave cycle, jitter included). The cursor is moved back to the first queued episode of each show (randomised shows: the queued episodes are removed from the played list), so the channel continues from where it was: the queue head is unchanged and later replacements carry on after the last queued episode.
- The planning logic now lives in one function, `_build_planned_tv_items`, used by both the initial build and Manage Interleave (no duplicate code).
- If the cursor cannot be rewound reliably (episode no longer in the library) the previous behaviour (re-weave the existing episodes) is used and a log line says so. Removing the last interleave source still just drops the blocks and keeps the episodes. Non-TV channels and Serial channels are unchanged.
- Test (sim, real regenerate_queue / _build_fresh_tv_queue with stub library): your setup (3 shows, size 10, block of 5 every 3) built without interleave (12 episodes) then interleave added -> 16 items [3,B x5,3,B x5], episodes 1-2 of each show, cursor ep_pos 2/2/2; partially played queue (head = show 3) -> 16 items starting with show 3; 90 jitter / multi-source / 1-3 show regenerations all >= queue_size and ending on a block; randomised shows -> 16. All earlier sims (initial build, jitter, audio) unchanged.

## 3.1.83
Initial TV queue with interleave (channel_manager.py `_build_fresh_tv_queue`; channels/interleave.py `plan_primary_count()`, `_source_rng()`, optional `seed`/`rng` on the weaver). Replaces 3.1.82 (not yet tested in Kodi). Audio, Movie, Folder, Party, Combo, service.py and the wizards are unchanged.
- Fix: sources with jitter. A jitter source draws random gaps, so 3.1.81/3.1.82 planned its cycle end on the nominal frequency only and the queue could end part-way through a group. The build now picks one random seed per queue build; the planner and the weaver draw their jitter gaps from the same seeded generators, so the planner knows the exact gaps the weave will use. Every queue (fixed frequency or jitter, one or several sources, one or several shows) ends right after an interleaved group and holds at least queue_size items.
- The planner searches primary counts one at a time when jitter is present (a multiple of the cycle length otherwise) and the build re-plans until the show rotation and the interleave cycle end together.
- Safety: `weave_seed` defaults to None so Serial / no-interleave paths cannot reach the weave with an undefined seed.
- Behaviour with a non-jitter source is identical to 3.1.82. Replacements stay one-for-one; existing queues are not touched (reset the channel to rebuild).
- Test (sim, real _build_fresh_tv_queue and weaver with stub library): 2,880 jitter builds (1-3 shows; folder and combo sources; one and two sources; count_per 1-2; queue sizes 1-60): none shorter than queue_size, none ending on a primary episode. T Host size 10 without jitter still gives [3,B,B,3,B,B]. 3.1.81/3.1.82 sims, audio sims unchanged.

## 3.1.82
Same area as 3.1.81 (initial TV queue with interleave), one tightening in `plan_primary_count()`.
- With several interleave sources the planner now requires EVERY source to have just fired at the end of the queue (3.1.81 only checked the last one) and searches far enough to find that point instead of falling back to the first long-enough queue. Single-source channels (all channels seen so far) build exactly as in 3.1.81.
- (Jitter sources were completed in 3.1.83.)
- Test (sim): same cases as 3.1.81 plus two- and three-source plans; every plan ends on a block.

## 3.1.81
TV channels with interleave only (channel_manager.py `_build_fresh_tv_queue`; new `cycle_length()` and `plan_primary_count()` in channels/interleave.py). Replaces 3.1.80 (never released for testing; it counted queue_size in episodes only). Audio, Movie, Folder, Party, Combo, service.py and the wizards are unchanged.
- Fix: the initial queue of a TV channel with interleave stopped part-way through an interleave group and counted queue_size in episodes only. T Host (queue size 10, a combo block of 2 items every 3 episodes) came out as 10 episodes + 6 combo items = 16 items ending on a group of 1 episode; replacements then grew that last group to 4 episodes before the next block.
- queue_size now counts every item in the queue (episodes and interleaved items) and is a minimum: the build adds primary episodes until the queue holds at least queue_size items AND ends right after an interleaved group, i.e. on a whole interleave cycle. T Host size 10 -> 3 episodes, block (2), 3 episodes, block (2) = exactly 10 items. When the size does not land on a cycle end the queue is longer, never shorter: size 11 -> 15 items, 9 -> 10, 16 -> 20. The show-rotation cycle is still completed (2 shows every 3 builds a multiple of 6 episodes).
- Counting uses each source's real items per firing (a combo block counts its unit size, times count_per). Jitter sources were completed in 3.1.83.
- Applies when a queue is built from scratch (create, reset, edit that rebuilds). Existing queues are not touched; reset the channel to get the new shape. Replacements stay one-for-one, so the spacing stays 3 afterwards.
- Not changed: channels without interleave (sizes identical to 3.1.79), Serial channels, regenerate_queue after an interleave change.
- Test (sim, real _build_fresh_tv_queue and weaver with stub library): 1 show, combo of 2 every 3: size 10 -> 10 items [3,B,B,3,B,B] ending on a block (3.1.79: 16 items ending on 1 episode); sizes 9/11/15/16/5/1 -> 10/15/15/20/5/5; folder source every 3 size 10 -> 12; count_per 2 -> 14; 2 shows -> 10 items; 3 shows every 4 -> 18; two sources >= 10; no interleave 10/10/12 unchanged; episodes in order, no duplicates. Audio replays (3.1.77-3.1.79) give the same results.

## 3.1.79
Audio channels only, Album Order and Shuffle Albums (`channels/audio.py` `_album_sort_key`). No video, Party, service.py or wizard changes.
- Fix: an album whose songs have no track number tagged (track 0) played only its first song, then the channel jumped to the next album; the other songs were never played. Found in the 3.1.78 T AlbumShuf soak: the "Bad Company" album played 1 song, every tagged album played all of its songs. Cause: the album sort key was albumartist, album, disc, track; songs with the same track number compared equal, and "next song after the tail" needs a strictly greater key, so tied songs were never chosen.
- The file path is now the last part of the sort key, so every song has a distinct place. Albums with tagged tracks play exactly as before; untagged songs play in file-name order (the best order available without a track number). The initial queue uses the same key.
- Also affected plain Album Order (same comparison), not only Shuffle Albums.
- Test (sim, album of 8 songs with track 0 except one, a tagged 6-song album, an untagged 5-song album; 300 replacements, queue sizes 4 and 10, with and without Shuffle Albums): every song plays and every album run is complete. The 3.1.78 code, same data: 7 of 19 songs never played. 3.1.77/3.1.78 replays (audio order, exclude dialog) give the same results.

## 3.1.78
Audio wizard, "exclude songs" step only (ui/dialogs.py `build_audio_song_exclusions`). No channel, playback or state logic changed.
- Fix: the count shown next to each artist ("N song(s) excluded") was the total for ALL artists, so excluding 3 songs on one album made every other artist show 3 too, and after 3 more on a second album both showed 6. The excluded list itself was correct (6 songs); only the label was wrong. Each artist now shows its own count, and the album list now shows a count per album.
- Change: songs are picked in one multi-select per album (tick the songs to exclude, confirm once) instead of a list that closed and reopened after every tap. Songs already excluded are pre-ticked; cancelling the dialog leaves the album unchanged; unticking a song removes the exclusion.
- Change: the song line no longer starts with "00." when the track number is not tagged (shows the title only).
- Test (sim, 2 artists x 2 albums x 5 songs): artist screens read "Tap / Tap", then "3 excluded / Tap", then "3 excluded / 3 excluded" with 6 songs in the final list; reopening an album pre-ticks its 3 songs; unticking, cancelling and clearing all behave. The old code, run on the same data, shows the same count on both artists.
- Unchanged: everything else, including all 3.1.77 audio order behaviour (3.1.77 replays give the same results).

## 3.1.77
Audio channels only (video, Party, service.py unchanged).
- Audio playback order is now two choices plus a yes/no question, instead of five orders:
  - **Shuffle (no repeats)**, then "Balance Artists?": every song plays once per cycle; with Balanced on, each artist gets equal turns (never the same artist back to back) and each artist cycles through its own songs independently (when all of an artist's songs have played, only that artist starts over).
  - **Album Order**, then "Shuffle Albums?": albums play in order, or with shuffle in random order. Every album plays once before any album repeats (previously a random other album was chosen each time, so one could repeat early).
- Saved channels keep working and nothing is rewritten on disk: `random` and `no_repeat` open as Shuffle, `balanced` as Shuffle + Balanced, `album` as Album, `album_shuffle` as Album + Shuffle Albums (`resolve_audio_mode`). New channel fields: `audio_balanced`, `audio_album_shuffle`.
- Album shuffle now identifies albums by album artist + title (the initial queue grouped by title only, so two artists with an album of the same name were merged).
- Played tracking: the `{channel}:audio_no_repeat_played` list in state.json is reused; it is now also recorded for Album + Shuffle Albums (needed to cycle albums). No new state key.
- build_one log line now includes artist and album, and the mode flags: `build_one: 'Title' by 'Artist' [Album] for 'Channel' (order=... balanced=... album_shuffle=...)`. New INFO lines when a Balanced artist starts over and when Album shuffle starts a new cycle.
- Strings: new #32934 (Shuffle (no repeats)), #32935/#32936 (Balance Artists question), #32937 (Shuffle Albums question). #32825 and #32854 reused for the info screen. Party channels keep their own Random / Random (no repeats) choices (#32217, #32855).
- Replay (sim): migration of all old values; Balanced with 40/10/5-song artists, 900 replacements: 0 adjacent same-artist, artists 33% each (was skewed to the big artist before 3.1.76); every song of a small artist plays equally often (+-10%); Album Shuffle with 8 albums: albums always play through, no album starts twice before a reset, 0 violations; two artists with an album of the same name stay separate; single artist/album and pool no larger than queue work. 3.1.69-3.1.76 replays give the same results.
- Known property (not a bug): the queue looks ahead 10 songs, so at a cycle boundary songs already queued count as used. A song can recur sooner than a full cycle at the boundary, and per-song play counts differ by about 10-15% over a long run. No Repeat without Balanced behaves as in 3.1.76.

## 3.1.76
Balanced audio order only.
- Fix: Balanced replacements gave big-catalogue artists more turns. `build_one` picked a random song from everything except the last artist's songs; with four artists holding 60/30/10/5 songs the replacements came out 42/35/15/8%. It now picks the artist first (uniformly, excluding the artist of the last queued song) and then one of that artist's songs: 25% each in the same replay, never the same artist back to back.
- Fix: in the initial Balanced queue (`_balanced_shuffle`, older code) each pass through the artists was shuffled independently, so the last artist of one pass could open the next (25% of the time with 4 artists). A pass no longer starts with the artist that ended the previous one when other artists are still available (0 of 26,000 boundaries in replay; was 25%).
- Refactor: the primary-artist rule is one helper (`_primary_artist`), shared by the shuffle and `build_one`.
- Unchanged: Random, No Repeat, Album, Album Shuffle, Party, service.py. Earlier replays (3.1.69-3.1.75) give the same results.

## 3.1.75
- Fix: on a skip in an Audio or Party channel whose pool is no larger than its queue (typically a single-album channel), the replacement was not the natural next song. Found in the 3.1.74 test with an 8-song album and queue size 8: skipping Bad Company appended "Can't Get Enough" (already queued), then "Bad Company". Cause: `_handle_skip` asks for the replacement while the skipped item is still in the queue, so `build_one` counted it as queued and every song looked taken.
- `AudioQueueBuilder.build_one`: the consumed/skipped song is no longer counted as queued, and is not handed straight back while other songs are free. Skip and natural end now give the same result (replay of the 8 songs from the log: both loop Bad Company, Can't Get Enough, Don't Let Me Down, Movin' On, Ready For Love, Rock Steady, The Way I Choose, Seagull). With a larger pool the skipped song is still never returned straight away.
- `PartyQueueBuilder.build_one`: same rule (first choice excludes queued files and the consumed file; the consumed file is reused only when nothing else is free).
- Replay (60-song library, queue 8, alternating skip and natural end, 600 each): 0 duplicates in queue and 0 skipped songs handed back for Random, No Repeat, Balanced, Album, Album Shuffle; Album order stays continuous. Party (30 files, queue 6): 0 duplicates, 0 handed back. service.py unchanged.
- Note (library data, not a bug): the songs in the test album have no track numbers (only "Seagull" has one), so Album order falls back to title order within an album. Tag track numbers for true track order.

## 3.1.74
- Fix: Audio and Party Mode channels never replaced a song after it played or was skipped, so the queue shrank until it was empty. Found in the 3.1.73 smoke test: `get_one_replacement: unhandled type 'audio'`. The gap is older than 3.1.73 (same in 3.1.42). The builders already supported top-ups, but the caller (`topup_channel_queue`) no longer exists.
- `ChannelManager.get_one_replacement` now handles `audio` and `party` through new `_replacement_audio` / `_replacement_party` (same pattern as `_replacement_folder`). service.py is unchanged: natural end and skip already call `get_one_replacement`.
- `AudioQueueBuilder.build_one(channel, host_queue, consumed_item)`: one song, avoiding songs already queued (a repeat only when the pool is no larger than the queue). Follows the channel order from the end of the queue: Random / No Repeat pick at random; Balanced avoids the artist of the last queued song; Album continues in album order (wraps at the end); Album Shuffle finishes the current album, then starts a random other album at track one.
- `PartyQueueBuilder.build_one(channel, host_queue, consumed_item)`: one file, queued files excluded.
- No Repeat (audio and party): the consumed song/file is now recorded as played (`record_no_repeat_played` was never called by anything before), and the cycle resets once every song has played.
- Refactor, no behaviour change: `AudioQueueBuilder.build` now uses `_load_pool` (library fetch + included albums + excluded songs) and `_song_to_item`, shared with `build_one`; the album sort key is one method (`_album_sort_key`).
- service.py: removed a redundant second `_make_listitem` import in `_handle_skip` (pyflakes clean again).
- Replay simulation (60-song library, queue 8; party folder of 30, queue 6; 600 consumptions each): 0 duplicates in queue for every order; Balanced never plays the same artist twice in a row; Album plays in strict track order; Album Shuffle plays albums through then switches; No Repeat has 0 repeats inside each cycle (cycles of 52-53 songs, party 24-25 files). Pool no larger than queue still returns a song.
- Comment-only: stale references to `topup_channel_queue` / `channels/tv.py` updated.

## 3.1.73
Cleanup only: dead code removed, no behaviour change intended.
- Removed 26 functions that nothing calls (including `ComboQueueBuilder.build_one_unit`, `FolderQueueBuilder.is_exhausted`, and unused helpers in channels/base.py, library.py, channel_manager.py, scheduler.py, carousel.py, side_panel.py, logo_overlay.py, ui/*) and the whole unused module `channels/tv.py` (the TV queue builder lives in channel_manager.py since the rewrite). About 350 lines in total.
- Removed unused imports (11 files) and unused local variables found by pyflakes; the redundant duplicate `_make_listitem` import in service.py.
- Removed the leftover "Recycle changed" check in `update_channel` and ui/channels.py: no wizard exposes Recycle, so it could never change on edit. Mode change = randomize, no-repeat or channel type, as before.
- Kept on purpose: legacy-data compatibility reads (old saved channel/state shapes) and the `recycle=False` branches in queue builders.
- Checks: compileall, import smoke test, pyflakes clean, replay sims for 3.1.69-3.1.72 unchanged (0 duplicates; save_json retry results identical).

## 3.1.72
Five items from the "finish list", built together on 3.1.71 at Mark's request.
- Fix (1): editing a TV or Serial channel's queue size (or interleave) rebuilt the queue from S01E01, the same root cause as the show-list case fixed in 3.1.69. `update_channel` now captures positions (`_capture_edit_positions`) before ANY rebuild that is not a mode change, not just a show-list change. Mode changes (randomize/recycle/type) still wipe state by design. Replay check: Serial and round-robin keep their place when queue_size 6 -> 8.
- Change (2): the combo Folder slot no longer asks "No Repeat". It is always on for a folder slot: Random plays every file once before any repeats (3.1.70); Sequential relies on it to advance through the folder (`FolderQueueBuilder.build` filters played files) and restarts at the end. strings.po: #32887, #32890, #32897 removed (used only by that question). Existing slots keep their saved value until edited.
- Fix (3): the interleave wizard's jitter input used heading #32344 "Interleave configured". Text of #32344 changed to "Jitter (J): most items to vary by" (it is used only there).
- Fix (4): `utils/paths.save_json` now retries a failed write (3 attempts, 250 ms then 750 ms pauses) for both local and shared/network paths, and returns False (logged as an error) if the write is still failing, instead of returning True after a lost SMB write. Helpers `_write_file` and `_write_shared` hold the write steps. Simulated: fails-once and fails-twice then succeed; always-fails returns False.
- Change (5): log noise. Per-tick carousel lines (skipping — currently playing / active schedule source, timed elapsed, intervals due, pop complete, appended next ep), `[ChannelManager] LOCAL STORAGE` and `Loaded N channel(s)` (constructed 2+ times a minute) and `[LibraryClient] Loaded N episodes` are now LOGDEBUG. The carousel still logs one INFO line per pop. `utils/logger.log` caches the `log_level` setting for 5 s instead of reading it on every call. In the 16-hour soak these lines were about 10,200 of the log's ~14,900 lines.
- strings.po: 537 entries (ids in numeric order).
- Note: debug lines show only when the addon Log Level setting is Debug and Kodi debug logging is on.

## 3.1.71
- Fix: Combo Block Movie and TV slots set to Random could repeat an item that was already in the queue (found while reviewing the 3.1.70 folder-slot fix). Random slots are now Random / No Repeat like the standalone channels.
- TV slot (`build_combo_tv_slot`): each draw reshuffled the show's whole episode list and took the first, with no memory of what had been drawn, so an episode could be queued twice or played twice in a row. Each random show now keeps the episodes drawn this cycle in state key `combo:<id>:slot:<id>:show:<id>:tv_played` (marked when drawn) and only draws an undrawn one. When the cycle completes, the next starts at once and episodes of that show still waiting in the queue count as drawn in it.
- Movie slot (`build_combo_movie_slot`): movies were already marked drawn at build time, so no repeat inside a cycle; at the cycle wrap the reset list ignored movies still waiting in the queue. Those now count as drawn in the new cycle. Sequential slots are unchanged.
- Both functions take an optional `host_queue` (passed through `build_one_slot` since 3.1.70). A repeat is only possible when a show/movie slot has no more items than the queue holds.
- Replay simulation (random slot, 4000 draws, pools 4/8/15/30, queue 3-5): duplicates in queue — TV 519/958/528/1752, movies 70/188/44/750 with 3.1.70; 0 with 3.1.71. The 3.1.70 folder-slot replay still shows 0.
- Existing combo state is read as-is; the first draw of an existing random TV show starts a fresh cycle (no `tv_played` key yet).
- Not changed: the combo Folder slot still asks the "No Repeat" question (a random folder slot is always No Repeat since 3.1.70).

## 3.1.70
- Fix: a Combo Block Folder slot (random + No Repeat) could queue the same file twice. Found in a 16-hour carousel soak: the queue held "Cartoon College - Bugs Bunny Celebrity Chef" at two positions while six of the folder's 15 files were still unplayed. Root cause: `ComboQueueBuilder.build_one_slot` never received the queue it appends to, so `_fetch_folder_items` called `FolderQueueBuilder.build` without `queued_files`, and a folder's played list is only updated when a file is consumed (the same class of defect as #18, in the combo slot path).
- `build_one_slot(channel, slot_index, host_queue=None)` now takes the queue; `_fetch_slot_items` and `_fetch_folder_items` pass it down. The slot's files already in the queue (matched by `_folder_state_id`) are excluded from the draw. service.py `_handle_combo_slot` and carousel.py `_handle_combo_slot_pop` pass their queue; scheduler.py `fire_block` passes the items gathered so far.
- When every file still unplayed in the cycle is already queued (No Repeat + recycle), the next cycle starts immediately (played list cleared via `record_folder_file_played(id, None)`) and the draw avoids queued files. Only if the folder has no more files than the queue holds is a repeat allowed.
- New debug log line per draw: `[ComboQueueBuilder] folder slot <id>: drew '<file>' (excluded N queued file(s))`.
- Replay simulation (random + No Repeat, pools 3/6/15, queue 3/6, 4000 draws each): duplicates in queue 1232-2541 before, 0 after.
- Not changed (found while checking): `build_combo_tv_slot` draws a random episode with no memory of what is queued or played, so a small random TV slot can repeat. The movie slot marks files played when drawn and is unaffected. Candidate for 3.1.71.

## 3.1.69
- Fix: editing a TV or Serial channel so that its show list changed (a show added or removed, shows reordered, or an episode exclusion changed) rebuilt the queue from a zero cursor, so every show restarted at S01E01 and a Serial channel restarted at its first show. The path was unchanged since at least 3.1.43. `update_channel` now calls the new `ChannelManager._capture_edit_positions()` before the rebuild: it records each kept sequential show's next queued episode and the show at the head of the queue, and the rebuild resumes from them (`starting_points` copy + `start_show_index`; the saved definition is not modified). New shows have no queued episode and start at S01E01. If the head show was removed, the next surviving show continues. Explicit starting episodes chosen in the wizard override the captured ones. Edits that do not change the show list, and mode changes (randomize/recycle/type, which still wipe state), are unaffected. Serial shows already finished stay finished; with recycle they return after the last show.
- Feature: the Serial wizard now offers "Set a starting episode for <show>?" for each show new to the channel (every show when creating). Shows already in the channel keep their position. The season/episode picker is now the shared `ask_starting_episode()` in ui/dialogs.py, used by both the TV and Serial wizards (the TV wizard's inline copy was removed; behaviour unchanged). No new strings.
- Not changed: a queue-size-only or interleave-only edit still rebuilds from a zero cursor (same root cause, not part of this fix).

## 3.1.68
- Fix: the Visibility question (all TV, Movie, Folder and Serial wizards) showed the list "Yes / No / Done", which did not say what it meant. It now asks **Show this channel in your channel list?** with **Show / Hide / Cancel**. The choice logic is unchanged (Show = visible, Hide = hidden, Cancel/Back leaves the wizard); the carousel and source guards still apply. Strings #32221, #32222 and #32223 were restored (they had been removed as unused in 3.1.62 although they were the intended labels), and #32933 "Cancel" was added.
- Change: the Folder wizard no longer asks "No Repeat" after the playback order. A Random folder always plays every file once before any repeat, so the answer was redundant: Random now saves no-repeat on, Sequential saves it off. (The Combo Block folder-slot wizard still asks it; unchanged.)
- strings.po: 540 entries.

## 3.1.67
- Fix: the Combo Block movie-slot "Exclude Movies?" question showed its heading text twice (same mistake fixed in the Movie wizard in 3.1.63); the body now uses #32594. No other change.

## 3.1.66
- Fix: random TV and Movie channels could re-queue an item that was already waiting in the queue, or the one just played, when a new cycle started (the same problem fixed for folders in 3.1.57). The movie back-to-back guard only looked at the queue being built, which is empty for a one-item replacement, and the TV random draw after a reset picked from the whole show. Replacements now draw first from items that are not in the host queue and are not the item just consumed, then relax those two rules only when the pool leaves no other choice (a pool no larger than the queue size cannot avoid repeats). Every item is still played once per cycle: skipped-over items stay in the cycle and are drawn later.
- Applies to: random Movie channels, random TV shows in Round Robin channels (replacement and skip), and Movie / TV sources interleaved into another channel (the host queue is used for the check). Sequential, Serial, Folder and initial queue builds are unchanged.
- Code: new `ChannelManager._queued_ids()` helper; `_replacement_movie` and `_replacement_tv` pass the host queue and the consumed item to the movie builder (`MovieQueueBuilder.build_one(queued_ids, consumed_id)`) and to `_pick_one_ep_no_slot_advance(queued_ids, consumed_id)`. All new parameters are optional.
- Simulation (3000 replacements, queue 10): 15 movies, 595 duplicates in queue and 145 immediate repeats before, 0 and 0 now; 30 movies 163/20 before, 0/0 now. Random TV show of 15 episodes: 632 duplicates before, 0 now.
- No string changes.

## 3.1.65
- Cleanup: removed the stray `<settings version="2"/>` element from the addon.xml metadata extension. Kodi never read it; settings are defined entirely by resources/settings.xml (unchanged).
- Cleanup: Auto-Create Channels no longer reads the nonexistent `default_recycle` setting (two places); channels always recycle. The settings-confirmation screen now takes its values from `_get_defaults()` instead of repeating the same setting reads (removes duplicate code).
- Fix: the Auto-Create settings-confirmation screen showed the paragraph from #32645 ("For each genre, an interleaved channel will be created...") after "Recycle:" because its Yes constant pointed at #32645 instead of #32607 ("Yes"). It now shows "Recycle: Yes". The unused `_S_NO` constant (also pointing at a wrong string) was removed.
- No strings.po changes.

## 3.1.64
- New: channel names must be unique. Right after the name is entered in Create Channel or Edit Channel, the name is checked against every other channel (hidden channels and Combo Blocks included; case and surrounding spaces ignored). If it is taken, a message (#32932, "A channel named '{0}' already exists. Please choose a different name.") is shown and the name box opens again with the entered text so it can be changed; Cancel leaves the wizard. Editing a channel and keeping its own name is allowed.
- New public `ChannelManager.channel_name_exists(name, exclude_id="")`; the create and edit wizards share one helper `_ask_channel_name` in ui/channels.py (replaces two inline name prompts). Auto-Create already skipped names that exist and is unchanged.
- Existing channels that already share a name are not touched; they only get the check the next time one is edited and renamed.
- strings.po: added #32932 (536 entries).

## 3.1.63
- Fix: the Movie wizard's "Exclude Movies?" question showed the heading text twice; the body now uses #32594 ("Exclude specific movies from this channel? Excluded movies will never play."), restored in strings.po.
- Fix: removing a Combo Block slot now asks with #32895 ("Remove Slot {0}?"), restored with a {0} placeholder instead of the unfinished "{slot name}" text. It replaced a hand-built "Remove Slot [TV] Show?" line.
- New: editing a Combo Block that is already used by another channel (interleave or schedule) now shows #32877, rewritten to match what the code does: "This Combo Block is used by '{0}'. Items already in that channel's queue will not change; your edits apply to items added from now on."
- Fix: the Combo Blocks separator in the Schedule wizard's source picker used the nonexistent #32822 and showed "── ──"; it now uses #32866 "Combo Block", as the Interleave wizard does.
- Not restored on purpose: #32878 (combo owned by another channel). The interleave and schedule pickers already leave out combos owned by other channels, so the message could never be reached. #32811 (sort-alphabetically confirm) left as is, per request.
- strings.po: 532 -> 535 entries. Re-scan of every .py/.xml/.json/.txt file: the only strings with no reference are #32840-#32843 (kept for the planned schedule ticker); every referenced ID exists.

## 3.1.62
- Cleanup: removed 90 unused strings from strings.po (622 -> 532 entries, numeric order kept). Each ID was checked against every .py, .xml, .json and .txt file in the addon (code, settings.xml, skins, addon.xml); none of the removed IDs is referenced anywhere. They were leftovers from earlier versions: the pipe-delimited option lists replaced in 3.1.60 (#32067, #32087, #32089), the old interleave remove/circular/nesting dialogs, soft-stop schedule text, recycle and "when all played" options, the old filter/surprise-me/exclusion texts, backup/restore and cache menu leftovers, #32824 and others. No code change.
- Kept on purpose: #32840-#32843 ("Tonight at", "Tomorrow at", "{0} at {1}", "Special programming on"), which are unreferenced today but are the phrases for the planned schedule ticker overlay.
- Found, not fixed here: ui/schedule_wizard.py line 429 builds the Combo Blocks separator in the source picker from #32822, which does not exist in strings.po (it never did), so the separator shows as "── ──". Reserved for its own fix.

## 3.1.61
- Fix: the four string settings with an empty default (Channel icon folder, Shared path, Backup path, ffprobe path) failed to load in 3.1.60 and logged "error reading the default value" repeatedly. The new settings format needs `<allowempty>true</allowempty>` in a string setting's constraints when the default is empty; added to all four.
- Fix: the cache-age settings (Settings > Cache) were only written when the addon was opened or a cache was rebuilt, so after a Kodi start they still showed their default 0. The service now writes them at start-up (`_service_ensure_caches`) and refreshes them once an hour from its tick loop (`_tick_cache_ages`), so they are right when Settings is opened.
- No string changes.

## 3.1.60
- Fix: the "Library cache age" and "Songs Cache Age" settings (Settings > Cache) never showed anything: they were empty legacy text fields that opened a keyboard, and nothing in the code ever wrote to them. They now display the age of each cache in whole days as read-only (disabled) integer fields. The new `LibraryClient.publish_cache_ages()` writes them (only when the value changed; a missing cache shows 0). It is called at the end of `build_local_cache` and `build_songs_cache` and on every addon start-up in `addon.py` main().
- Change: resources/settings.xml converted from the legacy format to the current Kodi settings format (section/category/group, version 1) so a setting can be disabled (`<enable>false</enable>`). All 52 setting ids, labels, defaults and category order are unchanged, so saved user values carry over; Enum settings (Coming Up Next corner and lead time, Logo corner, size and opacity) keep their saved index values and are now integer settings with option lists. Action buttons keep their close-on-click behavior, and the ffprobe scan button is still Windows-only.
- strings.po: added #32918-#32931, the option labels for those lists (Top Left, Top Right, Bottom Left, Bottom Right, 1-5 Minute(s), Small, Medium, Large, Low, High); they replace the literal `values=` text in the old settings.xml. Numeric order kept.
- Revert path if the settings page misbehaves: 3.1.59 has the legacy settings.xml.

## 3.1.59
- Remove: the unused "Show Ticker" setting (`show_ticker`, #32049) and the lower-third ticker remnants. Nothing in the code ever read the setting. Removed: the setting from settings.xml; the hidden ticker control group 400 (controls 400-404) from the Default, Confluence and Estuary SmartChannels_Main.xml skin files; the `setVisible(False)` call on control 400 and the ticker comments in ui/side_panel.py; and the unused strings #32049, #32720, #32721 and #32722 from strings.po (numbering now has gaps, numeric order kept). No playback behavior change. Verified: all three skin files parse, every control id the Side Panel uses (100, 200, 300, 301) is still present in each skin, and no navigation reference points to a removed control.

## 3.1.58
- New: removing an interleave source now offers to reset it. In Manage Interleave, after a single source is removed (Edit/Remove Sources) a yes/no dialog asks whether to reset that source (#32916); after Remove All, one yes/no dialog asks whether to reset all the removed sources (#32917). Yes resets each one exactly as Reset Channel does, so the next time it is used as a source it starts from the beginning instead of continuing from where the earlier interleave left its cursor. No leaves the source untouched. Combo Blocks keep their existing ownership/reset handling and are not offered the dialog.
- Refactor: new public `ChannelManager.reset_channel(channel_id)` holds the Reset Channel steps (clear cursor and folder cycle, clear resume points, empty the queue, reload, rebuild the queue). `Router.reset_channel` (context-menu Reset Channel, after its own confirmation) and the interleave wizard both call it; the inline copy in router.py is removed.
- strings.po: added #32916 and #32917 (numeric order kept).

## 3.1.57
- Fix: random Folder channels were drawing in three fixed groups (3.1.55). With a queue of 10 and 15 files, each new cycle was seeded only from the files outside the queue, so the same 5 files always played together in the same group order (186 five-item stretches in an overnight carousel run contained only 3 distinct sets). A cycle now starts from the whole folder and each draw is random among the not-yet-drawn files that are not already in the host queue and are not the item just consumed; skipped files stay in the cycle for a later draw. Every file is still drawn once per cycle (no repeat before all have played), the queue never holds a duplicate when the folder is larger than the queue, and the order is no longer locked. Existing saved cycle state remains valid; Reset Channel starts clean.
- No string changes.

## 3.1.56
- Change: a channel with Carousel enabled can no longer be hidden. Both paths are guarded and show the new string #32915, leaving the channel visible: the context-menu Toggle Visibility (router.py `toggle_channel_visibility`) and the wizards' visibility step (`ask_visibility` in ui/dialogs.py, used by the TV, Movie and Folder wizards). Previously the wizard silently switched Carousel off when Hidden was chosen, and the toggle hid the channel while leaving Carousel enabled. To hide a carousel channel, disable its Carousel in the wizard first, then edit again and choose Hidden. Channels that cannot have a carousel (Serial, Audio, Party, Combo) are unaffected.
- strings.po: added #32915 (numeric order kept).

## 3.1.55
- Fix: random Folder channels repeated files before the whole folder had played (3.1.54). The initial queue is built without the random cycle, so the first cycle started from the full folder and could redraw files that were just played or were still waiting in the queue (15 files, queue of 10: Pete Puma and Animated Pastorals came back while three files had never been queued). A new cycle is now seeded from the files not in the host queue and not the item just consumed (`FolderQueueBuilder.build_one` takes `consumed_file`; `ChannelManager._replacement_folder` supplies it). If the queue already holds every file the whole folder is used and the most recent file is avoided. Also applies after Reset Channel, which clears the cycle and rebuilds the queue.
- Existing cycle state saved by 3.1.54 is still valid; a stale list simply finishes and the next cycle seeds correctly. Use Reset Channel to start clean.
- No string changes.

## 3.1.54
- New: random Folder channels are always Random/No Repeat. `FolderQueueBuilder.build_one` keeps a per-folder list of files not yet used this cycle (state key `{id}:__folder_cycle__`, public `ChannelManager.get_folder_cycle` / `set_folder_cycle`), draws from it at random, prefers files not already waiting in the host queue, and refills with the whole folder when empty — every file is used before any repeats, and consumed, skipped and carousel-popped items all advance the cycle. This also covers a folder interleaved as a source into another channel. Files removed from the folder are dropped from the list; new files join at the next refill. Sequential folders are unchanged.
- Change: `clear_cursor` (used by Reset Channel and edit invalidation) now also clears the folder cycle so a reset starts a fresh cycle.
- The wizard's "No Repeat" question is left in place; it still governs initial builds/top-up in `FolderQueueBuilder.build`.

## 3.1.53
- Fix: Folder channels now always recycle on 1-for-1 replacement. Previously the replacement was built with the channel's own queued files excluded, so when every file in the folder was already in the queue (folder smaller than the queue size, or any interleaved folder source) no replacement was returned: interleaved folder items were not replaced and a folder carousel pop would have been aborted. New `FolderQueueBuilder.build_one(channel, host_queue)` uses the queue the item will be appended to as the authority: sequential continues with the file after the last one from that folder (wrapping); random picks a file not already queued from that folder, or any file except the most recent when all are queued. `ChannelManager._replacement_folder` calls it; `get_one_replacement` passes the host queue through for both own and interleaved folder items. Initial builds, interleave weaves, combo folder slots and top-up (`FolderQueueBuilder.build`) are unchanged.
- Refactor: `FolderQueueBuilder._make_item` / `_default_duration` replace the item-building and default-duration code that was inline in `build` (same item, no duplication with `build_one`).
- New: visible Folder channels can enable Carousel. The Folder wizard now asks the carousel questions (same `ask_carousel` as the Movie wizard; hidden channels skip the step) and `carousel.py` accepts "folder" in its channel-type guard. The carousel's generic replacement path now passes the in-progress queue to `get_one_replacement`.
- No string changes.

## 3.1.52
- Change: interleave sources must be hidden channels. The Manage Interleave source picker (ui/wizards/interleave.py) now lists only hidden channels (a carousel flag on a hidden channel still disqualifies it; Combo Blocks, always hidden, are unchanged). The "carousel channels are excluded" notice (#32824) is removed from that wizard — visible channels are excluded as a group, so it was misleading. When no eligible source exists the wizard shows the new string #32914 ("Interleave sources must be hidden channels...") and ends. Existing visible sources are left as they are and can still be edited or removed.
- Change: a hidden channel that is in use as an interleave or schedule source can no longer be made visible. Both paths are guarded: the context-menu hide/unhide toggle (router.py `toggle_channel_visibility`) and the wizards' visibility step (`ask_visibility` in ui/dialogs.py, now given the manager by the TV, Movie, Folder and Serial wizards). Both show the new string #32913. A source that is already visible is untouched.
- Refactor: new public `ChannelManager.get_source_usage(channel_id)` returns the interleave or schedule relationship for a source, or None. `ask_carousel` (ui/dialogs.py) used its own inline copy of the same two scans; it now calls the new method, with the same dialog and result as before.
- strings.po: added #32913 and #32914 (numeric order kept). #32824 is no longer referenced by the code and is left in place.
- Build On Top of 3.1.51 (new feature; 3.1.51 confirmed working). The 3.1.52 CUN runtime change that was tried and withdrawn is not included.

## 3.1.51
- Fix: Coming Up Next named the wrong "next" item when a scheduled block was about to play. Two causes in `_get_next_episode` (service.py): (1) a block fired onto the disk queue is not in the in-memory queue until the boundary reload, so the overlay read the stale queue and named the next regular episode; (2) an explicit rule skipped `_schedule_id` items whenever the current item was regular content. The rule is removed, and when a block reload is pending the overlay uses the block's leading items from the disk queue (via the public `get_channel_queue`).
- Silent items are still never named as the next item (unchanged). The "Suppress Coming Up Next during silent interleave items" setting (#32074) still governs only the overlay while a silent item is playing (unchanged). If every block item is silent, the overlay falls back to the next regular item.
- Build On Top of 3.1.50 (separate defect; 3.1.50 skip fix confirmed working from log).

## 3.1.50
- Fix: a scheduled block item skipped with the OSD Next button received a 1-for-1 replacement (an extra target-channel episode was appended) and was never counted toward its block, leaving the block's `active_block` state stale. Root cause: `_handle_skip` (service.py) did not check `_schedule_id`, unlike natural end and the carousel. Skipped block items are now popped with no replacement and counted via `_count_block_item(..., "skip")`, after the queue write. `_schedule_id` takes precedence over `_interleaved` (combo-sourced block items carry both). Skipped target-channel and interleaved (non-block) items still get their normal 1-for-1 replacement. The skip log line labels items BLOCK / COMBO / primary.
- Build On Top of 3.1.49 (first attempt; root cause confirmed from log). A stale `active_block` already in state.json is not cleared retroactively.

## 3.1.49
- Fix: Add Schedule wizard (ui/schedule_wizard.py) now treats the channel it was opened from as the target — the Target picker is no longer shown. Combo Block, Audio and Party channels are never offered as targets (Combo Blocks are source-only). When editing a schedule, the picker is still shown and the schedule's current target stays selectable.
- Fix: removed the "No other channels available as source." dialog (#32771) that appeared whenever a carousel channel existed, before the source picker. That string now appears only in the one case it describes: no eligible source exists, and the wizard then ends.
- Change: schedule sources must be Hidden channels (plus Combo Blocks, which are always hidden, in their own group). Visible channels are no longer offered as sources. When editing, a schedule's existing source stays selectable even if it is a visible channel, so an edit never silently swaps it.

## 3.1.48
- Feature: hidden channels are tagged in the channel list when Show Hidden Channels is enabled — in both the standard Kodi channel list (router.py `list_channels`) and the Side Panel channel pane. One public helper, `ChannelManager.get_channel_list_label()`, builds the label for both. The tag text is string #32230 (`[H]`), added to strings.po by Mark's instruction.
- strings.po: #32228 and #32229 (missing-durations log strings) were stranded at the end of the file after #32912; moved into numeric order after #32227, with #32230 following them. No text changed on #32228/#32229.
- strings.po: #32783 sat before #32781/#32782; moved after #32782. All strings are now in numeric order. No text changed.

## 3.1.47
- Fix: choosing a new starting episode in Edit Channel > Select Starting Episodes did nothing. Root cause: `update_channel` saved `starting_points` into the channel definition, but only a fresh queue build reads them, and a starting-point-only edit does not trigger a rebuild. `reset_show_to_start` is generalised into `set_show_start(channel_id, show_id, start_episode_id)` (channel_manager.py; `reset_show_to_start` is now a thin wrapper), which splices the show's queue slots from the chosen episode, wrapping past the last episode, and sets `ep_pos` to continue after it. `update_channel` calls it for each show the user explicitly set in the wizard (sequential TV shows only; shows left on "Keep" are untouched).
- Build On Top of 3.1.46 (separate defect from the Reset Show fix; 3.1.45/3.1.46 not yet tested).

## 3.1.46
- Fix: Edit Channel > Select Starting Episodes (TV wizard) showed "Keep: S01E01" and pre-selected S01E01 for every show. Root cause: the wizard read the per-show state record (`get_show_state`), which playback does not advance in 3.x (and which Reset Show sets to S01E01). The wizard now asks the new public `ChannelManager.get_show_next_queued_episode()`, which returns the show's first queued episode, so the Keep label and the preselected season/episode reflect the show's actual next episode. Shows with no queued episode fall back to "Keep current position" (#32599). No new strings. Combo block wizard (reads the saved starting point) is unchanged.

## 3.1.45
- Fix: Reset Show produced queue items missing `tvshowtitle`, `show_id`, `_show_id`, `channel_id`, `_channel_id`, `duration`, `_span` and `_span_ids` (side panel showed no show name). Root cause: the 3.1.43 splice inserted raw library episode dicts instead of normalised queue items. The splice in `reset_show_to_start` (channel_manager.py) now builds each replacement with `normalize_ep`, the same path as the normal queue build, and skips (and logs) episodes with no duration.
- Fix: after a splice, `ep_pos` for the reset show was cleared, so the next 1-for-1 replacement would have re-queued S01E01. It is now set to the position after the last spliced episode (randomised shows record the spliced episodes in `ep_played` instead).
- Build On Top of 3.1.44: root cause confirmed, only the implementation detail was wrong.

## 3.1.44
- Feature: episode context menu in the Side Panel. Pressing C/Menu on a TV episode in the right pane offers Reset Show (#32353); movies, audio, folder and interleaved items show no menu.
- Fix: the Reset Show item in the standard Kodi episode context menu used #32334 ([Remove Interleave]); now uses #32353 (Reset Show).

## 3.1.43
- Fix: Reset Show rebuilt the whole queue from the cursor, which advanced other shows by the size of the old queue. `reset_show_to_start` now splices the existing queue in place, replacing only the reset show's slots, and no longer deletes or regenerates the queue file.

## 3.1.42
- Fix: Combo Block channels could be played directly if the plugin URL was constructed manually or called from an unexpected path. Reinstated guardrail in `play_channel()` in router.py — rejects combo channels with string #32896 before any playback logic runs. Context menu already omits Play for combo channels; this guard closes the back-door path.

## 3.1.41
- Fix: serial channels with a combo block interleaved were not appending replacements for primary items. Root cause: `_replacement_serial()` in channel_manager.py determined the next serial episode by inspecting `queue[-1]` (the tail item), but when combo block items are interleaved they sit at the tail after every primary item. The combo item's show_id belongs to the combo source, not the serial channel's show list, so the tail show lookup failed, the serial position was lost, and no replacement was appended. Fixed by scanning backward through the queue for the last non-interleaved item (`not item.get("_interleaved")`) instead of blindly using `queue[-1]`. This correctly ignores interleaved items from any source (combo, TV, movie, folder) and finds the true last serial episode as the anchor for the next replacement.

## 3.1.40
- Fix: Blank entry in Backup and Restore settings (label #32913, action browse_backup_path) was missed in 3.1.39 and still appeared in the UI, taking the user to the channel list when selected. Removed from settings.xml.

## 3.1.39
- Fix: Settings UI showed two entries for Channel Icon Folder and two for Backup Path — the text field plus a redundant [Browse...] action button. Removed the companion action settings from settings.xml, removed browse_icon_folder() and browse_backup_path() from router.py, removed their dispatch entries from addon.py, and removed string #32913 from strings.po. Both settings now behave like Shared Storage Path: a single editable text field, no browse button.

## 3.1.38
- Fix: Season 0 / Specials could not be added as exceptions in the channel wizard's Add Exceptions dialog. Root cause: `e.get("season")` returns `0` for Season 0, which is falsy in Python, so the list comprehensions in `build_episode_filter` and `build_episode_exclusions` (dialogs.py) silently excluded all Season 0 episodes. Fixed both occurrences: `if e.get("season")` → `if e.get("season") is not None`.
- Fix: Channel Icon Folder and Backup Path settings could not be cleared or typed into freely because they used Kodi's `type="folder"` widget, which has no delete/clear affordance. Changed both settings to `type="text"` so the user can edit or clear the path directly.

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
