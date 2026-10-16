# plugin.video.smartchannels
# resources/lib/ui/channels.py
#
# OWNS:   Channel list UI, context menu building, create/edit dispatch,
#         channel_info dialog, view_exclusions, view_missing_durations.
#         Delegates all wizard logic to resources/lib/ui/wizards/.
#
# NEVER:  Queue building, state reads/writes, executeJSONRPC calls,
#         private method calls on other classes.
#
# All user-visible strings via addon.getLocalizedString().
# Ported from 2.x ui/channels.py — wizard logic split into wizards/.
#
# spec §6, §14, §15, Version: 3.0.0 Phase 5

from __future__ import annotations

import time

import xbmc
import xbmcgui

from resources.lib.channels.audio import resolve_audio_mode
from resources.lib.channels.interleave import tv_slot_takes_turns, tv_turn_size
from resources.lib.ui.dialogs import describe_filters
from resources.lib.utils.logger import log


# ---------------------------------------------------------------------------
# Toast helper
# ---------------------------------------------------------------------------

def _notify(addon, message: str, duration_ms: int = 3000) -> None:
    """Non-blocking toast notification."""
    xbmc.executebuiltin("Notification({},{},{},)".format(
        addon.getLocalizedString(32000), message, duration_ms))


# ---------------------------------------------------------------------------
# Channel creation / edit entry points
# ---------------------------------------------------------------------------

def run_create_wizard(addon, manager) -> bool:
    """Run channel creation wizard.
    Step order: Type → Playback mode (TV) → Name → type-specific steps.
    Returns True if channel was created.
    """
    d = xbmcgui.Dialog()

    # Step 1: Channel type
    type_labels = [
        addon.getLocalizedString(32440),   # TV Shows
        addon.getLocalizedString(32441),   # Movies
        addon.getLocalizedString(32531),   # Folder
        addon.getLocalizedString(32800),   # Audio Channel
        addon.getLocalizedString(32833),   # Party Mode
        addon.getLocalizedString(32866),   # Combo Block
    ]
    type_choice = d.select(
        addon.getLocalizedString(32300).format(""),
        type_labels)
    if type_choice < 0:
        return False

    channel_type  = ["tv", "movies", "folder", "audio", "party", "combo"][type_choice]
    playback_mode = "round_robin"

    # For TV: ask Round Robin or Serial
    if channel_type == "tv":
        mode_choice = d.select(
            addon.getLocalizedString(32214),
            [addon.getLocalizedString(32216),    # Round Robin
             addon.getLocalizedString(32303)])   # Serial
        if mode_choice < 0:
            return False
        if mode_choice == 1:
            playback_mode = "serial"

    # Step 2: Name
    name = _ask_channel_name(addon, manager)
    if name is None:
        return False

    defn = _run_typed_wizard(addon, manager, channel_type, playback_mode,
                             name, existing=None)
    if defn is None:
        return False

    xbmc.executebuiltin("ActivateWindow(busydialognocancel)")
    try:
        channel = manager.create_channel(defn)
    finally:
        xbmc.executebuiltin("Dialog.Close(busydialognocancel)")

    _notify(addon, addon.getLocalizedString(32437).format(
        defn.get("name", "")))
    log("[ui/channels] Created channel '{}' id={}".format(
        defn.get("name"), channel.get("id")))
    return True


def _ask_channel_name(addon, manager, default: str = "",
                      exclude_id: str = ""):
    """Ask for a channel name and re-ask while another channel has it.

    Returns the name, or None if the user cancels.  An empty entry is an
    error when creating (default empty) and keeps the current name when
    editing.  exclude_id is the channel being edited.
    """
    d = xbmcgui.Dialog()
    entered = default
    while True:
        entered = d.input(addon.getLocalizedString(32213),
                          defaultt=entered,
                          type=xbmcgui.INPUT_ALPHANUM)
        if entered is None:
            return None
        name = entered.strip()
        if not name:
            if default:
                return default
            d.ok(addon.getLocalizedString(32000),
                 addon.getLocalizedString(32209))
            return None
        if manager.channel_name_exists(name, exclude_id):
            d.ok(addon.getLocalizedString(32000),
                 addon.getLocalizedString(32932).format(name))
            entered = name
            continue
        return name


