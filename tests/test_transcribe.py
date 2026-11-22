"""Unit tests for the alignment logic in subsync/synchro/transcribe.py.

They use synthetic films (see synthetic.py) with a known right answer, so they
run in seconds without videos, Whisper or the compiled engine:

    python -m unittest discover -s tests -v
"""

import logging
import random
import os
import tempfile
import unittest

from synthetic import transcribe as t, makeSpeech, makeSubtitles, mistime, cut, times, reword

logging.disable(logging.INFO)

# unusual speed and offset, not a standard frame rate ratio
SPEED, OFFSET = 1.0012, 7.3


def offsetErrors(fileLines, videoLines, a, offsets):
    """Error (seconds) of every synchronized line start."""
    return [ abs(a * f[0] + o - v[0]) for f, v, o in zip(fileLines, videoLines, offsets) ]


class TimeFormatTest(unittest.TestCase):
    def test_round_trip(self):
        for seconds in (0.0, 1.5, 59.999, 61.0, 3599.25, 7322.004):
            self.assertAlmostEqual(t.parseTime(t.formatTime(seconds)), seconds, places=3)

    def test_srt_round_trip(self):
        lines = [ (1.0, 2.5, 'first line'), (3600.125, 3601.0, 'second, with comma') ]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'x.srt')
            t.writeSrt(path, lines)
            back = t.readSrt(path)
        self.assertEqual([ x[2] for x in back ], [ x[2] for x in lines ])
        for (s1, e1, _), (s2, e2, _) in zip(back, lines):
            self.assertAlmostEqual(s1, s2, places=3)
            self.assertAlmostEqual(e1, e2, places=3)


class TimeLinesTest(unittest.TestCase):
    """Transcript lines are retimed the way subtitles are shown."""

    lines = [ (10.0, 12.0, 'short'), (12.5, 13.0, 'x' * 100), (40.0, 41.0, 'a') ]

    def test_rules(self):
        res = t.timeLines(self.lines)
        for no, ((start, end, text), (begin, finish, _)) in enumerate(zip(self.lines, res)):
            self.assertAlmostEqual(begin, start + t.lineLeadIn)
            self.assertGreaterEqual(finish, end, 'never shorter than the speech')
            self.assertLessEqual(finish - begin, t.lineMaxDuration + 1e-9)
            if no + 1 < len(res):
                self.assertLessEqual(finish, res[no + 1][0] - t.lineMinGap + 1e-9,
                        'gap before the next line')

    def test_reading_time(self):
        begin, finish, _ = t.timeLines(self.lines)[1]
        self.assertGreaterEqual(finish - begin, min(100 / t.lineReadingSpeed, t.lineMaxDuration) - 1e-9)


class SpreadOrderTest(unittest.TestCase):
    def test_order(self):
        self.assertEqual(t.spreadOrder(0), [])
        self.assertEqual(t.spreadOrder(1), [ 0 ])
        for count in (2, 5, 24):
            order = t.spreadOrder(count)
            self.assertEqual(sorted(order), list(range(count)))
            self.assertEqual(order[:2], [ 0, count - 1 ])
        self.assertIn(t.spreadOrder(24)[2], (11, 12))


class FilmTest(unittest.TestCase):
    """Base: one synthetic film, its correct subtitles and a mistimed copy."""

    @classmethod
    def setUpClass(cls):
        cls.speech = makeSpeech(3600.0)
        cls.video = makeSubtitles(cls.speech)              # right in the video
        cls.file = mistime(cls.video, SPEED, OFFSET)       # as the file has them


class JapaneseTextTest(unittest.TestCase):
    """Japanese is written without spaces: whole phrases must not be treated
    as words, or differently worded transcript lines never match."""

    subtitle = '今夜はどこへ行くの、サツキ？'
    transcript = 'サツキ、今夜どこ行くの？'

    def test_phrases_alone_never_match(self):
        self.assertEqual(t._words(self.subtitle, 5) & t._words(self.transcript, 5), set())

    def test_letter_groups_match(self):
        shared = t._words(self.subtitle, 5, ngrams=3) & t._words(self.transcript, 5, ngrams=3)
        self.assertIn('サツキ', shared)
        self.assertIn('行くの', shared)

    def test_english_unchanged(self):
        self.assertEqual(t._words('Where are you going tonight?', 5), { 'where', 'going', 'tonight' })


