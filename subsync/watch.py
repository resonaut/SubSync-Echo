"""Watch mode for home servers: watches media folders and syncs subtitles that
arrive next to their videos, the way media servers (Jellyfin, Plex, Emby) name
them:

    Movie (2010).mkv
    Movie (2010).en.srt          synced in place
    Movie (2010).en.srt.orig     the original, kept (media servers ignore it)
    Movie (2010).en.forced.srt   synced too; words like "forced" are skipped
                                 when reading the language

How it works:
  - the folders are scanned every --interval seconds (polling works on network
    and FUSE mounts too, where change notifications don't);
  - a subtitle is synced once it and its video haven't changed for --settle
    seconds, so files still being downloaded are left alone;
  - its language comes from the file name (Movie.en.srt, Movie.eng.srt), or,
    when the name has none (Movie.srt), from its text when that's clear; the
    audio language is detected;
  - one subtitle is synced at a time; the result replaces the subtitle and the
    original is kept as <name>.orig;
  - a state file remembers each subtitle's size and time, so nothing is synced
    twice, and a subtitle that couldn't be synced is tried again only when the
    file changes (for example when a new one is downloaded);
  - when the models it needs can't be downloaded (no internet yet), the
    subtitle is tried again an hour later;
  - a subtitle renamed or moved within the library (as Radarr and Sonarr do)
    isn't synced again, and its kept original follows it;
  - when the video is replaced (a better release, which may have another
    frame rate or cut), the subtitle is synced again from its kept original;
  - on the first start, subtitles already in the library are only noted, not
    synced, unless --existing is given.

The scanning and file handling here use only the standard library; the sync
itself is passed in (see run()), so they can be tested without the engine.
"""

import datetime
import json
import os
import shutil
import time

SUB_EXTS = ('.srt', '.ass', '.ssa')
VIDEO_EXTS = ('.mkv', '.mp4', '.m4v', '.avi', '.mov', '.webm', '.wmv', '.ts', '.m2ts',
              '.mpg', '.mpeg', '.ogv', '.flv', '.vob', '.3gp')
# words media servers allow in subtitle names besides the language
FLAGS = { 'forced', 'sdh', 'cc', 'hi', 'default', 'full', 'signs', 'songs', 'foreign' }
ORIG = '.orig'
TMP = '.subsync-tmp-'
STATE_VERSION = 1
RETRY = 3600        # seconds before a sync that couldn't run is tried again


class Retry(Exception):
    """The sync couldn't run for a passing reason (models not downloaded):
    the subtitle is tried again after RETRY seconds."""


def stem(name):
    return os.path.splitext(name)[0]


def videoFor(subName, videoNames):
    """The video a subtitle belongs to: the one whose name, without its
    extension, starts the subtitle's name and is followed by nothing or a dot
    (Movie.mkv for Movie.srt and Movie.en.forced.srt). The longest such name
    wins, so "Movie 2.mkv" isn't taken for "Movie.mkv"."""
    subStem = stem(subName)
    best = None
    for video in videoNames:
        v = stem(video)
        if subStem == v or subStem.startswith(v + '.'):
            if best is None or len(v) > len(stem(best)):
                best = video
    return best


def langFromName(subName, videoName, langFn):
    """3-letter language code from the words between the video's name and the
    subtitle's extension (Movie.en.forced.srt: "en"), or None."""
    rest = stem(subName)[len(stem(videoName)):].strip('.')
    for word in rest.split('.') if rest else []:
        if word.lower() in FLAGS:
            continue
        code = langFn(word)
        if code:
            return code
    return None


