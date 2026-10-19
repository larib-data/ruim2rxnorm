"""Orchestrate the full RUIM + Athena resolution into the one shipped table.

This is the ``build-refs`` ETL: the **only** part of ``ruim2rxnorm`` that reads
the downloaded source vocabularies. It ties together the three build stages —

* :mod:`ruim2rxnorm.etl.ruim_io`  — RUIM ``CIS`` / ``Compositions`` /
  ``Substances`` readers (brand -> CIS rows, CIS -> moieties, substance names);
* :mod:`ruim2rxnorm.etl.resolve`  — the Athena ATC->RxNorm-Ingredient index and
  the RUIM-first :class:`~ruim2rxnorm.etl.resolve.Resolver`;

— and precomputes, for **every** RUIM brand key, its list of individual active
ingredients (each carrying its own 5th-level ATC and RxNorm ingredient). The
result is written as a single table:

* ``brand_ingredient_map.csv`` — one row per ``(brand_key, individual
  ingredient)``; the *only* large artifact the runtime ships and reads.
* ``REFS_MANIFEST.json`` — provenance (Athena vocabulary versions, source dirs,
  build timestamp), row/brand counts, and coverage stats.

Design invariant (inherited from :mod:`resolve`): French name -> ATC is a RUIM
lookup; Athena is consulted **only** for the ATC -> RxNorm-Ingredient step. A
combination is decomposed into its RUIM moieties, each resolved through *its own*
mono speciality — the combination's own ATC class is never expanded.
"""

from __future__ import annotations

import csv
import datetime as _dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from . import resolve as _resolve
from . import ruim_io
from .resolve import (
    Resolver,
    brand_moieties,
    build_substance_atc_index,
    load_athena_index,
    load_overrides,
)

# --- Output artifacts -------------------------------------------------------

BRAND_INGREDIENT_MAP = "brand_ingredient_map.csv"
MANIFEST = "REFS_MANIFEST.json"
OVERRIDES = "overrides.csv"

#: Columns of ``brand_ingredient_map.csv`` (see the module docstring / plan).
COLUMNS: Tuple[str, ...] = (
    "brand_key",
    "brand_display",
    "n_specialities",
    "cis_atc",
    "substance_code",
    "substance_fr",
    "individual_atc",
    "libelle_atc",
    "rxnorm_concept_id",
    "rxnorm_code",
    "rxnorm_name",
    "is_combination",
    "status",
    "reason",
)

#: ``rxnorm_concept_id`` placeholder for an unmapped ingredient (mirrors the STCM
#: ``target_concept_id = 0`` convention the runtime emits).
_NO_CONCEPT = "0"

#: Default minimum share of specialities that must reach a RxNorm ingredient for
#: ``--validate`` to pass. The real Athena/RUIM dumps clear ~0.94; kept modestly
#: below that so a genuinely healthy build never trips, a broken one does.
DEFAULT_COVERAGE_THRESHOLD = 0.90

#: Golden mapped ingredients re-checked by ``--validate``: brand_key -> substrings
#: that must each appear (case-insensitively) in some **mapped** ingredient name.
_GOLDEN_MAPPED: Dict[str, Tuple[str, ...]] = {
    "coveram": ("perindopril", "amlodipine"),
    "doliprane": ("acetaminophen",),
    "augmentin": ("amoxicillin",),
}
#: Golden moieties that must be **present as a row** (any status) — this is how we
#: assert a combination is decomposed even when a moiety is an explicit failure.
#: This is data-drop-agnostic (it runs against the tiny test fixtures too), so it
#: only requires *presence*: clavulanate maps in the shipped refs via a curated
#: override (refs/overrides.csv), but the fixture build ships none and leaves it an
#: explicit failure — both are valid decompositions of the combination.
_GOLDEN_PRESENT: Dict[str, Tuple[str, ...]] = {
    "augmentin": ("clavulan",),
}


class ValidationError(RuntimeError):
    """Raised when ``--validate`` finds a broken/incomplete build."""


@dataclass
class _BuildResult:
    """Rows + derived stats produced by :func:`_resolve_all`, for writing/validation."""

    rows: List[Tuple]
    n_brand_keys: int
    n_specialities: int
    specialities_reached: int
    n_mapped: int
    n_unmapped: int
    athena_versions: Dict[str, str]


def _refs_dir() -> Path:
    """Package ``refs/`` directory (the shipped resource location)."""
    return Path(__file__).resolve().parent.parent / "refs"


def _tool_version() -> str:
    from .. import __version__

    return __version__


