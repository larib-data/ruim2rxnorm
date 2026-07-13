Rx-Risk comorbidities
=====================

The separate ``ruim2rxrisk`` console script reuses the French-name → ATC pipeline
(:func:`ruim2rxnorm.lookup.default_index`) to go one step further: from a **patient's
list of French medicines** it derives the set of **Rx-Risk comorbidity conditions**
present, each annotated with its **ICD-10-AM** codes, plus an **unweighted score**
(= the number of distinct conditions) and a per-drug breakdown.

The whole list of names on one invocation is treated as **one person's medicines**.

Source
------

The mapping is transcribed from the *updated* Rx-Risk Index:

  Widagdo I, Kerr M, Kalisch Ellett L, *et al.* "Validity of the Updated Rx-Risk
  Index…", *Clinical Interventions in Aging* (`cia-20-309`).

Two tables are used: **Table 1** maps each of **52 conditions** to WHO ATC codes as
prefixes/classes with include/exclude carve-outs, and **Table 2** supplies ICD-10-AM
codes for **20** of those conditions (output annotation only — never matched against).
Nine conditions are new in this update. See :doc:`provenance` for the licence
(CC BY-NC) and the dropped-qualifier / overlap limitations.

Quick start
-----------

Names on the command line — the whole list is one patient:

.. code-block:: console

   $ ruim2rxrisk DOLIPRANE COVERAM AUGMENTIN
   DOLIPRANE -> [Pain - Paracetamol]
   COVERAM -> [Hypertension]
   AUGMENTIN -> no Rx-Risk condition

   Rx-Risk conditions (2):
     Hypertension  (ICD-10 I10-I15)  <- COVERAM
     Pain - Paracetamol [new]  (ICD-10 -)  <- DOLIPRANE
   Unweighted score: 2

Each drug prints its triggered conditions (or ``no Rx-Risk condition`` / ``no match``).
The summary lists the **distinct** conditions with their ICD-10 codes, the unweighted
score, and any names that matched no brand. AUGMENTIN (an antibiotic) contributes
nothing; unlike the 2018 paper, plain paracetamol now maps.

File input and CSV outputs
--------------------------

.. code-block:: console

   $ ruim2rxrisk --file meds.csv --column NAME --out-dir out/

The input file is a plain one-name-per-line list, or a CSV read with ``--column NAME``
(same reader as ``ruim2rxnorm map-file``). With ``--out-dir`` three CSVs are written:

* ``rxrisk_conditions.csv`` — one row per distinct condition: ``condition``, ``icd10``,
  ``contributing_drugs``, ``matched_atc``, ``is_new``.
* ``rxrisk_by_drug.csv`` — one row per input medicine: ``input_name``, ``brand_key``,
  ``match_type``, ``atc_codes``, ``conditions``.
* ``rxrisk_summary.csv`` — a single row: ``n_drugs``, ``n_matched_brand``,
  ``n_conditions`` (= the unweighted score).

Matching model
--------------

For each query the ATC codes are the **union** of every matched row's individual-level
ATC and its ``;``-split product-level (CIS) ATC, deduped and upper-cased. Each Table-1
condition is a set of **include** and **exclude** patterns, where a pattern is either a
**prefix** (matches ``code`` iff ``code.startswith(prefix)``; a full 7-char code is just
a length-7 prefix) or a **range** ``LOW-HIGH`` (matches iff ``LOW <= code[:len(LOW)] <=
HIGH``). A condition is present iff **some include matches and no exclude matches** — the
carve-outs also route intended double-counts (e.g. bupropion ``N06AX12`` to Smoking
cessation, not Depression; lithium ``N05AN01`` to Bipolar, not Antipsychotics).

Scoring is **unweighted**: the updated paper publishes no per-condition weights, so the
score is simply the count of distinct conditions — the measure the paper validates.

Limitations
-----------

Table-1 qualifiers that cannot be evaluated from a single drug's ATC are **dropped**
(matched on the plain codes) and noted in the map's ``notes`` column: PBS/RPBS item-code,
route and strength limits; multi-medicine combination rules; the male-only gender
restriction; and cross-condition exclusions. Known benign ATC overlaps (e.g. some
``J05AF`` agents map to both Hepatitis B and HIV) are left in and documented; because the
score counts each distinct condition once, an overlap can add a condition the paper's
footnotes would have disambiguated.
