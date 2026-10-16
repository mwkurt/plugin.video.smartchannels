"""
resources/lib/utils/duration_cache.py
======================================
Duration utilities for Smart TV Channels.

OWNS:
  - Resolving the NFO file path for any queue item
  - Reading durationinseconds from NFO files (TV episodes and movies)
  - Reading / writing companion NFO files for Folder channel items
  - Formatting duration seconds as a human-readable string

NEVER:
  - State reads/writes (channel_manager.py owns those)
  - Queue file access (channel_manager.py owns that)
  - Playback control (service.py owns that)
  - Any Kodi JSON-RPC calls (library.py owns that)

CALLERS:
  - channels/base.py  (normalize_ep, normalize_movie)
  - channels/folder.py (get_folder_duration)
  - channel_manager.py (capture_folder_duration, record_missing_duration)
  - ui/side_panel.py   (format_duration for display)

NFO CONVENTION:
  Episode / movie NFO sits alongside the video file with the same
  base name:
    /path/to/S01E01 - Title.mkv
    /path/to/S01E01 - Title.nfo   <- read this

  XPath:  fileinfo/streamdetails/video/durationinseconds

  For folder items with no Sonarr/Radarr NFO, a minimal companion NFO
  is written by write_companion_nfo() after first playback.

DURATION FIELD CONTRACT:
  - Always an integer number of seconds
  - > 0  means a real, confirmed duration
  - == 0 means "could not be read" (item should be skipped from queue
    for all channel types — duration=0 must never enter a queue)
  - Pre-1.1.7a queue items have no "duration" key at all;
    callers use item.get("duration", 0)
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET

import xbmc
import xbmcvfs

from resources.lib.utils.logger import log

# ---------------------------------------------------------------------------
# Public: duration reading
# ---------------------------------------------------------------------------

def get_duration(item: dict) -> int:
    """
    Read duration in seconds from the NFO file for a TV episode or movie.

    Returns an integer > 0 on success.
    Returns 0 if:
      - item has no "file" key
      - NFO file does not exist           (reason: "no_nfo")
      - NFO exists but has no duration    (reason: "no_duration")
      - NFO cannot be parsed             (reason: "parse_error")

    Logs a LOGWARNING for every failure so the Kodi log is searchable.
    Does NOT write to missing_durations.txt — that is the caller's job
    (channel_manager.record_missing_duration).
    """
    file_path = item.get("file", "")
    if not file_path:
        log("[duration_cache] get_duration: item has no file path",
            xbmc.LOGWARNING)
        return 0

    nfo_path = _nfo_path_for(file_path)
    if not nfo_path or not xbmcvfs.exists(nfo_path):
        _warn(item, nfo_path or "", "no_nfo")
        return 0

    duration = _read_nfo_duration(nfo_path)
    if duration <= 0:
        _warn(item, nfo_path, "no_duration")
        return 0

    return duration


def get_folder_duration(item: dict, default_seconds: int) -> tuple:
    """
    Return (duration, is_default) for a Folder channel item.

    If a companion NFO exists alongside the video file and contains a
    valid durationinseconds value, returns (real_duration, False).

    If no companion NFO exists (or it has no duration), returns
    (default_seconds, True).  The item IS added to the queue with the
    default — folder items are never skipped for missing duration.

    default_seconds: the user-configured default folder item duration,
    already converted from minutes to seconds by the caller.
    """
    file_path = item.get("file", "")
    if file_path:
        nfo_path = _nfo_path_for(file_path)
        if nfo_path and xbmcvfs.exists(nfo_path):
            duration = _read_nfo_duration(nfo_path)
            if duration > 0:
                log("[duration_cache] folder item has companion NFO "
                    "duration={}s: {}".format(duration, file_path))
                return duration, False

    log("[duration_cache] folder item using default duration={}s: {}".format(
        default_seconds, file_path))
    return default_seconds, True


# ---------------------------------------------------------------------------
# Public: companion NFO writing
# ---------------------------------------------------------------------------

def write_companion_nfo(file_path: str, duration_seconds: int) -> bool:
    """
    Write a minimal companion NFO alongside file_path containing the
    captured duration.

    Returns True on success, False on any failure.
    Never raises — all exceptions are caught and logged.

    The NFO format matches Sonarr/Radarr output so it is readable by
    any Kodi addon that parses NFO files.
    """
    if not file_path or duration_seconds <= 0:
        log("[duration_cache] write_companion_nfo: invalid args "
            "file={} duration={}".format(file_path, duration_seconds),
            xbmc.LOGWARNING)
        return False

    nfo_path = _nfo_path_for(file_path)
    if not nfo_path:
        log("[duration_cache] write_companion_nfo: cannot resolve NFO "
            "path for {}".format(file_path), xbmc.LOGWARNING)
        return False

    content = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<fileinfo>\n'
        '    <streamdetails>\n'
        '        <video>\n'
        '            <durationinseconds>{}</durationinseconds>\n'
        '        </video>\n'
        '    </streamdetails>\n'
        '</fileinfo>\n'
    ).format(int(duration_seconds))

    try:
        f = xbmcvfs.File(nfo_path, "w")
        result = f.write(content)
        f.close()
        if result:
            log("[duration_cache] write_companion_nfo: wrote {}s to "
                "{}".format(duration_seconds, nfo_path))
            return True
        else:
            log("[duration_cache] write_companion_nfo: xbmcvfs.File.write "
                "returned False for {}".format(nfo_path), xbmc.LOGWARNING)
            return False
    except Exception as e:
        log("[duration_cache] write_companion_nfo: error writing {}: "
            "{}".format(nfo_path, e), xbmc.LOGWARNING)
        return False


# ---------------------------------------------------------------------------
# Public: display formatting
# ---------------------------------------------------------------------------

def format_duration(seconds: int) -> str:
    """
    Format an integer number of seconds as a human-readable string.

    Examples:
      0       -> ""          (unknown — caller hides the field)
      45      -> "45 sec"
      600     -> "10 min"
      3720    -> "1 hr 2 min"
      5400    -> "1 hr 30 min"

    Used by side_panel._format_queue_item() to append duration to label2.
    """
    if seconds <= 0:
        return ""
    if seconds < 60:
        return "{} sec".format(seconds)
    minutes = seconds // 60
    if minutes < 60:
        return "{} min".format(minutes)
    hours   = minutes // 60
    mins    = minutes % 60
    if mins == 0:
        return "{} hr".format(hours)
    return "{} hr {} min".format(hours, mins)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _nfo_path_for(file_path: str) -> str:
    """
    Return the expected NFO file path for a video file.

    Strips the video file extension and appends .nfo.
    Handles both local paths and network paths (smb://, nfs://).

    Returns empty string if the path cannot be resolved.
    """
    if not file_path:
        return ""

    # Network path: use string manipulation (os.path.splitext is
    # unreliable for smb:// and nfs:// URLs on some platforms)
    if "://" in file_path:
        # Strip query string if present
        base = file_path.split("?")[0]
        # Find last dot after last slash
        last_slash = base.rfind("/")
        last_dot   = base.rfind(".")
        if last_dot > last_slash and last_dot > 0:
            return base[:last_dot] + ".nfo"
        return base + ".nfo"

    # Local / UNC path
    base, _ = os.path.splitext(file_path)
    if not base:
        return ""
    return base + ".nfo"


def _read_nfo_duration(nfo_path: str) -> int:
    """
    Parse an NFO file and return durationinseconds as an integer.

    Looks for:
      fileinfo/streamdetails/video/durationinseconds

    Returns 0 on any parse failure or if the element is missing/empty.
    """
    try:
        f = xbmcvfs.File(nfo_path, "r")
        raw = f.read()
        f.close()
    except Exception as e:
        log("[duration_cache] _read_nfo_duration: read error {}: {}".format(
            nfo_path, e), xbmc.LOGWARNING)
        return 0

    if not raw:
        return 0

    # Sonarr/Radarr writes multi-episode NFOs as two consecutive
    # <episodedetails> root elements in one file — invalid XML that
    # ET.fromstring() rejects with "junk after document element".
    # Wrap in a synthetic root so all episodes become valid children,
    # then search across them.  The strip() removes a leading XML
    # declaration (<?xml ...?>) which ET rejects inside a wrapper.
    def _parse(text):
        try:
            return ET.fromstring(text)
        except ET.ParseError:
            return None

    root = _parse(raw)
    if root is None:
        # Strip XML declaration if present, wrap, retry
        stripped = raw.strip()
        if stripped.startswith("<?"):
            end = stripped.find("?>")
            if end != -1:
                stripped = stripped[end + 2:].lstrip()
        wrapped = "<_root>{}</_root>".format(stripped)
        root = _parse(wrapped)
        if root is None:
            log("[duration_cache] _read_nfo_duration: XML parse error {}: "
                "could not parse even with synthetic root".format(nfo_path),
                xbmc.LOGWARNING)
            return 0

    elem = root.find(".//durationinseconds")

    if elem is None or not (elem.text or "").strip():
        return 0

    try:
        val = int(float(elem.text.strip()))
        return val if val > 0 else 0
    except (ValueError, TypeError):
        return 0


def _warn(item: dict, nfo_path: str, reason: str) -> None:
    """Log a LOGWARNING for a missing/invalid NFO. Caller records to file."""
    show  = item.get("tvshowtitle", item.get("title", ""))
    title = item.get("title", "")
    ep    = "S{:02d}E{:02d}".format(
        int(item.get("season", 0) or 0),
        int(item.get("episode", 0) or 0)) if item.get("season") else ""
    file_ = item.get("file", "")
    log(
        "[duration_cache] Duration skip: show=\"{}\" title=\"{}\" ep=\"{}\" "
        "file=\"{}\" nfo=\"{}\" reason=\"{}\"".format(
            show, title, ep, file_, nfo_path, reason),
        xbmc.LOGWARNING)
