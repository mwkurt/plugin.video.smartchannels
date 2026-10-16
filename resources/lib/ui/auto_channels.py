"""
resources/lib/ui/auto_channels.py
==================================
Auto-Channel Creation wizard.

OWNS:   The complete Auto-Create Channels wizard UI and channel definition
        assembly. Calls channel_manager.create_channel() for all actual
        channel creation — no direct JSON or state writes here.

NEVER:  State reads/writes, queue building, playback logic, JSON-RPC calls,
        hardcoded user-visible strings (all text via self._s() / strings.po).

Entry point: AutoChannelUI(handle, base_url, addon, manager).run()
Called from: router.py -> auto_create_channels()

Wizard flow
-----------
Screen 1  Content type   (TV / Movies / Both)
Screen 2  Group by       (Genre / Decade / Genre+Decade / Studio/Network)
Screen 3  Minimum items  (numeric input, default 5)
Screen 4  Settings       (shows global defaults, OK to confirm)
Screen 5  Interleave?    (only when Both + Genre or Decade grouping)
Screen 6  Preview        (multiselect — check/uncheck channels to create)
Screen 7  Confirm        (yes/no)
Screen 8  Progress       (no user input)
Screen 9  Done           (OK)
"""

from __future__ import annotations

import random
import xbmc
import xbmcgui

from resources.lib.utils.logger import log

# String IDs — all user-visible text through strings.po
_S_TITLE             = 32003   # "Auto-Create Channels"
_S_CONTENT_Q         = 32630   # "What would you like to create channels for?"
_S_TV_ONLY           = 32631
_S_MOVIES_ONLY       = 32632
_S_BOTH              = 32633
_S_GROUP_Q           = 32634   # "Group channels by:"
_S_GENRE             = 32492
_S_DECADE            = 32636
_S_GENRE_DECADE      = 32637
_S_STUDIO_NETWORK    = 32638
_S_MIN_Q             = 32639   # "Minimum items per channel"
_S_MIN_BODY          = 32640
_S_SETTINGS_TITLE    = 32641
_S_SETTINGS_BODY     = 32642
_S_SETTINGS_VALS     = 32643   # "{0} {1} {2} {3}"
_S_INTERLEAVE_Q      = 32644
_S_INTERLEAVE_BODY   = 32645
_S_INTERLEAVE_FREQ_Q = 32646
_S_PREVIEW_TITLE     = 32647   # "Channels to create"
_S_PREVIEW_COUNT     = 32648   # "{0} selected of {1}"
_S_FMT_MOVIES        = 32649   # "{0} ({1} movies)"
_S_FMT_TV            = 32650   # "{0} ({1} shows, {2} episodes)"
_S_FMT_INTERLEAVED   = 32651   # "{0} ({1} shows + {2} movies)"
_S_FMT_BELOW_MIN     = 32652   # "{0} — below minimum ({1} items)"
_S_FMT_EXISTS        = 32653   # "{0} — already exists"
_S_CREATE_SELECTED   = 32654
_S_CONFIRM_TITLE     = 32655   # "Create {0} channels?"
_S_CONFIRM_BODY      = 32656   # "This will add {0} new channels..."
_S_PROGRESS_TITLE    = 32657
_S_PROGRESS_LINE     = 32658   # "Creating channel {0} of {1}: {2}"
_S_DONE_TITLE        = 32491
_S_DONE_OK           = 32660   # "{0} channels created successfully."
_S_DONE_SKIPPED      = 32661   # "{0} created. {1} skipped — already exist."
_S_NO_CHANNELS       = 32662
_S_NO_CHANNELS_BODY  = 32663
_S_ROUND_ROBIN       = 32664
_S_RANDOM            = 32217
_S_YES               = 32607
_S_DECADE_FMT        = 32665   # "{0}s"
_S_TV_NAME           = 32666   # "{0} TV"
_S_MOVIE_NAME        = 32667   # "{0} Movies"
_S_DECADE_TV         = 32668   # "{0}s TV"
_S_DECADE_MOVIE      = 32669   # "{0}s Movies"
_S_GENRE_DECADE_TV   = 32670   # "{0}s {1} TV"
_S_GENRE_DECADE_MOV  = 32671   # "{0}s {1} Movies"
_S_INTERLEAVE_GENRE  = 32672   # "{0} — TV + Movies"
_S_INTERLEAVE_DECADE = 32673   # "{0}s — TV + Movies"
_S_INTERLEAVE_GD     = 32674   # "{0}s {1} — TV + Movies"
_S_LIB_NOT_READY     = 32675
_S_LIB_NOT_READY_B   = 32676
_S_INVALID_FREQ      = 32677
_S_INVALID_FREQ_B    = 32678
_S_INVALID_MIN       = 32679
_S_INVALID_MIN_B     = 32680
_S_START_Q           = 32681   # "Starting Episodes"
_S_START_SURPRISE    = 32682   # "Randomising starting episodes..."

