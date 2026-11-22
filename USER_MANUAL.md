# Smart TV Channels – User Manual

Version 3.1.165 · For Kodi 21 (Omega) and newer

---

## 1. What Smart TV Channels Does

Smart TV Channels turns your own Kodi library into broadcast-style television. You build **channels**. Each channel plays its shows, movies, music or files one after another, keeps a rolling line-up, remembers where you stopped, and can show a "Coming Up Next" notice and a channel logo while you watch.

You can have a channel of nothing but one sitcom, a "1980s Comedy" channel made from many shows, a movie channel, a cartoon block that is dropped into other channels, or a music channel.

## 2. Requirements and Installation

- Kodi 21 (Omega) or newer.
- A Kodi video library with your TV shows and movies scanned in. For music channels, a Kodi music library.
- **Episode durations:** the best source of an episode's length is its `.nfo` file (the normal Kodi/Tiny Media Manager kind). If it is missing or unreadable, Smart TV Channels uses the running time Kodi holds for the episode, then your default length setting; an episode is skipped only when none of the three gives a length. See section 17.

To install, use Kodi's *Add-ons > Install from zip file*, choose the add-on zip and wait for the "Add-on installed" message.

## 3. Quick Start

1. Open **Add-ons > Video add-ons > Smart TV Channels > Settings**.
2. Nothing needs doing for the library. The first time any part of the add-on is used, it reads your Kodi library by itself and shows a progress window; wait for "Library cache updated." so the wizards are fast. (You can read the library again at any time with **Settings > Cache > Refresh Library Cache**.)
3. Go to **Channels** and choose **Create New Channel**.
4. Type a name, choose the channel type and follow the prompts (section 7).
5. Choose **Open Smart Channels**. Your channel is in the list.
6. There are three ways to play it: select the channel and choose the **>> Play Channel** row at the top of its list; select any item in that list to start from that item; or open the channel's context menu (press **C**, right-click, or long-press) and choose **Play Channel**. With the side panel on (section 5), press Enter on a channel to play it.

## 4. Key Ideas

**Channel.** A saved set of rules for what to play and in what order.

**Queue.** The list of items a channel will play next. The first item is playing now. When an item ends it leaves the front of the queue and a new item is added at the back, so the queue stays the same length. A TV channel's queue always holds at least one episode of every show on the channel.

**Queue size.** The minimum number of items in a channel's queue (10 to 200). The queue can be a little longer so that every show gets its turn, and a channel with interleave always ends on a full cycle.

**Recycle.** When a show runs out of episodes, it starts again from the beginning. Every channel type recycles; there is no setting to turn it off.

**Resume.** If you stop a channel part-way through an item, it picks up at that point next time. A resume point is cleared when the item finishes, is skipped, or is moved past by the carousel. Smart TV Channels also removes, when it starts and every 6 hours, any resume point whose episode is no longer in that channel's queue (for example after you changed a show's starting episode), so an old point cannot linger.

**Hidden channel.** A channel kept out of the normal list. Hidden channels are used as building blocks (interleave and schedule sources).

**Silent item.** An item that plays but is not announced in Coming Up Next, for example a short bumper.

## 5. The Channel List

Choose **Open Smart Channels** (from the add-on or from Settings > Channels). Each channel shows its name, logo and, depending on settings, the next episode.

Open the context menu on a channel for these actions:

| Action | What it does |
|---|---|
| Channel Info | Shows the channel's type, shows, order, interleave and carousel details |
| Play Channel | Starts the channel |
| Edit Channel | Re-runs the wizard with your current choices filled in |
| Reset Channel | Starts every show at S01E01 and clears resume points |
| Rebuild Queue, Keep Places | Only on a channel that has something woven into it (interleave). Rebuilds the queue so an edited Combo Block (or any other woven-in source) shows up at once. Every show keeps its place and resume points are kept. A Combo slot that takes turns or plays several shows together starts its rotation again from its first show. A Combo show that has just been added, or was random on the last build, starts at its first episode (or its starting point). Also in the side-panel channel menu |
| Delete Channel | Removes the channel |
| Set Channel Icon | Picks a logo image for the channel (and Clear Icon to remove it) |
| Toggle Visibility | Hides or shows the channel |
| Add Schedule | Creates a scheduled block for this channel |
| Manage Interleave | Adds or changes things woven into the channel |
| View Exclusions | Lists excluded episodes or movies |
| Missing Durations (n) | Appears only when episodes were skipped for a missing length |
| Move Up / Move Down | Changes the channel's place in the list |

Which actions you see depends on the channel type. For example, Audio and Party channels have no schedule or interleave actions, Serial channels have no interleave, and Combo Blocks can only be viewed, edited or deleted.

