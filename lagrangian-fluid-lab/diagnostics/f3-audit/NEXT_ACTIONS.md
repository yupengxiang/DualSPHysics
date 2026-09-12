# F3 continuation checkpoint — 2026-09-12 Asia/Shanghai

The full goal remains active: reproducible qualified numerical recipe, independent development trajectories, material tasks and real learning/recovery closure. No production resolution/control domain or full-window CFD material reference is qualified. Do not mark complete or redefine the goal as diagnostics.

## Live continuation at2026-09-12T08:16Z

NP02 zero drive completed on GPU4: all836 frames pass hard audit, issues=[]/unknowns=[]. Full-window v2 drift maxima all below.01 (largest q90/L=.0052310963; TV=.0019360758). Report F3-NP02-ZERO-DRIFT.json is a preliminary single-control score, not a stage/domain gate.

NP03 half-step completed with836-frame hard pass and all temporal v2 differences<=.01 (max local velocity/U=.001601315). Actual dt min/max ratios both.5. Session97324 and its wrapper/worker are terminal. NP04 .002s output is RUNNING, session3833, lifecycle F3-NP04-WORKER-2cfee69670c8.json. Revalidate actual process/log before acting. NP05 .0075m is prepared but has not run. Start the next entry only after current terminal audit; use scripts/f3_gpu_worker.py ENTRY for verified private GPU runtime and lifecycle accounting. Never repeat NP01/NP02/NP03.

Qualification execution is frozen in F3-NATIVE-NOPEN-EXECUTION-STAGE.json, with the approved72 cap and NP01 pass bound. scripts/f3_nopen_qualification.py passed33 CPU tests plus real read-only initial checks at all3 resolutions. scripts/f3_nopen_stage_score.py passed16 CPU tests, including peaks between coarse output times; no actual complete stage gate exists yet. scripts/f3_nopen_development.py is implemented/tested but real development remains0; it requires full domain qualification and all8 original pilots before expansion.

Latest count:55/72 qualification attempts including live NP04. Prior07:08 snapshot before NP04:54/72;0/40 development,0/12 training,10/32 materials; Refresh ledger for live GPU/CPU charges; caps remain64h/768coreh. Shared ledger now includes separate training-attempt fees and conservative CPU addition. Training launcher production contract validation remains pending; no production training has been launched. CFD forward CPU reservation includes the solver timeout plus10min normalization/audit allowance at17.6cores.

## Completed NP01 worker — never duplicate

- Case: `F3_CELL3_LONG_dp0p01_a1p000_noslip_visco1_nopen`
- GPU4 completed successfully; solver PID1204721, shell session89392, wrapper PID1204658 and runner PID1204680 are terminal. Lifecycle finished2026-09-12T07:29:20Z.
- Attempt: `20260912T072256.206799Z-30e6322a`; started2026-09-12T07:22:56Z.
- Native log confirms `SlipMode="No-slip"`, `No Penetration=True`; unchanged .01m CELL3 particles, amplitude1, CFL/floor.05, output.01s, horizon8.35s, boundary viscosity1, artificial fluid viscosity.05, shifting0.
- One attempt only, timeout1800s. Runtime uses process-local matching NVIDIA libraries (see GPU_RUNTIME.md); ordinary system nvidia-smi still has a driver/library mismatch.
- F3-NATIVE-NOPEN-WORKER-LIFECYCLE.json records wrapper/runner IDs and final status. The wrapper closes its CPU activity window after the solver and postprocessing return; reopen an activity window for subsequent real work. Never infer liveness from this file alone.
- F3-NATIVE-NOPEN-DESIGN.json preregisters the single contrast. The new native option changes near-wall velocity and integrated displacement. Do not call it the old no-projection recipe, reuse old convergence qualification, or infer qualification from the option name.
- Independent review confirmed unchanged BI4/control bytes and the sole XML NoPenetration change. Seventeen input/attempt/budget guard tests passed. Completed native initialization must be present before auditing, including reused latest results; any existing attempt blocks a second launch even if latest.json is missing.