class RefineFormulaTest(FilmTest):
    def test_finds_speed_and_offset(self):
        # lines exactly over speech, so the best overlap is the right answer
        video = makeSubtitles(self.speech, lead=0.0, tail=0.0)
        subs = times(mistime(video, SPEED, OFFSET))
        # matched words give an answer about a second off
        res = t.refineFormula(subs, self.speech, SPEED + 2e-4, OFFSET + 1.2)
        self.assertIsNotNone(res)
        a, b = res
        for f, v in ((subs[0], video[0]), (subs[-1], video[-1])):
            self.assertAlmostEqual(a * f[0] + b, v[0], delta=0.03)

    def test_short_video_speed_found_by_wider_search(self):
        # a 10-minute video with subtitles made for 25 fps on a 23.976 fps
        # video: matched words got the speed 0.5% wrong, right only in the
        # middle; the usual narrow search can't reach the answer
        speed = 25 / (24000 / 1001)
        speech = makeSpeech(600.0, seed=3)
        video = makeSubtitles(speech, lead=0.0, tail=0.0)
        subs = times(mistime(video, speed, OFFSET))
        a0 = speed + 0.005
        b0 = speed * 300 + OFFSET - a0 * 300
        self.assertIsNone(t.refineFormula(subs, speech, a0, b0, t.refineScaleRange))
        res = t.refineFormula(subs, speech, a0, b0)
        self.assertIsNotNone(res)
        a, b = res
        self.assertAlmostEqual(a, speed, places=6)
        for f, v in ((subs[0], video[0]), (subs[-1], video[-1])):
            self.assertAlmostEqual(a * f[0] + b, v[0], delta=0.02)

    def test_long_film_speed_not_snapped(self):
        # a film's own speech pins the speed precisely: a speed close to a
        # frame rate conversion (0.03% off it) stays as it is
        speed = 24 / 25 * 1.0003
        video = makeSubtitles(self.speech, lead=0.0, tail=0.0)
        subs = times(mistime(video, speed, OFFSET))
        a, b = t.refineFormula(subs, self.speech, speed + 2e-4, OFFSET + 1.2)
        self.assertAlmostEqual(a, speed, delta=2e-5)

    def test_wider_search_refuses_other_speeds(self):
        # in a short video only a frame rate conversion is believed (speech
        # overlap is too flat to tell a speed close to the words' one)
        speed = 1.0083
        speech = makeSpeech(600.0, seed=3)
        video = makeSubtitles(speech, lead=0.0, tail=0.0)
        subs = times(mistime(video, speed, OFFSET))
        a0 = speed + 0.005
        b0 = speed * 300 + OFFSET - a0 * 300
        self.assertIsNone(t.refineFormula(subs, speech, a0, b0))

    def test_short_video_split_to_more_chunks(self):
        self.assertEqual(t.chunkCount(7200.0), 24)
        self.assertEqual(t.chunkCount(734.0), 4)
        self.assertEqual(t.chunkCount(400.0), 3)
        self.assertEqual(t.chunkCount(60.0), 1)

    def test_refuses_far_answer(self):
        # 10 s off: outside the searched range, speech must not confirm it
        res = t.refineFormula(times(self.file), self.speech, SPEED, OFFSET + 10.0)
        self.assertIsNone(res)

    def test_refuses_unrelated_subtitles(self):
        other = times(makeSubtitles(makeSpeech(3600.0, seed=99)))
        self.assertIsNone(t.refineFormula(other, self.speech, 1.0, 0.0))


