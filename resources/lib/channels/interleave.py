# channels/interleave.py
#
# OWNS:   All Unified Interleave logic:
#         - Normalising the interleave config (single-dict -> list migration shim)
#         - get_sources()           : return the list of source configs for a channel
#         - cycle_length()          : primary items in one complete interleave cycle
#         - plan_primary_count()    : primary items for an initial queue that ends on a whole cycle
#         - apply_interleave_list() : weave ALL sources (silent and non-silent) into a queue
#         - get_all_foreign_ids()   : return every foreign channel_id referenced
#         - advance_counters()      : increment per-source counters, return fired sources
#
# NEVER:  State reads/writes (state.json -- that is channel_manager.py's job).
#         Library access.
#         Playback control or UI rendering.
#         Writing queue files.
#
# CALLERS: channel_manager.py only.
#
# DESIGN NOTE -- single-dict compatibility shim
# ---------------------------------------------
# Versions <= 1.1.1f stored interleave as a single dict:
#   {"channel_id": "...", "frequency": 4, ...}
# Unified Interleave stores it as a list:
#   [{"channel_id": "...", "frequency": 4, "silent": false}, ...]
#
# get_sources() normalises both forms transparently.
#
# SILENT FLAG
# -----------
# silent: true  -- items are woven into the queue like non-silent items, BUT:
#                  - Tagged _silent: True on the item dict (written to queue file)
#                  - Tagged _channel_name: <primary channel name> so the OSD
#                    shows the primary channel name instead of the item title
#                  - Coming Up Next skips them (handled in service.py)
#                  - Movie state still advances when they complete (correct)
# silent: false -- standard behaviour, items appear normally in queue and CUN

from __future__ import annotations

import random
from resources.lib.utils.logger import log


# ---------------------------------------------------------------------------
# Public: config normalisation
# ---------------------------------------------------------------------------

def get_sources(channel: dict) -> list:
    """
    Return the list of interleave source configs for *channel*.

    Handles both legacy single-dict format and new list format.
    Returns an empty list when no interleave is configured.
    Each source dict is guaranteed to have:
        channel_id  str
        frequency   int  >= 1
        jitter      int  >= 0
        count_per   int  >= 1
        silent      bool
    """
    raw = channel.get("interleave")
    if not raw:
        return []

    # Legacy single-dict -> wrap in list
    if isinstance(raw, dict):
        raw = [raw]

    sources = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        cid = entry.get("channel_id", "")
        if not cid:
            continue
        sources.append({
            "channel_id":   cid,
            "frequency":    max(1, int(entry.get("frequency",    4))),
            "jitter":       max(0, int(entry.get("jitter",       0))),
            "count_per":    max(1, int(entry.get("count_per",    1))),
            "silent":       bool(entry.get("silent",       False)),
        })
    return sources


_MAX_CYCLE = 60


def cycle_length(channel: dict) -> int:
    """Return how many primary items make one complete interleave cycle.

    A cycle ends exactly when every source has just inserted its items:
    the least common multiple of the sources' frequencies (3 and 4 ->
    12).  Used by the initial queue build so the queue ends on a whole
    cycle instead of a partial group.  Returns 1 when no interleave is
    configured, and falls back to the largest frequency when the common
    multiple would exceed _MAX_CYCLE.  The nominal
    frequencies only set the search step when no source has jitter.
    """
    from math import gcd
    freqs = [s["frequency"] for s in get_sources(channel)]
    if not freqs:
        return 1
    cycle = 1
    for f in freqs:
        cycle = cycle * f // gcd(cycle, f)
        if cycle > _MAX_CYCLE:
            return max(freqs)
    return cycle


def _items_per_fire(source: dict, get_channel_fn) -> int:
    """Items one firing of *source* inserts (mirrors the weaver)."""
    foreign_ch = get_channel_fn(source["channel_id"])
    if foreign_ch and foreign_ch.get("channel_type") == "combo":
        return source["count_per"] * combo_unit_size(foreign_ch)
    return source["count_per"]


def source_rotation_size(source: dict, get_channel_fn) -> int:
    """Items one full round of *source* holds.

    A round-robin TV source hands out its shows in turn (show 1, show 2,
    ... show N, then show 1 again), so a queue only treats every show
    fairly when the number of items taken from the source is a whole
    number of rounds.  Replacements keep each slot on its show, so a
    half-finished round stays unbalanced for as long as the channel
    plays.  Returns the number of shows for a round-robin TV source and 1
    for everything else (folder, movie, combo block, serial TV).
    """
    foreign_ch = get_channel_fn(source["channel_id"])
    if (foreign_ch
            and foreign_ch.get("channel_type") == "tv"
            and foreign_ch.get("playback_mode") != "serial"):
        return max(1, len(foreign_ch.get("shows") or []))
    return 1


