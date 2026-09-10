# F3 continuation checkpoint — 2026-09-11 Asia/Shanghai

Full goal remains active: qualified reproducible F3 recipe, independent development cases, and material/learning closure. No production resolution or control interval is qualified. This is progress, not DONE or an external blocker.

## Live focused diagnostic — revalidate before continuing

`F3_CELL3_LONG_dp0p01_a1p000_noslip_visco1_time` is running on GPU4, verified solver PID 184678, attempt `20260910T163308.432433Z-743cf17a`, shell session 26723. Poll the existing handle; do not duplicate. Native log confirms No-slip, No Penetration=False, ViscoBoundFactor=1, CFL=.025, DtMin=1.49771375e-5. Wait for full solver, normalization and audit. CPU activity window remains open while the worker runs.

F3-NS1-TIME-DIAGNOSTIC-DESIGN.json preregisters exactly one hash-bound failed-canary temporal diagnostic. This is an explicit scoped amendment, not a passed-canary qualification. Nine gate/input tests passed, including rejection of resolution/amplitude/output expansion and changed predecessor evidence.

Completed CROSSING-DETAIL.json resolves the 15 events: actual saved positions are outside nominal wall planes, maximum depth 0.00306335 m, longest 19 outside frames. These are not artifacts of connecting two interior endpoints. All remain below the 0.0051 m tolerance; hard crossing gate remains failed. Native NoPenetration applies velocity/displacement corrections, so enabling it would change the registered no-projection recipe.

## Prepared next diagnostic option (not launched)

`scripts/f3_boundary_support_preflight.py` generated a four-layer candidate and checked native input. F3-BOUNDARY4-DESIGN.json and F3-BOUNDARY4-INPUT-PREFLIGHT.json bind the evidence. h/dp=1.59215, so the native documented 2h <= layers*dp condition needs at least four layers. Original 42,480 boundary points are retained; 15,968 external boundary points added, giving 58,448. All 14,580 fluid positions are exactly unchanged. Physical normal-generating wall surfaces, open top and dynamics parameters are unchanged. This is not a solver launch and does not qualify a recipe.

GenCase overwrote the pre-copied acceleration file with an empty template; caught before any solver. The script now restores the official drive after GenCase. The repaired candidate passes the native acceleration reader with 167,001 rows covering 0–8.35 s and the original SHA256. The defect and repair are retained in the preflight report. The native DDT warning checks h/dp but does not inspect layer count, so warning disappearance is not proof of correctness.

Wait for NS1 temporal diagnostic before choosing whether to launch this candidate. It needs a new immutable prepared record, resource checks, original hard audit and its own qualification if selected.

## Latest completed work

Session 52165 completed solver, normalization and audit for `F3_CELL3_LONG_dp0p01_a1p000_noslip_visco1`, attempt `20260910T162141.469237Z-ba96b65c`. GPU4 solver completed code 0 in 339.243 s; all 836 frames were audited. Effective no-slip and ViscoBoundFactor=1 were verified. There are zero native exclusions, missing IDs and wall-tolerance exceedances, but 15 nominal wall-plane outward crossings across 13 intervals. First crossing: 4.746602 s, left wall. The unchanged hard audit is `quality_failed`. No worker from this case remains.

Earlier corrected CLI no-slip with boundary viscosity factor 0 completed with 491 exclusions and true wall-tolerance exceedance. Both FORENSICS reports are retained. Neither recipe is qualified.

## Completed evidence

