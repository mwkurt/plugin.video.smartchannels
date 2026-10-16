"""
resources/lib/channels/audio.py
================================
Queue builder for Audio channels (channel_type="audio").

OWNS:   Fetching songs from the Kodi music library, applying audio_filters,
        included_albums, excluded_songs, ordering (shuffle with optional
        artist balancing / album order with optional album shuffle), and
        building/topping-up the queue.

NEVER:  State reads/writes, playback control, UI rendering.
        All library access via self._cm.library (LibraryClient).
        All queue file I/O via channel_manager methods.

CALLERS: channel_manager.py only — via build_queue() (fresh build) and
         get_one_replacement() (1-for-1 replacement, build_one()).
         ui/channels.py imports resolve_audio_mode() for the info screen.
"""

from __future__ import annotations

import random

from resources.lib.channels.base import BaseQueueBuilder
from resources.lib.utils.logger  import log


def resolve_audio_mode(channel: dict) -> tuple:
    """Return (order, balanced, album_shuffle) for an audio channel.

    Two orders exist: "no_repeat" (shuffle, every song once per cycle) and
    "album".  "audio_balanced" refines no_repeat and "audio_album_shuffle"
    refines album.  Channels saved before 3.1.77 are mapped on read:
        "random"        -> no_repeat
        "balanced"      -> no_repeat + balanced
        "album_shuffle" -> album + album shuffle
    Anything unrecognised is treated as no_repeat.  Nothing is rewritten on
    disk; the new fields are saved the next time the channel is edited.
    """
    order         = channel.get("audio_order", "random")
    balanced      = bool(channel.get("audio_balanced", False))
    album_shuffle = bool(channel.get("audio_album_shuffle", False))
    if order == "balanced":
        order, balanced = "no_repeat", True
    elif order == "album_shuffle":
        order, album_shuffle = "album", True
    elif order != "album":
        order = "no_repeat"
    return (order,
            balanced and order == "no_repeat",
            album_shuffle and order == "album")


