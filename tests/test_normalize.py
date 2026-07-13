"""Tests for accent/case/whitespace/punctuation folding."""

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
