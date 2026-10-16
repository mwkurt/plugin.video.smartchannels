# plugin.video.smartchannels
# resources/lib/ui/dialogs.py
#
# OWNS:   Shared dialog helpers used by all channel wizards.
#         Filter builder, episode exclusions, movie exclusions,
#         list order picker, audio song exclusions, recycle/queue/visibility.
#
# NEVER:  Queue building, state reads/writes, executeJSONRPC calls,
#         private method calls on other classes.
#
# All user-visible strings via addon.getLocalizedString().
# Ported from 2.x ui/channels.py private methods.
#
# spec §6, §3 module map (ui/dialogs.py — shared dialog helpers)
# Version: 3.0.0 Phase 5

from __future__ import annotations

import re
import random

import xbmcgui

from resources.lib.utils.logger import log
from resources.lib.channels.folder import is_local_drive_path


# ---------------------------------------------------------------------------
# Folder picker
# ---------------------------------------------------------------------------

def browse_folder_path(addon, default_path: str = "") -> str:
    """Let the user pick a folder; return the path, or "" if cancelled.

    Channels and their folder paths live in shared storage, so every
    device reads the same path.  A drive-letter path (D:\\...) exists only
    on the device that has that drive.  When one is chosen the user is told
    so and may keep it (fine for a channel played on that device alone) or
    choose another folder.
    """
    d = xbmcgui.Dialog()
    while True:
        path = d.browseSingle(
            0, addon.getLocalizedString(32532), "files",
            defaultt=default_path)
        if not path:
            return ""
        if not is_local_drive_path(path):
            return path
        keep = d.yesno(
            addon.getLocalizedString(32000),
            addon.getLocalizedString(32938).format(path),
            nolabel=addon.getLocalizedString(32940),    # Choose Another
            yeslabel=addon.getLocalizedString(32939))   # Keep This Path
        if keep:
            return path
        default_path = path


# ---------------------------------------------------------------------------
# List order picker
# ---------------------------------------------------------------------------

def pick_list_order(addon, d, items: list, title_str: str,
                    pos_str: str) -> list:
    """Keep / Shuffle / Manual order picker for a list of strings.
    Returns the reordered list. Never returns None.
    spec §6.1 step 5
    """
    if len(items) <= 1:
        return items

    order_choice = d.select(
        title_str,
        [addon.getLocalizedString(32241),
         addon.getLocalizedString(32242),
         addon.getLocalizedString(32243)])

    if order_choice < 0 or order_choice == 0:
        return items

    if order_choice == 1:
        while True:
            random.shuffle(items)
            preview = "\n".join(
                "{}. {}".format(i + 1, s) for i, s in enumerate(items))
            d.ok(title_str, preview[:300])
            shuf = d.select(
                title_str,
                [addon.getLocalizedString(32245),
                 addon.getLocalizedString(32244),
                 addon.getLocalizedString(32491)])
            if shuf <= 0:
                break
            if shuf == 1:
                continue
            break
        return items

    # Manual
    while True:
        remaining = list(items)
        ordered   = []
        for pos in range(len(items)):
            pick = d.select(pos_str.format(pos + 1), list(remaining))
            if pick < 0:
                ordered = list(items)
                break
            ordered.append(remaining[pick])
            remaining.pop(pick)
        summary = "\n".join(
            "{}. {}".format(i + 1, s) for i, s in enumerate(ordered))
        d.ok(addon.getLocalizedString(32247), summary)
        confirm = d.select(
            addon.getLocalizedString(32247),
            [addon.getLocalizedString(32245),
             addon.getLocalizedString(32248)])
        if confirm == 0:
            items = ordered
            break
        elif confirm == 1:
            continue
        else:
            break
    return items


# ---------------------------------------------------------------------------
# Episode filter builder
# ---------------------------------------------------------------------------

