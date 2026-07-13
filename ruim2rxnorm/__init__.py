"""ruim2rxnorm — map French drug (brand) names to RxNorm ingredients via ATC.

French brand name --normalize--> CIS rows (RUIM) --composition--> active moieties
--resolver--> individual ATC + RxNorm ingredient --> OMOP SOURCE_TO_CONCEPT_MAP.

The core package depends only on the Python standard library. Large OMOP Athena
vocabulary tables are touched only by the ``build-refs`` ETL, which emits the
compact ``refs/`` tables shipped as package data.
"""

__version__ = "0.1.0"
