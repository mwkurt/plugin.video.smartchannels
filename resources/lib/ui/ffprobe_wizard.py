"""
resources/lib/ui/ffprobe_wizard.py
====================================
Wizard UI for the ffprobe batch NFO scanner.

OWNS:
  - Platform check (Windows-only gate)
  - ffprobe discovery (delegates to ffprobe_scanner.find_ffprobe)
  - Folder picker dialog
  - Progress dialog (drives ffprobe_scanner.scan_folder)
  - Results dialog

NEVER:
  - Scanner logic (ffprobe_scanner.py owns that)
  - State reads/writes (channel_manager.py owns those)
  - Queue access (channel_manager.py owns that)
  - Playback control (service.py owns that)

Ported from 2.x. String IDs updated to 3.x strings.po.
"""

from __future__ import annotations

import sys

import xbmcaddon
import xbmcgui

from resources.lib.utils.ffprobe_scanner import find_ffprobe, scan_folder
from resources.lib.utils.logger import log


class FfprobeWizard:

    def __init__(self, addon: xbmcaddon.Addon):
        self._addon = addon

    def _s(self, id_: int) -> str:
        """Return localised string from strings.po. Never hardcode text."""
        return self._addon.getLocalizedString(id_)

    def run(self) -> None:
        """
        Entry point. Runs the full wizard and returns when complete
        or when the user cancels at any step.
        """
        log("[ffprobe_wizard] run: started")

        # -- Platform gate: Windows only -------------------------------------
        if not sys.platform.startswith("win"):
            log("[ffprobe_wizard] run: non-Windows platform, aborting")
            xbmcgui.Dialog().ok(
                self._s(32000),   # "Smart TV Channels"
                self._s(32907))   # "ffprobe scanning is only available on Windows."
            return

        # -- Locate ffprobe --------------------------------------------------
        explicit    = self._addon.getSetting("ffprobe_path").strip()
        ffprobe_exe = find_ffprobe(explicit)
        if not ffprobe_exe:
            log("[ffprobe_wizard] run: ffprobe not found")
            xbmcgui.Dialog().ok(
                self._s(32000),   # "Smart TV Channels"
                self._s(32908))   # "ffprobe not found. Install ffmpeg..."
            return

        log("[ffprobe_wizard] run: ffprobe at {}".format(ffprobe_exe))

        # -- Folder picker ---------------------------------------------------
        folder = xbmcgui.Dialog().browse(
            3,
            self._s(32905),   # "Scan Folder for Durations"
            "files")

        if not folder:
            log("[ffprobe_wizard] run: no folder selected, aborting")
            return

        log("[ffprobe_wizard] run: folder selected: {}".format(folder))

        # -- Progress dialog -------------------------------------------------
        progress = xbmcgui.DialogProgress()
        progress.create(self._s(32905), "")   # "Scan Folder for Durations"

        cancelled = [False]

        def _progress_callback(current, total, filename):
            if progress.iscanceled():
                cancelled[0] = True
                return
            pct = int((current / max(total, 1)) * 100)
            progress.update(pct, self._s(32909).format(filename))
                            # "Scanning: {0}"

        def _cancel_check():
            return cancelled[0] or progress.iscanceled()

        try:
            result = scan_folder(
                folder_path=folder,
                ffprobe_exe=ffprobe_exe,
                progress_callback=_progress_callback,
                cancel_check=_cancel_check,
            )
        finally:
            progress.close()

        log("[ffprobe_wizard] run: scan result={}".format(result))

        # -- Results dialog --------------------------------------------------
        if result["cancelled"]:
            xbmcgui.Dialog().ok(
                self._s(32905),   # "Scan Folder for Durations"
                self._s(32911).format(result["written"]))
                # "Scan cancelled. {0} NFOs written before cancellation."
        else:
            xbmcgui.Dialog().ok(
                self._s(32905),   # "Scan Folder for Durations"
                self._s(32910).format(
                    result["scanned"],
                    result["written"],
                    result["skipped"],
                    result["failed"]))
                # "Scan complete. {0} files scanned, {1} NFOs written,
                #  {2} already had durations, {3} failed."
