"""Tests for build-side resolution: Athena index, composition, RUIM-first resolver.

Design invariant under test: French name -> ATC is a **RUIM** lookup; Athena is
used **only** for ATC -> RxNorm ingredient. The resolver never name-matches Athena.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ruim2rxnorm.etl import resolve as RS
from ruim2rxnorm.etl import ruim_io as R

ATHENA = Path(__file__).parent / "fixtures" / "athena_mini"
RUIM = Path(__file__).parent / "fixtures" / "ruim_mini"


@pytest.fixture(scope="module")
def index():
    return RS.load_athena_index(ATHENA)


@pytest.fixture(scope="module")
def substance_atc():
    return RS.build_substance_atc_index(R.load_cis(RUIM), R.load_compositions(RUIM))


# --- load_athena_index: ATC -> ingredient only, no name indexes --------------

def test_atc_to_ingredients_and_sec_up_excluded(index):
    assert index.best_ingredient("C09AA04").code == "54552"
    assert index.best_ingredient("C08CA01").code == "17767"
    assert index.best_ingredient("N02BE01").code == "161"
    assert index.best_ingredient("J01CA04").code == "723"
    # C09BB04 (combination) legitimately lists both ingredients here...
    assert {i.code for i in index.atc_to_ingredients["C09BB04"]} == {"54552", "17767"}
    # ...but the 'sec up' edge (C09AA -> amlodipine) is excluded.
    assert "C09AA" not in index.atc_to_ingredients


def test_ingredient_filtering(index):
    assert "9999999" not in index.ingredient_by_id  # invalid_reason=D
    assert "8888888" not in index.ingredient_by_id  # Clinical Drug, not Ingredient
    assert index.atc5_name_by_code["N02BE01"] == "paracetamol"


def test_index_has_no_name_indexes(index):
    """Structural guarantee: Athena carries no name->ATC / name->ingredient map."""
    assert not hasattr(index, "inn_to_atc")
    assert not hasattr(index, "name_to_ingredient")
    assert not hasattr(index, "synonym_to_ingredient")


# --- build_substance_atc_index: RUIM substance -> individual (mono) ATC -------

def test_substance_atc_index_from_mono_specialities(substance_atc):
    # Recovered from AMLOR / COVERSYL / CLAMOXYL / DOLIPRANE (single-moiety CIS).
    assert substance_atc["S_AML"] == "C08CA01"
    assert substance_atc["S_PER"] == "C09AA04"
    assert substance_atc["S_AMOX"] == "J01CA04"
    assert substance_atc["S_PARA"] == "N02BE01"
    # Clavulanic acid is never sold alone -> no mono ATC in RUIM.
    assert "S_CLAV" not in substance_atc


# --- Resolver: RUIM ATC bridge + Athena ATC->RxNorm --------------------------

def test_resolve_mono_via_ruim(index, substance_atc):
    r = RS.Resolver(index, substance_atc)
    para = r.resolve(RS.Moiety("S_PARA", "paracétamol"))
    assert para.status == "mapped" and para.individual_atc == "N02BE01"
    assert para.ingredient.code == "161" and para.reason == ""


def test_resolve_combination_decomposes_via_ruim(index, substance_atc):
    """COVERAM: each moiety's individual ATC from its own RUIM mono speciality."""
    rows = R.group_by_brand_key(R.load_cis(RUIM))["coveram"]
    moieties = RS.brand_moieties(rows, R.load_compositions(RUIM), R.load_substances(RUIM))
    r = RS.Resolver(index, substance_atc)
    got = {m.name_fr: r.resolve(m) for m in moieties}
    assert got["amlodipine"].individual_atc == "C08CA01"
    assert got["amlodipine"].ingredient.code == "17767"
    assert got["périndopril"].individual_atc == "C09AA04"
    assert got["périndopril"].ingredient.code == "54552"


def test_resolve_augmentin_maps_amox_fails_clavulanic(index, substance_atc):
    rows = R.group_by_brand_key(R.load_cis(RUIM))["augmentin"]
    moieties = RS.brand_moieties(rows, R.load_compositions(RUIM), R.load_substances(RUIM))
    r = RS.Resolver(index, substance_atc)
    got = {m.name_fr: r.resolve(m) for m in moieties}
    assert got["amoxicilline"].status == "mapped"
    assert got["amoxicilline"].individual_atc == "J01CA04"
    assert got["amoxicilline"].ingredient.code == "723"
    # Never sold alone, no override -> explicit failure, no Athena name guess.
    clav = got["acide clavulanique"]
    assert clav.status == "unmapped" and clav.reason == "no_ruim_mono_atc"
    assert clav.individual_atc == "" and clav.ingredient is None


