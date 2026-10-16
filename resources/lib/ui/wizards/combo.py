# plugin.video.smartchannels
# resources/lib/ui/wizards/combo.py
#
# OWNS:   Combo Block channel wizard and slot wizard.
# spec §6.7, §6.7.1, Version: 3.0.0 Phase 5

from __future__ import annotations

import uuid

import xbmcgui

from resources.lib.ui.dialogs import (
    build_filters, build_episode_exclusions, build_movie_exclusions,
    browse_folder_path)
from resources.lib.channels.folder import _normalise_path
from resources.lib.channels.interleave import (
    TV_MODE_TURNS, tv_slot_takes_turns, tv_turn_size)


def run(addon, manager, name: str, existing: dict | None) -> dict | None:
    """Combo Block wizard. Returns channel definition dict or None."""
    d = xbmcgui.Dialog()

    # Edit warning
    if existing:
        d.ok(addon.getLocalizedString(32000),
             addon.getLocalizedString(32872))
        owner = manager.get_combo_owner(existing.get("id", ""))
        if owner:
            d.ok(addon.getLocalizedString(32000),
                 addon.getLocalizedString(32877).format(
                     owner.get("channel_name", "?")))

    slots = list(existing.get("slots", []) if existing else [])

    # ---- Slot management loop ------------------------------------------------
    while True:
        menu_items = []
        for sl in slots:
            src = sl.get("source_type", "?")
            if src == "tv":
                shows = sl.get("shows", [])
                title = ", ".join(s.get("title", "") for s in shows) \
                        if shows else "?"
            elif src == "movies":
                title = addon.getLocalizedString(32441)
            else:
                fp    = sl.get("folder_path", "")
                title = (fp.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
                         if fp else "?")
            menu_items.append("[{}] {}".format(src.upper(), title))

        add_idx = len(slots)
        menu_items.append(addon.getLocalizedString(32867))   # Add Slot
        menu_items.append(addon.getLocalizedString(32491))   # Done
        done_idx = len(menu_items) - 1

        choice = d.select(
            addon.getLocalizedString(32898), menu_items)
        if choice < 0 or choice == done_idx:
            break

        if choice == add_idx:
            new_slot = _run_slot_wizard(addon, manager, d, None)
            if new_slot:
                slots.append(new_slot)
            continue

        sl_idx    = choice
        sl        = slots[sl_idx]
        sl_name   = menu_items[sl_idx]
        sl_choice = d.select(
            sl_name,
            [addon.getLocalizedString(32873),    # Edit
             addon.getLocalizedString(32874),    # Move Up
             addon.getLocalizedString(32875),    # Move Down
             addon.getLocalizedString(32876),    # Remove
             addon.getLocalizedString(32491)])   # Cancel
        if sl_choice < 0 or sl_choice == 4:
            continue
        if sl_choice == 0:
            updated = _run_slot_wizard(addon, manager, d, sl)
            if updated:
                slots[sl_idx] = updated
        elif sl_choice == 1:
            if sl_idx > 0:
                slots[sl_idx - 1], slots[sl_idx] = \
                    slots[sl_idx], slots[sl_idx - 1]
        elif sl_choice == 2:
            if sl_idx < len(slots) - 1:
                slots[sl_idx + 1], slots[sl_idx] = \
                    slots[sl_idx], slots[sl_idx + 1]
        elif sl_choice == 3:
            if d.yesno(addon.getLocalizedString(32876),
                       addon.getLocalizedString(32895).format(sl_name)):
                slots.pop(sl_idx)

    if not slots:
        d.ok(addon.getLocalizedString(32000), addon.getLocalizedString(32868))
        return None

    # queue_size is not asked or stored for Combo Blocks.
    # No queue file is written in 3.x — items are built on-demand
    # via build_one_slot (1-for-1 replacement).

    return {
        "name":         name,
        "channel_type": "combo",
        "visible":      False,
        "slots":        slots,
        "owner":        existing.get("owner") if existing else None,
        "shows":        [],
        "movies":       [],
        "filters":      [],
        "randomize":    False,
        "recycle":      True,
        "starting_points": {},
        "carousel_enabled":   False,
        "carousel_mode":      "timed",
        "carousel_interval":  60,
        "carousel_pop_count": 1,
    }


