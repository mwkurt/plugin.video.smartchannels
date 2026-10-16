"""
resources/lib/scheduler.py
===========================
Channel Scheduling manager.

A schedule causes a source channel's content to be prepended to a target
channel's queue at a recurring day/time.  The block plays as the next N
items on the target channel; when the block finishes the regular queue
items resume naturally.

Who fires: only the client that is playing the schedule's target channel.
Schedules and queues live in shared storage, so every client's service
sees every schedule; if any client could fire, a client that merely has
the add-on running (and cannot reach the same folders) would build and
insert the block, and the client actually playing the channel would never
reload for it.  check_all() therefore ignores every schedule whose target
is not the channel the calling client is playing, and does nothing when
the client is playing nothing.  A schedule whose start time has passed
fires on the first 60-second tick after its target channel is playing,
once per calendar day.

Architecture rules
------------------
- This module owns ALL schedule logic: fire decisions, block insertion,
  block completion tracking, last_fired updates.
- channel_manager.py queue-file read/write methods are used for all
  file I/O — no bare file access here.
- service.py calls ScheduleManager().check_all() every 60 seconds
  (same pattern as CarouselManager).
- service.py calls ScheduleManager().on_block_item_complete() from
  its set_now_playing / _check_now_playing logic whenever the target
  channel has an active block.
- player.py, channel_manager.py, and channel builders are untouched
  by this module.

State key
---------
sch_<id>:active_block -> {
    "schedule_id":   str,
    "target_ch_id":  str,
    "source_ch_id":  str,
    "items_played":  int,
    "item_count":    int,
    "inserted_at":   float,
}

schedules.json key structure
-----------------------------
{
  "sch_<uuid>": {
    "id":             "sch_<uuid>",
    "name":           "Tuesday Night Drama",
    "target_channel": "ch_abc123",
    "source_channel": "ch_def456",
    "day":            "tuesday",
    "time":           "21:00",
    "item_count":     4,
    "recurrence":     "weekly",
    "active":         true,
    "last_fired":     1720000000,
    "created":        1720000000
  }
}
"""

from __future__ import annotations

import datetime
import time

from resources.lib.utils.logger import log

# Day-of-week names used in schedule["day"] field.
_WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday", "friday"}
_WEEKENDS = {"saturday", "sunday"}

_DOW_NAMES = [
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
]  # datetime.weekday() 0-6


