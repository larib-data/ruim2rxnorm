"""Command-line entry point ``ruim2rxrisk`` — French medicines -> Rx-Risk conditions.

A separate console script (not a ``ruim2rxnorm`` subcommand) that treats the whole
list of French drug names as **one patient's medicine list** and derives the set of
Rx-Risk comorbidity conditions present, each annotated with its ICD-10-AM codes, plus
an unweighted score (= number of distinct conditions) and a per-drug breakdown.

The name -> ATC step reuses :func:`ruim2rxnorm.lookup.default_index` verbatim; the
ATC -> condition step is :mod:`ruim2rxnorm.rxrisk`. See ``PROVENANCE.md`` for the
source paper (updated Rx-Risk Index, Widagdo et al.) and the dropped-qualifier /
overlap limitations.

Two input forms::

    ruim2rxrisk NAME [NAME ...]                       # medicines on the command line
    ruim2rxrisk --file meds.csv [--column C] [--out-dir DIR]

With ``--out-dir`` three CSVs are written: ``rxrisk_conditions.csv`` (one row per
distinct condition), ``rxrisk_by_drug.csv`` (one row per input drug) and
``rxrisk_summary.csv`` (a single summary row).
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, Iterable, List, Tuple

from .cli import _iter_input_names
from .rxrisk import (
    ConditionHit,
    RxRiskProfile,
    _code_matches_condition,
)

#: Output CSV column layouts (one row per distinct condition / per drug / summary).
CONDITIONS_COLUMNS: List[str] = [
    "condition",
    "icd10",
    "contributing_drugs",
    "matched_atc",
    "is_new",
]
BY_DRUG_COLUMNS: List[str] = [
    "input_name",
    "brand_key",
    "match_type",
    "atc_codes",
    "conditions",
]
SUMMARY_COLUMNS: List[str] = ["n_drugs", "n_matched_brand", "n_conditions"]


def _matched_atc_for(hit: ConditionHit, profile: RxRiskProfile) -> Tuple[str, ...]:
    """ATC codes (across the contributing drugs) that trigger *hit*'s condition."""
    contributing = set(hit.contributing_drugs)
    codes: List[str] = []
    for drug in profile.by_drug:
        if drug.input_name not in contributing:
            continue
        for code in drug.atc_codes:
            if code not in codes and _code_matches_condition(code, hit.condition):
                codes.append(code)
    return tuple(codes)


# --- output rows -------------------------------------------------------------


def conditions_rows(profile: RxRiskProfile) -> Iterable[Dict[str, str]]:
    """One row per distinct Rx-Risk condition present in the patient."""
    for hit in profile.conditions:
        yield {
            "condition": hit.condition.condition,
            "icd10": ";".join(hit.condition.icd10),
            "contributing_drugs": ";".join(hit.contributing_drugs),
            "matched_atc": ";".join(_matched_atc_for(hit, profile)),
            "is_new": "1" if hit.condition.is_new else "",
        }


def by_drug_rows(profile: RxRiskProfile) -> Iterable[Dict[str, str]]:
    """One row per input medicine, with its ATC codes and triggered conditions."""
    for drug in profile.by_drug:
        yield {
            "input_name": drug.input_name,
            "brand_key": ";".join(drug.brand_keys),
            "match_type": drug.match_type,
            "atc_codes": ";".join(drug.atc_codes),
            "conditions": ";".join(drug.conditions),
        }


def summary_row(profile: RxRiskProfile) -> Dict[str, str]:
    """The single-row Rx-Risk summary (``n_conditions`` is the unweighted score)."""
    n_matched = sum(1 for d in profile.by_drug if d.matched)
    return {
        "n_drugs": str(len(profile.by_drug)),
        "n_matched_brand": str(n_matched),
        "n_conditions": str(profile.score),
    }


# --- human-readable stdout ---------------------------------------------------


