# plugin.video.smartchannels
# channels/base.py
#
# OWNS:   Shared utilities used by all queue builder modules:
#           normalize_ep()           — strip a raw Kodi episode dict to queue format
#           normalize_movie()        — strip a raw Kodi movie dict to queue format
#           get_filtered_episodes()  — episode pool with filters applied only
#           get_available_episodes() — episode pool with filters + exclusions applied
#           BaseQueueBuilder         — abstract base class for all channel builders
#
# CALLERS: channels/movies.py, channels/folder.py,
#          channels/audio.py, channels/party.py, channels/combo.py
#          (all via inheritance or direct import)
#          channel_manager.py imports get_filtered_episodes and
#          get_available_episodes via public delegation methods only.
#
# NEVER:  State reads/writes, playback control, UI rendering, Kodi API calls.
#         This module must remain importable and testable without a live Kodi
#         environment. The only exception is duration_cache, which is imported
#         at call time inside normalize_ep so tests can stub it out.
#
# Version: 3.0.0

from __future__ import annotations

from resources.lib.utils.logger import log


# ---------------------------------------------------------------------------
# normalize_ep
# ---------------------------------------------------------------------------

def normalize_ep(ep: dict,
                 channel_id: str,
                 show_id,
                 skip_missing_duration: bool = True,
                 all_episodes_for_show: list | None = None) -> dict | None:
    """Strip a raw Kodi episode dict to the minimal queue-item format.

    Reads duration from the companion NFO / duration cache and stores it on
    the item.  Returns ``None`` when the duration is zero and
    ``skip_missing_duration`` is True — the caller must log the miss and skip
    the item.

    For TV episodes, embeds ``_span`` (int) and ``_span_ids`` (list[int]) so
    service.py can advance the cursor correctly for multi-episode files.

    ``all_episodes_for_show`` is the full available-episode list for the show;
    used only by ``span_episode_ids`` for ID resolution.  May be ``None`` for
    movie items or when span ID resolution is not needed.

    Queue item fields written — see spec §4.2 for full table:
        channel_id, _channel_id, show_id, _show_id,
        episodeid, tvshowtitle, title, season, episode,
        file, duration, _span, _span_ids
    """
    # Deferred imports so the module stays testable without Kodi.
    from resources.lib.utils.duration_cache import get_duration as _get_dur
    from resources.lib.utils.multi_episode import (
        count_episode_span as _count_span,
        span_episode_ids   as _span_ids_fn,
    )

    cid = ep.get("_channel_id") or ep.get("channel_id", channel_id)
    sid = ep.get("_show_id")    or ep.get("show_id",    show_id)

    duration = _get_dur(ep)
    if skip_missing_duration and duration <= 0:
        return None  # caller must call record_missing_duration and skip

    span     = _count_span(ep)
    span_ids = _span_ids_fn(ep, all_episodes_for_show or [])

    return {
        "channel_id":  cid,
        "_channel_id": cid,
        "show_id":     sid,
        "_show_id":    sid,
        "episodeid":   ep.get("episodeid", -1),
        "tvshowtitle": ep.get("showtitle", ep.get("tvshowtitle", "")),
        "title":       ep.get("title",   ""),
        "season":      ep.get("season",  0),
        "episode":     ep.get("episode", 0),
        "file":        ep.get("file",    ""),
        "duration":    duration,
        "_span":       span,
        "_span_ids":   span_ids,
    }


# ---------------------------------------------------------------------------
# normalize_movie
# ---------------------------------------------------------------------------

