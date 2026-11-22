"""
resources/lib/ui/side_panel.py
================================
Two-pane channel browser using a custom WindowXML window.

Left pane  (control 100) : Channel list.
Right pane (control 200) : Upcoming queue items for the highlighted channel.

OWNS:   Window lifecycle, focus/navigation state machine, populating both
        panes, context menu, dispatching playback via router URL actions.

NEVER:  Direct state.json or queue file writes — all queue mutations go
        through channel_manager.reorder_queue_from_item().
        Playback event handling (service.py owns that).
        Hardcoded user-visible strings — all text via self._s().

Navigation contract:
  Up/Down in left pane   → moves channel selection, updates right pane.
  Right from left pane   → focus moves to right pane (control 200).
  Left from right pane   → focus returns to left pane (control 100).
  Enter on left pane     → plays channel from queue front.
  Enter on right pane[0] → plays channel from queue front.
  Enter on right pane[N] → reorders queue so item N is first, then plays.
  C / Menu key           → context menu for focused channel (left pane only).
  Back / Escape          → closes window, returns to Kodi Home.

XML window ID: 9700  (unused by Kodi itself and all standard skins).

Ported from 2.x. Queue watcher thread kept intact (carousel pop triggers right-pane
refresh via queue file mtime change).
"""

from __future__ import annotations

import os
import time
from urllib.parse import urlencode

import xbmc
import xbmcgui
import xbmcvfs

from resources.lib.utils.logger import log

# ---------------------------------------------------------------------------
# Kodi action IDs
# ---------------------------------------------------------------------------
ACTION_MOVE_LEFT     = 1
ACTION_MOVE_RIGHT    = 2
ACTION_MOVE_UP       = 3
ACTION_MOVE_DOWN     = 4
ACTION_PREVIOUS_MENU = 10    # Escape key
ACTION_CONTEXT_MENU  = 117   # C key / Menu button / long-press
ACTION_NAV_BACK      = 92    # Back button / Backspace

# ---------------------------------------------------------------------------
# Control IDs — must match SmartChannels_Main.xml exactly
# ---------------------------------------------------------------------------
CTRL_CHANNEL_LIST  = 100
CTRL_UPCOMING_LIST = 200
CTRL_UPCOMING_HDR  = 300
CTRL_CHANNEL_HDR   = 302   # "Channels:" heading above the channel list
CTRL_RIGHT_GROUP   = 301

# ---------------------------------------------------------------------------
# String IDs
# ---------------------------------------------------------------------------
_S_PLAY_CHANNEL = 32690   # "> Play"
_S_UPCOMING     = 32691   # "Upcoming"
_S_NO_ITEMS     = 32692   # "No items in queue"
_S_SEP_EP       = 32693   # "S{0}E{1} — {2}"
_S_CHANNELS_HDR = 32984   # "Channels:"
_S_ROW_NEXT     = 32985   # "Next: {0}"
_S_ROW_QUEUE    = 32986   # "{0} in queue"
_S_ROW_EP       = 32987   # "S{0}E{1}"

# The line under each channel name is filled from the queue files while the
# panel opens; if that takes longer than this many seconds the rest stay blank.
_ROW_LINE_BUDGET_S = 4.0

# Context menu string IDs — reuse existing strings from channels.py
_S_CTX_CHANNEL_INFO = 32415
_S_CTX_PLAY         = 32201
_S_CTX_EDIT         = 32202
_S_CTX_RESET        = 32350
_S_CTX_DELETE       = 32203
_S_CTX_INTERLEAVE   = 32205
_S_CTX_VIEW_EXCL    = 32609
_S_CTX_ADD_SCHEDULE = 32730
_S_CTX_MOVE_UP      = 32781
_S_CTX_MOVE_DOWN    = 32782
_S_RESET_CONFIRM    = 32354   # "Reset {0}?"
_S_RESET_DONE       = 32355   # "{0} reset"
_S_ADDON_NAME       = 32000   # "Smart TV Channels"

_PLUGIN_URL = "plugin://plugin.video.smartchannels/"


def _url(**kwargs):
    """Build a plugin:// URL for RunPlugin / RunAddon calls."""
    return "{}?{}".format(_PLUGIN_URL, urlencode(kwargs))


