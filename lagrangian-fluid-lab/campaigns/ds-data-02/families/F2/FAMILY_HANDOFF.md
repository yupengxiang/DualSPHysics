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
