# Building, testing and releasing

[Back to the README](../README.md)

## Check the results yourself

The README's accuracy numbers come from tests anyone can run again. One command downloads two free films and their subtitles, deliberately mistimes the subtitles, syncs them with SubSync Echo, and compares every line with the correct timing:

- **Tears of Steel** (Blender Foundation, CC BY 3.0, 12 minutes): its official English, Spanish, German, Italian, Dutch and Russian subtitles, mistimed as if made for 25 fps instead of 23.976 fps, plus 2.5 seconds.
- **Sita Sings the Blues** (Nina Paley, public domain, 82 minutes, about a third of its lines sung): community subtitles in English, Spanish, Chinese, Czech and French, mistimed by a 4.3% speed difference plus 9.4 seconds. Song lines and dialogue are scored separately.

**You need:** Windows 10/11 or Linux (x86-64), Python 3.8 or newer (tested with 3.12; only to run the tests, nothing else to install), about 3 GB of free disk space and an internet connection.

**Run it** from a copy of this repository:

```
git clone https://github.com/resonaut/SubSync-Echo.git
cd SubSync-Echo
python tests/run_all.py e2e
```

It downloads the latest release of SubSync Echo for your system and checks its SHA-256 against the release's `SHA256SUMS` file (from 0.21) or the one GitHub keeps for each release file (if GitHub's limit of 60 requests an hour without signing in is reached, set `GITHUB_TOKEN`; the summary says when a download couldn't be checked), then downloads the films and their subtitles (about 850 MB). SubSync Echo downloads its speech and translation models the first time (about 980 MB). Everything goes into the `e2e-data` folder, and a second run reuses it. On the test laptop (AMD Ryzen 9 5900HX, no graphics card), with the downloads already done, the syncing took 2.2 minutes for Tears of Steel (including translating its subtitles) and 6 minutes for Sita Sings the Blues (with its translations already made); a first run adds the downloads and translating the Sita subtitles.

**What a pass looks like:** each film prints a table with a row per subtitle language, then the run ends with a summary. From a run on the test laptop (2026-11-19):

```
| Subtitles | Method | Time | Lines | Within 0.2 s | Average error | Bias | Worst |
|---|---|---|---|---|---|---|---|
| en | original, then same | 48 s | 76 | 100.0% | 0.184 s | +0.184 s | 0.18 s |
| es | pivot | 6 s | 76 | 100.0% | 0.184 s | +0.184 s | 0.18 s |
...
| Subtitles | Method | Time | Song lines within 0.2 s | Worst song line | Other lines within 0.2 s | Worst other line |
|---|---|---|---|---|---|---|
| en | original | 80 s | 100.0% of 246 | 0.06 s | 100.0% of 438 | 0.06 s |
...
| fr (timing style) | pivot | 35 s | 55.4% of 350 | 0.39 s | 20.5% of 502 | 0.40 s |

== Summary
  Tears of Steel         PASS  1.5 min
  Sita Sings the Blues   PASS  5.7 min

Everything passed.
```

The columns of the tables:

| Column | Meaning |
|---|---|
| Method | how SubSync matched the subtitles: `pivot` translates them to English, `same` writes the speech down in its own language, `original` is the original SubSync method; `original, then same` means Whisper took over |
| Within 0.2 s | share of lines within 0.2 seconds of the correct timing, the difference you can't notice when watching. A language fails below 80%. |
| Average error, Bias, Worst | how far lines are from the correct timing on average, in which direction (positive means later), and the worst line |

**Compare with the README:** the current version gets every line within 0.2 seconds for all 6 Tears of Steel languages, and for English, Spanish, Chinese and Czech on Sita Sings the Blues, songs included. The French Sita file is marked *timing style*: it shows every line about 0.3 seconds later than SubSync's "just before speech" target, so it is shown but doesn't fail the test. The Tears of Steel bias of about +0.18 seconds is expected too: the official files show lines 0.33 seconds before speech, SubSync 0.15 seconds.

**Small differences are normal.** Whisper's output differs slightly between processors, so the average error, the worst line and the time taken vary a little from computer to computer. The share of lines within 0.2 seconds shouldn't change. Both tests run on GitHub's Windows and Linux machines before every release, and a release is published only when both pass.

**What can't be repeated:** the results on commercial films in [results.md](results.md) (9 Japanese and 11 English films) come from our own copies, which can't be shared. [benchmark.md](benchmark.md) describes how they were measured.

**Something failed?** The output above the summary says which language and how far off it was. The logs and synced files are in `e2e-data/work`, and each app's transcripts and translations in its own folder under `e2e-data/temp` (versions never share them, because each expects transcripts made its own way). Please [open an issue](https://github.com/resonaut/SubSync-Echo/issues/new?template=bug_report.yml) with the summary, the table and the log of the failing language.

## More test options

