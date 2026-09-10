# F3 continuation checkpoint — 2026-09-11 Asia/Shanghai

Full goal remains active: qualified reproducible F3 recipe, independent development cases, and material/learning closure. No production resolution or control interval is qualified. This is progress, not DONE or an external blocker.

## Live third temporal level — revalidate before continuing

`F3_CELL3_LONG_dp0p01_a1p000_noslip_visco1_time_quarter` is running on GPU4, verified PID 195461, attempt `20260910T164658.770292Z-98cdb4e4`, tool session 26452. Poll this handle; no duplicate launch. Native initialization confirms No-slip, ViscoBoundFactor=1, No Penetration=False, CFL=.0125 and DtMin=7.488568751149017e-6. Expected solver duration about 22 minutes; timeout 1800 s and UUID/memory guards remain active. CPU activity window stays open while this worker runs.

F3-NS1-QUARTER-TIME-DIAGNOSTIC-DESIGN.json binds the completed half-step audit (original full bytes and compacted summary hashes retained before launch). It registers one third-level temporal diagnostic, not matrix expansion. Generated XML comparison confirms only CFL and CoefDtMin changed from the half-step source. Ten gate/input tests passed after this change.

## Newly completed half-step evidence

Session 26723 is terminal. NS1 half-step finished code0 in 669.870 s and passed normalization, but full 836-frame audit is quality_failed solely for 5 nominal-plane crossings. No exclusions, missing IDs, wall tolerance exceedance or runtime-domain exit. First crossing 5.418987 s; max depth .000922959 m; longest 10 frames. Nominal NS1 had 15 crossings, max .00306335m and longest19 frames. Remaining excursions are real saved positions, not drawing artifacts.

Native CSV evidence proves dt halved from 2.9954275e-5 to 1.49771375e-5 s; interval step counts sum 278741 -> 557479. Full-window failed-source v2 diagnostic maxima: TV .000747482, COM/L .000193384, q90/L .001292, mean velocity/U .000656703, energy .000466935, local velocity/U .00133880, unmatched support mass 3.76344e-9. Timestamp mismatch <=1.497715e-5s. These observable differences are below .01, but do not waive the failed wall gate. Full rows preserved through full_report archive pointers.

Strong time sensitivity motivated the third temporal level before the optional four-layer experiment. Four-layer solver has NOT launched.

## Prepared next diagnostic option (not launched)

`scripts/f3_boundary_support_preflight.py` generated a four-layer candidate and checked native input. F3-BOUNDARY4-DESIGN.json and F3-BOUNDARY4-INPUT-PREFLIGHT.json bind the evidence. h/dp=1.59215, so the native documented 2h <= layers*dp condition needs at least four layers. Original 42,480 boundary points are retained; 15,968 external boundary points added, giving 58,448. All 14,580 fluid positions are exactly unchanged. Physical normal-generating wall surfaces, open top and dynamics parameters are unchanged. This is not a solver launch and does not qualify a recipe.

GenCase overwrote the pre-copied acceleration file with an empty template; caught before any solver. The script now restores the official drive after GenCase. The repaired candidate passes the native acceleration reader with 167,001 rows covering 0–8.35 s and the original SHA256. The defect and repair are retained in the preflight report. The native DDT warning checks h/dp but does not inspect layer count, so warning disappearance is not proof of correctness.

Wait for the active third temporal level before choosing whether to launch this candidate. It needs a new immutable prepared record, resource checks, original hard audit and its own qualification if selected.

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

1. Poll the existing third temporal-level runner through normalization and audit, then run f3_timestep_evidence, f3_crossing_details and f3_failure_forensics on the completed case. Compare full-window observables with the half-step source. Keep hard failures distinct from small macro errors. NS1 matrix expansion stays blocked until a successful source and explicit qualification design.
2. A successful new boundary candidate needs its own temporal/spatial/parameter qualification. It is not the old ladder. Domain expansion alone cannot repair original sustained penetration. No projections, discarded failures, padding, or threshold relaxation.
3. Complete output/interpolation control, reference ladder, endpoints and independent interior point before production. Registered 1.5 s prefix remains diagnostic; posthoc truncation cannot turn failed 8.35 s into a pass.
4. Then produce independent physical cases, source-bound material references (including cross-dp same-point paths), two real learned routes × three seeds, autonomous rollout and recovery/cost evidence. Engineering material outputs cannot substitute for a qualified source.

## Resources and verification

Owner approved CPU total 768 core-hours on 2026-09-10. Other caps unchanged: qualification 56, development 40, training 12, materials 32, GPU 64 h, storage 512 GiB, expiry no later than 2026-09-16 00:00 UTC. User prefers GPU for CFD/training. GPUs 0–3 protected; one CFD solver on UUID-checked GPU4–7. CPU supports conversion, finite-wall tracer geometry and scoring.

At checkpoint: 50 qualification attempts charged including the running third temporal level, 6 remaining; two material configurations charged, none qualified. Refresh RESOURCE-LEDGER. Running guarded attempts reserve recorded timeout without inventing elapsed runtime; a record alone never proves liveness. CPU activity window stays open while verified work runs; close it once no campaign worker remains, avoiding idle-hour charges.

Tests cover observer/time contracts, finite walls, causal controls, input/CLI-mode guards and resource reservations. Manufactured and real-data evidence remain separate. Raw arrays stay outside Git; manifests/hashes/reports tracked. No formal release, hidden test or main merge.

Large new audit/diagnostic panels are retained byte-for-byte in local content-addressed archives. Tracked summaries contain full_report paths and SHA256; scalar findings and failure decisions are unchanged.

## Additional verified work

Local checkpoint commit: 9e73cfe. Twenty-four observer/control/input/resource/finite-wall tests passed. Seven full-report archive hashes and all retained scalar summary values matched originals.

Material manufactured checks are in tests/test_f3_material_manufactured.py and F3-MATERIAL-MANUFACTURED-CHECK.json: actual advect_hdf5 reproduces independent constant-translation seed paths and analytic residence to 1e-12; NaN unknown positions now retain full unknown duration instead of contaminating labels. Both tests passed; existing two engineering arrays/hashes are untouched and residence outputs exactly unchanged. Nonuniform fields, support-loss/finite-wall held-out paths and qualified cross-dp CFD references remain required.

scripts/f3_crossing_details.py exactly reproduced all 15 prior crossing identities, intervals, times and endpoint depths. scripts/f3_timestep_evidence.py reproduces the original measured step statistics from completed native CSVs (Steps is per PART and must be summed; comments at CSV end are excluded).

Four-layer candidate PREPARED record now exists. scripts/f3_boundary4_campaign.py prepare revalidates asset/design hashes and input; run requires a completed failed latest NS1 temporal audit (including the third level once prepared) before the shared guarded GPU runner. No four-layer solver launched yet.

Qualification cap extension request is pending: F3-QUALIFICATION-BUDGET-FORECAST.json proposes 56 -> 64, eight additional attempts, with all other limits unchanged. At proposal time count was 49; current count is 50 with six remaining under the still-enforced cap 56. User has NOT yet approved this proposal. Conditional minimal total is 63 if one more boundary canary succeeds; the plan is not a promise of success or authorization to exceed current limits.
