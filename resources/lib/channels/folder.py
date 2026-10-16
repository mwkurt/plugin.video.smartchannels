"""
resources/lib/channels/folder.py
==================================

OWNS:   Queue building logic for Folder (directory source) channels.
        Walks a configured folder path recursively, finds all media
        files, and builds a playback queue in random or sequential order.

NEVER:  State reads/writes (through channel_manager.py).
        Kodi JSON-RPC calls (no library dependency — folder channels
        are explicitly for content NOT in the Kodi library).
        UI rendering, routing, playback control.

CALLERS: channel_manager.py only — via build_queue() dispatch.

Channel config keys used:
  folder_path  : str  — the folder to walk (SMB, local, or UNC path)
  randomize    : bool — True = random order; False = filename order
  recycle      : bool — True = restart when exhausted; False = stop
  queue_size   : int  — number of items to include in queue

Queue item format (matches normalize_ep output for compatibility):
  {
    "channel_id":  str,
    "_channel_id": str,
    "show_id":     0,
    "_show_id":    0,
    "episodeid":   -1,
    "movieid":     -1,
    "title":       str,    # filename without extension
    "season":      0,
    "episode":     0,
    "file":        str,    # full path to media file
    "is_folder_item": True,
  }
"""

from __future__ import annotations

import os
import random

import xbmc
import xbmcvfs

from resources.lib.channels.base import BaseQueueBuilder
from resources.lib.utils.logger  import log

# Media file extensions to include
_MEDIA_EXTS = {
    ".mkv", ".mp4", ".avi", ".mov", ".wmv", ".m4v",
    ".ts",  ".m2ts", ".mpg", ".mpeg", ".flv", ".webm",
}


