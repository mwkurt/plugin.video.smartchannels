# plugin.video.smartchannels
# channels/movies.py
#
# OWNS:   Queue building entry point for Movie channels.
#         Delegates entirely to channel_manager public methods.
#
# NEVER:  State reads/writes, library access, playback control, UI rendering.
#         Private method calls on ChannelManager (Architecture Rule 14/15).
#
# CALLERS: channel_manager.py only — via build_channel_queue() dispatch.
#
# Version: 3.0.0

from __future__ import annotations

from resources.lib.channels.base import BaseQueueBuilder
from resources.lib.utils.logger  import log


class MovieQueueBuilder(BaseQueueBuilder):
    """Queue builder for Movie channels. Thin dispatch shim."""

    def build(self, channel: dict, target_size: int) -> list:
        log("[channels/movies] build: fresh build, target={}".format(target_size))
        return self._cm.build_fresh_movie_queue(channel, target_size)

    def build_one(self, channel: dict, queued_ids=None,
                  consumed_id=None) -> list:
        """Return exactly one replacement movie for 1-for-1 replacement.

        queued_ids:  movieids of this channel already in the host queue.
        consumed_id: movieid just consumed/skipped.
        Random draws avoid both when the pool allows it.
        """
        return self._cm.build_fresh_movie_queue(
            channel, 1, queued_ids=queued_ids, consumed_id=consumed_id)
