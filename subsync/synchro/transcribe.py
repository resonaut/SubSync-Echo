"""Whisper based transcription, for languages without a pocketsphinx model.

SubSync recognises speech with pocketsphinx, which has no model for Japanese
and many other languages. For such languages the audio is transcribed here
(with the optional faster-whisper package) to timed text lines, which are then
used as a subtitle reference.

Audio is split to chunks of a few minutes, cut in quiet moments, and every
chunk is transcribed to its own SRT file. During synchronization chunks are
transcribed in an order spread over the whole file (first, last, middle...),
so synchronization could stop as soon as its result is stable, without
transcribing the whole movie. Chunks are cached in the temporary directory, so
synchronizing against the same file again does not repeat the transcription.

This module deliberately imports nothing from subsync or gizmo, so it can also
be run on its own to produce a reference for an unmodified SubSync:

    python subsync/synchro/transcribe.py video.mkv

Environment variables:
    SUBSYNC_WHISPER_MODEL    model size or path (default: small)
    SUBSYNC_WHISPER_DEVICE   cpu, cuda or auto (default: cpu)
    SUBSYNC_WHISPER_COMPUTE  ctranslate2 compute type (default: int8)
    SUBSYNC_WHISPER_PYTHON   Python with faster-whisper, when SubSync's own
                             Python does not have it (default: .whisper next
                             to the sources)
"""

import hashlib
import json
import os
import sys
import tempfile
import threading

import logging
logger = logging.getLogger(__name__)


# 3-letter language code => whisper language code, for languages that have no
# pocketsphinx speech model
languages = {
        'alb': 'sq', 'ara': 'ar', 'bel': 'be', 'bul': 'bg', 'cat': 'ca',
        'cze': 'cs', 'dan': 'da', 'est': 'et', 'fao': 'fo', 'fin': 'fi',
        'glg': 'gl', 'heb': 'he', 'hrv': 'hr', 'hun': 'hu', 'ice': 'is',
        'ind': 'id', 'jpn': 'ja', 'kor': 'ko', 'lat': 'la', 'lav': 'lv',
        'lit': 'lt', 'may': 'ms', 'mlg': 'mg', 'mlt': 'mt', 'nor': 'no',
        'per': 'fa', 'pol': 'pl', 'por': 'pt', 'rum': 'ro', 'slo': 'sk',
        'slv': 'sl', 'srp': 'sr', 'swe': 'sv', 'tur': 'tr', 'ukr': 'uk',
        }

sampleRate = 16000

# audio is transcribed in chunks of about this length (seconds), so memory use
# does not grow with the length of the movie and synchronization could stop
# before the whole movie is transcribed
chunkLength = 300.0
# short videos are split to at least this many chunks (none shorter than
# chunkMinLength seconds), as synchronization must be confirmed by at least
# checkMinChunks chunks on their own (Tears of Steel, 12 minutes, was split
# in 2 and its credits half had too few words)
chunkMinCount = 4
chunkMinLength = 120.0
# chunks are cut in the quietest moment of this long window (seconds) around
# their nominal border, to not split a sentence in the middle
chunkCutWindow = 60.0
# resolution of the audio energy used to find quiet moments (seconds)
energyStep = 0.25

# whisper times a line from the first to the last spoken word, while subtitle
# lines usually appear at speech start and stay on screen longer, to be read;
# SubSync spreads words evenly over the line display time, so the transcript is
# timed like subtitles are, otherwise synchronized subtitles would come early;
# measured on two movies, subtitles start ~0.3 s after whisper lines and end
# ~0.7-1.1 s after them, with these values synchronization error was < 0.02 s
lineLeadIn = 0.3
lineLeadOut = 1.0
lineReadingSpeed = 17.0     # characters per second
lineMinDuration = 0.833
lineMaxDuration = 7.0
lineMinGap = 0.083
# Whisper's speech filter cuts music out, and sometimes joins speech from
# both sides of a song into one segment: it then lasts far longer than its
# text needs (75 s for 4 s of text across a song in Sita Sings the Blues)
# and starts far from where the words are said; such lines are left out,
# they made a whole transcribed part disagree with the right timing
lineMaxStretch = 3.0        # times the reading time of the text,
lineStretchSlack = 10.0     # plus this many seconds

# bump when transcript content or timing changes, to not reuse old cache
cacheVersion = 3

# speech is detected (for refineFormula) in blocks of this length (seconds);
# pauses shorter than speechMinSilence (seconds) do not split it
speechBlockLength = 300.0
speechMinSilence = 0.3

# synchronization found by matching words of a few transcript chunks is
# polished with speech of the whole file (see refineFormula), searched this
# close to it: speed (as a fraction) and offset (seconds)
refineScaleRange = 4e-4
# in short videos (subtitles spanning less than shortVideo seconds) matched
# words span only a few minutes and pin the speed down less precisely (on
# Tears of Steel, 10 minutes, they were 0.5% off), and speech overlap is flat
# enough to confirm a wrong speed close to them: speed is searched this wide
# instead, and accepted only as a frame rate conversion (see frameRates), set
# exactly, since speech alone pins it to only ~0.03% in a short video
shortVideo = 1800.0
refineScaleWide = 0.02
# frame rates subtitles are made for: speed differences between them are the
# speeds accepted from the wide search (within refineScaleRange)
frameRates = (24000 / 1001, 24.0, 25.0, 30000 / 1001, 30.0)
refineOffsetRange = 3.0
# polished result must be the best one in this much wider offset range too
refineWideRange = 60.0
refineStep = 0.01   # seconds

# every transcribed chunk must agree with the synchronization formula on its
# own (see checkChunks), otherwise subtitles may not fit one formula at all,
# e.g. they were made for a different cut of the movie: words of transcript
# lines are matched with subtitle lines up to checkWindow seconds away, and
# the time differences of matches must cluster around zero (+-checkTolerance)
checkWindow = 120.0
checkTolerance = 2.0
checkMinLines = 10      # chunks with fewer transcript lines are not judged
checkMinMatches = 3
checkMinChunks = 2      # this many chunks must agree
# a transcript line starting while its subtitle line is shown is on time:
# Whisper splits long sentences, the later pieces start seconds after the
# subtitle line; lines shown longer than this are counted only this long
checkSpanMax = 10.0

# speech of the whole file is checked region by region too (see checkRegions),
# as transcribed chunks may miss the part of the movie that does not fit:
# subtitles of every region are moved up to regionSearch seconds against
# detected speech, the best fit must be within regionTolerance seconds
regionLength = 900.0
regionMinLines = 30     # regions with fewer subtitle lines are not judged
regionSearch = 60.0
regionTolerance = 1.0
regionMargin = 1.2      # fit elsewhere must be this much better to disagree

# subtitles made for a different cut of the movie (scenes added or removed)
# are synchronized piecewise (see alignPiecewise): offsets of regions are
# searched this far (seconds) around the formula; changing the offset between
# subtitle lines costs piecewiseSplitCost (seconds of speech overlap, roughly
# 20 subtitle lines worth), so only clear evidence splits the subtitles
piecewiseRange = 600.0
piecewiseSplitCost = 10.0
piecewiseFineRange = 0.5    # each piece is then fine tuned this far
# offsets to choose from come from the regions and from windows of
# piecewiseWindow seconds sliding by half of it: a cut near the end of a region
# (or of the film) moves too few of the region's lines for its own best fit to
# move, but most of a window's; a window also needs regionMinLines lines, and
# its offset counts only when the next window (half over it) fits there too
piecewiseWindow = 300.0

# fitting subtitle lines to speech overlap leaves them slightly late: correct
# subtitles appear a moment before people start speaking. Synchronized lines
# are moved so that their starts lead speech by leadTarget seconds (median of
# lines that follow a pause and have one clear speech start within leadReach
# seconds). The habit differs between film traditions, measured on 26
# subtitle files: subtitles of 9 Japanese films start 0.16 - 0.31 s before
# speech (median 0.25 s), subtitles of 13 English-language films 0.13 - 0.35 s
# (median 0.15 s; a few start after speech, down to -0.6 s). So the target
# depends on the audio language: leadTargetEnglish for English audio. Not done
# when fewer than leadMinLines lines are measured, or when it would move lines
# more than leadMaxShift seconds.
leadTarget = 0.25
leadTargetEnglish = 0.15
leadGap = 0.4
leadReach = 1.0
leadClear = 0.4
leadMinLines = 30
leadMaxShift = 0.3

# films with very little dialogue (Sintel: 26 lines in 15 minutes, much music)
# give the correlator too few matched words (minPointsNo) and speech detection
# too little speech to confirm anything. When every chunk is transcribed and
# nothing correlated, subtitles of at most sparseMaxLines lines are
# synchronized from whole lines instead (see sparseFit): subtitle lines are
# paired with transcript lines saying the same, in order of both, and the
# speed must be one of frameRatios. Whisper's line times are seconds off in
# such films (its speech filter joins music to the lines), so speech around
# the paired lines is transcribed again with word times first, sparseMargin
# seconds around each (see getWordLines); the first, rougher transcript must
# pair at least sparseMinPaired lines, and every transcript line is timed
# again when that is at most sparseMaxAudio seconds of audio. The result is
# accepted when at least sparseMinLines pairs agree within sparseTolerance
# seconds, they are at least sparseMinShare of all pairs and span
# sparseMinSpan seconds, and no other
# speed and offset fitting as many pairs would move a line by more than
# 2 * sparseTolerance, and no sparseCutLines of the pairs left out agree among
# themselves on another offset (as subtitles of a different cut would).
# Longer subtitles never take this way. The offset is
# then measured again on every subtitle line that has exactly one transcript
# line starting within sparseTolerance (see sparseRefine): which lines pair
# by text depends on the translation, which differs a little between
# computers, and an offset from 5 or 6 lines moved by up to 0.1 s with it.
sparseMaxLines = 300
sparseMinSim = 0.34     # share of the shorter line's words found in the other
sparseWordLen = 4       # shortest word compared (without letter groups)
sparseMinLines = 5
sparseMinPaired = 3
sparseMaxAudio = 1200.0
sparseMinShare = 0.6
sparseMinSpan = 120.0
sparseTolerance = 1.0
sparseMargin = 3.0
sparseMinOnsets = 3     # speech starts needed to correct word times
sparseCutLines = 2      # paired lines agreeing on another offset: another cut
sparsePause = 0.8       # seconds between words that end a line (see wordLines)


