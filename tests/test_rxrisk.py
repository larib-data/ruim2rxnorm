"""Tests for the runtime Rx-Risk classification module (:mod:`ruim2rxnorm.rxrisk`).

Split into two layers:

* pure-logic unit tests over the pattern matcher / include-minus-exclude test /
  ``atc_codes_for`` that construct their own ``MatchResult`` rows; and
* golden classification against the **shipped** ``rxrisk_map.csv`` + real
  ``brand_ingredient_map.csv`` (via ``default_index()`` / ``default_rxrisk_index()``),
  so they double as an end-to-end check of the two tables together.
"""

from __future__ import annotations

from ruim2rxnorm.lookup import IngredientRow, MatchResult, default_index
from ruim2rxnorm.rxrisk import (
    RxRiskProfile,
    _code_matches_condition,
    _pattern_matches,
    atc_codes_for,
    default_rxrisk_index,
)


# --- helpers -----------------------------------------------------------------


def _cond(index, name):
    """Fetch the shipped ``RxRiskCondition`` with condition name *name*."""
    for c in index.conditions:
        if c.condition == name:
            return c
    raise AssertionError(f"condition not in shipped map: {name!r}")


def _result(query, *atc_pairs):
    """Build a fake exact ``MatchResult`` whose rows carry the given ATC codes.

    Each *atc_pairs* item is ``(individual_atc, cis_atc)``.
    """
    rows = [
        IngredientRow.from_dict(
            {"brand_key": query.lower(), "individual_atc": ind, "cis_atc": cis}
        )
        for ind, cis in atc_pairs
    ]
    return MatchResult(
        query=query,
        query_key=query.lower(),
        match_type="exact",
        matched_keys=[query.lower()],
        rows=rows,
    )


# --- _pattern_matches --------------------------------------------------------


def test_pattern_prefix_hit_and_miss():
    assert _pattern_matches("A10", "A10AE04")
    assert _pattern_matches("A10", "A10")
    assert not _pattern_matches("A10", "A09AA02")
    assert not _pattern_matches("C10AA", "C10AB08")


def test_pattern_full_code_is_a_prefix():
    assert _pattern_matches("N02BE01", "N02BE01")
    assert not _pattern_matches("N02BE01", "N02BE02")


def test_pattern_range_in_and_out():
    # C01DA02-C01DA14 (IHD: angina).
    assert _pattern_matches("C01DA02-C01DA14", "C01DA08")
    assert _pattern_matches("C01DA02-C01DA14", "C01DA02")
    assert _pattern_matches("C01DA02-C01DA14", "C01DA14")
    assert not _pattern_matches("C01DA02-C01DA14", "C01DA01")
    assert not _pattern_matches("C01DA02-C01DA14", "C01DA15")


# --- include-minus-exclude ---------------------------------------------------


def test_aspirin_is_antiplatelet_not_anticoagulant():
    rx = default_rxrisk_index()
    antiplatelets = _cond(rx, "Antiplatelets")
    anticoagulants = _cond(rx, "Anticoagulants")
    # B01AC06 = acetylsalicylic acid.
    assert _code_matches_condition("B01AC06", antiplatelets)
    assert not _code_matches_condition("B01AC06", anticoagulants)


def test_bupropion_is_smoking_cessation_not_depression():
    rx = default_rxrisk_index()
    smoking = _cond(rx, "Smoking cessation")
    depression = _cond(rx, "Depression")
    # N06AX12 = bupropion.
    assert _code_matches_condition("N06AX12", smoking)
    assert not _code_matches_condition("N06AX12", depression)


def test_lithium_is_bipolar_not_antipsychotic():
    rx = default_rxrisk_index()
    bipolar = _cond(rx, "Bipolar disorder")
    antipsychotics = _cond(rx, "Antipsychotics")
    # N05AN01 = lithium.
    assert _code_matches_condition("N05AN01", bipolar)
    assert not _code_matches_condition("N05AN01", antipsychotics)


# --- atc_codes_for -----------------------------------------------------------


def test_atc_codes_for_unions_individual_and_cis():
    result = _result("COVERAM", ("C09AA04", "C09BB04"), ("C08CA01", "C09BB04"))
    assert atc_codes_for(result) == {"C09AA04", "C09BB04", "C08CA01"}


def test_atc_codes_for_drops_blanks_and_uppercases():
    result = _result("X", ("", "c10aa05"), (" ", ""))
    assert atc_codes_for(result) == {"C10AA05"}


# --- golden classification (shipped tables) ----------------------------------


def test_golden_coveram_is_hypertension():
    idx = default_index()
    profile = RxRiskProfile.build([idx.lookup("COVERAM")])
    names = {h.condition.condition for h in profile.conditions}
    assert "Hypertension" in names
    hyp = next(h for h in profile.conditions if h.condition.condition == "Hypertension")
    assert hyp.condition.icd10 == ("I10-I15",)


def test_golden_doliprane_is_paracetamol_new_no_icd10():
    idx = default_index()
    profile = RxRiskProfile.build([idx.lookup("DOLIPRANE")])
    hits = {h.condition.condition: h for h in profile.conditions}
    assert "Pain - Paracetamol" in hits
    cond = hits["Pain - Paracetamol"].condition
    assert cond.is_new is True
    assert cond.icd10 == ()


def test_golden_augmentin_has_no_condition():
    idx = default_index()
    profile = RxRiskProfile.build([idx.lookup("AUGMENTIN")])
    assert profile.conditions == ()
    assert "AUGMENTIN" in profile.unmatched_names


def test_golden_diabetes_and_statin_brands():
    idx = default_index()
    diabetes = RxRiskProfile.build([idx.lookup("ABASAGLAR")])
    dh = {h.condition.condition: h.condition for h in diabetes.conditions}
    assert "Diabetes" in dh and dh["Diabetes"].icd10 == ("E10-E14",)

    statin = RxRiskProfile.build([idx.lookup("CRESTOR")])
    sh = {h.condition.condition: h.condition for h in statin.conditions}
    assert "Hyperlipidaemia" in sh and sh["Hyperlipidaemia"].icd10 == ("E78",)


# --- RxRiskProfile aggregate -------------------------------------------------


def test_profile_distinct_conditions_and_unweighted_score():
    idx = default_index()
    results = [idx.lookup(n) for n in ("DOLIPRANE", "COVERAM", "AUGMENTIN")]
    profile = RxRiskProfile.build(results)

    names = {h.condition.condition for h in profile.conditions}
    assert names == {"Pain - Paracetamol", "Hypertension"}
    # Unweighted score = number of distinct conditions.
    assert profile.score == len(profile.conditions) == 2
    assert "AUGMENTIN" in profile.unmatched_names

    # Contributing drugs are surfaced per condition.
    hyp = next(h for h in profile.conditions if h.condition.condition == "Hypertension")
    assert hyp.contributing_drugs == ("COVERAM",)


def test_profile_no_match_name_is_unmatched():
    idx = default_index()
    profile = RxRiskProfile.build([idx.lookup("ZZZNOTADRUG")])
    assert profile.conditions == ()
    assert profile.unmatched_names == ("ZZZNOTADRUG",)
    assert profile.by_drug[0].match_type == "no_match"


def test_shipped_map_has_52_conditions_with_expected_counts():
    rx = default_rxrisk_index()
    assert len(rx.conditions) == 52
    assert sum(1 for c in rx.conditions if c.icd10) == 20
    assert sum(1 for c in rx.conditions if c.is_new) == 9
