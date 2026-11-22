"""Language codes in subtitle file names and on the command line, as media
servers (Jellyfin, Plex, Emby) and Bazarr write them.

    python -m unittest discover -s tests -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
try:
    import builtins
    builtins.__dict__.setdefault('_', lambda s: s)
    from subsync.data import languages
    from subsync.synchro.input import getLangFromPath
except ImportError:         # the app's packages (pysubs2...) aren't installed
    languages = None


@unittest.skipIf(languages is None, "SubSync's packages not installed")
class LanguagesTest(unittest.TestCase):
    def test_both_kinds_of_three_letter_codes(self):
        # ISO 639-2 has bibliographic (fre) and terminological (fra) codes
        for t, b in [ ('fra', 'fre'), ('deu', 'ger'), ('zho', 'chi'), ('ces', 'cze'), ('nld', 'dut'),
                      ('ell', 'gre'), ('isl', 'ice'), ('msa', 'may'), ('fas', 'per'), ('ron', 'rum'),
                      ('slk', 'slo'), ('sqi', 'alb') ]:
            self.assertEqual(languages.get(t).code3, b, t)
            self.assertEqual(languages.get(b).code3, b, b)

    def test_language_from_file_name(self):
        for name, lang in [ ('Movie.en.srt', 'eng'), ('Movie.eng.srt', 'eng'), ('subs-fr.srt', 'fre'),
                            ('Movie.fra.srt', 'fre'), ('Movie.en.forced.srt', 'eng'),
                            ('Movie.en.hi.srt', 'eng'), ('Movie.es.sdh.srt', 'spa'),
                            ('Show.S01E01.deu.cc.default.srt', 'ger') ]:
            self.assertEqual(getLangFromPath(name), lang, name)

    def test_no_language_in_file_name(self):
        for name in [ 'Movie.srt', 'Movie.forced.srt', 'Movie.hi.srt', 'Movie.final.srt' ]:
            self.assertIsNone(getLangFromPath(name), name)


if __name__ == '__main__':
    unittest.main()
