# plugin.video.smartchannels
# service.py
#
# OWNS:   ALL playback callbacks, state advancement, queue replacement,
#         resume save/seek, combo unit tracker, tick loop (carousel + scheduler).
#
# Architecture:
#   SmartChannelsPlayer(xbmc.Player)  — receives ALL playback callbacks.
#   SmartChannelsMonitor(xbmc.Monitor) — tick loop and abort detection only.
#
# xbmc.Player subclass is REQUIRED for onPlayBackStarted, onPlayBackEnded,
# onPlayBackStopped, onAVStarted etc. xbmc.Monitor does NOT receive these.
#
# spec §21, §1.10, §7.3, §7.4
# Version: 3.0.0 Phase 1

from __future__ import annotations

import enum
import json
import os
import threading

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from resources.lib.channel_manager import ChannelManager
from resources.lib.carousel        import tick_carousel
from resources.lib.player          import SmartPlayer
from resources.lib.utils.channel_wait import (stop_waiting, waiting_entries)
from resources.lib.utils.logger    import log


# ---------------------------------------------------------------------------
# StopReason enum  (spec §1.10, §23)
# ---------------------------------------------------------------------------

class StopReason(enum.Enum):
    NATURAL    = "natural"
    USER       = "user"
    SKIP       = "skip"
    HARD_START = "hard_start"
    UNKNOWN    = "unknown"


# ---------------------------------------------------------------------------
# SmartChannelsPlayer — xbmc.Player subclass
# This is the ONLY class that receives playback callbacks.
# ---------------------------------------------------------------------------

