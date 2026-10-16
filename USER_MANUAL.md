# Smart TV Channels – User Manual

Version 3.1.101 · For Kodi 21 (Omega) and newer

---

## 1. What Smart TV Channels Does

Smart TV Channels turns your own Kodi library into broadcast-style television. You build **channels**. Each channel plays its shows, movies, music or files one after another, keeps a rolling line-up, remembers where you stopped, and can show a "Coming Up Next" notice and a channel logo while you watch.

You can have a channel of nothing but one sitcom, a "1980s Comedy" channel made from many shows, a movie channel, a cartoon block that is dropped into other channels, or a music channel.

## 2. Requirements and Installation

- Kodi 21 (Omega) or newer.
- A Kodi video library with your TV shows and movies scanned in. For music channels, a Kodi music library.
- **Episode durations:** each TV episode needs a `.nfo` file (the normal Kodi/Tiny Media Manager kind) that holds the episode length. Episodes without a readable length are skipped. See section 17.

To install, use Kodi's *Add-ons > Install from zip file*, choose the add-on zip and wait for the "Add-on installed" message.

## 3. Quick Start

1. Open **Add-ons > Video add-ons > Smart TV Channels > Settings**.
2. Go to **Cache** and choose **Refresh Library Cache**. This reads your library once so the wizards are fast. Wait for "Library cache updated."
3. Go to **Channels** and choose **Create New Channel**.
4. Type a name, choose the channel type and follow the prompts (section 7).
5. Choose **Open Smart Channels**. Your channel is in the list.
6. Open the channel's context menu (press **C**, right-click, or long-press) and choose **Play Channel**.

## 4. Key Ideas

**Channel.** A saved set of rules for what to play and in what order.

**Queue.** The list of items a channel will play next. The first item is playing now. When an item ends it leaves the front of the queue and a new item is added at the back, so the queue stays the same length. A TV channel's queue always holds at least one episode of every show on the channel.

**Queue size.** The minimum number of items in a channel's queue (10 to 200). The queue can be a little longer so that every show gets its turn, and a channel with interleave always ends on a full cycle.

**Recycle.** When a show runs out of episodes, it starts again from the beginning (Folder channels always recycle).

**Resume.** If you stop a channel part-way through an item, it picks up at that point next time.

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
| Delete Channel | Removes the channel |
| Set Channel Icon | Picks a logo image for the channel (and Clear Icon to remove it) |
| Toggle Visibility | Hides or shows the channel |
| Add Schedule | Creates a scheduled block for this channel |
| Manage Interleave | Adds or changes things woven into the channel |
| View Exclusions | Lists excluded episodes or movies |
| Missing Durations (n) | Appears only when episodes were skipped for a missing length |
| Move Up / Move Down | Changes the channel's place in the list |

Which actions you see depends on the channel type. For example, Audio and Party channels have no schedule or interleave actions, Serial channels have no interleave, and Combo Blocks can only be viewed, edited or deleted.

**Side panel.** With **Settings > Advanced > Use Side Panel** switched on, selecting a channel opens a panel instead of the plain context menu. It shows what is coming up, the carousel status, and lets you play from any queued item. The plain-list menu above is used when the side panel is off.

**Sorting.** *Settings > Channels > Sort Channels A-Z* puts the list in alphabetical order. Move Up / Move Down fine-tunes it.

## 6. Channel Types

### 6.1 TV Channel

The most common type. You pick one or more shows.

- **Round-Robin:** one episode from each show in turn (Show A, Show B, Show C, Show A…).
- **Random:** episodes of the shows come up in random order.

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

A reusable group of items (called *slots*) that is **not played directly**. Each slot is a folder, a movie source or a TV show source. A Combo Block is used inside another channel through Manage Interleave or a Schedule. Example: one block made of a cartoon, a second cartoon and a vintage bumper.

For each slot you choose the source, how many items it plays per turn, and whether it plays silently. Editing a Combo Block changes only items added from then on; items already queued do not change.

**A TV slot with two or more shows** asks how they share the slot:
- **Together: every show plays in every cycle.** Each show plays its own number of episodes (you are asked for it per show) every time the block comes round. Show A with 2 and Show B with 1 gives A, A, B, then A, A, B again.
- **Taking turns: one show per cycle.** Only one show plays each time the block comes round, and the next show gets the next cycle. You enter one number, **Episodes per turn**, used for every show. With two shows and 2 episodes per turn the cycles go A, A, then B, B, then A, A, and so on. Any whole number from 1 up works, so an odd number needs no special handling.

