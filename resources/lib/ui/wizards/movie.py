# plugin.video.smartchannels
# resources/lib/ui/wizards/movie.py
#
# OWNS:   Movie channel wizard.
# spec §6.3, Version: 3.0.0 Phase 5

from __future__ import annotations

import xbmcgui

from resources.lib.ui.dialogs import (
    build_filters, build_movie_exclusions,
    ask_queue_size, ask_visibility, ask_carousel)


def run(addon, manager, name: str, existing: dict | None) -> dict | None:
    """Movie wizard. Returns channel definition dict or None."""
    d = xbmcgui.Dialog()

    all_movies = manager.library.get_all_movies()
    if not all_movies:
        d.ok(addon.getLocalizedString(32000), addon.getLocalizedString(32451))
        return None

    # ---- Movie selection -----------------------------------------------------
    filter_choice = d.select(
        addon.getLocalizedString(32452),
        [addon.getLocalizedString(32453).format(len(all_movies)),
         addon.getLocalizedString(32454)])
    if filter_choice < 0:
        return None

    filters      = []
    pick_specific = (filter_choice == 1)

    if pick_specific:
        existing_ids = {m["movieid"] for m in existing.get("movies", [])} \
                       if existing else set()
        movie_labels = [m.get("title", str(m["movieid"])) for m in all_movies]
        preselected  = [i for i, m in enumerate(all_movies)
                        if m["movieid"] in existing_ids]
        chosen = d.multiselect(
            addon.getLocalizedString(32454),
            movie_labels,
            preselect=preselected)
        if chosen is None:
            return None
        if not chosen:
            d.ok(addon.getLocalizedString(32000),
                 addon.getLocalizedString(32457))
            return None
        selected_movies = [
            {"movieid": all_movies[i]["movieid"],
             "title":   all_movies[i].get("title", "")}
            for i in chosen
        ]
    else:
        selected_movies = [
            {"movieid": m["movieid"], "title": m.get("title", "")}
            for m in all_movies
        ]

    # ---- Movie filters (all-movies path only) --------------------------------
    if not pick_specific:
        existing_filters = existing.get("filters", []) if existing else []
        add_filters = d.yesno(
            addon.getLocalizedString(32458),
            addon.getLocalizedString(32459),
            nolabel=addon.getLocalizedString(32460),
            yeslabel=addon.getLocalizedString(32461))
        if add_filters:
            filters = build_filters(addon, manager, existing_filters, "movies")
            if filters:
                matched = manager.library.get_movies_with_filters(filters)
                d.ok(addon.getLocalizedString(32447),
                     addon.getLocalizedString(32521).format(len(matched)))
        else:
            filters = existing_filters

    # ---- Movie exclusions (all-movies path only) -----------------------------
    excluded_movies = existing.get("excluded_movies", []) if existing else []
    if not pick_specific:
        want_excl = d.yesno(
            addon.getLocalizedString(32593),
            addon.getLocalizedString(32594),
            nolabel=addon.getLocalizedString(32587),
            yeslabel=addon.getLocalizedString(32588))
        if want_excl:
            excluded_movies = build_movie_exclusions(
                addon, selected_movies, excluded_movies)

    # ---- Playback order ------------------------------------------------------
    default_rand = existing.get("randomize", True) if existing else True
    rand_choice = d.yesno(
        addon.getLocalizedString(32462),
        addon.getLocalizedString(32463),
        nolabel=addon.getLocalizedString(32464),    # In Order
        yeslabel=addon.getLocalizedString(32217),   # Random
        defaultbutton=(xbmcgui.DLG_YESNO_YES_BTN
                       if default_rand
                       else xbmcgui.DLG_YESNO_NO_BTN))
    randomize = bool(rand_choice)

    # All Movie channels always recycle (design decision)
    recycle = True

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
        "name":               name,
        "channel_type":       "movies",
        "playback_mode":      "round_robin",
        "shows":              [],
        "movies":             selected_movies,
        "randomize":          randomize,
        "recycle":            recycle,
        "queue_size":         queue_size,
        "visible":            visible,
        "filters":            filters,
        "excluded_movies":    excluded_movies,
        "interleave":         existing.get("interleave") if existing else None,
        "starting_points":    {},
        "carousel_enabled":   carousel["enabled"],
        "carousel_mode":      carousel["mode"],
        "carousel_interval":  carousel["interval"],
        "carousel_pop_count": carousel["pop_count"],
    }