class SmartChannelsPlayer(xbmc.Player):
    """Receives all Kodi playback callbacks. Owns all state advancement."""

    def __init__(self, addon: xbmcaddon.Addon):
        super().__init__()
        self.addon = addon

        # Active channel tracking — protected by _lock
        self._channel_id: str | None  = None
        self._channel:    dict | None = None
        self._queue:      list        = []
        self._queue_pos:  int         = 0
        self._lock = threading.Lock()

        # Stop reason — set BEFORE any programmatic stop (spec §1.10)
        self._stop_reason: StopReason = StopReason.UNKNOWN

        # Resume position tracking
        self._resume_pos:   float = 0.0
        self._poll_timer:   threading.Timer | None = None

        self._poll_interval = self._get_poll_interval()

        # Scheduled block tracking (spec §14).
        # _pending_block_channel: set by _tick_scheduler when fire_block()
        # writes block items to the front of the currently-playing channel's
        # queue file.  Consumed in onPlayBackEnded at the next natural item
        # boundary — triggers a start_channel() reload so Kodi picks up the
        # block items from disk and plays them before resuming normal content.
        # Ported from 2.x _pending_block_reload / _maybe_start_block_reload.
        self._pending_block_channel: dict | None = None
        # _block_count_last: (schedule_id, file) de-dupe guard so a single
        # block item is never counted twice even if onPlayBackEnded fires
        # for a skipped item.  Ported from 2.x _block_count_last / _count_block_item.
        self._block_count_last: tuple | None = None
        # Suppresses false skip detection on the onAVStarted callback
        # triggered by start_channel() during a block reload.
        self._block_reload_pending: bool = False
        # Consecutive 60 s ticks with nothing playing while this device still
        # holds a channel lock (3.1.109).  Two in a row release the lock.
        self._idle_lock_ticks: int = 0

        # Coming Up Next overlay state (spec §17.1)
        self._overlay_shown:   bool       = False  # True once shown for current episode
        self._pending_overlay: tuple | None = None  # (next_ep, settings) queued by poll

        # Logo overlay — instantiated once, lives for service lifetime (spec §17.2)
        from resources.lib.overlays.logo_overlay import SmartChannelsLogoOverlay
        self._logo_overlay = SmartChannelsLogoOverlay()

        log("[service] SmartChannelsPlayer initialised")

    def _get_poll_interval(self) -> int:
        """Read the position-poll interval from settings (seconds).

        Default 60 s.  User can increase for lower-powered devices or
        decrease for more precise resume accuracy.
        """
        try:
            return max(1, int(
                self.addon.getSetting("resume_poll_interval") or "60"))
        except (ValueError, TypeError):
            return 60

    def _reset_watched_if_enabled(self, episodeid: int,
                                   movieid: int) -> None:
        """Reset Kodi watched/playcount after natural episode completion.

        Only fires when the reset_watched setting is True.
        Never called for folder items, skipped items, or user stops.
        Ported from 2.x service.py.
        """
        try:
            if not self.addon.getSettingBool("reset_watched"):
                return
            from resources.lib.library import LibraryClient
            lib = LibraryClient(self.addon)
            if episodeid and episodeid > 0:
                lib.reset_watched_episode(episodeid)
            elif movieid and movieid > 0:
                lib.reset_watched_movie(movieid)
        except Exception as exc:
            log("[service] _reset_watched_if_enabled error: {}".format(exc),
                level=xbmc.LOGWARNING)

    def _maybe_start_block_reload(self) -> None:
        """Fire a start_channel() reload when a scheduled block is waiting.

        Called from onPlayBackEnded AFTER the finished item is processed.
        When fire_block() has prepended block items to the disk queue while
        the channel was playing, _pending_block_channel is set.

        The core problem: fire_block() writes block items to the DISK queue
        but self._queue (in memory) never sees them.  onPlayBackEnded checks
        self._queue[_queue_pos] for _schedule_id to decide whether to take the
        block path -- but the in-memory queue shows only regular content, so
        the block path is never taken and _do_replacement fires instead.

        Fix (ported from 2.x _update_queue_file + _maybe_start_block_reload):
          1. Read the disk queue -- it now starts with the block items.
          2. Sync self._queue and self._queue_pos to match disk (pos=0).
          3. Call start_channel() from a daemon thread so Kodi rebuilds its
             playlist from the disk queue, playing the block items first.

        Runs on a daemon thread because xbmc.Player().play() must never be
        called synchronously from a player callback -- it can deadlock on
        some platforms.
        """
        block_ch = self._pending_block_channel
        if block_ch is None:
            return

        # Never trigger off the back of a block item -- they chain naturally.
        if self._queue and self._queue_pos > 0:
            prev_item = self._queue[self._queue_pos - 1]
            if prev_item.get("_schedule_id"):
                return

        self._pending_block_channel = None
        self._block_count_last      = None  # fresh block session

        ch_id   = block_ch.get("id", "")
        ch_name = block_ch.get("name", ch_id)

        # Step 1 -- sync in-memory queue from disk so block items are visible.
        # fire_block() already wrote them to disk; we just need to load them.
        try:
            _mgr_sync = self._get_manager()
            _disk_q   = _mgr_sync.get_channel_queue(ch_id) if _mgr_sync else None
            if _disk_q:
                self._queue     = _disk_q
                self._queue_pos = 0
                log("[service] block reload: in-memory queue synced from disk "
                    "({} items, pos=0) -- block items now at front".format(
                        len(_disk_q)))
            else:
                log("[service] block reload: disk queue empty or unreadable -- "
                    "proceeding without sync", level=xbmc.LOGWARNING)
        except Exception as exc:
            log("[service] block reload: queue sync error: {}".format(exc),
                level=xbmc.LOGWARNING)

        log("[service] block reload: restarting '{}' to play "
            "scheduled block".format(ch_name))

        # Suppress false skip detection on the playlist-rebuild callback.
        self._block_reload_pending = True

        # Step 2 -- restart the channel off the callback thread.
        def _reload() -> None:
            try:
                from resources.lib.player import SmartPlayer as _Player
                _mgr   = self._get_manager()
                _fresh = (_mgr.get_channel(ch_id) if _mgr else None) or block_ch
                _Player(self.addon, _mgr).start_channel(_fresh)
            except Exception as exc:
                log("[service] block reload: start_channel error: {}".format(exc),
                    level=xbmc.LOGWARNING)

        threading.Thread(target=_reload, daemon=True).start()

    def _count_block_item(self, schedule_id: str, item: dict,
                          source: str) -> None:
        """Count a scheduled block item as consumed.

        De-duplicates consecutive calls for the same (schedule_id, file)
        so a skipped item that fires onPlayBackEnded is never double-counted.
        Ported from 2.x _count_block_item.
        """
        if not schedule_id:
            return
        identity = (schedule_id, item.get("file", ""))
        if self._block_count_last == identity:
            log("[service] block count: duplicate suppressed for "
                "schedule='{}' ({})".format(schedule_id[:8], source))
            return
        try:
            from resources.lib.scheduler import ScheduleManager
            ScheduleManager().on_block_item_complete(
                schedule_id, self._get_manager())
            self._block_count_last = identity
            log("[service] block count: counted via {} "
                "(schedule='{}')".format(source, schedule_id[:8]))
        except Exception as exc:
            log("[service] block count error ({}): {}".format(source, exc),
                level=xbmc.LOGWARNING)

    def _get_manager(self) -> ChannelManager:
        # Create a fresh ChannelManager on every call — same as 2.x.
        # A fresh instance always reads channels.json from disk so it
        # sees channels created after the service started. Never hold
        # a persistent instance — stale state causes channels created
        # after service startup to be invisible.
        return ChannelManager(self.addon)

    # =========================================================================
    # Playback callbacks — MUST be on xbmc.Player subclass
    # =========================================================================

    def onPlayBackStarted(self) -> None:
        # Keep this callback minimal — same pattern as 2.x.
        # Kodi fires onPlayBackStarted before the file is open so
        # getPlayingFile() is unreliable here.  All channel identification
        # and queue position tracking happens in onAVStarted where the
        # file handle is guaranteed to be ready.
        log("[service] onPlayBackStarted")
        self._stop_reason = StopReason.UNKNOWN

    def onAVStarted(self) -> None:
        # By the time onAVStarted fires, Kodi has the file open and
        # getPlayingFile() is reliable.  Identify the channel, set queue
        # state, handle skip detection, and start position polling here.
        # Run in a background thread — same pattern as 2.x — so we never
        # block the Kodi player callback thread.
        log("[service] onAVStarted")
        import threading
        threading.Thread(target=self._on_av_started_worker,
                         daemon=True).start()

    def _on_av_started_worker(self) -> None:
        try:
            channel_id = self._read_active_channel_id()
            if not channel_id:
                log("[service] onAVStarted: no active channel — ignoring")
                return

            channel = self._get_manager().get_channel(channel_id)
            if not channel:
                log("[service] onAVStarted: channel not found — ignoring")
                return

            now_playing_file = self._get_kodi_playing_file()

            with self._lock:
                channel_switched = (channel_id != self._channel_id)
                if channel_switched:
                    self._queue_pos = 0

                self._channel_id = channel_id
                self._channel    = channel
                # Use in-memory queue when channel unchanged — it was already
                # updated by _do_replacement_inner which holds the lock during
                # its queue write. Only read disk on switch or cold start.
                if channel_switched or not self._queue:
                    self._queue = self._get_manager().get_channel_queue(
                        channel_id)

                new_pos = 0
                if now_playing_file:
                    found = next(
                        (i for i, item in enumerate(self._queue)
                         if item.get("file") == now_playing_file), None)
                    if found is None:
                        log("[service] onAVStarted: playing file not in "
                            "queue — defaulting to 0")
                    else:
                        new_pos = found

                    log("[service] onAVStarted: file_pos={} _queue_pos={} "
                        "queue_len={}".format(
                        new_pos, self._queue_pos, len(self._queue)))
                    if new_pos > self._queue_pos:
                        if self._block_reload_pending:
                            # False skip — this is the Kodi playlist transition
                            # caused by start_channel() during a block reload.
                            # Block items at the front are real content, not
                            # skipped items.  Clear the flag and do not handle.
                            log("[service] onAVStarted: block reload transition "
                                "— skip detection suppressed (pos {} -> {})".format(
                                self._queue_pos, new_pos))
                            self._block_reload_pending = False
                        else:
                            log("[service] onAVStarted: skip detected "
                                "(was={} now={})".format(
                                self._queue_pos, new_pos))
                            # Release lock before calling _handle_skip which
                            # needs the lock itself to update shared state.
                            self._lock.release()
                            try:
                                self._handle_skip(channel_id, now_playing_file)
                            finally:
                                self._lock.acquire()
                            new_pos = 0
                else:
                    log("[service] onAVStarted: could not get playing file "
                        "— defaulting to queue[0]")

                self._queue_pos = new_pos
                snap_queue   = self._queue
                snap_channel = self._channel

            log("[service] onAVStarted: playing queue[{}] '{}'".format(
                new_pos,
                snap_queue[new_pos].get("title", "?") if snap_queue else "?"))

            # Update now_playing.json — outside lock (disk I/O)
            if snap_queue and new_pos < len(snap_queue):
                try:
                    self._get_manager().update_now_playing(
                        snap_channel, snap_queue[new_pos])
                except Exception as exc:
                    log("[service] onAVStarted: update_now_playing error: {}"
                        .format(exc), level=xbmc.LOGWARNING)

            # Execute any pending resume seek — outside lock (seekTime blocks)
            try:
                seek_to = self._get_manager().pop_pending_seek(channel_id)
                if seek_to is not None:
                    log("[service] onAVStarted: seeking to {:.0f}s".format(
                        seek_to))
                    xbmc.sleep(200)
                    self.seekTime(seek_to)
                    log("[service] onAVStarted: seek complete")
            except Exception as exc:
                log("[service] onAVStarted: seek error: {}".format(exc),
                    level=xbmc.LOGWARNING)

            self._start_poll(now_playing_file or "")

            # Reset overlay flag so Coming Up Next fires for this episode.
            self._overlay_shown = False

            # Logo overlay — show channel logo for configured duration.
            try:
                from resources.lib.overlays.logo_overlay import load_settings as _lo_s
                _lo_cfg = _lo_s()
                if _lo_cfg.get("enabled", False) and snap_channel:
                    _icon = self._get_manager().resolve_channel_icon(snap_channel)
                    if _icon and _icon != "DefaultVideoPlaylists.png":
                        self._logo_overlay.show(_icon, _lo_cfg)
                    else:
                        self._logo_overlay.hide_permanent()
            except Exception as _logo_err:
                log("[service] logo overlay error: {}".format(_logo_err),
                    level=xbmc.LOGWARNING)

        except Exception as exc:
            log("[service] _on_av_started_worker error: {}".format(exc),
                level=xbmc.LOGWARNING)

    def onPlayBackEnded(self) -> None:
        log("[service] onPlayBackEnded")
        self._stop_reason = StopReason.NATURAL
        self._stop_poll()

        if not self._channel_id:
            return

        if self._queue and self._queue_pos < len(self._queue):
            finished_item = self._queue[self._queue_pos]
            manager = self._get_manager()
            manager.clear_resume_position(
                self._channel_id, finished_item.get("file", ""))

            # Capture real duration for folder items that used the default.
            # getTotalTime() is still valid at onPlayBackEnded — Kodi
            # retains the file metadata until the next item starts.
            # Writes a companion NFO and updates the queue entry in place
            # so the next queue build uses the real duration. (spec §20)
            if (finished_item.get("is_folder_item")
                    and finished_item.get("duration_is_default", False)):
                try:
                    _real_dur = int(self.getTotalTime() or 0)
                    if _real_dur > 0:
                        _folder_file = finished_item.get("file", "")
                        _folder_cid  = (finished_item.get("_channel_id")
                                        or finished_item.get("channel_id")
                                        or self._channel_id)
                        manager.capture_folder_duration(
                            _folder_cid, _folder_file, _real_dur)
                        log("[service] folder duration captured: {}s for {}".format(
                            _real_dur, _folder_file))
                except Exception as _fde:
                    log("[service] folder duration capture error: {}".format(_fde),
                        level=xbmc.LOGWARNING)

            # Reset watched/playcount if the setting is enabled.
            # Called here on natural completion only — not on user stop or skip.
            # Ported from 2.x service.py.
            self._reset_watched_if_enabled(
                finished_item.get("episodeid", -1),
                finished_item.get("movieid", -1))
            # Record folder/combo-folder-slot items as played so that
            # no_repeat and recycle=False tracking work correctly.
            # For combo folder slots, the state key is the synthetic
            # "combo:{combo_id}:slot:{slot_id}" id stored in _channel_id.
            # For standalone folder channels, _channel_id == channel_id.
            if finished_item.get("is_folder_item"):
                file_path = finished_item.get("file", "")
                # Use _folder_state_id when present — this is the scoped
                # "combo:{id}:slot:{id}" key that FolderQueueBuilder uses
                # for state isolation of combo folder slots.  Falls back to
                # _channel_id for standalone folder channels.
                record_ch_id = (finished_item.get("_folder_state_id")
                                or finished_item.get("_channel_id")
                                or self._channel_id)
                if file_path:
                    try:
                        manager.record_folder_file_played(
                            record_ch_id, file_path)
                    except Exception as exc:
                        log("[service] record_folder_file_played error: {}"
                            .format(exc), level=xbmc.LOGWARNING)

        # ── Scheduled block item completion ──────────────────────────────
        # If the finished item belonged to a scheduled block, count it
        # and pop it from the disk queue (no 1-for-1 replacement — the source
        # channel already replenished itself when fire_block() ran).
        if (self._queue and
                self._queue_pos < len(self._queue) and
                self._queue[self._queue_pos].get("_schedule_id")):
            finished_sched = self._queue[self._queue_pos]
            self._count_block_item(
                finished_sched["_schedule_id"], finished_sched, "natural end")
            # Pop the block item from the disk queue so it cannot replay if
            # the user stops and restarts the channel mid-block.
            try:
                manager = self._get_manager()
                dq = manager.get_channel_queue(self._channel_id)
                if dq and dq[0].get("_schedule_id"):
                    dq.pop(0)
                    manager.write_channel_queue(self._channel_id, dq)
            except Exception as _bpop:
                log("[service] block item disk-pop error: {}".format(_bpop),
                    level=xbmc.LOGWARNING)
            self._queue_pos += 1
            # Check if a block reload is pending (more block items or the
            # block just ended and normal content resumes from disk).
            self._maybe_start_block_reload()
            return

        # If a scheduled block is waiting, skip the normal _do_replacement path
        # but still consume the finished episode and append its replacement on
        # disk.  fire_block() prepended N block items to the disk queue, so the
        # finished episode now sits at queue[N], not queue[0].  We trim it from
        # wherever it sits (matched by file path) and append one replacement so
        # the 1-for-1 invariant is maintained.  start_channel() then reloads
        # from the corrected disk queue: [block1, block2, ..., replacements...].
        if self._pending_block_channel is not None:
            self._consume_finished_before_block_reload()
            self._queue_pos += 1
            self._maybe_start_block_reload()
            return

        self._do_replacement()
        # Advance BEFORE onPlayBackStarted fires for the next item.
        # Without this, the skip detector in onPlayBackStarted sees
        # new_pos (1) > self._queue_pos (0) and fires a false skip,
        # consuming an extra replacement and advancing ep_pos one step
        # too far.
        self._queue_pos += 1
        # Trigger block reload if one was set by _tick_scheduler while this
        # item was playing (fires at the natural boundary — spec §14).
        self._maybe_start_block_reload()

    def onPlayBackStopped(self) -> None:
        log("[service] onPlayBackStopped (reason={})".format(self._stop_reason))
        self._stop_poll()
        self._logo_overlay.hide_permanent()
        self._pending_overlay = None
        self._overlay_shown   = False
        SmartPlayer.clear_now_playing(self.addon)

        if self._stop_reason == StopReason.HARD_START:
            self._stop_reason = StopReason.UNKNOWN
            return

        if self._stop_reason == StopReason.NATURAL:
            self._stop_reason = StopReason.UNKNOWN
            return

        self._stop_reason = StopReason.UNKNOWN

        if not self._channel_id:
            return

        if self._queue and self._queue_pos < len(self._queue):
            stopped_item = self._queue[self._queue_pos]
            if self._resume_pos > 10:
                self._get_manager().save_resume_position(
                    self._channel_id,
                    stopped_item.get("file", ""),
                    self._resume_pos)
                log("[service] onPlayBackStopped: saved resume @ {:.0f}s "
                    "for '{}'".format(
                        self._resume_pos, stopped_item.get("title", "")))

        stopped_channel = self._channel_id
        with self._lock:
            self._channel_id = None
            self._channel    = None
            self._queue      = []
            self._queue_pos  = 0

        # The user stopped the channel: free it for other devices at once.
        try:
            self._get_manager().release_channel_lock(stopped_channel)
        except Exception as exc:
            log("[service] release_channel_lock error: {}".format(exc),
                level=xbmc.LOGWARNING)

    def onPlayBackError(self) -> None:
        log("[service] onPlayBackError")
        self._stop_poll()
        self._stop_reason = StopReason.UNKNOWN

    # =========================================================================
    # 1-for-1 replacement  (spec §7.3)
    # =========================================================================

    def _consume_finished_before_block_reload(self) -> None:
        """Consume the just-finished episode from the disk queue before a
        block reload.

        fire_block() prepended N block items to the disk queue while the
        channel was playing.  The finished episode therefore sits at queue[N]
        (not queue[0]) on disk.  We need to remove it and append one
        replacement so the 1-for-1 invariant holds, before start_channel()
        reloads from disk.

        We identify the finished episode by file path using
        self._queue[self._queue_pos] — the in-memory queue still has the
        pre-block layout, so queue_pos correctly points to the finished item.
        """
        try:
            if not (self._queue and self._queue_pos < len(self._queue)):
                log("[service] _consume_finished_before_block_reload: "
                    "no finished item in in-memory queue — skipping")
                return

            finished_item = self._queue[self._queue_pos]
            finished_file = finished_item.get("file", "")

            manager = self._get_manager()
            queue   = manager.get_channel_queue(self._channel_id)
            if not queue:
                return

            # Find and remove the finished episode by file path from the
            # disk queue.  fire_block() prepended block items so the finished
            # episode is no longer at index 0.
            consumed_item = None
            removed_idx   = -1
            for i, item in enumerate(queue):
                if item.get("file", "") == finished_file:
                    consumed_item = queue.pop(i)
                    removed_idx   = i
                    break

            if consumed_item is None:
                log("[service] _consume_finished_before_block_reload: "
                    "finished item not found in disk queue — skipping replace",
                    level=xbmc.LOGWARNING)
                return

            log("[service] _consume_finished_before_block_reload: removed '{}' "
                "from disk queue at index {}".format(
                    consumed_item.get("title", "?"), removed_idx))

            # Append one replacement — same logic as normal 1-for-1.
            consumed_cid = (consumed_item.get("_channel_id")
                            or consumed_item.get("channel_id", ""))
            if manager.is_combo_channel(consumed_cid):
                self._handle_combo_slot(manager, consumed_item, queue)
            else:
                replacement = manager.get_one_replacement(
                    self._channel_id, consumed_item, current_queue=queue)
                if replacement:
                    queue.append(replacement)
                    log("[service] _consume_finished_before_block_reload: "
                        "appended '{}' as replacement".format(
                            replacement.get("title", "?")))

            manager.write_channel_queue(self._channel_id, queue)

        except Exception as exc:
            log("[service] _consume_finished_before_block_reload error: {}"
                .format(exc), level=xbmc.LOGWARNING)

    def _do_replacement(self) -> None:
        try:
            self._do_replacement_inner()
        except Exception as exc:
            import traceback
            log("[service] _do_replacement EXCEPTION: {}\n{}".format(
                exc, traceback.format_exc()))

    def _do_replacement_inner(self) -> None:
        # Hold the lock for the entire queue read-pop-replace-write cycle.
        # This ensures _on_av_started_worker (background thread) always sees
        # a fully consistent self._queue — never a partially updated state.
        #
        # ONE manager for the entire operation.  Multiple _get_manager() calls
        # within a single pop/replace cycle each create a fresh ChannelManager
        # that loads state.json independently.  The later instance's _save_state()
        # clobbers state written by an earlier one, causing tv_next_ep to regress
        # and the same episode to repeat.  Capture once, pass through.
        with self._lock:
            if not self._channel_id:
                log("[service] _do_replacement: early return — no channel_id")
                return

            manager = self._get_manager()

            queue = manager.get_channel_queue(self._channel_id)
            if not queue:
                log("[service] _do_replacement: early return — queue empty")
                return

            # queue[0] is always the consumed item.
            consumed_item = queue.pop(0)
            log("[service] _do_replacement: consumed '{}' interleaved={} "
                "queue now {} items, _queue_pos={}".format(
                consumed_item.get("title", "?"),
                consumed_item.get("_interleaved", False),
                len(queue), self._queue_pos))

            consumed_cid = (consumed_item.get("_channel_id")
                            or consumed_item.get("channel_id", ""))

            replacement = None
            if manager.is_combo_channel(consumed_cid):
                # Strict 1-for-1: _handle_combo_slot appends exactly one
                # replacement slot to queue.  Capture it for Kodi playlist.
                q_before = len(queue)
                self._handle_combo_slot(manager, consumed_item, queue)
                replacement = queue[-1] if len(queue) > q_before else None
            else:
                replacement = manager.get_one_replacement(
                    self._channel_id, consumed_item, current_queue=queue)
                if replacement:
                    queue.append(replacement)
                    log("[service] _do_replacement: appended '{}' to queue"
                        .format(replacement.get("title", "?")))
                else:
                    log("[service] _do_replacement: no replacement returned")

            manager.write_channel_queue(self._channel_id, queue)
            self._queue = queue

        # Kodi playlist ops outside lock — they may block and are not
        # shared state that _on_av_started_worker cares about.
        if replacement:
            try:
                from resources.lib.player import _make_listitem
                kodi_playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
                kodi_playlist.add(replacement["file"],
                                  _make_listitem(replacement))
                log("[service] _do_replacement: added '{}' to Kodi playlist "
                    "(size={} pos={})".format(
                    replacement.get("title", "?"),
                    kodi_playlist.size(), kodi_playlist.getposition()))
            except Exception as exc:
                log("[service] _do_replacement: playlist update error: {}"
                    .format(exc))

    def _handle_combo_slot(self, manager, consumed_item: dict,
                            queue: list) -> None:
        """Strict 1-for-1 replacement for combo block slots.

        When a combo slot is consumed, immediately append the next item
        for that same slot — no waiting for the full unit to complete.

        ``manager`` must be the single shared ChannelManager instance for this
        operation — do NOT call self._get_manager() here.  A fresh instance
        would load stale state from disk and clobber the tv_next_ep/show_slot
        values that ComboQueueBuilder is about to write.
        """
        cid          = (consumed_item.get("_channel_id")
                        or consumed_item.get("channel_id", ""))
        consumed_slot_id = consumed_item.get("_combo_slot", "")

        log("[service] _handle_combo_slot: consumed='{}' slot='{}' cid={}".format(
            consumed_item.get("title", "?"),
            consumed_slot_id[:8], cid[-8:]))

        combo_ch = manager.get_channel(cid)
        if not combo_ch:
            log("[service] _handle_combo_slot: combo channel not found "
                "for cid={}".format(cid[-8:]))
            return

        # Find the index of the consumed slot within the combo channel.
        slots = combo_ch.get("slots", [])
        slot_index = next(
            (i for i, s in enumerate(slots)
             if s.get("slot_id", "") == consumed_slot_id), None)

        if slot_index is None:
            log("[service] _handle_combo_slot: slot_id {} not found in "
                "combo channel — cannot replace".format(consumed_slot_id[:8]),
                level=xbmc.LOGWARNING)
            return

        from resources.lib.channels.combo import ComboQueueBuilder
        replacement_items = ComboQueueBuilder(manager).build_one_slot(
            combo_ch, slot_index, host_queue=queue)

        if replacement_items:
            queue.extend(replacement_items)
            log("[service] _handle_combo_slot: 1-for-1 replaced slot {} "
                "with '{}'".format(slot_index,
                replacement_items[0].get("title", "?")))
        else:
            log("[service] _handle_combo_slot: no replacement for slot {} "
                "(exhausted?)".format(slot_index))

    # =========================================================================
    # Skip detection  (spec §7.4)
    # =========================================================================

    def _handle_skip(self, channel_id: str, now_playing_file: str) -> None:
        # Handle user skipping forward in the Kodi playlist.
        # For each skipped item fire 1-for-1 replacement and add to
        # Kodi playlist. Remove skipped items from disk queue so the
        # now-playing item becomes position 0. Rebuild Kodi playlist
        # to match. spec §1.7, §7.4
        manager = self._get_manager()
        queue   = manager.get_channel_queue(channel_id)

        current_pos = next(
            (i for i, item in enumerate(queue)
             if item.get("file") == now_playing_file), None)

        if current_pos is None or current_pos == 0:
            return

        skipped = queue[:current_pos]
        log("[service] _handle_skip: {} items skipped, now_playing='{}' "
            "at pos={} in queue of {}".format(
            len(skipped),
            queue[current_pos].get("title", "?") if current_pos < len(queue) else "?",
            current_pos, len(queue)))
        log("[service] _handle_skip: skipped items: {}".format(
            ", ".join("[{}] {}".format(
                "BLOCK" if item.get("_schedule_id")
                else ("COMBO" if item.get("_interleaved") else "primary"),
                item.get("title", "?"))
            for item in skipped)))

        # Clear any saved resume positions for skipped items.
        for item in skipped:
            f = item.get("file", "")
            if f:
                manager.clear_resume_position(channel_id, f)

        # Fire 1-for-1 replacement for every skipped item, preserving the
        # original interleave order in the appended tail.
        #
        # Combo slots: call build_one_slot for the specific slot that was
        # skipped — same strict 1-for-1 behaviour as natural playback.
        # No tracker, no unit counting, no remainder logic needed.
        #
        # Primary items: 1-for-1 via get_one_replacement as usual.
        from resources.lib.channels.combo import ComboQueueBuilder
        from resources.lib.player import _make_listitem

        replacements = []   # all replacements for Kodi playlist
        skipped_block_items = []   # scheduled block items, counted at the end
        for item in skipped:
            # Scheduled block items are foreign to the target channel and do
            # not repeat: popped with NO replacement, exactly as on natural
            # end and in the carousel. _schedule_id takes precedence over
            # _interleaved — combo-sourced block items carry both.
            if item.get("_schedule_id"):
                skipped_block_items.append(item)
                continue
            consumed_cid = item.get("_channel_id") or item.get("channel_id", "")
            if manager.is_combo_channel(consumed_cid):
                combo_ch = manager.get_channel(consumed_cid)
                if not combo_ch:
                    continue
                consumed_slot_id = item.get("_combo_slot", "")
                slots = combo_ch.get("slots", [])
                slot_index = next(
                    (i for i, s in enumerate(slots)
                     if s.get("slot_id", "") == consumed_slot_id), None)
                if slot_index is None:
                    log("[service] _handle_skip: slot_id {} not found — "
                        "skipping replacement".format(consumed_slot_id[:8]),
                        level=xbmc.LOGWARNING)
                    continue
                new_items = ComboQueueBuilder(
                    manager).build_one_slot(
                        combo_ch, slot_index, host_queue=queue)
                if new_items:
                    queue.extend(new_items)
                    replacements.extend(new_items)
                    log("[service] _handle_skip: replaced combo slot {} "
                        "with '{}'".format(slot_index,
                        new_items[0].get("title", "?")))
            else:
                replacement = manager.get_one_replacement(
                    channel_id, item, current_queue=queue)
                if replacement:
                    queue.append(replacement)
                    replacements.append(replacement)

        # Remove skipped items from disk queue — now-playing becomes index 0.
        del queue[:current_pos]
        with self._lock:
            manager.write_channel_queue(channel_id, queue)
            self._queue     = queue
            self._queue_pos = 0

        # Resync the Kodi playlist to the disk queue.
        #
        # Append all replacements to the Kodi playlist tail.
        # Skipped items are behind Kodi's cursor — harmless, no removal needed.
        # Replacements (both primary and combo slots) go to the tail in the
        # same order they were appended to the disk queue above.
        try:
            kodi_playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
            size_before = kodi_playlist.size()
            for rep in replacements:
                kodi_playlist.add(rep["file"], _make_listitem(rep))
            log("[service] _handle_skip: appended {} replacement(s) to "
                "Kodi playlist (size {}->{}): {}".format(
                len(replacements), size_before, kodi_playlist.size(),
                ", ".join(r.get("title","?") for r in replacements)))
        except Exception as exc:
            log("[service] _handle_skip: playlist update error: {}"
                .format(exc), level=xbmc.LOGWARNING)

        # Count skipped scheduled block items toward their block. Done last,
        # after every write made through `manager` above: counting uses a
        # fresh ChannelManager, and a later save from the older instance would
        # overwrite the updated active_block state.
        for item in skipped_block_items:
            self._count_block_item(item["_schedule_id"], item, "skip")

    # =========================================================================
    # Resume  (spec §1.6)
    # =========================================================================

    # =========================================================================
    # Position polling
    # =========================================================================

    def _start_poll(self, file_path: str) -> None:
        self._stop_poll()
        self._resume_pos = 0.0
        self._schedule_poll()

    def _stop_poll(self) -> None:
        if self._poll_timer:
            self._poll_timer.cancel()
            self._poll_timer = None

    def _schedule_poll(self) -> None:
        self._poll_timer = threading.Timer(
            self._poll_interval, self._poll_position)
        self._poll_timer.daemon = True
        self._poll_timer.start()

    def _poll_position(self) -> None:
        try:
            if not self.isPlaying():
                return
            self._resume_pos = self.getTime()
            self._schedule_poll()

            # Coming Up Next overlay trigger.
            # Defers xbmcgui call to main tick loop via _pending_overlay.
            if self._overlay_shown:
                return
            try:
                with self._lock:
                    snap_queue   = list(self._queue)
                    snap_pos     = self._queue_pos
                if not snap_queue or snap_pos >= len(snap_queue):
                    return
                cur_item = snap_queue[snap_pos]
                duration = cur_item.get("duration", 0) or 0
                if duration <= 0:
                    return
                from resources.lib.overlays.coming_up_next import load_settings as _ls
                is_audio = cur_item.get("is_audio", False)
                if is_audio:
                    if not self.addon.getSettingBool("cun_audio_enabled"):
                        return
                    audio_min = max(0, int(
                        self.addon.getSetting("cun_audio_min_duration") or "60"))
                    if duration < audio_min:
                        return
                    lead_s  = max(1, int(
                        self.addon.getSetting("cun_audio_lead") or "20"))
                    disp_s  = max(1, int(
                        self.addon.getSetting("cun_audio_duration") or "15"))
                    cun_cfg = _ls()
                    cun_cfg["duration"] = disp_s
                    cun_cfg["is_audio"] = True
                    cun_cfg["enabled"]  = True
                else:
                    cun_cfg = _ls()
                    if not cun_cfg.get("enabled", False):
                        return
                    min_dur = cun_cfg.get("min_duration", 120)
                    if duration < min_dur:
                        return
                    if cur_item.get("_silent") and cun_cfg.get("suppress_silent"):
                        return
                    lead_s = (int(cun_cfg.get("lead_minutes", 2)) * 60) + \
                             int(cun_cfg.get("duration", 8))
                time_left = duration - self._resume_pos
                if time_left <= lead_s:
                    self._overlay_shown   = True
                    self._pending_overlay = (cur_item, cun_cfg)
                    log("[service] CUN: queued overlay for '{}' "
                        "({:.0f}s left)".format(
                            cur_item.get("title", "?"), time_left))
            except Exception as _cun_err:
                log("[service] CUN poll error: {}".format(_cun_err),
                    level=xbmc.LOGWARNING)
        except Exception:
            pass

    def _get_next_episode(self, cur_item: dict):
        """Return the next item to show in the Coming Up Next overlay.

        Scheduled block items are shown like any other next item: the block
        is what actually plays next. Silent items are always skipped (they
        have nothing to show). When a block has been fired onto the disk
        queue but the reload has not happened yet, the block's leading items
        are used, because the in-memory queue does not contain them yet.
        """
        try:
            with self._lock:
                snap_queue = list(self._queue)
                snap_pos   = self._queue_pos
                pending_ch = self._pending_block_channel
            in_block = bool(cur_item.get("_schedule_id"))
            if pending_ch is not None and not in_block:
                mgr = self._get_manager()
                disk_q = (mgr.get_channel_queue(pending_ch.get("id", ""))
                          if mgr else [])
                for blk in disk_q:
                    if not blk.get("_schedule_id"):
                        break
                    if not blk.get("_silent"):
                        return blk
            nxt_pos = snap_pos + 1
            while nxt_pos < len(snap_queue):
                nxt = snap_queue[nxt_pos]
                if nxt.get("_silent"):
                    nxt_pos += 1
                    continue
                return nxt
            return None
        except Exception:
            return None

    # =========================================================================
    # Helpers
    # =========================================================================


    def _read_active_channel_id(self) -> str | None:
        try:
            profile    = xbmcvfs.translatePath(
                self.addon.getAddonInfo("profile"))
            local_path = os.path.join(profile, "now_playing.json")
            if xbmcvfs.exists(local_path):
                with xbmcvfs.File(local_path, "r") as f:
                    data = json.loads(f.read())
                return data.get("active_channel_id")
        except Exception as exc:
            log("[service] _read_active_channel_id error: {}".format(exc))
        return None

    def _get_kodi_playing_file(self) -> str | None:
        try:
            return self.getPlayingFile()
        except Exception:
            return None


