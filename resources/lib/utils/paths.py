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

from resources.lib.utils.logger import log

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

    xbmcvfs.exists() needs a trailing slash to check a directory: without
    it Kodi's VFS layer treats the path as a file check and can return
    False for a folder that is really there.  That holds for SMB/NFS paths
    and for local ones, so both get the trailing separator.  Before 3.1.149
    a local folder was checked without it, and a missing file in the add-on
    profile was reported as "folder not reachable" once a minute.
    """
    if not path:
        return False
    if "://" in path:
        return xbmcvfs.exists(path.rstrip("/") + "/")
    return xbmcvfs.exists(path.rstrip("/\\") + os.sep)


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
                log("[paths] Cannot create shared dir {}: {}".format(
                    shared, exc), xbmc.LOGWARNING)
        return path_join(shared, filename)
    return os.path.join(profile, filename)


class JsonReadError(Exception):
    """A JSON file that should be readable could not be read or parsed."""


_READ_ATTEMPTS = 3
_READ_RETRY_MS = (150, 400)    # pause before the 2nd and 3rd attempt

# (path, leftover length) pairs already reported, so a file that stays in this
# state is logged once per Kodi session and not on every read.
_LEFTOVER_LOGGED: set = set()


def _parse_json_text(text: str, path: str):
    """Parse *text* as JSON, ignoring leftover text after a complete value.

    A write to a network share that is shorter than the file it replaces can
    leave the tail of the old content behind: a complete, valid JSON object
    followed by junk.  json.loads rejects that ("Extra data"); here the valid
    object is used and the leftover is reported.  Anything else that does not
    parse (empty, half-written, not JSON) still raises, so it is retried.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        if not exc.msg.startswith("Extra data"):
            raise
        body = text.lstrip()
        obj, end = json.JSONDecoder().raw_decode(body)
        if not isinstance(obj, (dict, list)):
            raise
        left = len(body) - end
        if (path, left) not in _LEFTOVER_LOGGED:
            _LEFTOVER_LOGGED.add((path, left))
            log("[paths] {} has {} characters of leftover text "
                     "after valid JSON - ignored; the next save rewrites "
                     "the file".format(path, left),
                     xbmc.LOGWARNING)
        return obj


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
                return _parse_json_text(f.read(), path)
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
        log("[paths] load_json failed {}".format(
            exc), xbmc.LOGWARNING)
        return default


_WRITE_ATTEMPTS = 3
_WRITE_RETRY_MS = (250, 750)   # pause before the 2nd and 3rd attempt


def _write_file(path: str, text: str) -> bool:
    """Write *text* to *path* via xbmcvfs.File.  True on success."""
    with xbmcvfs.File(path, "w") as f:
        return f.write(text) is not False


def _reads_back(path: str) -> bool:
    """True when *path* now holds a complete JSON document (strict: leftover
    text after the document counts as bad).  Read twice, 150 ms apart, so a
    moment when another device is replacing the file is not mistaken for a
    bad write."""
    for attempt in range(2):
        if attempt:
            xbmc.sleep(150)
        try:
            with xbmcvfs.File(path, "r") as f:
                json.loads(f.read())
            return True
        except Exception:
            continue
    return False


def _verify_shared_write(local_copy: str, path: str) -> bool:
    """Check the file just copied to a network share and repair a bad write.

    A copy over an existing file on a share can fail to cut the old content
    (the share refuses the delete or truncate while the file is busy), leaving
    leftover text after the new content.  If the file does not read back as
    valid JSON it is deleted and copied again.  Returns True when it reads
    back, False when it still does not (the caller retries).
    """
    if _reads_back(path):
        return True
    log("[paths] {} did not read back as valid JSON after the write "
             "- deleting it and writing it again".format(path),
             xbmc.LOGWARNING)
    try:
        xbmcvfs.delete(path)
    except Exception:
        pass
    return bool(xbmcvfs.copy(local_copy, path)) and _reads_back(path)


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
    copied to the destination.  A .json file copied to a share is read back
    and, if it is not valid JSON (an old tail left behind), deleted and
    copied again.

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
                if ok and path.endswith(".json"):
                    ok = _verify_shared_write(local_copy, path)
            else:
                ok = _write_file(path, json_str)
        except Exception as exc:
            ok = False
            log("[paths] save_json attempt {} failed {}: {}".format(
                attempt + 1, path, exc), xbmc.LOGWARNING)
        if ok:
            if attempt:
                log("[paths] save_json succeeded on attempt {} for "
                         "{}".format(attempt + 1, path),
                         xbmc.LOGINFO)
            return True

    log("[paths] save_json failed after {} attempts, write lost: "
             "{}".format(_WRITE_ATTEMPTS, path), xbmc.LOGERROR)
    return False


