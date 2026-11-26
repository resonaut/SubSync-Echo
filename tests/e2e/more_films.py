"""More end-to-end tests anyone can rerun, on free films. Like the Tears of
Steel and Sita Sings the Blues tests, each takes a film's own subtitles as the
answer key, mistimes a copy by a known error, syncs it with SubSync and scores
every line. Each language has a limit (GATES below); a release is published
only when every limit holds, on Windows and on Linux.

Lines the answer key can't score are left out: a line shown for no time at
all (a translator's credit at 0:00) and a line with another subtitle's number
and timing inside its text (a broken block in the file). How many lines each
language leaves out is pinned too, and a different number fails the test.

The limits were set from the results of the code they first ran with, so
they catch a result getting worse; they aren't an outside standard.

    sintel      Sintel (Blender Foundation, CC BY 3.0, 15 minutes): very little
                dialogue (26 lines), much music; subtitles in Japanese, French,
                Dutch, Russian, Chinese and Czech on the English audio.
    tos-vfr     Tears of Steel converted to a variable frame rate (the frame
                rate changes every few seconds, as in phone and screen
                recordings), with its English and Spanish subtitles. SubSync
                times .srt subtitles by the audio; this checks that it reads
                such a file correctly. Converting needs PyAV (pip install av).

usage:
    python tests/e2e/more_films.py --film sintel --app dist/subsync/subsync-cmd.exe --data DIR
        [--work DIR] [--download] [--report-only]

Writes a Markdown table to $GITHUB_STEP_SUMMARY when set. Exit code 1 when a
limit isn't met (not with --report-only), 2 when something couldn't be
prepared (a download or the conversion failed).
"""

import argparse
import os
import re
import statistics
import subprocess
import sys
import time
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tears_of_steel import readSrt, writeSrt              # noqa: E402
import tears_of_steel as tos                               # noqa: E402

FILMS = {
    'sintel': {
        'title': 'Sintel',
        'video': 'Sintel.2010.720p.mkv',
        'video_url': 'https://download.blender.org/demo/movies/Sintel.2010.720p.mkv.zip',
        'subs': 'sintel_{}.srt',
        'subs_url': 'https://download.blender.org/durian/subs/sintel_{}.srt',
        # the files in other languages there aren't UTF-8 or are empty
        'langs': { 'jp': 'jpn', 'fr': 'fre', 'nl': 'dut', 'ru': 'rus', 'zh': 'chi', 'cz': 'cze' },
        # subtitles made for 25 fps shown on the 24 fps film, 2.5 s late
        'speed': 25 / 24, 'offset': 2.5,
        'about': 'Official subtitles mistimed as 25 fps on the 24 fps film plus 2.5 s.',
        # Japanese is refused for now (its translation pairs too few lines): a
        # refusal passes, a saved file must be right
        'gates': { 'jp': ('min-or-none', 95), 'fr': ('min', 95), 'nl': ('all',),
                   'ru': ('min', 95), 'zh': ('min', 95), 'cz': ('all',) },
        # lines left out as unscorable, pinned so a changed file or rule can't
        # raise a score unnoticed: the Dutch broken block, the Czech credit
        'unscored': { 'nl': 1, 'cz': 1 },
    },
    'tos-vfr': {
        'title': 'Tears of Steel, variable frame rate',
        'video': 'tears_of_steel_vfr.mkv',
        'source': ('tears-of-steel', tos.VIDEO, tos.VIDEO_URL),
        'subs': 'TOS-{}.srt',
        'subs_url': tos.SUBS_URL,
        'langs': { 'en': 'eng', 'es': 'spa' },
        'speed': tos.SPEED, 'offset': tos.OFFSET,
        'about': 'Tears of Steel converted to a variable frame rate; official subtitles '
                 'mistimed as 25 fps on the 23.976 fps film plus 2.5 s.',
        'gates': { 'en': ('min', 95), 'es': ('min', 95) },
    },
}


def unscorable(start, end, text):
    """A line the answer key can't score: shown for no time at all, or with
    another subtitle's timing inside its text (a broken block)."""
    return end <= start or re.search(r'\d+:\d\d:\d\d[,.]\d+ --> ', text) is not None


def pairLines(truth, synced):
    """(index in truth, start time error) for each answer-key line found in
    the result. SubSync changes only timing, so lines are paired by text, in
    order (as tears_of_steel.compare does)."""
    import difflib
    key = lambda text: ' '.join(text.split())
    matcher = difflib.SequenceMatcher(None, [ key(t) for _, _, t in truth ],
            [ key(t) for _, _, t in synced ], autojunk=False)
    pairs = []
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            pairs.append((block.a + k, synced[block.b + k][0] - truth[block.a + k][0]))
    return pairs