# ---------------------------------------------------------------------------
# SmartChannelsMonitor — xbmc.Monitor subclass
# Only used for abortRequested() / waitForAbort() and tick loop.
# Does NOT receive playback callbacks.
# ---------------------------------------------------------------------------

class SmartChannelsMonitor(xbmc.Monitor):
    """xbmc.Monitor subclass — tick loop, abort detection, notifications.

    onNotification and onSettingsChanged ported from 2.x service.py.
    Playback callbacks (onPlayBackStarted etc.) live on xbmc.Player only.
    """

    def __init__(self, player: "SmartChannelsPlayer") -> None:
        super().__init__()
        self._player = player
        # Baseline for onSettingsChanged: the shared path in force when the
        # service starts.  (Starting from None made the first change in each
        # Kodi session set the baseline from the NEW value and skip the
        # data-migration prompt.)
        from resources.lib.utils.paths import shared_root
        self._last_shared_root = shared_root()

    def onNotification(self, sender: str, method: str, data: str) -> None:
        """Rebuild library cache when Kodi finishes a library scan.

        Ported from 2.x.  Keeps the local cache current without requiring
        a manual refresh from settings or a Kodi restart.
        """
        import threading as _threading
        if method == "VideoLibrary.OnScanFinished":
            log("[service] VideoLibrary.OnScanFinished — rebuilding cache")
            def _rebuild():
                try:
                    from resources.lib.channel_manager import ChannelManager
                    ChannelManager(xbmcaddon.Addon()).library.build_local_cache(
                        progress_callback=None)
                    log("[service] Library cache rebuilt after scan")
                except Exception as exc:
                    log("[service] Library cache rebuild error: {}".format(exc),
                        level=xbmc.LOGWARNING)
            _threading.Thread(target=_rebuild, daemon=True).start()

        elif method == "AudioLibrary.OnScanFinished":
            log("[service] AudioLibrary.OnScanFinished — rebuilding songs cache")
            def _rebuild_songs():
                try:
                    from resources.lib.channel_manager import ChannelManager
                    ChannelManager(xbmcaddon.Addon()).library.build_songs_cache()
                    log("[service] Songs cache rebuilt after scan")
                except Exception as exc:
                    log("[service] Songs cache rebuild error: {}".format(exc),
                        level=xbmc.LOGWARNING)
            _threading.Thread(target=_rebuild_songs, daemon=True).start()

    def onSettingsChanged(self) -> None:
        """Handle settings changes.

        1. Reloads the resume poll interval immediately.
        2. Detects changes to shared_storage_path and offers to migrate
           existing data files to the new location.
        """
        from resources.lib.utils.paths import (
            shared_root, _get_profile, _dir_exists,
            migrate_storage_path, delete_files_in_root,
            _list_files_in_root)

        addon = xbmcaddon.Addon()

        # -- Poll interval --------------------------------------------------
        try:
            new_interval = self._player._get_poll_interval()
            with self._player._lock:
                self._player._poll_interval = new_interval
                timer_running = self._player._poll_timer is not None
            if timer_running:
                self._player._stop_poll()
                self._player._schedule_poll()
            log("[service] onSettingsChanged: poll interval now {}s".format(
                new_interval))
        except Exception as exc:
            log("[service] onSettingsChanged poll error: {}".format(exc))

        # -- Shared storage path change detection ---------------------------
        try:
            new_shared = shared_root()
            old_shared = getattr(self, "_last_shared_root", None)

            # Defensive: no baseline recorded — nothing to compare with.
            if old_shared is None:
                self._last_shared_root = new_shared
                return

            # No change — nothing to do.
            if new_shared == old_shared:
                return

            self._last_shared_root = new_shared
            profile = _get_profile()
            d = xbmcgui.Dialog()

            # Determine source and destination roots.
            # old_shared == "" means data was in local profile.
            # new_shared == "" means user cleared the shared path.
            old_root = old_shared if old_shared else profile
            new_root = new_shared if new_shared else profile

            # Verify new path is accessible.
            # _dir_exists() appends "/" for SMB/NFS paths so Kodi's VFS
            # recognises them as directories rather than treating them as
            # a file check (which returns False even on reachable shares).
            if not _dir_exists(new_root):
                try:
                    xbmcvfs.mkdirs(new_root)
                except Exception:
                    pass
            if not _dir_exists(new_root):
                d.ok(addon.getLocalizedString(32000),
                     addon.getLocalizedString(32391))
                log("[service] onSettingsChanged: new shared path not "
                    "accessible: {}".format(new_root), level=xbmc.LOGWARNING)
                return

            # Choose the correct prompt string.
            if not new_shared:
                # shared → local
                prompt_str = addon.getLocalizedString(32386).format(old_root)
            else:
                # local → shared  OR  shared → shared
                prompt_str = addon.getLocalizedString(32390).format(new_root)

            if not d.yesno(addon.getLocalizedString(32000), prompt_str):
                log("[service] onSettingsChanged: user declined data migration")
                return

            # Copy files.
            copied, failed = migrate_storage_path(old_root, new_root)
            log("[service] onSettingsChanged: migrated {}/{} file(s) "
                "{} → {}".format(copied, copied + failed, old_root, new_root))

            # Report result.
            total = copied + failed
            if failed == 0:
                if new_shared:
                    d.ok(addon.getLocalizedString(32000),
                         addon.getLocalizedString(32388).format(copied))
                else:
                    d.ok(addon.getLocalizedString(32000),
                         addon.getLocalizedString(32387))
            else:
                d.ok(addon.getLocalizedString(32000),
                     addon.getLocalizedString(32392).format(copied, total))

            # Offer to delete old files when moving shared → shared or
            # local → shared (not when moving back to local profile, since
            # local profile files are still needed as write-staging copies).
            if new_shared and copied > 0:
                old_files = _list_files_in_root(old_root)
                del_prompt = addon.getLocalizedString(32389).format(old_root)
                if d.yesno(addon.getLocalizedString(32000), del_prompt):
                    delete_files_in_root(old_root, old_files)
                    log("[service] onSettingsChanged: deleted old files "
                        "from {}".format(old_root))

        except Exception as exc:
            log("[service] onSettingsChanged storage migration error: "
                "{}".format(exc), level=xbmc.LOGERROR)


