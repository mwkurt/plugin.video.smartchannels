# plugin.video.smartchannels
# resources/lib/channel_manager.py
#
# OWNS:   Channel definitions (channels.json), queue files, state (state.json),
#         cursor API, 1-for-1 replacement, combo unit tracker, library access.
#
# NEVER:  Playback callbacks (service.py), playlist management (service.py),
#         start_channel / now_playing (player.py), UI rendering (ui/*),
#         direct executeJSONRPC calls (library.py only).
#
# Architecture rules enforced here:
#   - No private method calls from outside this class.
#   - No duplicate logic from channels/base.py or library.py.
#   - All user-visible strings must come from strings.po (not hardcoded here).
#   - All queue file I/O goes through write_channel_queue / get_channel_queue.
#
# Version: 3.0.0
# Spec ref: §4, §7, §8, §11

from __future__ import annotations

import contextlib
import copy
import os
import random
import sys
import threading
import time
import uuid
from typing import Any, Optional

import xbmc
import xbmcaddon
import xbmcvfs

from resources.lib.library      import LibraryClient
from resources.lib.utils import journal, write_lock
from resources.lib.utils.logger import log
from resources.lib.utils.paths  import (load_json, load_json_strict,
                                        JsonReadError, save_json,
                                        resolve_path, shared_root,
                                        normalize_share_path, path_join,
                                        remove_local_copy, local_queue_files,
                                        channel_lock_files)
from resources.lib.channels.interleave import (
    plan_primary_count  as plan_interleave_primaries,
    tv_slot_takes_turns,
    tv_turn_size,
)
from resources.lib.channels.base import (
    normalize_ep        as _normalize_ep_fn,
    normalize_movie     as _normalize_movie_fn,
    get_available_episodes as _get_available_episodes_fn,
    get_filtered_episodes  as _get_filtered_episodes_fn,
)

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------
ChannelDef  = dict
EpisodeInfo = dict