class ChecksTest(FilmTest):
    """Per-part word check and region check: right formula passes, subtitles
    of a different cut are refused."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # subtitles made for a version with a 45 s scene added in the middle
        cls.cutFile = mistime(cut(cls.video, 1800.0, 45.0), SPEED, OFFSET)
        # transcribed parts: 12 lines from 5 places in the video, slightly off
        cls.chunks = []
        for pos in (0.05, 0.3, 0.5, 0.7, 0.95):
            first = int(pos * (len(cls.video) - 12))
            cls.chunks.append([ (s + 0.3, e + 0.3, text)
                for s, e, text in cls.video[first:first + 12] ])

    def test_chunks_agree(self):
        self.assertTrue(t.checkChunks(self.file, self.chunks, SPEED, OFFSET))

    def test_pieces_of_one_line_count_once(self):
        # Whisper split one subtitle line in three; the rest of each part
        # matches nothing. Three matches, but one line of evidence: not
        # enough for a part to agree
        words = [ 'harbor', 'castle', 'winter', 'dragon', 'forest', 'silver', 'garden', 'thunder',
                  'mirror', 'candle', 'meadow' ]
        subs = [ (100.0, 104.0, 'Remember the lighthouse tonight') ] + \
               [ (200.0 + 60 * n, 202.0 + 60 * n, 'The ' + w) for n, w in enumerate(words) ]
        pieces = [ (100.2, 101.0, 'Remember'), (101.5, 102.5, 'the lighthouse'), (102.8, 103.6, 'tonight') ]
        filler = [ (110.0 + 5 * n, 112.0 + 5 * n, 'zzzzzz qqqqqq') for n in range(8) ]
        part = sorted(pieces + filler)
        self.assertFalse(t.checkChunks(subs, [ part, part ], 1.0, 0.0))
        # three different lines do agree
        three = sorted([ (100.2, 101.0, 'Remember'), (200.5, 201.0, 'harbor'),
                         (260.5, 261.0, 'castle') ] + filler)
        self.assertTrue(t.checkChunks(subs, [ three, three ], 1.0, 0.0))

    def test_chunks_refuse_cut(self):
        self.assertFalse(t.checkChunks(self.cutFile, self.chunks, SPEED, OFFSET))

    def test_split_sentences_agree(self):
        # Whisper split long subtitle lines in pieces: the later pieces start
        # 2.5 s or more after their line, while it is still shown
        chunks = []
        for pos in (0.05, 0.3, 0.5, 0.7, 0.95):
            long = [ l for l in self.video[int(pos * (len(self.video) - 40)):] if l[1] - l[0] >= 3.2 ]
            chunks.append([ (e - 0.5, e + 1.0, text) for s, e, text in long[:12] ])
        self.assertTrue(t.checkChunks(self.file, chunks, SPEED, OFFSET))
        self.assertFalse(t.checkChunks(self.cutFile, chunks, SPEED, OFFSET))

    def test_chunks_need_two_opinions(self):
        self.assertFalse(t.checkChunks(self.file, self.chunks[:1], SPEED, OFFSET))

    def test_short_video_small_chunks_judged_together(self):
        # parts with fewer than checkMinLines lines (e.g. after stretched
        # lines were left out) still count together in a short video
        video = [ l for l in self.video if l[0] < 1200.0 ]
        chunks = []
        for pos in (0.1, 0.35, 0.6, 0.85):
            first = int(pos * (len(video) - 6))
            chunks.append([ (s + 0.3, e + 0.3, text if no < 2 else 'mumble')
                for no, (s, e, text) in enumerate(video[first:first + 6]) ])
        self.assertTrue(t.checkChunks(mistime(video, SPEED, OFFSET), chunks, SPEED, OFFSET))
        self.assertFalse(t.checkChunks(self.file, chunks, SPEED, OFFSET))

    def test_stretched_lines_left_out(self):
        # Whisper line spanning a song: 75 s for text read in 4 s, timed
        # 70 s before its words; normal and slowly sung lines stay
        text = "I've committed a terrible sin in a previous life"
        self.assertTrue(t.isStretched(3609.1, 3684.1, text))
        self.assertFalse(t.isStretched(3380.4, 3386.4, text))
        self.assertFalse(t.isStretched(100.0, 112.0, 'Moanin low, my sweet man'))
        path = os.path.join(tempfile.mkdtemp(prefix='subsync-test-'), 'chunk-000.srt')
        try:
            t.writeSrt(path, [ (3380.7, 3386.4, 'I think basically as a king'),
                               (3609.4, 3684.1, text) ])
            self.assertEqual([ l[2] for l in t.readChunk(path) ], [ 'I think basically as a king' ])
        finally:
            os.remove(path)
            os.rmdir(os.path.dirname(path))

    def test_short_video_chunks_judged_together(self):
        # 4 parts of a short video with only 2 recognizable lines each: too
        # few on their own, enough together (in a long film, never pooled)
        video = [ l for l in self.video if l[0] < 1200.0 ]
        chunks = []
        for pos in (0.1, 0.35, 0.6, 0.85):
            first = int(pos * (len(video) - 12))
            chunks.append([ (s + 0.3, e + 0.3, text if no < 2 else 'mumble')
                for no, (s, e, text) in enumerate(video[first:first + 12]) ])
        short = mistime(video, SPEED, OFFSET)
        self.assertTrue(t.checkChunks(short, chunks, SPEED, OFFSET))
        self.assertFalse(t.checkChunks(self.file, chunks, SPEED, OFFSET))

    def japanese(self):
        """Japanese subtitles, a different-cut copy, and transcribed parts
        worded slightly differently."""
        rnd = random.Random(5)
        video = makeSubtitles(self.speech, japanese=True)
        chunks = []
        for pos in (0.05, 0.3, 0.5, 0.7, 0.95):
            first = int(pos * (len(video) - 12))
            chunks.append([ (s + 0.3, e + 0.3, reword(text, rnd))
                for s, e, text in video[first:first + 12] ])
        return (mistime(video, SPEED, OFFSET),
                mistime(cut(video, 1800.0, 45.0), SPEED, OFFSET), chunks)

    def test_japanese_chunks_agree(self):
        file, _, chunks = self.japanese()
        self.assertTrue(t.checkChunks(file, chunks, SPEED, OFFSET, ngrams=3))

    def test_japanese_chunks_refuse_cut(self):
        _, cutFile, chunks = self.japanese()
        self.assertFalse(t.checkChunks(cutFile, chunks, SPEED, OFFSET, ngrams=3))

    def test_japanese_needs_letter_groups(self):
        # without letter groups nothing matches, so nothing is ever confirmed
        file, _, chunks = self.japanese()
        self.assertFalse(t.checkChunks(file, chunks, SPEED, OFFSET))

    def test_regions_agree(self):
        self.assertTrue(t.checkRegions(times(self.file), self.speech, SPEED, OFFSET))

    def test_regions_refuse_cut(self):
        self.assertFalse(t.checkRegions(times(self.cutFile), self.speech, SPEED, OFFSET))

    def test_region_verdicts(self):
        self.assertEqual(t.regionVerdict(times(self.file), self.speech, SPEED, OFFSET), t.REGIONS_AGREE)
        self.assertEqual(t.regionVerdict(times(self.cutFile), self.speech, SPEED, OFFSET), t.REGIONS_DISAGREE)
        # a very short video: too few lines for any region to be judged; the
        # regions confirm nothing (checkRegions, a veto, doesn't refuse it)
        short = times(self.file)[:20]
        self.assertEqual(t.regionVerdict(short, self.speech, SPEED, OFFSET), t.REGIONS_INCONCLUSIVE)
        self.assertTrue(t.checkRegions(short, self.speech, SPEED, OFFSET))


class PiecewiseTest(FilmTest):
    """Pieces are fitted by speech overlap, so lines exactly over speech are
    used to know the right answer (lines shown longer than speech fit about
    0.1 s off, which leadShift corrects afterwards)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.exact = makeSubtitles(cls.speech, lead=0.0, tail=0.0)

    def test_cut_is_aligned_in_two_pieces(self):
        cutFile = times(mistime(cut(self.exact, 1800.0, 45.0), SPEED, OFFSET))
        offsets = t.alignPiecewise(cutFile, self.speech, SPEED, OFFSET)
        self.assertIsNotNone(offsets)
        pieces = sorted(set(round(o, 1) for o in offsets))
        self.assertEqual(len(pieces), 2)
        self.assertAlmostEqual(pieces[1] - pieces[0], 45.0, delta=0.2)
        err = offsetErrors(cutFile, self.exact, SPEED, offsets)
        self.assertGreaterEqual(sum(e <= 0.1 for e in err) / len(err), 0.98, 'lines within 0.1 s')

    def test_cuts_away_from_region_boundaries(self):
        # the cut above falls exactly between two regions; these don't
        for name, video in [
                ('mid-region', cut(self.exact, 1337.0, 45.0)),
                ('early', cut(self.exact, 450.0, 45.0)),
                ('5 minutes before the end', cut(self.exact, 3300.0, 45.0)),
                ('2.5 minutes before the end', cut(self.exact, 3450.0, 45.0)),
                ('a scene removed', cut(self.exact, 1337.0, -30.0)),
                ('5 seconds', cut(self.exact, 1337.0, 5.0)),
                ('two cuts 5 minutes apart', cut(cut(self.exact, 2000.0, 45.0), 2345.0, 45.0)),
                ('two cuts 20 minutes apart', cut(cut(self.exact, 1200.0, 30.0), 2430.0, 60.0)) ]:
            with self.subTest(name):
                file = times(mistime(video, SPEED, OFFSET))
                offsets = t.alignPiecewise(file, self.speech, SPEED, OFFSET)
                err = offsetErrors(file, self.exact, SPEED, offsets)
                self.assertGreaterEqual(sum(e <= 0.1 for e in err) / len(err), 0.98, 'lines within 0.1 s')

    @unittest.expectedFailure
    def test_short_section_between_two_cuts(self):
        # known limit: a section of 100 s (24 lines) between two cuts has
        # fewer lines than a window needs (regionMinLines), so its offset is
        # never a candidate; its lines keep the offset around them
        file = times(mistime(cut(cut(self.exact, 2000.0, 45.0), 2145.0, 45.0), SPEED, OFFSET))
        offsets = t.alignPiecewise(file, self.speech, SPEED, OFFSET)
        err = offsetErrors(file, self.exact, SPEED, offsets)
        self.assertGreaterEqual(sum(e <= 0.1 for e in err) / len(err), 0.98)

    def test_no_pieces_without_a_cut(self):
        for seed in (3, 4, 5):
            with self.subTest(film=seed):
                speech = makeSpeech(3600.0, seed=seed)
                file = times(mistime(makeSubtitles(speech, lead=0.0, tail=0.0, seed=seed), SPEED, OFFSET))
                offsets = t.alignPiecewise(file, speech, SPEED, OFFSET)
                self.assertEqual(len(set(round(o, 1) for o in offsets)), 1)

    def test_normal_file_stays_one_piece(self):
        file = times(mistime(self.exact, SPEED, OFFSET))
        offsets = t.alignPiecewise(file, self.speech, SPEED, OFFSET)
        self.assertEqual(len(set(round(o, 1) for o in offsets)), 1)
        err = offsetErrors(file, self.exact, SPEED, offsets)
        self.assertGreaterEqual(sum(e <= 0.1 for e in err) / len(err), 0.99)

    def test_pieces_then_lead_correction(self):
        # real subtitles: lines shown before and after speech; pieces plus
        # the lead correction must land on the right timing
        cutFile = times(mistime(cut(self.video, 1800.0, 45.0), SPEED, OFFSET))
        offsets = t.alignPiecewise(cutFile, self.speech, SPEED, OFFSET)
        mapped = [ (SPEED * s + o, SPEED * e + o) for (s, e), o in zip(cutFile, offsets) ]
        shift = t.leadShift(mapped, self.speech)
        err = offsetErrors(cutFile, self.video, SPEED, [ o + shift for o in offsets ])
        self.assertGreaterEqual(sum(e <= 0.1 for e in err) / len(err), 0.95)


