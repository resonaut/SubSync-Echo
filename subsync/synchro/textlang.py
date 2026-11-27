"""Language of subtitles from their text, when neither the file name nor the
file's stream tag says it.

Nothing is downloaded and only Python's standard library is used. The writing
system settles Japanese (kana), Chinese, Korean, Greek, Hebrew, Arabic and
Persian, and the Cyrillic languages by their own letters (Ukrainian і ї є,
Belarusian ў, Serbian ђ ћ џ ј љ њ, Russian ы э, Bulgarian ъ). Languages
written in Latin letters are told apart by their most common short words.

It answers only when the text is long enough and one language clearly leads;
otherwise `None`, and the language has to be chosen as before. A language
from the file name or from the user always wins over this one.
"""

import codecs
import os
import re

import logging
logger = logging.getLogger(__name__)


minLetters = 200        # fewer letters than this: no answer
minSyllables = 60       # the same for Chinese, Japanese and Korean, whose
                        # characters each carry a syllable or a word
minWords = 40           # Latin script: fewer words than this, no answer
minShare = 0.12         # Latin script: share of words that must be common words
minLead = 1.3           # Latin script: the best language's share over the next one's
maxBytes = 2 << 20      # read at most this much of a file

# the most common short words of each language written in Latin letters,
# without apostrophes (text is split at them: "c'est" -> "c", "est"); words
# two languages share count for both, the ones only one uses decide
COMMON = {
    'eng': 'the and to of a you it is in that what we me this he for my your on be have not do '
           'no know are was with just don so but all can get here they there she him her right '
           'come go yeah oh okay re ll ve didn',
    'spa': 'de que no la el y a en es lo un los se por me una qué con para te mi las del está '
           'pero eso como sí bien al le tu esto más yo ya muy todo tengo hay soy estoy',
    'fre': 'de je pas le la les et un est à tu que vous il ne une en ce des on qui pour ça bien '
           'mais oui non suis dans moi te me du au avec elle nous fait sais rien',
    'ger': 'ich die und der nicht du das ist sie es zu ein wir was mir in den mit ja auf sich '
           'dich mich ihr eine so wie hier auch noch aber nein bin hast habe haben',
    'ita': 'di che non è e il la un per mi ti lo sono io si ma una le ho cosa me questo con ci '
           'da in no sei bene gli tu del come hai mio sta',
    'por': 'que não de o a é e um você eu se do da para com isso uma me os no na está mas em '
           'ele por sim bem meu tem estou vou',
    'dut': 'ik je de het een is niet dat en van wat in we hij zijn op met maar die er dit voor '
           'ze hebben jij ben heb wel nee kan mijn hier ook',
    'pol': 'nie to się jest w na i że z co jak ja mnie do tak mi ale czy ty ten już jestem go '
           'tu by jego może tylko dobrze wiem jesteś',
    'cze': 'je to se na že ne v a jsem co mi tak jak ale si s z tady já ty pro do už jsi by mě '
           'jen bylo není proč',
    'slo': 'je to sa na že nie v a som čo mi tak ako ale si s z tu ja ty pre do už by ma len '
           'bolo prečo aj',
    'swe': 'och det att jag är du en som inte på har vi för med den vad till kan mig ska han '
           'så här nej ja var de dig om men',
    'dan': 'det er jeg ikke at du og en har til de på vi med for som hvad kan mig han så her '
           'nej ja var skal den dig om men noget nu meget ved lige',
    'nor': 'det er jeg ikke at du og en har til de på vi med for som hva kan meg han så her '
           'nei ja var skal den deg om men noe nå mye vet veldig',
    'fin': 'on ja se ei en että mitä minä sinä hän me te ne oli olen ole kun mutta niin tämä '
           'joo nyt vain jos sitä mikä',
    'hun': 'a az és nem hogy is egy van meg én de ez te mi ki csak most már igen mit itt vagy '
           'volt kell azt',
    'rum': 'și nu de în că e o să a la ce un pe eu mai cu tu se ești sunt asta ne te mă da '
           'acum ai',
    'tur': 'bir ve bu ne ben sen da de mi çok için o var değil evet hayır ama gibi şey seni '
           'beni neden nasıl',
    'hrv': 'je i da se u ne na to su sam što ti ja mi a li si kako ali za od ovo smo bio '
           'ovdje gdje',
    'slv': 'je in da se v ne na to so sem kaj ti jaz mi pa ali si kako za od tukaj smo bil '
           'kje',
    'ind': 'yang dan aku tidak kau ini itu di kita ke apa ada dia saya kamu akan dengan untuk '
           'ya tak bisa sudah',
    'cat': 'de que i no la el a és un en per em una amb què els ho al ha jo ets molt però '
           'això també',
    'est': 'ja on ei see et ma sa me te mis kas oli olen aga siis nii kui seda mind sind ka',
    'lav': 'un ir ne es tu ka tas ko man par to kas jā viņš mēs jūs bet vai esmu tev mani',
    'lit': 'ir ne aš tu kad tai kas yra su į man ką jis mes jūs bet ar taip čia mane tave',
    'ice': 'að og ég er það ekki þú á í við hann en hvað um sem til mér þig já nei',
    'alb': 'të e në një që është dhe nuk unë ti për me ky kjo po jo mua ju çfarë',
    'glg': 'de que non a o e é un en se por me unha para co como pero isto xa moi',
}
COMMON = { lang: set(words.split()) for lang, words in COMMON.items() }

