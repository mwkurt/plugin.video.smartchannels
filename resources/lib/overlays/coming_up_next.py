# overlays/coming_up_next.py
#
# Ported from 2.x resources/lib/coming_up_next.py
# Path updated: now lives in resources/lib/overlays/
#
# Self-contained Coming Up Next overlay for plugin.video.smartchannels.
#
# Responsibilities (this module only):
#   - Read the next-episode data passed in from service.py
#   - Build and display the overlay window using xbmcgui
#   - Auto-dismiss after the user-configured duration
#   - Apply user settings: corner, duration, display fields
#
# service.py is the ONLY caller. It reads settings, reads the queue to
# find the next episode, and calls show_overlay(). This module never
# reads state.json, queue files, or channels.json directly.
#
# Architecture rules honoured:
#   - No playback callbacks here (all in service.py)
#   - No queue/state access (all in channel_manager.py)
#   - No hardcoded user-visible strings (all via strings.po)

import threading
import xbmc
import xbmcgui
import xbmcaddon

ADDON = xbmcaddon.Addon()


def _s(string_id):
    """Return localised string for the given ID."""
    return ADDON.getLocalizedString(string_id)


# ── Corner position constants ────────────────────────────────────────────────
# Kodi's coordinate space is 1280x720 logical units regardless of actual
# resolution. The overlay adapts automatically to 4K / 1080p / 720p displays
# because Kodi scales from this logical space to the physical display.

OVERLAY_W = 580   # logical width  — matches bg_overlay.png width
OVERLAY_H = 160   # logical height — matches bg_overlay.png height
MARGIN    = 40    # distance from screen edge

CORNERS = {
    "top_left":     (MARGIN,              MARGIN),
    "top_right":    (1280 - OVERLAY_W - MARGIN, MARGIN),
    "bottom_left":  (MARGIN,              720 - OVERLAY_H - MARGIN),
    "bottom_right": (1280 - OVERLAY_W - MARGIN, 720 - OVERLAY_H - MARGIN),
}

CORNER_KEYS = ["top_left", "top_right", "bottom_left", "bottom_right"]


class ComingUpNextWindow(xbmcgui.WindowDialog):
    """
    Lightweight overlay window drawn entirely via xbmcgui controls.
    Uses WindowDialog so it renders over the video without interrupting
    playback. No XML skin file required — fully self-contained.
    """

    def __init__(self, lines, corner_key, duration_s):
        """
        lines      : list of strings to display (already localised/formatted)
        corner_key : one of the CORNERS keys
        duration_s : seconds before auto-dismiss
        """
        super(ComingUpNextWindow, self).__init__()
        self._duration   = duration_s
        self._timer      = None
        self._dismissed  = False

        x, y = CORNERS.get(corner_key, CORNERS["bottom_right"])

        # ── Background ───────────────────────────────────────────────────────
        # bg_overlay.png is a 580x160 RGBA PNG with rounded corners (radius=18)
        # and 73% opacity black fill. aspectRatio=0 stretches to fill the panel.
        bg_path = xbmcaddon.Addon().getAddonInfo("path")
        bg_file = bg_path + "/resources/lib/overlays/bg_overlay.png"
        bg = xbmcgui.ControlImage(
            x, y, OVERLAY_W, OVERLAY_H,
            filename=bg_file,
            aspectRatio=0
        )
        self.addControl(bg)

        # ── Header label ("Coming Up Next") ─────────────────────────────────
        lbl_header = xbmcgui.ControlLabel(
            x + 20, y + 12, OVERLAY_W - 40, 30,
            label=_s(32064),      # "Coming Up Next"
            font="font16",
            textColor="0xFFFFAA00",   # amber
            alignment=0
        )
        self.addControl(lbl_header)

        # ── Content lines ────────────────────────────────────────────────────
        for i, line in enumerate(lines):
            lbl = xbmcgui.ControlLabel(
                x + 20,
                y + 50 + i * 34,
                OVERLAY_W - 40,
                30,
                label=line,
                font="font14",
                textColor="0xFFFFFFFF",
                alignment=0
            )
            self.addControl(lbl)

    def show_timed(self):
        """Show the overlay and auto-dismiss after _duration seconds."""
        self.show()
        self._timer = threading.Timer(self._duration, self._auto_dismiss)
        self._timer.daemon = True
        self._timer.start()

    def _auto_dismiss(self):
        """Called by timer thread — close the window."""
        if not self._dismissed:
            self._dismissed = True
            self.close()

    def onClick(self, control_id):
        """Tapping anywhere dismisses immediately."""
        self._auto_dismiss()

    def onAction(self, action):
        """Any remote/keyboard action dismisses the overlay."""
        if not self._dismissed:
            self._auto_dismiss()


