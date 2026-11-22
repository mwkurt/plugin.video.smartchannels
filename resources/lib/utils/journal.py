"""
resources/lib/utils/journal.py
==============================
Append-only evidence journal (3.1.140).

Why it exists
-------------
kodi.log keeps only the current and the previous session, and its pop lines
do not say which show, which episode or which position was involved.  When a
channel's positions do not add up, nothing could show why.  The journal
records every pop, draw, wrap, skip and position change as one JSON line, so
what happened (and on which device, and when) can be read back later from the
files alone.

What it is
----------
* One JSON object per line:  {"t": "...", "dev": "...", "ev": "...", ...}
* Written to the add-on profile, one file per device per hour
  (journal_<device>_<YYYYMMDD>_<HH>.jsonl), buffered and flushed every few
  seconds, so a draw never waits for a disk or a network share.
* Copied to <shared folder>/journals/ every few minutes and at shutdown, so
  the files of all devices end up in one place and in the backup.
* The previous session's kodi.log (kodi.old.log) is copied next to them when
  the service starts, so a restart no longer destroys the evidence.
* Files older than JOURNAL_KEEP_DAYS days are deleted.
* Bulky state-save lines (DEBUG_ONLY_EVENTS) are written only when the Log
  level setting is Debug; the evidence a normal review needs is always kept.

This module only writes evidence.  It never changes playback state, and every
function swallows its own errors: the journal must never break playback.
"""

import datetime
import json
import os
import re
import sys
import threading
import time
import traceback

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from resources.lib.utils.logger import is_debug, log

_ADDON_ID = "plugin.video.smartchannels"

JOURNAL_SUBDIR     = "journals"
JOURNAL_PREFIX     = "journal_"
JOURNAL_SUFFIX     = ".jsonl"
OLD_LOG_PREFIX     = "kodi_old_"
OLD_LOG_SUFFIX     = ".log"
JOURNAL_KEEP_DAYS  = 5
OLD_LOGS_KEEP      = 5          # per device
BACKUP_DAYS        = 3          # journal days put into a backup zip
FLUSH_SECONDS      = 10
FLUSH_MAX_LINES    = 40
SYNC_SECONDS       = 300
BUFFER_HARD_LIMIT  = 5000       # lines; older ones are dropped, never memory

# Lines that record every state.json save and every clock check: about 40% of
# the journal's size, and not used by a normal overnight review.  They are
# written only at Log level Debug (3.1.165).
DEBUG_ONLY_EVENTS = frozenset((
    "state_write", "chanstate_write", "clock_verified", "clock_table",
    "memory_behind"))

# Home-window property that remembers when the last playback ended or was
# stopped (set by service.py through note_playback_end), so the backup and
# journal-copy log lines can say how long after a video the copy was tried.
_PLAY_END_PROP = "smartchannels.last_playback_end"

_lock        = threading.Lock()
_buffer      = []               # (segment_name, line)
_timer       = None
_device      = ""               # readable label, e.g. "Kodi (GaragePC) #7a56"
_dirty       = set()            # segment names written locally, not yet synced
_last_sync   = 0.0
_sync_failed = False            # a copy failed and none has worked since
_sync_fail_count = 0            # consecutive failed tries
SYNC_WARN_EVERY  = 12           # log the first failure, then every 12th (~1 h)
_enabled_at  = -1e9
_enabled     = True
_ENABLED_TTL = 30.0
_sync_detail = ""               # what the last failed copy looked like


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _profile_dir() -> str:
    return xbmcvfs.translatePath(
        xbmcaddon.Addon(_ADDON_ID).getAddonInfo("profile"))


def where(exc: BaseException, frames: int = 4) -> str:
    """Where an exception happened, for a log line: the last few frames as
    'file.py:123 function', plus the error type.  Never raises."""
    try:
        tb = traceback.extract_tb(exc.__traceback__)[-frames:]
        trail = " > ".join("{}:{} {}".format(os.path.basename(f.filename),
                                             f.lineno, f.name) for f in tb)
        return "{} at {}".format(type(exc).__name__, trail or "?")
    except Exception:
        return type(exc).__name__


def note_playback_end() -> None:
    """Remember now as the time playback last ended or was stopped.  Called
    by service.py from its playback callbacks.  Never raises."""
    try:
        xbmcgui.Window(10000).setProperty(_PLAY_END_PROP,
                                          str(int(time.time())))
    except Exception:
        pass


def playback_context() -> str:
    """'playing=no, last playback end 12 s ago' for diagnostic log lines.
    Never raises."""
    try:
        playing = "yes" if xbmc.Player().isPlaying() else "no"
    except Exception:
        playing = "?"
    try:
        raw = xbmcgui.Window(10000).getProperty(_PLAY_END_PROP)
        ago = ("{} s ago".format(max(0, int(time.time() - int(raw))))
               if raw else "none since Kodi started")
    except Exception:
        ago = "unknown"
    return "playing={}, last playback end {}".format(playing, ago)