class ScheduleManager:
    """
    Checks all schedules and fires blocks when the conditions are met.
    Instantiated fresh on each call from service.py so there is no
    shared mutable state between calls — mirrors CarouselManager exactly.
    """

    def check_all(self, channel_manager, now_playing_channel_id=None):
        """
        Called every 60 seconds from service.py tick loop.

        Only schedules whose target channel is the channel this client is
        playing are considered (now_playing_channel_id).  When the client is
        playing nothing (None or empty) nothing is checked and nothing
        fires, so a client that is not playing the target channel can never
        fire its block.

        For each such active schedule:
          1. Is today the right day?
          2. Has the soft-start time passed?
          3. Has it already fired today (last_fired within same calendar day)?
          4. Is there already an active block in progress for this schedule?
          If all checks pass: fire the block.

        fire_block() only writes to the queue file on disk — it does not
        touch Kodi's in-memory playlist.  If the target channel is playing,
        content_changed in _check_now_playing detects the update, reloads
        self._queue, and _handle_end sets _pending_block_reload at the next
        natural item boundary for seamless block insertion.

        now_playing_channel_id: id of the channel this client is playing
        right now, or None/"" when it is playing nothing.  The caller
        (service.py) supplies it only while Kodi is actually playing.

        channel_manager may be None on very early startup — guard and return.

        Returns the set of target channel ids for which a block was fired
        by this call (empty when nothing fired).  The service uses it to
        queue the playlist reload, so it does not depend on what else is
        in state.json (for example blocks left over from earlier runs).
        """
        fired_targets = set()

        if channel_manager is None:
            return fired_targets

        # Only the client playing the target channel may fire its blocks.
        if not now_playing_channel_id:
            return fired_targets

        try:
            schedules = channel_manager.get_all_schedules()
        except Exception as e:
            log("[Scheduler] check_all: could not load schedules: {}".format(e))
            return fired_targets

        if not schedules:
            return fired_targets

        now = datetime.datetime.now()

        for sch_id, schedule in schedules.items():
            if not schedule.get("active", False):
                continue

            # Not the channel this client is playing: another client (or
            # nobody) is responsible for it.
            if schedule.get("target_channel", "") != now_playing_channel_id:
                continue

            try:
                if self._check_schedule(
                        schedule, channel_manager,
                        now, now_playing_channel_id):
                    fired_targets.add(schedule.get("target_channel", ""))
            except Exception as e:
                log("[Scheduler] check_all: error processing schedule "
                    "'{}': {}".format(
                    schedule.get("name", sch_id), e))

        return fired_targets

    def on_block_item_complete(self, schedule_id, channel_manager):
        """
        Called by service.py when an item finishes playing and the
        currently-playing channel has an active schedule block.

        Increments items_played.  When items_played >= item_count the
        block is done and active_block is cleared.  The regular queue
        items behind the block continue playing naturally via Kodi's
        playlist — no queue manipulation needed.
        """
        if channel_manager is None:
            return

        block = channel_manager.get_active_block(schedule_id)
        if not block:
            log("[Scheduler] on_block_item_complete: no active block for "
                "'{}'".format(schedule_id))
            return

        items_played = block.get("items_played", 0) + 1
        item_count   = block.get("item_count", 1)

        log("[Scheduler] block item complete: schedule='{}' "
            "items_played={}/{}".format(
            schedule_id, items_played, item_count))

        if items_played >= item_count:
            log("[Scheduler] block complete for schedule '{}' — "
                "clearing active_block".format(schedule_id))
            channel_manager.clear_active_block(schedule_id)
        else:
            block["items_played"] = items_played
            channel_manager.set_active_block(schedule_id, block)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _check_schedule(self, schedule, channel_manager, now,
                        now_playing_channel_id):
        """Evaluate one schedule and fire its block if all checks pass.

        Returns True when a block was fired (the schedule's last_fired
        changed), False otherwise.
        """
        sch_id      = schedule["id"]
        target_id   = schedule.get("target_channel", "")
        source_id   = schedule.get("source_channel", "")
        name        = schedule.get("name", sch_id)

        if not target_id or not source_id:
            return False

        # 1. Is today the right day?
        if not self._should_fire_today(schedule, now):
            return False

        # 2. Has the soft-start time passed?
        start_time = schedule.get("time", "00:00")
        if not self._time_has_passed(start_time, now):
            log("[Scheduler] '{}': start time '{}' not yet reached".format(
                name, start_time))
            return False

        # 3. Already fired today?
        if self._already_fired_today(schedule, now):
            log("[Scheduler] '{}': already fired today".format(name))
            return False

        # 4. Active block already in progress for this schedule?
        if self._is_block_active(sch_id, channel_manager):
            # Guard against stale active_block keys. Two staleness conditions:
            #
            # a) last_fired == 0: the wizard reset it (time/day/source changed),
            #    meaning the user wants a fresh fire — any existing block is
            #    from a superseded schedule config.
            #
            # b) inserted_at is from a previous calendar day: a real block
            #    cannot span midnight; the block was abandoned (e.g. crash).
            last_fired  = schedule.get("last_fired", 0)
            block       = channel_manager.get_active_block(sch_id)
            inserted_at = block.get("inserted_at", 0) if block else 0
            stale       = False

            if last_fired == 0:
                stale = True
                log("[Scheduler] '{}': clearing stale active_block "
                    "(last_fired reset to 0)".format(name))
            elif inserted_at:
                import datetime as _dt
                inserted_date = _dt.datetime.fromtimestamp(inserted_at).date()
                if inserted_date < now.date():
                    stale = True
                    log("[Scheduler] '{}': clearing stale active_block "
                        "from {} (today is {})".format(
                            name, inserted_date, now.date()))

            if stale:
                channel_manager.clear_active_block(sch_id)
                # Fall through to fire
            else:
                log("[Scheduler] '{}': block already active".format(name))
                return False

        # All checks passed — fire.
        # NOTE: fire_block() only writes to the queue file on disk.
        # It does not touch Kodi's in-memory playlist.  If the channel
        # is currently playing, content_changed in _check_now_playing
        # will detect the queue file update on the next tick, reload
        # self._queue with the block items at front, and _handle_end
        # will set _pending_block_reload at the next natural item
        # boundary — giving seamless block insertion (Option C).
        log("[Scheduler] '{}': all checks passed, firing block".format(name))
        last_fired_before = schedule.get("last_fired", 0)
        self.fire_block(schedule, channel_manager)
        current = channel_manager.get_all_schedules().get(sch_id) or {}
        return current.get("last_fired", last_fired_before) != last_fired_before

    def fire_block(self, schedule, channel_manager):
        """
        Pull item_count items from the source channel queue and prepend
        them to the target channel queue.

        The source channel's queue is treated as a read-advance loop:
        items are taken from the front, and the source queue is written
        back with those items removed (same as if the user had watched
        them on the source channel directly).

        The active_block state key is written so service.py can track
        block item completions.  last_fired is updated and the schedule
        is saved back.
        """
        sch_id     = schedule["id"]
        target_id  = schedule.get("target_channel", "")
        source_id  = schedule.get("source_channel", "")
        item_count = max(1, int(schedule.get("item_count", 4)))
        name       = schedule.get("name", sch_id)

        # Verify channels exist
        target_ch = channel_manager.get_channel(target_id)
        source_ch = channel_manager.get_channel(source_id)
        if not target_ch:
            log("[Scheduler] fire_block: target channel '{}' not "
                "found".format(target_id))
            return
        if not source_ch:
            log("[Scheduler] fire_block: source channel '{}' not "
                "found".format(source_id))
            return

        log("[Scheduler] fire_block: '{}' target={} source={} "
            "count={}".format(name, target_id[:8], source_id[:8], item_count))

        # ── Combo block source path ──────────────────────────────────────────
        # Combo blocks have no queue file — items are built on demand via
        # build_unit() using state keys as the position authority.
        # Never read or write a queue file for a combo source.
        if source_ch.get("channel_type") == "combo":
            from resources.lib.channels.combo import ComboQueueBuilder
            block_items = []
            if not source_ch.get("slots"):
                log("[Scheduler] fire_block: combo source has no slots — aborting")
                return
            # item_count is a number of UNITS.  Each unit is every slot once,
            # in slot order, with each slot's own per-unit count.
            builder = ComboQueueBuilder(channel_manager)
            for _unit in range(item_count):
                try:
                    unit_items = builder.build_unit(
                        source_ch, host_queue=block_items)
                except Exception as _cbe:
                    log("[Scheduler] fire_block: combo build_unit error "
                        "unit={}: {}".format(_unit, _cbe))
                    continue
                for item in unit_items:
                    item = dict(item)
                    item["_schedule_id"] = sch_id
                    item["_channel_id"]  = target_id
                    item["channel_id"]   = target_id
                    block_items.append(item)
            if not block_items:
                log("[Scheduler] fire_block: combo source produced no items — aborting")
                return
            log("[Scheduler] fire_block: combo source built {} items "
                "({} unit(s))".format(len(block_items), item_count))
            # Fall through to target queue write, active_block and last_fired.
            tgt_queue = channel_manager.get_channel_queue(target_id) or []
            new_tgt_queue = block_items + tgt_queue
            try:
                channel_manager.write_channel_queue(target_id, new_tgt_queue)
                log("[Scheduler] fire_block: target queue {} -> {} items "
                    "({} block items prepended)".format(
                    len(tgt_queue), len(new_tgt_queue), len(block_items)))
            except Exception as e:
                log("[Scheduler] fire_block: cannot write target queue: "
                    "{}".format(e))
                return
            block_state = {
                "schedule_id":    sch_id,
                "target_ch_id":   target_id,
                "source_ch_id":   source_id,
                "items_played":   0,
                "item_count":     len(block_items),
                "inserted_at":    time.time(),
            }
            channel_manager.set_active_block(sch_id, block_state)
            schedules = channel_manager.get_all_schedules()
            if sch_id in schedules:
                updated = dict(schedules[sch_id])
                updated["last_fired"] = time.time()
                if schedule.get("recurrence") == "once":
                    updated["active"] = False
                    log("[Scheduler] fire_block: once-only schedule '{}' "
                        "deactivated".format(name))
                channel_manager.update_schedule(sch_id, updated)
            log("[Scheduler] fire_block: block fired for '{}' — {} items "
                "inserted into '{}'".format(
                name, len(block_items),
                channel_manager.get_channel(target_id).get("name", target_id)))
            return

        # ── Regular (non-combo) source path ─────────────────────────────────
        # Read source queue
        try:
            src_queue = channel_manager.get_channel_queue(source_id)
        except Exception as e:
            log("[Scheduler] fire_block: cannot read source queue: "
                "{}".format(e))
            return

        if not src_queue:
            log("[Scheduler] fire_block: source queue empty, "
                "attempting rebuild")
            try:
                src_queue = channel_manager.build_channel_queue(source_ch)
                if src_queue:
                    channel_manager.write_channel_queue(source_id, src_queue)
            except Exception as _tu:
                log("[Scheduler] fire_block: source rebuild failed: "
                    "{}".format(_tu))
            if not src_queue:
                log("[Scheduler] fire_block: source queue still empty, "
                    "aborting")
                return

        # Take items from front of source queue (skip silent interleave items)
        block_items = []
        remaining_src = list(src_queue)
        while remaining_src and len(block_items) < item_count:
            item = remaining_src.pop(0)
            if item.get("_silent", False):
                # Silent interleave items from the source channel should not
                # be injected into a different target channel — skip them.
                continue
            # Tag the item so service.py knows it belongs to this block
            item = dict(item)
            item["_schedule_id"] = sch_id
            item["_channel_id"]  = target_id
            item["channel_id"]   = target_id   # ownership check reads channel_id first
            block_items.append(item)

        if not block_items:
            log("[Scheduler] fire_block: no real items available in "
                "source queue")
            return

        # Write source queue back with consumed items removed, then append
        # one 1-for-1 replacement per consumed item so the source queue
        # stays at its stable size (spec §1.2 — 1 out = 1 in).
        try:
            channel_manager.write_channel_queue(source_id, remaining_src)
            log("[Scheduler] fire_block: source queue {} -> {} items".format(
                len(src_queue), len(remaining_src)))
        except Exception as e:
            log("[Scheduler] fire_block: cannot write source queue: "
                "{}".format(e))
            return

        # 1-for-1 replenishment for each item taken from the source queue.
        # Each consumed item is replaced by the next item from the same
        # channel rotation so the source channel does not shrink.
        replenished = 0
        for consumed in block_items:
            # block_items have _channel_id rewritten to target_id — use
            # a clean copy with the original source channel_id for the
            # cursor lookup.
            original_item = dict(consumed)
            original_item["channel_id"]  = source_id
            original_item["_channel_id"] = source_id
            try:
                replacement = channel_manager.get_one_replacement(
                    source_id, original_item, current_queue=remaining_src)
                if replacement:
                    remaining_src.append(replacement)
                    replenished += 1
            except Exception as _re:
                log("[Scheduler] fire_block: replacement error for '{}': {}".format(
                    consumed.get("title", "?"), _re))
        if replenished:
            try:
                channel_manager.write_channel_queue(source_id, remaining_src)
                log("[Scheduler] fire_block: source replenished {} item(s) "
                    "-- queue now {} items".format(replenished, len(remaining_src)))
            except Exception as _we:
                log("[Scheduler] fire_block: cannot write replenished source "
                    "queue: {}".format(_we))

        # Read target queue and prepend block items
        try:
            tgt_queue = channel_manager.get_channel_queue(target_id)
        except Exception as e:
            log("[Scheduler] fire_block: cannot read target queue: "
                "{}".format(e))
            return

        new_tgt_queue = block_items + tgt_queue
        try:
            channel_manager.write_channel_queue(target_id, new_tgt_queue)
            log("[Scheduler] fire_block: target queue {} -> {} items "
                "({} block items prepended)".format(
                len(tgt_queue), len(new_tgt_queue), len(block_items)))
        except Exception as e:
            log("[Scheduler] fire_block: cannot write target queue: "
                "{}".format(e))
            return

        # Write active_block state
        block_state = {
            "schedule_id":    sch_id,
            "target_ch_id":   target_id,
            "source_ch_id":   source_id,
            "items_played":   0,
            "item_count":     len(block_items),
            "inserted_at":    time.time(),
        }
        channel_manager.set_active_block(sch_id, block_state)

        # Update last_fired and deactivate once-only schedules.
        # Uses update_schedule() — channel_manager owns all schedules.json I/O.
        schedules = channel_manager.get_all_schedules()
        if sch_id in schedules:
            updated = dict(schedules[sch_id])
            updated["last_fired"] = time.time()
            if schedule.get("recurrence") == "once":
                updated["active"] = False
                log("[Scheduler] fire_block: once-only schedule '{}' "
                    "deactivated".format(name))
            channel_manager.update_schedule(sch_id, updated)

        log("[Scheduler] fire_block: block fired for '{}' — "
            "{} items inserted into '{}'".format(
            name, len(block_items),
            target_ch.get("name", target_id)))

    # ------------------------------------------------------------------
    # Predicates
    # ------------------------------------------------------------------

    def _should_fire_today(self, schedule, now=None) -> bool:
        """
        Return True if the schedule's day/recurrence includes today.
        now: datetime.datetime.  Uses current time if not provided.
        """
        if now is None:
            now = datetime.datetime.now()

        day_str = schedule.get("day", "").lower()
        dow     = now.weekday()   # 0=Monday, 6=Sunday
        today   = _DOW_NAMES[dow]

        if day_str == "daily":
            return True
        if day_str == "weekdays":
            return today in _WEEKDAYS
        if day_str == "weekends":
            return today in _WEEKENDS
        if day_str == "once":
            # If a specific fire_date was set in the wizard, check it.
            # fire_date is stored as "DD/MM/YYYY".  Empty string (schedules
            # created before 1.1.9t) falls back to the old behaviour: fire
            # on whatever day the start time is next reached.
            fire_date = schedule.get("fire_date", "")
            if not fire_date:
                return True  # legacy / no date set — fire any day
            try:
                day_s, mon_s, yr_s = fire_date.split("/")
                target_date = datetime.date(int(yr_s), int(mon_s), int(day_s))
                return now.date() == target_date
            except Exception:
                return True  # malformed date — fail open
        # Specific day name
        return day_str == today

    def _time_has_passed(self, time_str, now=None) -> bool:
        """Return True if HH:MM wall time has been reached today."""
        if now is None:
            now = datetime.datetime.now()
        try:
            h, m = (int(x) for x in time_str.split(":"))
            target = now.replace(hour=h, minute=m, second=0, microsecond=0)
            return now >= target
        except Exception:
            return False

    def _already_fired_today(self, schedule, now=None) -> bool:
        """
        Return True if last_fired timestamp is within the current
        calendar day (midnight-to-midnight local time).
        """
        if now is None:
            now = datetime.datetime.now()
        last = schedule.get("last_fired")
        if not last:
            return False
        last_dt = datetime.datetime.fromtimestamp(last)
        return last_dt.date() == now.date()

    def _is_block_active(self, schedule_id, channel_manager) -> bool:
        """Return True if sch_<id>:active_block exists in state.json."""
        return channel_manager.get_active_block(schedule_id) is not None

    # ------------------------------------------------------------------
    # Public helper: find the active block for a given target channel
    # (used by service.py to check all schedules for a channel)
    # ------------------------------------------------------------------
