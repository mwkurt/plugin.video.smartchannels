"""
resources/lib/utils/ffprobe_scanner.py
=======================================
Batch NFO writer using ffprobe for duration detection.

OWNS:
  - Finding ffprobe executable
  - Walking folder trees for video files
  - Running ffprobe subprocess and parsing output
  - Calling write_companion_nfo() for each hit

NEVER:
  - UI (that is ffprobe_wizard.py)
  - State reads/writes (channel_manager.py)
  - Queue access (channel_manager.py)
  - Playback control (service.py)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import xbmc
import xbmcvfs

from resources.lib.utils.duration_cache import get_duration, write_companion_nfo
from resources.lib.utils.logger import log
from resources.lib.utils.paths import clean_path_setting, smb_to_unc

VIDEO_EXTENSIONS = {
    ".mkv", ".mp4", ".avi", ".m4v", ".ts", ".mov",
    ".wmv", ".flv", ".m2ts", ".mpg", ".mpeg",
}


def find_ffprobe(explicit_path=""):
    """
    Return absolute path to ffprobe executable, or None if not found.
    If explicit_path is set, only that path is tried — no PATH fallback.
    If explicit_path is blank, searches PATH.
    """
    explicit_path = clean_path_setting(explicit_path)
    if explicit_path:
        # Accept a smb:// or UNC path, a file, or the folder that holds it.
        translated = xbmcvfs.translatePath(smb_to_unc(explicit_path))
        candidates = [translated]
        if os.path.isdir(translated):
            candidates = [os.path.join(translated, "ffprobe.exe"),
                          os.path.join(translated, "ffprobe")]
        elif not os.path.splitext(translated)[1]:
            candidates.append(translated + ".exe")
        for candidate in candidates:
            if os.path.isfile(candidate):
                log("[ffprobe_scanner] find_ffprobe: using explicit path: "
                    "{}".format(candidate))
                return candidate
        log("[ffprobe_scanner] find_ffprobe: explicit path not found: "
            "{}".format(explicit_path), xbmc.LOGWARNING)
        # Do NOT fall through to PATH search — the user set a specific path
        # and it wasn't valid. Return None so the wizard shows an error.
        return None

    found = shutil.which("ffprobe") or shutil.which("ffprobe.exe")
    if found:
        log("[ffprobe_scanner] find_ffprobe: found on PATH: {}".format(found))
        return found

    log("[ffprobe_scanner] find_ffprobe: not found", xbmc.LOGWARNING)
    return None


def scan_folder(folder_path, ffprobe_exe, progress_callback=None,
                cancel_check=None):
    """
    Walk folder_path recursively. For each video file found:
      - Skip if a valid NFO already exists (get_duration returns > 0)
      - Run ffprobe to read duration
      - Call write_companion_nfo() on success

    progress_callback(current, total, filename): called per file processed.
    cancel_check(): returns True if the user cancelled.

    Returns dict:
      {
        "scanned":   int,   # total video files found
        "written":   int,   # NFOs written this run
        "skipped":   int,   # already had a valid duration/NFO
        "failed":    int,   # ffprobe failed or duration == 0
        "cancelled": bool,  # True if user cancelled mid-scan
      }
    """
    result = {
        "scanned":   0,
        "written":   0,
        "skipped":   0,
        "failed":    0,
        "cancelled": False,
    }

    # Collect all video files first so we can report accurate totals.
    video_files = _collect_video_files(folder_path)
    total = len(video_files)
    log("[ffprobe_scanner] scan_folder: found {} video files under "
        "{}".format(total, folder_path))

    for idx, file_path in enumerate(video_files):
        if cancel_check and cancel_check():
            log("[ffprobe_scanner] scan_folder: cancelled by user at "
                "{}/{}".format(idx, total))
            result["cancelled"] = True
            break

        filename = os.path.basename(file_path)
        if progress_callback:
            progress_callback(idx, total, filename)

        result["scanned"] += 1

        # Check for existing valid NFO via the public duration_cache API.
        # get_duration() expects a dict with a "file" key.
        existing = get_duration({"file": file_path})
        if existing > 0:
            log("[ffprobe_scanner] skipping (has duration={}s): "
                "{}".format(existing, file_path))
            result["skipped"] += 1
            continue

        # Translate special:// and smb:// paths to a local/UNC path that
        # ffprobe can handle.  If translation leaves another network prefix
        # (nfs://) intact, ffprobe cannot use it — count as failed.
        local_path = smb_to_unc(xbmcvfs.translatePath(file_path))
        if "://" in local_path:
            log("[ffprobe_scanner] cannot translate to local path, "
                "skipping: {}".format(file_path), xbmc.LOGWARNING)
            result["failed"] += 1
            continue

        duration = _run_ffprobe(local_path, ffprobe_exe)
        if duration <= 0:
            log("[ffprobe_scanner] ffprobe returned no duration for: "
                "{}".format(file_path), xbmc.LOGWARNING)
            result["failed"] += 1
            continue

        ok = write_companion_nfo(file_path, duration)
        if ok:
            log("[ffprobe_scanner] wrote NFO ({}s) for: "
                "{}".format(duration, file_path))
            result["written"] += 1
        else:
            log("[ffprobe_scanner] write_companion_nfo failed for: "
                "{}".format(file_path), xbmc.LOGWARNING)
            result["failed"] += 1

    log("[ffprobe_scanner] scan_folder complete: "
        "scanned={scanned} written={written} skipped={skipped} "
        "failed={failed} cancelled={cancelled}".format(**result))
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _collect_video_files(folder_path):
    """
    Walk folder_path recursively and return a sorted list of all video
    file paths whose extension is in VIDEO_EXTENSIONS.
    Uses xbmcvfs.listdir for network-path compatibility.
    """
    found = []
    _walk(folder_path, found)
    found.sort()
    return found


def _walk(path, accumulator):
    """Recursive walk using xbmcvfs.listdir to support network paths."""
    try:
        dirs, files = xbmcvfs.listdir(path)
    except Exception as e:
        log("[ffprobe_scanner] _walk: cannot list {}: {}".format(path, e),
            xbmc.LOGWARNING)
        return

    # Normalise the base path separator for concatenation.
    base = path.rstrip("/").rstrip("\\")
    sep = "/" if ("://" in path or path.startswith("/")) else os.sep

    for filename in files:
        _, ext = os.path.splitext(filename)
        if ext.lower() in VIDEO_EXTENSIONS:
            accumulator.append(base + sep + filename)

    for dirname in dirs:
        if not dirname:
            continue
        _walk(base + sep + dirname, accumulator)


def _run_ffprobe(file_path, ffprobe_exe):
    """
    Run ffprobe on file_path and return duration in seconds as int.
    Returns 0 on any failure (timeout, parse error, missing stream).

    Command: ffprobe -v quiet -print_format json -show_streams -show_format
    Parses the first video stream's duration, falls back to format duration.
    Timeout: 30 seconds per file.
    """
    cmd = [
        ffprobe_exe,
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        file_path,
    ]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            creationflags=(subprocess.CREATE_NO_WINDOW
                           if hasattr(subprocess, "CREATE_NO_WINDOW") else 0),
        )
    except subprocess.TimeoutExpired:
        log("[ffprobe_scanner] _run_ffprobe: timeout on: "
            "{}".format(file_path), xbmc.LOGWARNING)
        return 0
    except Exception as e:
        log("[ffprobe_scanner] _run_ffprobe: subprocess error: "
            "{}".format(e), xbmc.LOGWARNING)
        return 0

    if proc.returncode != 0:
        log("[ffprobe_scanner] _run_ffprobe: non-zero exit {} for: "
            "{}".format(proc.returncode, file_path), xbmc.LOGWARNING)
        return 0

    try:
        data = json.loads(proc.stdout.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError) as e:
        log("[ffprobe_scanner] _run_ffprobe: JSON parse error: "
            "{}".format(e), xbmc.LOGWARNING)
        return 0

    # Try video stream duration first.
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            raw = stream.get("duration", "")
            if raw:
                try:
                    val = int(float(raw))
                    if val > 0:
                        return val
                except (ValueError, TypeError):
                    pass

    # Fall back to format-level duration.
    raw = data.get("format", {}).get("duration", "")
    if raw:
        try:
            val = int(float(raw))
            if val > 0:
                return val
        except (ValueError, TypeError):
            pass

    return 0