def _resolve_skin_xml(addon_path):
    """
    Return the path to SmartChannels_Main.xml for the active Kodi skin.

    Search order:
      1. resources/skins/<active_skin_id>/<res>/SmartChannels_Main.xml
      2. resources/skins/Default/1080i/SmartChannels_Main.xml  (fallback)

    <res> is 720p for Confluence, 1080i for everything else.
    """
    skin_id  = xbmc.getSkinDir()
    res      = "720p" if skin_id == "skin.confluence" else "1080i"
    specific = os.path.join(
        addon_path, "resources", "skins", skin_id, res,
        "SmartChannels_Main.xml")
    if xbmcvfs.exists(specific):
        log("[SidePanel] Using skin-specific XML: {}".format(specific))
        return specific

    fallback = os.path.join(
        addon_path, "resources", "skins", "Default", "1080i",
        "SmartChannels_Main.xml")
    log("[SidePanel] Using fallback XML: {}".format(fallback))
    return fallback


def _queue_item_kind(item, ch_type):
    """Return "movie", "folder" or "episode" for one queue item.

    The one place that decides what kind of item a queue entry is, so the
    right pane and the line under each channel name agree.
    """
    is_movie = (item.get("is_movie") or (item.get("movieid") or -1) > 0
                or ch_type == "movies")
    if is_movie:
        return "movie"
    if ch_type == "folder" and not item.get("episodeid"):
        return "folder"
    return "episode"


