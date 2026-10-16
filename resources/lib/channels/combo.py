# channels/combo.py
#
# OWNS:   Queue building logic for Combo Block channels.
#         Per-slot item fetching (TV, Movie, Folder).
#         Per-slot state read/write via channel_manager public methods only.
#
# NEVER:  UI rendering. Playback control.
#         Private channel_manager methods (Rule 14).
#         Direct state.json or queue file access.
#
# CALLERS: channel_manager.py only, via build_queue() dispatch and
#          _load_foreign_items combo branch.
#
# STATUS 1.2.4a: Initial implementation.

from __future__ import annotations

import xbmc

from resources.lib.channels.base import BaseQueueBuilder
from resources.lib.channels.interleave import slot_item_count
from resources.lib.utils.logger  import log

# State key templates — all scoped to combo channel + slot
_TV_NEXT_EP_KEY    = "combo:{}:slot:{}:tv_next_ep"
_TV_EP_INDEX_KEY   = "combo:{}:slot:{}:tv_ep_index"
_MOVIE_STATE_KEY   = "combo:{}:slot:{}:movie_state"
_FOLDER_PLAYED_KEY = "combo:{}:slot:{}:folder_played"


class ComboQueueBuilder(BaseQueueBuilder):
    """
    Queue builder for Combo Block channels.

    A Combo Block defines an ordered list of slots.  Each slot is one
    content source (TV show, Movie pool, or Folder).  One item fires
    per slot per unit.  The queue is a flat list of interleaved slot
    items:  [slot1[0], slot2[0], slot1[1], slot2[1], ...].

    All state is scoped to the Combo Block channel ID + slot ID so that
    a TV show used in a Combo Block slot never shares its playback
    position with the same show configured as a standalone channel.
    """

    def build(self, channel: dict, target_size: int,
              current_queue=None) -> list:
        """
        Build a Combo Block queue of up to target_size items.

        current_queue is accepted for API compatibility but ignored —
        Combo Blocks always build fresh (top-up is handled by the caller
        in _load_foreign_items via a separate topup call).
        """
        channel_id = channel["id"]
        slots      = channel.get("slots", [])

        if not slots:
            log("[ComboQueueBuilder] '{}': no slots configured — "
                "returning empty queue".format(channel.get("name", channel_id)))
            return []

        num_slots    = len(slots)
        units_needed = max(1, target_size // num_slots)

        log("[ComboQueueBuilder] '{}': {} slot(s), {} units, "
            "target={} items".format(
            channel.get("name", channel_id),
            num_slots, units_needed, target_size))

        # Fetch items per slot.
        # TV slots honour episodes_per_slot; Movie slots honour movies_per_slot.
        # Folder slots always contribute 1 item per unit.
        per_slot = []
        for slot in slots:
            src = slot.get("source_type", "")
            slot_count = slot_item_count(slot)
            items = self._fetch_slot_items(
                channel_id, slot, units_needed * slot_count)
            per_slot.append((slot, items, slot_count))
            log("[ComboQueueBuilder] slot {} ({}) count={}: {} items fetched"
                .format(slot.get("slot_id", "?")[:8],
                        src, slot_count, len(items)))

        # Interleave into units.
        # Each unit: for each slot, take slot_count consecutive items.
        # e.g. slots=[CC(1), LT(2), 1950s(1)] →
        #      unit: [CC[0], LT[0], LT[1], 1950s[0]]
        queue = []
        for unit_idx in range(units_needed):
            for slot, items, slot_count in per_slot:
                base = unit_idx * slot_count
                for k in range(slot_count):
                    item_idx = base + k
                    if item_idx < len(items):
                        item = dict(items[item_idx])
                        # TV slots stamp _silent per-show in build_combo_tv_slot;
                        # Movie/Folder slots carry silent at slot level.
                        if "_silent" not in item:
                            item["_silent"] = slot.get("silent", False)
                        item["_combo_slot"]  = slot.get("slot_id", "")
                        item["_interleaved"] = True
                        queue.append(item)
                    # If a slot is exhausted, skip silently.

        log("[ComboQueueBuilder] '{}': built {} items ({} complete "
            "units of {})".format(
            channel.get("name", channel_id),
            len(queue), units_needed, num_slots))
        return queue

    def build_unit(self, channel: dict, host_queue: list = None) -> list:
        """Build ONE complete unit: every slot once, in slot order.

        Each slot contributes its full per-unit count (see
        slot_item_count), so a block of N units is N calls to this
        method.  Used by the scheduler to compose a block that has the
        same shape as the Combo Block's normal queue units.

        host_queue holds items already chosen for the same block; Folder
        slots use it to avoid drawing a file that is already waiting.

        A slot that yields nothing (for example an unreachable folder)
        is logged and skipped; the rest of the unit is still returned.
        """
        channel_id = channel["id"]
        unit       = []
        for slot in channel.get("slots", []):
            slot_count = slot_item_count(slot)
            items = self._fetch_slot_items(
                channel_id, slot, slot_count,
                host_queue=list(host_queue or []) + unit)
            if not items:
                log("[ComboQueueBuilder] build_unit: slot {} ({}) "
                    "produced no items".format(
                        slot.get("slot_id", "?")[:8],
                        slot.get("source_type", "?")),
                    xbmc.LOGWARNING)
                continue
            for item in items[:slot_count]:
                item = dict(item)
                if "_silent" not in item:
                    item["_silent"] = slot.get("silent", False)
                item["_combo_slot"]  = slot.get("slot_id", "")
                item["_interleaved"] = True
                item["_channel_id"]  = channel_id
                unit.append(item)
        return unit

    def build_one_slot(self, channel: dict, slot_index: int,
                       host_queue: list = None) -> list:
        """Build one replacement item for a single slot by index.

        Used for strict 1-for-1 replacement: when slot N is consumed,
        immediately append the next item for slot N — no waiting for
        the full unit to complete.  Returns a list of 0 or 1 items.

        host_queue is the queue the item will be appended to (consumed item
        already removed).  A Folder slot uses it so a random draw does not
        pick a file that is already waiting in the queue.
        """
        slots = channel.get("slots", [])
        if not slots or slot_index >= len(slots):
            return []
        channel_id = channel["id"]
        slot       = slots[slot_index]
        items      = self._fetch_slot_items(channel_id, slot, 1,
                                            host_queue=host_queue)
        if not items:
            return []
        item = dict(items[0])
        if "_silent" not in item:
            item["_silent"] = slot.get("silent", False)
        item["_combo_slot"]  = slot.get("slot_id", "")
        item["_interleaved"] = True
        item["_channel_id"]  = channel_id   # needed for next carousel pop
        log("[ComboQueueBuilder] build_one_slot: slot_index={} slot={} "
            "built '{}'".format(
            slot_index, slot.get("slot_id","?")[:8],
            item.get("title","?")))
        return [item]

    # ------------------------------------------------------------------
    # Per-slot item fetching
    # ------------------------------------------------------------------

    def _fetch_slot_items(self, combo_id: str, slot: dict,
                          count: int, host_queue: list = None) -> list:
        """Dispatch to the correct fetcher based on slot source_type."""
        src = slot.get("source_type", "")
        if src == "tv":
            return self._fetch_tv_items(combo_id, slot, count,
                                        host_queue=host_queue)
        if src == "movies":
            return self._fetch_movie_items(combo_id, slot, count,
                                           host_queue=host_queue)
        if src == "folder":
            return self._fetch_folder_items(combo_id, slot, count,
                                            host_queue=host_queue)
        log("[ComboQueueBuilder] Unknown source_type '{}' in slot "
            "{}".format(src, slot.get("slot_id", "?")),
            xbmc.LOGWARNING)
        return []

    def _fetch_tv_items(self, combo_id: str, slot: dict,
                        count: int, host_queue: list = None) -> list:
        """
        Fetch `count` TV episodes for one TV slot.
        Delegates to channel_manager.build_combo_tv_slot which owns
        all state I/O for combo TV slots.
        """
        return self._cm.build_combo_tv_slot(combo_id, slot, count,
                                            host_queue=host_queue)

    def _fetch_movie_items(self, combo_id: str, slot: dict,
                           count: int, host_queue: list = None) -> list:
        """
        Fetch `count` movies for one Movie slot.
        Delegates to channel_manager.build_combo_movie_slot.
        """
        return self._cm.build_combo_movie_slot(combo_id, slot, count,
                                               host_queue=host_queue)

    def _fetch_folder_items(self, combo_id: str, slot: dict,
                             count: int, host_queue: list = None) -> list:
        """
        Fetch `count` folder items for one Folder slot.
        Builds a synthetic channel dict from the slot config and delegates
        to FolderQueueBuilder.  State is scoped to the combo+slot key.
        """
        from resources.lib.channels.folder import FolderQueueBuilder

        slot_id     = slot.get("slot_id", "")
        folder_path = slot.get("folder_path", "")

        if not folder_path:
            log("[ComboQueueBuilder] Folder slot {} has no "
                "folder_path".format(slot_id[:8]), xbmc.LOGWARNING)
            return []

        # Build a synthetic channel dict so FolderQueueBuilder can work
        # with its standard interface.  The id is the combo+slot scoped
        # key so played_files state is isolated from any standalone channel.
        synthetic_ch = {
            "id":          "combo:{}:slot:{}".format(combo_id, slot_id),
            "name":        "combo_slot_{}".format(slot_id[:8]),
            "folder_path": folder_path,
            "randomize":   slot.get("randomize", True),
            "recycle":     slot.get("recycle",   True),
            "no_repeat":   slot.get("no_repeat", False),
        }

        # Files of this slot already waiting in the host queue must not be
        # drawn again (played_files is only updated when a file is consumed).
        # If that leaves nothing, fall through the cases below.
        queued_files = [i.get("file", "") for i in (host_queue or [])
                        if i.get("file")
                        and i.get("_folder_state_id") == synthetic_ch["id"]]
        items = FolderQueueBuilder(self._cm).build(
            synthetic_ch, count, queued_files=queued_files or None)
        if (not items and queued_files and synthetic_ch["no_repeat"]
                and synthetic_ch["recycle"]):
            # Every file still unplayed in this cycle is already queued, so
            # the cycle is effectively complete: start the next one now (the
            # queued files are marked played in it when they are consumed)
            # and draw from the files not waiting in the queue.
            self._cm.record_folder_file_played(synthetic_ch["id"], None)
            items = FolderQueueBuilder(self._cm).build(
                synthetic_ch, count, queued_files=queued_files)
        if not items and queued_files:
            # Fewer files than queued items — the repeat is unavoidable.
            items = FolderQueueBuilder(self._cm).build(synthetic_ch, count)
        if not items:
            return []
        log("[ComboQueueBuilder] folder slot {}: drew '{}' "
            "(excluded {} queued file(s))".format(
                slot_id[:8], items[0].get("file", ""),
                len(set(queued_files))))

        # Overwrite _channel_id with the real combo channel ID so that
        # service.py's is_combo_channel() correctly identifies these items
        # as belonging to the combo block.  FolderQueueBuilder sets it to
        # the synthetic "combo:{id}:slot:{id}" key (used for state isolation)
        # which has no entry in channels.json, causing is_combo_channel to
        # return False and misroute the item in _do_replacement_inner.
        # Preserve the synthetic id as _folder_state_id so service.py can
        # record played files against the correct scoped state key for
        # no_repeat / recycle=False tracking.
        synthetic_id = synthetic_ch["id"]
        for item in items:
            item["_channel_id"]      = combo_id
            item["channel_id"]       = combo_id
            item["_folder_state_id"] = synthetic_id

        # If this slot is silent, replace each item's title with the
        # folder's leaf name so the OSD and playlist show a clean label
        # (e.g. "1950s" or "Cartoon College") rather than individual
        # file names like "1950s CAPTAIN KANGAROO".
        if slot.get("silent", False):
            import re as _re
            _leaf = _re.split(r"[/\\]",
                              folder_path.rstrip("/").rstrip("\\"))
            folder_label = _leaf[-1] if _leaf else folder_path
            for item in items:
                item["title"] = folder_label

        return items
