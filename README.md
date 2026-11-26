# <img src="resources/subsync.svg" width="44" height="44" alt="" align="top"> SubSync Echo

[![Build](https://github.com/resonaut/SubSync-Echo/actions/workflows/build.yml/badge.svg?branch=master)](https://github.com/resonaut/SubSync-Echo/actions/workflows/build.yml)
[![Latest release](https://img.shields.io/github/v/release/resonaut/SubSync-Echo?label=Release)](https://github.com/resonaut/SubSync-Echo/releases/latest)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue)](LICENSE)
![Platforms: Windows and Linux](https://img.shields.io/badge/Platforms-Windows%20%7C%20Linux-0078D6)
![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Runs offline on the CPU](https://img.shields.io/badge/Runs-Offline%20%C2%B7%20CPU%20only-2EA44F)

**Subtitles out of sync with your video? SubSync Echo fixes them for you.** It listens to what is said in the film and moves every subtitle line to the moment it's spoken. It works with anime and other Japanese films, and with subtitles in a different language from the audio. Everything runs on your own computer, with no graphics card, and nothing is uploaded.

<p align="center"><img src="doc/images/before-after.webp" width="560" alt="Tears of Steel with mistimed English subtitles (before) and the same subtitles synced by SubSync Echo (after). Under the film, the audio, with the speech SubSync detects in blue, and bars for when each file shows its lines: the before lines appear over silence, the after lines over the speech."></p>

<p align="center"><sub>Tears of Steel with mistimed English subtitles (before) and synced by SubSync Echo (after). Blue marks the speech SubSync hears; the bars show when each file shows its lines.</sub></p>

<p align="center"><b><a href="https://github.com/resonaut/SubSync-Echo/releases/latest">⬇ Download for Windows or Linux</a></b> · <a href="https://resonaut.github.io/SubSync-Echo/">Website</a> · <a href="doc/guide.md">User guide</a> · <a href="CHANGELOG.md">What's new</a> · <a href="#questions">Questions</a></p>

## Quick start

1. **Download** `subsync-<version>-portable-amd64.exe` from [Releases](https://github.com/resonaut/SubSync-Echo/releases/latest), run it to unpack, and open **`subsync.exe`** in the new `subsync` folder. On Linux, unpack the `.tar.xz` and run `./subsync/subsync` ([details](doc/guide.md#installing)).
2. **Choose your subtitles and your video,** set the language of the subtitles, and click **Start**.
3. When it says **Subtitles synchronized**, click **Save**.

The first time, SubSync downloads its speech model once (about 490 MB). After that it works offline.

<p align="center">
<img src="doc/images/main-window.png" width="420" alt="The SubSync window: Spanish subtitles and the Tears of Steel video chosen, with the Start button.">
&nbsp;
<img src="doc/images/sync-done.png" width="310" alt="The result: Subtitles synchronized, correlation 99.99%, formula 1.0427x+2.684, elapsed time 0:44.">
</p>

<p align="center"><sub>Spanish subtitles on the 12-minute English film Tears of Steel, synced in 44 seconds on a laptop with no graphics card.</sub></p>

## Is this for me?

**Yes, if your subtitles** are early or late all the way through, drift further off as the film goes on, were made for a different release of the film, or are for anime or another film in a language different from the subtitles.

**Not quite, if** you have no subtitles yet (it fixes timing, it doesn't write them), the subtitles are burned into the picture, you use a Mac, or your computer has less than 8 GB of RAM.

Your subtitle text and styling stay exactly as they were; only the timing changes.

## How well it works

Every number comes from a real test: correct subtitles were mistimed on purpose, synced, and compared line by line with the right timing. Under 0.2 seconds off isn't noticeable when watching.

- **Japanese films with English subtitles:** every line within 0.2 s in 7 of 9 films.
- **Free test films in many languages:** every line within 0.2 s in all 6 languages of Tears of Steel, and in 4 of 5 languages of Sita Sings the Blues, songs included.
- **English films with English subtitles:** 99.8–100% of lines within 0.2 s in 7 of 11 films; the rest are off by the same small amount on every line, a different timing style.
- **When it can't confirm the timing, it saves nothing** rather than saving wrong subtitles.
- **Time:** 1.5–2.5 minutes for most films the first time on a laptop with no graphics card, seconds for the same film again.

All results, which languages work how, and how it works inside: [doc/results.md](doc/results.md). [Run the tests yourself](doc/development.md#check-the-results-yourself) with one command.

## Questions

<details>
<summary><b>Is it free?</b></summary>

Yes. It's free and open source under the [GPL-3.0](LICENSE), with no account and no ads.

</details>

<details>
<summary><b>Is my video uploaded anywhere?</b></summary>

No. Speech recognition and translation run on your computer. The only downloads are the models, once ([more about privacy](doc/guide.md#your-privacy)).

</details>

<details>
<summary><b>Do I need a graphics card or a fast computer?</b></summary>

No graphics card: it runs on the processor. The times above were measured on a laptop with an AMD Ryzen 9 5900HX and 8 GB of RAM; a slower processor takes longer.

</details>

<details>
<summary><b>It says "Couldn't synchronize". What can I try?</b></summary>

- Check that the subtitles are for this film and, if you can, for this release of it.
- Check the subtitle language you chose. If you set the video's language by hand, check that too.
- If it still fails, [report it](https://github.com/resonaut/SubSync-Echo/issues/new?template=bug_report.yml) with a log ([how to save one](doc/guide.md#troubleshooting)).

</details>

<details>
<summary><b>Can it sync subtitles on my media server (Jellyfin, Plex, Emby) automatically?</b></summary>

Yes, from 0.21: **watch mode** syncs each new subtitle placed next to its video, and **Bazarr** can run SubSync Echo after each download. It also comes as a Docker image. See [doc/home-server.md](doc/home-server.md). *A build for ARM computers such as the Raspberry Pi is planned, not built yet.*

</details>

<details>
<summary><b>Does it work on a Mac?</b></summary>

No. It runs on Windows and Linux.

</details>

More answers are in the [user guide](doc/guide.md#more-questions).

## Learn more

- [Website](https://resonaut.github.io/SubSync-Echo/): SubSync Echo on one page
- [User guide](doc/guide.md): installing, using the app, what its messages mean, known limits, troubleshooting and the command line
- [Home server](doc/home-server.md): watch mode, running as a service, Bazarr
- [Test results and how it works](doc/results.md)
- [Privacy and security](SECURITY.md): what is downloaded and how it's checked
- [Building and testing](doc/development.md)
- [What's new](CHANGELOG.md)

## License and credits

Free software under the [GNU General Public License v3](LICENSE), based on [SubSync](https://github.com/sc0ty/subsync) by Michał Szymaniak. It uses OpenAI's Whisper, Meta's M2M100, Silero VAD, FFmpeg and more: see [credits](doc/credits.md).
