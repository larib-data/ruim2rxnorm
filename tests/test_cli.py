"""Tests for the runtime CLI subcommands (``map`` / ``map-file``).

These exercise the real shipped ``brand_ingredient_map.csv`` (like the golden
smoke tests in ``test_lookup``), so they double as an end-to-end check that the
CLI wires lookup + outputs together over the precomputed table.
"""

from __future__ import annotations

import csv

from ruim2rxnorm.cli import main


# --- map ---------------------------------------------------------------------

def test_map_coveram_prints_both_ingredients(capsys):
    rc = main(["map", "COVERAM"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.startswith("COVERAM -> [")
    assert "perindopril" in out and "amlodipine" in out
    assert "RxNorm 54552" in out and "RxNorm 17767" in out


def test_map_multiple_names_one_line_each(capsys):
    main(["map", "COVERAM", "DOLIPRANE"])
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln]
    assert len(lines) == 2
    assert lines[0].startswith("COVERAM -> [")
    assert lines[1].startswith("DOLIPRANE -> [")


def test_map_no_match_reports_and_strict_exits_nonzero(capsys):
    rc_default = main(["map", "ZZZNOTADRUG"])
    out = capsys.readouterr().out
    assert rc_default == 0
    assert "ZZZNOTADRUG -> no match" in out

    rc_strict = main(["map", "ZZZNOTADRUG", "--strict"])
    assert rc_strict == 1


# --- map-file ----------------------------------------------------------------

def _read(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def test_map_file_writes_mapping_and_stcm(tmp_path, capsys):
    src = tmp_path / "names.txt"
    src.write_text("COVERAM\nDOLIPRANE\nZZZNOTADRUG\n", encoding="utf-8")
    out_dir = tmp_path / "out"

    rc = main(["map-file", str(src), "--out-dir", str(out_dir), "--stcm"])
    assert rc == 0

    mapping = _read(out_dir / "mapping.csv")
    inputs = {r["input_name"] for r in mapping}
    assert {"COVERAM", "DOLIPRANE", "ZZZNOTADRUG"} <= inputs
    # COVERAM expands to two ingredient rows.
    coveram = [r for r in mapping if r["input_name"] == "COVERAM"]
    assert len(coveram) == 2
    # no_match query appears as a placeholder row.
    nomatch = [r for r in mapping if r["input_name"] == "ZZZNOTADRUG"]
    assert len(nomatch) == 1 and nomatch[0]["status"] == "no_match"

    stcm = _read(out_dir / "SOURCE_TO_CONCEPT_MAP.csv")
    assert list(stcm[0].keys()) == [
        "source_code", "source_concept_id", "source_vocabulary_id",
        "source_code_description", "target_concept_id", "target_vocabulary_id",
        "valid_start_date", "valid_end_date", "invalid_reason",
    ]
    coveram_targets = {
        r["target_concept_id"] for r in stcm if r["source_code_description"] == "COVERAM"
    }
    assert "0" not in coveram_targets and len(coveram_targets) == 2

    report = capsys.readouterr().out
    assert "coverage report" in report
    assert "ZZZNOTADRUG" in report  # listed among unmatched


def test_map_file_named_column(tmp_path):
    src = tmp_path / "names.csv"
    src.write_text("id,drug\n1,COVERAM\n2,DOLIPRANE\n", encoding="utf-8")
    out_dir = tmp_path / "out"

    rc = main(["map-file", str(src), "--out-dir", str(out_dir), "--column", "drug"])
    assert rc == 0
    inputs = {r["input_name"] for r in _read(out_dir / "mapping.csv")}
    assert {"COVERAM", "DOLIPRANE"} == inputs


def test_map_file_missing_column_errors(tmp_path, capsys):
    src = tmp_path / "names.csv"
    src.write_text("id,drug\n1,COVERAM\n", encoding="utf-8")
    rc = main(["map-file", str(src), "--out-dir", str(tmp_path / "out"),
               "--column", "nope"])
    assert rc == 1
    assert "not found" in capsys.readouterr().err


def test_map_file_usagi_optional(tmp_path):
    src = tmp_path / "names.txt"
    src.write_text("COVERAM\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    main(["map-file", str(src), "--out-dir", str(out_dir), "--usagi"])
    assert (out_dir / "usagi.csv").exists()
    assert not (out_dir / "SOURCE_TO_CONCEPT_MAP.csv").exists()


def test_map_file_empty_input_errors(tmp_path, capsys):
    src = tmp_path / "empty.txt"
    src.write_text("\n\n", encoding="utf-8")
    rc = main(["map-file", str(src), "--out-dir", str(tmp_path / "out")])
    assert rc == 1
    assert "no names" in capsys.readouterr().err
