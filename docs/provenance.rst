Data provenance
===============

Neither source vocabulary is vendored. The package ships only the compact ETL output
(``refs/brand_ingredient_map.csv`` plus the small curated and manifest files); the source
vocabularies are downloaded by the user and read only by :doc:`build-refs <etl>`.

The exact versions baked into the shipped table are recorded machine-readably in
``refs/REFS_MANIFEST.json`` and written up in ``ruim2rxnorm/PROVENANCE.md``. As of the current
build:

RUIM — ANSM
-----------

* **Release:** ``terminologie-ref_interop_med-2026-06`` (June 2026).
* **Publisher:** ANSM (Agence nationale de sécurité du médicament), via
  `data.esante.gouv.fr <https://data.esante.gouv.fr/>`_. Licence Ouverte 2.0 — redistribution
  permitted with attribution.
* Tables read: ``CIS.csv`` (15,922 specialities; ``codeATC`` on 100% of rows),
  ``Compositions_qualitatives.csv``, ``Substances.csv``.

OMOP Athena vocabulary
----------------------

* **Bundle:** ``v5.0 27-FEB-26``, downloaded from `athena.ohdsi.org <https://athena.ohdsi.org/>`_.
* Component versions: ATC ``2026-02-01``, RxNorm ``20260105``, RxNorm Extension ``2026-01-14``.
* The ~2 GB dump is not shipped.

Coverage
--------

For the versions above: 11,391 ingredient rows (8,713 mapped, 2,678 unmapped) across 8,755
distinct brand keys; **speciality coverage 15,035 / 15,922 = 94.4%** reach a RxNorm ingredient.
Unmapped residuals are dominated by homeopathy, excipients/minerals, and moieties never sold
alone, left as explicit failures for manual ``overrides.csv`` curation.

Reference-only
--------------

``ATC-RxNorm/`` — a 2023 MIE snapshot of the ATC↔RxNorm relationship set, retained for
method/provenance documentation only. It is superseded by the Athena-derived mapping now baked
into ``refs/brand_ingredient_map.csv`` and is not a runtime dependency.
