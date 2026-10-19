"""Command-line entry point for ruim2rxnorm.

Three subcommands, split across the build side and the runtime side:

* ``build-refs`` — the offline ETL that reads the downloaded Athena + RUIM
  sources and (re)emits the shipped ``refs/brand_ingredient_map.csv`` + manifest.
  The **only** command that touches the source vocabularies.
* ``map`` — resolve one (or several) French brand names on the command line and
  print their RxNorm ingredient(s), read from the precomputed shipped table.
* ``map-file`` — batch-map a file of French brand names; write the mapping CSV
  (and optionally ``SOURCE_TO_CONCEPT_MAP`` / Usagi) plus a coverage summary.

``map`` / ``map-file`` never download or parse a vocabulary — they only read the
compact ``brand_ingredient_map.csv`` baked in at build time.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from typing import Iterator, List, Optional

# --- build-refs (build side) -------------------------------------------------


def _cmd_build_refs(args: argparse.Namespace) -> int:
    from .etl import build_refs as etl

    try:
        manifest = etl.build_refs(
            athena_dir=args.athena_dir,
            ruim_dir=args.ruim_dir,
            out_dir=args.out,
            validate=args.validate,
        )
    except etl.ValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    n_rows = manifest["row_counts"][etl.BRAND_INGREDIENT_MAP]
    cov = manifest["coverage"]
    print("build-refs: wrote brand_ingredient_map.csv")
    print(
        f"  ingredient rows: {n_rows} ({manifest['ingredient_rows_mapped']} mapped, "
        f"{manifest['ingredient_rows_unmapped']} unmapped)"
    )
    print(f"  distinct brand keys: {manifest['distinct_brand_keys']}")
    print(
        f"  speciality coverage: {cov['specialities_reached']}/{cov['specialities_total']} "
        f"({cov['specialities_reached_share']:.1%})"
    )
    versions = ", ".join(
        f"{k}={v}" for k, v in manifest["vocabulary_versions"].items() if v
    )
    if versions:
        print(f"  vocabulary versions: {versions}")
    if args.validate:
        print("  validation: OK")
    return 0


# --- map / map-file (runtime side) -------------------------------------------


def _format_ingredient(row) -> str:
    """One ingredient as ``name ATC / RxNorm code`` (or an explicit failure)."""
    name = row.rxnorm_name or row.substance_fr or row.substance_code
    if row.is_mapped:
        atc = row.individual_atc or "?"
        return f"{name} {atc} / RxNorm {row.rxnorm_code}"
    return f"{row.substance_fr or name} (unmapped: {row.reason or 'no_rxnorm'})"


def _format_match(res) -> str:
    """Render a :class:`~ruim2rxnorm.lookup.MatchResult` as a single readable line."""
    if not res.matched:
        return f"{res.query} -> no match"
    ingredients = ", ".join(_format_ingredient(r) for r in res.rows)
    suffix = ""
    if res.match_type == "prefix":
        suffix = f"  [prefix match: {', '.join(res.matched_keys)}]"
    elif res.match_type == "alias":
        suffix = f"  [alias -> {res.matched_keys[0]}]"
    return f"{res.query} -> [{ingredients}]{suffix}"


def _cmd_map(args: argparse.Namespace) -> int:
    from . import lookup as lk

    index = lk.default_index()
    any_unmatched = False
    for name in args.names:
        res = index.lookup(name)
        if not res.matched:
            any_unmatched = True
        print(_format_match(res))
    return 1 if (any_unmatched and args.strict) else 0


def _iter_input_names(path: str, column: Optional[str]) -> Iterator[str]:
    """Yield the drug names from *path*.

    With ``--column`` the file is read as a CSV with a header and that named
    column is taken; otherwise every row's first field is used (no header
    assumed), which also handles a plain one-name-per-line list.
    """
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        if column is not None:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None or column not in reader.fieldnames:
                cols = ", ".join(reader.fieldnames or [])
                raise KeyError(
                    f"column {column!r} not found in {path} (columns: {cols})"
                )
            for row in reader:
                value = (row.get(column) or "").strip()
                if value:
                    yield value
        else:
            for row in csv.reader(fh):
                if row and row[0].strip():
                    yield row[0].strip()


def _cmd_map_file(args: argparse.Namespace) -> int:
    from . import lookup as lk
    from . import outputs as out

    try:
        names = list(_iter_input_names(args.input, args.column))
    except (OSError, KeyError) as exc:
        print(f"map-file: {exc}", file=sys.stderr)
        return 1

    if not names:
        print(f"map-file: no names found in {args.input}", file=sys.stderr)
        return 1

    index = lk.default_index()
    results = [index.lookup(name) for name in names]

    os.makedirs(args.out_dir, exist_ok=True)
    mapping_path = os.path.join(args.out_dir, "mapping.csv")
    n_mapping = out.write_mapping_csv(results, mapping_path)
    written = [(mapping_path, n_mapping)]

    if args.stcm:
        stcm_path = os.path.join(args.out_dir, "SOURCE_TO_CONCEPT_MAP.csv")
        n_stcm = out.write_stcm_csv(
            results, stcm_path, source_vocabulary_id=args.source_vocabulary_id
        )
        written.append((stcm_path, n_stcm))

    if args.usagi:
        usagi_path = os.path.join(args.out_dir, "usagi.csv")
        n_usagi = out.write_usagi_csv(results, usagi_path)
        written.append((usagi_path, n_usagi))

    _print_coverage(results, written)
    return 0


def _print_coverage(results: List, written) -> None:
    """Print a short coverage report for a ``map-file`` batch."""
    n_queries = len(results)
    n_matched = sum(1 for r in results if r.matched)
    n_ingredient_rows = sum(len(r.rows) for r in results)
    n_mapped = sum(1 for r in results for row in r.rows if row.is_mapped)
    n_unmapped = n_ingredient_rows - n_mapped
    unmatched_names = sorted({r.query for r in results if not r.matched})

    print("map-file: coverage report")
    print(f"  input names:        {n_queries}")
    print(f"  matched a brand:    {n_matched} ({_share(n_matched, n_queries)})")
    print(f"  no match:           {n_queries - n_matched}")
    print(
        f"  ingredient rows:    {n_ingredient_rows} "
        f"({n_mapped} mapped, {n_unmapped} unmapped)"
    )
    print("  outputs:")
    for path, count in written:
        print(f"    {path}  ({count} rows)")
    if unmatched_names:
        shown = ", ".join(unmatched_names[:10])
        more = (
            ""
            if len(unmatched_names) <= 10
            else f", (+{len(unmatched_names) - 10} more)"
        )
        print(f"  unmatched names: {shown}{more}")


def _share(part: int, whole: int) -> str:
    return f"{part / whole:.1%}" if whole else "0.0%"


# --- parser ------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ruim2rxnorm",
        description="Map French drug (brand) names to RxNorm ingredients via ATC (OMOP CDM).",
    )
    sub = parser.add_subparsers(dest="_command", metavar="<command>")

    # build-refs (build side).
    p_build = sub.add_parser(
        "build-refs",
        help="Rebuild refs/brand_ingredient_map.csv from the Athena + RUIM sources (the only command that reads them).",
    )
    p_build.add_argument(
        "--athena-dir",
        required=True,
        help="Directory with Athena CONCEPT.csv / CONCEPT_RELATIONSHIP.csv / VOCABULARY.csv.",
    )
    p_build.add_argument(
        "--ruim-dir",
        required=True,
        help="Directory with RUIM CIS.csv / Compositions_qualitatives.csv / Substances.csv.",
    )
    p_build.add_argument(
        "--out",
        default=None,
        help="Output directory for the precomputed table + manifest (default: the package's shipped refs/ directory).",
    )
    p_build.add_argument(
        "--validate",
        action="store_true",
        help="Re-check invariants (golden mappings, no duplicate keys, complete manifest) and fail loudly.",
    )
    p_build.set_defaults(func=_cmd_build_refs)

    # map (runtime): one or more names on the command line.
    p_map = sub.add_parser(
        "map",
        help="Map a French drug name to its RxNorm ingredient(s); prints the result.",
    )
    p_map.add_argument(
        "names",
        nargs="+",
        metavar="NAME",
        help='One or more French brand names, e.g. "COVERAM" "DOLIPRANE".',
    )
    p_map.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any name did not match a brand.",
    )
    p_map.set_defaults(func=_cmd_map)

    # map-file (runtime): batch a file of names.
    p_file = sub.add_parser(
        "map-file",
        help="Batch-map a file of French drug names; write mapping CSV (+ optional STCM/Usagi) and a coverage report.",
    )
    p_file.add_argument(
        "input",
        metavar="FILE",
        help="CSV (or one-name-per-line) file of French brand names.",
    )
    p_file.add_argument(
        "--out-dir",
        required=True,
        help="Directory to write mapping.csv (and any requested outputs) into.",
    )
    p_file.add_argument(
        "--column",
        default=None,
        help="Read names from this named column (file is treated as CSV-with-header); "
        "default: the first field of every row.",
    )
    p_file.add_argument(
        "--stcm",
        action="store_true",
        help="Also write SOURCE_TO_CONCEPT_MAP.csv (OMOP STCM).",
    )
    p_file.add_argument(
        "--usagi",
        action="store_true",
        help="Also write usagi.csv (OHDSI Usagi review input).",
    )
    p_file.add_argument(
        "--source-vocabulary-id",
        default=None,
        help="Custom source_vocabulary_id for the STCM output (default: FR_ANSM_BRAND).",
    )
    p_file.set_defaults(func=_cmd_map_file)

    return parser


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "_command", None):
        parser.print_help(sys.stderr)
        return 1
    # Fill the STCM default here so outputs.SOURCE_VOCABULARY_ID stays the source of truth.
    if (
        getattr(args, "source_vocabulary_id", None) is None
        and args._command == "map-file"
    ):
        from . import outputs as out

        args.source_vocabulary_id = out.SOURCE_VOCABULARY_ID
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
