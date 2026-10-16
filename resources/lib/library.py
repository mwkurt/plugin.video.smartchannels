from __future__ import annotations
"""
resources/lib/library.py
=========================
Abstracts all Kodi library queries.

Supports two backends:
  1. xbmc.executeJSONRPC  - uses Kodi's built-in JSON-RPC API (preferred).
     Works transparently whether Kodi is using SQLite or MySQL/MariaDB under
     the hood, since Kodi itself handles that routing.

  2. Direct MySQL/MariaDB  - optional fallback if the user explicitly wants
     to query the DB server directly (useful for advanced setups).

Results are cached in memory per Kodi session to avoid hammering the DB.
The cache is cleared on explicit user request or addon restart.
"""

import json

import xbmc
import xbmcaddon

from resources.lib.utils.logger import log
from resources.lib.utils.paths import normalize_share_path

# Kodi home-window property shared by every Python process of this Kodi
# instance (service, plugin calls, settings actions).  Changing it tells
# every LibraryClient to drop its in-memory lists on its next lookup.
_CACHE_GEN_PROP = "smartchannels.library_cache_gen"


# -- Filter rule helpers -----------------------------------------------------
# A filter rule is {"type", "value", "operator", "comparison"}.  "operator"
# says how the rule joins the rule BEFORE it ("and" / "or"; ignored on the
# first rule).  "comparison" is one of:
#   text fields (genre, studio, mpaa):  equals, notequals, contains (the
#       default for rules saved before 3.1.99), doesnotcontain
#   number fields (year, rating, season): equals, notequals, greaterthan,
#       greaterthanequal, lessthan, lessthanequal

# Our filter types -> Kodi JSON-RPC fields.
_JRPC_FIELDS = {
    "genre":       "genre",
    "year":        "year",
    "mpaa":        "mpaa",
    "studio":      "studio",
    "watched":     "playcount",
    "rating":      "rating",
    "season":      "season",      # episode-level filter
    "firstaired":  "airdate",     # episode-level filter (Kodi field: airdate)
    # Audio fields (1.2.0a)
    "artist":      "artist",
    "albumartist": "albumartist",
    "album":       "album",
    "playcount":   "playcount",
}

# Our comparisons -> JSON-RPC operators.
# Kodi 21 JSON-RPC List.Filter.Operators has no "greaterthanequal" or
# "lessthanequal" (rejected with "Value does not match any of the enum
# values in type operator"); those are emulated per field type below.
_JRPC_OPERATORS = {
    "contains":       "contains",
    "doesnotcontain": "doesnotcontain",
    "equals":         "is",
    "notequals":      "isnot",
    "greaterthan":    "greaterthan",
    "lessthan":       "lessthan",
}


def _filter_groups(filters):
    """Split filter rules into groups joined by OR; the rules inside a group
    are joined by AND (AND is applied before OR)."""
    groups = []
    for f in filters:
        if not groups or str(f.get("operator", "and")).lower() == "or":
            groups.append([f])
        else:
            groups[-1].append(f)
    return groups


def _text_matches(values, fval, comp):
    """Compare a text rule value (already lower-cased) with an item's
    value(s): a string or a list of strings such as genres."""
    if isinstance(values, str):
        values = [values]
    vals = [str(v).lower().strip() for v in (values or []) if v]
    if comp == "equals":
        return fval in vals
    if comp == "notequals":
        return fval not in vals
    if comp == "doesnotcontain":
        return not any(fval in v for v in vals)
    return any(fval in v for v in vals)       # contains (and the default)


def _numbers_match(item_value, rule_value, comp, default):
    """Compare numbers; an unknown comparison uses *default*."""
    results = {
        "equals":           item_value == rule_value,
        "notequals":        item_value != rule_value,
        "greaterthan":      item_value > rule_value,
        "greaterthanequal": item_value >= rule_value,
        "lessthan":         item_value < rule_value,
        "lessthanequal":    item_value <= rule_value,
    }
    if comp == "is":
        comp = "equals"
    return results.get(comp, results[default])


def _jrpc_integer_rule(field, comp, fval, default_operator):
    """JSON-RPC rule for an integer field (year, season).  >= N is sent as
    > N-1 and <= N as < N+1 because Kodi has no >= / <= operators."""
    try:
        number = int(fval)
    except (ValueError, TypeError):
        number = None
    if comp == "greaterthanequal":
        return {"field": field, "operator": "greaterthan",
                "value": str(fval if number is None else number - 1)}
    if comp == "lessthanequal":
        return {"field": field, "operator": "lessthan",
                "value": str(fval if number is None else number + 1)}
    return {"field": field,
            "operator": _JRPC_OPERATORS.get(comp, default_operator),
            "value": str(fval)}