def _print_profile(profile: RxRiskProfile) -> None:
    """Print the per-drug lines + the distinct-condition summary to stdout."""
    for drug in profile.by_drug:
        if not drug.matched:
            print(f"{drug.input_name} -> no match")
        elif drug.conditions:
            print(f"{drug.input_name} -> [{', '.join(drug.conditions)}]")
        else:
            print(f"{drug.input_name} -> no Rx-Risk condition")

    print()
    print(f"Rx-Risk conditions ({profile.score}):")
    if profile.conditions:
        for hit in profile.conditions:
            icd10 = ";".join(hit.condition.icd10) or "-"
            drugs = ", ".join(hit.contributing_drugs)
            new = " [new]" if hit.condition.is_new else ""
            print(f"  {hit.condition.condition}{new}  (ICD-10 {icd10})  <- {drugs}")
    else:
        print("  (none)")
    print(f"Unweighted score: {profile.score}")

    unmatched = [d.input_name for d in profile.by_drug if not d.matched]
    if unmatched:
        print(f"No brand match: {', '.join(unmatched)}")


# --- writers -----------------------------------------------------------------


def _write_outputs(profile: RxRiskProfile, out_dir: str) -> List[Tuple[str, int]]:
    """Write the three Rx-Risk CSVs into *out_dir*; return ``(path, rows)`` pairs."""
    from . import outputs as out

    os.makedirs(out_dir, exist_ok=True)
    written: List[Tuple[str, int]] = []

    conditions_path = os.path.join(out_dir, "rxrisk_conditions.csv")
    n = out._write_csv(conditions_path, CONDITIONS_COLUMNS, conditions_rows(profile))
    written.append((conditions_path, n))

    by_drug_path = os.path.join(out_dir, "rxrisk_by_drug.csv")
    n = out._write_csv(by_drug_path, BY_DRUG_COLUMNS, by_drug_rows(profile))
    written.append((by_drug_path, n))

    summary_path = os.path.join(out_dir, "rxrisk_summary.csv")
    n = out._write_csv(summary_path, SUMMARY_COLUMNS, [summary_row(profile)])
    written.append((summary_path, n))

    return written


# --- command -----------------------------------------------------------------


def _cmd_rxrisk(args: argparse.Namespace) -> int:
    from . import lookup as lk

    if args.file:
        try:
            names = list(_iter_input_names(args.file, args.column))
        except (OSError, KeyError) as exc:
            print(f"ruim2rxrisk: {exc}", file=sys.stderr)
            return 1
    else:
        names = list(args.names)

    if not names:
        print("ruim2rxrisk: no medicine names given", file=sys.stderr)
        return 1

    index = lk.default_index()
    results = [index.lookup(name) for name in names]
    profile = RxRiskProfile.build(results)

    _print_profile(profile)

    if args.out_dir:
        written = _write_outputs(profile, args.out_dir)
        print()
        print("Outputs:")
        for path, count in written:
            print(f"  {path}  ({count} rows)")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ruim2rxrisk",
        description=(
            "Map a patient's French medicines to Rx-Risk comorbidity conditions "
            "(+ ICD-10) via ATC; prints the distinct conditions and an unweighted score."
        ),
    )
    parser.add_argument(
        "names",
        nargs="*",
        metavar="NAME",
        help='French brand names on the command line, e.g. "DOLIPRANE" "COVERAM".',
    )
    parser.add_argument(
        "--file",
        default=None,
        help="Read medicine names from this CSV (or one-name-per-line) file instead.",
    )
    parser.add_argument(
        "--column",
        default=None,
        help="With --file, read names from this named column (file treated as "
        "CSV-with-header); default: the first field of every row.",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Also write rxrisk_conditions.csv / rxrisk_by_drug.csv / "
        "rxrisk_summary.csv into this directory.",
    )
    parser.set_defaults(func=_cmd_rxrisk)
    return parser


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.names and not args.file:
        parser.print_help(sys.stderr)
        return 1
    if args.names and args.file:
        print(
            "ruim2rxrisk: give names OR --file, not both",
            file=sys.stderr,
        )
        return 1
    if args.column and not args.file:
        print("ruim2rxrisk: --column only applies with --file", file=sys.stderr)
        return 1
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