The previous .0075m quarter-step worker (session73691/PID214157) is TERMINAL, not live. It finished2026-09-10T17:48:45Z,1928.249s; full836-frame audit failed with2 position exclusions and115 nominal crossings across113 particles. Maximum nominal penetration.018734459m, longest nominal outside streak44 frames; first tolerance exceedance6.280003s,37 offending frames, longest tolerance-exceedance streak15frames. Native dt5.530674216767470e-6s;1,509,684 steps. Both missing IDs are reconciled with native position exclusions (one ymin, one ymax).

Coarse/fine quarter-step v2 diagnostic maxima: TV.016339868, local velocity/U.033993224, mean velocity/U.034459113, energy.031977537, COM/L.009057626, q90/L.006986313. These macro differences are below spatial.05 but cannot waive hard failures. Full archived panels are hash-bound;13 full_report archives verified.

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

1. NP01 completed: all836 frames,14580 particles, zero exclusions/crossings/nonfinite values, issues=[] and unknowns=[]. This passing source is not production qualification. Register and execute NP02 zero drive, NP03 half-step, NP04 .002s output, NP05/06 spatial controls under the shared single-solver guard.
2. F3-NATIVE-NOPEN-QUALIFICATION-PLAN.json gives a deduplicated conditional minimum of14 new runs including this single contrast, total65 from the prior51. The historical conditional plan remains launch_allowed=false; a separate execution registration binds the approved limits and passed NP01. User explicitly approved cap72 at2026-09-12T07:31:35Z; old64 proposal is superseded. Production dp changes or extra diagnostics can require more.
3. Only after full T1/time/output/spatial/domain gates, run the registered eight-case development pilot, then remaining24 if integrity holds. Complete full-window cross-dp material tasks, two learned routes×3seeds, autonomous failures, checkpoint recovery and cost evidence.

Engineering additions: F3FrameReader refuses training mode and failed sources, keeps full IDs/mass and separates current/past inputs from targets. Seven reader/input checks passed and a real14580-particle frame20 read used only[0,20,19]. EngineeringF3Rollout uses the new explicit direct-displacement/(U*dt) convention, not the historical next-velocity/trapezoidal trainer. Eleven rollout/input checks passed; real short-canary initial state completed5 fake-model autonomous CPU steps after reader closure, with no later fluid reads. Reports explicitly retain training/reference qualification=false. Actual independent development CFD and actual training remain0.

Historical snapshot immediately after NP01:52/72 qualification attempts (see current live snapshot above); materials10/32; CPU cap768 approved; GPU64h, development40, training12, storage512GiB and expiry2026-09-16T00:00Z unchanged. Refresh ledger for current charges. GPUs0–3 protected; only one CFD solver; UUID/memory guards remain.

RESOURCE-PAUSE-RECONCILIATION-20260912.json preserves the previously captured606.118coreh and all historical charges. The prior worker's final audit was written17:49:24Z on Sept10; a further five-minute full-rate cleanup reserve closes the unclosed window, with its inferred-bound semantics explicit. The inactive task gap is not treated as live compute. This continuation opens at2026-09-12T06:58Z. Original ledger/window bytes and full audit are archived by hash. No CPU approval has been requested again or historical charges reset.

Local checkpoints:9e73cfe (observations/long evidence),bada6a4 (temporal diagnostics),f580f90 (material contact repair),aeb030f (development inputs/learning adapter). No push, merge, formal release or hidden test generation.

Latest engineering update: scripts/f3_local_neighbors.py replaces unreliable float32 distance-threshold self exclusion with explicit ID exclusion and exact distance/ID ordering in the active F3 rollout. F3-LOCAL-IDENTITY-REPAIR.json binds the new code and measured single-CPU initial-state check; historical rollout/learning reports retain their old hashes. Training must bind this prospective feature revision.
