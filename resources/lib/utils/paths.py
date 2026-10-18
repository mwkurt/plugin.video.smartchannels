# utils/paths.py
#
# OWNS:   resolve_path(), load_json(), load_json_strict(), JsonReadError,
#         save_json(), shared_root(),
#         normalize_share_path(), clean_path_setting(), smb_to_unc(),
#         path_join(), and the _s() string helper.
#         These are the ONLY implementations of these functions in the
#         entire codebase.  All other modules import from here.
#
# NEVER:  Kodi playback control, state logic, UI rendering, JSON-RPC calls.
#
# CALLERS: Any module may import and call these utilities.
#
# If you are writing a resolve_path(), load_json(), or save_json() anywhere
# other than this file, you are in the wrong place. Delete it and import this.

from __future__ import annotations

import json
import os

import xbmc
import xbmcaddon
import xbmcvfs

_ADDON_ID = "plugin.video.smartchannels"


def _get_profile() -> str:
    """Return the local addon profile directory path."""
    return xbmcvfs.translatePath(
        xbmcaddon.Addon(_ADDON_ID).getAddonInfo("profile"))


def clean_path_setting(raw) -> str:
    """
    Return a path typed or pasted into a setting with surrounding spaces and
    quotes removed (Windows "Copy as path" adds quotes).  None gives "".
    """
    return (raw or "").strip().strip('"').strip()


def normalize_share_path(raw: str) -> str:
    """
    Return a folder path in the form Kodi handles on every platform.
    Converts Windows UNC paths (\\\\Server\\share or //Server/share)
    to smb://Server/share, drops a trailing slash, and returns "" for an
    empty or bare "smb://" entry.  Other paths (smb://, nfs://, drive
    letters, local folders) are returned unchanged.
    """
    raw = clean_path_setting(raw)
    if raw in ("", "smb://", "smb:/"):
        return ""
    if raw.startswith("\\\\") or raw.startswith("//"):
        raw = raw.lstrip("\\/")
        raw = "smb://" + raw.replace("\\", "/")
    raw = raw.rstrip("/").rstrip("\\")
    if len(raw) == 2 and raw[1] == ":":
        raw += "\\"          # drive root: "C:" would mean "current folder"
    return raw


def smb_to_unc(path: str) -> str:
    """
    Convert smb://[user[:password]@]host/share/dir to \\\\host\\share\\dir
    so a Windows program (ffprobe) can open it.  Any other path is returned
    unchanged.  Windows uses its own login for the share; a user name and
    password in the Kodi path are dropped.
    """
    if not path or not path.lower().startswith("smb://"):
        return path
    host, _, tail = path[6:].partition("/")
    if "@" in host:
        host = host.rsplit("@", 1)[1]
    return "\\\\" + host + ("\\" + tail.replace("/", "\\") if tail else "")


def shared_root() -> str:
    """
    Return the shared storage root path if configured, else empty string.
    """
    try:
        raw = xbmcaddon.Addon(_ADDON_ID).getSetting("shared_storage_path")
    except Exception:
        raw = ""
    return normalize_share_path(raw)


def path_join(root: str, filename: str) -> str:
    """
    Join root and filename correctly for both local and network paths.
    Network paths (smb://, nfs://, etc.) use forward slash.
    Local paths use os.path.join.
    """
    if "://" in root:
        return root.rstrip("/") + "/" + filename
    return os.path.join(root, filename)


def _dir_exists(path: str) -> bool:
    """
    Return True if the directory at *path* exists and is accessible.

    xbmcvfs.exists() requires a trailing slash when checking SMB/NFS
    directory paths — without it Kodi's VFS layer treats the path as a
    file check and returns False even when the share is reachable.
    Local paths are unaffected by the trailing slash.
    """
    if "://" in path:
        return xbmcvfs.exists(path.rstrip("/") + "/")
    return xbmcvfs.exists(path)