def _ask_tv_rotation(addon, d, ex: dict, slot: dict,
                     selected_shows: list) -> bool:
    """Ask how a TV slot with two or more shows shares each cycle.

    Together (the default): every show plays in every cycle, with its own
    episodes-per-slot count.  Taking turns: one show plays per cycle, the
    next show on the next cycle, with one shared episodes-per-turn count.

    Sets tv_mode / episodes_per_turn on *slot* and returns True when the
    shows take turns; returns False (slot untouched) when they play
    together or the dialog is cancelled on a slot that played together.
    """
    previous = 1 if tv_slot_takes_turns(ex) else 0
    choice = d.select(
        addon.getLocalizedString(32941),
        [addon.getLocalizedString(32942), addon.getLocalizedString(32943)],
        preselect=previous)
    if choice < 0:
        choice = previous
    if choice != 1:
        return False
    current = tv_turn_size(ex)
    turn_str = d.input(
        addon.getLocalizedString(32944).format(current),
        defaultt=str(current),
        type=xbmcgui.INPUT_NUMERIC)
    try:
        turn = max(1, int(turn_str or current))
    except (ValueError, TypeError):
        turn = current
    slot["tv_mode"]           = TV_MODE_TURNS
    slot["episodes_per_turn"] = turn
    for show in selected_shows:
        show.pop("episodes_per_slot", None)
    return True