# ---------------------------------------------------------------------------
# Tick loop
# ---------------------------------------------------------------------------

def _run_tick_loop(player: SmartChannelsPlayer,
                   monitor: SmartChannelsMonitor) -> None:
    tick = 0
    log("[service] Tick loop started")
    while not monitor.abortRequested():
        monitor.waitForAbort(1)
        tick += 1

        # Coming Up Next overlay — dispatch pending overlay on main thread.
        # _poll_position() (called from a Timer thread) queues the overlay
        # in _pending_overlay; we show it here so xbmcgui runs on main thread.
        _pending = player._pending_overlay
        if _pending is not None:
            player._pending_overlay = None
            _cur_ep, _cun_cfg = _pending
            try:
                _next_ep = player._get_next_episode(_cur_ep)
                if _next_ep:
                    from resources.lib.overlays.coming_up_next import show_overlay
                    show_overlay(_next_ep, _cun_cfg)
                    log("[service] CUN: displayed overlay for '{}'".format(
                        _next_ep.get("title", "?")))
                else:
                    log("[service] CUN: no next episode — overlay skipped")
            except Exception as _oe:
                log("[service] CUN dispatch error: {}".format(_oe),
                    level=xbmc.LOGWARNING)

        if tick % 60 == 0:
            _tick_channel_lock(player)
            _tick_carousel(player)
            _tick_scheduler(player)

        if tick % 3600 == 0:
            _tick_cache_ages(player)


