# Smart TV Channels (plugin.video.smartchannels)

Turn your own Kodi library into broadcast-style TV channels. Pick the shows, movies, music or folders for a channel and Smart TV Channels plays them back to back, keeps a rolling queue, remembers where you stopped and shows "Coming Up Next" and a channel logo while you watch.

Requires Kodi 21 (Omega) or newer. Video add-on, Python 3.

## What it does

- **Channel types:** TV (round robin or random across shows), Serial (each show plays through before the next), Movie, Folder, Audio, Party Mode, and Combo Block (a building block used inside other channels).
- **Rolling queue:** every time an item finishes it is replaced at the end of the queue, so a channel never runs dry.
- **Resume:** stop a channel and pick it up where it left off.
- **Interleave:** weave movies, cartoons, bumpers or other channels into a TV channel every N episodes.
- **Filters and exclusions:** genre, year, rating, studio, MPAA, watched status; exclude single episodes, seasons or movies.
- **Carousel:** a channel that keeps advancing while you are not watching, like a real channel.
- **Schedules:** drop special programming into a channel at a set day and time.
- **Auto-Create:** build many channels at once, grouped by decade, genre or studio.
- **Overlays:** Coming Up Next and a channel logo, with corner, size and timing settings.
- **Several devices:** point every device at one shared folder so they use the same channels and queues.
- **Backup and restore** of all add-on data.

## Quick start

1. Install the add-on and open **Settings > Channels**.
2. Choose **Refresh Library Cache** (Settings > Cache) the first time.
3. Choose **Create New Channel**, name it, pick a type and follow the prompts.
4. Choose **Open Smart Channels**, select the channel's context menu and choose **Play Channel**.

## Documentation

- `USER_MANUAL.md`: the full user manual.
- `CHANGELOG.md`: what changed in each version.

## Data and privacy

Channel definitions, queues and play state are stored as JSON files in the add-on data folder, or in the shared folder you set under Settings > Network. Nothing is sent over the internet.

## Reporting problems

Set the log level in Settings > Advanced, reproduce the problem, and include `kodi.log` with your report. Lines from this add-on start with `[plugin.video.smartchannels]`.
