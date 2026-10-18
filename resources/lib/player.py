# plugin.video.smartchannels
# resources/lib/player.py
#
# OWNS:   start_channel() — builds the Kodi playlist and starts playback.
#         _write_now_playing() — writes now_playing.json.
#
# NEVER:  Playback event callbacks (service.py owns ALL of those).
#         State advancement, queue replacement, resume saves (service.py).
#         Any logic beyond building the playlist and calling play().
#
# spec §21 — player.py owns ONLY start_channel() and _write_now_playing().
#
# Version: 3.0.0

from __future__ import annotations

import json
import os
import time

import xbmc
import xbmcgui
import xbmcvfs

from resources.lib.utils.logger import log


class SmartPlayer:
    """Builds the initial playlist and starts playback. Nothing else."""

    def __init__(self, addon, manager):
        self.addon   = addon
        self.manager = manager

    def start_channel(self, channel: dict) -> bool:
        """Load existing queue (or build fresh if none exists), load the Kodi
        playlist and call play(). Returns False if the queue is empty.

        spec §7.1 — the disk queue is the stable source of truth.
        Queue is only rebuilt when no queue file exists (first play, reset,
        or post-edit rebuild). After that, 1-for-1 replacement in service.py
        keeps the queue current — we never rebuild from scratch on play.

        service.py takes over from the moment play() is called.
        """
        channel_id = channel["id"]
        log("[player] start_channel: '{}'".format(channel.get("name", channel_id)))

        # One device at a time: take the channel lock before any queue is
        # read or built.  False means another device holds the channel (the
        # menu normally catches this first; this covers a simultaneous start).
        if not self.manager.claim_channel_lock(channel_id):
            log("[player] start_channel: channel held by another device — "
                "not starting")
            return False

        # Reuse existing queue if present — it is already up to date via
        # 1-for-1 replacement in service.py.  Only build fresh when the queue
        # file does not exist yet (first play, channel reset, or post-edit).
        queue = self.manager.read_channel_queue(channel_id)
        if queue is None:
            # The queue file exists but could not be read (another device is
            # writing it, or the shared folder dropped).  Building a new queue
            # here would replace the real one.
            log("[player] start_channel: queue unreadable — not starting, "
                "not rebuilding", xbmc.LOGWARNING)
            xbmcgui.Dialog().notification(
                self.addon.getLocalizedString(32000),
                self.addon.getLocalizedString(32950),
                xbmcgui.NOTIFICATION_WARNING, 4000)
            return False
        if queue:
            log("[player] start_channel: reusing existing queue "
                "({} items)".format(len(queue)))
        else:
            log("[player] start_channel: no queue on disk — building fresh")
            queue = self.manager.build_channel_queue(channel)
            if not queue:
                log("[player] start_channel: empty queue for '{}' — "
                    "aborting".format(channel.get("name", channel_id)))
                return False
            self.manager.write_channel_queue(channel_id, queue)
            log("[player] start_channel: wrote {} items to queue file".format(
                len(queue)))

        # Write now_playing.json
        self._write_now_playing(channel, queue[0])

        # Check for a saved resume position on the first queue item.
        # Dialog is shown BEFORE play() so it is never a blocking overlay
        # on top of active video.  seek_to is None if no resume or user
        # declines; seekTime() is called after play() starts.
        seek_to = self._get_resume_position(channel["id"], queue[0])

        # Build Kodi playlist
        playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
        playlist.clear()
        for item in queue:
            li = _make_listitem(item)
            playlist.add(item["file"], li)

        log("[player] start_channel: playlist built with {} items, "
            "starting playback".format(len(queue)))
        xbmc.Player().play(playlist)

        # Store the seek target for service.py to execute in onAVStarted,
        # where seekTime() is guaranteed safe because Kodi has the file open.
        # Attempting seekTime() here (immediately after play()) is unreliable
        # — isPlaying() becomes True before the file is fully open.
        if seek_to is not None:
            log("[player] start_channel: pending seek at {:.0f}s — "
                "will execute in onAVStarted".format(seek_to))
            self.manager.set_pending_seek(channel["id"], seek_to)

        return True

    def _get_resume_position(self, channel_id: str,
                              first_item: dict) -> "float | None":
        """Return the resume position for first_item if one exists and the
        user confirms, otherwise None.  Called before play() so the dialog
        never blocks over active video.
        """
        if self.addon.getSetting("resume_on_stop") != "true":
            return None

        file_path = first_item.get("file", "")
        entry = self.manager.get_resume_position(channel_id, file_path)
        if not entry:
            return None

        position = entry.get("position", 0)
        if position <= 10:
            return None

        ask = self.addon.getSetting("resume_ask_user") == "true"
        if ask:
            mins = int(position // 60)
            secs = int(position % 60)
            title = first_item.get("title", "")
            show  = first_item.get("tvshowtitle", "")
            label = "{} - {}".format(show, title) if show else title
            time_str = "{}m {}s".format(mins, secs)
            if not xbmcgui.Dialog().yesno(
                    self.addon.getLocalizedString(32000),
                    self.addon.getLocalizedString(32400).format(label, time_str)):
                return None

        return float(position)

    @staticmethod
    def clear_now_playing(addon) -> None:
        """Clear active_channel_id from now_playing.json on playback stop.

        Prevents onAVStarted from mis-identifying non-SmartChannels playback
        (e.g. an IPTV/PVR player) as an active SmartChannels session when
        a stale now_playing.json is present from the previous channel.

        Written to the local profile only — the shared copy is intentionally
        local per client (spec §21) so there is no shared path to clear.
        """
        try:
            profile    = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
            local_path = os.path.join(profile, "now_playing.json")
            if not xbmcvfs.exists(local_path):
                return
            with xbmcvfs.File(local_path, "w") as f:
                f.write(json.dumps({"active_channel_id": None}, indent=2))
            log("[player] clear_now_playing: active_channel_id cleared")
        except Exception as exc:
            log("[player] clear_now_playing error: {}".format(exc))

    def _write_now_playing(self, channel: dict, first_item: dict) -> None:
        """Write now_playing.json so service.py knows which channel is active.

        Fields written per spec §21:
            active_channel_id, channel_name, title, tvshowtitle,
            season, episode, duration, start_time
        """
        channel_id = channel["id"]
        profile    = xbmcvfs.translatePath(
            self.addon.getAddonInfo("profile"))

        data = {
            "active_channel_id": channel_id,
            "channel_name":      channel.get("name", ""),
            "title":             first_item.get("title",       ""),
            "tvshowtitle":       first_item.get("tvshowtitle", ""),
            "season":            first_item.get("season",      0),
            "episode":           first_item.get("episode",     0),
            "duration":          first_item.get("duration",    0),
            "start_time":        time.time(),
        }

        # Always write to local profile first (fast, reliable)
        local_path = os.path.join(profile, "now_playing.json")
        try:
            with xbmcvfs.File(local_path, "w") as f:
                f.write(json.dumps(data, indent=2))
            log("[player] _write_now_playing: written to local profile")
        except Exception as exc:
            log("[player] _write_now_playing error: {}".format(exc))

        # If shared storage is configured, also copy there
        shared_path = self.manager._resolve_path("now_playing.json")
        if shared_path != local_path:
            try:
                xbmcvfs.copy(local_path, shared_path)
            except Exception as exc:
                log("[player] _write_now_playing: shared copy failed: "
                    "{}".format(exc))


# ---------------------------------------------------------------------------
# ListItem builder — used by player.py and service.py (playlist append)
# ---------------------------------------------------------------------------

def _make_listitem(item: dict) -> xbmcgui.ListItem:
    """Build an xbmcgui.ListItem from a queue item dict."""
    title    = item.get("title", "")
    is_movie = item.get("is_movie", False)
    silent   = item.get("_silent", False)

    # ── Audio items — handle before video path so Kodi shows music metadata
    # in the playlist rather than [Movie] or [Episode]. Matches 2.x exactly.
    if item.get("is_audio"):
        artist = item.get("artist", "") or ""
        label  = "{} — {}".format(artist, title) if artist else title
        li = xbmcgui.ListItem(label=label)
        li.setArt({"thumb": item.get("thumbnail", "")})
        try:
            tag = li.getMusicInfoTag()
            tag.setTitle(title)
            tag.setArtist(artist)
            tag.setAlbum(item.get("album", "") or "")
            tag.setYear(int(item.get("year",     0) or 0))
            tag.setDuration(int(item.get("duration", 0) or 0))
            tag.setRating(float(item.get("rating",   0) or 0))
            tag.setTrack(int(item.get("track",    0) or 0))
        except Exception:
            li.setInfo("music", {
                "title":    title,
                "artist":   artist,
                "album":    item.get("album", "") or "",
                "year":     int(item.get("year",     0) or 0),
                "duration": int(item.get("duration", 0) or 0),
            })
        li.setProperty("IsPlayable", "true")
        return li

    if silent and item.get("_channel_name"):
        label = item["_channel_name"]
    elif is_movie:
        label = title
    else:
        show  = item.get("tvshowtitle", "")
        s     = int(item.get("season",  0) or 0)
        e     = int(item.get("episode", 0) or 0)
        if show and s:
            label = "{} - S{:02d}E{:02d} - {}".format(show, s, e, title)
        else:
            label = title

    li = xbmcgui.ListItem(label=label)

    try:
        tag = li.getVideoInfoTag()
        if is_movie:
            tag.setMediaType("movie")
            tag.setTitle(title)
            tag.setDbId(int(item.get("movieid", -1) or -1))
            tag.setYear(int(item.get("year", 0) or 0))
            tag.setPlot(item.get("plot", "") or "")
            tag.setDuration(int(item.get("duration", 0) or 0))
        elif item.get("is_folder_item") or silent:
            tag.setMediaType("video")
            tag.setTitle(label)
        else:
            tag.setMediaType("episode")
            tag.setTitle(title)
            tag.setTvShowTitle(item.get("tvshowtitle", ""))
            tag.setSeason(int(item.get("season",  0) or 0))
            tag.setEpisode(int(item.get("episode", 0) or 0))
            tag.setDuration(int(item.get("duration", 0) or 0))
    except Exception:
        # Kodi version fallback
        if is_movie:
            li.setInfo("video", {"mediatype": "movie", "title": title})
        else:
            li.setInfo("video", {
                "mediatype":   "episode",
                "title":       title,
                "tvshowtitle": item.get("tvshowtitle", ""),
                "season":      int(item.get("season",  0) or 0),
                "episode":     int(item.get("episode", 0) or 0),
            })

    li.setProperty("IsPlayable", "true")
    return li
