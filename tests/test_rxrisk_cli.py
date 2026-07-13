"""Tests for the ``ruim2rxrisk`` console entry point (:mod:`ruim2rxnorm.rxrisk_cli`).

Exercise the real shipped tables end-to-end: names form, ``--file`` form, the
three ``--out-dir`` CSVs and the argument-validation paths.
"""

from __future__ import annotations

import csv

from ruim2rxnorm.rxrisk_cli import main


def _read(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


# --- names form --------------------------------------------------------------


def test_names_form_prints_conditions_and_score(capsys):
    rc = main(["DOLIPRANE", "COVERAM", "AUGMENTIN"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "COVERAM -> [Hypertension]" in out
    assert "DOLIPRANE -> [Pain - Paracetamol]" in out
    assert "AUGMENTIN -> no Rx-Risk condition" in out
    assert "Rx-Risk conditions (2):" in out
    assert "Hypertension" in out and "ICD-10 I10-I15" in out
    assert "Unweighted score: 2" in out


def test_names_form_no_brand_match(capsys):
    rc = main(["ZZZNOTADRUG"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "ZZZNOTADRUG -> no match" in out
    assert "No brand match: ZZZNOTADRUG" in out
    assert "Unweighted score: 0" in out


# --- file form + out-dir -----------------------------------------------------


def test_file_form_writes_three_csvs(tmp_path, capsys):
    src = tmp_path / "meds.txt"
    src.write_text("DOLIPRANE\nCOVERAM\nAUGMENTIN\n", encoding="utf-8")
    out_dir = tmp_path / "out"

    rc = main(["--file", str(src), "--out-dir", str(out_dir)])
    assert rc == 0

    conditions = _read(out_dir / "rxrisk_conditions.csv")
    by_cond = {r["condition"]: r for r in conditions}
    assert set(by_cond) == {"Pain - Paracetamol", "Hypertension"}
    assert by_cond["Hypertension"]["icd10"] == "I10-I15"
    assert by_cond["Hypertension"]["contributing_drugs"] == "COVERAM"
    assert by_cond["Pain - Paracetamol"]["is_new"] == "1"
    # matched_atc lists only the codes that actually trigger the condition.
    assert "C09BB04" in by_cond["Hypertension"]["matched_atc"]

    by_drug = {r["input_name"]: r for r in _read(out_dir / "rxrisk_by_drug.csv")}
    assert by_drug["AUGMENTIN"]["conditions"] == ""
    assert by_drug["AUGMENTIN"]["match_type"] == "exact"
    assert "N02BE01" in by_drug["DOLIPRANE"]["atc_codes"]

    summary = _read(out_dir / "rxrisk_summary.csv")
    assert len(summary) == 1
    assert summary[0] == {"n_drugs": "3", "n_matched_brand": "3", "n_conditions": "2"}

    report = capsys.readouterr().out
    assert "rxrisk_conditions.csv" in report


def test_file_form_named_column(tmp_path):
    src = tmp_path / "meds.csv"
    src.write_text("id,drug\n1,COVERAM\n2,ABASAGLAR\n", encoding="utf-8")
    out_dir = tmp_path / "out"

    rc = main(["--file", str(src), "--column", "drug", "--out-dir", str(out_dir)])
    assert rc == 0
    conditions = {r["condition"] for r in _read(out_dir / "rxrisk_conditions.csv")}
    assert conditions == {"Hypertension", "Diabetes"}


# --- argument validation -----------------------------------------------------


def test_no_arguments_prints_help(capsys):
    rc = main([])
    assert rc == 1
    assert "usage" in capsys.readouterr().err.lower()


def test_names_and_file_are_mutually_exclusive(tmp_path, capsys):
    src = tmp_path / "meds.txt"
    src.write_text("COVERAM\n", encoding="utf-8")
    rc = main(["DOLIPRANE", "--file", str(src)])
    assert rc == 1
    assert "not both" in capsys.readouterr().err


def test_column_requires_file(capsys):
    rc = main(["DOLIPRANE", "--column", "drug"])
    assert rc == 1
    assert "only applies with --file" in capsys.readouterr().err
