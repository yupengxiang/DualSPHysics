# R6-N3 latest handoff

Generated: 2026-09-08T12:07:12.878433+00:00
Baseline: `dcfef001eed3889ca6a055619a31dd4964515638`  Branch at generation: `codex/lagrangian-fluid-exploration`

## Decision

`formal_v0.1 = NO_GO` and `development_authorized = false` remain invariant.
The N3 result is `candidate_same_cfl_h10_bridge_resolution_tv_blocked`: the two endpoint fine probes and the h10
coarse/medium/fine bridge all use the same controlled `cflnumber=0.1`, but the
other endpoint resolutions were not rerun under that recipe.  In addition, the
h10 coarse-to-medium distribution comparison is above its diagnostic TV gate.
Therefore this round does not admit a three-height, three-resolution T1
production recipe.

| item | result |
|---|---|
| endpoint CFL probe | `pass_full_time_no_identity_loss` |
| h10 same-CFL bridge | `pass_full_time_triplet_resolution_tv_blocked` |
| T2 material | `candidate_t2_numerical_reference_only` |
| CUDA candidate | `candidate_cuda_not_admitted` |
| G4/development | `not launched` |

## P1 identity cause

The old N2 fine losses are solver-native density exclusions, not top absorption;
the new CFL endpoint probes retain all fine-grid identities:

| case | status/audit | missing final identities | classification | native evidence |
|---|---|---:|---|---|
| `R6_F1_plain_dam_break_h09_fine` | `solver_exclusions_only` | 1 | `solver_exclusions_only` | `{'density': 1}` |
| `R6_F1_plain_dam_break_h11_fine` | `solver_exclusions_only` | 27 | `solver_exclusions_only` | `{'density': 27}` |
| `R6_N3_F1_plain_dam_break_h09_fine_cfl010` | `pass` | 0 | `no_missing_final_identities` | `{}` |
| `R6_N3_F1_plain_dam_break_h11_fine_cfl010` | `pass` | 0 | `no_missing_final_identities` | `{}` |

The identity-level report joins `PartOut` particle IDs to `RunPARTs.csv` native
counters, records the last valid state and failure window, and checks event
positions against the resolved GenCase particle envelope.  The physical top is
open geometrically but is not registered as an absorbing outlet.

## P2 endpoint and bridge evidence

| case | full-time audit | missing | classification |
|---|---|---:|---|
| `R6_N3_F1_plain_dam_break_h10_coarse_cfl010` | `pass` | 0 | `no_missing_final_identities` |
| `R6_N3_F1_plain_dam_break_h10_medium_cfl010` | `pass` | 0 | `no_missing_final_identities` |
| `R6_N3_F1_plain_dam_break_h10_fine_cfl010` | `pass` | 0 | `no_missing_final_identities` |

The two endpoint N3 cases each saved 1,501 frames and retained all initial
identities.  Solver `PartsOut=0` and `NpOutRho=0` were observed for both.  The
h10 bridge also has `PartsOut=0` for all three resolutions.  Pair comparisons
remain numerical diagnostics, not external-fluid validation.

| comparison | status | max TV / gate | max COM / gate (m) | max q90 / gate (m) |
|---|---|---:|---:|---:|
| `coarse_to_medium` | `fail_diagnostic` | 0.056904761904761875 / 0.05 | 0.04096581324518249 / 0.06 | 0.04397571086883545 / 0.06 |
| `medium_to_fine` | `pass_diagnostic` | 0.04836915535444947 / 0.05 | 0.02737614558257564 / 0.06 | 0.026804447174072266 / 0.06 |

The coarse-to-medium bridge is `fail_diagnostic` because max TV is
`0.056904761904761875` against a `0.05` gate; medium-to-fine is
`pass_diagnostic`.  This is recorded as a resolution-consistency blocker, not
as particle-identity loss.

## P3 material reference

Six existing bundles were reused (medium 256/512 seeds × substeps 2/4; fine
512 seeds × substeps 2/4).  The report stores full saved-time source-wise
target occupancy, cumulative first passage, active unknown, solver-identity
unknown, error, and support-gate rejection.  First passage and terminal
destination are separate; no survivor renormalization is used.