# a word several languages use counts for each of them by 1 / how many: close
# languages (Danish and Norwegian, Czech and Slovak) share most common words,
# and the words only one of them uses decide between them
WEIGHT = {}
for _common in COMMON.values():
    for _w in _common:
        WEIGHT[_w] = WEIGHT.get(_w, 0) + 1
WEIGHT = { w: 1 / n for w, n in WEIGHT.items() }


def _scripts(text):
    """Letters of text counted by writing system."""
    counts = dict.fromkeys(('latin', 'kana', 'han', 'hangul', 'cyrillic', 'greek',
                            'arabic', 'hebrew', 'other'), 0)
    for ch in text:
        if not ch.isalpha():
            continue
        o = ord(ch)
        if o < 0x250 or 0x1E00 <= o <= 0x1EFF:
            counts['latin'] += 1
        elif 0x3040 <= o <= 0x30FF or 0x31F0 <= o <= 0x31FF or 0xFF66 <= o <= 0xFF9D:
            counts['kana'] += 1
        elif 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or 0xF900 <= o <= 0xFAFF:
            counts['han'] += 1
        elif 0xAC00 <= o <= 0xD7AF or 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F:
            counts['hangul'] += 1
        elif 0x0400 <= o <= 0x04FF:
            counts['cyrillic'] += 1
        elif 0x0370 <= o <= 0x03FF or 0x1F00 <= o <= 0x1FFF:
            counts['greek'] += 1
        elif 0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F or 0xFB50 <= o <= 0xFDFF \
                or 0xFE70 <= o <= 0xFEFF:
            counts['arabic'] += 1
        elif 0x0590 <= o <= 0x05FF:
            counts['hebrew'] += 1
        else:
            counts['other'] += 1
    return counts


def _rate(text, letters, total):
    return sum(text.count(c) for c in letters) / total


def _cyrillic(text, total):
    """Cyrillic languages by the letters only they use (or don't)."""
    if _rate(text, 'ў', total) > 0.003:
        return 'bel'
    if _rate(text, 'ѓќѕ', total) > 0.003:
        return None                         # Macedonian, not supported
    if _rate(text, 'іїєґ', total) > 0.005:
        return 'ukr'
    if _rate(text, 'ђћџјљњ', total) > 0.003:
        return 'srp'
    if _rate(text, 'ыэ', total) > 0.005:
        return 'rus'
    if _rate(text, 'ъ', total) > 0.005:
        return 'bul'
    return None


def _latin(text):
    """(language, share of common words, lead over the next language) for text
    in Latin letters, or None."""
    words = [ w for w in re.split(r"[^\w]+|[\d_]+", text.lower()) if w ]
    if len(words) < minWords:
        return None
    scores = sorted(((sum(WEIGHT[w] for w in words if w in common), lang)
                     for lang, common in COMMON.items()), reverse=True)
    (best, lang), (second, other) = scores[0], scores[1]
    share = sum(w in COMMON[lang] for w in words) / len(words)
    if share < minShare or best < minLead * second:
        logger.debug('text language: no clear answer, %s %.1f, %s %.1f, %.0f%% common words',
                lang, best, other, second, 100 * share)
        return None
    return lang, share, best / max(second, 1e-9)


def detectText(text):
    """Language of subtitle text.

    Returns
    -------
    tuple of (str, float) or None
        3-letter language code (as in subsync.data.languages) and the share
        of letters (or common words) that decided it, `None` when there is
        no clear answer.
    """
    counts = _scripts(text)
    total = sum(counts.values())
    syllables = counts['han'] + counts['kana'] + counts['hangul']
    if total < minLetters and not (syllables >= minSyllables and syllables >= 0.6 * total):
        return None
    script = max(counts, key=counts.get)
    share = counts[script] / total

    if counts['kana'] >= 0.1 * (counts['kana'] + counts['han']) and counts['kana'] + counts['han'] >= 0.5 * total:
        return 'jpn', (counts['kana'] + counts['han']) / total
    if share < 0.6:
        return None                         # several writing systems mixed
    if script == 'han':
        return 'chi', share
    if script == 'hangul':
        return 'kor', share
    if script == 'greek':
        return 'gre', share
    if script == 'hebrew':
        return 'heb', share
    if script == 'arabic':
        # Persian has letters Arabic lacks, and writes ی and ک for ي and ك
        return ('per' if _rate(text, 'پچژگیک', counts['arabic']) > 0.02 else 'ara'), share
    if script == 'cyrillic':
        lang = _cyrillic(text, counts['cyrillic'])
        return (lang, share) if lang else None
    if script == 'latin':
        res = _latin(text)
        return (res[0], res[1]) if res else None
    return None