**Reset Show on one episode.** On an upcoming TV episode (in the plain list, or in the side panel's right-hand list), the context menu offers **Reset Show**. It puts that show back to S01E01 on this channel. You are asked to confirm first, and it is refused (with a message naming the other device) while another device is playing the channel. It works the same way in both views.

**Side panel.** With **Settings > Advanced > Use Side Panel** switched on, Open Smart Channels shows a two-part panel instead of the plain list. The left part, headed **Channels:**, lists your channels; each channel has a second line showing what plays next, such as `Next: Bones · S3E4 · 42 in queue`. The right part, headed **Upcoming – <channel name>**, lists the items coming up for the highlighted channel. The highlighted channel has a blue bar. Press Enter on a channel to play it, Right to move to its items, Left to come back, **C** for the channel menu (or the episode menu when you are in the right-hand list), and Back to close. It also shows the carousel status and lets you play from any queued item.

The second line under a channel reads: the next show name (left out when the channel has only one show or the show has the channel's name), then the season and episode, then how many items are in the queue. A movie reads `Next: Title (Year) · N in queue`, a folder file shows its file name without the extension, a song shows `Artist - Title`, and a channel that mixes movies and episodes shows each item its own way. A channel with nothing queued shows "No items in queue". The lines are read when the panel opens (they are given up to four seconds in all, so a slow network share cannot hold the panel up; a line that could not be read is left blank), and the highlighted channel's line is refreshed whenever its queue changes.

**Which channel the panel opens on.** *Settings > Advanced > Channel list opens on* chooses the highlighted channel when the panel opens: **First channel** (the default), **Last channel played** (the last channel started on this device, including one started by a schedule), or **A specific channel** (press **Choose the channel to open on** to pick it; its name is shown below the button). The last channel is remembered separately by each device. If the remembered channel has since been deleted, or is hidden while *Show hidden channels* is off, the panel opens on the first channel. Playing from an item skips the items in front of it exactly like the Next button: each one is removed and replaced by the next episode of its show at the end of the queue, so nothing is moved or played out of order. If a queued file is missing (for example after an upgrade), it is skipped, noted in the log and replaced the same way, and the channel carries on; Settings > Cache > Repair Queue Paths can fix paths that changed. The side panel's channel menu also offers Rebuild Queue, Keep Places on channels that have something woven into them. The plain-list menu above is used when the side panel is off. The panel's colours and text sizes are fixed; they are not settings.

**Sorting.** *Settings > Channels > Sort Channels A-Z* puts the list in alphabetical order. Move Up / Move Down fine-tunes it.

## 6. Channel Types

### 6.1 TV Channel

The most common type. You pick one or more shows.

- **Round-Robin:** one episode from each show in turn (Show A, Show B, Show C, Show A…).
- **Random:** episodes of the shows come up in random order.

With either choice, and two or more shows, you are asked for the **show order**: keep your selection order, shuffle, or set it manually. A shuffled or manual order is shown as a scrolling list of every show before you accept it. The shows then come round in that order, again and again; it is fixed when you create or edit the channel, not reshuffled every cycle.

For each show you can also choose sequential or random episode order, and play more than one episode per turn (for example Show A twice, then Show B once).

### 6.2 Serial Channel

Each show plays all the way through before the next one starts. Choose the shows, then choose the show order (keep your selection order, shuffle, or set it manually).

### 6.3 Movie Channel

Plays movies in order or at random. You can use the whole movie library, pick specific movies, or add filter rules (genre, year, rating, studio, MPAA, watched status). You can also exclude individual movies.

### 6.4 Folder Channel

Plays every video file in a folder you choose, in order or at random. A random Folder channel plays every file once before repeating. Folder channels always recycle. Pick folders through Network Locations (smb://Server/Share/...) if the channel is played on more than one device: a drive letter such as D:\ exists only on the device that has that drive, and you are warned when you choose one. Files without a duration use the **Default Folder Item Duration** from Settings > Channels (default 120 seconds).

### 6.5 Audio Channel

A music channel. Choose the source (the whole library, selected artists, or a genre/year/rating filter), then the play order:

- **Random (no repeats):** every song plays once before any repeats.
- **Album order:** albums play in order, optionally with the albums shuffled so every album plays once before any repeats.
- **Balance Artists:** gives every artist equal turns. When an artist runs out of songs, only that artist starts over.

You can exclude specific songs from the albums you include. A songs cache is built in the background the first time and can be rebuilt from Settings > Cache.

### 6.6 Party Mode Channel

Plays a folder of music files in random order, with or without repeats.

### 6.7 Combo Block

A reusable group of items (called *slots*) that is **not played directly**. Each slot is a folder, a single file, a movie source or a TV show source. A Combo Block is used inside another channel through Manage Interleave or a Schedule. Example: one block made of a cartoon, a second cartoon and a vintage bumper.

For each slot you choose the source, how many items it plays per turn, and whether it plays silently. A **Single File** slot has no count: it plays its one file once each time the block comes round. Editing a Combo Block changes only items added from then on; items already queued do not change.

**A TV slot with two or more shows** asks how they share the slot:
- **Together: every show plays in every cycle.** Each show plays its own number of episodes (you are asked for it per show) every time the block comes round. Show A with 2 and Show B with 1 gives A, A, B, then A, A, B again.
- **Taking turns: one show per cycle.** Only one show plays each time the block comes round, and the next show gets the next cycle. You enter one number, **Episodes per turn**, used for every show. With two shows and 2 episodes per turn the cycles go A, A, then B, B, then A, A, and so on. Any whole number from 1 up works, so an odd number needs no special handling.

**A Single File slot** plays one media file (a station ident, a bumper, a short film) that does not need a folder of its own. Choose *Single File* as the slot's source, then pick the file in the file browser. Pick a file on a network location (smb://...) so every device can play it; a file on a drive letter such as D:\ exists only on that device and you are warned. The file's running time is read like a Folder file's (from its `.nfo`, otherwise the *Default Folder Item Duration* setting). The same file is added again every time its slot comes round, so it can appear more than once in the queue. Inside a scheduled Combo Block it plays once per block and is then removed, like every other scheduled item; a block made only of the same file still counts each play and finishes.

A slot with a single show always plays together. To change an existing slot, edit the Combo Block and go through that slot again; the question shows the current choice. Items already in a queue do not change. The same helps apply to a TV or Movie slot as to a TV or Movie channel: editing a TV slot keeps its episodes-per-turn numbers (you are asked whether to keep, change or set only new shows), shows already on the slot stay in the list when a filter does not match them, and with a filter in use you can add shows or movies that the filter does not match.

## 7. Creating a Channel – Step by Step

Settings > Channels > **Create New Channel**.

1. **Name.** Names must be unique.
2. **Type.** TV, Serial, Movie, Folder, Audio, Party Mode or Combo Block.
3. **Pick content.**
   - For TV and Serial, your library may be large, so you are asked *Show All* or *Filter First*. Filter First narrows the list by genre, year and so on before you tick shows.
   - For Movies, choose all movies, specific movies, or a filtered set.
   - With a filter in use you are asked whether to **add shows (or movies) that do not match the filter**. Tick the extra titles you want; they play next to the filtered ones. When you edit the channel later the extras are already ticked, and unticking removes them. Shows already on a TV channel always stay in the list when you edit it, even if the filter does not match them.
   - Select Specific Movies on a channel that was built with a filter shows only the movies the channel really plays as ticked (the ones the filter matches, minus exclusions, plus the ones you added).
   - When you edit a TV channel in which some show plays more than 1 episode per turn, you are asked whether to **keep those numbers**, change them for every show, or (if you added shows) set only the new shows. Keep asks nothing more. New shows start at 1.
   - For Folder, Audio and Party, choose the folder or music source.
4. **Order.** Round-Robin or Random (TV); show order (Serial); In Order or Random (Movie).
5. **Starting point** (TV and Serial). Start from S01E01, set starting points by hand for each show, or **Surprise Me!** for random starting episodes (you can *Try Again*).
6. **Optional per-show settings.** Episodes per turn for each show, sequential or random order per show, episode filters, and exclusions (sections 8 and 9).
7. **Queue size.** Minimum 10, maximum 200. The default comes from Settings > Playback.
8. **Visibility.** Show the channel in your list, or hide it.

When you edit a channel, your shows keep their current position unless you change the rotation. If you change the Random setting, you are told that saved resume points for that channel will be removed.

## 8. Filters

Filters narrow the shows or movies you can pick from. They are available when choosing TV shows (Filter First), movies, and audio.

**Filter types**

| Filter | Comparisons |
|---|---|
| Genre | is, is not, contains, does not contain |
| Studio / Network | is, is not, contains, does not contain (*contains* and *does not contain* ask you to type part of the name, for example "Universal") |
| MPAA Rating | is, is not, contains, does not contain |
| Year | =, !=, >, >=, <, <= |
| Rating (0–10) | =, !=, >, >=, <, <= |
| Watched status | watched or unwatched |

**Combining rules.** When you add a second or later rule, you choose how to join it to the one before:

- **AND:** both rules must match.
- **OR:** either may match.

AND is applied before OR. So "Genre is Comedy AND Year >= 1990 OR Genre is Drama" means *(Comedy and 1990 or later)* or *Drama*.

In the filter menu you can **Remove last filter rule**, **Clear all filters**, and choose **Done**. The summary lines show each rule in full, such as "Genre is not Comedy" or "Year >= 2000".

Episode filters (watched only, unwatched only, a season, or a first-aired date) can be set per show for TV and Serial channels.

## 9. Exclusions

Exclusions remove specific content from a channel without removing the whole show.

- **Exclude Episodes:** pick a show, then exclude whole seasons or individual episodes.
- **Exclude Movies:** pick movies that must never play on the channel.
- **Exclude Songs:** audio channels, per album.

Use **View Exclusions** in the channel's menu to see what is excluded.

## 10. Interleave

Interleave weaves other content into a **TV, Movie or Folder channel** (not Serial, Audio or Party channels, and not Combo Blocks). Example: a cartoon block after every three episodes, or a bumper after every movie.

Open the channel's menu and choose **Manage Interleave**, then **Add Source**.

- **Source.** A *hidden* channel. It can be a hidden TV, Movie or Folder channel, or a Combo Block. Serial, Audio and Party channels cannot be sources, and a channel with Carousel on cannot be a source. A source channel stays hidden while it is in use.
- **Mode.** *Fixed* inserts exactly every N items. *Random* inserts every N ± J items, where J is the jitter you choose.
- **How many.** How many items (or complete blocks) are inserted each time.
- **Silent or Visible.** Silent items play without being named in Coming Up Next.

Choose **Edit / Remove Sources** to change a source, or **Remove All Interleave** to strip every interleaved item from the queue. When you remove a source you are asked whether to reset it so it starts from the beginning next time. After the last source is removed, a TV channel's queue is refilled to its full queue size.

**Jitter and queue size.** With *Random* mode the jitter is chosen at random once, when the queue is built; after that the same pattern repeats as the queue cycles. A bigger queue therefore looks more random, because the pattern takes longer to repeat. *Rebuild Queue, Keep Places*, Reset Channel, or changing the sources in Manage Interleave gives a new pattern.

**Replacement keeps the pattern.** A finished episode is replaced by the next episode of the same show. A finished interleaved item is replaced by the next item from the same source. The queue length and the pattern stay fixed.

**Queue size with interleave.** The queue size is a minimum and counts every item, episodes and interleaved. The queue always ends right after a complete interleave cycle, so it may be larger than the number you chose. Example: one show, a block of 2 after every 3 episodes, queue size 10 gives exactly 10 items; size 11 gives 15.

## 11. Carousel

Normally a channel waits where you left it. With **Carousel**, the channel keeps moving on its own while you are not watching, like a real channel that is always on.

Enable it in the wizard (or from Edit Channel):

- **Timed:** every X minutes (minimum 1), remove Y items from the front of the queue.
- **Duration:** the front item leaves the queue when its own running time has passed.

Items the carousel moves past have their resume point cleared. With *Remove scheduled blocks when their time slot ends* on (section 12), a carousel channel that has a scheduled block at the front of its queue is left alone by the carousel until the block has gone; the time the block took is not owed afterwards, so the carousel does not catch up in a burst. Carousel channels cannot be hidden. A channel that is the source of an active schedule cannot use Carousel (and the reverse).

Channel Info shows the carousel settings and when the next pop is due. If a show on a carousel channel has no playable episode, the carousel retries about every minute.

## 12. Schedules

A schedule puts **special programming** into a channel at a chosen time. It takes items from a *source* channel and puts them at the front of a *target* channel's queue. They play as the next items, then the channel carries on with its regular queue.

Settings > Channels > **Manage Schedules**, or Add Schedule from a channel's menu.

1. **Name.**
2. **Target channel.** Where the programming appears.
3. **Source channel.** Where the items come from. Each target needs its own dedicated source channel.
4. **Day.** Daily, Weekdays (Mon–Fri), Weekends (Sat–Sun), a single weekday, or **Once** on a date (DD/MM/YYYY).
5. **Start time** (HH:MM, 24-hour).
6. **Number of items.** When the source is a Combo Block, this is the number of complete blocks: 2 plays the whole block twice, each slot in its listed order.

The schedule list shows `[ACTIVE]` or `[OFF]`; select a schedule to edit, activate, deactivate or delete it. A conflict message appears if the target already has a schedule at that time. If you enter a time that has passed today, you are told the schedule will next fire tomorrow.

A schedule fires once a day, as soon as its start time has passed, on one device. If a device is playing the target channel, that device fires it. If no device is playing it, any device running Smart Channels on the same shared folder fires it; the first one to claim the schedule builds the block and the others leave it alone. A device never fires a channel that another device is playing. The block is added to the front of the channel's queue and plays when the item that is currently playing finishes, or when you next start the channel. If you are watching that channel, the block starts after the current episode ends even when the next episode of the old queue has already begun.

Only one scheduled block waits in a channel at a time. While any item from a schedule is still in the channel's queue (not yet watched or skipped), every other schedule for that channel is skipped: a repeating schedule tries again on its next day, and a one-time schedule is switched off. If several schedules are due together, the earliest start time goes first. On a channel with a carousel that is not playing, the block's items are removed by the carousel at its normal pace, and the next schedule can then fire. With *Remove scheduled blocks when their time slot ends* on (Settings > Channels, off by default) this changes: each block item is removed from the queue when its time slot ends, measured from the schedule's start time and the running times of the items (an item with no length counts as the default TV episode or movie length from the settings; 30 or 100 minutes if that default is 0). Nothing is added to replace a removed item. A channel that is being played on any device is left alone until playback stops. On a carousel channel the carousel does nothing while a block is at the front and does not owe the time afterwards, so there is no burst of pops when the block has gone. A block that fired while Kodi was off, or that you never watched, waits at the front until you watch or skip it. While a block is waiting to play or playing, the channel shows "Now — Scheduled Block". Coming Up Next and the side panel also name upcoming blocks.

## 13. Auto-Create Channels

Settings > Channels > **Auto-Create Channels** builds many channels in one go.

1. Choose what to create channels for: TV Shows only, Movies only, or both.
2. Choose how to group: **Decade**, **Genre**, **Genre + Decade**, or **Studio / Network**.
3. Set the minimum number of items a group needs before it is selected by default (0 shows every group).
4. Optionally create interleaved TV + Movie channels, with a movie woven in every N episodes (1 to 20).
5. Review the preview list, untick anything you do not want, and choose **Create selected**.

Groups that fall below the minimum appear in the list but are not ticked. Names that already exist are skipped. The global defaults (rotation and queue size) are applied to all new channels; change individual channels afterwards with Edit Channel. The library cache must exist first.

## 14. Coming Up Next and the Channel Logo

### 14.1 Coming Up Next

A small overlay that announces what plays after the current item.

Settings > **Coming Up Next**:

| Setting | Default |
|---|---|
| Enable Coming Up Next overlay | On |
| Corner position | Bottom Right |
| Show overlay this far before episode ends | 2 Minutes (choices 1–5) |
| Display duration (seconds) | 8 |
| Show show / movie name | On |
| Show season and episode number | On |
| Show episode title | On |
| Minimum item duration to show overlay (seconds, 0 = always) | 120 |
| Suppress during silent interleave items | On |

Audio has its own set: Enable Audio Coming Up Next (On), seconds before end of song (20), overlay duration (15), minimum song duration (60).

**While an overlay is on screen** (Coming Up Next or the channel logo) **every button on the remote is inoperable** until it disappears; that is how Kodi treats these overlay windows. Keep the display durations short if this bothers you.

### 14.2 Channel Logo Overlay

Shows the channel's logo in a corner for a few seconds when an item starts. Settings > **Channel Logo Overlay**:

| Setting | Default |
|---|---|
| Show Channel Logo During Playback | Off |
| Logo Corner | Top Right |
| Logo Size | Medium (Small, Medium, Large) |
| Logo Opacity | Medium (Low, Medium, High) |
| Margin from Edge (pixels) | 30 |
| Display duration (seconds) | 5 |

The logo is found in this order: the image you chose with **Set Channel Icon** (png or jpg), then a picture in the **Channel Icon Folder** (Settings > Channels, network folders allowed) whose file name matches the channel name, for example `Comedy Channel.png`, then a default icon. Name matching ignores upper and lower case.

## 15. Settings Reference

**Channels**

- Create New Channel, Auto-Create Channels, Open Smart Channels, Manage Schedules, Sort Channels A-Z.
- *Channel Icon Folder:* a folder of logo pictures named after your channels (for example `Comedy Channel.png`).
- *Remove scheduled blocks when their time slot ends:* default Off. When on, block items that nobody watched are taken out of the channel when their time slot ends, so a missed block does not wait at the front. See section 12. Turn it on for every device that shares the folder.
- *Default Folder Item Duration:* length used for folder files with no known duration (default 120 s).
- *Default TV Episode Length* and *Default Movie Length:* minutes used when an episode or movie has no readable `.nfo` and Kodi holds no running time for it (defaults 30 and 100; 0 skips such items). An episode with no readable `.nfo` first uses the running time stored in Kodi.

**Playback**

- *Default Minimum Queue Size:* default 30.
- *Randomize by Default:* default Off.
- *Reset watched status after each item plays:* default Off.

**Cache**

- *Maximum age before auto-refresh (days):* default 7.
- *Kodi library scans:* whenever Kodi finishes a library scan, each device that has Kodi running rebuilds the library list (`local_library.json`) in the background, so new episodes are known without any action from you.
- *Auto-rebuild Kodi library cache on expiry:* default On. The cache file is checked for age when the add-on is opened; if it is older than the setting above it is rebuilt with a progress window. With the daily library update switched on the file is rarely older than a day, so this works as a safety net.
- *Library cache age*, *Songs Cache Age:* read-only information.
- *Refresh Library Cache, Rebuild Songs Cache.*
- *Update the library automatically every day* (off by default) and *Daily library update time (HH:MM)* (04:00): once a day, at that time, one device rebuilds the shared library cache, then does what *Repair Queue Paths* does and puts back any show missing from a TV queue. Turn it on in each device's settings. If you switch it on after its set time has passed for today, it runs at once (within about a minute) rather than waiting for tomorrow. If the library list was already rebuilt within the last hour (for example by a Kodi scan), it is used as it is and not rebuilt again; the rest of the job still runs. A channel that is being played on any device is skipped and retried every hour (three tries); after that it is left as it was until the next day. Other devices reload their library lists on their own when the cache file changes. Nothing is deleted; queue order, carousel clocks and resume points are kept.
- *Repair Queue Paths:* updates queued TV episodes from the Kodi library when files were renamed or moved. Queue order and resume points are kept. Update the Kodi library first, and restart any channel that is playing afterwards.

**Network**

- *Shared path:* leave blank to use Kodi's add-on data folder. See section 16.
- *This device is the timing master:* default Off, and most setups never need it. It is a back-up measure for people who share the folder between two or more devices and use carousel channels and still see an episode skipped twice or missing from a queue even with *Lock the shared folder while saving* on. In that case turn it on for ONE device that is left running Kodi all day, and restart Kodi. See "Timing master" in section 16.
- *Lock the shared folder while saving:* default On. See section 16.

**Resume**

- *Enable resume on stop:* default On.
- *Background polling interval (seconds):* default 60.
- *Ask before resuming:* default On. When on, you are asked "{item} — resume from {time}?".

**Advanced**

- *Show Next Episode in Channel View, Show Episode Count:* default On.
- *Show hidden channels:* default Off.
- *Number of upcoming programs to show:* default 5.
- *Use Side Panel:* default Off.
- *Channel list opens on:* First channel (default), Last channel played, or A specific channel, for the side panel (section 5). **Choose the channel to open on** picks the specific channel.
- *Log level:* **Warning** writes only warnings and errors to the Kodi log; **Info** (the default) also writes the add-on's normal progress lines; **Debug** writes everything. Use Info for normal use and for any testing, because the progress lines are what show what the add-on did. The setting is re-read about every five seconds, so a change takes effect without restarting Kodi.
- *Keep a draw journal:* default On. See section 18a.
- *Delete All Addon Data:* removes everything Smart TV Channels has saved, from both the local and the shared folder: channels, schedules, play state and its saved copies, kept positions, queues, channel locks and the library and song caches. Your settings and this device's identity are kept. Take a backup first.

**Backup & Restore**

- *Backup folder path, Backup Addon Data, Restore Addon Data.* See section 18.

**Tools**

- *ffprobe path, Scan Folder for Durations, View Missing Durations Log.* See section 17.

## 16. Using Several Devices (Shared Folder)

Two or more Kodi devices can share the same channels and queues.

1. Choose a folder both devices can reach, for example a network share.
2. On each device, set **Settings > Network > Shared path** to that folder.
3. The first time you change the path you are offered to **copy your existing data** to the new location. Accept this on the device that already has your channels. On a second device that has no channels yet, decline the copy so the shared data is not overwritten.
4. If you later clear the path, you are offered to copy the files back to the local Kodi folder.

The shared folder then holds channels, play state, queues, the library cache and the missing-durations log. Both devices should use the same Kodi library (for example a shared MySQL database). If two devices save a channel's positions at the same moment and one overwrites the other, the add-on notices a moment later and writes the lost positions again (the log says `was overwritten by another device`). Local working copies that deleted channels leave in a device's own add-on folder are removed when the add-on starts. The small `channel_lock_<id>.json` files that stop two devices playing one channel are removed when a device stops the channel; any that are left behind (Kodi was closed or crashed) are removed at start-up and every 6 hours once they are an hour old or their channel is gone. Carousel channels are safe on two devices; each device checks before it advances a queue so a pop is not applied twice.

**One device per channel.** Only one device can play a given channel at a time. The first device to start it owns it; a second device that tries to start the same channel sees a message naming the other device, and nothing plays. When the channel becomes free (the owner stops, switches channel, closes Kodi, or loses power for about 3 minutes) the second device gets a notification, even if it is playing another channel by then. Different channels can be played on different devices at the same time. A carousel channel that is playing on one device is not advanced by the other devices. A channel that another device is playing also cannot be edited, reset, deleted, have its interleave managed or have a show reset from the other devices; you get the same message and notification.

**Daily library update (optional).** With *Update the library automatically every day* (Settings > Cache) switched on, at the chosen time one device wins the job and the others stay quiet; you can switch it on in every device's settings or in just one. It rebuilds the library cache file in the shared folder, repairs queued file paths and puts back missing shows. A channel that is being played on any device is skipped and retried every hour (three tries). The other devices notice the new cache file within a minute and reload their library lists by themselves.

**Timing master (optional, off by default).** Most setups never need it. Leave it off unless you share the folder between two or more devices, have at least one carousel channel, **and** still see problems that the folder lock (below) does not cure: an episode skipped twice, or queue items that go missing.

*What it is for.* On a carousel channel, something has to advance the queue while nobody is watching. Every device that is running Kodi checks the carousel clocks about once a minute, so two devices can find the same pop due within a few seconds of each other. The add-on already guards against this in two ways: each device claims a pop before it does it, and *Lock the shared folder while saving* (below, on by default) makes the claim check one device at a time. Together these are normally enough. The timing master is a different kind of protection that you keep in reserve: instead of making the devices take turns, it stops all but one of them from trying to pop at all. Switch it on only if double pops or missing queue items appear even with the folder lock on.

*What the setting does.* One device is named the timing master. While it is running, it is the only device that pops carousel episodes, for every channel. The other devices still keep the clock of whichever channel they are playing, so that clock stays right, but they leave the popping to the master. Nothing else changes: channels, queues, schedules and playback behave as before on every device.

*How to set it up.*
1. Pick ONE device that is left running Kodi all day, such as a media PC or a Shield that is never switched off. It does not have to be playing anything. Do not pick a device that is often off.
2. On that device only, open Settings > Network and switch on **This device is the timing master**.
3. Restart Kodi on that device. Leave the setting off on every other device.

*How it works.* The master writes a small file, `master.json`, in the shared folder about once a minute. A device that is not the master looks at that file and, while the file keeps changing, leaves the pops to the master. Each device judges this by its own clock, so a device whose clock is a few seconds wrong does not matter.

*If the master is turned off.* Nothing stops. After five minutes with no new heartbeat, the other devices start popping again exactly as they did before the setting existed, and they hand back to the master when it returns. If you switch the setting on for two devices by mistake, only the one with the lower device id acts and the other defers.

*What to expect.* The journal (section 18a) records `master_seen`, `master_lost` and `master_back` when the other devices notice the master appear, disappear and return, and `follower_skip` (once an hour) with how many pops each follower left to the master. The master only decides who pops the carousel; every device still saves its own positions and queues, and the folder lock still applies to those saves. If you use a single device, or have no carousel channels, leave the setting off; it does nothing useful there.

**Lock the shared folder while saving.** When several devices share the folder, each device takes a lock while it saves state.json and while it claims a carousel pop, so two devices cannot overwrite each other's changes. The lock is one small file, `mutex.dat`, in the shared folder (created by the first device if it is missing). A device that finds it taken waits up to two seconds and then saves anyway, so a stuck share can never freeze playback; the journal records every such case (`lock_fail_open`). A lock left behind by a device that was switched off in the middle of a save is taken over by another device after two minutes. Settings > Network > Lock the shared folder while saving; leave it on. Without a shared folder it does nothing. The lock and the timing master do different jobs and can be used together: the lock makes devices take turns while they save and claim, the master stops the other devices from popping at all.

**Tip.** If a network share is briefly unavailable, one episode may be skipped for that cycle and logged. See section 17.

## 17. Episode Durations and the Missing Durations Log

Smart TV Channels needs each item's running time to schedule the carousel and Coming Up Next. It looks for the length in this order and uses the first one that gives a number:

1. **The `.nfo` file** (`durationinseconds`).
2. **The running time Kodi holds** for the episode or movie in its library. A value under 60 seconds is treated as a wrong unit and ignored.
3. **Your default length** from Settings > Channels: *Default TV Episode Length* (30 minutes unless you change it) and *Default Movie Length* (100 minutes). Movies use it only when Kodi holds no running time for the movie.

So an episode whose `.nfo` is missing or unreadable is still queued, with Kodi's running time or your default, and the queue stays the same size. Whenever step 2 or 3 is used the Kodi log gets a line starting `Duration fallback:` with the source (`kodi_runtime` or `default_setting`). An item that took Kodi's running time (step 2) is not added to the Missing Durations list. An episode or movie that had to take your default length (step 3) **is** added, once per file in each Kodi session, and marked *(default length used)*, so you know its length is a guess; it stays in the queue. Folder files are not listed for this, because every folder file without a length takes the default until it has played once (see below).

**If none of the three gives a length** (no `.nfo`, no running time in Kodi, and the default is set to 0) the episode is skipped as if it had played, the next episode of that show takes its place, and the skip is logged.

**Where it is logged**

- A per-channel list. Open it with the channel's *Missing Durations (n)* menu entry, or in the side panel. Each row reads *show — episode — title* with the file path under it, and *(default length used)* after the rows for guessed lengths. It has a *Clear Missing Durations List* option. Rows saved by builds before 3.1.159 may show the episode title where the show name belongs; clear the list to get the new format.
- A shared text file, `missing_durations.txt`, in the data (or shared) folder. View or clear it from **Settings > Tools > View Missing Durations Log**. If nothing has been recorded you see "No missing durations have been recorded."

**Fixing missing durations**

- Make sure each episode has a `.nfo` containing the stream details and duration. Episodes that rely on Kodi's running time or your default length work, but their times are less exact.
- **Folder channels learn lengths by themselves.** A folder file with no known length is queued with *Default Folder Item Duration*. When it finishes playing, the add-on writes a small `.nfo` next to the video that holds only the real length (`durationinseconds`) and corrects the queue entry, so later queues use the real length. This happens for folder items only, not for TV episodes or movies from your Kodi library.
- **Scan Folder for Durations** (Settings > Tools, Windows only) uses `ffprobe` to read each video file and write the missing NFO data. Set the *ffprobe path* if it is not on your system PATH. The scan still treats a missing `.nfo` as missing, even when Kodi or your default would supply a length. It reports how many files were scanned, how many NFOs were written, how many already had durations and how many failed, and can be cancelled.

## 18. Backup and Restore

- **Backup Addon Data** (Settings > Backup & Restore) copies your data into one backup file in the backup folder you set. The backup folder can be a network path and is set on each device separately. The backup holds channels, schedules, play state, the library cache, the song cache, what is playing now, and the queue of every channel that exists (queues of deleted channels are left out). The log records the result: `backup: N file(s) copied to <file>`, or `NOT copied` with the reason. A copy that the network share refuses is tried up to three times before it is reported as failed. When a copy is refused, the log line also says how big the zip was, what the share showed, and how long after a video stopped the copy was tried; after a successful copy it states whether the saved file has the same size as the zip that was sent. The backup also holds the draw journals of the last three days (see section 18a); Restore does not offer them.
- **Restore Addon Data** lists the backups it finds. Choose one, choose which files to restore, confirm the overwrite, and restart Kodi when asked.
- The add-on also keeps rolling copies of your channel positions on the shared folder (`state.bak0.json` to `state.bak7.json`, one every 3 hours, about 24 hours in all), and one copy per day for the last 14 days (`state.day0.json` to `state.day13.json`). If a channel's positions are ever saved with far fewer shows or far lower positions than before, the log says so and the earlier positions of that channel are kept in `cursor_kept_<first 8 characters of the channel id>.json`. If positions are ever lost, close Kodi on every device and copy the newest good copy over `state.json`.

Take a backup before you use Delete All Addon Data, Restore, or change the shared path.

## 18a. The draw journal (diagnostics)

The add-on keeps a journal of what it does to every channel's queue: each episode taken off the front, each episode added, the show's position before and after, wraps back to the first episode, skips, and a check point of every TV channel once an hour. It is written on every device to `journals/` in the add-on data folder and copied every few minutes to a `journals` folder inside the shared storage folder, together with a copy of the previous Kodi log (`kodi_old_...`) made each time Kodi starts. The newest five logs per device and 5 days of journals are kept. The journal lines that record every state save and clock check are large and are written only when Settings > Advanced > *Log level* is set to Debug; at Warning and Info the journal holds everything a normal review needs, in far less space. Nothing in the journal changes how the add-on plays.

- To investigate a problem, give the developer the journal files from `<shared folder>/journals/` for the days in question, the Kodi logs, and a backup made at the start and at the end of the period. The tool `journal_check.py` reports what the files cover, every position that moved without a recorded draw, and every hole.
- The journal also records scheduled-block items removed when their slot ended (`block_expired`) and the daily library update (`upkeep_start`, `upkeep_skipped`, `upkeep_done`).
- Settings > Advanced > *Keep a draw journal* turns it off. *Delete All Addon Data* deletes the journals.

## 19. Troubleshooting

| Problem | What to try |
|---|---|
| "The library cache has not been built yet" (seen only on the Auto-Create Channels screen) | Open Settings > Cache and choose Refresh Library Cache. The add-on normally builds it by itself the first time it is opened, so you rarely see this |
| A channel shows "No items in queue" | Nothing playable could be queued: its shows have no episodes with a usable length, a filter matches nothing, or its folder is empty. Check Missing Durations (n), the filters and the folder, then Reset Channel (or Edit Channel and save) to build the queue again |
| The side panel opens on the wrong channel | Check *Settings > Advanced > Channel list opens on*. A deleted channel, or a hidden one while *Show hidden channels* is off, makes the panel open on the first channel |
| The Kodi log is too full, or has too little in it | Settings > Advanced > Log level: Warning for the least, Info for normal use, Debug for the most |
| Carousel channels lose an episode, or pop twice, when several devices share the folder | First check *Lock the shared folder while saving* is on (Settings > Network). If it still happens, set one always-on device as the timing master (section 16) |
| A show disappears from the rotation or an episode never plays | Check Missing Durations (n) for that channel; fix the `.nfo` |
| Files were renamed or moved and queued episodes will not play | Update the Kodi library, then Settings > Cache > Repair Queue Paths, and restart the channel. The daily library update (Settings > Cache) does this for you each night |
| Channel logo does not appear | Make sure the overlay is enabled, the channel has an icon, and the version is current. Logo shows when an item starts |
| Coming Up Next does not appear for short items | Raise or lower *Minimum item duration*; items shorter than the limit are skipped |
| "Combo Blocks cannot be played directly" | Use the block as an interleave or schedule source in another channel |
| Cannot hide a channel | It is a carousel channel or a source in use. Disable the carousel or remove it as a source first |
| Cannot delete a source | You are warned that deleting it breaks the link; choose Delete anyway only if intended |
| Edit Channel says the queue could not be read, or that the positions could not be saved | The shared folder was busy for a moment. Nothing was changed and the old queue and positions were kept. Wait a few seconds and save again |
| Backup does not finish | Check that this device's *Backup folder path* is set and reachable (smb://... rather than a drive letter), then look in the log for `backup:` lines. |
| Two devices disagree about a queue | Make sure both use the same shared path and the same Kodi library, and restart both |
| Anything else | Set Log level to Debug, reproduce, and read `kodi.log`. Lines from this add-on begin with `[plugin.video.smartchannels]`. Put it back to Info afterwards |

## 20. Glossary

**Carousel** – a channel that advances on its own.
**Combo Block** – a reusable group of slots used inside other channels.
**Interleave** – inserting other content every N items.
**Jitter** – random variation of N in interleave.
**Queue** – the line-up of items a channel will play.
**Recycle** – restarting a finished show from the beginning.
**Silent item** – an item not announced in Coming Up Next.
**Side panel** – the two-part channel view (channels on the left, upcoming items on the right) used when *Use Side Panel* is on.
**Slot** – one source inside a Combo Block.
**Source channel** – a hidden channel that supplies items to another.
**Target channel** – a channel that receives scheduled items.
**Timing master** – an optional back-up setting: one always-on device pops the carousel channels and the others leave it to that device (section 16). Off by default.

---

## Appendix A – Screenshot Shot List

For the final published manual, capture these screens:

1. Settings > Channels page.
2. Channel list with several channels and icons.
3. Channel context menu.
4. Channel Info dialog (TV channel with interleave and carousel).
5. Create New Channel – channel type choice.
6. TV wizard – show selection with Filter First.
7. Manage Filters menu with a few rules.
8. Starting Point choices.
9. Manage Interleave – source edit dialog.
10. Combo Block slot list.
11. Carousel settings.
12. Add Schedule – day and time pickers; schedules list.
13. Auto-Create preview list.
14. Coming Up Next overlay on video.
15. Channel logo overlay on video.
16. Side panel with upcoming items.
17. Missing Durations list.
18. Settings > Network, Backup & Restore, Tools.