class FolderQueueBuilder(BaseQueueBuilder):
    """
    Queue builder for Folder channels.
    Walks a folder path (recursively, including subdirectories) and
    builds a queue from the media files found there.
    """

    def build(self, channel: dict, target_size: int,
              current_queue=None, queued_files: list = None) -> list:
        """
        Build a Folder channel queue.

        current_queue is accepted for API compatibility but ignored —
        Folder channels always build fresh from the directory listing.
        The ordering (random or sequential) is re-applied each time.

        queued_files: list of file paths already in the current_queue.
        When provided, these files are excluded from the result so that
        top-up never duplicates files still waiting to be played.
        """
        channel_id  = channel["id"]
        folder_path = channel.get("folder_path", "")
        randomize   = channel.get("randomize", False)
        recycle     = channel.get("recycle", True)
        # no_repeat: play every file once before any repeat, then reset and
        # cycle again.  Distinct from recycle=False which stops permanently.
        # When no_repeat=True, filter out played files exactly like
        # recycle=False does, but on exhaustion clear the played list and
        # restart rather than stopping.
        no_repeat   = channel.get("no_repeat", False)

        if not folder_path:
            log("[FolderQueueBuilder] No folder_path in channel {}".format(
                channel_id), xbmc.LOGWARNING)
            return []

        # Normalise path for xbmcvfs
        norm_path = _normalise_path(folder_path)

        if not xbmcvfs.exists(_ensure_slash(norm_path)):
            # Try _accessible_path which tests multiple forms
            if not _accessible_path(norm_path):
                log("[FolderQueueBuilder] Folder not accessible: {}".format(
                    norm_path), xbmc.LOGWARNING)
                return []
            norm_path = _accessible_path(norm_path)

        # Walk folder recursively collecting media files
        media_files = []
        _walk(norm_path, media_files)

        if not media_files:
            log("[FolderQueueBuilder] No media files found in: {}".format(
                norm_path), xbmc.LOGWARNING)
            return []

        log("[FolderQueueBuilder] Found {} media files in {}".format(
            len(media_files), norm_path))

        # Track played files for recycle=False (stop when exhausted) and
        # no_repeat=True (reset and cycle again when exhausted).
        played = self._get_played_files(channel_id)

        if not recycle and played and set(media_files).issubset(set(played)):
            log("[FolderQueueBuilder] Channel '{}' exhausted "
                "(recycle=False)".format(channel["name"]))
            return []

        # no_repeat exhaustion: all files played — clear played list and
        # restart from the full file set so the cycle begins again.
        if no_repeat and played and set(media_files).issubset(set(played)):
            log("[FolderQueueBuilder] no_repeat cycle complete for '{}' "
                "— resetting played list".format(channel["name"]))
            self._cm.record_folder_file_played(channel_id, None)  # clear
            played = []

        # Filter out played files when recycle=False or no_repeat=True.
        if (not recycle or no_repeat) and played:
            remaining = [f for f in media_files if f not in played]
            if not remaining:
                # Shouldn't happen (exhaustion handled above) but be safe.
                if no_repeat:
                    self._cm.record_folder_file_played(channel_id, None)
                    remaining = list(media_files)
                else:
                    return []
            source_files = remaining
        else:
            source_files = media_files

        # Exclude files already sitting in the current queue (not yet played).
        # Without this, a folder with N files and threshold > N would add all
        # N files again on the very first top-up, before any file completes —
        # producing duplicates and ignoring recycle=False until the duplicates
        # are consumed.  queued_files is passed by topup_channel_queue only; the
        # initial build (queued_files=None) is unaffected.
        if queued_files:
            queued_set   = set(queued_files)
            source_files = [f for f in source_files if f not in queued_set]
            if not source_files:
                # Nothing to add that isn't already queued
                return []

        # Apply order
        if randomize:
            source_files = source_files[:]
            random.shuffle(source_files)
            # Safety net: if a resume position exists for any file in the
            # list, move it to position 0 so it always survives the
            # target_size slice below.  The primary resume guarantee is
            # that _resume_from_existing_queue returns the existing queue
            # without rebuilding — this is defence-in-depth only.
            try:
                channel_id = channel["id"]
                for _idx, _fp in enumerate(source_files):
                    if self._cm.has_resume_for_file(channel_id, _fp):
                        if _idx != 0:
                            source_files.insert(0, source_files.pop(_idx))
                            log("[FolderQueueBuilder] Moved resume file to "
                                "position 0: {}".format(_fp))
                        break
            except Exception as _re:
                log("[FolderQueueBuilder] Resume file pin error: {}".format(_re))
        else:
            source_files = sorted(source_files)

        # Wrap to target_size (with recycling)
        queue_files = []
        while len(queue_files) < target_size:
            needed = target_size - len(queue_files)
            queue_files.extend(source_files[:needed])
            if not recycle or len(source_files) == 0:
                break
            if len(queue_files) < target_size:
                if randomize:
                    random.shuffle(source_files)

        # Build queue items
        queue = []
        _default_secs = self._default_duration()

        for file_path in queue_files:
            queue.append(self._make_item(channel_id, file_path, _default_secs))

        log("[FolderQueueBuilder] Built queue of {} items for '{}'".format(
            len(queue), channel["name"]))
        return queue

    def _make_item(self, channel_id: str, file_path: str,
                   default_secs: int) -> dict:
        """Return one queue item dict for a folder file."""
        from resources.lib.utils.duration_cache import (
            get_folder_duration as _get_folder_dur)
        title = _title_from_path(file_path)
        duration, is_default = _get_folder_dur({"file": file_path},
                                               default_secs)
        if is_default:
            self._cm.record_missing_duration(
                channel_id,
                {"file": file_path, "title": title},
                "default_duration")
        return {
            "channel_id":          channel_id,
            "_channel_id":         channel_id,
            "show_id":             0,
            "_show_id":            0,
            "episodeid":           -1,
            "movieid":             -1,
            "title":               title,
            "tvshowtitle":         "",
            "season":              0,
            "episode":             0,
            "file":                file_path,
            "is_folder_item":      True,
            "is_movie":            False,
            "duration":            duration,
            "duration_is_default": is_default,
        }

    def _default_duration(self) -> int:
        try:
            return int(
                self._cm.addon.getSetting("folder_default_duration") or "120")
        except Exception:
            return 120

    def build_one(self, channel: dict, host_queue: list,
                  consumed_file: str = "") -> list:
        """
        Build exactly one replacement item for a Folder channel.

        Used for 1-for-1 replacement (natural end, skip, carousel pop, and
        interleaved-source replacement).  Folder channels always recycle, so
        this returns an item whenever the folder has any media file.

        host_queue is the queue the item will be appended to (consumed item
        already removed); consumed_file is the file of the item just
        consumed, so a new random cycle does not redraw it.  It is the authority for what comes next:
          - sequential: the file after the last item in host_queue that came
            from this channel (wrapping to the first file);
          - random: Random/No Repeat — a persisted cycle of not-yet-drawn
            files that starts from the whole folder; each draw is random
            among cycle files not in host_queue (and not consumed_file).
        """
        channel_id = channel["id"]
        folder_path = channel.get("folder_path", "")
        if not folder_path:
            return []
        norm_path = _normalise_path(folder_path)
        if not xbmcvfs.exists(_ensure_slash(norm_path)):
            norm_path = _accessible_path(norm_path)
            if not norm_path:
                log("[FolderQueueBuilder] Folder not accessible: {}".format(
                    folder_path), xbmc.LOGWARNING)
                return []
        media_files = []
        _walk(norm_path, media_files)
        if not media_files:
            return []

        pool = sorted(set(media_files))
        queued = [i.get("file", "") for i in (host_queue or [])
                  if i.get("file")
                  and (i.get("_channel_id") or i.get("channel_id")) == channel_id]
        last = queued[-1] if queued else None

        if channel.get("randomize", False):
            # Random is always Random/No Repeat: every file is drawn once (in
            # random order) before any file is drawn again.  The not-yet-drawn
            # files are kept in state and shared by every queue this folder
            # feeds.  Each cycle starts from the whole folder; a draw never
            # takes a file already waiting in the host queue or the one just
            # consumed (such files stay in the cycle for a later draw).
            cycle = self._cm.get_folder_cycle(channel_id)
            unplayed = ([f for f in cycle if f in pool]
                        if cycle is not None else [])
            if not unplayed:
                unplayed = list(pool)
            queued_set = set(queued)
            candidates = ([f for f in unplayed
                           if f not in queued_set and f != consumed_file]
                          or [f for f in unplayed if f not in queued_set]
                          or [f for f in unplayed if f != last]
                          or unplayed)
            chosen = random.choice(candidates)
            unplayed.remove(chosen)
            self._cm.set_folder_cycle(channel_id, unplayed)
        else:
            if last in pool:
                chosen = pool[(pool.index(last) + 1) % len(pool)]
            else:
                chosen = pool[0]

        return [self._make_item(channel_id, chosen, self._default_duration())]

    def _get_played_files(self, channel_id: str) -> list:
        """
        Return the list of file paths already played in this channel.
        Uses the channel state stored by channel_manager.
        Returns empty list if no state exists.
        """
        try:
            state = self._cm.get_show_state(channel_id, 0)
            return state.get("played_files", [])
        except Exception:
            return []

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _normalise_path(path: str) -> str:
    """
    Normalise a folder path for xbmcvfs:
    - Convert Windows UNC paths (\\\\server\\share) to smb://
    - Encode literal spaces as %20 in network paths
    - Strip trailing separators
    """
    if not path:
        return path
    # UNC → smb://
    if path.startswith("\\\\") or path.startswith("//"):
        path = "smb://" + path.lstrip("\\/").replace("\\", "/")
    # Strip trailing separators
    path = path.rstrip("/").rstrip("\\")
    # Encode spaces in network paths
    if "://" in path:
        path = path.replace(" ", "%20")
    return path


