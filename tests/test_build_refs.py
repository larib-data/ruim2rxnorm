"""Tests for the build-refs orchestrator over the athena_mini + ruim_mini fixtures.

The orchestrator precomputes ``brand_ingredient_map.csv`` — one row per
``(brand_key, individual ingredient)`` — plus a provenance/coverage manifest. The
resolution invariants (RUIM-first, Athena only for ATC->RxNorm, combinations
decomposed) are exercised in ``test_resolve.py``; here we check the end-to-end
table shape, the golden brands, and ``--validate``.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from ruim2rxnorm.etl import build_refs as etl

ATHENA = Path(__file__).parent / "fixtures" / "athena_mini"
RUIM = Path(__file__).parent / "fixtures" / "ruim_mini"


def _read(path: Path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture()
def built(tmp_path):
    # No overrides in the fixture build (clavulanic acid stays an explicit failure).
    manifest = etl.build_refs(
        ATHENA, RUIM, out_dir=tmp_path, overrides_path=None, validate=True
    )
    return tmp_path, manifest


def _by_brand(rows):
    out = {}
    for r in rows:
        out.setdefault(r["brand_key"], []).append(r)
    return out


def test_table_header_and_columns(built):
    out, _ = built
    with open(out / etl.BRAND_INGREDIENT_MAP, encoding="utf-8", newline="") as fh:
        header = next(csv.reader(fh))
    assert header == list(etl.COLUMNS)


def test_coveram_decomposes_to_two_ingredients(built):
    out, _ = built
    by_brand = _by_brand(_read(out / etl.BRAND_INGREDIENT_MAP))
    coveram = {r["substance_fr"]: r for r in by_brand["coveram"]}
    assert set(coveram) == {"amlodipine", "périndopril"}
    # Each moiety resolves through its own mono speciality's individual ATC.
    assert coveram["amlodipine"]["individual_atc"] == "C08CA01"
    assert coveram["amlodipine"]["rxnorm_code"] == "17767"
    assert coveram["périndopril"]["individual_atc"] == "C09AA04"
    assert coveram["périndopril"]["rxnorm_code"] == "54552"
    # Combination flag + CIS-level (combination) ATC carried as reference metadata.
    assert all(r["is_combination"] == "1" for r in by_brand["coveram"])
    assert all(r["cis_atc"] == "C09BB04" for r in by_brand["coveram"])
    assert all(r["n_specialities"] == "2" for r in by_brand["coveram"])
    assert all(r["status"] == "mapped" for r in by_brand["coveram"])


def test_doliprane_mono(built):
    out, _ = built
    by_brand = _by_brand(_read(out / etl.BRAND_INGREDIENT_MAP))
    rows = by_brand["doliprane"]
    assert len(rows) == 1
    r = rows[0]
    assert r["substance_fr"] == "paracétamol"
    assert r["individual_atc"] == "N02BE01"
    assert "acetaminophen" in r["rxnorm_name"].lower()
    assert r["is_combination"] == "0"
    assert r["brand_display"] == "DOLIPRANE"
    # French ATC label comes from RUIM libelleATC, not the English Athena INN.
    assert r["libelle_atc"] == "Paracétamol"


def test_augmentin_amox_mapped_clav_unmapped(built):
    out, _ = built
    by_brand = _by_brand(_read(out / etl.BRAND_INGREDIENT_MAP))
    aug = {r["substance_fr"]: r for r in by_brand["augmentin"]}
    assert aug["amoxicilline"]["status"] == "mapped"
    assert aug["amoxicilline"]["individual_atc"] == "J01CA04"
    assert aug["amoxicilline"]["rxnorm_code"] == "723"
    clav = aug["acide clavulanique"]
    assert clav["status"] == "unmapped"
    assert clav["reason"] == "no_ruim_mono_atc"
    assert clav["rxnorm_concept_id"] == "0"
    assert clav["individual_atc"] == "" and clav["rxnorm_code"] == ""


def test_salt_and_base_collapse_to_one_ingredient(built):
    # AMLODUO lists two distinct moieties (amlodipine base S_AML + its salt
    # bésilate d'amlodipine S_AML2) that both resolve to the same RxNorm
    # ingredient. The shipped unit is (brand_key x ingredient), so they collapse
    # to a single mapped row; the salt substances are merged for provenance.
    out, _ = built
    rows = _by_brand(_read(out / etl.BRAND_INGREDIENT_MAP))["amloduo"]
    assert len(rows) == 1
    r = rows[0]
    assert r["rxnorm_code"] == "17767"  # amlodipine, once
    assert r["substance_code"] == "S_AML;S_AML2"
    assert r["substance_fr"] == "amlodipine;bésilate d'amlodipine"
    assert r["individual_atc"] == "C08CA01"
    assert r["status"] == "mapped"


def test_no_duplicate_mapped_keys(built):
    out, _ = built
    rows = _read(out / etl.BRAND_INGREDIENT_MAP)
    keys = [
        (r["brand_key"], r["rxnorm_concept_id"])
        for r in rows
        if r["status"] == "mapped"
    ]
    assert len(keys) == len(set(keys))


def test_manifest_provenance_and_coverage(built):
    out, manifest = built
    on_disk = json.loads((out / etl.MANIFEST).read_text(encoding="utf-8"))
    assert on_disk == manifest
    assert manifest["vocabulary_versions"]["RxNorm"] == "RxNorm 20260105"
    assert manifest["vocabulary_versions"]["ATC"] == "ATC 2026-02-01"
    assert manifest["ruim_dir"] == str(RUIM)
    assert manifest["row_counts"][etl.BRAND_INGREDIENT_MAP] == len(
        _read(out / etl.BRAND_INGREDIENT_MAP)
    )
    # Every fixture speciality has at least one mapped moiety -> full coverage.
    assert manifest["coverage"]["specialities_reached_share"] == 1.0
    assert manifest["coverage"]["specialities_total"] == 9
    assert manifest["ingredient_rows_unmapped"] == 1  # clavulanic acid
    assert manifest["tool_version"]


def test_validate_raises_on_missing_golden(tmp_path, monkeypatch):
    monkeypatch.setitem(etl._GOLDEN_MAPPED, "doliprane", ("definitely-not-real",))
    with pytest.raises(etl.ValidationError):
        etl.build_refs(
            ATHENA, RUIM, out_dir=tmp_path, overrides_path=None, validate=True
        )


def test_validate_raises_on_coverage_threshold(tmp_path):
    with pytest.raises(etl.ValidationError):
        etl.build_refs(
            ATHENA,
            RUIM,
            out_dir=tmp_path,
            overrides_path=None,
            validate=True,
            coverage_threshold=1.01,  # impossible -> must fail
        )
