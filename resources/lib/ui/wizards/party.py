# plugin.video.smartchannels
# resources/lib/ui/wizards/party.py
#
# OWNS:   Party channel wizard.
# spec §6.6, Version: 3.0.0 Phase 5

from __future__ import annotations

import xbmcgui

from resources.lib.ui.dialogs import ask_queue_size
from resources.lib.channels.folder import _normalise_path, _accessible_path


def run(addon, manager, name: str, existing: dict | None) -> dict | None:
    """Party wizard. Returns channel definition dict or None."""
    d = xbmcgui.Dialog()

    existing_path = existing.get("folder_path", "") if existing else ""
    folder_path   = d.browseSingle(
        0,
        addon.getLocalizedString(32807),
        "files",
        defaultt=existing_path)
    if not folder_path:
        d.ok(addon.getLocalizedString(32000), addon.getLocalizedString(32533))
        return None

    folder_path = _normalise_path(folder_path)
    if not _accessible_path(folder_path):
        d.ok(addon.getLocalizedString(32000),
             addon.getLocalizedString(32534).format(folder_path))
        return None

    order_choice = d.select(
        addon.getLocalizedString(32214),
        [addon.getLocalizedString(32217),    # Random
         addon.getLocalizedString(32855)])   # Random no-repeats
    if order_choice < 0:
        return None
    audio_order = {0: "random", 1: "no_repeat"}.get(order_choice, "random")

    queue_size = ask_queue_size(addon, existing)
    if queue_size is None:
        return None

    return {
        "name":            name,
        "channel_type":    "party",
        "folder_path":     folder_path,
        "audio_order":     audio_order,
        "randomize":       True,
        "recycle":         True,
        "queue_size":      queue_size,
        "visible":         True,
        "shows":           [],
        "movies":          [],
        "filters":         [],
        "audio_filters":   [],
        "starting_points": {},
        "interleave":      None,
        "carousel_enabled":   False,
        "carousel_mode":      "timed",
        "carousel_interval":  60,
        "carousel_pop_count": 1,
    }
