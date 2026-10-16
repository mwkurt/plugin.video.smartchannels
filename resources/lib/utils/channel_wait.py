# plugin.video.smartchannels
# resources/lib/utils/channel_wait.py
#
# OWNS:   The short list of channels this device tried to watch while another
#         device was playing them.  The menu (router.py) adds to it; the
#         service tick (service.py) reads it and tells the user when a
#         channel becomes free.
#
# The list lives in a Kodi home-window property because the menu and the
# service are separate processes.  It is per device, never written to the
# shared storage, and a Kodi restart clears it.
#
# Version: 3.1.109

from __future__ import annotations

import json
import time

import xbmcgui

_PROP         = "smartchannels.waiting_channels"
_HOME_WINDOW  = 10000
# A device stops waiting for a channel after this many seconds.
WAIT_EXPIRY_SECONDS = 4 * 3600


def _window():
    return xbmcgui.Window(_HOME_WINDOW)


def _read() -> list:
    try:
        data = json.loads(_window().getProperty(_PROP) or "[]")
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write(entries: list) -> None:
    try:
        _window().setProperty(_PROP, json.dumps(entries))
    except Exception:
        pass


def note_waiting(channel_id: str, channel_name: str) -> None:
    """Remember that this device wants channel_id as soon as it is free."""
    entries = [e for e in _read() if e.get("id") != channel_id]
    entries.append({"id": channel_id, "name": channel_name,
                    "since": time.time()})
    _write(entries)


def waiting_entries() -> list:
    """Return the live waiting entries, dropping ones past the expiry."""
    now   = time.time()
    live  = [e for e in _read()
             if now - float(e.get("since", 0) or 0) <= WAIT_EXPIRY_SECONDS]
    if len(live) != len(_read()):
        _write(live)
    return live


def stop_waiting(channel_id: str = "") -> None:
    """Forget one channel, or every channel when channel_id is empty."""
    if not channel_id:
        _write([])
        return
    _write([e for e in _read() if e.get("id") != channel_id])
