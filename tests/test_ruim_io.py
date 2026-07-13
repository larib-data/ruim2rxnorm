"""Tests for the build-side RUIM readers + brand-key extraction."""

from __future__ import annotations

from pathlib import Path

from ruim2rxnorm.etl import ruim_io as R

RUIM = Path(__file__).parent / "fixtures" / "ruim_mini"


# --- brand_key ---------------------------------------------------------------

def test_brand_key_cuts_at_dose():
    assert R.brand_key("COVERAM 5 mg/5 mg, comprimé") == "coveram"
    assert R.brand_key("PARACETAMOL ZYDUS FRANCE 500 mg, gélule") == "paracetamol zydus france"


def test_brand_key_cuts_at_comma_before_dose():
    assert R.brand_key("HUMEX RHUME, comprimé et gélule") == "humex rhume"


def test_brand_key_strips_query_dose():
    assert R.brand_key("DOLIPRANE 1000") == "doliprane"
    assert R.brand_key("COVERAM") == "coveram"


# --- CIS ---------------------------------------------------------------------

def test_load_cis_fields():
    rows = R.load_cis(RUIM)
    # 4 originals + AMLOR/COVERSYL/CLAMOXYL mono specialities + AMLOSEL/AMLODUO
    # (salt+base collapse fixtures).
    assert len(rows) == 9
    cov = [r for r in rows if r.brand_key == "coveram"]
    assert {r.cis for r in cov} == {"100", "101"}
    assert {r.code_atc for r in cov} == {"C09BB04"}
    assert cov[0].forme == "FT001" and cov[0].voie == "20"


def test_group_by_brand_key():
    by_key = R.group_by_brand_key(R.load_cis(RUIM))
    assert {r.cis for r in by_key["coveram"]} == {"100", "101"}
    assert [r.cis for r in by_key["doliprane"]] == ["200"]
    assert "" not in by_key


# --- Compositions (fraction thérapeutique only) ------------------------------

def test_load_compositions_prefers_fraction_therapeutique():
    comp = R.load_compositions(RUIM)
    # CIS 100 has fraction thérapeutique rows -> use the base moieties, not the salts.
    assert comp["100"] == ["S_AML", "S_PER"]
    assert "S_AML_SALT" not in comp["100"]
    assert comp["300"] == ["S_AMOX", "S_CLAV"]


def test_load_compositions_falls_back_to_substance_active():
    # CIS 200 (DOLIPRANE) has no fraction thérapeutique row -> use substance active.
    assert R.load_compositions(RUIM)["200"] == ["S_PARA"]


# --- Substances --------------------------------------------------------------

def test_load_substances_names_and_synonyms():
    subs = R.load_substances(RUIM)
    assert subs["S_AML"].name_fr == "amlodipine"
    assert subs["S_PER"].synonyms_fr == ["périndopril tert-butylamine"]
    assert subs["S_AML"].synonyms_fr == []
