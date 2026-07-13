"""String normalization + FR->EN morphology / salt-stripping helpers.

Three concerns, kept in one place so queries, brand keys and substance names are
all folded the same way:

* :func:`normalize` -- accent/case/whitespace/punctuation folding. Everything the
  matcher compares (a user query, a RUIM ``libelle`` brand key, a French
  substance name, an INN in ``atc5_names``) is passed through this first so
  comparison is apples-to-apples. Output is **lower-case, ASCII-folded**.
* :func:`strip_salt` -- reduce a French substance name to its therapeutic moiety
  by removing salt / hydrate wrappers (``chlorhydrate de metoclopramide`` ->
  ``metoclopramide``, ``rifampicine sodique`` -> ``rifampicine``). The RUIM
  ``fraction therapeutique`` rows already name the moiety in most cases, so this
  is a safety net for residual salt/hydrate suffixes.
* :func:`to_english_inn` -- light French->English INN morphology (``-ine`` ->
  ``-in``, ``-ique`` -> ``-ic``, ...) applied *only as a fallback* by the
  resolver, after an exact match on the normalized name has failed.

:func:`substance_variants` bundles the last two into the ordered candidate list
the resolver walks (most-faithful first) when mapping a moiety to an ATC class.
"""

from __future__ import annotations

import re
import unicodedata
from typing import List

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


# --- Salt / hydrate stripping -------------------------------------------------
#
# All terms are written in already-normalized form (lower-case, no accents), the
# state :func:`strip_salt` operates on. Two shapes occur in the RUIM substance
# table:
#   * prefix ester/salt + linker: "chlorhydrate de metoclopramide",
#     "mesilate d'almitrine", "succinate sodique de methylprednisolone"
#   * trailing adjectival salt / hydration: "rifampicine sodique",
#     "cefadroxil monohydrate", "chlorure de magnesium anhydre"

# Anionic / ester salt heads that appear as "<head> de <moiety>".
_PREFIX_SALTS = [
    "chlorhydrate", "bromhydrate", "iodhydrate", "sulfate", "hemisulfate",
    "bisulfate", "phosphate", "diphosphate", "hydrogenophosphate", "nitrate",
    "acetate", "diacetate", "maleate", "hydrogenomaleate", "tartrate",
    "hydrogenotartrate", "bitartrate", "citrate", "dihydrogenocitrate",
    "fumarate", "hemifumarate", "succinate", "mesilate", "mesylate", "besilate",
    "besylate", "tosilate", "tosylate", "esilate", "isetionate", "gluconate",
    "lactate", "malate", "oxalate", "salicylate", "stearate", "palmitate",
    "propionate", "dipropionate", "valerate", "aceponate", "aceponate",
    "furoate", "xinafoate", "embonate", "pamoate", "napadisilate", "edisilate",
    "camsilate", "camsylate", "orotate", "pidolate", "aspartate", "glutamate",
    "benzoate", "undecylenate", "enantate", "decanoate", "hemisuccinate",
    "chlorure", "bromure", "iodure", "trifenatate", "teoclate", "cromoglicate",
]

# Trailing adjectival salts and hydration states.
_SUFFIX_SALTS = [
    "sodique", "disodique", "trisodique", "potassique", "dipotassique",
    "calcique", "magnesique", "zincique", "ferrique", "ferreux", "argentique",
    "monosodique", "monopotassique", "anhydre", "base",
    "hydrate", "hydratee", "monohydrate", "monohydratee", "dihydrate",
    "dihydratee", "trihydrate", "trihydratee", "tetrahydrate", "pentahydrate",
    "hexahydrate", "heptahydrate", "sesquihydrate", "hemihydrate",
]

_PREFIX_RE = re.compile(
    r"^(?:%s)\s+d[e']\s*" % "|".join(sorted(_PREFIX_SALTS, key=len, reverse=True))
)
# Optional cation adjective may sit between the ester head and the linker, e.g.
# "succinate sodique de methylprednisolone".
_PREFIX_CATION_RE = re.compile(
    r"^(?:%s)\s+(?:%s)\s+d[e']\s*"
    % ("|".join(sorted(_PREFIX_SALTS, key=len, reverse=True)),
       "|".join(sorted(_SUFFIX_SALTS, key=len, reverse=True)))
)
_SUFFIX_RE = re.compile(
    r"\s+(?:%s)$" % "|".join(sorted(_SUFFIX_SALTS, key=len, reverse=True))
)


def strip_salt(name: str) -> str:
    """Reduce a normalized French substance name to its therapeutic moiety.

    Iteratively peels prefix ester/salt heads (``chlorhydrate de ...``) and
    trailing salt/hydrate adjectives (``... sodique``, ``... monohydrate``)
    until the name stabilizes. Input is expected already :func:`normalize`-d.

    >>> strip_salt("chlorhydrate de metoclopramide")
    'metoclopramide'
    >>> strip_salt("succinate sodique de methylprednisolone")
    'methylprednisolone'
    >>> strip_salt("cefadroxil monohydrate")
    'cefadroxil'
    """
    prev = None
    while name and name != prev:
        prev = name
        stripped = _PREFIX_CATION_RE.sub("", name)
        if stripped == name:
            stripped = _PREFIX_RE.sub("", name)
        name = _SUFFIX_RE.sub("", stripped).strip()
    return name


# --- FR -> EN INN morphology --------------------------------------------------
#
# Ordered suffix rewrites bridging common French INN spellings to their English
# form. Applied only as a fallback after exact matching fails, so mild
# over-transformation is tolerable. Longest suffixes first.
_MORPHOLOGY_RULES = [
    ("ique", "ic"),      # -ique  -> -ic   (folique -> folic)
    ("yle", "yl"),       # -yle   -> -yl
    ("ine", "in"),       # -ine   -> -in   (amoxicilline -> amoxicillin)
    ("ase", "ase"),      # kept (identity guard so -ine rule can't touch it)
    ("ol", "ol"),        # kept
]


def to_english_inn(name: str) -> str:
    """Apply light French->English INN suffix morphology to a normalized name.

    >>> to_english_inn("amoxicilline")
    'amoxicillin'
    >>> to_english_inn("acide folique")
    'acide folic'
    """
    for fr, en in _MORPHOLOGY_RULES:
        if fr != en and name.endswith(fr):
            return name[: -len(fr)] + en
    return name


def substance_variants(name: str) -> List[str]:
    """Ordered, de-duplicated match candidates for a French substance name.

    Most-faithful first so the resolver prefers an exact hit before a
    morphologically transformed one:

    1. the normalized name,
    2. the salt/hydrate-stripped moiety,
    3. the morphology-rewritten moiety.

    >>> substance_variants("Chlorhydrate de Metoclopramide")
    ['chlorhydrate de metoclopramide', 'metoclopramide']
    >>> substance_variants("amoxicilline")
    ['amoxicilline', 'amoxicillin']
    """
    base = normalize(name)
    out: List[str] = []
    for cand in (base, strip_salt(base), to_english_inn(strip_salt(base))):
        if cand and cand not in out:
            out.append(cand)
    return out
