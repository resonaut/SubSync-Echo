# User guide

[Back to the README](../README.md)

- [Installing](#installing)
- [Using it](#using-it)
- [More questions](#more-questions)
- [Your privacy](#your-privacy)
- [Known limits](#known-limits)
- [Troubleshooting](#troubleshooting)
- [For advanced users](#for-advanced-users)

## Installing

**You need:**
- 64-bit Windows 10 or 11, or 64-bit Linux with glibc 2.35 or newer: Ubuntu 22.04 or newer, Debian 12, Fedora 36, Linux Mint 21 and similar.
- 8 GB of RAM. It uses about 1–1.6 GB while syncing.
- About 1 GB of disk space: 410 MB for the app and 490 MB for the speech model, plus 490 MB for the translation model if your subtitles aren't in English.
- Internet once, the first time a model is needed, to download it.

**Windows**
1. Download **`subsync-<version>-portable-amd64.exe`** from **[Releases](https://github.com/resonaut/SubSync-Echo/releases/latest)**.
2. Run it and choose where to unpack, for example `Downloads`. It creates a `subsync` folder.
3. Open that folder and run **`subsync.exe`**.

The same app is also available as a zip (`subsync-<version>-windows-x64.zip`). Unzip it anywhere and run `subsync.exe`.

Windows may show *"Windows protected your PC"* the first time, because SubSync is new and not yet known to Windows. Click **More info**, then **Run anyway**.

**Linux:** download `subsync-<version>-linux-x86_64.tar.xz`, unpack it anywhere and run the app:

```
tar xf subsync-<version>-linux-x86_64.tar.xz
./subsync/subsync
```

Nothing is installed; the `subsync` folder holds everything. To remove SubSync, delete that folder, and the models if you like (see [where they are](#where-does-it-keep-its-files-and-can-i-delete-them)). `./subsync/subsync-cmd` is the command line version.

To check that a download wasn't changed, compare its checksum with the `SHA256SUMS` file on the release page ([how](../SECURITY.md#release-files)).

## Using it

1. **Subtitles:** choose your subtitle file and set its language, for example **English**.
2. **References:** choose the video file. If its language box stays empty, leave it: SubSync detects the spoken language when you click Start (about 5–15 seconds).
3. Click **Start**. The first time only, agree to download the speech model (about 490 MB), and for subtitles that aren't in English, the translation model (about 490 MB).
4. When it says **Subtitles synchronized**, click **Save**.

To sync several files at once, open the menu (**⋮**) and choose **Batch processing**.

**What the messages mean:**

| Message | Meaning |
|---|---|
| **Subtitles synchronized** | Done. The timing was confirmed by the transcribed parts, and by the speech in every stretch of the film with enough dialogue to judge. |
| **Couldn't synchronize** | The timing couldn't be confirmed, so no file is saved rather than saving wrong timing. See [what you can try](../README.md#questions). |
| **Subtitles do not fit this video as a whole, they may be made for a different cut or release** | The subtitles are for another version of the film, and piece-by-piece sync couldn't confirm a result either. Try subtitles made for your release. |
| **Couldn't download the speech recognition model** (or **the translation model**)**, check your internet connection** | The first-time download failed. Connect and click Start again; it resumes where it stopped. |

## More questions

<details>
<summary><b>Will it change the text or style of my subtitles?</b></summary>

No. Only the times change.

</details>

<details>
<summary><b>Which files does it work with?</b></summary>

Subtitles: `.srt`, `.ass`, `.ssa`, `.sub` (MicroDVD), `.txt` (TMP), or text subtitles stored inside a video file. Video: `.mkv`, `.mp4`, `.avi`, `.mov`, `.webm` and most other formats.

</details>

<details>
<summary><b>Which languages does it work with?</b></summary>

Japanese and English audio are tested, with subtitles in English, Japanese, Spanish, German, Italian, Dutch, Russian, Chinese, Czech, Polish, Portuguese, Bulgarian and French. More audio languages use the same method but haven't been tested yet; [the results page](results.md#which-languages-work-how) lists them.

</details>

<details>
<summary><b>Every line is a little early or late, always by the same amount. Why?</b></summary>

Subtitle makers time lines differently: some show a line just before people speak, some just after. SubSync shows each line a moment before speech (0.25 s, or 0.15 s for English-language films). If you prefer another style, change **Settings → Output timing offset**.

</details>

<details>
<summary><b>How is it different from the original SubSync?</b></summary>

SubSync Echo continues the original [SubSync](https://github.com/sc0ty/subsync), which is no longer maintained. It adds the Whisper speech recognition model and translation, so it works where the original couldn't: Japanese films and subtitles in a different language from the audio. It also checks its timing against the speech detected in the whole film before saving. The program and its files keep the name `subsync`.

</details>

<details>
<summary><b>Where does it keep its files, and can I delete them?</b></summary>

- Models: `%USERPROFILE%\.cache\huggingface\hub` on Windows, `~/.cache/huggingface/hub` on Linux. Deleting them means downloading them again next time.
- Transcripts and translations, which make a second sync of the same film quick: `%TEMP%\subsync-transcripts` and `%TEMP%\subsync-translations`. These can be deleted at any time.

</details>

## Your privacy

Speech recognition and translation run on your computer. Your videos and subtitles are never uploaded. The only downloads are the speech and translation models, from `huggingface.co`, always the exact versions SubSync was tested with, and, for languages handled by the original method, the original SubSync's speech models and dictionaries. [SECURITY.md](../SECURITY.md) lists how each download is checked, how to verify a release file with its checksum, and how to report a security problem.

## Known limits

- Lines are timed to start a moment before people speak: 0.25 s for films in other languages and 0.15 s for English-language films, the typical values measured on 26 subtitle files. Some subtitles are timed differently, for example showing each line after the speech starts; the result then differs from them by up to a second. Adjust it in **Settings**, under **Output timing offset**.
- Within a few lines of a cut, some lines may land on the wrong side.
- Of the audio languages Whisper adds, only Japanese has been tested so far (and English, through translation). These use the same method but are untested: Albanian, Arabic, Belarusian, Bulgarian, Catalan, Croatian, Czech, Danish, Estonian, Faroese, Finnish, Galician, Hebrew, Hungarian, Icelandic, Indonesian, Korean, Latin, Latvian, Lithuanian, Malagasy, Malay, Maltese, Norwegian, Persian, Polish, Portuguese, Romanian, Serbian, Slovak, Slovenian, Swedish, Turkish, Ukrainian.
- All other languages work as in the original SubSync, without the Whisper fallback English has.
- English subtitles on an English film take longer when the original method can't sync them: it listens to the whole film first, then Whisper takes over and adds the usual Whisper time. The command line downloads the speech model for this the first time (unless run with `--offline`); in the app window, the fallback is used only when the model is already downloaded, for example after syncing a film in another language.
- Films with very little dialogue are synced from whole lines when too few words match. This needs at least 5 lines Whisper hears clearly, spread over 2 minutes or more, and subtitles of up to 300 lines; otherwise no file is saved. In Sintel, a free 15-minute film with 26 subtitle lines and much music, 5 of 6 languages were synced; Japanese subtitles were refused.
- In videos under 30 minutes, subtitles with a speed difference that isn't a frame-rate conversion aren't synced (no file is saved).
- Automatic updates are turned off. New versions appear on the [Releases](https://github.com/resonaut/SubSync-Echo/releases) page.

## Troubleshooting

- **To save a log of what SubSync does:**
  1. Open the SubSync folder, click the address bar, type `cmd` and press Enter.
  2. Run `subsync.exe --loglevel=INFO --logfile=log.txt`.
  3. Repeat the sync. The log is written to `log.txt`.

  On the command line, add the same two options to `subsync-cmd.exe`.
- **To report a problem,** use the [bug report form](https://github.com/resonaut/SubSync-Echo/issues/new?template=bug_report.yml) and include the log.

## For advanced users

**Command line:**

```
subsync-cmd.exe --cli sync --sub movie.en.srt --sub-lang=eng --ref movie.mkv --ref-stream-by-type=audio --ref-lang=jpn --out movie.synced.srt
```

Run `subsync-cmd.exe --help` for all options.

**Another Whisper model:** SubSync uses Whisper's `small` model. To try another one, set the environment variable `SUBSYNC_WHISPER_MODEL` to its size (for example `medium`) before starting SubSync. Smaller models aren't faster here: `tiny` (75 MB) failed to sync all 4 films it was tested on, and `base` (145 MB) failed 1 of 4 and was slower than `small` on the rest, because SubSync needed more parts of the film before it could confirm the timing.

**Home server** (from 0.21): sync subtitles automatically as they arrive, with watch mode or from Bazarr; see [home-server.md](home-server.md).

**Building from source and running the tests:** see [development.md](development.md). Unit tests run on every build; two end-to-end tests on free films run on both packages before every release, and a release is published only when they pass.
