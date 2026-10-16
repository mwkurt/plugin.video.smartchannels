"""
resources/lib/ui/schedule_wizard.py
=====================================
8-step wizard for creating and editing channel schedules (1.1.9a).

Called from:
  - ui/channels.py context menu: "Add Schedule" (target pre-selected)
  - router.py action "manage_schedules": "Edit Schedule" from manage list

OWNS:   Dialog interaction, schedule data validation, conflict checking.
NEVER:  Direct state.json / queue file access.
        All persistence goes through channel_manager.py CRUD methods.
        Hardcoded user-visible strings (all via _s() / addon.getLocalizedString).
"""

from __future__ import annotations

import time

import xbmcgui


# String IDs (1.1.9a range starting at #32686)
_S_ADD_SCHEDULE         = 32730
_S_MANAGE_SCHEDULES     = 32755
_S_SCHEDULE_NAME        = 32731
_S_SELECT_TARGET        = 32732
_S_SELECT_SOURCE        = 32733
_S_SCHEDULE_DAY         = 32734
_S_START_TIME           = 32735
_S_NUM_ITEMS            = 32736
_S_SCHEDULE_SAVED       = 32739
_S_DELETE_CONFIRM       = 32740
_S_SCHEDULE_DELETED     = 32741
_S_CONFLICT_TARGET      = 32742
_S_CONFLICT_SOURCE      = 32743
_S_DAILY                = 32744
_S_WEEKDAYS             = 32745
_S_WEEKENDS             = 32746
_S_ONCE                 = 32747
_S_TONIGHT_AT           = 32748
_S_NOW_SCHEDULED_BLOCK  = 32749
_S_THIS_DAY_AT          = 32750
_S_EDIT_SCHEDULE        = 32752
_S_ACTIVATE             = 32753
_S_DEACTIVATE           = 32754
_S_SCHEDULES_HEADING    = 32755
_S_ACTIVE_FMT           = 32756
_S_OFF_FMT              = 32757
_S_NO_SCHEDULES         = 32758
_S_INVALID_TIME         = 32759
_S_MON                  = 32761
_S_TUE                  = 32762
_S_WED                  = 32763
_S_THU                  = 32764
_S_FRI                  = 32765
_S_SAT                  = 32766
_S_SUN                  = 32767
_S_WEEKDAYS_LABEL       = 32768
_S_WEEKENDS_LABEL       = 32769
_S_ADDON_NAME           = 32000  # "Smart TV Channels"
_S_NO_CHANNELS          = 32770
_S_NO_SOURCE_CHANNELS   = 32771
_S_SUMMARY_NAME         = 32772
_S_SUMMARY_TARGET       = 32773
_S_SUMMARY_SOURCE       = 32774
_S_SUMMARY_DAY_TIME     = 32775
_S_SUMMARY_ITEMS        = 32776
_S_FIRE_DATE            = 32778   # "Fire Date (DD/MM/YYYY)"
_S_INVALID_DATE         = 32779   # "Invalid date. Please enter..."
_S_SUMMARY_DATE         = 32780   # "Date:   {0}"
_S_PAST_TIME            = 32783   # "The time {0} has already passed today..."