class Terminated(Exception):
    """Transcription was cancelled by the caller."""


class NotInstalled(Exception):
    """faster-whisper package is not installed."""

    def __init__(self):
        super().__init__('faster-whisper is not installed, '
                'install it with: pip install faster-whisper')


def supports(lang):
    """Check whether audio in this language (3-letter code) is handled here."""
    return bool(lang) and lang.lower() in languages


def whisperCode(lang):
    """Whisper language code of a 3-letter one. English has a pocketsphinx
    model, but its speech goes through Whisper too when subtitles in another
    language are matched through English (see route.py)."""
    lang = lang.lower()
    return languages.get(lang) or { 'eng': 'en' }.get(lang, lang)


def isAvailable():
    """Check whether faster-whisper is installed, here or in separate Python."""
    return _hasModule() or bool(findPython())


def translates(refLang, subLang):
    """Check whether speech should be translated to English, instead of being
    transcribed. It is much more reliable for English subtitles than matching
    the transcript through the dictionary."""
    return supports(refLang) and bool(subLang) and subLang.lower() == 'eng'


def defaultModel():
    return os.environ.get('SUBSYNC_WHISPER_MODEL') or 'small'


def formatTime(seconds):
    ms = max(int(round(seconds * 1000.0)), 0)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return '{:02d}:{:02d}:{:02d},{:03d}'.format(h, m, s, ms)


def parseTime(text):
    hms, _, ms = text.strip().partition(',')
    h, m, s = hms.split(':')
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms or 0) / 1000.0


# --- audio decoding --------------------------------------------------------

def _openAudio(container, path, streamNo):
    stream = None
    if streamNo is not None and 0 <= streamNo < len(container.streams):
        stream = container.streams[streamNo]
        if stream.type != 'audio':
            stream = None
    if stream is None:
        if not container.streams.audio:
            raise ValueError('there is no audio stream in {}'.format(path))
        stream = container.streams.audio[0]
    return stream


def _frames(container, stream, runCb):
    """Decoded audio frames, followed by `None` (to flush the resampler)."""
    for no, frame in enumerate(container.decode(stream)):
        if runCb and no % 256 == 0 and not runCb():
            raise Terminated()
        yield frame
    yield None


class _Mixer(object):
    """Resamples decoded frames to mono 16 kHz 16-bit samples, listening only
    to `channels` (FFmpeg channel names, e.g. ['FC'], as SubSync's own speech
    recognition does, see channels.py) or, when `None`, to all of them."""

    def __init__(self, channels=None):
        self.channels = list(channels) if channels else None
        self.resampler = None
        self.pick = None

    def _open(self, frame):
        import av
        names = [ ch.name for ch in frame.layout.channels ]
        pick = [ names.index(ch) for ch in self.channels or () if ch in names ]
        if pick and len(pick) < len(names):
            logger.info('listening to channels %s of %s', ','.join(names[i] for i in pick),
                    ','.join(names))
            self.pick = pick
            self.resampler = av.AudioResampler(format='fltp', layout=frame.layout, rate=sampleRate)
        else:
            if self.channels and not pick:
                logger.info('channels %s not in %s, listening to all',
                        ','.join(self.channels), ','.join(names))
            self.resampler = av.AudioResampler(format='s16', layout='mono', rate=sampleRate)

    def resample(self, frame):
        """List of int16 arrays; `None` frame flushes the resampler."""
        import numpy as np
        if self.resampler is None:
            if frame is None:
                return []
            self._open(frame)
        res = []
        for out in self.resampler.resample(frame):
            data = out.to_ndarray()
            if self.pick is None:
                res.append(data.reshape(-1))
            else:
                mono = data[self.pick].mean(axis=0) * 32768.0
                res.append(np.clip(np.round(mono), -32768, 32767).astype(np.int16))
        return res


class _SpeechDetector(object):
    """Detects speech, with voice activity detector of faster-whisper, in
    audio pushed in pieces. Appends (start, end) times to `result`."""

    def __init__(self, result):
        try:
            from faster_whisper.vad import VadOptions, get_speech_timestamps
        except ImportError:
            raise NotInstalled()
        self.detect = get_speech_timestamps
        self.options = VadOptions(
                min_silence_duration_ms=int(speechMinSilence * 1000),
                speech_pad_ms=0)
        self.result = result
        self.pending, self.size, self.offset = [], 0, 0

    def push(self, data):
        self.pending.append(data)
        self.size += len(data)
        if self.size >= speechBlockLength * sampleRate:
            self.flush()

    def flush(self):
        import numpy as np
        if self.size:
            audio = np.concatenate(self.pending).astype(np.float32) / 32768.0
            for item in self.detect(audio, self.options):
                self.result.append((
                    round((self.offset + item['start']) / sampleRate, 3),
                    round((self.offset + item['end']) / sampleRate, 3)))
            self.offset += len(audio)
            self.pending, self.size = [], 0


def chunkCount(duration, length=None):
    """Number of chunks `duration` seconds of audio are split to."""
    count = int(round(duration / (length or chunkLength)))
    short = min(chunkMinCount, int(duration // chunkMinLength))
    return max(count, short, 1)


def planChunks(path, streamNo=None, runCb=None, length=None, speech=None, channels=None):
    """Split audio stream to chunks of about `length` seconds, cut in the
    quietest moments.

    When `speech` list is given, it is filled with (start, end) times of speech
    detected in the whole stream. `channels` see `_Mixer`.

    Returns
    -------
    list of (float, float)
        Chunks start and end times, in seconds.
    """
    import av
    import numpy as np

    length = length or chunkLength
    step = int(sampleRate * energyStep)
    energy, rest, total = [], np.zeros(0, dtype=np.float32), 0
    detector = _SpeechDetector(speech) if speech is not None else None

    with av.open(path) as container:
        stream = _openAudio(container, path, streamNo)
        mixer = _Mixer(channels)
        for frame in _frames(container, stream, runCb):
            for data in mixer.resample(frame):
                if detector:
                    detector.push(data)
                data = data.astype(np.float32)
                total += len(data)
                if len(rest):
                    data = np.concatenate((rest, data))
                count = len(data) // step
                if count:
                    energy.append(np.square(data[:count * step]).reshape(count, step).mean(axis=1))
                rest = data[count * step:]

    if detector:
        detector.flush()

    duration = total / sampleRate
    if duration <= 0:
        return []

    energy = np.concatenate(energy) if energy else np.zeros(0)
    pairs = energy[:-1] + energy[1:]    # 0.5 s windows
    count = chunkCount(duration, length)
    half = chunkCutWindow / 2.0 / energyStep

    cuts = [ 0.0 ]
    for no in range(1, count):
        center = no * duration / count / energyStep
        lo, hi = int(max(center - half, 0)), int(min(center + half, len(pairs)))
        if hi > lo:
            # cut in the middle of the quietest window
            cut = (lo + int(np.argmin(pairs[lo:hi])) + 1) * energyStep
            if cuts[-1] < cut < duration:
                cuts.append(cut)
    cuts.append(duration)
    return list(zip(cuts[:-1], cuts[1:]))


def decodeRange(path, streamNo=None, start=0.0, end=None, runCb=None, channels=None):
    """Decode audio between `start` and `end` seconds to mono 16 kHz float32
    numpy array. streamNo is 0-based stream index in the container, `None` for
    the first audio stream; `channels` see `_Mixer`."""
    import av
    import numpy as np

    first = int(round(start * sampleRate))
    size = None if end is None else int(round(end * sampleRate)) - first

    def decode(seek):
        chunks, got, pos = [], 0, None
        with av.open(path) as container:
            stream = _openAudio(container, path, streamNo)
            if seek:
                # lands on the last packet before `start`
                container.seek(int(start / stream.time_base), stream=stream)
            mixer = _Mixer(channels)

            for frame in _frames(container, stream, runCb):
                if pos is None and frame is not None:
                    if not seek:
                        pos = 0
                    elif frame.time is None:
                        return None     # position unknown, decode from start
                    else:
                        pos = int(round(frame.time * sampleRate))
                        if pos > first:     # seek landed too far, keep timing
                            chunks.append(np.zeros(pos - first, dtype=np.int16))
                            got = pos - first

                for data in mixer.resample(frame):
                    if pos < first:
                        skip = min(first - pos, len(data))
                        data, pos = data[skip:], pos + skip
                    if len(data):
                        chunks.append(data)
                        got += len(data)
                        pos += len(data)

                if size is not None and got >= size:
                    break

        audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.int16)
        return audio if size is None else audio[:size]

    audio = decode(seek=start > 0)
    if audio is None:
        audio = decode(seek=False)
    return audio.astype(np.float32) / 32768.0


# --- language detection ----------------------------------------------------

# audio language is detected from a few minutes taken from these positions
# (fractions of the length), skipping intros and credits; only speech counts
detectPositions = (0.3, 0.5, 0.7)
detectLength = 120.0
detectSegments = 4          # 30 s pieces of speech the model listens to
detectMinProbability = 0.5


def _duration(path, streamNo):
    import av
    with av.open(path) as container:
        stream = _openAudio(container, path, streamNo)
        if stream.duration and stream.time_base:
            return float(stream.duration * stream.time_base)
        if container.duration:
            return container.duration / 1000000.0
    return None


def detectLanguage(path, streamNo=None, model=None, runCb=None):
    """Detect language spoken in the audio stream, in this process.

    Returns
    -------
    tuple of (str, float)
        Whisper language code (e.g. 'ja') and its probability, or `None`
        when there is too little speech or the model is not sure.
    """
    import numpy as np

    length = _duration(path, streamNo)
    if length and length > 3 * detectLength:
        ranges = [ (length * pos, length * pos + detectLength) for pos in detectPositions ]
    else:
        ranges = [ (0.0, None) ]

    audio = np.concatenate([ decodeRange(path, streamNo, start, end, runCb)
        for start, end in ranges ])
    if runCb and not runCb():
        raise Terminated()

    whisper = loadModel(model)
    lang, prob, _all = whisper.detect_language(audio, vad_filter=True,
            language_detection_segments=detectSegments)
    logger.info('detected audio language: %s (%.0f%%)', lang, 100 * prob)
    if prob < detectMinProbability:
        return None
    return lang, prob


def getLanguage(path, streamNo=None, model=None, runCb=None):
    """Detect spoken language like `detectLanguage`, in this process or in
    separate Python (see `findPython`)."""
    if _hasModule():
        return detectLanguage(path, streamNo, model, runCb)

    import subprocess
    python = findPython()
    if not python:
        raise NotInstalled()
    cmd = [ python, os.path.abspath(__file__), path, '--detect-language' ]
    if streamNo is not None:
        cmd += [ '--stream', str(streamNo + 1) ]
    if model:
        cmd += [ '--model', model ]
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=flags)
    for line in res.stdout.decode('utf-8', 'replace').splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[0] == 'language':
            return fields[1], float(fields[2])
        if fields == [ 'language', 'none' ]:
            return None
    raise RuntimeError('language detection failed: {}'.format(
        res.stderr.decode('utf-8', 'replace').strip().splitlines()[-1:]))