def build_episode_filters(addon, manager, show_title: str,
                           existing_filters: list) -> list:
    """Per-show episode filter builder. Returns updated filter list.
    spec §6.1 step 8
    """
    d        = xbmcgui.Dialog()
    filters  = list(existing_filters) if existing_filters else []
    modified = False

    season_list = []
    try:
        for s in manager.library.get_all_tvshows():
            if s.get("title", "").lower() == show_title.lower():
                eps         = manager.library.get_episodes_for_show(s["tvshowid"])
                season_list = sorted(
                    set(e["season"] for e in eps if e.get("season") is not None))
                break
    except Exception:
        pass

    while True:
        if filters:
            summary = " | ".join(describe_filters(addon, filters))
        else:
            summary = addon.getLocalizedString(32580)

        title   = "{} — {}".format(
            addon.getLocalizedString(32572).format(show_title), summary)
        options = [
            addon.getLocalizedString(32579),
            addon.getLocalizedString(32575),
            addon.getLocalizedString(32576),
            addon.getLocalizedString(32489),
            addon.getLocalizedString(32490),
            addon.getLocalizedString(32491),
        ]
        action = d.select(title, options)

        if action < 0 or action == 5:
            break
        elif action == 0:
            wc = d.select(
                addon.getLocalizedString(32579),
                [addon.getLocalizedString(32573),
                 addon.getLocalizedString(32574)])
            if wc == 0:
                filters = [f for f in filters if f.get("type") != "watched"]
                filters.append({"type": "watched", "value": "watched",
                                 "operator": "and", "comparison": "equals"})
                modified = True
            elif wc == 1:
                filters = [f for f in filters if f.get("type") != "watched"]
                filters.append({"type": "watched", "value": "unwatched",
                                 "operator": "and", "comparison": "equals"})
                modified = True
        elif action == 1:
            if not season_list:
                d.ok(addon.getLocalizedString(32000),
                     addon.getLocalizedString(32584))
                continue
            comp_labels = ["=", ">=", "<=", ">", "<"]
            comp_values = ["equals", "greaterthanequal", "lessthanequal",
                           "greaterthan", "lessthan"]
            cc = d.select(addon.getLocalizedString(32575), comp_labels)
            if cc < 0:
                continue
            sc = d.select(
                addon.getLocalizedString(32507),
                [str(s) for s in season_list])
            if sc < 0:
                continue
            filters.append({"type": "season", "value": season_list[sc],
                             "operator": "and",
                             "comparison": comp_values[cc]})
            modified = True
        elif action == 2:
            comp_labels = ["after (>)", "before (<)", "on (=)"]
            comp_values = ["greaterthan", "lessthan", "equals"]
            cc = d.select(addon.getLocalizedString(32576), comp_labels)
            if cc < 0:
                continue
            date_str = d.input(
                addon.getLocalizedString(32577),
                defaultt="2000-01-01",
                type=xbmcgui.INPUT_ALPHANUM)
            if not date_str:
                continue
            date_str = date_str.strip()
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
                d.ok(addon.getLocalizedString(32000),
                     addon.getLocalizedString(32583))
                continue
            filters.append({"type": "firstaired", "value": date_str,
                             "operator": "and",
                             "comparison": comp_values[cc]})
            modified = True
        elif action == 3:
            if filters:
                filters.pop()
                modified = True
        elif action == 4:
            filters  = []
            modified = True

    return filters if modified else existing_filters


# ---------------------------------------------------------------------------
# Episode exclusion builder
# ---------------------------------------------------------------------------

