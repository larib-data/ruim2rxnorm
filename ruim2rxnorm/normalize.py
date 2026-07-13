"""String normalization helpers.

:func:`normalize` -- accent/case/whitespace/punctuation folding. Everything the
matcher compares (a user query, a RUIM ``libelle`` brand key, a French substance
name) is passed through this first so comparison is apples-to-apples. Output is
**lower-case, ASCII-folded**.

Matching is French-to-French throughout and the only crossing into RxNorm is by
ATC code, so no substance name is ever translated or salt-stripped for matching
here -- the RUIM ``fraction therapeutique`` rows already name the moiety.
"""

from __future__ import annotations

import re
import unicodedata

# Apostrophe glyphs that appear in the French source ("d'almitrine" may use a
# straight quote or a typographic one). Normalized to a straight apostrophe.
_APOSTROPHES = "’ʼ‘`"

# Characters kept inside a token; everything else becomes a separator. We keep
# letters, digits, spaces and the two intra-word joiners (hyphen, apostrophe).
_KEEP = re.compile(r"[^a-z0-9 '\-]+")
_WS = re.compile(r"\s+")


def strip_accents(text: str) -> str:
    """Return *text* with diacritics removed via NFKD decomposition.

    ``"Perindopril"`` keeps its letters; ``"perindopril"`` with accents loses
    them (``é`` -> ``e``, ``ç`` -> ``c``). The ligatures ``œ``/``æ`` are not
    combining marks, so they are expanded explicitly first.
    """
    text = text.replace("œ", "oe").replace("æ", "ae")
    text = text.replace("Œ", "oe").replace("Æ", "ae")
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize(text: str) -> str:
    """Fold *text* to a canonical comparison key.

    Lower-cases, strips accents, normalizes apostrophes, drops any character
    that is not a letter/digit/space/hyphen/apostrophe, and collapses runs of
    whitespace. Surrounding whitespace and stray leading/trailing joiners are
    trimmed. ``None``/empty input yields ``""``.

    >>> normalize("Perindopril")
    'perindopril'
    >>> normalize("  DOLIPRANE 1000 mg, comprime  ")
    'doliprane 1000 mg comprime'
    """
    if not text:
        return ""
    for ch in _APOSTROPHES:
        text = text.replace(ch, "'")
    text = strip_accents(text).lower()
    text = _KEEP.sub(" ", text)
    text = _WS.sub(" ", text).strip()
    # A hyphen/apostrophe that ended up on a word boundary is punctuation, not a
    # joiner (e.g. a trailing dash left by dose stripping).
    text = re.sub(r"(?:^|(?<=\s))['\-]+|['\-]+(?=\s|$)", "", text)
    return _WS.sub(" ", text).strip()
