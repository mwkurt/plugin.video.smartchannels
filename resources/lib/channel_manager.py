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

import copy
import os
import random
import time
import uuid
from typing import Any, Optional

import xbmc
import xbmcaddon
import xbmcvfs

from resources.lib.library      import LibraryClient
from resources.lib.utils.logger import log
from resources.lib.utils.paths  import (load_json, save_json, resolve_path,
                                        shared_root, normalize_share_path,
                                        path_join)
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

        self._channels = self._load_json(self._channels_path, [])
        self._state    = self._load_json(self._state_path,    {})
        log("[ChannelManager] Loaded {} channel(s)".format(len(self._channels)),
            xbmc.LOGDEBUG)

        # Keys explicitly deleted this session; stripped from merge on save.
        self._deleted_state_keys: set = set()

        # {source_id: {str(show_id): episode info}} — where each interleaved
        # TV show was up to in its host's queue.  Held only while a host
        # rebuilds (begin/end_interleave_resume).
        self._interleave_resume: dict = {}

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

    def _save_channels(self) -> None:
        self._save_json(self._channels_path, self._channels)

    def _save_state(self) -> None:
        """Read-before-write merge for state.json.

        Reads current file from disk, merges our in-memory changes on top,
        strips explicitly deleted keys, strips orphan keys (channels that no
        longer exist), then writes. Keeps in-memory copy consistent.
        """
        try:
            on_disk = self._load_json(self._state_path, {})
            merged  = {**on_disk, **self._state}
            for k in self._deleted_state_keys:
                merged.pop(k, None)
            # Orphan-key pruning: drop keys for deleted channels.
            # Exemptions: keys starting with "resume:" or "combo:" are managed
            # independently and must not be pruned here.
            # Read live channel IDs directly from disk so channels created by
            # other processes (e.g. addon.py) are not falsely treated as orphans
            # by the long-running service process.
            try:
                disk_channels = self._load_json(self._channels_path, [])
                live_ids = {c["id"] for c in disk_channels}
                # Keep in-memory channels in sync
                self._channels = disk_channels
            except Exception:
                live_ids = {c["id"] for c in self._channels}
            orphans  = [
                k for k in list(merged.keys())
                if ":" in k
                and not k.startswith("resume:")
                and not k.startswith("combo:")
                and not k.startswith("pending_seek:")
                and not k.startswith("sch_")   # schedule active_block keys
                and k.split(":", 1)[0] not in live_ids
            ]
            for k in orphans:
                del merged[k]
            self._save_json(self._state_path, merged)
            self._state = merged
        except Exception as exc:
            log("[ChannelManager] _save_state error: {}".format(exc),
                level=xbmc.LOGWARNING)

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

    def write_channel_queue(self, channel_id: str, queue: list) -> None:
        """Write the queue list for any channel type."""
        self._write_queue_file(channel_id, queue)

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
            c = dict(self._ZERO_CURSOR)
            c.update(stored)
            # Ensure sub-dicts are always present (forward-compat)
            for k in ("ep_pos", "ep_played", "slot_owed"):
                if not isinstance(c.get(k), dict):
                    c[k] = {}
            return c
        return dict(self._ZERO_CURSOR)

    def set_cursor(self, channel_id: str, cursor: dict) -> None:
        """Write cursor to state for channel_id."""
        key = "{}:cursor".format(channel_id)
        self._deleted_state_keys.discard(key)
        self._state[key] = cursor
        self._save_state()

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

        Returns None if the channel is exhausted (recycle=False, pool empty).
        """
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
                                 popped_show_id: int) -> Optional[dict]:
        """Get next episode of the SAME show that was carousel-popped.

        Does NOT advance show_slot — only the per-show ep_pos advances.
        spec §8.5, §9.2
        """
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
        ep      = self._pick_one_ep_no_slot_advance(
            show, sid_str, episodes, cursor,
            channel.get("randomize", False), channel.get("recycle", True),
            channel_id=channel_id)
        self.set_cursor(channel_id, cursor)
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
                                    all_episodes_for_show=episodes)
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
        self.set_cursor(channel_id, cursor)
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
                        self.set_cursor(channel_id, cursor)
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
                        self.set_cursor(channel_id, cursor)
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
                self.set_cursor(channel_id, cursor)
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
        for _ in range(max(1, len(episodes))):
            ep = self._next_candidate_ep(
                show, sid_str, episodes, cursor, randomize, recycle,
                queued_ids=queued_ids, consumed_id=consumed_id)
            if ep is None or ep["episodeid"] in tried:
                return None
            tried.add(ep["episodeid"])
            norm = _normalize_ep_fn(ep, channel_id or show.get("tvshowid", 0),
                                    int(sid_str),
                                    all_episodes_for_show=episodes)
            if norm is not None:
                return norm
            self.record_missing_duration(channel_id, ep, "no_nfo")
        return None

    def _next_candidate_ep(self, show: dict, sid_str: str,
                           episodes: list, cursor: dict,
                           randomize: bool,
                           recycle: bool,
                           queued_ids: Optional[set] = None,
                           consumed_id=None) -> Optional[dict]:
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
            # Seed ep_pos from state if first access
            if sid_str not in cursor["ep_pos"]:
                cursor["ep_pos"][sid_str] = 0

            idx = cursor["ep_pos"].get(sid_str, 0)
            if idx >= len(episodes):
                if not recycle:
                    return None
                cursor["ep_pos"][sid_str] = 0
                idx = 0
            ep = episodes[idx]
            # Advance by span
            from resources.lib.utils.multi_episode import count_episode_span
            span = count_episode_span(ep)
            cursor["ep_pos"][sid_str] = idx + span

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
                            start_show_index: Optional[int] = None) -> list:
        """Build a fresh queue of exactly queue_size items for any channel type.

        Called on channel create, reset, or edit requiring rebuild.
        Writes the cursor and returns the queue list (caller writes to disk).

        spec §7.2
        """
        channel_id  = channel["id"]
        target_size = int(channel.get("queue_size",
                                      self._default_queue_size()))
        ctype       = channel.get("channel_type", "tv")

        if ctype == "tv":
            return self._build_fresh_tv_queue(channel, target_size,
                                              start_show_index)
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
                               start_show_index: Optional[int] = None) -> list:
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

        items, cursor, weave_seed = self._build_planned_tv_items(
            channel, target_size, zero)
        self.set_cursor(channel_id, cursor)

        items = self.weave_interleave_sources(channel, items,
                                               seed=weave_seed)

        log("[ChannelManager] _build_fresh_tv_queue: built {} items for '{}'"
            .format(len(items), channel.get("name", channel_id)))
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
                                    all_episodes_for_show=episodes)
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

        spec §7.5
        """
        import datetime as _dt

        file_path = item.get("file", "")
        show      = item.get("tvshowtitle", item.get("title", ""))
        title     = item.get("title", "")
        season    = int(item.get("season",  0) or 0)
        episode   = int(item.get("episode", 0) or 0)
        ep_label  = ("S{:02d}E{:02d}".format(season, episode)
                     if season else "")

        # 1. Per-channel state list
        state_key = "{}:missing_durations".format(channel_id)
        try:
            state    = self._load_json(self._state_path, {})
            existing = state.get(state_key, [])
            known    = {e.get("file", "") for e in existing}
            if file_path not in known:
                existing.append({
                    "show":    show,
                    "title":   title,
                    "episode": ep_label,
                    "file":    file_path,
                    "reason":  reason,
                    "ts":      int(_dt.datetime.utcnow().timestamp()),
                })
                if len(existing) > 200:
                    existing = existing[-200:]
                state[state_key] = existing
                self._save_json(self._state_path, state)
        except Exception as exc:
            log("[ChannelManager] record_missing_duration state error: "
                "{}".format(exc))

        # 2. Global missing_durations.txt
        try:
            txt_path = self._resolve_path("missing_durations.txt")
            ts_str   = _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            ch_obj   = self.get_channel(channel_id)
            ch_name  = (ch_obj.get("name", channel_id)
                        if ch_obj else channel_id)
            line     = "{}\t{}\t{}\t{}\t{}\t{}\n".format(
                ts_str, ch_name, show, ep_label, file_path, reason)
            existing_txt = ""
            if xbmcvfs.exists(txt_path):
                try:
                    rf = xbmcvfs.File(txt_path, "r")
                    existing_txt = rf.read()
                    rf.close()
                except Exception:
                    existing_txt = ""
            wf = xbmcvfs.File(txt_path, "w")
            wf.write(existing_txt + line)
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
        self._state[key] = value
        self._save_state()

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
        if self.owned_lock_channel() == channel_id:
            self._save_json(self._owned_lock_path(), {"channel_id": ""})

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
        self._channels = self._load_json(self._channels_path, [])

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
                                old_shows: list) -> tuple:
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
            ep = self.get_show_next_queued_episode(channel_id,
                                                   show["tvshowid"])
            if ep and ep.get("episodeid") is not None:
                points[str(show["tvshowid"])] = {
                    "episodeid": ep["episodeid"],
                    "season":    ep.get("season", 1),
                    "episode":   ep.get("episode", 1),
                    "title":     ep.get("title", ""),
                }

        head = next((i for i in self.get_channel_queue(channel_id)
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
                    channel_id, channel, old_shows)
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
            self._pregenerate_queue_safe(rebuild_ch,
                                         start_show_index=keep_start)

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

        log("[ChannelManager] Deleted channel id={} — removed {} state "            "key(s), {} schedule(s)".format(
                channel_id, len(keys_to_del), len(sched_ids_to_del)))
        return True

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

    def delete_schedule(self, schedule_id: str) -> None:
        schedules = self.get_all_schedules()
        if schedule_id in schedules:
            del schedules[schedule_id]
            self._save_json(self._schedules_path, schedules)
        block_key = "{}:active_block".format(schedule_id)
        try:
            state = self._load_json(self._state_path, {})
            if block_key in state:
                del state[block_key]
                self._save_json(self._state_path, state)
        except Exception:
            pass

    def save_schedules_data(self, schedules: dict) -> None:
        self._save_json(self._schedules_path, schedules)

    def get_active_block(self, schedule_id: str) -> Optional[dict]:
        key = "{}:active_block".format(schedule_id)
        return self._load_json(self._state_path, {}).get(key)

    def set_active_block(self, schedule_id: str, block: dict) -> None:
        key   = "{}:active_block".format(schedule_id)
        state = self._load_json(self._state_path, {})
        state[key] = block
        self._save_json(self._state_path, state)

    def clear_active_block(self, schedule_id: str) -> None:
        key   = "{}:active_block".format(schedule_id)
        state = self._load_json(self._state_path, {})
        if key in state:
            del state[key]
            self._save_json(self._state_path, state)

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
                                movie, channel_id, library=self.library)
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
                        movie, channel_id, library=self.library)
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
                                        all_episodes_for_show=sp["available"])
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
        if explicit_movies:
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
            norm = _normalize_movie_fn(movie, combo_channel_id, library=self.library)
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
                                     show_id: int) -> Optional[dict]:
        """Return the first queued (next-to-play) episode item for show_id on
        this channel, or None when the show has no episode in the queue.

        The queue is the authority for what a show will play next; the
        per-show state record is not advanced by playback. Interleaved
        items are ignored — their show belongs to another channel.
        """
        for item in self.get_channel_queue(channel_id):
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
            if keys_to_clear:
                self._save_state()
                log("[ChannelManager] _reset_combo_interleave_sources: "
                    "cleared {} state key(s) for combo '{}' so next "
                    "build starts from episode 1".format(
                        len(keys_to_clear), src_ch.get("name", combo_id)))
            reset_combos.append(src_ch)
        return reset_combos

    def _pregenerate_queue_safe(self, channel: dict,
                                start_show_index: Optional[int] = None) -> None:
        """Build a fresh queue for channel and write it to disk.
        Catches and logs all exceptions so a builder failure never crashes
        the wizard.
        """
        channel_id = channel["id"]
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
                                             start_show_index=start_show_index)
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

        queue = self.get_channel_queue(channel_id)
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
                                            all_episodes_for_show=episodes)
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

        existing_queue = self.get_channel_queue(channel_id)
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
                    new_queue = primary
                    log("[ChannelManager] regenerate_queue: interleave "
                        "removed, {} primary items".format(len(new_queue)))
                    self.write_channel_queue(channel_id, new_queue)
                return

        # No usable queue — full rebuild
        log("[ChannelManager] regenerate_queue: no existing queue, "
            "full rebuild")
        self.clear_cursor(channel_id)
        q_path = self._queue_file_path(channel_id)
        if _xbmcvfs.exists(q_path):
            _xbmcvfs.delete(q_path)
        self._pregenerate_queue_safe(channel)

    def repair_queue_paths(self) -> dict:
        """Bring every TV queue entry up to date with the Kodi library.

        For each queued episode, look it up in the library (by episode ID,
        then by show + season + episode) and rewrite its file path, title,
        IDs and span from the library.  Queue order, cursors, carousel state
        and the entries themselves stay in place; a resume position saved
        under the old path moves to the new one.  An episode the library no
        longer has is left untouched and counted as not found.  Movies,
        folders and audio are not checked.  The in-memory library lists are
        cleared first (in the service too) so the lookup is current.
        Returns {"fixed": n, "not_found": n, "unchanged": n}.
        """
        result = {"fixed": 0, "not_found": 0, "unchanged": 0}
        self.library.invalidate_cache()

        # Load each show's episodes before touching any queue, so the
        # read-patch-write of a queue file below is short.
        lookups = {}
        for ch in self.get_all_channels():
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

    def repair_missing_shows(self) -> dict:
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
        the same show twice.
        Returns {"added": n, "no_episode": n}.
        """
        result = {"added": 0, "no_episode": 0}
        for channel in list(self.get_all_channels()):
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

            cursor = self.get_cursor(channel_id)
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
            queue   = self.get_channel_queue(channel_id)
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

    def reorder_queue_from_item(self, channel_id: str,
                                queue_index: int) -> bool:
        """Rotate the queue so the item at queue_index becomes position 0.
        Items before it move to the tail in their original order.
        Called by play_from_item (side panel click).
        Returns True on success.
        spec §16.1 (side panel Enter on right pane[N])
        """
        queue = self.get_channel_queue(channel_id)
        if not queue:
            return False
        if queue_index <= 0 or queue_index >= len(queue):
            return False

        reordered = queue[queue_index:] + queue[:queue_index]
        self.write_channel_queue(channel_id, reordered)
        log("[ChannelManager] reorder_queue_from_item: channel={} "
            "rotated to index {}".format(channel_id, queue_index))
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
