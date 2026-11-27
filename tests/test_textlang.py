"""Unit tests for subsync/synchro/textlang.py: the language of subtitles from
their text, when the file name doesn't say it.

    python -m unittest discover -s tests -v
"""

import importlib.util
import os
import tempfile
import unittest

_path = os.path.join(os.path.dirname(__file__), '..', 'subsync', 'synchro', 'textlang.py')
_spec = importlib.util.spec_from_file_location('textlang', _path)
textlang = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(textlang)


# the same few lines of dialogue in each language
LATIN = {
    'eng': "I don't know what you want from me. We have to go now, it's getting dark and they are "
           "coming. Did you see him? No, I didn't. Okay, just stay here with me and don't move. This "
           "is not what we planned, but we can still get out of here if you trust me.",
    'spa': "No sé qué quieres de mí. Tenemos que irnos ya, se está haciendo de noche y ellos vienen. "
           "¿Lo viste? No, no lo vi. Bien, quédate aquí conmigo y no te muevas. Esto no es lo que "
           "planeamos, pero todavía podemos salir de aquí si confías en mí. Eso es todo lo que tengo.",
    'fre': "Je ne sais pas ce que tu veux de moi. On doit partir maintenant, il fait nuit et ils "
           "arrivent. Tu l'as vu ? Non, je ne l'ai pas vu. Bon, reste ici avec moi et ne bouge pas. "
           "Ce n'est pas ce qu'on avait prévu, mais on peut encore sortir d'ici si tu me fais confiance.",
    'ger': "Ich weiß nicht, was du von mir willst. Wir müssen jetzt gehen, es wird dunkel und sie "
           "kommen. Hast du ihn gesehen? Nein, habe ich nicht. Gut, bleib hier bei mir und beweg dich "
           "nicht. Das ist nicht das, was wir geplant haben, aber wir können noch hier raus.",
    'ita': "Non so cosa vuoi da me. Dobbiamo andare adesso, si sta facendo buio e stanno arrivando. "
           "L'hai visto? No, non l'ho visto. Va bene, resta qui con me e non muoverti. Questo non è "
           "quello che avevamo pianificato, ma possiamo ancora uscire da qui se ti fidi di me.",
    'por': "Eu não sei o que você quer de mim. Temos que ir agora, está escurecendo e eles estão "
           "vindo. Você o viu? Não, eu não vi. Tudo bem, fique aqui comigo e não se mexa. Isso não é "
           "o que planejamos, mas ainda podemos sair daqui se você confiar em mim.",
    'dut': "Ik weet niet wat je van me wilt. We moeten nu gaan, het wordt donker en ze komen eraan. "
           "Heb je hem gezien? Nee, dat heb ik niet. Goed, blijf hier bij mij en beweeg niet. Dit is "
           "niet wat we gepland hadden, maar we kunnen hier nog weg als je me vertrouwt.",
    'pol': "Nie wiem, czego ode mnie chcesz. Musimy już iść, robi się ciemno i oni nadchodzą. "
           "Widziałeś go? Nie, nie widziałem. Dobrze, zostań tu ze mną i się nie ruszaj. To nie jest "
           "to, co planowaliśmy, ale wciąż możemy się stąd wydostać, jeśli mi ufasz. Wiem, że to trudne.",
    'cze': "Nevím, co ode mě chceš. Musíme jít, už se stmívá a oni přicházejí. Viděl jsi ho? Ne, "
           "neviděl jsem ho. Dobře, zůstaň tady se mnou a nehýbej se. Tohle není to, co jsme "
           "plánovali, ale pořád se odsud můžeme dostat, jestli mi věříš. Proč jsi to udělal? Já jsem to nebyl.",
    'slo': "Neviem, čo odo mňa chceš. Musíme ísť, už sa stmieva a oni prichádzajú. Videl si ho? Nie, "
           "nevidel som ho. Dobre, zostaň tu so mnou a nehýb sa. Toto nie je to, čo sme plánovali, "
           "ale stále sa odtiaľto môžeme dostať, ak mi veríš. Prečo si to urobil? Ja som to nebol.",
    'swe': "Jag vet inte vad du vill ha av mig. Vi måste gå nu, det börjar bli mörkt och de kommer. "
           "Såg du honom? Nej, det gjorde jag inte. Okej, stanna här med mig och rör dig inte. Det "
           "här är inte vad vi planerade, men vi kan fortfarande ta oss härifrån om du litar på mig.",
    'dan': "Jeg ved ikke, hvad du vil have af mig. Vi skal gå nu, det bliver mørkt, og de kommer. "
           "Så du ham? Nej, det gjorde jeg ikke. Okay, bliv her hos mig og lad være med at bevæge "
           "dig. Det er ikke det, vi planlagde, men vi kan stadig komme ud herfra, hvis du stoler på mig.",
    'nor': "Jeg vet ikke hva du vil ha av meg. Vi må gå nå, det blir mørkt, og de kommer. Så du "
           "ham? Nei, det gjorde jeg ikke. Ok, bli her hos meg og ikke beveg deg. Det er ikke det vi "
           "planla, men vi kan fortsatt komme oss ut herfra hvis du stoler på meg. Hva skjer?",
    'fin': "En tiedä, mitä sinä haluat minulta. Meidän täytyy lähteä nyt, alkaa olla pimeää ja he "
           "tulevat. Näitkö hänet? En nähnyt. Hyvä on, pysy tässä minun kanssani äläkä liiku. Tämä "
           "ei ole se mitä suunnittelimme, mutta pääsemme vielä pois täältä, jos luotat minuun. Se on nyt niin.",
    'hun': "Nem tudom, mit akarsz tőlem. Most mennünk kell, sötétedik és jönnek. Láttad őt? Nem, "
           "nem láttam. Jó, maradj itt velem és ne mozdulj. Ez nem az, amit terveztünk, de még ki "
           "tudunk jutni innen, ha megbízol bennem. Csak ennyi van, és most már igen, itt vagyunk.",
    'rum': "Nu știu ce vrei de la mine. Trebuie să plecăm acum, se întunecă și ei vin. L-ai văzut? "
           "Nu, nu l-am văzut. Bine, stai aici cu mine și nu te mișca. Asta nu e ce am plănuit, dar "
           "încă putem ieși de aici dacă ai încredere în mine. Eu sunt aici acum.",
    'tur': "Benden ne istediğini bilmiyorum. Şimdi gitmemiz lazım, hava kararıyor ve onlar geliyor. "
           "Onu gördün mü? Hayır, görmedim. Tamam, burada benimle kal ve kıpırdama. Bu bizim "
           "planladığımız şey değil ama bana güvenirsen hâlâ buradan çıkabiliriz. Neden bunu yaptın? "
           "Bilmiyorum, sen de bir şey söyle. Bu çok kötü.",
    'hrv': "Ne znam što želiš od mene. Moramo ići sada, pada mrak i oni dolaze. Jesi li ga vidio? "
           "Ne, nisam ga vidio. Dobro, ostani ovdje sa mnom i ne miči se. Ovo nije ono što smo "
           "planirali, ali još uvijek možemo otići odavde ako mi vjeruješ. Gdje si bio? Ja sam bio ovdje.",
    'slv': "Ne vem, kaj hočeš od mene. Zdaj moramo iti, temni se in prihajajo. Si ga videl? Ne, "
           "nisem ga videl. Dobro, ostani tukaj z mano in se ne premikaj. To ni tisto, kar smo "
           "načrtovali, ampak še vedno lahko pobegnemo od tod, če mi zaupaš. Kje si bil? Jaz sem bil tukaj.",
    'ind': "Aku tidak tahu apa yang kau inginkan dariku. Kita harus pergi sekarang, hari sudah gelap "
           "dan mereka datang. Apa kau melihatnya? Tidak, aku tidak melihatnya. Baiklah, tetap di sini "
           "bersamaku dan jangan bergerak. Ini bukan yang kita rencanakan, tapi kita masih bisa keluar.",
    'cat': "No sé què vols de mi. Hem de marxar ara, s'està fent fosc i ells venen. L'has vist? No, "
           "no l'he vist. D'acord, queda't aquí amb mi i no et moguis. Això no és el que havíem "
           "planejat, però encara podem sortir d'aquí si confies en mi. Jo també ho sé, és molt difícil.",
    'glg': "Non sei que queres de min. Temos que marchar xa, está a escurecer e eles veñen. Vícheo? "
           "Non, non o vin. Ben, queda aquí comigo e non te movas. Isto non é o que planeamos, pero "
           "aínda podemos saír de aquí se confías en min. Xa está, é moi tarde e non hai nada.",
}

