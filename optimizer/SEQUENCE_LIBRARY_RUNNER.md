# Local-first sequence library: one neutral candidate per invocation

The command in optimizer/sequence_library_runner.py generates ONE **outcome-independent**
GSS question sequence, evaluates the resulting LSM-index changes across several
synthetic initial-state specifications and appends an auditable attempt record to
a persistent local library. It does **not** optimize directional persuasion or
rejection-sample candidates until a desired ideology movement is achieved.

The CLI --type flag accepts ++, +-, -+, -- as an **anticipated observational
category**, and records whether that description agrees with the model output.
It is NOT an objective, a search constraint, or a criterion for keeping a set.
An observed category is named only if all starting-state specifications show
the same sign pair, with group-level bootstrap intervals excluding zero. In
other cases it is saved as unclassified. Every invocation persists one candidate
even when observed behavior is not supported or the anticipated label differs.

## Install and remote model provisioning

Clone the entire DTAG repository on the machine, then from its root:

    git switch dev
    git pull --ff-only origin dev
    python -m pip install -r requirements.txt
    export OPENAI_API_KEY=...  # needed for first persona decode for each GSS year

Required GSS maps (including 2016, 2018 and 2024), the wave-specific
ideology-pole CSVs, and the source persona text files are versioned in Git.
Do not download them from an unrelated website.

The model is installed on first use automatically via the SAME Python code
as the web app:

    scripts/fetch_models.py
    scripts/dtag_paths.py

The code downloads the model archive using the published Google Cloud Storage
manifest (defaults: bucket git-zeroknowledgediscovery-dtag, release v0.2.1).
It verifies the archive's SHA-256, safe-extracts the compressed native trees,
and reuses the installed model. Default model cache is:

    ~/.cache/dtag/models/gss/gss_2016
    ~/.cache/dtag/models/gss/gss_2018
    ~/.cache/dtag/models/gss/gss_2024

Override with DTAG_MODEL_ROOT. The public release may also be overridden by
DTAG_MODEL_RELEASE, DTAG_PUBLIC_BUCKET, and DTAG_MODEL_MANIFEST_URL.
The first persona decode per wave uses the LLM; the fully decoded base states
are then cached under library/cache/gss_YEAR_base_personas.json. These fixed
base states are used on subsequent runs so per-wave source decoding cannot
drift. This is an experimental cache; check provenance before sharing.

## Run (one new candidate per invocation)

    python -m optimizer.sequence_library_runner \
      --year 2024 --type '++' --workers 4

    python -m optimizer.sequence_library_runner \
      --year 2018 --type '+-' --freezeinit --length 12 --workers 4

    python -m optimizer.sequence_library_runner \
      --year 2016 --type '--' --min-length 10 --max-length 20 \
      --plateau-tolerance 0.0005 --plateau-window 3 \
      --states 30 --draws 10 --specifications 5 --workers 4

Always quote the type value in your shell: '--' must not be mistaken for a
separator, and '+-' must not be interpreted as a shell option. An explicit
--length sets a fixed length (10-20). Otherwise, the script samples a
candidate with --max-length questions (default 20), estimates a prefix
length on an **independent pilot**, and validates only the selected prefix.

The pilot uses a **sign-neutral plateau rule**: stop at the first length at
least --min-length (default 10) where both groups' absolute, signed-agnostic
mean *additional* index changes are no greater than --plateau-tolerance
for --plateau-window consecutive questions (default three). If no plateau is
observed, use --max-length (default 20). This does NOT stop when a desired
political separation or shift is attained. Pilot responses are excluded from
validation and from the reported uncertainty and z-scores.

## Persona protection and robustness

The two original persona descriptions are read from the existing CM/WF text
assets and decoded separately for each GSS wave against that model's legal
survey labels. No 2024-specific expected-state reference is imposed on an
earlier survey wave.

By default, only polviews and partyid remain immutable. Every other
persona assignment may be dropped or resampled in the LSM's initialization.
--freezeinit locks all assignments retained in each specification.