def build_refs(
    athena_dir: Union[str, Path],
    ruim_dir: Union[str, Path],
    out_dir: Optional[Union[str, Path]] = None,
    overrides_path: Optional[Union[str, Path]] = None,
    validate: bool = False,
    coverage_threshold: float = DEFAULT_COVERAGE_THRESHOLD,
) -> dict:
    """Build ``brand_ingredient_map.csv`` + manifest; return the manifest dict.

    Parameters
    ----------
    athena_dir:
        Directory with the Athena ``CONCEPT.csv`` / ``CONCEPT_RELATIONSHIP.csv`` /
        ``VOCABULARY.csv`` files (ATC + RxNorm + RxNorm Extension).
    ruim_dir:
        Directory with the RUIM ``CIS.csv`` / ``Compositions_qualitatives.csv`` /
        ``Substances.csv`` files.
    out_dir:
        Where to write the table + manifest. Defaults to the shipped ``refs/``.
    overrides_path:
        Curated substance override table. Defaults to ``refs/overrides.csv`` if it
        exists (missing file => no overrides).
    validate:
        Re-check invariants (golden mappings present, no duplicate mapped keys,
        non-empty table, coverage >= *coverage_threshold*, complete manifest) and
        raise :class:`ValidationError` on any failure.
    coverage_threshold:
        Minimum share of specialities reaching a RxNorm ingredient under
        ``--validate``.
    """
    athena_dir = Path(athena_dir)
    ruim_dir = Path(ruim_dir)
    out = Path(out_dir) if out_dir is not None else _refs_dir()
    out.mkdir(parents=True, exist_ok=True)

    if overrides_path is None:
        default_ov = _refs_dir() / OVERRIDES
        overrides_path = default_ov if default_ov.exists() else None
    overrides = load_overrides(overrides_path) if overrides_path is not None else {}

    result = _resolve_all(athena_dir, ruim_dir, overrides)

    _write_csv(out / BRAND_INGREDIENT_MAP, list(COLUMNS), result.rows)

    coverage_specialities = (
        result.specialities_reached / result.n_specialities if result.n_specialities else 0.0
    )
    manifest = {
        "tool": "ruim2rxnorm",
        "tool_version": _tool_version(),
        "built_at": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
        "athena_dir": str(athena_dir),
        "ruim_dir": str(ruim_dir),
        "vocabularies": list(_resolve.VOCABULARIES),
        "vocabulary_versions": result.athena_versions,
        "relationships_kept": list(_resolve._RELATIONSHIP_PRIORITY),
        "relationship_excluded": ["ATC - RxNorm sec up"],
        "row_counts": {BRAND_INGREDIENT_MAP: len(result.rows)},
        "distinct_brand_keys": result.n_brand_keys,
        "specialities": result.n_specialities,
        "ingredient_rows_mapped": result.n_mapped,
        "ingredient_rows_unmapped": result.n_unmapped,
        "coverage": {
            "specialities_reached": result.specialities_reached,
            "specialities_total": result.n_specialities,
            "specialities_reached_share": round(coverage_specialities, 4),
        },
    }
    (out / MANIFEST).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    if validate:
        _validate(result, manifest, coverage_threshold)

    return manifest


