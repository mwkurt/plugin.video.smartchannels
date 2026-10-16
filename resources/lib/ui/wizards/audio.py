# plugin.video.smartchannels
# resources/lib/ui/wizards/audio.py
#
# OWNS:   Audio channel wizard.
#         ENH-AUD.01: album picker nothing pre-selected; Select All button.
# spec §6.5, Version: 3.0.0 Phase 5

from __future__ import annotations

import xbmcgui

from resources.lib.ui.dialogs import (
    pick_list_order, build_filters, build_audio_song_exclusions,
    ask_queue_size)


def run(addon, manager, name: str, existing: dict | None) -> dict | None:
    """Audio wizard. Returns channel definition dict or None."""
    d = xbmcgui.Dialog()

    # ---- Playback order ------------------------------------------------------
    order_choice = d.select(
        addon.getLocalizedString(32214),
        [addon.getLocalizedString(32934),    # Shuffle (no repeats)
         addon.getLocalizedString(32806)])   # Album Order
    if order_choice < 0:
        return None
    audio_order = "no_repeat" if order_choice == 0 else "album"

    # ---- Order refinement: balance artists / shuffle albums -------------------
    if audio_order == "no_repeat":
        audio_balanced      = d.yesno(addon.getLocalizedString(32935),
                                      addon.getLocalizedString(32936))
        audio_album_shuffle = False
    else:
        audio_balanced      = False
        audio_album_shuffle = d.yesno(addon.getLocalizedString(32854),
                                      addon.getLocalizedString(32937))

    # ---- Content mode --------------------------------------------------------
    mode_choice = d.select(
        addon.getLocalizedString(32857),
        [addon.getLocalizedString(32802),    # Filter by Artist
         addon.getLocalizedString(32803),    # Filter by other
         addon.getLocalizedString(32804)])   # No Filter
    if mode_choice < 0:
        return None

    audio_filters   = list(existing.get("audio_filters",  []) if existing else [])
    included_albums = dict(existing.get("included_albums", {}) if existing else {})
    excluded_songs  = list(existing.get("excluded_songs",  []) if existing else [])

    if mode_choice == 0:
        # ---- Artist multiselect ----------------------------------------------
        try:
            artists = manager.library.get_all_artists()
        except Exception:
            artists = []
        if not artists:
            d.ok(addon.getLocalizedString(32000),
                 addon.getLocalizedString(32838))
            return None

        artist_names = [a.get("artist", "") for a in artists]

        # ENH-AUD.01: nothing pre-selected by default
        selected = d.multiselect(
            addon.getLocalizedString(32808),
            artist_names,
            preselect=[])   # nothing pre-selected
        if selected is None:
            return None
        if not selected:
            d.ok(addon.getLocalizedString(32000),
                 addon.getLocalizedString(32839))
            return None
        chosen_artist_names = [artist_names[i] for i in selected]

        # Artist rotation order
        if (audio_balanced or audio_order == "album") and \
                len(chosen_artist_names) > 1:
            chosen_artist_names = pick_list_order(
                addon, d,
                chosen_artist_names,
                addon.getLocalizedString(32850),
                addon.getLocalizedString(32852))

        audio_filters = [
            {"type": "artist", "value": n,
             "operator": "or", "comparison": "contains"}
            for n in chosen_artist_names
        ]

        # ---- Album picker per artist ----------------------------------------
        try:
            albums_by_artist = manager.library.get_albums_for_artists(
                chosen_artist_names)
        except Exception:
            albums_by_artist = {n: [] for n in chosen_artist_names}

        new_included_albums = {}
        for artist in chosen_artist_names:
            all_albums = albums_by_artist.get(artist, [])
            if not all_albums:
                new_included_albums[artist] = []
                continue

            # ENH-AUD.01: nothing pre-selected by default; Select All option
            # We implement Select All by prepending a "Select All" item.
            picker_labels = [addon.getLocalizedString(32856)] + list(all_albums)
            # "Select All" is index 0; real albums start at index 1.
            chosen_alb = d.multiselect(
                addon.getLocalizedString(32826).format(artist),
                picker_labels,
                preselect=[])   # nothing pre-selected

            if chosen_alb is None:
                # Cancelled — keep existing or empty
                new_included_albums[artist] = included_albums.get(artist, [])
            elif not chosen_alb:
                new_included_albums[artist] = []
            elif 0 in chosen_alb:
                # "Select All" chosen — include all albums
                chosen_album_names = list(all_albums)
                new_included_albums[artist] = chosen_album_names
            else:
                # Adjust indices (subtract 1 for the Select All header)
                chosen_album_names = [all_albums[i - 1] for i in chosen_alb
                                      if i > 0 and i - 1 < len(all_albums)]

                if audio_order == "album" and \
                        len(chosen_album_names) > 1:
                    chosen_album_names = pick_list_order(
                        addon, d,
                        chosen_album_names,
                        addon.getLocalizedString(32851).format(artist),
                        addon.getLocalizedString(32853))

                new_included_albums[artist] = chosen_album_names

        included_albums = new_included_albums

        # ---- Song exclusions -------------------------------------------------
        do_excl = d.yesno(
            addon.getLocalizedString(32858),
            addon.getLocalizedString(32828))
        if do_excl:
            excluded_songs = build_audio_song_exclusions(
                addon, manager, chosen_artist_names, included_albums,
                audio_filters, excluded_songs)

    elif mode_choice == 1:
        # Advanced filter builder
        audio_filters   = build_filters(addon, manager, audio_filters, "audio")
        included_albums = {}
        excluded_songs  = []

    else:
        # No filter — full library
        audio_filters   = []
        included_albums = {}
        excluded_songs  = []

    # ---- Queue size ----------------------------------------------------------
    queue_size = ask_queue_size(addon, existing)
    if queue_size is None:
        return None

    # Audio channels always visible, always recycle
    return {
        "name":             name,
        "channel_type":     "audio",
        "audio_filters":    audio_filters,
        "included_albums":  included_albums,
        "excluded_songs":   excluded_songs,
        "audio_order":      audio_order,
        "audio_balanced":      audio_balanced,
        "audio_album_shuffle": audio_album_shuffle,
        "randomize":        (audio_order == "no_repeat"),
        "recycle":          True,
        "queue_size":       queue_size,
        "visible":          True,
        "shows":            [],
        "movies":           [],
        "filters":          [],
        "starting_points":  {},
        "interleave":       existing.get("interleave") if existing else None,
        "carousel_enabled":   False,
        "carousel_mode":      "timed",
        "carousel_interval":  60,
        "carousel_pop_count": 1,
    }
