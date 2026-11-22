"""Watch mode (subsync/watch.py): which subtitles are synced, when, and what
happens to the files. The sync itself is replaced by a stand-in that writes a
marked copy, so these run in seconds without the engine.

    python -m unittest discover -s tests -v
"""

import importlib.util
import json
import os
import shutil
import tempfile
import time
import unittest

_path = os.path.join(os.path.dirname(__file__), '..', 'subsync', 'watch.py')
_spec = importlib.util.spec_from_file_location('watch', _path)
watch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(watch)

LANGS = { 'en': 'eng', 'eng': 'eng', 'es': 'spa', 'ja': 'jpn' }
OLD = time.time() - 3600     # an hour ago: settled


def langFn(word):
    return LANGS.get(word.lower())


class Library(object):
    """A temporary media folder."""

    def __init__(self):
        self.root = tempfile.mkdtemp()
        self.state = os.path.join(self.root, '.state', 'watch.json')
        self.synced = []

    def add(self, name, text='original', age=OLD):
        path = os.path.join(self.root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fp:
            fp.write(text)
        os.utime(path, (age, age))
        return path

    def read(self, name):
        with open(os.path.join(self.root, name), encoding='utf-8') as fp:
            return fp.read()

    def exists(self, name):
        return os.path.exists(os.path.join(self.root, name))

    def sync(self, sub, video, lang, out):
        self.synced.append((os.path.relpath(sub, self.root), lang))
        with open(sub, encoding='utf-8') as src, open(out, 'w', encoding='utf-8') as dst:
            dst.write('synced: ' + src.read())
        return True

    def run(self, syncFn=None, **kw):
        kw.setdefault('settle', 120)
        return watch.watch([self.root], self.state, syncFn or self.sync, langFn,
                           once=True, log=lambda msg: None, **kw)

    def status(self, name):
        with open(self.state, encoding='utf-8') as fp:
            return json.load(fp)['files'][os.path.join(self.root, name)]['status']

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


class NamesTest(unittest.TestCase):
    def test_video_for_subtitle(self):
        videos = ['Movie.mkv', 'Movie 2.mkv', 'Other.mp4']
        self.assertEqual(watch.videoFor('Movie.srt', videos), 'Movie.mkv')
        self.assertEqual(watch.videoFor('Movie.en.forced.srt', videos), 'Movie.mkv')
        self.assertEqual(watch.videoFor('Movie 2.en.srt', videos), 'Movie 2.mkv')
        self.assertIsNone(watch.videoFor('Moviex.en.srt', videos), 'a longer name is another film')

    def test_longest_video_name_wins(self):
        self.assertEqual(watch.videoFor('Show.S01E01.en.srt', ['Show.mkv', 'Show.S01E01.mkv']), 'Show.S01E01.mkv')

    def test_language_from_name(self):
        self.assertEqual(watch.langFromName('Movie.en.srt', 'Movie.mkv', langFn), 'eng')
        self.assertEqual(watch.langFromName('Movie.forced.es.srt', 'Movie.mkv', langFn), 'spa')
        self.assertEqual(watch.langFromName('Movie.en.sdh.srt', 'Movie.mkv', langFn), 'eng')
        self.assertIsNone(watch.langFromName('Movie.srt', 'Movie.mkv', langFn))
        self.assertIsNone(watch.langFromName('Movie.final.srt', 'Movie.mkv', langFn))


class WatchTest(unittest.TestCase):
    def setUp(self):
        self.lib = Library()

    def tearDown(self):
        self.lib.close()

    def test_first_start_notes_existing_subtitles(self):
        self.lib.add('Movie.mkv')
        self.lib.add('Movie.en.srt')
        self.lib.run()
        self.assertEqual(self.lib.synced, [])
        self.assertEqual(self.lib.read('Movie.en.srt'), 'original')
        self.assertEqual(self.lib.status('Movie.en.srt'), 'existing')

    def test_new_subtitle_is_synced_and_original_kept(self):
        self.lib.add('Movie.mkv')
        self.lib.run()                          # first start, nothing there yet
        self.lib.add('Movie.en.srt')
        self.lib.run()
        self.assertEqual(self.lib.synced, [('Movie.en.srt', 'eng')])
        self.assertEqual(self.lib.read('Movie.en.srt'), 'synced: original')
        self.assertEqual(self.lib.read('Movie.en.srt.orig'), 'original')
        self.assertEqual(self.lib.status('Movie.en.srt'), 'synced')

    def test_nothing_is_synced_twice(self):
        self.lib.add('Movie.mkv')
        self.lib.run()
        self.lib.add('Movie.en.srt')
        self.lib.run()
        self.lib.run()
        self.assertEqual(len(self.lib.synced), 1, 'its own result is not synced again')

    def test_existing_option_syncs_the_library(self):
        self.lib.add('Movie.mkv')
        self.lib.add('Movie.en.srt')
        self.lib.add('Shows/Show.S01E01.mkv')
        self.lib.add('Shows/Show.S01E01.es.forced.srt')
        self.lib.run(existing=True)
        self.assertEqual(sorted(s for s, _ in self.lib.synced),
                         ['Movie.en.srt', os.path.join('Shows', 'Show.S01E01.es.forced.srt')])

    def test_files_still_changing_wait(self):
        self.lib.add('Movie.mkv')
        self.lib.run()
        self.lib.add('Movie.en.srt', age=time.time() - 10)     # still arriving
        self.lib.run(settle=120)
        self.assertEqual(self.lib.synced, [])
        self.lib.run(settle=5)
        self.assertEqual(len(self.lib.synced), 1)

    def test_video_still_arriving_waits(self):
        self.lib.run()
        self.lib.add('Movie.en.srt')
        self.lib.run()
        self.assertEqual(self.lib.synced, [], 'no video yet')
        self.lib.add('Movie.mkv', age=time.time() - 10)
        self.lib.run()
        self.assertEqual(self.lib.synced, [], 'video still being downloaded')
        os.utime(os.path.join(self.lib.root, 'Movie.mkv'), (OLD, OLD))
        self.lib.run()
        self.assertEqual(len(self.lib.synced), 1)

    def test_failed_sync_is_retried_only_when_the_file_changes(self):
        tries = []

        def refuse(sub, video, lang, out):
            tries.append(sub)
            return False

        self.lib.add('Movie.mkv')
        self.lib.run()
        self.lib.add('Movie.en.srt')
        self.lib.run(syncFn=refuse)
        self.lib.run(syncFn=refuse)
        self.assertEqual(len(tries), 1)
        self.assertEqual(self.lib.read('Movie.en.srt'), 'original', 'left untouched')
        self.assertFalse(self.lib.exists('Movie.en.srt.orig'))
        self.assertEqual(self.lib.status('Movie.en.srt'), 'failed')
        self.lib.add('Movie.en.srt', text='a new download')
        self.lib.run()
        self.assertEqual(self.lib.read('Movie.en.srt'), 'synced: a new download')

    def test_subtitle_without_language_is_skipped(self):
        self.lib.add('Movie.mkv')
        self.lib.run()
        self.lib.add('Movie.srt')
        self.lib.run()
        self.assertEqual(self.lib.synced, [])
        self.assertEqual(self.lib.status('Movie.srt'), 'skipped')

    def test_replaced_while_syncing_is_left_for_later(self):
        lib = self.lib

        def slowSync(sub, video, lang, out):
            lib.add('Movie.en.srt', text='a newer download')    # arrives meanwhile
            return lib.sync(sub, video, lang, out)

        lib.add('Movie.mkv')
        lib.run()
        lib.add('Movie.en.srt')
        lib.run(syncFn=slowSync)
        self.assertEqual(lib.read('Movie.en.srt'), 'a newer download', 'the new file is kept as it is')
        self.assertFalse(lib.exists('Movie.en.srt.orig'))
        lib.run()
        self.assertEqual(lib.read('Movie.en.srt'), 'synced: a newer download')

    def test_new_download_after_sync_replaces_the_kept_original(self):
        self.lib.add('Movie.mkv')
        self.lib.run()
        self.lib.add('Movie.en.srt', text='first')
        self.lib.run()
        self.lib.add('Movie.en.srt', text='second')
        self.lib.run()
        self.assertEqual(self.lib.read('Movie.en.srt'), 'synced: second')
        self.assertEqual(self.lib.read('Movie.en.srt.orig'), 'second')

    def test_hidden_kept_and_temporary_files_are_ignored(self):
        self.lib.add('Movie.mkv')
        self.lib.run()
        self.lib.add('.hidden/Movie.mkv')
        self.lib.add('.hidden/Movie.en.srt')
        self.lib.add('Movie.en.srt.orig')
        self.lib.add(watch.TMP + 'Movie.en.srt')
        self.lib.run()
        self.assertEqual(self.lib.synced, [])
        self.assertFalse(self.lib.exists(watch.TMP + 'Movie.en.srt'), 'left-over temporary file removed')


if __name__ == '__main__':
    unittest.main()