class LeadTest(FilmTest):
    """Lines are moved to start `leadTarget` before speech."""

    def shift(self, lead, count=None):
        lines = times(makeSubtitles(self.speech, lead=lead))
        return t.leadShift(lines[:count] if count else lines, self.speech)

    def test_already_right(self):
        self.assertAlmostEqual(self.shift(t.leadTarget), 0.0, delta=0.02)

    def test_late_lines_move_earlier(self):
        self.assertAlmostEqual(self.shift(0.1), 0.1 - t.leadTarget, delta=0.02)
        self.assertAlmostEqual(self.shift(0.0), -t.leadTarget, delta=0.02)

    def test_target_for_english_audio(self):
        lines = times(makeSubtitles(self.speech, lead=0.25))
        self.assertAlmostEqual(t.leadShift(lines, self.speech, t.leadTargetEnglish),
                0.25 - t.leadTargetEnglish, delta=0.02)
        self.assertLess(t.leadTargetEnglish, t.leadTarget,
                'English-language subtitles start closer to speech')

    def test_too_few_lines(self):
        self.assertEqual(self.shift(0.1, count=20), 0.0)

    def test_implausible_shift_refused(self):
        self.assertEqual(self.shift(t.leadTarget + t.leadMaxShift + 0.15), 0.0)