class AudioQueueBuilder(BaseQueueBuilder):
    """
    Queue builder for Audio channels backed by the Kodi music library.

    Queue item keys:
        channel_id, _channel_id, songid, title, artist, album, genre,
        year, duration, file, track, disc, thumbnail, is_audio=True

    No NFO, no Duration Cache — duration comes directly from
    AudioLibrary.GetSongs response.

    Playback order (see resolve_audio_mode):
        "no_repeat" — shuffle; every song plays once per cycle.
                      audio_balanced: each artist gets equal turns and
                      cycles through its own songs independently.
        "album"     — albumartist -> album -> disc -> track.
                      audio_album_shuffle: albums play in random order and
                      every album plays once before any repeats.
    """

    def build(self, channel: dict, target_size: int,
              current_queue=None) -> list:
        """
        Build a fresh queue or top up an existing one.

        current_queue=None  -- fresh build: fetch all matching songs,
                               order them, trim to target_size.
        current_queue=list  -- top-up: re-fetch, exclude files already
                               in current_queue, append up to target_size
                               new items and return current_queue + new.
        """
        channel_id = channel["id"]
        order, balanced, album_shuffle = resolve_audio_mode(channel)

        songs = self._load_pool(channel)
        if not songs:
            return current_queue if current_queue is not None else []

        if current_queue is not None:
            # Top-up: exclude files already sitting in the queue
            queued_files = {item.get("file", "") for item in current_queue}
            songs = [s for s in songs
                     if s.get("file", "") not in queued_files]

            # no_repeat mode: also exclude song IDs played this cycle.
            # full_pool is the complete available song set (after exclusions)
            # used to detect when every song has played and the cycle resets.
            if order == "no_repeat":
                full_pool_ids = {s.get("songid", -1) for s in songs} | \
                                {item.get("songid", -1) for item in current_queue}
                songs = self._no_repeat_filter(
                    channel_id, songs, full_pool_ids)

            if not songs:
                log("[AudioQueueBuilder] top-up: all songs already queued")
                return current_queue

        # Order
        songs = self._sort_songs(songs, order, balanced, album_shuffle)

        # Trim to target_size
        songs = songs[:target_size]

        # Build queue items
        items = [self._song_to_item(channel_id, s) for s in songs]

        if current_queue is not None:
            log("[AudioQueueBuilder] top-up: {} new items for '{}'".format(
                len(items), channel.get("name", channel_id)))
            return current_queue + items

        log("[AudioQueueBuilder] built {} items for '{}'".format(
            len(items), channel.get("name", channel_id)))
        return items

    def _load_pool(self, channel: dict) -> list:
        """Return the channel's song pool: library songs matching the
        channel filters, with included_albums and excluded_songs applied.
        Returns [] (and logs why) when nothing is available."""
        channel_id      = channel["id"]
        filters         = channel.get("audio_filters", [])
        included_albums = channel.get("included_albums", {})
        excluded_songs  = set(channel.get("excluded_songs", []))

        # Fetch songs from library (cached within the LibraryClient instance)
        try:
            songs = self._cm.library.get_songs_with_filters(filters)
        except Exception as e:
            log("[AudioQueueBuilder] library fetch error: {}".format(e))
            return []

        if not songs:
            log("[AudioQueueBuilder] no songs found for channel '{}'".format(
                channel.get("name", channel_id)))
            return []

        # Apply included_albums filter -- only when artist mode was used
        # and at least one artist has an explicit album selection.
        # included_albums = {"Artist Name": ["Album A", "Album B"], ...}
        # An artist with an empty list means all albums included for them.
        if included_albums:
            songs = self._apply_included_albums(songs, filters,
                                                included_albums)

        # Apply excluded_songs -- set of songid ints
        if excluded_songs:
            before = len(songs)
            songs  = [s for s in songs
                      if s.get("songid", -1) not in excluded_songs]
            log("[AudioQueueBuilder] excluded_songs: removed {} song(s)".format(
                before - len(songs)))

        if not songs:
            log("[AudioQueueBuilder] no songs remain after exclusions "
                "for channel '{}'".format(channel.get("name", channel_id)))
        return songs

    @staticmethod
    def _song_to_item(channel_id: str, s: dict) -> dict:
        """Convert a library song dict to a queue item."""
        artist_list = s.get("artist", [])
        artist_str  = (", ".join(artist_list)
                       if isinstance(artist_list, list)
                       else str(artist_list))
        genre_list  = s.get("genre", [])
        genre_str   = (", ".join(genre_list)
                       if isinstance(genre_list, list)
                       else str(genre_list))
        return {
            "channel_id":  channel_id,
            "_channel_id": channel_id,
            "songid":      s.get("songid",    -1),
            "title":       s.get("title",      ""),
            "artist":      artist_str,
            "album":       s.get("album",      ""),
            "genre":       genre_str,
            "year":        int(s.get("year",   0) or 0),
            "duration":    int(s.get("duration", 0) or 0),
            "file":        s.get("file",       ""),
            "track":       int(s.get("track",  0) or 0),
            "disc":        int(s.get("disc",   0) or 0),
            "thumbnail":   s.get("thumbnail",  ""),
            "is_audio":    True,
        }

    @staticmethod
    def _album_id(s: dict) -> tuple:
        """Identify the album a library song belongs to."""
        aa = s.get("albumartist", [])
        aa_str = (", ".join(aa) if isinstance(aa, list) else str(aa))
        return (aa_str.lower(), s.get("album", "").lower())

    @classmethod
    def _album_sort_key(cls, s: dict) -> tuple:
        """albumartist -> album -> disc -> track -> file.

        The file path is the last tie-breaker so every song has a distinct
        key.  Without it, songs whose track number is not tagged (all 0)
        compare equal, and "the next song after the tail" (strictly
        greater key) skipped them.
        """
        return cls._album_id(s) + (int(s.get("disc",  0) or 0),
                                   int(s.get("track", 0) or 0),
                                   str(s.get("file", "")).lower())

    def build_one(self, channel: dict, host_queue: list,
                  consumed_item=None) -> list:
        """Return exactly one replacement song (or [] if none available).

        host_queue:    the queue the song will be appended to (consumed item
                       already removed).  Songs already in it are avoided
                       unless the pool is no larger than the queue.
        consumed_item: the item just played or skipped.  It is recorded as
                       played for no_repeat channels and for album channels
                       with album shuffle (which need it to cycle albums).

        Follows the channel's playback order from the end of host_queue:
        no_repeat picks a song not yet played this cycle (balanced: from a
        different artist than the queue tail, each artist cycling on its
        own); album continues in album order, or with album shuffle
        finishes the tail album and then starts an album not yet heard
        this cycle.
        """
        channel_id = channel["id"]
        mode       = resolve_audio_mode(channel)
        order, balanced, album_shuffle = mode
        songs      = self._load_pool(channel)
        if not songs:
            return []

        consumed_file = ""
        if consumed_item and consumed_item.get("is_audio"):
            consumed_file = consumed_item.get("file", "")
            if order == "no_repeat" or (order == "album" and album_shuffle):
                self.record_no_repeat_played(
                    channel_id, int(consumed_item.get("songid", -1)))

        own = [i for i in (host_queue or [])
               if i.get("is_audio")
               and (i.get("_channel_id") or channel_id) == channel_id]
        # On a skip the skipped item is still in host_queue but is about to
        # leave it, so it must not count as queued (it would hide the natural
        # next song when the pool is no larger than the queue).
        queued_files = {i.get("file", "") for i in own}
        queued_files.discard(consumed_file)
        tail = own[-1] if own else None

        candidates = [s for s in songs if s.get("file", "") not in queued_files]
        # Never hand back the song just played/skipped while others exist.
        others = [s for s in candidates if s.get("file", "") != consumed_file]
        if others:
            candidates = others
        if not candidates:
            # Pool smaller than the queue: a repeat is unavoidable.
            candidates = ([s for s in songs if s.get("file", "") != consumed_file]
                          or list(songs))

        pick = self._pick_next(channel_id, mode, songs, candidates, own, tail,
                               consumed_file)
        if pick is None:
            return []
        artist = self._primary_artist(pick)
        log("[AudioQueueBuilder] build_one: '{}' by '{}' [{}] for '{}' "
            "(order={} balanced={} album_shuffle={})".format(
                pick.get("title", ""), artist, pick.get("album", ""),
                channel.get("name", channel_id), order, balanced,
                album_shuffle))
        return [self._song_to_item(channel_id, pick)]

    def _pick_next(self, channel_id: str, mode: tuple, songs: list,
                   candidates: list, own: list, tail, consumed_file: str):
        """Choose the next song from candidates according to mode."""
        order, balanced, album_shuffle = mode

        # The queue item has no albumartist, so find the tail's library
        # song (by file) to get its artist / place in album order.
        tail_song = None
        if tail is not None:
            tail_song = next((s for s in songs
                              if s.get("file", "") == tail.get("file", "")),
                             None)

        if order == "no_repeat":
            if balanced:
                return self._pick_balanced(channel_id, songs, candidates,
                                           own, tail_song)
            played = set(self._cm.get_audio_no_repeat_played(channel_id))
            avail  = [s for s in candidates if s.get("songid", -1) not in played]
            if not avail:
                log("[AudioQueueBuilder] no_repeat: full cycle complete for "
                    "'{}', resetting played list".format(channel_id))
                self._cm.set_audio_no_repeat_played(channel_id, [])
                avail = ([s for s in candidates
                          if s.get("file", "") != consumed_file] or candidates)
            return random.choice(avail)

        if tail_song is None:
            return random.choice(candidates)

        ordered    = sorted(candidates, key=self._album_sort_key)
        tail_key   = self._album_sort_key(tail_song)
        tail_album = self._album_id(tail_song)
        later      = [s for s in ordered
                      if self._album_sort_key(s) > tail_key]
        if not album_shuffle:
            # Next song after the tail in album order, wrapping round.
            return later[0] if later else ordered[0]
        # Album shuffle: finish the tail's album first.
        same = [s for s in later if self._album_id(s) == tail_album]
        if same:
            return same[0]
        return self._pick_next_album(channel_id, songs, ordered, own,
                                    tail_album)

    def _pick_balanced(self, channel_id: str, songs: list, candidates: list,
                       own: list, tail_song):
        """Balanced no_repeat pick.

        Picks an artist other than the tail's artist (equal turns per
        artist), then one of that artist's songs not yet played in its own
        cycle.  A song counts as used once it has played or is waiting in
        the queue; when every song of an artist is used, only that artist's
        songs are cleared from the played list and it starts over.
        """
        tail_artist = (self._primary_artist(tail_song)
                       if tail_song is not None else None)
        played      = set(self._cm.get_audio_no_repeat_played(channel_id))
        queued_ids  = {i.get("songid", -1) for i in own}
        cand_files  = {s.get("file", "") for s in candidates}

        catalogue = {}
        for s in songs:
            catalogue.setdefault(self._primary_artist(s), []).append(s)

        changed = False
        avail   = {}
        for artist, lst in catalogue.items():
            ids = {s.get("songid", -1) for s in lst}
            if ids <= (played | queued_ids):
                log("[AudioQueueBuilder] balanced: all {} song(s) by '{}' "
                    "used, starting that artist over".format(
                        len(lst), artist))
                played -= ids
                changed = True
            pool = [s for s in lst
                    if s.get("songid", -1) not in played
                    and s.get("file", "") in cand_files]
            if pool:
                avail[artist] = pool
        if changed:
            self._cm.set_audio_no_repeat_played(channel_id, sorted(played))

        if not avail:
            # Everything left is already queued: a repeat is unavoidable.
            return random.choice(candidates)
        artists = [a for a in avail if a != tail_artist] or list(avail)
        return random.choice(avail[random.choice(artists)])

    def _pick_next_album(self, channel_id: str, songs: list, ordered: list,
                         own: list, tail_album: tuple):
        """First song of the next album for album shuffle.

        Chooses at random among albums not heard this cycle, not queued and
        not the tail album.  When every other album has been heard the
        played list is cleared and a new cycle starts.
        """
        by_file = {s.get("file", ""): s for s in songs}
        queued  = {self._album_id(by_file[i.get("file", "")])
                   for i in own if i.get("file", "") in by_file}
        played  = set(self._cm.get_audio_no_repeat_played(channel_id))
        heard   = {self._album_id(s) for s in songs
                   if s.get("songid", -1) in played}
        albums  = sorted({self._album_id(s) for s in ordered})
        busy    = queued | {tail_album}

        fresh = [a for a in albums if a not in busy and a not in heard]
        if not fresh:
            rest = [a for a in albums if a not in busy]
            if rest:
                log("[AudioQueueBuilder] album_shuffle: all albums played "
                    "for '{}', starting a new cycle".format(channel_id))
                self._cm.set_audio_no_repeat_played(channel_id, [])
                fresh = rest
            else:
                # Every album is queued or is the tail album.
                fresh = ([a for a in albums if a != tail_album] or albums)
        chosen = random.choice(fresh)
        return next(s for s in ordered if self._album_id(s) == chosen)

    def _apply_included_albums(self, songs: list, filters: list,
                               included_albums: dict) -> list:
        """
        Filter songs to only those whose album appears in included_albums
        for their matched artist.

        Only applied when mode = Artist picker (all filters have type=artist).
        For artists with an empty album list, all their albums are included.
        Songs from artists not in included_albums are excluded entirely.
        """
        if not filters or not all(f.get("type") == "artist"
                                  for f in filters):
            return songs

        artist_names_lower = {name.lower(): name
                               for name in included_albums.keys()}
        result = []
        for song in songs:
            song_artists = song.get("artist", [])
            if isinstance(song_artists, str):
                song_artists = [song_artists]
            for sa in song_artists:
                sa_lower = sa.lower()
                matched_name = None
                for configured_lower, configured_name in \
                        artist_names_lower.items():
                    if configured_lower in sa_lower:
                        matched_name = configured_name
                        break
                if matched_name is None:
                    continue
                allowed_albums = included_albums.get(matched_name, [])
                # Empty list = all albums allowed for this artist
                if not allowed_albums or \
                        song.get("album", "") in allowed_albums:
                    result.append(song)
                    break  # don't double-add if song matches multiple artists
        return result

    def _no_repeat_filter(self, channel_id: str, songs: list,
                          full_pool_ids: set) -> list:
        """
        Filter songs for no_repeat mode.

        Reads the played-songids list via channel_manager public API.
        Excludes any song whose songid appears in that list.
        If excluding played songs leaves nothing (all songs have been heard),
        resets the played list and returns all songs — starting a new cycle.
        """
        played    = set(self._cm.get_audio_no_repeat_played(channel_id))
        available = [s for s in songs if s.get("songid", -1) not in played]

        if not available:
            # Every song in the pool has been played — reset and start over.
            log("[AudioQueueBuilder] no_repeat: full cycle complete for \'{}\'"
                ", resetting played list".format(channel_id))
            self._cm.set_audio_no_repeat_played(channel_id, [])
            played    = set()
            available = songs  # all songs are fair game again

        log("[AudioQueueBuilder] no_repeat: {}/{} songs available ({} played)"
            .format(len(available), len(full_pool_ids), len(played)))
        return available

    def record_no_repeat_played(self, channel_id: str, songid: int) -> None:
        """
        Record a song as played for no_repeat / album-shuffle tracking.
        Called from build_one() for the consumed item.
        """
        if songid < 0:
            return
        played = self._cm.get_audio_no_repeat_played(channel_id)
        if songid not in played:
            played.append(songid)
            self._cm.set_audio_no_repeat_played(channel_id, played)

    def _sort_songs(self, songs: list, order: str, balanced: bool = False,
                    album_shuffle: bool = False) -> list:
        """
        Order the song list for a fresh build or top-up.

        order=="album"     -- albumartist -> album -> disc -> track, or with
                              album_shuffle the albums in random order.
        order=="no_repeat" -- pure shuffle (repeat avoidance is upstream),
                              or with balanced an artist-interleaved shuffle.
        """
        songs = list(songs)   # copy -- don't mutate the cached library list
        if order == "album":
            if album_shuffle:
                songs = self._album_shuffle(songs)
            else:
                songs.sort(key=self._album_sort_key)
        elif balanced:
            songs = self._balanced_shuffle(songs)
        else:
            random.shuffle(songs)
        return songs

    def _album_shuffle(self, songs: list) -> list:
        """
        Album-coherent shuffle.

        Groups songs by album (album artist + title), shuffles the album
        sequence randomly, then sorts tracks within each album by
        disc -> track number.

        Result: complete albums play through in order, but the sequence of
        albums is randomised across all artists.
        """
        by_album = {}
        for s in songs:
            by_album.setdefault(self._album_id(s), []).append(s)

        for album_songs in by_album.values():
            album_songs.sort(key=lambda s: (
                int(s.get("disc",  0) or 0),
                int(s.get("track", 0) or 0),
            ))

        album_keys = list(by_album.keys())
        random.shuffle(album_keys)

        result = []
        for key in album_keys:
            result.extend(by_album[key])
        return result

    def _balanced_shuffle(self, songs: list) -> list:
        """
        Artist-interleaved shuffle.

        Groups songs by primary artist, shuffles each group independently,
        then interleaves in round-robin order with per-pass artist-order
        jitter so it doesn't feel mechanical.

        Result: each artist gets equal turns regardless of catalogue size.
        """
        by_artist = {}
        for s in songs:
            by_artist.setdefault(self._primary_artist(s), []).append(s)

        pools = list(by_artist.values())
        for pool in pools:
            random.shuffle(pool)

        result  = []
        indices = list(range(len(pools)))
        last    = None            # artist pool played last in the previous pass
        while True:
            random.shuffle(indices)
            active = [i for i in indices if pools[i]]
            if not active:
                break
            # Do not start a pass with the artist that ended the last one.
            if last is not None and len(active) > 1 and active[0] == last:
                j = random.randrange(1, len(active))
                active[0], active[j] = active[j], active[0]
            for i in active:
                result.append(pools[i].pop(0))
            last = active[-1]
        return result

    @staticmethod
    def _primary_artist(s: dict) -> str:
        """Artist a song is grouped under for Balanced order."""
        artist_list = s.get("artist", [])
        if isinstance(artist_list, list) and artist_list:
            return artist_list[0]
        if isinstance(artist_list, str) and artist_list:
            return artist_list
        return "Unknown"