# --- transcription ---------------------------------------------------------

def isStretched(start, end, text):
    """Transcript line lasting far longer than its text needs, see
    `lineMaxStretch`."""
    return end - start > lineMaxStretch * len(text) / lineReadingSpeed + lineStretchSlack


def readChunk(path):
    """Transcript lines of a chunk (see `readSrt`) without stretched ones
    (see `isStretched`), also of chunks transcribed before they were left
    out: a line keeps the end of its speech (see `timeLines`)."""
    lines = readSrt(path)
    res = [ l for l in lines if not isStretched(*l) ]
    if len(res) < len(lines):
        logger.info('%i stretched transcript lines left out of %s', len(lines) - len(res),
                os.path.basename(path))
    return res


def timeLines(lines):
    """Time transcript lines like subtitles, see `lineLeadIn` and following.

    lines is list of (start, end, text) tuples, sorted by start time.
    """
    res = []
    for no, (start, end, text) in enumerate(lines):
        begin = start + lineLeadIn
        finish = max(end + lineLeadOut, begin + len(text) / lineReadingSpeed,
                begin + lineMinDuration)
        finish = min(finish, begin + lineMaxDuration)
        if no + 1 < len(lines):
            finish = min(finish, lines[no + 1][0] + lineLeadIn - lineMinGap)
        # never shorter than the speech itself
        res.append((begin, max(finish, end), text))
    return res


# the last loaded model is kept, so language detection and transcription of
# several files (batch mode) don't load it again every time
_loaded = {}
_loadedLock = threading.Lock()


def loadModel(model=None):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise NotInstalled()

    model = model or defaultModel()
    device = os.environ.get('SUBSYNC_WHISPER_DEVICE') or 'cpu'
    compute = os.environ.get('SUBSYNC_WHISPER_COMPUTE') or 'int8'
    key = (model, device, compute)

    with _loadedLock:
        if key in _loaded:
            return _loaded[key]
        _loaded.clear()

        logger.info('loading whisper model %s (%s, %s)', model, device, compute)
        try:
            whisper = WhisperModel(model, device=device, compute_type=compute,
                    revision=modelRevision(model))
        except Exception as err:
            if isModelInstalled(model) is False:
                raise DownloadFailed('could not download speech recognition model, '
                        'check internet connection ({})'.format(err))
            raise
        _loaded[key] = whisper
        return whisper


# the default model is downloaded at the revision it was tested with, so a
# change in its Hugging Face repository can't change results unnoticed
modelRevisions = {
        'small': '536b0662742c02347bc0e980a01041f333bce120',
        }


def modelRevision(model):
    return modelRevisions.get(model)


# approximate download size of the models, in bytes
modelSizes = {
        'tiny': 75e6, 'base': 145e6, 'small': 486e6, 'medium': 1530e6,
        'large-v2': 3090e6, 'large-v3': 3090e6,
        }

# running model downloads by model, shared by all callers of the same model
_downloads = {}
_downloadsLock = threading.Lock()


class DownloadFailed(Exception):
    """Model could not be downloaded, usually there is no internet."""


def getModelSize(model=None):
    """Approximate model download size in bytes, `None` if not known."""
    return modelSizes.get(model or defaultModel())


def isModelInstalled(model=None):
    """Check whether the model is already downloaded.

    Returns
    -------
    bool or None
        `None` when it cannot be told, because faster-whisper runs in
        separate Python (it then downloads the model itself).
    """
    model = model or defaultModel()
    if os.path.isdir(model):
        return True
    if not _hasModule():
        return None
    try:
        from faster_whisper.utils import download_model
        download_model(model, local_files_only=True, revision=modelRevision(model))
        return True
    except Exception:
        return False


def _downloadedBytes(model):
    """Bytes of the model already on disk, including partial files."""
    try:
        from faster_whisper.utils import _MODELS
        from huggingface_hub.constants import HF_HUB_CACHE
        repo = _MODELS.get(model, model)
        folder = os.path.join(HF_HUB_CACHE, 'models--' + repo.replace('/', '--'))
        total = 0
        for root, dirs, files in os.walk(folder):
            for name in files:
                path = os.path.join(root, name)
                if not os.path.islink(path):
                    total += os.path.getsize(path)
        return total
    except Exception:
        return 0


def downloadModel(model=None, runCb=None, progressCb=None):
    """Download the model to the Hugging Face cache, unless already there.

    Download continues in background if `runCb` stops waiting for it, and the
    next call for the same model waits for the same download (a different
    model is downloaded on its own). Partially downloaded files are resumed.

    Parameters
    ----------
    runCb: callable, optional
        Called periodically, stop waiting when it returns `False`.
    progressCb: callable, optional
        Called periodically with (downloaded bytes, expected size or `None`).

    Returns
    -------
    bool
        `True` when downloaded, `False` when stopped by `runCb`.

    Raises
    ------
    DownloadFailed
    """
    model = model or defaultModel()
    if isModelInstalled(model) is not False:
        return True

    with _downloadsLock:
        state = _downloads.get(model)
        if state is None or not state['thread'].is_alive():
            state = { 'error': None, 'model': model }

            def run(state=state):
                try:
                    from faster_whisper.utils import download_model
                    logger.info('downloading whisper model %s', model)
                    download_model(model, revision=modelRevision(model))
                    logger.info('whisper model %s downloaded', model)
                except Exception as err:
                    logger.warning('whisper model download failed: %r', err, exc_info=True)
                    state['error'] = err

            state['thread'] = threading.Thread(target=run, name='ModelDownload', daemon=True)
            state['thread'].start()
            _downloads[model] = state

    size = getModelSize(model)
    while state['thread'].is_alive():
        if progressCb:
            progressCb(_downloadedBytes(model), size)
        if runCb and not runCb():
            return False
        state['thread'].join(timeout=0.25)

    if state['error'] is not None:
        raise DownloadFailed('could not download speech recognition model, '
                'check internet connection ({})'.format(state['error']))
    return True


def transcribeRange(whisper, path, streamNo, start, end, lang, translate=False,
        runCb=None, progressCb=None, channels=None):
    """Transcribe audio between `start` and `end` seconds.

    Returns
    -------
    list of (float, float, str)
        Lines start time, end time and text, timed like subtitles.
    """
    audio = decodeRange(path, streamNo, start, end, runCb, channels)

    # voice detection and no conditioning on previous text keeps whisper from
    # inventing lines during music or silence, which would spoil the timing;
    # greedy decoding (beam_size=1) is about twice as fast as the default beam
    # search, worse wording does not matter for synchronization; word
    # timestamps are not needed either: without them a film syncs about 20%
    # faster with the same accuracy (measured on 3 films, both orders)
    segments, _info = whisper.transcribe(audio,
            language=lang,
            task='translate' if translate else 'transcribe',
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,
            word_timestamps=False)

    lines = []
    for segment in segments:
        if runCb and not runCb():
            raise Terminated()

        text = ' '.join(segment.text.split())
        if isStretched(segment.start, segment.end, text):
            logger.info('stretched transcript line left out: %s - %s, %s', formatTime(start + segment.start),
                    formatTime(start + segment.end), text[:40])
        elif text and segment.end > segment.start:
            lines.append((start + segment.start, start + segment.end, text))

        if progressCb:
            progressCb(start + segment.end)

    return timeLines(lines)


def transcribeWords(whisper, path, streamNo, ranges, lang, translate=False,
        runCb=None, channels=None):
    """Transcribe audio of `ranges` ((start, end) seconds) with word times.

    Returns
    -------
    list of (float, float, str)
        Lines from the start of their first word to the end of their last,
        split into sentences (see `wordLines`).
    """
    lines = []
    for start, end in ranges:
        audio = decodeRange(path, streamNo, start, end, runCb, channels)
        segments, _info = whisper.transcribe(audio,
                language=lang,
                task='translate' if translate else 'transcribe',
                beam_size=1,
                vad_filter=True,
                condition_on_previous_text=False,
                word_timestamps=True)
        for segment in segments:
            if runCb and not runCb():
                raise Terminated()
            words = [ (w.start, w.end, w.word) for w in segment.words or [] if w.end > w.start ]
            lines += wordLines(words, start)
    return sorted(lines)


def wordLines(words, offset=0.0):
    """Lines of one Whisper segment from its timed words: a new line starts
    after a word ending a sentence (. ? !) and at a pause of `sparsePause`
    seconds or more. Whisper sometimes puts two or three spoken lines in one
    segment, and how it groups them differs between computers; split, every
    sentence keeps the time of its own first word.

    words is a list of (start, end, text) tuples, times from `offset`.
    """
    lines, current = [], []

    def close():
        text = ' '.join(' '.join(w[2] for w in current).split())
        if text:
            lines.append((offset + current[0][0], offset + current[-1][1], text))
        del current[:]

    for word in words:
        if current and word[0] - current[-1][1] >= sparsePause:
            close()
        current.append(word)
        if word[2].strip().endswith(('.', '?', '!', '\u3002', '\uff1f', '\uff01')):
            close()
    if current:
        close()
    return lines


def spreadOrder(count):
    """Chunk indices ordered to cover the whole file as soon as possible:
    first, last, middle, quarters and so on."""
    if count <= 0:
        return []
    order = [ 0 ]
    if count > 1:
        order.append(count - 1)
    left = set(range(count)) - set(order)
    while left:
        best = max(sorted(left), key=lambda no: min(abs(no - x) for x in order))
        order.append(best)
        left.remove(best)
    return order


