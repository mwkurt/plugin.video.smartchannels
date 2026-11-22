"""
resources/lib/utils/write_lock.py
=================================
A lock for the shared folder, built from one rename (3.1.148).

Why it exists
-------------
Up to four devices read, change and write state.json and the other shared
files over a network share that has no locking.  Two devices that save at the
same moment each write a whole file and one of the two changes is lost (the
share probe measured 42 of 80 counter updates lost without a lock).  The
double carousel pops of 11/02 to 11/08 came from this.

How it works
------------
One empty file, mutex.dat, lives in the shared folder.  A device takes the
lock by renaming it to a name of its own (mutex.held.<device>.<nonce>) and
gives it back by renaming that file to mutex.dat.  Renaming a file that exists
can succeed for only one device: the share probe measured 33 of 33 rounds
exclusive, at about 3 ms per rename.  Creating a folder or copying a file is
NOT exclusive on these shares and is not used.

* The wait is short (the caller says how long).  When the lock stays busy the
  caller goes on WITHOUT it and a 'lock_fail_open' line is journalled: a
  stuck share must never freeze playback.
* A held name that has not changed for STALE_SECONDS (120 s, longer than the
  longest Shield stall measured, 13 s) belongs to a device that is gone.  A
  waiter takes it over by renaming that exact name to its own; as above only
  one waiter can succeed.
* Every hold has a new name, so a slow but living holder never looks stale.
* The holder checks that its name still exists right after taking the lock
  and again when giving it back; if another device took it over meanwhile it
  does not touch mutex.dat ('lock_lost').
* Taking it again in the same thread costs nothing (re-entrant); threads of
  one process queue on an ordinary in-process lock first.
* If neither mutex.dat nor a held name exists, mutex.dat is created.
* Nothing here raises: every error means "no lock, go on".

mutex.dat and mutex.held.* are not data files: migration, backup and Delete
All Data do not touch them.
"""

import contextlib
import random
import threading
import time
import uuid

import xbmc
import xbmcvfs

from resources.lib.utils import journal

LOCK_NAME = "mutex.dat"
HELD_PREFIX = "mutex.held."
STALE_SECONDS = 120
POLL_MS = 100
STATS_SECONDS = 3600
FAIL_LOG_SECONDS = 60
BUSY_LOG_MS = 1000


class KodiFS:
    """The few file operations the lock needs, through Kodi's VFS."""

    def join(self, base: str, name: str) -> str:
        if "://" in base:
            return base.rstrip("/") + "/" + name
        sep = "\\" if ("\\" in base and "/" not in base) else "/"
        return base.rstrip("/\\") + sep + name

    def exists(self, path: str) -> bool:
        return bool(xbmcvfs.exists(path))

    def rename(self, src: str, dst: str) -> bool:
        return bool(xbmcvfs.rename(src, dst))

    def listdir(self, path: str) -> list:
        dirs, files = xbmcvfs.listdir(path)
        return list(files)

    def write(self, path: str, text: str) -> bool:
        f = xbmcvfs.File(path, "w")
        try:
            return bool(f.write(text))
        finally:
            f.close()


def default_fs():
    return KodiFS()


def _clean(name: str) -> str:
    out = "".join(ch for ch in str(name) if ch.isalnum())
    return out[:12] or "dev"


