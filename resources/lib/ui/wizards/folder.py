# plugin.video.smartchannels
# resources/lib/ui/wizards/folder.py
#
# OWNS:   Folder channel wizard.
# spec §6.4, Version: 3.0.0 Phase 5

from __future__ import annotations

import xbmcgui

from resources.lib.ui.dialogs import (
    ask_queue_size, ask_visibility, ask_carousel, browse_folder_path)
from resources.lib.channels.folder import _normalise_path, _accessible_path


def run(addon, manager, name: str, existing: dict | None) -> dict | None:
    """Folder wizard. Returns channel definition dict or None."""
    d = xbmcgui.Dialog()

    # ---- Folder path ---------------------------------------------------------
    existing_path = existing.get("folder_path", "") if existing else ""
    folder_path   = browse_folder_path(addon, existing_path)
    if not folder_path:
        d.ok(addon.getLocalizedString(32000), addon.getLocalizedString(32533))
        return None

    folder_path = _normalise_path(folder_path)
    if not _accessible_path(folder_path):
        d.ok(addon.getLocalizedString(32000),
             addon.getLocalizedString(32534).format(folder_path))
        return None

    # ---- Playback order ------------------------------------------------------
    default_rand = existing.get("randomize", False) if existing else (
        addon.getSetting("default_randomize") == "true")
    rand_choice = d.yesno(
        addon.getLocalizedString(32214),
        addon.getLocalizedString(32215),
        nolabel=addon.getLocalizedString(32285),    # Sequential
        yeslabel=addon.getLocalizedString(32217),   # Random
        defaultbutton=(xbmcgui.DLG_YESNO_YES_BTN
                       if default_rand
                       else xbmcgui.DLG_YESNO_NO_BTN))
    randomize = bool(rand_choice)

    # All Folder channels always recycle (design decision)
    recycle = True

    # ---- No Repeat -----------------------------------------------------------
    # A Random folder always plays every file once before any repeats
    # (Random / No Repeat), so there is nothing to ask: Sequential never
    # repeats within a pass either.
    no_repeat = randomize

    # ---- Queue size ----------------------------------------------------------
    queue_size = ask_queue_size(addon, existing)
    if queue_size is None:
        return None

    # ---- Visibility  NEVER REMOVE --------------------------------------------
    visible = ask_visibility(addon, existing, manager)
    if visible is None:
        return None

    # ---- Carousel — hidden channels cannot have carousel --------------------
    no_carousel = {"enabled": False, "mode": "timed",
                   "interval": 60, "pop_count": 1}
    if not visible:
        carousel = no_carousel
    else:
        channel_id = existing.get("id") if existing else None
        carousel   = ask_carousel(addon, manager, channel_id, existing)
        if carousel is None:
            return None

    return {
        "name":            name,
        "channel_type":    "folder",
        "folder_path":     folder_path,
        "shows":           [],
        "movies":          [],
        "randomize":       randomize,
        "recycle":         recycle,
        "no_repeat":       no_repeat,
        "queue_size":      queue_size,
        "visible":         visible,
        "filters":         [],
        "interleave":      existing.get("interleave") if existing else None,
        "starting_points": {},
        "carousel_enabled":   carousel["enabled"],
        "carousel_mode":      carousel["mode"],
        "carousel_interval":  carousel["interval"],
        "carousel_pop_count": carousel["pop_count"],
    }