A slot with a single show always plays together. To change an existing slot, edit the Combo Block and go through that slot again; the question shows the current choice. Items already in a queue do not change.

## 7. Creating a Channel – Step by Step

Settings > Channels > **Create New Channel**.

1. **Name.** Names must be unique.
2. **Type.** TV, Serial, Movie, Folder, Audio, Party Mode or Combo Block.
3. **Pick content.**
   - For TV and Serial, your library may be large, so you are asked *Show All* or *Filter First*. Filter First narrows the list by genre, year and so on before you tick shows.
   - For Movies, choose all movies, specific movies, or a filtered set.
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
| Studio / Network | is, is not, contains, does not contain |
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

Choose **Edit / Remove Sources** to change a source, or **Remove All Interleave** to strip every interleaved item from the queue. When you remove a source you are asked whether to reset it so it starts from the beginning next time.

**Replacement keeps the pattern.** A finished episode is replaced by the next episode of the same show. A finished interleaved item is replaced by the next item from the same source. The queue length and the pattern stay fixed.

**Queue size with interleave.** The queue size is a minimum and counts every item, episodes and interleaved. The queue always ends right after a complete interleave cycle, so it may be larger than the number you chose. Example: one show, a block of 2 after every 3 episodes, queue size 10 gives exactly 10 items; size 11 gives 15.

## 11. Carousel

Normally a channel waits where you left it. With **Carousel**, the channel keeps moving on its own while you are not watching, like a real channel that is always on.

Enable it in the wizard (or from Edit Channel):

- **Timed:** every X minutes (minimum 1), remove Y items from the front of the queue.
- **Duration:** the front item leaves the queue when its own running time has passed.

Items the carousel moves past have their resume point cleared. Carousel channels cannot be hidden. A channel that is the source of an active schedule cannot use Carousel (and the reverse).

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

A schedule fires only on the device that is playing its target channel; a device playing another channel, or nothing, never fires it. Once the start time has passed, it fires on the first one-minute check while the target channel is playing (once per day), and the block plays when the item that is currently playing finishes. If you start the target channel after the start time, the block fires then. While a block is waiting to play or playing, the channel shows "Now — Scheduled Block". Coming Up Next and the side panel also name upcoming blocks.

## 13. Auto-Create Channels

Settings > Channels > **Auto-Create Channels** builds many channels in one go.

1. Choose what to create channels for: TV Shows only, Movies only, or both.
2. Choose how to group: **Decade**, **Genre**, **Genre + Decade**, or **Studio / Network**.
3. Set the minimum number of items a group needs before it is selected by default (0 shows every group).
4. Optionally create interleaved TV + Movie channels, with a movie woven in every N episodes (1 to 20).
5. Review the preview list, untick anything you do not want, and choose **Create selected**.

Groups that fall below the minimum appear in the list but are not ticked. Names that already exist are skipped. The global defaults (rotation, recycle, queue size) are applied to all new channels; change individual channels afterwards with Edit Channel. The library cache must exist first.

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
- *Default Folder Item Duration:* length used for folder files with no known duration (default 120 s).

**Playback**

- *Default Minimum Queue Size:* default 30.
- *Randomize by Default:* default Off.
- *Reset watched status after each item plays:* default Off.

**Cache**

- *Maximum age before auto-refresh (days):* default 7.
- *Auto-rebuild Kodi library cache on expiry:* default On.
- *Library cache age*, *Songs Cache Age:* read-only information.
- *Refresh Library Cache, Rebuild Songs Cache.*
- *Repair Queue Paths:* updates queued TV episodes from the Kodi library when files were renamed or moved. Queue order and resume points are kept. Update the Kodi library first, and restart any channel that is playing afterwards.

**Network**

- *Shared path:* leave blank to use Kodi's add-on data folder. See section 16.

**Resume**

- *Enable resume on stop:* default On.
- *Background polling interval (seconds):* default 60.
- *Ask before resuming:* default On. When on, you are asked "{item} — resume from {time}?".

**Advanced**