class SparseDialogueTest(unittest.TestCase):
    """Films with very little dialogue, like Sintel: 26 lines in three
    groups, synchronized from whole lines (see sparseFit)."""

    TEXTS = [ 'This blade has a dark past', 'It has shed much innocent blood',
              'You are a fool for traveling alone', 'You are lucky your blood still flows',
              'Thank you', 'So what brings you here', 'To the land of the gatekeepers',
              'I am searching for someone', 'Someone very dear, a kindred spirit',
              'A dragon', 'A dangerous quest for a lone hunter',
              'I have been alone for as long as I can remember',
              'It is almost over, hold still', 'Good night little Scales',
              'Catch him, quickly', 'Where are you hiding', 'Scales come back',
              'Bring the dragon home', 'Scales where are you', 'I have failed',
              'You have only failed to see', 'These are dragon lands Sintel',
              'You are closer than you know', 'Scales is that you', 'Forgive me Scales',
              'Goodbye little dragon' ]
    STARTS = [ 107.25, 111.8, 118.0, 121.75, 125.25, 127.5, 129.4, 135.0, 138.0, 143.4,
               148.85, 152.95, 207.25, 228.25, 250.35, 265.25, 304.0, 338.75, 360.0,
               445.85, 452.8, 457.8, 460.85, 557.6, 621.6, 626.2 ]
    HEARD = [ 2, 3, 4, 5, 7, 8, 9, 11, 13, 19, 20, 21, 22 ]   # lines Whisper writes down

    def film(self, early=0.35, outlier=21):
        """Subtitle lines and word-timed transcript lines of the film: words
        start `early` seconds before the subtitle line, one line far off."""
        subs = [ (s, s + 2.5, text) for s, text in zip(self.STARTS, self.TEXTS) ]
        rnd = random.Random(5)
        lines = []
        for no in self.HEARD:
            start = self.STARTS[no] - early + rnd.uniform(-0.3, 0.3)
            if no == outlier:
                start -= 3.9
            lines.append((start, start + 2.0, self.TEXTS[no]))
        return subs, lines

    def test_lines_paired_in_order(self):
        subs, lines = self.film()
        pairs = t.pairLines(subs, lines)
        self.assertEqual([ i for i, _j in pairs ], self.HEARD)
        self.assertEqual([ j for _i, j in pairs ], list(range(len(self.HEARD))))

    def test_speed_and_offset_found(self):
        subs, lines = self.film()
        res = t.sparseFit(mistime(subs, 25 / 24, 2.5), lines)
        self.assertIsNotNone(res)
        a, b, agree = res
        self.assertAlmostEqual(a, 25 / 24, places=6)
        self.assertEqual(len(agree), len(self.HEARD) - 1, 'the line far off is left out')
        for (s, _e, _x), (m, _e2, _x2) in zip(subs, mistime(subs, 25 / 24, 2.5)):
            self.assertLess(abs(a * m + b - (s - 0.35)), 0.3)

    def test_offset_does_not_depend_on_lines_paired_by_text(self):
        # a weaker translation pairs fewer lines; the offset is measured on
        # every line near a transcript line, so it comes out the same
        subs, lines = self.film()
        weak = [ (st, e, 'qqxz vvkk' if no in (2, 4, 8, 13, 20) else x)
                 for no, (st, e, x) in enumerate(subs) ]
        full, part = t.sparseFit(subs, lines), t.sparseFit(weak, lines)
        self.assertLess(len(t.pairLines(weak, lines)), len(t.pairLines(subs, lines)))
        self.assertAlmostEqual(full[1], part[1], places=6)

    def test_different_cut_refused(self):
        # a 45 s scene added at 7:30: the 3 lines heard after it agree on
        # another offset; most lines agree, but saving would put 6 lines 45 s off
        subs, lines = self.film(outlier=None)
        heard = [ (s + 45.0, e + 45.0, x) if s >= 450.0 else (s, e, x) for s, e, x in lines ]
        self.assertIsNone(t.sparseFit(mistime(subs, 25 / 24, 2.5), heard))

    def test_repeated_lines_never_give_a_wrong_answer(self):
        # the same short line said again and again ("Scales!"): pairing may
        # pick the wrong one of them, which must not move the result
        subs, lines = self.film(outlier=None)
        repeated = { 13, 16, 18, 22, 23 }
        subs = [ (s, e, 'Scales!' if no in repeated else x) for no, (s, e, x) in enumerate(subs) ]
        lines = [ (s, e, 'Scales!' if no in repeated else x) for no, (s, e, x) in zip(self.HEARD, lines) ]
        lines.append((self.STARTS[23] - 0.35, self.STARTS[23] + 1.0, 'Scales!'))   # heard, not in HEARD
        mistimed = mistime(subs, 25 / 24, 2.5)
        res = t.sparseFit(mistimed, sorted(lines))
        if res is not None:
            a, b, _agree = res
            for (s, _e, _x), (m, _e2, _x2) in zip(subs, mistimed):
                self.assertLess(abs(a * m + b - (s - 0.35)), 0.5)

    def test_subtitles_of_another_film_refused(self):
        _subs, lines = self.film()
        rnd = random.Random(3)
        other = [ (s, s + 2.0, reword(x, rnd) + ' ' + ''.join(rnd.choice('xyzq') for _ in range(9)))
                  for s, x in zip(self.STARTS, reversed(self.TEXTS)) ]
        self.assertIsNone(t.sparseFit(other, lines))

    def test_lines_close_together_refused(self):
        subs, lines = self.film()
        heard = set(range(8))                   # only the first minute
        lines = [ l for no, l in zip(self.HEARD, lines) if no in heard ]
        self.assertIsNone(t.sparseFit(subs, lines), 'speed is not pinned by 40 s of lines')

    def test_too_few_lines_refused(self):
        subs, lines = self.film()
        self.assertIsNone(t.sparseFit(subs, lines[:2] + lines[-2:]))

    def test_lead_measured_from_speech(self):
        agree = [ (s, s - 0.35) for s in self.STARTS[:6] ]
        speech = [ (w + 0.4, w + 2.0) for _s, w in agree ]
        self.assertAlmostEqual(t.sparseShift(agree, speech, 0.15), 0.25)
        self.assertAlmostEqual(t.sparseShift(agree, speech[:2], 0.15), -0.15,
                msg='too few speech starts: lines start target before the words')

    def test_windows_joined(self):
        lines = [ (10.0, 12.0, 'a'), (14.0, 15.0, 'b'), (40.0, 41.0, 'c'), (1.0, 2.0, 'd') ]   # d's range ends at 5 s, a's starts at 7 s
        self.assertEqual(t.sparseWindows(lines, duration=42.5),
                [ (0.0, 5.0), (7.0, 18.0), (37.0, 42.5) ])


