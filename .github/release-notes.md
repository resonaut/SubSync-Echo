<!-- Release page template. The release workflow (.github/release_notes.py)
     replaces {{VERSION}} with the version, {{HIGHLIGHTS}} with the Highlights
     of that version's section of CHANGELOG.md, and {{CHANGES_URL}} with a
     link to the whole section. Keep it short and friendly: the details live
     in the CHANGELOG, the guide in the README. -->
**SubSync Echo fixes subtitles that are out of sync with your video.** It listens to what is said and moves every line to the moment it's spoken: anime and other Japanese films, English films, and subtitles in a different language from the audio. Everything runs on your own computer, and nothing is uploaded.

## What's new in {{VERSION}}

{{HIGHLIGHTS}}

**[Everything that changed in {{VERSION}}]({{CHANGES_URL}})**, with the test results behind each point.

## Get started

1. **Windows:** download **`subsync-{{VERSION}}-portable-amd64.exe`** below, run it to unpack, then open **`subsync.exe`** in the new `subsync` folder. **Linux:** download **`subsync-{{VERSION}}-linux-x86_64.tar.xz`**, unpack it and run **`./subsync/subsync`**.
2. Choose your subtitles and the video, then click **Start**.
3. When it says **Subtitles synchronized**, click **Save**.

The first time, SubSync downloads its speech model once (about 490 MB), and for subtitles that aren't in English, its translation model (about 490 MB). After that it works offline. It needs 64-bit Windows 10 or 11, or 64-bit Linux (Ubuntu 22.04 or newer and similar), and 8 GB of RAM.

If Windows shows *"Windows protected your PC"*, click **More info**, then **Run anyway**: SubSync is new and not yet known to Windows. To check a download, compare its checksum with `SHA256SUMS` below ([how](https://github.com/resonaut/SubSync-Echo/blob/{{VERSION}}/SECURITY.md#release-files)).

**[User guide](https://github.com/resonaut/SubSync-Echo/blob/{{VERSION}}/doc/guide.md)** · **[Questions and answers](https://github.com/resonaut/SubSync-Echo#questions)** · **[Report a problem](https://github.com/resonaut/SubSync-Echo/issues/new?template=bug_report.yml)**