- `F3-CELL3-PROTOCOL.json`: registered 0–8.35 s; candidate dp=0.010, finer references 0.0075/0.006; amplitudes 0.9/1.0/1.1 and independent 0.97; fixed computational tank frame and version-specific forcing. These are targets, not qualifications.
- `F3-V2-OBSERVATION-DESIGN.json` and `diagnostics/f3-audit/v2-calibration.json`: fixed 0.06 m tent half-width (0.12 m support), 0.06 m cells, conservative closed-wall truncation, explicit outside/missing mass. Manufactured static/translation/rotation/volume-preserving shear calibration passed; all origin/bin-scale sensitivities retained. Fixed-scale max TV error 0.0015655, shared-support velocity error/U 0.00011985; reference quadrature difference below 0.00000812. Held-out translation/counterflow/missing/outside controls passed. No pointwise, thin-film, droplet or material-path claim.
- `F3-V1-REAUDIT.json`: four historical TV maxima exactly reproduced through original observe(). Plain 0.015/0.010 remains 0.05216051407639587 and FAIL. Original report untouched. Marginal TVs are lower bounds, not additive causal decompositions.
- Nominal CELL3 long: 836 frames to 8.350023746 s, 293 native position exclusions. First true penetration 3.300 s; max wall depth 0.025785 m against tolerance 0.0051 m; longest excess 89 frames. See its AUDIT and FORENSICS reports. This is not merely a chord event.
- Zero drive: gravity and hydrostatic initialization preserved; 836-frame integrity passed, no loss/crossings. `F3-ZERO-DRIFT.json` has all fixed-scale drift metrics below 0.01 (TV 0.0018769, local velocity/U 0.0030295). This does not qualify driven cases.
- Temporal control: 836 frames, 292 position exclusions, sustained wall excess. `F3-TIME-STEP-EVIDENCE.json` proves actual dt halved from 2.9954275e-5 to 1.49771375e-5 s. Full failed-source diagnostic comparison: max TV 0.0126323, mean velocity/U 0.0401895, energy 0.0238757, common-support velocity/U 0.0581726. Budget 0.01 fails; nearest-native timestamp mismatch is at most 1.497715e-5 s. Failed hard gates are not waived.
- `F3-NOSLIP-CLI-REPAIR.json`: first boundary contrast retained CLI `-mdbc`, overriding XML SlipMode=2. Verified owned PID 165620 was terminated; failed attempt and data retained and charged. It is not a physical boundary contrast. Corrected CLI is `-mdbc_noslip`; both attempts count.
- Two real material engineering configurations: 512 independent equal-volume seeds (16x8x4), 2/4 substeps on the 1.5 s canary. `F3-MATERIAL-ENGINEERING-COMPARISON.json` binds arrays/hashes, first passage, final left/right/unknown, residence by source, full failure denominator. Same-seed max path difference 1.15019e-5 m; first-passage and terminal classifications agree; unknown=0. These are temporal/interface results only, not qualified T2-macro/T2-path data.
- `scripts/f3_control.py` implements causal known forcing inputs. No new training or independent development case has been generated.

## Next executable actions

1. Inspect the 15 remaining NS1 nominal-plane crossings and endpoint trajectories. Register any focused diagnostic before launch. The runner blocks NS1 matrix expansion after a failed canary; F3-NS1-QUALIFICATION-PLAN.json is conditional, not approval or a passed result.
2. A successful new boundary candidate needs its own temporal/spatial/parameter qualification. It is not the old ladder. Domain expansion alone cannot repair original sustained penetration. No projections, discarded failures, padding, or threshold relaxation.
3. Complete output/interpolation control, reference ladder, endpoints and independent interior point before production. Registered 1.5 s prefix remains diagnostic; posthoc truncation cannot turn failed 8.35 s into a pass.
4. Then produce independent physical cases, source-bound material references (including cross-dp same-point paths), two real learned routes × three seeds, autonomous rollout and recovery/cost evidence. Engineering material outputs cannot substitute for a qualified source.

## Resources and verification

Owner approved CPU total 768 core-hours on 2026-09-10. Other caps unchanged: qualification 56, development 40, training 12, materials 32, GPU 64 h, storage 512 GiB, expiry no later than 2026-09-16 00:00 UTC. User prefers GPU for CFD/training. GPUs 0–3 protected; one CFD solver on UUID-checked GPU4–7. CPU supports conversion, finite-wall tracer geometry and scoring.

At checkpoint: 49 qualification attempts charged including the running NS1 temporal diagnostic, 7 remaining; two material configurations charged, none qualified. Refresh RESOURCE-LEDGER. Running guarded attempts reserve recorded timeout without inventing elapsed runtime; a record alone never proves liveness. CPU activity window stays open while verified work runs; close it once no campaign worker remains, avoiding idle-hour charges.

Tests cover observer/time contracts, finite walls, causal controls, input/CLI-mode guards and resource reservations. Manufactured and real-data evidence remain separate. Raw arrays stay outside Git; manifests/hashes/reports tracked. No formal release, hidden test or main merge.

Large new audit/diagnostic panels are retained byte-for-byte in local content-addressed archives. Tracked summaries contain full_report paths and SHA256; scalar findings and failure decisions are unchanged.
