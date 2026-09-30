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

For any unrun medium/fine reference, submit its exact `gencase_*_request.json`
through the shared runtime first; never construct a solver prefix before the
completed GenCase artifact and receipt exist. Keep CPU threads <=4, max wall
<=300 s, and storage <=256 MiB, then bind actual population, 3-D output,
initial mass, finite-boundary/control coverage, and copied motion hashes before
registering a primary-process qualification request.

## Actual coarse native state evidence

The primary process has now completed the bound 4.0 s coarse qualification
runs. The family owner did not launch GPU work. The immutable full-frame
conversion and event sidecars are registered in
`native_state_evidence.json`; the two solver inputs use the completed GenCase
prefixes recorded in `native_state_ready_manifest.json`, including the actual
XML, BI4, and copied motion-control hashes.

The center and offset trajectories each contain 401 full-precision `RunPARTs`
frames, 35,184 particles, 1,764 initial Type=3 fluid particles, 28,734 fixed
boundary particles, and 4,686 Type=1 moving-boundary particles. The rigid-body
sidecar fits the saved moving nodes and selects native control sign -1 from
the copied control versus the observed pose; maximum center fit residuals are
0.003641 rad, 3.30e-8 m RMS position, and 0.00513 m/s RMS velocity. The offset
run retains 30 native excluded fluid identities as unknown mass.

The CPU event products are
`f2-native-observations.json`/`f2-native-labels.h5` under the center and offset
`labels-f2-*-native-v3` attempts. Center records 434 cup departures and 665
receiver entries with final masses cup 15.953125 kg, receiver 10.390625 kg,
inflight 1.21875 kg. Offset records 438 cup departures, 620 receiver entries,
61 tray entries and 30 unknown identities with final unknown mass 0.46875 kg.
The original converter-only audit remains open-boundary incomplete by design;
the explicit finite-initial-cohort sidecar below supplies the native exclusion
ledger and is the current Q-I reading. Q-N and production eligibility remain
unassessed.

`integration_step_requests.json` freezes an actual reduced internal-Dt request
for each coarse background at half the observed native minimum `DtMin`, and
keeps medium/fine requests bound to their exact definitions and motion files
until completed GenCase prefixes exist. The physical-case registry check is
48 unique physical cases; the six reference resolution views do not increase
that count.

## Superseding actual Q-I and reference evidence

The shared CPU runner completed `full-qi-audit-f2-center-coarse-v4` and
`full-qi-audit-f2-offset-coarse-v4` with PartVTKOut executed against the
immutable `PartOut_000.obi4`. The compact source-binding report is
`full_qi_audit_evidence.json`; each report and execution receipt remains at
the external data root named in that file. Both current audits are
`Q-I-structure-pass` with generic integrity also `Q-I-structure-pass`, 401
full frames, typed identity `(Zone,Idp)`, 3-D solver evidence, nonzero Type=3
fluid, and all 4,686 Type=1 moving nodes present at every frame. Actual
moving-node fits have maximum angle residual 0.003641 rad, position RMS
3.30e-8 m, and velocity RMS 0.00513 m/s; the copied motion hash and native
control sign -1 are bound in the report.

The center ledger has no native exclusions. The offset ledger has 30 initial
fluid identities, each bound to a first missing frame and finite PartVTKOut
position/density record; RunPARTs sums are `NpOut=30`, `NpOutPos=30`,
`NpOutRho=0`. The converter's 30 invalid `type=-1` rows are recorded as
invalid-state sentinels, while live identities have zero births, revivals, or
type changes. The offset numerical unknown is 30 identities / 0.46875 kg.
The physical event ledger remains separate: only 0.0625 kg of tray entries
follow a prior same-identity cup departure, while 0.890625 kg is unmatched
tray-event mass and is unresolved rather than relabelled as spill.

All six coarse/medium/fine reference GenCase products are now completed and
bound in `definitions/reference_matrix.json`; medium and fine have actual
3-D totals 54,738 / 98,291, fluid counts 3,672 / 8,096, fixed counts 43,986 /
78,105, moving counts 7,080 / 12,090, source-layer MK counts, positive mass,
and copied motion hash. They remain qualification-pending until the primary
process runs the registered requests. The half-native offset definition is a
separate CPU-preflight artifact with `DtFixed=4.8226823140586686e-05`, exactly
half the observed positive native `DtMin=9.645364628117337e-05`; no solver was
launched by this owner.

`qualification_ready_manifest.json` contains exact completed GenCase prefixes
and separate XML/BI4/copied-motion hashes for center medium/fine, offset
medium/fine, and offset half-native. Its physical condition hash excludes
dp, DtFixed, integrator and save cadence; its numerical recipe hash includes
those fields. The primary process must schedule these requests through the
shared runner and must not substitute an attempt-root placeholder.

`split_range_design.json` records the independent 48 physical conditions as
24 paired center/offset parents, the nested 8/24/48 parent sets, and the
24/6/6/6/6 train/validation/ID-test/parameter-OOD/geometry-control-OOD
counts. Resolution remains a view of the same physical case and cannot add
registry rows; the geometry/control holdout is a joint tuple claim, not a
marginal one-factor OOD claim.