class SmartChannelsSidePanel(xbmcgui.WindowXML):
    """Two-pane channel browser. Instantiated by open_side_panel()."""

    def __new__(cls, xml_file, addon_path, addon, manager):
        return super().__new__(cls, xml_file, addon_path)

    def __init__(self, xml_file, addon_path, addon, manager):
        self._addon          = addon
        self._addon_path     = addon_path
        self._manager        = manager
        self._channels       = []    # visible channel dicts
        self._panel_data     = []    # items shown in right pane
        self._current_ch_idx = 0     # highlighted channel index
        self._panel_focused  = False # True when focus is in right pane

        # Queue watcher state
        self._watcher_thread  = None
        self._watcher_active  = False
        self._watcher_mtime   = None

    # ── Channel list helper ────────────────────────────────────────────────

    def _get_channels(self) -> list:
        """Return channels to display per the show_hidden_channels setting."""
        try:
            show_hidden = self._addon.getSetting("show_hidden_channels") == "true"
        except Exception:
            show_hidden = False
        if show_hidden:
            return self._manager.get_all_channels()
        return self._manager.get_visible_channels()

    # ── Kodi WindowXML lifecycle ───────────────────────────────────────────

    def onInit(self):
        """Called by Kodi when the window is ready to render."""
        log("[SidePanel] onInit")
        self.getControl(CTRL_CHANNEL_HDR).setLabel(self._s(_S_CHANNELS_HDR))
        self._channels = self._get_channels()
        self._populate_channel_list()
        if self._channels:
            start = self._manager.get_panel_start_index(self._channels)
            self._current_ch_idx = start
            if start:
                self.getControl(CTRL_CHANNEL_LIST).selectItem(start)
            # Kodi tries to focus the list when the window opens, before it
            # has any rows, and fails ("asked to focus, but it can't"); the
            # first Enter then went nowhere until an arrow key gave it focus
            # (3.1.168).  Ask again now that the list is filled.
            self.setFocusId(CTRL_CHANNEL_LIST)
            self._panel_focused = False
            self._populate_panel(self._channels[start])

        self._start_queue_watcher()

    def onAction(self, action):
        """Handle navigation, back, and context menu."""
        action_id = action.getId()

        focused_ctrl = self.getFocusId()
        if focused_ctrl == CTRL_CHANNEL_LIST:
            self._panel_focused = False
        elif focused_ctrl == CTRL_UPCOMING_LIST:
            self._panel_focused = True

        if action_id in (ACTION_PREVIOUS_MENU, ACTION_NAV_BACK):
            log("[SidePanel] Back/Escape — closing")
            self._stop_queue_watcher()
            self.close()
            xbmc.executebuiltin("ActivateWindow(Home)")
            return

        if action_id == ACTION_CONTEXT_MENU and not self._panel_focused:
            self._show_context_menu()
            return

        if action_id == ACTION_CONTEXT_MENU and self._panel_focused:
            self._show_episode_context_menu()
            return

        if action_id == ACTION_MOVE_RIGHT and not self._panel_focused:
            if self._panel_data:
                self.setFocusId(CTRL_UPCOMING_LIST)
                self._panel_focused = True
            return

        if action_id == ACTION_MOVE_LEFT and self._panel_focused:
            self.setFocusId(CTRL_CHANNEL_LIST)
            self._panel_focused = False
            return

        if action_id in (ACTION_MOVE_UP, ACTION_MOVE_DOWN):
            if not self._panel_focused:
                xbmc.sleep(50)
                ctrl    = self.getControl(CTRL_CHANNEL_LIST)
                new_idx = ctrl.getSelectedPosition()
                if new_idx != self._current_ch_idx:
                    self._current_ch_idx = new_idx
                    if new_idx < len(self._channels):
                        self._watcher_mtime = None
                        self._populate_panel(self._channels[new_idx])

    def onFocus(self, control_id):
        if control_id == CTRL_CHANNEL_LIST:
            self._panel_focused = False
        elif control_id == CTRL_UPCOMING_LIST:
            self._panel_focused = True

    def onClick(self, control_id):
        """Handle Enter on either pane."""
        if control_id == CTRL_CHANNEL_LIST:
            ctrl = self.getControl(CTRL_CHANNEL_LIST)
            idx  = ctrl.getSelectedPosition()
            if idx < len(self._channels):
                self._play_channel(self._channels[idx]["id"])

        elif control_id == CTRL_UPCOMING_LIST:
            ctrl = self.getControl(CTRL_UPCOMING_LIST)
            idx  = ctrl.getSelectedPosition()
            if idx < 0 or idx >= len(self._panel_data):
                return
            item = self._panel_data[idx]
            if item.get("_is_play_button"):
                ch_idx = self._current_ch_idx
                if ch_idx < len(self._channels):
                    self._play_channel(self._channels[ch_idx]["id"])
            else:
                ch_idx = self._current_ch_idx
                if ch_idx < len(self._channels):
                    ch = self._channels[ch_idx]
                    raw_queue_index = item.get("_raw_queue_index", idx - 1)
                    self._play_from_item(ch["id"], item, raw_queue_index)

    # ── Context menu ──────────────────────────────────────────────────────

    def _show_context_menu(self):
        """Channel context menu — left pane only (C key / Menu button)."""
        if self.getFocusId() != CTRL_CHANNEL_LIST:
            return

        ctrl = self.getControl(CTRL_CHANNEL_LIST)
        idx  = ctrl.getSelectedPosition()
        if idx < 0 or idx >= len(self._channels):
            return

        ch           = self._channels[idx]
        channel_id   = ch["id"]
        channel_type = ch.get("channel_type", "tv")

        options = [
            (self._s(_S_CTX_CHANNEL_INFO), "channel_info"),
            (self._s(_S_CTX_PLAY),         "play_channel"),
            (self._s(_S_CTX_EDIT),         "edit_channel"),
            (self._s(_S_CTX_RESET),        "reset_channel"),
            (self._s(_S_CTX_DELETE),       "delete_channel"),
            (self._s(32700),               "set_channel_icon"),
            (self._s(_S_CTX_MOVE_UP),      "move_channel_up"),
            (self._s(_S_CTX_MOVE_DOWN),    "move_channel_down"),
        ]
        if channel_type == "combo":
            options = [(lbl, act) for lbl, act in options
                       if act not in ("play_channel", "reset_channel",
                                      "set_channel_icon", "move_channel_up",
                                      "move_channel_down")]
        if ch.get("interleave") and channel_type in ("tv", "movies", "folder"):
            reset_pos = next(i for i, o in enumerate(options)
                             if o[1] == "reset_channel")
            options.insert(reset_pos + 1,
                           (self._s(32976), "rebuild_keep_places"))
        if channel_type not in ("audio", "party", "combo"):
            options.append((self._s(_S_CTX_ADD_SCHEDULE), "add_schedule"))
        if channel_type not in ("audio", "party", "serial", "combo"):
            options.append((self._s(_S_CTX_INTERLEAVE), "manage_interleave"))
        if channel_type in ("tv", "serial", "movies"):
            options.append((self._s(_S_CTX_VIEW_EXCL), "view_exclusions"))
        _missing = self._manager.get_missing_durations(channel_id)
        if _missing:
            options.append(
                (self._s(32710).format(len(_missing)), "view_missing_durations"))

        labels = [o[0] for o in options]
        choice = xbmcgui.Dialog().select(ch.get("name", ""), labels)
        if choice < 0:
            return

        action_name = options[choice][1]
        log("[SidePanel] context: {}".format(action_name))

        if action_name == "play_channel":
            self._play_channel(channel_id)

        elif action_name == "reset_channel":
            confirmed = xbmcgui.Dialog().yesno(
                self._s(_S_CTX_RESET),
                self._s(32354).format(ch["name"]))
            if confirmed:
                self._manager.clear_cursor(channel_id)
                self._manager.clear_channel_resume_points(channel_id)
                self._manager.write_channel_queue(channel_id, [])
                fresh_ch = self._manager.get_channel(channel_id)
                if fresh_ch:
                    queue = self._manager.build_channel_queue(fresh_ch)
                    self._manager.write_channel_queue(channel_id, queue)
                xbmcgui.Dialog().notification(
                    self._s(_S_ADDON_NAME),
                    self._s(32355).format(ch["name"]),
                    xbmcgui.NOTIFICATION_INFO, 2000)
                self._refresh_panel(idx)

        elif action_name == "rebuild_keep_places":
            # Same action as the channel-list menu (router.rebuild_keep_places):
            # the rebuild itself is ChannelManager.rebuild_keep_places.
            holder = self._manager.channel_lock_holder(channel_id)
            if holder:
                xbmcgui.Dialog().ok(
                    self._s(_S_ADDON_NAME),
                    self._s(32949).format(
                        holder.get("device_name") or self._s(32948)))
                return
            from resources.lib.ui.channels import confirm_rebuild_keep_places
            if confirm_rebuild_keep_places(self._addon, ch["name"]):
                if self._manager.rebuild_keep_places(channel_id):
                    xbmcgui.Dialog().notification(
                        self._s(_S_ADDON_NAME),
                        self._s(32978).format(ch["name"]),
                        xbmcgui.NOTIFICATION_INFO, 2000)
                else:
                    xbmcgui.Dialog().ok(
                        self._s(_S_ADDON_NAME),
                        self._s(32979).format(ch["name"]))
                self._refresh_panel(idx)

        elif action_name in ("move_channel_up", "move_channel_down"):
            if action_name == "move_channel_up":
                self._manager.move_channel_up(channel_id)
                new_idx = max(0, idx - 1)
            else:
                self._manager.move_channel_down(channel_id)
                new_idx = min(len(self._channels) - 1, idx + 1)
            self._refresh_after_list_change(new_idx)

        elif action_name in ("channel_info", "view_exclusions", "set_channel_icon"):
            plugin_url = _url(action=action_name, channel_id=channel_id)
            xbmc.executebuiltin("RunPlugin({})".format(plugin_url))
            if action_name == "set_channel_icon":
                self._manager.reload_channels()
                self._channels = self._get_channels()
                self._populate_channel_list()

        elif action_name == "view_missing_durations":
            self._show_missing_durations_dialog(channel_id, ch)

        elif action_name in ("edit_channel", "manage_interleave"):
            if action_name == "edit_channel":
                from resources.lib.ui.channels import run_edit_wizard
                run_edit_wizard(self._addon, self._manager, channel_id)
            else:
                from resources.lib.ui.wizards.interleave import run as interleave_run
                interleave_run(self._addon, self._manager, channel_id)
            self._manager.reload_channels()
            self._channels = self._get_channels()
            self._populate_channel_list()
            safe_idx = min(idx, len(self._channels) - 1) if self._channels else 0
            self._current_ch_idx = safe_idx
            if self._channels:
                self._populate_panel(self._channels[safe_idx])

        elif action_name == "add_schedule":
            from resources.lib.ui.schedule_wizard import ScheduleWizard
            _wizard = ScheduleWizard(
                self._addon, self._manager,
                existing=None,
                target_channel_id=channel_id)
            result = _wizard.run()
            if result:
                self._manager.add_schedule(result)
                xbmcgui.Dialog().notification(
                    self._s(_S_ADDON_NAME),
                    self._s(32739),
                    xbmcgui.NOTIFICATION_INFO, 2000)

        elif action_name == "delete_channel":
            combo_owner       = None
            combo_owner_clean = None
            if channel_type == "combo":
                combo_owner = self._manager.get_combo_owner(channel_id)
                if combo_owner:
                    rel_str = (self._s(32883) if
                               combo_owner.get("relationship") == "interleave"
                               else self._s(32884))
                    proceed = xbmcgui.Dialog().yesno(
                        self._s(_S_ADDON_NAME),
                        self._s(32879).format(
                            ch["name"], rel_str,
                            combo_owner.get("channel_name", "?")))
                    if not proceed:
                        return
                    combo_owner_clean = combo_owner

            confirmed = xbmcgui.Dialog().yesno(
                self._s(_S_ADDON_NAME), self._s(32211))
            if confirmed:
                if combo_owner_clean:
                    rel    = combo_owner_clean.get("relationship", "")
                    tgt_id = combo_owner_clean.get("channel_id", "")
                    tgt_name = combo_owner_clean.get("channel_name", "?")
                    rel_str  = (self._s(32883) if rel == "interleave"
                                else self._s(32884))
                    if rel == "interleave" and tgt_id:
                        tgt_ch = self._manager.get_channel(tgt_id)
                        if tgt_ch:
                            from resources.lib.channels.interleave import get_sources
                            new_srcs = [s for s in get_sources(tgt_ch)
                                        if s.get("channel_id") != channel_id]
                            self._manager.update_channel(
                                tgt_id, {"interleave": new_srcs or None})
                    elif rel == "schedule":
                        sched_id = combo_owner_clean.get("schedule_id", "")
                        if sched_id:
                            self._manager.delete_schedule(sched_id)

                self._manager.delete_channel(channel_id)

                if combo_owner_clean:
                    xbmcgui.Dialog().notification(
                        self._s(_S_ADDON_NAME),
                        self._s(32880).format(ch["name"], tgt_name, rel_str),
                        xbmcgui.NOTIFICATION_INFO, 4000)
                else:
                    xbmcgui.Dialog().notification(
                        self._s(_S_ADDON_NAME),
                        self._s(32206),
                        xbmcgui.NOTIFICATION_INFO, 2000)
                self._refresh_after_list_change(max(0, idx - 1) if idx > 0 else 0)

        else:
            xbmc.executebuiltin("RunPlugin({})".format(
                _url(action=action_name, channel_id=channel_id)))

    def _show_episode_context_menu(self):
        """Episode context menu — right pane only (C key / Menu button).
        Currently offers Reset Show to Episode 1 for TV episodes.
        """
        if self.getFocusId() != CTRL_UPCOMING_LIST:
            return

        ctrl = self.getControl(CTRL_UPCOMING_LIST)
        idx  = ctrl.getSelectedPosition()
        if idx < 0 or idx >= len(self._panel_data):
            return

        item = self._panel_data[idx]
        if item.get("_is_play_button"):
            return

        # Only TV episodes have a resettable show — skip movies, folder items,
        # audio, and interleaved items (their show belongs to another channel).
        show_id = item.get("show_id") or item.get("_show_id", 0)
        is_tv_ep = (show_id
                    and not item.get("is_movie")
                    and not item.get("is_audio")
                    and item.get("movieid", -1) < 0
                    and not item.get("_interleaved"))
        if not is_tv_ep:
            return

        ch_idx = self._current_ch_idx
        if ch_idx < 0 or ch_idx >= len(self._channels):
            return
        ch         = self._channels[ch_idx]
        channel_id = ch["id"]

        options = [
            (self._s(32353), "reset_show"),  # "Reset Show"
        ]
        labels = [o[0] for o in options]
        choice = xbmcgui.Dialog().select(
            item.get("tvshowtitle", self._s(32353)), labels)
        if choice < 0:
            return

        action_name = options[choice][1]

        if action_name == "reset_show":
            # Same path as the Kodi list's Reset Show: the router asks for
            # confirmation and refuses when another device is playing the
            # channel.  The pane refreshes itself when the queue file changes
            # (queue watcher).  (3.1.158)
            xbmc.executebuiltin("RunPlugin({})".format(
                _url(action="reset_next_episode",
                     channel_id=channel_id,
                     show_id=int(show_id),
                     show_title=item.get("tvshowtitle", ""))))

    # ── Pane refresh helpers ───────────────────────────────────────────────

    def _refresh_panel(self, ch_idx):
        if not self._channels or ch_idx >= len(self._channels):
            return
        self._current_ch_idx = ch_idx
        self._populate_panel(self._channels[ch_idx])

    def _refresh_after_list_change(self, prev_idx):
        self._channels = self._get_channels()
        self._populate_channel_list()
        if not self._channels:
            self._current_ch_idx = 0
            self._panel_data     = []
            self.getControl(CTRL_UPCOMING_LIST).reset()
            self.getControl(CTRL_UPCOMING_HDR).setLabel(self._s(_S_UPCOMING))
            return
        safe_idx = min(prev_idx, len(self._channels) - 1)
        self._current_ch_idx = safe_idx
        self._populate_panel(self._channels[safe_idx])

    # ── Pane population ───────────────────────────────────────────────────

    def _populate_channel_list(self):
        ctrl = self.getControl(CTRL_CHANNEL_LIST)
        ctrl.reset()
        started = time.monotonic()
        skipped = 0
        for ch in self._channels:
            li = xbmcgui.ListItem(
                label=self._manager.get_channel_list_label(ch))
            li.setArt({"icon": self._manager.resolve_channel_icon(ch)})
            if time.monotonic() - started <= _ROW_LINE_BUDGET_S:
                li.setLabel2(self._row_line_for(ch))
            else:
                skipped += 1
            ctrl.addItem(li)
        log("[SidePanel] channel list: {} channels, lines in {:.2f}s, "
            "{} left blank".format(len(self._channels),
                                   time.monotonic() - started, skipped))

    def _row_line_for(self, channel):
        """The line under a channel name, read from its queue file.  Blank when
        the queue cannot be read; the list must still open."""
        try:
            return self._channel_row_line(
                channel, self._manager.get_channel_queue(channel["id"]))
        except Exception as e:
            log("[SidePanel] row line for '{}' failed: {}".format(
                channel.get("name"), e))
            return ""

    def _channel_row_line(self, channel, queue):
        """Text for the line under a channel name: what plays next and how many
        items are queued, e.g. "Next: Bones · S3E4 · 42 in queue"."""
        items = [i for i in (queue or []) if not i.get("_silent")]
        if not items:
            return self._s(_S_NO_ITEMS)
        item    = items[0]
        ch_type = channel.get("channel_type", "tv")
        kind    = _queue_item_kind(item, ch_type)
        if kind == "movie":
            title = item.get("title", "")
            year  = item.get("year", "")
            what  = "{} ({})".format(title, year) if year else title
        elif kind == "folder":
            raw  = item.get("file", item.get("label", ""))
            name = raw.rstrip("/").rstrip("\\").rsplit("/", 1)[-1]
            what = os.path.splitext(name.rsplit("\\", 1)[-1])[0]
        elif ch_type == "audio":
            artist = item.get("artist", "")
            what   = " - ".join(p for p in (artist, item.get("title", "")) if p)
        else:
            show = item.get("tvshowtitle", "")
            what = self._s(_S_ROW_EP).format(
                item.get("season", 0), item.get("episode", 0))
            one_show = (len(channel.get("shows") or []) == 1
                        or show.casefold() == channel.get("name", "").casefold())
            if show and not one_show:
                what = "{} \u00b7 {}".format(show, what)
        return "{} \u00b7 {}".format(
            self._s(_S_ROW_NEXT).format(what),
            self._s(_S_ROW_QUEUE).format(len(items)))

    def _update_row_line(self, channel, queue):
        """Refresh the line under one channel after its queue has been read
        again (queue watcher, channel change)."""
        try:
            for idx, ch in enumerate(self._channels):
                if ch.get("id") == channel.get("id"):
                    self.getControl(CTRL_CHANNEL_LIST).getListItem(idx).setLabel2(
                        self._channel_row_line(channel, queue))
                    return
        except Exception as e:
            log("[SidePanel] row line update failed: {}".format(e))

    def _populate_panel(self, channel):
        ctrl     = self.getControl(CTRL_UPCOMING_LIST)
        hdr_ctrl = self.getControl(CTRL_UPCOMING_HDR)
        ctrl.reset()
        self._panel_data = []

        hdr_ctrl.setLabel(
            self._s(_S_UPCOMING) + "  —  " + channel.get("name", ""))

        queue = []
        try:
            queue = self._manager.get_channel_queue(channel["id"])
        except Exception as e:
            log("[SidePanel] _populate_panel read error: {}".format(e))

        self._update_row_line(channel, queue)

        try:
            n = max(1, min(int(
                self._addon.getSetting("num_upcoming_programs") or "10"), 30))
        except Exception:
            n = 10

        _ch_icon = self._manager.resolve_channel_icon(channel)
        play_li  = xbmcgui.ListItem(
            label=self._s(_S_PLAY_CHANNEL), label2=channel.get("name", ""))
        play_li.setArt({"icon": _ch_icon, "thumb": _ch_icon})
        ctrl.addItem(play_li)
        self._panel_data.append({"_is_play_button": True})

        if not queue:
            empty_li = xbmcgui.ListItem(label=self._s(_S_NO_ITEMS), label2="")
            ctrl.addItem(empty_li)
            self._panel_data.append({"_is_no_items": True})
            return

        ch_type = channel.get("channel_type", "tv")
        visible = 0

        try:
            _shows        = self._manager.library.get_all_tvshows()
            _movies       = self._manager.library.get_all_movies()
            _show_poster  = {s["tvshowid"]: s.get("poster", "") for s in _shows}
            _movie_poster = {m["movieid"]:  m.get("poster", "") for m in _movies}
        except Exception:
            _show_poster  = {}
            _movie_poster = {}

        for raw_idx, item in enumerate(queue):
            if visible >= n:
                break
            if item.get("_silent"):
                continue
            label, label2, thumb = self._format_queue_item(
                item, ch_type, _show_poster, _movie_poster)
            li = xbmcgui.ListItem(label=label, label2=label2)
            if thumb:
                li.setArt({"thumb": thumb})
            ctrl.addItem(li)
            item_copy = dict(item)
            item_copy["_raw_queue_index"] = raw_idx
            self._panel_data.append(item_copy)
            visible += 1

        log("[SidePanel] right pane: {} items for '{}'".format(
            visible, channel.get("name")))

    def _format_queue_item(self, item, ch_type,
                           show_poster=None, movie_poster=None):
        """Return (label, label2, thumb) for one queue item."""
        from resources.lib.utils.duration_cache import format_duration as _fmt_dur

        show_poster  = show_poster  or {}
        movie_poster = movie_poster or {}
        duration_str = _fmt_dur(int(item.get("duration", 0) or 0))

        kind      = _queue_item_kind(item, ch_type)
        is_movie  = (kind == "movie")
        is_folder = (kind == "folder")

        if is_movie:
            label  = item.get("title", "")
            year   = item.get("year", "")
            parts  = [str(year)] if year else []
            if duration_str:
                parts.append(duration_str)
            label2 = " \u00b7 ".join(parts)
            thumb  = (movie_poster.get(item.get("movieid", -1), "")
                      or item.get("thumbnail") or item.get("thumb") or "")
        elif is_folder:
            raw   = item.get("file", item.get("label", ""))
            fname = raw.rstrip("/").rstrip("\\").rsplit("/", 1)[-1]
            fname = fname.rsplit("\\", 1)[-1]
            label  = os.path.splitext(fname)[0]
            label2 = duration_str
            thumb  = item.get("thumbnail") or item.get("thumb") or ""
        else:
            label  = item.get("tvshowtitle", "")
            ep_str = self._s(_S_SEP_EP).format(
                item.get("season", 0),
                item.get("episode", 0),
                item.get("title", ""))
            label2 = "{} \u00b7 {}".format(ep_str, duration_str) \
                     if duration_str else ep_str
            thumb  = (show_poster.get(
                          item.get("show_id") or item.get("_show_id", -1), "")
                      or item.get("thumbnail") or item.get("thumb") or "")

        return label, label2, thumb

    # ── Missing Durations dialog ───────────────────────────────────────────

    def _show_missing_durations_dialog(self, channel_id, channel):
        missing = self._manager.get_missing_durations(channel_id)
        if not missing:
            return
        from resources.lib.ui.channels import missing_duration_label
        items = []
        for m in missing:
            items.append((missing_duration_label(self._addon, m),
                          m.get("file", "")))
        clear_label = self._s(32711)
        labels = [i[0] for i in items] + [clear_label]
        choice = xbmcgui.Dialog().select(
            self._s(32710).format(len(missing)), labels)
        if choice < 0:
            return
        if choice == len(items):
            if xbmcgui.Dialog().yesno(
                    self._s(32710).format(len(missing)), self._s(32712)):
                self._manager.clear_missing_durations(channel_id)
                xbmcgui.Dialog().notification(
                    channel.get("name", ""), self._s(32713),
                    xbmcgui.NOTIFICATION_INFO, 3000)

    # ── Playback dispatch ─────────────────────────────────────────────────

    def _play_channel(self, channel_id):
        log("[SidePanel] _play_channel id={}".format(channel_id))
        self._stop_queue_watcher()
        self.close()
        xbmc.executebuiltin("ActivateWindow(Home)")
        xbmc.sleep(200)
        xbmc.executebuiltin(
            "RunPlugin({})".format(_url(action="play_channel",
                                        channel_id=channel_id)))

    def _play_from_item(self, channel_id, item, queue_index):
        log("[SidePanel] _play_from_item channel={} idx={}".format(
            channel_id, queue_index))
        if queue_index <= 0:
            self._play_channel(channel_id)
            return
        try:
            ok = self._manager.reorder_queue_from_item(channel_id, queue_index)
            if not ok:
                log("[SidePanel] reorder failed — falling back to front")
        except Exception as e:
            log("[SidePanel] _play_from_item error: {}".format(e))
        self.close()
        xbmc.executebuiltin("ActivateWindow(Home)")
        xbmc.sleep(200)
        xbmc.executebuiltin(
            "RunPlugin({})".format(_url(action="play_channel",
                                        channel_id=channel_id)))

    # ── Queue file watcher ────────────────────────────────────────────────

    def _start_queue_watcher(self):
        """Poll current channel's queue file mtime every 10s.
        When it changes, refresh the right pane automatically.
        Kept from 2.x — carousel pops trigger right-pane refresh via
        the queue file mtime change.
        """
        import threading
        self._watcher_active = True
        self._watcher_mtime  = None
        self._watcher_thread = threading.Thread(
            target=self._queue_watch_loop,
            name="SmartChannelsQueueWatcher",
            daemon=True)
        self._watcher_thread.start()
        log("[SidePanel] Queue watcher started")

    def _stop_queue_watcher(self):
        self._watcher_active = False
        if self._watcher_thread is not None:
            self._watcher_thread.join(timeout=2)
            self._watcher_thread = None
        log("[SidePanel] Queue watcher stopped")

    def _queue_watch_loop(self):
        import time
        while self._watcher_active:
            time.sleep(10)
            if not self._watcher_active:
                break
            try:
                ch_idx = self._current_ch_idx
                if not self._channels or ch_idx >= len(self._channels):
                    continue
                ch     = self._channels[ch_idx]
                q_path = self._manager.get_channel_queue_path(ch["id"])
                if not os.path.exists(q_path):
                    continue
                mtime = os.path.getmtime(q_path)
                if self._watcher_mtime is None:
                    self._watcher_mtime = mtime
                    continue
                if mtime != self._watcher_mtime:
                    self._watcher_mtime = mtime
                    log("[SidePanel] Queue changed for '{}' — refreshing".format(
                        ch.get("name", ch["id"])))
                    if self._current_ch_idx == ch_idx:
                        self._refresh_panel(ch_idx)
            except Exception as e:
                log("[SidePanel] Queue watcher error: {}".format(e))

    # ── Helper ────────────────────────────────────────────────────────────

    def _s(self, sid):
        return self._addon.getLocalizedString(sid)


# ── Public entry point ─────────────────────────────────────────────────────

def open_side_panel(addon, manager):
    """Open the side panel. Called from router.py when use_side_panel=True."""
    xbmc.executebuiltin("ActivateWindow(Home)")
    xbmc.sleep(150)

    addon_path = xbmcvfs.translatePath(addon.getAddonInfo("path"))
    xml_file   = _resolve_skin_xml(addon_path)
    xml_name   = os.path.basename(xml_file)

    log("[SidePanel] open_side_panel: xml={}".format(xml_file))
    try:
        panel = SmartChannelsSidePanel(xml_name, addon_path, addon, manager)
        panel.doModal()
        del panel
    except Exception as e:
        log("[SidePanel] open_side_panel error: {}".format(e))
        xbmcgui.Dialog().notification(
            addon.getLocalizedString(32000),
            addon.getLocalizedString(32860).format(str(e)[:60]),
            xbmcgui.NOTIFICATION_ERROR, 4000)