def resolve_path(filename: str) -> str:
    """
    Return the full path for *filename*.

    Routes to the configured shared storage root when set, otherwise
    to the local addon profile directory.  Works for local drives,
    mapped drives, SMB, NFS.
    """
    profile = _get_profile()
    shared  = shared_root()
    if shared:
        if not _dir_exists(shared):
            try:
                xbmcvfs.mkdirs(shared)
            except Exception as exc:
                xbmc.log("[{}][paths] Cannot create shared dir {}: {}".format(
                    _ADDON_ID, shared, exc), xbmc.LOGWARNING)
        return path_join(shared, filename)
    return os.path.join(profile, filename)


class JsonReadError(Exception):
    """A JSON file that should be readable could not be read or parsed."""


_READ_ATTEMPTS = 3
_READ_RETRY_MS = (150, 400)    # pause before the 2nd and 3rd attempt


def _parent_reachable(path: str) -> bool:
    """
    Return True when the folder holding *path* can be reached.

    A network share that is down makes xbmcvfs.exists() answer False for a
    file that is really there, which looks the same as a file that was never
    written.  The same applies to a mapped drive that has gone offline.
    """
    if "://" in path:
        parent = path.rsplit("/", 1)[0]
    else:
        parent = os.path.dirname(path)
    return _dir_exists(parent) if parent else True


def load_json_strict(path: str, default):
    """
    Read and parse a JSON file from *path*.

    Returns *default* only when the file does not exist (and its folder can
    be reached).  A file that exists but cannot be read or parsed, or a
    folder that cannot be reached, raises JsonReadError.  A read that
    returns nothing or half a file - another device is overwriting it at
    that moment - is retried before giving up.

    Use this wherever the result is written back, so that a failed read is
    never mistaken for an empty file.
    """
    last_error = "not readable"
    for attempt in range(_READ_ATTEMPTS):
        if attempt:
            xbmc.sleep(_READ_RETRY_MS[attempt - 1])
        if not xbmcvfs.exists(path):
            if _parent_reachable(path):
                return default
            last_error = "folder not reachable"
            continue
        try:
            with xbmcvfs.File(path, "r") as f:
                return json.loads(f.read())
        except Exception as exc:
            last_error = str(exc)
    raise JsonReadError("{}: {}".format(path, last_error))


def load_json(path: str, default):
    """
    Read and parse a JSON file from *path*.
    Returns *default* if the file does not exist or cannot be parsed.

    For data that is read and then written back, use load_json_strict
    instead: this function cannot tell a missing file from a failed read.
    """
    try:
        return load_json_strict(path, default)
    except JsonReadError as exc:
        xbmc.log("[{}][paths] load_json failed {}".format(
            _ADDON_ID, exc), xbmc.LOGWARNING)
        return default


_WRITE_ATTEMPTS = 3
_WRITE_RETRY_MS = (250, 750)   # pause before the 2nd and 3rd attempt


def _write_file(path: str, text: str) -> bool:
    """Write *text* to *path* via xbmcvfs.File.  True on success."""
    with xbmcvfs.File(path, "w") as f:
        return f.write(text) is not False


def _write_shared(local_copy: str, path: str) -> bool:
    """Copy the local temp file to a shared / network path.  True on success.

    xbmcvfs.copy is tried first; for local mapped drives (no "://") a plain
    xbmcvfs.File write is the fallback.
    """
    if xbmcvfs.copy(local_copy, path):
        return True
    if "://" in path:
        return False
    with xbmcvfs.File(local_copy, "r") as src:
        return _write_file(path, src.read())


