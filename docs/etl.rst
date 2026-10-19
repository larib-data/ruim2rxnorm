The build-refs ETL
==================

``build-refs`` is the offline, rerunnable ETL that keeps the tool current across Athena and RUIM
releases. It is the **only** command that reads the source vocabularies; the runtime never
touches them.

.. code-block:: console

   $ ruim2rxnorm build-refs \
         --athena-dir /path/to/athena_vocabulary \
         --ruim-dir   /path/to/RUIM_csv_files \
         --validate

It reads the large tables streaming, resolves the full brand-to-ingredient mapping, and writes
``refs/brand_ingredient_map.csv`` + ``refs/REFS_MANIFEST.json`` (by default into the package's
shipped ``refs/`` directory; override with ``--out``).

Inputs
------

**OMOP Athena vocabulary** (``--athena-dir``) — ATC + RxNorm + RxNorm Extension. Needs
``CONCEPT.csv``, ``CONCEPT_RELATIONSHIP.csv``, ``VOCABULARY.csv``. Athena tab files contain
literal ``"`` inside drug names and are read with ``delimiter='\t'``, ``quoting=csv.QUOTE_NONE``
and ``field_size_limit(sys.maxsize)`` (see :mod:`ruim2rxnorm.etl.athena_io`); a default parser
silently merges lines and drops concepts.

**RUIM** (``--ruim-dir``) — needs ``CIS.csv``, ``Compositions_qualitatives.csv``,
``Substances.csv`` (standard comma CSV).

See :doc:`provenance` for where to download each and the versions in the shipped table.

Pipeline
--------

.. code-block:: text

   CIS.csv            -- brand-key extraction --> brand_key -> [CIS rows]     (etl/ruim_io.py)
   Compositions       -- fraction thérapeutique --> active moieties          (etl/resolve.py)
   substance          -- RUIM mono speciality --> individual 5th-level ATC   (etl/resolve.py)
   ATC                -- Athena ATC->RxNorm --> RxNorm ingredient            (etl/resolve.py)
   union / dedup by substance                                                (etl/build_refs.py)
     -> refs/brand_ingredient_map.csv  +  refs/REFS_MANIFEST.json

Stage 1 groups CIS specialities by normalized brand key. Stage 2 takes each CIS's
``fraction thérapeutique`` composition rows (falling back to ``substance active`` for salt-free
mono drugs) as the active moieties. Stage 3 resolves each moiety to its individual ATC from the
RUIM speciality where it is the sole moiety, then to a RxNorm ingredient via Athena — the only
place Athena is consulted, and never against a substance *name*.

When a substance's mono specialities carry different ATC codes (RUIM miscodes a few: PROFEMIGR,
a ketoprofen, is coded ``M01AE01``, ibuprofen), the code is picked by: codes Athena maps to a
single RxNorm ingredient first (a combination class maps to several), then the most
specialities, then the smallest code.

Curated layers
--------------

Both ship (nearly) empty and grow by hand as real failures appear:

* ``refs/overrides.csv`` — ``substance_code_or_name, atc, rxnorm_concept_id, note``. For a
  moiety never sold alone in RUIM (no individual ATC in any vocabulary), an override supplies a
  curated ATC (still bridged to RxNorm by Athena) or a hand-picked RxNorm ``concept_id`` (looked
  up by id, not by name). Seeded with clavulanate and tazobactam.
* ``refs/source_aliases.csv`` — ``source_label, brand_key, note``. Redirects a non-RUIM /
  custom / misspelled source label to an existing RUIM brand key (a lookup-time layer).

Validation
----------

``--validate`` re-checks invariants and fails loudly on a bad data drop:

* golden end-to-end mappings present — ``COVERAM`` -> {perindopril, amlodipine}, ``DOLIPRANE``
  -> acetaminophen, ``AUGMENTIN`` -> amoxicillin mapped + clavulanate row present;
* no duplicate ``(brand_key, rxnorm_concept_id)`` among mapped rows;
* non-empty table, complete manifest, and speciality coverage at or above the threshold.
