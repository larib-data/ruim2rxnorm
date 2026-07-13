# ruim2rxnorm

Map native **French drug (brand) names** → **ATC** → **RxNorm ingredient**, and emit an
OMOP-loadable mapping (`SOURCE_TO_CONCEPT_MAP`), for integrating French EHR/OMOP drug data
into the OMOP CDM.

## What it does

A French brand name (e.g. `DOLIPRANE`, `COVERAM`) is looked up in the ANSM RUIM speciality
table, decomposed into its active moieties, and each moiety is resolved to an **individual
ATC** code and a **RxNorm ingredient**. Combinations decompose into their individual
ingredients. Because a bare brand name carries no dose, the tool returns **all** candidate
ingredients rather than a single guess.

Mapping is **ingredient-level only** and the `map` / `map-file` commands run fully **offline**
on one small shipped table (`refs/brand_ingredient_map.csv`). The ~2 GB OMOP Athena dump and
the RUIM CSVs are needed **only** to (re)build that table via `ruim2rxnorm build-refs`.

```
map "COVERAM"  -> perindopril (C09AA04 / RxNorm 54552) + amlodipine (C08CA01 / RxNorm 17767)
map "DOLIPRANE" -> acetaminophen (N02BE01 / RxNorm 161)
map "AUGMENTIN" -> amoxicillin (J01CA04 / RxNorm 723) + clavulanate (RxNorm 48203)
```

## Install

