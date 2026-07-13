Usage
=====

Install
-------

This project is managed with `uv <https://docs.astral.sh/uv/>`_:

.. code-block:: console

   $ uv sync                  # core (stdlib-only) + dev group (pytest)
   $ uv sync --group docs     # also install the docs toolchain (sphinx)

The ``ruim2rxnorm`` console script is installed as an entry point; run it with
``uv run ruim2rxnorm ...`` (or activate ``.venv``). The stdlib-only core also
installs with a plain ``pip install .`` for non-uv consumers.

``map`` — one or more names
---------------------------

.. code-block:: console

   $ ruim2rxnorm map COVERAM DOLIPRANE AUGMENTIN
   COVERAM -> [amlodipine C08CA01 / RxNorm 17767, perindopril C09AA04 / RxNorm 54552]
   DOLIPRANE -> [acetaminophen N02BE01 / RxNorm 161]
   AUGMENTIN -> [amoxicillin J01CA04 / RxNorm 723, clavulanate ? / RxNorm 48203]

Each ingredient prints as ``name ATC / RxNorm <code>``. An unmapped moiety is shown explicitly
(``clavulanate`` above is resolved by override and has no ATC, hence ``?``). A prefix or alias
match annotates the matched key in brackets. Pass ``--strict`` to exit non-zero if any name did
not match a brand.

``map-file`` — batch a file
---------------------------

.. code-block:: console

   $ ruim2rxnorm map-file names.csv --out-dir out/ --stcm --usagi

The input file is either a plain one-name-per-line list or a CSV; with ``--column NAME`` the
file is read as a CSV-with-header and that named column is taken. Outputs are written into
``--out-dir``:

* ``mapping.csv`` — always written; the human-readable audit / coverage table.
* ``SOURCE_TO_CONCEPT_MAP.csv`` — with ``--stcm``; the OMOP STCM table.
* ``usagi.csv`` — with ``--usagi``; the OHDSI Usagi review input.

``--source-vocabulary-id`` overrides the STCM ``source_vocabulary_id`` (default
``FR_ANSM_BRAND``). A coverage report is printed to stdout. See :doc:`outputs` for the column
shapes.

``build-refs`` — rebuild the shipped table
------------------------------------------

The only command that reads the source vocabularies. See :doc:`etl`.

.. code-block:: console

   $ ruim2rxnorm build-refs --athena-dir ATHENA --ruim-dir RUIM --validate

Matching behaviour
------------------

A query is normalized (accent/case/whitespace/punctuation folded, dose stripped) and reduced to
a brand key, then matched against the shipped table:

1. **exact** brand-key hit;
2. else **whole-word prefix** — every table key that begins with the query key as a whole word,
   so an umbrella brand fans out to its variants;
3. else **no match**.

A curated ``source_aliases.csv`` layer can redirect a raw source label that is not a RUIM brand
(a local custom name, a foreign spelling) to an existing brand key before matching.