def _run_slot_wizard(addon, manager, d, existing_slot) -> dict | None:
    """Configure one Combo Block slot. Returns slot dict or None."""
    import random as _random
    ex = existing_slot or {}

    src_types  = ["tv", "movies", "folder"]
    src_labels = [
        addon.getLocalizedString(32440),   # TV Shows
        addon.getLocalizedString(32441),   # Movies
        addon.getLocalizedString(32531),   # Folder
    ]
    src_choice = d.select(addon.getLocalizedString(32869), src_labels)
    if src_choice < 0:
        return None
    source_type = src_types[src_choice]

    slot_id = ex.get("slot_id") or str(uuid.uuid4())
    slot    = {"slot_id": slot_id, "source_type": source_type}

    if source_type == "tv":
        show_pool = manager.library.get_all_tvshows()
        if not show_pool:
            d.ok(addon.getLocalizedString(32000),
                 addon.getLocalizedString(32212))
            return None

        # Genre/year filter — only offered on large libraries
        if len(show_pool) > 20:
            use_filter = d.yesno(
                addon.getLocalizedString(32443),
                addon.getLocalizedString(32444).format(len(show_pool)),
                nolabel=addon.getLocalizedString(32445),
                yeslabel=addon.getLocalizedString(32446))
            if use_filter:
                existing_filters = ex.get("filters", [])
                filters = build_filters(addon, manager, existing_filters, "tv")
                if filters:
                    filtered = manager.library.get_tvshows_with_filters(filters)
                    if filtered:
                        show_pool = filtered
                        d.ok(addon.getLocalizedString(32447),
                             addon.getLocalizedString(32448).format(
                                 len(show_pool)))
                    else:
                        d.ok(addon.getLocalizedString(32000),
                             addon.getLocalizedString(32212))
                slot["filters"] = filters

        existing_shows_list = ex.get("shows")
        if not existing_shows_list and ex.get("tvshowid"):
            existing_shows_list = [{"tvshowid": ex["tvshowid"],
                                     "title": ex.get("title", "")}]
        existing_shows_list = existing_shows_list or []
        ex_show_ids  = {s["tvshowid"] for s in existing_shows_list}
        ex_show_map  = {s["tvshowid"]: s for s in existing_shows_list}
        preselected  = [i for i, s in enumerate(show_pool)
                        if s["tvshowid"] in ex_show_ids]

        chosen_idxs = d.multiselect(
            addon.getLocalizedString(32450).format(len(show_pool)),
            [s["title"] for s in show_pool],
            preselect=preselected)
        if chosen_idxs is None:
            return None
        if not chosen_idxs:
            d.ok(addon.getLocalizedString(32000),
                 addon.getLocalizedString(32210))
            return None

        selected_shows = []
        for idx in chosen_idxs:
            sp       = show_pool[idx]
            show_id  = sp["tvshowid"]
            prev     = ex_show_map.get(show_id, {})
            show_cfg = {
                "tvshowid":          show_id,
                "title":             sp["title"],
                "episode_filters":   [],
                "excluded_episodes": prev.get("excluded_episodes", []),
            }

            # Per-show episode exclusions
            want_excl = d.yesno(
                addon.getLocalizedString(32585),
                addon.getLocalizedString(32622).format(sp["title"]),
                nolabel=addon.getLocalizedString(32587),
                yeslabel=addon.getLocalizedString(32588))
            if want_excl:
                show_cfg["excluded_episodes"] = build_episode_exclusions(
                    addon, manager, show_cfg, sp["title"],
                    show_cfg["excluded_episodes"])
            else:
                show_cfg["excluded_episodes"] = prev.get("excluded_episodes", [])

            # Per-show order
            rand_tv = d.yesno(
                "{} — {}".format(addon.getLocalizedString(32214), sp["title"]),
                addon.getLocalizedString(32215),
                nolabel=addon.getLocalizedString(32285),    # Sequential
                yeslabel=addon.getLocalizedString(32217),   # Random
                defaultbutton=(xbmcgui.DLG_YESNO_YES_BTN
                               if prev.get("randomize", True)
                               else xbmcgui.DLG_YESNO_NO_BTN))
            show_cfg["randomize"] = bool(rand_tv)
            show_cfg["recycle"]   = True

            selected_shows.append(show_cfg)

        # ---- Show rotation order (2+ shows only) ----------------------------
        if len(selected_shows) > 1:
            order_title  = addon.getLocalizedString(32240)
            order_choice = d.select(
                order_title,
                [addon.getLocalizedString(32241),   # Keep current order
                 addon.getLocalizedString(32242),   # Shuffle
                 addon.getLocalizedString(32243)])  # Pick manually
            if order_choice == 1:
                # Shuffle loop
                while True:
                    _random.shuffle(selected_shows)
                    new_order = "\n".join(
                        "{}. {}".format(i + 1, s["title"])
                        for i, s in enumerate(selected_shows))
                    d.ok(order_title, new_order[:300])
                    shuf = d.yesno(
                        order_title,
                        addon.getLocalizedString(32249),
                        nolabel=addon.getLocalizedString(32244),  # Shuffle Again
                        yeslabel=addon.getLocalizedString(32245), # Accept
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
                        nolabel=addon.getLocalizedString(32248),  # Start Over
                        yeslabel=addon.getLocalizedString(32245), # Accept
                        defaultbutton=xbmcgui.DLG_YESNO_YES_BTN)
                    if confirm:
                        selected_shows = ordered
                        break

        slot["shows"] = selected_shows

        # ---- Shows share the slot together, or take turns (2+ shows) --------
        takes_turns = (len(selected_shows) > 1
                       and _ask_tv_rotation(addon, d, ex, slot,
                                            selected_shows))

        # ---- Episodes per slot (1+ shows, playing together) ------------------
        if len(selected_shows) >= 1 and not takes_turns:
            any_nondefault = any(
                s.get("episodes_per_slot", 1) != 1 for s in selected_shows)
            if any_nondefault:
                do_eps = True
            else:
                if len(selected_shows) > 1:
                    body = addon.getLocalizedString(32269)    # ...per combo unit...
                else:
                    cur_single = int(selected_shows[0].get("episodes_per_slot", 1))
                    body = addon.getLocalizedString(32275).format(cur_single)
                do_eps = bool(d.yesno(
                    addon.getLocalizedString(32268),           # Episodes Per Slot?
                    body,
                    nolabel=addon.getLocalizedString(32272),   # No, Keep 1 Each
                    yeslabel=addon.getLocalizedString(32273),  # Yes, Customize
                    defaultbutton=xbmcgui.DLG_YESNO_NO_BTN))
            if do_eps:
                for show in selected_shows:
                    cur_eps = int(show.get("episodes_per_slot", 1))
                    eps_str = d.input(
                        addon.getLocalizedString(32267).format(
                            show.get("title", ""), cur_eps),   # Episodes per slot for {0} (current: {1}):
                        defaultt=str(cur_eps),
                        type=xbmcgui.INPUT_NUMERIC)
                    try:
                        show["episodes_per_slot"] = max(1, int(eps_str or cur_eps))
                    except (ValueError, TypeError):
                        show["episodes_per_slot"] = cur_eps
            else:
                for show in selected_shows:
                    show.pop("episodes_per_slot", None)

        # ---- Per-show starting point (sequential shows only) ----------------
        starting_points = {}
        any_sequential  = any(
            not s.get("randomize", False) for s in selected_shows)
        if any_sequential:
            start_choice = d.select(
                addon.getLocalizedString(32470),
                [addon.getLocalizedString(32471),   # From beginning / current
                 addon.getLocalizedString(32472),   # Manual
                 addon.getLocalizedString(32473)])  # Surprise Me
            if start_choice == 2:
                # Surprise Me
                seq_shows = [s for s in selected_shows
                             if not s.get("randomize", False)]
                while True:
                    surprise_picks = {}
                    for show in seq_shows:
                        eps = manager.get_available_episodes(show)
                        if eps:
                            surprise_picks[show["tvshowid"]] = \
                                _random.choice(eps)
                    summary_lines = []
                    for show in seq_shows:
                        sid = show["tvshowid"]
                        ep  = surprise_picks.get(sid)
                        if ep:
                            summary_lines.append("{}: {}".format(
                                show["title"],
                                addon.getLocalizedString(32693).format(
                                    ep["season"], ep["episode"],
                                    ep.get("title", ""))))
                        else:
                            summary_lines.append("{}: {}".format(
                                show["title"],
                                addon.getLocalizedString(32483).format("")))
                    d.ok(addon.getLocalizedString(32473),
                         "\n".join(summary_lines))
                    accept = d.yesno(
                        addon.getLocalizedString(32473),
                        addon.getLocalizedString(32249),
                        nolabel=addon.getLocalizedString(32475),   # Try Again
                        yeslabel=addon.getLocalizedString(32245),  # Accept
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
                # Manual pick per show
                seq_shows = [s for s in selected_shows
                             if not s.get("randomize", False)]
                for show in seq_shows:
                    sid        = show["tvshowid"]
                    show_title = show["title"]
                    nolabel    = addon.getLocalizedString(32599)
                    if ex.get("starting_points", {}).get(str(sid)):
                        sp  = ex["starting_points"][str(sid)]
                        nolabel = addon.getLocalizedString(32477).format(
                            sp.get("season", 1), sp.get("episode", 1))
                    do_set = d.yesno(
                        show_title,
                        addon.getLocalizedString(32479).format(show_title),
                        nolabel=nolabel,
                        yeslabel=addon.getLocalizedString(32478))
                    if not do_set:
                        continue
                    episodes = manager.get_available_episodes(show)
                    if not episodes:
                        d.ok(addon.getLocalizedString(32000),
                             addon.getLocalizedString(32483).format(show_title))
                        continue
                    seasons       = sorted(set(e["season"] for e in episodes))
                    season_labels = [addon.getLocalizedString(32480).format(s)
                                     for s in seasons]
                    season_choice = d.select(
                        addon.getLocalizedString(32481).format(
                            show_title, ""),
                        season_labels)
                    if season_choice < 0:
                        continue
                    chosen_season = seasons[season_choice]
                    season_eps    = sorted(
                        [e for e in episodes
                         if e["season"] == chosen_season],
                        key=lambda e: e["episode"])
                    ep_labels = [
                        addon.getLocalizedString(32693).format(
                            e["season"], e["episode"], e["title"])
                        for e in season_eps]
                    ep_choice = d.select(
                        addon.getLocalizedString(32482).format(
                            show_title, ""),
                        ep_labels)
                    if ep_choice < 0:
                        continue
                    chosen_ep = season_eps[ep_choice]
                    starting_points[sid] = {
                        "episodeid": chosen_ep["episodeid"],
                        "season":    chosen_ep["season"],
                        "episode":   chosen_ep["episode"],
                        "title":     chosen_ep.get("title", ""),
                    }
        slot["starting_points"] = starting_points

    elif source_type == "movies":
        all_movies = manager.library.get_all_movies()
        if not all_movies:
            d.ok(addon.getLocalizedString(32000),
                 addon.getLocalizedString(32451))
            return None

        # Pick specific movies or use filters
        method_choice = d.select(
            addon.getLocalizedString(32452),
            [addon.getLocalizedString(32453).format(len(all_movies)),  # All Movies
             addon.getLocalizedString(32454),                          # Select Specific
             addon.getLocalizedString(32461)])                         # Add Filters
        if method_choice < 0:
            return None

        slot["movies"]   = []
        slot["filters"]  = []

        if method_choice == 1:
            # Pick specific movies by hand
            existing_movie_ids = {m["movieid"] for m in ex.get("movies", [])}
            preselected = [i for i, m in enumerate(all_movies)
                           if m.get("movieid") in existing_movie_ids]
            chosen = d.multiselect(
                addon.getLocalizedString(32456),
                [m.get("label", m.get("title", "")) for m in all_movies],
                preselect=preselected)
            if not chosen:
                d.ok(addon.getLocalizedString(32000),
                     addon.getLocalizedString(32457))
                return None
            slot["movies"] = [
                {"movieid": all_movies[i]["movieid"],
                 "title":   all_movies[i].get("label",
                            all_movies[i].get("title", ""))}
                for i in chosen]

        elif method_choice == 2:
            # Filter-based selection
            existing_filters = ex.get("filters", [])
            slot["filters"] = build_filters(
                addon, manager, existing_filters, "movies") or []
            if slot["filters"]:
                matched = manager.library.get_movies_with_filters(slot["filters"])
                d.ok(addon.getLocalizedString(32447),
                     addon.getLocalizedString(32521).format(len(matched)))

        # Exclusions (only meaningful for all-movies or filter modes)
        if method_choice != 1:
            existing_excl = ex.get("excluded_movies", [])
            want_excl = d.yesno(
                addon.getLocalizedString(32593),
                addon.getLocalizedString(32594),
                nolabel=addon.getLocalizedString(32587),
                yeslabel=addon.getLocalizedString(32588))
            if want_excl:
                slot["excluded_movies"] = build_movie_exclusions(
                    addon, all_movies, existing_excl)
            else:
                slot["excluded_movies"] = existing_excl
        else:
            slot["excluded_movies"] = []

        # Movies per slot
        cur_mps = int(ex.get("movies_per_slot", 1))
        do_mps  = bool(d.yesno(
            addon.getLocalizedString(32270),
            addon.getLocalizedString(32275).format(cur_mps),
            nolabel=addon.getLocalizedString(32272),   # No, keep 1 each
            yeslabel=addon.getLocalizedString(32273),  # Yes, customise
            defaultbutton=(xbmcgui.DLG_YESNO_YES_BTN
                           if cur_mps > 1
                           else xbmcgui.DLG_YESNO_NO_BTN)))
        if do_mps:
            mps_str = d.input(
                addon.getLocalizedString(32274).format(cur_mps),
                defaultt=str(cur_mps),
                type=xbmcgui.INPUT_NUMERIC)
            try:
                slot["movies_per_slot"] = max(1, int(mps_str or cur_mps))
            except (ValueError, TypeError):
                slot["movies_per_slot"] = cur_mps
        else:
            slot.pop("movies_per_slot", None)

        rand_mv = d.yesno(
            addon.getLocalizedString(32462),
            addon.getLocalizedString(32463),
            nolabel=addon.getLocalizedString(32464),    # In Order
            yeslabel=addon.getLocalizedString(32217),   # Random
            defaultbutton=(xbmcgui.DLG_YESNO_YES_BTN
                           if ex.get("randomize", True)
                           else xbmcgui.DLG_YESNO_NO_BTN))
        slot["randomize"] = bool(rand_mv)
        slot["recycle"]   = True

    elif source_type == "folder":
        cur_path    = ex.get("folder_path", "")
        folder_path = browse_folder_path(addon, cur_path)
        if not folder_path:
            return None
        slot["folder_path"] = _normalise_path(folder_path)

        rand_fl = d.yesno(
            addon.getLocalizedString(32214),
            addon.getLocalizedString(32215),
            nolabel=addon.getLocalizedString(32285),    # Sequential
            yeslabel=addon.getLocalizedString(32217),   # Random
            defaultbutton=(xbmcgui.DLG_YESNO_YES_BTN
                           if ex.get("randomize", True)
                           else xbmcgui.DLG_YESNO_NO_BTN))
        slot["randomize"] = bool(rand_fl)
        slot["recycle"]   = True

        # No Repeat is always on for a folder slot, so there is nothing to
        # ask: Random plays every file once before any repeats, and
        # Sequential walks the folder in order (the played list is what
        # advances it) and starts over when it reaches the end.
        slot["no_repeat"] = True

        # ---- Items per slot --------------------------------------------------
        cur_fps = int(ex.get("episodes_per_slot", 1))
        do_fps  = bool(d.yesno(
            addon.getLocalizedString(32270),
            addon.getLocalizedString(32275).format(cur_fps),
            nolabel=addon.getLocalizedString(32272),
            yeslabel=addon.getLocalizedString(32273),
            defaultbutton=(xbmcgui.DLG_YESNO_YES_BTN
                           if cur_fps > 1
                           else xbmcgui.DLG_YESNO_NO_BTN)))
        if do_fps:
            fps_str = d.input(
                addon.getLocalizedString(32274).format(cur_fps),
                defaultt=str(cur_fps),
                type=xbmcgui.INPUT_NUMERIC)
            try:
                slot["episodes_per_slot"] = max(1, int(fps_str or cur_fps))
            except (ValueError, TypeError):
                slot["episodes_per_slot"] = cur_fps
        else:
            slot.pop("episodes_per_slot", None)

    # Silent — asked at slot level for all source types.
    # TV slots: one question covers all shows in the slot (they rotate
    # round-robin as a unit so mixing silent/non-silent within one slot
    # makes no sense). Movie and Folder slots: same as before.
    slot["silent"] = d.yesno(
        addon.getLocalizedString(32555),
        addon.getLocalizedString(32899),
        nolabel=addon.getLocalizedString(32886),
        yeslabel=addon.getLocalizedString(32885))

    return slot