def _jrpc_rule(f):
    """Convert one filter rule to a JSON-RPC rule, or None if its type is
    not one Kodi can filter on."""
    ftype = f.get("type", "")
    fval  = f.get("value", "")
    comp  = f.get("comparison", "contains")
    if ftype not in _JRPC_FIELDS:
        return None
    field = _JRPC_FIELDS[ftype]

    if ftype == "watched":
        if fval == "watched":
            return {"field": "playcount",
                    "operator": "greaterthan", "value": "0"}
        if fval == "unwatched":
            return {"field": "playcount", "operator": "is", "value": "0"}
        return None
    if ftype == "year":
        return _jrpc_integer_rule(field, comp, fval, "greaterthan")
    if ftype == "season":
        return _jrpc_integer_rule(field, comp, fval, "is")
    if ftype == "rating":
        # Float field: >= / <= cannot be emulated exactly by adjusting the
        # value, so they use the strict operator (approximate in practice).
        if comp in ("greaterthan", "greaterthanequal"):
            operator = "greaterthan"
        elif comp in ("lessthan", "lessthanequal"):
            operator = "lessthan"
        else:
            operator = _JRPC_OPERATORS.get(comp, "is")
        return {"field": "rating", "operator": operator, "value": str(fval)}
    if ftype == "firstaired":
        # Air date is a YYYY-MM-DD string; Kodi uses after / before.
        date_ops = {"greaterthan": "after", "greaterthanequal": "after",
                    "lessthan": "before", "lessthanequal": "before",
                    "equals": "is"}
        return {"field": "airdate", "operator": date_ops.get(comp, "after"),
                "value": str(fval)}
    if ftype in ("genre", "studio", "mpaa"):
        operator = _JRPC_OPERATORS.get(comp, "contains")
        if operator not in ("contains", "doesnotcontain", "is", "isnot"):
            operator = "contains"
        return {"field": field, "operator": operator, "value": str(fval)}
    return {"field": field, "operator": "contains", "value": str(fval)}


