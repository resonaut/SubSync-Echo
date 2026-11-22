"""End-to-end test of watch mode (subsync-cmd --cli watch), on a small media
library made of Tears of Steel and its mistimed Spanish subtitles. Each step
runs the real app once (--once), like a scheduled task would:

    1. first start, only the video there: nothing is synced
    2. subtitles arrive: Movie.es.srt is synced in place and its original
       kept as .orig; Movie.srt (no language in its name) is left alone
    3. another look: nothing is synced again
    4. the video is replaced (here: its time changes, as when a new release
       is copied in): the subtitle is synced again from the kept original

The synced subtitles are scored like the Tears of Steel test. The library is
made in --work, with a copy of the film (the film in --data isn't touched).

usage:
    python tests/e2e/watch_mode.py --app dist/subsync/subsync-cmd.exe --data DIR
        [--work DIR] [--download]

Writes a Markdown table to $GITHUB_STEP_SUMMARY when set.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tears_of_steel as tos                                    # noqa: E402

NAME = 'Tears of Steel (2012)'
LANG = 'es'
MIN_WITHIN = 80.0       # percent of lines within 0.2 s, like the Tears of Steel test


def appCommand(app):
    """A path to the app (even with spaces) is used whole, made absolute for
    Windows; otherwise a command such as "python run.py" is split."""
    if os.path.exists(app):
        return [ os.path.abspath(app) ]
    return [ os.path.abspath(x) if os.path.exists(x) else x for x in app.split() ]


def age(path, seconds):
    t = time.time() - seconds
    os.utime(path, (t, t))


def read(path):
    with open(path, encoding='utf-8') as fp:
        return fp.read()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--app', required=True, help='subsync-cmd of the package, or "python run.py"')
    parser.add_argument('--data', required=True, help='folder with Tears of Steel and its subtitles')
    parser.add_argument('--work', default='e2e-watch', help='folder for the library and results')
    parser.add_argument('--download', action='store_true', help='download missing files first')
    args = parser.parse_args()

    if args.download:
        tos.download(args.data)
    work = os.path.abspath(args.work)
    library = os.path.join(work, 'library')
    folder = os.path.join(library, NAME)
    if os.path.isdir(library):
        shutil.rmtree(library)
    os.makedirs(folder)
    state = os.path.join(work, 'watch-state.json')
    log = os.path.join(work, 'watch.log')
    for path in (state, log):
        if os.path.exists(path):
            os.remove(path)

    video = os.path.join(folder, NAME + '.mov')
    sub = os.path.join(folder, '{}.{}.srt'.format(NAME, LANG))
    noLang = os.path.join(folder, NAME + '.srt')
    truth = tos.readSrt(os.path.join(args.data, 'TOS-{}.srt'.format(LANG)))
    mistimed = [ ((s - tos.OFFSET) / tos.SPEED, (e - tos.OFFSET) / tos.SPEED, x) for s, e, x in truth ]

    def logText():
        if not os.path.exists(log):
            return ''
        with open(log, encoding='utf-8', errors='replace') as fp:
            return fp.read()

    def run():
        """Runs watch once; returns how long it took and how many subtitles
        it synced (from what this run wrote to the log)."""
        cmd = appCommand(args.app) + [ '--cli', '--loglevel=INFO', '--logfile=' + log, 'watch',
                '--dir', library, '--once', '--settle', '60', '--state', state ]
        before = logText()
        start = time.time()
        subprocess.run(cmd, stdin=subprocess.DEVNULL)
        took = time.time() - start
        text = logText()
        new = text[len(before):] if text.startswith(before) else text
        return took, new.count('[+] synced ')

    def status(path):
        try:
            with open(state, encoding='utf-8') as fp:
                rec = json.load(fp)['files'].get(os.path.abspath(path))
        except (OSError, ValueError):
            return None
        return rec and rec['status']

    def score(path):
        """Percent of lines within 0.2 s and the worst error, like the Tears
        of Steel test."""
        err, _missing = tos.compare(truth, tos.readSrt(path))
        if not err:
            return 0.0, float('inf')
        return 100 * sum(abs(e) <= 0.2 for e in err) / len(truth), max(map(abs, err))

    def scoreText(res):
        return '{:.1f}% of lines within 0.2 s, worst {:.2f} s'.format(*res)

    rows, failed = [], False

    def check(step, took, ok, detail):
        nonlocal failed
        rows.append((step, took, ok, detail))
        failed = failed or not ok
        print('{}: {} ({})'.format(step, 'PASS' if ok else 'FAIL', detail), flush=True)

    # 1. first start with only the video
    shutil.copyfile(os.path.join(args.data, tos.VIDEO), video)
    age(video, 3600)
    took, count = run()
    check('first start, video only', took, os.path.exists(state) and count == 0,
          'state file written: {}; subtitles synced: {}'.format(os.path.exists(state), count))

    # 2. subtitles arrive (an hour old, so settled)
    tos.writeSrt(sub, mistimed)
    tos.writeSrt(noLang, mistimed)
    original = read(sub)
    for path in (sub, noLang):
        age(path, 3600)
    took, count = run()
    res = score(sub)
    kept = os.path.exists(sub + '.orig') and read(sub + '.orig') == original
    ok = count == 1 and res[0] >= MIN_WITHIN and kept and status(sub) == 'synced' \
        and read(noLang) == original and status(noLang) == 'skipped'
    check('subtitles arrive', took, ok, '{}: {}; original kept: {}; {}: {}'.format(
        os.path.basename(sub), scoreText(res), kept, os.path.basename(noLang), status(noLang)))

    # 3. another look: nothing to do
    before = (os.stat(sub).st_mtime_ns, os.stat(sub + '.orig').st_mtime_ns)
    took, count = run()
    after = (os.stat(sub).st_mtime_ns, os.stat(sub + '.orig').st_mtime_ns)
    check('another look', took, count == 0 and before == after,
          'subtitles synced: {}; files unchanged: {}'.format(count, before == after))

    # 4. the video is replaced: synced again from the kept original
    age(video, 1800)
    took, count = run()
    res = score(sub)
    kept = read(sub + '.orig') == original
    ok = count == 1 and res[0] >= MIN_WITHIN and kept and status(sub) == 'synced'
    check('video replaced', took, ok, 'subtitles synced: {}; {}; original kept: {}'.format(
        count, scoreText(res), kept))

    os.remove(video)        # the copy of the film isn't needed any more
    table = [ '| Step | Time | Result | Detail |', '|---|---|---|---|' ]
    for step, took, ok, detail in rows:
        table.append('| {} | {:.0f} s | {} | {} |'.format(step, took, 'pass' if ok else '**fail**', detail))
    report = '\n'.join([ '### Watch mode, end to end', '',
        'A media library with Tears of Steel and its Spanish subtitles mistimed as 25 fps on the '
        '23.976 fps film plus 2.5 s; `subsync-cmd --cli watch --once` run after each change.', '' ] + table)
    print(report)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as fp:
            fp.write(report + '\n')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