class LanguageTest(unittest.TestCase):
    def test_supports(self):
        self.assertTrue(t.supports('jpn'))
        self.assertTrue(t.supports('JPN'))
        self.assertFalse(t.supports('eng'))
        self.assertFalse(t.supports(None))

    def test_translates_only_for_english_subtitles(self):
        self.assertTrue(t.translates('jpn', 'eng'))
        self.assertFalse(t.translates('jpn', 'pol'))
        self.assertFalse(t.translates('eng', 'eng'))


class CacheDirTest(unittest.TestCase):
    def test_key(self):
        with tempfile.NamedTemporaryFile(delete=False) as fp:
            fp.write(b'video')
        try:
            a = t.getCacheDir(fp.name, 1, 'jpn', translate=True)
            self.assertEqual(a, t.getCacheDir(fp.name, 1, 'jpn', translate=True))
            self.assertNotEqual(a, t.getCacheDir(fp.name, 1, 'jpn', translate=False))
            self.assertNotEqual(a, t.getCacheDir(fp.name, 2, 'jpn', translate=True))
            self.assertNotEqual(a, t.getCacheDir(fp.name, 1, 'kor', translate=True))
            self.assertTrue(a.endswith('.en'))
        finally:
            os.remove(fp.name)

    def test_model_folder_counts_as_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(t.isModelInstalled(tmp))