def _build_lines(next_ep, settings):
    """
    Build the list of text lines to show, based on user display settings
    and the next episode data dict.

    next_ep keys (TV):    tvshowtitle, title, season, episode
    next_ep keys (Movie): title, year, is_movie=True
    next_ep keys (Audio): artist, title, album, is_audio=True
    """
    lines = []
    is_movie = next_ep.get("is_movie", False) or next_ep.get("movieid", -1) > 0

    # ── Audio items ──────────────────────────────────────────────────────────
    if next_ep.get("is_audio"):
        artist_raw = next_ep.get("artist", "") or ""
        artist = (", ".join(artist_raw)
                  if isinstance(artist_raw, list)
                  else str(artist_raw))
        title  = next_ep.get("title",  "") or ""
        album  = next_ep.get("album",  "") or ""
        if artist:
            lines.append(artist)
        if title:
            lines.append(title)
        if album and settings.get("show_ep_title", True):
            lines.append(album)
        return lines

    if is_movie:
        # Movie: show title and optionally year
        if settings.get("show_title", True):
            title = next_ep.get("title", "")
            year  = next_ep.get("year", 0)
            if year and settings.get("show_season_ep", True):
                lines.append("{} ({})".format(title, year))
            else:
                lines.append(title)
    else:
        # TV episode
        if settings.get("show_title", True):
            lines.append(next_ep.get("tvshowtitle", ""))

        if settings.get("show_season_ep", True):
            s = next_ep.get("season",  0)
            e = next_ep.get("episode", 0)
            if s and e:
                lines.append("S{:02d}E{:02d}".format(s, e))

        if settings.get("show_ep_title", True):
            ep_title = next_ep.get("title", "")
            if ep_title:
                lines.append(ep_title)

    return lines


def show_overlay(next_ep, settings):
    """
    Entry point called by service.py.

    next_ep  : dict with the next episode/movie from the queue
    settings : dict with overlay settings (from load_settings())

    Must be called from the main service thread — xbmcgui WindowDialog
    requires the main thread on all Kodi platforms.
    """
    if not settings.get("enabled", True):
        return
    if not next_ep:
        return

    lines = _build_lines(next_ep, settings)
    if not lines:
        return

    corner   = settings.get("corner",   "bottom_right")
    duration = max(1, int(settings.get("duration", 8)))

    try:
        win = ComingUpNextWindow(lines, corner, duration)
        win.show_timed()
        xbmc.log("[plugin.video.smartchannels] [ComingUpNext] shown: {}".format(
            " | ".join(lines)), xbmc.LOGINFO)
    except Exception as e:
        xbmc.log("[plugin.video.smartchannels] [ComingUpNext] error: {}".format(
            e), xbmc.LOGWARNING)


def load_settings():
    """
    Read all Coming Up Next settings from addon settings.
    Returns a dict consumed by show_overlay().
    Called once per episode from service.py so settings are always current.
    """
    addon = xbmcaddon.Addon()
    corner_index = int(addon.getSetting("cun_corner") or "3")
    corner_key   = CORNER_KEYS[corner_index] if 0 <= corner_index < len(CORNER_KEYS) \
                   else "bottom_right"
    _lead_idx    = max(0, int(addon.getSetting("cun_lead") or "1"))
    lead_minutes = _lead_idx + 1
    return {
        "enabled":        addon.getSetting("cun_enabled").lower() == "true",
        "corner":         corner_key,
        "duration":       max(1, int(addon.getSetting("cun_duration")     or "8")),
        "lead_minutes":   lead_minutes,
        "show_title":     addon.getSetting("cun_show_title").lower()     != "false",
        "show_season_ep": addon.getSetting("cun_show_season_ep").lower() != "false",
        "show_ep_title":  addon.getSetting("cun_show_ep_title").lower()  != "false",
        "min_duration":   max(0, int(addon.getSetting("cun_min_duration") or "120")),
        "suppress_silent":addon.getSetting("cun_suppress_silent").lower() == "true",
    }