def judge(gate, res):
    """(passed, rule) for one language; res is None when no file was saved."""
    kind = gate[0]
    if kind == 'all':
        rule = 'every scored line within 0.2 s'
        return res is not None and res['within'] >= 100, rule
    rule = 'at least {}% within 0.2 s'.format(gate[1])
    if kind == 'min-or-none':
        rule = 'no file, or ' + rule
        return res is None or res['within'] >= gate[1], rule
    return res is not None and res['within'] >= gate[1], rule


def fetch(url, path):
    """Downloads url to path; a dropped connection can end a download early
    without an error, so the size is checked."""
    print('downloading', url, flush=True)
    req = urllib.request.Request(url, headers={ 'User-Agent': 'subsync-e2e-test' })
    with urllib.request.urlopen(req) as src, open(path + '.part', 'wb') as dst:
        total, done = int(src.headers.get('Content-Length') or 0), 0
        while True:
            chunk = src.read(1 << 20)
            if not chunk:
                break
            dst.write(chunk)
            done += len(chunk)
    if total and done != total:
        os.remove(path + '.part')
        raise IOError('download of {} cut off: {} of {} bytes, please run again'.format(url, done, total))
    os.replace(path + '.part', path)


def makeVfr(src, dst):
    """Writes a copy of src whose frame rate changes every few seconds: all
    frames for 7 s, every second frame for 5 s, two of three for 4 s, so the
    film runs at 24, 12 and 16 frames per second in turn, with the original
    frame times. The audio is copied unchanged."""
    try:
        import av
    except ImportError:
        raise RuntimeError('making the variable frame rate copy needs PyAV: pip install av')
    from fractions import Fraction
    pattern = [ (7, 1), (5, 2), (4, 3) ]        # (seconds, keep 1 of n; 3 keeps 2 of 3)
    cycle = sum(s for s, _ in pattern)

    def keep(t, n):
        pos = t % cycle
        for seconds, every in pattern:
            if pos < seconds:
                if every == 1:
                    return True
                if every == 2:
                    return n % 2 == 0
                return n % 3 != 2
            pos -= seconds
        return True

    print('making a variable frame rate copy of', os.path.basename(src), flush=True)
    inp = av.open(src)
    vin, ain = inp.streams.video[0], inp.streams.audio[0]
    out = av.open(dst + '.part', 'w', format='matroska')
    vout = out.add_stream('mpeg4', rate=24)
    vout.width, vout.height, vout.pix_fmt = 640, 272, 'yuv420p'
    vout.bit_rate = 800000
    vout.time_base = vout.codec_context.time_base = Fraction(1, 1000)
    aout = out.add_stream_from_template(ain)
    n = 0
    for packet in inp.demux(vin, ain):
        if packet.stream is ain:
            if packet.dts is not None:
                packet.stream = aout
                out.mux(packet)
            continue
        for frame in packet.decode():
            n += 1
            if frame.time is None or not keep(frame.time, n):
                continue
            small = frame.reformat(width=640, height=272, format='yuv420p')
            small.pts, small.time_base = int(round(frame.time * 1000)), Fraction(1, 1000)
            for p in vout.encode(small):
                out.mux(p)
    for p in vout.encode(None):
        out.mux(p)
    out.close()
    inp.close()
    os.replace(dst + '.part', dst)