def run_edit_wizard(addon, manager, channel_id: str) -> bool:
    """Run edit wizard for an existing channel. Returns True if updated."""
    channel = manager.get_channel(channel_id)
    if not channel:
        return False

    d             = xbmcgui.Dialog()
    channel_type  = channel.get("channel_type", "tv")
    playback_mode = channel.get("playback_mode", "round_robin")
    old_randomize = channel.get("randomize", False)

    # Name step (pre-filled, user can rename)
    name = _ask_channel_name(addon, manager, channel.get("name", ""),
                             exclude_id=channel_id)
    if name is None:
        return False

    defn = _run_typed_wizard(addon, manager, channel_type, playback_mode,
                             name, existing=channel)
    if defn is None:
        return False

    # Invalidate resume if key settings changed
    resume_invalidated = (
        old_randomize != defn.get("randomize", False))
    if resume_invalidated:
        d.ok(addon.getLocalizedString(32000),
             addon.getLocalizedString(32436).format(channel.get("name", "")))
        manager.clear_channel_resume_points(channel_id)

    xbmc.executebuiltin("ActivateWindow(busydialognocancel)")
    try:
        manager.update_channel(channel_id, defn)
    finally:
        xbmc.executebuiltin("Dialog.Close(busydialognocancel)")

    _notify(addon, addon.getLocalizedString(32439).format(defn.get("name", "")))
    return True


def _run_typed_wizard(addon, manager, channel_type: str, playback_mode: str,
                      name: str, existing: dict | None) -> dict | None:
    """Dispatch to the correct wizard module."""
    if channel_type == "tv" and playback_mode == "serial":
        from resources.lib.ui.wizards.serial import run
        return run(addon, manager, name, existing)
    elif channel_type == "tv":
        from resources.lib.ui.wizards.tv import run
        return run(addon, manager, name, existing)
    elif channel_type == "movies":
        from resources.lib.ui.wizards.movie import run
        return run(addon, manager, name, existing)
    elif channel_type == "folder":
        from resources.lib.ui.wizards.folder import run
        return run(addon, manager, name, existing)
    elif channel_type == "audio":
        from resources.lib.ui.wizards.audio import run
        return run(addon, manager, name, existing)
    elif channel_type == "party":
        from resources.lib.ui.wizards.party import run
        return run(addon, manager, name, existing)
    elif channel_type == "combo":
        from resources.lib.ui.wizards.combo import run
        return run(addon, manager, name, existing)
    return None


# ---------------------------------------------------------------------------
# Channel info dialog  (spec §15)
# ---------------------------------------------------------------------------

def show_channel_info(addon, manager, channel_id: str) -> None:
    """Show channel info textviewer. Ported from 2.x channel_info."""
    ch = manager.get_channel(channel_id)
    if not ch:
        return

    channel_type = ch.get("channel_type", "tv")
    randomize    = ch.get("randomize", False)
    recycle      = ch.get("recycle",   True)
    shows        = ch.get("shows",     [])
    movies       = ch.get("movies",    [])
    lines        = []

    if channel_type == "combo":
        _combo_info_lines(addon, manager, ch, channel_id, lines)
        xbmcgui.Dialog().ok(ch.get("name", ""), "\n".join(lines))
        return

    if channel_type == "movies":
        _movie_info_lines(addon, ch, randomize, recycle, movies, lines)
    elif channel_type == "serial":
        _serial_info_lines(addon, ch, recycle, shows, lines)
    elif channel_type == "folder":
        _folder_info_lines(addon, ch, randomize, recycle, lines)
    elif channel_type == "audio":
        _audio_info_lines(addon, ch, lines)
    elif channel_type == "party":
        _party_info_lines(addon, ch, lines)
    else:
        _tv_info_lines(addon, ch, randomize, recycle, shows, lines)

    # Interleave section
    _interleave_info_lines(addon, manager, ch, channel_id, lines)

    # Carousel section
    _carousel_info_lines(addon, manager, ch, channel_id, lines)

    # Schedules section
    _schedule_info_lines(addon, manager, ch, channel_id, lines)

    xbmcgui.Dialog().textviewer(
        addon.getLocalizedString(32433).format(ch["name"]),
        "\n".join(lines))


