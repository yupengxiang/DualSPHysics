# F3 continuation checkpoint — 2026-09-11 Asia/Shanghai

The full goal remains active: reproducible qualified numerical recipe, independent development trajectories, material tasks and real learning/recovery closure. No production resolution/control domain or full-window CFD material reference is qualified. Do not mark complete or redefine the goal as diagnostics.

## Live worker — revalidate, never duplicate

- Case: `F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_time_quarter`
- GPU4; verified PID214157; shell session73691.
- Attempt: `20260910T171636.775830Z-1ed8f09b`.
- Command: `OMP_NUM_THREADS=8 OPENBLAS_NUM_THREADS=1 .venv/bin/python -u -m scripts.f3_long_campaign run --dp .0075 --variant noslip_visco1_time_quarter`
- Native initialization: No-slip, No Penetration=False, ViscoBoundFactor=1, CFL=.0125, DtMin=5.530674216767470e-6, total108000 particles (34560 fluid).
- Preregistered timeout5400s. Shared runner now requires the entire timeout to fit remaining GPU budget, default1800s retained for older cases; finite positive limit at most7200s. Fourteen input/diagnostic-gate/resource tests passed.
- Poll the existing session through normalization and full audit. CPU activity window stays open while real work runs. Files or intent alone never prove liveness.

F3-NS1-SPATIAL-DIAGNOSTIC-DESIGN.json binds one spatial failure diagnostic to the completed coarse quarter-step audit. Same geometry/water volume, dp-dependent CELL3 initialization policy, native boundary recipe, amplitude1, full0–8.35s, output.01s and CFL/floor coefficients. This is not matrix expansion or development production.

## Completed numerical evidence

Original nominal and half-step boundary-velocity-zero long cases lost293/292 particles with sustained wall-tolerance exceedance. Gravity-only control passed with all fixed-scale drift metrics below.01. An ineffective XML no-slip attempt was stopped after CLI override was identified and remains charged. Corrected no-slip with boundary viscosity0 lost491 particles. Native recommended boundary viscosity1 eliminated exclusions but retained nominal wall crossings.

For no-slip, boundary viscosity1, dp=.01, full0–8.35s:

| Temporal level | Actual dt (s) | Crossings | Max nominal-wall depth | Longest outside streak | Exclusions |
|---|---:|---:|---:|---:|---:|
| nominal | 2.9954275e-5 | 15 | .00306335m | 19 frames | 0 |
| half | 1.49771375e-5 | 5 | .000922959m | 10 frames | 0 |
| quarter | 7.48856875e-6 | 7 | .003067303m | 17 frames | 0 |

All836 frames audited for each. None exceeded the .0051m registered wall tolerance, but all failed the unchanged nominal-wall crossing hard gate. Quarter session26452 is terminal: code0,1326.716s, native per-PART step counts sum1114955. No monotone elimination of crossings; do not keep halving time by default.

Nominal/half v2 diagnostic max TV=.000747482 and local velocity/U=.00133880. Half/quarter max TV=.001017053, COM/L=.000295940, q90/L=.001185172, mean velocity/U=.000877560, energy=.000503550, local velocity/U=.001352776, unmatched support mass1.53864e-9. All these macro differences are below.01; hard failure is not waived. Half/quarter timestamp mismatch <=7.488751e-6s. Full panels have content-addressed full_report paths/hashes.

scripts/f3_timestep_evidence.py reads native CSV step ranges (Steps counts are per PART and summed). scripts/f3_crossing_details.py reproduces identities, intervals, crossing times and endpoint depths; scripts/f3_failure_forensics.py separately reconciles exclusions, tolerance exceedance and nominal crossings.

## Fourth-layer option is prepared but not selected

F3-BOUNDARY4-INPUT-PREFLIGHT.json proves all14580 fluid initial positions unchanged, old42480 boundary points retained,15968 added (58448 total boundary). All execution parameters and driving hashes match the nominal three-layer NS1 source. GenCase empty driving-template overwrite was caught and repaired before any solver launch; native reader verifies167001 rows over0–8.35s.

F3-BOUNDARY4-COUPLING-PREFLIGHT.json bounds every new boundary point's distance to enclosing saved-fluid AABBs. Minimum bounds nominal/half/quarter=.031936675/.034077041/.031932712m, all above kernel radius.031843408m. Hence no direct kernel contribution at saved states or their linear chords. Unsaved stages and indirect cell-order effects are not ruled out. The generic DDT warning alone does not establish a useful repair. Four-layer CFD has NOT run. Its guarded script also waits for the latest coarse temporal audit; do not launch alongside the live spatial diagnostic.