def scan(dirs):
    """Every subtitle in dirs and their subfolders, with its video or None,
    once also when the folders overlap (/media and /media/Movies). Hidden
    files and folders, kept originals and SubSync's temporary files are
    skipped."""
    seen = set()
    for top in dirs:
        for folder, subdirs, files in os.walk(top):
            subdirs[:] = sorted(d for d in subdirs if not d.startswith('.'))
            videos = [ f for f in files if f.lower().endswith(VIDEO_EXTS) and not f.startswith('.') ]
            for name in sorted(files):
                if name.startswith('.') or name.startswith(TMP) or not name.lower().endswith(SUB_EXTS):
                    continue
                path = os.path.join(folder, name)
                key = os.path.normcase(os.path.realpath(path))
                if key in seen:
                    continue
                seen.add(key)
                video = videoFor(name, videos)
                yield path, os.path.join(folder, video) if video else None


def fingerprint(path):
    st = os.stat(path)
    return [ st.st_size, st.st_mtime_ns ]


def isOurs(rec):
    """Whether the subtitle recorded in rec is SubSync's own result, with its
    original kept as .orig (records written before 'ours' was kept: those
    with status synced)."""
    return bool(rec.get('ours')) or rec.get('status') == 'synced'


def videoPrint(video):
    """fingerprint of the video, None when there is none (or it's gone)."""
    try:
        return fingerprint(video) if video else None
    except OSError:
        return None


def videoChanged(rec, video, vfp):
    """Whether the subtitle's video was replaced since rec was written. State
    files written before videos were recorded have no 'vfp': nothing is
    known, the video is recorded now (see plan)."""
    if video is None or 'vfp' not in rec:
        return False
    return rec.get('video') != video or rec['vfp'] != vfp


def settled(path, now, settle):
    """True when the file hasn't changed for settle seconds."""
    return now - os.stat(path).st_mtime >= settle


class State(object):
    """What happened to each subtitle, kept in a JSON file: its size and time
    when last seen, and whether it was synced, noted on the first start, or
    couldn't be synced."""

    def __init__(self, path):
        self.path = path
        self.files = {}
        self.isNew = True
        if path and os.path.exists(path):
            with open(path, encoding='utf-8') as fp:
                data = json.load(fp)
            self.files = data.get('files', {})
            self.isNew = False

    def get(self, sub):
        return self.files.get(os.path.abspath(sub))

    def move(self, old, new):
        self.files[os.path.abspath(new)] = self.files.pop(old)

    def set(self, sub, fp, status, **info):
        """Records what happened to a subtitle. SubSync's own result stays
        marked as such ('ours') while the file is unchanged, also when a
        later sync of it fails or can't run."""
        key = os.path.abspath(sub)
        prev = self.files.get(key)
        if 'ours' not in info and prev and prev['fp'] == fp and isOurs(prev):
            info['ours'] = True
        rec = dict(info, fp=fp, status=status,
                   at=datetime.datetime.now().replace(microsecond=0).isoformat())
        self.files[key] = rec
        return rec

    def save(self):
        if not self.path:
            return
        folder = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(folder, exist_ok=True)
        tmp = self.path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fp:
            json.dump({ 'version': STATE_VERSION, 'files': self.files }, fp, indent=1, sort_keys=True)
        os.replace(tmp, self.path)
        self.isNew = False