_TAGS = re.compile(r'<[^>]*>|\{[^}]*\}|\\[Nnh]')


def subtitleText(raw, ext):
    """The spoken text of a subtitle file's content, without numbers, times,
    styles or tags. ext: the file's extension (.srt, .ass, .ssa, .sub, .txt,
    .vtt)."""
    lines = []
    ext = ext.lower()
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if ext in ('.ass', '.ssa'):
            if not line.lower().startswith('dialogue:'):
                continue
            parts = line.split(',', 9)
            line = parts[9] if len(parts) == 10 else ''
        elif ext == '.sub':
            line = re.sub(r'^(\{\d*\}){1,2}', '', line).replace('|', ' ')
        elif ext == '.txt':
            line = re.sub(r'^\d+:\d\d:\d\d[:=]', '', line).replace('|', ' ')
        if line.isdigit() or '-->' in line or line.upper().startswith('WEBVTT'):
            continue
        lines.append(_TAGS.sub(' ', line))
    return '\n'.join(lines)


# legacy encodings tried when a file isn't Unicode; each decoding is read and
# the one that gives the clearest answer is kept
LEGACY = ['cp1251', 'cp1250', 'cp1252', 'cp1253', 'cp1254', 'cp1255', 'cp1256', 'cp1257',
          'gb18030', 'big5', 'shift_jis', 'euc-kr']


def _decodings(data):
    if data.startswith(codecs.BOM_UTF8):
        yield 'utf-8-sig', data.decode('utf-8-sig', errors='replace')
        return
    for bom, enc in ((codecs.BOM_UTF16_LE, 'utf-16'), (codecs.BOM_UTF16_BE, 'utf-16')):
        if data.startswith(bom):
            yield enc, data.decode(enc, errors='replace')
            return
    try:
        yield 'utf-8', data.decode('utf-8')
        return
    except UnicodeDecodeError:
        pass
    for enc in LEGACY:
        try:
            yield enc, data.decode(enc)
        except UnicodeDecodeError:
            continue


def detectFile(path):
    """Language of a subtitle file from its text.

    Returns
    -------
    tuple of (str, float) or None
        as `detectText`; `None` also when the file can't be read.
    """
    ext = os.path.splitext(path)[1]
    try:
        with open(path, 'rb') as fp:
            data = fp.read(maxBytes)
    except OSError as err:
        logger.info('text language of %s: file not read, %s', path, err)
        return None
    answers = []
    for enc, raw in _decodings(data):
        res = detectText(subtitleText(raw, ext))
        if res:
            answers.append((res, enc))
    if not answers:
        logger.info('text language of %s: no clear answer', path)
        return None
    if len(set(res[0] for res, _enc in answers)) > 1:
        # a file in an old 8-bit encoding read one way looks Greek, another
        # way Cyrillic: when the readings disagree there's no clear answer
        logger.info('text language of %s: readings disagree (%s)', path,
                ', '.join('{} as {}'.format(res[0], enc) for res, enc in answers))
        return None
    (lang, share), enc = max(answers, key=lambda a: a[0][1])
    logger.info('text language of %s: %s (%.0f%%, read as %s)', path, lang, 100 * share, enc)
    return lang, share


# languages close enough that the text can't always tell them apart, or one
# written like the other (Serbian in Latin letters reads as Croatian): a
# language given as the other one isn't called a mismatch
CLOSE = [ {'hrv', 'srp', 'slv'}, {'dan', 'nor', 'swe'}, {'cze', 'slo'}, {'ind', 'may'},
          {'spa', 'glg', 'cat'}, {'por', 'glg'} ]


def sameLanguage(a, b):
    """Whether codes a and b are the same language, or close ones (CLOSE)."""
    a, b = (a or '').lower(), (b or '').lower()
    return a == b or any(a in group and b in group for group in CLOSE)


# subtitle files whose text can be read (subtitles inside a video file can't)
TEXT_EXTENSIONS = ('.srt', '.ass', '.ssa', '.sub', '.txt', '.vtt')


def isTextSubtitle(path):
    return bool(path) and os.path.splitext(path)[1].lower() in TEXT_EXTENSIONS
