"""
resources/lib/channels/party.py
=================================
Queue builder for Party Mode channels (channel_type="party").

A Party Mode channel walks a user-specified folder (local or SMB, recursively),
collects audio files, and plays them in random order.

Queue items use the filename stem as the display title. Kodi reads full
tags (artist, album, etc.) directly from the file at playback time, so no
library lookup is needed and no delay is introduced at channel start.

OWNS:   Folder walk for audio files, queue item construction,
        recycle=False exhaustion tracking.

NEVER:  State reads/writes beyond the played-files list (via
        channel_manager.record_folder_file_played), playback control,
        UI rendering.

CALLERS: channel_manager.py only — via build_queue() (fresh build) and
         get_one_replacement() (1-for-1 replacement, build_one()).
"""

from __future__ import annotations

import os
import random

import xbmc
import xbmcvfs

from resources.lib.channels.base   import BaseQueueBuilder
from resources.lib.channels.folder  import (
    _normalise_path, _ensure_slash, _accessible_path,
    _title_from_path,
)
from resources.lib.utils.logger import log

# Audio file extensions accepted by Party Mode.
_AUDIO_EXTS = {
    ".mp3", ".flac", ".m4a", ".aac", ".ogg",
    ".wma", ".wav", ".opus", ".alac", ".ape",
}


def _walk_audio(path: str, results: list) -> None:
    """
    Recursively walk path, collecting audio files only (_AUDIO_EXTS).
    Uses xbmcvfs.listdir so both local and network (SMB) paths work.
    Separate from folder.py's _walk which is video-only.
    """
    acc = _accessible_path(path)
    if not acc:
        log("[PartyQueueBuilder] listdir: path not accessible: {}".format(
            path), xbmc.LOGWARNING)
        return
    try:
        dirs, files = xbmcvfs.listdir(acc)
    except Exception as e:
        log("[PartyQueueBuilder] listdir error {}: {}".format(path, e),
            xbmc.LOGWARNING)
        return

    for fname in (files or []):
        ext = os.path.splitext(fname.lower())[1]
        if ext in _AUDIO_EXTS:
            if "://" in path:
                results.append(path.rstrip("/") + "/" + fname)
            else:
                results.append(os.path.join(path, fname))

    for d in sorted(dirs or []):
        if "://" in path:
            sub = path.rstrip("/") + "/" + d
        else:
            sub = os.path.join(path, d)
        _walk_audio(sub, results)