class ModelDownloadTest(unittest.TestCase):
    """A download of one model must not stand in for another model's."""

    def test_downloads_kept_by_model(self):
        import sys
        import threading
        import types
        from unittest import mock

        release, calls = threading.Event(), []

        def download_model(model, revision=None):
            calls.append(model)
            if model == 'small':
                release.wait(10)

        utils = types.ModuleType('faster_whisper.utils')
        utils.download_model = download_model
        modules = { 'faster_whisper': types.ModuleType('faster_whisper'),
                    'faster_whisper.utils': utils }
        with mock.patch.dict(sys.modules, modules), \
                mock.patch.object(t, 'isModelInstalled', return_value=False), \
                mock.patch.object(t, '_downloadedBytes', return_value=0), \
                mock.patch.dict(t._downloads, clear=True):
            try:
                # 'small' keeps downloading in background
                self.assertFalse(t.downloadModel('small', runCb=lambda: False))
                # 'medium' is downloaded on its own, not mistaken for done
                # when the 'small' download finishes (or waited for)
                deadline = threading.Event()
                timer = threading.Timer(5, deadline.set)
                timer.start()
                self.assertTrue(t.downloadModel('medium', runCb=lambda: not deadline.is_set()))
                timer.cancel()
                self.assertEqual(calls, [ 'small', 'medium' ])
                # the same model waits for the running download
                self.assertFalse(t.downloadModel('small', runCb=lambda: False))
                self.assertEqual(calls, [ 'small', 'medium' ])
            finally:
                release.set()
                for state in t._downloads.values():
                    state['thread'].join(5)


if __name__ == '__main__':
    unittest.main()


try:
    import av
    import numpy as np
except ImportError:
    av = None


