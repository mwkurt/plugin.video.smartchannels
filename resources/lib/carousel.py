# plugin.video.smartchannels
# resources/lib/carousel.py
#
# OWNS:   Carousel pop logic.  Called from the service.py tick loop only.
#
# RULES (all absolute, spec §9):
#   - One item popped at a time, regardless of item type.
#   - Timed mode:    timer fires every N minutes, pops pop_count items.
#   - Duration mode: pops when elapsed time >= queue-front item's duration.
#   - Every pop fires the standard 1-for-1 replacement rule (§7.3).
#   - last_pop_time updated on every pop regardless of item type.
#   - last_popped_show updated ONLY when a primary TV item is popped.
#   - NO sweep logic.  NO atomic combo unit popping.  NO adjacent removal.
#   - carousel_live_join REMOVED in 3.0.0 (spec Appendix A).
#
# PORTED FROM 2.x (compatible with 1-for-1, no spec conflict):
#   1.  Skip currently-playing channel — watching it IS the drift.
#   2.  Skip active schedule source channels — concurrent pop + scheduler
#       would double-drain the source queue.
#   3.  Timed mode: catch-up for multiple missed intervals (Kodi was off).
#   4.  Timed mode: last_pop_time is None guard → init clock, return.
#   5.  Duration mode: catch-up loop (pop N items if Kodi was off for hours).
#   7.  Duration mode: last_pop_time is None guard → init clock, return.
#   8.  Abort pop if replacement returns nothing (library temporarily down).
#   9.  Clear resume position for each popped item.
#   10. Channel type guard: only "tv" and "movies" channels are eligible.
#
# NOT PORTED FROM 2.x (conflict with 3.x 1-for-1 / spec §9.1):
#   - Batch top-up / topup_carousel_queue  → replaced by 1-for-1
#   - Trailing sweep / atomic combo unit pop → spec §9.1: one item at a time
#   - Combo-aware duration summing          → spec §9.1: queue-front item only
#   - interleave_counters in carousel state → eliminated
#
# CRITICAL — ONE MANAGER PER TICK CALL:
#   A single ChannelManager instance must be used for the entire pop/replace
#   cycle.  Multiple _get_manager() calls each create a fresh instance with
#   their own in-memory state copy.  A later _save_state() clobbers state
#   written by an earlier one, causing tv_next_ep to regress and the same
#   episode to repeat forever.
#
# Called by: service.py _tick_carousel() ONLY.
# spec §9, §26 Phase 3
# Version: 3.0.0

from __future__ import annotations

import time
from typing import Optional

import xbmc

from resources.lib.utils.logger import log

# Minimum carousel interval enforced by the wizard (minutes).
CAROUSEL_MIN_INTERVAL = 1


# ---------------------------------------------------------------------------
# Public entry point — called every 60 s from service.py tick loop
# ---------------------------------------------------------------------------