The script assesses --specifications (default 5) separately constructed
initial descriptions. Specification 0 uses the decoded base state; later
specifications omit increasingly many of the *noncore* assignments (up to
approximately 40%). Each specification samples --states distinct initial
state attempts per persona (default 30) and --draws response replicates
per starting state (default 10). Actual state duplicates remain one
cluster; directional confidence intervals resample distinct states.
The final record contains results for every specification.

Note that these are perturbations of two synthetic descriptions, not
independent population samples or clinical/trial evidence. A fully frozen
configuration still varies the *set of assignments* across specifications
before locking them individually.

## 0-to-10 robustness score and naming

The score is a rounded, clipped, conservative z-like signal-to-noise ratio
computed from **distinct starting-state means**, not raw response draws.

For group g, specification p and the OBSERVED sign direction s_g:

    z[g,p] = s_g * mean(raw_delta[g,p]) / SE(raw_delta[g,p])
    z_robust = min(z[g,p] for all g,p)
    score = clip(round(z_robust), 0, 10)

Both groups must show compatible signs and a 95% state-cluster bootstrap
interval excluding zero **in every specification** before a category
is treated as confirmed. Unknown/unstable scores are recorded as 0.
The quality score is *not used to sample, reroll, truncate, filter, or
otherwise choose survey questions*. An observed result of zero does not
mean the selected questions were bad; it means robust direction support
was not demonstrated in this narrow synthetic study.

Filename: OBSERVED_CATEGORY_score__YEAR__NNN.csv; the numeric NNN is
sequential within observed category/year. An unsupported or
specification-inconsistent outcome uses unclassified_score__YEAR__NNN.csv.
The requested --type is retained separately in metadata to avoid false labels.

Examples of filename shape:

    ++_7__2024__001.csv
    +-_0__2018__001.csv
    unclassified_0__2016__001.csv

This library is an observational research audit of fixed-model changes,
not a collection of causally validated political attitude interventions.

## Persistent output

Default root: outputs/optimizer/sequence_library (excluded from Git).
Each run creates:

    library.json                        # append-only attempt manifest
    sequences/TYPE_score__YEAR__NNN.csv # one outcome-labeled file per completed run
    attempts/00001/
      run_parameters.json
      candidate_full.csv                # all sampled questions, including unused suffix
      pilot_length.json                 # only for variable-length runs
      question_set.csv                  # chosen question prefix
      result.json                       # observed signs, z, score, per-spec results
      spec_00/
        personas.yaml
        validation_trajectories.npz
        per_state.csv
        analysis.json
        manifest.json
      ...
    cache/gss_YEAR_base_personas.json   # frozen LLM-decoded base
    cache/gss_YEAR_setup/bank.jsonl
    cache/gss_YEAR_llm_cache.json

On a run failure, the attempt is still persisted with status failed and an
error.json file. A file lock serializes local invocations. Don't use this
same-directory flock locking arrangement for multiple concurrent MCC nodes;
we will implement a queue/job-ID and merger arrangement separately.

To list completed sets:

    find outputs/optimizer/sequence_library/sequences -name '*.csv' | sort

To view the library manifest:

    python -m json.tool outputs/optimizer/sequence_library/library.json | less

The older multi-year scanner can independently inspect new spec-level
trajectory files (which have manifest.json) using:

    python -m optimizer.multiyear_regime_summary \
      --runs-root outputs/optimizer/sequence_library \
      --out outputs/optimizer/multiyear_library_audit \
      --years 2016 2018 2024 --target-per-cell 3

This is a RUN inventory; per-specification revalidations must not be
misinterpreted as independent unique question sets. The canonical
deduplicated unit in the new library is the candidate sequence digest
and run_id, not one spec-level NPZ file.

Run the unit suite:

    python -m pytest -q optimizer/tests

## Limitations

This script needs internet and an available OpenAI-compatible credential for
the first decoding of each wave. The model files themselves come from the
public Google Cloud bucket, while source maps, poles and persona texts come
from the Git checkout. Starting-state stability is assessed only against
perturbations of the two source personas. The fixed native model is not an
empirical test of causal political persuasion, and the code does not adapt
wording or choose candidates to produce a requested ideological effect.
