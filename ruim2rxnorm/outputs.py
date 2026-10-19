"""Output writers: mapping CSV, OMOP ``SOURCE_TO_CONCEPT_MAP``, optional Usagi CSV.

The runtime path ends here. :mod:`ruim2rxnorm.lookup` turns each query into a
:class:`~ruim2rxnorm.lookup.MatchResult` (all matched ingredient rows, mapped and
unmapped alike); these writers serialise a stream of results into the three
curator/OMOP-facing shapes.

Three outputs, all one *row per individual ingredient* — so a combination or an
umbrella brand naturally expands to several rows:

* **mapping CSV** (:func:`write_mapping_csv`) — the human-readable audit table:
  the input name, the matched ``brand_key`` and how it matched, and the resolved
  ingredient columns straight from ``brand_ingredient_map.csv``
  (``individual_atc`` / ``rxnorm_*`` / ``status`` / ``reason``). Unmapped moieties
  and whole ``no_match`` queries appear too, so the file doubles as a coverage
  report.
* **SOURCE_TO_CONCEPT_MAP** (:func:`write_stcm_csv`) — the loadable OMOP STCM
  table (9 spec columns). ``target_concept_id`` is the RxNorm ingredient
  *concept_id* (``rxnorm_concept_id``, e.g. COVERAM -> 1373225 + 1332418); an
  unresolved moiety maps to ``target_concept_id = 0`` with the resolver reason in
  ``invalid_reason`` so the gap is explicit, never silently dropped.
* **Usagi CSV** (:func:`write_usagi_csv`) — optional input for the OHDSI Usagi
  review tool, for a curator to approve/fix the ambiguous or unmapped rows.

Every writer accepts a destination path (``str``/``os.PathLike``) or an already
open text file object, and a lower-level ``*_rows`` generator is exposed for each
so the shapes can be tested without touching disk.
"""

from __future__ import annotations

import csv
import os
from contextlib import contextmanager
from typing import Dict, Iterable, Iterator, List

from .lookup import IngredientRow, MatchResult

# --- STCM constants ----------------------------------------------------------

#: Custom OMOP source vocabulary id for the French ANSM brand names.
SOURCE_VOCABULARY_ID = "FR_ANSM_BRAND"
#: The only target vocabulary we emit into (ingredient level).
TARGET_VOCABULARY_ID = "RxNorm"
#: Open validity window for every emitted mapping row.
VALID_START_DATE = "1970-01-01"
VALID_END_DATE = "2099-12-31"

#: OMOP SOURCE_TO_CONCEPT_MAP columns, in spec order.
STCM_COLUMNS: List[str] = [
    "source_code",
    "source_concept_id",
    "source_vocabulary_id",
    "source_code_description",
    "target_concept_id",
    "target_vocabulary_id",
    "valid_start_date",
    "valid_end_date",
    "invalid_reason",
]

#: Human-readable mapping / coverage CSV columns.
MAPPING_COLUMNS: List[str] = [
    "input_name",
    "brand_key",
    "match_type",
    "n_specialities",
    "cis_atc",
    "substance_fr",
    "individual_atc",
    "libelle_atc",
    "rxnorm_concept_id",
    "rxnorm_code",
    "rxnorm_name",
    "is_combination",
    "status",
    "reason",
]

#: Usagi input columns (curator review of ambiguous / unmapped rows).
USAGI_COLUMNS: List[str] = [
    "sourceCode",
    "sourceName",
    "sourceFrequency",
    "conceptId",
    "conceptName",
    "mappingStatus",
]


# --- row generators ----------------------------------------------------------


