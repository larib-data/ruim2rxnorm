Overview
========

What it does
------------

``ruim2rxnorm`` turns a native French drug **brand** name into the OMOP-standard **RxNorm
ingredient(s)** it contains, bridged through the drug's **ATC** classification. The input
strings are brand names as they appear in French EHR/OMOP data (``DOLIPRANE``, ``AUGMENTIN``) —
typically without a dose — not codes.

The resolution, done entirely at build time, is:

.. code-block:: text

   French brand name
     -> RUIM specialities (CIS)          brand key -> the matching speciality rows
     -> active moieties                  composition (fraction thérapeutique)
     -> individual 5th-level ATC         each moiety's own mono-speciality codeATC (RUIM)
     -> RxNorm ingredient                ATC -> RxNorm (Athena)

Everything up to the ATC code is a **French-to-French RUIM lookup**; the only crossing into
RxNorm is by ATC code (via the OMOP Athena vocabulary). No substance name is ever translated or
matched against English.

Design decisions
----------------

**One precomputed table.** The ETL does the whole resolution offline and emits a single shipped
artifact, ``refs/brand_ingredient_map.csv`` (one row per ``brand_key × ingredient``). The
runtime just normalizes a query, extracts its brand key, and looks it up — no vocabulary
parsing, no composition logic, no Athena access at query time.

**Ambiguity is preserved, not resolved.** A bare brand with no dose can span several ATC
classes (``HUMEX`` covers ~14 products). The tool returns *all* candidate ingredients with
their support counts rather than guessing one.

**Combinations decompose via RUIM composition, not the combination ATC.** A combination's own
ATC class is not product-specific (``J01CR02`` = "amoxicillin and beta-lactamase inhibitor"
covers six different inhibitors), so the moiety list comes from the RUIM composition tables and
each moiety is resolved through its *own* mono speciality (``COVERAM`` -> perindopril
``C09AA04`` from COVERSYL + amlodipine ``C08CA01`` from AMLOR).

**Explicit failures, never silent drops.** A moiety never sold alone in RUIM (clavulanate,
tazobactam) has no individual ATC in any vocabulary. It is resolved only if a curated override
supplies one; otherwise it is emitted as ``unmapped`` with a reason, and (in STCM) a
``target_concept_id`` of ``0``.

Scope
-----

**Ingredient-level only.** Dose- and form-level mapping is out of scope (the Athena
``DRUG_STRENGTH`` / ``CONCEPT_ANCESTOR`` tables make it a possible future extension). The core
package depends only on the Python standard library.