class ChannelManager:
    """Central brain: channel CRUD, queue building, state, cursor, replacement."""

    CHANNELS_FILE  = "channels.json"
    STATE_FILE     = "state.json"
    SCHEDULES_FILE = "schedules.json"

    # A channel lock whose timestamp is further than this many seconds from
    # this device's clock (either direction) counts as dead.  Failing open on
    # a wrong clock means "no lock", which is the pre-3.1.109 behaviour.
    LOCK_STALE_SECONDS = 180
    # A lock file this old is a leftover (the owner was closed without
    # releasing it) and is swept.  Much longer than LOCK_STALE_SECONDS so
    # clock differences between devices can never remove a live lock.
    LOCK_SWEEP_SECONDS = 3600

    # Zero cursor — used for fresh builds and as a safe default.
    # Keys: show_slot (int), ep_pos (dict), ep_played (dict), slot_owed (dict).
    # spec §4.3
    _ZERO_CURSOR = {
        "show_slot": 0,
        "ep_pos":    {},
        "ep_played": {},
        "slot_owed": {},
    }

    # Shared path last reported in the log, so the message is written once
    # per Kodi session (and again only if the path changes).
    _shared_logged = ""

    # One read-merge-write of state.json at a time within this process
    # (service threads and the carousel all save state).
    _STATE_LOCK = threading.RLock()

    # The rename lock on the shared folder (3.1.148, utils/write_lock.py).
    # One per process; rebuilt when the folder, the setting or the device
    # changes.  Waits are short: a busy lock means "write anyway", never
    # "freeze playback".
    _WRITE_LOCK     = None
    _WRITE_LOCK_KEY = None
    _WRITE_LOCK_MU  = threading.Lock()
    WRITE_LOCK_WAIT_MS       = 2000   # state.json saves and carousel writes
    WRITE_LOCK_CLAIM_WAIT_MS = 2000   # the check-and-write part of a claim

    # state.json snapshots: one is written at most every STATE_BACKUP_SECONDS,
    # into one of STATE_BACKUP_SLOTS files used in turn, so the last
    # SLOTS x SECONDS (24 hours) of good state stay on the share.
    STATE_BACKUP_SECONDS = 10800
    STATE_BACKUP_SLOTS   = 8
    _state_backup_at     = 0.0

    # One more snapshot per day, state.day<N>.json, N cycling through
    # STATE_DAILY_SLOTS days, so a loss that is noticed late can still be
    # recovered from.  Written by the first clean save of each day.
    STATE_DAILY_SLOTS = 14
    _state_daily_on   = -1

    # Evidence for the journal (3.1.142): what this process last knew about
    # the shared carousel clocks and about state.json itself.  Process-wide,
    # like the backup clocks above.  Logging only: nothing here changes what
    # is read, written or decided.
    _clock_seen      = {}      # "<chan>:carousel" -> [clock, who, wall time]
    _clock_regressed = {}      # "<chan>:carousel" -> lower clock already reported
    _behind_noted    = set()   # (key, clock) pairs of memory_behind already reported
    _stamp_seen      = None    # [mtime, size] of state.json, newest known here
    _stale_count     = 0
    _write_seq       = 0
    _clk_logged      = None    # clock table of the last state_write line
    _watch_wall      = 0.0
    _watch_mono      = 0.0
    _table_at        = 0.0
    _unreadable_at   = 0.0

    # Timing master (3.1.146).  Process-wide because the service makes a
    # fresh ChannelManager for every call.  Keyed by this device's id so that
    # several devices in one test process stay apart.
    _master_obs      = {}      # device id -> what it saw of the master's file
    _won_at          = {}      # channel id -> time of this process's last won claim (3.1.147)
    _last_clock      = {}      # channel id -> carousel clock this process last read from the channel's file or wrote (3.1.147)
    _queue_stamps    = {}      # channel id -> [mtime, size] of its queue file at the last clock write (3.1.147)
    _master_beat     = {}      # device id -> wall time of its last heartbeat
    _skips           = {}      # follower_skip counter (since, per channel)
    _conflict_logged = set()   # (device id, other master id) already journalled

    # Skipped items (no duration) are written down in batches: a pass that
    # skips hundreds of items must not rewrite state.json and
    # missing_durations.txt once per item.  Each file is recorded once per
    # Kodi session.  An entry is written at once when nothing was written in
    # the last MISSING_FLUSH_SECONDS (a single skip is not delayed); entries
    # arriving faster than that wait and are written together when
    # MISSING_FLUSH_MAX are waiting, or by a timer MISSING_FLUSH_SECONDS later.
    MISSING_FLUSH_MAX     = 50
    MISSING_FLUSH_SECONDS = 15
    _missing_flushed_at   = 0.0
    _MISSING_LOCK    = threading.Lock()
    _missing_seen: set  = set()      # (channel_id, file) recorded this session
    _missing_pending: dict = {}      # channel_id -> [entry, ...]
    _missing_lines: list   = []      # missing_durations.txt lines waiting
    _missing_timer         = None

    # Channels whose last queue rebuild was refused because the new positions
    # could not be saved (state.json unreadable).  The edit screens read this
    # through rebuild_failed() to tell the user.
    _rebuild_failed: set = set()

    # Channels whose last Edit was refused, with nothing saved, because the
    # channel's queue could not be read (another device was writing it).
    # The edit screens read this through edit_blocked().
    _edit_blocked: set = set()

    # A state.json that is missing while channels exist is a failed read for
    # this many seconds (another device is replacing the file), then it is
    # taken as really gone.  _absent_since: path -> when it was first seen
    # missing in this Kodi session.
    STATE_ABSENT_GRACE = 120

    # Wait before the episode list is fetched again when a position is past
    # its end (see _next_candidate_ep).
    WRAP_RECHECK_MS = 500
    # Shows that wrapped back to their first episode a moment ago, as
    # {(channel_id, show_id): time}.  _guard_cursors reads it so a wrap is not
    # reported as a lost position.  Shared by all instances in this process.
    _RECENT_WRAPS: dict = {}
    WRAP_NOTE_SECONDS = 120
    _absent_since: dict = {}

    # A saved cursor that lost at least this share of its shows, or of its
    # accumulated positions, is logged and the cursor it replaced is kept in
    # cursor_kept_<channel>.json (the last CURSOR_KEPT_MAX replaced cursors).
    CURSOR_SHRINK_RATIO = 0.5
    CURSOR_SHRINK_MIN   = 20
    CURSOR_KEPT_MAX     = 5

    def __init__(self, addon: xbmcaddon.Addon):
        self.addon   = addon
        self.profile = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
        self._ensure_profile_dir()

        self._channels_path  = self._resolve_path(self.CHANNELS_FILE)
        self._state_path     = self._resolve_path(self.STATE_FILE)
        self._schedules_path = self._resolve_path(self.SCHEDULES_FILE)

        shared = self._shared_root()
        if shared:
            if ChannelManager._shared_logged != shared:
                ChannelManager._shared_logged = shared
                log("[ChannelManager] SHARED STORAGE ACTIVE: {}".format(
                    shared))
        else:
            log("[ChannelManager] LOCAL STORAGE: {}".format(self.profile),
                xbmc.LOGDEBUG)

        # A file that exists but cannot be read (another device is writing it,
        # or the share dropped) is not the same as an empty file.  An
        # unreadable channels.json or state.json is flagged and never written
        # back.  While state.json is flagged, nothing is drawn from the
        # cursor and no cursor is saved (_ensure_state).
        self._channels, self._channels_ok = self._read_strict(
            self._channels_path, [])
        self._state,    self._state_ok    = self._read_strict(
            self._state_path, {},
            expected=bool(self._channels) or not self._channels_ok)
        # The state as last read or written.  A save writes only the keys
        # that differ from it, so a manager that has been open for a while
        # cannot put its old copy of another channel's positions back.
        self._state_base = copy.deepcopy(self._state)
        log("[ChannelManager] Loaded {} channel(s)".format(len(self._channels)),
            xbmc.LOGDEBUG)

        # Keys explicitly deleted this session; stripped from merge on save.
        self._deleted_state_keys: set = set()

        # {source_id: {str(show_id): episode info}} — where each interleaved
        # TV show was up to in its host's queue.  Held only while a host
        # rebuilds (begin/end_interleave_resume).
        self._interleave_resume: dict = {}
        # Combo Block shows to continue at their place during one rebuild
        # (rebuild_keep_places): {tv_next_ep state key: episode id}.
        self._combo_resume: dict = {}

        self.library = LibraryClient(addon)

    # =========================================================================
    # Settings helpers
    # =========================================================================

    def _default_queue_size(self) -> int:
        try:
            return max(10, int(
                self.addon.getSetting("default_queue_size") or "30"))
        except (ValueError, TypeError):
            return 30

    # =========================================================================
    # Path / IO helpers (private — no callers outside this file)
    # =========================================================================

    def _ensure_profile_dir(self) -> None:
        if not xbmcvfs.exists(self.profile):
            xbmcvfs.mkdirs(self.profile)

    def _shared_root(self) -> str:
        return shared_root()

    def _resolve_path(self, filename: str) -> str:
        return resolve_path(filename)

    def _load_json(self, path: str, default: Any) -> Any:
        return load_json(path, default)

    def _save_json(self, path: str, data: Any) -> None:
        save_json(path, data)

    def _read_strict(self, path: str, default: Any,
                     expected: bool = False) -> tuple:
        """Return (data, True), or (default, False) if the file is unreadable.

        expected=True means the file is known to exist (channels exist, so
        the add-on has run here).  A file that is missing then counts as a
        failed read, not an empty one: another device may be replacing it at
        this very moment, and reading it as empty would send every show back
        to its first episode.  It is looked for again after a short wait; if
        it stays missing for STATE_ABSENT_GRACE seconds it is taken as gone.
        """
        try:
            data = load_json_strict(path, None if expected else default)
            if expected and data is None:
                for pause in (300, 700):
                    xbmc.sleep(pause)
                    data = load_json_strict(path, None)
                    if data is not None:
                        break
            if expected and data is None:
                now   = time.time()
                since = ChannelManager._absent_since.setdefault(path, now)
                if now - since < self.STATE_ABSENT_GRACE:
                    log("[ChannelManager] {} is missing - treated as "
                        "unreadable (writes to it are held back) until it "
                        "is back".format(path), level=xbmc.LOGWARNING)
                    return default, False
                ChannelManager._absent_since.pop(path, None)
                log("[ChannelManager] {} has been missing for {}s - treated "
                    "as gone".format(path, int(now - since)),
                    level=xbmc.LOGWARNING)
                return default, True
            ChannelManager._absent_since.pop(path, None)
            return data, True
        except JsonReadError as exc:
            log("[ChannelManager] cannot read {} - writes to it are held "
                "back until it can be read".format(exc), level=xbmc.LOGWARNING)
            return default, False

    def _ensure_state(self) -> bool:
        """True when the in-memory state is a real copy of state.json.

        If state.json could not be read when this manager was created, the
        in-memory state is an empty stand-in: a cursor taken from it is a
        zero cursor, and saving that would replace the channel's real
        positions.  Try to read it again; False means still unreadable and
        callers must not draw from the cursor or save one.
        """
        if self._state_ok:
            return True
        data, ok = self._read_strict(
            self._state_path, {},
            expected=bool(self._channels) or not self._channels_ok)
        if ok:
            self._state      = {**data, **self._state}
            self._state_base = copy.deepcopy(data)
            self._state_ok   = True
        return ok

    def _save_channels(self) -> None:
        if not self._channels_ok:
            # The list in memory started as an empty stand-in for a file that
            # could not be read; writing it would erase every channel.
            self._channels, self._channels_ok = self._read_strict(
                self._channels_path, [])
            log("[ChannelManager] channels.json was unreadable when loaded - "
                "this change was not saved", level=xbmc.LOGWARNING)
            return
        self._save_json(self._channels_path, self._channels)

    def _lock_scope(self, wait_ms: int):
        """Context manager: hold the shared-folder rename lock for the block.
        Yields True when held, False when the block runs without it (setting
        off, no shared folder, lock busy too long, any error).  Never raises."""
        try:
            cls  = ChannelManager
            root = self._shared_root()
            on   = str(self.addon.getSetting("write_lock")
                       ).strip().lower() != "false"
            dev  = self.get_device_label()
            key  = (root, on, self.get_device_id())   # label can change at start-up
            with cls._WRITE_LOCK_MU:
                if cls._WRITE_LOCK is None or cls._WRITE_LOCK_KEY != key:
                    cls._WRITE_LOCK = write_lock.WriteLock(
                        write_lock.default_fs(), root, dev, enabled=on,
                        record=self._jrec)
                    cls._WRITE_LOCK_KEY = key
                lock = cls._WRITE_LOCK
            return lock.scope(wait_ms)
        except Exception as exc:
            log("[ChannelManager] write lock unavailable: {}".format(exc),
                level=xbmc.LOGWARNING)
            return contextlib.nullcontext(False)

    def _save_state(self) -> bool:
        """Write state.json under the shared-folder lock (3.1.148); see
        _save_state_unlocked for what a save does."""
        with self._lock_scope(self.WRITE_LOCK_WAIT_MS):
            return self._save_state_unlocked()

    def _save_state_unlocked(self) -> bool:
        """Read-before-write merge for state.json.  True when state.json was
        written, False when the save was skipped or failed.

        Reads current file from disk, merges our in-memory changes on top,
        strips explicitly deleted keys, strips orphan keys (channels that no
        longer exist), then writes. Keeps in-memory copy consistent.

        If state.json exists but cannot be read, nothing is written: the merge
        would start from an empty file and erase every channel's position.
        Orphan pruning is skipped unless channels.json was read and holds at
        least one channel, for the same reason.
        """
        with ChannelManager._STATE_LOCK:
            try:
                try:
                    on_disk = load_json_strict(self._state_path, {})
                except JsonReadError as exc:
                    log("[ChannelManager] _save_state skipped, state.json "
                        "unreadable: {}".format(exc), level=xbmc.LOGWARNING)
                    self._journal_unreadable("save", exc)
                    return False
                via, stamp_read = self._diag_before_save(on_disk)
                self._backup_state(on_disk)
                # Only what this manager changed since it last read or wrote
                # state.json goes on top of the file as it is now.  Writing
                # its whole copy would put every other channel's positions
                # back to where they were when this manager was created.
                if on_disk:
                    merged = dict(on_disk)
                    for k, v in self._state.items():
                        if (k not in self._state_base
                                or self._state_base[k] != v):
                            merged[k] = v
                else:
                    # The file is gone or empty: write everything this
                    # manager holds rather than only what it changed.
                    merged = dict(self._state)
                if self._deleted_state_keys:
                    self._jrec("state_keys_deleted",
                               n=len(self._deleted_state_keys), via=via,
                               keys=sorted(self._deleted_state_keys)[:20])
                for k in self._deleted_state_keys:
                    merged.pop(k, None)
                self._keep_newer_carousel(on_disk, merged)
                self._guard_cursors(on_disk, merged)
                # Orphan-key pruning: drop keys for deleted channels.
                # Exemptions: keys starting with "resume:" or "combo:" are
                # managed independently and must not be pruned here.
                # Read live channel IDs directly from disk so channels created
                # by other processes (e.g. addon.py) are not falsely treated
                # as orphans by the long-running service process.
                try:
                    disk_channels = load_json_strict(self._channels_path, [])
                except JsonReadError:
                    disk_channels = []
                if disk_channels:
                    self._channels    = disk_channels
                    self._channels_ok = True
                    live_ids = {c["id"] for c in disk_channels}
                    orphans  = [
                        k for k in list(merged.keys())
                        if ":" in k
                        and not k.startswith("resume:")
                        and not k.startswith("combo:")
                        and not k.startswith("pending_seek:")
                        and not k.startswith("sch_")   # schedule active_block
                        and k.split(":", 1)[0] not in live_ids
                    ]
                    if orphans:
                        self._jrec("orphans_pruned", n=len(orphans), via=via,
                                   channels=len(disk_channels),
                                   keys=sorted(orphans)[:20])
                    for k in orphans:
                        del merged[k]
                else:
                    log("[ChannelManager] _save_state: channel list empty or "
                        "unreadable - orphan pruning skipped",
                        level=xbmc.LOGWARNING)
                self._journal_lowering(merged, stamp_read, via)
                self._keep_seen_clock(
                    merged, via,
                    {c["id"] for c in disk_channels} if disk_channels
                    else None)
                merged["_writer"] = self._writer_tag(via)
                if not save_json(self._state_path, merged):
                    log("[ChannelManager] _save_state: state.json could not "
                        "be written", level=xbmc.LOGWARNING)
                    self._jrec("state_write_failed", via=via, read=stamp_read)
                    return False
                self._state      = merged
                self._state_base = copy.deepcopy(merged)
                # The deletions are on disk now; a key deleted here and
                # written by another device later must not be removed again.
                self._deleted_state_keys.clear()
                self._journal_write(merged, stamp_read, via)
                return True
            except Exception as exc:
                log("[ChannelManager] _save_state error: {}".format(exc),
                    level=xbmc.LOGWARNING)
                return False

    def _keep_newer_carousel(self, on_disk: dict, merged: dict) -> None:
        """A save never lowers a channel's carousel clock.  (3.1.142)

        _save_state puts this manager's changed keys on top of the file as it
        is now.  A carousel entry is written whole, so a manager holding an
        older copy (read before another device popped) wrote the old
        last_pop_time back over the new one without any error: seen 7 times
        in the night of 11/02 to 11/03, twice followed by a second pop for
        the same interval.  Every clock the code writes is a raise (a pop,
        the first-run set, the playing-channel hold), so when the file's
        clock is ahead of the one about to be written, the file's entry is
        kept as it is.  Each case is journalled as 'carousel_kept' with the
        path that tried to write (the eraser the journals could not name).
        """
        for k in [x for x in merged if x.endswith(":carousel")]:
            mine, theirs = merged.get(k), on_disk.get(k)
            if not isinstance(mine, dict) or not isinstance(theirs, dict) \
                    or mine == theirs:
                continue
            try:
                my_clock = float(mine.get("last_pop_time") or 0)
                disk_clock = float(theirs.get("last_pop_time") or 0)
            except (TypeError, ValueError):
                continue
            if disk_clock > my_clock + self.CAROUSEL_CLOCK_SLACK:
                merged[k] = copy.deepcopy(theirs)
                chan = k[:-len(":carousel")]
                log("[ChannelManager] save would have lowered the carousel "
                    "clock of {} from {:.0f} to {:.0f} - kept the newer "
                    "one".format(chan[:8], disk_clock, my_clock),
                    level=xbmc.LOGWARNING)
                journal.record("carousel_kept",
                               ch=self._journal_channel(chan),
                               mine=my_clock, disk=disk_clock,
                               via=journal.chain(2, 6))

    def _keep_seen_clock(self, merged: dict, via: str, live) -> None:
        """A save never writes a carousel clock below the highest one this
        process has seen on the share (read or written).  (3.1.145)

        _keep_newer_carousel compares with the copy of state.json this save
        read.  When that copy was itself an old one (the share handed back a
        file from before another device's pop), nothing in it is higher, and
        the lower clock, or none at all, went out: 11/07 09:33 the PC wrote
        0.0 for a channel whose clock the Livingroom had put there 40 s
        earlier, which the PC had itself seen.  Every clock the code writes
        is a raise, so one below what this process has seen is put back to
        it, and a missing entry is created again.

        Left alone: a key being deleted on purpose, a channel that no longer
        exists, every clock when the channel list could not be read
        (live is None), and a clock seen more than CLOCK_FLOOR_SECONDS ago
        (the stale views measured were 21 to 43 s old; a restore or edit made
        by another process long after must not be undone).  Each change is
        journalled as 'clock_floor', after 'clock_lowering_write' has
        recorded what the save was about to write.
        """
        if live is None:
            return
        for k, seen in list(ChannelManager._clock_seen.items()):
            chan = k[:-len(":carousel")]
            if k in self._deleted_state_keys or chan not in live:
                continue
            if time.time() - seen[2] > self.CLOCK_FLOOR_SECONDS:
                continue
            entry = merged.get(k)
            try:
                cur = float(entry.get("last_pop_time") or 0) \
                    if isinstance(entry, dict) else 0.0
            except (TypeError, ValueError):
                cur = 0.0
            if cur >= seen[0] - self.CAROUSEL_CLOCK_SLACK:
                continue
            fixed = copy.deepcopy(entry) if isinstance(entry, dict) else {}
            fixed["last_pop_time"] = seen[0]
            merged[k] = fixed
            log("[ChannelManager] save would have written the carousel clock "
                "of {} as {:.0f}, below {:.0f} seen on the share - kept the "
                "higher one".format(chan[:8], cur, seen[0]),
                level=xbmc.LOGWARNING)
            self._jrec("clock_floor", ch=self._journal_channel(chan),
                       floor=seen[0], was=cur, floor_who=seen[1], via=via)

    def _backup_state(self, good_state: dict) -> None:
        """Keep rolling and daily snapshots of the last state.json that read cleanly.

        Written at most once per STATE_BACKUP_SECONDS per process, into
        state.bak<N>.json with N cycling through STATE_BACKUP_SLOTS, so an
        earlier good copy survives a bad overwrite for about 24 hours.  The
        first clean save of each day also writes state.day<N>.json (14 slots).
        An empty state is never snapshotted.
        """
        if not good_state:
            return
        now = time.time()
        day = int(now // 86400)
        if day != ChannelManager._state_daily_on:
            ChannelManager._state_daily_on = day
            self._save_json(
                self._resolve_path("state.day{}.json".format(
                    day % self.STATE_DAILY_SLOTS)), good_state)
        if now - ChannelManager._state_backup_at < self.STATE_BACKUP_SECONDS:
            return
        ChannelManager._state_backup_at = now
        slot = int(now // self.STATE_BACKUP_SECONDS) % self.STATE_BACKUP_SLOTS
        self._save_json(self._resolve_path("state.bak{}.json".format(slot)),
                        good_state)

    @staticmethod
    def _cursor_size(cursor: Any) -> tuple:
        """(number of shows, sum of their positions) of a stored cursor."""
        pos = cursor.get("ep_pos") if isinstance(cursor, dict) else None
        if not isinstance(pos, dict):
            return 0, 0
        return len(pos), sum(v for v in pos.values()
                             if isinstance(v, int) and not isinstance(v, bool))

    def _guard_cursors(self, on_disk: dict, merged: dict) -> None:
        """Log, and keep a copy of, any cursor this save is about to shrink.

        A channel's cursor replaced by one with far fewer shows or far lower
        positions is what "the channel started over" looks like in state.json.
        The save still goes ahead (a reset or an edit can do this on purpose;
        those remove the key first and are not compared), but the cursor that
        is being replaced is written to cursor_kept_<channel>.json together
        with the device that did it, so it can be put back and the log says
        who and when.
        """
        for key, old in on_disk.items():
            if not key.endswith(":cursor") or key not in merged:
                continue
            old_pos = old.get("ep_pos") if isinstance(old, dict) else None
            new_pos = (merged[key].get("ep_pos")
                       if isinstance(merged[key], dict) else None)
            wrap_loss = 0       # positions given back by shows that just wrapped
            if isinstance(old_pos, dict) and isinstance(new_pos, dict):
                drops = [
                    "{}: {} -> {}".format(sid, was, new_pos.get(sid, "gone"))
                    for sid, was in old_pos.items()
                    if isinstance(was, int) and (
                        sid not in new_pos
                        or (isinstance(new_pos[sid], int)
                            and new_pos[sid] < was))]
                if drops:
                    import traceback
                    cid_ = key[:-len(":cursor")]
                    now_ = time.time()
                    wrapped = [
                        d for d in drops
                        if now_ - self._RECENT_WRAPS.get(
                            (cid_, d.split(":", 1)[0]), 0)
                        <= self.WRAP_NOTE_SECONDS]
                    lost = [d for d in drops if d not in wrapped]
                    for d in wrapped:
                        sid_ = d.split(":", 1)[0]
                        was_, new_ = old_pos.get(sid_), new_pos.get(sid_)
                        if isinstance(was_, int) and isinstance(new_, int):
                            wrap_loss += was_ - new_
                    if wrapped:
                        log("[ChannelManager] wrapped to the first episode: "
                            "channel {} - {}".format(
                                cid_[:8], "; ".join(wrapped[:5])))
                    if lost:
                        log("[ChannelManager] POSITION DROP: channel {} - {} "
                            "show(s) went back: {} - saved by {} via {}".format(
                                cid_[:8], len(lost),
                                "; ".join(lost[:5]), self.get_device_label(),
                                " < ".join(f.name for f in
                                           traceback.extract_stack(limit=8)[:-1]
                                           )), level=xbmc.LOGWARNING)
            if isinstance(old_pos, dict) and isinstance(new_pos, dict) and drops:
                journal.record("position_drop",
                               ch=self._journal_channel(
                                   key[:-len(":cursor")]),
                               drops=drops[:20], via=journal.chain(2, 8))
            old_n, old_sum = self._cursor_size(old)
            new_n, new_sum = self._cursor_size(merged[key])
            lost_shows = (old_n >= 4
                          and new_n <= old_n * self.CURSOR_SHRINK_RATIO)
            # A show that just wrapped to its first episode gives its whole
            # position back; that part is not a lost cursor.  Add it back
            # before comparing, so only the unexplained part can trip the check.
            lost_pos   = (old_sum >= self.CURSOR_SHRINK_MIN
                          and new_sum + wrap_loss
                          <= old_sum * self.CURSOR_SHRINK_RATIO)
            if not (lost_shows or lost_pos):
                continue
            cid  = key[:-len(":cursor")]
            name = next((c.get("name", "") for c in self._channels
                         if c.get("id") == cid), "")
            log("[ChannelManager] CURSOR SHRINK: channel '{}' ({}) cursor "
                "replaced by one with {} show(s) / position total {} "
                "(was {} / {}) - saved by {}; the replaced cursor is kept in "
                "cursor_kept_{}.json".format(
                    name, cid, new_n, new_sum, old_n, old_sum,
                    self.get_device_label(), cid[:8]),
                level=xbmc.LOGWARNING)
            path = self._resolve_path("cursor_kept_{}.json".format(cid[:8]))
            try:
                kept = load_json_strict(path, [])
            except JsonReadError:
                continue    # unreadable now: do not replace what is there
            if not isinstance(kept, list):
                kept = []
            kept.append({"at": int(time.time()),
                         "by": self.get_device_label(),
                         "channel": cid,
                         "cursor": old})
            self._save_json(path, kept[-self.CURSOR_KEPT_MAX:])

    def _queue_file_path(self, channel_id: str) -> str:
        return self._resolve_path("queue_{}.json".format(channel_id))

    def _write_queue_file(self, channel_id: str, queue: list) -> None:
        self._save_json(self._queue_file_path(channel_id), queue)

    # =========================================================================
    # Queue file public API
    # Called by: player.py, service.py, ui/*, scheduler.py
    # =========================================================================

    def get_channel_queue(self, channel_id: str) -> list:
        """Read and return the queue list for any channel type.
        Returns [] if the queue file does not exist or cannot be read.
        """
        return self._load_json(self._queue_file_path(channel_id), [])

    def read_channel_queue(self, channel_id: str) -> Optional[list]:
        """Return the queue list, [] if there is no queue file, or None if the
        file exists but cannot be read (another device is writing it, or the
        shared folder is not reachable).

        Use this where an empty answer would start a new build: a queue that
        is merely unreadable must not be replaced.
        """
        try:
            return load_json_strict(self._queue_file_path(channel_id), [])
        except JsonReadError as exc:
            log("[ChannelManager] cannot read queue: {}".format(exc),
                level=xbmc.LOGWARNING)
            return None

    def write_channel_queue(self, channel_id: str, queue: list) -> None:
        """Write the queue list for any channel type."""
        self._write_queue_file(channel_id, queue)

    # -- Side panel starting channel (this device only) -----------------------
    # panel_start.json lives in the local profile and is never shared: each
    # device remembers its own last channel and its own chosen channel.

    PANEL_START_FILE = "panel_start.json"

    def _panel_start_path(self) -> str:
        return os.path.join(self.profile, self.PANEL_START_FILE)

    def _read_panel_start(self) -> dict:
        data = load_json(self._panel_start_path(), {})
        return data if isinstance(data, dict) else {}

    def remember_last_channel(self, channel_id: str) -> None:
        """Record channel_id as the last channel started on this device."""
        if not channel_id:
            return
        data = self._read_panel_start()
        if data.get("last_channel_id") == channel_id:
            return
        data["last_channel_id"] = channel_id
        save_json(self._panel_start_path(), data)

    def set_panel_start_channel(self, channel_id: str) -> None:
        """Record the channel the side panel opens on when the setting is
        'A specific channel'."""
        data = self._read_panel_start()
        data["fixed_channel_id"] = channel_id
        save_json(self._panel_start_path(), data)

    def get_panel_start_index(self, channels: list) -> int:
        """Return the index in channels the side panel list opens on.

        Follows the 'Channel list opens on' setting: 0 = first channel,
        1 = last channel started on this device, 2 = the chosen channel.
        Returns 0 when the setting is first channel, nothing is recorded, or
        the recorded channel is not in channels (deleted or hidden).
        """
        try:
            mode = int(self.addon.getSetting("panel_open_on") or 0)
        except (TypeError, ValueError):
            mode = 0
        if mode not in (1, 2) or not channels:
            return 0
        key = "last_channel_id" if mode == 1 else "fixed_channel_id"
        wanted = self._read_panel_start().get(key, "")
        for i, ch in enumerate(channels):
            if ch.get("id") == wanted:
                return i
        return 0

    def get_channel_queue_path(self, channel_id: str) -> str:
        """Return the filesystem path to the queue file.
        Public wrapper for use by UI components that monitor the file
        (e.g. side panel queue watcher thread).
        """
        return self._queue_file_path(channel_id)

    # =========================================================================
    # Cursor public API  (spec §8.1)
    # Called by: service.py, player.py
    # =========================================================================

    def get_cursor(self, channel_id: str) -> dict:
        """Read the TV cursor for channel_id from state.
        Returns a zero cursor if no cursor exists yet.
        """
        key    = "{}:cursor".format(channel_id)
        stored = self._state.get(key)
        if stored and isinstance(stored, dict):
            c = copy.deepcopy(self._ZERO_CURSOR)
            c.update(stored)
            # Ensure sub-dicts are always present (forward-compat)
            for k in ("ep_pos", "ep_played", "slot_owed"):
                if not isinstance(c.get(k), dict):
                    c[k] = {}
            return c
        # A deep copy: a shallow one would hand every caller the same
        # ep_pos / ep_played / slot_owed dicts, so a position written for one
        # channel would show up in the blank cursor of the next.
        return copy.deepcopy(self._ZERO_CURSOR)

    def set_cursor(self, channel_id: str, cursor: dict,
                   verify: bool = False) -> bool:
        """Write cursor to state for channel_id.  True when it was saved to
        state.json, False when the save was skipped or failed.

        verify=True is used by the per-episode draws (1-for-1 replacement and
        carousel pop): after saving, state.json is read again and a position
        another device wrote over is written again (_verify_cursor_saved)."""
        if not self._ensure_state():
            log("[ChannelManager] set_cursor: state.json unreadable - cursor "
                "for '{}' not saved".format(channel_id),
                level=xbmc.LOGWARNING)
            return False
        key = "{}:cursor".format(channel_id)
        self._deleted_state_keys.discard(key)
        # Positions as they were when state.json was last read or written:
        # the "old" values a lost save would leave behind.
        old_cur = self._state_base.get(key) or {}
        old_pos = dict(old_cur.get("ep_pos") or {})
        self._state[key] = cursor
        saved = self._save_state()
        self._journal_cursor(channel_id, old_cur, cursor, saved)
        if saved and verify:
            self._verify_cursor_saved(channel_id, cursor, old_pos)
        return saved

    def _journal_cursor(self, channel_id: str, old_cur: dict, cursor: dict,
                        saved: bool) -> None:
        """Journal every position that this save changed: show id, the value
        state.json had and the value now written, and who called."""
        try:
            new_pos = cursor.get("ep_pos") or {}
            old_pos = old_cur.get("ep_pos") or {}
            changes = {sid: [old_pos.get(sid), pos]
                       for sid, pos in new_pos.items()
                       if old_pos.get(sid) != pos}
            played = {sid: [len(old_cur.get("ep_played", {}).get(sid, ())),
                            len(lst)]
                      for sid, lst in (cursor.get("ep_played") or {}).items()
                      if len(old_cur.get("ep_played", {}).get(sid, ()))
                      != len(lst)}
            slot = [old_cur.get("show_slot"), cursor.get("show_slot")]
            if not changes and not played and slot[0] == slot[1]:
                return
            journal.record(
                "cursor", ch=self._journal_channel(channel_id),
                pos=changes, played=played,
                slot=slot if slot[0] != slot[1] else None,
                saved=bool(saved), via=journal.chain(2))
        except Exception:
            pass

    def journal_channel_name(self, channel_id: str) -> str:
        """Public form of the journal's channel label, for service.py and
        carousel.py ('Name (abcd1234)')."""
        return self._journal_channel(channel_id)

    def _journal_channel(self, channel_id: str) -> str:
        """'Name (abcd1234)' for journal lines."""
        ch = next((c for c in self._channels if c.get("id") == channel_id),
                  None)
        return "{} ({})".format(ch.get("name", "?") if ch else "?",
                                str(channel_id)[:8])

    def journal_snapshot(self) -> None:
        """Journal every TV channel's positions and the episode ids waiting
        in its queue.  Called by service.py once an hour (and at start), so
        the journal holds regular check points that need no backup."""
        try:
            if not self._ensure_state():
                return
            for ch in self._channels:
                if ch.get("channel_type", "tv") != "tv":
                    continue
                cid   = ch["id"]
                cur   = self.get_cursor(cid)
                queue = self.read_channel_queue(cid) or []
                journal.record(
                    "snapshot", ch=self._journal_channel(cid),
                    pos=cur.get("ep_pos"), slot=cur.get("show_slot"),
                    queue=[[i.get("show_id") or i.get("_show_id"),
                            i.get("season"), i.get("episode"),
                            i.get("episodeid")]
                           for i in queue if not i.get("_interleaved")])
        except Exception as exc:
            log("[ChannelManager] journal_snapshot error: {}".format(exc),
                level=xbmc.LOGWARNING)

    CURSOR_VERIFY_MS    = 1200
    CURSOR_VERIFY_TRIES = 3

    def _verify_cursor_saved(self, channel_id: str, cursor: dict,
                             old_pos: dict) -> None:
        """Put back positions that another device's save wiped out.

        state.json is read, changed and written back whole.  If another device
        reads it before this save and writes it after, its copy has the old
        positions and replaces this save without any error.  A short time
        after saving, read state.json again; for each show whose position this
        save changed, if the file shows the OLD value again, write ours once
        more.  A value that is neither old nor ours is another change and is
        left alone.
        """
        key     = "{}:cursor".format(channel_id)
        changed = {sid: pos for sid, pos in
                   (cursor.get("ep_pos") or {}).items()
                   if old_pos.get(sid) != pos}
        if not changed:
            return
        for attempt in range(self.CURSOR_VERIFY_TRIES):
            xbmc.sleep(self.CURSOR_VERIFY_MS)
            disk, ok = self._read_strict(self._state_path, {})
            if not ok:
                return
            on_disk = disk.get(key)
            on_pos  = (on_disk.get("ep_pos") if isinstance(on_disk, dict)
                       else None) or {}
            lost    = {sid: pos for sid, pos in changed.items()
                       if on_pos.get(sid) == old_pos.get(sid)
                       and on_pos.get(sid) != pos}
            if not lost:
                return
            log("[ChannelManager] cursor of {} was overwritten by another "
                "device - {} position(s) written again".format(
                    channel_id[:8], len(lost)), level=xbmc.LOGWARNING)
            journal.record("cursor_rewritten",
                           ch=self._journal_channel(channel_id),
                           lost={sid: [old_pos.get(sid), pos]
                                 for sid, pos in lost.items()},
                           on_disk={sid: on_pos.get(sid) for sid in lost},
                           attempt=attempt + 1)
            fixed = copy.deepcopy(on_disk) if isinstance(on_disk, dict) \
                else copy.deepcopy(cursor)
            fixed.setdefault("ep_pos", {}).update(lost)
            self._state[key] = fixed
            self._state_base[key] = copy.deepcopy(on_disk) \
                if isinstance(on_disk, dict) else None
            if not self._save_state():
                return

    def rebuild_failed(self, channel_id: str) -> bool:
        """True when the last queue rebuild of channel_id was refused because
        its new positions could not be saved.  The old queue and positions
        were left as they were."""
        return channel_id in ChannelManager._rebuild_failed

    def edit_blocked(self, channel_id: str) -> bool:
        """True when the last Edit of channel_id was refused, with nothing
        saved, because its queue could not be read.  Edit Channel tells the
        user; the flag clears at the start of the next edit."""
        return channel_id in ChannelManager._edit_blocked

    def clear_cursor(self, channel_id: str) -> None:
        """Delete the cursor for channel_id.
        The next queue build will use a zero cursor (fresh start).
        """
        for key in ("{}:cursor".format(channel_id),
                    "{}:__folder_cycle__".format(channel_id)):
            self._state.pop(key, None)
            self._deleted_state_keys.add(key)
        self._save_state()

    def update_cursor_for_edit(self, channel_id: str,
                               added_show_ids: list,
                               removed_show_ids: list,
                               invalidate: bool) -> None:
        """Adjust the cursor after a channel edit.

        invalidate=True  → clear the cursor entirely (recycle/randomize changed).
        invalidate=False → preserve cursor but add/drop show entries.
        """
        if invalidate:
            self.clear_cursor(channel_id)
            log("[ChannelManager] update_cursor_for_edit: invalidated cursor "
                "for '{}'".format(channel_id))
            return

        cursor  = self.get_cursor(channel_id)
        changed = False

        for sid in removed_show_ids:
            sid_str = str(sid)
            cursor["ep_pos"].pop(sid_str,    None)
            cursor["ep_played"].pop(sid_str, None)
            cursor["slot_owed"].pop(sid_str, None)
            changed = True

        if removed_show_ids:
            cursor["show_slot"] = max(
                0, cursor["show_slot"] - len(removed_show_ids))

        if added_show_ids:
            # No cursor entry created for new shows — _fill_slot seeds
            # ep_pos from show state on first access.
            changed = True

        if changed:
            self.set_cursor(channel_id, cursor)
            log("[ChannelManager] update_cursor_for_edit: updated cursor for "
                "'{}' removed={} added={}".format(
                    channel_id, removed_show_ids, added_show_ids))

    # =========================================================================
    # 1-for-1 replacement  (spec §7.3, §8.1)
    # Called by: service.py only
    # =========================================================================

    def get_one_replacement(self, channel_id: str,
                            consumed_item: dict,
                            current_queue: Optional[list] = None) -> Optional[dict]:
        """Return one replacement item for consumed_item and update cursor.

        Called by service.py after every item completion (natural end, skip,
        or carousel pop) for non-combo items.  The returned item should be
        appended to the queue tail by the caller.

        current_queue: the in-memory queue AFTER the consumed item has been
        removed.  Serial replacement uses this to find the true tail of the
        queue without reading a potentially stale disk copy.

        Returns None if the channel is exhausted (recycle=False, pool empty),
        or if state.json cannot be read (the cursor is unknown, so nothing is
        drawn).
        """
        if not self._ensure_state():
            log("[ChannelManager] get_one_replacement: state.json "
                "unreadable - no replacement drawn", level=xbmc.LOGWARNING)
            return None
        # Interleaved items must be replaced from their source channel, not the
        # host channel.  Without this, a movie interleaved into a TV channel
        # would be replaced with a TV episode (wrong source, wrong type).
        # The replacement must also carry the same interleave tags as the
        # consumed item so that when IT is later skipped or consumed, the
        # correct replacement path is taken again.
        if consumed_item.get("_interleaved"):
            source_cid = consumed_item.get("_channel_id", "")
            if source_cid and source_cid != channel_id:
                source_ch = self.get_channel(source_cid)
                if source_ch:
                    sctype = source_ch.get("channel_type", "tv")
                    result = None
                    host_queue = (current_queue if current_queue is not None
                                  else self.get_channel_queue(channel_id))
                    if sctype == "movies":
                        result = self._replacement_movie(
                            source_cid, source_ch, consumed_item,
                            host_queue=host_queue)
                    elif sctype == "folder":
                        result = self._replacement_folder(
                            source_cid, source_ch, consumed_item,
                            host_queue=host_queue)
                    elif sctype == "tv":
                        result = self.get_interleaved_tv_replacement(
                            source_ch, consumed_item, host_queue)
                    if result is not None:
                        result = dict(result)
                        result["_interleaved"]  = True
                        result["_channel_id"]   = source_cid
                        if consumed_item.get("_silent"):
                            result["_silent"]       = True
                        if consumed_item.get("_channel_name"):
                            result["_channel_name"] = consumed_item["_channel_name"]
                    return result
                log("[ChannelManager] get_one_replacement: interleaved item "
                    "source channel {} not found — falling through to host"
                    .format(source_cid))

        channel = self.get_channel(channel_id)
        if not channel:
            log("[ChannelManager] get_one_replacement: channel {} not "
                "found".format(channel_id))
            return None

        ctype = channel.get("channel_type", "tv")

        if ctype == "tv":
            return self._replacement_tv(channel_id, channel, consumed_item,
                                        current_queue=current_queue)
        if ctype == "movies":
            return self._replacement_movie(channel_id, channel, consumed_item,
                                           host_queue=current_queue)
        if ctype == "folder":
            return self._replacement_folder(channel_id, channel, consumed_item,
                                            host_queue=current_queue)

        if ctype == "audio":
            return self._replacement_audio(channel_id, channel, consumed_item,
                                           host_queue=current_queue)
        if ctype == "party":
            return self._replacement_party(channel_id, channel, consumed_item,
                                           host_queue=current_queue)

        log("[ChannelManager] get_one_replacement: unhandled type '{}' for "
            "channel {}".format(ctype, channel_id))
        return None

    def get_carousel_replacement(self, channel_id: str,
                                 popped_show_id: int,
                                 queue: Optional[list] = None,
                                 consumed_id=None) -> Optional[dict]:
        """Get next episode of the SAME show that was carousel-popped.

        Does NOT advance show_slot — only the per-show ep_pos advances.
        spec §8.5, §9.2

        queue / consumed_id (optional): the queue with the popped item
        already removed, and the popped episode's id.  With them an episode
        that is already waiting in the queue, or that was just popped, is not
        drawn again (same rule as the TV 1-for-1 replacement); without them
        the draw is unchanged.
        """
        if not self._ensure_state():
            log("[ChannelManager] get_carousel_replacement: state.json "
                "unreadable - no replacement drawn", level=xbmc.LOGWARNING)
            return None
        channel = self.get_channel(channel_id)
        if not channel:
            return None

        cursor = self.get_cursor(channel_id)
        shows  = channel.get("shows", [])
        show   = next(
            (s for s in shows if s["tvshowid"] == popped_show_id), None)
        if not show:
            log("[ChannelManager] get_carousel_replacement: show_id {} not "
                "found in channel {}".format(popped_show_id, channel_id))
            return None

        episodes = self.get_available_episodes(show)
        if not episodes:
            return None

        sid_str = str(popped_show_id)
        queued_ids = (None if queue is None else
                      self._queued_ids(queue, channel_id, "episodeid",
                                       show_id=popped_show_id))
        ep      = self._pick_one_ep_no_slot_advance(
            show, sid_str, episodes, cursor,
            channel.get("randomize", False), channel.get("recycle", True),
            channel_id=channel_id,
            queued_ids=queued_ids, consumed_id=consumed_id)
        self.set_cursor(channel_id, cursor, verify=True)
        return ep

    def get_interleaved_tv_replacement(self, source_ch: dict,
                                       consumed_item: dict,
                                       host_queue: list) -> Optional[dict]:
        """Return the replacement for an interleaved TV episode.

        The host queue is the authority for where each show is: the
        replacement is the episode after the last one of the same show
        (from the same source) still waiting in host_queue, or after the
        episode just consumed when none is waiting.  The source channel's
        own saved position is neither read nor changed, so the queue keeps
        the order it was built with (including the source's starting
        episodes).  Randomised shows and Serial sources keep the previous
        behaviour (_replacement_tv).
        Returns None when the show has no more episodes (recycle off).
        """
        source_cid = source_ch.get("id", "")
        show_id = consumed_item.get("show_id") or consumed_item.get("_show_id")
        show = next((s for s in source_ch.get("shows", [])
                     if s["tvshowid"] == show_id), None)
        if (show is None
                or source_ch.get("playback_mode") == "serial"
                or show.get("randomize", source_ch.get("randomize", False))):
            return self._replacement_tv(source_cid, source_ch, consumed_item,
                                        current_queue=host_queue)
        episodes = self.get_available_episodes(show)
        if not episodes:
            return None
        ids = [e["episodeid"] for e in episodes]
        anchor = None
        for item in host_queue or []:
            if (item.get("_interleaved")
                    and item.get("_channel_id") == source_cid
                    and (item.get("show_id") or item.get("_show_id")) == show_id
                    and item.get("episodeid") in ids):
                anchor = ids.index(item["episodeid"])      # last one wins
        if anchor is None and consumed_item.get("episodeid") in ids:
            anchor = ids.index(consumed_item["episodeid"])
        if anchor is None:
            return self._replacement_tv(source_cid, source_ch, consumed_item,
                                        current_queue=host_queue)
        from resources.lib.utils.multi_episode import count_episode_span
        idx = anchor
        for _ in range(len(episodes)):
            idx += count_episode_span(episodes[idx])
            if idx >= len(episodes):
                if not source_ch.get("recycle", True):
                    return None
                idx = 0
            norm = _normalize_ep_fn(episodes[idx], source_cid, int(show_id),
                                    all_episodes_for_show=episodes,
                                    default_seconds=self._default_episode_seconds())
            self._note_default_length(source_cid, episodes[idx], norm)
            if norm:
                return norm
            self.record_missing_duration(source_cid, episodes[idx], "no_nfo")
        return None

    def _replacement_tv(self, channel_id: str, channel: dict,
                        consumed_item: dict,
                        current_queue: Optional[list] = None) -> Optional[dict]:
        """Return one TV replacement.

        Round-robin: next episode of the same consumed show.
        Serial: advance to the next show in serial sequence.
        """
        # Serial channels: stay on the current show until it is fully
        # exhausted, then advance to the next show. This handles the case
        # where the queue size cut the show off before all episodes were
        # queued — we must continue appending that show's episodes until
        # ep_pos reaches the end before moving to the next show.
        if channel.get("playback_mode") == "serial":
            return self._replacement_serial(channel_id, channel,
                                            consumed_item,
                                            current_queue=current_queue)

        show_id  = consumed_item.get("show_id") or consumed_item.get("_show_id")
        shows    = channel.get("shows", [])
        show     = next((s for s in shows if s["tvshowid"] == show_id), None)
        if not show:
            # show no longer in channel — advance rotation to next show
            return self._replacement_tv_next_show(channel_id, channel)

        episodes = self.get_available_episodes(show)
        if not episodes:
            return None

        host_queue = (current_queue if current_queue is not None
                      else self.get_channel_queue(channel_id))
        cursor  = self.get_cursor(channel_id)
        sid_str = str(show_id)
        ep      = self._pick_one_ep_no_slot_advance(
            show, sid_str, episodes, cursor,
            channel.get("randomize", False), channel.get("recycle", True),
            channel_id=channel_id,
            queued_ids=self._queued_ids(host_queue, channel_id, "episodeid",
                                        show_id=show_id),
            consumed_id=consumed_item.get("episodeid"))
        self.set_cursor(channel_id, cursor, verify=True)
        return ep

    @staticmethod
    def _queued_ids(host_queue, channel_id: str, key: str,
                    show_id=None) -> set:
        """Return the set of item[key] values in host_queue that belong to
        channel_id (own items or items interleaved from it), optionally only
        those of one show.  Used so a random replacement avoids what is
        already queued."""
        ids = set()
        for item in host_queue or []:
            if (item.get("_channel_id") or channel_id) != channel_id:
                continue
            if show_id is not None and (
                    item.get("show_id") or item.get("_show_id")) != show_id:
                continue
            value = item.get(key)
            if value is not None and value != -1:
                ids.add(value)
        return ids

    def _replacement_serial(self, channel_id: str, channel: dict,
                            consumed_item: dict,
                            current_queue: Optional[list] = None) -> Optional[dict]:
        """Serial replacement: continue from wherever the queue tail currently is.

        For serial channels the rule is simple: always append the successor of
        whatever is last in the queue. The consumed item's show is irrelevant —
        what matters is the tail, because the tail represents what has already
        been scheduled. This is correct for both natural play (one item at a
        time) and skip (N items at a time) because each call sees the growing
        queue including all replacements appended by previous calls in the loop.

        If the tail show is exhausted (last episode already queued), advance to
        the next show. If no queue exists yet, fall back to consumed item's show.
        """
        shows = channel.get("shows", [])
        if not shows:
            return None

        queue = current_queue if current_queue is not None \
            else self.get_channel_queue(channel_id)

        # Find the last NON-interleaved item in the queue and what show it
        # belongs to.  That determines what comes next in serial order.
        # Interleaved items (combo block, foreign TV, movies, folders) must be
        # skipped — their show_id belongs to the source channel, not this serial
        # channel, so using them as the tail anchor would break the serial order.
        tail_item    = next(
            (item for item in reversed(queue)
             if not item.get("_interleaved")),
            None)
        tail_show_id = (tail_item.get("show_id") or tail_item.get("_show_id")
                        if tail_item else None)

        if tail_show_id:
            tail_show = next(
                (s for s in shows if s["tvshowid"] == tail_show_id), None)

            if tail_show:
                episodes = self.get_available_episodes(tail_show)
                if episodes:
                    tail_ep_id = tail_item.get("episodeid")
                    tail_idx   = next(
                        (i for i, ep in enumerate(episodes)
                         if ep["episodeid"] == tail_ep_id), None)

                    if tail_idx is not None and tail_idx + 1 < len(episodes):
                        # More episodes of the tail show remain — continue it.
                        next_idx = tail_idx + 1
                        cursor   = self.get_cursor(channel_id)
                        sid_str  = str(tail_show_id)
                        cursor["ep_pos"][sid_str] = next_idx
                        log("[ChannelManager] _replacement_serial: show {} "
                            "continuing from idx {} (ep {})".format(
                            tail_show_id, next_idx,
                            episodes[next_idx].get("episode", "?")))
                        ep = self._pick_one_ep_no_slot_advance(
                            tail_show, sid_str, episodes, cursor,
                            channel.get("randomize", False),
                            channel.get("recycle", True),
                            channel_id=channel_id)
                        self.set_cursor(channel_id, cursor, verify=True)
                        return ep

        # Tail show is exhausted (or queue is empty) — advance to next show.
        # Use the tail show id (not the consumed show id) as skip_show_id so
        # we don't immediately re-pick the show that was just exhausted.
        skip_id = tail_show_id or 0
        log("[ChannelManager] _replacement_serial: show {} exhausted in "
            "queue, advancing to next show".format(skip_id))
        return self._replacement_tv_next_show(channel_id, channel,
                                              skip_show_id=skip_id)

    def _replacement_tv_next_show(self, channel_id: str,
                                  channel: dict,
                                  skip_show_id: int = 0) -> Optional[dict]:
        """Return one episode from the next show after the exhausted one.

        For serial channels: find skip_show_id in the show list and pick
        the show at (index + 1) % len(shows). This is deterministic and
        never drifts — it doesn't rely on show_slot which can become
        misaligned after multiple boundary crossings and skips.

        For round-robin channels: use show_slot % len(shows) as before.
        """
        shows  = channel.get("shows", [])
        cursor = self.get_cursor(channel_id)

        is_serial = (channel.get("playback_mode") == "serial")

        if is_serial and skip_show_id:
            # Find the exhausted show's index and pick the next one.
            exhausted_idx = next(
                (i for i, s in enumerate(shows)
                 if s["tvshowid"] == skip_show_id), None)
            if exhausted_idx is not None:
                for attempt in range(len(shows)):
                    next_idx  = (exhausted_idx + 1 + attempt) % len(shows)
                    show      = shows[next_idx]
                    episodes  = self.get_available_episodes(show)
                    if not episodes:
                        continue
                    sid_str = str(show["tvshowid"])
                    ep = self._pick_one_ep_no_slot_advance(
                        show, sid_str, episodes, cursor,
                        channel.get("randomize", False),
                        channel.get("recycle", True),
                        channel_id=channel_id)
                    if ep:
                        # Keep show_slot in sync so round-robin path stays
                        # consistent if the channel mode ever changes.
                        cursor["show_slot"] = next_idx + 1
                        self.set_cursor(channel_id, cursor, verify=True)
                        return ep
            return None

        # Round-robin path: use show_slot as before.
        for _ in range(len(shows)):
            show_slot = cursor["show_slot"]
            show_idx  = show_slot % len(shows)
            show      = shows[show_idx]
            cursor["show_slot"] = show_slot + 1
            if skip_show_id and show["tvshowid"] == skip_show_id:
                continue
            episodes  = self.get_available_episodes(show)
            if not episodes:
                continue
            sid_str = str(show["tvshowid"])
            ep = self._pick_one_ep_no_slot_advance(
                show, sid_str, episodes, cursor,
                channel.get("randomize", False), channel.get("recycle", True),
                channel_id=channel_id)
            if ep:
                self.set_cursor(channel_id, cursor, verify=True)
                return ep
        return None

    def _replacement_movie(self, channel_id: str, channel: dict,
                           consumed_item: dict,
                           host_queue: Optional[list] = None) -> Optional[dict]:
        """Return one movie replacement from the channel's movie pool.

        host_queue is the queue the replacement will be appended to; when
        omitted the channel's own disk queue is used.
        """
        from resources.lib.channels.movies import MovieQueueBuilder
        if host_queue is None:
            host_queue = self.get_channel_queue(channel_id)
        items = MovieQueueBuilder(self).build_one(
            channel,
            queued_ids=self._queued_ids(host_queue, channel_id, "movieid"),
            consumed_id=consumed_item.get("movieid") if consumed_item else None)
        return items[0] if items else None

    def _replacement_folder(self, channel_id: str, channel: dict,
                            consumed_item: dict,
                            host_queue: Optional[list] = None) -> Optional[dict]:
        """Return one folder replacement (folders always recycle).

        host_queue is the queue the replacement will be appended to; when
        omitted the channel's own disk queue is used.
        """
        from resources.lib.channels.folder import FolderQueueBuilder
        if host_queue is None:
            host_queue = self.get_channel_queue(channel_id)
        consumed_file = (consumed_item.get("file", "")
                         if consumed_item and consumed_item.get("is_folder_item")
                         else "")
        items = FolderQueueBuilder(self).build_one(
            channel, host_queue, consumed_file=consumed_file)
        return items[0] if items else None

    def _replacement_audio(self, channel_id: str, channel: dict,
                           consumed_item: dict,
                           host_queue: Optional[list] = None) -> Optional[dict]:
        """Return one audio replacement following the channel's order."""
        from resources.lib.channels.audio import AudioQueueBuilder
        if host_queue is None:
            host_queue = self.get_channel_queue(channel_id)
        items = AudioQueueBuilder(self).build_one(
            channel, host_queue, consumed_item=consumed_item)
        return items[0] if items else None

    def _replacement_party(self, channel_id: str, channel: dict,
                           consumed_item: dict,
                           host_queue: Optional[list] = None) -> Optional[dict]:
        """Return one Party Mode replacement file."""
        from resources.lib.channels.party import PartyQueueBuilder
        if host_queue is None:
            host_queue = self.get_channel_queue(channel_id)
        items = PartyQueueBuilder(self).build_one(
            channel, host_queue, consumed_item=consumed_item)
        return items[0] if items else None

    def _pick_one_ep_no_slot_advance(self, show: dict, sid_str: str,
                                     episodes: list, cursor: dict,
                                     randomize: bool,
                                     recycle: bool,
                                     channel_id: str = "",
                                     queued_ids: Optional[set] = None,
                                     consumed_id=None) -> Optional[dict]:
        """Pick exactly one playable episode and advance cursor for that
        show only.

        Used by both carousel replacement and TV 1-for-1 replacement.
        Does NOT advance show_slot.

        An episode whose duration cannot be read is recorded in the missing
        durations list and skipped; the show's next episode is tried, so the
        queue keeps its size.  Returns None only when the show has no
        playable episode left (or is exhausted with recycle off).
        """
        tried = set()
        skipped = []
        before = cursor["ep_pos"].get(sid_str)
        played_before = len(cursor["ep_played"].get(sid_str, ()))
        chosen = None
        for _ in range(max(1, len(episodes))):
            ep = self._next_candidate_ep(
                show, sid_str, episodes, cursor, randomize, recycle,
                queued_ids=queued_ids, consumed_id=consumed_id,
                channel_id=channel_id)
            if ep is None or ep["episodeid"] in tried:
                break
            tried.add(ep["episodeid"])
            norm = _normalize_ep_fn(ep, channel_id or show.get("tvshowid", 0),
                                    int(sid_str),
                                    all_episodes_for_show=episodes,
                                    default_seconds=self._default_episode_seconds())
            self._note_default_length(channel_id, ep, norm)
            if norm is not None:
                chosen = norm
                break
            skipped.append([ep.get("season"), ep.get("episode"),
                            ep["episodeid"]])
            self.record_missing_duration(channel_id, ep, "no_nfo")
        self._journal_draw(channel_id, show, sid_str, episodes, cursor,
                           before, played_before, chosen, skipped,
                           randomize, queued_ids, consumed_id)
        return chosen

    def _journal_draw(self, channel_id, show, sid_str, episodes, cursor,
                      before, played_before, chosen, skipped, randomize,
                      queued_ids, consumed_id) -> None:
        """Journal one draw: the show, its position before and after, the
        episode drawn (or why none), and episodes skipped for a missing
        length.  The position BEFORE is the one in the cursor this draw
        started from."""
        try:
            journal.record(
                "draw", ch=self._journal_channel(channel_id),
                show=sid_str, title=show.get("title", ""),
                rand=bool(show.get("randomize", randomize)),
                n_eps=len(episodes),
                pos=[before, cursor["ep_pos"].get(sid_str)],
                played=[played_before,
                        len(cursor["ep_played"].get(sid_str, ()))],
                got=([chosen.get("season"), chosen.get("episode"),
                      chosen.get("episodeid"), chosen.get("title")]
                     if chosen else None),
                skipped=skipped or None,
                queued=(len(queued_ids) if queued_ids is not None else None),
                consumed=consumed_id, via=journal.chain(2, 6))
        except Exception:
            pass

    def _next_candidate_ep(self, show: dict, sid_str: str,
                           episodes: list, cursor: dict,
                           randomize: bool,
                           recycle: bool,
                           queued_ids: Optional[set] = None,
                           consumed_id=None,
                           channel_id: str = "") -> Optional[dict]:
        """Choose the show's next episode and advance its cursor.

        Duration is not checked here; _pick_one_ep_no_slot_advance does that.

        Random shows: queued_ids (episodes already in the host queue) and
        consumed_id (the episode just consumed) are avoided when other
        unplayed episodes exist, so a new cycle never re-queues an episode
        that is still waiting or was just played.
        """
        show_randomize = show.get("randomize", randomize)
        ep_ids         = [e["episodeid"] for e in episodes]

        if show_randomize:
            played_set = set(cursor["ep_played"].get(sid_str, []))
            unplayed   = [eid for eid in ep_ids if eid not in played_set]
            if not unplayed:
                if not recycle:
                    return None
                # Reset cycle
                journal.record("cycle_reset",
                               ch=self._journal_channel(channel_id),
                               show=sid_str, n_eps=len(ep_ids))
                cursor["ep_played"][sid_str] = []
                unplayed = list(ep_ids)
            queued = queued_ids or set()
            pool = ([e for e in unplayed
                     if e not in queued and e != consumed_id]
                    or [e for e in unplayed if e not in queued]
                    or [e for e in unplayed if e != consumed_id]
                    or unplayed)
            chosen_id = random.choice(pool)
            ep = next((e for e in episodes if e["episodeid"] == chosen_id),
                      None)
            if ep is None:
                return None
            played_list = cursor["ep_played"].setdefault(sid_str, [])
            if chosen_id not in played_list:
                played_list.append(chosen_id)
        else:
            from resources.lib.utils.multi_episode import count_episode_span
            # Seed ep_pos from state if first access.  A show with no saved
            # position but episodes already in the queue (the saved position
            # was lost, or an edit kept the queue without recording it)
            # continues after its last queued episode; starting at the first
            # episode would put S01E01 at the end of a mid-series queue.
            # Only the TV 1-for-1 replacement passes queued_ids.
            if sid_str not in cursor["ep_pos"]:
                seed = 0
                known = set(queued_ids or ())
                if consumed_id is not None:
                    known.add(consumed_id)
                if known:
                    last = max((i for i, e in enumerate(episodes)
                                if e["episodeid"] in known), default=None)
                    if last is not None:
                        seed = last + count_episode_span(episodes[last])
                        log("[ChannelManager] _next_candidate_ep: show {} - "
                            "no saved position, continuing after its last "
                            "queued episode (index {})".format(sid_str, seed))
                        journal.record(
                            "seed_position",
                            ch=self._journal_channel(channel_id),
                            show=sid_str, seed=seed)
                cursor["ep_pos"][sid_str] = seed

            idx = cursor["ep_pos"].get(sid_str, 0)
            if idx >= len(episodes):
                if not recycle:
                    return None
                # The list may be short only for a moment (the library is
                # being updated).  Wrapping here would send the show back to
                # its first episode, so the list is fetched once more first.
                self.library.invalidate_cache()
                xbmc.sleep(self.WRAP_RECHECK_MS)
                again = self.get_available_episodes(show)
                if len(again) > len(episodes):
                    episodes = again
                if idx >= len(episodes):
                    journal.record("wrap", ch=self._journal_channel(channel_id),
                                   show=sid_str, was=idx, n_eps=len(episodes))
                    ChannelManager._RECENT_WRAPS[(channel_id, sid_str)] = \
                        time.time()
                    cursor["ep_pos"][sid_str] = 0
                    idx = 0
            ep = episodes[idx]
            # Advance by span
            span = count_episode_span(ep)
            cursor["ep_pos"][sid_str] = idx + span

            # An episode that is already waiting in the queue, or that was
            # just consumed, is not drawn again: the show moves on to its
            # next episode.  The consumed episode has already been removed
            # from the queue by now, so it is counted here as well; without
            # it a saved position that points at the episode which just
            # finished would draw that same episode again.  This only
            # happens when the saved position is behind the queue; the
            # position then catches up.  If every episode is queued or
            # consumed the first one found is used.  Only the TV 1-for-1
            # replacement passes queued_ids, so other draws are unchanged.
            blocked = queued_ids
            if queued_ids is not None and consumed_id is not None:
                blocked = set(queued_ids)
                blocked.add(consumed_id)
            if blocked and ep["episodeid"] in blocked:
                first   = ep
                skipped = 1          # the one found at the saved position
                for _ in range(len(episodes)):
                    nxt = cursor["ep_pos"][sid_str]
                    if nxt >= len(episodes):
                        if not recycle:
                            break
                        nxt = 0
                    cand = episodes[nxt]
                    if cand["episodeid"] not in blocked:
                        cursor["ep_pos"][sid_str] = nxt + count_episode_span(cand)
                        ep = cand
                        break
                    cursor["ep_pos"][sid_str] = nxt + count_episode_span(cand)
                    skipped += 1
                if ep is not first:
                    log("[ChannelManager] _next_candidate_ep: show {} - {} "
                        "episode(s) already queued skipped".format(
                            sid_str, skipped))
                    journal.record(
                        "skip_queued", ch=self._journal_channel(channel_id),
                        show=sid_str, skipped=skipped,
                        first=[first.get("season"), first.get("episode"),
                               first.get("episodeid")],
                        used=[ep.get("season"), ep.get("episode"),
                              ep.get("episodeid")])

        return ep

    # =========================================================================
    # Combo unit tracker public API  (spec §4.5, §7.3, §11)
    # Called by: service.py only
    # =========================================================================

    def is_combo_channel(self, channel_id: str) -> bool:
        """Return True if channel_id is a Combo Block channel.
        Gate for all combo-aware decisions in service.py.  spec §11.1
        """
        ch = self.get_channel(channel_id)
        return bool(ch and ch.get("channel_type") == "combo")

    # =========================================================================
    # Queue building public API
    # Called by: player.py (initial build), service.py (1-for-1 append)
    # =========================================================================

    def build_queue(self, channel: dict,
                    start_show_index: Optional[int] = None) -> list:
        """2.x compatibility alias for build_channel_queue.
        player.py calls this name; removed once player.py is rewritten in
        Phase 4.
        """
        return self.build_channel_queue(channel,
                                        start_show_index=start_show_index)

    def build_channel_queue(self, channel: dict,
                            start_show_index: Optional[int] = None,
                            keep_places=None) -> list:
        """Build a fresh queue of exactly queue_size items for any channel type.

        Called on channel create, reset, or edit requiring rebuild.
        Writes the cursor and returns the queue list (caller writes to disk).

        spec §7.2

        Returns [] without building when state.json cannot be read: a build
        writes the cursor, which must not happen from an empty stand-in.

        keep_places: for a TV channel, True (or a set of show ids as text)
        makes the build continue those shows from their saved positions
        instead of from the channel's starting episodes.  Used when a queue
        has to be rebuilt although the channel has been playing (its queue
        file was missing or unreadable), so no show goes back to its first
        episode.  None (the default) is the behaviour of a first build.
        """
        if not self._ensure_state():
            log("[ChannelManager] build_channel_queue: state.json "
                "unreadable - '{}' not built".format(
                    channel.get("name", channel.get("id", "?"))),
                level=xbmc.LOGWARNING)
            return []
        channel_id  = channel["id"]
        target_size = int(channel.get("queue_size",
                                      self._default_queue_size()))
        ctype       = channel.get("channel_type", "tv")

        if ctype == "tv":
            return self._build_fresh_tv_queue(channel, target_size,
                                              start_show_index,
                                              keep_places)
        if ctype == "movies":
            from resources.lib.channels.movies import MovieQueueBuilder
            return self.build_planned_queue(
                channel, MovieQueueBuilder(self).build, target_size)
        if ctype == "folder":
            from resources.lib.channels.folder import FolderQueueBuilder
            return self.build_planned_queue(
                channel, FolderQueueBuilder(self).build, target_size)
        if ctype == "audio":
            from resources.lib.channels.audio import AudioQueueBuilder
            return AudioQueueBuilder(self).build(channel, target_size)
        if ctype == "party":
            from resources.lib.channels.party import PartyQueueBuilder
            return PartyQueueBuilder(self).build(channel, target_size)
        if ctype == "combo":
            from resources.lib.channels.combo import ComboQueueBuilder
            return ComboQueueBuilder(self).build(channel, target_size)

        log("[ChannelManager] build_channel_queue: unknown type '{}' for "
            "channel '{}'".format(ctype, channel.get("name", channel_id)))
        return []

    def weave_interleave_sources(self, channel: dict, items: list,
                                  seed=None) -> list:
        """Weave the channel's interleave sources into a freshly built queue.

        Returns *items* unchanged when the channel has no interleave sources
        or the queue is empty.  Used by every fresh build that supports
        interleave (TV, Movie, Folder), so a reset or rebuild keeps the
        interleaved items.  *seed* is the TV planner's jitter seed (None for
        channels that are not planned).
        """
        if not channel.get("interleave") or not items:
            return items
        from resources.lib.channels.interleave import apply_interleave_list
        woven = apply_interleave_list(
            items, channel,
            self._load_foreign_items,
            self.get_channel,
            seed=seed)
        # Sync combo slot tv_next_ep to the episode after the last one
        # actually woven into the queue (not all fetched items).
        self._sync_combo_state_from_queue(woven, channel)
        log("[ChannelManager] weave_interleave_sources: '{}' {} primary "
            "-> {} total".format(channel.get("name", channel.get("id", "?")),
                                 len(items), len(woven)))
        return woven

    def build_planned_queue(self, channel: dict, build_fn,
                            target_size: int) -> list:
        """Build a fresh queue for a Movie or Folder channel.

        *build_fn(channel, n)* returns n of the channel's own items.  With
        interleave configured the queue holds at least *target_size* of the
        channel's own items, then continues until it ends right after an
        interleaved group and every round-robin TV source has given whole
        rounds of its shows, so it may be longer than target_size.  The
        interleaved items come on top of target_size.  One seed drives both
        the plan and the weave, so the jitter gaps are predicted exactly.
        Without interleave this is just build_fn(channel, target_size).
        """
        if not channel.get("interleave"):
            return build_fn(channel, target_size)
        seed = random.getrandbits(32)
        wanted = plan_interleave_primaries(
            channel, 1, self.get_channel, minimum=target_size, seed=seed)
        items = build_fn(channel, wanted)
        log("[ChannelManager] build_planned_queue: interleave cycle -> {} "
            "own item(s) for '{}' (queue_size {})".format(
                len(items), channel.get("name", channel.get("id", "?")),
                target_size))
        return self.weave_interleave_sources(channel, items, seed=seed)

    def extend_primary_to_cycle(self, channel: dict, primary: list) -> tuple:
        """Return (primary, seed) with *primary* extended so the woven queue
        ends right after an interleaved group and every round-robin TV
        source has given whole rounds of its shows.

        Used by Manage Interleave on a Movie or Folder channel: the queue
        keeps the items it has and gets extra items of its own kind where
        the cycle needs them.  Pass the seed to the weave so the jitter
        gaps match the plan.  The list is returned unchanged (with a seed)
        when no extra items are needed or none can be found.
        """
        seed = random.getrandbits(32)
        wanted = plan_interleave_primaries(
            channel, 1, self.get_channel, minimum=len(primary), seed=seed)
        extended = list(primary)
        while len(extended) < wanted:
            extra = self.get_one_replacement(
                channel["id"], {}, current_queue=extended)
            if not extra:
                log("[ChannelManager] extend_primary_to_cycle: no more "
                    "items for '{}' ({} of {})".format(
                        channel.get("name", channel["id"]),
                        len(extended), wanted))
                break
            extended.append(extra)
        return extended, seed

    def _apply_starting_points(self, channel: dict,
                               cursor: dict) -> None:
        """Translate starting_points from channel definition into cursor ep_pos.

        For each show with a starting_point, finds the episode's index in the
        available episode list and sets cursor ep_pos[sid_str] to that index.
        Called before _build_tv_items so the queue builds from the correct
        episode.  Matches the intent of 2.x _apply_starting_points.
        """
        starting_points = channel.get("starting_points", {})
        if not starting_points:
            return

        for sid_str, ep_info in starting_points.items():
            try:
                sid = int(sid_str)
            except (ValueError, TypeError):
                continue

            show = next(
                (s for s in channel.get("shows", [])
                 if s["tvshowid"] == sid), None)
            if not show:
                continue

            episodes = self.get_available_episodes(show)
            if not episodes:
                continue

            chosen_id = ep_info.get("episodeid")
            idx = next(
                (i for i, ep in enumerate(episodes)
                 if ep["episodeid"] == chosen_id), None)

            if idx is not None:
                cursor["ep_pos"][str(sid)] = idx
                log("[ChannelManager] _apply_starting_points: show {} "
                    "starting at index {} (S{}E{} '{}')".format(
                    sid, idx,
                    ep_info.get("season", "?"),
                    ep_info.get("episode", "?"),
                    ep_info.get("title", "")))
            else:
                log("[ChannelManager] _apply_starting_points: episodeid {} "
                    "not found for show {} — starting from beginning".format(
                    chosen_id, sid))

    def _build_planned_tv_items(self, channel: dict, target_size: int,
                                start_cursor: dict) -> tuple:
        """Build the primary TV items for a queue and return
        (items, cursor, weave_seed).

        queue_size is a minimum and counts every item in the queue.  With
        interleave configured the build continues to the end of the
        interleave cycle, so the queue ends right after an interleaved
        group instead of part-way through a group of primary items.
        One seed drives both the plan and the later weave
        (apply_interleave_list(..., seed=weave_seed)), so jitter gaps are
        predicted exactly.  weave_seed is None when no plan was made.
        Serial channels cannot have interleave (spec §6.8) and stop at
        exactly the requested size.
        Used by _build_fresh_tv_queue and regenerate_queue.
        """
        weave_seed = None
        if (channel.get("interleave")
                and channel.get("playback_mode") != "serial"):
            weave_seed = random.getrandbits(32)
            wanted = plan_interleave_primaries(
                channel, target_size, self.get_channel, seed=weave_seed)
            for _ in range(500):
                items, cursor = self._build_tv_items(
                    channel, wanted, copy.deepcopy(start_cursor))
                if len(items) <= wanted:
                    break          # as planned (or the pool ran out)
                # The show rotation had to build more than planned.
                wanted = plan_interleave_primaries(
                    channel, target_size, self.get_channel,
                    minimum=len(items), seed=weave_seed)
            log("[ChannelManager] _build_planned_tv_items: interleave "
                "cycle -> {} primary item(s) for '{}' (queue_size {})"
                .format(len(items), channel.get("name", channel["id"]),
                        target_size))
        else:
            items, cursor = self._build_tv_items(
                channel, target_size, copy.deepcopy(start_cursor))
        return items, cursor, weave_seed

    def _rewind_tv_cursor(self, channel: dict, primaries: list):
        """Return a copy of the channel cursor moved back to just before
        *primaries* (the primary items of the existing queue, in order),
        or None when that cannot be done reliably.

        Sequential shows: ep_pos goes back to the first queued episode of
        the show.  Randomised shows: the queued episodes are removed from
        ep_played.  show_slot goes back to the show of the first item.
        """
        shows = channel.get("shows", [])
        if not shows or not primaries:
            return None
        cursor = copy.deepcopy(self.get_cursor(channel["id"]))
        cursor["slot_owed"] = {}
        randomize = channel.get("randomize", False)
        show_ids = [str(sh["tvshowid"]) for sh in shows]
        first_sid = str(primaries[0].get("show_id"))
        if first_sid not in show_ids:
            return None
        cursor["show_slot"] = show_ids.index(first_sid)
        for sh in shows:
            sid = str(sh["tvshowid"])
            queued = [it for it in primaries if str(it.get("show_id")) == sid]
            if not queued:
                continue
            if sh.get("randomize", randomize):
                ids = set()
                for it in queued:
                    ids.update(it.get("_span_ids") or [it.get("episodeid")])
                cursor["ep_played"][sid] = [
                    e for e in cursor["ep_played"].get(sid, [])
                    if e not in ids]
                continue
            eps = self.get_available_episodes(sh)
            first_id = queued[0].get("episodeid")
            pos = next((i for i, e in enumerate(eps)
                        if e.get("episodeid") == first_id), None)
            if pos is None:
                return None
            cursor["ep_pos"][sid] = pos
        return cursor

    def _build_fresh_tv_queue(self, channel: dict,
                               target_size: int,
                               start_show_index: Optional[int] = None,
                               keep_places=None) -> list:
        """Build a fresh TV queue using a zero cursor.

        Applies interleave if configured.  Writes the cursor to state.
        """
        channel_id = channel["id"]
        shows      = channel.get("shows", [])

        zero = dict(self._ZERO_CURSOR)
        zero["ep_pos"]    = {}
        zero["ep_played"] = {}
        zero["slot_owed"] = {}

        if (start_show_index is not None
                and isinstance(start_show_index, int)
                and 0 < start_show_index < len(shows)):
            zero["show_slot"] = start_show_index
            log("[ChannelManager] _build_fresh_tv_queue: seeding "
                "show_slot={}".format(start_show_index))
        else:
            zero["show_slot"] = 0

        # Apply starting points — translates starting_points from the
        # channel definition into ep_pos entries in the cursor so the
        # queue builds from the user's chosen starting episodes.
        self._apply_starting_points(channel, zero)

        # A rebuild of a channel that has been playing continues each show
        # from its saved position, ahead of the starting episodes the
        # channel was created with.
        if keep_places:
            show_ids = {str(sh["tvshowid"]) for sh in shows}
            for sid_str, pos in self.get_cursor(channel_id).get(
                    "ep_pos", {}).items():
                if (sid_str in show_ids
                        and (keep_places is True or sid_str in keep_places)
                        and isinstance(pos, int) and pos > 0):
                    zero["ep_pos"][sid_str] = pos

        items, cursor, weave_seed = self._build_planned_tv_items(
            channel, target_size, zero)
        # The queue and the saved positions must agree.  If the positions
        # cannot be saved, the queue is not handed back to be written: the
        # old queue and old positions stay as a matching pair.
        if not self.set_cursor(channel_id, cursor):
            ChannelManager._rebuild_failed.add(channel_id)
            log("[ChannelManager] _build_fresh_tv_queue: positions for '{}' "
                "could not be saved - queue not rebuilt, old queue and "
                "positions kept".format(channel.get("name", channel_id)),
                level=xbmc.LOGWARNING)
            return []

        items = self.weave_interleave_sources(channel, items,
                                               seed=weave_seed)

        log("[ChannelManager] _build_fresh_tv_queue: built {} items for '{}'"
            .format(len(items), channel.get("name", channel_id)))
        journal.record(
            "build", ch=self._journal_channel(channel_id),
            keep_places=(sorted(keep_places) if isinstance(keep_places, set)
                         else keep_places),
            queue=[[i.get("show_id") or i.get("_show_id"), i.get("season"),
                    i.get("episode"), i.get("episodeid")]
                   for i in items if not i.get("_interleaved")],
            via=journal.chain(1, 6))
        return items

    # =========================================================================
    # _build_tv_items  (spec §8.2–8.4)
    # Pure function: reads library + cursor, returns (items, cursor), no I/O.
    # =========================================================================

    def _build_tv_items(self, channel: dict, n_requested: int,
                        cursor: dict) -> tuple:
        """Build TV episode queue items using the cursor.

        Returns (items, updated_cursor).  No file I/O performed.

        For round_robin channels the builder completes a full rotation cycle
        before stopping (may slightly overshoot n_requested to avoid mid-cycle
        truncation).  For serial channels it stops exactly at n_requested and
        records slot_owed for continuation.

        spec §8.2–8.4
        """
        channel_id = channel["id"]
        shows      = channel.get("shows", [])
        mode       = channel.get("playback_mode", "round_robin")
        randomize  = channel.get("randomize", False)
        recycle    = channel.get("recycle",   True)

        if not shows:
            log("[ChannelManager] _build_tv_items: no shows in '{}'"
                .format(channel.get("name", channel_id)))
            return [], cursor

        cursor = copy.deepcopy(cursor)

        # Pre-load episode pools (filters + exclusions applied)
        all_episodes: dict[str, list] = {}
        for show in shows:
            sid_str = str(show["tvshowid"])
            eps     = self.get_available_episodes(show)
            if eps:
                all_episodes[sid_str] = eps

        if not all_episodes:
            log("[ChannelManager] _build_tv_items: no episodes for '{}'"
                .format(channel.get("name", channel_id)))
            return [], cursor

        items:    list = []
        exhausted: set = set()
        # sid -> index in items where the show's current pass began.  The
        # no-duplicate-file check only looks from there, so a show that
        # recycles (last episode -> first) is not skipped.
        pass_start: dict = {}

        # --- Phase 1: complete any in-progress slots (slot_owed > 0) ---------
        for sid_str, owed in list(cursor.get("slot_owed", {}).items()):
            if owed <= 0:
                cursor["slot_owed"].pop(sid_str, None)
                continue
            show     = next((s for s in shows
                             if str(s["tvshowid"]) == sid_str), None)
            episodes = all_episodes.get(sid_str, [])
            if not show or not episodes:
                cursor["slot_owed"].pop(sid_str, None)
                continue
            placed = self._fill_slot(show, sid_str, owed, episodes, cursor,
                                     randomize, recycle, channel_id, items,
                                     all_episodes, mode,
                                     pass_start.get(sid_str, 0))
            if placed >= owed:
                cursor["slot_owed"].pop(sid_str, None)
            else:
                cursor["slot_owed"][sid_str] = owed - placed
                if not recycle:
                    exhausted.add(sid_str)

        # --- Phase 2: rotation loop ------------------------------------------
        cycle_start_slot   = cursor.get("show_slot", 0)
        stall_count        = 0  # consecutive shows that placed 0 items

        while True:
            if len(exhausted) >= len(shows):
                break

            show_slot = cursor.get("show_slot", 0)
            show_idx  = show_slot % len(shows)
            show      = shows[show_idx]
            sid_str   = str(show["tvshowid"])

            # Round-robin stop: n_requested met AND back to cycle start.
            # Must complete the full cycle so every show has an episode in
            # the initial queue — otherwise shows beyond n_requested would
            # never appear until the cursor cycles back to them via 1-for-1
            # replacement, breaking uniform rotation.
            if len(items) >= n_requested and mode != "serial":
                if show_slot % len(shows) == cycle_start_slot % len(shows):
                    break

            # Serial stop: n_requested met
            if len(items) >= n_requested and mode == "serial":
                break

            episodes = all_episodes.get(sid_str, [])
            if not episodes:
                cursor["show_slot"] = show_slot + 1
                exhausted.add(sid_str)
                continue

            eps_per_slot = self._eps_per_slot(show, mode, episodes)

            # Pool-empty pre-check
            if self._is_pool_empty(sid_str, episodes, cursor, show, randomize):
                if not recycle:
                    cursor["show_slot"] = show_slot + 1
                    exhausted.add(sid_str)
                    continue
                self._reset_pool(sid_str, cursor, randomize)
                pass_start[sid_str] = len(items)
                stall_count = 0
                continue  # show_slot NOT incremented — retry same show

            cursor["show_slot"] = show_slot + 1
            # Cap to prevent unbounded growth
            if cursor["show_slot"] >= len(shows) * 1000:
                cursor["show_slot"] = cursor["show_slot"] % len(shows)

            prev_count = len(items)
            placed     = self._fill_slot(show, sid_str, eps_per_slot,
                                         episodes, cursor,
                                         randomize, recycle, channel_id,
                                         items, all_episodes, mode,
                                         pass_start.get(sid_str, 0))

            if len(items) == prev_count:
                stall_count += 1
            else:
                stall_count = 0

            if stall_count >= len(shows):
                log("[ChannelManager] _build_tv_items: full rotation stalled "
                    "— stopping at {} items".format(len(items)))
                break

            if placed < eps_per_slot:
                if mode == "serial":
                    remaining = eps_per_slot - placed
                    if remaining > 0:
                        cursor["slot_owed"][sid_str] = remaining
                if not recycle and placed == 0:
                    exhausted.add(sid_str)

        log("[ChannelManager] _build_tv_items: built {} items for '{}' "
            "(mode={} requested={})".format(
                len(items), channel.get("name", channel_id),
                mode, n_requested))
        return items, cursor

    def _fill_slot(self, show: dict, sid_str: str, count: int,
                   episodes: list, cursor: dict,
                   randomize: bool, recycle: bool,
                   channel_id: str, items: list,
                   all_episodes: dict,
                   mode: str = "round_robin",
                   pass_start: int = 0) -> int:
        """Place up to count episodes from show into items.

        Handles sequential (ep_pos) and random (ep_played) placement.
        Advances cursor by multi-episode span when applicable.
        Skips items with missing duration (logs via record_missing_duration).

        pass_start is the index in items where this show's current pass
        through its episodes began: the duplicate-file check only considers
        items from there on, so a recycled show may queue its first episode
        again.

        Returns the number of episodes actually placed.
        """
        from resources.lib.utils.multi_episode import (
            count_episode_span as _count_span,
            span_episode_ids   as _span_ids_fn,
        )

        show_randomize = show.get("randomize", randomize)
        ep_ids         = [e["episodeid"] for e in episodes]
        placed         = 0
        queued_files   = {item.get("file", "") for item in items[pass_start:]
                          if item.get("file")}

        # Seed ep_pos from show state on first access (sequential mode)
        if not show_randomize and sid_str not in cursor["ep_pos"]:
            cursor["ep_pos"][sid_str] = 0

        max_attempts = len(episodes) * 2 + count + 10
        attempts     = 0

        while placed < count and attempts < max_attempts:
            attempts += 1

            if show_randomize:
                played_set = set(cursor["ep_played"].get(sid_str, []))
                unplayed   = [eid for eid in ep_ids if eid not in played_set]
                if not unplayed:
                    break  # caller handles recycle
                chosen_id = random.choice(unplayed)
                ep = next((e for e in episodes
                           if e["episodeid"] == chosen_id), None)
                if ep is None:
                    break
            else:
                idx = cursor["ep_pos"].get(sid_str, 0)
                if idx >= len(episodes):
                    break  # caller handles recycle
                ep = episodes[idx]

            # Skip duplicate files (sequential round_robin only)
            ep_file = ep.get("file", "")
            if (ep_file and ep_file in queued_files
                    and not show_randomize and mode != "serial"):
                cursor["ep_pos"][sid_str] = \
                    cursor["ep_pos"].get(sid_str, 0) + 1
                continue

            # Multi-episode span detection
            span     = _count_span(ep)
            span_ids = _span_ids_fn(ep, episodes) if span > 1 else [ep["episodeid"]]

            # Normalise (reads duration)
            norm = _normalize_ep_fn(ep, channel_id, int(sid_str),
                                    all_episodes_for_show=episodes,
                                    default_seconds=self._default_episode_seconds())
            self._note_default_length(channel_id, ep, norm)
            if norm is None:
                # Missing duration — skip, advance cursor past it
                self.record_missing_duration(channel_id, ep, "no_nfo")
                if not show_randomize:
                    cursor["ep_pos"][sid_str] = \
                        cursor["ep_pos"].get(sid_str, 0) + 1
                else:
                    played_list = cursor["ep_played"].setdefault(sid_str, [])
                    if ep["episodeid"] not in played_list:
                        played_list.append(ep["episodeid"])
                continue

            # Advance cursor by span
            if not show_randomize:
                cursor["ep_pos"][sid_str] = \
                    cursor["ep_pos"].get(sid_str, 0) + span
            else:
                played_list = cursor["ep_played"].setdefault(sid_str, [])
                for eid in span_ids:
                    if eid not in played_list:
                        played_list.append(eid)

            # Track queued files to avoid duplicates
            if ep_file:
                queued_files.add(ep_file)
                for eid in span_ids:
                    s_ep = next((e for e in episodes
                                 if e["episodeid"] == eid), None)
                    if s_ep and s_ep.get("file"):
                        queued_files.add(s_ep["file"])

            items.append(norm)
            placed += span  # multi-episode files count as span slots

        return placed

    @staticmethod
    def _eps_per_slot(show: dict, mode: str, episodes: list) -> int:
        if mode == "serial":
            return len(episodes)
        return max(1, int(show.get("episodes_per_slot", 1)))

    def _is_pool_empty(self, sid_str: str, episodes: list, cursor: dict,
                       show: dict, randomize: bool) -> bool:
        show_randomize = show.get("randomize", randomize)
        if show_randomize:
            played_set = set(cursor["ep_played"].get(sid_str, []))
            return all(e["episodeid"] in played_set for e in episodes)
        idx = cursor["ep_pos"].get(sid_str, 0)
        return idx >= len(episodes)

    @staticmethod
    def _reset_pool(sid_str: str, cursor: dict, randomize: bool) -> None:
        cursor["ep_played"].pop(sid_str, None)
        cursor["ep_pos"][sid_str] = 0

    # =========================================================================
    # Episode pool public API
    # Called by: channels/*.py, ui/*.py, service.py
    # =========================================================================

    def get_available_episodes(self, show_entry: dict) -> list:
        """Return a show's PLAYABLE episode pool: filters + exclusions applied.
        Delegates to channels/base.py — single source of truth.
        """
        return _get_available_episodes_fn(show_entry, self.library)

    def get_filtered_episodes(self, show_entry: dict) -> list:
        """Return a show's episode pool with filters applied only (no exclusions).
        Used by the exclusions picker UI.
        Delegates to channels/base.py — single source of truth.
        """
        return _get_filtered_episodes_fn(show_entry, self.library)

    # =========================================================================
    # Multi-episode span public API
    # Called by: service.py, ui/channels.py
    # =========================================================================

    def get_episode_span(self, episode_dict: dict) -> int:
        from resources.lib.utils.multi_episode import count_episode_span
        return count_episode_span(episode_dict)

    def get_span_episode_ids(self, episode_dict: dict,
                             all_episodes_for_show: list) -> list:
        from resources.lib.utils.multi_episode import span_episode_ids
        return span_episode_ids(episode_dict, all_episodes_for_show)

    # =========================================================================
    # Missing duration logging  (spec §7.5)
    # Called by: _fill_slot, channels/folder.py
    # =========================================================================

    def record_missing_duration(self, channel_id: str, item: dict,
                                reason: str) -> None:
        """Record a skipped item (zero/missing duration) in two places:

        1. Per-channel list in state.json — what context menus read.
        2. missing_durations.txt in the addon profile — permanent human log.

        Each file is recorded once per Kodi session; a burst of skips is
        written in batches (see MISSING_FLUSH_MAX / MISSING_FLUSH_SECONDS).

        spec §7.5
        """
        import datetime as _dt

        file_path = item.get("file", "")
        # A raw Kodi episode names its show "showtitle"; a queue item
        # "tvshowtitle"; a movie has neither (3.1.159).
        show      = (item.get("tvshowtitle") or item.get("showtitle")
                     or item.get("title", ""))
        title     = item.get("title", "")
        season    = int(item.get("season",  0) or 0)
        episode   = int(item.get("episode", 0) or 0)
        ep_label  = ("S{:02d}E{:02d}".format(season, episode)
                     if season else "")

        # Recorded once per file per Kodi session, then written in batches.
        seen_key = (channel_id, file_path)
        ch_obj   = self.get_channel(channel_id)
        ch_name  = (ch_obj.get("name", channel_id) if ch_obj else channel_id)
        now_dt   = _dt.datetime.utcnow()
        entry = {
            "show":    show,
            "title":   title,
            "episode": ep_label,
            "file":    file_path,
            "reason":  reason,
            "ts":      int(now_dt.timestamp()),
        }
        line = "{}\t{}\t{}\t{}\t{}\t{}\n".format(
            now_dt.strftime("%Y-%m-%d %H:%M:%S"), ch_name, show, ep_label,
            file_path, reason)
        cls = ChannelManager
        with cls._MISSING_LOCK:
            if (seen_key in cls._missing_seen
                    or any(e["file"] == file_path
                           for e in cls._missing_pending.get(channel_id, ()))):
                return
            cls._missing_pending.setdefault(channel_id, []).append(entry)
            cls._missing_lines.append(line)
            waiting = sum(len(v) for v in cls._missing_pending.values())
            flush_now = (waiting >= self.MISSING_FLUSH_MAX
                         or time.time() - cls._missing_flushed_at
                         >= self.MISSING_FLUSH_SECONDS)
            if not flush_now and cls._missing_timer is None:
                timer = threading.Timer(self.MISSING_FLUSH_SECONDS,
                                        self._flush_missing_later)
                timer.daemon = True
                cls._missing_timer = timer
                timer.start()
        if flush_now:
            self.flush_missing_durations()

    DEFAULT_LENGTH_REASON = "default_length"

    def _note_default_length(self, channel_id: str, raw: dict, norm) -> None:
        """Note an item that was queued with the default length because its
        NFO gave no duration and Kodi held no running time (3.1.159).

        ``norm`` is what normalize_ep / normalize_movie returned for the raw
        Kodi item ``raw``.  Only the default-length guess is noted: an NFO or
        Kodi running time is not, an item that was skipped is noted by its
        caller, and folder items (which always use a default) do not come
        through here.  Recording only: the item stays in the queue.
        """
        if norm is None or getattr(norm, "duration_source", "") != "default_setting":
            return
        self.record_missing_duration(channel_id, raw,
                                     self.DEFAULT_LENGTH_REASON)

    def _flush_missing_later(self) -> None:
        """Timer callback: write whatever is waiting with a fresh manager,
        so the state it merges back is current, not this object's copy."""
        try:
            ChannelManager(self.addon).flush_missing_durations()
        except Exception as exc:
            log("[ChannelManager] flush_missing_durations (timer) error: "
                "{}".format(exc), level=xbmc.LOGWARNING)

    def flush_missing_durations(self) -> None:
        """Write the waiting skipped-item entries: one state.json save for all
        channels and one rewrite of missing_durations.txt for all lines."""
        cls = ChannelManager
        with cls._MISSING_LOCK:
            pending, cls._missing_pending = cls._missing_pending, {}
            lines,   cls._missing_lines   = cls._missing_lines, []
            timer,   cls._missing_timer   = cls._missing_timer, None
            previous_flush = cls._missing_flushed_at
            cls._missing_flushed_at = time.time()
        if timer is not None:
            timer.cancel()
        if not pending and not lines:
            return

        # 1. Per-channel state lists, one save for all of them
        saved = False
        try:
            for channel_id, entries in pending.items():
                state_key = "{}:missing_durations".format(channel_id)
                existing  = list(self.read_state_key(state_key, []))
                known     = {e.get("file", "") for e in existing}
                added     = [e for e in entries
                             if e.get("file", "") not in known]
                if added:
                    existing.extend(added)
                    if len(existing) > 200:
                        existing = existing[-200:]
                    self._deleted_state_keys.discard(state_key)
                    self._state[state_key] = existing
            saved = self._save_state()
        except Exception as exc:
            log("[ChannelManager] record_missing_duration state error: "
                "{}".format(exc))
        if not saved:
            # state.json could not be written (unreadable or share down):
            # keep the entries for the next flush instead of losing them.
            with cls._MISSING_LOCK:
                for channel_id, entries in pending.items():
                    cls._missing_pending.setdefault(channel_id, [])[:0] = entries
                cls._missing_lines[:0] = lines
                cls._missing_flushed_at = previous_flush
            return
        with cls._MISSING_LOCK:
            for channel_id, entries in pending.items():
                for e in entries:
                    cls._missing_seen.add((channel_id, e.get("file", "")))

        # 2. Global missing_durations.txt, one rewrite for all lines
        try:
            txt_path = self._resolve_path("missing_durations.txt")
            existing_txt = ""
            if xbmcvfs.exists(txt_path):
                try:
                    rf = xbmcvfs.File(txt_path, "r")
                    existing_txt = rf.read()
                    rf.close()
                except Exception:
                    existing_txt = ""
            wf = xbmcvfs.File(txt_path, "w")
            wf.write(existing_txt + "".join(lines))
            wf.close()
        except Exception as exc:
            log("[ChannelManager] record_missing_duration txt error: "
                "{}".format(exc))

    def get_missing_durations(self, channel_id: str) -> list:
        """Return the per-channel missing_durations list from state.json."""
        state_key = "{}:missing_durations".format(channel_id)
        try:
            state = self._load_json(self._state_path, {})
            return state.get(state_key, [])
        except Exception:
            return []

    # =========================================================================
    # Carousel state  (spec §4.4, §9.3)
    # Called by: carousel.py, service.py
    # =========================================================================

    def get_carousel_state(self, channel_id: str) -> dict:
        key = "{}:carousel".format(channel_id)
        return self._state.get(key, {})

    def set_carousel_state(self, channel_id: str, value: dict) -> None:
        key = "{}:carousel".format(channel_id)
        self._deleted_state_keys.discard(key)
        prev = self._clock_of_entry(self._state.get(key))
        self._state[key] = value
        # The channel's own file is the authoritative copy (3.1.146); the
        # save of state.json after it keeps the mirror an older build reads.
        # Both writes happen under one hold of the shared-folder lock.
        with self._lock_scope(self.WRITE_LOCK_WAIT_MS):
            self._write_clock_entry(channel_id, value, prev=prev)
            self._save_state()

    # ------------------------------------------------------------------
    # Per-channel carousel file (3.1.146, slice 1 of the per-channel state)
    #
    # state.json is one file that every device reads, changes and writes
    # whole, over a share with no locking.  A device that read it just before
    # another device saved a pop wrote the OLD carousel clock back, and the
    # next check found the same pop due again (11/08 20:41: Bedroom and
    # Kidsroom, 4.9 s apart).  The carousel entry of a channel (clock, last
    # popped show, pop claim) now lives in chanstate_<channel id>.json, a
    # small file that only the device popping or playing that channel writes.
    # Reads take the entry from there.  state.json keeps a copy of it, so the
    # build before this one (and the diagnostics) still find the clock.  A
    # channel with no file yet is read from state.json, and the first write
    # creates the file.
    # ------------------------------------------------------------------

    def _clock_file_path(self, channel_id: str) -> str:
        return self._resolve_path("chanstate_{}.json".format(channel_id))

    def _read_clock_entry(self, channel_id: str) -> tuple:
        """(entry, readable, writer): the channel's carousel entry from its
        own file; entry None when the file does not exist or holds none;
        readable False when the file exists but cannot be read."""
        try:
            data = load_json_strict(self._clock_file_path(channel_id), None)
        except JsonReadError as exc:
            log("[ChannelManager] cannot read the carousel file of {}: {}"
                .format(channel_id[:8], exc), level=xbmc.LOGWARNING)
            return None, False, None
        if not isinstance(data, dict):
            return None, True, None
        entry = data.get("carousel")
        writer = data.get("_writer")
        return (entry if isinstance(entry, dict) else None), True, writer

    @staticmethod
    def _clock_of_entry(entry):
        """last_pop_time of a carousel entry as a float, or None."""
        try:
            return float(entry.get("last_pop_time")) \
                if isinstance(entry, dict) \
                and entry.get("last_pop_time") is not None else None
        except (TypeError, ValueError):
            return None

    def _queue_stamp(self, channel_id: str):
        """[mtime, size] of the channel's queue file as seen now, or None.
        Journalled with each clock write: a clock that moved while the queue
        file did not change had no pop behind it.  (3.1.147)"""
        try:
            st = xbmcvfs.Stat(self._queue_file_path(channel_id))
            return [int(st.st_mtime()), int(st.st_size())]
        except Exception:
            return None

    def _clock_write_evidence(self, channel_id: str, prev, clock: float,
                              via: str) -> dict:
        """Fields for the chanstate_write line, and a 'clock_jump' line when
        the clock moved forward by more than CLOCK_JUMP_SECONDS although this
        process won no claim on the channel in the last CLOCK_JUMP_CLAIM_AGE
        seconds and the write is not the hold of a playing channel.  Logging
        only; never raises.  (3.1.147)"""
        try:
            cls = ChannelManager
            # The caller may have changed the entry in place before the
            # write, so the clock to compare with is the one last read from
            # the file or written, not the one in memory.
            known = cls._last_clock.get(channel_id)
            if known is not None:
                prev = known
            cls._last_clock[channel_id] = clock
            q = self._queue_stamp(channel_id)
            q_prev = cls._queue_stamps.get(channel_id)
            cls._queue_stamps[channel_id] = q
            fields = {"prev": prev, "q": q, "q_prev": q_prev}
            if prev is None:
                return fields
            delta = round(clock - prev, 1)
            fields["delta"] = delta
            won = cls._won_at.get(channel_id)
            claim_age = round(time.time() - won, 1) if won else None
            if (delta > self.CLOCK_JUMP_SECONDS
                    and "_hold_clock_while_playing" not in (via or "")
                    and (claim_age is None
                         or claim_age > self.CLOCK_JUMP_CLAIM_AGE)):
                self._jrec("clock_jump", ch=self._journal_channel(channel_id),
                           prev=prev, clock=clock, delta=delta, via=via,
                           claim_age=claim_age, q=q, q_prev=q_prev,
                           queue_changed=(q != q_prev))
                log("[ChannelManager] carousel clock of {} moved forward {:.0f}"
                    "s with no claim won here ({})".format(
                        channel_id[:8], delta, via), level=xbmc.LOGWARNING)
            return fields
        except Exception:
            return {}

    def _write_clock_entry(self, channel_id: str, entry: dict,
                           via: str = "", prev=None) -> bool:
        """Write the channel's carousel entry to its own file.  True when it
        was written.  Never raises: the mirror save that follows still runs."""
        try:
            via = via or journal.chain(2, 6)
            data = {"carousel": entry, "_writer": self._writer_tag(via)}
            ok = bool(save_json(self._clock_file_path(channel_id), data))
            try:
                clock = float((entry or {}).get("last_pop_time") or 0)
            except (TypeError, ValueError):
                clock = 0.0
            extra = self._clock_write_evidence(channel_id, prev, clock, via)
            self._jrec("chanstate_write", ch=self._journal_channel(channel_id),
                       clock=clock, ok=ok, via=via, **extra)
            if not ok:
                log("[ChannelManager] the carousel file of {} could not be "
                    "written".format(channel_id[:8]), level=xbmc.LOGWARNING)
            return ok
        except Exception as exc:
            log("[ChannelManager] _write_clock_entry error: {}".format(exc),
                level=xbmc.LOGWARNING)
            return False

    def refresh_carousel_clocks(self, channel_ids) -> None:
        """Take the carousel entry of each channel from its own file as this
        manager's copy, without marking it as a change of this manager (as
        _adopt_carousel).  A channel with no file, or an unreadable one, is
        left as it is.  Called by the carousel tick before the due-checks."""
        for cid in channel_ids or []:
            try:
                entry, ok, _w = self._read_clock_entry(cid)
                if ok and entry is not None:
                    self._adopt_carousel("{}:carousel".format(cid), entry)
                    seen = self._clock_of_entry(entry)
                    if seen is not None:
                        ChannelManager._last_clock[cid] = seen
            except Exception as exc:
                log("[ChannelManager] refresh_carousel_clocks error: {}"
                    .format(exc), level=xbmc.LOGWARNING)

    def _with_clock_files(self, disk: dict) -> dict:
        """A copy of the state.json content in which the carousel entry of
        every carousel channel is the one from its own file (for the
        diagnostics, which compare clocks).  Unreadable files are skipped."""
        out = dict(disk)
        for ch in self._channels:
            if not ch.get("carousel_enabled", False):
                continue
            entry, ok, _w = self._read_clock_entry(ch["id"])
            if ok and entry is not None:
                out["{}:carousel".format(ch["id"])] = entry
        return out

    def get_carousel_elapsed(self, channel_id: str):
        """Return seconds elapsed since the last carousel pop for channel_id.

        Returns None if last_pop_time is absent (carousel has never fired).
        Used by channel info display.  Ported from 2.x channel_manager.py.
        """
        import time as _time
        try:
            state    = self.get_carousel_state(channel_id)
            last_pop = state.get("last_pop_time")
            if last_pop is None:
                return None
            return max(0.0, _time.time() - float(last_pop))
        except Exception as exc:
            log("[ChannelManager] get_carousel_elapsed error: {}".format(exc))
            return None

    # =========================================================================
    # State key generic public API
    # Called by: scheduler.py, service.py, channels/serial.py
    # =========================================================================

    def read_state_key(self, key: str, default=None):
        """Read a single key from state.json (always fresh from disk)."""
        try:
            fresh = self._load_json(self._state_path, {})
            return fresh.get(key, default)
        except Exception as exc:
            log("[ChannelManager] read_state_key '{}' error: {}".format(
                key, exc))
            return default

    def write_state_key(self, key: str, value) -> None:
        """Write a single key/value to state.json."""
        try:
            self._deleted_state_keys.discard(key)
            self._state[key] = value
            self._save_state()
        except Exception as exc:
            log("[ChannelManager] write_state_key '{}' error: {}".format(
                key, exc))

    # =========================================================================
    # Channel lock  (3.1.109)
    # One device at a time may play a given channel.  The lock is a small file
    # next to the queue file on the shared storage.  Called by: player.py,
    # router.py, service.py, carousel.py
    # =========================================================================

    def get_device_id(self) -> str:
        """Return this device's random ID, creating it on first use.

        Stored in the local profile (never on the shared storage) so every
        device has its own.
        """
        cached = getattr(self, "_device_id", "")
        if cached:
            return cached
        path = os.path.join(self.profile, "device_id.json")
        data = self._load_json(path, {})
        dev_id = data.get("device_id", "") if isinstance(data, dict) else ""
        if not dev_id:
            dev_id = str(uuid.uuid4())
            self._save_json(path, {"device_id": dev_id})
        self._device_id = dev_id
        return dev_id

    def get_device_label(self) -> str:
        """Return a short readable name for this device, for log lines.

        The device's friendly name plus the first four characters of its
        device ID, e.g. "SHIELD #a1b2".  The ID part tells apart two devices
        that share a name.  Used so a log can say which device acted.
        (3.1.116)
        """
        cached = getattr(self, "_device_label", "")
        if cached:
            return cached
        try:
            name = (xbmc.getInfoLabel("System.FriendlyName") or "").strip()
        except Exception:
            name = ""
        label = "{} #{}".format(name or "Kodi", self.get_device_id()[:4])
        if name:                       # name not known yet at start-up: retry later
            self._device_label = label
        return label

    def _channel_lock_path(self, channel_id: str) -> str:
        return self._resolve_path("channel_lock_{}.json".format(channel_id))

    def _owned_lock_path(self) -> str:
        return os.path.join(self.profile, "channel_lock_owned.json")

    def _lock_is_live(self, lock) -> bool:
        """True when the lock data looks like a running owner's."""
        if not isinstance(lock, dict) or not lock.get("device_id"):
            return False
        try:
            age = abs(time.time() - float(lock.get("updated_at", 0)))
        except (TypeError, ValueError):
            return False
        return age <= self.LOCK_STALE_SECONDS

    def channel_lock_holder(self, channel_id: str) -> Optional[dict]:
        """Return the lock of ANOTHER device that is still alive, else None.

        A lock owned by this device, a missing lock and a dead lock all give
        None, so the caller only has to ask "is someone else on it?".
        The result has device_id, device_name, counter and updated_at.
        """
        if not channel_id:
            return None
        lock = self._load_json(self._channel_lock_path(channel_id), None)
        if not self._lock_is_live(lock):
            return None
        if lock.get("device_id") == self.get_device_id():
            return None
        return lock

    def owned_lock_channel(self) -> str:
        """Return the id of the channel this device holds a lock on, or ""."""
        data = self._load_json(self._owned_lock_path(), {})
        return data.get("channel_id", "") if isinstance(data, dict) else ""

    def _write_channel_lock(self, channel_id: str, counter: int) -> None:
        self._save_json(self._channel_lock_path(channel_id), {
            "device_id":   self.get_device_id(),
            "device_name": xbmc.getInfoLabel("System.FriendlyName") or "",
            "counter":     counter,
            "updated_at":  time.time(),
        })
        self._save_json(self._owned_lock_path(), {"channel_id": channel_id})

    def claim_channel_lock(self, channel_id: str) -> bool:
        """Take (or keep) the lock for channel_id.

        Returns False when another device holds a live lock, or when it
        wins a simultaneous claim.  A device holds one lock at a time, so
        the lock for any other channel it held is released first.
        """
        if not channel_id:
            return True
        if self.channel_lock_holder(channel_id):
            return False
        previous = self.owned_lock_channel()
        if previous and previous != channel_id:
            self.release_channel_lock(previous)
        current = self._load_json(self._channel_lock_path(channel_id), None)
        counter = 1
        if isinstance(current, dict) and \
                current.get("device_id") == self.get_device_id():
            counter = int(current.get("counter", 0) or 0) + 1
        self._write_channel_lock(channel_id, counter)
        # Two devices claiming in the same moment: both write, the one
        # whose write landed last owns it; the other reads it back here.
        xbmc.sleep(300)
        return self.channel_lock_holder(channel_id) is None

    def refresh_channel_lock(self, channel_id: str) -> bool:
        """Keep the lock alive while this device plays channel_id.

        Returns False (and writes nothing) when another device now holds a
        live lock, for example after this device slept for several minutes.
        """
        if not channel_id:
            return True
        if self.channel_lock_holder(channel_id):
            log("[ChannelManager] refresh_channel_lock: another device holds "
                "the lock for {}".format(channel_id[-8:]),
                level=xbmc.LOGWARNING)
            return False
        current = self._load_json(self._channel_lock_path(channel_id), None)
        counter = 1
        if isinstance(current, dict) and \
                current.get("device_id") == self.get_device_id():
            counter = int(current.get("counter", 0) or 0) + 1
        self._write_channel_lock(channel_id, counter)
        return True

    def release_channel_lock(self, channel_id: str) -> None:
        """Delete the lock for channel_id if this device owns it."""
        if not channel_id:
            return
        path = self._channel_lock_path(channel_id)
        lock = self._load_json(path, None)
        if isinstance(lock, dict) and \
                lock.get("device_id") == self.get_device_id():
            try:
                if xbmcvfs.exists(path):
                    xbmcvfs.delete(path)
            except Exception as exc:
                log("[ChannelManager] release_channel_lock delete error: {}"
                    .format(exc), level=xbmc.LOGWARNING)
            # save_json wrote the lock through a same-named working copy in
            # the local profile folder; it is not needed any more (3.1.130).
            remove_local_copy("channel_lock_{}.json".format(channel_id))
        if self.owned_lock_channel() == channel_id:
            self._save_json(self._owned_lock_path(), {"channel_id": ""})

    def remove_stale_channel_locks(self) -> int:
        """Delete leftover channel_lock_<id>.json files, in the local folder
        and on the share: locks of channels that no longer exist, and locks
        not refreshed for LOCK_SWEEP_SECONDS.  The lock this device holds is
        never touched.  Nothing is removed when no channel was loaded.
        Returns the number of files removed.  (3.1.130)"""
        if not self._channels or not getattr(self, "_channels_ok", True):
            return 0
        known = {c["id"] for c in self._channels}
        own = self.owned_lock_channel()
        now = time.time()
        removed = 0
        for path in channel_lock_files():
            name = os.path.basename(path.rstrip("/"))
            cid = name[len("channel_lock_"):-len(".json")]
            if cid == own:
                continue
            lock = self._load_json(path, None)
            if cid in known:
                # Only a lock that was read and is plainly old is removed;
                # a file that cannot be read right now is left alone.
                if not isinstance(lock, dict):
                    continue
                try:
                    age = now - float(lock.get("updated_at", 0))
                except (TypeError, ValueError):
                    continue
                if age <= self.LOCK_SWEEP_SECONDS:
                    continue
            try:
                if xbmcvfs.delete(path):
                    removed += 1
                    log("[ChannelManager] removed leftover channel lock "
                        "{}".format(name))
            except Exception as exc:
                log("[ChannelManager] channel lock sweep could not remove "
                    "{}: {}".format(name, exc), level=xbmc.LOGWARNING)
        return removed

    # =========================================================================
    # Channel CRUD
    # =========================================================================

    def get_all_channels(self) -> list:
        return self._channels

    def get_visible_channels(self) -> list:
        return [c for c in self._channels if c.get("visible", True)]

    def get_channel_list_label(self, ch: dict) -> str:
        """Return the name to show for ch in a channel list.

        Hidden channels (only listed when the Show Hidden Channels setting is
        on) are prefixed with the hidden tag (#32230) so they can be told
        apart.
        """
        name = ch.get("name", ch.get("id", ""))
        if not ch.get("visible", True):
            return "{} {}".format(self.addon.getLocalizedString(32230), name)
        return name

    def get_channel(self, channel_id: str) -> Optional[ChannelDef]:
        for ch in self._channels:
            if ch["id"] == channel_id:
                return ch
        return None

    def channel_name_exists(self, name: str, exclude_id: str = "") -> bool:
        """True if another channel (hidden ones included) already has name.

        Comparison ignores case and surrounding spaces.  exclude_id is the
        channel being edited, so keeping its own name is allowed.
        """
        wanted = (name or "").strip().casefold()
        return any(
            (ch.get("name") or "").strip().casefold() == wanted
            for ch in self._channels
            if ch.get("id") != exclude_id)

    def reload_channels(self) -> None:
        self._channels, self._channels_ok = self._read_strict(
            self._channels_path, [])

    def create_channel(self, definition: dict) -> ChannelDef:
        """Create a new channel and persist to channels.json.
        Pre-generates the queue immediately after creation.
        """
        channel = {
            "id":                 str(uuid.uuid4()),
            "name":               definition.get("name",             "Unnamed Channel"),
            "channel_type":       definition.get("channel_type",     "tv"),
            "playback_mode":      definition.get("playback_mode",    "round_robin"),
            "visible":            definition.get("visible",          True),
            "queue_size":         int(definition.get("queue_size",   self._default_queue_size())),
            "recycle":            definition.get("recycle",          True),
            "randomize":          definition.get("randomize",        False),
            "icon_path":          definition.get("icon_path",        ""),
            "interleave":         definition.get("interleave",       None),
            "carousel_enabled":   definition.get("carousel_enabled", False),
            "carousel_mode":      definition.get("carousel_mode",    "timed"),
            "carousel_interval":  definition.get("carousel_interval",  60),
            "carousel_pop_count": definition.get("carousel_pop_count", 1),
            "starting_points":    definition.get("starting_points",  {}),
            "owner":              definition.get("owner",            None),
            "sc_version":         "3.0.0",
            # TV
            "shows":              definition.get("shows",            []),
            "filters":            definition.get("filters",          []),
            # Movies
            "movies":             definition.get("movies",           []),
            "excluded_movies":    definition.get("excluded_movies",  []),
            # Folder
            "folder_path":        definition.get("folder_path",      ""),
            "no_repeat":          definition.get("no_repeat",         False),
            # NOTE: queue_size is not used for combo block channels in 3.x.
            # Combo blocks do not write queue files — items are built on-demand
            # via build_one_slot (1-for-1). The combo wizard no longer asks for
            # or returns queue_size. Existing stored values in channels.json are
            # harmless and left in place; new combo channels will use the default.
            # Audio
            "audio_order":        definition.get("audio_order",      "random"),
            "audio_balanced":     definition.get("audio_balanced",   False),
            "audio_album_shuffle": definition.get("audio_album_shuffle", False),
            "audio_filters":      definition.get("audio_filters",    []),
            "included_albums":    definition.get("included_albums",  {}),
            "excluded_songs":     definition.get("excluded_songs",   []),
            # Combo Block
            "slots":              definition.get("slots",            []),
        }
        self._channels.append(channel)
        self._save_channels()
        log("[ChannelManager] Created channel '{}' id={}".format(
            channel["name"], channel["id"]))
        # Initialise carousel last_pop_time to now so the first tick does NOT
        # fire immediately.  Without this, last_pop_time defaults to 0 and the
        # very first carousel tick sees elapsed >> any reasonable duration,
        # popping the queue front before the user has finished configuring the
        # channel (e.g. adding interleave sources).
        if channel.get("carousel_enabled", False):
            import time as _time
            self.set_carousel_state(channel["id"], {
                "last_pop_time":    _time.time(),
                "last_popped_show": None,
            })
            log("[ChannelManager] Carousel initialised last_pop_time=now "
                "for new channel '{}'".format(channel["name"]))
        self._pregenerate_queue_safe(channel)
        return channel

    def _capture_edit_positions(self, channel_id: str, channel: dict,
                                old_shows: list,
                                queue: Optional[list] = None) -> tuple:
        """Read the live queue before an edit-triggered rebuild.

        Returns (starting_points, start_show_index):
          starting_points  — {str(tvshowid): {episodeid, season, episode,
                             title}} for every sequential show of the edited
                             show list that has an episode in the queue.
          start_show_index — index in the edited show list of the show at the
                             head of the queue (the one now playing); if that
                             show was removed, the next surviving show after
                             it in the old order.  None when unknown or 0.
        New shows have no queued episode, so they start at the beginning.
        """
        shows = channel.get("shows", [])
        if not shows:
            return {}, None

        points = {}
        for show in shows:
            if show.get("randomize", channel.get("randomize", False)):
                continue
            ep = self.get_show_next_queued_episode(
                channel_id, show["tvshowid"], queue=queue)
            if ep and ep.get("episodeid") is not None:
                points[str(show["tvshowid"])] = {
                    "episodeid": ep["episodeid"],
                    "season":    ep.get("season", 1),
                    "episode":   ep.get("episode", 1),
                    "title":     ep.get("title", ""),
                }

        head = next((i for i in (queue if queue is not None
                                 else self.get_channel_queue(channel_id))
                     if not i.get("_interleaved")), None)
        head_sid = (head.get("show_id") or head.get("_show_id")) if head else None
        if head_sid is None:
            return points, None

        new_ids = [s["tvshowid"] for s in shows]
        if head_sid in new_ids:
            return points, new_ids.index(head_sid)

        # Head show was removed: continue with the next surviving show.
        old_ids = [s["tvshowid"] for s in old_shows]
        if head_sid in old_ids:
            n = len(old_ids)
            start = old_ids.index(head_sid)
            for step in range(1, n):
                cand = old_ids[(start + step) % n]
                if cand in new_ids:
                    return points, new_ids.index(cand)
        return points, None

    def update_channel(self, channel_id: str,
                       definition: dict) -> Optional[ChannelDef]:
        """Update an existing channel and rebuild queue if needed."""
        channel = self.get_channel(channel_id)
        if not channel:
            return None

        # An edit that can rebuild the queue first notes where every show
        # is up to from the channel's queue.  If the queue cannot be read
        # right now (another device is writing it) that note would be empty
        # and the rebuild would start every show at its first episode, so
        # nothing is changed or saved; edit_blocked() tells the screen.
        ChannelManager._edit_blocked.discard(channel_id)
        edit_queue = None
        if channel.get("channel_type", "tv") == "tv" and "shows" in definition:
            edit_queue = self.read_channel_queue(channel_id)
            if edit_queue is None:
                ChannelManager._edit_blocked.add(channel_id)
                log("[ChannelManager] update_channel: queue of '{}' cannot "
                    "be read - edit not saved".format(
                        channel.get("name", channel_id)),
                    level=xbmc.LOGWARNING)
                return channel

        old_shows      = list(channel.get("shows",        []))
        old_queue_size = channel.get("queue_size",        30)
        old_randomize  = channel.get("randomize",         False)
        old_no_repeat  = channel.get("no_repeat",         False)
        old_type       = channel.get("channel_type",      "tv")
        old_interleave = channel.get("interleave",        None)
        old_slots      = list(channel.get("slots",        []))

        old_points = dict(channel.get("starting_points") or {})

        channel.update({k: definition.get(k, channel.get(k))
                        for k in definition})
        # The wizard only sends the shows the user explicitly picked this
        # time.  Keep the starting episodes saved earlier for the other
        # shows (a rebuild or interleave weave reads them), let the new
        # picks win, and drop entries for shows no longer in the channel.
        if channel.get("channel_type", "tv") == "tv":
            kept_ids = {str(s.get("tvshowid"))
                        for s in channel.get("shows", [])}
            merged_points = dict(old_points)
            for k, v in (definition.get("starting_points") or {}).items():
                merged_points[str(k)] = v
            channel["starting_points"] = {
                k: v for k, v in merged_points.items() if k in kept_ids}
        channel["sc_version"] = "3.0.0"
        self._save_channels()

        mode_changed = (
            old_randomize  != channel.get("randomize",  False)
            or old_no_repeat  != channel.get("no_repeat",  False)
            or old_type       != channel.get("channel_type", "tv")
        )

        new_show_ids = {s["tvshowid"] for s in channel.get("shows", [])}
        old_show_ids = {s["tvshowid"] for s in old_shows}
        removed      = old_show_ids - new_show_ids

        no_queue_change = (
            not mode_changed
            and not removed
            and definition.get("shows",      old_shows)      == old_shows
            and definition.get("queue_size", old_queue_size) == old_queue_size
            and definition.get("interleave", old_interleave) == old_interleave
            and definition.get("slots",      old_slots)      == old_slots
        )

        keep_points, keep_start = {}, None
        if mode_changed:
            keys_to_del = [k for k in self._state
                           if k.startswith("{}:".format(channel_id))]
            for k in keys_to_del:
                del self._state[k]
            self._deleted_state_keys.update(keys_to_del)
            self._save_state()
        else:
            # Any change that forces a full rebuild (show list, order or
            # exclusions, queue size, interleave) starts from a zero cursor.
            # Capture each kept show's next-to-play episode (and the show at
            # the head of the queue) first so the rebuild resumes there
            # instead of restarting at S01E01.
            if not no_queue_change:
                keep_points, keep_start = self._capture_edit_positions(
                    channel_id, channel, old_shows, queue=edit_queue)
            self.update_cursor_for_edit(
                channel_id,
                added_show_ids=list(new_show_ids - old_show_ids),
                removed_show_ids=list(removed),
                invalidate=False)

        if not no_queue_change:
            rebuild_ch = channel
            if keep_points:
                # Explicit wizard picks override the captured positions.
                # Copy only — the saved definition is not modified.
                merged = dict(keep_points)
                for k, v in (definition.get("starting_points") or {}).items():
                    merged[str(k)] = v
                rebuild_ch = dict(channel)
                rebuild_ch["starting_points"] = merged
            # No queue to read the shows' places from although the channel
            # has saved positions (the queue file looked missing): continue
            # from those, except for shows picked in this edit.
            keep_set = None
            if edit_queue == [] and not keep_points:
                picked = {str(k) for k in
                          (definition.get("starting_points") or {})}
                keep_set = {sid for sid in
                            self.get_cursor(channel_id).get("ep_pos", {})
                            if sid not in picked}
            self._pregenerate_queue_safe(rebuild_ch,
                                         start_show_index=keep_start,
                                         keep_places=keep_set)

        # Starting episodes chosen in the Edit wizard (only shows the user
        # explicitly set are present). Apply them to the live queue — the
        # saved definition alone is only read by a fresh build.
        if channel.get("channel_type", "tv") == "tv":
            for sid_key, ep_info in (definition.get("starting_points")
                                     or {}).items():
                try:
                    sid = int(sid_key)
                except (ValueError, TypeError):
                    continue
                show = next((s for s in channel.get("shows", [])
                             if s.get("tvshowid") == sid), None)
                if (not show or show.get("randomize",
                                         channel.get("randomize", False))):
                    continue
                self.set_show_start(channel_id, sid,
                                    ep_info.get("episodeid"))

        # If carousel is enabled and last_pop_time is not yet set, initialise it
        # to now so the first tick does not fire immediately.
        cs = self.get_carousel_state(channel_id)
        if channel.get("carousel_enabled", False) and not cs.get("last_pop_time"):
            import time as _time
            self.set_carousel_state(channel_id, {
                "last_pop_time":    _time.time(),
                "last_popped_show": cs.get("last_popped_show"),
            })
            log("[ChannelManager] Carousel initialised last_pop_time=now "
                "for updated channel '{}'".format(channel.get("name", channel_id)))

        log("[ChannelManager] Updated channel id={}".format(channel_id))
        return channel

    def delete_channel(self, channel_id: str) -> bool:
        """Delete a channel and ALL associated data.

        Handles (regardless of deletion order):
        1.  Own state keys: "{channel_id}:*" and "resume:{channel_id}:*"
        2.  Combo slot state keys: "combo:{channel_id}:*" (tv_next_ep,
            show_slot, movie_state, folder_played, missing_durations)
        3.  Combo owner field: clear owner on any combo this channel owned
            so it becomes available as a source for other channels.
        4.  Interleave back-references: remove this channel from every other
            channel's interleave source list.
        5.  Schedules: delete any schedule where this channel is the source
            or the target.
        6.  Auto-companion channels: recursively delete any __auto__ companion
            channel that is only referenced by this channel's interleave
            config.  (Ported from 2.x — applies once auto_channels is active.)
        7.  Queue file(s): delete queue_{channel_id}.json and any .tmp copy.
        """
        from resources.lib.channels.interleave import get_sources

        channel = self.get_channel(channel_id)
        if not channel:
            return False

        # ── Step 1: Cross-channel pre-cleanup (before removing from list) ──

        # Clear combo owner and delete auto-companions in interleave sources.
        for source in get_sources(channel):
            src_id  = source.get("channel_id", "")
            src_ch  = self.get_channel(src_id)
            if not src_ch:
                continue
            # Clear owner field so the combo becomes available elsewhere.
            if src_ch.get("channel_type") == "combo":
                self.clear_combo_owner(src_id)
                log("[ChannelManager] delete_channel: cleared combo owner "                    "for '{}'".format(src_ch.get("name", src_id)))
            # Recursively delete __auto__ companion channels.
            if (src_ch.get("name", "").startswith("__auto__")
                    and not src_ch.get("visible", True)):
                self.delete_channel(src_id)
                log("[ChannelManager] delete_channel: deleted auto-companion "                    "'{}'".format(src_ch.get("name", src_id)))

        # Remove this channel from every other channel's interleave config.
        for ch in self._channels:
            if ch["id"] == channel_id:
                continue
            raw = ch.get("interleave")
            if not raw:
                continue
            sources_list = raw if isinstance(raw, list) else [raw]
            filtered     = [s for s in sources_list
                            if s.get("channel_id") != channel_id]
            if len(filtered) != len(sources_list):
                ch["interleave"] = filtered if filtered else None
                log("[ChannelManager] delete_channel: removed interleave "                    "ref from '{}'".format(ch.get("name", ch["id"])))

        # Delete schedules where this channel is source or target.
        schedules = self.get_all_schedules()
        sched_ids_to_del = [
            sid for sid, sch in schedules.items()
            if sch.get("target_channel_id") == channel_id
            or sch.get("target_channel")    == channel_id
            or sch.get("source_channel_id") == channel_id
            or sch.get("source_channel")    == channel_id
        ]
        if sched_ids_to_del:
            for sid in sched_ids_to_del:
                del schedules[sid]
                log("[ChannelManager] delete_channel: deleted schedule "                    "{}".format(sid))
            self.save_schedules_data(schedules)

        # ── Step 2: Remove channel from list ──
        before = len(self._channels)
        self._channels = [c for c in self._channels if c["id"] != channel_id]
        if len(self._channels) >= before:
            return False

        # ── Step 3: State key cleanup ──
        # Standard keys:   "{channel_id}:*"
        # Resume keys:     "resume:{channel_id}:*"
        # Combo slot keys: "combo:{channel_id}:*" (show_slot, tv_next_ep,
        #                   movie_state, folder_played, missing_durations)
        prefixes = (
            "{}:".format(channel_id),
            "resume:{}:".format(channel_id),
            "combo:{}:".format(channel_id),
        )
        keys_to_del = [k for k in self._state
                       if any(k.startswith(p) for p in prefixes)]
        for k in keys_to_del:
            del self._state[k]
        self._deleted_state_keys.update(keys_to_del)

        # ── Step 4: Persist all changes ──
        self._save_channels()
        self._save_state()

        # ── Step 5: Delete queue file ──
        queue_path = self._queue_file_path(channel_id)
        for p in (queue_path, queue_path + ".tmp"):
            try:
                if xbmcvfs.exists(p):
                    xbmcvfs.delete(p)
            except Exception:
                pass
        # The local working copy that save_json leaves in the profile folder
        # when the queue is on the shared folder.
        remove_local_copy("queue_{}.json".format(channel_id))
        # The channel's own carousel file (3.1.146).
        clock_path = self._clock_file_path(channel_id)
        for p in (clock_path, clock_path + ".tmp"):
            try:
                if xbmcvfs.exists(p):
                    xbmcvfs.delete(p)
            except Exception:
                pass
        remove_local_copy("chanstate_{}.json".format(channel_id))

        log("[ChannelManager] Deleted channel id={} — removed {} state "            "key(s), {} schedule(s)".format(
                channel_id, len(keys_to_del), len(sched_ids_to_del)))
        return True

    def known_queue_filenames(self) -> list:
        """queue_<id>.json file names of the channels that exist."""
        return ["queue_{}.json".format(c["id"]) for c in self._channels]

    def remove_orphan_local_queues(self) -> int:
        """Delete local queue_*.json working copies of channels that no longer
        exist.  Only with shared storage active, and never when no channel
        was loaded (an unreadable channels.json must not look like "all
        channels deleted").  Returns the number of files removed."""
        if not self._channels or not getattr(self, "_channels_ok", True):
            return 0
        known = set(self.known_queue_filenames())
        removed = 0
        for name in local_queue_files():
            if name not in known and remove_local_copy(name):
                removed += 1
                log("[ChannelManager] removed leftover local queue file "
                    "{}".format(name))
        return removed

    def toggle_visibility(self, channel_id: str) -> None:
        channel = self.get_channel(channel_id)
        if channel:
            channel["visible"] = not channel.get("visible", True)
            self._save_channels()

    def save_channel_list(self) -> None:
        """Flush the in-memory channel list to channels.json.
        Public alias for callers outside channel_manager.py.
        """
        self._save_channels()

    # =========================================================================
    # Channel ordering
    # =========================================================================

    def _find_channel_index(self, channel_id: str) -> int:
        for i, ch in enumerate(self._channels):
            if ch["id"] == channel_id:
                return i
        return -1

    def move_channel_up(self, channel_id: str) -> bool:
        idx = self._find_channel_index(channel_id)
        if idx <= 0:
            return False
        self._channels[idx], self._channels[idx - 1] = \
            self._channels[idx - 1], self._channels[idx]
        self._save_channels()
        return True

    def move_channel_down(self, channel_id: str) -> bool:
        idx = self._find_channel_index(channel_id)
        if idx < 0 or idx >= len(self._channels) - 1:
            return False
        self._channels[idx], self._channels[idx + 1] = \
            self._channels[idx + 1], self._channels[idx]
        self._save_channels()
        return True

    def sort_channels_alpha(self) -> None:
        import re as _re
        def _natural_key(c):
            parts = _re.split(r'(\d+)', c.get("name", "").lower())
            return [int(p) if p.isdigit() else p for p in parts]
        self._channels.sort(key=_natural_key)
        self._save_channels()

    # =========================================================================
    # Schedule CRUD  (unchanged from 2.x — spec §12)
    # =========================================================================

    def get_all_schedules(self) -> dict:
        return self._load_json(self._schedules_path, {})

    def add_schedule(self, definition: dict) -> dict:
        schedules = self.get_all_schedules()
        sch_id    = "sch_" + str(uuid.uuid4())
        definition["id"] = sch_id
        schedules[sch_id] = definition
        self._save_json(self._schedules_path, schedules)
        return definition

    def update_schedule(self, schedule_id: str,
                        definition: dict) -> Optional[dict]:
        schedules = self.get_all_schedules()
        if schedule_id not in schedules:
            return None
        definition["id"]        = schedule_id
        schedules[schedule_id]  = definition
        self._save_json(self._schedules_path, schedules)
        return definition

    # How long a schedule's fire claim holds other devices off.  (3.1.115)
    SCHEDULE_CLAIM_SECONDS = 300
    # Wait between writing a claim and checking it won, so a device claiming
    # in the same moment has time to write.  (3.1.115)
    SCHEDULE_CLAIM_SETTLE_MS = 1500

    # How long a carousel pop claim holds other devices off, and the wait
    # between writing a claim and checking it won.  (3.1.117)
    CAROUSEL_CLAIM_SECONDS   = 120
    CAROUSEL_CLAIM_SETTLE_MS = 1500
    CAROUSEL_MOVED_SLACK     = 1.0    # s: claim refuses when the shared clock is
                                      # more than this ahead of the one the check used
    CAROUSEL_CLOCK_SLACK     = 0.5    # s: a save never lowers a clock by more than this
    CLOCK_FLOOR_SECONDS      = 120    # s: a clock seen this recently is a floor for saves (3.1.145)

    # ------------------------------------------------------------------
    # Timing master (3.1.146)
    #
    # Every device on the shared folder used to check the carousel about once
    # a minute, so two devices could find the same pop due in the same few
    # seconds and both pop it (11/08, four times in 16 hours; the claim and
    # the clock repair came too late).  One device may now be the timing
    # master (setting "timing_master").  It writes a small heartbeat file,
    # master.json, once a minute.  A device that is not the master and sees
    # a live heartbeat leaves the carousel pops to it.  With no heartbeat, an
    # old one or an unreadable file every device behaves as before, claims
    # included, so nothing stops when the master is off.
    #
    # How "live" is judged: by THIS device's clock.  A heartbeat counts while
    # its sequence number has changed within MASTER_STALE_SECONDS of the time
    # this device last saw it change, so a Shield whose clock is a few
    # seconds off does not matter.  The first time a master is seen, the
    # time written in its file must also be recent (an old file left by a
    # master that was switched off hours ago is not a master).
    # Two devices set as master: the lower device id acts, the other defers.
    # ------------------------------------------------------------------

    CLOCK_JUMP_SECONDS   = 300    # a clock moved forward by more than this ...
    CLOCK_JUMP_CLAIM_AGE = 120    # ... with no claim won here this recently is journalled (3.1.147)
    MASTER_BEAT_SECONDS  = 50     # least time between two heartbeats
    MASTER_STALE_SECONDS = 300    # a heartbeat that has not changed this long is gone
    FOLLOWER_LOG_SECONDS = 3600   # follower_skip is journalled once an hour

    def _master_path(self) -> str:
        return self._resolve_path("master.json")

    def is_timing_master(self) -> bool:
        """True when the 'timing_master' setting is on for this device."""
        try:
            return str(self.addon.getSetting("timing_master")
                       ).strip().lower() == "true"
        except Exception:
            return False

    def _read_master(self) -> tuple:
        """(heartbeat, readable): the heartbeat dict, or None when the file
        is missing or holds none; readable False when it cannot be read."""
        try:
            data = load_json_strict(self._master_path(), None)
        except JsonReadError:
            return None, False
        if isinstance(data, dict) and data.get("device_id"):
            return data, True
        return None, True

    def _observe_master(self):
        """The other device's live heartbeat as {'id', 'name', 'seq',
        'seen_at', 'alive'}, or None when no other device is a live master.
        Journals master_seen / master_lost / master_back on a change."""
        cls = ChannelManager
        me = self.get_device_id()
        now = time.time()
        hb, readable = self._read_master()
        obs = cls._master_obs.get(me)
        if readable and hb is not None and hb.get("device_id") != me:
            other = hb["device_id"]
            if obs is None or obs.get("id") != other \
                    or obs.get("seq") != hb.get("seq"):
                seen_at = now
                if obs is None or obs.get("id") != other:
                    try:
                        age = abs(now - float(hb.get("t")))
                    except (TypeError, ValueError):
                        age = self.MASTER_STALE_SECONDS + 1
                    if age > self.MASTER_STALE_SECONDS:
                        seen_at = now - self.MASTER_STALE_SECONDS - 1
                new = {"id": other, "name": hb.get("device_name") or other,
                       "seq": hb.get("seq"), "seen_at": seen_at,
                       "alive": obs.get("alive") if obs else None}
                cls._master_obs[me] = obs = new
        if obs is None:
            return None
        alive = (now - obs["seen_at"]) <= self.MASTER_STALE_SECONDS
        was = obs.get("alive")
        obs["alive"] = alive
        if alive and was is None:
            self._jrec("master_seen", master=obs["name"],
                       age=round(now - obs["seen_at"], 1), seq=obs["seq"])
        elif alive and was is False:
            self._jrec("master_back", master=obs["name"], seq=obs["seq"])
        elif not alive and was:
            self._jrec("master_lost", master=obs["name"],
                       age=round(now - obs["seen_at"], 1), seq=obs["seq"])
        return obs if alive else None

    def _acting_master(self) -> bool:
        """True when this device is set as master and no master with a lower
        device id is alive."""
        if not self.is_timing_master():
            return False
        other = self._observe_master()
        me = self.get_device_id()
        if other is not None and other["id"] < me:
            tag = (me, other["id"])
            if tag not in ChannelManager._conflict_logged:
                ChannelManager._conflict_logged.add(tag)
                self._jrec("master_conflict", master=other["name"],
                           master_id=other["id"][:8], this_id=me[:8])
                log("[ChannelManager] two devices are set as timing master - "
                    "{} has the lower id and acts, this device defers".format(
                        other["name"]), level=xbmc.LOGWARNING)
            return False
        return True

    def tick_master(self) -> None:
        """Write the heartbeat when this device is the acting timing master.
        Called by the carousel tick; at most one write per
        MASTER_BEAT_SECONDS.  Never raises."""
        try:
            if not self._acting_master():
                return
            cls = ChannelManager
            me = self.get_device_id()
            now = time.time()
            if now - cls._master_beat.get(me, 0.0) < self.MASTER_BEAT_SECONDS:
                return
            beat = {"device_id": me, "device_name": self.get_device_label(),
                    "t": now, "seq": int(now * 1000),
                    "version": str(self.addon.getAddonInfo("version"))}
            if save_json(self._master_path(), beat):
                cls._master_beat[me] = now
            else:
                log("[ChannelManager] the timing master heartbeat could not "
                    "be written", level=xbmc.LOGWARNING)
        except Exception as exc:
            log("[ChannelManager] tick_master error: {}".format(exc),
                level=xbmc.LOGWARNING)

    def master_in_charge(self) -> bool:
        """True when another device is the live timing master, so this
        device leaves the carousel pops to it.  False when this device is
        the acting master, when no master is set, or when the heartbeat is
        old or unreadable.  Never raises."""
        try:
            if self.is_timing_master():
                return not self._acting_master()
            return self._observe_master() is not None
        except Exception as exc:
            log("[ChannelManager] master_in_charge error: {}".format(exc),
                level=xbmc.LOGWARNING)
            return False

    def note_follower_skip(self, channel_id: str) -> None:
        """Count a carousel pop left to the master; one follower_skip
        journal line per hour with the count per channel."""
        try:
            sk = ChannelManager._skips
            now = time.time()
            if not sk.get("since"):
                sk["since"] = now
                sk["per"] = {}
            per = sk.setdefault("per", {})
            per[channel_id] = per.get(channel_id, 0) + 1
            if now - sk["since"] >= self.FOLLOWER_LOG_SECONDS:
                self._jrec("follower_skip", n=sum(per.values()),
                           ch={self._journal_channel(c): n
                               for c, n in per.items()},
                           hours=round((now - sk["since"]) / 3600.0, 2))
                sk["since"] = now
                sk["per"] = {}
        except Exception:
            pass

    def claim_carousel_pop(self, channel_id: str, new_last_pop: float,
                           based_on: Optional[float] = None) -> bool:
        """Claim the carousel pop that is due on a channel for this device.

        Several devices on the same shared folder check the carousel about
        once a minute and can find the same pop due in the same moment; each
        then removes the same front item and draws its own replacement, and
        one replacement is lost.  The device that wins this claim pops; the
        others leave it, and the next check finds the clock moved on.
        (3.1.117)

        new_last_pop is the carousel clock value the pop will set.  based_on
        is the clock value the caller's due-check started from.  Returns
        False when the shared state already shows that clock value reached
        (another device popped), when the shared clock is ahead of based_on
        (another device popped since the check began: the caller's
        elapsed time and queue front belong to different pops, 3.1.142),
        when another device holds a live claim for it, when this device's
        claim is overwritten by another device's (checked by reading the file
        back after a short wait), or when the shared state cannot be read.
        Shared storage has no atomic create, so as for schedule fires the
        read-back settles a simultaneous claim.  On return the in-memory
        carousel state of this channel is the one read from the shared file,
        so the pop continues from current data.

        Every outcome is journalled as a 'claim' line (3.1.142).
        """
        key  = "{}:carousel".format(channel_id)
        name = self.get_device_label()
        # Check and write under the lock, so two devices cannot both find
        # the pop free and both write their claim.  The lock is given back
        # before the settle wait, so other devices' saves are not held up.
        with self._lock_scope(self.WRITE_LOCK_CLAIM_WAIT_MS):
            wrote = self._claim_write(channel_id, new_last_pop, based_on)
        if wrote is None:
            return False
        token, clock, stamp = wrote
        xbmc.sleep(self.CAROUSEL_CLAIM_SETTLE_MS)
        back_entry, ok, _w = self._read_clock_entry(channel_id)
        back = dict(back_entry) if ok and back_entry is not None else {}
        won  = (ok and isinstance(back.get("pop_claim"), dict)
                and back["pop_claim"].get("token") == token)
        if back:
            self._adopt_carousel(key, back)
        if won:
            log("[ChannelManager] carousel claim: channel {} won by {}".format(
                channel_id[:8], name))
        else:
            other = (back.get("pop_claim") or {}).get("device_name") \
                if isinstance(back.get("pop_claim"), dict) else None
            log("[ChannelManager] carousel claim: channel {} lost on {} - {} "
                "claimed it in the same moment".format(
                    channel_id[:8], name, other or "another device"))
        self._journal_claim(channel_id, "won" if won else "lost",
                            based_on=based_on, target=new_last_pop,
                            disk=clock, stamp=stamp)
        return won

    def _claim_write(self, channel_id: str, new_last_pop: float,
                     based_on: Optional[float]):
        """The check-and-write half of claim_carousel_pop, run while the
        shared-folder lock is held (3.1.148).  Returns None when the claim
        is refused (the outcome is journalled here), else (token, clock,
        stamp) after this device's claim has been written."""
        key  = "{}:carousel".format(channel_id)
        me   = self.get_device_id()
        name = self.get_device_label()
        # The channel's own file is the source (3.1.146); state.json only
        # for a channel that has no file yet.
        entry, fok, _w = self._read_clock_entry(channel_id)
        disk, ok = self._read_strict(self._state_path, {})
        stamp = self._state_stamp()
        if not fok or (entry is None and not ok):
            self._journal_claim(channel_id, "unreadable", based_on=based_on,
                                target=new_last_pop, stamp=stamp)
            return None
        cs   = dict(entry) if entry is not None \
            else dict((disk.get(key) if ok else None) or {})
        try:
            clock = float(cs.get("last_pop_time") or 0)
        except (TypeError, ValueError):
            clock = 0.0
        if clock >= new_last_pop:
            self._adopt_carousel(key, cs)
            log("[ChannelManager] carousel claim: channel {} already popped "
                "for this interval - nothing to do on {}".format(
                    channel_id[:8], name))
            self._journal_claim(channel_id, "already_popped",
                                based_on=based_on, target=new_last_pop,
                                disk=clock, stamp=stamp)
            return None
        if based_on is not None:
            try:
                moved = clock > float(based_on) + self.CAROUSEL_MOVED_SLACK
            except (TypeError, ValueError):
                moved = False
            if moved:
                self._adopt_carousel(key, cs)
                log("[ChannelManager] carousel claim: channel {} refused on "
                    "{} - the clock moved on since this check began "
                    "(check used {:.0f}, shared clock {:.0f}); the next "
                    "check starts from the shared clock".format(
                        channel_id[:8], name, float(based_on), clock))
                self._journal_claim(channel_id, "clock_moved",
                                    based_on=based_on, target=new_last_pop,
                                    disk=clock, stamp=stamp)
                return None
        held = cs.get("pop_claim")
        if isinstance(held, dict) and held.get("device_id") != me:
            try:
                age = abs(time.time() - float(held.get("at", 0)))
                covers = float(held.get("for", 0)) >= new_last_pop - 1.0
            except (TypeError, ValueError):
                age, covers = self.CAROUSEL_CLAIM_SECONDS + 1, False
            if covers and age <= self.CAROUSEL_CLAIM_SECONDS:
                self._adopt_carousel(key, cs)
                log("[ChannelManager] carousel claim: channel {} refused on "
                    "{} - {} is popping it ({:.0f}s ago)".format(
                        channel_id[:8], name,
                        held.get("device_name") or "another device", age))
                self._journal_claim(
                    channel_id, "held", based_on=based_on,
                    target=new_last_pop, disk=clock, stamp=stamp,
                    held={"dev": held.get("device_name"),
                          "for": held.get("for"), "age": round(age, 1)})
                return None
        token = uuid.uuid4().hex
        cs["pop_claim"] = {"device_id": me, "device_name": name,
                           "for": new_last_pop, "at": time.time(),
                           "token": token}
        self.set_carousel_state(channel_id, cs)
        return token, clock, stamp

    def _adopt_carousel(self, key: str, entry: dict) -> None:
        """Take the carousel entry read from the shared file as this
        manager's copy WITHOUT marking it as a change of this manager.

        The claim used to set only _state[key].  _save_state writes every key
        whose in-memory value differs from _state_base, so a device that had
        merely READ the entry (a refused claim) wrote that older copy back
        with its next save of anything, and erased the winner's newer clock.
        (3.1.142)
        """
        self._state[key] = entry
        self._state_base[key] = copy.deepcopy(entry)

    def _journal_claim(self, channel_id: str, outcome: str, **fields) -> None:
        """One 'claim' journal line: the decision and the numbers behind it."""
        if outcome == "won":
            ChannelManager._won_at[channel_id] = time.time()
        journal.record("claim", ch=self._journal_channel(channel_id),
                       outcome=outcome, **fields)

    def _state_stamp(self):
        """[mtime, size] of state.json as this device sees it now, or None.
        Journalled with each claim so that a device reading an older copy of
        the shared file can be shown from the journals.  (3.1.142)"""
        try:
            st = xbmcvfs.Stat(self._state_path)
            return [int(st.st_mtime()), int(st.st_size())]
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Diagnostics (3.1.142).  They only write journal lines.  Every method
    # here swallows its own errors: a failed diagnostic never touches a save.
    # ------------------------------------------------------------------

    CLOCK_WATCH_RECHECK_MS = 3000   # re-read after a clock went backwards
    TICK_GAP_SECONDS       = 150    # the carousel tick runs every 60 s
    SLEEP_JUMP_SECONDS     = 5      # wall time ahead of the monotonic clock
    CLOCK_TABLE_SECONDS    = 3600   # hourly table of every carousel clock
    UNREADABLE_LOG_SECONDS = 600
    STALE_LOG_MAX          = 200    # stale_read lines per Kodi session

    def _jrec(self, event: str, **fields) -> None:
        """journal.record with this device's name on the line itself, so a
        line written by the add-on's plugin process (which has no journal
        file name of its own) still says which device wrote it."""
        try:
            fields.setdefault("dev", self.get_device_label())
            journal.record(event, **fields)
        except Exception:
            pass

    @staticmethod
    def _proc_tag() -> str:
        """'<pid>:<script>' of this Kodi process: service or plugin call."""
        try:
            return "{}:{}".format(os.getpid(),
                                  os.path.basename(sys.argv[0] or "")[:24])
        except Exception:
            return "?"

    @staticmethod
    def _clocks_of(state) -> dict:
        """{'<channel>:carousel': last_pop_time} for every carousel entry."""
        out = {}
        try:
            for k, v in (state or {}).items():
                if k.endswith(":carousel") and isinstance(v, dict):
                    try:
                        out[k] = float(v.get("last_pop_time") or 0)
                    except (TypeError, ValueError):
                        pass
        except Exception:
            pass
        return out

    @staticmethod
    def _writer_name(state) -> str:
        """Device name in the _writer tag of a state.json, or '?'."""
        try:
            tag = state.get("_writer")
            return str(tag.get("dev") or "?") if isinstance(tag, dict) else "?"
        except Exception:
            return "?"

    def _writer_tag(self, via: str) -> dict:
        """The tag every save puts into state.json as '_writer': which
        device, process and code path wrote this version of the file.  A
        carousel clock found lowered can then be traced to the writer of
        the version that lowered it."""
        try:
            ChannelManager._write_seq += 1
            return {"dev": self.get_device_label(),
                    "id": self.get_device_id()[:8],
                    "t": round(time.time(), 1),
                    "n": ChannelManager._write_seq,
                    "proc": self._proc_tag(), "via": via}
        except Exception:
            return {}

    def _learn_clocks(self, state, who: str) -> None:
        """Remember the highest carousel clock this process has seen on the
        share (read or written), and who put it there."""
        try:
            for k, c in self._clocks_of(state).items():
                seen = ChannelManager._clock_seen.get(k)
                if seen is None or c > seen[0]:
                    ChannelManager._clock_seen[k] = [c, who, time.time()]
                elif c == seen[0]:
                    seen[2] = time.time()   # seen again: still the floor (3.1.145)
        except Exception:
            pass

    def _note_stamp(self, where: str, stamp, via: str = "") -> None:
        """Journal 'stale_read' when state.json's modified time is OLDER than
        one this process has already seen or written.  A file cannot go back
        in time, so this proves that the share (or its cache) handed this
        device an older copy."""
        try:
            if not stamp:
                return
            seen = ChannelManager._stamp_seen
            if seen and stamp[0] < seen[0]:
                if ChannelManager._stale_count < self.STALE_LOG_MAX:
                    ChannelManager._stale_count += 1
                    self._jrec("stale_read", where=where, seen=seen,
                               now=stamp, via=via or journal.chain(2, 5))
                return
            ChannelManager._stamp_seen = [stamp[0], stamp[1]]
        except Exception:
            pass

    def _diag_before_save(self, on_disk: dict) -> tuple:
        """(code path of the caller of _save_state, state.json stamp) for the
        journal, and learn the clocks on the share.  Never raises."""
        try:
            via = journal.chain(2, 7)
            stamp = self._state_stamp()
            self._note_stamp("save", stamp, via)
            self._learn_clocks(on_disk, self._writer_name(on_disk))
            return via, stamp
        except Exception:
            return "", None

    def _journal_unreadable(self, where: str, exc=None) -> None:
        """'state_unreadable' (at most one per UNREADABLE_LOG_SECONDS)."""
        try:
            now = time.time()
            if now - ChannelManager._unreadable_at < self.UNREADABLE_LOG_SECONDS:
                return
            ChannelManager._unreadable_at = now
            self._jrec("state_unreadable", where=where, err=str(exc)[:120],
                       stamp=self._state_stamp())
        except Exception:
            pass

    def _journal_lowering(self, merged: dict, stamp_read, via: str) -> None:
        """Journal 'clock_lowering_write' when this save is about to write a
        carousel clock below one this process has seen on the share.  The
        copy of state.json this save started from was then older than the
        share's (stale read), which _keep_newer_carousel cannot see."""
        try:
            for k, c in self._clocks_of(merged).items():
                seen = ChannelManager._clock_seen.get(k)
                if seen and c < seen[0] - self.CAROUSEL_CLOCK_SLACK:
                    chan = k[:-len(":carousel")]
                    self._jrec("clock_lowering_write",
                               ch=self._journal_channel(chan), writing=c,
                               known=seen[0], known_who=seen[1],
                               known_at=round(seen[2]), read=stamp_read,
                               seen=ChannelManager._stamp_seen, via=via)
            live = {c.get("id") for c in self._channels}
            have = self._clocks_of(merged)
            for k, seen in list(ChannelManager._clock_seen.items()):
                chan = k[:-len(":carousel")]
                if k not in have and chan in live:
                    self._jrec("clock_dropped_write",
                               ch=self._journal_channel(chan),
                               known=seen[0], known_who=seen[1],
                               deleted=k in self._deleted_state_keys,
                               read=stamp_read, via=via)
        except Exception:
            pass

    def _journal_write(self, merged: dict, stamp_read, via: str) -> None:
        """One 'state_write' line per save of state.json: what the save read,
        what it left on the share, the gap between this device's clock and
        the share's file time, and the carousel clocks when they changed."""
        try:
            wrote = self._state_stamp()
            if wrote:
                ChannelManager._stamp_seen = [wrote[0], wrote[1]]
            self._learn_clocks(merged, "me")
            rec = {"n": ChannelManager._write_seq, "via": via,
                   "read": stamp_read, "wrote": wrote,
                   "skew": (round(time.time() - wrote[0], 1)
                            if wrote else None),
                   "proc": self._proc_tag()}
            clocks = self._clocks_of(merged)
            if clocks != ChannelManager._clk_logged:
                ChannelManager._clk_logged = dict(clocks)
                rec["clk"] = {k.split(":", 1)[0][:8]: int(v)
                              for k, v in clocks.items()}
            self._jrec("state_write", **rec)
        except Exception:
            pass

    def watch_carousel_clocks(self) -> None:
        """Called by the carousel tick once a minute.  Records what this
        device can prove about the shared carousel clocks:
          tick_gap         the tick came late: the device slept (wall time
                           ran on while the monotonic clock stopped), the
                           service was stalled, or the clock was set
          stale_read       state.json's file time went backwards
          clock_regressed  a clock on the share is lower than one this
                           device saw or wrote earlier, with the _writer tag
                           of the file and a second reading 3 s later
          memory_behind    this device's in-memory clock is older than the
                           share's (the state a due-check would use)
          clock_table      every carousel clock, once an hour
        Logging only.  (3.1.142)"""
        try:
            self._watch_clocks()
        except Exception as exc:
            log("[ChannelManager] watch_carousel_clocks error: {}".format(exc),
                level=xbmc.LOGWARNING)

    def _watch_clocks(self) -> None:
        cls = ChannelManager
        wall, mono = time.time(), time.monotonic()
        if cls._watch_wall:
            dwall, dmono = wall - cls._watch_wall, mono - cls._watch_mono
            if dwall > self.TICK_GAP_SECONDS \
                    or abs(dwall - dmono) > self.SLEEP_JUMP_SECONDS:
                if dwall - dmono > self.SLEEP_JUMP_SECONDS:
                    kind = "slept"
                elif dmono - dwall > self.SLEEP_JUMP_SECONDS:
                    kind = "wall_clock_set_back"
                else:
                    kind = "late"
                self._jrec("tick_gap", kind=kind, wall=round(dwall, 1),
                           mono=round(dmono, 1))
        cls._watch_wall, cls._watch_mono = wall, mono

        disk, ok = self._read_strict(self._state_path, {})
        if not ok:
            self._journal_unreadable("watch")
            return
        stamp = self._state_stamp()
        self._note_stamp("watch", stamp)
        tag = disk.get("_writer") if isinstance(disk.get("_writer"), dict) \
            else None
        who = self._writer_name(disk)
        disk = self._with_clock_files(disk)       # 3.1.146
        clocks = self._clocks_of(disk)
        for k, c in clocks.items():
            chan = k[:-len(":carousel")]
            seen = cls._clock_seen.get(k)
            if seen and c < seen[0] - self.CAROUSEL_CLOCK_SLACK:
                if cls._clock_regressed.get(k) != c:
                    cls._clock_regressed[k] = c
                    self._report_regression(k, c, seen, stamp, tag)
            else:
                cls._clock_regressed.pop(k, None)
                if seen is None or c > seen[0]:
                    cls._clock_seen[k] = [c, who, time.time()]
            mem = self._state.get(k)
            try:
                mem_clock = float(mem.get("last_pop_time") or 0) \
                    if isinstance(mem, dict) else 0.0
            except (TypeError, ValueError):
                mem_clock = 0.0
            if c > mem_clock + self.CAROUSEL_CLOCK_SLACK \
                    and (k, c) not in cls._behind_noted:
                if len(cls._behind_noted) > 400:
                    cls._behind_noted.clear()
                cls._behind_noted.add((k, c))
                self._jrec("memory_behind", ch=self._journal_channel(chan),
                           mem=mem_clock, disk=c, stamp=stamp, writer=tag)
        live = {c.get("id") for c in self._channels}
        for k, seen in list(cls._clock_seen.items()):
            if k in clocks:
                continue
            if k[:-len(":carousel")] not in live:
                cls._clock_seen.pop(k, None)
                continue
            if cls._clock_regressed.get(k) != "missing":
                cls._clock_regressed[k] = "missing"
                self._report_regression(k, None, seen, stamp, tag)
        if wall - cls._table_at >= self.CLOCK_TABLE_SECONDS:
            cls._table_at = wall
            self._jrec("clock_table", stamp=stamp, writer=tag,
                       clk={k.split(":", 1)[0][:8]: int(v)
                            for k, v in clocks.items()})

    def _report_regression(self, key: str, now_clock: float, seen: list,
                           stamp, tag) -> None:
        """A carousel clock on the share is below one this device knew.
        Journal who wrote the file that way, then read again after 3 s to
        show whether it stayed that way."""
        chan = key[:-len(":carousel")]
        label = self._journal_channel(chan)
        self._jrec("clock_regressed", ch=label, was=seen[0],
                   was_who=seen[1], was_at=round(seen[2]), now=now_clock,
                   stamp=stamp, writer=tag, seen=ChannelManager._stamp_seen)
        log("[ChannelManager] carousel clock of {} went back from {:.0f} to "
            "{} on the share".format(
                chan[:8], seen[0],
                "nothing (entry missing)" if now_clock is None
                else "{:.0f}".format(now_clock)), level=xbmc.LOGWARNING)
        xbmc.sleep(self.CLOCK_WATCH_RECHECK_MS)
        disk, ok = self._read_strict(self._state_path, {})
        again = self._clocks_of(disk).get(key) if ok else None
        self._jrec("clock_regressed_after", ch=label, now=again,
                   stamp=self._state_stamp(),
                   writer=disk.get("_writer") if ok else None)

    CLOCK_VERIFY_MS    = 1200
    CLOCK_VERIFY_TRIES = 3

    def verify_carousel_clock(self, channel_id: str, expected: float,
                              last_popped_show=None) -> None:
        """Put back a carousel clock that another device's save wiped out.

        state.json is read, changed and written back whole.  A device that
        read it before a pop was saved and writes it after puts the old
        last_pop_time back without any error, and the next check then finds
        the same pop due again.  A short time after the pop was saved, read
        state.json again; if last_pop_time is below the value the pop set,
        write it once more.  A value at or above it is another device's later
        pop and is left alone.  (3.1.141)
        """
        key = "{}:carousel".format(channel_id)
        for attempt in range(self.CLOCK_VERIFY_TRIES):
            xbmc.sleep(self.CLOCK_VERIFY_MS)
            entry, fok, fwriter = self._read_clock_entry(channel_id)
            if not fok:
                self._journal_unreadable("verify")
                return
            if entry is not None:
                # The channel's own file (3.1.146).
                disk, ok = {key: entry, "_writer": fwriter}, True
            else:
                disk, ok = self._read_strict(self._state_path, {})
            if not ok:
                self._journal_unreadable("verify")
                return
            on_disk = disk.get(key)
            try:
                clock = float((on_disk or {}).get("last_pop_time") or 0)
            except (TypeError, ValueError, AttributeError):
                clock = 0.0
            stamp = self._state_stamp()
            self._note_stamp("verify", stamp)
            if clock >= expected:
                self._jrec("clock_verified",
                           ch=self._journal_channel(channel_id),
                           expected=expected, on_disk=clock,
                           attempt=attempt + 1, stamp=stamp,
                           writer=disk.get("_writer"))
                self._learn_clocks(disk, self._writer_name(disk))
                return
            log("[ChannelManager] carousel clock of {} was overwritten by "
                "another device - written again".format(channel_id[:8]),
                level=xbmc.LOGWARNING)
            journal.record("clock_rewritten",
                           ch=self._journal_channel(channel_id),
                           expected=expected, on_disk=clock,
                           attempt=attempt + 1, stamp=stamp,
                           writer=disk.get("_writer"),
                           seen=ChannelManager._stamp_seen,
                           entry=on_disk if key in disk else "MISSING")
            fixed = copy.deepcopy(on_disk) if isinstance(on_disk, dict) \
                else copy.deepcopy(self._state.get(key) or {})
            fixed["last_pop_time"] = expected
            if last_popped_show is not None:
                fixed["last_popped_show"] = last_popped_show
            self._state[key] = fixed
            self._state_base[key] = copy.deepcopy(on_disk) \
                if isinstance(on_disk, dict) else None
            wrote = self._write_clock_entry(channel_id, fixed, "verify")
            saved = self._save_state()
            if not (wrote or saved):
                return

    def _note_claim(self, schedule_id: str, outcome: str, text: str) -> None:
        """Log one claim outcome per schedule, day and outcome.  The check
        runs every minute, so a repeated refusal is logged once.  (3.1.116)"""
        import datetime as _dt
        noted = getattr(self, "_claim_noted", None)
        if noted is None:
            noted = self._claim_noted = set()
        key = (schedule_id, _dt.date.today().isoformat(), outcome)
        if key in noted:
            return
        noted.add(key)
        log("[ChannelManager] schedule claim: {}".format(text))

    def claim_schedule_fire(self, schedule_id: str) -> bool:
        """Claim today's fire of a schedule for this device.

        Returns True when this device may build and insert the block, False
        when another device holds a live claim for today or wins a claim
        made at the same moment.  Each schedule fires once: the claim covers
        the seconds between deciding to fire and fire_block() recording
        last_fired.  Shared storage has no atomic create, so the claim is
        written, given a moment, and read back; the device whose claim is
        still there proceeds.  (3.1.115)  The outcome is logged with the
        device names involved.  (3.1.116)
        """
        import datetime as _dt
        schedules = self.get_all_schedules()
        sch = schedules.get(schedule_id)
        if not sch:
            return False
        name  = sch.get("name", schedule_id)
        today = _dt.date.today().isoformat()
        me    = self.get_device_id()
        held  = sch.get("fire_claim")
        if isinstance(held, dict) and held.get("date") == today \
                and held.get("device_id") != me:
            try:
                age = abs(time.time() - float(held.get("at", 0)))
            except (TypeError, ValueError):
                age = self.SCHEDULE_CLAIM_SECONDS + 1
            if age <= self.SCHEDULE_CLAIM_SECONDS:
                self._note_claim(
                    schedule_id, "refused",
                    "'{}' refused - already claimed by {} {:.0f}s ago".format(
                        name, held.get("device_name") or "another device",
                        age))
                return False
        token = uuid.uuid4().hex
        mine  = dict(sch)
        mine["fire_claim"] = {"device_id": me, "date": today,
                              "device_name": self.get_device_label(),
                              "at": time.time(), "token": token}
        self.update_schedule(schedule_id, mine)
        xbmc.sleep(self.SCHEDULE_CLAIM_SETTLE_MS)
        back = (self.get_all_schedules().get(schedule_id) or {}) \
            .get("fire_claim")
        won = isinstance(back, dict) and back.get("token") == token
        if won:
            self._note_claim(
                schedule_id, "won",
                "'{}' won by {}".format(name, self.get_device_label()))
        else:
            self._note_claim(
                schedule_id, "lost",
                "'{}' lost - {} claimed it in the same moment".format(
                    name, (back or {}).get("device_name") or "another device")
                if isinstance(back, dict) else
                "'{}' lost - claim not found on read-back".format(name))
        return won

    def release_schedule_claim(self, schedule_id: str) -> None:
        """Drop this device's fire claim (the block could not be built), so
        the schedule can be tried again on the next check.  (3.1.115)"""
        sch = self.get_all_schedules().get(schedule_id)
        if not sch:
            return
        held = sch.get("fire_claim")
        if isinstance(held, dict) and held.get("device_id") == self.get_device_id():
            mine = dict(sch)
            mine.pop("fire_claim", None)
            self.update_schedule(schedule_id, mine)

    def delete_schedule(self, schedule_id: str) -> None:
        schedules = self.get_all_schedules()
        if schedule_id in schedules:
            del schedules[schedule_id]
            self._save_json(self._schedules_path, schedules)
        self.clear_active_block(schedule_id)

    def save_schedules_data(self, schedules: dict) -> None:
        self._save_json(self._schedules_path, schedules)

    def get_active_block(self, schedule_id: str) -> Optional[dict]:
        key = "{}:active_block".format(schedule_id)
        return self._load_json(self._state_path, {}).get(key)

    def set_active_block(self, schedule_id: str, block: dict) -> None:
        self.write_state_key("{}:active_block".format(schedule_id), block)

    def clear_active_block(self, schedule_id: str) -> None:
        key = "{}:active_block".format(schedule_id)
        if self.read_state_key(key) is None and key not in self._state:
            return
        self._state.pop(key, None)
        self._deleted_state_keys.add(key)
        self._save_state()

    # ------------------------------------------------------------------
    # Block expiry by slot  (3.1.155)
    # ------------------------------------------------------------------

    # How long a block-expiry claim holds other devices off, and the wait
    # between writing it and checking it won.
    BLOCK_EXPIRY_CLAIM_SECONDS   = 120
    BLOCK_EXPIRY_CLAIM_SETTLE_MS = 1500

    def block_expiry_enabled(self) -> bool:
        """True when the "remove scheduled blocks when their slot ends"
        setting is on (default off)."""
        return self.addon.getSetting("block_expiry") == "true"

    def default_item_seconds(self, item: dict) -> int:
        """Default running time for a queue item whose own duration is 0:
        the movie default for a movie, the episode default for the rest.
        A default of 0 means "skip such items" elsewhere; for a time slot
        that would end the moment it starts, so the built-in length (100
        minutes for a movie, 30 for the rest) is used instead."""
        if item.get("is_movie"):
            return self._default_movie_seconds() or 100 * 60
        return self._default_episode_seconds() or 30 * 60

    def claim_block_expiry(self, channel_id: str) -> bool:
        """Claim the block-expiry pass of a channel for this device.

        Devices on the shared folder run the pass about once a minute; the
        one whose claim is still there after a short wait removes the due
        items, the others leave them.  A live claim of another device
        refuses; a stale one is ignored.
        """
        key  = "{}:block_expiry_claim".format(channel_id)
        me   = self.get_device_id()
        held = self.read_state_key(key)
        if isinstance(held, dict) and held.get("device_id") != me:
            try:
                age = abs(time.time() - float(held.get("at", 0)))
            except (TypeError, ValueError):
                age = self.BLOCK_EXPIRY_CLAIM_SECONDS + 1
            if age <= self.BLOCK_EXPIRY_CLAIM_SECONDS:
                return False
        token = uuid.uuid4().hex
        self.write_state_key(key, {
            "device_id": me, "device_name": self.get_device_label(),
            "at": time.time(), "token": token})
        xbmc.sleep(self.BLOCK_EXPIRY_CLAIM_SETTLE_MS)
        back = self.read_state_key(key)
        return isinstance(back, dict) and back.get("token") == token

    def release_block_expiry_claim(self, channel_id: str) -> None:
        """Drop this device's block-expiry claim for channel_id."""
        key = "{}:block_expiry_claim".format(channel_id)
        held = self.read_state_key(key)
        if isinstance(held, dict) and held.get("device_id") == self.get_device_id():
            self._state.pop(key, None)
            self._deleted_state_keys.add(key)
            self._save_state()

    def remove_block_items(self, channel_id: str, schedule_id: str,
                           seqs) -> list:
        """Remove the queue items of one scheduled block whose block
        sequence number is in ``seqs``.  No replacement is added (the block
        was extra to the channel).  The saved resume point of each removed
        item is cleared.  Done under the block-expiry claim; the queue is
        read again after the claim, and one that cannot be read is left
        alone.  Returns the removed items (empty when nothing was removed or
        the claim was lost).
        """
        wanted = set(seqs)
        if not wanted or not self.claim_block_expiry(channel_id):
            return []
        removed = []
        try:
            queue = self.read_channel_queue(channel_id)
            if not queue:
                return []
            keep = []
            for item in queue:
                if (item.get("_schedule_id") == schedule_id
                        and item.get("_block_seq") in wanted):
                    removed.append(item)
                else:
                    keep.append(item)
            if removed:
                self.write_channel_queue(channel_id, keep)
                for item in removed:
                    self.clear_resume_position(channel_id,
                                               item.get("file", ""))
        finally:
            self.release_block_expiry_claim(channel_id)
        return removed

    # =========================================================================
    # Combo Block public API  (spec §11)
    # =========================================================================

    def set_combo_owner(self, combo_id: str, target_id: str,
                        target_name: str, relationship: str) -> None:
        ch = self.get_channel(combo_id)
        if not ch:
            return
        ch["owner"] = {
            "channel_id":   target_id,
            "channel_name": target_name,
            "relationship": relationship,
        }
        self._save_channels()

    def clear_combo_owner(self, combo_id: str) -> None:
        ch = self.get_channel(combo_id)
        if ch and ch.get("owner") is not None:
            ch["owner"] = None
            self._save_channels()

    def get_interleave_source_owner(self, source_id: str,
                                    exclude_channel_id: str = "") -> Optional[dict]:
        """Return the channel that uses source_id as an interleave source, or None.

        Scans all channels' interleave source lists.  Used by the interleave
        source picker to enforce the one-owner rule for regular (non-combo)
        channels.

        exclude_channel_id: the channel currently being edited — its own
        sources are not counted as foreign ownership.
        """
        from resources.lib.channels.interleave import get_sources
        for ch in self.get_all_channels():
            if ch["id"] == exclude_channel_id:
                continue
            for src in get_sources(ch):
                if src.get("channel_id") == source_id:
                    return ch
        return None

    def get_source_usage(self, channel_id: str) -> Optional[dict]:
        """Return how channel_id is used as a source, or None if it is not.

        Checks interleave sources first, then schedule sources.  The result is
        {"relationship": "interleave" | "schedule", "channel_id": <target id>,
        "channel_name": <target name>}.  Used to keep source channels hidden
        and to block carousel on them.
        """
        owner = self.get_interleave_source_owner(channel_id)
        if owner:
            return {"relationship": "interleave",
                    "channel_id":   owner.get("id", ""),
                    "channel_name": owner.get("name", "?")}
        for sch in (self.get_all_schedules() or {}).values():
            src = sch.get("source_channel") or sch.get("source_channel_id", "")
            if src and src == channel_id:
                target = self.get_channel(
                    sch.get("target_channel", "")) or {}
                return {"relationship": "schedule",
                        "channel_id":   target.get("id", ""),
                        "channel_name": target.get("name",
                                                   sch.get("name", "?"))}
        return None

    def get_combo_owner(self, combo_id: str) -> Optional[dict]:
        ch = self.get_channel(combo_id)
        return (ch.get("owner") or None) if ch else None

    # =========================================================================
    # Resume position  (spec §1.6)
    # Called by: service.py, player.py
    # =========================================================================

    def save_resume_position(self, channel_id: str, item_file: str,
                             position_seconds: float) -> None:
        """Save resume position for item_file on channel_id."""
        if not item_file:
            return
        key = "resume:{}:{}".format(channel_id, item_file)
        self._deleted_state_keys.discard(key)
        self._state[key] = round(position_seconds, 2)
        self._save_state()
        log("[ChannelManager] save_resume_position: {} @ {:.0f}s".format(
            key, position_seconds))

    def get_resume_position(self, channel_id: str,
                            item_file: str) -> Optional[dict]:
        """Return saved resume entry for item_file, or None.
        Returns None if position <= 10s (treat as not started).
        """
        if not item_file:
            return None
        key      = "resume:{}:{}".format(channel_id, item_file)
        position = self._state.get(key)
        if position is None:
            return None
        if float(position) <= 10:
            return None
        return {"position": float(position)}

    def clear_resume_position(self, channel_id: str, item_file: str) -> None:
        """Remove resume entry for item_file on channel_id."""
        if not item_file:
            return
        key = "resume:{}:{}".format(channel_id, item_file)
        self._state.pop(key, None)
        self._deleted_state_keys.add(key)
        self._save_state()

    def set_pending_seek(self, channel_id: str, position: float) -> None:
        """Store a seek position for service.py to execute in onAVStarted.

        Called by player.py start_channel() after the user accepts a resume
        dialog.  service.py reads and clears it via pop_pending_seek() once
        the file is open and seekTime() is safe (onAVStarted).
        """
        key = "pending_seek:{}".format(channel_id)
        self._state[key] = round(position, 2)
        self._deleted_state_keys.discard(key)
        self._save_state()

    def pop_pending_seek(self, channel_id: str) -> Optional[float]:
        """Return and remove any pending seek position for channel_id.

        Returns None if no seek is pending.  Clears the entry so it fires
        exactly once even if onAVStarted is called more than once.
        """
        key = "pending_seek:{}".format(channel_id)
        position = self._state.pop(key, None)
        if position is not None:
            self._deleted_state_keys.add(key)
            self._save_state()
            return float(position)
        return None

    # =========================================================================
    # Channel exhaustion  (spec §1.2)
    # =========================================================================

    # =========================================================================
    # Channel icon resolution
    # =========================================================================

    def resolve_channel_icon(self, ch: dict) -> str:
        """Resolve the display icon path for a channel.

        Priority: manual icon_path → channel_icon_folder auto-match → default.
        """
        ch_name   = ch.get("name", "")
        icon_path = ch.get("icon_path", "")
        if icon_path and xbmcvfs.exists(icon_path):
            return icon_path

        folder = normalize_share_path(
            self.addon.getSetting("channel_icon_folder"))
        if folder:
            ch_name_lower = ch_name.strip().lower()
            for ext in (".png", ".jpg", ".jpeg"):
                candidate = xbmcvfs.translatePath(
                    path_join(folder, ch_name + ext))
                if xbmcvfs.exists(candidate):
                    return candidate
            try:
                _dirs, files = xbmcvfs.listdir(folder)
                for fname in files:
                    if "." not in fname:
                        continue
                    base, fext = fname.rsplit(".", 1)
                    if ("." + fext.lower()) in (".png", ".jpg", ".jpeg"):
                        if base.lower() == ch_name_lower:
                            return xbmcvfs.translatePath(
                                path_join(folder, fname))
            except Exception as e:
                log("[ChannelManager] channel icon folder {} cannot be "
                    "listed: {}".format(folder, e), xbmc.LOGWARNING)

        return "DefaultVideoPlaylists.png"

    # =========================================================================
    # EPG stub  (spec §24)
    # =========================================================================

    # =========================================================================
    # Movie queue building  (used by channels/movies.py and _replacement_movie)
    # =========================================================================

    def build_fresh_movie_queue(self, channel: dict, size: int,
                                queued_ids=None, consumed_id=None) -> list:
        """Build a fresh movie queue. Called by MovieQueueBuilder and
        get_one_replacement. Delegates to _build_movie_queue."""
        return self._build_movie_queue(channel, size, queued_ids=queued_ids,
                                       consumed_id=consumed_id)

    def _build_movie_queue(self, channel: dict, target_size: int,
                           queued_ids=None, consumed_id=None) -> list:
        """Build a queue of movies for a movie channel.

        Uses the channel's movies list, applies filters and exclusions,
        respects randomize/recycle, tracks played_ids in state.json.

        queued_ids / consumed_id (1-for-1 replacement only): random draws
        prefer movies that are not already queued and not the one just
        consumed, falling back only when the pool leaves no other choice.

        target_size is a hard ceiling — the queue is filled by recycling
        through the movie pool as many times as needed until the queue
        reaches target_size (or the pool is exhausted for recycle=False).
        Matches 2.x behaviour exactly.
        """
        import random as _random

        channel_id = channel["id"]
        movies     = channel.get("movies", [])
        randomize  = channel.get("randomize", True)
        recycle    = channel.get("recycle",   True)

        if not movies:
            log("[ChannelManager] _build_movie_queue: no movies in channel")
            return []

        excluded     = set(channel.get("excluded_movies", []))
        filters      = channel.get("filters", [])
        movie_ids    = [m["movieid"] for m in movies
                        if m["movieid"] not in excluded]
        movie_id_set = set(movie_ids)

        # Load details from local cache — always read from file so we
        # see fresh data including plots, bypassing any stale in-memory copy.
        cached = self.library.load_local_cache()
        if cached and cached.get("movies"):
            all_movies = [m for m in cached["movies"]
                          if m.get("movieid") in movie_id_set]
        else:
            all_movies = [m for m in self.library.get_all_movies()
                          if m.get("movieid") in movie_id_set]

        if filters and all_movies:
            # Movies added by hand next to the filters ("pinned" in the
            # channel's list) are not filtered out.
            pinned_ids = {m["movieid"] for m in movies if m.get("pinned")}
            if pinned_ids:
                kept = [m for m in all_movies
                        if m.get("movieid") in pinned_ids]
                rest = [m for m in all_movies
                        if m.get("movieid") not in pinned_ids]
                all_movies = self.library.filter_items(rest, filters) + kept
            else:
                all_movies = self.library.filter_items(all_movies, filters)

        movie_lookup = {m["movieid"]: m for m in all_movies}
        if not movie_lookup:
            log("[ChannelManager] _build_movie_queue: no movies in library")
            return []

        # Dedup channel movie list preserving order
        seen_ids = set()
        all_available = []
        for mid in movie_ids:
            if mid not in seen_ids and mid in movie_lookup:
                seen_ids.add(mid)
                all_available.append(mid)

        if not all_available:
            return []

        # Load state fresh from disk so we always see the latest played_ids.
        state_key  = "{}:__movie_state__".format(channel_id)
        fresh      = self._load_json(self._state_path, {})
        mstate     = fresh.get(state_key, {"played_ids": [], "next_index": 0})
        played_ids = list(mstate.get("played_ids", []))
        next_index = mstate.get("next_index", 0)

        # Reconstruct unplayed pool, honouring any stored order and
        # appending movies added to the channel since the last build.
        stored_unplayed = mstate.get("unplayed_ids")
        valid_id_set    = set(all_available)
        if stored_unplayed is not None:
            unplayed_ids = [mid for mid in stored_unplayed if mid in valid_id_set]
            stored_set   = set(stored_unplayed) | set(played_ids)
            for mid in all_available:
                if mid not in stored_set:
                    unplayed_ids.append(mid)
        else:
            unplayed_ids = [mid for mid in all_available if mid not in played_ids]

        queue = []

        if randomize:
            # Draw from unplayed pool, recycling through all_available as
            # needed until target_size is reached.  Matches 2.x exactly:
            # every movie plays once per cycle before any repeats; the cycle
            # boundary falls wherever target_size lands (no padding to a full
            # cycle).  A back-to-back repeat guard is applied at each cycle
            # reset so the last movie of one cycle never immediately precedes
            # the first movie of the next.
            if not recycle and not unplayed_ids:
                pass  # pool exhausted and recycle=False — return empty
            else:
                working_unplayed = list(unplayed_ids)
                working_played   = list(played_ids)
                while len(queue) < target_size:
                    if not working_unplayed:
                        if not recycle:
                            break
                        log("[ChannelManager] _build_movie_queue: "
                            "cycle complete — resetting for next cycle")
                        working_played   = []
                        working_unplayed = list(all_available)
                        if not working_unplayed:
                            break
                    # Shuffle the remaining pool each draw pass.
                    draw_pool = list(working_unplayed)
                    _random.shuffle(draw_pool)
                    if queued_ids or consumed_id is not None:
                        # Stable sort keeps the shuffle inside each tier:
                        # 0 not queued & not just consumed, 1 not queued,
                        # 2 not just consumed, 3 anything.
                        _q = queued_ids or set()
                        draw_pool.sort(key=lambda m: (
                            (0 if m != consumed_id else 1) if m not in _q
                            else (2 if m != consumed_id else 3)))
                    # Back-to-back repeat guard at cycle boundary.
                    if (queue and len(draw_pool) > 1 and
                            draw_pool[0] == queue[-1].get("movieid")):
                        draw_pool = draw_pool[1:] + draw_pool[:1]
                    slots_needed = target_size - len(queue)
                    for mid in draw_pool[:slots_needed]:
                        movie = movie_lookup.get(mid)
                        if movie:
                            norm = _normalize_movie_fn(
                                movie, channel_id, library=self.library,
                                default_seconds=self._default_movie_seconds())
                            self._note_default_length(channel_id, movie, norm)
                            if not norm or not norm.get("duration"):
                                self.record_missing_duration(
                                    channel_id, movie, "no_runtime")
                            else:
                                queue.append(norm)
                        working_unplayed.remove(mid)
                        working_played.append(mid)
                unplayed_ids = working_unplayed
                played_ids   = working_played
        else:
            # Sequential — walk all_available from next_index, wrapping
            # when recycle=True, stopping when recycle=False.
            for _ in range(target_size):
                if not all_available:
                    break
                if next_index >= len(all_available):
                    if not recycle:
                        break
                    next_index = 0
                chosen_id = all_available[next_index]
                movie     = movie_lookup.get(chosen_id)
                if movie:
                    norm = _normalize_movie_fn(
                        movie, channel_id, library=self.library,
                        default_seconds=self._default_movie_seconds())
                    self._note_default_length(channel_id, movie, norm)
                    if not norm or not norm.get("duration"):
                        self.record_missing_duration(
                            channel_id, movie, "no_runtime")
                    else:
                        queue.append(norm)
                next_index += 1

        # Persist updated cycle state.
        self.write_state_key(state_key, {
            "played_ids":   played_ids,
            "unplayed_ids": unplayed_ids,
            "next_index":   next_index,
        })

        log("[ChannelManager] _build_movie_queue: built {} items for '{}'".format(
            len(queue), channel.get("name", channel_id)))
        return queue

    # =========================================================================
    # Combo Block queue building  (used by channels/combo.py)
    # =========================================================================

    def build_combo_tv_slot(self, combo_channel_id: str,
                            slot: dict, count: int,
                            host_queue: Optional[list] = None) -> list:
        """Build `count` TV episodes for one Combo Block TV slot.

        When multiple shows are configured on the slot they rotate in
        round-robin order — one episode per show per unit — matching 2.x
        exactly.  Result order: [show0_ep0, show1_ep0, show0_ep1, ...].
        A slot set to take turns plays one show per cycle instead
        (episodes_per_turn episodes), the next show on the next cycle.

        State is isolated to combo_channel_id:slot_id and never touches
        any standalone channel's state.

        Random shows are Random / No Repeat: each show keeps the episodes
        drawn this cycle (state key ...:tv_played) and a draw only takes an
        undrawn one.  When the cycle wraps, episodes of this show still
        waiting in host_queue count as already drawn in the new cycle.
        """
        import random as _random

        slot_id = slot.get("slot_id", "")
        shows   = slot.get("shows")
        if not shows:
            legacy_id = slot.get("tvshowid")
            if not legacy_id:
                return []
            shows = [{
                "tvshowid":          legacy_id,
                "title":             slot.get("title", str(legacy_id)),
                "episode_filters":   slot.get("episode_filters",   []),
                "excluded_episodes": slot.get("excluded_episodes", []),
                "randomize":         slot.get("randomize", True),
                "recycle":           slot.get("recycle",   True),
                "silent":            slot.get("silent",    False),
            }]

        num_shows = len(shows)
        log("[ChannelManager] build_combo_tv_slot: slot {} — {} show(s), "
            "count={}".format(slot_id[:8], num_shows, count))

        # show_slot tracks position within the per-unit episode sequence.
        # The sequence repeats the show index eps_per_slot times, e.g. for
        # Show A (eps=2) and Show B (eps=1): sequence = [0, 0, 1] (length 3).
        # Each 1-for-1 replacement call (count=1) advances show_slot by 1
        # through this sequence so the correct show is always picked.
        show_slot_key = "combo:{}:slot:{}:show_slot".format(
            combo_channel_id, slot_id)
        try:
            show_slot = int(self.read_state_key(show_slot_key, 0))
        except (TypeError, ValueError):
            show_slot = 0

        # Build the repeating show sequence from eps_per_slot values.
        # sequence[i] = show_pools index for the i-th episode in one unit.
        # When the shows take turns, each show owns a run of
        # episodes_per_turn positions and one cycle plays one run:
        # A(2) B(2) -> [0, 0, 1, 1]; cycle 1 plays A, cycle 2 plays B.
        takes_turns = tv_slot_takes_turns(slot)
        unit_sequence = []
        for pool_idx, show_entry in enumerate(shows):
            if takes_turns:
                eps = tv_turn_size(slot)
            else:
                eps = max(1, int(show_entry.get("episodes_per_slot", 1)))
            unit_sequence.extend([pool_idx] * eps)
        unit_cycle = len(unit_sequence) if unit_sequence else num_shows

        # Silent is a slot-level setting — all shows in a TV slot share
        # the same silent flag (they rotate as a unit).
        slot_silent = slot.get("silent", False)

        # Build per-show episode pools once.
        show_pools = []
        for show_entry in shows:
            show_id   = show_entry.get("tvshowid")
            randomize = show_entry.get("randomize", True)
            recycle   = show_entry.get("recycle",   True)
            # Per-show silent is kept for backward-compat with existing
            # channel data that stored it per-show; slot level takes
            # precedence when set, otherwise fall back to per-show value.
            silent    = slot_silent or show_entry.get("silent", False)

            available = self.get_available_episodes(show_entry)
            if not available:
                log("[ChannelManager] build_combo_tv_slot: no episodes for "
                    "show {} (slot {})".format(show_id, slot_id[:8]))
                show_pools.append(None)
                continue

            avail_ids   = [e["episodeid"] for e in available]
            next_ep_key = "combo:{}:slot:{}:show:{}:tv_next_ep".format(
                combo_channel_id, slot_id, show_id)

            stored_next = self.read_state_key(next_ep_key, None)
            if stored_next is not None:
                try:
                    start_idx = avail_ids.index(int(stored_next))
                except ValueError:
                    start_idx = 0
            else:
                start_idx = 0

            played_key = "combo:{}:slot:{}:show:{}:tv_played".format(
                combo_channel_id, slot_id, show_id)
            played_set = set()
            queued_now = set()
            if randomize:
                # Episodes of this show already waiting in the queue.  A
                # draw avoids them whenever it can, whatever the saved
                # "drawn this cycle" list says.
                queued_now = {i.get("episodeid") for i in (host_queue or [])
                              if i.get("_combo_slot") == slot_id
                              and i.get("show_id") == show_id
                              and i.get("episodeid") in avail_ids}
                try:
                    played_set = set(
                        self.read_state_key(played_key, None) or [])
                except TypeError:
                    played_set = set()
                played_set &= set(avail_ids)
                undrawn = [e for e in available
                           if e["episodeid"] not in played_set]
                if not undrawn:
                    # Cycle complete: start the next one.  Episodes of this
                    # show still waiting in the queue count as drawn in it.
                    played_set = set()
                    if len(queued_now) < len(avail_ids):
                        played_set = set(queued_now)
                    undrawn = [e for e in available
                               if e["episodeid"] not in played_set]
                    log("[ChannelManager] build_combo_tv_slot: slot {} "
                        "show {} cycle wrapped, {} queued episode(s) "
                        "kept out of the new cycle".format(
                            slot_id[:8], show_id, len(played_set)))
                pool = [e for e in undrawn
                        if e["episodeid"] not in queued_now]
                held = [e for e in undrawn
                        if e["episodeid"] in queued_now]
                _random.shuffle(pool)
                _random.shuffle(held)
                pool = pool + held
            else:
                pool = available[start_idx:] + available[:start_idx]

            show_pools.append({
                "played_key":   played_key,
                "played_set":   played_set,
                "show_id":      show_id,
                "randomize":    randomize,
                "recycle":      recycle,
                "silent":       silent,
                "available":    available,
                "avail_ids":    avail_ids,
                "pool":         pool,
                "queued":       queued_now,
                "pool_offset":  0,
                "exhausted":    False,
                "next_ep_key":  next_ep_key,
                "eps_per_slot": max(1, int(
                    show_entry.get("episodes_per_slot", 1))),
            })

        # Round-robin: one full turn per show per unit.
        # Each turn fetches eps_per_slot consecutive episodes from that show
        # before advancing to the next show, giving correct grouping:
        # [A_ep1, A_ep2, B_ep1] for eps_per_slot(A)=2, eps_per_slot(B)=1.
        #
        # `count` passed in = units_needed * sum(eps_per_slot).
        # Recover units_needed so we iterate the right number of rounds.
        def _cycle_pool(sp):
            """Episodes for a new cycle, shuffled, with those already in
            the queue (or drawn in this call) last so they are drawn only
            when nothing else is left."""
            fresh = [e for e in sp["available"]
                     if e["episodeid"] not in sp["queued"]]
            held  = [e for e in sp["available"]
                     if e["episodeid"] in sp["queued"]]
            _random.shuffle(fresh)
            _random.shuffle(held)
            return fresh + held

        def _fetch_one_ep(sp):
            """Pop the next valid episode from a show pool.
            Handles recycle and no-duration skipping.
            Returns a normalised item dict or None.
            """
            pool = sp["pool"]
            ep   = None

            if sp["pool_offset"] < len(pool):
                ep                = pool[sp["pool_offset"]]
                sp["pool_offset"] += 1
            elif sp["recycle"]:
                if sp["randomize"]:
                    # Pool used up inside one call: new cycle.
                    pool[:]            = _cycle_pool(sp)
                    sp["played_set"].clear()
                    log("[ChannelManager] build_combo_tv_slot: show {} "
                        "cycle wrapped inside one call".format(
                            sp["show_id"]))
                sp["pool_offset"] = 1
                ep = pool[0] if pool else None
                if ep is None:
                    sp["exhausted"] = True
                    return None
            else:
                sp["exhausted"] = True
                return None
            if sp["randomize"]:
                sp["played_set"].add(ep["episodeid"])
                sp["queued"].add(ep["episodeid"])

            # Try episodes until one has a valid duration.
            attempts = len(pool)
            while attempts > 0:
                norm = _normalize_ep_fn(ep, combo_channel_id,
                                        sp["show_id"],
                                        all_episodes_for_show=sp["available"],
                                        default_seconds=self._default_episode_seconds())
                self._note_default_length(combo_channel_id, ep, norm)
                if norm is not None:
                    norm["channel_id"]  = combo_channel_id
                    norm["_channel_id"] = combo_channel_id
                    norm["show_id"]     = sp["show_id"]
                    norm["_show_id"]    = sp["show_id"]
                    norm["_silent"]     = sp["silent"]
                    return norm
                self.record_missing_duration(combo_channel_id, ep, "no_nfo")
                attempts -= 1
                if sp["pool_offset"] < len(pool):
                    ep                = pool[sp["pool_offset"]]
                    sp["pool_offset"] += 1
                elif sp["recycle"]:
                    if sp["randomize"]:
                        pool[:]            = _cycle_pool(sp)
                        sp["played_set"].clear()
                        log("[ChannelManager] build_combo_tv_slot: show "
                            "{} cycle wrapped inside one call".format(
                                sp["show_id"]))
                    sp["pool_offset"] = 1
                    ep = pool[0] if pool else None
                    if ep is None:
                        break
                else:
                    break
                if sp["randomize"]:
                    sp["played_set"].add(ep["episodeid"])
                    sp["queued"].add(ep["episodeid"])
            return None

        # Build exactly `count` episodes, selecting shows via unit_sequence.
        # show_slot is the position within unit_sequence, persisted across
        # calls so the 1-for-1 replacement path (count=1) always picks the
        # correct show for the current position in the repeating pattern.
        #
        # Example: A(eps=2), B(eps=1) → unit_sequence=[0,0,1], cycle=3
        #   call 1 (count=1, show_slot=0): seq[0]=Show A → A_ep1, show_slot→1
        #   call 2 (count=1, show_slot=1): seq[1]=Show A → A_ep2, show_slot→2
        #   call 3 (count=1, show_slot=2): seq[2]=Show B → B_ep1, show_slot→3
        #   call 4 (count=1, show_slot=3%3=0): seq[0]=Show A → A_ep3 ...
        result = []
        episodes_needed = count
        while episodes_needed > 0:
            seq_idx  = show_slot % unit_cycle if unit_cycle else 0
            pool_idx = unit_sequence[seq_idx] if unit_sequence else 0
            sp       = show_pools[pool_idx] if pool_idx < len(show_pools) else None

            if sp is None or sp["exhausted"]:
                # This show is exhausted — advance and try next position.
                show_slot += 1
                if all(sp is None or sp["exhausted"] for sp in show_pools):
                    break
                continue

            norm = _fetch_one_ep(sp)
            if norm is not None:
                result.append(norm)
                episodes_needed -= 1
            show_slot += 1

        # Persist per-show next-episode pointers (and, for random shows,
        # the episodes drawn this cycle).
        for sp in show_pools:
            if sp is None:
                continue
            if sp["randomize"]:
                self.write_state_key(sp["played_key"],
                                     sorted(sp["played_set"]))
            last_ep_id = None
            for item in reversed(result):
                if item.get("show_id") == sp["show_id"]:
                    last_ep_id = item.get("episodeid", -1)
                    break
            if last_ep_id is not None:
                avail_ids = sp["avail_ids"]
                available = sp["available"]
                try:
                    last_idx = avail_ids.index(last_ep_id)
                    next_idx = (last_idx + 1) % len(available)
                    next_id  = avail_ids[next_idx]
                except (ValueError, ZeroDivisionError):
                    next_id  = avail_ids[0] if avail_ids else None
                if next_id is not None:
                    self.write_state_key(sp["next_ep_key"], next_id)

        # Persist show_slot — already advanced in the loop above.
        self.write_state_key(show_slot_key, show_slot)

        log("[ChannelManager] build_combo_tv_slot: slot {} built {} "
            "items".format(slot_id[:8], len(result)))
        return result

    def build_combo_movie_slot(self, combo_channel_id: str,
                               slot: dict, count: int,
                               host_queue: Optional[list] = None) -> list:
        """Build count movies for one Combo Block Movie slot.

        Random slots are Random / No Repeat: a movie is marked drawn when it
        is built, so no movie is drawn twice per cycle.  host_queue (the
        queue the item is appended to) is used when a cycle wraps: movies
        still waiting in the queue count as already drawn in the new cycle.
        """
        import random as _random

        slot_id   = slot.get("slot_id", "")
        randomize = slot.get("randomize", True)
        recycle   = slot.get("recycle",   True)
        excluded  = set(slot.get("excluded_movies", []))
        filters   = slot.get("filters", [])
        state_key = "combo:{}:slot:{}:movie_state".format(
            combo_channel_id, slot_id)

        explicit_movies = slot.get("movies", [])
        if filters and explicit_movies:
            # Filter slot with extras (3.1.152): the movies the filters match
            # plus the ones added by hand, which the filters do not touch.
            extra_ids = {m["movieid"] for m in explicit_movies
                         if "movieid" in m}
            matched   = self.library.get_movies_with_filters(filters)
            seen      = {m.get("movieid") for m in matched}
            all_movies = list(matched) + [
                m for m in self.library.get_all_movies()
                if m.get("movieid") in extra_ids
                and m.get("movieid") not in seen]
        elif explicit_movies:
            # User picked specific movies — build pool from those IDs only.
            explicit_ids = {m["movieid"] for m in explicit_movies
                            if "movieid" in m}
            all_movies = [m for m in self.library.get_all_movies()
                          if m.get("movieid") in explicit_ids]
        else:
            if filters:
                all_movies = self.library.get_movies_with_filters(filters)
            else:
                all_movies = self.library.get_all_movies()
        all_movies = [m for m in all_movies
                      if m.get("movieid", -1) not in excluded]
        if not all_movies:
            return []

        all_ids    = [m["movieid"] for m in all_movies]
        mstate     = self.read_state_key(state_key, None) or {}
        played     = set(mstate.get("played_ids", []))
        unplayed   = [m for m in all_movies if m.get("movieid", -1) not in played]

        if not unplayed:
            if not recycle:
                return []
            played   = set()
            if randomize and host_queue:
                # New cycle: movies of this slot still waiting in the queue
                # are treated as already drawn in it.
                slot_queued = {i.get("movieid") for i in host_queue
                               if i.get("_combo_slot") == slot_id
                               and i.get("movieid") in all_ids}
                if len(slot_queued) < len(all_ids):
                    played = set(slot_queued)
            unplayed = [m for m in all_movies
                        if m.get("movieid", -1) not in played]
            self.write_state_key(state_key, {
                "played_ids":   list(played),
                "unplayed_ids": [m["movieid"] for m in unplayed]})

        if randomize:
            pool = unplayed[:]
            _random.shuffle(pool)
        else:
            pool = unplayed

        result = []
        for movie in pool[:count]:
            norm = _normalize_movie_fn(movie, combo_channel_id, library=self.library,
                                default_seconds=self._default_movie_seconds())
            self._note_default_length(combo_channel_id, movie, norm)
            if not norm or not norm.get("duration"):
                self.record_missing_duration(combo_channel_id, movie, "no_runtime")
                continue
            norm["channel_id"]  = combo_channel_id
            norm["_channel_id"] = combo_channel_id
            result.append(norm)
            played.add(movie.get("movieid", -1))

        remaining = [m["movieid"] for m in all_movies
                     if m.get("movieid", -1) not in played]
        self.write_state_key(state_key, {
            "played_ids":   list(played),
            "unplayed_ids": remaining,
        })
        return result

    def get_interleave_items(self, source_channel_id: str, count: int) -> list:
        """Fetch count items from source_channel_id for interleave insertion.
        Called by carousel.py.
        """
        foreign_ch = self.get_channel(source_channel_id)
        if not foreign_ch:
            return []
        try:
            return self._load_foreign_items(source_channel_id, foreign_ch, count) or []
        except Exception as exc:
            log("[ChannelManager] get_interleave_items error: {}".format(exc))
            return []

    def _load_foreign_items(self, foreign_id: str, foreign_ch: dict,
                            needed: int) -> list:
        """Load needed items from a foreign channel for interleave weaving.

        For TV channel sources: builds from a FRESH cursor (ep_pos all zeroes)
        plus the source's starting episodes, regardless of where the TV
        channel's own queue build left the cursor.  The fresh cursor is
        written back so subsequent calls continue from where this one left off,
        but the TV channel's own standalone cursor is not touched — we save it
        first and restore it after so the TV channel's own queue is unaffected.
        """
        ctype = foreign_ch.get("channel_type", "tv")
        if ctype == "tv":
            # Save the TV channel's own cursor so we can restore it.
            own_cursor = self.get_cursor(foreign_id)
            # Build a fresh interleave cursor starting from episode 1.
            fresh_cursor = {
                "show_slot": 0,
                "ep_pos":    {},
                "ep_played": {},
                "slot_owed": {},
            }
            # The source's chosen starting episodes apply, as they do when
            # the channel builds its own queue.  During a host rebuild the
            # episodes the host had reached override them show by show.
            self._apply_starting_points(foreign_ch, fresh_cursor)
            resume = self._interleave_resume.get(foreign_id)
            if resume:
                resume_ch = dict(foreign_ch)
                resume_ch["starting_points"] = resume
                self._apply_starting_points(resume_ch, fresh_cursor)
            items, interleave_cursor = self._build_tv_items(
                foreign_ch, needed, fresh_cursor)
            # Restore the TV channel's own cursor — the channel's standalone
            # queue must not be affected by the interleave build.
            self.set_cursor(foreign_id, own_cursor)
            return items
        if ctype == "movies":
            return self._build_movie_queue(foreign_ch, needed)
        if ctype == "folder":
            from resources.lib.channels.folder import FolderQueueBuilder
            return FolderQueueBuilder(self).build(foreign_ch, needed) or []
        if ctype == "combo":
            from resources.lib.channels.combo import ComboQueueBuilder
            return ComboQueueBuilder(self).build(foreign_ch, needed)
        return []

    # =========================================================================
    # Show state public API  (used by folder.py, party.py, service.py)
    # =========================================================================

    def get_show_state(self, channel_id: str, show_id: int) -> dict:
        """Return the playback state dict for show_id within channel_id."""
        key = "{}:{}".format(channel_id, show_id)
        return self._state.get(key, {
            "next_episode_id": None,
            "season":          1,
            "episode":         1,
            "played_ids":      [],
        })

    def capture_interleave_progress(self, channel_id: str) -> dict:
        """Where each interleaved sequential TV show is up to in a host queue.

        Returns {source_id: {str(show_id): {episodeid, season, episode,
        title}}}: the first queued (next-to-play) episode of each show from
        each TV source.  Randomised shows and Serial sources are skipped —
        they have no fixed next episode.
        """
        progress: dict = {}
        sources: dict = {}
        for item in self.get_channel_queue(channel_id):
            if not item.get("_interleaved"):
                continue
            source_id = item.get("_channel_id")
            sid = item.get("show_id") or item.get("_show_id")
            ep_id = item.get("episodeid")
            if not source_id or sid is None or ep_id is None:
                continue
            if source_id not in sources:
                sources[source_id] = self.get_channel(source_id)
            source = sources[source_id]
            if (not source or source.get("channel_type", "tv") != "tv"
                    or source.get("playback_mode") == "serial"):
                continue
            show = next((s for s in source.get("shows", [])
                         if s["tvshowid"] == sid), None)
            if show is None or show.get(
                    "randomize", source.get("randomize", False)):
                continue
            shows = progress.setdefault(source_id, {})
            if str(sid) in shows:
                continue
            shows[str(sid)] = {
                "episodeid": ep_id,
                "season":    item.get("season", 1),
                "episode":   item.get("episode", 1),
                "title":     item.get("title", ""),
            }
        return progress

    def begin_interleave_resume(self, progress: dict) -> None:
        """Make interleave weaves start each source show at *progress*
        (from capture_interleave_progress) until end_interleave_resume."""
        self._interleave_resume = progress or {}

    def end_interleave_resume(self) -> None:
        """Stop applying captured interleave progress."""
        self._interleave_resume = {}

    def get_show_next_queued_episode(self, channel_id: str,
                                     show_id: int,
                                     queue: Optional[list] = None
                                     ) -> Optional[dict]:
        """Return the first queued (next-to-play) episode item for show_id on
        this channel, or None when the show has no episode in the queue.

        The queue is the authority for what a show will play next; the
        per-show state record is not advanced by playback. Interleaved
        items are ignored — their show belongs to another channel.

        queue: the channel's queue, when the caller has already read it
        (strictly); otherwise it is read here.
        """
        for item in (queue if queue is not None
                     else self.get_channel_queue(channel_id)):
            if item.get("_interleaved"):
                continue
            sid = item.get("show_id") or item.get("_show_id")
            if sid is not None and int(sid) == int(show_id):
                return item
        return None

    def save_show_state(self, channel_id: str, show_id: int,
                        state: dict) -> None:
        """Persist show state for show_id within channel_id."""
        key = "{}:{}".format(channel_id, show_id)
        self._state[key] = state
        self._save_state()

    def record_folder_file_played(self, channel_id: str,
                                   file_path: Optional[str]) -> None:
        """Record a folder/party file as played for recycle=False / no_repeat tracking.

        When file_path is None, clears the entire played list — used by
        FolderQueueBuilder when a no_repeat cycle completes and the slot
        should start over from the full file set.
        """
        state = self.get_show_state(channel_id, 0)
        if file_path is None:
            # Clear played list — no_repeat cycle reset.
            if "played_files" in state:
                state["played_files"] = []
                self.save_show_state(channel_id, 0, state)
            return
        played = state.get("played_files", [])
        if file_path not in played:
            played.append(file_path)
            state["played_files"] = played
            self.save_show_state(channel_id, 0, state)

    # =========================================================================
    # Audio no-repeat state  (used by channels/audio.py)
    # =========================================================================

    def get_audio_no_repeat_played(self, channel_id: str) -> list:
        state_key = "{}:audio_no_repeat_played".format(channel_id)
        return list(self._load_json(self._state_path, {}).get(state_key, []))

    def set_audio_no_repeat_played(self, channel_id: str,
                                    played: list) -> None:
        state_key = "{}:audio_no_repeat_played".format(channel_id)
        self.write_state_key(state_key, played)

    # =========================================================================
    # Folder random cycle state  (used by channels/folder.py build_one)
    # =========================================================================

    def get_folder_cycle(self, channel_id: str) -> Optional[list]:
        """Return the files not yet used this random cycle, or None."""
        state_key = "{}:__folder_cycle__".format(channel_id)
        val = self._load_json(self._state_path, {}).get(state_key)
        return list(val) if isinstance(val, list) else None

    def set_folder_cycle(self, channel_id: str, unplayed: list) -> None:
        """Store the files not yet used this random cycle."""
        self.write_state_key("{}:__folder_cycle__".format(channel_id),
                             list(unplayed))

    # =========================================================================
    # Party no-repeat state  (used by channels/party.py)
    # =========================================================================

    def get_party_no_repeat_played(self, channel_id: str) -> list:
        state_key = "{}:party_no_repeat_played".format(channel_id)
        return list(self._load_json(self._state_path, {}).get(state_key, []))

    def set_party_no_repeat_played(self, channel_id: str,
                                    played: list) -> None:
        state_key = "{}:party_no_repeat_played".format(channel_id)
        self.write_state_key(state_key, played)

    # =========================================================================
    # has_resume_for_file  (used by channels/folder.py)
    # =========================================================================

    def has_resume_for_file(self, channel_id: str, file_path: str) -> bool:
        """Return True if a resume position exists for file_path on channel."""
        import hashlib
        if not file_path:
            return False
        md5 = hashlib.md5(file_path.encode("utf-8")).hexdigest()[:16]
        key = "resume:{}:file:{}".format(channel_id, md5)
        return key in self._load_json(self._state_path, {})

    # =========================================================================
    # Default length settings (used when neither the NFO nor Kodi has one)
    # =========================================================================

    def _default_length_seconds(self, setting_id: str, fallback_minutes: int) -> int:
        """Return a default-length setting (stored in minutes) as seconds.
        0 means "not set": the item is skipped as before."""
        try:
            raw = self.addon.getSetting(setting_id)
            minutes = int(raw) if str(raw).strip() != "" else fallback_minutes
        except Exception:
            minutes = fallback_minutes
        return max(0, minutes) * 60

    def _default_episode_seconds(self) -> int:
        return self._default_length_seconds("default_episode_minutes", 30)

    def _default_movie_seconds(self) -> int:
        return self._default_length_seconds("default_movie_minutes", 100)

    # =========================================================================
    # folder_default_duration setting helper
    # =========================================================================

    # =========================================================================
    # Queue pre-generation helper (called after create / edit)
    # =========================================================================

    def _apply_combo_slot_starting_points(self, channel: dict) -> None:
        """Write tv_next_ep state for any combo TV slots that have starting_points.

        Called when a combo channel is created or updated so that the first
        episode fetched by build_combo_tv_slot starts from the user's chosen
        episode rather than the beginning of the show.
        """
        channel_id = channel["id"]
        for slot in channel.get("slots", []):
            if slot.get("source_type") != "tv":
                continue
            slot_id         = slot.get("slot_id", "")
            starting_points = slot.get("starting_points", {})
            if not starting_points:
                continue
            for show in slot.get("shows", []):
                sid    = show["tvshowid"]
                sp     = starting_points.get(str(sid)) or starting_points.get(sid)
                if not sp:
                    continue
                ep_id  = sp.get("episodeid")
                if ep_id is None:
                    continue
                key = "combo:{}:slot:{}:show:{}:tv_next_ep".format(
                    channel_id, slot_id, sid)
                if key in self._combo_resume:
                    # A rebuild that keeps places: the show continues where
                    # it was, not at its starting point.
                    continue
                self.write_state_key(key, ep_id)
                log("[ChannelManager] combo slot starting point: "
                    "show {} → episodeid {} (S{}E{} '{}')".format(
                    sid, ep_id,
                    sp.get("season", "?"), sp.get("episode", "?"),
                    sp.get("title", "")))

    def _sync_combo_state_from_queue(self, woven_queue: list,
                                     channel: dict) -> None:
        """After weaving, set tv_next_ep for each combo TV slot to the episode
        that follows the last one actually inserted into the woven queue.

        The interleave weaver may fetch more items from a combo source than it
        inserts (e.g. ComboQueueBuilder.build fetches N items but the weaver
        only inserts a subset).  Without this, tv_next_ep points past all
        fetched items, causing the first 1-for-1 replacement to skip episodes.

        Called after apply_interleave_list returns in both regenerate_queue
        and _build_fresh_tv_queue.
        """
        from resources.lib.channels.interleave import get_sources
        for source in get_sources(channel):
            src_ch = self.get_channel(source["channel_id"])
            if not src_ch or src_ch.get("channel_type") != "combo":
                continue
            combo_id = src_ch["id"]
            for slot in src_ch.get("slots", []):
                if slot.get("source_type") != "tv":
                    continue
                slot_id = slot.get("slot_id", "")
                for show in slot.get("shows", []):
                    show_id = show.get("tvshowid")
                    if not show_id:
                        continue
                    # Find the last episode from this show/slot in the queue.
                    last_ep_id = None
                    for item in reversed(woven_queue):
                        if (item.get("_combo_slot") == slot_id
                                and item.get("show_id") == show_id):
                            last_ep_id = item.get("episodeid")
                            break
                    if last_ep_id is None:
                        continue
                    # Set tv_next_ep to the episode after the last one used.
                    available  = self.get_available_episodes(show)
                    avail_ids  = [e["episodeid"] for e in available]
                    try:
                        last_idx = avail_ids.index(last_ep_id)
                        next_id  = avail_ids[(last_idx + 1) % len(avail_ids)]
                    except (ValueError, ZeroDivisionError):
                        next_id  = avail_ids[0] if avail_ids else None
                    if next_id is not None:
                        key = "combo:{}:slot:{}:show:{}:tv_next_ep".format(
                            combo_id, slot_id, show_id)
                        self.write_state_key(key, next_id)
                        log("[ChannelManager] _sync_combo_state_from_queue: "
                            "slot {} show {} → next episodeid {}".format(
                                slot_id[:8], show_id, next_id))
                if tv_slot_takes_turns(slot):
                    self._sync_turn_position(woven_queue, combo_id, slot)
        self._save_state()

    def _sync_turn_position(self, queue: list, combo_id: str,
                            slot: dict) -> None:
        """Point a taking-turns TV slot at the turn that follows the last
        item of that slot actually in *queue*.

        The weaver can fetch more cycles than it inserts, which would leave
        the turn counter ahead of the queue and could play the same show
        in two cycles in a row.  The next draw continues the show that is
        last in the queue until its turn is complete, then moves on.
        """
        slot_id  = slot.get("slot_id", "")
        show_ids = [s.get("tvshowid") for s in slot.get("shows", [])]
        turn     = tv_turn_size(slot)
        items    = [i for i in queue
                    if i.get("_combo_slot") == slot_id
                    and i.get("show_id") in show_ids]
        if not items:
            return
        last_show = items[-1].get("show_id")
        run = 0
        for item in reversed(items):
            if item.get("show_id") != last_show:
                break
            run += 1
        position = (show_ids.index(last_show) * turn
                    + min(run, turn)) % (len(show_ids) * turn)
        self.write_state_key(
            "combo:{}:slot:{}:show_slot".format(combo_id, slot_id), position)
        log("[ChannelManager] _sync_turn_position: slot {} next turn "
            "position {}".format(slot_id[:8], position))

    def _reset_combo_interleave_sources(self, channel: dict) -> list:
        """Clear episode-position state for every combo block that is an
        interleave source of *channel*, then return those combo channels.

        Called before building a TV channel queue so that both the interleave
        weave inside that build AND the subsequent standalone combo queue
        rebuild start from episode 1 rather than from wherever the pointer
        was left by a previous build.

        The state keys cleared per combo TV slot are:
            combo:{combo_id}:slot:{slot_id}:show_slot
            combo:{combo_id}:slot:{slot_id}:show:{show_id}:tv_next_ep

        Returns the list of combo channel dicts that were reset, so the
        caller can rebuild their standalone queues afterwards.
        """
        from resources.lib.channels.interleave import get_sources
        reset_combos = []
        for source in get_sources(channel):
            src_ch = self.get_channel(source["channel_id"])
            if not src_ch or src_ch.get("channel_type") != "combo":
                continue
            combo_id = src_ch["id"]
            # Clear show_slot and tv_next_ep for every TV slot in this combo.
            keys_to_clear = []
            for slot in src_ch.get("slots", []):
                if slot.get("source_type") != "tv":
                    continue
                slot_id = slot.get("slot_id", "")
                keys_to_clear.append(
                    "combo:{}:slot:{}:show_slot".format(combo_id, slot_id))
                for show in slot.get("shows", []):
                    keys_to_clear.append(
                        "combo:{}:slot:{}:show:{}:tv_next_ep".format(
                            combo_id, slot_id, show["tvshowid"]))
            for k in keys_to_clear:
                self._state.pop(k, None)
                self._deleted_state_keys.add(k)
            # A rebuild that keeps places puts the captured episodes back
            # (rebuild_keep_places); every other caller has nothing here.
            for k in keys_to_clear:
                if k in self._combo_resume:
                    self._deleted_state_keys.discard(k)
                    self._state[k] = self._combo_resume[k]
            if keys_to_clear:
                self._save_state()
                log("[ChannelManager] _reset_combo_interleave_sources: "
                    "cleared {} state key(s) for combo '{}' so next "
                    "build starts from episode 1".format(
                        len(keys_to_clear), src_ch.get("name", combo_id)))
            reset_combos.append(src_ch)
        return reset_combos

    def _pregenerate_queue_safe(self, channel: dict,
                                start_show_index: Optional[int] = None,
                                keep_places=None) -> None:
        """Build a fresh queue for channel and write it to disk.
        Catches and logs all exceptions so a builder failure never crashes
        the wizard.
        """
        channel_id = channel["id"]
        ChannelManager._rebuild_failed.discard(channel_id)
        try:
            # Combo block channels do not use a standalone queue file.
            # Their items are built on-demand via build_one_slot (1-for-1
            # replacement) or woven into the owning TV channel queue during
            # build_channel_queue.  Writing a queue file here would produce
            # a file that is never read and would advance state (show_slot,
            # tv_next_ep) before the TV channel interleave build runs,
            # causing the TV channel to start at the wrong episode.
            # Only apply_combo_slot_starting_points is needed here — it
            # initialises the state keys so the first build_one_slot call
            # starts at the chosen episode.
            if channel.get("channel_type") == "combo":
                self._apply_combo_slot_starting_points(channel)
                log("[ChannelManager] _pregenerate_queue_safe: skipping "
                    "queue file for combo '{}' (not used in 3.x)".format(
                        channel.get("name", channel_id)))
                return

            # For TV channels with combo interleave sources: reset the combo
            # episode pointers to the beginning before building the TV queue.
            # This ensures the interleave weave inside build_channel_queue
            # starts from episode 1, not from wherever the pointer was left
            # by a previous standalone combo build.  After the TV queue is
            # written, rebuild each combo's standalone queue so it picks up
            # from the episode immediately after those used by the TV queue.
            reset_combos = []
            if channel.get("channel_type") in ("tv", "movies", "folder"):
                reset_combos = self._reset_combo_interleave_sources(channel)

            queue = self.build_channel_queue(channel,
                                             start_show_index=start_show_index,
                                             keep_places=keep_places)
            if queue:
                self._write_queue_file(channel_id, queue)
                log("[ChannelManager] Pre-generated {} items for '{}'".format(
                    len(queue), channel.get("name", channel_id)))
            else:
                log("[ChannelManager] Pre-generate: empty queue for '{}' "
                    "(library may be empty or all durations missing)".format(
                        channel.get("name", channel_id)))

            # Combo queue files are not written in 3.x — their state
            # (show_slot, tv_next_ep) is the authoritative source and was
            # already reset by _reset_combo_interleave_sources above.
            # apply_combo_slot_starting_points ensures state is initialised.
            for combo_ch in reset_combos:
                try:
                    self._apply_combo_slot_starting_points(combo_ch)
                    log("[ChannelManager] _pregenerate_queue_safe: "
                        "combo state initialised for '{}'".format(
                            combo_ch.get("name", combo_ch["id"])))
                except Exception as combo_exc:
                    log("[ChannelManager] _pregenerate_queue_safe: combo "
                        "state init error for '{}': {}".format(
                            combo_ch.get("name", combo_ch["id"]), combo_exc))

        except Exception as exc:
            log("[ChannelManager] _pregenerate_queue_safe error for '{}': "
                "{}".format(channel.get("name", channel_id), exc))

    # -------------------------------------------------------------------------
    # Phase 5 public API additions
    # -------------------------------------------------------------------------

    def clear_missing_durations(self, channel_id: str) -> None:
        """Clear the per-channel missing_durations list from state.json.

        Does NOT touch missing_durations.txt — that is the permanent record.
        Ported from 2.x channel_manager.py.
        """
        state_key = "{}:missing_durations".format(channel_id)
        try:
            if state_key in self._state:
                del self._state[state_key]
                self._deleted_state_keys.add(state_key)
                self._save_state()
        except Exception as exc:
            log("[ChannelManager] clear_missing_durations error: {}".format(exc),
                level=xbmc.LOGWARNING)

    def capture_folder_duration(self, channel_id: str,
                                 file_path: str,
                                 duration_seconds: int) -> None:
        """Write a companion NFO for a folder item and update its queue entry.

        Called by service.py after a folder item finishes playing so that
        subsequent queue builds use the real duration instead of the default.
        1. Writes companion NFO via duration_cache.
        2. Updates the matching item in the channel queue file in place.
        Ported from 2.x channel_manager.py.
        """
        from resources.lib.utils.duration_cache import (
            write_companion_nfo as _write_nfo)

        if not file_path or duration_seconds <= 0:
            return

        log("[ChannelManager] capture_folder_duration: {}s for {}".format(
            duration_seconds, file_path))

        _write_nfo(file_path, duration_seconds)

        try:
            queue = self.get_channel_queue(channel_id)
            if not queue:
                return
            changed = False
            for item in queue:
                if item.get("file") == file_path and item.get("duration_is_default"):
                    item["duration"]          = duration_seconds
                    item["duration_is_default"] = False
                    changed = True
            if changed:
                self.write_channel_queue(channel_id, queue)
                log("[ChannelManager] capture_folder_duration: "
                    "updated queue entry for {}".format(file_path))
        except Exception as exc:
            log("[ChannelManager] capture_folder_duration queue update "
                "error: {}".format(exc), level=xbmc.LOGWARNING)

    def reset_channel(self, channel_id: str) -> bool:
        """Reset a channel to a fresh start and rebuild its queue.

        Clears the cursor (and folder cycle), resume points and queue, then
        builds a new queue.  Shared by the Reset Channel context action and
        the interleave source-removal reset.  Returns False if the channel
        does not exist.
        """
        if not self.get_channel(channel_id):
            return False
        # Interleaved shows keep their place: note where each one is up to
        # before the queue is cleared.
        progress = self.capture_interleave_progress(channel_id)
        self.clear_cursor(channel_id)
        self.clear_channel_resume_points(channel_id)
        self.write_channel_queue(channel_id, [])
        self.reload_channels()
        channel = self.get_channel(channel_id)
        if channel:
            self.begin_interleave_resume(progress)
            try:
                self.write_channel_queue(
                    channel_id, self.build_channel_queue(channel))
            finally:
                self.end_interleave_resume()
        return True

    def clear_channel_resume_points(self, channel_id: str) -> None:
        """Remove all resume-position entries for a channel from state.json.
        Called when recycle/randomize/type changes make saved positions invalid.
        spec §21 (service.py onPlayBackStopped USER path)
        """
        try:
            prefix   = "resume:{}:".format(channel_id)
            mem_keys = [k for k in self._state if k.startswith(prefix)]
            for k in mem_keys:
                del self._state[k]
            self._deleted_state_keys.update(mem_keys)
            # Flush so disk stays clean
            if mem_keys:
                self._save_state()
                log("[ChannelManager] Cleared {} resume point(s) "
                    "for channel {}".format(len(mem_keys), channel_id[:8]))
        except Exception as e:
            log("[ChannelManager] clear_channel_resume_points error: "
                "{}".format(e))

    def remove_stale_resume_points(self, only_channel: Optional[str] = None) -> int:
        """Remove resume points of episodes that are no longer in their
        channel's queue, and resume points of channels that no longer exist.
        Returns the number removed.

        A resume point is cleared when its episode finishes, is skipped or is
        popped, but an episode can also leave the queue another way (Set
        Start, an edit, a lost update on state.json) and its point stayed
        for good (Real Crime, 10/24).  A channel whose queue cannot be read,
        or is empty, is left alone, and nothing is done when the channel list
        could not be read.  only_channel limits the check to one channel.
        """
        if not self._channels or not self._channels_ok:
            return 0
        if not self._ensure_state():
            return 0
        live = {c["id"] for c in self._channels}
        by_channel: dict = {}
        for key in self._state:
            if not key.startswith("resume:"):
                continue
            parts = key.split(":", 2)           # resume : <channel> : <file>
            if len(parts) != 3 or parts[2].startswith("file:"):
                continue
            by_channel.setdefault(parts[1], []).append((key, parts[2]))
        stale = []
        for cid, entries in by_channel.items():
            if only_channel and cid != only_channel:
                continue
            if cid not in live:
                stale.extend(k for k, _ in entries)
                continue
            queue = self.read_channel_queue(cid)
            if not queue:
                continue
            queued = {it.get("file", "") for it in queue}
            stale.extend(k for k, f in entries if f not in queued)
        if not stale:
            return 0
        for key in stale:
            log("[ChannelManager] removed stale resume point {}".format(key))
            self._state.pop(key, None)
        self._deleted_state_keys.update(stale)
        self._save_state()
        return len(stale)

    def reset_show_to_start(self, channel_id: str, show_id: int) -> bool:
        """Reset one show to its first episode (spec TC-30.17).
        Thin wrapper over set_show_start().
        """
        return self.set_show_start(channel_id, show_id, None)

    def set_show_start(self, channel_id: str, show_id: int,
                       start_episode_id: Optional[int] = None) -> bool:
        """Make a show's next-to-play episode ``start_episode_id`` (or its
        first episode when None) and splice the existing queue in place, so
        other shows' queue positions are never disturbed.

          1. Load the existing queue as-is.
          2. Replace every non-interleaved slot belonging to this show with
             the next playable episodes starting at the chosen episode, built
             via normalize_ep so all queue fields (show_id, tvshowtitle,
             duration, _span, ...) are present. Episodes with no duration are
             logged and skipped. Running past the last episode wraps to the
             first; if the show has fewer playable episodes than slots, the
             extra slots are dropped rather than duplicated.
          3. Write the queue back.
          4. Set the cursor so the next 1-for-1 replacement continues after
             the last spliced episode, and set the show-state pointer.

        Returns False if the show has no episodes or ``start_episode_id`` is
        not among them. Used by Reset Show and by the Edit Channel wizard's
        Select Starting Episodes.
        """
        channel    = self.get_channel(channel_id)
        show_entry = None
        if channel:
            show_entry = next(
                (s for s in channel.get("shows", [])
                 if int(s.get("tvshowid", -1)) == int(show_id)), None)

        episodes = (self.get_available_episodes(show_entry) if show_entry
                    else self.library.get_episodes_for_show(show_id))
        if not episodes:
            return False

        # The queue is spliced below.  One that cannot be read right now is
        # not an empty one: nothing is changed.
        queue = self.read_channel_queue(channel_id)
        if queue is None:
            log("[ChannelManager] set_show_start: queue of channel {} cannot "
                "be read - nothing changed".format(channel_id[:8]),
                level=xbmc.LOGWARNING)
            return False

        start_idx = 0
        if start_episode_id is not None:
            start_idx = next(
                (i for i, e in enumerate(episodes)
                 if e["episodeid"] == start_episode_id), None)
            if start_idx is None:
                log("[ChannelManager] set_show_start: episodeid {} not "
                    "found for show {} in channel {}".format(
                        start_episode_id, show_id, channel_id[:8]))
                return False

        # ── 1. Splice the queue ──────────────────────────────────────────────
        from resources.lib.utils.multi_episode import (
            count_episode_span as _count_span,
            span_episode_ids   as _span_ids_fn,
        )

        sid_str        = str(show_id)
        show_randomize = (show_entry.get("randomize",
                                         channel.get("randomize", False))
                          if (show_entry and channel) else False)
        cursor         = self.get_cursor(channel_id)
        cursor.get("ep_pos",    {}).pop(sid_str, None)
        cursor.get("ep_played", {}).pop(sid_str, None)
        cursor.get("slot_owed", {}).pop(sid_str, None)
        pos    = start_idx   # index of the next un-queued episode
        placed = set()       # episode ids already spliced in this pass

        if queue:
            new_queue = []
            spliced   = 0
            for item in queue:
                item_sid = item.get("show_id") or item.get("_show_id") or -1
                if item.get("_interleaved") or int(item_sid) != int(show_id):
                    new_queue.append(item)
                    continue

                # Fetch the next playable episode, normalised exactly as the
                # normal build path does so every queue field is present.
                norm  = None
                tries = 0
                while norm is None and tries < len(episodes):
                    if pos >= len(episodes):
                        pos = 0                       # recycle
                    ep   = episodes[pos]
                    span = _count_span(ep)
                    tries += 1
                    if ep["episodeid"] in placed:
                        break                         # whole show used
                    norm = _normalize_ep_fn(ep, channel_id, int(show_id),
                                            all_episodes_for_show=episodes,
                                            default_seconds=self._default_episode_seconds())
                    self._note_default_length(channel_id, ep, norm)
                    if norm is None:
                        self.record_missing_duration(channel_id, ep, "no_nfo")
                    else:
                        for eid in _span_ids_fn(ep, episodes):
                            placed.add(eid)
                            if show_randomize:
                                played = cursor["ep_played"].setdefault(
                                    sid_str, [])
                                if eid not in played:
                                    played.append(eid)
                    pos += span

                if norm is None:
                    continue    # more slots than playable episodes — drop

                for key in ("_schedule_id", "_silent"):
                    if key in item:
                        norm[key] = item[key]
                new_queue.append(norm)
                spliced += 1

            self.write_channel_queue(channel_id, new_queue)
            log("[ChannelManager] set_show_start: spliced {} slot(s) for "
                "show {} in channel {} (start index {})".format(
                    spliced, show_id, channel_id[:8], start_idx))

        # Replacements continue AFTER the last spliced episode.
        if not show_randomize:
            cursor["ep_pos"][sid_str] = pos
        self.set_cursor(channel_id, cursor)
        # Episodes the splice dropped from the queue keep no resume point.
        self.remove_stale_resume_points(channel_id)

        # ── 2. Set show-state pointer ────────────────────────────────────────
        start_ep = episodes[start_idx]
        self.save_show_state(channel_id, show_id, {
            "next_episode_id": start_ep["episodeid"],
            "season":          start_ep.get("season",  1),
            "episode":         start_ep.get("episode", 1),
            "played_ids":      [],
        })

        return True

    def _regenerate_tv_interleave(self, channel: dict,
                                  start_cursor: dict) -> None:
        """Rebuild a TV queue with interleave from start_cursor.

        Same plan and weave as _build_fresh_tv_queue.  Called by
        regenerate_queue after an interleave change.
        """
        channel_id = channel["id"]
        reset_combos = self._reset_combo_interleave_sources(channel)
        items, cursor, weave_seed = self._build_planned_tv_items(
            channel, int(channel.get("queue_size",
                    self._default_queue_size())), start_cursor)
        self.set_cursor(channel_id, cursor)
        from resources.lib.channels.interleave import apply_interleave_list
        new_queue = apply_interleave_list(
            items, channel, self._load_foreign_items, self.get_channel,
            seed=weave_seed)
        log("[ChannelManager] regenerate_queue: rebuilt {} primary + "
            "interleave -> {} total".format(len(items), len(new_queue)))
        self.write_channel_queue(channel_id, new_queue)
        self._sync_combo_state_from_queue(new_queue, channel)
        for combo_ch in reset_combos:
            try:
                self._apply_combo_slot_starting_points(combo_ch)
            except Exception as combo_exc:
                log("[ChannelManager] regenerate_queue: combo state init "
                    "error for '{}': {}".format(
                        combo_ch.get("name", combo_ch["id"]), combo_exc))

    def capture_combo_progress(self, channel_id: str) -> dict:
        """Where each sequential Combo Block TV show is up to in a host queue.

        Returns {tv_next_ep state key: episode id}: the first queued
        (next-to-play) episode of each sequential show of each TV slot of
        each Combo Block woven into *channel_id*.  Randomised shows are
        skipped (they have no fixed next episode).  A show whose queued
        episodes are not in order (it was random on the last build) or that
        has nothing queued gets the slot's starting point for it; a show
        with neither is left out and starts at its first episode.
        """
        from resources.lib.channels.interleave import get_sources
        channel = self.get_channel(channel_id)
        if not channel:
            return {}
        queue = self.get_channel_queue(channel_id)
        progress: dict = {}
        for source in get_sources(channel):
            combo = self.get_channel(source["channel_id"])
            if not combo or combo.get("channel_type") != "combo":
                continue
            for slot in combo.get("slots", []):
                if slot.get("source_type") != "tv":
                    continue
                slot_id = slot.get("slot_id", "")
                for show in slot.get("shows", []):
                    if show.get("randomize", True):
                        continue
                    sid = show.get("tvshowid")
                    key = "combo:{}:slot:{}:show:{}:tv_next_ep".format(
                        combo["id"], slot_id, sid)
                    queued = [i for i in queue
                              if i.get("_combo_slot") == slot_id
                              and i.get("show_id") == sid
                              and i.get("episodeid") is not None]
                    start = None
                    if queued and self._queued_in_order(show, queued):
                        start = queued[0]["episodeid"]
                    else:
                        # Nothing queued, or the queued episodes were drawn
                        # at random (the show was random on the last build):
                        # the show's own starting point applies, if it has one.
                        sp = (slot.get("starting_points") or {}).get(str(sid))
                        if sp and sp.get("episodeid") is not None:
                            start = sp["episodeid"]
                    if start is not None:
                        progress[key] = start
        return progress

    def _queued_in_order(self, show: dict, queued: list) -> bool:
        """True when *queued* (a show's queued items, in queue order) follow
        each other in the show's own episode order, as a sequential show's
        do.  A single queued item cannot show a pattern and counts as in
        order.  Items drawn at random do not follow each other."""
        if len(queued) < 2:
            return True
        ids = [e["episodeid"] for e in self.get_available_episodes(show)]
        if not ids:
            return False
        pos = {ep: n for n, ep in enumerate(ids)}
        places = [pos.get(i["episodeid"]) for i in queued]
        if None in places:
            return False
        return all((b - a) % len(ids) == 1 for a, b in zip(places, places[1:]))

    def rebuild_keep_places(self, channel_id: str) -> bool:
        """Rebuild a channel's queue so that what is woven into it is
        brought up to date (an edited Combo Block, for example) while every
        show keeps its place.

        The channel's own shows continue from the head of the queue, the
        interleaved TV shows and the Combo Block shows continue at the
        episode that was next to play.  Nothing is reset: resume points are
        kept.  Shows that were added to a Combo Block since start at their
        beginning.  A Combo slot that takes turns, or plays a unit of
        several shows, starts its rotation again from its first show.

        Returns False, changing nothing, when the channel does not exist, has
        nothing woven into it, or its queue cannot be read right now.
        """
        channel = self.get_channel(channel_id)
        if (not channel or channel.get("channel_type") == "combo"
                or not channel.get("interleave")):
            return False
        if self.read_channel_queue(channel_id) is None:
            return False
        self._combo_resume = self.capture_combo_progress(channel_id)
        try:
            self.regenerate_queue(channel_id)
        finally:
            self._combo_resume = {}
        return True

    def regenerate_queue(self, channel_id: str) -> None:
        """Rebuild the queue after an interleave change, keeping each
        interleaved TV show at the episode it had reached."""
        progress = self.capture_interleave_progress(channel_id)
        self.begin_interleave_resume(progress)
        try:
            self._regenerate_queue_body(channel_id)
        finally:
            self.end_interleave_resume()

    def _regenerate_queue_body(self, channel_id: str) -> None:
        """Rebuild the queue after an interleave change.
        Strips existing interleaved items from the current queue and
        re-weaves with the updated interleave config. Falls back to a
        full rebuild if no usable queue exists.
        spec §10.2
        """
        import xbmcvfs as _xbmcvfs

        channel = self.get_channel(channel_id)
        if not channel:
            return

        log("[ChannelManager] regenerate_queue for '{}'".format(
            channel.get("name", channel_id)))

        # A queue that cannot be read right now is not an empty queue:
        # nothing is changed (the next interleave change tries again).
        existing_queue = self.read_channel_queue(channel_id)
        if existing_queue is None:
            log("[ChannelManager] regenerate_queue: queue of '{}' cannot be "
                "read - not rebuilt".format(channel.get("name", channel_id)),
                level=xbmc.LOGWARNING)
            return
        interleave_cfg = channel.get("interleave")

        if existing_queue:
            # Strip previously-interleaved items, keep primary items
            primary = [item for item in existing_queue
                       if not item.get("_interleaved")]
            if primary:
                if (interleave_cfg
                        and channel.get("channel_type") == "tv"
                        and channel.get("playback_mode") != "serial"):
                    # TV: rebuild the primary items from the head of the
                    # queue through the same cycle planner as a new queue,
                    # so queue_size and the cycle end are honoured.
                    rewound = self._rewind_tv_cursor(channel, primary)
                    if rewound is not None:
                        self._regenerate_tv_interleave(channel, rewound)
                        return
                    log("[ChannelManager] regenerate_queue: cannot rewind "
                        "cursor — re-weaving existing items")
                if interleave_cfg:
                    from resources.lib.channels.interleave import (
                        apply_interleave_list)
                    # Reset combo episode pointers before weaving so the
                    # interleave starts from episode 1, not wherever a
                    # previous build left the pointer.
                    reset_combos = self._reset_combo_interleave_sources(channel)
                    weave_seed = None
                    if channel.get("channel_type") in ("movies", "folder"):
                        primary, weave_seed = self.extend_primary_to_cycle(
                            channel, primary)
                    new_queue = apply_interleave_list(
                        primary, channel,
                        self._load_foreign_items,
                        self.get_channel,
                        seed=weave_seed)
                    log("[ChannelManager] regenerate_queue: wove {} primary "
                        "+ interleave → {} total".format(
                            len(primary), len(new_queue)))
                    self.write_channel_queue(channel_id, new_queue)
                    # Sync combo slot tv_next_ep to the episode after the last
                    # one actually woven into the queue (not all fetched items).
                    self._sync_combo_state_from_queue(new_queue, channel)
                    # Combo queue files are not written in 3.x.
                    # State (show_slot, tv_next_ep) was reset by
                    # _reset_combo_interleave_sources; just initialise
                    # starting points so the next build_one_slot call
                    # starts at the correct episode.
                    for combo_ch in reset_combos:
                        try:
                            self._apply_combo_slot_starting_points(combo_ch)
                        except Exception as combo_exc:
                            log("[ChannelManager] regenerate_queue: combo "
                                "state init error for '{}': {}".format(
                                    combo_ch.get("name", combo_ch["id"]),
                                    combo_exc))
                else:
                    if (channel.get("channel_type") == "tv"
                            and channel.get("playback_mode") != "serial"):
                        # queue_size counted the interleaved items, so the
                        # primary items left over are fewer than queue_size.
                        # Rebuild them from the head of the queue to the full
                        # size, as the interleave-on path does (3.1.130).
                        rewound = self._rewind_tv_cursor(channel, primary)
                        if rewound is not None:
                            self._regenerate_tv_interleave(channel, rewound)
                            return
                        log("[ChannelManager] regenerate_queue: cannot rewind "
                            "cursor — keeping the existing primary items")
                    new_queue = primary
                    log("[ChannelManager] regenerate_queue: interleave "
                        "removed, {} primary items".format(len(new_queue)))
                    self.write_channel_queue(channel_id, new_queue)
                return

        # No usable queue — full rebuild
        log("[ChannelManager] regenerate_queue: no existing queue, "
            "full rebuild")
        is_tv = channel.get("channel_type", "tv") == "tv"
        if not is_tv:
            self.clear_cursor(channel_id)
        q_path = self._queue_file_path(channel_id)
        if _xbmcvfs.exists(q_path):
            _xbmcvfs.delete(q_path)
        # A TV channel keeps the places its shows have reached.
        self._pregenerate_queue_safe(channel, keep_places=True if is_tv
                                     else None)

    # ------------------------------------------------------------------
    # Automatic library upkeep  (3.1.156)
    # ------------------------------------------------------------------
    # State key "library_upkeep" in state.json:
    #   date, done, tries, next_try, built_date, claim
    # One device per day does the job (claim); the others see "done" and
    # reload when local_library.json changes (LibraryClient).

    UPKEEP_KEY           = "library_upkeep"
    UPKEEP_CLAIM_SECONDS = 7200
    UPKEEP_CLAIM_SETTLE_MS = 1500
    UPKEEP_RETRY_SECONDS = 3600
    UPKEEP_MAX_TRIES     = 3
    # A local_library.json rebuilt this recently (by the hourly rebuild after
    # a Kodi scan on the PVR PC, say) is not rebuilt again by the daily job.
    UPKEEP_FRESH_SECONDS = 3600
    UPKEEP_FRESH_SKEW    = 300     # a file this far "in the future" is clock skew

    def library_upkeep_enabled(self) -> bool:
        """True when the daily library upkeep setting is on (default off)."""
        return self.addon.getSetting("library_upkeep") == "true"

    def _upkeep_clock(self):
        """(hour, minute) of the daily run; 04:00 when unset or invalid."""
        raw = str(self.addon.getSetting("library_upkeep_time") or "").strip()
        try:
            hh, mm = raw.split(":")
            hh, mm = int(hh), int(mm)
            if 0 <= hh < 24 and 0 <= mm < 60:
                return hh, mm
        except ValueError:
            pass
        return 4, 0

    def _upkeep_state(self, today: str) -> dict:
        st = self.read_state_key(self.UPKEEP_KEY)
        st = dict(st) if isinstance(st, dict) else {}
        if st.get("date") != today:
            # A new day starts clean (the library is rebuilt again).
            st = {"date": today, "done": False, "tries": 0, "next_try": 0}
        return st

    def library_upkeep_due(self, now=None) -> bool:
        """True when the daily upkeep should run now: the setting is on, the
        run time has passed, today is not done and no retry is waiting."""
        import datetime as _dt
        if not self.library_upkeep_enabled():
            return False
        now = time.time() if now is None else now
        day = _dt.datetime.fromtimestamp(now)
        hh, mm = self._upkeep_clock()
        if (day.hour, day.minute) < (hh, mm):
            return False
        st = self._upkeep_state(day.date().isoformat())
        return not st["done"] and now >= float(st.get("next_try") or 0)

    def claim_library_upkeep(self, now=None) -> bool:
        """Claim today's upkeep for this device (see claim_block_expiry for
        the pattern).  False when it is done today, a retry is waiting,
        another device holds a live claim, or the claim is lost."""
        import datetime as _dt
        now = time.time() if now is None else now
        today = _dt.datetime.fromtimestamp(now).date().isoformat()
        st = self._upkeep_state(today)
        if st["done"] or now < float(st.get("next_try") or 0):
            return False
        me = self.get_device_id()
        held = st.get("claim")
        if isinstance(held, dict) and held.get("device_id") != me:
            try:
                age = abs(now - float(held.get("at", 0)))
            except (TypeError, ValueError):
                age = self.UPKEEP_CLAIM_SECONDS + 1
            if age <= self.UPKEEP_CLAIM_SECONDS:
                return False
        token = uuid.uuid4().hex
        st["claim"] = {"device_id": me, "device_name": self.get_device_label(),
                       "at": now, "token": token}
        self.write_state_key(self.UPKEEP_KEY, st)
        xbmc.sleep(self.UPKEEP_CLAIM_SETTLE_MS)
        back = self.read_state_key(self.UPKEEP_KEY) or {}
        return (isinstance(back.get("claim"), dict)
                and back["claim"].get("token") == token)

    def upkeep_busy_channels(self) -> set:
        """Ids of the channels in use: held by another device or played on
        this one.  The upkeep leaves their queues alone."""
        busy = set()
        for ch in self.get_all_channels():
            cid = ch.get("id", "")
            if cid and self.channel_lock_holder(cid):
                busy.add(cid)
        own = self.owned_lock_channel()
        if own:
            busy.add(own)
        return busy

    def run_library_upkeep(self, now=None) -> dict:
        """The daily job, after claim_library_upkeep() succeeded.

        1. rebuild local_library.json (once per day; not when it was
           rebuilt within the last hour),
        2. clear the in-memory library lists,
        3. repair_queue_paths and repair_missing_shows for every channel not
           in use.
        A rebuild that fails, or channels left out because they are in use,
        schedule a retry in an hour; after three tries the day is closed.
        Returns {"built": bool, "skipped": [channel ids], "done": bool}.
        """
        import datetime as _dt
        now = time.time() if now is None else now
        today = _dt.datetime.fromtimestamp(now).date().isoformat()
        st = self._upkeep_state(today)
        st.pop("claim", None)
        journal.record("upkeep_start", tries=st["tries"])
        log("[ChannelManager] library upkeep: start (try {})".format(
            st["tries"] + 1))
        built = st.get("built_date") == today
        skipped = []
        paths = shows = None
        rebuilt = False
        if not built:
            age = self.library.local_cache_age_days() * 86400.0
            if -self.UPKEEP_FRESH_SKEW <= age <= self.UPKEEP_FRESH_SECONDS:
                # Already rebuilt within the last hour: use it as it is.
                built = True
                st["built_date"] = today
                log("[ChannelManager] library upkeep: local_library.json "
                    "was rebuilt {} min ago - not rebuilt again".format(
                        int(max(age, 0) // 60)))
            else:
                built = bool(self.library.build_local_cache(
                    progress_callback=None))
                rebuilt = built
                if built:
                    st["built_date"] = today
        if built:
            self.library.invalidate_cache()
            skipped = sorted(self.upkeep_busy_channels())
            paths = self.repair_queue_paths(skip=skipped)
            shows = self.repair_missing_shows(skip=skipped)
        st["tries"] = st["tries"] + 1
        retry = (not built) or bool(skipped)
        st["done"] = (not retry) or st["tries"] >= self.UPKEEP_MAX_TRIES
        st["next_try"] = 0 if st["done"] else now + self.UPKEEP_RETRY_SECONDS
        self.write_state_key(self.UPKEEP_KEY, st)
        if retry:
            journal.record("upkeep_skipped", built=built, channels=skipped,
                           tries=st["tries"], done=st["done"])
            log("[ChannelManager] library upkeep: {} - {}".format(
                "library rebuild failed" if not built
                else "{} channel(s) in use left out".format(len(skipped)),
                "day closed" if st["done"] else "retry in an hour"))
        if built:
            journal.record("upkeep_done", paths=paths, shows=shows,
                           skipped=len(skipped), done=st["done"],
                           rebuilt=rebuilt)
            log("[ChannelManager] library upkeep: done {} {}".format(
                paths, shows))
        return {"built": built, "skipped": skipped, "done": st["done"]}

    def repair_queue_paths(self, skip=None) -> dict:
        """Bring every TV queue entry up to date with the Kodi library.

        For each queued episode, look it up in the library (by episode ID,
        then by show + season + episode) and rewrite its file path, title,
        IDs and span from the library.  Queue order, cursors, carousel state
        and the entries themselves stay in place; a resume position saved
        under the old path moves to the new one.  An episode the library no
        longer has is left untouched and counted as not found.  Movies,
        folders and audio are not checked.  The in-memory library lists are
        cleared first (in the service too) so the lookup is current.
        ``skip`` is an optional set of channel ids left out entirely (the
        automatic library upkeep skips channels in use).
        Returns {"fixed": n, "not_found": n, "unchanged": n}.
        """
        result = {"fixed": 0, "not_found": 0, "unchanged": 0}
        skip = set(skip or ())
        self.library.invalidate_cache()

        # Load each show's episodes before touching any queue, so the
        # read-patch-write of a queue file below is short.
        lookups = {}
        for ch in self.get_all_channels():
            if ch.get("id", "") in skip:
                continue
            for item in self.get_channel_queue(ch.get("id", "")):
                show_id = self._queue_item_show_id(item)
                if show_id and show_id not in lookups:
                    episodes = self.library.get_episodes_for_show(show_id)
                    lookups[show_id] = (
                        episodes,
                        {e.get("episodeid"): e for e in episodes},
                        {(e.get("season"), e.get("episode")): e
                         for e in episodes})

        for ch in self.get_all_channels():
            channel_id = ch.get("id", "")
            if channel_id in skip:
                continue
            queue      = self.get_channel_queue(channel_id)
            touched    = False
            for item in queue:
                show_id = self._queue_item_show_id(item)
                if not show_id or show_id not in lookups:
                    continue
                outcome = self._repair_queue_item(
                    channel_id, item, lookups[show_id])
                result[outcome] += 1
                touched = touched or outcome == "fixed"
            if touched:
                self.write_channel_queue(channel_id, queue)

        log("[ChannelManager] repair_queue_paths: {} fixed, {} not found, "
            "{} unchanged".format(result["fixed"], result["not_found"],
                                  result["unchanged"]))
        return result

    def repair_missing_shows(self, skip=None) -> dict:
        """Put back any show that has dropped out of a TV channel's queue.

        A round-robin TV queue holds at least one episode of every show on
        the channel.  If a show has none (it lost its place earlier, for
        example when one of its episodes had no readable duration), that
        show's next episode is added after the last regular episode in the
        queue, ahead of any trailing interleaved items.  The show's own
        cursor moves on as for any other pick.  Queue order, other cursors,
        carousel state and resume points are not touched.  Serial, movie,
        folder, audio, party and combo channels are not checked.

        The queue is read again just before it is written, so a second
        device repairing the same channel at the same moment does not add
        the same show twice.  ``skip`` is an optional set of channel ids
        left out (channels in use, for the automatic library upkeep).
        Returns {"added": n, "no_episode": n}.
        """
        result = {"added": 0, "no_episode": 0}
        skip = set(skip or ())
        for channel in list(self.get_all_channels()):
            if channel.get("id", "") in skip:
                continue
            if (channel.get("channel_type", "tv") != "tv"
                    or channel.get("playback_mode") == "serial"
                    or not channel.get("shows")):
                continue
            channel_id = channel.get("id", "")
            queue      = self.get_channel_queue(channel_id)
            if not queue:
                continue
            missing = self._shows_missing_from_queue(channel, queue)
            if not missing:
                continue

            # A copy: the positions only change if the queue is written.
            cursor = copy.deepcopy(self.get_cursor(channel_id))
            added  = []
            for show in missing:
                episodes = self.get_available_episodes(show)
                ep = None
                if episodes:
                    ep = self._pick_one_ep_no_slot_advance(
                        show, str(show["tvshowid"]), episodes, cursor,
                        channel.get("randomize", False),
                        channel.get("recycle", True),
                        channel_id=channel_id)
                if ep is None:
                    result["no_episode"] += 1
                    log("[ChannelManager] repair_missing_shows: '{}' on "
                        "'{}' has no playable episode".format(
                            show.get("title", ""), channel.get("name", "")),
                        xbmc.LOGWARNING)
                    continue
                added.append((show, ep))
            if not added:
                continue

            # Read the queue again and keep only the shows still missing.
            # One that cannot be read now is left alone (never written back
            # as an empty queue).
            queue = self.read_channel_queue(channel_id)
            if not queue:
                continue
            missing = {s["tvshowid"]
                       for s in self._shows_missing_from_queue(channel, queue)}
            insert_at = len(queue)
            while (insert_at > 0
                   and queue[insert_at - 1].get("_interleaved")):
                insert_at -= 1
            for show, ep in added:
                if show["tvshowid"] not in missing:
                    continue
                queue.insert(insert_at, ep)
                insert_at += 1
                result["added"] += 1
                log("[ChannelManager] repair_missing_shows: added '{}' "
                    "S{:02d}E{:02d} to '{}'".format(
                        show.get("title", ""), ep.get("season", 0),
                        ep.get("episode", 0), channel.get("name", "")))
            self.write_channel_queue(channel_id, queue)
            self.set_cursor(channel_id, cursor)
        log("[ChannelManager] repair_missing_shows: {} added, {} with no "
            "playable episode".format(result["added"], result["no_episode"]))
        return result

    @staticmethod
    def _shows_missing_from_queue(channel: dict, queue: list) -> list:
        """Return the channel's shows that have no regular (non-interleaved)
        episode in queue."""
        present = set()
        for item in queue:
            if item.get("_interleaved"):
                continue
            show_id = item.get("_show_id") or item.get("show_id")
            if show_id:
                present.add(show_id)
        return [s for s in channel.get("shows", [])
                if s.get("tvshowid") not in present]

    @staticmethod
    def _queue_item_show_id(item) -> int:
        """Return the TV show ID of a queued episode, or 0 for any other
        kind of entry (movie, folder file, audio)."""
        if not isinstance(item, dict):
            return 0
        episode_id = item.get("episodeid")
        if not isinstance(episode_id, int) or episode_id <= 0:
            return 0
        return item.get("_show_id") or item.get("show_id") or 0

    def _repair_queue_item(self, channel_id: str, item: dict,
                           lookup: tuple) -> str:
        """Update one queued episode in place from the library.
        Returns "fixed", "unchanged" or "not_found"."""
        episodes, by_id, by_season_episode = lookup
        ep = by_id.get(item.get("episodeid")) or by_season_episode.get(
            (item.get("season"), item.get("episode")))
        if not ep or not ep.get("file"):
            log("[ChannelManager] repair_queue_paths: not in library: {} "
                "S{}E{} ({})".format(item.get("tvshowtitle", "?"),
                                     item.get("season"), item.get("episode"),
                                     item.get("file", "")),
                xbmc.LOGWARNING)
            return "not_found"

        fresh = {
            "episodeid": ep.get("episodeid"),
            "file":      ep["file"],
            "title":     ep.get("title", item.get("title", "")),
            "season":    ep.get("season", item.get("season")),
            "episode":   ep.get("episode", item.get("episode")),
        }
        if all(item.get(k) == v for k, v in fresh.items()):
            return "unchanged"

        old_file = item.get("file", "")
        item.update(fresh)
        item["_span"]     = self.get_episode_span(ep)
        item["_span_ids"] = self.get_span_episode_ids(ep, episodes)
        if old_file and old_file != fresh["file"]:
            saved = self.get_resume_position(channel_id, old_file)
            if saved:
                self.save_resume_position(
                    channel_id, fresh["file"], saved["position"])
                self.clear_resume_position(channel_id, old_file)
        log("[ChannelManager] repair_queue_paths: fixed {} S{}E{}: {}".format(
            item.get("tvshowtitle", "?"), fresh["season"], fresh["episode"],
            fresh["file"]))
        return "fixed"

    def skip_items_with_replacement(self, channel_id: str, queue: list,
                                    count: int) -> tuple:
        """Pop the first `count` items of `queue` and draw one replacement
        for each, appended to the tail (the 1-for-1 rule for skipped items).

        `queue` is changed in place and NOT written: the caller writes it.
        Resume points of the popped items are cleared.  Scheduled block items
        are popped with no replacement (they are foreign to the channel and do
        not repeat).  A combo slot item is replaced by one item of its own
        slot.  Everything else goes through get_one_replacement.

        Returns (replacements, block_items): the items appended to the tail,
        in order, and the popped scheduled block items, which the caller
        counts toward their block (counting saves state, so it must happen
        after the caller's own writes).
        Shared by service._handle_skip (Next button / playlist jump),
        reorder_queue_from_item (side panel) and the service's handling of an
        unplayable item.  spec §1.2, §7.4, §16.1
        """
        count = max(0, min(int(count), len(queue)))
        skipped = queue[:count]

        for item in skipped:
            f = item.get("file", "")
            if f:
                self.clear_resume_position(channel_id, f)

        from resources.lib.channels.combo import ComboQueueBuilder

        replacements = []
        block_items  = []
        for item in skipped:
            # _schedule_id takes precedence over _interleaved: combo-sourced
            # block items carry both.
            if item.get("_schedule_id"):
                block_items.append(item)
                continue
            consumed_cid = item.get("_channel_id") or item.get("channel_id", "")
            if self.is_combo_channel(consumed_cid):
                combo_ch = self.get_channel(consumed_cid)
                if not combo_ch:
                    continue
                consumed_slot_id = item.get("_combo_slot", "")
                slots = combo_ch.get("slots", [])
                slot_index = next(
                    (i for i, sl in enumerate(slots)
                     if sl.get("slot_id", "") == consumed_slot_id), None)
                if slot_index is None:
                    log("[ChannelManager] skip_items_with_replacement: "
                        "slot_id {} not found - no replacement".format(
                            consumed_slot_id[:8]), level=xbmc.LOGWARNING)
                    continue
                new_items = ComboQueueBuilder(self).build_one_slot(
                    combo_ch, slot_index, host_queue=queue)
                if new_items:
                    queue.extend(new_items)
                    replacements.extend(new_items)
                    log("[ChannelManager] skip_items_with_replacement: "
                        "replaced combo slot {} with '{}'".format(
                            slot_index, new_items[0].get("title", "?")))
            else:
                replacement = self.get_one_replacement(
                    channel_id, item, current_queue=queue)
                if replacement:
                    queue.append(replacement)
                    replacements.append(replacement)

        del queue[:count]
        return replacements, block_items

    def reorder_queue_from_item(self, channel_id: str,
                                queue_index: int) -> bool:
        """Make the item at queue_index the front of the queue by skipping
        every item in front of it: each is popped and one replacement is
        appended to the tail, exactly as for the Next button.  Nothing is
        rotated, so a show's episodes never end up out of order.
        Scheduled block items passed over are popped with no replacement and
        counted toward their block.
        Called by play_from_item (side panel click and standard list).
        Returns True on success.
        spec §16.1 (side panel Enter on right pane[N]), §7.4
        """
        queue = self.get_channel_queue(channel_id)
        if not queue:
            return False
        if queue_index <= 0 or queue_index >= len(queue):
            return False

        passed = [it.get("title", "?") for it in queue[:queue_index]]
        replacements, block_items = self.skip_items_with_replacement(
            channel_id, queue, queue_index)
        self.write_channel_queue(channel_id, queue)
        log("[ChannelManager] reorder_queue_from_item: channel={} skipped {} "
            "item(s) to index {} ({} replacement(s), {} block item(s)): {}"
            .format(channel_id, queue_index, queue_index, len(replacements),
                    len(block_items), ", ".join(passed)))

        # Bookkeeping for the passed-over block items, after the queue write
        # (counting saves state through this same manager).
        if block_items:
            from resources.lib.scheduler import ScheduleManager
            for it in block_items:
                try:
                    ScheduleManager().on_block_item_complete(
                        it["_schedule_id"], self)
                except Exception as exc:
                    log("[ChannelManager] reorder_queue_from_item: block "
                        "count error for '{}': {}".format(
                            it.get("title", "?"), exc),
                        level=xbmc.LOGWARNING)
        return True

    def update_now_playing(self, channel: dict, item: dict) -> None:
        """Update now_playing.json with the currently playing item.

        Called by service.py on every new episode start so the file stays
        current throughout playback — not just at channel start.
        Writes to local profile first, then copies to shared storage if
        configured.  spec §21, §24.
        """
        import time as _time
        import os   as _os

        channel_id = channel.get("id", "")
        profile    = xbmcvfs.translatePath(
            self.addon.getAddonInfo("profile"))

        data = {
            "active_channel_id": channel_id,
            "channel_name":      channel.get("name", ""),
            "title":             item.get("title",       ""),
            "tvshowtitle":       item.get("tvshowtitle", ""),
            "season":            item.get("season",      0),
            "episode":           item.get("episode",     0),
            "duration":          item.get("duration",    0),
            "start_time":        _time.time(),
        }

        import json as _json
        local_path = _os.path.join(profile, "now_playing.json")
        try:
            with xbmcvfs.File(local_path, "w") as f:
                f.write(_json.dumps(data, indent=2))
            log("[ChannelManager] update_now_playing: '{}' on '{}'".format(
                item.get("title", "?"), channel.get("name", "?")))
        except Exception as exc:
            log("[ChannelManager] update_now_playing error: {}".format(exc))
            return

        shared_path = self._resolve_path("now_playing.json")
        if shared_path != local_path:
            try:
                xbmcvfs.copy(local_path, shared_path)
            except Exception as exc:
                log("[ChannelManager] update_now_playing: shared copy "
                    "failed: {}".format(exc))
