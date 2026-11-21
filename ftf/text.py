"""Text / narrative features (Polish): normalisation, MinHash near-duplicate signatures (raw and
entity-masked), multilingual-e5-small embeddings (ONNX int8), YAKE keywords, money amounts."""
from __future__ import annotations

import re
from functools import lru_cache

import numpy as np
from datasketch import MinHash

from . import config
from .gazetteer import fold, mask_entities

NUM_PERM = 128
STOP_PL = set("""a aby ach acz aczkolwiek aj albo ale alez ani az bardziej bardzo bo bowiem by byli bylo byl byla byly
bedzie beda cali cala caly ci cie ciebie co cokolwiek cos czasami czasem czemu czy czyli daleko dla dlaczego dlatego
do dobrze dokad dosc duzo dwa dwaj dwie dwoje dzis dzisiaj gdy gdyby gdyz gdzie gdziekolwiek gdzies i ich ile im inna
inne inny innych iz ja jak jakas jakby jaki jakichs jakie jakis jakiz jakkolwiek jako jakos je jeden jedna jedno jednak
jednakze jego jej jemu jest jestem jeszcze jesli jezeli juz ja kazdy kiedy kilka kims kto ktokolwiek ktora ktore ktorego
ktorej ktory ktorych ktorym ktorzy ku lat lecz lub ma maja malo mam mi miedzy mimo mna mnie moga moi moim moja moje moze
mozliwe mozna moj mu musi my na nad nam nami nas nasi nasz nasza nasze naszego naszych natomiast natychmiast nawet nia
nic nich nie niech niego niej niemu nigdy nim nimi niz no o obok od okolo on ona one oni ono oraz oto owszem pan pana
pani po pod podczas pomimo ponad poniewaz powinien powinna powinni powinno poza prawie przeciez przed przede przedtem
przez przy roku rowniez sam sama sa sie skad soba sobie sposob swoje ta tak taka taki takie takze tam te tego tej temu
ten teraz tez to toba tobie totez trzeba tu tutaj twoi twoim twoja twoje twym twoj ty tych tylko tym u w wam wami was
wasz wasza wasze we wedlug wiec wiecej wiele wielu wlasnie wszyscy wszystkich wszystkie wszystkim wszystko wtedy wy
z za zaden zadna zadne zadnych zapewne zawsze ze zeby zero zl the and of to in is for on you your with this that""".split())


def normalize(text: str) -> str:
    t = fold(text)
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"[^\w\s%]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def tokens(text: str) -> list[str]:
    return [w for w in normalize(text).split() if len(w) > 1]


def minhash(text: str, k: int = 4) -> MinHash | None:
    toks = tokens(text)
    if len(toks) < k + 2:
        return None
    m = MinHash(num_perm=NUM_PERM, seed=7)
    for i in range(len(toks) - k + 1):
        m.update(" ".join(toks[i:i + k]).encode())
    return m


def minhash_sig(text: str, masked: bool = False) -> list[int] | None:
    m = minhash(mask_entities(text) if masked else text)
    return m.hashvalues.tolist() if m is not None else None


def jaccard_sig(a: list[int] | None, b: list[int] | None) -> float | None:
    if not a or not b:
        return None
    a, b = np.asarray(a), np.asarray(b)
    return float(np.mean(a == b))


def title_template(title: str) -> str:
    """Title with person names and numbers masked: 'pilne brutalna napasc na <per> tuz po publikacji ...'"""
    t = mask_entities(title or "")
    t = re.sub(r"\d+", "<n>", t)
    t = re.sub(r"[^\w<>\s]", " ", t)
    t = re.sub(r"\b(gazeta pl|tvn24|onet|wp pl|interia|polsat news|fakt|wprost)\b", " <media> ", t)
    return re.sub(r"\s+", " ", t).strip()


def char_ngram_sim(a: str, b: str, n: int = 3) -> float:
    if not a or not b:
        return 0.0
    A = {a[i:i + n] for i in range(len(a) - n + 1)}
    B = {b[i:i + n] for i in range(len(b) - n + 1)}
    return len(A & B) / max(1, len(A | B))


# ----------------------------------------------------------------------------- e5 embeddings
@lru_cache(maxsize=1)
def _tok():
    from tokenizers import Tokenizer

    t = Tokenizer.from_file(str(config.MODELS / "e5" / "tokenizer.json"))
    t.enable_truncation(max_length=512)
    t.enable_padding(pad_id=1, pad_token="<pad>")
    return t


def embed_text(text: str) -> np.ndarray | None:
    p = config.MODELS / "e5" / "model.onnx"
    if not p.exists() or not text or len(text.strip()) < 10:
        return None
    from .vision import _session

    # Sample up to 3 windows (lead, middle, end) for long landing pages,
    # L2-normalising each window before averaging so every region has equal weight.
    words = text.split()
    win = 220
    if len(words) <= win:
        chunks = [" ".join(words)] if words else [text]
    elif len(words) <= 2 * win:
        chunks = [" ".join(words[:win]), " ".join(words[-win:])]
    else:
        mid = max(win, (len(words) - win) // 2)
        chunks = [" ".join(words[:win]), " ".join(words[mid:mid + win]), " ".join(words[-win:])]

    enc = _tok().encode_batch([f"query: {c}" for c in chunks])
    ids = np.array([e.ids for e in enc], dtype=np.int64)
    mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
    sess = _session(str(p))
    h = sess.run(["last_hidden_state"], {"input_ids": ids, "attention_mask": mask,
                                          "token_type_ids": np.zeros_like(ids)})[0]
    v = (h * mask[..., None]).sum(1) / np.maximum(mask.sum(1, keepdims=True), 1)
    v = v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)
    v = v.mean(0)
    return (v / (np.linalg.norm(v) + 1e-9)).astype(np.float32)


# ----------------------------------------------------------------------------- keywords, amounts
def keywords(text: str, n: int = 15) -> list[str]:
    if not text or len(text) < 40:
        return []
    import yake

    try:
        kw = yake.KeywordExtractor(lan="pl", n=2, top=n * 2, dedupLim=0.7)
        out = []
        for k, _ in kw.extract_keywords(text[:20000]):
            kf = fold(k)
            if any(w in STOP_PL for w in kf.split()) and len(kf.split()) == 1:
                continue
            out.append(k.lower())
        return list(dict.fromkeys(out))[:n]
    except Exception:
        return []


AMOUNT_RX = re.compile(r"(\d[\d  .,]{0,12}\d|\d)\s*(zł|zl|pln|eur|€|usd|\$|tys\.? ?zł|tys\.?)", re.I)


def amounts(text: str) -> list[str]:
    out = []
    for m in AMOUNT_RX.finditer(text or ""):
        num = re.sub(r"[  ]", "", m.group(1))
        out.append(f"{num} {m.group(2).lower().replace('zl', 'zł')}")
    return list(dict.fromkeys(out))[:20]
