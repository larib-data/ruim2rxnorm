"""Runtime Rx-Risk classification: ATC codes -> comorbidity conditions (+ ICD-10).

Layered directly on top of :mod:`ruim2rxnorm.lookup`. ``lookup.default_index()``
already resolves a French brand name to its ATC codes; this module takes those
codes and derives which **Rx-Risk conditions** (comorbidities) a patient is being
treated for, per the *updated* Rx-Risk Index (Widagdo I, Kerr M, Kalisch Ellett
L, et al., "Validity of the Updated Rx-Risk Index", *Clin Interv Aging* — see
``PROVENANCE.md``). RxNorm resolution is not involved: Rx-Risk is ATC-only.

The mapping is shipped as ``refs/rxrisk_map.csv`` — one row per condition (52
rows), each carrying include/exclude ATC **patterns** and, for 20 of them, the
ICD-10-AM codes from the paper's Table 2 (output annotation only, never matched).

ATC matching model (see the plan / module transcription notes):

* a **prefix** pattern matches a code ``c`` iff ``c.startswith(prefix)`` (a full
  7-char ATC is just a length-7 prefix);
* a **range** pattern ``LOW-HIGH`` (equal-length bounds) matches iff
  ``LOW <= c[:len(LOW)] <= HIGH`` — ATC's fixed format makes the lexical
  comparison hierarchy-correct.

A condition is present for a code iff **some include pattern matches AND no
exclude pattern matches**. Evaluated per code and OR-ed across the query's codes,
so the exclude carve-outs stay per-drug (aspirin ``B01AC06`` -> Antiplatelets but
not Anticoagulants; lithium ``N05AN01`` -> Bipolar but not Antipsychotics).

Several Table-1 qualifiers cannot be evaluated from a single drug's ATC (PBS/RPBS
item codes, route/strength limits, sex restrictions, multi-medicine combination
rules, cross-condition exclusions). Those are **dropped** — matched on the plain
codes — and recorded per condition in the map's ``notes`` column. Scoring is
**unweighted**: the score is the count of distinct conditions (the updated paper
publishes no per-condition weights).
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from importlib import resources
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .lookup import MatchResult

#: Package subdirectory + file holding the shipped Rx-Risk map.
_REFS_PACKAGE = "ruim2rxnorm.refs"
RXRISK_MAP = "rxrisk_map.csv"


def _split_list(value: str) -> Tuple[str, ...]:
    """Parse a ``;``-joined CSV cell into a tuple of trimmed, non-empty tokens."""
    return tuple(tok.strip() for tok in (value or "").split(";") if tok.strip())


@dataclass(frozen=True)
class RxRiskCondition:
    """One Rx-Risk condition — a row of ``rxrisk_map.csv``.

    ``includes`` / ``excludes`` are ATC patterns (prefixes and/or ``LOW-HIGH``
    ranges); ``icd10`` are the Table-2 ICD-10-AM codes (empty for the 32
    conditions the paper leaves unmapped). ``is_new`` flags the 9 conditions
    added in this update; ``notes`` records dropped qualifiers / overlaps.
    """

    condition: str
    includes: Tuple[str, ...]
    excludes: Tuple[str, ...]
    icd10: Tuple[str, ...]
    is_new: bool
    notes: str

    @classmethod
    def from_dict(cls, row: Dict[str, str]) -> "RxRiskCondition":
        return cls(
            condition=(row.get("condition", "") or "").strip(),
            includes=_split_list(row.get("atc_include", "")),
            excludes=_split_list(row.get("atc_exclude", "")),
            icd10=_split_list(row.get("icd10", "")),
            is_new=(row.get("is_new", "") or "").strip() == "1",
            notes=(row.get("notes", "") or "").strip(),
        )


def _pattern_matches(pattern: str, code: str) -> bool:
    """True iff ATC *code* matches *pattern* (prefix or ``LOW-HIGH`` range)."""
    if "-" in pattern:
        low, _, high = pattern.partition("-")
        low, high = low.strip(), high.strip()
        # Equal-length bounds; compare the code's matching-length prefix lexically.
        return low <= code[: len(low)] <= high
    return code.startswith(pattern)


def _code_matches_condition(code: str, cond: RxRiskCondition) -> bool:
    """Include-minus-exclude test of a single ATC *code* against *cond*."""
    if not any(_pattern_matches(p, code) for p in cond.includes):
        return False
    return not any(_pattern_matches(p, code) for p in cond.excludes)


class RxRiskIndex:
    """In-memory Rx-Risk map: ATC codes -> matched conditions."""

    def __init__(self, conditions: Sequence[RxRiskCondition]) -> None:
        self.conditions: Tuple[RxRiskCondition, ...] = tuple(conditions)

    @classmethod
    def load(cls, package: str = _REFS_PACKAGE, name: str = RXRISK_MAP) -> "RxRiskIndex":
        """Load the shipped ``rxrisk_map.csv`` via :mod:`importlib.resources`."""
        conditions: List[RxRiskCondition] = []
        with io.TextIOWrapper(
            resources.files(package).joinpath(name).open("rb"),
            encoding="utf-8",
            newline="",
        ) as fh:
            for raw in csv.DictReader(fh):
                cond = RxRiskCondition.from_dict(raw)
                if cond.condition:
                    conditions.append(cond)
        return cls(conditions)

    def conditions_for_atc(self, codes: Iterable[str]) -> List[RxRiskCondition]:
        """Conditions present for any code in *codes* (stable map order)."""
        code_list = [c for c in codes if c]
        return [
            cond
            for cond in self.conditions
            if any(_code_matches_condition(code, cond) for code in code_list)
        ]


_DEFAULT_RXRISK_INDEX: Optional[RxRiskIndex] = None


def default_rxrisk_index() -> RxRiskIndex:
    """Return the process-wide default Rx-Risk index, loading it on first use."""
    global _DEFAULT_RXRISK_INDEX
    if _DEFAULT_RXRISK_INDEX is None:
        _DEFAULT_RXRISK_INDEX = RxRiskIndex.load()
    return _DEFAULT_RXRISK_INDEX


def atc_codes_for(result: MatchResult) -> Set[str]:
    """Union of ``individual_atc`` + split ``cis_atc`` across *result*'s rows.

    Both the product-level (CIS) and decomposed-ingredient codes are used so a
    Table-1 prefix matches at whatever ATC level applies (COVERAM contributes
    ``C09BB04``/``C09AA04``/``C08CA01``). Blanks are dropped, all upper-cased.
    """
    codes: Set[str] = set()
    for row in result.rows:
        if row.individual_atc.strip():
            codes.add(row.individual_atc.strip().upper())
        for part in row.cis_atc.split(";"):
            if part.strip():
                codes.add(part.strip().upper())
    return codes


@dataclass(frozen=True)
class DrugRxRisk:
    """Rx-Risk outcome for a single input medicine name."""

    input_name: str
    query_key: str
    match_type: str
    brand_keys: Tuple[str, ...]
    atc_codes: Tuple[str, ...]
    conditions: Tuple[str, ...]

    @property
    def matched(self) -> bool:
        return self.match_type != "no_match"


@dataclass(frozen=True)
class ConditionHit:
    """A distinct condition present in the patient, with contributing drugs."""

    condition: RxRiskCondition
    contributing_drugs: Tuple[str, ...]


@dataclass(frozen=True)
class RxRiskProfile:
    """Per-patient Rx-Risk aggregate over a whole medicine list."""

    by_drug: Tuple[DrugRxRisk, ...]
    conditions: Tuple[ConditionHit, ...]
    unmatched_names: Tuple[str, ...]

    @property
    def score(self) -> int:
        """Unweighted Rx-Risk score = number of distinct conditions present."""
        return len(self.conditions)

    @classmethod
    def build(
        cls,
        results: Sequence[MatchResult],
        index: Optional[RxRiskIndex] = None,
    ) -> "RxRiskProfile":
        """Aggregate name->ATC *results* into a patient Rx-Risk profile.

        A medicine is "unmatched" when it triggers no Rx-Risk condition (no brand
        match, no ATC, or ATC that maps to nothing). Distinct conditions are kept
        in the map's stable order; each records the input names that produced it.
        """
        rxrisk = index or default_rxrisk_index()

        by_drug: List[DrugRxRisk] = []
        # condition name -> (RxRiskCondition, ordered list of contributing drugs)
        hits: Dict[str, Tuple[RxRiskCondition, List[str]]] = {}
        unmatched: List[str] = []

        for result in results:
            codes = sorted(atc_codes_for(result))
            conditions = rxrisk.conditions_for_atc(codes)
            by_drug.append(
                DrugRxRisk(
                    input_name=result.query,
                    query_key=result.query_key,
                    match_type=result.match_type,
                    brand_keys=tuple(result.matched_keys),
                    atc_codes=tuple(codes),
                    conditions=tuple(c.condition for c in conditions),
                )
            )
            if not conditions:
                unmatched.append(result.query)
                continue
            for cond in conditions:
                bucket = hits.setdefault(cond.condition, (cond, []))
                if result.query not in bucket[1]:
                    bucket[1].append(result.query)

        ordered = [
            ConditionHit(cond, tuple(hits[cond.condition][1]))
            for cond in rxrisk.conditions
            if cond.condition in hits
        ]
        return cls(
            by_drug=tuple(by_drug),
            conditions=tuple(ordered),
            unmatched_names=tuple(unmatched),
        )
