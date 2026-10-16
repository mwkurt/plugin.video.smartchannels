# overlays/logo_overlay.py
#
# Timed channel logo overlay for plugin.video.smartchannels.
#
# Shows the channel logo for a configurable number of seconds when a
# channel starts or changes, then hides automatically. No persistent
# window — avoids all Kodi input-stack interception issues.
#
# Architecture mirrors coming_up_next.py exactly:
#   - xbmcgui.WindowDialog shown for N seconds then auto-dismissed
#   - service.py calls show() on channel start/change
#   - No onAction handling needed — window is gone before user presses anything
#
# service.py is the ONLY caller. It resolves the icon path via
# channel_manager.resolve_channel_icon() and calls show().
# This module never reads state.json, queue files, or channels.json.

import threading
import xbmc
import xbmcgui
import xbmcaddon

# ── Size constants ────────────────────────────────────────────────────────────
# Kodi logical coordinate space is 1280x720 regardless of physical resolution.
SIZE_MAP = {
    0: 60,    # Small
    1: 80,    # Medium (default)
    2: 100,   # Large
}

# ── Opacity constants (ARGB alpha hex) ───────────────────────────────────────
OPACITY_MAP = {
    0: "7F",   # Low  ~50%
    1: "B2",   # Medium ~70%
    2: "E5",   # High ~90%
}

# ── Corner positions ──────────────────────────────────────────────────────────
CORNER_KEYS = ["top_left", "top_right", "bottom_left", "bottom_right"]


def _corner_pos(corner_key, size, margin):
    """Return (x, y) top-left for the icon given corner, size, margin."""
    if corner_key == "top_left":
        return (margin, margin)
    elif corner_key == "top_right":
        return (1280 - size - margin, margin)
    elif corner_key == "bottom_left":
        return (margin, 720 - size - margin)
    else:  # bottom_right
        return (1280 - size - margin, 720 - size - margin)


class LogoOverlayWindow(xbmcgui.WindowDialog):
    """
    Timed channel logo window. Shows for `duration` seconds then closes.
    No onAction override — the window is auto-dismissed before the user
    is likely to press anything, so input interception is never an issue.
    """

    def __init__(self, icon_path, corner_key, size, alpha_hex, margin, duration):
        super(LogoOverlayWindow, self).__init__()
        self._duration  = duration
        self._timer     = None
        self._dismissed = False

        x, y = _corner_pos(corner_key, size, margin)
        color_diffuse = "{}FFFFFF".format(alpha_hex)
        img = xbmcgui.ControlImage(
            x, y, size, size,
            filename=icon_path,
            aspectRatio=2,
            colorDiffuse=color_diffuse,
        )
        self.addControl(img)

    def show_timed(self):
        """Show the window and start the auto-dismiss timer."""
        self.show()
        self._timer = threading.Timer(self._duration, self._auto_dismiss)
        self._timer.daemon = True
        self._timer.start()

    def _auto_dismiss(self):
        if not self._dismissed:
            self._dismissed = True
            try:
                self.close()
            except Exception:
                pass

    def cancel(self):
        """Cancel the timer and close immediately (called on channel change or stop)."""
        if self._timer is not None:
            self._timer.cancel()
        self._auto_dismiss()


class SmartChannelsLogoOverlay:
    """
    Manages timed logo display. Instantiated once by service.py at startup.
    """

    def __init__(self):
        self._lock    = threading.Lock()
        self._window  = None   # current LogoOverlayWindow or None

    def show(self, icon_path, settings):
        """
        Show the logo for settings['duration'] seconds.
        Cancels any currently showing logo first.
        Does nothing if icon_path is empty or the generic fallback.
        """
        if not icon_path or icon_path == "DefaultVideoPlaylists.png":
            return

        corner_idx  = settings.get("corner",   1)
        size_idx    = settings.get("size",      1)
        opacity_idx = settings.get("opacity",   1)
        margin      = settings.get("margin",    30)
        duration    = settings.get("duration",  5)

        corner_key = CORNER_KEYS[corner_idx] if 0 <= corner_idx < 4 else "top_right"
        size       = SIZE_MAP.get(size_idx,    80)
        alpha_hex  = OPACITY_MAP.get(opacity_idx, "B2")

        # Cancel any existing window
        with self._lock:
            old = self._window
            self._window = None
        if old is not None:
            try:
                old.cancel()
            except Exception:
                pass

        try:
            win = LogoOverlayWindow(
                icon_path, corner_key, size, alpha_hex, margin, duration)
            win.show_timed()
            with self._lock:
                self._window = win
            xbmc.log("[plugin.video.smartchannels] [LogoOverlay] shown for {}s: {} "
                     "corner={} size={}px".format(
                         duration, icon_path, corner_key, size), xbmc.LOGINFO)
        except Exception as e:
            xbmc.log("[plugin.video.smartchannels] [LogoOverlay] show error: {}".format(
                e), xbmc.LOGWARNING)

    def hide_permanent(self):
        """Cancel any showing logo immediately. Called on playback stop."""
        with self._lock:
            win = self._window
            self._window = None
        if win is not None:
            try:
                win.cancel()
            except Exception:
                pass
        xbmc.log("[plugin.video.smartchannels] [LogoOverlay] cancelled",
                 xbmc.LOGINFO)

def load_settings():
    """
    Read logo overlay settings from addon settings.
    Returns dict consumed by SmartChannelsLogoOverlay.show().
    """
    addon = xbmcaddon.Addon()
    return {
        "enabled":  addon.getSetting("logo_overlay_enabled").lower() == "true",
        "corner":   int(addon.getSetting("logo_overlay_corner")  or "1"),
        "size":     int(addon.getSetting("logo_overlay_size")    or "1"),
        "opacity":  int(addon.getSetting("logo_overlay_opacity") or "1"),
        "margin":   max(0, int(addon.getSetting("logo_overlay_margin")   or "30")),
        "duration": max(1, int(addon.getSetting("logo_overlay_duration") or "5")),
    }
