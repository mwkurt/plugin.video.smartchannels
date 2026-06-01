# Smart TV Channels — Changelog

\---

## Version 1.0.6

### Changes

**Removed MySQL/Network Settings (settings.xml)**

* Removed the Network settings category (MySQL host, port, user, password, database).
* These settings were never read by any addon code. Kodi handles its own database
connection transparently via advancedsettings.xml — the addon queries the library
via JSON-RPC regardless of whether Kodi uses SQLite or MySQL.

\---

## Version 1.0.5

### New Features

**Clean Channel Names (channels.py)**

* Channel list now shows clean channel names only — status indicators removed from labels.
* New "Channel Info" context menu item (first in list) shows a formatted dialog with: channel type, rotation mode, playback/recycle setting, show list (TV) or movie count (Movies), queue depth, and interleave configuration.

**Backup \& Restore (router.py, settings.xml)**

* New "Backup \& Restore" category in Settings.
* "Backup Addon Data" — copies channels.json, state.json, and settings.xml to a timestamped folder (SmartChannels\_Backup\_YYYYMMDD\_HHMMSS) in a user-selected destination.
* "Restore Addon Data" — browse to a backup folder, select which files to restore. Warns before overwriting. Notes if Kodi restart is needed after restoring settings.xml.
* Queue files excluded from backup — they are rebuilt automatically on next channel launch.

**Playlist Show Names (player.py)**

* TV episode ListItem labels now include show name: "Show - S01E14 - Episode Title". Visible in Kodi playlist overlay during playback.
* Fixed tvshowtitle field mismatch (was reading "showtitle", now correctly reads "tvshowtitle").

\---

## Version 1.0.4

### Bug Fixes

**Queue Refill (channel\_manager.py)**

* Fixed queue top-up producing too few items after multiple refill cycles. The safety guard compared the absolute `show\_index` (which grows with each refill) against a relative limit, causing early loop exit. Fixed to use a per-call iteration counter instead.

**Manual Starting Point Picker (channels.py)**

* Fixed the "Set Starting Points Manually" option being unreachable in the channel creation wizard. The manual picker block was incorrectly nested inside the Surprise Me branch due to `if` vs `elif` indentation, making it silently skip when selected.

**State.json Cleanup — played\_ids Bloat**

* Sequential mode: `played\_ids` in the show state entry no longer accumulates. It is always written as `\[]` since position tracking uses `next\_episode\_id` exclusively.
* Random mode: `played\_ids` in the show state entry no longer accumulates. No-repeat tracking is handled entirely by the queue tail (`\_\_queue\_tail\_\_` → `played\_ids`), which correctly resets per cycle. Two separate code paths were fixed: `\_advance\_random` in `channel\_manager.py` and `advance\_state` in `service.py`.

**Exact Resume Feature (service.py, channel\_manager.py)**

* Resume was implemented in `SmartPlayerMonitor` (player.py) which is garbage-collected when the plugin call returns. Moved full resume implementation to the long-lived `SmartPlayer` in service.py.
* Fixed `getTime()` raising "not playing any media" in `onPlayBackStopped` by using poll-saved position instead.
* Fixed `onAVStarted` race condition where `\_current\_ep` was not yet set when the resume check ran. Now uses a background thread (`\_do\_resume\_check`) that identifies the playing episode directly from the queue file rather than waiting for `\_current\_ep`.
* Fixed resume dialog appearing after episode had already started playing. Player now pauses before showing dialog, then seeks and unpauses.
* Fixed player staying frozen after resume seek. Replaced `isPaused()` toggle with `xbmc.executebuiltin("PlayerControl(Play)")`.
* Fixed `getSetting("resume\_on\_stop")` returning wrong value at service startup (Kodi settings not fully loaded yet). Settings are now read lazily on first channel launch.
* Fixed resume position not updating on Android/Shield. Poll timer now queues the save via `\_pending\_resume\_save` for the main service thread to write, since `xbmcvfs` SMB operations must run on the main thread on Android.

**Resume Data Lifecycle**

* Simplified to single-file: `save\_resume\_position\_local` now writes directly to state.json (shared path) instead of a separate `resume\_backup.json`. Eliminates the promote-on-stop step and enables crash recovery from the last poll save.
* Resume entries are now correctly cleared in all three scenarios: natural episode finish (via `set\_now\_playing` detecting episode transition), skip (via skip loop in `\_check\_now\_playing`), and playlist end (via `onPlayBackEnded`).
* Channel deletion now cleans up all `resume:channel\_id:\*` keys from state.json.
* File path comparison used instead of `episodeid` for episode transition detection — more reliable across TV and movie items.

**Orphaned Shared Data Warning**

* Suppressed false-positive warning on secondary clients. A missing local `channels.json` with shared storage configured is the expected state for secondary clients, not an error.

**Playlist Labels (player.py)**

* TV episode `ListItem` labels now include the show name: `"Show - S01E14 - Episode Title"`. Previously only the episode title was shown in the Kodi playlist overlay during playback.
* Fixed `tvshowtitle` field name mismatch (`"showtitle"` vs `"tvshowtitle"`) in both the `InfoTagVideo` path and the `setInfo` fallback.

\---

## Version 1.0.3

* Surprise Me starting point option
* Shuffle Rotation Try Again loop
* Count Per Interleave setting
* Exact Resume infrastructure (settings, channel\_manager helpers)
* Management Items Toggle setting
* Show interleaved items in channel detail view

## Version 1.0.2

* Interleave bug fixes (max/needed, jitter simulation, TV→TV nested guard)
* Movie deck fix (interleave\_order filtered against all\_available)
* Upcoming list labels for all four interleave combinations

## Version 1.0.1

* Multi-client shared SMB storage (Group G)
* Queue building, top-up, refill threshold
* TV episode interleaving round-robin
* Movie channel interleaving
* Stop/resume on interleaved movies
* Reset Channel to Start context menu
* Reset individual show to S01E01 context menu
* num\_upcoming\_programs setting
* Delete All Addon Data on SMB

## Version 1.0.0

* Initial release
* Smart TV channel creation with round-robin episode interleaving
* Persistent queue and state files
* Continuous playback with automatic queue top-ups
* Kodi 21 Omega (Python 3)

