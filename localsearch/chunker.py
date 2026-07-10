"""Sentence-accumulating, CJK-aware chunker + BM25 tokenizer."""
import re
import sys

_SENT = re.compile(r"[^.!?。！？；\n]*[.!?。！？；\n]+|\S[^.!?。！？；\n]*$")
_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿]")
_CJK_RUN = re.compile(r"[぀-ヿ㐀-䶿一-鿿]+")

_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset((
    "a an and are as at be by for from has he in is it its of on that the to was were "
    "will with this these those i you your we our they them their his her she him my me "
    "but or not no if then than so such can could should would may might must do does did "
    "have had having been being am are what which who whom when where why how all any both "
    "each few more most other some only own same too very s t just don now about above below "
    "up down out off over under again further once here there into through during before after"
).split())


def _weight(s):
    """Chunk-size weight of a sentence: whitespace words + CJK chars."""
    return len(s.split()) + len(_CJK.findall(s))


def chunk_text(text, max_words=150, overlap_sentences=1):
    """Return [(chunk_text, start_char, end_char)]."""
    sents = [(m.group().strip(), m.start(), m.end())
             for m in _SENT.finditer(text) if m.group().strip()]
    if not sents:
        return []
    chunks, cur, cur_w = [], [], 0
    for s, st, en in sents:
        w = _weight(s)
        if cur and cur_w + w > max_words:
            chunks.append((" ".join(x[0] for x in cur), cur[0][1], cur[-1][2]))
            cur = cur[-overlap_sentences:] if overlap_sentences else []
            cur_w = sum(_weight(x[0]) for x in cur)
        cur.append((s, st, en))
        cur_w += w
    if cur:
        chunks.append((" ".join(x[0] for x in cur), cur[0][1], cur[-1][2]))
    return chunks


def tokenize(text):
    """BM25 tokens: [a-z0-9]+ words (stopword-filtered) + CJK character bigrams."""
    low = text.lower()
    toks = [sys.intern(w) for w in _WORD.findall(low)
            if w not in _STOP and len(w) > 1]
    for run in _CJK_RUN.findall(low):
        if len(run) == 1:
            toks.append(sys.intern(run))
        else:
            toks.extend(sys.intern(run[i:i + 2]) for i in range(len(run) - 1))
    return toks