def _tick_channel_lock(player: SmartChannelsPlayer) -> None:
    """Channel lock upkeep, every 60 s from the tick loop.  (3.1.109)

    Playing: keep this device's lock alive.  Idle for two ticks in a row:
    release the lock (one idle tick is tolerated so a schedule block reload
    never drops it).  Playing or idle: tell the user when a channel they were
    refused has become free (3.1.110: also while they watch another channel).
    """
    try:
        manager    = player._get_manager()
        # now_playing.json is cleared on stop, so it confirms the channel id
        # is not a leftover from a finished session.
        channel_id = (player._channel_id
                      if player.isPlaying()
                      and player._read_active_channel_id() == player._channel_id
                      else None)

        if channel_id:
            player._idle_lock_ticks = 0
            # This device now plays it, so there is nothing left to wait for.
            stop_waiting(channel_id)
            manager.refresh_channel_lock(channel_id)
        else:
            owned = manager.owned_lock_channel()
            if owned:
                player._idle_lock_ticks += 1
                if player._idle_lock_ticks >= 2:
                    manager.release_channel_lock(owned)
                    player._idle_lock_ticks = 0
            else:
                player._idle_lock_ticks = 0

        for entry in waiting_entries():
            wid = entry.get("id", "")
            if wid and wid != channel_id and not manager.channel_lock_holder(wid):
                stop_waiting(wid)
                xbmcgui.Dialog().notification(
                    player.addon.getLocalizedString(32000),
                    player.addon.getLocalizedString(32947).format(
                        entry.get("name", wid)),
                    xbmcgui.NOTIFICATION_INFO, 6000)
                log("[service] channel '{}' is free — user notified".format(
                    entry.get("name", wid)))
    except Exception as exc:
        log("[service] _tick_channel_lock error: {}".format(exc),
            level=xbmc.LOGWARNING)


