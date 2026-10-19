"""Tests for the output writers (mapping CSV / STCM / Usagi)."""

from __future__ import annotations

import csv
import io

from ruim2rxnorm import outputs as O
from ruim2rxnorm.lookup import IngredientRow, MatchResult


def _row(
    brand_key,
    substance_fr,
    concept_id,
    code,
    name,
    status="mapped",
    reason="",
    is_combination="1",
):
    return IngredientRow.from_dict(
        {
            "brand_key": brand_key,
            "brand_display": brand_key.upper(),
            "n_specialities": "29",
            "cis_atc": "C09BB04",
            "substance_code": "39727",
            "substance_fr": substance_fr,
            "individual_atc": "",
            "libelle_atc": "",
            "rxnorm_concept_id": concept_id,
            "rxnorm_code": code,
            "rxnorm_name": name,
            "is_combination": is_combination,
            "status": status,
            "reason": reason,
        }
    )


def _coveram() -> MatchResult:
    rows = [
        _row("coveram", "amlodipine", "1332418", "17767", "amlodipine"),
        _row("coveram", "périndopril", "1373225", "54552", "perindopril"),
    ]
    return MatchResult("COVERAM", "coveram", "exact", ["coveram"], rows)


def _augmentin() -> MatchResult:
    rows = [
        _row("augmentin", "amoxicilline", "1713", "723", "amoxicillin"),
        _row(
            "augmentin",
            "acide clavulanique",
            "0",
            "",
            "",
            status="unmapped",
            reason="no_ruim_mono_atc",
        ),
    ]
    return MatchResult("AUGMENTIN", "augmentin", "exact", ["augmentin"], rows)


def _no_match() -> MatchResult:
    return MatchResult("NOTADRUG", "notadrug", "no_match", [], [])


def _read(text):
    return list(csv.DictReader(io.StringIO(text)))


# --- mapping CSV -------------------------------------------------------------


def test_mapping_csv_one_row_per_ingredient():
    buf = io.StringIO()
    n = O.write_mapping_csv([_coveram()], buf)
    rows = _read(buf.getvalue())
    assert n == 2 and len(rows) == 2
    assert [r["rxnorm_name"] for r in rows] == ["amlodipine", "perindopril"]
    assert all(r["input_name"] == "COVERAM" for r in rows)
    assert rows[0]["match_type"] == "exact"


def test_mapping_csv_surfaces_unmapped_reason():
    buf = io.StringIO()
    O.write_mapping_csv([_augmentin()], buf)
    rows = {r["substance_fr"]: r for r in _read(buf.getvalue())}
    clav = rows["acide clavulanique"]
    assert clav["status"] == "unmapped"
    assert clav["reason"] == "no_ruim_mono_atc"
    assert clav["rxnorm_concept_id"] == "0"


def test_mapping_csv_emits_no_match_placeholder():
    buf = io.StringIO()
    O.write_mapping_csv([_no_match()], buf)
    rows = _read(buf.getvalue())
    assert len(rows) == 1
    assert rows[0]["input_name"] == "NOTADRUG"
    assert rows[0]["status"] == "no_match"
    assert rows[0]["rxnorm_concept_id"] == ""


# --- STCM --------------------------------------------------------------------


def test_stcm_has_nine_spec_columns():
    buf = io.StringIO()
    O.write_stcm_csv([_coveram()], buf)
    header = _read(buf.getvalue())[0].keys() if buf.getvalue() else []
    assert list(header) == O.STCM_COLUMNS
    assert len(O.STCM_COLUMNS) == 9


def test_stcm_coveram_two_target_rows_use_concept_id():
    buf = io.StringIO()
    O.write_stcm_csv([_coveram()], buf)
    rows = _read(buf.getvalue())
    assert len(rows) == 2
    # target_concept_id is the RxNorm concept_id, NOT the rxnorm_code.
    assert {r["target_concept_id"] for r in rows} == {"1332418", "1373225"}
    for r in rows:
        assert r["source_code"] == "coveram"
        assert r["source_vocabulary_id"] == "FR_ANSM_BRAND"
        assert r["target_vocabulary_id"] == "RxNorm"
        assert r["source_code_description"] == "COVERAM"
        assert r["valid_start_date"] == "1970-01-01"
        assert r["valid_end_date"] == "2099-12-31"
        assert r["invalid_reason"] == ""


def test_stcm_unresolved_is_zero_with_reason():
    buf = io.StringIO()
    O.write_stcm_csv([_augmentin()], buf)
    rows = {r["target_concept_id"]: r for r in _read(buf.getvalue())}
    assert "0" in rows
    assert rows["0"]["invalid_reason"] == "no_ruim_mono_atc"


def test_stcm_skips_no_match_queries():
    buf = io.StringIO()
    n = O.write_stcm_csv([_no_match()], buf)
    assert n == 0
    assert _read(buf.getvalue()) == []


def test_stcm_custom_source_vocabulary():
    buf = io.StringIO()
    O.write_stcm_csv([_coveram()], buf, source_vocabulary_id="MY_VOCAB")
    rows = _read(buf.getvalue())
    assert all(r["source_vocabulary_id"] == "MY_VOCAB" for r in rows)


# --- Usagi -------------------------------------------------------------------


def test_usagi_marks_mapped_and_unmapped():
    buf = io.StringIO()
    O.write_usagi_csv([_augmentin()], buf)
    by_status = {r["mappingStatus"] for r in _read(buf.getvalue())}
    assert by_status == {"APPROVED", "UNCHECKED"}


# --- path destination --------------------------------------------------------


def test_writers_accept_a_path(tmp_path):
    p = tmp_path / "stcm.csv"
    O.write_stcm_csv([_coveram()], p)
    rows = _read(p.read_text(encoding="utf-8"))
    assert len(rows) == 2