def _local_dir(create: bool = True) -> str:
    """The journals folder in the add-on profile.  Created when *create*;
    clean-up code passes False so it never makes a folder just to empty it."""
    path = os.path.join(_profile_dir(), JOURNAL_SUBDIR)
    if create:
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:
            pass
    return path


def _shared_dir() -> str:
    """The journals folder on the shared storage, or '' when none is set."""
    from resources.lib.utils.paths import shared_root, path_join
    root = shared_root()
    return path_join(root, JOURNAL_SUBDIR) if root else ""


def device_tag(label: str = "") -> str:
    """File-name safe form of the device label."""
    text = re.sub(r"[^A-Za-z0-9]+", "_", label or _device or "device")
    return text.strip("_") or "device"


def enabled() -> bool:
    """The journal_enabled setting (default on), cached for a few seconds."""
    global _enabled, _enabled_at
    now = time.monotonic()
    if now - _enabled_at >= _ENABLED_TTL:
        try:
            raw = xbmcaddon.Addon(_ADDON_ID).getSetting("journal_enabled")
            _enabled = (raw or "true").lower() != "false"
        except Exception:
            pass
        _enabled_at = now
    return _enabled


def set_device(label: str) -> None:
    """Tell the journal which device it is writing for."""
    global _device
    if label:
        _device = label


def chain(skip: int = 1, depth: int = 5) -> str:
    """Names of the calling functions, nearest first, as 'a<b<c'.

    Tells the journal WHICH path caused an event (natural end, skip, carousel
    tick, queue build) without every caller having to pass a reason.
    """
    names = []
    try:
        frame = sys._getframe(skip + 1)
        while frame is not None and len(names) < depth:
            names.append(frame.f_code.co_name)
            frame = frame.f_back
    except Exception:
        pass
    return "<".join(names)


def item_summary(item: dict) -> dict:
    """The fields of a queue item that the journal records: show id, title,
    season, episode, episode id, movie id and whether it is interleaved."""
    return {"show": item.get("show_id") or item.get("_show_id"),
            "title": item.get("title"),
            "s": item.get("season"), "e": item.get("episode"),
            "id": item.get("episodeid"), "movie": item.get("movieid"),
            "il": bool(item.get("_interleaved"))}


def _segment_name(now: datetime.datetime) -> str:
    return "{}{}_{}{}".format(JOURNAL_PREFIX, device_tag(),
                              now.strftime("%Y%m%d_%H"), JOURNAL_SUFFIX)


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