def _tick_cache_ages(player: SmartChannelsPlayer) -> None:
    """Refresh the cache-age settings (Settings > Cache) once an hour."""
    try:
        player._get_manager().library.publish_cache_ages()
    except Exception as exc:
        log("[service] _tick_cache_ages error: {}".format(exc),
            level=xbmc.LOGWARNING)


def _tick_carousel(player: SmartChannelsPlayer) -> None:
    """Fire carousel check for all carousel-enabled channels.
    Called every 60 s from the tick loop.  spec §9.1
    """
    try:
        tick_carousel(player)
    except Exception as exc:
        log("[service] _tick_carousel error: {}".format(exc),
            level=xbmc.LOGWARNING)


def _tick_scheduler(player: SmartChannelsPlayer) -> None:
    """Fire the schedule engine every 60 s from the tick loop.

    Checks all active schedules and fires any whose time has been reached.
    When fire_block() writes block items to the front of the currently-playing
    channel's queue file, sets player._pending_block_channel so that
    onPlayBackEnded can reload the channel and play the block at the next
    natural item boundary.  spec §14.

    Only the client that is playing the schedule's target channel fires it.
    The channel id passed to the scheduler is this client's own channel, and
    only while Kodi is really playing (the id can outlive the last item
    after a natural end), so a client playing something else, or nothing,
    never fires a block.
    """
    try:
        from resources.lib.scheduler import ScheduleManager
        manager    = player._get_manager()
        playing_id = player._channel_id if player.isPlaying() else None
        # check_all reports the target channels it actually fired a block
        # for; that, not the state of other blocks in state.json, decides
        # whether a reload is needed.
        fired_targets = ScheduleManager().check_all(
            manager,
            now_playing_channel_id=playing_id)

        if playing_id and playing_id in fired_targets:
            # The target channel is currently playing — schedule a reload
            # at the next natural episode boundary.
            if player._pending_block_channel is None:
                ch = manager.get_channel(playing_id)
                if ch:
                    player._pending_block_channel = ch
                    log("[service] _tick_scheduler: block fired on active "
                        "channel '{}' — reload pending at next boundary".format(
                            ch.get("name", playing_id)))
    except Exception as exc:
        log("[service] _tick_scheduler error: {}".format(exc),
            level=xbmc.LOGWARNING)


