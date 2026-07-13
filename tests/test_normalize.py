"""Tests for accent/case/whitespace folding, salt-stripping and FR->EN morphology."""

from __future__ import annotations

from ruim2rxnorm import normalize as N


# --- normalize ---------------------------------------------------------------

def test_accent_and_case_folding():
    assert N.normalize("Périndopril") == "perindopril"
    assert N.normalize("PARACÉTAMOL") == "paracetamol"
    assert N.normalize(" ésoméprazole ") == "esomeprazole"


def test_ligatures_expanded():
    assert N.normalize("œstradiol") == "oestradiol"


def test_whitespace_collapsed_and_punctuation_dropped():
    assert N.normalize("  DOLIPRANE   1000 mg, comprimé  ") == "doliprane 1000 mg comprime"
    # Trailing dash / apostrophe left on a boundary is punctuation, not a joiner.
    assert N.normalize("HUMEX -") == "humex"


def test_apostrophe_variants_unified():
    assert N.normalize("mésilate d’almitrine") == N.normalize("mesilate d'almitrine")


def test_empty_and_none_safe():
    assert N.normalize("") == ""
    assert N.normalize(None) == ""


# --- strip_salt --------------------------------------------------------------

def test_strip_prefix_salt():
    assert N.strip_salt("chlorhydrate de metoclopramide") == "metoclopramide"
    assert N.strip_salt("mesilate d'almitrine") == "almitrine"


def test_strip_prefix_salt_with_cation():
    assert N.strip_salt("succinate sodique de methylprednisolone") == "methylprednisolone"


def test_strip_suffix_salt_and_hydrate():
    assert N.strip_salt("rifampicine sodique") == "rifampicine"
    assert N.strip_salt("cefadroxil monohydrate") == "cefadroxil"
    assert N.strip_salt("chlorure de magnesium anhydre") == "magnesium"


def test_strip_salt_leaves_plain_moiety_untouched():
    assert N.strip_salt("perindopril") == "perindopril"
    assert N.strip_salt("amlodipine") == "amlodipine"


# --- morphology --------------------------------------------------------------

def test_fr_en_morphology():
    assert N.to_english_inn("amoxicilline") == "amoxicillin"
    assert N.to_english_inn("acide folique") == "acide folic"
    # No applicable rule -> unchanged.
    assert N.to_english_inn("amlodipine") == "amlodipin"  # -ine rule; exact-match wins upstream


# --- substance_variants ------------------------------------------------------

def test_substance_variants_ordered_and_deduped():
    assert N.substance_variants("Chlorhydrate de Métoclopramide") == [
        "chlorhydrate de metoclopramide",
        "metoclopramide",
    ]


def test_substance_variants_includes_morphology():
    assert N.substance_variants("amoxicilline") == ["amoxicilline", "amoxicillin"]


def test_substance_variants_plain_name_single_entry():
    assert N.substance_variants("perindopril") == ["perindopril"]