def _source_rng(seed, idx):
    """Per-source random generator for a seeded weave (None = global)."""
    if seed is None:
        return None
    return random.Random("{}:{}".format(seed, idx))


def plan_primary_count(channel: dict, queue_size: int, get_channel_fn,
                       minimum: int = 1, seed=None) -> int:
    """Return how many primary items an initial queue should be built from.

    The finished queue (primary + interleaved items) must hold at least
    *queue_size* items and end exactly after an interleaved group, i.e. on
    a complete interleave cycle.  The queue may therefore be larger than
    queue_size, never shorter.  Example: queue_size 10, one combo block of
    2 items every 3 episodes -> 6 primaries -> 3 eps, block, 3 eps, block
    = 10 items.

    *minimum* is the fewest primaries allowed (the caller raises it when
    the show rotation had to build more than planned).

    The count mirrors the weaver exactly: each source is applied in turn
    over everything built so far.  Sources with jitter draw their gaps from
    the same per-source generators the weave will use (*seed*, see
    apply_interleave_list), so the end of the cycle is known in advance;
    pass the same seed to both.

    A round-robin TV source must also have given a whole number of rounds
    of its shows (source_rotation_size): with four shows the queue holds
    4, 8, 12 ... episodes from it, never a half round.
    """
    sources = get_sources(channel)
    rotations = [source_rotation_size(s, get_channel_fn) for s in sources]
    jittery = any(s["jitter"] for s in sources)
    step = 1 if jittery else cycle_length(channel)
    p = step * -(-max(1, minimum) // step)
    for _ in range(5000):
        tokens = ["P"] * p
        on_boundary = True
        for idx, s in enumerate(sources):
            ipf = _items_per_fire(s, get_channel_fn)
            rng = _source_rng(seed, idx) or random
            freq, jit = s["frequency"], s["jitter"]

            def gap():
                if not jit:
                    return freq
                return rng.randint(max(1, freq - jit), freq + jit)

            out, since, next_gap, fires = [], 0, gap(), 0
            for tok in tokens:
                since += 1
                out.append(tok)
                if since >= next_gap:
                    out.extend(["I"] * ipf)
                    fires += 1
                    since = 0
                    next_gap = gap()
            tokens = out
            # A source is on a cycle boundary when it has just fired and
            # has given a whole number of rounds of its shows.
            on_boundary = (on_boundary and since == 0
                           and (fires * ipf) % rotations[idx] == 0)
        if len(tokens) >= queue_size and on_boundary:
            return p
        p += step
    return p


def get_all_foreign_ids(channel: dict) -> list:
    """Return every foreign channel_id referenced by *channel*'s interleave."""
    return [s["channel_id"] for s in get_sources(channel)]


# ---------------------------------------------------------------------------
# Public: runtime counter advancement
# ---------------------------------------------------------------------------

def advance_counters(sources, counters, popped_item=None):
    """
    Pure counter logic — no state I/O.

    Each source tracks:
        count     — real items popped since the last fire
        threshold — the randomly rolled target for the current cycle,
                    set once when the counter resets and held stable
                    until the source fires

    The threshold is rolled ONCE per cycle (at reset time) and never
    changed mid-cycle.  This gives true jitter — every cycle has a
    different random length — without the instability of re-rolling on
    every tick.

    counters format:
        {source_channel_id: {"count": int, "threshold": int}}

    popped_item: the real queue item just removed from the front.
                 Used to determine which show/movie was popped.
                 None is safe — treated as a generic item.

    Returns (updated_counters, fired_sources).
    """
    updated = {}
    fired   = []

    for source in sources:
        cid       = source["channel_id"]
        frequency = source["frequency"]
        jitter    = source["jitter"]

        src = dict(counters.get(cid, {}))

        # If no threshold stored yet (first run or fresh channel),
        # roll one now for the current cycle.
        if "threshold" not in src:
            if jitter == 0:
                src["threshold"] = frequency
            else:
                src["threshold"] = random.randint(
                    max(1, frequency - jitter), frequency + jitter)
            src["count"] = src.get("count", 0)

        src["count"] = src.get("count", 0) + 1
        threshold    = src["threshold"]

        if src["count"] >= threshold:
            fired.append(source)
            # Roll a new threshold for the NEXT cycle now, store at count=0.
            if jitter == 0:
                next_threshold = frequency
            else:
                next_threshold = random.randint(
                    max(1, frequency - jitter), frequency + jitter)
            updated[cid] = {"count": 0, "threshold": next_threshold}
            log("[channels/interleave] counter fired: source='{}' "
                "count={} threshold={} next_threshold={}".format(
                cid[:8], src["count"], threshold, next_threshold))
        else:
            updated[cid] = src
            log("[channels/interleave] counter tick: source='{}' "
                "count={}/{} threshold={}".format(
                cid[:8], src["count"], threshold, threshold))

    return updated, fired


# ---------------------------------------------------------------------------
# Public: queue weaving (all sources -- silent and non-silent)
# ---------------------------------------------------------------------------

TV_MODE_TURNS = "turns"


def tv_slot_takes_turns(slot: dict) -> bool:
    """True for a TV slot with two or more shows set to take turns.

    In that mode each cycle plays one show (``episodes_per_turn`` episodes)
    and the next cycle plays the next show, instead of every show playing
    in every cycle.  A slot with a single show always plays together.
    """
    return (slot.get("source_type", "tv") == "tv"
            and slot.get("tv_mode") == TV_MODE_TURNS
            and len(slot.get("shows") or []) > 1)


def tv_turn_size(slot: dict) -> int:
    """Episodes one show plays on its turn (at least 1)."""
    try:
        return max(1, int(slot.get("episodes_per_turn", 1)))
    except (TypeError, ValueError):
        return 1


def slot_item_count(slot: dict) -> int:
    """Return how many items one Combo Block slot contributes per unit.

    TV slots sum episodes_per_slot over their shows, or, when the shows
    take turns, use episodes_per_turn; Movie slots use movies_per_slot,
    Folder slots use episodes_per_slot (default 1).
    This is the single definition used by the queue builder, the
    interleave engine and the scheduler.
    """
    src = slot.get("source_type", "")
    if src == "tv":
        if tv_slot_takes_turns(slot):
            return tv_turn_size(slot)
        return max(1, sum(
            max(1, int(sh.get("episodes_per_slot", 1)))
            for sh in slot.get("shows", [{"episodes_per_slot": 1}])))
    if src == "movies":
        return max(1, int(slot.get("movies_per_slot", 1)))
    return max(1, int(slot.get("episodes_per_slot", 1)))


def combo_unit_size(combo_ch: dict) -> int:
    """Return the true number of items in one combo block unit.

    Accounts for episodes_per_slot / movies_per_slot on each slot so
    the interleave engine requests and inserts the correct number of
    items per firing — not just len(slots).
    """
    return max(1, sum(slot_item_count(slot)
                      for slot in combo_ch.get("slots", [])))


def apply_interleave_list(queue, channel, get_foreign_items_fn,
                          get_channel_fn, primary_offset=0,
                          out_counters=None, source_offsets=None,
                          seed=None):
    """
    Weave items from ALL interleave sources into *queue*.

    Sources are processed in list order. Each source uses its own
    independent pass so their frequencies are independent of each other.

    get_foreign_items_fn(foreign_id, foreign_ch, needed) -> list
    get_channel_fn(channel_id)                           -> dict | None

    primary_offset: number of primary items already played/queued before
    this batch (used to align the first insertion point correctly on top-ups).
    Ignored for any source whose foreign_id is present in source_offsets.

    source_offsets: optional dict {foreign_id: int} of exact cycle positions
    persisted from a prior weave.  When provided, overrides the primary_offset
    approximation for that source so the weaver knows exactly where in the
    bumper cycle it left off — used by carousel to prevent drift after trim.

    out_counters: optional dict.  When provided, each source's ending cycle
    position (primary_since) is written into it keyed by foreign_id.  The
    caller can then persist these values and pass them back as source_offsets
    on the next top-up.  Only written for sources that actually weave items;
    sources that return early (channel not found, no items) leave any existing
    value in out_counters unchanged.

    Silent sources are woven in the same way as non-silent, but their items
    are tagged _silent: True and _channel_name: <primary channel name> so
    that Coming Up Next can skip them and the OSD can show the channel name.

    seed: optional.  When given, each source draws its jitter gaps from its
    own random.Random seeded from it, so plan_primary_count() can predict
    exactly where the weave will end.  None = the global random module.

    Returns the woven queue.
    """
    if not queue:
        return queue

    sources = get_sources(channel)
    if not sources:
        return queue

    channel_name = channel.get("name", "")
    result = queue
    for idx, source in enumerate(sources):
        result = _weave_single_source(
            result, source, get_foreign_items_fn, get_channel_fn,
            primary_offset, channel_name,
            out_counters=out_counters,
            source_offsets=source_offsets,
            rng=_source_rng(seed, idx))

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _weave_single_source(queue, source, get_foreign_items_fn,
                         get_channel_fn, primary_offset=0,
                         channel_name="", out_counters=None,
                         source_offsets=None, rng=None):
    """
    Weave one source's items into *queue*.

    Silent sources get items tagged _silent: True and
    _channel_name: channel_name for OSD label suppression.

    out_counters: if not None, the ending primary_since value is written
    here keyed by foreign_id after the weave loop completes.

    source_offsets: if not None and foreign_id is present, that value is
    used directly as the starting primary_since instead of computing it
    from primary_offset % frequency.  This eliminates drift after tail trims.
    """
    rng          = rng or random
    foreign_id   = source["channel_id"]
    frequency    = source["frequency"]
    jitter       = source["jitter"]
    count_per    = source["count_per"]
    is_silent    = source["silent"]

    foreign_ch = get_channel_fn(foreign_id)
    if not foreign_ch:
        log("[channels/interleave] source channel {} not found -- "
            "skipping".format(foreign_id))
        return queue

    # Estimate how many foreign items we need.
    # Use source_offsets if available for this source, else approximate
    # from primary_offset.  The estimation uses min_gap (conservative) so
    # we never under-fetch; any unused tagged items are simply not inserted.
    if source_offsets and foreign_id in source_offsets:
        _since = source_offsets[foreign_id]
    else:
        _since = primary_offset % frequency if frequency else 0
    min_gap  = max(1, frequency - jitter)
    # For combo blocks, each firing inserts count_per * unit_size items.
    # unit_size accounts for episodes_per_slot on each slot.
    if foreign_ch.get("channel_type") == "combo":
        items_per_fire = count_per * combo_unit_size(foreign_ch)
    else:
        items_per_fire = count_per
    needed   = 0
    for _ in queue:
        _since += 1
        if _since >= min_gap:
            needed += items_per_fire
            _since = 0
    if needed == 0:
        # No insertions needed this window, but still record where we are
        # in the cycle so the next top-up knows to continue counting from
        # here rather than resetting.  Without this, the caller's
        # weave_counters stays empty and the persisted position is lost,
        # causing the weaver to restart the cycle on the next call.
        if out_counters is not None:
            out_counters[foreign_id] = _since
        return queue
    # NOTE: do NOT multiply needed by count_per here — items_per_fire
    # already incorporates count_per (and num_slots for combo blocks).

    foreign_items = get_foreign_items_fn(foreign_id, foreign_ch, needed)
    if not foreign_items:
        log("[channels/interleave] no items from '{}' -- "
            "skipping".format(foreign_ch.get("name", foreign_id)))
        return queue

    # Tag items
    tagged = []
    for item in foreign_items:
        item = dict(item)
        item["_channel_id"]  = foreign_id
        item["_show_id"]     = (item.get("_show_id")
                                or item.get("show_id", 0))
        item["_interleaved"] = True
        # Preserve per-slot _silent if already set (e.g. combo block slots
        # have individual silent settings). Only apply source-level is_silent
        # if the item doesn't already carry its own flag.
        if "_silent" not in item:
            if is_silent:
                item["_silent"]       = True
                item["_channel_name"] = channel_name
        elif item.get("_silent"):
            # Item is already silent (e.g. a combo slot marked silent=True).
            # Always write _channel_name so the OSD shows the host channel
            # name regardless of whether the source-level silent flag is set.
            item["_channel_name"] = channel_name
        tagged.append(item)

    # Weave.  Use persisted cycle position if available, otherwise derive
    # from primary_offset.
    result        = []
    foreign_index = 0
    if source_offsets and foreign_id in source_offsets:
        primary_since = source_offsets[foreign_id]
    else:
        primary_since = primary_offset % frequency if frequency else 0

    if jitter == 0:
        next_gap = frequency
    else:
        next_gap = rng.randint(max(1, frequency - jitter),
                                  frequency + jitter)

    for primary_item in queue:
        primary_since += 1
        result.append(primary_item)
        if primary_since >= next_gap and foreign_index < len(tagged):
            # For combo blocks, insert count_per complete units per firing.
            # Each unit is combo_unit_size items (accounts for eps_per_slot).
            if foreign_ch.get("channel_type") == "combo":
                insert_count = count_per * combo_unit_size(foreign_ch)
            else:
                insert_count = count_per
            for _ in range(insert_count):
                if foreign_index < len(tagged):
                    result.append(tagged[foreign_index])
                    foreign_index += 1
            primary_since = 0
            if jitter == 0:
                next_gap = frequency
            else:
                next_gap = rng.randint(max(1, frequency - jitter),
                                          frequency + jitter)

    # Record ending cycle position so the caller can persist it and pass
    # it back as source_offsets on the next top-up, eliminating drift.
    if out_counters is not None:
        out_counters[foreign_id] = primary_since

    mode_str = (
        "every {}x{}{}".format(frequency, count_per,
                               " [silent]" if is_silent else "")
        if jitter == 0
        else "every {}+/-{}x{}{} (range {}-{})".format(
            frequency, jitter, count_per,
            " [silent]" if is_silent else "",
            max(1, frequency - jitter), frequency + jitter))
    log("[channels/interleave] wove {} items from '{}' "
        "({}, offset={})".format(
        foreign_index, foreign_ch.get("name", foreign_id),
        mode_str, primary_offset))

    return result