def build_episode_exclusions(addon, manager, show_entry: dict,
                              show_title: str,
                              existing_excluded: list) -> list:
    """Per-show episode exclusion picker. Returns list of episodeids.
    spec §6.1 step 9
    """
    d        = xbmcgui.Dialog()
    excluded = set(existing_excluded) if existing_excluded else set()

    eligible = manager.get_filtered_episodes(show_entry)
    if not eligible:
        d.ok(addon.getLocalizedString(32000),
             addon.getLocalizedString(32584))
        return list(excluded)

    seasons = sorted(set(e["season"] for e in eligible if e.get("season") is not None))

    while True:
        summary = (addon.getLocalizedString(32590).format(len(excluded))
                   if excluded else addon.getLocalizedString(32591))
        title   = addon.getLocalizedString(32589).format(show_title, summary)

        choice = d.select(
            title,
            [str(s) for s in seasons] + [addon.getLocalizedString(32491)])
        if choice < 0 or choice == len(seasons):
            break

        chosen_season = seasons[choice]
        season_eps    = sorted(
            [e for e in eligible if e["season"] == chosen_season],
            key=lambda e: e["episode"])

        action = d.select(
            addon.getLocalizedString(32600).format(chosen_season),
            [addon.getLocalizedString(32597).format(chosen_season),
             addon.getLocalizedString(32598)])
        if action < 0:
            continue

        if action == 0:
            season_ids = {e["episodeid"] for e in season_eps}
            excluded  -= season_ids
            excluded  |= season_ids
            continue

        ep_labels = [
            addon.getLocalizedString(32693).format(
                e["season"], e["episode"], e["title"])
            for e in season_eps
        ]
        preselect = [i for i, e in enumerate(season_eps)
                     if e["episodeid"] in excluded]
        picked = d.multiselect(
            addon.getLocalizedString(32592).format(show_title, chosen_season),
            ep_labels,
            preselect=preselect)
        if picked is None:
            continue

        season_ids = {e["episodeid"] for e in season_eps}
        excluded  -= season_ids
        for i in picked:
            excluded.add(season_eps[i]["episodeid"])

    return list(excluded)


# ---------------------------------------------------------------------------
# Movie exclusion builder
# ---------------------------------------------------------------------------

def build_movie_exclusions(addon, movies: list,
                            existing_excluded: list) -> list:
    """Movie exclusion picker. Returns list of movieids.
    spec §6.3 step 5
    """
    d        = xbmcgui.Dialog()
    excluded = set(existing_excluded) if existing_excluded else set()

    if not movies:
        return list(excluded)

    movie_labels = [m.get("title", str(m.get("movieid", "?")))
                    for m in movies]
    preselect    = [i for i, m in enumerate(movies)
                    if m.get("movieid") in excluded]

    picked = d.multiselect(
        addon.getLocalizedString(32595),
        movie_labels,
        preselect=preselect)
    if picked is None:
        return list(excluded)

    return [movies[i]["movieid"] for i in picked]


# ---------------------------------------------------------------------------
# General filter builder
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Filter rule text
# ---------------------------------------------------------------------------

# Comparisons shown as symbols (numbers, dates) ...
_COMPARISON_SYMBOLS = {
    "equals": "=", "notequals": "!=", "greaterthan": ">",
    "greaterthanequal": ">=", "lessthan": "<", "lessthanequal": "<=",
    "after": ">", "before": "<",
}
# ... and as words (text fields).
_TEXT_FILTER_TYPES = ("genre", "studio", "mpaa", "artist", "albumartist",
                      "album")
_TEXT_COMPARISON_STRINGS = {
    "equals": 32496, "notequals": 32497,
    "contains": 32519, "doesnotcontain": 32520,
}
_FILTER_TYPE_STRINGS = {"genre": 32492, "mpaa": 32494, "studio": 32495,
                        "year": 32493}


def describe_filter_rule(addon, rule: dict) -> str:
    """One filter rule as text, e.g. "Genre is not Comedy", "Year >= 2000"."""
    ftype = rule.get("type", "")
    comp  = rule.get("comparison", "")
    label = (addon.getLocalizedString(_FILTER_TYPE_STRINGS[ftype])
             if ftype in _FILTER_TYPE_STRINGS else ftype.capitalize())
    if ftype in _TEXT_FILTER_TYPES:
        # Rules saved before 3.1.99 have no match type: they were "contains".
        comparison = addon.getLocalizedString(
            _TEXT_COMPARISON_STRINGS.get(comp, 32519))
    else:
        comparison = _COMPARISON_SYMBOLS.get(comp, "=")
    return "{} {} {}".format(label, comparison, rule.get("value", ""))


