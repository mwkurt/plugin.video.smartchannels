# plugin.video.smartchannels
# utils/multi_episode.py
#
# OWNS:   Multi-episode file span detection.
#         Determines how many consecutive episodes a single video file covers
#         (e.g. a file named S01E01E02 covers two episodes).
#
# CALLERS: channels/base.py (via normalize_ep)
#          channel_manager.py (via get_episode_span / get_span_episode_ids)
#
# NEVER:  State reads/writes, Kodi API calls, UI rendering.
#         The core detection logic (count_episode_span, span_episode_ids,
#         _span_from_filename) is fully standalone and unit-testable without
#         Kodi. Only _span_from_nfo imports xbmcvfs, and only at call time.
#
# Version: 3.0.0

from __future__ import annotations

import os
import re

from resources.lib.utils.logger import log

# ---------------------------------------------------------------------------
# Regex patterns for multi-episode filename detection.
#
# Priority order matches the detection tiers in count_episode_span():
#   1. episode_end field (handled in code, not regex)
#   2. Filename patterns below
#   3. NFO block count (handled in code, not regex)
#   4. Default: 1
#
# All patterns are compiled once at import time, case-insensitive.
# ---------------------------------------------------------------------------

# Sonarr / scene: S01E01E02, S01E01-E02, S01E01–E02, S01E01E02E03
# Group 1: first episode number.
# Group 2: one or more additional episode numbers, each preceded by an
#           optional hyphen/en-dash and then the E/e marker.
# Handles: E01E02, E01-E02, E01–E02 (en-dash), E01E02E03.
_RE_SONARR = re.compile(
    r'[Ss]\d{1,2}[Ee](\d{1,3})((?:[-\u2013]?[Ee]\d{1,3})+)',
    re.IGNORECASE,
)

# Additional episode numbers within the trailing part of a Sonarr match.
_RE_EP_NUM = re.compile(r'\d{1,3}')

# Scene shorthand: 101102 = season 1, ep 01, ep 02 (6 consecutive digits only).
# Must NOT be preceded or followed by another digit.
_RE_SCENE = re.compile(r'(?<!\d)(\d{1,2})(\d{2})(\d{2})(?!\d)')


def count_episode_span(episode_dict: dict) -> int:
    """Return the number of consecutive episodes the file covers.

    Returns 1 for a normal single-episode file.

    Detection priority:
      1. ``episode_end`` field in the episode dict (populated by some Kodi
         builds when a file is explicitly tagged as a multi-episode file).
      2. Filename pattern matching (Sonarr multi-ep naming, scene shorthand).
      3. NFO file ``<episodedetails>`` block count.
      4. Default: 1.

    Args:
        episode_dict: A raw episode dict as returned by the Kodi library.
                      Must contain at least ``"episode"`` (int).
                      May contain ``"file"`` (str) and ``"episode_end"`` (int).

    Returns:
        int >= 1
    """
    # --- Tier 1: episode_end field -------------------------------------------
    ep_end = episode_dict.get("episode_end")
    ep_num = episode_dict.get("episode", 0)
    if isinstance(ep_end, int) and ep_end > ep_num > 0:
        span = ep_end - ep_num + 1
        log("[multi_episode] episode_end tier: span={} (ep {} -> {})".format(
            span, ep_num, ep_end))
        return span

    # --- Tier 2: filename pattern matching -----------------------------------
    file_path = episode_dict.get("file", "")
    if file_path:
        filename = os.path.basename(file_path)
        span = _span_from_filename(filename)
        if span > 1:
            log("[multi_episode] filename tier: span={} from '{}'".format(
                span, filename))
            return span

    # --- Tier 3: NFO block count --------------------------------------------
    if file_path:
        span = _span_from_nfo(file_path)
        if span > 1:
            log("[multi_episode] NFO tier: span={} for '{}'".format(
                span, file_path))
            return span

    return 1


def span_episode_ids(episode_dict: dict, all_episodes_for_show: list) -> list:
    """Return all episodeid values covered by this file.

    For a single-episode file, returns a one-element list.
    For a multi-episode file (span N), returns up to N episodeid values
    by finding all library entries in the same season whose episode
    numbers fall in the covered range.

    Args:
        episode_dict:          The episode whose file is being examined.
                               Must contain ``"season"`` and ``"episode"``.
        all_episodes_for_show: Full filtered+available episode list for the
                               show, as returned by get_available_episodes().

    Returns:
        list[int] -- at least one element (the episode's own episodeid).
    """
    own_id = episode_dict.get("episodeid", -1)
    span   = count_episode_span(episode_dict)

    if span <= 1:
        return [own_id] if own_id >= 0 else []

    season   = episode_dict.get("season", 0)
    ep_start = episode_dict.get("episode", 0)
    ep_end   = ep_start + span - 1

    covered = [
        e["episodeid"]
        for e in all_episodes_for_show
        if (e.get("season") == season
            and ep_start <= e.get("episode", -1) <= ep_end
            and e.get("episodeid", -1) >= 0)
    ]

    # Always include at least the episode's own ID.
    if own_id >= 0 and own_id not in covered:
        covered.insert(0, own_id)

    return covered


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _span_from_filename(filename: str) -> int:
    """Parse a filename for multi-episode patterns and return the span count.

    Returns 1 if no multi-episode pattern is found.

    Patterns checked (in order):
      - Sonarr / scene release naming: S01E01E02, S01E01-E02, S01E01E02E03
      - Scene shorthand: 101102 (season 1, ep 01 + ep 02)
    """
    # Sonarr pattern: S01E01E02, S01E01-E02, S01E01E02E03
    m = _RE_SONARR.search(filename)
    if m:
        first_ep  = int(m.group(1))
        trailing  = m.group(2)
        extra_eps = [int(n) for n in _RE_EP_NUM.findall(trailing)]
        if extra_eps:
            last_ep = extra_eps[-1]
            span    = last_ep - first_ep + 1
            if span > 1:
                return span

    # Scene shorthand: 101102 -> season 1, ep 01, ep 02
    m = _RE_SCENE.search(filename)
    if m:
        ep1 = int(m.group(2))
        ep2 = int(m.group(3))
        if ep2 > ep1:
            return ep2 - ep1 + 1

    return 1


def _span_from_nfo(video_file_path: str) -> int:
    """Read the companion NFO file and count ``<episodedetails>`` blocks.

    Returns 1 if the NFO is absent, unreadable, or contains only one block.
    Imports xbmcvfs at call time so the rest of this module remains testable
    without a live Kodi environment.
    """
    try:
        import xbmcvfs  # deferred so unit tests can run without Kodi
        base, _  = os.path.splitext(video_file_path)
        nfo_path = base + ".nfo"

        if not xbmcvfs.exists(nfo_path):
            return 1

        f = xbmcvfs.File(nfo_path)
        try:
            content = f.read()
        finally:
            f.close()

        if not content:
            return 1

        count = content.lower().count("<episodedetails>")
        return max(1, count)

    except Exception as exc:
        log("[multi_episode] NFO read error for '{}': {}".format(
            video_file_path, exc))
        return 1