def getChunkPath(outDir, no):
    return os.path.join(outDir, 'chunk-{:03d}.srt'.format(no))


def loadPlan(outDir):
    try:
        with open(os.path.join(outDir, 'plan.json'), encoding='utf-8') as fp:
            return [ tuple(x) for x in json.load(fp)['chunks'] ]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def loadSpeech(outDir):
    """Speech (start, end) times detected in the whole audio stream, `None`
    when not detected yet."""
    try:
        with open(os.path.join(outDir, 'plan.json'), encoding='utf-8') as fp:
            return [ tuple(x) for x in json.load(fp)['speech'] ]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _savePlan(outDir, chunks, speech=None):
    path = os.path.join(outDir, 'plan.json')
    data = { 'chunks': chunks }
    if speech is not None:
        data['speech'] = speech
    with open(path + '.part', 'w', encoding='utf-8') as fp:
        json.dump(data, fp)
    os.replace(path + '.part', path)


def isShort(subs):
    """Subtitles of a short video (see shortVideo), (start, end, ...) times."""
    starts = [ s[0] for s in subs ]
    return bool(starts) and max(starts) - min(starts) < shortVideo


def refineFormula(subs, speech, a, b, scaleRange=None):
    """Polish synchronization formula with speech of the whole file.

    Formula (synchronized time = a * subtitle time + b) found by matching words
    of a few transcript chunks is right within a second or so. Here speed and
    offset are searched close to it, for the best overlap of subtitle lines with
    detected speech. That uses the whole file and needs no language knowledge,
    but alone it could settle on a wrong answer far away; starting from matched
    words and checking a much wider range prevents that.

    Parameters
    ----------
    subs: list of (float, float)
        Subtitle lines start and end times (not synchronized), sorted.
    speech: list of (float, float)
        Speech start and end times, see `loadSpeech`.
    scaleRange: float, optional
        Speeds searched around `a` (default `refineScaleRange`, or
        `refineScaleWide` for a short video).

    Returns
    -------
    tuple of (float, float) or None
        Polished a and b, or `None` when speech does not confirm the formula:
        best overlap is elsewhere, or at the edge of the searched range.
    """
    import numpy as np

    if not subs or not speech:
        return None

    step = refineStep
    near = int(round(refineOffsetRange / step))
    wide = int(round(refineWideRange / step))

    length = int(max(speech[-1][1], a * subs[-1][1] + b) / step) + 1
    size = 1 << (length + 2 * wide).bit_length()

    voice = np.zeros(size, dtype=np.float32)
    for start, end in speech:
        voice[int(round(start / step)):int(round(end / step))] = 1.0
    # subtitle shown over silence costs as much as shown over speech gains
    voice[:length] -= voice[:length].mean()
    voiceFft = np.fft.rfft(voice)

    def overlaps(scale):
        ''' Overlap of speech with subtitles moved by -wide .. +wide steps. '''
        shown = np.zeros(size, dtype=np.float32)
        for start, end in subs:
            i = int(round((scale * start + b) / step))
            j = int(round((scale * end + b) / step))
            if j > 0 and i < length:
                shown[max(i, 0):min(j, length)] = 1.0
        res = np.fft.irfft(voiceFft * np.conj(np.fft.rfft(shown)), size)
        return np.concatenate((res[-wide:], res[:wide + 1]))

    def best(scale):
        res = overlaps(scale)
        pos = wide - near + int(np.argmax(res[wide - near:wide + near + 1]))
        return float(res[pos]), scale, pos - wide, float(res.max())

    # coarse to fine search of the speed
    scaleRange = scaleRange or (refineScaleWide if isShort(subs) else refineScaleRange)
    top = None
    width = scaleRange
    # the wide search refines more, to reach the same final step
    for count in (10, 4, 4) if scaleRange <= refineScaleRange else (10, 4, 4, 4, 4):
        center = top[1] if top else a
        for no in range(-count, count + 1):
            res = best(center + no * width / count)
            if top is None or res[0] > top[0]:
                top = res
        width /= count

    logger.info('speech overlap: best for %.6fx%+.3f, words gave %.6fx%+.3f',
            top[1], b + top[2] * step, a, b)

    if scaleRange > refineScaleRange:
        # far from the words' speed: only a frame rate conversion is believed
        ratio = min(frameRatios(), key=lambda r: abs(r - top[1]))
        if abs(ratio - top[1]) > refineScaleRange * ratio:
            logger.info('speed %.6f is not a frame rate conversion, not confirmed', top[1])
            return None
        top = best(ratio)
        logger.info('speed set to frame rate conversion %.6f, offset %+.3f',
                ratio, b + top[2] * step)

    score, scale, shift, widest = top

    if score <= 0.0:
        logger.info('subtitles do not overlap speech, not confirmed')
        return None
    if widest > score * 1.0001:
        logger.info('speech overlap is better far from this formula, not confirmed')
        return None
    if abs(shift) >= near:
        logger.info('speech overlap is best at the edge of searched offsets, not confirmed')
        return None
    if abs(scale - a) >= scaleRange * 0.999:
        logger.info('speech overlap is best at the edge of searched speeds, not confirmed')
        return None
    return scale, b + shift * step


def frameRatios():
    """Speeds of subtitles made for one of `frameRates` shown at another."""
    return sorted(set(round(x / y, 9) for x in frameRates for y in frameRates))


def _words(text, minLen, ngrams=None):
    """Words of a subtitle or transcript line, as a set.

    Languages written without spaces (Japanese, Chinese) would give whole
    phrases as words, which never match differently worded lines; for them
    `ngrams` splits text to overlapping groups of that many letters, like
    SubSync's own matching does (see `ngrams` in subsync/data/languages.py).
    """
    import re
    text = re.sub(r'\{[^}]*\}|\\[Nnh]|<[^>]*>', ' ', text.lower())
    tokens = re.findall(r'[^\W\d_]+', text)
    if ngrams:
        return set(token[i:i + ngrams] for token in tokens
                for i in range(len(token) + 1 - ngrams))
    return set(w for w in tokens if len(w) >= minLen)


def checkChunks(subs, chunks, a, b, minWordLen=5, ngrams=None):
    """Check that every transcribed chunk agrees with synchronization formula.

    Speech overlap (see `refineFormula`) looks at the whole file at once, so
    subtitles that fit one formula only in part of the movie (e.g. made for a
    different cut) could still pass it. Here words of transcript lines are
    matched with nearby subtitle lines, separately in every chunk. When the
    formula is right, time differences of the matches cluster around zero.
    A transcript line is measured against the time its subtitle line is
    shown: starting anywhere in it is on time (Whisper may split one
    subtitle line in pieces), before or after it is that far off. Matches
    are counted by subtitle line, so the pieces of one line count once.

    Parameters
    ----------
    subs: list of (float, float, str)
        Subtitle lines start, end and text (not synchronized).
    chunks: list of list of (float, float, str)
        Transcript lines of every transcribed chunk.
    ngrams: int, optional
        Match groups of this many letters instead of words, for languages
        written without spaces (see `_words`).

    Returns
    -------
    bool
        `True` when no chunk disagrees and at least `checkMinChunks` agree.
        In a short video (see `isShort`), chunks with too few matches on
        their own are judged together too.
    """
    import bisect

    subWords = sorted((a * start + b, a * min(end, start + checkSpanMax) + b,
            _words(text, minWordLen, ngrams)) for start, end, text in subs)
    subTimes = [ x[0] for x in subWords ]

    def difference(time, begin, end):
        # transcript line start against the span its subtitle line is shown
        if time < begin:
            return time - begin
        return max(0.0, time - end)
    agree, disagree = 0, 0
    pool = [ 0, 0 ] if isShort(subs) else None

    for no, lines in enumerate(chunks):
        # chunk with few lines isn't judged on its own, in a short video its
        # matches are still judged together with other such chunks
        few = len(lines) < checkMinLines
        if few and pool is None:
            continue

        # (difference, subtitle line(s) matched) of every matched transcript line
        diffs = []
        for start, _, text in lines:
            words = _words(text, minWordLen, ngrams)
            if not words:
                continue
            lo = bisect.bisect_left(subTimes, start - checkWindow)
            hi = bisect.bisect_right(subTimes, start + checkWindow)
            # subtitle line sharing the most words; skipped when ambiguous
            # (words repeated in many lines, e.g. names, would match anywhere)
            best, found, matched = 0, [], []
            for k, (begin, end, sw) in enumerate(subWords[lo:hi], lo):
                shared = len(words & sw)
                if shared > best:
                    best, found, matched = shared, [ difference(start, begin, end) ], [ k ]
                elif shared and shared == best:
                    found.append(difference(start, begin, end))
                    matched.append(k)
            if found and max(found) - min(found) <= 2 * checkTolerance:
                diffs.append((sum(found) / len(found), tuple(matched)))

        # matches are counted by subtitle line: Whisper may split one line in
        # pieces, and those are one piece of evidence, not several
        near = len(set(k for d, k in diffs if abs(d) <= checkTolerance))
        # biggest cluster of differences elsewhere
        others = sorted((d, k) for d, k in diffs if abs(d) > checkTolerance)
        other, j = 0, 0
        for i in range(len(others)):
            while others[i][0] - others[j][0] > 2 * checkTolerance:
                j += 1
            other = max(other, len(set(k for _d, k in others[j:i + 1])))

        # chunk with too few matches has no opinion, it disagrees only when
        # its matches clearly point elsewhere
        if few:
            verdict = 'too few lines'
        elif near >= checkMinMatches and near > other:
            verdict = 'agrees'
            agree += 1
        elif other >= checkMinMatches and other >= near:
            verdict = 'DISAGREES'
            disagree += 1
        else:
            verdict = 'too few matches'
        logger.info('chunk check: %i lines, %i matches agree, %i in another cluster: %s',
                len(lines), near, other, verdict)

        # pooled, they can only agree: like a single chunk with too few
        # matches, they have no opinion against the formula (a few lines
        # merged differently by Whisper would block it), only chunks with
        # enough matches of their own disagree
        if pool is not None and verdict in ('too few matches', 'too few lines'):
            pool[0] += near
            pool[1] += other
            if pool[0] >= checkMinMatches and pool[0] > pool[1]:
                logger.info('chunk check: chunks with too few matches together: '
                        '%i matches agree, %i in another cluster: agree', pool[0], pool[1])
                agree += 1
                pool = [ 0, 0 ]

    return disagree == 0 and agree >= checkMinChunks