def mapping_rows(results: Iterable[MatchResult]) -> Iterator[Dict[str, str]]:
    """Yield one mapping-CSV row per matched ingredient (a placeholder per
    ``no_match`` query), preserving the order the results are given in."""
    for res in results:
        if not res.rows:
            yield {
                "input_name": res.query,
                "brand_key": res.query_key,
                "match_type": res.match_type,
                "n_specialities": "",
                "cis_atc": "",
                "substance_fr": "",
                "individual_atc": "",
                "libelle_atc": "",
                "rxnorm_concept_id": "",
                "rxnorm_code": "",
                "rxnorm_name": "",
                "is_combination": "",
                "status": res.match_type,  # "no_match"
                "reason": "",
            }
            continue
        for row in res.rows:
            yield {
                "input_name": res.query,
                "brand_key": row.brand_key,
                "match_type": res.match_type,
                "n_specialities": row.n_specialities,
                "cis_atc": row.cis_atc,
                "substance_fr": row.substance_fr,
                "individual_atc": row.individual_atc,
                "libelle_atc": row.libelle_atc,
                "rxnorm_concept_id": row.rxnorm_concept_id,
                "rxnorm_code": row.rxnorm_code,
                "rxnorm_name": row.rxnorm_name,
                "is_combination": row.is_combination,
                "status": row.status,
                "reason": row.reason,
            }


def _target_concept_id(row: IngredientRow) -> str:
    """STCM target: the RxNorm ingredient concept_id, or ``0`` when unmapped."""
    return row.rxnorm_concept_id if row.is_mapped else "0"


def stcm_rows(
    results: Iterable[MatchResult],
    source_vocabulary_id: str = SOURCE_VOCABULARY_ID,
) -> Iterator[Dict[str, str]]:
    """Yield OMOP STCM rows — one per individual ingredient.

    ``source_code`` is the matched (normalized) brand key, so a combination or an
    umbrella brand emits several rows under one code; ``source_code_description``
    keeps the original query text. An unmapped moiety is emitted with
    ``target_concept_id = 0`` and its resolver reason in ``invalid_reason``.
    Queries that matched nothing are skipped (there is no brand to map).
    """
    for res in results:
        for row in res.rows:
            mapped = row.is_mapped
            yield {
                "source_code": row.brand_key,
                "source_concept_id": "0",
                "source_vocabulary_id": source_vocabulary_id,
                "source_code_description": res.query,
                "target_concept_id": _target_concept_id(row),
                "target_vocabulary_id": TARGET_VOCABULARY_ID,
                "valid_start_date": VALID_START_DATE,
                "valid_end_date": VALID_END_DATE,
                "invalid_reason": "" if mapped else row.reason,
            }


def usagi_rows(results: Iterable[MatchResult]) -> Iterator[Dict[str, str]]:
    """Yield Usagi input rows — mapped ingredients pre-filled and ``APPROVED``,
    unmapped ones left ``UNCHECKED`` for a curator to resolve."""
    for res in results:
        for row in res.rows:
            mapped = row.is_mapped
            yield {
                "sourceCode": row.brand_key,
                "sourceName": res.query,
                "sourceFrequency": row.n_specialities or "1",
                "conceptId": row.rxnorm_concept_id if mapped else "",
                "conceptName": row.rxnorm_name if mapped else "",
                "mappingStatus": "APPROVED" if mapped else "UNCHECKED",
            }


# --- writers -----------------------------------------------------------------


@contextmanager
def _text_sink(dest):
    """Yield a text file for *dest*, opening a path but leaving a handle open."""
    if isinstance(dest, (str, os.PathLike)):
        fh = open(dest, "w", encoding="utf-8", newline="")
        try:
            yield fh
        finally:
            fh.close()
    else:
        yield dest


def _write_csv(dest, columns: List[str], rows: Iterable[Dict[str, str]]) -> int:
    """Write *rows* (dicts keyed by *columns*) to *dest*; return the row count."""
    with _text_sink(dest) as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        count = 0
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def write_mapping_csv(results: Iterable[MatchResult], dest) -> int:
    """Write the human-readable mapping / coverage CSV; return rows written."""
    return _write_csv(dest, MAPPING_COLUMNS, mapping_rows(results))


def write_stcm_csv(
    results: Iterable[MatchResult],
    dest,
    source_vocabulary_id: str = SOURCE_VOCABULARY_ID,
) -> int:
    """Write the OMOP ``SOURCE_TO_CONCEPT_MAP`` CSV; return rows written."""
    return _write_csv(dest, STCM_COLUMNS, stcm_rows(results, source_vocabulary_id))


def write_usagi_csv(results: Iterable[MatchResult], dest) -> int:
    """Write the optional Usagi review CSV; return rows written."""
    return _write_csv(dest, USAGI_COLUMNS, usagi_rows(results))