# ---------------------------------------------------------------------------
# Service entry point
# ---------------------------------------------------------------------------

def _service_ensure_caches(addon: xbmcaddon.Addon,
                            manager: ChannelManager) -> None:
    """Build library and songs caches on first run if they do not exist.

    Called once at service startup. Runs cache builds on a background thread
    so the service tick loop is not blocked.  The video library cache uses a
    progress dialog when opened via addon.py; here we run it silently in the
    background and emit a toast when done.

    Songs cache always runs in background (same as addon.py path).
    """
    import threading

    def _build_video():
        if manager.library.local_cache_exists():
            log("[service] Video library cache already present — skipping")
            return
        log("[service] Video library cache missing — building in background")
        ok = manager.library.build_local_cache(progress_callback=None)
        if ok:
            xbmc.executebuiltin("Notification({},{},{},)".format(
                addon.getLocalizedString(32000),
                addon.getLocalizedString(32404),   # "Library cache updated."
                3000))
            log("[service] Video library cache built successfully")
        else:
            log("[service] Video library cache build FAILED",
                level=xbmc.LOGWARNING)

    def _build_songs():
        if manager.library.songs_cache_exists():
            log("[service] Songs cache already present — skipping")
            return
        log("[service] Songs cache missing — building in background")
        xbmc.executebuiltin("Notification({},{},{},)".format(
            addon.getLocalizedString(32000),
            addon.getLocalizedString(32848),   # "Building songs cache in background..."
            3000))
        manager.library.build_songs_cache()

    # Show the current cache ages in Settings > Cache right away.
    try:
        manager.library.publish_cache_ages()
    except Exception as exc:
        log("[service] publish_cache_ages error: {}".format(exc),
            level=xbmc.LOGWARNING)

    threading.Thread(target=_build_video, daemon=True).start()
    threading.Thread(target=_build_songs,  daemon=True).start()


