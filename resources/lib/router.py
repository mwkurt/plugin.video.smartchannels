# plugin.video.smartchannels
# resources/lib/router.py
#
# OWNS:   URL action dispatch. Instantiates ChannelManager and SmartPlayer,
#         routes addon.py actions to the correct handler.
#
# NEVER:  Playback callbacks (service.py), queue building (channel_manager.py),
#         state reads/writes (channel_manager.py), executeJSONRPC (library.py).
#
# Phase 1 scope: list_channels, open_channel, play_channel.
# Remaining actions added per phase.
#
# Version: 3.0.0

from __future__ import annotations

import xbmcgui
import xbmcplugin

import xbmc

from resources.lib.channel_manager  import ChannelManager
from resources.lib.player           import SmartPlayer
from resources.lib.ui.channels      import (run_create_wizard, run_edit_wizard,
                                            show_channel_info,
                                            view_exclusions, view_missing_durations,
                                            confirm_delete, confirm_reset)
from resources.lib.utils.channel_wait import note_waiting, stop_waiting
from resources.lib.utils.logger     import log


class Router:

    def __init__(self, handle: int, base_url: str, addon,
                 manager: ChannelManager | None = None):
        self.handle   = handle
        self.base_url = base_url
        self.addon    = addon
        self.manager  = manager if manager is not None else ChannelManager(addon)

    # -------------------------------------------------------------------------
    # list_channels
    # -------------------------------------------------------------------------

    def list_channels(self, params: dict) -> None:
        """Display channels as a Kodi directory listing.

        When use_side_panel setting is True, opens the custom WindowXML
        browser instead. Falls back to the standard listing on error.
        Respects the show_hidden_channels setting — same as 2.x.
        """
        if self.addon.getSetting("use_side_panel") == "true":
            log("[router] list_channels: opening side panel")
            try:
                from resources.lib.ui.side_panel import open_side_panel
                xbmcplugin.endOfDirectory(self.handle, succeeded=False)
                open_side_panel(self.addon, self.manager)
                return
            except Exception as _sp_err:
                log("[router] side panel error, falling back to list: {}".format(
                    _sp_err))
            # Fall through to standard listing on error.
        show_hidden  = self.addon.getSetting("show_hidden_channels") == "true"
        all_channels = self.manager.get_all_channels()
        channels     = (all_channels
                        if show_hidden
                        else self.manager.get_visible_channels())
        log("[router] list_channels: {} channels (show_hidden={})".format(
            len(channels), show_hidden))

        if not channels:
            # Use a different message when channels exist but none are
            # visible — guides the user to enable Show Hidden Channels.
            if all_channels and not show_hidden:
                msg = self.addon.getLocalizedString(32227)
            else:
                msg = self.addon.getLocalizedString(32226)
            xbmcgui.Dialog().ok(
                self.addon.getLocalizedString(32000), msg)
            xbmcplugin.endOfDirectory(self.handle, succeeded=False)
            return

        for ch in channels:
            ch_id   = ch["id"]
            ch_name = ch.get("name", ch_id)
            icon    = self.manager.resolve_channel_icon(ch)

            # Build the upcoming label from the queue front
            queue = self.manager.get_channel_queue(ch_id)
            if queue:
                front = queue[0]
                show  = front.get("tvshowtitle", "")
                title = front.get("title", "")
                s     = int(front.get("season",  0) or 0)
                e     = int(front.get("episode", 0) or 0)
                if show and s:
                    sub = "{} — S{:02d}E{:02d} — {}".format(show, s, e, title)
                elif show:
                    sub = "{} — {}".format(show, title)
                else:
                    sub = title
            else:
                sub = ""

            label = self.manager.get_channel_list_label(ch)
            li    = xbmcgui.ListItem(label=label)
            li.setArt({"icon": icon, "thumb": icon})
            if sub:
                li.setLabel2(sub)

            # Channel is a folder — pointing to open_channel so Kodi skins
            # render the upcoming queue items in the right panel when focused.
            # Play is via context menu (play_channel action).
            open_url = "{}?action=open_channel&channel_id={}".format(
                self.base_url, ch_id)

            li.setInfo("video", {"title": ch_name})
            li.setProperty("IsPlayable", "false")

            # Context menu — full set matching 2.x behaviour.
            # replaceItems=True so the menu IS the channel options.
            ch_type = ch.get("channel_type", "tv")
            def _ctx(action):
                return "RunPlugin({}?action={}&channel_id={})".format(
                    self.base_url, action, ch_id)
            # Combo Block channels: only Channel Info, Edit, Delete.
            # No Play (not directly playable), no Reset (no queue file),
            # no Set Icon, no Toggle Visibility (always hidden),
            # no Add Schedule (combo is source only, not target),
            # no Move Up/Down (not in the visible channel list).
            is_combo = (ch_type == "combo")

            ctx = [
                (self.addon.getLocalizedString(32415), _ctx("channel_info")),
            ]
            if not is_combo:
                ctx.append((self.addon.getLocalizedString(32201),
                             _ctx("play_channel")))
            ctx.append((self.addon.getLocalizedString(32202),
                         _ctx("edit_channel")))
            if not is_combo:
                ctx.append((self.addon.getLocalizedString(32350),
                             _ctx("reset_channel")))
            ctx.append((self.addon.getLocalizedString(32203),
                         _ctx("delete_channel")))
            if not is_combo:
                ctx.append((self.addon.getLocalizedString(32700),
                             _ctx("set_channel_icon")))
            if ch_type not in ("audio", "party", "combo"):
                ctx.append((self.addon.getLocalizedString(32204),
                             _ctx("toggle_channel_visibility")))
            if ch_type not in ("audio", "party", "combo"):
                ctx.append((self.addon.getLocalizedString(32730),
                             _ctx("add_schedule")))
            if ch_type not in ("serial", "audio", "party", "combo"):
                ctx.append((self.addon.getLocalizedString(32205),
                             _ctx("manage_interleave")))
            if ch_type in ("tv", "serial", "movies"):
                ctx.append((self.addon.getLocalizedString(32609),
                             _ctx("view_exclusions")))
            missing = self.manager.get_missing_durations(ch_id)
            if missing:
                ctx.append((self.addon.getLocalizedString(32710).format(
                    len(missing)), _ctx("view_missing_durations")))
            if not is_combo:
                ctx.append((self.addon.getLocalizedString(32781),
                             _ctx("move_channel_up")))
                ctx.append((self.addon.getLocalizedString(32782),
                             _ctx("move_channel_down")))
            li.addContextMenuItems(ctx, replaceItems=True)

            xbmcplugin.addDirectoryItem(
                self.handle, open_url, li, isFolder=True)

        xbmcplugin.setContent(self.handle, "videos")
        xbmcplugin.endOfDirectory(self.handle, succeeded=True)

    # -------------------------------------------------------------------------
    # open_channel  (episode listing view)
    # -------------------------------------------------------------------------

    def open_channel(self, params: dict) -> None:
        """Display upcoming queue items for a channel.

        Called when the user focuses/enters a channel in the list.
        Renders up to num_upcoming_programs items with full setInfo()
        metadata so skins can display them in the right panel.
        Silent items are filtered out — they are never shown here.
        spec §1.8, §18 (num_upcoming_programs, show_next_episode)
        """
        channel_id = params.get("channel_id", "")
        channel    = self.manager.get_channel(channel_id)
        if not channel:
            xbmcgui.Dialog().ok(
                self.addon.getLocalizedString(32000),
                self.addon.getLocalizedString(32207))
            xbmcplugin.endOfDirectory(self.handle, succeeded=False)
            return

        # Respect num_upcoming_programs setting (default 5)
        try:
            num_up = max(1, int(
                self.addon.getSetting("num_upcoming_programs") or "5"))
        except (ValueError, TypeError):
            num_up = 5

        queue = self.manager.get_channel_queue(channel_id)
        log("[router] open_channel: {} items in queue for '{}'".format(
            len(queue), channel.get("name", channel_id)))

        # Filter silent items first, then limit to num_up
        visible = [item for item in queue
                   if not item.get("_silent")][:num_up]

        play_url = "{}?action=play_channel&channel_id={}".format(
            self.base_url, channel_id)

        # ">> Play Channel" item always first — plays from queue front.
        # IsPlayable must be false: the plugin:// URL is a RunPlugin trigger,
        # not a resolvable media item.  If set to true, Kodi inserts the URL
        # as item 0 in its internal playlist, then skips it as unplayable and
        # jumps to our queue[1] — bypassing queue[0].  Same fix as channel
        # list items (Phase 1).
        icon    = self.manager.resolve_channel_icon(channel)
        play_li = xbmcgui.ListItem(
            label=self.addon.getLocalizedString(32434))
        play_li.setArt({"icon": icon, "thumb": icon})
        play_li.setProperty("IsPlayable", "false")
        xbmcplugin.addDirectoryItem(
            self.handle, play_url, play_li, isFolder=False)

        # Build queue-index lookup from the full unfiltered queue so that
        # each visible item carries its correct position for play_from_item.
        queue = self.manager.get_channel_queue(channel_id)
        file_to_index = {item.get("file", ""): i
                         for i, item in enumerate(queue)
                         if item.get("file")}

        for item in visible:
            is_movie = (item.get("is_movie")
                        or item.get("movieid", -1) > 0
                        or (not item.get("tvshowtitle")
                            and not item.get("is_folder_item")
                            and not item.get("is_audio")
                            and item.get("episodeid", -1) < 0))

            if is_movie:
                title = item.get("title", "")
                year  = item.get("year", "")
                label = "{}{}".format(
                    title, " ({})".format(year) if year else "")
                li = xbmcgui.ListItem(label=label)
                li.setInfo("video", {
                    "title":     title,
                    "year":      year,
                    "plot":      item.get("plot", ""),
                    "mediatype": "movie",
                })
                thumb = item.get("thumbnail", "") or item.get("thumb", "")
                if thumb:
                    li.setArt({"thumb": thumb, "icon": thumb})
            elif item.get("is_audio"):
                title  = item.get("title", "")
                artist = item.get("artist", "") or ""
                label  = "{} — {}".format(artist, title) if artist else title
                li = xbmcgui.ListItem(label=label)
                li.setInfo("music", {
                    "title":  title,
                    "artist": artist,
                    "album":  item.get("album", "") or "",
                })
                thumb = item.get("thumbnail", "") or item.get("thumb", "")
                if thumb:
                    li.setArt({"thumb": thumb, "icon": thumb})
            elif item.get("is_folder_item"):
                title = item.get("title", "")
                li    = xbmcgui.ListItem(label=title)
                li.setInfo("video", {"title": title, "mediatype": "video"})
            else:
                # TV episode
                show  = item.get("tvshowtitle", "")
                title = item.get("title", "")
                s     = int(item.get("season",  0) or 0)
                e     = int(item.get("episode", 0) or 0)
                if show and s:
                    label = "{} — S{:02d}E{:02d} — {}".format(
                        show, s, e, title)
                elif show:
                    label = "{} — {}".format(show, title)
                else:
                    label = title
                li = xbmcgui.ListItem(label=label)
                li.setInfo("video", {
                    "tvshowtitle": show,
                    "title":       title,
                    "season":      s,
                    "episode":     e,
                    "mediatype":   "episode",
                })
                thumb = item.get("thumbnail", "") or item.get("thumb", "")
                if thumb:
                    li.setArt({"thumb": thumb, "icon": thumb})

            # Each item links to play_from_item with its queue index so the
            # user can click any item in the channel view to start from there.
            # Falls back to play_channel (index 0) if the file isn't in the
            # index map (should not happen in practice).
            q_idx = file_to_index.get(item.get("file", ""), 0)
            if q_idx > 0:
                item_url = "{}?action=play_from_item&channel_id={}&queue_index={}".format(
                    self.base_url, channel_id, q_idx)
            else:
                item_url = play_url

            # Reset Show context menu — TV episodes only (spec §14, TC-30.17).
            # Resets the next-episode position for this show on this channel
            # back to S01E01. Only shown when the item has a _show_id.
            show_id_ctx = item.get("_show_id", 0) or item.get("show_id", 0)
            if show_id_ctx and not item.get("is_movie") and not item.get("is_audio"):
                reset_url = "{}?action=reset_next_episode&channel_id={}&show_id={}".format(
                    self.base_url, channel_id, show_id_ctx)
                li.addContextMenuItems([
                    (self.addon.getLocalizedString(32353),
                     "RunPlugin({})".format(reset_url)),
                ], replaceItems=False)

            li.setProperty("IsPlayable", "true")
            xbmcplugin.addDirectoryItem(
                self.handle, item_url, li, isFolder=False)

        channel_type = channel.get("channel_type", "tv")
        xbmcplugin.setPluginCategory(self.handle, channel.get("name", ""))
        xbmcplugin.setContent(
            self.handle,
            "movies" if channel_type == "movies" else "episodes")
        xbmcplugin.endOfDirectory(self.handle, succeeded=True)

    # -------------------------------------------------------------------------
    # channel lock guard  (3.1.109)
    # -------------------------------------------------------------------------

    def _channel_busy_elsewhere(self, channel_id: str, channel: dict,
                                resolved: bool = False,
                                text_id: int = 32946) -> bool:
        """True (after telling the user) when another device is playing
        this channel.  Remembers the channel so the service can say when it
        is free again.  resolved=True when the plugin handle is already
        resolved (a start that lost a simultaneous claim)."""
        holder = self.manager.channel_lock_holder(channel_id)
        if not holder:
            return False
        name = channel.get("name", channel_id)
        device = (holder.get("device_name")
                  or self.addon.getLocalizedString(32948))
        log("[router] channel '{}' is playing on '{}' — start refused".format(
            name, device))
        note_waiting(channel_id, name)
        if not resolved:
            dummy = xbmcgui.ListItem(label=self.addon.getLocalizedString(32000))
            dummy.setProperty("IsPlayable", "true")
            xbmcplugin.setResolvedUrl(
                self.handle, succeeded=False, listitem=dummy)
        xbmcgui.Dialog().ok(
            self.addon.getLocalizedString(32000),
            self.addon.getLocalizedString(text_id).format(device))
        return True

    def _channel_change_blocked(self, channel_id: str) -> bool:
        """True (after telling the user) when another device is playing the
        channel, so it must not be edited, reset, deleted or have its queue
        changed from here.  (3.1.110)"""
        channel = self.manager.get_channel(channel_id) if channel_id else None
        return bool(channel) and self._channel_busy_elsewhere(
            channel_id, channel, resolved=True, text_id=32949)

    # -------------------------------------------------------------------------
    # play_channel
    # -------------------------------------------------------------------------

    def play_channel(self, params: dict) -> None:
        """Build the playlist and start playback for a channel."""
        channel_id = params.get("channel_id", "")
        channel    = self.manager.get_channel(channel_id)
        if not channel:
            log("[router] play_channel: channel {} not found".format(channel_id),
                level=2)
            xbmcgui.Dialog().ok(
                self.addon.getLocalizedString(32000),
                self.addon.getLocalizedString(32207))
            return

        # Combo Block channels are source-only — they cannot be played directly.
        # Guard here in case the URL is constructed manually or called from an
        # unexpected path; the context menu already omits Play for combo channels.
        if channel.get("channel_type") == "combo":
            log("[router] play_channel: blocked direct play of combo channel "
                "{}".format(channel_id), level=xbmc.LOGWARNING)
            xbmcgui.Dialog().ok(
                self.addon.getLocalizedString(32000),
                self.addon.getLocalizedString(32896))
            return

        if self._channel_busy_elsewhere(channel_id, channel):
            return

        # CRITICAL: resolve the Kodi plugin handle BEFORE starting playback.
        # Without this, Kodi inserts the plugin:// action URL as position 0
        # in its internal playlist, then skips it as unplayable — causing a
        # false skip detection on every channel start. Matches 2.x exactly.
        dummy = xbmcgui.ListItem(label=self.addon.getLocalizedString(32000))
        dummy.setProperty("IsPlayable", "true")
        xbmcplugin.setResolvedUrl(self.handle, succeeded=False, listitem=dummy)

        player = SmartPlayer(self.addon, self.manager)
        result = player.start_channel(channel)
        if not result and self._channel_busy_elsewhere(
                channel_id, channel, resolved=True):
            # Lost a simultaneous start to another device.
            return
        if result:
            stop_waiting(channel_id)
        if not result:
            xbmcgui.Dialog().ok(
                self.addon.getLocalizedString(32000),
                self.addon.getLocalizedString(32208))

    # -------------------------------------------------------------------------
    # create_channel
    # -------------------------------------------------------------------------

    def create_channel(self, params: dict) -> None:
        """Launch channel creation wizard then refresh the channel list."""
        created = run_create_wizard(self.addon, self.manager)
        if created:
            xbmc.executebuiltin("Container.Refresh")

    # -------------------------------------------------------------------------
    # Direct context menu action handlers
    # Each fires from its own RunPlugin URL — no intermediate picker dialog.
    # -------------------------------------------------------------------------

    def edit_channel(self, params: dict) -> None:
        """Edit an existing channel via the wizard."""
        channel_id = params.get("channel_id", "")
        if self._channel_change_blocked(channel_id):
            return
        updated = run_edit_wizard(self.addon, self.manager, channel_id)
        if updated:
            xbmc.executebuiltin("Container.Refresh")

    def delete_channel(self, params: dict) -> None:
        """Delete a channel after confirmation."""
        channel_id = params.get("channel_id", "")
        channel    = self.manager.get_channel(channel_id)
        if not channel:
            return
        if self._channel_change_blocked(channel_id):
            return
        if confirm_delete(self.addon, channel.get("name", channel_id)):
            self.manager.delete_channel(channel_id)
            xbmc.executebuiltin("Container.Refresh")

    def reset_channel(self, params: dict) -> None:
        """Reset a channel queue and cursor after confirmation."""
        channel_id = params.get("channel_id", "")
        channel    = self.manager.get_channel(channel_id)
        if not channel:
            return
        if self._channel_change_blocked(channel_id):
            return
        if confirm_reset(self.addon, channel.get("name", channel_id)):
            self.manager.reset_channel(channel_id)
            xbmc.executebuiltin("Container.Refresh")

    def move_channel_up(self, params: dict) -> None:
        """Move a channel one position up in the list."""
        channel_id = params.get("channel_id", "")
        self.manager.move_channel_up(channel_id)
        xbmc.executebuiltin("Container.Refresh")

    def move_channel_down(self, params: dict) -> None:
        """Move a channel one position down in the list."""
        channel_id = params.get("channel_id", "")
        self.manager.move_channel_down(channel_id)
        xbmc.executebuiltin("Container.Refresh")

    # -------------------------------------------------------------------------
    # channel_info
    # -------------------------------------------------------------------------

    def channel_info(self, params: dict) -> None:
        channel_id = params.get("channel_id", "")
        show_channel_info(self.addon, self.manager, channel_id)

    # -------------------------------------------------------------------------
    # set_channel_icon
    # -------------------------------------------------------------------------

    def set_channel_icon(self, params: dict) -> None:
        channel_id = params.get("channel_id", "")
        ch = self.manager.get_channel(channel_id)
        if not ch:
            return
        options = [self.addon.getLocalizedString(32700),    # Set Channel Icon
                   self.addon.getLocalizedString(32701)]    # Clear Icon
        choice = xbmcgui.Dialog().select(ch.get("name", ""), options)
        if choice < 0:
            return
        if choice == 0:
            path = xbmcgui.Dialog().browse(
                1, self.addon.getLocalizedString(32700),
                "files", ".png|.jpg|.jpeg",
                False, False, ch.get("icon_path", ""))
            if not path or path == ch.get("icon_path", ""):
                return
            self.manager.update_channel(channel_id, {"icon_path": path})
        elif choice == 1:
            self.manager.update_channel(channel_id, {"icon_path": ""})
        xbmc.executebuiltin("Container.Refresh")

    # -------------------------------------------------------------------------
    # toggle_channel_visibility
    # -------------------------------------------------------------------------

    def toggle_channel_visibility(self, params: dict) -> None:
        channel_id = params.get("channel_id", "")
        if channel_id:
            channel = self.manager.get_channel(channel_id)
            # A source channel must stay hidden — refuse to unhide it.
            if channel and not channel.get("visible", True):
                usage = self.manager.get_source_usage(channel_id)
                if usage:
                    xbmcgui.Dialog().ok(
                        self.addon.getLocalizedString(32000),
                        self.addon.getLocalizedString(32913).format(
                            channel.get("name", channel_id),
                            usage["channel_name"]))
                    return
            # A carousel channel must stay visible — refuse to hide it.
            if (channel and channel.get("visible", True)
                    and channel.get("carousel_enabled", False)):
                xbmcgui.Dialog().ok(
                    self.addon.getLocalizedString(32000),
                    self.addon.getLocalizedString(32915).format(
                        channel.get("name", channel_id)))
                return
            self.manager.toggle_visibility(channel_id)
            xbmc.executebuiltin("Container.Refresh")

    # -------------------------------------------------------------------------
    # manage_interleave
    # -------------------------------------------------------------------------

    def manage_interleave(self, params: dict) -> None:
        channel_id = params.get("channel_id", "")
        if channel_id and self._channel_change_blocked(channel_id):
            return
        if channel_id:
            from resources.lib.ui.wizards.interleave import run as interleave_run
            interleave_run(self.addon, self.manager, channel_id)

    # -------------------------------------------------------------------------
    # view_exclusions
    # -------------------------------------------------------------------------

    def view_exclusions_action(self, params: dict) -> None:
        channel_id = params.get("channel_id", "")
        view_exclusions(self.addon, self.manager, channel_id)

    # -------------------------------------------------------------------------
    # view_missing_durations
    # -------------------------------------------------------------------------

    def view_missing_durations_action(self, params: dict) -> None:
        channel_id = params.get("channel_id", "")
        view_missing_durations(self.addon, self.manager, channel_id)

    # -------------------------------------------------------------------------
    # add_schedule / manage_schedules
    # -------------------------------------------------------------------------

    def add_schedule(self, params: dict) -> None:
        channel_id = params.get("channel_id", "")
        xbmcplugin.endOfDirectory(self.handle, succeeded=False)
        from resources.lib.ui.schedule_wizard import ScheduleWizard
        wizard  = ScheduleWizard(self.addon, self.manager,
                                 target_channel_id=channel_id)
        result  = wizard.run()
        if result:
            self.manager.add_schedule(result)
            xbmc.executebuiltin("Container.Refresh")

    def manage_schedules(self, params: dict) -> None:
        xbmcplugin.endOfDirectory(self.handle, succeeded=False)
        from resources.lib.ui.schedule_wizard import manage_schedules as _manage
        _manage(self.addon, self.manager)

    # -------------------------------------------------------------------------
    # sort_channels_alpha
    # -------------------------------------------------------------------------

    def sort_channels_alpha(self, params: dict) -> None:
        self.manager.sort_channels_alpha()
        xbmc.executebuiltin("Container.Refresh")

    # -------------------------------------------------------------------------
    # open_channels (from settings)
    # -------------------------------------------------------------------------

    def auto_create_channels(self, params: dict) -> None:
        """Launch the Auto-Create Channels wizard."""
        from resources.lib.ui.auto_channels import AutoChannelUI
        xbmcplugin.endOfDirectory(self.handle, succeeded=False)
        AutoChannelUI(
            handle=self.handle,
            base_url=self.base_url,
            addon=self.addon,
            manager=self.manager,
        ).run()

    def ffprobe_scan(self, params: dict) -> None:
        """Launch the ffprobe batch NFO scanner wizard."""
        from resources.lib.ui.ffprobe_wizard import FfprobeWizard
        xbmcplugin.endOfDirectory(self.handle, succeeded=False)
        FfprobeWizard(self.addon).run()

    def view_missing_durations_global(self, params: dict) -> None:
        """Show the global missing_durations.txt log file in a textviewer."""
        from resources.lib.utils.paths import resolve_path
        import xbmcvfs
        path = resolve_path("missing_durations.txt")

        def _read_log():
            if not xbmcvfs.exists(path):
                return ""
            try:
                with xbmcvfs.File(path, "r") as f:
                    return f.read()
            except Exception:
                return ""

        text = _read_log()
        has_content = bool(text.strip())

        # Show a select dialog with View / Clear options.
        # If the log is empty, only offer to acknowledge.
        if not has_content:
            xbmcgui.Dialog().ok(
                self.addon.getLocalizedString(32000),
                self.addon.getLocalizedString(32715))
            return

        options = [
            self.addon.getLocalizedString(32906),   # "View Missing Durations Log"
            self.addon.getLocalizedString(32711),   # "Clear Missing Durations List"
        ]
        choice = xbmcgui.Dialog().select(
            self.addon.getLocalizedString(32000), options)

        if choice == 0:
            xbmcgui.Dialog().textviewer(
                self.addon.getLocalizedString(32906), text)

        elif choice == 1:
            confirmed = xbmcgui.Dialog().yesno(
                self.addon.getLocalizedString(32000),
                self.addon.getLocalizedString(32228))
            if confirmed:
                try:
                    xbmcvfs.delete(path)
                except Exception:
                    pass
                xbmcgui.Dialog().notification(
                    self.addon.getLocalizedString(32000),
                    self.addon.getLocalizedString(32229),
                    xbmcgui.NOTIFICATION_INFO, 2000)

    def refresh_songs_cache(self, params: dict) -> None:
        import threading
        xbmc.executebuiltin("Notification({},{},{},)".format(
            self.addon.getLocalizedString(32000),
            self.addon.getLocalizedString(32849),
            3000))
        def _build():
            self.manager.library.build_songs_cache()
        threading.Thread(target=_build, daemon=True).start()

    def open_channels(self, params: dict) -> None:
        xbmc.executebuiltin("Dialog.Close(all,true)")
        xbmc.sleep(300)
        xbmc.executebuiltin(
            "ActivateWindow(Videos,"
            "plugin://plugin.video.smartchannels/?action=list_channels,return)")

    # -------------------------------------------------------------------------
    # open_settings
    # -------------------------------------------------------------------------

    def open_settings(self, params: dict) -> None:
        self.addon.openSettings()

    # -------------------------------------------------------------------------
    # play_from_item
    # -------------------------------------------------------------------------

    def play_from_item(self, params: dict) -> None:
        channel_id  = params.get("channel_id")
        queue_index = params.get("queue_index")
        if not channel_id or queue_index is None:
            xbmcplugin.endOfDirectory(self.handle, succeeded=False)
            return
        try:
            queue_index = int(queue_index)
        except (ValueError, TypeError):
            xbmcplugin.endOfDirectory(self.handle, succeeded=False)
            return
        channel = self.manager.get_channel(channel_id)
        if not channel:
            xbmcplugin.endOfDirectory(self.handle, succeeded=False)
            return
        # Checked before the reorder: a blocked device must not touch the
        # owner's queue.
        if self._channel_busy_elsewhere(channel_id, channel):
            return
        if queue_index > 0:
            self.manager.reorder_queue_from_item(channel_id, queue_index)
        dummy = xbmcgui.ListItem(label=self.addon.getLocalizedString(32000))
        dummy.setProperty("IsPlayable", "true")
        xbmcplugin.setResolvedUrl(self.handle, succeeded=False, listitem=dummy)
        player = SmartPlayer(self.addon, self.manager)
        if player.start_channel(channel):
            stop_waiting(channel_id)

    # -------------------------------------------------------------------------
    # reset_next_episode (TC-30.17 — Reset Show context menu on episode)
    # -------------------------------------------------------------------------

    def reset_next_episode(self, params: dict) -> None:
        channel_id = params.get("channel_id")
        show_id    = params.get("show_id")
        if not channel_id or not show_id:
            return
        try:
            show_id = int(show_id)
        except (ValueError, TypeError):
            return
        channel    = self.manager.get_channel(channel_id)
        if not channel:
            return
        if self._channel_change_blocked(channel_id):
            return
        show_title = params.get("show_title", "")
        if not show_title:
            for s in channel.get("shows", []):
                if s.get("tvshowid") == show_id:
                    show_title = s.get("title", "")
                    break
        confirmed = xbmcgui.Dialog().yesno(
            self.addon.getLocalizedString(32353),
            self.addon.getLocalizedString(32354).format(show_title))
        if not confirmed:
            return
        ok = self.manager.reset_show_to_start(channel_id, show_id)
        if ok:
            xbmcgui.Dialog().notification(
                self.addon.getLocalizedString(32000),
                self.addon.getLocalizedString(32355).format(show_title),
                xbmcgui.NOTIFICATION_INFO, 2000)
            xbmc.executebuiltin("Container.Refresh")

    # -------------------------------------------------------------------------
    # refresh_library
    # -------------------------------------------------------------------------

    def refresh_library(self, params: dict) -> None:
        progress = xbmcgui.DialogProgress()
        progress.create(self.addon.getLocalizedString(32000),
                        self.addon.getLocalizedString(32356))
        cancelled = [False]

        def _on_progress(pct, msg):
            if progress.iscanceled():
                cancelled[0] = True
                return
            progress.update(pct, msg)

        try:
            success = self.manager.library.build_local_cache(
                progress_callback=_on_progress)
            progress.close()
            if cancelled[0]:
                xbmcgui.Dialog().notification(
                    self.addon.getLocalizedString(32000),
                    self.addon.getLocalizedString(32358),
                    xbmcgui.NOTIFICATION_WARNING, 2000)
            elif success:
                xbmcgui.Dialog().notification(
                    self.addon.getLocalizedString(32000),
                    self.addon.getLocalizedString(32359),
                    xbmcgui.NOTIFICATION_INFO, 2000)
            else:
                xbmcgui.Dialog().notification(
                    self.addon.getLocalizedString(32000),
                    self.addon.getLocalizedString(32360),
                    xbmcgui.NOTIFICATION_ERROR, 3000)
        except Exception as e:
            progress.close()
            xbmcgui.Dialog().notification(
                self.addon.getLocalizedString(32000),
                str(e)[:80],
                xbmcgui.NOTIFICATION_ERROR, 3000)
        xbmc.executebuiltin("Container.Refresh")

    # -------------------------------------------------------------------------
    # repair_queue_paths
    # -------------------------------------------------------------------------

    def repair_queue_paths(self, params: dict) -> None:
        """Settings > Cache button: refresh queued episodes from the library
        after files were renamed or moved (the Kodi library must already be
        updated)."""
        if not xbmcgui.Dialog().yesno(self.addon.getLocalizedString(32000),
                                      self.addon.getLocalizedString(32027)):
            return
        try:
            result = self.manager.repair_queue_paths()
        except Exception as e:
            xbmcgui.Dialog().notification(
                self.addon.getLocalizedString(32000),
                str(e)[:80], xbmcgui.NOTIFICATION_ERROR, 3000)
            return
        xbmcgui.Dialog().notification(
            self.addon.getLocalizedString(32000),
            self.addon.getLocalizedString(32028).format(
                result["fixed"], result["not_found"], result["unchanged"]),
            xbmcgui.NOTIFICATION_INFO, 4000)

    # -------------------------------------------------------------------------
    # backup_data / restore_data / delete_all_data
    # -------------------------------------------------------------------------

    def backup_data(self, params: dict) -> None:
        import xbmcvfs as _vfs, os as _os, datetime, zipfile
        from resources.lib.utils.paths import (
            shared_root as _shared_root,
            normalize_share_path as _normalize)

        backup_root = _normalize(self.addon.getSetting("backup_path"))
        if not backup_root:
            if xbmcgui.Dialog().yesno(self.addon.getLocalizedString(32362),
                                      self.addon.getLocalizedString(32363)):
                self.addon.openSettings()
                backup_root = _normalize(self.addon.getSetting("backup_path"))
            if not backup_root:
                return

        profile = _vfs.translatePath(self.addon.getAddonInfo("profile"))
        shared  = _shared_root()
        data_files = ["channels.json", "state.json",
                      "local_library.json", "now_playing.json"]
        for root in set(p for p in [profile, shared] if p):
            try:
                _, files = _vfs.listdir(root)
                for fn in files:
                    if fn.startswith("queue_") and fn.endswith(".json"):
                        data_files.append(fn)
            except Exception:
                pass
        data_files = list(dict.fromkeys(data_files))

        file_data = {}
        for fn in data_files:
            src = (shared + "/" + fn if shared and _vfs.exists(shared + "/" + fn)
                   else _os.path.join(profile, fn))
            try:
                if _vfs.exists(src):
                    with _vfs.File(src, "r") as f:
                        raw = f.read()
                    if raw:
                        file_data[fn] = (raw.encode("utf-8")
                                         if isinstance(raw, str) else raw)
            except Exception as e:
                log("[Router] backup: could not read {}: {}".format(src, e),
                    xbmc.LOGWARNING)

        if not file_data:
            xbmcgui.Dialog().ok(self.addon.getLocalizedString(32362),
                                self.addon.getLocalizedString(32365))
            return

        ts       = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_name = "SmartChannels_Backup_" + ts + ".zip"
        tmp_zip  = _os.path.join(
            _vfs.translatePath("special://temp/"), zip_name)
        zip_path = backup_root + "/" + zip_name
        try:
            with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                for arc_name, data in file_data.items():
                    zf.writestr(arc_name, data)
            # Create the backup folder if it is not there yet.
            if not _vfs.exists(backup_root + "/") and not _vfs.mkdirs(
                    backup_root + "/"):
                log("[Router] backup: could not create folder {}".format(
                    backup_root), xbmc.LOGWARNING)
            ok = _vfs.copy(tmp_zip, zip_path)
            if not ok:
                log("[Router] backup: copy of {} to {} failed".format(
                    tmp_zip, zip_path), xbmc.LOGERROR)
            try:
                _os.remove(tmp_zip)
            except Exception:
                pass
            if ok:
                xbmcgui.Dialog().ok(
                    self.addon.getLocalizedString(32362),
                    self.addon.getLocalizedString(32367).format(
                        len(file_data), zip_name))
            else:
                xbmcgui.Dialog().ok(
                    self.addon.getLocalizedString(32362),
                    self.addon.getLocalizedString(32368).format(zip_path))
        except Exception as e:
            log("[Router] backup: {}".format(e), xbmc.LOGERROR)
            xbmcgui.Dialog().ok(self.addon.getLocalizedString(32362), str(e))

    def restore_data(self, params: dict) -> None:
        import xbmcvfs as _vfs, os as _os, zipfile
        from resources.lib.utils.paths import (
            shared_root as _shared_root,
            normalize_share_path as _normalize)

        backup_root = _normalize(self.addon.getSetting("backup_path"))
        if not backup_root:
            if xbmcgui.Dialog().yesno(self.addon.getLocalizedString(32369),
                                      self.addon.getLocalizedString(32363)):
                self.addon.openSettings()
                backup_root = _normalize(self.addon.getSetting("backup_path"))
            if not backup_root:
                return

        try:
            _, dir_files = _vfs.listdir(backup_root)
            zips = sorted(
                [f for f in dir_files
                 if f.startswith("SmartChannels_Backup_")
                 and f.endswith(".zip")],
                reverse=True)
        except Exception as e:
            log("[Router] restore: cannot list {}: {}".format(
                backup_root, e), xbmc.LOGERROR)
            xbmcgui.Dialog().ok(self.addon.getLocalizedString(32369),
                                str(e))
            return
        if not zips:
            xbmcgui.Dialog().ok(
                self.addon.getLocalizedString(32369),
                self.addon.getLocalizedString(32372).format(backup_root))
            return

        chosen_idx = xbmcgui.Dialog().select(
            self.addon.getLocalizedString(32373), zips)
        if chosen_idx < 0:
            return

        zip_path = backup_root + "/" + zips[chosen_idx]
        profile  = _vfs.translatePath(self.addon.getAddonInfo("profile"))
        shared   = _shared_root()
        tmp_zip  = _os.path.join(
            _vfs.translatePath("special://temp/"), "_sc_restore_tmp.zip")

        try:
            if _os.path.exists(tmp_zip):
                _os.remove(tmp_zip)
            if not _vfs.copy(zip_path, tmp_zip):
                log("[Router] restore: copy of {} failed".format(zip_path),
                    xbmc.LOGERROR)
                xbmcgui.Dialog().ok(self.addon.getLocalizedString(32369),
                                    self.addon.getLocalizedString(32374))
                return
            zf        = zipfile.ZipFile(tmp_zip, "r")
            available = zf.namelist()
        except Exception as e:
            xbmcgui.Dialog().ok(self.addon.getLocalizedString(32362), str(e))
            return

        if not available:
            xbmcgui.Dialog().ok(self.addon.getLocalizedString(32369),
                                self.addon.getLocalizedString(32375))
            zf.close()
            return

        chosen = xbmcgui.Dialog().multiselect(
            self.addon.getLocalizedString(32376),
            available,
            preselect=list(range(len(available))))
        if not chosen:
            zf.close()
            return

        files_to_restore = [available[i] for i in chosen]
        if not xbmcgui.Dialog().yesno(
                self.addon.getLocalizedString(32377),
                self.addon.getLocalizedString(32378).format(
                    len(files_to_restore))):
            zf.close()
            return

        data_root     = (shared + "/") if shared else (profile.rstrip("/") + "/")
        needs_restart = False
        restored      = []
        failed        = []

        for fn in files_to_restore:
            dst = (profile.rstrip("/") + "/" + fn
                   if fn == "settings.xml" else data_root + fn)
            if fn == "settings.xml":
                needs_restart = True
            try:
                tmp_file = _os.path.join(
                    _vfs.translatePath("special://temp/"),
                    "_sc_restore_" + fn.replace("/", "_"))
                with _vfs.File(tmp_file, "w") as out:
                    out.write(zf.read(fn).decode("latin-1"))
                if _vfs.exists(dst):
                    _vfs.delete(dst)
                if _vfs.copy(tmp_file, dst):
                    restored.append(fn)
                else:
                    failed.append(fn)
                try:
                    _os.remove(tmp_file)
                except Exception:
                    pass
            except Exception:
                failed.append(fn)

        zf.close()
        try:
            _os.remove(tmp_zip)
        except Exception:
            pass

        parts = []
        if restored:
            parts.append(self.addon.getLocalizedString(32379).format(
                ", ".join(restored)))
        if failed:
            parts.append(self.addon.getLocalizedString(32380).format(
                ", ".join(failed)))
        if needs_restart and "settings.xml" in restored:
            parts.append(self.addon.getLocalizedString(32381))
        xbmcgui.Dialog().ok(self.addon.getLocalizedString(32382),
                            "\n".join(parts))
        if restored:
            xbmc.sleep(500)
            xbmc.executebuiltin("Container.Refresh")

    def delete_all_data(self, params: dict) -> None:
        import xbmcvfs as _vfs, os as _os
        from resources.lib.utils.paths import shared_root as _shared_root

        if not xbmcgui.Dialog().yesno(
                self.addon.getLocalizedString(32051),
                self.addon.getLocalizedString(32384)):
            return

        data_files = ["channels.json", "state.json",
                      "local_library.json", "now_playing.json"]

        def _delete_from(folder, is_network):
            deleted = 0
            for fn in data_files:
                p = (folder + "/" + fn if is_network
                     else _os.path.join(folder, fn))
                try:
                    if _vfs.exists(p):
                        _vfs.delete(p)
                        deleted += 1
                except Exception:
                    pass
            try:
                _, files = _vfs.listdir(folder)
                for fn in files:
                    if fn.startswith("queue_") and fn.endswith(".json"):
                        p = (folder + "/" + fn if is_network
                             else _os.path.join(folder, fn))
                        try:
                            if _vfs.exists(p):
                                _vfs.delete(p)
                                deleted += 1
                        except Exception:
                            pass
            except Exception:
                pass
            return deleted

        profile = _vfs.translatePath(self.addon.getAddonInfo("profile"))
        total   = _delete_from(profile, False)
        shared  = _shared_root()
        if shared:
            total += _delete_from(shared, "://" in shared)

        xbmcgui.Dialog().notification(
            self.addon.getLocalizedString(32000),
            self.addon.getLocalizedString(32385).format(total),
            xbmcgui.NOTIFICATION_INFO, 3000)
        xbmc.sleep(500)
        xbmc.executebuiltin("Container.Refresh")