SCRIPTS = {
    'jpn': 'どこに行くの？待って、一緒に行こう。本当にありがとう。私は何も知らなかった。ここにいてください。大丈夫だよ、心配しないで。',
    'chi': '你要去哪里？等一下，我们一起走。真的谢谢你。我什么都不知道。请你留在这里。没关系，不要担心。',
    'kor': '어디 가는 거야? 잠깐만, 같이 가자. 정말 고마워. 나는 아무것도 몰랐어. 여기 있어 줘. 괜찮아, 걱정하지 마.',
    'gre': 'Δεν ξέρω τι θέλεις από μένα. Πρέπει να φύγουμε τώρα, νυχτώνει και έρχονται. Τον είδες; '
           'Όχι, δεν τον είδα. Εντάξει, μείνε εδώ μαζί μου και μην κουνηθείς.',
    'heb': 'אני לא יודע מה אתה רוצה ממני. אנחנו צריכים ללכת עכשיו, מחשיך והם באים. ראית אותו? '
           'לא, לא ראיתי. בסדר, תישאר כאן איתי ואל תזוז.',
    'ara': 'لا أعرف ماذا تريد مني. يجب أن نذهب الآن، الظلام يحل وهم قادمون. هل رأيته؟ لا، لم أره. '
           'حسنا، ابق هنا معي ولا تتحرك.',
    'per': 'نمی‌دانم از من چه می‌خواهی. باید الان برویم، هوا دارد تاریک می‌شود و آنها می‌آیند. '
           'او را دیدی؟ نه، ندیدم. باشه، اینجا پیش من بمان و تکان نخور.',
    'rus': 'Я не знаю, чего ты от меня хочешь. Нам нужно идти сейчас, темнеет, и они идут. Ты его '
           'видел? Нет, не видел. Хорошо, останься здесь со мной и не двигайся. Это не то, что мы '
           'планировали, но мы ещё можем выбраться отсюда, если ты мне веришь.',
    'ukr': 'Я не знаю, чого ти від мене хочеш. Нам треба йти зараз, темніє, і вони йдуть. Ти його '
           'бачив? Ні, не бачив. Добре, залишайся тут зі мною і не рухайся. Це не те, що ми '
           'планували, але ми ще можемо вибратися звідси, якщо ти мені віриш. Її тут немає, є лише ми.',
    'bel': 'Я не ведаю, чаго ты ад мяне хочаш. Нам трэба ісці зараз, цямнее, і яны ідуць. Ты яго '
           'бачыў? Не, не бачыў. Добра, застанься тут са мной і не рухайся. Гэта не тое, што мы '
           'планавалі, але мы яшчэ можам выбрацца адсюль, калі ты мне верыш.',
    'srp': 'Не знам шта желиш од мене. Морамо да идемо сада, пада мрак и они долазе. Јеси ли га '
           'видео? Не, нисам га видео. Добро, остани овде са мном и не мичи се. Ово није оно што смо '
           'планирали, али још увек можемо да одемо одавде ако ми верујеш. Где си био, љубави?',
    'bul': 'Не знам какво искаш от мен. Трябва да тръгваме сега, стъмва се и те идват. Видя ли го? '
           'Не, не съм го видял. Добре, остани тук с мен и не мърдай. Това не е това, което '
           'планирахме, но все още можем да се измъкнем оттук, ако ми вярваш. Къде беше?',
}


