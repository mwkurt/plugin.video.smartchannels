"""
resources/lib/utils/logger.py
==============================
Thin wrapper around xbmc.log so all addon messages share a consistent
prefix and respect the user's chosen log-level setting.
"""

import time

import xbmc
import xbmcaddon

_ADDON_ID = "plugin.video.smartchannels"
_PREFIX   = f"[{_ADDON_ID}] "

# The log_level setting is cached for a few seconds: log() is called many
# times per second during a build, and reading a setting every call is slow.
_PREF_TTL  = 5.0
_pref      = 0
_pref_time = -_PREF_TTL


def _log_pref() -> int:
    """Return the cached log_level setting (0=Info, 1=Debug, 2=Warning)."""
    global _pref, _pref_time
    now = time.monotonic()
    if now - _pref_time >= _PREF_TTL:
        try:
            _pref = int(
                xbmcaddon.Addon(_ADDON_ID).getSetting("log_level") or "0")
        except Exception:
            pass  # addon not initialised yet: keep the previous value
        _pref_time = now
    return _pref


def is_debug() -> bool:
    """True when the Log level setting is Debug (1).  Public so other modules
    (the draw journal) can follow the same setting without reading it twice."""
    return _log_pref() == 1


def log(message: str, level: int = xbmc.LOGINFO) -> None:
    """
    Write a message to the Kodi log.

    Args:
        message: Text to log.
        level:   xbmc.LOGINFO (default), xbmc.LOGDEBUG, xbmc.LOGWARNING,
                 xbmc.LOGERROR, xbmc.LOGFATAL.
    """
    # log_level setting: 0 = Info (default; Debug messages are left out),
    # 1 = Debug (everything), 2 = Warning (only warnings and errors).
    pref = _log_pref()
    if pref == 2:
        if level < xbmc.LOGWARNING:
            return
    elif level == xbmc.LOGDEBUG and pref != 1:
        return

    xbmc.log(_PREFIX + str(message), level=level)
