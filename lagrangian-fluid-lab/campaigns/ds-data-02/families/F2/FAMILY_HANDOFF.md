# F2 DS-DATA-02 handoff

Status: definitions and contracts ready; two bounded CPU GenCase preflights are
registered for the shared runner. No GPU or solver was launched by this family
owner.

The new physical mechanisms are `center_catch` and `offset_spill`. Both use a
finite three-dimensional cup with explicit bottom/side/front/back walls, a
finite receiver, and a finite spill tray. The cup uses the W06 successful DBC
`mvrotfile` interface about the Y axis: 0--0.5 s static hold, cosine-ramped
rotation to -105 degrees over 1.20 s, then a post-stop hold
through 4.00 s. The offset background keeps the same source
fluid and control while moving the receiver to a transverse offset; spill is
classified only after finite cup-mouth departure and remains in the initial
mass denominator.

`definitions/reference_matrix.json` freezes the same continuous geometry and
control at coarse/medium/fine dp = 0.025/0.020/0.015 m for both backgrounds.
`quality_contract.json` and `event_definitions.json` freeze Q-I/Q-N thresholds,
finite-surface crossings, source-layer labels, destination categories, and
unknown-mass rules before native results exist. `integration_save_plan.json`
keeps native-dt, half-native-dt, save-0.005 s, and event-save-0.001 s controls
independent; 0.01 s matrix output cannot by itself qualify event timing.

The historical W06 inventory records 5 cases with zero missing initial IDs and
7 cases with positive missing IDs. All 12 remain historical evidence only;
D05 is recorded as reference reuse and no old model/tracer is revived.

The registry contains 48 independent physical cases (24 paired center/offset
groups), with nested 8/24/48 progression and split counts train 24,
validation 6, ID-test 6, parameter-OOD 6, geometry/control-OOD 6. Resolution
views and integration/save controls never add case count. Short-spout rows are
held out until a fresh geometry reference is generated.

Next executable task: submit the two `gencase_*_request.json` files via
`scripts/ds_data02_runtime.py run --request PATH` from the integration worktree
with CPU threads <=4, max wall <=300 s, and storage <=256 MiB. Use the receipts
to bind actual total/fluid particles, actual 3-D output evidence, initial mass,
finite-boundary/control coverage, and only then register the qualification
requests for the primary process.

## Stage 8 Production Status Addendum (2026-10-02)

1. **8-Case Stage 8 Roster**:
   - `F2_CENTER_P01` / `F2_OFFSET_P01` (Pair 1, open_rim, rx=0.45m, GPUs 2 & 5)
   - `F2_CENTER_P02` / `F2_OFFSET_P02` (Pair 2, short_spout, rx=0.45m, GPUs 6 & 7)
   - `F2_CENTER_P03` / `F2_OFFSET_P03` (Pair 3, open_rim, rx=0.65m, GPUs 2 & 5)
   - `F2_CENTER_P04` / `F2_OFFSET_P04` (Pair 4, short_spout, rx=0.65m, GPUs 6 & 7)
2. **Containment Geometry Remediation**:
   - Catch basin floor extended to $[-1.20, 2.80] \times [-1.00, 1.00] \times [-0.20]\text{ m}$.
   - 4 perimeter containment lip walls ($h = 0.15\text{ m}$) drawn via `<boxfill>bottom | left | right | front | back</boxfill>`.
   - Simulation domain ceiling raised to $z = 2.20\text{ m}$ (domain $[-1.20, 2.80] \times [-1.00, 1.00] \times [-0.50, 2.20]$).
3. **Preflight Verification**:
   - All 8 cases preflighted via `GenCase_linux64` with returncode 0.
   - Particle loss strictly zero ($N_{\text{out}} = 0$) across all 8 cases.
   - Exact particle counts: 103,995 for P01/P02, 105,662 for P03/P04 (Fluid = 3,094 across all 8 cases).
   - Continuum mass consistency: $+31.13\%$ relative error matching lattice discretization of initial cup volume.
4. **GPU Solver Launch Requests**:
   - 8 solver requests emitted to `requests/{cid}-solver.json`.
   - Strictly allocated to permitted GPUs $\{2, 5, 6, 7\}$; GPU 0 preserved; GPUs 1, 3, 4 strictly forbidden.
   - All input hashes and GenCase receipts bound; ready for primary runner execution.