REGIONS_AGREE, REGIONS_DISAGREE, REGIONS_INCONCLUSIVE = 'agree', 'disagree', 'inconclusive'


def checkRegions(subs, speech, a, b):
    """`True` unless a region clearly fits speech elsewhere (see
    `regionVerdict`): a veto, which no region being judged doesn't give."""
    return regionVerdict(subs, speech, a, b) != REGIONS_DISAGREE


def regionVerdict(subs, speech, a, b):
    """Check that subtitles fit detected speech with the formula in every
    region of the movie, not only on the whole.

    Transcribed chunks cover only a part of the movie, they could all fall on
    one side of a place where subtitles stop fitting the formula (e.g. made for
    a different cut). Speech is detected in the whole file, so here subtitles
    of every region of about `regionLength` seconds are moved against speech,
    and the best fit must be where the formula puts them.

    Parameters
    ----------
    subs: list of (float, float)
        Subtitle lines start and end times (not synchronized).
    speech: list of (float, float)
        Speech start and end times, see `loadSpeech`.

    Returns
    -------
    str
        `REGIONS_DISAGREE` when a region clearly fits speech elsewhere,
        `REGIONS_AGREE` when at least one region fits where the formula puts
        it and none elsewhere, `REGIONS_INCONCLUSIVE` when no region could be
        judged (all with fewer than `regionMinLines` lines, as in a very
        short video) or none fits clearly: then the regions confirm nothing.
    """
    import numpy as np

    if not subs or not speech:
        return REGIONS_DISAGREE

    step = refineStep
    search = int(round(regionSearch / step))
    tol = int(round(regionTolerance / step))

    lines = sorted((a * start + b, a * end + b) for start, end in subs)
    first, last = lines[0][0], lines[-1][0]
    count = max(int(round((last - first) / regionLength)), 1)
    width = (last - first) / count

    voiceAll = np.zeros(int(speech[-1][1] / step) + 1, dtype=np.float32)
    for start, end in speech:
        voiceAll[int(round(start / step)):int(round(end / step))] = 1.0
    mean = float(voiceAll.mean())

    disagree, agree = 0, 0
    for no in range(count):
        lo = first + no * width
        hi = lo + width if no + 1 < count else last + 1.0
        region = [ l for l in lines if lo <= l[0] < hi ]
        if len(region) < regionMinLines:
            logger.info('region check %s - %s: %i lines, not judged',
                    formatTime(lo)[:8], formatTime(hi)[:8], len(region))
            continue

        # speech around the region, with margin for moving subtitles
        origin = lo - regionSearch - 10.0
        length = int((hi - lo + 2 * regionSearch + 20.0) / step) + 1
        size = 1 << (length + 2 * search).bit_length()

        voice = np.zeros(size, dtype=np.float32)
        i0 = int(round(origin / step))
        src = voiceAll[max(i0, 0):max(i0 + length, 0)]
        if len(src):
            dst = max(-i0, 0)
            voice[dst:dst + len(src)] = src
        voice[:length] -= mean

        shown = np.zeros(size, dtype=np.float32)
        for start, end in region:
            shown[int(round((start - origin) / step)):int(round((end - origin) / step))] = 1.0

        res = np.fft.irfft(np.fft.rfft(voice) * np.conj(np.fft.rfft(shown)), size)
        res = np.concatenate((res[-search:], res[:search + 1]))
        pos = int(np.argmax(res))
        best, shift = float(res[pos]), (pos - search) * step
        here = float(res[search - tol:search + tol + 1].max())

        if abs(pos - search) <= tol:
            verdict = 'agrees'
            agree += 1
        elif best > 0.0 and (here <= 0.0 or best > regionMargin * here):
            verdict = 'DISAGREES'
            disagree += 1
        else:
            verdict = 'unclear'
        logger.info('region check %s - %s: %i lines, best fit %+.2f s: %s',
                formatTime(lo)[:8], formatTime(hi)[:8], len(region), shift, verdict)

    if disagree:
        return REGIONS_DISAGREE
    if not agree:
        logger.info('region check: no region agrees or disagrees, it confirms nothing')
        return REGIONS_INCONCLUSIVE
    return REGIONS_AGREE


def _regionOffsets(lines, speech, search):
    """Best offset (seconds) of every region's subtitle lines against speech,
    searched +-search seconds; lines are synchronized (start, end) times.
    Regions with fewer than `regionMinLines` lines are skipped."""
    import numpy as np

    step = refineStep
    width = int(round(search / step))
    voiceAll = np.zeros(int(speech[-1][1] / step) + 1, dtype=np.float32)
    for start, end in speech:
        voiceAll[int(round(start / step)):int(round(end / step))] = 1.0
    mean = float(voiceAll.mean())

    first, last = lines[0][0], lines[-1][0]
    count = max(int(round((last - first) / regionLength)), 1)
    span = (last - first) / count
    res = []
    for no in range(count):
        lo = first + no * span
        hi = lo + span if no + 1 < count else last + 1.0
        region = [ l for l in lines if lo <= l[0] < hi ]
        if len(region) < regionMinLines:
            continue
        origin = lo - search - 10.0
        length = int((hi - lo + 2 * search + 20.0) / step) + 1
        size = 1 << (length + 2 * width).bit_length()
        voice = np.zeros(size, dtype=np.float32)
        i0 = int(round(origin / step))
        src = voiceAll[max(i0, 0):max(i0 + length, 0)]
        if len(src):
            voice[max(-i0, 0):max(-i0, 0) + len(src)] = src
        voice[:length] -= mean
        shown = np.zeros(size, dtype=np.float32)
        for start, end in region:
            shown[int(round((start - origin) / step)):int(round((end - origin) / step))] = 1.0
        corr = np.fft.irfft(np.fft.rfft(voice) * np.conj(np.fft.rfft(shown)), size)
        corr = np.concatenate((corr[-width:], corr[:width + 1]))
        pos = int(np.argmax(corr))
        # best fit counts only when it is clearly better than any other one
        # (more than 2 regionTolerance away), searching far finds coincidences
        guard = int(round(2 * regionTolerance / step))
        rest = np.concatenate((corr[:max(pos - guard, 0)], corr[pos + guard + 1:]))
        second = float(rest.max()) if len(rest) else 0.0
        if corr[pos] > 0.0 and corr[pos] > regionMargin * max(second, 0.0):
            res.append((lo, hi, len(region), (pos - width) * step))
        else:
            logger.info('piecewise: region %s - %s, %i lines, no clear fit',
                    formatTime(lo)[:8], formatTime(hi)[:8], len(region))
    return res


def alignPiecewise(subs, speech, a, b):
    """Synchronize subtitles piecewise: lines get one of a few offsets.

    For subtitles made for a different cut of the movie, one formula cannot
    fit the whole movie. Speed (a) stays the same, but the offset changes
    where scenes were added or removed.

    First every region of the movie (see `checkRegions`) finds the offset
    where its subtitles fit detected speech best, searched up to
    `piecewiseRange` seconds; a region holds many lines, so that is reliable.
    So does every window of `piecewiseWindow` seconds sliding over the
    subtitles, for cuts that move only a part of a region. These offsets (and
    the formula's own) are the only candidates. Then every
    subtitle line picks one of them by dynamic programming, maximizing overlap
    with speech, with a penalty for every change of the offset between
    consecutive lines. Finally every piece is fine tuned.

    Parameters
    ----------
    subs: list of (float, float)
        Subtitle lines start and end times (not synchronized), sorted.
    speech: list of (float, float)
        Speech start and end times, see `loadSpeech`.
    a, b: float
        Formula found so far.

    Returns
    -------
    list of float or None
        Offset of every line (synchronized time = a * time + offset), `None`
        when there is nothing to align.
    """
    import numpy as np

    if not subs or not speech:
        return None

    mapped = [ (a * start + b, a * end + b) for start, end in subs ]
    regions = _regionOffsets(mapped, speech, piecewiseRange)

    # candidate offsets: the formula's and those of the regions, merged when
    # closer than regionTolerance
    # and of shorter windows sliding over the subtitles (see piecewiseWindow),
    # when two neighbouring windows fit at the same offset: a short window
    # sometimes fits speech far away by chance, which its neighbour doesn't
    first, last = mapped[0][0], mapped[-1][0]
    at, previous = first, None
    while at < last:
        window = [ l for l in mapped if at <= l[0] < at + piecewiseWindow ]
        fit = _regionOffsets(window, speech, piecewiseRange) if window else []
        fit = fit[0] if fit else None
        if fit and previous and abs(fit[3] - previous[3]) <= regionTolerance:
            regions.append((previous[0], fit[1], previous[2] + fit[2], (fit[3] + previous[3]) / 2))
        previous = fit
        at += piecewiseWindow / 2
    candidates = [ 0.0 ]
    for lo, hi, count, shift in regions:
        logger.info('piecewise: region %s - %s, %i lines, fits speech at %+.2f s',
                formatTime(lo)[:8], formatTime(hi)[:8], count, shift)
        if all(abs(shift - c) > regionTolerance for c in candidates):
            candidates.append(shift)

    fine = refineStep
    end = max(speech[-1][1], mapped[-1][1]) + piecewiseRange + 10.0
    voice = np.zeros(int(end / fine) + 1, dtype=np.float32)
    for start, stop in speech:
        voice[int(round(start / fine)):int(round(stop / fine))] = 1.0
    mean = float(voice[:int(speech[-1][1] / fine)].mean())
    cum = np.concatenate(([0.0], np.cumsum(voice, dtype=np.float64))) * fine
    lastIdx = len(cum) - 1

    def overlap(start, stop, shift):
        i0 = min(max(int(round((start + shift) / fine)), 0), lastIdx)
        i1 = min(max(int(round((stop + shift) / fine)), 0), lastIdx)
        return cum[i1] - cum[i0] - mean * (stop - start)

    # dynamic programming over lines and candidate offsets
    count = len(candidates)
    best = np.array([ overlap(mapped[0][0], mapped[0][1], c) for c in candidates ])
    choice = np.zeros((len(mapped), count), dtype=np.int64)
    choice[0] = np.arange(count)
    for no in range(1, len(mapped)):
        top = int(np.argmax(best))
        jump = best[top] - piecewiseSplitCost
        choice[no] = np.where(jump > best, top, np.arange(count))
        best = np.maximum(best, jump) + np.array(
                [ overlap(mapped[no][0], mapped[no][1], c) for c in candidates ])

    ks = np.zeros(len(mapped), dtype=np.int64)
    k = int(np.argmax(best))
    for no in range(len(mapped) - 1, -1, -1):
        ks[no] = k
        k = int(choice[no][k])

    # fine tune every piece (run of lines with the same offset)
    pieces, first = [], 0
    for no in range(1, len(mapped) + 1):
        if no == len(mapped) or ks[no] != ks[first]:
            pieces.append((first, no))
            first = no

    width = int(round(piecewiseFineRange / fine))
    fineSteps = np.arange(-width, width + 1)
    offsets = [ 0.0 ] * len(mapped)
    for first, last in pieces:
        shift = candidates[int(ks[first])]
        total = np.zeros(len(fineSteps))
        for start, stop in mapped[first:last]:
            i0 = np.clip(int(round((start + shift) / fine)) + fineSteps, 0, lastIdx)
            i1 = np.clip(int(round((stop + shift) / fine)) + fineSteps, 0, lastIdx)
            total += cum[i1] - cum[i0]
        shift += fineSteps[int(np.argmax(total))] * fine
        for no in range(first, last):
            offsets[no] = b + shift
        logger.info('piecewise: piece %s - %s, %i lines, offset %+.3f s',
                formatTime(mapped[first][0] + shift)[:8],
                formatTime(mapped[last - 1][0] + shift)[:8], last - first, b + shift)

    return offsets


