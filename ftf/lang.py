"""Language of a text from stop-word counts, without a model.

Used only to decide whether two texts can be compared word by word: word-shingle overlap between a page and
its translation is zero by construction, so for a pair in two different known languages the `text` and `ocr`
views are treated as unavailable instead of as "dissimilar" (similarity.views). Unsure -> "und", which never
switches a view off.
"""
from __future__ import annotations

import re
from collections import Counter

UNKNOWN = "und"
_WORD = re.compile(r"[^\W\d_]+")
_STOP = {k: frozenset(v.split()) for k, v in {
    "en": "the and of to is for you your with that this are it be as at we our from have can will not",
    "pl": "nie się jest że jak dla po od ale czy już przez oraz na do to co jego ich twoje nasz są tylko może",
    "de": "der die und das ist nicht mit für auf den ein eine sie ich zu von dem wir ihre sich auch wird sind bei",
    "fr": "le les et des est pour dans que qui une du vous nous votre sur avec pas au ce sont vos plus aux",
    "es": "el los las y que en es para con por una su se del al tu más como sus nuestro está puede",
    "it": "il di che per un una con non sono del della le si più come gli nel alla tuo dei ed è anche",
    "pt": "os as que em para com não uma um do da no na se você mais seu sua dos das são ao pela",
    "nl": "de het een en van is op te dat voor met niet zijn je uw aan bij ook naar wij onze wordt",
    "cs": "že pro jako nebo vaše jsou které při jsme však být není tak už také nás aby jak po",
    "sk": "že pre ako alebo vaše sú ktoré pri sme však byť nie tak už tiež nás aby po",
    "hu": "az és hogy nem egy meg van ez de csak mint vagy már még ha az ön által lehet kell",
    "ro": "și de la în cu pentru este că un care nu se mai pe din sau sunt dvs prin ale",
    "sv": "och att det är som på för med av inte till den har du vi ett din från kan eller",
    "da": "og at det er som på for med af av ikke til den har du vi et din fra kan eller",
    "fi": "ja on ei se että tai kun niin myös ovat sinun voit ole kanssa sekä joka",
    "tr": "ve bir bu için ile da de ne en daha çok gibi var olarak veya sizin",
    "hr": "je se da za su od ne kao što ili sa te koji će vaš biti može",
    "id": "dan yang di untuk dengan ini itu dari anda tidak akan atau pada kami dapat",
    "vi": "và của là có cho các không được trong với một này bạn để những",
    "lt": "ir kad yra su tai į iš jūsų kaip arba bet mes gali per",
    "el": "και το της την του να με για από που είναι σε τα στο",
}.items()}
# Non-Latin scripts decide on their own: (name, first code point, last code point, minimum share of letters).
_SCRIPTS = (("cyr", "Ѐ", "ӿ", 0.3), ("el", "Ͱ", "Ͽ", 0.3), ("ar", "؀", "ۿ", 0.3),
            ("he", "֐", "׿", 0.3), ("th", "฀", "๿", 0.3), ("ja", "぀", "ヿ", 0.08),
            ("ko", "가", "힯", 0.3), ("zh", "一", "鿿", 0.3))
MIN_WORDS = 25


def language(text: str) -> str:
    """ISO 639-1 code of the majority stop-word language, a script-based code for non-Latin text, else "und"."""
    words = [w.lower() for w in _WORD.findall((text or "")[:60000])]
    if len(words) < MIN_WORDS:
        return UNKNOWN
    letters = "".join(words)[:8000]
    for name, lo, hi, share in _SCRIPTS:
        if sum(lo <= ch <= hi for ch in letters) / len(letters) > share:
            if name != "cyr":
                return name
            return "uk" if re.search("[їєґ]", letters) else "bg" if letters.count("ъ") / len(letters) > 0.005 else "ru"
    words = words[:4000]
    hits = Counter({lang: sum(w in sw for w in words) for lang, sw in _STOP.items()})
    (best, n1), (_, n2) = hits.most_common(2)
    if n1 < 8 or n1 / len(words) < 0.05 or n1 < 1.25 * n2:
        return UNKNOWN
    return best


def differ(a: str | None, b: str | None) -> bool:
    """True only when both languages are known and different."""
    return bool(a and b and a != UNKNOWN and b != UNKNOWN and a != b)
