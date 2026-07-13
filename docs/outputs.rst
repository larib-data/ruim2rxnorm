Outputs
=======

``map-file`` serialises the matched ingredient rows into up to three shapes, each **one row per
individual ingredient** — so a combination or an umbrella brand naturally expands to several
rows. See :mod:`ruim2rxnorm.outputs`.

mapping.csv
-----------

Always written. The human-readable audit / coverage table: the input name, the matched
``brand_key`` and how it matched, and the resolved ingredient columns straight from the shipped
table. Unmapped moieties and whole ``no_match`` queries appear too, so the file doubles as a
coverage report.

Columns: ``input_name``, ``brand_key``, ``match_type``, ``n_specialities``, ``cis_atc``,
``substance_fr``, ``individual_atc``, ``libelle_atc``, ``rxnorm_concept_id``, ``rxnorm_code``,
``rxnorm_name``, ``is_combination``, ``status``, ``reason``.

SOURCE_TO_CONCEPT_MAP.csv (``--stcm``)
--------------------------------------

The loadable OMOP STCM table — a legacy-but-still-used OMOP CDM table for custom source-code
mappings. Nine spec columns:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - column
     - value
   * - ``source_code``
     - the normalized brand key
   * - ``source_concept_id``
     - ``0`` (no source concept)
   * - ``source_vocabulary_id``
     - ``FR_ANSM_BRAND`` (custom; override with ``--source-vocabulary-id``)
   * - ``source_code_description``
     - the original brand text
   * - ``target_concept_id``
     - the RxNorm ingredient **concept_id** (e.g. COVERAM -> ``1373225`` + ``1332418``)
   * - ``target_vocabulary_id``
     - ``RxNorm``
   * - ``valid_start_date`` / ``valid_end_date``
     - ``1970-01-01`` / ``2099-12-31``
   * - ``invalid_reason``
     - empty when mapped; the resolver reason when unmapped

.. important::

   ``target_concept_id`` is the RxNorm **concept_id** (``rxnorm_concept_id``), **not** the
   RxNorm code shown by ``map`` (COVERAM's ``17767`` / ``54552`` are codes; the concept_ids are
   ``1332418`` / ``1373225``).

One ``source_code`` legitimately has **multiple rows** — this is how brand ambiguity and
combinations are represented. An unresolved moiety maps to ``target_concept_id = 0`` with the
resolver reason in ``invalid_reason``, so the gap is explicit and never silently dropped;
``no_match`` queries are skipped.

usagi.csv (``--usagi``)
-----------------------

Optional input for the OHDSI Usagi review tool, for a curator to approve or fix the ambiguous /
unmapped rows. Columns: ``sourceCode``, ``sourceName``, ``sourceFrequency``, ``conceptId``,
``conceptName``, ``mappingStatus`` (``APPROVED`` for mapped rows, ``UNCHECKED`` for unmapped).