def tick_carousel(player) -> None:
    """Check every carousel-enabled channel and pop if the interval has elapsed.

    Ported from 2.x: skips the currently-playing channel (watching it IS the
    drift) and skips channels that are active schedule sources (concurrent
    carousel + scheduler would double-drain the source queue).

    ONE manager for the entire tick so state written by combo slot replacement
    is never clobbered by a subsequent _save_state() from a different instance.
    spec §9.1, §9.2
    """
    manager = player._get_manager()

    try:
        channels = manager.get_all_channels()
    except Exception as exc:
        log("[carousel] tick_carousel: get_all_channels error: {}".format(exc),
            level=xbmc.LOGWARNING)
        return

    # Build set of channel IDs that are active schedule sources so we can
    # skip them.  A carousel pop on a schedule source would double-drain it.
    # Ported from 2.x check_all().
    source_channel_ids: set = set()
    try:
        schedules = manager.get_all_schedules() or {}
        for sch in schedules.values():
            if sch.get("active", False):
                src = sch.get("source_channel_id") or sch.get("source_channel", "")
                if src:
                    source_channel_ids.add(src)
    except Exception as exc:
        log("[carousel] tick_carousel: could not read schedules "
            "(source-channel guard skipped): {}".format(exc))

    now = time.time()
    for channel in channels:
        if not channel.get("carousel_enabled", False):
            continue

        # Channel type guard — ported from 2.x.  Only tv, movies and folder are eligible.
        if channel.get("channel_type", "tv") not in ("tv", "movies", "folder"):
            continue

        channel_id = channel["id"]

        # Skip the channel currently playing — watching it IS the drift.
        if channel_id == player._channel_id:
            log("[carousel] '{}': skipping — currently playing".format(
                channel.get("name", channel_id)), xbmc.LOGDEBUG)
            continue

        # Skip a channel another device is playing — its owner is the only
        # one allowed to change that queue.  (3.1.109)
        if manager.channel_lock_holder(channel_id):
            log("[carousel] '{}': skipping — playing on another device".format(
                channel.get("name", channel_id)), xbmc.LOGDEBUG)
            continue

        # Skip active schedule source channels.
        if channel_id in source_channel_ids:
            log("[carousel] '{}': skipping — active schedule source".format(
                channel.get("name", channel_id)), xbmc.LOGDEBUG)
            continue

        try:
            _check_channel(player, manager, channel, channel_id, now)
        except Exception as exc:
            log("[carousel] tick_carousel: error on '{}': {}".format(
                channel.get("name", channel_id), exc),
                level=xbmc.LOGWARNING)


# ---------------------------------------------------------------------------
# Per-channel carousel check
# ---------------------------------------------------------------------------

def _check_channel(player, manager, channel: dict,
                   channel_id: str, now: float) -> None:
    """Dispatch to timed or duration mode."""
    mode = channel.get("carousel_mode", "timed")
    if mode == "duration":
        _check_duration_mode(player, manager, channel, channel_id, now)
    else:
        _check_timed_mode(player, manager, channel, channel_id, now)


# ---------------------------------------------------------------------------
# Timed mode
# ---------------------------------------------------------------------------

