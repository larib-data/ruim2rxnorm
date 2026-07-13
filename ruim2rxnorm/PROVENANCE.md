# Data provenance

The versions below are the ones baked into the shipped `refs/brand_ingredient_map.csv`.
They are recorded machine-readably in `refs/REFS_MANIFEST.json` by the `build-refs` ETL and
should be regenerated from it on every rebuild.

## What is shipped vs. downloaded

Neither source vocabulary is vendored. The package ships **only** the compact ETL output:

- `refs/brand_ingredient_map.csv` — the precomputed brand → ingredient mapping (one row per
  `brand_key × ingredient`); the sole data the runtime reads.
- `refs/overrides.csv`, `refs/source_aliases.csv` — small curated build/lookup layers.
- `refs/REFS_MANIFEST.json` — provenance + coverage manifest.

The source vocabularies (Athena ~2 GB, RUIM CSVs ~9 MB) are downloaded by the user and read
**only** by the offline `build-refs` ETL — never at runtime.

## RUIM — Référentiel Unique et Interopérable du Médicament (ANSM)

- **Release built into the shipped table:** `terminologie-ref_interop_med-2026-06` (June 2026).
- **Publisher:** ANSM (Agence nationale de sécurité du médicament), France, via
  data.esante.gouv.fr. Licence Ouverte 2.0 (redistribution permitted with attribution).
- **Tables read by the ETL** (from the RUIM CSV distribution):
  - `CIS.csv` — 15,922 specialities. Brand name is the leading text of `libelle`; `codeATC`
    populated for 100% of rows. (`gamme` empty in all rows.)
  - `Compositions_qualitatives.csv` — qualitative composition. `relationSubstance` values:
    `fraction thérapeutique` (the therapeutic moiety used for mapping), `substance active`,
    `substance portant le dosage`.
  - `Substances.csv` — substances: `libelle_fr` + `synonymes_fr`.

## OMOP Athena vocabulary (ATC / RxNorm / RxNorm Extension)

- **Athena bundle version:** `v5.0 27-FEB-26` (recorded in `refs/REFS_MANIFEST.json` from
  `VOCABULARY.csv`).
- Component vocabulary versions in this bundle: **ATC 2026-02-01**, **RxNorm 20260105**,
  **RxNorm Extension 2026-01-14**.
- Downloaded from athena.ohdsi.org. The ~2 GB dump (`athena_vocabulary/`) is **not shipped**.
- **Athena parsing note:** Athena tab files contain literal `"` inside drug names and must be
  read with `delimiter='\t'`, `quoting=csv.QUOTE_NONE`, and `csv.field_size_limit(sys.maxsize)`
  — see `etl/athena_io.py`. A default parser silently merges lines and drops concepts.

## Coverage of the shipped table

From `refs/REFS_MANIFEST.json` for the versions above:

- 11,391 ingredient rows (8,713 mapped, 2,678 unmapped) across 8,755 distinct brand keys.
- **Speciality coverage: 15,035 / 15,922 = 94.4%** reach a RxNorm ingredient.
- Unmapped residuals are dominated by homeopathy, excipients/minerals, and moieties never sold
  alone; they are explicit failures left for manual `overrides.csv` curation.

## Rx-Risk comorbidity map (`refs/rxrisk_map.csv`)

The `ruim2rxrisk` console script maps a patient's ATC codes to Rx-Risk comorbidity
conditions. Its shipped table is hand-transcribed from the **updated** Rx-Risk Index.

**Source paper (used — the map is transcribed from its Table 1 + Table 2):**

> Widagdo I, Kerr M, Kalisch Ellett L, Schlegel C, Sadeqzadeh E, Wang A, Clarke AL,
> Pratt N. "Validity of the Updated Rx-Risk Index as a Disease Identification and
> Risk-Adjustment Tool for Use in Observational Health Studies." *Clinical Interventions
> in Aging*. 2025;20:309. Quality Use of Medicines and Pharmacy Research Centre,
> University of South Australia. Open access, **CC BY-NC 4.0**
> (<https://creativecommons.org/licenses/by-nc/4.0/>), Dovepress / Taylor & Francis.
> Local extracted copy: `chandra/cia-20-309/` (untracked working artifact).

**Prior paper (superseded — retained for method lineage, NOT transcribed):**

> Pratt NL, Kerr M, Barratt JD, Kemp-Casey A, Kalisch Ellett LM, Ramsay E,
> Roughead EE. "The validity of the Rx-Risk Comorbidity Index using medicines mapped to
> the Anatomical Therapeutic Chemical (ATC) Classification System." *BMJ Open*.
> 2018;8:e021122. doi:10.1136/bmjopen-2017-021122. Open access, **CC BY-NC 4.0**.
> Local extracted copy: `chandra/e021122.full/` (untracked working artifact). The user
> considers this version outdated; the shipped map does **not** use its 7-char ranges.

- **License:** both papers are open access under **CC BY-NC 4.0** — attribution,
  non-commercial. Only the ATC ↔ condition ↔ ICD-10 mapping (facts / short codes) is
  transcribed from the updated paper, not article prose.
- **What is transcribed:** Table 1 → the 52 conditions with their WHO ATC include/exclude
  patterns (`atc_include` / `atc_exclude`, as prefixes and `LOW-HIGH` ranges); Table 2 →
  ICD-10-AM codes for the 20 conditions that carry them (`icd10`, output annotation only,
  never matched against). Nine conditions are flagged `is_new`.
- **Qualifiers omitted** (dropped to plain-ATC matching, noted per row in `notes`):
  PBS/RPBS item-code, route and strength restrictions; multi-medicine combination rules
  (e.g. congestive-heart-failure `C03CA + …`); the male-only gender restriction
  (benign prostatic hyperplasia); and cross-condition exclusions. Known benign ATC
  overlaps (e.g. `J05AF` agents shared by Hepatitis B and HIV) are retained and noted.
- **Scoring is unweighted** — the updated paper publishes no per-condition weights, so
  the score is the count of distinct conditions, the measure the paper validates.

The name → ATC step reuses `refs/brand_ingredient_map.csv` above; Rx-Risk itself is
ATC-only and needs no RxNorm resolution.

## Reference-only (not a runtime dependency)

- `ATC-RxNorm/` — 2023 MIE snapshot of the ATC↔RxNorm relationship set; retained for
  method/provenance documentation only. Superseded by the Athena-derived mapping now baked into
  `refs/brand_ingredient_map.csv`.