_DEFAULT_MIN       = 5
_DEFAULT_FREQ      = 4
_DEFAULT_QUEUE_SZ  = 30

# Content-type constants
_CT_TV      = "tv"
_CT_MOVIES  = "movies"
_CT_BOTH    = "both"

# Grouping constants
_GRP_GENRE        = "genre"
_GRP_DECADE       = "decade"
_GRP_GENRE_DECADE = "genre_decade"
_GRP_STUDIO       = "studio"


class AutoChannelUI:
    """
    Auto-Channel Creation wizard.
    Instantiated by router.py and invoked via .run().
    """

    def __init__(self, handle, base_url, addon, manager):
        self.handle   = handle
        self.base_url = base_url
        self.addon    = addon
        self.manager  = manager

    def _s(self, sid: int) -> str:
        """Return localised string. Never hardcode user-visible text."""
        return self.addon.getLocalizedString(sid)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self):
        """
        Run the full wizard. Returns when the user completes or cancels.
        Each screen returns None on cancel/back — propagated up to abort.
        """
        log("[AutoChannelUI] wizard started")

        # Ensure library cache exists before doing anything
        if not self._library_ready():
            xbmcgui.Dialog().ok(
                self._s(_S_TITLE),
                self._s(_S_LIB_NOT_READY_B))
            return

        # Screen 1 — Content type
        content_type = self._screen_content_type()
        if content_type is None:
            return

        # Screen 2 — Group by
        grouping = self._screen_grouping(content_type)
        if grouping is None:
            return

        # Screen 3 — Minimum items
        minimum = self._screen_minimum()
        if minimum is None:
            return

        # Screen 4 — Settings confirmation
        if not self._screen_settings():
            return

        # Screen 5 — Interleave (only for Both + Genre/Decade grouping)
        interleave_freq = None
        if (content_type == _CT_BOTH
                and grouping in (_GRP_GENRE, _GRP_DECADE, _GRP_GENRE_DECADE)):
            interleave_freq = self._screen_interleave()
            if interleave_freq is None:
                return   # user cancelled

        # Build candidate channel list
        candidates = self._build_candidates(
            content_type, grouping, minimum, interleave_freq)

        if not candidates:
            xbmcgui.Dialog().ok(
                self._s(_S_TITLE),
                self._s(_S_NO_CHANNELS_BODY))
            return

        # Screen 6 — Preview / multiselect
        selected = self._screen_preview(candidates)
        if selected is None:
            return

        if not selected:
            return

        # Screen 7 — Confirm
        if not self._screen_confirm(len(selected)):
            return

        # Screen 8+9 — Create with progress, then done dialog
        self._create_channels(selected)

    # ------------------------------------------------------------------
    # Screen 1 — Content type
    # ------------------------------------------------------------------

    def _screen_content_type(self):
        choices = [
            self._s(_S_TV_ONLY),
            self._s(_S_MOVIES_ONLY),
            self._s(_S_BOTH),
        ]
        idx = xbmcgui.Dialog().select(
            self._s(_S_CONTENT_Q), choices)
        if idx < 0:
            return None
        return [_CT_TV, _CT_MOVIES, _CT_BOTH][idx]

    # ------------------------------------------------------------------
    # Screen 2 — Group by
    # ------------------------------------------------------------------

    def _screen_grouping(self, content_type):
        choices = [
            self._s(_S_GENRE),
            self._s(_S_DECADE),
            self._s(_S_GENRE_DECADE),
            self._s(_S_STUDIO_NETWORK),
        ]
        idx = xbmcgui.Dialog().select(
            self._s(_S_GROUP_Q), choices)
        if idx < 0:
            return None
        return [_GRP_GENRE, _GRP_DECADE, _GRP_GENRE_DECADE, _GRP_STUDIO][idx]

    # ------------------------------------------------------------------
    # Screen 3 — Minimum items
    # ------------------------------------------------------------------

    def _screen_minimum(self):
        d = xbmcgui.Dialog()
        while True:
            result = d.input(
                self._s(_S_MIN_Q),
                defaultt=str(_DEFAULT_MIN),
                type=xbmcgui.INPUT_NUMERIC)
            if result == "" or result is None:
                return None
            try:
                val = int(result)
                if val < 0:
                    d.ok(self._s(_S_TITLE), self._s(_S_INVALID_MIN_B))
                    continue
                return val
            except ValueError:
                d.ok(self._s(_S_TITLE), self._s(_S_INVALID_MIN_B))

    # ------------------------------------------------------------------
    # Screen 4 — Settings confirmation (read-only display)
    # ------------------------------------------------------------------

    def _screen_settings(self):
        queue_size, tv_random, _recycle = self._get_defaults()

        tv_rot  = self._s(_S_RANDOM) if tv_random else self._s(_S_ROUND_ROBIN)
        mov_rot = self._s(_S_RANDOM)
        rec_str = self._s(_S_YES)   # channels always recycle

        body = (self._s(_S_SETTINGS_BODY) + "\n\n"
                + self._s(_S_SETTINGS_VALS).format(
                    tv_rot, mov_rot, rec_str, queue_size))

        result = xbmcgui.Dialog().yesno(
            self._s(_S_SETTINGS_TITLE), body)
        return result

    # ------------------------------------------------------------------
    # Screen 5 — Interleave
    # ------------------------------------------------------------------

    def _screen_interleave(self):
        """
        Ask whether to create interleaved TV+Movie channels.
        If yes, ask for frequency.
        Returns frequency int if yes, 0 if no, None if cancelled.
        """
        d = xbmcgui.Dialog()
        want = d.yesno(
            self._s(_S_TITLE),
            self._s(_S_INTERLEAVE_BODY))
        if not want:
            return 0   # 0 = no interleave, not cancelled

        while True:
            result = d.input(
                self._s(_S_INTERLEAVE_FREQ_Q),
                defaultt=str(_DEFAULT_FREQ),
                type=xbmcgui.INPUT_NUMERIC)
            if result == "" or result is None:
                return None
            try:
                freq = int(result)
                if freq < 1 or freq > 20:
                    d.ok(self._s(_S_TITLE), self._s(_S_INVALID_FREQ_B))
                    continue
                return freq
            except ValueError:
                d.ok(self._s(_S_TITLE), self._s(_S_INVALID_FREQ_B))

    # ------------------------------------------------------------------
    # Screen 6 — Preview multiselect
    # ------------------------------------------------------------------

    def _screen_preview(self, candidates):
        """
        Show all candidates as a multiselect list.
        Channels above minimum are pre-selected.
        Channels that already exist are shown but locked out (not selectable).
        Returns list of selected candidate dicts, or None if cancelled.
        """
        d = xbmcgui.Dialog()

        labels      = []
        preselect   = []
        locked_idxs = set()   # indices of already-existing channels

        for i, c in enumerate(candidates):
            if c["exists"]:
                labels.append(self._s(_S_FMT_EXISTS).format(c["name"]))
                locked_idxs.add(i)
            else:
                labels.append(c["display"])

        chosen = d.multiselect(
            self._s(_S_PREVIEW_TITLE),
            labels,
            preselect=preselect)

        if chosen is None:
            return None

        # Filter out any locked (already-existing) channels the user
        # may have toggled — we honour the lock server-side.
        chosen = [i for i in chosen if i not in locked_idxs]

        return [candidates[i] for i in chosen]

    # ------------------------------------------------------------------
    # Screen 7 — Confirm
    # ------------------------------------------------------------------

    def _screen_confirm(self, count):
        return xbmcgui.Dialog().yesno(
            self._s(_S_CONFIRM_TITLE).format(count),
            self._s(_S_CONFIRM_BODY).format(count))

    # ------------------------------------------------------------------
    # Screen 8 — Create with progress + Screen 9 — Done
    # ------------------------------------------------------------------

    def _create_channels(self, selected):
        total    = len(selected)
        created  = 0
        skipped  = 0

        queue_size, tv_random, recycle = self._get_defaults()

        # Ask starting point preference once for all TV candidates.
        # Only shown if at least one selected candidate has TV shows.
        # Must be asked BEFORE opening the progress dialog, which
        # would block any subsequent dialogs from appearing.
        has_tv = any(c["channel_type"] in (_CT_TV, _CT_BOTH)
                     for c in selected)
        surprise_start = False
        if has_tv:
            d = xbmcgui.Dialog()
            _start_choice = d.select(
                self._s(_S_START_Q),
                [self._s(32471),   # Start from S01E01 (default)
                 self._s(32473)])  # Surprise Me!
            if _start_choice < 0:
                return   # user cancelled
            surprise_start = (_start_choice == 1)

        # Open progress dialog only after all pre-creation dialogs done
        progress = xbmcgui.DialogProgress()
        progress.create(self._s(_S_PROGRESS_TITLE))
        try:
            for i, candidate in enumerate(selected):
                if progress.iscanceled():
                    break

                pct = int((i / total) * 100)
                progress.update(
                    pct,
                    self._s(_S_PROGRESS_LINE).format(
                        i + 1, total, candidate["name"]))

                # Double-check name collision at creation time
                # (user may have been in preview for a while)
                existing_names = {
                    ch["name"] for ch in self.manager.get_all_channels()}
                if candidate["name"] in existing_names:
                    skipped += 1
                    log("[AutoChannelUI] skipping '{}' — name exists".format(
                        candidate["name"]))
                    continue

                try:
                    definition = self._build_definition(
                        candidate, queue_size, tv_random, recycle,
                        surprise_start)
                    self.manager.create_channel(definition)
                    created += 1
                    log("[AutoChannelUI] created '{}'".format(
                        candidate["name"]))
                except Exception as e:
                    log("[AutoChannelUI] error creating '{}': {}".format(
                        candidate["name"], e))
                    skipped += 1

        finally:
            progress.close()

        # Screen 9 — Done
        if skipped > 0:
            msg = self._s(_S_DONE_SKIPPED).format(created, skipped)
        else:
            msg = self._s(_S_DONE_OK).format(created)

        xbmcgui.Dialog().ok(self._s(_S_DONE_TITLE), msg)
        log("[AutoChannelUI] complete — {} created, {} skipped".format(
            created, skipped))
        if created > 0:
            xbmc.executebuiltin("Container.Refresh")

    # ------------------------------------------------------------------
    # Candidate building
    # ------------------------------------------------------------------

    def _build_candidates(self, content_type, grouping,
                          minimum, interleave_freq):
        """
        Query the library and assemble a list of candidate channel dicts.
        Each dict has:
          name        str   — display name / channel name
          display     str   — formatted label for preview list
          item_count  int   — number of items (for threshold check)
          above_min   bool
          exists      bool  — name collision with existing channel
          channel_type str
          definition  dict  — partial definition for create_channel()
        """
        lib      = self.manager.library
        existing = {ch["name"] for ch in self.manager.get_all_channels()}

        # Gather all TV shows and movies with full metadata
        all_shows  = (lib.get_all_tvshows_full()
                      if content_type in (_CT_TV, _CT_BOTH) else [])
        all_movies = (lib.get_all_movies()
                      if content_type in (_CT_MOVIES, _CT_BOTH) else [])

        candidates = []

        if grouping == _GRP_GENRE:
            candidates = self._candidates_by_genre(
                content_type, all_shows, all_movies,
                minimum, existing, interleave_freq)

        elif grouping == _GRP_DECADE:
            candidates = self._candidates_by_decade(
                content_type, all_shows, all_movies,
                minimum, existing, interleave_freq)

        elif grouping == _GRP_GENRE_DECADE:
            candidates = self._candidates_by_genre_decade(
                content_type, all_shows, all_movies,
                minimum, existing, interleave_freq)

        elif grouping == _GRP_STUDIO:
            candidates = self._candidates_by_studio(
                content_type, all_shows, all_movies,
                minimum, existing)

        # Sort: above-min first, then below-min; alphabetical within each
        candidates.sort(key=lambda c: (not c["above_min"], c["name"].lower()))

        # Hide below-minimum candidates unless minimum=0 (show all).
        # Candidates below the threshold cannot be created as meaningful
        # channels and add scroll noise — especially for Studio grouping
        # where single-movie studios are common in large libraries.
        if minimum > 0:
            candidates = [c for c in candidates
                          if c["above_min"] or c["exists"]]

        return candidates

    # -- Genre grouping ------------------------------------------------

    def _candidates_by_genre(self, content_type, all_shows, all_movies,
                             minimum, existing, interleave_freq):
        candidates = []

        # Collect all genres present in library
        tv_genres  = self._genres_from(all_shows)
        mov_genres = self._genres_from(all_movies)
        all_genres = sorted(tv_genres | mov_genres)

        for genre in all_genres:
            genre_shows  = [s for s in all_shows
                            if genre in [g for g in s.get("genre", [])]]
            genre_movies = [m for m in all_movies
                            if genre in [g for g in m.get("genre", [])]]

            # TV channel
            if content_type in (_CT_TV, _CT_BOTH) and genre_shows:
                name  = self._s(_S_TV_NAME).format(genre)
                count = self._episode_count(genre_shows)
                candidates.append(self._make_tv_candidate(
                    name, genre_shows, count, minimum, existing))

            # Movie channel
            if content_type in (_CT_MOVIES, _CT_BOTH) and genre_movies:
                name  = self._s(_S_MOVIE_NAME).format(genre)
                count = len(genre_movies)
                candidates.append(self._make_movie_candidate(
                    name, genre_movies, count, minimum, existing))

            # Interleaved channel
            if (interleave_freq and genre_shows and genre_movies
                    and content_type == _CT_BOTH):
                name = self._s(_S_INTERLEAVE_GENRE).format(genre)
                candidates.append(self._make_interleaved_candidate(
                    name, genre_shows, genre_movies,
                    interleave_freq, minimum, existing))

        return candidates

    # -- Decade grouping -----------------------------------------------

    def _candidates_by_decade(self, content_type, all_shows, all_movies,
                              minimum, existing, interleave_freq):
        candidates = []

        tv_decades  = self._decades_from(all_shows)
        mov_decades = self._decades_from(all_movies)
        all_decades = sorted(tv_decades | mov_decades)

        for decade in all_decades:
            decade_shows  = [s for s in all_shows
                             if self._year_to_decade(
                                 s.get("year", 0)) == decade]
            decade_movies = [m for m in all_movies
                             if self._year_to_decade(
                                 m.get("year", 0)) == decade]

            if content_type in (_CT_TV, _CT_BOTH) and decade_shows:
                name  = self._s(_S_DECADE_TV).format(decade)
                count = self._episode_count(decade_shows)
                candidates.append(self._make_tv_candidate(
                    name, decade_shows, count, minimum, existing))

            if content_type in (_CT_MOVIES, _CT_BOTH) and decade_movies:
                name  = self._s(_S_DECADE_MOVIE).format(decade)
                count = len(decade_movies)
                candidates.append(self._make_movie_candidate(
                    name, decade_movies, count, minimum, existing))

            if (interleave_freq and decade_shows and decade_movies
                    and content_type == _CT_BOTH):
                name = self._s(_S_INTERLEAVE_DECADE).format(decade)
                candidates.append(self._make_interleaved_candidate(
                    name, decade_shows, decade_movies,
                    interleave_freq, minimum, existing))

        return candidates

    # -- Genre + Decade grouping ---------------------------------------

    def _candidates_by_genre_decade(self, content_type, all_shows,
                                    all_movies, minimum, existing,
                                    interleave_freq):
        candidates = []

        tv_genres  = self._genres_from(all_shows)
        mov_genres = self._genres_from(all_movies)
        all_genres = sorted(tv_genres | mov_genres)

        tv_decades  = self._decades_from(all_shows)
        mov_decades = self._decades_from(all_movies)
        all_decades = sorted(tv_decades | mov_decades)

        for genre in all_genres:
            for decade in all_decades:
                gd_shows = [
                    s for s in all_shows
                    if (genre in s.get("genre", [])
                        and self._year_to_decade(s.get("year", 0)) == decade)]
                gd_movies = [
                    m for m in all_movies
                    if (genre in m.get("genre", [])
                        and self._year_to_decade(m.get("year", 0)) == decade)]

                if content_type in (_CT_TV, _CT_BOTH) and gd_shows:
                    name  = self._s(_S_GENRE_DECADE_TV).format(decade, genre)
                    count = self._episode_count(gd_shows)
                    candidates.append(self._make_tv_candidate(
                        name, gd_shows, count, minimum, existing))

                if content_type in (_CT_MOVIES, _CT_BOTH) and gd_movies:
                    name  = self._s(_S_GENRE_DECADE_MOV).format(
                        decade, genre)
                    count = len(gd_movies)
                    candidates.append(self._make_movie_candidate(
                        name, gd_movies, count, minimum, existing))

                if (interleave_freq and gd_shows and gd_movies
                        and content_type == _CT_BOTH):
                    name = self._s(_S_INTERLEAVE_GD).format(decade, genre)
                    candidates.append(self._make_interleaved_candidate(
                        name, gd_shows, gd_movies,
                        interleave_freq, minimum, existing))

        return candidates

    # -- Studio / Network grouping -------------------------------------

    def _candidates_by_studio(self, content_type, all_shows, all_movies,
                              minimum, existing):
        """
        TV: grouped by studio/network field.
        Movies: grouped by studio field.
        No interleave for this grouping (TV network ≠ movie studio).
        """
        candidates = []

        if content_type in (_CT_TV, _CT_BOTH):
            tv_studios = self._studios_from(all_shows)
            for studio in sorted(tv_studios):
                studio_shows = [
                    s for s in all_shows
                    if studio in s.get("studio", [])]
                if not studio_shows:
                    continue
                name  = studio
                count = self._episode_count(studio_shows)
                candidates.append(self._make_tv_candidate(
                    name, studio_shows, count, minimum, existing))

        if content_type in (_CT_MOVIES, _CT_BOTH):
            mov_studios = self._studios_from(all_movies)
            for studio in sorted(mov_studios):
                studio_movies = [
                    m for m in all_movies
                    if studio in m.get("studio", [])]
                if not studio_movies:
                    continue
                name  = self._s(_S_MOVIE_NAME).format(studio)
                count = len(studio_movies)
                candidates.append(self._make_movie_candidate(
                    name, studio_movies, count, minimum, existing))

        return candidates

    # ------------------------------------------------------------------
    # Candidate factories
    # ------------------------------------------------------------------

    def _make_tv_candidate(self, name, shows, episode_count,
                           minimum, existing):
        above = episode_count >= minimum
        display = self._s(_S_FMT_TV).format(
            name, len(shows), episode_count)
        return {
            "name":         name,
            "display":      display,
            "item_count":   episode_count,
            "above_min":    above,
            "exists":       name in existing,
            "channel_type": _CT_TV,
            "shows":        shows,
            "movies":       [],
            "interleave":   None,
        }

    def _make_movie_candidate(self, name, movies, count, minimum, existing):
        above = count >= minimum
        display = self._s(_S_FMT_MOVIES).format(name, count)
        return {
            "name":         name,
            "display":      display,
            "item_count":   count,
            "above_min":    above,
            "exists":       name in existing,
            "channel_type": _CT_MOVIES,
            "shows":        [],
            "movies":       movies,
            "interleave":   None,
        }

    def _make_interleaved_candidate(self, name, shows, movies,
                                    freq, minimum, existing):
        """
        Interleaved channel: Movie channel with TV channel woven in.
        The TV channel must already exist (or be in this batch) —
        interleave is configured after creation via channel ID.
        We store the tv_channel_name so _build_definition can look up
        the ID at creation time.
        """
        count = len(shows) + len(movies)
        above = count >= minimum
        display = self._s(_S_FMT_INTERLEAVED).format(
            name, len(shows), len(movies))
        return {
            "name":            name,
            "display":         display,
            "item_count":      count,
            "above_min":       above,
            "exists":          name in existing,
            "channel_type":    _CT_BOTH,
            "shows":           shows,
            "movies":          movies,
            "interleave_freq": freq,
            "interleave":      True,   # resolved to ID at creation time
        }

    # ------------------------------------------------------------------
    # Definition builder — called at creation time
    # ------------------------------------------------------------------

    def _build_definition(self, candidate, queue_size, tv_random, recycle,
                          surprise_start=False):
        """
        Assemble the definition dict for channel_manager.create_channel().
        surprise_start=True randomises the starting episode for each TV show.
        """
        ch_type = candidate["channel_type"]

        if ch_type == _CT_TV:
            shows = [
                {"tvshowid": s["tvshowid"], "title": s["title"]}
                for s in candidate["shows"]
            ]
            random.shuffle(shows)   # randomise show rotation order
            starting_points = {}
            if surprise_start:
                starting_points = self._surprise_starting_points(
                    candidate["shows"])
            return {
                "name":           candidate["name"],
                "channel_type":   "tv",
                "shows":          shows,
                "randomize":      tv_random,
                "recycle":        recycle,
                "queue_size":     queue_size,
                "visible":        True,
                "starting_points": starting_points,
            }

        elif ch_type == _CT_MOVIES and not candidate.get("interleave"):
            movies = [{"movieid": m["movieid"], "title": m["title"]}
                      for m in candidate["movies"]]
            return {
                "name":         candidate["name"],
                "channel_type": "movies",
                "movies":       movies,
                "randomize":    True,   # Movies always random
                "recycle":      recycle,
                "queue_size":   queue_size,
                "visible":      True,
            }

        else:
            # Interleaved TV + Movies channel.
            # Primary channel = TV (visible to user).
            # Interleave source = Movies (invisible companion channel).
            #
            # We create the invisible movies companion first so its ID
            # is available when we wire up the TV channel's interleave.
            # The companion is marked visible=False so it never appears
            # in the user's channel list.
            movies = [{"movieid": m["movieid"], "title": m["title"]}
                      for m in candidate["movies"]]
            companion_name = "__auto__{}".format(candidate["name"])
            companion_def = {
                "name":         companion_name,
                "channel_type": "movies",
                "movies":       movies,
                "randomize":    True,
                "recycle":      recycle,
                "queue_size":   queue_size,
                "visible":      False,
            }
            # Create (or find existing) invisible companion
            existing_names = {
                ch["name"]: ch["id"]
                for ch in self.manager.get_all_channels()}
            if companion_name in existing_names:
                companion_id = existing_names[companion_name]
            else:
                companion_ch = self.manager.create_channel(companion_def)
                companion_id = companion_ch["id"]
                log("[AutoChannelUI] created invisible companion '{}'".format(
                    companion_name))

            shows = [
                {"tvshowid": s["tvshowid"], "title": s["title"]}
                for s in candidate["shows"]
            ]
            random.shuffle(shows)   # randomise show rotation order
            starting_points = {}
            if surprise_start:
                starting_points = self._surprise_starting_points(
                    candidate["shows"])
            interleave_cfg = [{
                "channel_id": companion_id,
                "frequency":  candidate["interleave_freq"],
                "jitter":     0,
                "count_per":  1,
                "silent":     False,
            }]
            return {
                "name":            candidate["name"],
                "channel_type":    "tv",
                "shows":           shows,
                "randomize":       tv_random,
                "recycle":         recycle,
                "queue_size":      queue_size,
                "visible":         True,
                "interleave":      interleave_cfg,
                "starting_points": starting_points,
            }

    # ------------------------------------------------------------------
    # Library helpers
    # ------------------------------------------------------------------

    def _surprise_starting_points(self, shows):
        """
        Return a starting_points dict with a random episode for each show.
        Only used when the user selects "Surprise Me!" at channel creation.
        Movies are never included — this is TV-only.
        """
        starting_points = {}
        for show in shows:
            sid = show["tvshowid"]
            try:
                eps = self.manager.get_available_episodes(show)
                if eps:
                    ep = random.choice(eps)
                    starting_points[sid] = {
                        "episodeid": ep["episodeid"],
                        "season":    ep["season"],
                        "episode":   ep["episode"],
                        "title":     ep.get("title", ""),
                    }
            except Exception:
                pass   # leave this show at S01E01
        return starting_points

    def _library_ready(self):
        """Return True if the local library cache has been built."""
        try:
            cached = self.manager.library.load_local_cache()
            return bool(cached and (cached.get("tvshows")
                                    or cached.get("movies")))
        except Exception:
            return False

    def _genres_from(self, items):
        """Return set of all genres present in items list."""
        genres = set()
        for item in items:
            for g in item.get("genre", []):
                if g and g.strip():
                    genres.add(g.strip())
        return genres

    def _decades_from(self, items):
        """Return set of all decades (as int, e.g. 1990) present in items."""
        decades = set()
        for item in items:
            decade = self._year_to_decade(item.get("year", 0))
            if decade:
                decades.add(decade)
        return decades

    def _studios_from(self, items):
        """Return set of all studios present in items."""
        studios = set()
        for item in items:
            for s in item.get("studio", []):
                if s and s.strip():
                    studios.add(s.strip())
        return studios

    @staticmethod
    def _year_to_decade(year):
        """Convert a year int to its decade int (e.g. 1994 -> 1990)."""
        if not year or year < 1900:
            return None
        return (year // 10) * 10

    def _episode_count(self, shows):
        """
        Return the total episode count for a list of shows.
        Uses the nbepisodes field from the local library cache — no JSONRPC
        calls needed.  Falls back to a full episode fetch only if the cached
        count is absent (e.g. cache was built before nbepisodes was added).
        """
        total = 0
        for show in shows:
            cached = show.get("nbepisodes")
            if cached is not None:
                total += cached
            else:
                try:
                    eps = self.manager.library.get_episodes_for_show(
                        show["tvshowid"])
                    total += len(eps)
                except Exception:
                    total += 1   # safe fallback — don't abort on one failure
        return total

    def _get_defaults(self):
        """Read global default settings for channel creation."""
        try:
            queue_size = int(self.addon.getSetting(
                "default_queue_size") or str(_DEFAULT_QUEUE_SZ))
        except (ValueError, TypeError):
            queue_size = _DEFAULT_QUEUE_SZ

        try:
            tv_random = self.addon.getSetting("default_randomize") == "true"
        except Exception:
            tv_random = False

        # Channels always recycle (no setting exists for it).
        return queue_size, tv_random, True