def test_resolve_no_ruim_atc_never_name_matches_athena(index):
    """A moiety whose French name equals an Athena ingredient name still fails
    when RUIM has no ATC for it: Athena is not consulted by name."""
    r = RS.Resolver(index, substance_atc={})  # empty RUIM index
    res = r.resolve(RS.Moiety("S_PARA", "paracetamol"))  # matches Athena name
    assert res.status == "unmapped" and res.reason == "no_ruim_mono_atc"
    assert res.ingredient is None


# --- Resolver: curated overrides (id / atc) ----------------------------------

def _ing(cid, code, name, vocab="RxNorm", standard="S"):
    return RS.Ingredient(concept_id=cid, code=code, name=name, vocab=vocab, standard=standard)


def test_resolve_override_by_concept_id():
    clav = _ing("500", "clav1", "clavulanic acid")
    idx = RS.AthenaIndex(ingredient_by_id={"500": clav})
    overrides = {"acide clavulanique": RS.Override(atc="", rxnorm_concept_id="500")}
    res = RS.Resolver(idx, {}, overrides).resolve(RS.Moiety("S_CLAV", "acide clavulanique"))
    assert res.status == "mapped" and res.reason == "override"
    assert res.ingredient.code == "clav1"


def test_resolve_override_by_atc(index):
    overrides = {"S_X": RS.Override(atc="N02BE01", rxnorm_concept_id="")}
    res = RS.Resolver(index, {}, overrides).resolve(RS.Moiety("S_X", "whatever"))
    assert res.status == "mapped" and res.reason == "override"
    assert res.individual_atc == "N02BE01" and res.ingredient.code == "161"


def test_resolve_atc_without_ingredient():
    """RUIM gives an ATC that Athena's ATC->RxNorm map does not cover."""
    idx = RS.AthenaIndex(atc5_name_by_code={"X01AA01": "foo"})
    res = RS.Resolver(idx, {"S_F": "X01AA01"}).resolve(RS.Moiety("S_F", "foo"))
    assert res.status == "unmapped" and res.individual_atc == "X01AA01"
    assert res.reason == "atc_not_in_rxnorm_map"


# --- Composition -------------------------------------------------------------

def test_brand_moieties_union_and_dedup():
    rows = R.group_by_brand_key(R.load_cis(RUIM))["coveram"]  # CIS 100 + 101
    comp = R.load_compositions(RUIM)
    subs = R.load_substances(RUIM)
    moieties = RS.brand_moieties(rows, comp, subs)
    # Two moieties, deduped across the two COVERAM specialities, first-seen order.
    assert [(m.code, m.name_fr) for m in moieties] == [
        ("S_AML", "amlodipine"),
        ("S_PER", "périndopril"),
    ]


def test_brand_moieties_mono():
    rows = R.group_by_brand_key(R.load_cis(RUIM))["doliprane"]
    moieties = RS.brand_moieties(rows, R.load_compositions(RUIM), R.load_substances(RUIM))
    assert [m.name_fr for m in moieties] == ["paracétamol"]


# --- Overrides loader --------------------------------------------------------

def test_load_overrides_skips_placeholders(tmp_path):
    p = tmp_path / "overrides.csv"
    p.write_text(
        "substance_code_or_name,atc,rxnorm_concept_id,note\n"
        "paracétamol,N02BE01,,seed\n"
        "acide folique,,,placeholder\n"
        "S_123,,600,by-code\n",
        encoding="utf-8",
    )
    ov = RS.load_overrides(p)
    # Placeholder (no atc/no concept_id) skipped; name reachable normalized, code raw.
    assert "acide folique" not in ov and "acide folique".replace("é", "e") not in ov
    assert ov["paracetamol"].atc == "N02BE01"      # normalized-name lookup
    assert ov["S_123"].rxnorm_concept_id == "600"  # raw-code lookup
