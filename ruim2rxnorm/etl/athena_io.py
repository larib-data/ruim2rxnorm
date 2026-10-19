"""Hardened streaming reader for OMOP Athena tab-delimited vocabulary files.

Athena's ``.csv`` files are actually tab-delimited and contain **literal
double-quote characters inside drug names** (e.g. ``paracetamol 500 "mg"``).
A default ``csv`` parser treats ``"`` as a quote character, silently merges
lines across a stray quote and drops concepts (paracetamol vanished until
quoting was disabled during development). Every Athena file must therefore be
read with ``delimiter='\\t'``, ``quoting=csv.QUOTE_NONE`` and an enlarged
``csv.field_size_limit`` so long concept-name fields do not overflow.

This module centralizes that reader so nothing else in the ETL has to
re-derive the parsing rules, plus a :func:`read_vocabulary_version` helper for
provenance stamping.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Dict, Iterator, Union

# Athena concept-name fields can be very long; a stray value must never raise
# ``field larger than field limit``. Raise the limit once, at import time.
csv.field_size_limit(sys.maxsize)

# The Athena tables the ETL streams. Files are named ``<TABLE>.csv`` but are
# tab-delimited despite the extension.
CONCEPT = "CONCEPT"
CONCEPT_RELATIONSHIP = "CONCEPT_RELATIONSHIP"
CONCEPT_SYNONYM = "CONCEPT_SYNONYM"
VOCABULARY = "VOCABULARY"


def table_path(athena_dir: Union[str, Path], table: str) -> Path:
    """Return the path to an Athena ``<table>.csv`` file, verifying it exists."""
    path = Path(athena_dir) / f"{table}.csv"
    if not path.is_file():
        raise FileNotFoundError(
            f"Athena table {table!r} not found at {path}. "
            f"Expected a directory containing CONCEPT.csv, CONCEPT_RELATIONSHIP.csv, "
            f"CONCEPT_SYNONYM.csv, VOCABULARY.csv, ..."
        )
    return path


def read_rows(path: Union[str, Path]) -> Iterator[Dict[str, str]]:
    """Stream an Athena tab file as a generator of ``header -> value`` dicts.

    The file is read lazily (one row in memory at a time) so multi-gigabyte
    tables like ``CONCEPT`` never have to be materialized. Parsing uses
    ``QUOTE_NONE`` so embedded double quotes are treated as ordinary text.
    """
    with open(path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE)
        try:
            header = next(reader)
        except StopIteration:
            return
        for row in reader:
            # Tolerate rows with trailing empty cells that Athena sometimes omits.
            if len(row) < len(header):
                row = row + [""] * (len(header) - len(row))
            yield dict(zip(header, row))


def read_table(athena_dir: Union[str, Path], table: str) -> Iterator[Dict[str, str]]:
    """Stream a named Athena table from *athena_dir* (convenience wrapper)."""
    return read_rows(table_path(athena_dir, table))


def read_vocabulary_version(athena_dir: Union[str, Path], vocabulary_id: str) -> str:
    """Return the ``vocabulary_version`` string for *vocabulary_id*.

    Used to stamp ``REFS_MANIFEST.json`` with the exact Athena release the
    reference tables were built from (e.g. ``"RxNorm 20260105"``).
    Raises ``KeyError`` if the vocabulary is absent from ``VOCABULARY.csv``.
    """
    for row in read_table(athena_dir, VOCABULARY):
        if row.get("vocabulary_id") == vocabulary_id:
            return row.get("vocabulary_version", "")
    raise KeyError(
        f"vocabulary_id {vocabulary_id!r} not found in {table_path(athena_dir, VOCABULARY)}"
    )