def _similarity(a, b):
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def pairLines(subs, lines, minWordLen=None, ngrams=None):
    """Pairs of subtitle and transcript lines saying the same (see
    `sparseMinSim`), in order of both: the pairing with the highest total
    similarity in which no two pairs cross.

    subs and lines are lists of (start, end, text) tuples, sorted by start.

    Returns
    -------
    list of (int, int)
        Index of the subtitle line and of the transcript line.
    """
    minWordLen = sparseWordLen if minWordLen is None else minWordLen
    subWords = [ _words(s[2], minWordLen, ngrams) for s in subs ]
    lineWords = [ _words(l[2], minWordLen, ngrams) for l in lines ]
    n, m = len(subs), len(lines)
    score = [ [ 0.0 ] * (m + 1) for _ in range(n + 1) ]
    for i in range(1, n + 1):
        row, prev = score[i], score[i - 1]
        for j in range(1, m + 1):
            best = max(prev[j], row[j - 1])
            sim = _similarity(subWords[i - 1], lineWords[j - 1])
            if sim >= sparseMinSim and prev[j - 1] + sim > best:
                best = prev[j - 1] + sim
            row[j] = best

    pairs = []
    i, j = n, m
    while i and j:
        if score[i][j] == score[i - 1][j]:
            i -= 1
        elif score[i][j] == score[i][j - 1]:
            j -= 1
        else:
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
    return pairs[::-1]


def _median(values):
    values = sorted(values)
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def sparseFit(subs, lines, minWordLen=None, ngrams=None):
    """Synchronization formula from paired lines, for films with very
    little dialogue (see `sparseMaxLines`).

    subs are subtitle lines and lines transcript lines timed by their words
    (see `transcribeWords`), both lists of (start, end, text) tuples.

    Returns
    -------
    tuple of (float, float, list) or None
        a and b of the formula (film time = a * subtitle time + b) and the
        (subtitle start, transcript start) pairs that agree with it; `None`
        when the pairs don't make one clear answer.
    """
    pairs = [ (subs[i][0], lines[j][0]) for i, j in pairLines(subs, lines, minWordLen, ngrams) ]
    if len(pairs) < sparseMinLines:
        logger.info('sparse dialogue: %i lines paired, too few', len(pairs))
        return None

    fits, seen = [], set()
    for a in frameRatios():
        for s, w in pairs:
            agree = tuple(p for p in pairs if abs(p[1] - a * p[0] - (w - a * s)) <= sparseTolerance)
            if len(agree) < 2 or (a, agree) in seen:
                continue
            seen.add((a, agree))
            b = _median([ w2 - a * s2 for s2, w2 in agree ])
            error = sum(abs(w2 - a * s2 - b) for s2, w2 in agree)
            fits.append((len(agree), -error, a, b, list(agree)))
    if not fits:
        logger.info('sparse dialogue: %i lines paired, no two agree', len(pairs))
        return None

    fits.sort(key=lambda f: f[:2], reverse=True)
    count, _error, a, b, agree = fits[0]
    span = agree[-1][0] - agree[0][0]
    logger.info('sparse dialogue: %i of %i paired lines agree on %.6fx%+.3f over %.0f s',
            count, len(pairs), a, b, span)
    if count < sparseMinLines or count < sparseMinShare * len(pairs) or span < sparseMinSpan:
        logger.info('sparse dialogue: too little agreement')
        return None

    first, last = min(s[0] for s in subs), max(s[0] for s in subs)
    tied = [ (a, b, agree) ]
    for count2, _e, a2, b2, agree2 in fits[1:]:
        if count2 < count:
            break
        if max(abs((a - a2) * t + b - b2) for t in (first, last)) > 2 * sparseTolerance:
            logger.info('sparse dialogue: %.6fx%+.3f fits as many lines, no clear answer', a2, b2)
            return None
        if all(a2 != t[0] for t in tied):
            tied.append((a2, b2, agree2))
    a, b, agree = sparseSpeed(subs, lines, tied)

    # the pairs left out must not agree among themselves on another offset:
    # that's what subtitles of a different cut look like, the lines after a
    # scene added or removed (single stray pairs are mismatched lines)
    rest = [ p for p in pairs if p not in agree ]
    for s, w in rest:
        other = w - a * s
        group = [ p for p in rest if abs(p[1] - a * p[0] - other) <= sparseTolerance ]
        if len(group) >= sparseCutLines and abs(other - b) > 2 * sparseTolerance:
            logger.info('sparse dialogue: %i other paired lines agree on %+.1f s more, the '
                    'subtitles may be for a different cut', len(group), other - b)
            return None
    return sparseRefine(subs, lines, a, b, agree)


def _sparseNear(subs, lines, a, b):
    """(subtitle start, transcript start) for every subtitle line with exactly
    one transcript line starting within `sparseTolerance` of where the formula
    puts it (the next one at least `leadClear` farther)."""
    starts = sorted(l[0] for l in lines)
    near = []
    for s in subs:
        at = a * s[0] + b
        found = sorted((abs(w - at), w) for w in starts if abs(w - at) <= sparseTolerance)
        if found and (len(found) == 1 or found[1][0] - found[0][0] >= leadClear):
            near.append((s[0], found[0][1]))
    return near


def sparseSpeed(subs, lines, tied):
    """Choice between frame-rate speeds that fit the same number of paired
    lines and stay within 2 * `sparseTolerance` of each other over the film,
    tied: list of (a, b, agree), best paired fit first.

    Speeds next to each other differ by 0.1% (25/24 and 25/23.976), 0.3 s over
    Sintel's 5 minutes of lines, so a few paired lines can fit both, and
    Whisper's word times decide between them by chance (Sintel's Chinese
    subtitles got the wrong one on one computer, lines up to 0.34 s off). The
    speed is measured on every line `sparseRefine` uses, more than the paired
    ones, by a straight-line fit, and the tied speed closest to it is kept.
    With fewer than `sparseMinLines` such lines the best paired fit is kept.
    """
    if len(tied) < 2:
        return tied[0]
    a, b, _agree = tied[0]
    near = _sparseNear(subs, lines, a, b)
    if len(near) < sparseMinLines:
        return tied[0]
    ms = sum(s for s, _w in near) / len(near)
    mw = sum(w for _s, w in near) / len(near)
    var = sum((s - ms) ** 2 for s, _w in near)
    if var <= 0:
        return tied[0]
    slope = sum((s - ms) * (w - mw) for s, w in near) / var
    best = min(tied, key=lambda t: abs(t[0] - slope))
    if best[0] != a:
        logger.info('sparse dialogue: %i lines measure speed %.6f, so %.6fx rather than %.6fx',
                len(near), slope, best[0], a)
    return best


def sparseRefine(subs, lines, a, b, agree):
    """Offset measured on every subtitle line with exactly one transcript
    line near where the formula puts it (see `_sparseNear`), when there are at
    least `sparseMinLines`; otherwise the result of `sparseFit` is kept."""
    near = _sparseNear(subs, lines, a, b)
    if len(near) < sparseMinLines:
        return a, b, agree
    refined = _median([ w - a * s for s, w in near ])
    logger.info('sparse dialogue: offset %+.3f measured on %i lines, was %+.3f from %i',
            refined, len(near), b, len(agree))
    return a, refined, near


def sparseShift(agree, speech, target=None):
    """Shift (seconds) making lines synchronized by `sparseFit` start
    `target` seconds before speech. They start where Whisper's first word
    does, which is a little early (about 0.35 s in Sintel): the speech start
    detected nearest to each of those words (within `leadReach`) gives the
    difference, when at least `sparseMinOnsets` are found."""
    target = leadTarget if target is None else target
    onsets = [ start for start, end in speech or [] ]
    diffs = []
    for _sub, word in agree:
        near = [ o - word for o in onsets if abs(o - word) <= leadReach ]
        if near:
            diffs.append(min(near, key=abs))
    late = _median(diffs) if len(diffs) >= sparseMinOnsets else 0.0
    logger.info('sparse dialogue: speech starts %+.3f s from the first words (%i measured), '
            'target lead %.2f s', late, len(diffs), target)
    return late - target


def sparseWindows(lines, duration=None):
    """Audio ranges around transcript lines (see `sparseMargin`), joined
    where they overlap."""
    ranges = []
    for start, end, _text in sorted(lines):
        start, end = max(start - sparseMargin, 0.0), end + sparseMargin
        if duration:
            end = min(end, duration)
        if ranges and start <= ranges[-1][1]:
            ranges[-1][1] = max(ranges[-1][1], end)
        else:
            ranges.append([ start, end ])
    return [ (round(s, 3), round(e, 3)) for s, e in ranges ]