def plan(dirs, state, now, settle, existing, langFn, textLangFn=None):
    """Looks at every subtitle once. Returns the ones to sync now, as
    (subtitle, video, language), and records the others that need no sync
    in state. A subtitle is synced when it is new or changed, or when its
    video was replaced. Subtitles still changing, or whose video is missing
    or still changing, are left for a later look. The language comes from the
    name (langFn), else from the text (textLangFn(path) -> code or None)."""
    todo = []
    baseline = state.isNew and not existing
    known = { tuple(rec['fp']): path for path, rec in state.files.items() }
    for sub, video in scan(dirs):
        try:
            fp = fingerprint(sub)
        except OSError:
            continue        # removed meanwhile
        vfp = videoPrint(video)
        rec = state.get(sub)
        if rec and rec['fp'] == fp:
            retry = rec['status'] == 'error' and now >= rec.get('retry', 0)
            if not retry and not videoChanged(rec, video, vfp):
                if 'vfp' not in rec and rec.get('video') == video:
                    rec['vfp'] = vfp    # written before videos were recorded
                continue    # synced, noted or refused already, unchanged since
        elif rec is None and moved(known.get(tuple(fp)), sub, state, video, vfp):
            continue        # renamed or moved, same file
        if baseline:
            state.set(sub, fp, 'existing', video=video, vfp=vfp)
            continue
        if video is None:
            continue        # its video may still arrive
        try:
            # an unchanged subtitle (its video was replaced) needn't settle:
            # it may be SubSync's own result, written a moment ago
            unchanged = rec is not None and rec['fp'] == fp
            if not (unchanged or settled(sub, now, settle)) or not settled(video, now, settle):
                continue
        except OSError:
            continue
        lang = langFromName(os.path.basename(sub), os.path.basename(video), langFn)
        if lang is None and textLangFn:
            lang = textLangFn(sub)
        if lang is None:
            state.set(sub, fp, 'skipped', video=video, vfp=vfp,
                      note='no language in the file name (such as Movie.en.srt), '
                           'and none could be read from its text')
            continue
        todo.append((sub, video, lang))
    return todo


def moved(old, new, state, video=None, vfp=None):
    """When a subtitle seen before under the name old (same size and time)
    is now at new and no longer at old, it was renamed or moved: its record
    follows it, and so does its kept original. When its video was renamed
    with it (same size and time), the record follows that too. Returns True
    then."""
    if old is None or os.path.exists(old):
        return False
    state.move(old, new)
    rec = state.get(new)
    if video and rec.get('vfp') == vfp:
        rec['video'] = video
    if os.path.exists(old + ORIG) and not os.path.exists(new + ORIG):
        try:
            os.replace(old + ORIG, new + ORIG)
        except OSError:
            pass
    return True


def syncOne(sub, video, lang, syncFn, state):
    """Syncs one subtitle with syncFn(sub, video, lang, out) -> bool, which
    writes the result to out. On success the result replaces the subtitle and
    the original is kept as <subtitle>.orig (replacing an older one: it is the
    original of what is there now). A subtitle SubSync synced before whose
    video was replaced is synced again from its kept original, which stays.
    Returns the state record."""
    folder, name = os.path.split(sub)
    tmp = os.path.join(folder, TMP + name)
    # the kept original, under a name with the subtitle's own extension
    # (the app tells the format from it)
    src = os.path.join(folder, TMP + 'orig-' + name)
    fp = fingerprint(sub)
    rec = state.get(sub)
    # SubSync's own result, unchanged since: synced again from the original,
    # also after an earlier attempt failed or couldn't run
    again = bool(rec) and rec['fp'] == fp and isOurs(rec) and os.path.exists(sub + ORIG)
    try:
        open(tmp, 'w').close()      # can it write here? (before minutes of work)
        os.remove(tmp)              # (the app wouldn't overwrite it)
        if again:
            shutil.copyfile(sub + ORIG, src)
        ok = syncFn(src if again else sub, video, lang, tmp)
        if ok and os.path.exists(tmp) and os.path.getsize(tmp) > 0:
            if fingerprint(sub) != fp:
                # replaced while syncing (a new download): try that one later
                return state.get(sub)
            if not again:
                os.replace(sub, sub + ORIG)
            try:
                os.replace(tmp, sub)
            except OSError:
                if not again:
                    os.replace(sub + ORIG, sub)     # put the subtitle back
                raise
            return state.set(sub, fingerprint(sub), 'synced', video=video,
                             vfp=videoPrint(video), lang=lang, ours=True)
        return state.set(sub, fp, 'failed', video=video, vfp=videoPrint(video), lang=lang,
                         note="couldn't be synced; tried again when it or its video changes")
    finally:
        for path in (tmp, src):
            if os.path.exists(path):
                os.remove(path)


def cleanTemp(dirs):
    """Removes temporary files left by an interrupted sync."""
    for top in dirs:
        for folder, subdirs, files in os.walk(top):
            subdirs[:] = [ d for d in subdirs if not d.startswith('.') ]
            for name in files:
                if name.startswith(TMP):
                    try:
                        os.remove(os.path.join(folder, name))
                    except OSError:
                        pass