def _resolve_all(athena_dir: Path, ruim_dir: Path, overrides) -> _BuildResult:
    """Run the full brand -> ingredient resolution over every RUIM brand key."""
    index = load_athena_index(athena_dir)

    cis_rows = ruim_io.load_cis(ruim_dir)
    compositions = ruim_io.load_compositions(ruim_dir)
    substances = ruim_io.load_substances(ruim_dir)
    by_brand = ruim_io.group_by_brand_key(cis_rows)
    substance_atc = build_substance_atc_index(cis_rows, compositions)

    # French ATC label lookup: RUIM carries a French libelleATC for every ATC it
    # references (including the individual mono codes recovered from mono
    # specialities), so an individual ATC's French label is available here.
    atc_label_fr: Dict[str, str] = {}
    for row in cis_rows:
        if row.code_atc and row.code_atc not in atc_label_fr and row.libelle_atc:
            atc_label_fr[row.code_atc] = row.libelle_atc

    resolver = Resolver(index, substance_atc, overrides)

    rows: List[Tuple] = []
    n_mapped = n_unmapped = 0
    # brand_key -> {substance_code: status} for speciality-level coverage below.
    brand_status: Dict[str, Dict[str, str]] = {}

    for brand_key in sorted(by_brand):
        cis = by_brand[brand_key]
        moieties = brand_moieties(cis, compositions, substances)
        if not moieties:
            continue
        display = ruim_io.brand_display(cis[0].libelle)
        n_spec = len(cis)
        cis_atc = ";".join(sorted({r.code_atc for r in cis if r.code_atc}))
        is_combo = "1" if len(moieties) >= 2 else "0"

        status_by_sub = brand_status.setdefault(brand_key, {})

        # Resolve every moiety, then collapse *mapped* resolutions that land on the
        # same RxNorm ingredient into a single row. A brand routinely lists one
        # active moiety twice as a salt + its base (Actonel: acide risedronique +
        # risedronate monosodique -> risedronate; Oxycontin: oxycodone +
        # chlorhydrate d'oxycodone) or via two route ATCs; the shipped unit is
        # (brand_key x ingredient), so these are one ingredient, not two. The
        # differing salt substances are merged (";"-joined) for provenance.
        mapped_groups: Dict[str, List[Tuple]] = {}
        for m in moieties:
            res = resolver.resolve(m)
            status_by_sub[m.code] = res.status
            if res.status == "mapped":
                assert res.ingredient is not None
                mapped_groups.setdefault(res.ingredient.concept_id, []).append((m, res))
            else:
                n_unmapped += 1
                rows.append(
                    (
                        brand_key, display, str(n_spec), cis_atc,
                        m.code, m.name_fr, res.individual_atc,
                        atc_label_fr.get(res.individual_atc, ""),
                        _NO_CONCEPT, "", "", is_combo, res.status, res.reason,
                    )
                )

        for concept_id in sorted(mapped_groups):
            group = sorted(mapped_groups[concept_id], key=lambda mr: (mr[1].individual_atc, mr[0].code))
            ing = group[0][1].ingredient
            rep_atc = group[0][1].individual_atc  # deterministic: smallest (atc, code)
            sub_codes = ";".join(dict.fromkeys(m.code for m, _ in group))
            sub_names = ";".join(dict.fromkeys(m.name_fr for m, _ in group))
            reason = ";".join(dict.fromkeys(r.reason for _, r in group if r.reason))
            n_mapped += 1
            rows.append(
                (
                    brand_key, display, str(n_spec), cis_atc,
                    sub_codes, sub_names, rep_atc,
                    atc_label_fr.get(rep_atc, ""),
                    ing.concept_id, ing.code, ing.name,
                    is_combo, "mapped", reason,
                )
            )

    # Speciality-level coverage: a speciality "reaches a RxNorm ingredient" if at
    # least one of its own moieties mapped. Skip specialities with no moiety at all.
    n_specialities = specialities_reached = 0
    for row in cis_rows:
        codes = compositions.get(row.cis)
        if not codes or not row.brand_key:
            continue
        statuses = brand_status.get(row.brand_key, {})
        n_specialities += 1
        if any(statuses.get(code) == "mapped" for code in codes):
            specialities_reached += 1

    return _BuildResult(
        rows=rows,
        n_brand_keys=len({r[0] for r in rows}),
        n_specialities=n_specialities,
        specialities_reached=specialities_reached,
        n_mapped=n_mapped,
        n_unmapped=n_unmapped,
        athena_versions=index.versions,
    )


def _write_csv(path: Path, header: List[str], rows) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def _validate(result: _BuildResult, manifest: dict, coverage_threshold: float) -> None:
    errors: List[str] = []
    rows = result.rows

    if not rows:
        errors.append("brand_ingredient_map.csv is empty")

    # Column index helpers.
    col = {name: i for i, name in enumerate(COLUMNS)}
    ci_brand = col["brand_key"]
    ci_sub = col["substance_fr"]
    ci_name = col["rxnorm_name"]
    ci_status = col["status"]
    ci_rxid = col["rxnorm_concept_id"]

    # No duplicate (brand_key, rxnorm_concept_id) among *mapped* rows (unmapped
    # rows legitimately share the "0" placeholder).
    mapped_keys = [
        (r[ci_brand], r[ci_rxid]) for r in rows if r[ci_status] == "mapped"
    ]
    if len(mapped_keys) != len(set(mapped_keys)):
        errors.append("duplicate (brand_key, rxnorm_concept_id) among mapped rows")

    # Golden mapped ingredients present per brand.
    mapped_names: Dict[str, List[str]] = {}
    present_subs: Dict[str, List[str]] = {}
    for r in rows:
        present_subs.setdefault(r[ci_brand], []).append(r[ci_sub].lower())
        if r[ci_status] == "mapped":
            mapped_names.setdefault(r[ci_brand], []).append(r[ci_name].lower())
    for brand, needles in _GOLDEN_MAPPED.items():
        names = mapped_names.get(brand, [])
        for needle in needles:
            if not any(needle in n for n in names):
                errors.append(
                    f"golden mapping missing: {brand} -> {needle} (mapped: {names or 'nothing'})"
                )
    for brand, needles in _GOLDEN_PRESENT.items():
        subs = present_subs.get(brand, [])
        for needle in needles:
            if not any(needle in s for s in subs):
                errors.append(
                    f"golden moiety row missing: {brand} -> {needle} (rows: {subs or 'nothing'})"
                )

    # Coverage threshold.
    share = manifest["coverage"]["specialities_reached_share"]
    if share < coverage_threshold:
        errors.append(
            f"speciality coverage {share:.4f} below threshold {coverage_threshold:.4f}"
        )

    # Manifest completeness.
    for key in ("tool_version", "vocabulary_versions", "row_counts", "relationships_kept"):
        if not manifest.get(key):
            errors.append(f"manifest missing/empty field: {key}")
    if not manifest.get("vocabulary_versions", {}).get("RxNorm"):
        errors.append("manifest missing RxNorm vocabulary_version")

    if errors:
        raise ValidationError(
            "build-refs --validate failed:\n  - " + "\n  - ".join(errors)
        )