def save_json(path: str, data) -> bool:
    """
    Serialise *data* as JSON and write to *path*.

    Local profile paths: written directly via xbmcvfs.File.
    Shared / network paths: written to a local temp copy first, then
    copied to the destination.

    A failed write is retried (up to 3 attempts, short pauses) because a
    network share can refuse a write for a moment.  Returns True only when a
    write succeeded; a write that is still failing after the last attempt is
    logged and returns False.
    """
    profile   = _get_profile()
    json_str  = json.dumps(data, indent=2, ensure_ascii=False)
    is_shared = not path.startswith(profile)
    local_copy = (os.path.join(profile, os.path.basename(path))
                  if is_shared else "")

    for attempt in range(_WRITE_ATTEMPTS):
        if attempt:
            xbmc.sleep(_WRITE_RETRY_MS[attempt - 1])
        try:
            if is_shared:
                ok = (_write_file(local_copy, json_str)
                      and _write_shared(local_copy, path))
            else:
                ok = _write_file(path, json_str)
        except Exception as exc:
            ok = False
            xbmc.log("[{}][paths] save_json attempt {} failed {}: {}".format(
                _ADDON_ID, attempt + 1, path, exc), xbmc.LOGWARNING)
        if ok:
            if attempt:
                xbmc.log("[{}][paths] save_json succeeded on attempt {} for "
                         "{}".format(_ADDON_ID, attempt + 1, path),
                         xbmc.LOGINFO)
            return True

    xbmc.log("[{}][paths] save_json failed after {} attempts, write lost: "
             "{}".format(_ADDON_ID, _WRITE_ATTEMPTS, path), xbmc.LOGERROR)
    return False


def _s(addon: xbmcaddon.Addon, string_id: int, fallback: str = "") -> str:
    """Return localised string for *string_id*, falling back to *fallback*."""
    try:
        val = addon.getLocalizedString(string_id)
        return val if val else fallback
    except Exception:
        return fallback


# ---------------------------------------------------------------------------
# Data files that live in shared storage (or local profile when no shared
# path is configured).  queue_*.json files are discovered dynamically.
# ---------------------------------------------------------------------------
_SHARED_DATA_FILES = [
    "channels.json",
    "state.json",
    "schedules.json",
    "now_playing.json",
    "local_library.json",
    "songs_cache.json",
    "missing_durations.txt",
]


def _list_files_in_root(root: str) -> list:
    """Return basenames of all SmartChannels data files present in *root*."""
    found = []
    for name in _SHARED_DATA_FILES:
        path = path_join(root, name) if "://" in root else os.path.join(
            root, name)
        if xbmcvfs.exists(path):
            found.append(name)
    # Discover queue_*.json files dynamically.
    try:
        _, files = xbmcvfs.listdir(root)
        for fname in files:
            if fname.startswith("queue_") and fname.endswith(".json"):
                found.append(fname)
    except Exception as exc:
        xbmc.log("[{}][paths] _list_files_in_root listdir failed {}: {}".format(
            _ADDON_ID, root, exc), xbmc.LOGWARNING)
    return found


def migrate_storage_path(old_root: str, new_root: str) -> tuple:
    """Copy all SmartChannels data files from *old_root* to *new_root*.

    Returns (copied: int, failed: int).
    old_root and new_root are resolved directory paths (not filenames).
    Pass _get_profile() for local profile, shared_root() for shared.
    """
    files = _list_files_in_root(old_root)
    copied = 0
    failed = 0
    for fname in files:
        src = (path_join(old_root, fname) if "://" in old_root
               else os.path.join(old_root, fname))
        dst = (path_join(new_root, fname) if "://" in new_root
               else os.path.join(new_root, fname))
        try:
            ok = xbmcvfs.copy(src, dst)
            if ok:
                copied += 1
                xbmc.log("[{}][paths] migrate: copied {} → {}".format(
                    _ADDON_ID, fname, new_root))
            else:
                failed += 1
                xbmc.log("[{}][paths] migrate: copy failed {} → {}".format(
                    _ADDON_ID, fname, dst), xbmc.LOGWARNING)
        except Exception as exc:
            failed += 1
            xbmc.log("[{}][paths] migrate: exception copying {}: {}".format(
                _ADDON_ID, fname, exc), xbmc.LOGERROR)
    return copied, failed


def delete_files_in_root(root: str, filenames: list) -> None:
    """Delete *filenames* from *root*. Errors are logged, not raised."""
    for fname in filenames:
        path = (path_join(root, fname) if "://" in root
                else os.path.join(root, fname))
        try:
            if xbmcvfs.exists(path):
                xbmcvfs.delete(path)
                xbmc.log("[{}][paths] migrate: deleted old file {}".format(
                    _ADDON_ID, path))
        except Exception as exc:
            xbmc.log("[{}][paths] migrate: delete failed {}: {}".format(
                _ADDON_ID, path, exc), xbmc.LOGWARNING)