def _tv_info_lines(addon, ch, randomize, recycle, shows, lines):
    rotation = (addon.getLocalizedString(32217) if randomize
                else addon.getLocalizedString(32216))
    lines.append(addon.getLocalizedString(32422))
    lines.append(addon.getLocalizedString(32423).format(rotation))
    lines.append("")
    if shows:
        lines.append(addon.getLocalizedString(32427).format(len(shows)))
        for i, show in enumerate(shows):
            excl_count = len(show.get("excluded_episodes", []))
            eps        = show.get("episodes_per_slot", 1)
            rand_s     = show.get("randomize", False)
            notes      = []
            if eps > 1:
                notes.append("{} eps/slot".format(eps))
            if rand_s:
                notes.append(addon.getLocalizedString(32217))
            if excl_count:
                notes.append("{} excl".format(excl_count))
            note_str = "  ({})".format(", ".join(notes)) if notes else ""
            lines.append("  {}. {}{}".format(
                i + 1, show.get("title", ""), note_str))


def _serial_info_lines(addon, ch, recycle, shows, lines):
    lines.append(addon.getLocalizedString(32421))
    lines.append("")
    if shows:
        lines.append(addon.getLocalizedString(32426).format(len(shows)))
        for i, show in enumerate(shows):
            lines.append("  {}. {}".format(i + 1, show.get("title", "")))


def _movie_info_lines(addon, ch, randomize, recycle, movies, lines):
    rotation = (addon.getLocalizedString(32217) if randomize
                else addon.getLocalizedString(32464))
    lines.append(addon.getLocalizedString(32420))
    lines.append(addon.getLocalizedString(32423).format(rotation))
    for text in describe_filters(addon, ch.get("filters", [])):
        lines.append("  " + text)
    lines.append(addon.getLocalizedString(32425).format(len(movies)))
    excl = ch.get("excluded_movies", [])
    if excl:
        lines.append(addon.getLocalizedString(32619).format(len(excl)))


def _folder_info_lines(addon, ch, randomize, recycle, lines):
    rotation = (addon.getLocalizedString(32217) if randomize
                else addon.getLocalizedString(32285))
    lines.append(addon.getLocalizedString(32536))
    lines.append(addon.getLocalizedString(32537).format(
        ch.get("folder_path", "").replace("%20", " ")))
    lines.append(addon.getLocalizedString(32423).format(rotation))


def _audio_info_lines(addon, ch, lines):
    order, balanced, album_shuffle = resolve_audio_mode(ch)
    audio_filters = ch.get("audio_filters", [])
    incl_albums   = ch.get("included_albums", {})
    if order == "album":
        order_text = addon.getLocalizedString(
            32854 if album_shuffle else 32806)
    else:
        order_text = addon.getLocalizedString(
            32825 if balanced else 32934)
    lines.append(addon.getLocalizedString(32800))
    lines.append(addon.getLocalizedString(32522).format(order_text))
    artists = [f["value"] for f in audio_filters
               if f.get("type") == "artist"]
    if artists:
        lines.append("")
        lines.append(addon.getLocalizedString(32523).format(
            ", ".join(artists)))
        for artist in artists:
            albums = incl_albums.get(artist, [])
            if albums:
                lines.append("  {}: {}".format(artist, ", ".join(albums[:5])))
                if len(albums) > 5:
                    lines[-1] += " +{}".format(len(albums) - 5)
    elif audio_filters:
        lines.append(addon.getLocalizedString(32810))
    else:
        lines.append(addon.getLocalizedString(32809))


def _party_info_lines(addon, ch, lines):
    order_map = {
        "random":    addon.getLocalizedString(32217),
        "no_repeat": addon.getLocalizedString(32855),
    }
    lines.append(addon.getLocalizedString(32801))
    lines.append(ch.get("folder_path", "").replace("%20", " "))
    lines.append(order_map.get(ch.get("audio_order", "random"), ""))


