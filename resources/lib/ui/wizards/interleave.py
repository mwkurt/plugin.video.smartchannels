# plugin.video.smartchannels
# resources/lib/ui/wizards/interleave.py
#
# OWNS:   Interleave dialog — add/edit/remove interleave sources.
# spec §6.8, Version: 3.0.0 Phase 5

from __future__ import annotations

import xbmc
import xbmcgui

from resources.lib.channels.interleave import get_sources


def run(addon, manager, channel_id: str) -> None:
    """Multi-source interleave configuration dialog.
    Ported from 2.x manage_interleave_dialog.
    spec §6.8
    """
    channel = manager.get_channel(channel_id)
    if not channel:
        return

    d = xbmcgui.Dialog()

    # Build eligible source lists
    all_regular = [c for c in manager.get_all_channels()
                   if c["id"] != channel_id
                   and c.get("channel_type") not in ("audio", "party", "combo")]
    # Sources must be hidden channels. A carousel flag left on a hidden
    # channel still disqualifies it (carousel and source cannot coexist).
    # Serial TV channels cannot be sources (stored as type "tv" with
    # playback_mode "serial").
    other             = [c for c in all_regular
                         if not c.get("visible", True)
                         and not c.get("carousel_enabled", False)
                         and c.get("playback_mode") != "serial"]
    combo_sources     = [c for c in manager.get_all_channels()
                         if c.get("channel_type") == "combo"
                         and c["id"] != channel_id]

    if not other and not combo_sources:
        d.ok(addon.getLocalizedString(32000),
             addon.getLocalizedString(32914))
        return

    def _would_be_circular(foreign_id, origin_id, visited=None):
        if visited is None:
            visited = set()
        if foreign_id in visited:
            return True
        visited.add(foreign_id)
        foreign_ch = manager.get_channel(foreign_id)
        if not foreign_ch:
            return False
        for src in get_sources(foreign_ch):
            next_id = src.get("channel_id", "")
            if next_id == origin_id:
                return True
            if _would_be_circular(next_id, origin_id, visited):
                return True
        return False

    def _source_input_dialog(existing=None):
        ex         = existing or {}
        cur_jitter = int(ex.get("jitter", 0))

        mode_choice = d.select(
            addon.getLocalizedString(32340),
            [addon.getLocalizedString(32341) +
             (addon.getLocalizedString(32873) if cur_jitter == 0 else ""),
             addon.getLocalizedString(32342) +
             (addon.getLocalizedString(32873) if cur_jitter > 0 else "")])
        if mode_choice == -1:
            return None
        use_jitter = (mode_choice == 1)

        cur_freq    = str(int(ex.get("frequency", 4)))
        freq_prompt = (addon.getLocalizedString(32342) if use_jitter
                       else addon.getLocalizedString(32341))
        freq_str    = d.input(freq_prompt, cur_freq,
                              type=xbmcgui.INPUT_NUMERIC)
        if freq_str is None or freq_str == "":
            return None
        try:
            frequency = max(1, int(freq_str))
        except ValueError:
            frequency = 4

        jitter = 0
        if use_jitter:
            max_jitter  = frequency - 1
            cur_jit_str = str(min(cur_jitter, max_jitter)
                              if cur_jitter else min(2, max_jitter))
            jit_str = d.input(addon.getLocalizedString(32344), cur_jit_str,
                              type=xbmcgui.INPUT_NUMERIC)
            if jit_str is None or jit_str == "":
                return None
            try:
                jitter = max(0, min(max_jitter, int(jit_str)))
            except ValueError:
                jitter = min(2, max_jitter)

        cur_count = int(ex.get("count_per", 1))
        src_channel_id = ex.get("channel_id", "")
        src_ch         = manager.get_channel(src_channel_id) \
                         if src_channel_id else None
        is_combo_src   = src_ch and src_ch.get("channel_type") == "combo"

        # The numeric pad shows a single heading line only, so a Combo
        # Block gets its own one-line heading instead of an extra line.
        count_str = d.input(
            addon.getLocalizedString(32870 if is_combo_src else 32343),
            defaultt=str(cur_count),
            type=xbmcgui.INPUT_NUMERIC)
        if count_str is None or count_str == "":
            return None
        try:
            count_per = max(1, int(count_str))
        except (ValueError, TypeError):
            count_per = cur_count

        if is_combo_src:
            silent_value = False
        else:
            cur_silent    = bool(ex.get("silent", False))
            silent_choice = d.select(
                addon.getLocalizedString(32545),
                [addon.getLocalizedString(32554) +
                 (addon.getLocalizedString(32873) if not cur_silent else ""),
                 addon.getLocalizedString(32553) +
                 (addon.getLocalizedString(32873) if cur_silent else "")])
            if silent_choice == -1:
                return None
            silent_value = (silent_choice == 1)

        return {"frequency": frequency, "jitter": jitter,
                "count_per": count_per, "silent": silent_value}

    # Main loop
    while True:
        sources = get_sources(channel)

        rows = [addon.getLocalizedString(32547)]   # Add Source
        if sources:
            rows.append(addon.getLocalizedString(32560))  # Edit/Remove Sources
        rows += [addon.getLocalizedString(32548),   # Remove All
                 addon.getLocalizedString(32491)]   # Done

        choice = d.select(addon.getLocalizedString(32545), rows)
        if choice == -1:
            return

        add_idx        = 0
        edit_idx       = 1 if sources else None
        remove_all_idx = 2 if sources else 1
        done_idx       = 3 if sources else 2

        if choice == done_idx:
            return

        if choice == remove_all_idx:
            if not d.yesno(addon.getLocalizedString(32000),
                           addon.getLocalizedString(32549)):
                continue
            removed_ids = []
            for src in (sources or []):
                src_ch = manager.get_channel(src["channel_id"])
                if src_ch and src_ch.get("channel_type") == "combo":
                    manager.clear_combo_owner(src["channel_id"])
                elif src_ch:
                    removed_ids.append(src["channel_id"])
            channel["interleave"] = None
            manager.save_channel_list()
            manager.regenerate_queue(channel_id)
            # Offer to reset the removed sources (same as Reset Channel).
            if removed_ids and d.yesno(addon.getLocalizedString(32000),
                                       addon.getLocalizedString(32917)):
                for rid in removed_ids:
                    manager.reset_channel(rid)
            d.notification(addon.getLocalizedString(32000),
                           addon.getLocalizedString(32550),
                           xbmcgui.NOTIFICATION_INFO, 2000)
            xbmc.sleep(300)
            xbmc.executebuiltin("Container.Refresh")
            return

        if edit_idx is not None and choice == edit_idx:
            def _source_label(s):
                ch     = manager.get_channel(s["channel_id"]) or {}
                name   = ch.get("name", s["channel_id"][:8])
                badge  = " {}".format(addon.getLocalizedString(32555)) \
                         if s.get("silent") else ""
                freq   = s["frequency"]
                jit    = s["jitter"]
                detail = ("every {}-{}".format(max(1, freq - jit), freq + jit)
                          if jit else "every {}".format(freq))
                if s["count_per"] > 1:
                    detail += " x{}".format(s["count_per"])
                return "{}{} — {}".format(name, badge, detail)

            src_choice = d.select(
                addon.getLocalizedString(32560),
                [_source_label(s) for s in sources])
            if src_choice == -1:
                continue
            src      = sources[src_choice]
            src_ch   = manager.get_channel(src["channel_id"]) or {}
            src_name = src_ch.get("name", src["channel_id"][:8])
            action   = d.select(
                addon.getLocalizedString(32551).format(src_name),
                [addon.getLocalizedString(32341)
                 if src["jitter"] == 0
                 else addon.getLocalizedString(32342),
                 addon.getLocalizedString(32552)])
            if action == -1:
                continue
            if action == 1:
                if src_ch.get("channel_type") == "combo":
                    manager.clear_combo_owner(src["channel_id"])
                new_sources       = [s for s in sources
                                     if s["channel_id"] != src["channel_id"]]
                channel["interleave"] = new_sources if new_sources else None
                manager.save_channel_list()
                manager.regenerate_queue(channel_id)
                # Offer to reset the removed source (same as Reset Channel).
                if (src_ch and src_ch.get("channel_type") != "combo"
                        and d.yesno(
                            addon.getLocalizedString(32000),
                            addon.getLocalizedString(32916).format(
                                src_name))):
                    manager.reset_channel(src["channel_id"])
                d.notification(addon.getLocalizedString(32000),
                               addon.getLocalizedString(32550),
                               xbmcgui.NOTIFICATION_INFO, 2000)
                continue
            result = _source_input_dialog(existing=src)
            if result is None:
                continue
            result["channel_id"] = src["channel_id"]
            new_sources = [
                result if s["channel_id"] == src["channel_id"] else s
                for s in sources
            ]
            channel["interleave"] = new_sources
            manager.save_channel_list()
            manager.regenerate_queue(channel_id)
            d.notification(addon.getLocalizedString(32000),
                           addon.getLocalizedString(32557),
                           xbmcgui.NOTIFICATION_INFO, 2000)
            continue

        if choice == add_idx:
            existing_ids = {s["channel_id"] for s in sources}
            eligible     = [c for c in other
                            if c["id"] not in existing_ids
                            and not _would_be_circular(c["id"], channel_id)
                            and not manager.get_interleave_source_owner(
                                c["id"], exclude_channel_id=channel_id)]
            combo_eligible = [c for c in combo_sources
                              if c["id"] not in existing_ids
                              and (
                                  # Include unowned combos
                                  not manager.get_combo_owner(c["id"])
                                  # Include combos already owned by THIS channel
                                  or (manager.get_combo_owner(c["id"]) or {})
                                     .get("channel_id") == channel_id
                              )]

            if not eligible and not combo_eligible:
                d.ok(addon.getLocalizedString(32000),
                     addon.getLocalizedString(32330))
                continue

            group1 = sorted([c for c in eligible if not get_sources(c)],
                            key=lambda c: c["name"])
            group2 = sorted([c for c in eligible if get_sources(c)],
                            key=lambda c: c["name"])
            group3 = sorted(combo_eligible, key=lambda c: c["name"])

            picker_rows     = [c["name"] for c in group1]
            picker_channels = list(group1)
            sep1_idx        = None
            sep2_idx        = None

            if group2:
                sep1_idx         = len(picker_rows)
                picker_rows.append(addon.getLocalizedString(32561))
                picker_rows     += [c["name"] for c in group2]
                picker_channels += [None] + list(group2)

            if group3:
                sep2_idx = len(picker_rows)
                picker_rows.append(
                    "── {} ──".format(addon.getLocalizedString(32866)))
                for cb in group3:
                    slot_types = "+".join(
                        s.get("source_type", "?").upper()
                        for s in cb.get("slots", []))
                    picker_rows.append("{}  ({})".format(
                        cb["name"], slot_types if slot_types else "?"))
                picker_channels += [None] + list(group3)

            if sources:
                cur_names    = []
                for s in sources:
                    sc = manager.get_channel(s["channel_id"]) or {}
                    cur_names.append(sc.get("name", s["channel_id"][:8]))
                picker_title = "{} ({}:{})".format(
                    addon.getLocalizedString(32545),
                    addon.getLocalizedString(32545),
                    ", ".join(cur_names))
            else:
                picker_title = addon.getLocalizedString(32545)

            pick = d.select(picker_title, picker_rows)
            if pick == -1:
                continue
            if sep1_idx is not None and pick == sep1_idx:
                continue
            if sep2_idx is not None and pick == sep2_idx:
                continue
            src_ch = picker_channels[pick]
            if src_ch is None:
                continue

            result = _source_input_dialog(
                existing={"channel_id": src_ch["id"]})
            if result is None:
                continue

            result["channel_id"] = src_ch["id"]
            new_sources         = list(sources) + [result]
            channel["interleave"] = new_sources
            manager.save_channel_list()

            if src_ch.get("channel_type") == "combo":
                tgt_ch = manager.get_channel(channel_id)
                manager.set_combo_owner(
                    src_ch["id"], channel_id,
                    tgt_ch.get("name", channel_id) if tgt_ch else channel_id,
                    "interleave")

            manager.regenerate_queue(channel_id)
            d.notification(addon.getLocalizedString(32000),
                           addon.getLocalizedString(32557),
                           xbmcgui.NOTIFICATION_INFO, 2000)
            continue