class LibraryClient:
    """Thin wrapper around Kodi JSON-RPC for video library access."""

    def __init__(self, addon: xbmcaddon.Addon):
        self.addon   = addon
        self._cache  = {}
        self._cache_gen = self._shared_cache_generation()
        import xbmcvfs as _xbmcvfs, os as _os
        self._profile = _xbmcvfs.translatePath(addon.getAddonInfo("profile"))
        # Route local_library.json to shared storage if configured
        try:
            shared = normalize_share_path(
                addon.getSetting("shared_storage_path"))
        except Exception:
            shared = ""
        if shared:
            if not _xbmcvfs.exists(shared):
                try:
                    _xbmcvfs.mkdirs(shared)
                except Exception:
                    pass
            # Network paths use forward slash; local paths use os.path.join
            if "://" in shared:
                self._local_cache_path = shared + "/local_library.json"
                self._songs_cache_path = shared + "/songs_cache.json"
            else:
                self._local_cache_path = _os.path.join(
                    shared, "local_library.json")
                self._songs_cache_path = _os.path.join(
                    shared, "songs_cache.json")
        else:
            self._local_cache_path = _os.path.join(
                self._profile, "local_library.json")
            self._songs_cache_path = _os.path.join(
                self._profile, "songs_cache.json")
        # Ensure profile directory exists
        if not _xbmcvfs.exists(self._profile):
            _xbmcvfs.mkdirs(self._profile)

    # -- Cache helpers ---------------------------------------------------------

    @staticmethod
    def _shared_cache_generation() -> str:
        """Return the cross-process cache generation ("" if unavailable)."""
        try:
            import xbmcgui as _xbmcgui
            return _xbmcgui.Window(10000).getProperty(_CACHE_GEN_PROP)
        except Exception:
            return ""

    def invalidate_cache(self) -> None:
        """Drop all in-memory library lists, in every process of this client.

        The lists (episodes per show, shows, movies) otherwise live until
        Kodi restarts, so a file renamed in the Kodi library stays at its
        old path here.  Bumping the shared generation makes the service and
        any other LibraryClient reload on their next lookup.
        """
        import time as _time
        self._cache.clear()
        try:
            import xbmcgui as _xbmcgui
            _xbmcgui.Window(10000).setProperty(
                _CACHE_GEN_PROP, str(_time.time()))
        except Exception as e:
            log("[LibraryClient] invalidate_cache: shared flag not set: "
                "{}".format(e), xbmc.LOGWARNING)
        self._cache_gen = self._shared_cache_generation()
        log("[LibraryClient] In-memory library cache cleared")

    def _cached(self, key: str, fetcher):
        gen = self._shared_cache_generation()
        if gen != self._cache_gen:
            self._cache.clear()
            self._cache_gen = gen
        if key not in self._cache:
            self._cache[key] = fetcher()
        return self._cache[key]

    # -- JSON-RPC helper -------------------------------------------------------

    @staticmethod
    def _rpc(method: str, params: dict) -> dict:
        """
        Execute a Kodi JSON-RPC call and return the parsed result dict.
        Returns {} on error.
        """
        payload = json.dumps({
            "jsonrpc": "2.0",
            "id":      1,
            "method":  method,
            "params":  params,
        })
        raw = xbmc.executeJSONRPC(payload)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            log("[LibraryClient] JSON decode error: {}".format(exc), level=xbmc.LOGERROR)
            return {}

        if "error" in data:
            log("[LibraryClient] RPC error for {}: {}".format(method, data['error']),
                level=xbmc.LOGWARNING)
            return {}

        return data.get("result", {})

    # -- TV Shows --------------------------------------------------------------

    # -- Local library cache ---------------------------------------------------

    def local_cache_exists(self):
        """Return True if a valid local cache file exists."""
        import xbmcvfs as _xbmcvfs
        if not _xbmcvfs.exists(self._local_cache_path):
            return False
        try:
            stat = _xbmcvfs.Stat(self._local_cache_path)
            return stat.st_size() > 100
        except Exception:
            return False

    def local_cache_age_days(self):
        """Return age of local cache file in days, or 999 if missing."""
        import xbmcvfs as _xbmcvfs, time as _time
        if not _xbmcvfs.exists(self._local_cache_path):
            return 999
        try:
            stat = _xbmcvfs.Stat(self._local_cache_path)
            age  = _time.time() - stat.st_mtime()
            return age / 86400.0
        except Exception:
            return 999

    def load_local_cache(self):
        """
        Load the local library cache from disk.
        Returns dict with tvshows and movies lists, or None if not found.
        """
        import json as _json
        import xbmcvfs as _xbmcvfs
        if not _xbmcvfs.exists(self._local_cache_path):
            return None
        try:
            with _xbmcvfs.File(self._local_cache_path, "r") as f:
                data = _json.loads(f.read())
            log("[LibraryClient] Loaded local cache: {} shows, {} movies".format(
                len(data.get("tvshows", [])),
                len(data.get("movies", []))))
            return data
        except Exception as e:
            log("[LibraryClient] Failed to load local cache: {}".format(e))
            return None

    # -- Songs cache -----------------------------------------------------------

    def publish_cache_ages(self) -> None:
        """Write the whole-day age of each cache to its read-only setting.

        Updates "Library cache age" (cache_age_display) and "Songs Cache Age"
        (songs_cache_age_display) in Settings > Cache.  A missing cache shows
        0.  Only writes a setting when its value changed.
        """
        for setting_id, age_fn, exists_fn in (
                ("cache_age_display", self.local_cache_age_days,
                 self.local_cache_exists),
                ("songs_cache_age_display", self.songs_cache_age_days,
                 self.songs_cache_exists)):
            try:
                days = int(age_fn()) if exists_fn() else 0
                if self.addon.getSetting(setting_id) != str(days):
                    self.addon.setSetting(setting_id, str(days))
            except Exception as exc:
                log("[LibraryClient] publish_cache_ages '{}' error: {}".format(
                    setting_id, exc), xbmc.LOGWARNING)

    def songs_cache_exists(self) -> bool:
        """Return True if a valid songs cache file exists."""
        import xbmcvfs as _xbmcvfs
        if not _xbmcvfs.exists(self._songs_cache_path):
            return False
        try:
            stat = _xbmcvfs.Stat(self._songs_cache_path)
            return stat.st_size() > 100
        except Exception:
            return False

    def songs_cache_age_days(self) -> float:
        """Return age of songs cache file in days, or 999 if missing."""
        import xbmcvfs as _xbmcvfs, time as _time
        if not _xbmcvfs.exists(self._songs_cache_path):
            return 999.0
        try:
            stat = _xbmcvfs.Stat(self._songs_cache_path)
            age  = _time.time() - stat.st_mtime()
            return age / 86400.0
        except Exception:
            return 999.0

    def load_songs_cache(self) -> list:
        """
        Load songs from the local songs cache file.
        Returns a list of song dicts, or None if the cache is missing/corrupt.
        """
        import json as _json
        import xbmcvfs as _xbmcvfs
        if not _xbmcvfs.exists(self._songs_cache_path):
            return None
        try:
            with _xbmcvfs.File(self._songs_cache_path, "r") as f:
                data = _json.loads(f.read())
            songs = data.get("songs", [])
            log("[LibraryClient] Loaded songs cache: {} songs".format(
                len(songs)))
            return songs
        except Exception as e:
            log("[LibraryClient] Failed to load songs cache: {}".format(e))
            return None

    def build_songs_cache(self) -> bool:
        """
        Fetch all songs from the Kodi music library and write songs_cache.json.
        Always runs on a background thread — never blocks the UI.
        Uses paginated GetSongs calls (500 per page) to avoid the 18-second
        single-query timeout on large MySQL libraries.
        No progress callback — callers use toast notifications instead.
        """
        import json as _json, time as _time
        import xbmcvfs as _xbmcvfs, os as _osl

        _BATCH = 500
        _PROPS = [
            "title", "artist", "albumartist", "album",
            "genre", "year", "duration", "file", "track", "disc",
            "rating", "playcount", "thumbnail",
        ]

        log("[LibraryClient] Building songs cache (paginated, {} per page)..."
            .format(_BATCH))

        songs     = []
        start     = 0
        page      = 0
        total_rpc = 0  # reported by first call

        while True:
            try:
                result = self._rpc("AudioLibrary.GetSongs", {
                    "properties": _PROPS,
                    "limits":     {"start": start, "end": start + _BATCH},
                })
            except Exception as e:
                log("[LibraryClient] Songs cache: RPC error on page {}: {}"
                    .format(page, e), xbmc.LOGWARNING)
                return False

            page_songs = result.get("songs", [])
            if page == 0:
                limits = result.get("limits", {})
                total_rpc = limits.get("total", 0)
                log("[LibraryClient] Songs cache: {} total songs reported"
                    .format(total_rpc))

            for s in page_songs:
                if not s.get("file"):
                    continue
                songs.append({
                    "songid":      s.get("songid",       -1),
                    "title":       s.get("title",         ""),
                    "artist":      s.get("artist",        []),
                    "albumartist": s.get("albumartist",   []),
                    "album":       s.get("album",         ""),
                    "genre":       s.get("genre",         []),
                    "year":        int(s.get("year",      0) or 0),
                    "duration":    int(s.get("duration",  0) or 0),
                    "file":        s.get("file",          ""),
                    "track":       int(s.get("track",     0) or 0),
                    "disc":        int(s.get("disc",      0) or 0),
                    "rating":      float(s.get("rating",  0) or 0),
                    "playcount":   int(s.get("playcount", 0) or 0),
                    "thumbnail":   s.get("thumbnail",     ""),
                })

            log("[LibraryClient] Songs cache: page {} fetched {} songs "
                "({} total so far)".format(page, len(page_songs), len(songs)))

            if len(page_songs) < _BATCH:
                break   # last page
            start += _BATCH
            page  += 1

        log("[LibraryClient] Songs cache: fetched {} songs total".format(
            len(songs)))

        data = {
            "last_updated": _time.strftime("%Y-%m-%d %H:%M:%S"),
            "songs":        songs,
        }

        try:
            if not _xbmcvfs.exists(self._profile):
                _xbmcvfs.mkdirs(self._profile)

            json_data = _json.dumps(data, indent=2)
            is_shared = not self._songs_cache_path.startswith(self._profile)

            if not is_shared:
                with _xbmcvfs.File(self._songs_cache_path, "w") as f:
                    f.write(json_data)
            else:
                local_copy = _osl.path.join(self._profile, "songs_cache.json")
                with _xbmcvfs.File(local_copy, "w") as f:
                    f.write(json_data)
                if not _xbmcvfs.copy(local_copy, self._songs_cache_path):
                    with _xbmcvfs.File(local_copy, "r") as sl, \
                         _xbmcvfs.File(self._songs_cache_path, "w") as dl:
                        dl.write(sl.read())

            if _xbmcvfs.exists(self._songs_cache_path):
                self._cache.pop("all_songs", None)
                log("[LibraryClient] Songs cache built: {} songs".format(
                    len(songs)))
                self.publish_cache_ages()
                return True
            else:
                log("[LibraryClient] Songs cache: file missing after write",
                    xbmc.LOGWARNING)
                return False

        except Exception as e:
            log("[LibraryClient] Songs cache write failed: {}".format(e),
                xbmc.LOGWARNING)
            return False

    def build_local_cache(self, progress_callback=None):
        """
        Query MySQL for all shows and movies and write local_library.json.
        progress_callback(pct, msg) is called during the build for UI updates.

        Excludes watched status (changes too frequently to cache reliably).
        Watched filter is applied at queue build time via live DB query.
        """
        import json as _json, time as _time

        log("[LibraryClient] Building local library cache...")

        def _progress(pct, msg):
            if progress_callback:
                progress_callback(pct, msg)

        _progress(5, "Fetching TV shows...")

        # Fetch TV shows with full filter-relevant properties
        result = self._rpc("VideoLibrary.GetTVShows", {
            "properties": ["title", "genre", "year", "studio",
                           "mpaa", "rating", "episode", "art"],
            "sort": {"order": "ascending", "method": "title"},
        })
        tvshows = []
        for s in result.get("tvshows", []):
            tvshows.append({
                "tvshowid":   s.get("tvshowid", -1),
                "title":      s.get("title", ""),
                "genre":      s.get("genre", []),
                "year":       s.get("year", 0),
                "studio":     s.get("studio", []),
                "mpaa":       s.get("mpaa", ""),
                "rating":     round(float(s.get("rating", 0) or 0), 1),
                "nbepisodes": s.get("episode", 0),
                "poster":     s.get("art", {}).get("poster", ""),
            })

        _progress(50, "Fetching movies...")

        # Fetch movies with full filter-relevant properties
        # Fetch movies in two passes to avoid large result sets timing out:
        # Pass 1: filter-relevant fields (fast)
        # Pass 2: display metadata fields (plot, runtime) separately
        result2 = self._rpc("VideoLibrary.GetMovies", {
            "properties": ["title", "genre", "year", "studio",
                           "mpaa", "rating", "file", "runtime", "art"],
            "sort": {"order": "ascending", "method": "title"},
        })
        movies = []
        for m in result2.get("movies", []):
            if not m.get("file"):
                continue
            movies.append({
                "movieid": m.get("movieid", -1),
                "title":   m.get("title", ""),
                "genre":   m.get("genre", []),
                "year":    m.get("year", 0),
                "studio":  m.get("studio", []),
                "mpaa":    m.get("mpaa", ""),
                "rating":  round(float(m.get("rating", 0) or 0), 1),
                "file":    m.get("file", ""),
                "runtime": m.get("runtime", 0),
                "plot":    "",
                "poster":  m.get("art", {}).get("poster", ""),
            })

        _progress(70, "Fetching movie descriptions...")

        # Pass 2: fetch plot separately - smaller result set per query
        # Do this in one batch query, not per-movie
        result3 = self._rpc("VideoLibrary.GetMovies", {
            "properties": ["plot"],
            "sort": {"order": "ascending", "method": "title"},
        })
        plot_map = {
            m.get("movieid"): (m.get("plot", "") or "")[:300]
            for m in result3.get("movies", [])
        }
        # Merge plots into movie list
        for m in movies:
            m["plot"] = plot_map.get(m["movieid"], "")

        _progress(90, "Writing cache file...")

        data = {
            "last_updated": _time.strftime("%Y-%m-%d %H:%M:%S"),
            "tvshows":      tvshows,
            "movies":       movies,
        }

        try:
            import xbmcvfs as _xbmcvfs2

            # Ensure profile directory exists before writing
            if not _xbmcvfs2.exists(self._profile):
                _xbmcvfs2.mkdirs(self._profile)
                log("[LibraryClient] Created profile dir: {}".format(
                    self._profile))

            json_data = _json.dumps(data, indent=2)
            log("[LibraryClient] Writing {} bytes to {}".format(
                len(json_data), self._local_cache_path))

            # Write cache: local path uses xbmcvfs.File directly;
            # shared path writes locally first then copies across.
            import os as _osl
            is_shared = not self._local_cache_path.startswith(self._profile)
            if not is_shared:
                with _xbmcvfs2.File(self._local_cache_path, "w") as _fl:
                    _fl.write(json_data)
            else:
                local_copy = _osl.path.join(self._profile,
                                            "local_library.json")
                with _xbmcvfs2.File(local_copy, "w") as _fl:
                    _fl.write(json_data)
                if not _xbmcvfs2.copy(local_copy, self._local_cache_path):
                    if "://" not in self._local_cache_path:
                        with _xbmcvfs2.File(local_copy, "r") as _sl, \
                             _xbmcvfs2.File(self._local_cache_path, "w") as _dl:
                            _dl.write(_sl.read())

            # Verify the file was actually written
            if not _xbmcvfs2.exists(self._local_cache_path):
                log("[LibraryClient] ERROR: cache file missing after write - "
                    "trying direct open() as fallback")
                with _xbmcvfs2.File(self._local_cache_path, "w") as f:
                    f.write(json_data)

            # Final verification
            if _xbmcvfs2.exists(self._local_cache_path):
                # Invalidate in-memory cache so next call re-reads fresh data
                self._cache.pop("tvshows_minimal", None)
                self._cache.pop("tvshows_full", None)
                self._cache.pop("movies_all", None)
                log("[LibraryClient] Local cache built: {} shows, {} movies".format(
                    len(tvshows), len(movies)))
                _progress(100, "Done!")
                self.publish_cache_ages()
                return True
            else:
                log("[LibraryClient] ERROR: cache file still missing after "
                    "both write attempts!")
                return False

        except Exception as e:
            log("[LibraryClient] Failed to write local cache: {} - {}".format(
                type(e).__name__, e))
            # Last resort: try plain Python file write
            try:
                with _xbmcvfs2.File(self._local_cache_path, "w") as f:
                    f.write(_json.dumps(data, indent=2))
                log("[LibraryClient] Fallback write succeeded")
                _progress(100, "Done (fallback)!")
                self.publish_cache_ages()
                return True
            except Exception as e2:
                log("[LibraryClient] Fallback write also failed: {}".format(e2))
                return False

    def get_all_tvshows(self) -> list[dict]:
        """
        Return all TV shows for multiselect display.
        Reads from local cache if available, falls back to live DB query.
        """
        def _fetch():
            cached = self.load_local_cache()
            if cached and cached.get("tvshows"):
                return cached["tvshows"]
            # Fallback: minimal live query
            result = self._rpc("VideoLibrary.GetTVShows", {
                "properties": ["title"],
                "sort": {"order": "ascending", "method": "title"},
            })
            shows = result.get("tvshows", [])
            log("[LibraryClient] Loaded {} TV shows (live fallback)".format(
                len(shows)))
            return shows
        return self._cached("tvshows_minimal", _fetch)

    def get_all_tvshows_full(self) -> list[dict]:
        """
        Return all TV shows with full filter properties.
        Reads from local cache if available.
        """
        def _fetch():
            cached = self.load_local_cache()
            if cached and cached.get("tvshows"):
                return cached["tvshows"]
            # Fallback: live full query
            result = self._rpc("VideoLibrary.GetTVShows", {
                "properties": ["title", "genre", "year", "studio",
                               "mpaa", "rating"],
                "sort": {"order": "ascending", "method": "title"},
            })
            return result.get("tvshows", [])
        return self._cached("tvshows_full", _fetch)


    # -- Episodes --------------------------------------------------------------

    def get_episodes_for_show(self, tvshowid: int) -> list[dict]:
        """
        Return all episodes for a show, sorted by season then episode number.
        Cached per show ID.

        Returns list of:
          {"episodeid": int, "title": str, "season": int, "episode": int,
           "file": str, "thumbnail": str, "plot": str, "runtime": int, ...}
        """
        cache_key = "episodes_{}".format(tvshowid)

        def _fetch():
            result = self._rpc("VideoLibrary.GetEpisodes", {
                "tvshowid":   tvshowid,
                # Minimal properties for queue building - reduces transfer size
                # and speeds up queries significantly on large libraries
                "properties": ["title", "season", "episode", "file",
                               "playcount", "showtitle"],
                "sort": {"order": "ascending", "method": "episode"},
            })
            episodes = result.get("episodes", [])
            # Remove episodes with no local file path
            episodes = [e for e in episodes if e.get("file")]
            log("[LibraryClient] Loaded {} episodes for show {}".format(
                len(episodes), tvshowid), xbmc.LOGDEBUG)
            return episodes

        return self._cached(cache_key, _fetch)

    # -- Movies ----------------------------------------------------------------

    def get_all_movies(self) -> list[dict]:
        """
        Return all movies. Reads from local cache if available.
        """
        def _fetch():
            cached = self.load_local_cache()
            if cached and cached.get("movies"):
                return cached["movies"]
            # Fallback: live query
            result = self._rpc("VideoLibrary.GetMovies", {
                "properties": ["title", "genre", "year", "file",
                               "thumbnail", "fanart", "plot", "runtime",
                               "rating", "mpaa", "studio", "playcount",
                               "art"],
                "sort": {"order": "ascending", "method": "title"},
            })
            movies = [m for m in result.get("movies", []) if m.get("file")]
            log("[LibraryClient] Loaded {} movies (live fallback)".format(
                len(movies)))
            return movies
        return self._cached("movies_all", _fetch)


    # -- Advanced filter queries -----------------------------------------------

    def build_jrpc_filter(self, filters):
        """
        Convert our filter list into a Kodi JSON-RPC filter object.

        Each filter dict:
          {"type": "genre",   "value": "Comedy",    "operator": "and",
           "comparison": "notequals"}
          {"type": "year",    "value": "1969",       "operator": "and",
           "comparison": "greaterthan"}
          {"type": "watched", "value": "unwatched",  "operator": "and"}

        Rules joined by AND are grouped; the groups are joined by OR.
        Returns a JSON-RPC filter dict or None if no filters.
        """
        if not filters:
            return None

        groups = []
        for group in _filter_groups(filters):
            rules = [r for r in (_jrpc_rule(f) for f in group)
                     if r is not None]
            if len(rules) == 1:
                groups.append(rules[0])
            elif rules:
                groups.append({"and": rules})

        if not groups:
            return None
        if len(groups) == 1:
            return groups[0]
        return {"or": groups}

    def get_tvshows_with_filters(self, filters):
        """
        Filter TV shows using the local cache - no MySQL query needed.
        Filters the cached show list in Python which is instant.
        Falls back to live DB query only if no local cache exists.
        """

        # Try filtering from local cache first (instant)
        all_shows = self.get_all_tvshows_full()
        if all_shows:
            result = self.filter_items(all_shows, filters)
            log("[LibraryClient] Python filter: {} of {} shows match".format(
                len(result), len(all_shows)))
            return result

        # Fallback: live DB query (slow but works without cache)
        log("[LibraryClient] No cache - falling back to live filter query")
        jrpc_filter = self.build_jrpc_filter(filters)
        params = {
            "properties": ["title", "genre", "year", "studio",
                           "mpaa", "rating"],
            "sort": {"order": "ascending", "method": "title"},
        }
        if jrpc_filter:
            params["filter"] = jrpc_filter
        result = self._rpc("VideoLibrary.GetTVShows", params)
        shows  = result.get("tvshows", [])
        log("[LibraryClient] Live filter query returned {} shows".format(
            len(shows)))
        return shows

    def get_movies_with_filters(self, filters):
        """
        Filter movies using the local cache - no MySQL query needed.
        Falls back to live DB query only if no local cache exists.
        """
        all_movies = self.get_all_movies()
        if all_movies:
            result = self.filter_items(all_movies, filters)
            log("[LibraryClient] Python filter: {} of {} movies match".format(
                len(result), len(all_movies)))
            return result

        # Fallback: live DB query
        log("[LibraryClient] No cache - falling back to live movie filter")
        jrpc_filter = self.build_jrpc_filter(filters)
        params = {
            "properties": ["title", "genre", "year", "file",
                           "mpaa", "studio", "rating"],
            "sort": {"order": "ascending", "method": "title"},
        }
        if jrpc_filter:
            params["filter"] = jrpc_filter
        result  = self._rpc("VideoLibrary.GetMovies", params)
        movies  = [m for m in result.get("movies", []) if m.get("file")]
        log("[LibraryClient] Live movie filter returned {} movies".format(
            len(movies)))
        return movies

    def filter_items(self, items, filters):
        """
        Filter a list of show/movie/episode/song dicts using our filter rules.
        All filtering is done in Python against cached data - no DB needed.

        Supports:
          genre, studio, mpaa - equals / notequals / contains /
                                doesnotcontain (case insensitive)
          year, rating, season - equals / notequals / greaterthan /
                                greaterthanequal / lessthan / lessthanequal
          firstaired, artist, albumartist, album, playcount

        Rules joined by AND are grouped; an item passes if every rule of
        any one OR-separated group matches (AND is applied before OR).
        """
        if not filters:
            return items

        def _matches_rule(item, f):
            ftype = f.get("type", "")
            fval  = str(f.get("value", "")).lower().strip()
            comp  = f.get("comparison", "contains")

            if ftype == "genre":
                return _text_matches(item.get("genre", []), fval, comp)

            elif ftype == "mpaa":
                return _text_matches(item.get("mpaa", ""), fval, comp)

            elif ftype == "studio":
                return _text_matches(item.get("studio", []), fval, comp)

            elif ftype in ("year", "season"):
                try:
                    cmp_number = int(fval)
                except (ValueError, TypeError):
                    return True
                item_number = int(item.get(ftype, 0) or 0)
                return _numbers_match(
                    item_number, cmp_number, comp,
                    "greaterthan" if ftype == "year" else "equals")

            elif ftype == "rating":
                try:
                    cmp_rating = round(float(fval), 1)
                except (ValueError, TypeError):
                    return True
                item_rating = round(float(item.get("rating", 0) or 0), 1)
                return _numbers_match(item_rating, cmp_rating, comp,
                                      "greaterthanequal")

            elif ftype == "firstaired":
                # Compare YYYY-MM-DD strings lexicographically — works
                # correctly for ISO date format.
                item_date = str(item.get("firstaired", "") or "").strip()
                cmp_date  = str(fval).strip()
                # Episodes with no firstaired date are excluded when filtering
                # by date — an unknown date cannot satisfy a date comparison.
                if not item_date:
                    return False
                if not cmp_date:
                    return True
                if comp in ("greaterthan", "greaterthanequal", "after"):
                    return item_date >= cmp_date
                elif comp in ("lessthan", "lessthanequal", "before"):
                    return item_date <= cmp_date
                return item_date == cmp_date

            elif ftype == "artist":
                # Match against both artist and albumartist lists
                artists = [a.lower() for a in item.get("artist", [])]
                albumartists = [a.lower() for a in item.get("albumartist", [])]
                all_artists = artists + albumartists
                return any(fval in a for a in all_artists)

            elif ftype == "albumartist":
                albumartists = [a.lower() for a in item.get("albumartist", [])]
                return any(fval in a for a in albumartists)

            elif ftype == "album":
                return fval in item.get("album", "").lower()

            elif ftype == "playcount":
                item_pc = int(item.get("playcount", 0) or 0)
                try:
                    cmp_pc = int(fval)
                except ValueError:
                    return True
                if comp == "greaterthan":
                    return item_pc > cmp_pc
                elif comp == "lessthan":
                    return item_pc < cmp_pc
                return item_pc == cmp_pc

            return True  # Unknown filter type - pass through

        groups = _filter_groups(filters)
        return [item for item in items
                if any(all(_matches_rule(item, f) for f in group)
                       for group in groups)]

    def get_episodes_with_filters(self, tvshowid, filters):
        """
        Return episodes for a show matching filter rules.
        Supports: watched/unwatched, season, firstaired.

        Strategy: build a Kodi JSON-RPC filter and pass it in the query.
        If the RPC rejects the filter (e.g. unsupported field/operator
        combination on this Kodi version), fall back to fetching all episodes
        and applying filter_items so the user always gets results.

        Note: "year" is NOT a valid episode property in Kodi JSON-RPC —
        do not add it to the properties list. Use "firstaired" for date-based
        episode filtering.
        """
        jrpc_filter = self.build_jrpc_filter(filters)
        log("[LibraryClient] get_episodes_with_filters: show={} "
            "jrpc_filter={}".format(tvshowid, jrpc_filter))

        params = {
            "tvshowid":   tvshowid,
            "properties": ["title", "season", "episode", "file",
                           "thumbnail", "plot", "runtime", "showtitle",
                           "playcount", "firstaired"],
        }
        if jrpc_filter:
            params["filter"] = jrpc_filter
        else:
            # Only add sort when there is no filter — Kodi rejects the
            # combination of tvshowid + filter + sort on some builds.
            params["sort"] = {"order": "ascending", "method": "episode"}

        result   = self._rpc("VideoLibrary.GetEpisodes", params)
        episodes = result.get("episodes", [])
        episodes = [e for e in episodes if e.get("file")]
        # Sort by season then episode — needed when sort param was omitted
        # (filtered queries drop the sort to avoid Kodi validator rejection)
        episodes.sort(key=lambda e: (e.get("season", 0), e.get("episode", 0)))

        # If Kodi rejected the filter (RPC error → empty result) but we had
        # valid filter rules, fall back to Python-side filtering so the
        # user still gets a filtered list rather than an empty queue.
        if not episodes and jrpc_filter and filters:
            log("[LibraryClient] get_episodes_with_filters: RPC filter "
                "failed or returned empty — falling back to Python filter "
                "for show {}".format(tvshowid))
            params_nf = {
                "tvshowid":   tvshowid,
                "properties": ["title", "season", "episode", "file",
                               "thumbnail", "plot", "runtime", "showtitle",
                               "playcount", "firstaired"],
                "sort": {"order": "ascending", "method": "episode"},
            }
            result_nf  = self._rpc("VideoLibrary.GetEpisodes", params_nf)
            all_eps    = result_nf.get("episodes", [])
            all_eps    = [e for e in all_eps if e.get("file")]
            episodes   = self.filter_items(all_eps, filters)
            log("[LibraryClient] get_episodes_with_filters: Python filter "
                "kept {} of {} episodes".format(len(episodes), len(all_eps)))

        return episodes

    def get_mpaa_ratings(self, media_type="movie"):
        """Return unique MPAA ratings present in the library."""
        cache_key = "mpaa_{}".format(media_type)
        def _fetch():
            if media_type == "movie":
                movies = self.get_all_movies()
                ratings = sorted(set(
                    m.get("mpaa", "") for m in movies
                    if m.get("mpaa", "").strip()))
            else:
                ratings = []
            return ratings
        return self._cached(cache_key, _fetch)

    def get_studios(self, media_type="movie"):
        """Return unique studios present in the library."""
        cache_key = "studios_{}".format(media_type)
        def _fetch():
            if media_type == "movie":
                items = self.get_all_movies()
            else:
                items = self.get_all_tvshows()
            studios = set()
            for item in items:
                for s in item.get("studio", []):
                    if s.strip():
                        studios.add(s.strip())
            return sorted(studios)
        return self._cached(cache_key, _fetch)

    # -- Genres (for filter selection) -----------------------------------------

    def get_all_genres(self, media_type: str = "tvshow") -> list[str]:
        """
        Return a sorted deduplicated list of genres for the given media type.
        media_type: "tvshow" or "movie"
        """
        cache_key = "genres_{}".format(media_type)

        def _fetch():
            result = self._rpc("VideoLibrary.GetGenres", {
                "type": media_type,
            })
            genres = [g["label"] for g in result.get("genres", [])]
            return sorted(set(genres))

        return self._cached(cache_key, _fetch)

    # -- Recently added (for new-episode detection) ----------------------------

    # -- Invalidate cache for a specific show (call after library scan) --------

    # -- Database version auto-detection ---------------------------------------

    # ------------------------------------------------------------------
    # Audio library methods (1.2.0a)
    # ------------------------------------------------------------------

    def get_all_songs(self) -> list:
        """
        Return all songs from the Kodi music library with full properties.

        Read order:
          1. In-memory cache (instant — same LibraryClient instance)
          2. songs_cache.json on disk (fast — avoids MySQL round-trip)
          3. Live AudioLibrary.GetSongs RPC (slow on large libraries —
             only used when the disk cache is missing)

        The disk cache is built/refreshed by build_songs_cache(), called
        from the background service on startup and on AudioLibrary.OnScanFinished.
        """
        def _fetch():
            # Try disk cache first
            cached = self.load_songs_cache()
            if cached is not None:
                log("[LibraryClient] get_all_songs: {} songs (from cache)".format(
                    len(cached)))
                return cached

            # No disk cache — fall back to live RPC
            log("[LibraryClient] get_all_songs: no disk cache, "
                "fetching live (may be slow on large libraries)")
            result = self._rpc("AudioLibrary.GetSongs", {
                "properties": [
                    "title", "artist", "albumartist", "album",
                    "genre", "year", "duration", "file", "track", "disc",
                    "rating", "playcount", "thumbnail",
                ],
            })
            songs = []
            for s in result.get("songs", []):
                if not s.get("file"):
                    continue
                songs.append({
                    "songid":      s.get("songid",      -1),
                    "title":       s.get("title",        ""),
                    "artist":      s.get("artist",       []),
                    "albumartist": s.get("albumartist",  []),
                    "album":       s.get("album",        ""),
                    "genre":       s.get("genre",        []),
                    "year":        int(s.get("year",     0) or 0),
                    "duration":    int(s.get("duration", 0) or 0),
                    "file":        s.get("file",         ""),
                    "track":       int(s.get("track",    0) or 0),
                    "disc":        int(s.get("disc",     0) or 0),
                    "rating":      float(s.get("rating", 0) or 0),
                    "playcount":   int(s.get("playcount",0) or 0),
                    "thumbnail":   s.get("thumbnail",    ""),
                })
            log("[LibraryClient] get_all_songs: {} songs (live RPC)".format(
                len(songs)))
            return songs

        return self._cached("all_songs", _fetch)

    def get_songs_with_filters(self, filters: list) -> list:
        """
        Return songs matching the given audio_filters list.
        Filters in Python against the cached get_all_songs() result —
        same approach as get_movies_with_filters().
        """
        all_songs = self.get_all_songs()
        if not filters:
            return all_songs
        result = self.filter_items(all_songs, filters)
        log("[LibraryClient] get_songs_with_filters: {} of {} songs match".format(
            len(result), len(all_songs)))
        return result

    def get_all_artists(self) -> list:
        """
        Return all artists from the music library for the artist picker.
        Results are cached.
        """
        def _fetch():
            result = self._rpc("AudioLibrary.GetArtists", {
                "properties": ["thumbnail"],
                "sort": {"order": "ascending", "method": "artist"},
                "albumartistsonly": False,
            })
            artists = []
            for a in result.get("artists", []):
                name = a.get("artist", "")
                if name:
                    artists.append({
                        "artist":    name,
                        "thumbnail": a.get("thumbnail", ""),
                    })
            log("[LibraryClient] get_all_artists: {} artists".format(
                len(artists)))
            return artists

        return self._cached("all_artists", _fetch)

    def get_audio_genres(self) -> list:
        """Return sorted deduplicated list of music genres.
        AudioLibrary.GetGenres returns genre items with 'title' field
        (not 'label') per Audio.Details.Genres schema.
        """
        def _fetch():
            result = self._rpc("AudioLibrary.GetGenres",
                               {"properties": ["title"]})
            genres = [g["title"] for g in result.get("genres", [])
                      if g.get("title")]
            return sorted(set(genres))
        return self._cached("audio_genres", _fetch)

    def get_albums_for_artists(self, artist_names: list) -> dict:
        """
        Return a dict mapping each artist name to a sorted list of album
        titles that contain at least one song by that artist.

        Works from the cached get_all_songs() result — no extra RPC call.
        artist_names is a list of strings as stored in audio_filters values.
        Matching is case-insensitive contains, same as filter_items.
        """
        all_songs = self.get_all_songs()
        result    = {name: set() for name in artist_names}
        for song in all_songs:
            album = song.get("album", "")
            if not album:
                continue
            # song["artist"] is a list from get_all_songs
            song_artists = song.get("artist", [])
            if isinstance(song_artists, str):
                song_artists = [song_artists]
            for name in artist_names:
                name_lower = name.lower()
                if any(name_lower in a.lower() for a in song_artists):
                    result[name].add(album)
        return {name: sorted(albums) for name, albums in result.items()}

    def reset_watched_episode(self, episodeid: int) -> bool:
        """
        Reset the watched status of a TV episode to unwatched (playcount=0).
        Called by service.py after an episode completes naturally, when the
        'reset_watched' setting is enabled.
        Returns True on success, False on failure.
        """
        try:
            result = LibraryClient._rpc(
                "VideoLibrary.SetEpisodeDetails",
                {"episodeid": episodeid, "playcount": 0})
            # _rpc returns data["result"] which for Set* calls is the
            # string "OK", not a dict — check accordingly.
            ok = (result == "OK")
            if ok:
                log("[LibraryClient] reset watched: episode {}".format(
                    episodeid))
            else:
                log("[LibraryClient] reset watched failed for episode {}: "
                    "{}".format(episodeid, result), xbmc.LOGWARNING)
            return ok
        except Exception as e:
            log("[LibraryClient] reset_watched_episode error: {}".format(e),
                xbmc.LOGWARNING)
            return False

    def reset_watched_movie(self, movieid: int) -> bool:
        """
        Reset the watched status of a movie to unwatched (playcount=0).
        Called by service.py after a movie completes naturally, when the
        'reset_watched' setting is enabled.
        Returns True on success, False on failure.
        """
        try:
            result = LibraryClient._rpc(
                "VideoLibrary.SetMovieDetails",
                {"movieid": movieid, "playcount": 0})
            ok = (result == "OK")
            if ok:
                log("[LibraryClient] reset watched: movie {}".format(movieid))
            else:
                log("[LibraryClient] reset watched failed for movie {}: "
                    "{}".format(movieid, result), xbmc.LOGWARNING)
            return ok
        except Exception as e:
            log("[LibraryClient] reset_watched_movie error: {}".format(e),
                xbmc.LOGWARNING)
            return False

