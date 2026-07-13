"""Golden check: real source labels -> expected ATC, resolved natively through RUIM.

A curated set of anaesthesia/ICU drug labels (the user's real source strings) with
their expected 5th-level ATC codes. The point of this test is **consistency of the
RUIM path**: French drug -> ATC is a RUIM lookup (``CIS.csv:codeATC`` is populated
for 100% of specialities), so a source label should resolve to its ATC via
``brand -> CIS -> codeATC`` *without* any Athena INN matching or override. The
French names (``noradrénaline``/``adrénaline``/``éphédrine`` ...) are caught by
RUIM directly — that is exactly why RUIM is used.

Two rows are non-RUIM **source-label** cases (not French-substance gaps), handled by
curated **source-label aliases** (``source_aliases.csv``) that redirect the raw
label to an existing RUIM brand — the manual layer, kept distinct from the
substance-level ``overrides.csv``: ``BabyNoradrenaline`` is a local custom label for
the TANOREN product (→ ``tanoren``), and ``CEFAZOLIN`` is a misspelling in the source
data of RUIM's ``céfazoline`` (→ ``cefazoline``). RUIM still supplies the ATC in both.

Gated: the RUIM CSV bundle is not vendored, so the test skips when absent. Set
``RUIM2RXNORM_RUIM_DIR`` to the ``..._csv_files`` directory, or place the bundle at
``<repo>/terminologie-ref_interop_med-2026-06/dat/..._csv_files``.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Dict, List

import pytest

from ruim2rxnorm.etl import ruim_io as R

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_RUIM = (
    _REPO_ROOT
    / "terminologie-ref_interop_med-2026-06"
    / "dat"
    / "terminologie-ref_interop_med-2026-06_csv_files"
)
_RUIM_DIR = Path(os.environ.get("RUIM2RXNORM_RUIM_DIR", _DEFAULT_RUIM))
_GOLDEN = Path(__file__).parent / "fixtures" / "golden_source_atc.csv"
_ALIASES = Path(__file__).resolve().parents[1] / "ruim2rxnorm" / "refs" / "source_aliases.csv"

pytestmark = pytest.mark.skipif(
    not (_RUIM_DIR / "CIS.csv").exists(),
    reason=f"RUIM bundle not found at {_RUIM_DIR} (set RUIM2RXNORM_RUIM_DIR)",
)


def _golden_rows():
    with open(_GOLDEN, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def brand_index() -> Dict[str, List[R.CisRow]]:
    return R.group_by_brand_key(R.load_cis(_RUIM_DIR))


@pytest.fixture(scope="module")
def aliases() -> Dict[str, str]:
    return R.load_source_aliases(_ALIASES)


def _candidate_atcs(by_key: Dict[str, List[R.CisRow]], aliases: Dict[str, str], label: str) -> List[str]:
    """ATC codes for a label: source alias -> exact brand-key hit -> whole-word prefix."""
    from ruim2rxnorm.normalize import normalize

    qkey = aliases.get(normalize(label)) or R.brand_key(label)
    rows = list(by_key.get(qkey, []))
    if not rows:
        for k, krows in by_key.items():
            if k.startswith(qkey + " "):
                rows.extend(krows)
    return sorted({r.code_atc for r in rows})


@pytest.mark.parametrize("row", _golden_rows(), ids=lambda r: r["source_label"])
def test_label_resolves_to_expected_atc_via_ruim(brand_index, aliases, row):
    label, expected = row["source_label"], row["code_atc"]
    candidates = _candidate_atcs(brand_index, aliases, label)
    assert candidates, f"{label}: no RUIM brand match"
    # A bare brand can be ambiguous (e.g. PARACETAMOL -> several ATCs); the
    # expected mono ATC must be among the candidates RUIM returns.
    assert expected in candidates, f"{label}: expected {expected}, got {candidates}"
