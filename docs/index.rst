ruim2rxnorm
===========

Map native **French drug (brand) names** to **ATC** to **RxNorm ingredient**, and emit an
OMOP-loadable mapping (``SOURCE_TO_CONCEPT_MAP``), for integrating French EHR/OMOP drug data
into the OMOP CDM.

A French brand name (e.g. ``DOLIPRANE``, ``COVERAM``) is looked up in the ANSM RUIM speciality
table, decomposed into its active moieties, and each moiety is resolved to an individual ATC
code and a RxNorm ingredient. Combinations decompose into their individual ingredients; because
a bare brand name carries no dose, the tool returns **all** candidate ingredients rather than a
single guess.

The ``map`` / ``map-file`` commands run fully offline on one small shipped table
(``refs/brand_ingredient_map.csv``). The OMOP Athena dump and the RUIM CSVs are needed only to
(re)build that table via ``ruim2rxnorm build-refs``.

.. toctree::
   :maxdepth: 2
   :caption: Contents

   overview
   usage
   rxrisk
   etl
   outputs
   provenance
   api

Indices
-------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