def describe_filters(addon, filters: list) -> list:
    """Every rule as a line of text; rules after the first start with the
    AND / OR that joins them to the rule before."""
    lines = []
    for i, rule in enumerate(filters):
        prefix = "" if i == 0 else "{} ".format(
            str(rule.get("operator", "and")).upper())
        lines.append(prefix + describe_filter_rule(addon, rule))
    return lines


def _ask_text_comparison(addon, d):
    """Ask how a text rule (genre, studio, MPAA) matches.  Returns the
    comparison token, or None if the user backed out."""
    choice = d.select(
        addon.getLocalizedString(32488),
        [addon.getLocalizedString(32496),    # is
         addon.getLocalizedString(32497),    # is not
         addon.getLocalizedString(32519),    # contains
         addon.getLocalizedString(32520)])   # does not contain
    if choice < 0:
        return None
    return ("equals", "notequals", "contains", "doesnotcontain")[choice]


def _ask_number_comparison(addon, d, title_id: int):
    """Ask how a number rule (year, rating) compares.  Returns the
    comparison token, or None if the user backed out."""
    tokens = ("equals", "notequals", "greaterthan", "greaterthanequal",
              "lessthan", "lessthanequal")
    choice = d.select(addon.getLocalizedString(title_id),
                      [_COMPARISON_SYMBOLS[t] for t in tokens])
    if choice < 0:
        return None
    return tokens[choice]


def build_filters(addon, manager, existing_filters: list,
                  media_type: str = "tv") -> list:
    """Filter rule builder for TV, movies, and audio.
    spec §6.1 step 8, §6.3 step 3
    """
    d       = xbmcgui.Dialog()
    filters = list(existing_filters) if existing_filters else []

    while True:
        if media_type == "tv":
            type_labels = [
                addon.getLocalizedString(32492),
                addon.getLocalizedString(32495),
                addon.getLocalizedString(32493),
                addon.getLocalizedString(32513),
                addon.getLocalizedString(32489),
                addon.getLocalizedString(32490),
                addon.getLocalizedString(32491),
            ]
            type_values = ["genre", "studio", "year", "rating",
                           "__remove__", "__clear__", None]
        elif media_type == "movies":
            type_labels = [
                addon.getLocalizedString(32492),
                addon.getLocalizedString(32494),
                addon.getLocalizedString(32495),
                addon.getLocalizedString(32493),
                addon.getLocalizedString(32513),
                addon.getLocalizedString(32489),
                addon.getLocalizedString(32490),
                addon.getLocalizedString(32491),
            ]
            type_values = ["genre", "mpaa", "studio", "year", "rating",
                           "__remove__", "__clear__", None]
        else:  # audio
            type_labels = [
                addon.getLocalizedString(32492),
                addon.getLocalizedString(32813),
                addon.getLocalizedString(32814),
                addon.getLocalizedString(32815),
                addon.getLocalizedString(32493),
                addon.getLocalizedString(32513),
                addon.getLocalizedString(32816),
                addon.getLocalizedString(32489),
                addon.getLocalizedString(32490),
                addon.getLocalizedString(32491),
            ]
            type_values = ["genre", "artist", "albumartist", "album",
                           "year", "rating", "playcount",
                           "__remove__", "__clear__", None]

        if filters:
            summary = " | ".join(describe_filters(addon, filters))
        else:
            summary = addon.getLocalizedString(32580)

        choice = d.select(
            "{} — {}".format(addon.getLocalizedString(32487), summary),
            type_labels)

        if choice < 0:
            break
        ftype = type_values[choice]
        if ftype is None:
            break
        if ftype == "__remove__":
            if filters:
                filters.pop()
            continue
        if ftype == "__clear__":
            filters = []
            continue

        operator = "and"
        if filters:
            op_choice = d.select(
                addon.getLocalizedString(32499),
                [addon.getLocalizedString(32500),
                 addon.getLocalizedString(32501)])
            if op_choice < 0:
                continue
            operator = "and" if op_choice == 0 else "or"

        rule = _add_filter_rule(addon, manager, d, ftype, operator, media_type)
        if rule:
            filters.append(rule)

    return filters