This project is managed with [uv](https://docs.astral.sh/uv/). `uv sync` creates
the virtual environment, installs the package (editable) and the `dev` group:

```
uv sync                  # core (stdlib-only) + dev group (pytest)
uv sync --group docs     # also install the docs toolchain (sphinx)
uv run pytest            # run the tests
uv run ruim2rxnorm map "COVERAM"
```

The runtime core depends only on the Python standard library; `pip install .`
still works for consumers who don't use uv.

## Quick start

Map one or more names on the command line:

```console
$ ruim2rxnorm map COVERAM DOLIPRANE AUGMENTIN
COVERAM -> [amlodipine C08CA01 / RxNorm 17767, perindopril C09AA04 / RxNorm 54552]
DOLIPRANE -> [acetaminophen N02BE01 / RxNorm 161]
AUGMENTIN -> [amoxicillin J01CA04 / RxNorm 723, clavulanate ? / RxNorm 48203]
```

Batch-map a file and emit an OMOP `SOURCE_TO_CONCEPT_MAP`:

```console
$ ruim2rxnorm map-file names.csv --out-dir out/ --stcm
map-file: coverage report
  input names:        4
  matched a brand:    4 (100.0%)
  ...
  outputs:
    out/mapping.csv  (…)
    out/SOURCE_TO_CONCEPT_MAP.csv  (…)
```

`names.csv` may be a plain one-name-per-line list, or a CSV — use `--column NAME` to read a
named column from a CSV-with-header. Add `--usagi` for an OHDSI Usagi review file.

## Outputs

| output | command flag | shape |
| --- | --- | --- |
| `mapping.csv` | always | human-readable audit / coverage table, one row per ingredient |
| `SOURCE_TO_CONCEPT_MAP.csv` | `--stcm` | OMOP STCM (9 spec columns); `target_concept_id` = RxNorm ingredient **concept_id** |
| `usagi.csv` | `--usagi` | OHDSI Usagi curator-review input |

One `source_code` (brand) legitimately produces **multiple** STCM rows — this is how brand
ambiguity and combinations are represented. Unresolved moieties are emitted explicitly
(`target_concept_id = 0` + a reason), never silently dropped.

## Rx-Risk comorbidities (`ruim2rxrisk`)

A second console script, `ruim2rxrisk`, reuses the same French-name → ATC pipeline to
derive a patient's **comorbidities** via the **updated Rx-Risk Index** (52 conditions),
annotating each with its **ICD-10-AM** codes. The whole list of names on one invocation
is treated as **one person's medicines**; the output is the **distinct set of conditions**
present, an **unweighted score** (= number of distinct conditions), and a per-drug
breakdown.

```console
$ ruim2rxrisk DOLIPRANE COVERAM AUGMENTIN
DOLIPRANE -> [Pain - Paracetamol]
COVERAM -> [Hypertension]
AUGMENTIN -> no Rx-Risk condition

Rx-Risk conditions (2):
  Hypertension  (ICD-10 I10-I15)  <- COVERAM
  Pain - Paracetamol [new]  (ICD-10 -)  <- DOLIPRANE
Unweighted score: 2
```

`--file meds.csv [--column NAME]` reads a list/CSV instead; `--out-dir DIR` also writes
`rxrisk_conditions.csv`, `rxrisk_by_drug.csv` and `rxrisk_summary.csv`.

- **Scoring is unweighted** — the updated paper publishes no per-condition weights, so
  the score is the count of distinct conditions, exactly the measure it validates.
- **Some Table-1 qualifiers are dropped** (matched on plain ATC): PBS/RPBS item-code,
  route and strength limits; multi-medicine combination rules; the male-only gender
  restriction; and cross-condition exclusions. Benign ATC overlaps (e.g. `J05AF` shared
  by Hepatitis B and HIV) are retained and noted.

Source: Widagdo et al., "Validity of the Updated Rx-Risk Index…", *Clinical
Interventions in Aging* — open access under **CC BY-NC**. See
[`ruim2rxnorm/PROVENANCE.md`](ruim2rxnorm/PROVENANCE.md).

## Caveats

- **Ambiguity is preserved, not resolved.** A bare brand with no dose can span several ATC
  classes (`HUMEX` covers ~14). All candidates are returned with their support.
- **Combinations decompose via RUIM composition, not the combination ATC** — the combination
  ATC class (e.g. `J01CR02`) is not product-specific. Each moiety is resolved through its own
  mono speciality.
- **Ingredient-level only** — dose/form mapping is out of scope.

## Rebuilding the shipped table (`build-refs`)

`map` / `map-file` need no downloads. To refresh the mapping for a new Athena or RUIM release,
download both sources and run the ETL — the **only** command that reads them:

```
ruim2rxnorm build-refs \
    --athena-dir /path/to/athena_vocabulary \
    --ruim-dir   /path/to/RUIM_csv_files \
    --validate
```

- **OMOP Athena vocabulary** (ATC + RxNorm + RxNorm Extension) — download from
  [athena.ohdsi.org](https://athena.ohdsi.org/); point `--athena-dir` at the directory holding
  `CONCEPT.csv`, `CONCEPT_RELATIONSHIP.csv`, `VOCABULARY.csv`.
- **RUIM** (`terminologie-ref_interop_med`) — the ANSM interoperability bundle from
  [data.esante.gouv.fr](https://data.esante.gouv.fr/) (Licence Ouverte 2.0; redistribution
  permitted with attribution); point `--ruim-dir` at the directory holding `CIS.csv`,
  `Compositions_qualitatives.csv`, `Substances.csv`.

`--validate` re-checks the golden mappings and structural invariants and fails loudly on a bad
data drop. See [`ruim2rxnorm/PROVENANCE.md`](ruim2rxnorm/PROVENANCE.md) for the exact versions
built into the shipped table.

Two small curated files feed the build and grow by hand as real failures appear:

- `refs/overrides.csv` — substance moiety → ATC / RxNorm, for moieties never sold alone in
  RUIM (e.g. clavulanate, tazobactam) that have no individual ATC in any vocabulary.
- `refs/source_aliases.csv` — raw source label → RUIM brand key, for non-RUIM/custom/misspelled
  labels in your source data.

## Documentation

Full docs (overview, usage, ETL, outputs, provenance, API) build with Sphinx:

```
uv sync --group docs
uv run ruim2rxnorm-docs          # -> docs/_build/html (warnings treated as errors)
```

`ruim2rxnorm-docs` wraps `sphinx-build -W -b html docs docs/_build/html`; extra
arguments are forwarded (e.g. `uv run ruim2rxnorm-docs -- -a -E` for a clean rebuild).