class PartyQueueBuilder(BaseQueueBuilder):
    """
    Queue builder for Party Mode channels.

    Walks the channel's folder_path (local or SMB) using xbmcvfs,
    collects audio files (_AUDIO_EXTS), shuffles randomly, and builds
    queue items. Items use the filename stem as the title; Kodi reads
    full tags from the file at playback time.
    """

    def build(self, channel: dict, target_size: int,
              current_queue=None, queued_files: list = None) -> list:
        """
        Build a Party Mode queue.

        current_queue is accepted for API compatibility.
        queued_files: list of file paths already in the queue;
            when provided these are excluded to prevent duplicates
            on top-up (same pattern as FolderQueueBuilder).
        """
        channel_id  = channel["id"]
        folder_path = channel.get("folder_path", "")
        recycle     = channel.get("recycle", True)
        audio_order = channel.get("audio_order", "random")

        if not folder_path:
            log("[PartyQueueBuilder] no folder_path in channel {}".format(
                channel_id), xbmc.LOGWARNING)
            return []

        norm_path = _normalise_path(folder_path)

        if not xbmcvfs.exists(_ensure_slash(norm_path)):
            acc = _accessible_path(norm_path)
            if not acc:
                log("[PartyQueueBuilder] folder not accessible: {}".format(
                    norm_path), xbmc.LOGWARNING)
                return []
            norm_path = acc

        # Walk folder collecting audio files directly
        audio_files = []
        _walk_audio(norm_path, audio_files)

        if not audio_files:
            log("[PartyQueueBuilder] no audio files found in: {}".format(
                norm_path), xbmc.LOGWARNING)
            return []

        log("[PartyQueueBuilder] found {} audio files in {}".format(
            len(audio_files), norm_path))

        # Recycle=False: track played files
        played = self._get_played_files(channel_id)
        if not recycle and played and set(audio_files).issubset(set(played)):
            log("[PartyQueueBuilder] channel '{}' exhausted "
                "(recycle=False)".format(channel.get("name", channel_id)))
            return []

        if not recycle and played:
            audio_files = [f for f in audio_files if f not in played]
            if not audio_files:
                return []

        # Exclude files already sitting in the queue (top-up dedup)
        if queued_files:
            queued_set = set(queued_files)
            audio_files = [f for f in audio_files if f not in queued_set]
            if not audio_files:
                log("[PartyQueueBuilder] top-up: all audio files already queued")
                return current_queue if current_queue is not None else []

        # no_repeat mode: exclude files already played this cycle.
        # When the full pool has been heard, reset and start a new cycle.
        if audio_order == "no_repeat" and current_queue is not None:
            played = self._cm.get_party_no_repeat_played(channel_id)
            if played:
                available = [f for f in audio_files if f not in played]
                if not available:
                    log("[PartyQueueBuilder] no_repeat: full cycle complete "
                        "for '{}', resetting".format(channel.get("name",
                                                                  channel_id)))
                    self._cm.set_party_no_repeat_played(channel_id, [])
                    available = audio_files
                audio_files = available

        # Always random
        random.shuffle(audio_files)
        queue_files = audio_files[:target_size]

        # Build queue items directly from file paths.
        # Party Mode skips the AudioLibrary.GetSongs lookup — that query
        # scans the entire music library and on large MySQL-backed libraries
        # takes 15–20+ seconds, killing the script invoker before playback
        # can start.  Kodi reads tags directly from the file at playback time,
        # so the player displays correct title/artist regardless.
        items = []
        for file_path in queue_files:
            item = {
                "channel_id":    channel_id,
                "_channel_id":   channel_id,
                "songid":        -1,
                "title":         _title_from_path(file_path),
                "artist":        "",
                "album":         "",
                "genre":         "",
                "year":          0,
                "duration":      0,
                "thumbnail":     "",
                "file":          file_path,
                "is_audio":      True,
                "is_party_item": True,
            }
            items.append(item)

        log("[PartyQueueBuilder] built {} items for '{}'".format(
                len(items), channel.get("name", channel_id)))

        if current_queue is not None:
            return current_queue + items
        return items

    def build_one(self, channel: dict, host_queue: list,
                  consumed_item=None) -> list:
        """Return exactly one replacement file (or [] if none available).

        host_queue:    the queue the file will be appended to (consumed item
                       already removed); files already in it are avoided.
        consumed_item: the item just played or skipped; in no_repeat mode it
                       is recorded as played.
        """
        channel_id = channel["id"]
        if (consumed_item and consumed_item.get("is_party_item")
                and channel.get("audio_order", "random") == "no_repeat"):
            self.record_no_repeat_played(
                channel_id, consumed_item.get("file", ""))

        consumed_file = (consumed_item or {}).get("file", "")
        queue  = list(host_queue or [])
        queued = [i.get("file", "") for i in queue
                  if i.get("is_party_item") and i.get("file")]
        # First choice: a file that is neither queued nor the one just
        # played/skipped.
        result = self.build(channel, 1, current_queue=queue,
                            queued_files=queued + [consumed_file])
        items = result[len(queue):]
        if not items:
            # The consumed item is leaving the queue (a skip leaves it in
            # host_queue until afterwards), so it may be reused when nothing
            # else is free.
            queued_wo = [f for f in queued if f != consumed_file]
            result = self.build(channel, 1, current_queue=queue,
                                queued_files=queued_wo)
            items = result[len(queue):]
        if not items and queued:
            # Folder holds fewer files than the queue: repeat unavoidable.
            items = self.build(channel, 1)
        return items[:1]

    def record_no_repeat_played(self, channel_id: str,
                                 file_path: str) -> None:
        """
        Record a file as played for no_repeat tracking.
        Called by build_one() for each consumed item when audio_order is
        'no_repeat'.
        Uses file path (not songid) since party items are not in the library.
        """
        if not file_path:
            return
        played = self._cm.get_party_no_repeat_played(channel_id)
        if file_path not in played:
            played.append(file_path)
            self._cm.set_party_no_repeat_played(channel_id, played)

    def _get_played_files(self, channel_id: str) -> list:
        """
        Return the list of file paths already played in this channel.
        Uses the same state key as FolderQueueBuilder.
        """
        try:
            state = self._cm.get_show_state(channel_id, 0)
            return state.get("played_files", [])
        except Exception:
            return []