def _add_filter_rule(addon, manager, d, ftype: str, operator: str,
                     media_type: str) -> dict | None:
    """Build one filter rule dict."""
    if ftype == "genre":
        try:
            if media_type == "tv":
                genres = manager.library.get_all_genres("tvshow")
            elif media_type == "movies":
                genres = manager.library.get_all_genres("movie")
            else:
                genres = manager.library.get_audio_genres()
        except Exception:
            genres = []
        if not genres:
            d.ok(addon.getLocalizedString(32000),
                 addon.getLocalizedString(32502))
            return None
        comparison = _ask_text_comparison(addon, d)
        if comparison is None:
            return None
        choice = d.select(addon.getLocalizedString(32455), genres)
        if choice < 0:
            return None
        return {"type": "genre", "value": genres[choice],
                "operator": operator, "comparison": comparison}

    elif ftype in ("artist", "albumartist", "album"):
        text = d.input(
            addon.getLocalizedString(32498).format(ftype.capitalize()),
            type=xbmcgui.INPUT_ALPHANUM)
        if not text:
            return None
        return {"type": ftype, "value": text,
                "operator": operator, "comparison": "contains"}

    elif ftype == "playcount":
        pc_choice = d.select(
            addon.getLocalizedString(32816),
            [addon.getLocalizedString(32820),
             addon.getLocalizedString(32821)])
        if pc_choice < 0:
            return None
        if pc_choice == 0:
            return {"type": "playcount", "value": "0",
                    "operator": operator, "comparison": "equals"}
        return {"type": "playcount", "value": "0",
                "operator": operator, "comparison": "greaterthan"}

    elif ftype == "year":
        comparison = _ask_number_comparison(addon, d, 32507)
        if comparison is None:
            return None
        year_str = d.input(addon.getLocalizedString(32511), "",
                           type=xbmcgui.INPUT_NUMERIC)
        if not year_str:
            return None
        try:
            year = int(year_str)
            if year < 1888 or year > 2100:
                raise ValueError
        except ValueError:
            d.ok(addon.getLocalizedString(32000),
                 addon.getLocalizedString(32512))
            return None
        return {"type": "year", "value": str(year),
                "operator": operator, "comparison": comparison}

    elif ftype == "mpaa":
        common = ["G", "PG", "PG-13", "R", "NC-17",
                  "NR", "TV-G", "TV-PG", "TV-14", "TV-MA"]
        try:
            lib_ratings = manager.library.get_mpaa_ratings("movie")
        except Exception:
            lib_ratings = []
        all_ratings = sorted(set(common + lib_ratings))
        if not all_ratings:
            d.ok(addon.getLocalizedString(32000),
                 addon.getLocalizedString(32503))
            return None
        comparison = _ask_text_comparison(addon, d)
        if comparison is None:
            return None
        choice = d.select(addon.getLocalizedString(32504), all_ratings)
        if choice < 0:
            return None
        return {"type": "mpaa", "value": all_ratings[choice],
                "operator": operator, "comparison": comparison}

    elif ftype == "studio":
        try:
            studios = manager.library.get_studios(
                "movie" if media_type == "movies" else "tv")
        except Exception:
            studios = []
        if not studios:
            d.ok(addon.getLocalizedString(32000),
                 addon.getLocalizedString(32505))
            return None
        comparison = _ask_text_comparison(addon, d)
        if comparison is None:
            return None
        choice = d.select(addon.getLocalizedString(32506), studios)
        if choice < 0:
            return None
        return {"type": "studio", "value": studios[choice],
                "operator": operator, "comparison": comparison}

    elif ftype == "rating":
        comparison = _ask_number_comparison(addon, d, 32513)
        if comparison is None:
            return None
        rating_str = d.input(addon.getLocalizedString(32517), "7",
                             type=xbmcgui.INPUT_NUMERIC)
        if not rating_str:
            return None
        try:
            rating = float(rating_str)
            if rating < 0 or rating > 10:
                raise ValueError
        except ValueError:
            d.ok(addon.getLocalizedString(32000),
                 addon.getLocalizedString(32518))
            return None
        return {"type": "rating", "value": str(rating),
                "operator": operator,
                "comparison": comparison}

    return None


