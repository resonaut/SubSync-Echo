# Home server: sync subtitles automatically

[Back to the README](../README.md)

If you run a media server such as Jellyfin, Plex or Emby, SubSync Echo can sync subtitles on its own as they arrive. There are two ways:

- **Watch mode** keeps an eye on your media folders and syncs every new subtitle placed next to its video.
- **Bazarr** users can have Bazarr run SubSync Echo right after each subtitle it downloads.

Both use the command line version, `subsync-cmd`, which needs no screen. Today it runs on 64-bit Windows and on Linux on x86-64 (the release's `.tar.xz`). *A build for ARM computers (Raspberry Pi and similar) and a Docker image are planned, not built yet.*

## Watch mode

```
subsync-cmd --cli watch --dir /media/movies --dir /media/tv
```

What it does:

- Every 60 seconds it looks through the folders (and their subfolders) for subtitles named the way media servers expect, next to their video:

  ```
  Movie (2010).mkv
  Movie (2010).en.srt          synced
  Movie (2010).en.forced.srt   synced too
  Movie (2010).en.srt.orig     the original, kept
  ```

- It waits until a subtitle and its video have not changed for 2 minutes, so files still being downloaded are left alone.
- The subtitle language comes from the file name (`.en.`, `.eng.`, `.fra.`, also with `forced`, `sdh`, `cc` or `hi` after it). The audio language is detected. A subtitle without a language in its name is skipped.
- It syncs one subtitle at a time. The result replaces the subtitle, so your media server shows the synced one with no setup, and the original is kept next to it as `.orig`, a name media servers ignore. To undo, rename the `.orig` file back.
- When a subtitle can't be synced (for example a film with very little speech), the file is left as it was and tried again only when it changes, for instance when a new one is downloaded.
- When it can't run at all because the models it needs couldn't be downloaded (no internet yet), it tries again an hour later.
- A subtitle renamed or moved within the library, as Radarr and Sonarr do when they rename a film, isn't synced again, and its `.orig` file follows it.
- When a video is replaced, for example by a better release (which may have another frame rate or cut), its subtitle is synced again from the kept `.orig`, which stays as it is.
- A state file remembers what it did, so nothing is synced twice and SubSync's own results aren't synced again. It's kept as `watch-state.json` in the settings folder (`~/.config/subsync` on Linux), or where `--state` says.
- **On the first start, subtitles already in your library are only noted, not synced.** Only subtitles that arrive or change afterwards are synced. To sync the whole library once, add `--existing` (at 1.5–2.5 minutes per film, a big library takes a long time).

Options:

| Option | Meaning |
|---|---|
| `--dir PATH` | a folder to watch, with its subfolders; repeat it for more folders |
| `--interval SECONDS` | time between looks, default 60 |
| `--settle SECONDS` | how long a subtitle and its video must stay unchanged before syncing, default 120 |
| `--state PATH` | where to keep the state file |
| `--existing` | also sync subtitles that were there on the first start |
| `--once` | look once, sync what is ready and stop (for a scheduled task such as cron) |

Add `--loglevel=INFO --logfile=/path/watch.log` before `watch` to keep a log of what it does. It works on network drives too: it looks for changes itself instead of relying on change notifications, which don't work on most network and FUSE mounts.

The first time a model is needed, SubSync downloads it (about 490 MB for speech, and 490 MB for translation if your subtitles aren't in English); after that it works offline.

### Run it as a service (Linux, systemd)

Save as `/etc/systemd/system/subsync-watch.service`, with your own paths and the user your media server runs as:

```
[Unit]
Description=SubSync Echo: sync subtitles in the media library
After=network-online.target

[Service]
User=media
ExecStart=/opt/subsync/subsync-cmd --cli --loglevel=INFO --logfile=/var/log/subsync/watch.log watch --dir /media/movies --dir /media/tv
Restart=on-failure
Nice=10

[Install]
WantedBy=multi-user.target
```

Then `sudo systemctl enable --now subsync-watch`. The user needs write access to the media folders, since synced subtitles replace the originals. `Nice=10` keeps syncing from slowing down your media server while it plays.

## Bazarr

[Bazarr](https://www.bazarr.media) downloads subtitles for Sonarr and Radarr and can run a command after each one. In Bazarr, open **Settings → Subtitles → Custom Post-Processing**, turn it on and enter:

```
/opt/subsync/subsync-cmd --cli sync --sub "{subtitles}" --ref "{episode}" --ref-stream-by-type audio --out "{subtitles}" --overwrite 2>&1
```

With your own path to `subsync-cmd`. SubSync reads the subtitle language from Bazarr's file name (`Movie.en.srt`, `Movie.en.hi.srt`, `Movie.fr.forced.srt`), detects the audio language and replaces the subtitle with the synced one. When it can't confirm the timing, it leaves the file as it is.

- Bazarr's post-processing thresholds let you sync only subtitles that score below a level you choose; leave them off to sync every download.
- Bazarr has its own sync tool (Settings → Subtitles → Audio Synchronization, using ffsubsync). Turn it off when you use SubSync Echo, so subtitles aren't synced twice.
- Bazarr's command can't start or end with a quote, so keep the path to `subsync-cmd` without spaces, or make a link to it.

Bazarr's settings are described in [its wiki](https://wiki.bazarr.media/Additional-Configuration/Settings/Subtitles/).
