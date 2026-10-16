# GSS 2018: centered index and one fixed neutral question sequence

The native experiment completed successfully in
[GitHub Actions run 38921436426](https://github.com/zeroknowledgediscovery/DTAG/actions/runs/38921436426).
It used the ORIGINAL 38-item GSS 2018 pole (v2) and the native model
from the DTAG GCS release; production poles were not modified.

Definition: I_centered(x) = I_native(x) - I_native(empty).
Measured I_native(empty) = +0.0600465.

## Native starting-state check

| Persona reference | I_native | I_centered |
|---|---:|---:|
| CM (rich baseline) | +0.08637 | +0.02633 |
| WF (rich baseline) | +0.02426 | -0.03578 |

These are native GSS 2018 rich reference states (not the earlier minimal
core-only states, whose numerical indexes differ). Two protected fields:
polviews and partyid.

## First fixed-sequence descriptive evaluation

Exactly ONE independently sampled 10-question sequence, selected from
valid GSS 2018 source-map variables by a fixed random seed=2018, with
no reference to predicted ideological directions or downstream outcomes.
12 sampled starting states per persona, 6 response draws per state,
total 144 simulated trajectories. Bootstrap performed over distinct
starting-state clusters (not treating 6 draws as independent).

| Coordinate | Starting-sign group | Distinct states | Mean raw change | 95% state-bootstrap interval |
|---|---|---:|---:|---|
| Uncentered | positive | 23 | +0.00057 | [+0.00023,+0.00090] |
| Uncentered | negative | 0 | unavailable | unavailable |
| Centered | positive | 12 | +0.00008 | [-0.00035,+0.00055] |
| Centered | negative | 12 | +0.00117 | [+0.00086,+0.00142] |

One neutral-band-excluded raw state makes 23 (not 24) raw positive
distinct states. In the centered coordinate, 12 positive and 12
negative starting states were observed.

The observed two-sign change pattern is (++), meaning that the mean
raw change in the index was positive in both *centered-starting* groups.
**It is descriptive only, NOT confirmed by both bootstrap intervals**:
the positive group's CI straddles zero and the mean is near zero.
Do not score or advertise this sequence as robustly directional.
No sequence optimization, reordering, multiple-candidate trial,
or outcome-based stopping was performed.

Maximum absolute difference between raw and centered within-trajectory
displacements: 6.94e-18 (numerical floating-point round-off).
The shift changes sign classification and hence group composition,
not the underlying response trajectory displacements.

## Code and output

Runner: scratch/gss2018_pole_geometry/test_empty_centering.py
Artifact: https://github.com/zeroknowledgediscovery/DTAG/actions/runs/38921436426/artifacts/12054797167

The archived artifact contains the single preregistered
fixed_question_set.csv, both coordinate trajectory archives,
result.json and REPORT.md.

Neutral question-library generator: optimizer/sequence_library_runner.py.
New *centered-only* default: outputs/optimizer/sequence_library_empty_centered_v1.
Old outputs/optimizer/sequence_library files remain historical, and the
read-only audit script optimizer/sanitize_sequence_library.py writes
the legacy inventory without deleting or reclassifying source records.

Neither the separate legacy optimizer Searcher nor the DTAG web app was
altered; only the neutral observational sequence-library coordinate was
changed. This diagnostic concerns inference under a fixed LSM, not
real-world persuasion or observed changes in human ideology.