# ---------------------------------------------------------------------------
# Audio song exclusion builder
# ---------------------------------------------------------------------------

def build_audio_song_exclusions(addon, manager, artist_names: list,
                                 included_albums: dict, audio_filters: list,
                                 existing_excluded: list) -> list:
    """Song exclusion picker for audio channels. Returns list of songids.
    spec §6.5
    """
    d        = xbmcgui.Dialog()
    excluded = set(existing_excluded) if existing_excluded else set()

    try:
        songs = manager.library.get_songs_with_filters(audio_filters)
    except Exception as e:
        log("[dialogs] build_audio_song_exclusions: {}".format(e))
        return list(excluded)

    pool = {}
    for s in songs:
        s_artists = s.get("artist", [])
        if isinstance(s_artists, str):
            s_artists = [s_artists]
        for artist in artist_names:
            if any(artist.lower() in sa.lower() for sa in s_artists):
                album   = s.get("album", "")
                allowed = included_albums.get(artist, [])
                if allowed and album not in allowed:
                    continue
                pool.setdefault(artist, {}).setdefault(album, []).append(s)
                break

    def _count(songs_):
        """How many of songs_ are currently excluded."""
        return sum(1 for s in songs_ if s.get("songid", -1) in excluded)

    def _summary(n):
        return (addon.getLocalizedString(32830).format(n) if n
                else addon.getLocalizedString(32831))

    while True:
        artist_labels = [
            "{} \u2014 {}".format(a, _summary(_count(
                [s for alb in pool.get(a, {}).values() for s in alb])))
            for a in artist_names]
        artist_labels.append(addon.getLocalizedString(32491))
        pick_a = d.select(addon.getLocalizedString(32827), artist_labels)
        if pick_a < 0 or pick_a == len(artist_names):
            break

        chosen_artist = artist_names[pick_a]
        albums_dict   = pool.get(chosen_artist, {})
        if not albums_dict:
            continue

        album_list = sorted(albums_dict.keys())
        while True:
            album_labels = [
                "{} \u2014 {}".format(
                    alb, _summary(_count(albums_dict[alb])))
                for alb in album_list]
            album_labels.append(addon.getLocalizedString(32491))
            pick_b = d.select(
                addon.getLocalizedString(32826).format(chosen_artist),
                album_labels)
            if pick_b < 0 or pick_b == len(album_list):
                break

            chosen_album = album_list[pick_b]
            album_songs  = sorted(
                albums_dict.get(chosen_album, []),
                key=lambda s: (int(s.get("disc", 0) or 0),
                               int(s.get("track", 0) or 0)))
            if not album_songs:
                continue

            # One multiselect for the whole album: ticked songs are the
            # excluded ones.  Cancelling leaves the album unchanged.
            song_labels = []
            preselect   = []
            for i, s in enumerate(album_songs):
                track = int(s.get("track", 0) or 0)
                title = s.get("title", "")
                song_labels.append("{:02d}. {}".format(track, title)
                                   if track else title)
                if s.get("songid", -1) in excluded:
                    preselect.append(i)
            picked = d.multiselect(
                addon.getLocalizedString(32829).format(chosen_album),
                song_labels, preselect=preselect)
            if picked is None:
                continue
            for s in album_songs:
                excluded.discard(s.get("songid", -1))
            for i in picked:
                sid = album_songs[i].get("songid", -1)
                if sid != -1:
                    excluded.add(sid)

    return list(excluded)


# ---------------------------------------------------------------------------
# Shared wizard step helpers
# ---------------------------------------------------------------------------


