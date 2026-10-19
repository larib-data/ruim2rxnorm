"""Tests for the runtime lookup over the precomputed brand->ingredient table."""

from __future__ import annotations

from ruim2rxnorm import lookup as L
from ruim2rxnorm.lookup import BrandIndex, IngredientRow


def _row(
    brand_key: str,
    substance_fr: str,
    concept_id: str,
    name: str,
    status: str = "mapped",
    reason: str = "",
) -> IngredientRow:
    return IngredientRow.from_dict(
        {
            "brand_key": brand_key,
            "brand_display": brand_key.upper(),
            "n_specialities": "1",
            "cis_atc": "",
            "substance_code": "",
            "substance_fr": substance_fr,
            "individual_atc": "",
            "libelle_atc": "",
            "rxnorm_concept_id": concept_id,
            "rxnorm_code": "",
            "rxnorm_name": name,
            "is_combination": "0",
            "status": status,
            "reason": reason,
        }
    )


def _index() -> BrandIndex:
    by_key = {
        "coveram": [
            _row("coveram", "amlodipine", "17767", "amlodipine"),
            _row("coveram", "périndopril", "54552", "perindopril"),
        ],
        "humex": [_row("humex", "carbocistéine", "2023", "carbocysteine")],
        "humex allergie cetirizine": [
            _row("humex allergie cetirizine", "cétirizine", "20610", "cetirizine")
        ],
        "humexpectorant": [  # not a whole-word prefix of "humex"
            _row("humexpectorant", "guaifénésine", "5032", "guaifenesin")
        ],
        "augmentin": [
            _row("augmentin", "amoxicilline", "723", "amoxicillin"),
            _row(
                "augmentin",
                "acide clavulanique",
                "0",
                "",
                status="unmapped",
                reason="no_ruim_mono_atc",
            ),
        ],
        "cefazoline": [_row("cefazoline", "céfazoline", "2180", "cefazolin")],
    }
    aliases = {"cefazolin": "cefazoline", "babynoradrenaline": "tanoren"}
    return BrandIndex(by_key, aliases)


# --- exact -------------------------------------------------------------------


def test_exact_returns_all_ingredient_rows():
    res = _index().lookup("COVERAM")
    assert res.match_type == "exact"
    assert res.query_key == "coveram"
    assert [r.rxnorm_name for r in res.rows] == ["amlodipine", "perindopril"]


def test_exact_strips_dose_from_query():
    res = _index().lookup("COVERAM 5 mg/5 mg, comprimé")
    assert res.match_type == "exact"
    assert len(res.rows) == 2


def test_exact_prefers_exact_over_prefix():
    # "humex" is both an exact key and a whole-word prefix of another key; exact wins.
    res = _index().lookup("HUMEX")
    assert res.match_type == "exact"
    assert res.matched_keys == ["humex"]
    assert [r.rxnorm_name for r in res.rows] == ["carbocysteine"]


# --- prefix ------------------------------------------------------------------


def test_prefix_fans_out_to_variants():
    idx = _index()
    del idx.by_key["humex"]  # drop the exact key -> fall through to prefix
    res = idx.lookup("HUMEX")
    assert res.match_type == "prefix"
    # whole-word prefix only: "humexpectorant" must NOT match.
    assert res.matched_keys == ["humex allergie cetirizine"]
    assert [r.rxnorm_name for r in res.rows] == ["cetirizine"]


# --- alias -------------------------------------------------------------------


def test_alias_redirects_to_brand_key():
    res = _index().lookup("CEFAZOLIN")
    assert res.match_type == "alias"
    assert res.query_key == "cefazoline"
    assert [r.rxnorm_name for r in res.rows] == ["cefazolin"]


# --- no match ----------------------------------------------------------------


def test_unknown_query_is_no_match():
    res = _index().lookup("NOTADRUG")
    assert res.match_type == "no_match"
    assert res.matched is False
    assert res.rows == []


def test_empty_query_is_no_match():
    res = _index().lookup("   ")
    assert res.match_type == "no_match"
    assert res.rows == []


# --- unmapped rows are surfaced, not dropped ---------------------------------


def test_unmapped_ingredient_row_is_returned():
    res = _index().lookup("AUGMENTIN")
    names = {r.substance_fr: r for r in res.rows}
    assert names["amoxicilline"].is_mapped is True
    clav = names["acide clavulanique"]
    assert clav.is_mapped is False
    assert clav.rxnorm_concept_id == "0"
    assert clav.reason == "no_ruim_mono_atc"


# --- golden smoke test against the real shipped table ------------------------


def test_shipped_table_coveram_golden():
    res = L.lookup("COVERAM")
    assert res.match_type == "exact"
    mapped = {r.rxnorm_name: r for r in res.rows if r.is_mapped}
    # "RxNorm 54552 / 17767" in the plan are RxNorm *codes* (rxnorm_code column).
    assert mapped["perindopril"].rxnorm_code == "54552"
    assert mapped["amlodipine"].rxnorm_code == "17767"


def test_shipped_table_doliprane_is_acetaminophen():
    res = L.lookup("DOLIPRANE")
    assert res.matched
    assert any(
        r.is_mapped and r.rxnorm_name in ("acetaminophen", "paracetamol")
        for r in res.rows
    )


def test_shipped_table_augmentin_clavulanate_override():
    # Clavulanate has no individual ATC anywhere; it maps only through the curated
    # clavulanate override shipped in refs/overrides.csv. Both AUGMENTIN moieties
    # must resolve in the shipped table.
    res = L.lookup("AUGMENTIN")
    mapped = {r.rxnorm_name: r for r in res.rows if r.is_mapped}
    assert mapped["amoxicillin"].rxnorm_code == "723"
    assert mapped["clavulanate"].rxnorm_code == "48203"


def test_shipped_table_tazobactam_override():
    # Same never-sold-alone case for the piperacillin/tazobactam combination.
    res = L.lookup("TAZOCILLINE")
    mapped = {r.rxnorm_name: r for r in res.rows if r.is_mapped}
    assert mapped["tazobactam"].rxnorm_code == "37617"
    assert mapped["piperacillin"].rxnorm_code == "8339"