Supplemental same-physical-point groups: common_physical_points_medium: end-reliable=1.0, wall-crossings=0; common_physical_points_fine: end-reliable=1.0, wall-crossings=0.

| bundle | seeds | substeps | max target occupancy by source | max active unknown by source | first-passage mass by source |
|---|---:|---:|---|---|---|
| `R4_F1_plain_dam_break_fine_seeds512_substeps2` | 512 | 2 | `{'lower': {'max': 0.47823183760683763, 'time_s': 1.04303}, 'middle': {'max': 0.5727831196581197, 'time_s': 0.970092}, 'upper': {'max': 0.5394230769230769, 'time_s': 0.926014}}` | `{'lower': {'max': 0.005341880341880342, 'time_s': 0.422034}, 'middle': {'max': 0.0, 'time_s': 0.0}, 'upper': {'max': 0.0, 'time_s': 0.0}}` | `{'lower': {'censored_by_tracer_failure': 0.005341880341880342, 'observed': 0.5905448717948718, 'right_censored_end_of_window': 0.40411324786324787}, 'middle': {'censored_by_tracer_failure': 0.0, 'observed': 0.6040331196581197, 'right_censored_end_of_window': 0.3959668803418803}, 'upper': {'censored_by_tracer_failure': 0.0, 'observed': 0.5631410256410256, 'right_censored_end_of_window': 0.43685897435897436}}` |
| `R4_F1_plain_dam_break_fine_seeds512_substeps4` | 512 | 4 | `{'lower': {'max': 0.47823183760683763, 'time_s': 1.04303}, 'middle': {'max': 0.5727831196581197, 'time_s': 0.970092}, 'upper': {'max': 0.5394230769230769, 'time_s': 0.926014}}` | `{'lower': {'max': 0.005341880341880342, 'time_s': 0.421068}, 'middle': {'max': 0.0, 'time_s': 0.0}, 'upper': {'max': 0.0, 'time_s': 0.0}}` | `{'lower': {'censored_by_tracer_failure': 0.005341880341880342, 'observed': 0.5905448717948718, 'right_censored_end_of_window': 0.40411324786324787}, 'middle': {'censored_by_tracer_failure': 0.0, 'observed': 0.6040331196581197, 'right_censored_end_of_window': 0.3959668803418803}, 'upper': {'censored_by_tracer_failure': 0.0, 'observed': 0.5631410256410256, 'right_censored_end_of_window': 0.43685897435897436}}` |
| `R4_F1_plain_dam_break_medium_seeds256_substeps2` | 256 | 2 | `{'lower': {'max': 0.5904761904761905, 'time_s': 0.916033}, 'middle': {'max': 0.5865079365079365, 'time_s': 0.901053}, 'upper': {'max': 0.5129251700680272, 'time_s': 0.89818}}` | `{'lower': {'max': 0.006122448979591836, 'time_s': 0.411032}, 'middle': {'max': 0.0, 'time_s': 0.0}, 'upper': {'max': 0.0, 'time_s': 0.0}}` | `{'lower': {'observed': 0.6292517006802721, 'right_censored_end_of_window': 0.3707482993197279}, 'middle': {'observed': 0.5865079365079365, 'right_censored_end_of_window': 0.41349206349206347}, 'upper': {'observed': 0.5244897959183673, 'right_censored_end_of_window': 0.47551020408163264}}` |
| `R4_F1_plain_dam_break_medium_seeds256_substeps4` | 256 | 4 | `{'lower': {'max': 0.5904761904761905, 'time_s': 0.916033}, 'middle': {'max': 0.5865079365079365, 'time_s': 0.901053}, 'upper': {'max': 0.5129251700680272, 'time_s': 0.89818}}` | `{'lower': {'max': 0.006122448979591836, 'time_s': 0.411032}, 'middle': {'max': 0.0, 'time_s': 0.0}, 'upper': {'max': 0.0, 'time_s': 0.0}}` | `{'lower': {'observed': 0.6292517006802721, 'right_censored_end_of_window': 0.3707482993197279}, 'middle': {'observed': 0.5865079365079365, 'right_censored_end_of_window': 0.41349206349206347}, 'upper': {'observed': 0.5244897959183673, 'right_censored_end_of_window': 0.47551020408163264}}` |
| `R4_F1_plain_dam_break_medium_seeds512_substeps2` | 512 | 2 | `{'lower': {'max': 0.5884353741496599, 'time_s': 0.916033}, 'middle': {'max': 0.5714285714285714, 'time_s': 0.901053}, 'upper': {'max': 0.5142857142857142, 'time_s': 0.89818}}` | `{'lower': {'max': 0.011564625850340135, 'time_s': 0.940058}, 'middle': {'max': 0.0, 'time_s': 0.0}, 'upper': {'max': 0.0, 'time_s': 0.0}}` | `{'lower': {'censored_by_tracer_failure': 0.003401360544217687, 'observed': 0.6285714285714286, 'right_censored_end_of_window': 0.36802721088435375}, 'middle': {'censored_by_tracer_failure': 0.0, 'observed': 0.5857142857142857, 'right_censored_end_of_window': 0.4142857142857143}, 'upper': {'censored_by_tracer_failure': 0.0, 'observed': 0.5217687074829932, 'right_censored_end_of_window': 0.4782312925170068}}` |
| `R4_F1_plain_dam_break_medium_seeds512_substeps4` | 512 | 4 | `{'lower': {'max': 0.5884353741496599, 'time_s': 0.916033}, 'middle': {'max': 0.5714285714285714, 'time_s': 0.901053}, 'upper': {'max': 0.5142857142857142, 'time_s': 0.89818}}` | `{'lower': {'max': 0.011564625850340135, 'time_s': 0.940058}, 'middle': {'max': 0.0, 'time_s': 0.0}, 'upper': {'max': 0.0, 'time_s': 0.0}}` | `{'lower': {'censored_by_tracer_failure': 0.003401360544217687, 'observed': 0.6285714285714286, 'right_censored_end_of_window': 0.36802721088435375}, 'middle': {'censored_by_tracer_failure': 0.0, 'observed': 0.5857142857142857, 'right_censored_end_of_window': 0.4142857142857143}, 'upper': {'censored_by_tracer_failure': 0.0, 'observed': 0.5217687074829932, 'right_censored_end_of_window': 0.4782312925170068}}` |