def ask_starting_episode(addon, manager, show: dict,
                         channel_id: str = "",
                         default_label_id: int = 32599) -> dict | None:
    """Ask for one show's starting episode (season, then episode).

    Returns a starting_points entry {episodeid, season, episode, title}, or
    None when the user keeps the default/current position or cancels.
    channel_id is the channel being edited (empty when creating); when the
    show already has a queued episode its season/episode are pre-selected
    and shown on the "keep" button.  default_label_id is the "keep" button
    label used when the show has no queued episode.
    Shared by the TV and Serial wizards.
    """
    d          = xbmcgui.Dialog()
    sid        = show["tvshowid"]
    show_title = show["title"]

    nolabel = addon.getLocalizedString(default_label_id)
    cur_ep  = None
    if channel_id:
        cur_ep = manager.get_show_next_queued_episode(channel_id, sid)
        if cur_ep:
            nolabel = addon.getLocalizedString(32477).format(
                cur_ep.get("season", 1), cur_ep.get("episode", 1))

    do_set = d.yesno(
        show_title,
        addon.getLocalizedString(32479).format(show_title),
        nolabel=nolabel,
        yeslabel=addon.getLocalizedString(32478))
    if not do_set:
        return None

    episodes = manager.get_available_episodes(show)
    if not episodes:
        d.ok(addon.getLocalizedString(32000),
             addon.getLocalizedString(32483).format(show_title))
        return None

    seasons       = sorted(set(e["season"] for e in episodes))
    season_labels = [addon.getLocalizedString(32480).format(s)
                     for s in seasons]
    default_s = 0
    if cur_ep:
        cs = cur_ep.get("season", 1)
        if cs in seasons:
            default_s = seasons.index(cs)

    cur_s_label = ""
    if channel_id and default_s > 0:
        cur_s_label = addon.getLocalizedString(32484).format(
            seasons[default_s])
    season_choice = d.select(
        addon.getLocalizedString(32481).format(show_title, cur_s_label),
        season_labels)
    if season_choice < 0:
        return None

    chosen_season = seasons[season_choice]
    season_eps    = sorted(
        [e for e in episodes if e["season"] == chosen_season],
        key=lambda e: e["episode"])
    ep_labels = [
        addon.getLocalizedString(32693).format(
            e["season"], e["episode"], e["title"])
        for e in season_eps
    ]
    default_e = 0
    if cur_ep:
        cur_nid = cur_ep.get("episodeid")
        for i, ep in enumerate(season_eps):
            if ep["episodeid"] == cur_nid:
                default_e = i
                break

    cur_e_label = ""
    if channel_id and 0 < default_e < len(ep_labels):
        cur_e_label = addon.getLocalizedString(32484).format(
            ep_labels[default_e])
    ep_choice = d.select(
        addon.getLocalizedString(32482).format(show_title, cur_e_label[:40]),
        ep_labels)
    if ep_choice < 0:
        return None

    chosen = season_eps[ep_choice]
    return {
        "episodeid": chosen["episodeid"],
        "season":    chosen["season"],
        "episode":   chosen["episode"],
        "title":     chosen["title"],
    }


def ask_queue_size(addon, existing: dict | None,
                   minimum: int = 10) -> int | None:
    """Queue size dialog. Returns int or None (cancelled)."""
    d = xbmcgui.Dialog()
    try:
        default = max(minimum, int(
            addon.getSetting("default_queue_size") or "30"))
    except (ValueError, TypeError):
        default = max(minimum, 30)
    cur     = str(existing.get("queue_size", default)) if existing \
              else str(default)
    entered = d.input(addon.getLocalizedString(32219),
                      defaultt=cur,
                      type=xbmcgui.INPUT_NUMERIC)
    if not entered:
        return None
    try:
        return max(minimum, min(200, int(entered)))
    except (ValueError, TypeError):
        return None


