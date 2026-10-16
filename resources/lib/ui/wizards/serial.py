# plugin.video.smartchannels
# resources/lib/ui/wizards/serial.py
#
# OWNS:   Serial channel wizard.
# spec §6.2, Version: 3.0.0 Phase 5

from __future__ import annotations

import random

import xbmcgui

from resources.lib.ui.dialogs import (
    build_episode_exclusions, ask_queue_size, ask_visibility,
    ask_starting_episode)


def run(addon, manager, name: str, existing: dict | None) -> dict | None:
    """Serial wizard. Returns channel definition dict or None."""
    d = xbmcgui.Dialog()

    existing_shows = existing.get("shows", []) if existing else []

    show_pool = manager.library.get_all_tvshows()
    if not show_pool:
        d.ok(addon.getLocalizedString(32000), addon.getLocalizedString(32212))
        return None

    show_labels = [s["title"] for s in show_pool]
    preselected = []
    if existing_shows:
        ex_ids      = {s["tvshowid"] for s in existing_shows}
        preselected = [i for i, s in enumerate(show_pool)
                       if s["tvshowid"] in ex_ids]

    chosen = d.multiselect(
        addon.getLocalizedString(32310),
        show_labels,
        preselect=preselected)
    if chosen is None:
        return None
    if not chosen:
        d.ok(addon.getLocalizedString(32000), addon.getLocalizedString(32210))
        return None

    selected_shows = [
        {"tvshowid": show_pool[i]["tvshowid"],
         "title":    show_pool[i]["title"]}
        for i in chosen
    ]

    # Preserve existing order
    if existing and existing_shows:
        existing_order = {s["tvshowid"]: idx
                          for idx, s in enumerate(existing_shows)}
        max_idx        = len(existing_shows)
        selected_shows.sort(
            key=lambda s: existing_order.get(s["tvshowid"], max_idx))
        # Preserve per-show exclusions
        existing_map = {s["tvshowid"]: s for s in existing_shows}
        for s in selected_shows:
            prev = existing_map.get(s["tvshowid"])
            if prev and "excluded_episodes" in prev:
                s["excluded_episodes"] = prev["excluded_episodes"]

    # ---- Show order (2+ shows) -----------------------------------------------
    if len(selected_shows) > 1:
        order_choice = d.select(
            addon.getLocalizedString(32311),
            [addon.getLocalizedString(32312),    # Manual order
             addon.getLocalizedString(32241),    # Keep selection order
             addon.getLocalizedString(32242)])   # Shuffle

        if order_choice == 0 or order_choice < 0:
            # Manual
            while True:
                remaining = list(selected_shows)
                ordered   = []
                for pos in range(len(selected_shows)):
                    labels = [s["title"] for s in remaining]
                    pick   = d.select(
                        addon.getLocalizedString(32246).format(pos + 1),
                        labels)
                    if pick < 0:
                        ordered = list(selected_shows)
                        break
                    ordered.append(remaining[pick])
                    remaining.pop(pick)
                summary = "\n".join(
                    "{}. {}".format(i + 1, s["title"])
                    for i, s in enumerate(ordered))
                d.ok(addon.getLocalizedString(32247), summary)
                confirm = d.yesno(
                    addon.getLocalizedString(32247),
                    addon.getLocalizedString(32249),
                    nolabel=addon.getLocalizedString(32248),    # Start Over
                    yeslabel=addon.getLocalizedString(32245),   # Accept
                    defaultbutton=xbmcgui.DLG_YESNO_YES_BTN)
                if confirm:
                    selected_shows = ordered
                    break

        elif order_choice == 2:
            # Shuffle
            while True:
                random.shuffle(selected_shows)
                new_order = "\n".join(
                    "{}. {}".format(i + 1, s["title"])
                    for i, s in enumerate(selected_shows))
                d.ok(addon.getLocalizedString(32311), new_order[:300])
                shuf = d.yesno(
                    addon.getLocalizedString(32311),
                    addon.getLocalizedString(32249),
                    nolabel=addon.getLocalizedString(32244),    # Shuffle Again
                    yeslabel=addon.getLocalizedString(32245),   # Accept
                    defaultbutton=xbmcgui.DLG_YESNO_YES_BTN)
                if shuf:
                    break

    # ---- Episode exclusions --------------------------------------------------
    do_any_ex = d.yesno(
        addon.getLocalizedString(32585),
        addon.getLocalizedString(32586),
        nolabel=addon.getLocalizedString(32587),
        yeslabel=addon.getLocalizedString(32588))
    if do_any_ex:
        while True:
            ex_labels = []
            for show in selected_shows:
                ec = len(show.get("excluded_episodes", []))
                ex_labels.append("{} — {}".format(
                    show.get("title", ""),
                    addon.getLocalizedString(32590).format(ec)
                    if ec else addon.getLocalizedString(32591)))
            ex_labels.append(addon.getLocalizedString(32491))
            ex_pick = d.select(addon.getLocalizedString(32596), ex_labels)
            if ex_pick < 0 or ex_pick == len(selected_shows):
                break
            show       = selected_shows[ex_pick]
            show_title = show.get("title", "")
            cur_excl   = list(show.get("excluded_episodes", []))
            new_excl   = build_episode_exclusions(
                addon, manager, show, show_title, cur_excl)
            if new_excl:
                show["excluded_episodes"] = new_excl
            else:
                show.pop("excluded_episodes", None)

    # ---- Starting episodes (shows new to this channel only) -------------------
    # Shows already in the channel keep their current position; only shows
    # being added (or every show when creating) can be given a start episode.
    starting_points = {}
    old_ids = {s["tvshowid"] for s in existing_shows}
    for show in selected_shows:
        if show["tvshowid"] in old_ids:
            continue
        pick = ask_starting_episode(addon, manager, show, "",
                                    default_label_id=32471)
        if pick:
            starting_points[show["tvshowid"]] = pick

    # All Serial channels always recycle (design decision)
    recycle = True

    # ---- Queue size ----------------------------------------------------------
    queue_size = ask_queue_size(addon, existing)
    if queue_size is None:
        return None

    # ---- Visibility  NEVER REMOVE --------------------------------------------
    visible = ask_visibility(addon, existing, manager)
    if visible is None:
        return None

    return {
        "name":            name,
        "channel_type":    "tv",
        "playback_mode":   "serial",
        "shows":           selected_shows,
        "movies":          [],
        "randomize":       False,
        "recycle":         recycle,
        "queue_size":      queue_size,
        "visible":         visible,
        "filters":         existing.get("filters", []) if existing else [],
        "excluded_movies": [],
        "interleave":      existing.get("interleave") if existing else None,
        "starting_points": starting_points,
        "carousel_enabled":   False,
        "carousel_mode":      "timed",
        "carousel_interval":  60,
        "carousel_pop_count": 1,
    }
