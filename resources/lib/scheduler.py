"""
resources/lib/scheduler.py
===========================
Channel Scheduling manager.

A schedule causes a source channel's content to be prepended to a target
channel's queue at a recurring day/time.  The block plays as the next N
items on the target channel; when the block finishes the regular queue
items resume naturally.

Who fires (3.1.115): a schedule fires once per day, when its start time has
passed (no upper limit), on one device:
  - the device playing the target channel, or
  - when no device is playing it, any device running the add-on on the same
    shared folder.
Before building the block the device claims the schedule
(ChannelManager.claim_schedule_fire); only the device whose claim stands
fires, and last_fired then keeps every other device off for the day.
A device never fires a channel another device is playing.

One block at a time per channel: while ANY item tagged with a schedule id is
still in the target channel's queue file, every other schedule for that
channel is skipped for the day (a repeating schedule tries again on its next
day; a once-only schedule is switched off).  The block items sit in the queue
untouched until they are watched, skipped by the user, or - on a carousel
channel that is not playing - popped by the carousel.  When several schedules
are due together the earliest start time goes first.

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

from resources.lib.utils import journal
from resources.lib.utils.logger import log

# Day-of-week names used in schedule["day"] field.
_WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday", "friday"}
_WEEKENDS = {"saturday", "sunday"}

_DOW_NAMES = [
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
]  # datetime.weekday() 0-6


# Waiting/skipping reasons already logged: (schedule id, date, text).  The
# check runs every minute, so a reason that does not change is logged once
# per schedule and day.  (3.1.116)
_NOTED = set()


def _note_once(sch_id, text):
    """Log a scheduler decision once per schedule and day."""
    key = (sch_id, datetime.date.today().isoformat(), text)
    if key in _NOTED:
        return
    _NOTED.add(key)
    log("[Scheduler] {}".format(text))


def _log_block_items(name, block_items):
    """Log every item of a block just built: position, title, show (or kind)
    and combo slot.  The queue file shows this only until the items are
    played, so the log keeps the record.  (3.1.116)"""
    total = len(block_items)
    for pos, item in enumerate(block_items, 1):
        show = item.get("tvshowtitle") or (
            "movie" if item.get("is_movie") else "folder item")
        log("[Scheduler] fire_block: '{}' item {}/{}: '{}' - {} (slot {}, "
            "{}s)".format(
            name, pos, total, item.get("title", "?"), show,
            str(item.get("_combo_slot", "-"))[:8],
            int(item.get("duration", 0) or 0)))


def _slot_start(schedule, now=None):
    """Timestamp of the schedule's start time today (the start of its slot).

    The slot of a block begins at the schedule's start time, not when the
    block was actually built, so a late fire is caught up from the right
    moment.  Falls back to ``now`` when the time cannot be read.  (3.1.155)
    """
    now = time.time() if now is None else now
    try:
        hh, mm = str(schedule.get("time", "")).split(":")
        day = datetime.datetime.fromtimestamp(now).date()
        return datetime.datetime.combine(
            day, datetime.time(int(hh), int(mm))).timestamp()
    except (ValueError, TypeError):
        return now


def _new_block_state(schedule, target_id, source_id, block_items, channel_manager):
    """The active_block record written when a block is fired.  Besides the
    counts it holds the slot start and every item's running time (by block
    sequence), which block expiry needs.  (3.1.155)"""
    durations = []
    for item in block_items:
        dur = int(item.get("duration", 0) or 0)
        durations.append(dur if dur > 0
                         else channel_manager.default_item_seconds(item))
    return {
        "schedule_id":    schedule["id"],
        "target_ch_id":   target_id,
        "source_ch_id":   source_id,
        "items_played":   0,
        "item_count":     len(block_items),
        "inserted_at":    time.time(),
        "slot_start":     _slot_start(schedule),
        "durations":      durations,
    }


class ScheduleManager:
    """
    Checks all schedules and fires blocks when the conditions are met.
    Instantiated fresh on each call from service.py so there is no
    shared mutable state between calls — mirrors CarouselManager exactly.
    """

    def check_all(self, channel_manager, now_playing_channel_id=None):
        """
        Called every 60 seconds from service.py tick loop.

        Looks at every active schedule that is due: today is its day, its
        start time has passed and it has not fired today.  Due schedules are
        taken earliest start time first; for each one _check_schedule()
        decides whether this device fires it.

        now_playing_channel_id: id of the channel this client is playing
        right now, or None/"" when it is playing nothing.  A schedule whose
        target another device is playing is left to that device.

        fire_block() only writes to the queue file on disk — it does not
        touch Kodi's in-memory playlist.  If the target channel is playing
        here, content_changed in _check_now_playing detects the update,
        reloads self._queue, and _handle_end sets _pending_block_reload at
        the next natural item boundary for seamless block insertion.

        channel_manager may be None on very early startup — guard and return.

        Returns the set of target channel ids for which a block was fired
        by this call (empty when nothing fired).  The service uses it to
        queue the playlist reload, so it does not depend on what else is
        in state.json (for example blocks left over from earlier runs).
        """
        fired_targets = set()

        if channel_manager is None:
            return fired_targets

        try:
            schedules = channel_manager.get_all_schedules()
        except Exception as e:
            log("[Scheduler] check_all: could not load schedules: {}".format(e))
            return fired_targets

        if not schedules:
            return fired_targets

        now = datetime.datetime.now()

        due = []
        for sch_id, schedule in schedules.items():
            if not schedule.get("active", False):
                continue
            if not schedule.get("target_channel") \
                    or not schedule.get("source_channel"):
                continue
            if not self._should_fire_today(schedule, now):
                continue
            if not self._time_has_passed(schedule.get("time", "00:00"), now):
                continue
            if self._already_fired_today(schedule, now):
                _note_once(
                    schedule.get("id", ""),
                    "'{}': already fired today by {} - nothing to do "
                    "here".format(
                        schedule.get("name", schedule.get("id", "?")),
                        schedule.get("last_fired_by") or "another device"))
                continue
            due.append(schedule)

        # Earliest start time first: it is "first in line" for its channel.
        due.sort(key=lambda s: (s.get("time", "00:00"), s.get("name", "")))

        for schedule in due:
            try:
                if self._check_schedule(
                        schedule, channel_manager,
                        now, now_playing_channel_id):
                    fired_targets.add(schedule.get("target_channel", ""))
            except Exception as e:
                log("[Scheduler] check_all: error processing schedule "
                    "'{}': {}".format(
                    schedule.get("name", schedule.get("id", "?")), e))

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
                "'{}' (device {})".format(
                schedule_id, channel_manager.get_device_label()))
            return

        items_played = block.get("items_played", 0) + 1
        item_count   = block.get("item_count", 1)

        log("[Scheduler] block item complete: schedule='{}' "
            "items_played={}/{} (device {})".format(
            schedule_id, items_played, item_count,
            channel_manager.get_device_label()))

        if items_played >= item_count:
            log("[Scheduler] block complete for schedule '{}' — "
                "clearing active_block (device {})".format(
                schedule_id, channel_manager.get_device_label()))
            channel_manager.clear_active_block(schedule_id)
        else:
            block["items_played"] = items_played
            channel_manager.set_active_block(schedule_id, block)

    def expire_blocks(self, channel_manager, now_playing_channel_id=None,
                      now=None):
        """Remove scheduled-block items whose time slot has ended.  (3.1.155)

        Only when the block_expiry setting is on.  A block's slot starts at
        the schedule's start time; item N's slot ends after the running
        times of items 1..N.  An item whose slot has ended is taken out of
        the queue (no replacement) and counted as complete.  A channel this
        device is playing and a channel another device holds are left alone.
        A block from before the upgrade (no slot yet) gets its slot at the
        first pass.  Called about once a minute from service.py.
        Returns the number of items removed.
        """
        if channel_manager is None or not channel_manager.block_expiry_enabled():
            return 0
        now = time.time() if now is None else now
        removed_total = 0
        try:
            schedules = channel_manager.get_all_schedules()
        except Exception as e:
            log("[Scheduler] expire_blocks: could not load schedules: "
                "{}".format(e))
            return 0
        for sch_id, schedule in list(schedules.items()):
            try:
                removed_total += self._expire_one(
                    sch_id, schedule, channel_manager,
                    now_playing_channel_id, now)
            except Exception as e:
                log("[Scheduler] expire_blocks: error on '{}': {}".format(
                    schedule.get("name", sch_id), e))
        return removed_total

    def _expire_one(self, sch_id, schedule, channel_manager,
                    now_playing_channel_id, now):
        block = channel_manager.get_active_block(sch_id)
        if not block:
            return 0
        target_id = block.get("target_ch_id") or schedule.get("target_channel", "")
        if not target_id or target_id == now_playing_channel_id:
            return 0
        if channel_manager.channel_lock_holder(target_id):
            return 0
        queue = channel_manager.read_channel_queue(target_id)
        if not queue:
            return 0
        items = {it.get("_block_seq"): it for it in queue
                 if it.get("_schedule_id") == sch_id}
        if not items:
            return 0

        durations = block.get("durations")
        if block.get("slot_start") is None or not durations:
            # Block from before the upgrade: its slot starts now, with the
            # items still in the queue.
            seqs = sorted(s for s in items if isinstance(s, int))
            durations = [0] * (max(seqs) + 1 if seqs else 0)
            for seq in seqs:
                it = items[seq]
                dur = int(it.get("duration", 0) or 0)
                durations[seq] = dur if dur > 0 \
                    else channel_manager.default_item_seconds(it)
            block = dict(block)
            block["slot_start"] = now
            block["durations"]  = durations
            channel_manager.set_active_block(sch_id, block)
            log("[Scheduler] '{}': block slot starts now (block from "
                "before block expiry)".format(schedule.get("name", sch_id)))
            return 0

        end = float(block["slot_start"])
        due = []
        for seq, dur in enumerate(durations):
            end += dur
            if seq in items and end <= now:
                due.append(seq)
        if not due:
            return 0
        removed = channel_manager.remove_block_items(target_id, sch_id, due)
        if not removed:
            return 0
        journal.record("block_expired",
                       ch=channel_manager.journal_channel_name(target_id),
                       schedule=schedule.get("name", sch_id), n=len(removed),
                       items=[journal.item_summary(i) for i in removed])
        log("[Scheduler] '{}': {} block item(s) removed - their time slot "
            "has ended".format(schedule.get("name", sch_id), len(removed)))
        for _ in removed:
            self.on_block_item_complete(sch_id, channel_manager)
        return len(removed)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _check_schedule(self, schedule, channel_manager, now,
                        now_playing_channel_id):
        """Decide whether this device fires one DUE schedule, and fire it.

        check_all() has already established that the schedule is active, due
        today and not yet fired today.  Returns True when a block was fired
        (the schedule's last_fired changed), False otherwise.
        """
        sch_id      = schedule["id"]
        target_id   = schedule.get("target_channel", "")
        name        = schedule.get("name", sch_id)

        # 1. Another device is playing the target channel: it fires.
        if target_id != now_playing_channel_id:
            holder = channel_manager.channel_lock_holder(target_id)
            if holder:
                _note_once(sch_id, "'{}': waiting - the target channel is "
                           "being played on {}; that device fires it".format(
                               name, holder.get("device_name")
                               or "another device"))
                return False

        # 2. One block at a time per channel.  The queue file is the truth:
        #    any item still tagged with a schedule id blocks every schedule
        #    for this channel (it may be this schedule's own earlier block).
        queue = channel_manager.read_channel_queue(target_id)
        if queue is None:
            _note_once(sch_id, "'{}': waiting - the target queue cannot be "
                       "read right now".format(name))
            return False          # unreadable right now - try next tick
        if not queue:
            _note_once(sch_id, "'{}': waiting - the target channel has no "
                       "queue yet".format(name))
            return False          # channel has no queue yet - nothing to prepend to
        if any(item.get("_schedule_id") for item in queue):
            self._skip_occurrence(
                schedule, channel_manager,
                "an earlier scheduled block is still in the queue")
            return False

        # A block record with no items left in the queue is a leftover.
        if channel_manager.get_active_block(sch_id) is not None:
            log("[Scheduler] '{}': clearing leftover active_block "
                "(no block items in the queue)".format(name))
            channel_manager.clear_active_block(sch_id)

        # 3. Claim today's fire so no other device builds the same block.
        if not channel_manager.claim_schedule_fire(sch_id):
            _note_once(sch_id, "'{}': not firing on {} - another device "
                       "holds the claim".format(
                           name, channel_manager.get_device_label()))
            return False

        log("[Scheduler] '{}': all checks passed, firing block on {}".format(
            name, channel_manager.get_device_label()))
        last_fired_before = schedule.get("last_fired", 0)
        self.fire_block(schedule, channel_manager)
        current = channel_manager.get_all_schedules().get(sch_id) or {}
        fired = current.get("last_fired", last_fired_before) != last_fired_before
        if not fired:
            log("[Scheduler] '{}': block was not recorded as fired - claim "
                "released, will retry".format(name))
            channel_manager.release_schedule_claim(sch_id)
        return fired

    def _skip_occurrence(self, schedule, channel_manager, reason) -> None:
        """Skip today's fire of a schedule for good.

        last_fired is set to now (the way the wizard marks a schedule created
        after its time) so it is not tried again today, and last_skipped
        records why it is not a real fire.  A once-only schedule is switched
        off; a repeating one tries again on its next day.  Logged once.
        """
        sch_id = schedule["id"]
        name   = schedule.get("name", sch_id)
        current = channel_manager.get_all_schedules().get(sch_id)
        if not current:
            return
        updated = dict(current)
        updated["last_fired"]   = time.time()
        updated["last_skipped"] = time.time()
        if updated.get("recurrence") == "once":
            updated["active"] = False
            log("[Scheduler] '{}': skipped - {} - once-only schedule "
                "switched off".format(name, reason))
        else:
            log("[Scheduler] '{}': skipped today - {}".format(name, reason))
        channel_manager.update_schedule(sch_id, updated)

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
                    item["_block_seq"]   = len(block_items)
                    item["_channel_id"]  = target_id
                    item["channel_id"]   = target_id
                    block_items.append(item)
            if not block_items:
                log("[Scheduler] fire_block: combo source produced no items — aborting")
                return
            log("[Scheduler] fire_block: combo source built {} items "
                "({} unit(s))".format(len(block_items), item_count))
            _log_block_items(name, block_items)
            # Fall through to target queue write, active_block and last_fired.
            tgt_queue = channel_manager.read_channel_queue(target_id)
            if tgt_queue is None:
                log("[Scheduler] fire_block: target queue cannot be read "
                    "right now - not fired")
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
            block_state = _new_block_state(
                schedule, target_id, source_id, block_items, channel_manager)
            channel_manager.set_active_block(sch_id, block_state)
            schedules = channel_manager.get_all_schedules()
            if sch_id in schedules:
                updated = dict(schedules[sch_id])
                updated["last_fired"] = time.time()
                updated["last_fired_by"] = channel_manager.get_device_label()
                if schedule.get("recurrence") == "once":
                    updated["active"] = False
                    log("[Scheduler] fire_block: once-only schedule '{}' "
                        "deactivated".format(name))
                channel_manager.update_schedule(sch_id, updated)
            log("[Scheduler] fire_block: block fired for '{}' — {} items "
                "inserted into '{}' (device {})".format(
                name, len(block_items),
                channel_manager.get_channel(target_id).get("name", target_id),
                channel_manager.get_device_label()))
            return

        # ── Regular (non-combo) source path ─────────────────────────────────
        # Read source queue (None = cannot be read right now: nothing is
        # rebuilt or written, the schedule is tried again)
        try:
            src_queue = channel_manager.read_channel_queue(source_id)
        except Exception as e:
            log("[Scheduler] fire_block: cannot read source queue: "
                "{}".format(e))
            return
        if src_queue is None:
            log("[Scheduler] fire_block: source queue cannot be read right "
                "now - not fired")
            return

        if not src_queue:
            log("[Scheduler] fire_block: source queue empty, "
                "attempting rebuild")
            try:
                src_queue = channel_manager.build_channel_queue(
                    source_ch, keep_places=True)
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
            item["_block_seq"]   = len(block_items)
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
            tgt_queue = channel_manager.read_channel_queue(target_id)
        except Exception as e:
            log("[Scheduler] fire_block: cannot read target queue: "
                "{}".format(e))
            return
        if tgt_queue is None:
            log("[Scheduler] fire_block: target queue cannot be read right "
                "now - not fired")
            return

        new_tgt_queue = block_items + tgt_queue
        _log_block_items(name, block_items)
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
        block_state = _new_block_state(
            schedule, target_id, source_id, block_items, channel_manager)
        channel_manager.set_active_block(sch_id, block_state)

        # Update last_fired and deactivate once-only schedules.
        # Uses update_schedule() — channel_manager owns all schedules.json I/O.
        schedules = channel_manager.get_all_schedules()
        if sch_id in schedules:
            updated = dict(schedules[sch_id])
            updated["last_fired"] = time.time()
            updated["last_fired_by"] = channel_manager.get_device_label()
            if schedule.get("recurrence") == "once":
                updated["active"] = False
                log("[Scheduler] fire_block: once-only schedule '{}' "
                    "deactivated".format(name))
            channel_manager.update_schedule(sch_id, updated)

        log("[Scheduler] fire_block: block fired for '{}' — "
            "{} items inserted into '{}' (device {})".format(
            name, len(block_items),
            target_ch.get("name", target_id),
            channel_manager.get_device_label()))

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

    # ------------------------------------------------------------------
    # Public helper: find the active block for a given target channel
    # (used by service.py to check all schedules for a channel)
    # ------------------------------------------------------------------