def _combo_info_lines(addon, manager, ch, channel_id, lines):
    slots = ch.get("slots", [])
    if not slots:
        lines.append(addon.getLocalizedString(32888))
    else:
        lines.append("{} — {} ({} {})".format(
            ch["name"], addon.getLocalizedString(32866),
            len(slots), addon.getLocalizedString(32871)))
        lines.append("")
        for i, sl in enumerate(slots):
            src = sl.get("source_type", "?")
            lines.append(addon.getLocalizedString(32903).format(i + 1, src.upper()))
            if src == "tv":
                sl_shows = sl.get("shows")
                if not sl_shows and sl.get("tvshowid"):
                    sl_shows = [{"title":     sl.get("title", "?"),
                                 "randomize": sl.get("randomize", True),
                                 "recycle":   sl.get("recycle",   True),
                                 "silent":    sl.get("silent",    False),
                                 "excluded_episodes": sl.get("excluded_episodes", [])}]
                for sh in (sl_shows or []):
                    rand_s = (addon.getLocalizedString(32217)
                              if sh.get("randomize", True)
                              else addon.getLocalizedString(32285))
                    rec_s  = (addon.getLocalizedString(32683)
                              if sh.get("recycle", True)
                              else addon.getLocalizedString(32684))
                    sil_s  = (addon.getLocalizedString(32885)
                              if sh.get("silent", False)
                              else addon.getLocalizedString(32886))
                    excl_n = len(sh.get("excluded_episodes", []))
                    excl_s = (addon.getLocalizedString(32617).format(excl_n)
                              if excl_n else addon.getLocalizedString(32591))
                    lines.append("  {} — {} — {} — {} — {}".format(
                        sh.get("title", "?"), rand_s, rec_s, sil_s, excl_s))
                if tv_slot_takes_turns(sl):
                    lines.append("  " + addon.getLocalizedString(32945)
                                 .format(tv_turn_size(sl)))
            elif src == "movies":
                flist = sl.get("filters", [])
                fstr  = (", ".join(describe_filters(addon, flist)) if flist
                         else addon.getLocalizedString(32441))
                rand_s = (addon.getLocalizedString(32217)
                          if sl.get("randomize", True)
                          else addon.getLocalizedString(32285))
                rec_s  = (addon.getLocalizedString(32683)
                          if sl.get("recycle", True)
                          else addon.getLocalizedString(32684))
                sil_s  = (addon.getLocalizedString(32885)
                          if sl.get("silent", False)
                          else addon.getLocalizedString(32886))
                lines.append("  {} — {} — {} — {}".format(
                    fstr, rand_s, rec_s, sil_s))
            else:
                fp    = sl.get("folder_path", "")
                fname = (fp.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] if fp else "?")
                rand_s = (addon.getLocalizedString(32217)
                          if sl.get("randomize", True)
                          else addon.getLocalizedString(32285))
                rec_s  = (addon.getLocalizedString(32683)
                          if sl.get("recycle", True)
                          else addon.getLocalizedString(32684))
                sil_s  = (addon.getLocalizedString(32885)
                          if sl.get("silent", False)
                          else addon.getLocalizedString(32886))
                lines.append("  {} — {} — {} — {}".format(
                    fname, rand_s, rec_s, sil_s))

    lines.append("")
    try:
        q     = manager.get_channel_queue(channel_id)
        n_sl  = max(1, len(slots))
        units = len(q) // n_sl
        lines.append(addon.getLocalizedString(32889).format(len(q), units))
    except Exception:
        pass

    owner = manager.get_combo_owner(channel_id)
    lines.append("")
    if owner:
        lines.append(addon.getLocalizedString(32881).format(
            owner.get("channel_name", "?"), owner.get("relationship", "?")))
    else:
        lines.append(addon.getLocalizedString(32882))