| Command | What it does |
|---|---|
| `python tests/run_all.py` | the unit tests only, in seconds: the timing logic on synthetic films with known right answers. They need numpy (`pip install numpy`, or add `--install`). |
| `python tests/run_all.py all` | the unit tests and both films |
| `python tests/run_all.py e2e --films tos` | only Tears of Steel, the quicker film (372 MB) |
| `python tests/run_all.py e2e --films watch` | watch mode for home servers: a small library made of Tears of Steel, with `watch --once` run after each change (see below) |
| `python tests/run_all.py e2e --films all` | also watch mode and the report-only films below (674 MB more, and PyAV: `pip install av`) |
| `python tests/run_all.py e2e --release 0.20` | test an older release |
| `python tests/run_all.py e2e --app dist/subsync/subsync-cmd.exe` | test the app you built |
| `python tests/run_all.py e2e --app "python run.py"` | test the app run from source |
| `python tests/run_all.py --install` | first install the unit tests' packages at the versions the release builds use |

The start of a unit test run says which optional parts it found: with PyAV, faster-whisper and the built SubSync engine, more unit tests run; without them, those are skipped, not failed. GitHub Actions runs the unit tests on every push and the end-to-end tests before every release, with this same command.

**Watch mode** (`--films watch`) makes a small media library with a copy of Tears of Steel and runs `subsync-cmd --cli watch --once` four times: on the first start with only the video there (nothing is synced); after its Spanish subtitles arrive, mistimed (they are synced in place, every line within 0.2 s, the original kept as `.orig`, and a subtitle without a language in its name left alone); once more (nothing is synced again); and after the video is replaced (synced again from the kept original). It fails the run if any step doesn't do that, and GitHub Actions runs it before every release.

**Report-only films** show their results as REPORT but never fail a run or a release, until they've run on both systems for a while. GitHub Actions runs them before every release too.

| Film | What it tests | Result now |
|---|---|---|
| **Tears of Steel, variable frame rate** (`--films tos-vfr`) | the film converted on your computer so its frame rate changes every few seconds (24, 12 and 16 frames per second), as in phone and screen recordings; English and Spanish subtitles. SubSync times `.srt` subtitles by the audio, so this checks that it reads such a file correctly. | both languages: every line within 0.2 s |
| **[Sintel](https://durian.blender.org)** (Blender Foundation, CC BY 3.0, 15 minutes; `--films sintel`) | very little dialogue (26 lines) and much music; its official Japanese, French, Dutch, Russian, Chinese and Czech subtitles on the English audio, mistimed as 25 fps on the 24 fps film plus 2.5 s | French, Russian and Chinese: every line within 0.2 s; Dutch and Czech: every spoken line (the other line is broken in the Dutch file, a translator credit in the Czech one); Japanese: no file saved. Whisper hears only 14 short lines in the whole film, so SubSync times them by their words (see the CHANGELOG) |

## Building

Windows and Linux packages are built by GitHub Actions; see [.github/workflows/build.yml](../.github/workflows/build.yml) for every step. The exact version of every Python package the builds install is in [.github/constraints.txt](../.github/constraints.txt).

## Releasing

1. In [CHANGELOG.md](../CHANGELOG.md), check the **Highlights** at the top of **Unreleased**: 3–5 points saying in plain words what the version means for people using it, each backed by a test result in the entries below. Then rename **Unreleased** to the new version and date.
2. See the release page before tagging: `python .github/release_notes.py 0.21` prints it.
3. Push a version tag such as `0.21`.

The tag builds the packages and the Docker image ([docker/Dockerfile](../docker/Dockerfile), made from the Linux package), runs the end-to-end tests on both packages and the watch mode test inside the image, and publishes a release and the image (`ghcr.io/resonaut/subsync-echo`, tagged with the version and `latest`) only when they pass. Its page ([.github/release-notes.md](../.github/release-notes.md)) shows the version's highlights and links to its whole section of the changelog for everything else. A tag without a changelog section, or a section without highlights, stops before building.

**WinGet**, once the release is published: `python .github/winget_manifests.py 0.21` writes the three WinGet files for it into `winget/manifests/r/resonaut/SubSyncEcho/0.21/`, with the address and SHA-256 of the release's Windows zip (taken from GitHub, nothing is downloaded). WinGet installs that zip as a portable app with the commands `subsync-echo` and `subsync-echo-cmd` (the original SubSync is already in WinGet with the short name `subsync`, so ours is `subsync-echo`). Check the files with `winget validate --manifest <that folder>`, then copy the folder into a fork of [microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs) and open a pull request there; once Microsoft's checks pass and it's merged, `winget install resonaut.SubSyncEcho` works.

## The icon

The app's icon is drawn in two SVG files: [resources/subsync.svg](../resources/subsync.svg), the full design, used from 64 px, and [resources/subsync-small.svg](../resources/subsync-small.svg), a bolder version for 16–48 px, where fine lines blur. The Windows `.ico`, the macOS `.icns` and the app's PNG images (`subsync/img/icon.png` from the small drawing, `logo.png` from the full one) are made from them.