Acceptance remains candidate T2 numerical reference only; source labels are
initial-depth measurement strata, not material lineage.

## P4 performance

Two saved windows were measured with NumPy reference, current exact CPU Torch,
and opt-in exact CUDA top-k.  HDF5/sidecar I/O, transfers, neighbor queries,
finite-wall sweep, integration, output encoding, warmup, and explicit CUDA
synchronization are recorded in the machine report.  Speedups were:

`cpu_torch_vs_numpy=0.7048538098823931`, `cuda_vs_numpy=0.9915312724069433`, `cuda_vs_cpu_torch=1.406719036635956`.

CUDA parity maxima were `5.551115123125783e-17 m` and
`2.3592239273284576e-16 m/s`; the 2× end-to-end gate is
`False`.  Production remains on CPU.

## Reproducibility and artifacts

- P0 compact profile: `campaigns/v0.1-candidate/r6-n3-phase-profile.json` (must remain under 100 KiB).
- P1 forensic evidence: `campaigns/v0.1-candidate/r6-n3-endpoint-forensics.json`.
- P2 endpoint closure: `campaigns/v0.1-candidate/r6-n3-endpoint-closure.json`.
- P2 h10 bridge: `campaigns/v0.1-candidate/r6-n3-bridge-h10.json`.
- P3 material reference: `campaigns/v0.1-candidate/r6-n3-material-reference.json`.
- P4 performance: `campaigns/v0.1-candidate/r6-n3-performance.json`.
- Raw BI4/attempt directories are intentionally ignored by Git but remain locally traceable from the reports and hashes.

## Remaining gate

To admit a same-recipe three-height T1 candidate, an explicitly authorized
follow-up would need the missing h09/h11 coarse and medium products under the
same accepted CFL recipe (or a reviewer-approved alternative).  This N3
budget stops after 2 endpoint probes + 3 bridge cases; no blind Cartesian scan,
F6 rerun, G4 ranking, or formal release was performed.