def _check_timed_mode(player, manager, channel: dict,
                      channel_id: str, now: float) -> None:
    """Pop items from the queue front if the fixed interval has elapsed.

    Ported from 2.x _maybe_pop_timed():
    - last_pop_time is None on first run → init clock, return (no immediate pop).
    - Catch-up: if Kodi was off for multiple intervals, pop for each missed one.
    spec §9.1
    """
    interval_min = max(CAROUSEL_MIN_INTERVAL,
                       int(channel.get("carousel_interval", 60)))
    interval_sec = interval_min * 60
    pop_count    = max(1, int(channel.get("carousel_pop_count", 1)))

    cs       = manager.get_carousel_state(channel_id)
    last_pop = cs.get("last_pop_time")

    # First-run guard — init clock, do not pop immediately.
    # (create_channel also sets this, but guard here covers manual state wipes.)
    if last_pop is None:
        log("[carousel] '{}': timed first run — initialising clock".format(
            channel.get("name", channel_id)))
        cs["last_pop_time"] = now
        manager.set_carousel_state(channel_id, cs)
        return

    elapsed = now - last_pop
    log("[carousel] '{}' timed: elapsed={:.0f}s interval={}s".format(
        channel.get("name", channel_id), elapsed, interval_sec),
        xbmc.LOGDEBUG)

    if elapsed < interval_sec:
        return

    # Catch-up: how many full intervals have elapsed?
    intervals_due = int(elapsed // interval_sec)
    total_to_pop  = pop_count * intervals_due
    new_last_pop  = last_pop + interval_sec * intervals_due

    log("[carousel] '{}': {:.0f}s elapsed ({} interval(s) due), "
        "popping {} item(s)".format(
            channel.get("name", channel_id),
            elapsed, intervals_due, total_to_pop), xbmc.LOGDEBUG)

    _do_pops(player, manager, channel, channel_id, total_to_pop,
             new_last_pop, "timed")


# ---------------------------------------------------------------------------
# Duration mode
# ---------------------------------------------------------------------------

def _check_duration_mode(player, manager, channel: dict,
                          channel_id: str, now: float) -> None:
    """Pop when elapsed time >= queue-front item's duration.

    Ported from 2.x _maybe_pop_duration():
    - last_pop_time is None on first run → init clock, return.
    - Catch-up loop: pop one item at a time until elapsed < current duration.
    spec §9.1
    """
    cs       = manager.get_carousel_state(channel_id)
    last_pop = cs.get("last_pop_time")

    queue = manager.get_channel_queue(channel_id)
    if not queue:
        log("[carousel] '{}' duration: queue empty".format(
            channel.get("name", channel_id)))
        return

    # Duration of the current queue-front item (spec §9.1: one item at a time,
    # no combo-aware summing).
    front_duration = _front_item_duration(queue)
    if front_duration <= 0:
        log("[carousel] '{}' duration: queue front has no duration — "
            "skipping".format(channel.get("name", channel_id)))
        return

    # First-run guard.
    if last_pop is None:
        log("[carousel] '{}': duration first run — initialising clock "
            "(front duration={}s)".format(
                channel.get("name", channel_id), front_duration))
        cs["last_pop_time"] = now
        manager.set_carousel_state(channel_id, cs)
        return

    elapsed = now - last_pop
    log("[carousel] '{}' duration: elapsed={:.0f}s front_duration={}s".format(
        channel.get("name", channel_id), elapsed, front_duration))

    if elapsed < front_duration:
        return

    # Catch-up loop — pop one item at a time.
    # Walk a working copy of the queue to track durations without mutating disk.
    work_queue   = list(queue)
    new_last_pop = last_pop
    total_to_pop = 0
    while True:
        if not work_queue:
            break

        cur_duration = _front_item_duration(work_queue)
        if cur_duration <= 0:
            log("[carousel] '{}' duration: next item has no duration — "
                "stopping catch-up".format(channel.get("name", channel_id)))
            break

        if (now - new_last_pop) < cur_duration:
            break

        # Safety floor — stop before draining too low.
        # Advance working queue by 1 real item (skipping leading silents).
        while work_queue and work_queue[0].get("_silent", False):
            work_queue.pop(0)
        if work_queue:
            work_queue.pop(0)

        new_last_pop += cur_duration
        total_to_pop += 1

    if total_to_pop == 0:
        return

    log("[carousel] '{}' duration: catch-up popping {} item(s)".format(
        channel.get("name", channel_id), total_to_pop))

    _do_pops(player, manager, channel, channel_id, total_to_pop,
             new_last_pop, "duration")


# ---------------------------------------------------------------------------
# Pop execution
# ---------------------------------------------------------------------------

def _do_pops(player, manager, channel: dict, channel_id: str,
             count: int, new_last_pop: float, mode: str) -> None:
    """Pop ``count`` items from the queue front, one at a time.

    For each pop:
      1. Read queue from disk.
      3. Remove item from queue front.
      4. Apply 1-for-1 replacement.
      5. Write updated queue to disk (only on successful replacement).
      6. Update carousel state.

    Ported from 2.x: abort pop if replacement returns nothing (library down).
    Ported from 2.x: clear resume position for each popped item.
    ONE manager throughout — never call player._get_manager() again here.
    spec §9.1, §9.2
    """
    # Multi-client guard: re-read carousel state before committing any writes.
    # If last_pop_time has already reached new_last_pop, another client on
    # shared storage handled this interval — nothing to do.
    fresh_cs = manager.get_carousel_state(channel_id)
    if fresh_cs.get("last_pop_time", 0) >= new_last_pop:
        log("[carousel] '{}' [{}]: last_pop_time already at {:.0f} — "
            "another client popped, skipping".format(
                channel.get("name", channel_id), mode,
                fresh_cs.get("last_pop_time", 0)))
        return

    for i in range(count):
        queue = manager.get_channel_queue(channel_id)
        if not queue:
            log("[carousel] '{}': queue empty after {} pop(s)".format(
                channel.get("name", channel_id), i))
            break

        popped_item = queue.pop(0)
        title    = popped_item.get("title") or popped_item.get("tvshowtitle", "?")
        is_block = bool(popped_item.get("_schedule_id"))

        log("[carousel] '{}' [{}]: popping item {} of {} -- '{}'{}" .format(
            channel.get("name", channel_id), mode, i + 1, count, title,
            " [scheduled block]" if is_block else ""))

        # Clear saved resume position for the popped item.
        try:
            manager.clear_resume_position(
                channel_id, popped_item.get("file", ""))
        except Exception as exc:
            log("[carousel] could not clear resume for '{}': {}".format(
                title, exc))

        if is_block:
            # Scheduled block items (_schedule_id): pop without replacement.
            # The queue shrinks by 1 permanently for this item.
            # Interleaved items (_interleaved=True) do NOT have _schedule_id
            # and always go through normal 1-for-1 replacement below.
            sch_id = popped_item["_schedule_id"]
            try:
                from resources.lib.scheduler import ScheduleManager
                ScheduleManager().on_block_item_complete(sch_id, manager)
                log("[carousel] block item consumed via carousel "
                    "(schedule='{}')".format(sch_id[:8]))
            except Exception as _bce:
                log("[carousel] on_block_item_complete error: {}".format(_bce))
            manager.write_channel_queue(channel_id, queue)
            cs = manager.get_carousel_state(channel_id)
            cs["last_pop_time"] = new_last_pop
            manager.set_carousel_state(channel_id, cs)
            log("[carousel] '{}': block pop complete. queue depth now {}".format(
                channel.get("name", channel_id), len(queue)), xbmc.LOGDEBUG)
            if player._channel_id == channel_id:
                player._queue = queue
            continue

        # 1-for-1 replacement for regular and interleaved items.
        q_before = len(queue)
        last_popped_show = _apply_replacement(
            manager, channel, channel_id, popped_item, queue)

        # Abort pop if replacement returned nothing (library temporarily down).
        if len(queue) <= q_before:
            log("[carousel] '{}': replacement returned nothing -- "
                "aborting pop, queue unchanged".format(
                    channel.get("name", channel_id)),
                level=xbmc.LOGWARNING)
            break

        # Write updated queue only after successful replacement.
        manager.write_channel_queue(channel_id, queue)

        # Update carousel state.
        cs = manager.get_carousel_state(channel_id)
        cs["last_pop_time"] = new_last_pop
        if last_popped_show is not None:
            cs["last_popped_show"] = last_popped_show
        manager.set_carousel_state(channel_id, cs)

        log("[carousel] '{}': pop complete. queue depth now {}".format(
            channel.get("name", channel_id), len(queue)), xbmc.LOGDEBUG)

        # Keep player's in-memory queue in sync if this is the active channel.
        if player._channel_id == channel_id:
            player._queue = queue


# ---------------------------------------------------------------------------
# 1-for-1 replacement logic (carousel variant, spec §7.3 / §9.2)
# ---------------------------------------------------------------------------

def _apply_replacement(manager, channel: dict, channel_id: str,
                        popped_item: dict, queue: list) -> Optional[int]:
    """Apply the 1-for-1 replacement rule for a carousel-popped item.

    Mutates ``queue`` (appends the replacement).
    Returns the tvshowid if a primary TV item was popped (updates
    last_popped_show), else None.
    spec §9.2
    """
    last_popped_show: Optional[int] = None
    consumed_cid = (popped_item.get("_channel_id")
                    or popped_item.get("channel_id", ""))

    if manager.is_combo_channel(consumed_cid):
        _handle_combo_slot_pop(manager, channel_id, popped_item,
                               consumed_cid, queue)
        # last_popped_show stays None — combo pops never update it (§9.3).
    else:
        ctype = channel.get("channel_type", "tv")
        if ctype == "tv" and not popped_item.get("_interleaved"):
            # Primary TV item — same-show carousel replacement (§8.5, §9.2).
            show_id = popped_item.get("show_id") or popped_item.get("_show_id")
            if show_id:
                replacement = manager.get_carousel_replacement(
                    channel_id, int(show_id))
                if replacement:
                    # Skip if this episode is already in the queue — the
                    # initial build may have placed it there already.
                    ep_id = replacement.get("episodeid", -1)
                    already_in_queue = any(
                        item.get("episodeid") == ep_id
                        for item in queue if ep_id > 0)
                    if already_in_queue:
                        log("[carousel] carousel_replacement: ep {} already "
                            "in queue — advancing one more".format(ep_id))
                        replacement = manager.get_carousel_replacement(
                            channel_id, int(show_id))
                    if replacement:
                        queue.append(replacement)
                        log("[carousel] carousel_replacement: appended next ep "
                            "of show_id={} — '{}'".format(
                                show_id, replacement.get("title", "?")),
                            xbmc.LOGDEBUG)
                else:
                    log("[carousel] carousel_replacement: no ep for "
                        "show_id={}".format(show_id),
                        level=xbmc.LOGWARNING)
                last_popped_show = int(show_id)
            else:
                replacement = manager.get_one_replacement(
                    channel_id, popped_item)
                if replacement:
                    queue.append(replacement)
        else:
            replacement = manager.get_one_replacement(
                channel_id, popped_item, current_queue=queue)
            if replacement:
                queue.append(replacement)
                log("[carousel] generic replacement: '{}'".format(
                    replacement.get("title", "?")))
            else:
                log("[carousel] no replacement for '{}'".format(
                    popped_item.get("title", "?")),
                    level=xbmc.LOGWARNING)

    return last_popped_show


def _handle_combo_slot_pop(manager, channel_id: str, popped_item: dict,
                            consumed_cid: str, queue: list) -> None:
    """1-for-1 replacement for a carousel-popped combo slot item.

    Uses the same shared manager — never calls player._get_manager().
    spec §7.3, §9.2, §11.1
    """
    consumed_slot_id = popped_item.get("_combo_slot", "")
    combo_ch = manager.get_channel(consumed_cid)
    if not combo_ch:
        log("[carousel] combo replacement: channel {} not found".format(
            consumed_cid), level=xbmc.LOGWARNING)
        return

    slots = combo_ch.get("slots", [])
    slot_index = next(
        (i for i, s in enumerate(slots)
         if s.get("slot_id", "") == consumed_slot_id), None)

    if slot_index is None:
        log("[carousel] combo replacement: slot {} not found in {}".format(
            consumed_slot_id[:8], consumed_cid[-8:]),
            level=xbmc.LOGWARNING)
        return

    from resources.lib.channels.combo import ComboQueueBuilder
    new_items = ComboQueueBuilder(manager).build_one_slot(
        combo_ch, slot_index, host_queue=queue)
    if new_items:
        queue.extend(new_items)
        log("[carousel] combo 1-for-1: slot {} → '{}'".format(
            slot_index, new_items[0].get("title", "?")))
    else:
        log("[carousel] combo replacement: no item for slot {} "
            "(exhausted?)".format(slot_index), level=xbmc.LOGWARNING)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _front_item_duration(queue: list) -> int:
    """Return the duration (seconds) of the first item in queue with duration>0.

    Spec §9.1: use the queue-front item's own duration — no combo-aware summing.
    """
    for item in queue:
        d = item.get("duration", 0) or 0
        if d > 0:
            return int(d)
    return 0


# ---------------------------------------------------------------------------
# Guard helpers — used by wizard / UI to enforce carousel constraints (§9.4)
# ---------------------------------------------------------------------------