def prepare(film, data, download):
    os.makedirs(data, exist_ok=True)
    video = os.path.join(data, film['video'])
    if not os.path.exists(video):
        if 'source' in film:
            folder, name, url = film['source']
            src = os.path.join(os.path.dirname(data), folder, name)
            if not os.path.exists(src):
                if not download:
                    raise RuntimeError('missing {} (use --download)'.format(src))
                os.makedirs(os.path.dirname(src), exist_ok=True)
                fetch(url, src)
            makeVfr(src, video)
        else:
            if not download:
                raise RuntimeError('missing {} (use --download)'.format(video))
            url = film['video_url']
            if url.endswith('.zip'):
                archive = video + '.zip'
                if not os.path.exists(archive):
                    fetch(url, archive)
                with zipfile.ZipFile(archive) as z:
                    member = next(m for m in z.namelist() if m.endswith(film['video']))
                    with z.open(member) as src, open(video + '.part', 'wb') as dst:
                        while True:
                            chunk = src.read(1 << 20)
                            if not chunk:
                                break
                            dst.write(chunk)
                os.replace(video + '.part', video)
                os.remove(archive)
            else:
                fetch(url, video)
    for lang in film['langs']:
        path = os.path.join(data, film['subs'].format(lang))
        if not os.path.exists(path):
            if not download:
                raise RuntimeError('missing {} (use --download)'.format(path))
            fetch(film['subs_url'].format(lang), path)
    return video


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--film', required=True, choices=sorted(FILMS))
    parser.add_argument('--app', required=True, help='subsync-cmd of the package, or "python run.py"')
    parser.add_argument('--data', required=True, help='folder with the film and its subtitles')
    parser.add_argument('--work', default='e2e-more', help='folder for mistimed copies and results')
    parser.add_argument('--download', action='store_true', help='download (or make) missing files first')
    parser.add_argument('--report-only', action='store_true', help="show the results, don't judge them")
    args = parser.parse_args()
    film = FILMS[args.film]

    try:
        video = os.path.abspath(prepare(film, args.data, args.download))
    except Exception as err:
        print('error: {}'.format(err), flush=True)
        return 2

    os.makedirs(args.work, exist_ok=True)
    if os.path.exists(args.app):
        app = [ os.path.abspath(args.app) ]
    else:
        app = [ os.path.abspath(x) if os.path.isfile(x) else x for x in args.app.split() ]
    rows = []
    for lang, code in film['langs'].items():
        truth = readSrt(os.path.join(args.data, film['subs'].format(lang)))
        mistimed = [ ((s - film['offset']) / film['speed'], (e - film['offset']) / film['speed'], x)
                for s, e, x in truth ]
        sub = os.path.abspath(os.path.join(args.work, '{}-{}.mistimed.srt'.format(args.film, lang)))
        out = os.path.abspath(os.path.join(args.work, '{}-{}.synced.srt'.format(args.film, lang)))
        log = os.path.abspath(os.path.join(args.work, '{}-{}.log'.format(args.film, lang)))
        writeSrt(sub, mistimed)
        for path in (out, log):
            if os.path.exists(path):
                os.remove(path)
        cmd = app + [ '--cli', '--loglevel=INFO', '--logfile=' + log, 'sync',
                '--sub', sub, '--sub-lang=' + code, '--ref', video,
                '--ref-stream-by-type=audio', '--out', out, '--overwrite' ]
        start = time.time()
        subprocess.run(cmd, stdin=subprocess.DEVNULL)
        took = time.time() - start

        logText = open(log, encoding='utf-8', errors='replace').read() if os.path.exists(log) else ''
        route = ', then '.join(re.findall(r'matching route: (\w+)', logText)) or 'original'
        scored = [ i for i, (s, e, x) in enumerate(truth) if not unscorable(s, e, x) ]
        res = None
        if os.path.exists(out):
            errs = dict(pairLines(truth, readSrt(out)))
            err = [ errs[i] for i in scored if i in errs ] or [ float('inf') ]
            res = { 'missing': sum(i not in errs for i in scored),
                    'within': 100 * sum(abs(errs[i]) <= 0.2 for i in scored if i in errs) / len(scored),
                    'avg': statistics.mean(map(abs, err)), 'bias': statistics.mean(err),
                    'worst': max(map(abs, err)) }
        passed, rule = judge(film['gates'][lang], res)
        skipped, expected = len(truth) - len(scored), film.get('unscored', {}).get(lang, 0)
        if skipped != expected:
            passed = False
            rule += '; {} line(s) not scored, expected {}'.format(skipped, expected)
        rows.append((lang, route, took, len(truth), skipped, res, passed, rule))

    table = [ '| Subtitles | Method | Time | Lines | Within 0.2 s | Average error | Bias | Worst | Limit | Result |',
              '|---|---|---|---|---|---|---|---|---|---|' ]
    for lang, route, took, n, skipped, res, passed, rule in rows:
        lines = '{}{}'.format(n, ', {} not scored'.format(skipped) if skipped else '')
        verdict = 'shown' if args.report_only else ('pass' if passed else '**FAIL**')
        if res is None and passed and not args.report_only:
            verdict = 'pass (refused)'       # allowed for this language, but shown as such
        if res is None:
            table.append('| {} | {} | {:.0f} s | {} | no file saved | | | | {} | {} |'.format(
                lang, route, took, lines, rule, verdict))
        else:
            if res['missing']:
                lines += ', {} missing'.format(res['missing'])
            table.append('| {} | {} | {:.0f} s | {} | {:.1f}% | {:.3f} s | {:+.3f} s | {:.2f} s | {} | {} |'.format(
                lang, route, took, lines, res['within'], res['avg'], res['bias'], res['worst'], rule, verdict))
    failed = not args.report_only and not all(passed for *_, passed, _ in rows)
    report = '\n'.join([ '### {}, end to end{}'.format(film['title'], ' (report only)' if args.report_only else ''), '',
        film['about'] + ' Synced by SubSync and scored against the file\'s own timing.', '' ] + table)
    print(report)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as fp:
            fp.write(report + '\n')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