class WriteLock:
    """The lock of one process on one shared folder."""

    def __init__(self, fs, root: str, device: str, enabled: bool = True,
                 record=None, now=None, sleep=None,
                 stale_seconds: float = STALE_SECONDS):
        self._fs = fs
        self._root = root or ""
        self._dev = _clean(device)
        self._on = bool(enabled)
        self._record = record or (lambda ev, **f: journal.record(ev, **f))
        self._now = now or time.monotonic
        self._sleep = sleep or xbmc.sleep
        self._stale = stale_seconds
        self._tl = threading.RLock()
        self._depth = 0
        self._have_file = False
        self._own = ""
        self._since = 0.0
        self._seen_name = ""
        self._seen_at = 0.0
        self._last_fail_log = -1e9
        self._fail_count = 0
        self._stats_at = self._now()
        self._stats = self._new_stats()

    # ------------------------------------------------------------------
    @staticmethod
    def _new_stats() -> dict:
        return {"n": 0, "waited": 0, "fail_open": 0, "takeovers": 0,
                "wait_ms": 0, "max_wait_ms": 0, "max_hold_ms": 0}

    def _rec(self, ev: str, **fields) -> None:
        try:
            self._record(ev, **fields)
        except Exception:
            pass

    def _path(self, name: str) -> str:
        return self._fs.join(self._root, name)

    def active(self) -> bool:
        return self._on and bool(self._root)

    # ------------------------------------------------------------------
    @contextlib.contextmanager
    def scope(self, wait_ms: int):
        """Hold the lock for the block.  Yields True when the lock is held,
        False when the block runs without it (switched off, no shared folder,
        busy for longer than wait_ms, or any error)."""
        if not self.active():
            yield False
            return
        start = self._now()
        if not self._tl.acquire(timeout=max(0.0, wait_ms / 1000.0)):
            self._fail_open(wait_ms, "process")
            yield False
            return
        try:
            if self._depth == 0:
                self._stats_tick()
                left = max(0, int(wait_ms - (self._now() - start) * 1000))
                self._have_file = self._acquire(left)
            self._depth += 1
            try:
                yield self._have_file
            finally:
                self._depth -= 1
                if self._depth == 0:
                    if self._have_file:
                        self._release()
                    self._have_file = False
        finally:
            self._tl.release()

    # ------------------------------------------------------------------
    def _acquire(self, wait_ms: int) -> bool:
        start = self._now()
        deadline = start + wait_ms / 1000.0
        own = "{}{}.{}".format(HELD_PREFIX, self._dev, uuid.uuid4().hex[:8])
        lock_path, own_path = self._path(LOCK_NAME), self._path(own)
        taken = False
        created = False
        polls = 0
        try:
            while True:
                if self._fs.rename(lock_path, own_path):
                    taken = True
                    return self._finish_take(own, own_path, start, polls)
                names = [n for n in self._fs.listdir(self._root)
                         if n.startswith("mutex")]
                held = sorted(n for n in names if n.startswith(HELD_PREFIX))
                if LOCK_NAME not in names and not held and not created:
                    created = True
                    if self._fs.write(lock_path, "lock"):
                        self._rec("lock_created", dev=self._dev)
                    continue
                if held:
                    name = held[0]
                    t = self._now()
                    if name != self._seen_name:
                        self._seen_name, self._seen_at = name, t
                    elif t - self._seen_at >= self._stale:
                        age = t - self._seen_at
                        if self._fs.rename(self._path(name), own_path):
                            taken = True
                            self._stats["takeovers"] += 1
                            self._rec("lock_takeover",
                                      **{"from": name.split(".")[2]
                                         if name.count(".") >= 3 else "?",
                                         "name": name, "age": round(age, 1)})
                            return self._finish_take(own, own_path, start,
                                                     polls)
                if self._now() >= deadline:
                    self._fail_open(wait_ms, "busy", held=held[:1])
                    return False
                polls += 1
                self._sleep(POLL_MS + random.randint(0, 60))
        except Exception as exc:
            if taken:
                try:
                    self._fs.rename(own_path, lock_path)
                except Exception:
                    pass
            self._fail_open(wait_ms, "error", err=str(exc)[:80])
            return False

    def _finish_take(self, own: str, own_path: str, start: float,
                     polls: int) -> bool:
        if not self._fs.exists(own_path):
            self._rec("lock_lost", where="take", name=own)
            return False
        t = self._now()
        waited = int((t - start) * 1000)
        self._own, self._since = own, t
        s = self._stats
        s["n"] += 1
        s["wait_ms"] += waited
        s["max_wait_ms"] = max(s["max_wait_ms"], waited)
        if polls:
            s["waited"] += 1
        if waited >= BUSY_LOG_MS:
            self._rec("lock_busy", waited_ms=waited)
        return True

    def _release(self) -> None:
        own = self._own
        lock_path, own_path = self._path(LOCK_NAME), self._path(own)
        try:
            held_ms = int((self._now() - self._since) * 1000)
            self._stats["max_hold_ms"] = max(self._stats["max_hold_ms"],
                                             held_ms)
            if not self._fs.exists(own_path):
                self._rec("lock_lost", where="release", name=own,
                          held_ms=held_ms)
            elif not self._fs.rename(own_path, lock_path):
                self._rec("lock_release_failed", name=own, held_ms=held_ms)
        except Exception as exc:
            self._rec("lock_release_failed", name=own, err=str(exc)[:80])

    # ------------------------------------------------------------------
    def _fail_open(self, wait_ms: int, why: str, **extra) -> None:
        self._stats["fail_open"] += 1
        self._fail_count += 1
        t = self._now()
        if t - self._last_fail_log >= FAIL_LOG_SECONDS:
            self._last_fail_log = t
            self._rec("lock_fail_open", why=why, wait_ms=int(wait_ms),
                      count=self._fail_count, **extra)
            self._fail_count = 0

    def _stats_tick(self) -> None:
        t = self._now()
        if t - self._stats_at < STATS_SECONDS:
            return
        s, self._stats = self._stats, self._new_stats()
        self._stats_at = t
        n = s["n"]
        self._rec("lock_stats", n=n, waited=s["waited"],
                  fail_open=s["fail_open"], takeovers=s["takeovers"],
                  avg_wait_ms=int(s["wait_ms"] / n) if n else 0,
                  max_wait_ms=s["max_wait_ms"], max_hold_ms=s["max_hold_ms"])