def _interleave_info_lines(addon, manager, ch, channel_id, lines):
    try:
        from resources.lib.channels.interleave import get_sources
        sources = get_sources(ch)
        if sources:
            lines.append("")
            lines.append(addon.getLocalizedString(32545))
            for src in sources:
                foreign = manager.get_channel(src["channel_id"])
                if foreign:
                    freq  = src["frequency"]
                    jit   = src["jitter"]
                    count = src["count_per"]
                    sil   = src["silent"]
                    jit_str = " +/-{}".format(jit) if jit else ""
                    sil_str = " [silent]" if sil else ""
                    lines.append(addon.getLocalizedString(32431).format(
                        foreign["name"], freq, jit_str,
                        ", {} per slot".format(count) if count > 1 else "")
                        + sil_str)
                else:
                    lines.append(addon.getLocalizedString(32432))
    except Exception:
        pass


def _carousel_info_lines(addon, manager, ch, channel_id, lines):
    if not ch.get("carousel_enabled", False):
        return
    lines.append("")
    car_mode = ch.get("carousel_mode", "timed")
    if car_mode == "duration":
        lines.append(addon.getLocalizedString(32864))
    else:
        interval  = int(ch.get("carousel_interval",  60))
        pop_count = int(ch.get("carousel_pop_count",  1))
        lines.append(addon.getLocalizedString(32612).format(interval, pop_count)
                     if pop_count == 1
                     else addon.getLocalizedString(32612).format(
                         interval, pop_count))
    try:
        car_state  = manager.get_carousel_state(channel_id)
        last_pop   = car_state.get("last_pop_time")
        if last_pop is None:
            lines.append(addon.getLocalizedString(32616))
        else:
            elapsed_s = time.time() - last_pop
            if car_mode == "duration":
                # Duration mode: pop interval = front item's duration.
                # Read it from the queue so the display is accurate.
                target_s = 0
                try:
                    queue = manager.get_channel_queue(channel_id)
                    for item in (queue or []):
                        d = item.get("duration", 0) or 0
                        if d > 0:
                            target_s = int(d)
                            break
                except Exception:
                    pass
                if target_s <= 0:
                    lines.append(addon.getLocalizedString(32864))
                else:
                    remaining = target_s - elapsed_s
                    if remaining <= 0:
                        lines.append(addon.getLocalizedString(32615))
                    else:
                        lines.append(addon.getLocalizedString(32614).format(
                            int(remaining // 60) + 1))
            else:
                interval  = int(ch.get("carousel_interval", 60))
                remaining = (interval * 60) - elapsed_s
                if remaining <= 0:
                    lines.append(addon.getLocalizedString(32615))
                else:
                    lines.append(addon.getLocalizedString(32614).format(
                        int(remaining // 60) + 1))
    except Exception:
        lines.append(addon.getLocalizedString(32616))


def _schedule_info_lines(addon, manager, ch, channel_id, lines):
    try:
        all_sch = manager.get_all_schedules()
        day_labels = {
            "monday": addon.getLocalizedString(32761),
            "tuesday": addon.getLocalizedString(32762),
            "wednesday": addon.getLocalizedString(32763),
            "thursday": addon.getLocalizedString(32764),
            "friday": addon.getLocalizedString(32765),
            "saturday": addon.getLocalizedString(32766),
            "sunday": addon.getLocalizedString(32767),
            "weekdays": addon.getLocalizedString(32768),
            "weekends": addon.getLocalizedString(32769),
            "daily": addon.getLocalizedString(32744),
            "once":  addon.getLocalizedString(32747),
        }
        target_entries = []
        source_entries = []
        for sch_id, sch in all_sch.items():
            tgt      = sch.get("target_channel", "")
            src      = sch.get("source_channel", "")
            sch_name = sch.get("name", sch_id)
            day_str  = sch.get("day", "").lower()
            time_str = sch.get("time", "")
            count    = int(sch.get("item_count", 0))
            active   = sch.get("active", False)
            day_lbl  = day_labels.get(day_str, day_str.capitalize())
            try:
                h, m   = (int(x) for x in time_str.split(":"))
                ampm   = "AM" if h < 12 else "PM"
                h12    = h % 12 or 12
                tlabel = "{:d}:{:02d} {}".format(h12, m, ampm)
            except Exception:
                tlabel = time_str
            day_time = "{} {}".format(day_lbl, tlabel)
            inact    = ("" if active
                        else " {}".format(addon.getLocalizedString(32847)))

            if tgt == channel_id:
                src_ch   = manager.get_channel(src)
                src_name = src_ch.get("name", src) if src_ch else src
                target_entries.append(
                    addon.getLocalizedString(32845).format(
                        sch_name, count, src_name, day_time) + inact)
            if src == channel_id:
                tgt_ch   = manager.get_channel(tgt)
                tgt_name = tgt_ch.get("name", tgt) if tgt_ch else tgt
                source_entries.append(
                    addon.getLocalizedString(32846).format(
                        sch_name, count, tgt_name, day_time) + inact)

        if target_entries or source_entries:
            lines.append("")
            lines.append(addon.getLocalizedString(32755))
            for e in target_entries + source_entries:
                lines.append(e)
    except Exception as e:
        log("[channels] schedule info error: {}".format(e))


# ---------------------------------------------------------------------------
# View exclusions / missing durations
# ---------------------------------------------------------------------------

def view_exclusions(addon, manager, channel_id: str) -> None:
    """Show excluded episodes or movies for a channel."""
    ch           = manager.get_channel(channel_id)
    if not ch:
        return
    channel_type = ch.get("channel_type", "tv")
    lines        = []

    if channel_type in ("tv", "serial"):
        for show in ch.get("shows", []):
            excl_ids = show.get("excluded_episodes", [])
            if not excl_ids:
                continue
            lines.append(show.get("title", ""))
            try:
                all_eps = manager.get_filtered_episodes(show)
                id_map  = {e["episodeid"]: e for e in all_eps}
                for eid in excl_ids:
                    ep = id_map.get(eid)
                    if ep:
                        lines.append("  " + addon.getLocalizedString(32693).format(
                            ep.get("season", 0),
                            ep.get("episode", 0),
                            ep.get("title", "")))
                    else:
                        lines.append(addon.getLocalizedString(32591).format(eid))
            except Exception:
                lines.append(addon.getLocalizedString(32617).format(len(excl_ids)))
    elif channel_type == "movies":
        excl = ch.get("excluded_movies", [])
        movies = ch.get("movies", [])
        movie_map = {m["movieid"]: m.get("title", str(m["movieid"]))
                     for m in movies}
        for mid in excl:
            lines.append("  {}".format(movie_map.get(mid, str(mid))))

    if lines:
        xbmcgui.Dialog().textviewer(
            addon.getLocalizedString(32609),
            "\n".join(lines))
    else:
        xbmcgui.Dialog().ok(
            addon.getLocalizedString(32000),
            addon.getLocalizedString(32611))


def view_missing_durations(addon, manager, channel_id: str) -> None:
    """Show missing durations log for a channel."""
    missing = manager.get_missing_durations(channel_id)
    if not missing:
        xbmcgui.Dialog().ok(
            addon.getLocalizedString(32000),
            addon.getLocalizedString(32714))
        return

    lines = []
    for entry in missing:
        head = " — ".join(filter(None, [
            entry.get("show", ""), entry.get("episode", ""),
            entry.get("title", "")])) or entry.get("file", "")
        path = entry.get("file", "")
        lines.append(head)
        if path:
            lines.append("  {}".format(path))

    xbmcgui.Dialog().textviewer(
        addon.getLocalizedString(32710).format(len(missing)),
        "\n".join(lines))


# ---------------------------------------------------------------------------
# Confirm helpers (used by router)
# ---------------------------------------------------------------------------

def confirm_delete(addon, channel_name: str) -> bool:
    return xbmcgui.Dialog().yesno(
        addon.getLocalizedString(32000),
        addon.getLocalizedString(32211))


def confirm_reset(addon, channel_name: str) -> bool:
    return xbmcgui.Dialog().yesno(
        addon.getLocalizedString(32350),
        addon.getLocalizedString(32351).format(channel_name))
