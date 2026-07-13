"""Substance -> (individual ATC, RxNorm ingredient) resolver.

Implemented in step 9. Two-stage, ATC-as-bridge: French moiety name -> ATC-5th
(atc5_names + morphology + rxnorm_synonyms + overrides), then mono ATC -> RxNorm
ingredient via atc_rxnorm. Residuals are emitted with a reason, never dropped.
"""