def measureLead(lines, speech):
    """How long before speech subtitle lines start, see `leadShift`.

    Returns
    -------
    tuple of (float, int) or None
        Median lead (seconds, positive when lines start before speech) and
        the number of lines measured, `None` when no line could be measured.
    """
    import bisect

    onsets = sorted(start for start, end in speech)
    leads = []
    lines = sorted(lines)
    for i, (start, end) in enumerate(lines):
        # lines right after another line often start in the middle of speech
        if i and start - lines[i - 1][1] < leadGap:
            continue
        lo = bisect.bisect_left(onsets, start - leadReach)
        hi = bisect.bisect_right(onsets, start + leadReach)
        near = sorted((abs(onset - start), onset - start) for onset in onsets[lo:hi])
        if not near:
            continue
        second = near[1][0] if len(near) > 1 else 2 * leadReach
        if second - near[0][0] >= leadClear:
            leads.append(near[0][1])

    if not leads:
        return None
    leads.sort()
    mid = len(leads) // 2
    median = leads[mid] if len(leads) % 2 else (leads[mid - 1] + leads[mid]) / 2
    return median, len(leads)


def leadShift(lines, speech, target=None):
    """Shift (seconds) that makes synchronized subtitle lines start `target`
    seconds before speech (default `leadTarget`), as correct subtitles do.

    Synchronization fits subtitle lines over speech, which leaves them a
    little late (about 0.1 s on average). Returns 0 when there is too little
    evidence or the shift would be implausibly large.
    """
    res = measureLead(lines, speech)
    if not res or res[1] < leadMinLines:
        logger.info('speech start lead: too few lines measured (%s)', res)
        return 0.0
    target = leadTarget if target is None else target
    shift = res[0] - target
    logger.info('speech start lead: lines start %.3f s before speech (%i lines), '
            'target %.2f s, shift %+.3f s', res[0], res[1], target, shift)
    if abs(shift) > leadMaxShift:
        logger.info('speech start lead: shift too large, not applied')
        return 0.0
    return shift


def writeSrt(path, lines):
    tmpPath = path + '.part'
    try:
        with open(tmpPath, 'w', encoding='utf-8', newline='\n') as fp:
            for no, (start, end, text) in enumerate(lines, 1):
                fp.write('{}\n{} --> {}\n{}\n\n'.format(no,
                    formatTime(start), formatTime(end), text))
        os.replace(tmpPath, path)
    finally:
        if os.path.exists(tmpPath):
            os.remove(tmpPath)


def readSrt(path):
    lines = []
    with open(path, encoding='utf-8') as fp:
        for block in fp.read().split('\n\n'):
            rows = block.strip().split('\n')
            if len(rows) >= 3 and ' --> ' in rows[1]:
                start, end = rows[1].split(' --> ')
                lines.append((parseTime(start), parseTime(end), ' '.join(rows[2:])))
    return lines


def transcribeChunks(path, outDir, lang, streamNo=None, model=None,
        translate=False, order='spread', runCb=None, progressCb=None,
        chunkCb=None, planCb=None, detectSpeech=True, channels=None):
    """Transcribe audio to SRT chunks `chunk-NNN.srt` in `outDir`.

    Chunks already present (e.g. from previous run) are not transcribed again.

    Parameters
    ----------
    lang: str
        Whisper language code, e.g. 'ja'.
    channels: list of str, optional
        Audio channels listened to (see `_Mixer`), all when `None`.
    order: str, optional
        'spread' (see `spreadOrder`) or 'sequential'.
    runCb: callable, optional
        Polled during processing, transcription is cancelled (raising
        `Terminated`) when it returns `False`.
    progressCb: callable, optional
        Called with transcribed and total length, in seconds.
    chunkCb: callable, optional
        Called with chunk number and path when chunk is ready, transcription
        stops when it returns `True`.
    planCb: callable, optional
        Called with list of chunks (start, end) times before transcription.
    detectSpeech: bool, optional
        Detect speech in the whole stream too (see `loadSpeech`).

    Returns
    -------
    bool
        `True` if all chunks were transcribed, `False` if stopped by `chunkCb`.
    """
    os.makedirs(outDir, exist_ok=True)
    chunks = loadPlan(outDir)
    if chunks and len(chunks) < chunkCount(chunks[-1][1]):
        # planned by an older version, which split short videos to fewer chunks
        logger.info('chunk plan is outdated, planning again')
        for no in range(len(chunks)):
            if os.path.isfile(getChunkPath(outDir, no)):
                os.remove(getChunkPath(outDir, no))
        chunks = None
    if chunks is None or (detectSpeech and loadSpeech(outDir) is None):
        logger.info('splitting audio to chunks%s', ', detecting speech' if detectSpeech else '')
        speech = [] if detectSpeech else None
        planned = planChunks(path, streamNo, runCb, speech=speech, channels=channels)
        if chunks is None:      # keep plan of chunks already transcribed
            chunks = planned
        _savePlan(outDir, chunks, speech)

    total = chunks[-1][1] if chunks else 0.0
    logger.info('audio split to %i chunks, %s total', len(chunks), formatTime(total))
    if planCb:
        planCb(chunks)

    indices = spreadOrder(len(chunks)) if order == 'spread' else range(len(chunks))
    whisper, done = None, 0.0

    for no in indices:
        start, end = chunks[no]
        chunkPath = getChunkPath(outDir, no)

        if not os.path.isfile(chunkPath):
            if whisper is None:
                whisper = loadModel(model)

            def chunkProgress(pos):
                if progressCb:
                    progressCb(done + min(max(pos - start, 0.0), end - start), total)

            logger.info('transcribing chunk %i/%i, %s - %s', no + 1, len(chunks),
                    formatTime(start), formatTime(end))
            lines = transcribeRange(whisper, path, streamNo, start, end, lang,
                    translate=translate, runCb=runCb, progressCb=chunkProgress,
                    channels=channels)
            writeSrt(chunkPath, lines)

        done += end - start
        if progressCb:
            progressCb(done, total)
        if chunkCb and chunkCb(no, chunkPath):
            return False

    return True


def transcribe(path, outPath, lang, streamNo=None, model=None, runCb=None,
        progressCb=None, translate=False, channels=None):
    """Transcribe audio from file `path` to single SRT file `outPath`.

    Returns
    -------
    int
        Number of subtitle lines written.
    """
    with tempfile.TemporaryDirectory(prefix='subsync-') as tmpDir:
        transcribeChunks(path, tmpDir, lang, streamNo=streamNo, model=model,
                translate=translate, order='sequential', runCb=runCb,
                progressCb=progressCb, detectSpeech=False, channels=channels)
        lines = []
        for no in range(len(loadPlan(tmpDir) or [])):
            lines += readSrt(getChunkPath(tmpDir, no))

    writeSrt(outPath, lines)
    logger.info('transcription done, %i lines written to %s', len(lines), outPath)
    return len(lines)


# --- running from SubSync --------------------------------------------------

def findPython():
    """Find Python interpreter with faster-whisper installed.

    SubSync itself may run under Python too old for faster-whisper, in such
    case transcription is run in a separate process, with interpreter set by
    SUBSYNC_WHISPER_PYTHON or installed in `.whisper` directory next to the
    sources.
    """
    path = os.environ.get('SUBSYNC_WHISPER_PYTHON')
    if path:
        return path if os.path.isfile(path) else None

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for sub in (('Scripts', 'python.exe'), ('bin', 'python')):
        path = os.path.join(root, '.whisper', *sub)
        if os.path.isfile(path):
            return path


# why faster-whisper can't be imported here, see `availability`
importError = None


def _hasModule():
    global importError
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError as err:
        importError = repr(err)
        logger.debug('faster-whisper not in this process: %s', importError)
        return False


def availability():
    """How Whisper can be used here, for --version and bug reports."""
    if _hasModule():
        return 'available'
    python = findPython()
    if python:
        return 'available through {}'.format(python)
    return 'not available ({})'.format(importError)