@unittest.skipIf(av is None, 'PyAV not installed')
class ChannelsTest(unittest.TestCase):
    """Whisper listens only to the chosen channels, like SubSync's own speech
    recognition does: dialogue in the center channel of 5.1 audio, music and
    effects in the others."""

    @classmethod
    def setUpClass(cls):
        rate, seconds = t.sampleRate, 6
        rnd = np.random.default_rng(7)
        n = rate * seconds
        # "dialogue": 440 Hz bursts every other second, center channel only
        tone = 0.3 * np.sin(2 * np.pi * 440 * np.arange(n) / rate)
        cls.dialogue = tone * (np.arange(n) // rate % 2 == 0)
        noise = 0.3 * rnd.standard_normal((6, n)).clip(-3, 3) / 3
        noise[2] = cls.dialogue                 # FL FR FC LFE BL BR
        cls.folder = tempfile.mkdtemp(prefix='subsync-test-')
        cls.path = os.path.join(cls.folder, 'surround.wav')
        with av.open(cls.path, 'w') as out:
            stream = out.add_stream('pcm_s16le', rate=rate, layout='5.1')
            frame = av.AudioFrame.from_ndarray(
                    (noise * 32767).astype(np.int16).T.reshape(1, -1), format='s16', layout='5.1')
            frame.sample_rate = rate
            for packet in stream.encode(frame):
                out.mux(packet)
            for packet in stream.encode(None):
                out.mux(packet)

    @classmethod
    def tearDownClass(cls):
        os.remove(cls.path)
        os.rmdir(cls.folder)

    def similarity(self, audio):
        n = min(len(audio), len(self.dialogue))
        a, b = audio[:n], self.dialogue[:n]
        return float(np.dot(a, b) / np.sqrt(np.dot(a, a) * np.dot(b, b)))

    def test_center_channel_only(self):
        audio = t.decodeRange(self.path, channels=['FC'])
        self.assertGreater(self.similarity(audio), 0.99)

    def test_all_channels_by_default(self):
        audio = t.decodeRange(self.path)
        self.assertLess(self.similarity(audio), 0.9)

    def test_missing_channel_means_all(self):
        audio = t.decodeRange(self.path, channels=['SL'])
        self.assertLess(self.similarity(audio), 0.9)

    def test_part_of_the_audio(self):
        audio = t.decodeRange(self.path, start=2.0, end=3.0, channels=['FC'])
        self.assertEqual(len(audio), t.sampleRate)
        n = t.sampleRate
        a, b = audio, self.dialogue[2 * n:3 * n]
        self.assertGreater(float(np.dot(a, b) / np.sqrt(np.dot(a, a) * np.dot(b, b))), 0.99)

    def test_speech_only(self):
        # speech detection without transcription (to polish the original
        # method's result) is kept like transcripts' plan, and reused
        out = tempfile.mkdtemp(prefix='subsync-test-')
        try:
            speech = t.planSpeech(self.path, out, channels=['FC'])
            self.assertIsInstance(speech, list)
            self.assertEqual(t.loadSpeech(out), speech)
            self.assertAlmostEqual(t.loadPlan(out)[-1][1], 6.0, delta=0.01)
            self.assertFalse(any(name.startswith('chunk-') for name in os.listdir(out)))
            mtime = os.path.getmtime(os.path.join(out, 'plan.json'))
            t.planSpeech(self.path, out, channels=['FC'])
            self.assertEqual(os.path.getmtime(os.path.join(out, 'plan.json')), mtime)
        finally:
            for name in os.listdir(out):
                os.remove(os.path.join(out, name))
            os.rmdir(out)

    def test_chunks_and_cache(self):
        self.assertNotEqual(t.getCacheDir(self.path, None, 'jpn'),
                t.getCacheDir(self.path, None, 'jpn', channels=['FC']))
        chunks = t.planChunks(self.path, speech=[], channels=['FC'])
        self.assertAlmostEqual(chunks[-1][1], 6.0, delta=0.01)


try:
    import faster_whisper
except ImportError:
    faster_whisper = None


@unittest.skipIf(faster_whisper is None, 'faster-whisper not installed')
class FasterWhisperTest(unittest.TestCase):
    """transcribe.py uses some of faster-whisper's internals; a new version of
    it must still have them, or model download and speech detection break."""

    def parameters(self, func):
        import inspect
        return inspect.signature(func).parameters

    def test_model_download(self):
        from faster_whisper.utils import _MODELS, download_model
        self.assertIn(t.defaultModel(), _MODELS)
        for name in ('revision', 'local_files_only'):
            self.assertIn(name, self.parameters(download_model))
        self.assertIn('revision', self.parameters(faster_whisper.WhisperModel.__init__))

    def test_speech_detection(self):
        from faster_whisper.vad import VadOptions, get_speech_timestamps  # noqa: F401
        VadOptions(min_silence_duration_ms=300, speech_pad_ms=0)

    def test_transcription_options(self):
        params = self.parameters(faster_whisper.WhisperModel.transcribe)
        for name in ('language', 'task', 'beam_size', 'vad_filter',
                'condition_on_previous_text', 'word_timestamps'):
            self.assertIn(name, params)
        params = self.parameters(faster_whisper.WhisperModel.detect_language)
        for name in ('vad_filter', 'language_detection_segments'):
            self.assertIn(name, params)