def record(event: str, **fields) -> None:
    """Add one event to the journal.  Never raises."""
    global _timer
    try:
        if not enabled():
            return
        if event in DEBUG_ONLY_EVENTS and not is_debug():
            return
        now  = datetime.datetime.now()
        data = {"t": now.strftime("%Y-%m-%d %H:%M:%S.")
                     + "{:03d}".format(now.microsecond // 1000),
                "dev": _device, "ev": event}
        data.update(fields)
        line = json.dumps(data, ensure_ascii=False, separators=(",", ":"),
                          default=str)
        with _lock:
            _buffer.append((_segment_name(now), line))
            if len(_buffer) > BUFFER_HARD_LIMIT:
                del _buffer[:len(_buffer) - BUFFER_HARD_LIMIT]
            full = len(_buffer) >= FLUSH_MAX_LINES
            if not full and _timer is None:
                _timer = threading.Timer(FLUSH_SECONDS, _flush_timer)
                _timer.daemon = True
                _timer.start()
        if full:
            flush()
    except Exception:
        pass


def _flush_timer() -> None:
    global _timer
    with _lock:
        _timer = None
    flush()


def flush(sync_now: bool = False) -> None:
    """Write the buffered lines to the local journal files; copy them to the
    shared folder when it is time (or sync_now).  Never raises."""
    global _timer, _buffer
    try:
        with _lock:
            lines, _buffer = _buffer, []
            timer, _timer = _timer, None
        if timer is not None:
            timer.cancel()
        if lines:
            by_segment = {}
            for seg, line in lines:
                by_segment.setdefault(seg, []).append(line)
            folder = _local_dir()
            for seg, seg_lines in by_segment.items():
                with open(os.path.join(folder, seg), "a",
                          encoding="utf-8") as fh:
                    fh.write("\n".join(seg_lines) + "\n")
                _dirty.add(seg)
        if _dirty and (sync_now
                       or time.time() - _last_sync >= SYNC_SECONDS):
            sync()
    except Exception as exc:
        log("[journal] flush error: {} ({})".format(exc, where(exc)),
            level=xbmc.LOGWARNING)


def _copy_detail(seg: str, src: str, dst: str, target: str) -> str:
    """What a refused copy looked like: file, local size, whether the target
    folder and the target file are visible.  Reads only; never raises."""
    try:
        size = os.path.getsize(src)
    except Exception:
        size = "?"
    try:
        folder_ok = xbmcvfs.exists(target + "/")
    except Exception:
        folder_ok = "?"
    try:
        dst_there = xbmcvfs.exists(dst)
    except Exception:
        dst_there = "?"
    return ("file {} ({} bytes) to {}: folder visible={}, target file "
            "visible={}".format(seg, size, target, folder_ok, dst_there))


def sync() -> bool:
    """Copy the changed local journal files to the shared folder."""
    global _last_sync, _sync_failed, _sync_fail_count, _sync_detail
    _last_sync = time.time()
    if not _dirty:
        return True
    target = _shared_dir()
    if not target:
        _dirty.clear()           # no shared folder: the local copy is it
        return True
    ok = True
    try:
        if not xbmcvfs.exists(target + "/"):
            xbmcvfs.mkdirs(target + "/")
        folder = _local_dir()
        for seg in sorted(_dirty):
            src = os.path.join(folder, seg)
            dst = target + "/" + seg
            if not os.path.exists(src):
                _dirty.discard(seg)
                continue
            if xbmcvfs.exists(dst):
                xbmcvfs.delete(dst)
            if xbmcvfs.copy(src, dst):
                _dirty.discard(seg)
            else:
                ok = False
                _sync_detail = _copy_detail(seg, src, dst, target)
    except Exception as exc:
        ok = False
        _sync_detail = "exception: {} ({})".format(exc, where(exc))
        log("[journal] sync error: {} ({})".format(exc, where(exc)),
            level=xbmc.LOGWARNING)
    if not ok:
        _sync_failed = True
        _sync_fail_count += 1
        # Logged on the first failure and then every SYNC_WARN_EVERY-th one:
        # one line per run hid a copy that stayed broken for 11 hours (3.1.142).
        if _sync_fail_count == 1 or _sync_fail_count % SYNC_WARN_EVERY == 0:
            log("[journal] could not copy the journal to the shared folder "
                "({} failed tries in a row); the local copy is kept and the "
                "copy will be tried again | {} | {}".format(
                    _sync_fail_count, _sync_detail, playback_context()),
                level=xbmc.LOGWARNING)
    elif _sync_failed:
        log("[journal] copy to the shared folder works again after {} failed "
            "tries | {}".format(_sync_fail_count, playback_context()))
        _sync_failed = False
        _sync_fail_count = 0
    return ok


# ---------------------------------------------------------------------------
# Session start / end, old log, pruning
# ---------------------------------------------------------------------------

def start(device_label: str, version: str) -> None:
    """Call once when the service starts.  Writes the session_start event and
    does the slower jobs (old-log copy, pruning) on a background thread."""
    set_device(device_label)
    record("session_start", version=version,
           kodi=xbmc.getInfoLabel("System.BuildVersion") or "")
    flush()

    def _background():
        try:
            save_previous_log()
            prune()
            sync()
        except Exception as exc:
            log("[journal] start-up job error: {} ({})".format(
                exc, where(exc)), level=xbmc.LOGWARNING)

    threading.Thread(target=_background, daemon=True).start()


def stop() -> None:
    """Call when the service ends: final event, final copy."""
    record("session_end")
    flush(sync_now=True)


def save_previous_log() -> None:
    """Copy kodi.old.log (the previous session) to the journals folder."""
    src = "special://logpath/kodi.old.log"
    if not xbmcvfs.exists(src):
        return
    try:
        mtime = xbmcvfs.Stat(src).st_mtime()
        stamp = datetime.datetime.fromtimestamp(mtime).strftime(
            "%Y%m%d_%H%M%S")
    except Exception:
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    name = "{}{}_{}{}".format(OLD_LOG_PREFIX, device_tag(), stamp,
                              OLD_LOG_SUFFIX)
    target = _shared_dir()
    if target:
        if not xbmcvfs.exists(target + "/"):
            xbmcvfs.mkdirs(target + "/")
        dst = target + "/" + name
    else:
        dst = os.path.join(_local_dir(), name)
    if xbmcvfs.exists(dst):
        return                       # this session's log is already saved
    if xbmcvfs.copy(src, dst):
        log("[journal] previous session log saved as {}".format(name))
    else:
        log("[journal] could not save the previous session log",
            level=xbmc.LOGWARNING)


def _file_date(name: str):
    """Date in a journal/old-log file name, or None."""
    m = re.search(r"_(\d{8})_\d{2,6}\.(?:jsonl|log)$", name)
    if not m:
        return None
    try:
        return datetime.datetime.strptime(m.group(1), "%Y%m%d").date()
    except ValueError:
        return None


def stale_files(names: list, today=None) -> list:
    """Which of *names* (journal segments and saved logs) are to be deleted:
    journals older than JOURNAL_KEEP_DAYS, and old logs beyond the newest
    OLD_LOGS_KEEP of each device.  A pure function, so it can be tested."""
    today = today or datetime.date.today()
    limit = today - datetime.timedelta(days=JOURNAL_KEEP_DAYS)
    stale = []
    logs  = {}
    for name in names:
        if name.startswith(JOURNAL_PREFIX) and name.endswith(JOURNAL_SUFFIX):
            day = _file_date(name)
            if day is not None and day < limit:
                stale.append(name)
        elif name.startswith(OLD_LOG_PREFIX) and name.endswith(OLD_LOG_SUFFIX):
            device = name[len(OLD_LOG_PREFIX):].rsplit("_", 2)[0]
            logs.setdefault(device, []).append(name)
    for device, group in logs.items():
        group.sort(reverse=True)         # newest first (timestamp in name)
        stale.extend(group[OLD_LOGS_KEEP:])
    return stale


def prune() -> None:
    """Delete journal files and saved logs that are no longer wanted."""
    folders = [_local_dir(False)]
    shared = _shared_dir()
    if shared:
        folders.append(shared)
    for folder in folders:
        try:
            _, files = xbmcvfs.listdir(folder)
        except Exception:
            continue
        for name in stale_files(files):
            path = (folder.rstrip("/") + "/" + name if "://" in folder
                    else os.path.join(folder, name))
            xbmcvfs.delete(path)


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

def is_backup_entry(name: str) -> bool:
    """True for a backup zip entry that holds journal evidence.  Restore
    leaves these out of its list: journals are a record of the past, not
    settings to put back over the running journal."""
    return name.startswith(JOURNAL_SUBDIR + "/")


def files_for_backup() -> list:
    """(archive name, bytes) for the journal files of the last BACKUP_DAYS
    days of ALL devices (from the shared folder), plus this device's local
    files when no shared folder is set.  A file that cannot be read is
    logged and left out; the others are still added."""
    out = []
    folder = ""
    names = []
    skipped = failed = 0
    try:
        flush(sync_now=True)
        folder = _shared_dir() or _local_dir()
        _, files = xbmcvfs.listdir(folder)
        names = sorted(files)
    except Exception as exc:
        log("[journal] could not add journal files to the backup: {} ({})"
            .format(exc, where(exc)), level=xbmc.LOGWARNING)
        return out
    limit = datetime.date.today() - datetime.timedelta(days=BACKUP_DAYS)
    for name in names:
        try:
            if not (name.startswith(JOURNAL_PREFIX)
                    and name.endswith(JOURNAL_SUFFIX)):
                continue
            day = _file_date(name)
            if day is not None and day < limit:
                skipped += 1
                continue
            path = (folder.rstrip("/") + "/" + name if "://" in folder
                    else os.path.join(folder, name))
            with xbmcvfs.File(path, "r") as fh:
                raw = fh.read()
            if raw:
                out.append(("{}/{}".format(JOURNAL_SUBDIR, name),
                            raw.encode("utf-8") if isinstance(raw, str)
                            else raw))
        except Exception as exc:
            failed += 1
            log("[journal] could not add journal file {} to the backup: {} "
                "({})".format(name, exc, where(exc)), level=xbmc.LOGWARNING)
    log("[journal] backup: {} journal file(s), {} bytes, from {} ({} older "
        "than {} days left out, {} unreadable)".format(
            len(out), sum(len(d) for _, d in out), folder, skipped,
            BACKUP_DAYS, failed))
    return out


def delete_all() -> int:
    """Delete every journal file and saved log, local and shared (used by
    Delete All Addon Data).  Returns how many files were deleted."""
    global _buffer
    with _lock:
        _buffer = []
    _dirty.clear()
    count = 0
    folders = [_local_dir(False)]
    shared = _shared_dir()
    if shared:
        folders.append(shared)
    for folder in folders:
        try:
            _, files = xbmcvfs.listdir(folder)
        except Exception:
            continue
        for name in files:
            if not ((name.startswith(JOURNAL_PREFIX)
                     and name.endswith(JOURNAL_SUFFIX))
                    or (name.startswith(OLD_LOG_PREFIX)
                        and name.endswith(OLD_LOG_SUFFIX))):
                continue
            path = (folder.rstrip("/") + "/" + name if "://" in folder
                    else os.path.join(folder, name))
            try:
                if xbmcvfs.delete(path):
                    count += 1
            except Exception:
                pass
    return count