def _service_repair_missing_shows(monitor: xbmc.Monitor,
                                  addon: xbmcaddon.Addon) -> None:
    """Once after start, put back any show missing from a TV channel queue.

    Runs on a background thread after a delay, because the network share and
    the Kodi library may not be ready right at boot.  If a show had no
    playable episode yet, it tries once more later.
    """
    import threading

    def _run():
        for delay in (60, 300):
            if monitor.waitForAbort(delay):
                return
            try:
                result = ChannelManager(addon).repair_missing_shows()
            except Exception as exc:
                log("[service] repair_missing_shows error: {}".format(exc),
                    level=xbmc.LOGWARNING)
                return
            if not result["no_episode"]:
                return

    threading.Thread(target=_run, daemon=True).start()


if __name__ == "__main__":
    addon   = xbmcaddon.Addon()
    player  = SmartChannelsPlayer(addon)
    monitor = SmartChannelsMonitor(player)

    log("[service] Service started — profile={}".format(
        xbmcvfs.translatePath(addon.getAddonInfo("profile"))))

    # Build library caches on first run so channels can be created immediately
    # without the user needing to open the addon first.
    # Use a fresh ChannelManager instance for the cache check.
    _service_ensure_caches(addon, ChannelManager(addon))
    _service_repair_missing_shows(monitor, addon)

    _run_tick_loop(player, monitor)
    # Kodi is closing: free any channel this device was holding.
    try:
        _mgr = ChannelManager(addon)
        _mgr.release_channel_lock(_mgr.owned_lock_channel())
    except Exception as exc:
        log("[service] shutdown lock release error: {}".format(exc),
            level=xbmc.LOGWARNING)
    log("[service] Service stopped")
