# plugin.video.smartchannels
# resources/lib/ui/wizards/tv.py
#
# OWNS:   TV round-robin channel wizard.
#         Ported from 2.x _run_wizard (TV path) with 3.0.0 architecture.
#         Queue/cursor creation is handled by channel_manager after this
#         wizard returns the definition dict.
#
# spec §6.1, Version: 3.0.0 Phase 5

from __future__ import annotations

import random

import xbmcgui

from resources.lib.ui.dialogs import (
    build_episode_filters, build_episode_exclusions,
    build_filters, ask_queue_size, ask_visibility, ask_carousel,
    ask_starting_episode)


def run(addon, manager, name: str, existing: dict | None) -> dict | None:
    """TV round-robin wizard. Returns channel definition dict or None."""
    d = xbmcgui.Dialog()

    # ---- Show selection -------------------------------------------------------
    existing_filters = existing.get("filters", []) if existing else []
    existing_shows   = existing.get("shows",   []) if existing else []

    show_pool = manager.library.get_all_tvshows()
    if not show_pool:
        d.ok(addon.getLocalizedString(32000), addon.getLocalizedString(32212))
        return None

    filters = list(existing_filters)

    # Offer filter-by on large libraries
    if len(show_pool) > 20:
        use_filter = d.yesno(
            addon.getLocalizedString(32443),
            addon.getLocalizedString(32444).format(len(show_pool)),
            nolabel=addon.getLocalizedString(32445),
            yeslabel=addon.getLocalizedString(32446))
        if use_filter:
            filters = build_filters(addon, manager, existing_filters, "tv")
            if filters:
                filtered = manager.library.get_tvshows_with_filters(filters)
                if filtered:
                    show_pool = filtered
                    d.ok(addon.getLocalizedString(32447),
                         addon.getLocalizedString(32448).format(len(show_pool)))
                else:
                    d.ok(addon.getLocalizedString(32000),
                         addon.getLocalizedString(32212))

    show_labels = [s["title"] for s in show_pool]
    preselected = []
    if existing_shows:
        ex_ids      = {s["tvshowid"] for s in existing_shows}
        preselected = [i for i, s in enumerate(show_pool)
                       if s["tvshowid"] in ex_ids]

    chosen = d.multiselect(
        addon.getLocalizedString(32450).format(len(show_pool)),
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

    # Preserve existing per-show settings
    if existing and existing_shows:
        existing_map   = {s["tvshowid"]: s for s in existing_shows}
        existing_order = {s["tvshowid"]: idx
                          for idx, s in enumerate(existing_shows)}
        max_idx        = len(existing_shows)
        selected_shows.sort(
            key=lambda s: existing_order.get(s["tvshowid"], max_idx))
        for s in selected_shows:
            prev = existing_map.get(s["tvshowid"])
            if prev:
                for key in ("episodes_per_slot", "randomize",
                            "episode_filters", "excluded_episodes"):
                    if key in prev:
                        s[key] = prev[key]

    # ---- Playback order -------------------------------------------------------
    default_rand = existing.get("randomize", False) if existing else (
        addon.getSetting("default_randomize") == "true")
    rand_choice = d.yesno(
        addon.getLocalizedString(32214),
        addon.getLocalizedString(32215),
        nolabel=addon.getLocalizedString(32216),    # Round-Robin
        yeslabel=addon.getLocalizedString(32217),   # Random
        defaultbutton=(xbmcgui.DLG_YESNO_YES_BTN
                       if default_rand
                       else xbmcgui.DLG_YESNO_NO_BTN))
    randomize = bool(rand_choice)

    if randomize:
        for s in selected_shows:
            s.pop("randomize", None)

    # ---- Show rotation order (2+ shows, sequential) --------------------------
    if not randomize and len(selected_shows) > 1:
        shows_changed = False
        change_notice = ""
        if existing and existing_shows:
            prev_ids       = [s["tvshowid"] for s in existing_shows]
            new_ids        = [s["tvshowid"] for s in selected_shows]
            added_titles   = [s["title"] for s in selected_shows
                              if s["tvshowid"] not in set(prev_ids)]
            removed_titles = [s["title"] for s in existing_shows
                              if s["tvshowid"] not in set(new_ids)]
            if added_titles or removed_titles:
                shows_changed = True
                lines = []
                if added_titles:
                    lines.append(addon.getLocalizedString(32260).format(
                        ", ".join(added_titles)))
                if removed_titles:
                    lines.append(addon.getLocalizedString(32261).format(
                        ", ".join(removed_titles)))
                cur_order = "\n".join(
                    "{}. {}".format(i + 1, s["title"])
                    for i, s in enumerate(selected_shows))
                lines += ["", addon.getLocalizedString(32262), cur_order]
                change_notice = "\n".join(lines)

        order_title = addon.getLocalizedString(32240)
        if shows_changed and change_notice:
            d.ok(order_title,
                 addon.getLocalizedString(32263) + "\n\n" + change_notice)

        order_choice = d.select(
            order_title,
            [addon.getLocalizedString(32241),
             addon.getLocalizedString(32242),
             addon.getLocalizedString(32243)])

        if order_choice == 1:
            # Shuffle loop
            while True:
                random.shuffle(selected_shows)
                new_order = "\n".join(
                    "{}. {}".format(i + 1, s["title"])
                    for i, s in enumerate(selected_shows))
                d.ok(order_title, new_order[:300])
                shuf = d.yesno(
                    order_title,
                    addon.getLocalizedString(32249),
                    nolabel=addon.getLocalizedString(32244),    # Shuffle Again
                    yeslabel=addon.getLocalizedString(32245),   # Accept
                    defaultbutton=xbmcgui.DLG_YESNO_YES_BTN)
                if shuf:
                    break

        elif order_choice == 2:
            # Manual order
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

    # ---- Episodes per slot (2+ shows) ----------------------------------------
    if len(selected_shows) > 1:
        any_nondefault = any(
            s.get("episodes_per_slot", 1) != 1 for s in selected_shows)
        if any_nondefault:
            do_eps = True
        else:
            eps_entry = d.yesno(
                addon.getLocalizedString(32276),            # Set Episodes Per Show?
                addon.getLocalizedString(32271),
                nolabel=addon.getLocalizedString(32272),    # No, Keep 1 Each
                yeslabel=addon.getLocalizedString(32273),   # Yes, Customize
                defaultbutton=xbmcgui.DLG_YESNO_NO_BTN)
            do_eps = bool(eps_entry)

        if do_eps:
            for show in selected_shows:
                cur_eps = int(show.get("episodes_per_slot", 1))
                eps_str = d.input(
                    addon.getLocalizedString(32277).format(
                        show.get("title", ""), cur_eps),
                    defaultt=str(cur_eps),
                    type=xbmcgui.INPUT_NUMERIC)
                try:
                    show["episodes_per_slot"] = max(1, int(eps_str or cur_eps))
                except (ValueError, TypeError):
                    show["episodes_per_slot"] = cur_eps
        else:
            for show in selected_shows:
                show.pop("episodes_per_slot", None)

    # ---- Per-show random (2+ shows, sequential channel) ----------------------
    if not randomize and len(selected_shows) > 1:
        any_show_rand = any(s.get("randomize", False) for s in selected_shows)
        if any_show_rand:
            do_psr = True
        else:
            do_psr = d.yesno(
                addon.getLocalizedString(32280),
                addon.getLocalizedString(32281),
                nolabel=addon.getLocalizedString(32282),
                yeslabel=addon.getLocalizedString(32273))

        if do_psr:
            for show in selected_shows:
                cur_rand   = show.get("randomize", False)
                psr_choice = d.yesno(
                    addon.getLocalizedString(32283).format(
                        show.get("title", "")),
                    addon.getLocalizedString(32284).format(
                        show.get("title", "")),
                    nolabel=addon.getLocalizedString(32285),
                    yeslabel=addon.getLocalizedString(32217),
                    defaultbutton=(xbmcgui.DLG_YESNO_YES_BTN
                                   if cur_rand
                                   else xbmcgui.DLG_YESNO_NO_BTN))
                if psr_choice:
                    show["randomize"] = True
                else:
                    show.pop("randomize", None)
        else:
            for show in selected_shows:
                show.pop("randomize", None)

    # ---- Episode filters (per show) ------------------------------------------
    if selected_shows:
        any_existing_ef = any(s.get("episode_filters") for s in selected_shows)
        do_ef = any_existing_ef or d.yesno(
            addon.getLocalizedString(32570),
            addon.getLocalizedString(32571),
            nolabel=addon.getLocalizedString(32581),
            yeslabel=addon.getLocalizedString(32582))
        if do_ef:
            for show in selected_shows:
                title  = show.get("title", "")
                cur_ef = list(show.get("episode_filters", []))
                new_ef = build_episode_filters(addon, manager, title, cur_ef)
                if new_ef is not None:
                    if new_ef:
                        show["episode_filters"] = new_ef
                    else:
                        show.pop("episode_filters", None)

    # ---- Episode exclusions --------------------------------------------------
    if selected_shows:
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
                ex_pick = d.select(
                    addon.getLocalizedString(32596), ex_labels)
                if ex_pick < 0 or ex_pick == len(selected_shows):
                    break
                show      = selected_shows[ex_pick]
                show_title = show.get("title", "")
                cur_excl   = list(show.get("excluded_episodes", []))
                new_excl   = build_episode_exclusions(
                    addon, manager, show, show_title, cur_excl)
                if new_excl:
                    show["excluded_episodes"] = new_excl
                else:
                    show.pop("excluded_episodes", None)

    # ---- Starting point (sequential channels) --------------------------------
    starting_points = {}
    any_sequential  = any(
        not s.get("randomize", randomize) for s in selected_shows)
    if selected_shows and any_sequential:
        start_choice = d.select(
            addon.getLocalizedString(32470),
            [addon.getLocalizedString(32471) if existing
             else addon.getLocalizedString(32471),
             addon.getLocalizedString(32472),
             addon.getLocalizedString(32473)])

        if start_choice == 2:
            # Surprise Me
            seq_shows = [s for s in selected_shows
                         if not s.get("randomize", randomize)]
            while True:
                surprise_picks = {}
                for show in seq_shows:
                    sid  = show["tvshowid"]
                    eps  = manager.get_available_episodes(show)
                    if eps:
                        surprise_picks[sid] = random.choice(eps)
                summary_lines = []
                for show in seq_shows:
                    sid = show["tvshowid"]
                    ep  = surprise_picks.get(sid)
                    if ep:
                        summary_lines.append(
                            "{}: {}".format(
                                show["title"],
                                addon.getLocalizedString(32693).format(
                                    ep["season"], ep["episode"],
                                    ep.get("title", ""))))
                    else:
                        summary_lines.append(
                            "{}: {}".format(show["title"],
                                            addon.getLocalizedString(32483).format("")))
                d.ok(addon.getLocalizedString(32473), "\n".join(summary_lines))
                accept = d.yesno(
                    addon.getLocalizedString(32473),
                    addon.getLocalizedString(32249),
                    nolabel=addon.getLocalizedString(32475),    # Try Again
                    yeslabel=addon.getLocalizedString(32245),   # Accept
                    defaultbutton=xbmcgui.DLG_YESNO_YES_BTN)
                if accept:
                    for show in seq_shows:
                        sid = show["tvshowid"]
                        ep  = surprise_picks.get(sid)
                        if ep:
                            starting_points[sid] = {
                                "episodeid": ep["episodeid"],
                                "season":    ep["season"],
                                "episode":   ep["episode"],
                                "title":     ep.get("title", ""),
                            }
                    break

        elif start_choice == 1:
            # Manual
            seq_shows_manual = [s for s in selected_shows
                                 if not s.get("randomize", randomize)]
            for show in seq_shows_manual:
                pick = ask_starting_episode(
                    addon, manager, show,
                    existing.get("id", "") if existing else "")
                if pick:
                    starting_points[show["tvshowid"]] = pick

    # All TV channels always recycle (design decision)
    recycle = True

    # ---- Queue size ----------------------------------------------------------
    queue_size = ask_queue_size(addon, existing)
    if queue_size is None:
        return None

    # ---- Visibility  NEVER REMOVE --------------------------------------------
    visible = ask_visibility(addon, existing, manager)
    if visible is None:
        return None

    # ---- Carousel (TV only) — hidden channels cannot have carousel ----------
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
        "channel_type":       "tv",
        "playback_mode":      "round_robin",
        "shows":              selected_shows,
        "movies":             [],
        "randomize":          randomize,
        "recycle":            recycle,
        "queue_size":         queue_size,
        "visible":            visible,
        "filters":            filters,
        "excluded_movies":    [],
        "interleave":         existing.get("interleave") if existing else None,
        "starting_points":    starting_points,
        "carousel_enabled":   carousel["enabled"],
        "carousel_mode":      carousel["mode"],
        "carousel_interval":  carousel["interval"],
        "carousel_pop_count": carousel["pop_count"],
    }