def _transcribeExternal(python, path, outDir, lang, streamNo=None, model=None,
        translate=False, runCb=None, progressCb=None, chunkCb=None, planCb=None,
        channels=None):
    """Run `transcribeChunks` in a separate Python process."""
    import subprocess
    import threading

    cmd = [ python, os.path.abspath(__file__), path, '--chunks-dir', outDir,
            '-l', lang, '--machine' ]
    if model:
        cmd += [ '-m', model ]
    if streamNo is not None:
        cmd += [ '-s', str(streamNo + 1) ]
    if channels:
        cmd += [ '--channels', ','.join(channels) ]
    if translate:
        cmd += [ '--translate' ]

    logger.info('running transcription: %s', ' '.join(cmd))
    flags = 0x08000000 if sys.platform == 'win32' else 0  # no console window
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, creationflags=flags, env=env)

    state = { 'stop': False, 'error': None, 'complete': False }
    errors = []

    def reader():
        for raw in proc.stderr:
            line = raw.decode('utf-8', 'replace').strip()
            cmd, _, args = line.partition(' ')
            try:
                if state['stop']:
                    pass
                elif cmd == 'progress':
                    if progressCb:
                        progressCb(*map(float, args.split()))
                elif cmd == 'plan':
                    if planCb:
                        planCb(loadPlan(outDir) or [])
                elif cmd == 'chunk':
                    no = int(args)
                    if chunkCb and chunkCb(no, getChunkPath(outDir, no)):
                        state['stop'] = True
                elif cmd == 'done':
                    state['complete'] = True
                elif line:
                    errors.append(line)
                    del errors[:-20]
            except Exception as err:
                state['error'] = err
                state['stop'] = True

    thread = threading.Thread(target=reader, name='TranscribeReader', daemon=True)
    thread.start()

    try:
        while True:
            try:
                proc.wait(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                if state['stop']:
                    break
                if runCb and not runCb():
                    raise Terminated()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
            # killed process had no chance to remove its partial output
            for name in os.listdir(outDir):
                if name.endswith('.part'):
                    os.remove(os.path.join(outDir, name))
        # chunks reported by the process may still be processed by chunkCb,
        # cached chunks are all reported at once, right before it exits
        while thread.is_alive():
            thread.join(timeout=0.5)
            if runCb and not runCb():
                state['stop'] = True

    if state['error']:
        raise state['error']
    if state['stop']:
        return False
    if proc.returncode != 0 or not state['complete']:
        raise RuntimeError('transcription process failed (code {}): {}'.format(
            proc.returncode, ' | '.join(errors[-5:])))
    return True


def getCacheDir(path, streamNo, lang, translate=False, model=None, channels=None):
    """Directory where transcript chunks of this audio stream are cached."""
    lang2 = whisperCode(lang)
    stat = os.stat(path)
    items = [ os.path.abspath(path), stat.st_size, stat.st_mtime_ns, streamNo,
        lang2, model or defaultModel(), 'translate' if translate else '',
        chunkLength, cacheVersion ]
    if channels:    # all channels keep the key they had before channels were chosen
        items.append(','.join(channels))
    key = '|'.join(str(x) for x in items)
    name = '{}.{}'.format(hashlib.sha1(key.encode('utf-8')).hexdigest()[:20],
            'en' if translate else lang2)
    return os.path.join(tempfile.gettempdir(), 'subsync-transcripts', name)


def planSpeech(path, outDir, streamNo=None, channels=None, runCb=None):
    """Detect speech in the whole stream (and plan chunks) without
    transcribing, kept in `outDir` like `transcribeChunks` keeps it."""
    os.makedirs(outDir, exist_ok=True)
    if loadSpeech(outDir) is None:
        logger.info('detecting speech')
        speech = []
        planned = planChunks(path, streamNo, runCb, speech=speech, channels=channels)
        _savePlan(outDir, loadPlan(outDir) or planned, speech)
    return loadSpeech(outDir)


def getSpeech(path, streamNo, lang, channels=None, runCb=None):
    """Speech (start, end) times in the whole audio stream, detected in this
    process or in separate Python (see `findPython`), cached with this
    stream's transcripts. `None` when speech can't be detected here.

    Used to polish what SubSync's original speech recognition found, the
    same way transcripts are (see `refineFormula`).
    """
    outDir = getCacheDir(path, streamNo, lang, False, None, channels)
    speech = loadSpeech(outDir)
    if speech is not None:
        return speech

    if _hasModule():
        return planSpeech(path, outDir, streamNo, channels, runCb)

    python = findPython()
    if not python:
        return None
    import subprocess
    cmd = [ python, os.path.abspath(__file__), path, '--chunks-dir', outDir, '--speech-only' ]
    if streamNo is not None:
        cmd += [ '-s', str(streamNo + 1) ]
    if channels:
        cmd += [ '--channels', ','.join(channels) ]
    logger.info('running speech detection: %s', ' '.join(cmd))
    flags = 0x08000000 if sys.platform == 'win32' else 0  # no console window
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=flags)
    try:
        while True:
            try:
                proc.wait(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                if runCb and not runCb():
                    raise Terminated()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    return loadSpeech(outDir)


def wordLinesPath(outDir, ranges):
    key = ','.join('{:.3f}-{:.3f}'.format(s, e) for s, e in ranges)
    # "words2": lines split into sentences (see wordLines)
    return os.path.join(outDir, 'words2-{}.srt'.format(
        hashlib.sha1(key.encode('utf-8')).hexdigest()[:12]))


def getWordLines(path, outDir, streamNo, lang, ranges, translate=False, model=None,
        channels=None, runCb=None):
    """Lines of `ranges` timed by their words (see `transcribeWords`),
    transcribed in this process or in separate Python (see `findPython`) and
    cached in `outDir`, the stream's transcript cache."""
    out = wordLinesPath(outDir, ranges)
    if os.path.isfile(out):
        return readSrt(out)
    lang2 = whisperCode(lang)
    os.makedirs(outDir, exist_ok=True)
    logger.info('transcribing %i ranges with word times, %s total', len(ranges),
            formatTime(sum(e - s for s, e in ranges)))

    if _hasModule():
        lines = transcribeWords(loadModel(model), path, streamNo, ranges, lang2,
                translate, runCb, channels)
        writeSrt(out, lines)
        return lines

    python = findPython()
    if not python:
        raise NotInstalled()
    import subprocess
    cmd = [ python, os.path.abspath(__file__), path, '--chunks-dir', outDir, '-l', lang2,
            '--words', ','.join('{:.3f}-{:.3f}'.format(s, e) for s, e in ranges) ]
    if model:
        cmd += [ '-m', model ]
    if streamNo is not None:
        cmd += [ '-s', str(streamNo + 1) ]
    if channels:
        cmd += [ '--channels', ','.join(channels) ]
    if translate:
        cmd += [ '--translate' ]
    logger.info('running transcription with word times: %s', ' '.join(cmd))
    flags = 0x08000000 if sys.platform == 'win32' else 0  # no console window
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, creationflags=flags, env=env)
    err = b''
    try:
        while True:
            try:
                _out, err = proc.communicate(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                if runCb and not runCb():
                    raise Terminated()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    if proc.returncode != 0 or not os.path.isfile(out):
        raise RuntimeError('transcription process failed (code {}): {}'.format(proc.returncode,
            ' | '.join(err.decode('utf-8', 'replace').strip().split('\n')[-5:])))
    return readSrt(out)


def getTranscriptChunks(path, streamNo, lang, translate=False, model=None,
        runCb=None, progressCb=None, chunkCb=None, planCb=None, channels=None):
    """Transcribe audio stream to cached SRT chunks, in this process or in
    separate Python (see `findPython`). See `transcribeChunks` for callbacks.

    Parameters
    ----------
    lang: str
        3-letter language code (see `supports`) or whisper language code.
    translate: bool, optional
        Get English translation of the speech instead of the transcript.
    channels: list of str, optional
        Audio channels listened to (see `_Mixer`), all when `None`.

    Returns
    -------
    bool
        `True` if all chunks were transcribed, `False` if stopped by `chunkCb`.
    """
    lang2 = whisperCode(lang)
    model = model or defaultModel()
    outDir = getCacheDir(path, streamNo, lang, translate, model, channels)
    os.makedirs(outDir, exist_ok=True)
    logger.info('transcript cache: %s', outDir)

    kw = dict(streamNo=streamNo, model=model, translate=translate, runCb=runCb,
            progressCb=progressCb, chunkCb=chunkCb, planCb=planCb, channels=channels)

    if _hasModule():
        return transcribeChunks(path, outDir, lang2, order='spread', **kw)

    python = findPython()
    if not python:
        raise NotInstalled()
    return _transcribeExternal(python, path, outDir, lang2, **kw)


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(
            description='Transcribe audio to an SRT file usable as SubSync reference.')
    parser.add_argument('input', help='video or audio file')
    parser.add_argument('-o', '--output',
            help='output SRT path (default: <input name>.whisper.<lang>.srt)')
    parser.add_argument('-l', '--lang', default='ja',
            help='spoken language, whisper code (default: ja)')
    parser.add_argument('-s', '--stream', type=int,
            help='1-based stream number (default: first audio stream)')
    parser.add_argument('-c', '--channels',
            help='audio channels to listen to, comma separated, e.g. FC (default: all)')
    parser.add_argument('-m', '--model', help='whisper model size or path '
            '(default: {})'.format(defaultModel()))
    parser.add_argument('-t', '--translate', action='store_true',
            help='write English translation of the speech instead of the transcript')
    parser.add_argument('--overwrite', action='store_true',
            help='overwrite existing output file')
    parser.add_argument('--chunks-dir',
            help='write chunks to this directory, in spread order (used by SubSync)')
    parser.add_argument('--machine', action='store_true',
            help='print progress in machine readable form')
    parser.add_argument('--detect-language', action='store_true',
            help='only print the spoken language (whisper code) and its probability')
    parser.add_argument('--speech-only', action='store_true',
            help='with --chunks-dir: only detect speech, without transcribing')
    parser.add_argument('--words', metavar='RANGES',
            help='with --chunks-dir: transcribe these ranges (start-end seconds, comma '
            'separated) with word times (used by SubSync for films with little dialogue)')
    args = parser.parse_args(argv)
    streamNo = None if args.stream is None else args.stream - 1
    channels = [ ch.strip().upper() for ch in args.channels.split(',') if ch.strip() ] \
            if args.channels else None

    def report(*items):
        sys.stderr.write(' '.join(str(x) for x in items) + '\n')
        sys.stderr.flush()

    def progress(pos, duration):
        if args.machine:
            report('progress', '{:.2f}'.format(pos), '{:.2f}'.format(duration))
        else:
            sys.stderr.write('\r{} / {}'.format(formatTime(pos), formatTime(duration)))
            sys.stderr.flush()

    try:
        if args.detect_language:
            res = detectLanguage(args.input, streamNo, model=args.model)
            print('language {} {:.3f}'.format(*res) if res else 'language none')
            return 0

        if args.chunks_dir and args.words:
            ranges = [ tuple(float(x) for x in r.split('-')) for r in args.words.split(',') ]
            getWordLines(args.input, args.chunks_dir, streamNo, args.lang, ranges,
                    translate=args.translate, model=args.model, channels=channels)
            report('done')
            return 0

        if args.chunks_dir and args.speech_only:
            planSpeech(args.input, args.chunks_dir, streamNo, channels)
            report('done')
            return 0

        if args.chunks_dir:
            transcribeChunks(args.input, args.chunks_dir, args.lang,
                    streamNo=streamNo, model=args.model, translate=args.translate,
                    progressCb=progress, channels=channels,
                    planCb=lambda chunks: report('plan', len(chunks)),
                    chunkCb=lambda no, path: report('chunk', no))
            report('done')
            return 0

        output = args.output
        if not output:
            outLang = 'en' if args.translate else args.lang
            output = '{}.whisper.{}.srt'.format(os.path.splitext(args.input)[0], outLang)

        if os.path.exists(output) and not args.overwrite:
            print('{} already exists, use --overwrite to replace it'.format(output),
                    file=sys.stderr)
            return 1

        count = transcribe(args.input, output, args.lang, streamNo=streamNo,
                model=args.model, progressCb=progress, translate=args.translate,
                channels=channels)

    except NotInstalled as err:
        print(err, file=sys.stderr)
        return 1

    sys.stderr.write('\n')
    print('{} lines written to {}'.format(count, output))
    return 0


if __name__ == '__main__':
    sys.exit(main())
