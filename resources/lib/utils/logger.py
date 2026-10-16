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


def log(message: str, level: int = xbmc.LOGINFO) -> None:
    """
    Write a message to the Kodi log.

    Args:
        message: Text to log.
        level:   xbmc.LOGINFO (default), xbmc.LOGDEBUG, xbmc.LOGWARNING,
                 xbmc.LOGERROR, xbmc.LOGFATAL.
    """
    # When the preference is Info, suppress Debug-level addon messages.
    if level == xbmc.LOGDEBUG and _log_pref() == 0:
        return

    xbmc.log(_PREFIX + str(message), level=level)
