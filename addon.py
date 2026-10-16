# plugin.video.smartchannels
# addon.py — entry point and action dispatch table
#
# Runs every time the user opens the addon or any plugin:// URL is resolved.
# Checks for the local library cache on every entry and builds it if absent,
# BEFORE dispatching to any handler.
#
# URL scheme:
#   plugin://plugin.video.smartchannels/                          → list_channels
#   plugin://plugin.video.smartchannels/?action=play_channel&...
#   plugin://plugin.video.smartchannels/?action=create_channel
#   plugin://plugin.video.smartchannels/?action=channel_context_menu&...
#
# Version: 3.0.0

import sys
from urllib.parse import parse_qsl

import xbmc
import xbmcaddon
import xbmcgui

from resources.lib.channel_manager import ChannelManager
from resources.lib.router          import Router
from resources.lib.utils.logger    import log

ADDON    = xbmcaddon.Addon()
HANDLE   = int(sys.argv[1])
BASE_URL = sys.argv[0]
PARAMS   = dict(parse_qsl(sys.argv[2][1:]))

# String IDs for cache build UI
_S_ADDON_NAME          = 32000
_S_CACHE_BUILDING      = 32402   # "Building library cache for the first time..."
_S_CACHE_REFRESHING    = 32403   # "Refreshing library cache ({0} days old)..."
_S_CACHE_BUILT         = 32404   # "Library cache updated."
_S_CACHE_FAILED        = 32360   # "Cache rebuild failed — check log for details."
_S_SONGS_BUILDING      = 32848   # "Building songs cache in background..."
_S_SONGS_REFRESHING    = 32849   # "Refreshing songs cache in background..."


def _ensure_library_cache(manager: ChannelManager) -> bool:
    """Check for local_library.json; build it if absent or stale.

    Stale = older than cache_max_age_days setting (default 7).
    Auto-rebuild only fires when cache_auto_rebuild setting is True (default).
    Shows a progress dialog during build and a toast on completion.
    Returns True when cache is ready, False if build failed.

    Called once at the top of main() before any action is dispatched.
    spec §18 (cache settings), §22 — library.py owns all executeJSONRPC calls.
    """
    exists = manager.library.local_cache_exists()

    if exists:
        # Check age against user setting (default 7 days).
        # cache_auto_rebuild defaults to True — only skip rebuild if
        # explicitly disabled.
        try:
            max_age = int(ADDON.getSetting("cache_max_age_days") or "7")
        except (ValueError, TypeError):
            max_age = 7
        auto_rebuild = ADDON.getSetting("cache_auto_rebuild") != "false"

        age_days = manager.library.local_cache_age_days()
        if age_days < max_age or not auto_rebuild:
            return True  # Cache is fresh enough — nothing to do

        log("[addon.py] Local library cache is {:.1f} days old "
            "(max {}d) — rebuilding".format(age_days, max_age))
        build_msg = ADDON.getLocalizedString(_S_CACHE_REFRESHING).format(
            int(age_days))
    else:
        log("[addon.py] Local library cache missing — building now")
        build_msg = ADDON.getLocalizedString(_S_CACHE_BUILDING)

    pd = xbmcgui.DialogProgress()
    pd.create(ADDON.getLocalizedString(_S_ADDON_NAME), build_msg)

    def _progress(pct, msg):
        if pd.iscanceled():
            return
        pd.update(int(pct), msg)

    ok = manager.library.build_local_cache(progress_callback=_progress)
    pd.close()

    if ok:
        xbmc.executebuiltin("Notification({},{},{},)".format(
            ADDON.getLocalizedString(_S_ADDON_NAME),
            ADDON.getLocalizedString(_S_CACHE_BUILT),
            3000))
        log("[addon.py] Local library cache built successfully")
    else:
        xbmcgui.Dialog().ok(
            ADDON.getLocalizedString(_S_ADDON_NAME),
            ADDON.getLocalizedString(_S_CACHE_FAILED))
        log("[addon.py] Local library cache build FAILED", level=xbmc.LOGERROR)

    return ok