def remove_local_copy(filename: str) -> bool:
    """Delete the local working copy (and any .tmp) of a shared data file.

    save_json writes a shared file through a copy of the same name in the
    local profile folder and leaves that copy behind.  Only used when shared
    storage is active; with no shared storage the profile file IS the data
    file and is never touched here.  True when a copy was removed.
    """
    if not shared_root():
        return False
    name = os.path.basename(filename)
    if not name:
        return False
    removed = False
    for suffix in ("", ".tmp"):
        path = os.path.join(_get_profile(), name + suffix)
        try:
            if xbmcvfs.exists(path) and xbmcvfs.delete(path):
                removed = True
        except Exception as exc:
            log("[paths] remove_local_copy failed {}: {}".format(
                path, exc), xbmc.LOGWARNING)
    return removed


def local_queue_files() -> list:
    """Basenames of queue_*.json files in the local profile folder, or an
    empty list when shared storage is not in use (then they are the data)."""
    if not shared_root():
        return []
    try:
        _, files = xbmcvfs.listdir(_get_profile())
    except Exception as exc:
        log("[paths] local_queue_files listdir failed: {}".format(
            exc), xbmc.LOGWARNING)
        return []
    return [f for f in files if f.startswith("queue_") and f.endswith(".json")]


def channel_lock_files() -> list:
    """Full paths of every channel_lock_<id>.json in the local profile folder
    and in the shared folder.  channel_lock_owned.json (this device's own
    record of the channel it holds) is not a channel lock and is left out."""
    roots = [_get_profile()]
    shared = shared_root()
    if shared:
        roots.append(shared)
    found = []
    for root in roots:
        try:
            _, files = xbmcvfs.listdir(root)
        except Exception as exc:
            log("[paths] channel_lock_files listdir failed: {}".format(
                exc), xbmc.LOGWARNING)
            continue
        for name in files:
            if (name.startswith("channel_lock_") and name.endswith(".json")
                    and name != "channel_lock_owned.json"):
                found.append(path_join(root, name))
    return found


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


# Files the add-on writes whose names are not fixed: queues, saved copies of
# the state, kept cursors and channel locks.
_DATA_FILE_PREFIXES = ("queue_", "cursor_kept_", "state.bak", "state.day",
                       "channel_lock_", "chanstate_")


def is_data_file(name: str) -> bool:
    """True when *name* is a data file the add-on created (not a setting and
    not this device's id).  Used by Delete All Addon Data."""
    if name.endswith(".tmp"):
        name = name[:-4]
    if name in _SHARED_DATA_FILES:
        return True
    return name.endswith(".json") and name.startswith(_DATA_FILE_PREFIXES)


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
            if fname.endswith(".json") and fname.startswith(
                    ("queue_", "chanstate_")):
                found.append(fname)
    except Exception as exc:
        log("[paths] _list_files_in_root listdir failed {}: {}".format(
            root, exc), xbmc.LOGWARNING)
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
                log("[paths] migrate: copied {} → {}".format(
                    fname, new_root), xbmc.LOGDEBUG)
            else:
                failed += 1
                log("[paths] migrate: copy failed {} → {}".format(
                    fname, dst), xbmc.LOGWARNING)
        except Exception as exc:
            failed += 1
            log("[paths] migrate: exception copying {}: {}".format(
                fname, exc), xbmc.LOGERROR)
    return copied, failed


def delete_files_in_root(root: str, filenames: list) -> None:
    """Delete *filenames* from *root*. Errors are logged, not raised."""
    for fname in filenames:
        path = (path_join(root, fname) if "://" in root
                else os.path.join(root, fname))
        try:
            if xbmcvfs.exists(path):
                xbmcvfs.delete(path)
                log("[paths] migrate: deleted old file {}".format(
                    path), xbmc.LOGDEBUG)
        except Exception as exc:
            log("[paths] migrate: delete failed {}: {}".format(
                path, exc), xbmc.LOGWARNING)