def watch(dirs, statePath, syncFn, langFn, interval=60, settle=120, existing=False,
          once=False, log=print, sleep=time.sleep, clock=time.time, textLangFn=None):
    """Scans dirs every interval seconds and syncs subtitles that arrive, one
    at a time, until stopped (or after one pass with once)."""
    state = State(statePath)
    if state.isNew and not existing:
        log('[+] first start: subtitles already in the library are noted, not synced '
            '(use --existing to sync them too)')
    cleanTemp(dirs)
    while True:
        todo = plan(dirs, state, clock(), settle, existing, langFn, textLangFn)
        state.save()
        for sub, video, lang in todo:
            log('[*] syncing {}'.format(sub))
            try:
                rec = syncOne(sub, video, lang, syncFn, state)
            except Retry as err:
                log('[-] {}: {}; tried again in {} minutes'.format(sub, err, RETRY // 60))
                try:
                    rec = state.set(sub, fingerprint(sub), 'error', video=video, note=str(err),
                                    retry=clock() + RETRY)
                except OSError:
                    rec = None
            except Exception as err:
                log('[!] {}: {}'.format(sub, err))
                try:
                    state.set(sub, fingerprint(sub), 'failed', video=video, note=str(err))
                except OSError:
                    pass
                rec = None
            state.save()
            if rec and rec['status'] == 'synced':
                log('[+] synced {} (original kept as {})'.format(sub, os.path.basename(sub) + ORIG))
            elif rec and rec['status'] == 'failed':
                log("[-] couldn't sync {}; tried again when it or its video changes".format(sub))
        if once:
            return 0
        sleep(interval)


def run(watchArgs, verbosity=1, offline=False):
    """The 'watch' command of the command line."""
    from subsync import cli
    from subsync import config
    from subsync.synchro import SyncTaskList
    from subsync.synchro.input import getLangFromPath

    dirs = [ os.path.abspath(d) for d in watchArgs['dir'] ]
    for d in dirs:
        if not os.path.isdir(d):
            cli.pr.println(0, '[!] not a folder: {}'.format(d))
            return 1
    statePath = watchArgs.get('state') or os.path.join(config.configdir, 'watch-state.json')
    app = cli.App(verbosity=verbosity, offline=offline)

    def syncFn(sub, video, lang, out):
        tasks = SyncTaskList.deserialize([{
            'sub': { 'path': sub, 'lang': lang },
            'ref': { 'path': video, 'streamByType': 'audio' },
            'out': { 'path': out },
        }])
        res = app.runTasks(tasks)
        if app.interrupted:
            raise KeyboardInterrupt
        if app.assetsMissing:
            raise Retry("the models it needs couldn't be downloaded")
        return res == 0

    def langFn(word):
        return getLangFromPath('x.{}.srt'.format(word))

    import logging
    logger = logging.getLogger(__name__)

    def log(msg):
        # to the console and to the log file (--logfile), where services look
        cli.pr.println(1, msg)
        logger.info(msg)

    def textLangFn(path):
        from subsync.synchro import textlang
        from subsync.data import languages
        res = textlang.detectFile(path)
        if res:
            log('[+] {}: no language in its name, read from its text: {}'.format(
                path, languages.getName(res[0])))
        return res[0] if res else None

    log('[+] watching {}'.format(', '.join(dirs)))
    log('[+] state file: {}'.format(statePath))
    try:
        return watch(dirs, statePath, syncFn, langFn,
                     interval=watchArgs.get('interval') or 60,
                     settle=watchArgs.get('settle') if watchArgs.get('settle') is not None else 120,
                     existing=watchArgs.get('existing', False),
                     once=watchArgs.get('once', False),
                     log=log, textLangFn=textLangFn)
    except KeyboardInterrupt:
        log('[-] stopped')
        return 0
