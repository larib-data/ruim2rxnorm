"""Mono ATC -> RxNorm ingredient lookup.

Implemented in step 8. Loads refs/atc_rxnorm_ingredient.csv (via
importlib.resources) into atc_code -> [(concept_id, code, name, relationship_id)].
Used only with single-substance (mono) ATC codes, never to expand a combination.
"""