def srt(text, repeat=1):
    """A subtitle file's content with text split into lines."""
    lines = [ l.strip() for l in (text + ' ') .replace('. ', '.\n').replace('? ', '?\n').splitlines() if l.strip() ]
    out = []
    for no, line in enumerate(lines * repeat, 1):
        out.append('{}\n00:00:{:02},000 --> 00:00:{:02},500\n{}\n'.format(no, no % 60, no % 60, line))
    return '\n'.join(out)


class TextLanguageTest(unittest.TestCase):
    def test_latin_script_languages(self):
        for lang, text in LATIN.items():
            with self.subTest(lang=lang):
                res = textlang.detectText(textlang.subtitleText(srt(text, 2), '.srt'))
                self.assertIsNotNone(res, lang)
                self.assertEqual(res[0], lang)

    def test_close_languages_told_apart(self):
        # most of their common words are the same; the others decide
        for a, b in (('dan', 'nor'), ('cze', 'slo'), ('hrv', 'slv'), ('spa', 'glg'), ('spa', 'cat'),
                     ('por', 'glg')):
            for lang in (a, b):
                with self.subTest(lang=lang):
                    self.assertEqual(textlang.detectText(LATIN[lang] * 2)[0], lang)

    def test_languages_by_writing_system(self):
        for lang, text in SCRIPTS.items():
            with self.subTest(lang=lang):
                res = textlang.detectText(text * 3)
                self.assertIsNotNone(res, lang)
                self.assertEqual(res[0], lang)

    def test_no_answer_without_enough_text(self):
        self.assertIsNone(textlang.detectText(LATIN['eng'][:120]))
        self.assertIsNone(textlang.detectText('Downloaded from YTS.MX\nOfficial YIFY movies site: YTS.MX'))
        self.assertIsNone(textlang.detectText(''))

    def test_no_answer_when_unclear(self):
        self.assertIsNone(textlang.detectText('lorem ipsum dolor sit amet consectetur adipiscing ' * 20),
                'none of the languages known')
        self.assertIsNone(textlang.detectText('क्या तुम मेरे साथ चलोगे? मुझे नहीं पता। ' * 10),
                'Hindi: SubSync has no Hindi')
        self.assertIsNone(textlang.detectText(LATIN['eng'] + ' ' + SCRIPTS['rus']),
                'two writing systems half and half')

    def test_text_of_each_format(self):
        cases = {
            '.ass': '[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
                    'Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,{\\i1}Hello,{\\i0} there\\Nfriend\n',
            '.sub': '{10}{20}Hello, there|friend\n',
            '.txt': '00:00:01:Hello, there|friend\n',
            '.vtt': 'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n<i>Hello, there</i>\nfriend\n',
            '.srt': '1\n00:00:01,000 --> 00:00:02,000\n<font color="#fff">Hello, there</font>\nfriend\n',
        }
        for ext, raw in cases.items():
            with self.subTest(ext=ext):
                self.assertEqual(textlang.subtitleText(raw, ext).split(), ['Hello,', 'there', 'friend'])

    def test_files_in_unicode_and_old_encodings(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, text, enc, lang in (
                    ('a.srt', srt(LATIN['fre'], 2), 'utf-8', 'fre'),
                    ('b.srt', srt(LATIN['ger'], 2), 'utf-8-sig', 'ger'),
                    ('c.srt', srt(LATIN['pol'], 2), 'utf-16', 'pol'),
                    ('d.srt', srt(SCRIPTS['rus'], 2), 'cp1251', 'rus'),
                    ('e.srt', srt(LATIN['spa'], 2), 'cp1252', 'spa')):
                path = os.path.join(tmp, name)
                with open(path, 'w', encoding=enc, newline='\n') as fp:
                    fp.write(text)
                with self.subTest(enc=enc):
                    res = textlang.detectFile(path)
                    self.assertIsNotNone(res, enc)
                    self.assertEqual(res[0], lang)
            self.assertIsNone(textlang.detectFile(os.path.join(tmp, 'missing.srt')))

    def test_text_subtitle_files(self):
        self.assertTrue(textlang.isTextSubtitle('Movie.SRT'))
        self.assertTrue(textlang.isTextSubtitle('a/b/Movie.ass'))
        self.assertFalse(textlang.isTextSubtitle('Movie.mkv'))
        self.assertFalse(textlang.isTextSubtitle(None))


if __name__ == '__main__':
    unittest.main()