class ScheduleWizard:
    """
    Runs the 8-step wizard and returns a schedule definition dict,
    or None if the user cancelled.

    Parameters
    ----------
    addon         : xbmcaddon.Addon
    channel_manager : ChannelManager
    existing      : dict | None  — pre-fill on edit; None for create
    target_channel_id : str | None — pre-select target (context menu)
    """

    def __init__(self, addon, channel_manager,
                 existing=None, target_channel_id=None):
        self.addon   = addon
        self.manager = channel_manager
        self.existing = existing
        self.preset_target = target_channel_id
        self._d = xbmcgui.Dialog()

    def _s(self, id_: int) -> str:
        return self.addon.getLocalizedString(id_)

    # ------------------------------------------------------------------
    # Day display labels and internal value mapping
    # ------------------------------------------------------------------

    def _day_options(self):
        """Return (display_labels, internal_values) for day selection."""
        labels = [
            self._s(_S_DAILY),
            self._s(_S_WEEKDAYS),
            self._s(_S_WEEKENDS),
            self._s(_S_MON),
            self._s(_S_TUE),
            self._s(_S_WED),
            self._s(_S_THU),
            self._s(_S_FRI),
            self._s(_S_SAT),
            self._s(_S_SUN),
            self._s(_S_ONCE),
        ]
        values = [
            "daily",
            "weekdays",
            "weekends",
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
            "once",
        ]
        return labels, values

    def _day_value_to_index(self, day_value):
        _, values = self._day_options()
        try:
            return values.index(day_value)
        except ValueError:
            return 0

    def _day_recurrence(self, day_value):
        """Derive recurrence string from day value."""
        if day_value == "daily":
            return "daily"
        if day_value == "weekdays":
            return "weekdays"
        if day_value == "weekends":
            return "weekends"
        if day_value == "once":
            return "once"
        return "weekly"

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def _validate_time(self, time_str):
        """Return True if time_str is a valid HH:MM string."""
        try:
            parts = time_str.strip().split(":")
            if len(parts) != 2:
                return False
            h, m = int(parts[0]), int(parts[1])
            return 0 <= h <= 23 and 0 <= m <= 59
        except (ValueError, AttributeError):
            return False

    def _validate_date(self, date_str):
        """
        Return True if date_str is a valid DD/MM/YYYY date that is today
        or in the future.  Rejects past dates and invalid calendar values
        (e.g. 31/02/2025).
        """
        import datetime
        try:
            parts = date_str.strip().split("/")
            if len(parts) != 3:
                return False
            d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
            target = datetime.date(y, m, d)   # raises ValueError if invalid
            return target >= datetime.date.today()
        except (ValueError, AttributeError):
            return False

    def _time_to_minutes(self, time_str):
        """Convert HH:MM to total minutes since midnight."""
        h, m = (int(x) for x in time_str.strip().split(":"))
        return h * 60 + m

    def _estimate_block_duration(self, source_id, item_count):
        """
        Return an estimated block duration in minutes for a schedule.

        Reads the source channel's queue file and sums the durations of the
        first item_count real (non-silent) items. Adds a 15-minute buffer.

        Falls back to item_count × 30 minutes if the queue cannot be read,
        is empty, or has no duration data.
        """
        _BUFFER_MINS   = 15
        _FALLBACK_MINS = 30   # per item if queue unreadable

        try:
            queue = self.manager.get_channel_queue(source_id)
            if not queue:
                return (item_count * _FALLBACK_MINS) + _BUFFER_MINS

            total_secs = 0
            counted    = 0
            for item in queue:
                if item.get("_silent", False):
                    continue
                dur = int(item.get("duration", 0) or 0)
                if dur > 0:
                    total_secs += dur
                else:
                    # Item has no duration — use fallback for this item
                    total_secs += _FALLBACK_MINS * 60
                counted += 1
                if counted >= item_count:
                    break

            if counted < item_count:
                # Fewer real items than requested — fill remainder with fallback
                total_secs += (_FALLBACK_MINS * 60) * (item_count - counted)

            total_mins = (total_secs // 60) + _BUFFER_MINS
            return total_mins

        except Exception:
            return (item_count * _FALLBACK_MINS) + _BUFFER_MINS

    # ------------------------------------------------------------------
    # Conflict checking
    # ------------------------------------------------------------------

    def _check_conflicts(self, definition, exclude_id=None):
        """
        Check for scheduling conflicts.
        Returns (True, None) if no conflict.
        Returns (False, error_message_string) if conflict found.

        Conflict rule 1: target channel must not already have an active
        schedule on the same day/time that overlaps.
        Conflict rule 2: source channel may only appear in one schedule.
        """
        schedules = self.manager.get_all_schedules()
        target_id   = definition.get("target_channel", "")
        source_id   = definition.get("source_channel", "")
        new_day     = definition.get("day", "")
        new_start   = definition.get("time", "00:00")
        item_count  = int(definition.get("item_count", 2))

        # Calculate block duration from the actual durations of the first
        # item_count real (non-silent) items in the source queue, plus a
        # 15-minute buffer. Falls back to item_count × 30 minutes if the
        # source queue cannot be read or has no duration data.
        block_mins = self._estimate_block_duration(source_id, item_count)
        window_end = self._time_to_minutes(new_start) + block_mins

        for sch_id, sch in schedules.items():
            if sch_id == exclude_id:
                continue
            if not sch.get("active", False):
                continue

            # Rule 1: target channel overlap
            if sch.get("target_channel") == target_id:
                if self._days_overlap(new_day, sch.get("day", "")):
                    sch_start      = self._time_to_minutes(sch.get("time", "00:00"))
                    sch_item_count = int(sch.get("item_count", 2))
                    sch_source_id  = sch.get("source_channel", "")
                    sch_block_mins = self._estimate_block_duration(
                        sch_source_id, sch_item_count)
                    sch_end = sch_start + sch_block_mins
                    new_start_mins = self._time_to_minutes(new_start)
                    if new_start_mins < sch_end and window_end > sch_start:
                        conflict_name = sch.get("name", sch_id)
                        return False, self._s(_S_CONFLICT_TARGET).format(
                            conflict_name)

            # Rule 2: source channel may not be shared between schedules
            # that target DIFFERENT channels. Source queue items are
            # permanently consumed when a block fires. Two schedules on the
            # SAME target channel may share a source — they fire at different
            # times and the source top-up replenishes between fires.
            if (sch.get("source_channel") == source_id
                    and sch.get("target_channel") != target_id):
                conflict_name = sch.get("name", sch_id)
                return False, self._s(_S_CONFLICT_SOURCE).format(
                    conflict_name)

        return True, None

    def _days_overlap(self, day_a, day_b):
        """Return True if the two day/recurrence values share any common day."""
        _WEEKDAY_SET = {"monday", "tuesday", "wednesday", "thursday", "friday"}
        _WEEKEND_SET = {"saturday", "sunday"}
        _ALL = _WEEKDAY_SET | _WEEKEND_SET

        def expand(d):
            if d == "daily":
                return _ALL
            if d == "weekdays":
                return _WEEKDAY_SET
            if d == "weekends":
                return _WEEKEND_SET
            if d == "once":
                return _ALL  # conservative: treat once as any day
            return {d}

        return bool(expand(day_a) & expand(day_b))

    # ------------------------------------------------------------------
    # Wizard entry point
    # ------------------------------------------------------------------

    def run(self):
        """
        Execute the 8-step wizard.  Returns a schedule definition dict
        on success, or None if the user cancelled at any step.
        """
        existing  = self.existing
        d         = self._d
        all_channels = self.manager.get_all_channels()

        if not all_channels:
            d.ok(self._s(_S_ADDON_NAME), self._s(_S_NO_CHANNELS))
            return None

        # ---- Step 1: Schedule Name ----------------------------------------
        default_name = existing.get("name", "") if existing else ""
        name = d.input(
            self._s(_S_SCHEDULE_NAME),
            default_name,
            type=xbmcgui.INPUT_ALPHANUM)
        if not name:
            return None
        name = name.strip()
        if not name:
            return None

        # ---- Step 2: Target Channel ----------------------------------------
        # Audio, Party and Combo Block channels cannot be schedule targets —
        # block items are video content, and Combo Blocks are source-only.
        # When the wizard is opened from a channel's context menu, that
        # channel IS the target and no picker is shown. When editing, the
        # schedule's current target is kept selectable even if its type is
        # no longer eligible, so an edit never silently changes it.
        existing_target = existing.get("target_channel", "") if existing else ""
        target_pool = [ch for ch in all_channels
                       if ch.get("channel_type") not in
                       ("audio", "party", "combo")
                       or ch.get("id") == existing_target]

        if not existing and self.preset_target and any(
                ch.get("id") == self.preset_target for ch in target_pool):
            target_id = self.preset_target
        else:
            if not target_pool:
                d.ok(self._s(_S_ADDON_NAME), self._s(_S_NO_CHANNELS))
                return None
            ch_labels = [ch.get("name", "") for ch in target_pool]
            ch_ids    = [ch.get("id",   "") for ch in target_pool]

            default_target_idx = 0
            wanted = existing_target or self.preset_target
            if wanted and wanted in ch_ids:
                default_target_idx = ch_ids.index(wanted)

            target_idx = d.select(
                self._s(_S_SELECT_TARGET), ch_labels,
                preselect=default_target_idx)
            if target_idx < 0:
                return None
            target_id = ch_ids[target_idx]

        # ---- Step 3: Source Channel ----------------------------------------
        # Sources must be Hidden channels (so a source never plays on its own
        # in the visible list). Exclude the target, Audio and Party channels
        # (1.2.0a decision), and carousel channels (1.2.0c — the carousel
        # would silently drain the queue the scheduler depends on).
        # Combo Blocks are always hidden; they are listed as a separate group
        # after the regular channels (1.2.4a).
        # When editing, the schedule's current source stays selectable even if
        # it is a visible channel, so an edit never silently swaps it.
        existing_src = existing.get("source_channel", "") if existing else ""
        src_channels = [ch for ch in all_channels
                        if ch.get("id") != target_id
                        and ch.get("channel_type") not in
                        ("audio", "party", "combo")
                        and not ch.get("carousel_enabled", False)
                        and (not ch.get("visible", True)
                             or ch.get("id") == existing_src)]

        # Combo Block sources — included only if unowned or already owned
        # by this schedule's target channel.  Combos owned by other channels
        # are excluded from the picker entirely rather than shown and then
        # blocked after selection.
        combo_src_channels = [
            ch for ch in all_channels
            if ch.get("channel_type") == "combo"
            and (
                not self.manager.get_combo_owner(ch["id"])
                or (self.manager.get_combo_owner(ch["id"]) or {})
                   .get("channel_id") == target_id
                or ch["id"] == existing_src   # keep current source in edit
            )
        ]

        # Only tell the user there is nothing to pick when that is the case.
        if not src_channels and not combo_src_channels:
            d.ok(self._s(_S_ADDON_NAME), self._s(_S_NO_SOURCE_CHANNELS))
            return None

        # Build combined picker with separator before Combo Blocks
        all_src_channels = list(src_channels)
        combo_separator_idx = None
        if combo_src_channels:
            combo_separator_idx = len(all_src_channels)
            all_src_channels.append(None)  # separator placeholder
            all_src_channels.extend(combo_src_channels)

        src_labels = []
        for ch in all_src_channels:
            if ch is None:
                src_labels.append("── {} ──".format(self._s(32866)))
            elif ch.get("channel_type") == "combo":
                slot_types = "+".join(
                    s.get("source_type", "?").upper()
                    for s in ch.get("slots", []))
                src_labels.append("{}  ({})".format(
                    ch["name"],
                    slot_types if slot_types else "?"))
            else:
                src_labels.append(ch.get("name", ""))

        src_ids = [ch.get("id", "") if ch else "" for ch in all_src_channels]

        default_src_idx = 0
        existing_src = existing.get("source_channel", "") if existing else ""
        if existing_src and existing_src in src_ids:
            default_src_idx = src_ids.index(existing_src)

        while True:
            src_idx = d.select(
                self._s(_S_SELECT_SOURCE), src_labels,
                preselect=default_src_idx)
            if src_idx < 0:
                return None
            # Ignore separator row
            if combo_separator_idx is not None and src_idx == combo_separator_idx:
                continue
            break

        source_id = src_ids[src_idx]
        src_ch_selected = all_src_channels[src_idx]

        # ---- Step 4: Day ----------------------------------------------------
        day_labels, day_values = self._day_options()
        existing_day = existing.get("day", "daily") if existing else "daily"
        default_day_idx = self._day_value_to_index(existing_day)

        day_idx = d.select(
            self._s(_S_SCHEDULE_DAY), day_labels,
            preselect=default_day_idx)
        if day_idx < 0:
            return None
        day_value = day_values[day_idx]

        # ---- Step 4b: Fire Date (Once only) ---------------------------------
        # When "Once" is selected, ask the user for the specific calendar date
        # on which the block should fire.  For all other recurrence types the
        # field is left empty and the scheduler ignores it.
        fire_date = ""
        if day_value == "once":
            import datetime as _dt
            existing_date = (existing.get("fire_date", "")
                             if existing else "")
            # Default to today's date formatted as DD/MM/YYYY
            default_date = (existing_date
                            if existing_date
                            else _dt.date.today().strftime("%d/%m/%Y"))
            while True:
                fire_date = d.input(
                    self._s(_S_FIRE_DATE),
                    default_date,
                    type=xbmcgui.INPUT_ALPHANUM)
                if fire_date is None:
                    return None
                fire_date = fire_date.strip()
                if self._validate_date(fire_date):
                    break
                d.ok(self._s(_S_ADDON_NAME), self._s(_S_INVALID_DATE))
                # Loop back so the user can correct the date without
                # restarting the whole wizard.

        # ---- Step 5: Start Time ---------------------------------------------
        existing_time = existing.get("time", "21:00") if existing else "21:00"
        start_time = d.input(
            self._s(_S_START_TIME),
            existing_time,
            type=xbmcgui.INPUT_ALPHANUM)
        if start_time is None:
            return None
        start_time = start_time.strip()
        if not self._validate_time(start_time):
            d.ok(self._s(_S_ADDON_NAME), self._s(_S_INVALID_TIME))
            return None

        # Cross-check: for "once" schedules, reject if the chosen date+time
        # is already in the past.  _validate_date accepts today as valid (the
        # user might be creating a schedule for later today), but if the time
        # has already passed we would silently never fire.
        if day_value == "once" and fire_date:
            import datetime as _dt
            try:
                _d, _m, _y = (int(x) for x in fire_date.split("/"))
                _h, _min   = (int(x) for x in start_time.split(":"))
                fire_datetime = _dt.datetime(_y, _m, _d, _h, _min)
                if fire_datetime <= _dt.datetime.now():
                    d.ok(self._s(_S_ADDON_NAME),
                         self._s(_S_PAST_TIME).format(start_time))
                    return None
            except (ValueError, TypeError):
                pass  # malformed values already caught by earlier validators

        # For recurring schedules, if the time has already passed today,
        # inform the user — the schedule will fire tomorrow, not today.
        # This is not an error; just let them know so it isn't surprising.
        if day_value != "once":
            import datetime as _dt
            now_hhmm = _dt.datetime.now().strftime("%H:%M")
            if start_time <= now_hhmm:
                d.ok(self._s(_S_ADDON_NAME),
                     self._s(_S_PAST_TIME).format(start_time))

        # ---- Step 6: Item Count ---------------------------------------------
        existing_count = existing.get("item_count", 4) if existing else 4
        count_str = d.input(
            self._s(_S_NUM_ITEMS),
            str(existing_count),
            type=xbmcgui.INPUT_NUMERIC)
        if count_str is None:
            return None
        try:
            item_count = max(1, min(50, int(count_str)))
        except (ValueError, TypeError):
            item_count = 4

        # ---- Build summary --------------------------------------------------
        target_ch  = next(ch for ch in all_channels
                          if ch.get("id") == target_id)
        source_ch  = src_ch_selected
        day_label  = day_labels[day_idx]
        recurrence = self._day_recurrence(day_value)

        summary_lines = [
            self._s(_S_SUMMARY_NAME).format(name),
            self._s(_S_SUMMARY_TARGET).format(target_ch.get("name", target_id)),
            self._s(_S_SUMMARY_SOURCE).format(source_ch.get("name", source_id)),
            self._s(_S_SUMMARY_DAY_TIME).format(day_label, start_time),
        ]
        if fire_date:
            summary_lines.append(self._s(_S_SUMMARY_DATE).format(fire_date))
        summary_lines.append(self._s(_S_SUMMARY_ITEMS).format(item_count))

        # ---- Step 7: Confirm -----------------------------------------------
        confirmed = d.yesno(
            self._s(_S_ADD_SCHEDULE) if not existing
            else self._s(_S_EDIT_SCHEDULE),
            "\n".join(summary_lines))
        if not confirmed:
            return None

        # ---- Build definition dict ----------------------------------------
        # If any scheduling-relevant field changed on edit (time, day, or
        # source channel), reset last_fired to 0 so the schedule can fire
        # again today at the new time without being blocked by the old
        # last_fired timestamp from earlier in the same day.
        old_last_fired = existing.get("last_fired", 0) if existing else 0
        if existing:
            time_changed   = (start_time != existing.get("time", ""))
            day_changed    = (day_value  != existing.get("day",  ""))
            source_changed = (source_id  != existing.get("source_channel", ""))
            date_changed   = (fire_date  != existing.get("fire_date", ""))
            if time_changed or day_changed or source_changed or date_changed:
                old_last_fired = 0
        else:
            # New schedule. For recurring schedules (not once-only), if the
            # configured time has already passed today, set last_fired to now
            # so the schedule does not fire immediately on the next tick.
            # If the time hasn't passed yet, leave last_fired=0 so it fires
            # at the correct time today.
            if recurrence != "once":
                now = time.localtime()
                now_hhmm = "{:02d}:{:02d}".format(now.tm_hour, now.tm_min)
                if start_time <= now_hhmm:
                    old_last_fired = time.time()

        definition = {
            "name":           name,
            "target_channel": target_id,
            "source_channel": source_id,
            "day":            day_value,
            "time":           start_time,
            "item_count":     item_count,
            "fire_date":      fire_date,   # "DD/MM/YYYY" for once; "" otherwise
            "recurrence":     recurrence,
            "active":         existing.get("active", True) if existing else True,
            "last_fired":     old_last_fired,
            "created":        (existing.get("created", time.time())
                               if existing else time.time()),
        }

        # ---- Conflict check -----------------------------------------------
        exclude_id = existing.get("id") if existing else None
        ok, conflict_msg = self._check_conflicts(definition, exclude_id)
        if not ok:
            d.ok(self._s(_S_ADDON_NAME), conflict_msg)
            return None

        return definition


# ---------------------------------------------------------------------------
# Manage Schedules screen
# ---------------------------------------------------------------------------

def manage_schedules(addon, channel_manager):
    """
    Open the Manage Schedules screen.  Called from router.py.

    Lists all schedules with [ACTIVE]/[OFF] prefixes.
    On selecting one: Edit / Toggle Active / Delete / Cancel.
    """

    def _s(id_):
        return addon.getLocalizedString(id_)

    schedules = channel_manager.get_all_schedules()

    if not schedules:
        xbmcgui.Dialog().ok(_s(_S_ADDON_NAME), _s(_S_NO_SCHEDULES))
        return

    def _label(sch):
        target = channel_manager.get_channel(sch.get("target_channel", ""))
        source = channel_manager.get_channel(sch.get("source_channel", ""))
        t_name = target.get("name", "?") if target else "?"
        s_name = source.get("name", "?") if source else "?"
        inner  = "{} — {} \u2190 {}".format(sch.get("name", "?"),
                                              t_name, s_name)
        if sch.get("active", False):
            return _s(_S_ACTIVE_FMT).format(inner)
        else:
            return _s(_S_OFF_FMT).format(inner)

    sch_list = list(schedules.values())

    while True:
        labels = [_label(s) for s in sch_list]
        chosen = xbmcgui.Dialog().select(
            _s(_S_MANAGE_SCHEDULES), labels)
        if chosen < 0:
            return

        sch      = sch_list[chosen]
        sch_id   = sch["id"]
        sch_name = sch.get("name", sch_id)

        toggle_label = (_s(_S_DEACTIVATE) if sch.get("active", False)
                        else _s(_S_ACTIVATE))
        action_idx = xbmcgui.Dialog().select(
            sch_name,
            [_s(_S_EDIT_SCHEDULE), toggle_label,
             _s(_S_DELETE_CONFIRM)])
        if action_idx < 0:
            continue

        if action_idx == 0:
            # Edit
            wizard = ScheduleWizard(addon, channel_manager, existing=sch)
            result = wizard.run()
            if result:
                # If source channel changed, update combo ownership
                old_src = sch.get("source_channel", "")
                new_src = result.get("source_channel", "")
                if old_src != new_src:
                    old_ch = channel_manager.get_channel(old_src)
                    if old_ch and old_ch.get("channel_type") == "combo":
                        channel_manager.clear_combo_owner(old_src)
                    new_ch = channel_manager.get_channel(new_src)
                    if new_ch and new_ch.get("channel_type") == "combo":
                        tgt_id   = result.get("target_channel", "")
                        tgt_ch   = channel_manager.get_channel(tgt_id)
                        tgt_name = (tgt_ch.get("name", tgt_id)
                                    if tgt_ch else tgt_id)
                        channel_manager.set_combo_owner(
                            new_src, tgt_id, tgt_name, "schedule")
                channel_manager.update_schedule(sch_id, result)
                xbmcgui.Dialog().notification(
                    _s(_S_ADDON_NAME), _s(_S_SCHEDULE_SAVED),
                    xbmcgui.NOTIFICATION_INFO, 2000)
                # Reload for next iteration
                schedules = channel_manager.get_all_schedules()
                sch_list  = list(schedules.values())

        elif action_idx == 1:
            # Toggle active
            schedules = channel_manager.get_all_schedules()
            if sch_id in schedules:
                schedules[sch_id]["active"] = not schedules[sch_id].get(
                    "active", False)
                channel_manager.save_schedules_data(schedules)
            schedules = channel_manager.get_all_schedules()
            sch_list  = list(schedules.values())

        elif action_idx == 2:
            # Delete
            confirmed = xbmcgui.Dialog().yesno(
                _s(_S_ADDON_NAME), _s(_S_DELETE_CONFIRM))
            if confirmed:
                # Clear combo owner if source is a Combo Block
                _src_id = sch.get("source_channel", "")
                _src_ch = channel_manager.get_channel(_src_id)
                if _src_ch and _src_ch.get("channel_type") == "combo":
                    channel_manager.clear_combo_owner(_src_id)
                channel_manager.delete_schedule(sch_id)
                xbmcgui.Dialog().notification(
                    _s(_S_ADDON_NAME), _s(_S_SCHEDULE_DELETED),
                    xbmcgui.NOTIFICATION_INFO, 2000)
                schedules = channel_manager.get_all_schedules()
                sch_list  = list(schedules.values())
                if not sch_list:
                    return