- *Show Next Episode in Channel View, Show Episode Count:* default On.
- *Show hidden channels:* default Off.
- *Number of upcoming programs to show:* default 5.
- *Use Side Panel:* default Off.
- *Log Level:* 0 = Info, 1 = Debug, 2 = Warning.
- *Delete All Addon Data:* removes channels, state, queues and caches from both the local and shared folder.

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

The shared folder then holds channels, play state, queues, the library cache and the missing-durations log. Both devices should use the same Kodi library (for example a shared MySQL database). Carousel channels are safe on two devices; each device checks before it advances a queue so a pop is not applied twice.

**One device per channel.** Only one device can play a given channel at a time. The first device to start it owns it; a second device that tries to start the same channel sees a message naming the other device, and nothing plays. When the channel becomes free (the owner stops, switches channel, closes Kodi, or loses power for about 3 minutes) the second device gets a notification, even if it is playing another channel by then. Different channels can be played on different devices at the same time. A carousel channel that is playing on one device is not advanced by the other devices. A channel that another device is playing also cannot be edited, reset, deleted, have its interleave managed or have a show reset from the other devices; you get the same message and notification.

**Tip.** If a network share is briefly unavailable, one episode may be skipped for that cycle and logged. See section 17.

## 17. Episode Durations and the Missing Durations Log

Smart TV Channels reads each episode's running time from its `.nfo` file (`durationinseconds`). It needs the length to schedule the carousel and Coming Up Next.

**If an episode has no readable duration** it is skipped as if it had played, the next episode of that show takes its place, and the skip is logged. The queue stays the same size.

**Where it is logged**

- A per-channel list. Open it with the channel's *Missing Durations (n)* menu entry, or in the side panel. It lists the show, episode, title and file path, and has a *Clear Missing Durations List* option.
- A shared text file, `missing_durations.txt`, in the data (or shared) folder. View or clear it from **Settings > Tools > View Missing Durations Log**. If nothing has been recorded you see "No missing durations have been recorded."

**Fixing missing durations**

- Make sure each episode has a `.nfo` containing the stream details and duration.
- **Scan Folder for Durations** (Settings > Tools, Windows only) uses `ffprobe` to read each video file and write the missing NFO data. Set the *ffprobe path* if it is not on your system PATH. It reports how many files were scanned, how many NFOs were written, how many already had durations and how many failed, and can be cancelled.

## 18. Backup and Restore

- **Backup Addon Data** (Settings > Backup & Restore) copies your data into one backup file in the backup folder you set. The backup folder can be a network path.
- **Restore Addon Data** lists the backups it finds. Choose one, choose which files to restore, confirm the overwrite, and restart Kodi when asked.

Take a backup before you use Delete All Addon Data, Restore, or change the shared path.

## 19. Troubleshooting

| Problem | What to try |
|---|---|
| "The library cache has not been built yet" | Settings > Cache > Refresh Library Cache |
| A show disappears from the rotation or an episode never plays | Check Missing Durations (n) for that channel; fix the `.nfo` |
| Files were renamed or moved and queued episodes will not play | Update the Kodi library, then Settings > Cache > Repair Queue Paths, and restart the channel |
| Channel logo does not appear | Make sure the overlay is enabled, the channel has an icon, and the version is current. Logo shows when an item starts |
| Coming Up Next does not appear for short items | Raise or lower *Minimum item duration*; items shorter than the limit are skipped |
| "Combo Blocks cannot be played directly" | Use the block as an interleave or schedule source in another channel |
| Cannot hide a channel | It is a carousel channel or a source in use. Disable the carousel or remove it as a source first |
| Cannot delete a source | You are warned that deleting it breaks the link; choose Delete anyway only if intended |
| Two devices disagree about a queue | Make sure both use the same shared path and the same Kodi library, and restart both |
| Anything else | Set Log Level to Debug, reproduce, and read `kodi.log`. Lines from this add-on begin with `[plugin.video.smartchannels]` |

## 20. Glossary

**Carousel** – a channel that advances on its own.
**Combo Block** – a reusable group of slots used inside other channels.
**Interleave** – inserting other content every N items.
**Jitter** – random variation of N in interleave.
**Queue** – the line-up of items a channel will play.
**Recycle** – restarting a finished show from the beginning.
**Silent item** – an item not announced in Coming Up Next.
**Slot** – one source inside a Combo Block.
**Source channel** – a hidden channel that supplies items to another.
**Target channel** – a channel that receives scheduled items.

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