def ask_visibility(addon, existing: dict | None,
                   manager=None) -> bool | None:
    """Visibility dialog. Returns True, False, or None (cancelled).
    NEVER REMOVE — spec §6.1 step 13.

    Uses d.select (not d.yesno) because d.yesno has no cancel detection —
    Back/Escape returns False, indistinguishable from choosing "Hidden".
    An explicit Cancel item is the only way to let the user abort the wizard
    at this step without accidentally creating a hidden channel.

    When ``manager`` is given and the channel being edited is a hidden source
    (interleave or schedule), choosing Visible is refused: sources stay hidden.
    A channel with Carousel enabled cannot be made Hidden: choosing Hidden is
    refused and the channel stays Visible.
    """
    d       = xbmcgui.Dialog()
    default = 0 if (not existing or existing.get("visible", True)) else 1
    idx     = d.select(
        addon.getLocalizedString(32221),    # Show this channel in your list?
        [addon.getLocalizedString(32223),   # Show
         addon.getLocalizedString(32222),   # Hide
         addon.getLocalizedString(32933)],  # Cancel
        preselect=default)
    if idx < 0 or idx == 2:
        return None
    if idx == 1 and existing and existing.get("carousel_enabled", False):
        d.ok(addon.getLocalizedString(32000),
             addon.getLocalizedString(32915).format(
                 existing.get("name", "")))
        return True
    if (idx == 0 and manager is not None and existing
            and not existing.get("visible", True)):
        usage = manager.get_source_usage(existing.get("id", ""))
        if usage:
            d.ok(addon.getLocalizedString(32000),
                 addon.getLocalizedString(32913).format(
                     existing.get("name", ""), usage["channel_name"]))
            return False
    return idx == 0


def ask_carousel(addon, manager, channel_id: str | None,
                 existing: dict | None) -> dict | None:
    """Carousel configuration dialog.
    Returns config dict, or None on mid-step cancel.
    spec §6.1 step 14, §9.4
    """
    d           = xbmcgui.Dialog()
    no_carousel = {"enabled": False, "mode": "timed",
                   "interval": 60, "pop_count": 1}

    if channel_id:
        try:
            if manager.get_source_usage(channel_id):
                d.ok(addon.getLocalizedString(32606),
                     addon.getLocalizedString(32823))
                return no_carousel
        except Exception:
            pass

    cur_interval = existing.get("carousel_interval",  60) if existing else 60
    cur_pop      = existing.get("carousel_pop_count",  1) if existing else 1

    enable = d.yesno(
        addon.getLocalizedString(32606),
        addon.getLocalizedString(32601),
        nolabel=addon.getLocalizedString(32608),
        yeslabel=addon.getLocalizedString(32607))

    if not enable:
        return no_carousel

    mode_idx = d.select(
        addon.getLocalizedString(32861),
        [addon.getLocalizedString(32862),
         addon.getLocalizedString(32863)])
    if mode_idx < 0:
        return None
    mode = "timed" if mode_idx == 0 else "duration"

    if mode == "timed":
        interval_str = d.input(
            addon.getLocalizedString(32603),
            str(cur_interval),
            type=xbmcgui.INPUT_NUMERIC)
        if not interval_str:
            return None
        try:
            interval = max(1, int(interval_str))
        except (ValueError, TypeError):
            interval = 60

        pop_str = d.input(
            addon.getLocalizedString(32604),
            str(cur_pop),
            type=xbmcgui.INPUT_NUMERIC)
        if not pop_str:
            return None
        try:
            pop_count = max(1, int(pop_str))
        except (ValueError, TypeError):
            pop_count = 1

        d.ok(addon.getLocalizedString(32606),
             addon.getLocalizedString(32602) + "\n" +
             addon.getLocalizedString(32605))
        return {"enabled": True, "mode": "timed",
                "interval": interval, "pop_count": pop_count}

    d.ok(addon.getLocalizedString(32606),
         addon.getLocalizedString(32865) + "\n" +
         addon.getLocalizedString(32602))
    return {"enabled": True, "mode": "duration",
            "interval": 60, "pop_count": 1}
