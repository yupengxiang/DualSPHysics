# M1 observation and acceptance contract

This contract is frozen before any F1/F5 comparison. A solver exit code is an
execution result; it is not an observation acceptance result. Each product
must retain the native time values, source hashes, probe definition, and
interpolation brackets used for comparison.

## F1: official mDBC DamBreak3D

**Target and source.** Use the official v5.4
`examples/mdbc/04_Dambreak/CaseDamBreak3D_Def.xml` and the matching official
GPU script. The run is 3D, `Dp=0.01 m`, `TimeMax=6 s`, and `TimeOut=0.01 s`.
The exact target XML hash in this worktree is
`1f7cca807e16a3b1a1cc4da649a68db5166439d3f4b30fa4ea25635baf6045b7`.
The old 601-frame candidate is documented in
`f1/reuse-audit.md`; it is diagnostic only because its physical case is an
asymmetric dual-channel case.

**Primary observations.** Extract water-surface elevation histories at the
four official H probes, H1 `(0.496,0.5,0)`, H2 `(0.992,0.5,0)`, H3
`(1.488,0.5,0)`, and H4 `(2.638,0.5,0)`, in metres relative to the official
`z=0` reference. Use the `MeasureTool` output and preserve its actual time
column. The eight points in `f1/input/pressure.txt` are auxiliary pressure
impact observations in Pa; they are not substituted for surface elevation.

**Reference and comparison.** The numerical reference is the mapped SPHERIC
Test 02 observation set specified by the campaign plan. Before comparison,
record its source URL/file hash, units, coordinate convention, sensor labels,
time origin, and digitisation uncertainty. No F1 numerical pass may be issued
until that mapping record exists. Match common timestamps by interpolation
only inside the two reference brackets; do not phase-shift, extrapolate, or
retime either series.

**Frozen metrics and provisional gates.** Report, per elevation probe,
RMSE, MAE, maximum absolute error, signed mean bias, peak elevation, and
peak/arrival time error. The provisional operational gate is elevation RMSE
`<= max(0.010 m, 0.10*H_ref)` and peak/arrival time error `<=0.020 s`
(two native output intervals). For pressure, report peak and integrated
impact-window error, with event timing `<=0.020 s` and relative peak error
`<=15%` when the reference pressure uncertainty is available. If the mapped
SPHERIC source gives a stricter uncertainty-based limit, record it before
comparison and use that limit. Missing reference uncertainty leaves the result
as diagnostic rather than accepted.

**Coverage checks.** Require monotonic real times covering `0..6 s`, all four
elevation probes, all eight pressure probes, finite SI-valued observations,
and an explicit record of any wet/dry or probe-missing samples. A fresh
official result can satisfy this data contract; the old DUAL result cannot
satisfy the physical identity gate.

## F5: CasePistonBeach_REG calibration

**Target and source.** Use the unchanged official v5.4
`examples/main/09_WavesPiston/CasePistonBeach_REG_Def.xml`. This is a 2D
calibration case and is recorded as `reference_role=calibration_2d` with
`upstream_case_id=CasePistonBeach_REG`; it does not count as an M4 3D result.
The prepared XML hash is
`79543b3f37e8bd18b2d6fd9ad27e76e080b82950f2de125f4f1e82dc4764210c`.
The official control is `Dp=0.02 m`, `H=0.15 m`, `T=2 s`, depth `0.66 m`,
`TimeMax=30 s`, and output interval `0.05 s`, with the official beach,
piston motion, and `savemotion periods=20 periodsteps=20 xpos=6 zpos=-0.26`.
Do not alter the full official domain or control settings.

**Reference data and observables.** The immutable official ODS
`CasePiston_SPHvsTheory.ods` has the `REGULAR_BEACH` sheet, a second-order
Stokes theory table with `time:40`, `dt:0.1`, `xpos:6`, `zpos:-0.26`, plus
SPH columns at x=5, 6, and 7 m and velocity at x=6 m, z=0.4 m. Its hash is
`7c40adc731643e90b503bda01e349bd2f988b17c80343ca4db48b49250d65218`.
Use `ETA_SPH(x=6m)` against `ETA_2ndStokes(x=6m)` as the primary surface
comparison. `ETA_SPH` is the elevation relative to still water; do not use
the `Height_SPH` column as eta. Report x=5 and x=7 surface histories as
auxiliary propagation checks. Compare `VelX_SPH` and `VelZ_SPH` at
`(x,y,z)=(6,0,0.4) m` against the corresponding second-order Stokes theory
columns in m/s.

**Frozen time policy.** The solver covers `0..30 s`, while the official ODS
table extends to `40 s`. Use only the common interval `[0,30] s`. Preserve
actual MeasureTool times (expected output spacing is approximately `0.05 s`)
and interpolate the ODS table only inside brackets at those times; never
extrapolate or shift phase. Because the piston has a one-period ramp
(`ramp=1`, `T=2 s`), report startup `[0,2) s` separately and apply the
primary acceptance gate only on `[2,30] s`.

**Frozen metrics and provisional gates.** For x=6 surface eta and each
velocity component, report RMSE, MAE, signed bias, amplitude/peak bias, and
zero-crossing or peak timing error. The provisional calibration gate is
surface RMSE `<= max(0.005 m, 0.10*H)` (therefore 0.015 m for this case),
surface timing error `<=0.10*T` (0.20 s), and velocity RMSE
`<= max(0.05 m/s, 0.10*max(|u_ref|))` with the same 0.20 s timing limit.
Report startup metrics separately even when they fail the primary gate. These
limits are frozen for this comparison and may not be tuned from the resulting
curves; a later campaign revision must carry a new contract.

**Acceptance status.** This F5 ODS is an official analytical comparison
reference, not an independent laboratory observation. Label the outcome
`calibration_2d`, retain the ODS and point-file hashes, and do not promote it
to a 3D qualification or production acceptance.

## Required postprocessing sequence

After the shared runner records a successful solver receipt, execute
`f5/scripts/extract_reference_observations.sh` with the solver attempt's NAS
root and a new NAS postprocess root. The script follows the official
postprocessing filters: PartVTK fluid and moving piston products,
PartVTKOut fluid products, MeasureTool elevation and velocity CSV/VTK, and an
IsoSurface slice for visual QA. The comparison inputs are only the two
MeasureTool CSV products; VTK and slices remain auxiliary evidence. A
postprocess manifest records paths, source points, and the frozen `[0,2)` /
`[2,30]` time windows.
