"""Build-side resolution: French moieties -> individual ATC -> RxNorm ingredient.

This module holds the resolution logic the ``build-refs`` orchestrator runs to
precompute ``brand_ingredient_map.csv``. The design invariant is strict:

    **The French name -> ATC step is a RUIM lookup. Athena is used only for the
    ATC -> RxNorm-Ingredient step.**

We never match a French substance string against Athena (no INN-name matching, no
ingredient name/synonym matching). RUIM already carries the ATC for every
speciality (``CIS.csv:codeATC``), and a substance's *individual* 5th-level ATC is
recovered from the RUIM specialities where that substance is the sole moiety (its
mono drugs). Athena's role is reduced to the one thing it is authoritative for:
turning an ATC code into an RxNorm ingredient concept.

Parts:

* :func:`load_athena_index` — stream the Athena vocabulary (via the hardened
  reader in :mod:`ruim2rxnorm.etl.athena_io`) into the in-memory
  :class:`AthenaIndex`: only the ATC->RxNorm-Ingredient map, the ATC-5th INN
  *labels* (carried through for display), and the ingredient-by-id table (for
  curated-override concept_id lookup). It deliberately holds **no** name->ATC or
  name->ingredient index, so the resolver structurally cannot name-match Athena.
* :func:`brand_moieties` — a brand's CIS rows + the RUIM composition/substance
  tables -> its de-duplicated therapeutic moieties (mono = 1, combination = >=2).
* :func:`build_substance_atc_index` — RUIM ``codeSubstance`` -> its individual
  (mono) 5th-level ATC, from specialities that contain only that one moiety.
* :class:`Resolver` — a single moiety -> :class:`Resolution`: curated override,
  else RUIM substance->ATC, else an explicit ``unmapped`` failure; the resolved
  ATC is turned into an RxNorm ingredient via Athena.

Relationship selection for the ATC->Ingredient map mirrors the verified ETL: keep
every ingredient-yielding ATC relationship *except* ``ATC - RxNorm sec up`` (broad
many-to-one), each ``(atc, ingredient)`` pair tagged with its most authoritative
relationship. The resolver only ever queries **mono** ATC-5th codes, so a
combination ATC that lists several ingredients here is never expanded.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from ..normalize import normalize
from . import athena_io
from .athena_io import (
    CONCEPT,
    CONCEPT_RELATIONSHIP,
    read_table,
    read_vocabulary_version,
)
from .ruim_io import CisRow, Substance

# --- Athena vocabulary / class / relationship configuration ----------------

VOCABULARIES: Tuple[str, ...] = ("ATC", "RxNorm", "RxNorm Extension")
_RXNORM_VOCABS = frozenset(("RxNorm", "RxNorm Extension"))
_INGREDIENT_CLASS = "Ingredient"
_ATC5_CLASS = "ATC 5th"

#: ATC -> RxNorm Ingredient relationships to keep, best first. ``ATC - RxNorm
#: sec up`` is deliberately excluded (broad many-to-one).
_RELATIONSHIP_PRIORITY: Tuple[str, ...] = (
    "ATC - RxNorm pr lat",
    "ATC - RxNorm pr up",
    "ATC - RxNorm sec lat",
    "Maps to",
    "Subsumes",
)
_KEPT_RELATIONSHIPS = frozenset(_RELATIONSHIP_PRIORITY)
_RELATIONSHIP_RANK = {rel: i for i, rel in enumerate(_RELATIONSHIP_PRIORITY)}


@dataclass(frozen=True)
class Ingredient:
    """An RxNorm / RxNorm Extension Ingredient concept."""

    concept_id: str
    code: str
    name: str
    vocab: str
    standard: str = ""

    @property
    def rank(self) -> Tuple[int, int, int]:
        """Preference key (lower is better): standard RxNorm concepts win."""
        return (
            0 if self.vocab == "RxNorm" else 1,
            0 if self.standard == "S" else 1,
            int(self.concept_id) if self.concept_id.isdigit() else 0,
        )


@dataclass
class AthenaIndex:
    """In-memory Athena indexes used by the resolver.

    Intentionally minimal: it maps ATC -> ingredient and holds ingredient
    identities, but carries **no** French/English name -> ATC or name ->
    ingredient index. Athena is the ATC -> RxNorm authority only.
    """

    #: mono/any ATC code -> its mapped RxNorm ingredients (deduped, best-ranked).
    atc_to_ingredients: Dict[str, List[Ingredient]] = field(default_factory=dict)
    #: ATC-5th code -> its INN concept name (a display label, carried through).
    atc5_name_by_code: Dict[str, str] = field(default_factory=dict)
    #: RxNorm concept_id -> Ingredient (for curated-override id lookup).
    ingredient_by_id: Dict[str, Ingredient] = field(default_factory=dict)
    #: Athena vocabulary versions (for the manifest).
    versions: Dict[str, str] = field(default_factory=dict)

    def best_ingredient(self, atc_code: str) -> Optional[Ingredient]:
        """The single best RxNorm ingredient for a (mono) ATC code, if any."""
        ings = self.atc_to_ingredients.get(atc_code)
        return min(ings, key=lambda i: i.rank) if ings else None


def load_athena_index(athena_dir: Union[str, Path]) -> AthenaIndex:
    """Stream an Athena dump into an :class:`AthenaIndex`.

    Two passes over ``CONCEPT`` / ``CONCEPT_RELATIONSHIP``, filtered to ATC +
    RxNorm + RxNorm Extension. ``CONCEPT_SYNONYM`` is not read: the resolver never
    name-matches Athena, so ingredient synonyms are not needed here.
    """
    athena_dir = Path(athena_dir)
    idx = AthenaIndex()

    atc_code_by_id: Dict[str, str] = {}

    # Pass 1 — CONCEPT.
    for c in read_table(athena_dir, CONCEPT):
        vocab = c.get("vocabulary_id", "")
        if vocab == "ATC":
            # Keep ATC source concepts regardless of invalid_reason (stable ids;
            # edge/target validity gates the mapping).
            code = c.get("concept_code", "")
            atc_code_by_id[c["concept_id"]] = code
            if c.get("concept_class_id") == _ATC5_CLASS:
                # Athena ATC-5th names carry a route suffix, e.g.
                # "amlodipine; oral" — strip it to recover the bare INN label.
                base = c.get("concept_name", "").split(";", 1)[0].strip()
                idx.atc5_name_by_code[code] = base
        elif vocab in _RXNORM_VOCABS:
            if c.get("invalid_reason") or c.get("concept_class_id") != _INGREDIENT_CLASS:
                continue
            ing = Ingredient(
                concept_id=c["concept_id"],
                code=c.get("concept_code", ""),
                name=c.get("concept_name", ""),
                vocab=vocab,
                standard=c.get("standard_concept", ""),
            )
            idx.ingredient_by_id[ing.concept_id] = ing

    # Pass 2 — CONCEPT_RELATIONSHIP: ATC -> Ingredient, best relationship per pair.
    best_rel: Dict[Tuple[str, str], str] = {}
    for r in read_table(athena_dir, CONCEPT_RELATIONSHIP):
        if r.get("invalid_reason"):
            continue
        rel = r.get("relationship_id", "")
        if rel not in _KEPT_RELATIONSHIPS:
            continue
        code = atc_code_by_id.get(r.get("concept_id_1", ""))
        c2 = r.get("concept_id_2", "")
        if code is None or c2 not in idx.ingredient_by_id:
            continue
        key = (code, c2)
        cur = best_rel.get(key)
        if cur is None or _RELATIONSHIP_RANK[rel] < _RELATIONSHIP_RANK[cur]:
            best_rel[key] = rel
    for (code, cid) in best_rel:
        idx.atc_to_ingredients.setdefault(code, []).append(idx.ingredient_by_id[cid])

    for vocab in (*VOCABULARIES, "None"):
        try:
            idx.versions[vocab] = read_vocabulary_version(athena_dir, vocab)
        except (KeyError, FileNotFoundError):
            continue

    return idx


# --- Composition: brand -> therapeutic moieties -----------------------------


@dataclass(frozen=True)
class Moiety:
    """A therapeutic moiety of a brand: RUIM code + French name (+ synonyms)."""

    code: str
    name_fr: str
    synonyms_fr: List[str] = field(default_factory=list)


def brand_moieties(
    cis_rows: List[CisRow],
    compositions: Dict[str, List[str]],
    substances: Dict[str, Substance],
) -> List[Moiety]:
    """Union the ``fraction thérapeutique`` moieties across a brand's CIS rows.

    De-duplicated by ``codeSubstance`` (first-seen order preserved). Mono drug =>
    1 moiety; combination => >=2. Names resolved via *substances*.
    """
    seen: set = set()
    out: List[Moiety] = []
    for row in cis_rows:
        for code in compositions.get(row.cis, []):
            if code in seen:
                continue
            seen.add(code)
            sub = substances.get(code)
            out.append(
                Moiety(
                    code=code,
                    name_fr=sub.name_fr if sub else "",
                    synonyms_fr=list(sub.synonyms_fr) if sub else [],
                )
            )
    return out


def build_substance_atc_index(
    cis_rows: List[CisRow],
    compositions: Dict[str, List[str]],
) -> Dict[str, str]:
    """RUIM ``codeSubstance`` -> its individual (mono) 5th-level ATC.

    A substance's *individual* ATC is taken from RUIM specialities that contain
    **only that one moiety** (its mono drugs): for such a speciality the
    ``CIS.codeATC`` is the substance's own 5th-level ATC. Combination specialities
    are skipped — their ``codeATC`` is the *combination* class (e.g. ``C09BB04``),
    never a moiety's individual code. On the rare substance carrying several mono
    ATCs, the lexicographically smallest is kept for determinism.

    This is the RUIM half of the bridge: French name -> ATC without ever touching
    Athena. A substance never sold alone (e.g. clavulanic acid) simply does not
    appear here, and the resolver fails it explicitly unless a curated override
    supplies a mapping.
    """
    out: Dict[str, str] = {}
    for row in cis_rows:
        codes = compositions.get(row.cis)
        if not codes or len(codes) != 1:
            continue
        atc = row.code_atc
        if not atc:
            continue
        sub = codes[0]
        if sub not in out or atc < out[sub]:
            out[sub] = atc
    return out


# --- Substance -> individual ATC + RxNorm ingredient ------------------------


@dataclass(frozen=True)
class Override:
    """A curated substance override (by RUIM code or by name)."""

    atc: str
    rxnorm_concept_id: str


@dataclass(frozen=True)
class Resolution:
    """Result of resolving one moiety to a RxNorm ingredient."""

    substance_code: str
    substance_fr: str
    individual_atc: str
    atc_name: str
    ingredient: Optional[Ingredient]
    status: str  # "mapped" | "unmapped"
    reason: str


def load_overrides(path: Union[str, Path]) -> Dict[str, Override]:
    """Load ``overrides.csv`` into ``key -> Override``.

    ``overrides.csv`` is the manually curated exception layer, empty by default
    and grown only when a real substance fails to resolve. ``substance_code_or_name``
    may be a RUIM ``codeSubstance`` (matched raw against ``Moiety.code``) or a
    French name (matched normalized); since the row does not say which, each
    override is indexed under **both** the raw string and its normalized form.
    A curated ``rxnorm_concept_id`` is a human-picked id (looked up by id, not by
    name) and does not violate the "no Athena name-matching" invariant. Rows with
    neither an ATC nor an ``rxnorm_concept_id`` are placeholders and are skipped.
    """
    out: Dict[str, Override] = {}
    with open(path, "r", encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            atc = (r.get("atc", "") or "").strip()
            rx = (r.get("rxnorm_concept_id", "") or "").strip()
            if not atc and not rx:
                continue
            raw_key = (r.get("substance_code_or_name", "") or "").strip()
            if not raw_key:
                continue
            ov = Override(atc=atc, rxnorm_concept_id=rx)
            out[raw_key] = ov
            norm_key = normalize(raw_key)
            if norm_key:
                out.setdefault(norm_key, ov)
    return out


class Resolver:
    """Resolve a :class:`Moiety` to an individual ATC + RxNorm ingredient.

    Order: curated override -> RUIM substance->ATC -> explicit failure. Only after
    an ATC is in hand (from RUIM or an override) is Athena consulted, and only to
    turn that ATC into an RxNorm ingredient. There is no name-matching fallback:
    a moiety with no RUIM mono ATC and no override fails as ``no_ruim_mono_atc``.
    """

    def __init__(
        self,
        index: AthenaIndex,
        substance_atc: Optional[Dict[str, str]] = None,
        overrides: Optional[Dict[str, Override]] = None,
    ) -> None:
        self.index = index
        self.substance_atc = substance_atc or {}
        self.overrides = overrides or {}

    def _mapped(self, moiety, atc, ing, reason="") -> Resolution:
        return Resolution(
            substance_code=moiety.code,
            substance_fr=moiety.name_fr,
            individual_atc=atc,
            atc_name=self.index.atc5_name_by_code.get(atc, ""),
            ingredient=ing,
            status="mapped",
            reason=reason,
        )

    def _unmapped(self, moiety, atc, reason) -> Resolution:
        return Resolution(
            substance_code=moiety.code,
            substance_fr=moiety.name_fr,
            individual_atc=atc,
            atc_name=self.index.atc5_name_by_code.get(atc, ""),
            ingredient=None,
            status="unmapped",
            reason=reason,
        )

    def _ingredient_for_atc(self, moiety, atc, reason) -> Resolution:
        """ATC (from RUIM or an override) -> RxNorm ingredient, the sole Athena step."""
        ing = self.index.best_ingredient(atc)
        if ing is not None:
            return self._mapped(moiety, atc, ing, reason)
        return self._unmapped(moiety, atc, "atc_not_in_rxnorm_map")

    def resolve(self, moiety: Moiety) -> Resolution:
        """Resolve *moiety*: override -> RUIM ATC bridge -> explicit failure."""
        # 1. Curated override (by code, else by normalized name).
        ov = self.overrides.get(moiety.code) or self.overrides.get(normalize(moiety.name_fr))
        if ov is not None:
            if ov.rxnorm_concept_id and ov.rxnorm_concept_id in self.index.ingredient_by_id:
                return self._mapped(moiety, ov.atc, self.index.ingredient_by_id[ov.rxnorm_concept_id], "override")
            if ov.atc:
                return self._ingredient_for_atc(moiety, ov.atc, "override")

        # 2. RUIM: substance code -> its individual (mono) 5th-level ATC.
        atc = self.substance_atc.get(moiety.code)
        if atc:
            # 3. Athena: ATC -> RxNorm ingredient (the ONLY Athena lookup).
            return self._ingredient_for_atc(moiety, atc, "")

        # 4. Explicit failure — no RUIM mono ATC and no override. Never name-match.
        return self._unmapped(moiety, "", "no_ruim_mono_atc")
