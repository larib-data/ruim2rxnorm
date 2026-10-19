"""RUIM source readers (build side only): ``CIS`` / ``Compositions`` / ``Substances``.

Part of the ETL, so it reads the **downloaded** RUIM bundle from a directory
(``--ruim-dir``) rather than any vendored copy — the RUIM CSVs are not shipped.
These readers feed the resolver in :mod:`ruim2rxnorm.etl.resolve`, which the
``build-refs`` orchestrator turns into the single precomputed
``brand_ingredient_map.csv``.

Three tables are consumed:

* ``CIS.csv`` — one row per speciality. The brand appears only as the leading
  text of ``libelle``; :func:`brand_key` extracts and normalizes it, and
  :func:`group_by_brand_key` builds ``brand_key -> [CisRow]`` (the unit the ETL
  iterates). (Relocated here from the former runtime ``load_ruim.py``; the
  query-time exact/prefix lookup moves to the runtime ``lookup.py`` in step 9.)
* ``Compositions_qualitatives.csv`` — the ``fraction thérapeutique`` rows give a
  speciality's **therapeutic moieties** (stable across salt variants), keyed by
  ``CIS`` -> ``[codeSubstance]``.
* ``Substances.csv`` — ``codeSubstance`` -> French name (+ synonyms) for those
  moiety codes.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Union

from ..normalize import normalize

CIS_CSV = "CIS.csv"
COMPOSITIONS_CSV = "Compositions_qualitatives.csv"
SUBSTANCES_CSV = "Substances.csv"

#: Composition relation kinds. The therapeutic moiety is the ``fraction
#: thérapeutique`` (present only when the moiety differs from the dosed salt,
#: e.g. a besilate/arginine combination); a salt-free mono drug has no such row,
#: so its ``substance active`` *is* the moiety.
FRACTION_THERAPEUTIQUE = "fraction thérapeutique"
SUBSTANCE_ACTIVE = "substance active"

# A ``libelle`` is ``<brand> [<strength>...] [, <form>...]``. The brand ends at
# the first dose token (a space followed by a digit) or the first comma —
# whichever comes first. Matched on the raw string, before normalization, so the
# comma boundary survives (``normalize`` turns commas into spaces).
_BRAND_CUT = re.compile(r",| \d")


@dataclass(frozen=True)
class CisRow:
    """One RUIM speciality (a row of ``CIS.csv``), reduced to the fields used downstream.

    ``cis`` is the join key to the composition table; ``brand_key`` is the
    normalized leading brand text (the grouping key); ``code_atc`` / ``libelle_atc``
    are the CIS-level ATC (a *combination* class for combos) carried as reference
    metadata only — never expanded into ingredients.
    """

    cis: str
    libelle: str
    brand_key: str
    code_atc: str
    libelle_atc: str
    forme: str
    voie: str


@dataclass(frozen=True)
class Substance:
    """A RUIM substance: its code, French name, and any French synonyms."""

    code: str
    name_fr: str
    synonyms_fr: List[str] = field(default_factory=list)


def brand_key(libelle: str) -> str:
    """Extract and normalize the brand key from a ``libelle`` (or a raw query).

    Cuts at the first ``" <digit>"`` (dose) or ``","`` (form) boundary and folds
    the head via :func:`~ruim2rxnorm.normalize.normalize`.

    >>> brand_key("COVERAM 5 mg/5 mg, comprimé")
    'coveram'
    >>> brand_key("HUMEX RHUME, comprimé et gélule")
    'humex rhume'
    >>> brand_key("DOLIPRANE 1000")
    'doliprane'
    """
    m = _BRAND_CUT.search(libelle)
    head = libelle[: m.start()] if m else libelle
    return normalize(head)


def brand_display(libelle: str) -> str:
    """Raw (un-normalized) leading brand text of a ``libelle``.

    Same cut as :func:`brand_key` but without folding, so the original casing is
    kept for human-readable descriptions.

    >>> brand_display("COVERAM 5 mg/5 mg, comprimé")
    'COVERAM'
    """
    m = _BRAND_CUT.search(libelle)
    head = libelle[: m.start()] if m else libelle
    return head.strip()


def _open(ruim_dir: Union[str, Path], name: str):
    return open(Path(ruim_dir) / name, "r", encoding="utf-8", newline="")


def load_source_aliases(path: Union[str, Path]) -> Dict[str, str]:
    """Load a ``source_aliases.csv`` into ``normalized source label -> brand_key``.

    A *source-label alias* is the curated ("manual") layer for raw input labels
    that are not RUIM brands — a local custom name (``BabyNoradrenaline``) or a
    foreign spelling. It only redirects the odd label to an existing RUIM brand
    key; RUIM still supplies the ATC. This is distinct from the substance-level
    ``overrides.csv`` (French moiety -> ATC/RxNorm), which the resolver applies.
    """
    aliases: Dict[str, str] = {}
    with open(path, "r", encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            label = normalize(r.get("source_label", "") or "")
            target = normalize(r.get("brand_key", "") or "")
            if label and target:
                aliases[label] = target
    return aliases


def load_cis(ruim_dir: Union[str, Path]) -> List[CisRow]:
    """Load ``CIS.csv`` from *ruim_dir* into a list of :class:`CisRow`.

    Comma-delimited UTF-8 with quoted fields (labels contain embedded commas),
    handled by the stdlib :mod:`csv` reader.
    """
    rows: List[CisRow] = []
    with _open(ruim_dir, CIS_CSV) as fh:
        for r in csv.DictReader(fh):
            libelle = r.get("libelle", "") or ""
            rows.append(
                CisRow(
                    cis=r.get("CIS", "") or "",
                    libelle=libelle,
                    brand_key=brand_key(libelle),
                    code_atc=r.get("codeATC", "") or "",
                    libelle_atc=r.get("libelleATC", "") or "",
                    forme=r.get("formeStandardisee", "") or "",
                    voie=r.get("voie", "") or "",
                )
            )
    return rows


def group_by_brand_key(rows: List[CisRow]) -> Dict[str, List[CisRow]]:
    """Group CIS rows into ``brand_key -> [CisRow]`` (rows with a key kept)."""
    by_key: Dict[str, List[CisRow]] = {}
    for row in rows:
        if row.brand_key:
            by_key.setdefault(row.brand_key, []).append(row)
    return by_key


def load_compositions(ruim_dir: Union[str, Path]) -> Dict[str, List[str]]:
    """Load ``CIS -> [codeSubstance]`` of therapeutic moieties.

    Per speciality: if it has any ``fraction thérapeutique`` rows, those are the
    moieties (the base forms, with the salt-bearing ``substance active`` rows
    ignored); otherwise the ``substance active`` rows are used (a salt-free mono
    drug has no fraction row). ``substance portant le dosage`` is always ignored.
    Codes are de-duplicated per CIS, first-seen order preserved.
    """
    fractions: Dict[str, List[str]] = {}
    actives: Dict[str, List[str]] = {}
    with _open(ruim_dir, COMPOSITIONS_CSV) as fh:
        for r in csv.DictReader(fh):
            rel = r.get("relationSubstance", "")
            if rel == FRACTION_THERAPEUTIQUE:
                bucket = fractions
            elif rel == SUBSTANCE_ACTIVE:
                bucket = actives
            else:
                continue
            cis = r.get("CIS", "") or ""
            code = r.get("codeSubstance", "") or ""
            if not cis or not code:
                continue
            codes = bucket.setdefault(cis, [])
            if code not in codes:
                codes.append(code)
    return {
        cis: fractions.get(cis) or actives[cis]
        for cis in (fractions.keys() | actives.keys())
    }


def load_substances(ruim_dir: Union[str, Path]) -> Dict[str, Substance]:
    """Load ``codeSubstance -> Substance`` (French name + synonyms) from ``Substances.csv``.

    ``synonymes_fr`` is a free-text field (comma-joined French inversions, but
    commas also occur *inside* a synonym), so it is kept whole as a single
    synonym string; the resolver folds it through the same normalization/salt
    logic as the primary name.
    """
    by_code: Dict[str, Substance] = {}
    with _open(ruim_dir, SUBSTANCES_CSV) as fh:
        for r in csv.DictReader(fh):
            code = r.get("codeSubstance", "") or ""
            if not code:
                continue
            syn_raw = (r.get("synonymes_fr", "") or "").strip()
            synonyms = [syn_raw] if syn_raw else []
            by_code[code] = Substance(
                code=code,
                name_fr=r.get("libelle_fr", "") or "",
                synonyms_fr=synonyms,
            )
    return by_code