def is_local_drive_path(path: str) -> bool:
    """Return True for a Windows drive-letter path such as D:\\Media.

    Such a path only exists on the device that has that drive.  Network
    (smb://, nfs://) and UNC paths are not local-drive paths.
    """
    return bool(path) and len(path) >= 2 and path[0].isalpha() \
        and path[1] == ":" and "://" not in path


def _ensure_slash(path: str) -> str:
    """Add trailing slash/separator to a path for xbmcvfs directory ops."""
    if "://" in path:
        return path.rstrip("/") + "/"
    # Local path — add trailing separator (backslash on Windows, slash elsewhere)
    if path and path[-1] not in ("/", "\\"):
        return path + "\\"
    return path


def _accessible_path(path: str) -> str:
    """
    Return the accessible form of a path, or empty string if not reachable.
    Tries multiple forms to handle Windows local, mapped drive, and SMB paths.
    """
    if not path:
        return ""
    candidates = [
        _ensure_slash(path),
        path + "/",
        path,
    ]
    # For network paths also try with spaces decoded
    if "://" in path:
        decoded = path.replace("%20", " ")
        candidates.append(_ensure_slash(decoded))
        candidates.append(decoded)
    for candidate in candidates:
        try:
            if xbmcvfs.exists(candidate):
                return candidate
        except Exception:
            pass
    return ""


def _walk(path: str, results: list) -> None:
    """
    Recursively walk path, collecting media files.
    Includes subdirectories.
    """
    acc = _accessible_path(path)
    if not acc:
        log("[FolderQueueBuilder] listdir: path not accessible: {}".format(
            path), xbmc.LOGWARNING)
        return
    try:
        dirs, files = xbmcvfs.listdir(acc)
    except Exception as e:
        log("[FolderQueueBuilder] listdir error {}: {}".format(path, e),
            xbmc.LOGWARNING)
        return

    for fname in (files or []):
        ext = os.path.splitext(fname.lower())[1]
        if ext in _MEDIA_EXTS:
            if "://" in path:
                results.append(path.rstrip("/") + "/" + fname)
            else:
                results.append(os.path.join(path, fname))

    for d in sorted(dirs or []):
        if "://" in path:
            sub = path.rstrip("/") + "/" + d
        else:
            sub = os.path.join(path, d)
        _walk(sub, results)


def _title_from_path(file_path: str) -> str:
    """
    Extract a display title from a file path.
    Returns filename without extension, with %20 decoded to spaces.
    """
    if "://" in file_path:
        basename = file_path.rsplit("/", 1)[-1]
    else:
        basename = os.path.basename(file_path)
    title, _ = os.path.splitext(basename)
    return title.replace("%20", " ")