def _ensure_songs_cache(manager: ChannelManager) -> None:
    """Check for songs_cache.json; trigger a background build if absent or stale.

    Runs on a background thread — never blocks the UI.
    Shows a toast notification when build starts.
    Called once at addon startup alongside _ensure_library_cache().
    """
    import threading

    exists = manager.library.songs_cache_exists()

    if exists:
        try:
            max_age = int(ADDON.getSetting("cache_max_age_days") or "7")
        except (ValueError, TypeError):
            max_age = 7
        auto_rebuild = ADDON.getSetting("cache_auto_rebuild") != "false"
        age_days = manager.library.songs_cache_age_days()
        if age_days < max_age or not auto_rebuild:
            return  # Songs cache is fresh enough

        log("[addon.py] Songs cache is {:.1f} days old — rebuilding".format(
            age_days))
        toast_msg = ADDON.getLocalizedString(_S_SONGS_REFRESHING)
    else:
        log("[addon.py] Songs cache missing — building in background")
        toast_msg = ADDON.getLocalizedString(_S_SONGS_BUILDING)

    xbmc.executebuiltin("Notification({},{},{},)".format(
        ADDON.getLocalizedString(_S_ADDON_NAME),
        toast_msg,
        3000))

    def _build():
        manager.library.build_songs_cache()

    t = threading.Thread(target=_build, daemon=True)
    t.start()


def main():
    action = PARAMS.get("action", "list_channels")
    log("[addon.py] action='{}' params={}".format(action, PARAMS))

    manager = ChannelManager(ADDON)

    # Cache check — build local_library.json and songs_cache.json if absent.
    # Runs on every addon entry so the first-open experience is seamless.
    # local_cache_exists() is a fast file-stat check once the file exists.
    # Skip for play_channel — if playing is already in progress we don't
    # want to block with a progress dialog.
    if action != "play_channel":
        _ensure_library_cache(manager)
        _ensure_songs_cache(manager)
        manager.library.publish_cache_ages()

    router = Router(HANDLE, BASE_URL, ADDON, manager)

    dispatch = {
        # Viewer
        "list_channels":             router.list_channels,
        "open_channel":              router.open_channel,
        "open_channels":             router.open_channels,
        "play_channel":              router.play_channel,
        "play_from_item":            router.play_from_item,

        # Channel management
        "create_channel":            router.create_channel,
        "auto_create_channels":       router.auto_create_channels,
        "ffprobe_scan":               router.ffprobe_scan,
        "view_missing_durations_global": router.view_missing_durations_global,
        "edit_channel":              router.edit_channel,
        "delete_channel":            router.delete_channel,
        "reset_channel":             router.reset_channel,
        "reset_next_episode":        router.reset_next_episode,
        "channel_info":              router.channel_info,
        "set_channel_icon":          router.set_channel_icon,
        "toggle_channel_visibility": router.toggle_channel_visibility,
        "manage_interleave":         router.manage_interleave,
        "view_exclusions":           router.view_exclusions_action,
        "view_missing_durations":    router.view_missing_durations_action,
        "move_channel_up":           router.move_channel_up,
        "move_channel_down":         router.move_channel_down,
        "sort_channels_alpha":       router.sort_channels_alpha,

        # Schedule management
        "add_schedule":              router.add_schedule,
        "manage_schedules":          router.manage_schedules,

        # Library / tools
        "refresh_library":           router.refresh_library,
        "refresh_songs_cache":        router.refresh_songs_cache,
        "repair_queue_paths":        router.repair_queue_paths,

        # Settings / misc
        "open_settings":             router.open_settings,
        "backup_data":               router.backup_data,
        "restore_data":              router.restore_data,
        "delete_all_data":           router.delete_all_data,
    }

    handler = dispatch.get(action)
    if handler:
        handler(PARAMS)
    else:
        log("[addon.py] Unknown action '{}' — falling back to "
            "list_channels".format(action), level=xbmc.LOGWARNING)
        router.list_channels(PARAMS)


if __name__ == "__main__":
    main()