def normalize_movie(movie: dict,
                    channel_id: str,
                    library=None) -> dict:
    """Strip a raw Kodi movie dict to the standard queue-item format.

    Includes metadata needed for playlist display (year, genre, plot, rating,
    mpaa).  When these fields are absent from the raw dict (old library cache),
    they are filled from ``library`` if provided.

    Queue item fields written — see spec §4.2 for full table:
        channel_id, _channel_id, show_id, _show_id,
        movieid, episodeid, title, season, episode,
        file, is_movie, year, genre, plot, rating, mpaa, duration
    """
    movie_id = movie.get("movieid", -1)
    genre    = movie.get("genre",   [])
    year     = movie.get("year",    0)
    plot     = movie.get("plot",    "") or ""
    rating   = movie.get("rating",  0)
    mpaa     = movie.get("mpaa",    "") or ""
    runtime  = movie.get("runtime", 0)

    # Backfill from local cache when fields are missing (stale cache entries).
    if movie_id > 0 and not year and not plot and library:
        try:
            cached = library.load_local_cache()
            if cached:
                m = next(
                    (x for x in cached.get("movies", [])
                     if x.get("movieid") == movie_id),
                    None,
                )
                if m:
                    year    = m.get("year",    0)
                    plot    = (m.get("plot",   "") or "")[:300]
                    genre   = m.get("genre",   genre)
                    rating  = m.get("rating",  rating)
                    mpaa    = (m.get("mpaa",   mpaa) or "")
                    runtime = m.get("runtime", runtime)
        except Exception as exc:
            log("[channels/base] normalize_movie cache lookup error: {}".format(exc))

    if isinstance(genre, list):
        genre_str = ", ".join(genre)
    else:
        genre_str = str(genre) if genre else ""

    return {
        "channel_id":  channel_id,
        "_channel_id": channel_id,
        "show_id":     0,
        "_show_id":    0,
        "movieid":     movie_id,
        "episodeid":   -1,
        "title":       movie.get("title", ""),
        "season":      0,
        "episode":     0,
        "file":        movie.get("file",  ""),
        "is_movie":    True,
        "year":        int(year   or 0),
        "genre":       genre_str,
        "plot":        plot[:300] if plot else "",
        "rating":      float(rating or 0),
        "mpaa":        mpaa,
        "duration":    int(runtime or 0),
    }


# ---------------------------------------------------------------------------
# Episode pool helpers
# ---------------------------------------------------------------------------

def get_filtered_episodes(show_entry: dict, library) -> list:
    """Return a show's episode pool with ``episode_filters`` applied only.

    Does NOT remove ``excluded_episodes``.  This is the pool the exclusion
    picker UI shows the user — what is eligible to exclude — not what will
    actually play.  Use ``get_available_episodes`` for queue building.

    Args:
        show_entry: a show dict from ``channel["shows"]``.  Must contain
                    ``"tvshowid"`` and may contain ``"episode_filters"``.
        library:    the LibraryClient instance.
    """
    sid        = show_entry["tvshowid"]
    ep_filters = show_entry.get("episode_filters", [])
    if ep_filters:
        return library.get_episodes_with_filters(sid, ep_filters)
    return library.get_episodes_for_show(sid)


def get_available_episodes(show_entry: dict, library) -> list:
    """Return a show's PLAYABLE episode pool: filters applied, exclusions removed.

    This is the pool every queue-building and replacement function must use
    when deciding what can play next.

    Args:
        show_entry: a show dict from ``channel["shows"]``.  Must contain
                    ``"tvshowid"`` and may contain ``"episode_filters"`` and
                    ``"excluded_episodes"``.
        library:    the LibraryClient instance.
    """
    eps      = get_filtered_episodes(show_entry, library)
    excluded = show_entry.get("excluded_episodes", [])
    if not excluded:
        return eps
    excluded_set = set(excluded)
    return [e for e in eps if e["episodeid"] not in excluded_set]


# ---------------------------------------------------------------------------
# BaseQueueBuilder
# ---------------------------------------------------------------------------

class BaseQueueBuilder:
    """Abstract base for all channel queue builders.

    Subclasses receive a ChannelManager instance and call its public methods
    rather than duplicating logic.  They must implement ``build()``.

    Rule: BaseQueueBuilder and its subclasses NEVER call private methods
    (prefixed ``_``) on ChannelManager.  All ChannelManager access goes
    through public methods only (Architecture Rule 14 / 15).
    """

    def __init__(self, channel_manager):
        self._cm = channel_manager

    def build(self, channel: dict, target_size: int) -> list:
        """Build and return a queue list of exactly ``target_size`` items.

        Subclasses must override this.  The returned list is written to disk
        by ChannelManager; this method must NOT write any files itself.
        """
        raise NotImplementedError(
            "{} must implement build()".format(type(self).__name__)
        )
