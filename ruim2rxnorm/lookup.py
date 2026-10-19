"""Runtime lookup over the precomputed ``brand_ingredient_map.csv``.

This is the whole runtime data path. The ETL (``build-refs``) has already done
the brand -> CIS -> moiety -> individual ATC -> RxNorm-ingredient resolution and
baked it into the shipped ``refs/brand_ingredient_map.csv`` (one row per
``brand_key x ingredient``). A ``map`` / ``map-file`` call is therefore just:

    normalize the query -> brand-key -> look the key up in that table.

No vocabulary parsing, composition logic or Athena access happens here — the
source vocabularies are not even present at runtime.

Two shipped tables are read via :mod:`importlib.resources`:

* ``brand_ingredient_map.csv`` — the precomputed mapping, loaded into
  ``brand_key -> [IngredientRow]``.
* ``source_aliases.csv`` — the curated ("manual") lookup layer that redirects a
  raw source label that is *not* a RUIM brand (a local custom name, a foreign
  spelling) to an existing RUIM ``brand_key`` before matching. Ships with only a
  couple of hand-added entries and grows as real source data needs it.

Matching, after the alias redirect (reported as ``alias``):

1. **exact** brand-key hit;
2. else **substance** — the key is a French substance name (``"paracetamol"``,
   ``"sugammadex"``): the rows of that substance's mono brands only;
3. else **whole-word prefix** — every table key that begins with the query key
   as a whole word (``"humex"`` -> ``humex allergie cetirizine`` ...), so an
   umbrella brand fans out to its variants;
4. else steps 1-3 again with salt words removed (``"sugammadex sodique"`` ->
   ``"sugammadex"``, see :data:`SALT_WORDS`);
5. else **no match**.

All matched ingredient rows are returned, including ``status = unmapped`` ones
(``target_concept_id`` 0 downstream) — an unmapped moiety is an explicit result,
never dropped.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, fields
from importlib import resources
from typing import Dict, List, Optional

from .etl.ruim_io import brand_key, load_source_aliases
from .normalize import normalize

#: Package subdirectory holding the shipped reference data.
_REFS_PACKAGE = "ruim2rxnorm.refs"
BRAND_INGREDIENT_MAP = "brand_ingredient_map.csv"
SOURCE_ALIASES = "source_aliases.csv"


@dataclass(frozen=True)
class IngredientRow:
    """One row of ``brand_ingredient_map.csv`` — a brand's individual ingredient.

    Field names mirror the CSV header exactly, so a row round-trips through
    :meth:`from_dict` / the output writers unchanged. All values are kept as the
    raw strings read from disk (``rxnorm_concept_id`` ``"0"`` marks an unmapped
    ingredient, matching the STCM ``target_concept_id`` convention).
    """

    brand_key: str
    brand_display: str
    n_specialities: str
    cis_atc: str
    substance_code: str
    substance_fr: str
    individual_atc: str
    libelle_atc: str
    rxnorm_concept_id: str
    rxnorm_code: str
    rxnorm_name: str
    is_combination: str
    status: str
    reason: str

    @classmethod
    def from_dict(cls, row: Dict[str, str]) -> "IngredientRow":
        return cls(**{f.name: (row.get(f.name, "") or "") for f in fields(cls)})

    @property
    def is_mapped(self) -> bool:
        """True when this ingredient resolved to a real RxNorm concept."""
        return self.status == "mapped" and self.rxnorm_concept_id not in ("", "0")


@dataclass(frozen=True)
class MatchResult:
    """Outcome of a single :func:`lookup`.

    ``match_type`` is one of ``"exact"``, ``"alias"`` (an alias redirect that then
    hit exactly), ``"prefix"`` or ``"no_match"``. ``matched_keys`` are the table
    keys that contributed rows (one for exact/alias, possibly several for prefix,
    none for no_match).
    """

    query: str
    query_key: str
    match_type: str
    matched_keys: List[str]
    rows: List[IngredientRow]

    @property
    def matched(self) -> bool:
        return self.match_type != "no_match"


#: Salt and hydrate words that source labels add to a substance name
#: (``"sugammadex sodique"``, ``"neostigmine methylsulfate"``,
#: ``"cefoxitine sel de Na"``). Removed, after normalization, for the last
#: matching step only.
SALT_WORDS = frozenset(
    {
        "sodique",
        "disodique",
        "potassique",
        "calcique",
        "magnesique",
        "chlorhydrate",
        "dichlorhydrate",
        "hydrochloride",
        "bromhydrate",
        "sulfate",
        "phosphate",
        "methylsulfate",
        "metilsulfate",
        "mesilate",
        "maleate",
        "tartrate",
        "bitartrate",
        "citrate",
        "acetate",
        "fumarate",
        "succinate",
        "besilate",
        "anhydre",
        "monohydrate",
        "dihydrate",
        "trihydrate",
        "hemihydrate",
        "base",
    }
)
_SALT_PHRASE = re.compile(r"\bsel de (?:na|sodium|k|potassium)\b")
_LINK_WORDS = frozenset({"de", "d'", "du"})


def strip_salts(key: str) -> str:
    """Drop salt and hydrate words (and the ``de`` they leave) from a key."""
    key = _SALT_PHRASE.sub(" ", key)
    words = [w for w in key.split() if w not in SALT_WORDS]
    while words and words[0] in _LINK_WORDS:
        words.pop(0)
    while words and words[-1] in _LINK_WORDS:
        words.pop()
    return " ".join(words)


class BrandIndex:
    """In-memory index over the precomputed table + the source-alias layer."""

    def __init__(
        self,
        by_key: Dict[str, List[IngredientRow]],
        aliases: Optional[Dict[str, str]] = None,
    ) -> None:
        self.by_key = by_key
        self.aliases = aliases or {}
        #: normalized French substance name -> its mono brands' rows.
        self.by_substance: Dict[str, List[IngredientRow]] = {}
        for rows in by_key.values():
            for row in rows:
                if row.is_combination == "0" and row.substance_fr:
                    name = normalize(row.substance_fr)
                    self.by_substance.setdefault(name, []).append(row)

    def lookup(self, query: str) -> MatchResult:
        """Resolve *query* to its ingredient rows (see module docstring for order)."""
        key = brand_key(query)

        # Manual layer: redirect a non-RUIM / misspelled source label to a real
        # brand key before matching. An alias hit is reported as "alias".
        if key in self.aliases:
            key = self.aliases[key]
            if key in self.by_key:
                return MatchResult(query, key, "alias", [key], list(self.by_key[key]))

        if not key:
            return MatchResult(query, key, "no_match", [], [])

        found = self._match(query, key)
        if found.matched:
            return found
        # Last resort: the label is a substance plus its salt.
        bare = strip_salts(key)
        if bare and bare != key:
            found = self._match(query, bare)
            if found.matched:
                return found
        return MatchResult(query, key, "no_match", [], [])

    def _match(self, query: str, key: str) -> MatchResult:
        # (1) exact brand-key hit.
        if key in self.by_key:
            return MatchResult(query, key, "exact", [key], list(self.by_key[key]))

        # (2) the key names a substance: its mono brands only, so that a bare
        # ingredient does not fan out to every combination starting with it
        # ("paracetamol" -> not "paracetamol cafeine codeine ...").
        if key in self.by_substance:
            rows = list(self.by_substance[key])
            keys = sorted({r.brand_key for r in rows})
            return MatchResult(query, key, "substance", keys, rows)

        # (3) whole-word prefix over the table's keys.
        prefix = key + " "
        matched_keys = sorted(k for k in self.by_key if k.startswith(prefix))
        if matched_keys:
            rows: List[IngredientRow] = []
            for k in matched_keys:
                rows.extend(self.by_key[k])
            return MatchResult(query, key, "prefix", matched_keys, rows)

        return MatchResult(query, key, "no_match", [], [])


def _load_by_key(package: str, name: str) -> Dict[str, List[IngredientRow]]:
    by_key: Dict[str, List[IngredientRow]] = {}
    with io.TextIOWrapper(
        resources.files(package).joinpath(name).open("rb"), encoding="utf-8", newline=""
    ) as fh:
        for raw in csv.DictReader(fh):
            row = IngredientRow.from_dict(raw)
            if row.brand_key:
                by_key.setdefault(row.brand_key, []).append(row)
    return by_key


def load_index(package: str = _REFS_PACKAGE) -> BrandIndex:
    """Load the shipped table + aliases into a :class:`BrandIndex`.

    Reads the package data via :mod:`importlib.resources`, so it works whether the
    package is installed as a wheel or run from a source checkout.
    """
    by_key = _load_by_key(package, BRAND_INGREDIENT_MAP)
    aliases: Dict[str, str] = {}
    alias_res = resources.files(package).joinpath(SOURCE_ALIASES)
    if alias_res.is_file():
        with resources.as_file(alias_res) as path:
            aliases = load_source_aliases(path)
    return BrandIndex(by_key, aliases)


_DEFAULT_INDEX: Optional[BrandIndex] = None


def default_index() -> BrandIndex:
    """Return the process-wide default index, loading it on first use."""
    global _DEFAULT_INDEX
    if _DEFAULT_INDEX is None:
        _DEFAULT_INDEX = load_index()
    return _DEFAULT_INDEX


def lookup(query: str, index: Optional[BrandIndex] = None) -> MatchResult:
    """Resolve *query* against the shipped table (or a supplied *index*)."""
    return (index or default_index()).lookup(query)