## Observations, controls and material evidence

F3-V1-REAUDIT.json preserves and exactly reproduces historical failures (plain .015/.010 TV=.05216051407639587). V2 was prospectively frozen and manufactured-calibrated: .06m tent half-width, .06m cells, finite closed-wall truncation, explicit outside/missing mass, fixed-scale max TV calibration error.0015655. This supports macro observations, not thin films or pointwise truth. F3-CELL3-PROTOCOL.json defines fixed tank coordinates, native version-specific body forcing, complete0–8.35s input and target amplitude domain.9–1.1; these targets are not qualified results.

Material engineering512 seeds×2/4 substeps on short canary is historical evidence only. F3-MATERIAL-CONTACT-REPAIR.json reproduces an old tracer bug: substeps landing exactly on a wall could tunnel while trusted. Closed-segment non-tangential contact now invalidates the tracer; neighbour visibility remains open-segment. Contact may conservatively become unknown, never a fabricated resolved bounce. CFD code and hard gates unchanged.28 targeted tests passed after repair; shared resource accounting then passed6 focused tests.

Current tracer calibration: F3-MATERIAL-AFFINE-CALIBRATION-contact-v2.json. Shear/rotation×dp.010/.006,64 common physical seeds,0–.5s. Four configurations pass frozen path<=.001m/residence<=.01s/all-reliable/no-terminal-disagreement criteria; max path.000432117m, max residence.00636627s. Original and repaired calibration artifacts are byte-identical and retained separately. Both rounds charged. Historical canary trajectories retain old tracer hashes and have not been promoted to current qualified outputs. Still required: qualified full-window CFD source, cross-dp shared-seed material reference and hard endpoint.

## Independent data and learning — inputs only so far

F3-DEVELOPMENT-CANDIDATES.json freezes32 distinct complete forcing inputs and physical-lineage hashes, excluding qualification amplitudes. All CSVs reread and exact transforms/hashes checked. Eight pilot cases fixed first; stop expansion on systematic failures, never substitute survivors. Sixteen training amplitudes span[.940625,1.059375], four interpolation validation cases are inside, twelve public development extrapolation cases outside training support but within target reference domain. All share initial water geometry intentionally; no initial-state or broad-family generalization claim. Test-labelled role is public development, not a formal hidden test. Actual development solver cases=0.

F3-LEARNING-INPUT-CONTRACT.json binds a48-wide current-state/control/finite-wall adapter using fixed scales and native forcing. Reuses ParticleMLP/LocalInteraction and real eight-nearest-neighbour summaries. CPU control/prefix/finite-wall checks and untrained forward passes passed. The historical115-wide cup trainer still marks acceleration-only controls missing; do not launch it unchanged. Qualified loader/trainer integration, two routes×seeds17/29/43, autonomous score/failure panels, checkpoint recovery and GPU/end-to-end costs remain. Actual training attempts=0. Planned2 pilot+6 final attempts leave4 reserve within12.

## Next actions and limits

1. Finish current spatial worker and audit all frames. Run crossing/forensic/native-step reports. Compare to coarse quarter source with failed-source semantics when needed.
2. If integrity passes, register the remaining recipe-specific spatial/time/output/control-domain qualification; one passing run is not production qualification. If it fails, use full evidence to choose remaining bounded work. No threshold relaxation, particle deletion, posthoc projection or shortened horizon to manufacture a pass.
3. Only after T1/domain/input gates, run actual registered eight-case pilot, then remaining24 if batch integrity holds. Complete qualified material tasks, real learning and recovery/cost work.

Current ledger: qualification51/56, remaining5; materials10/32; CPU conservative597.236/768coreh; GPU budget charge8.335/64h including running timeout reservation and historical unknown reserves. Refresh before new work. Development40, training12, storage512GiB and expiry2026-09-16T00:00Z unchanged. GPUs0–3 protected, only one CFD solver, UUID/memory guards retained.

CPU768 approval is explicit. Qualification cap64 proposal remains pending: no owner answer yet; do not exceed56. Forecast63 assumed an earlier candidate succeeded and is conditional, not authorization or assurance about the refined recipe. Preserve all historical charges. Close CPU activity window once all real workers stop, not while a GPU solver is live.

Local checkpoints:9e73cfe (observations/long evidence),bada6a4 (temporal diagnostics),f580f90 (material contact repair),aeb030f (development inputs/learning adapter). No push, merge, formal release or hidden test generation.
