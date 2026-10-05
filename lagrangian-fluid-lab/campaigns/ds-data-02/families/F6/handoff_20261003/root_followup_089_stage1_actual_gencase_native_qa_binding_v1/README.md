# F6 fresh089: Root539 actual GenCase to pose-aware native QA

This is an F6 source-only handoff for the 24 mechanical-pose/omega cases from
fresh088. Root539 has completed all 24 genuine GenCase requests with
returncode 0. The package binds the producer `prepared-input-report.json`,
generated XML, receipt, source definition, canonical owner, and producer
attested BI4 digest. It does not open or hash BI4/H5/CSV/DAT/IBI4/trajectory
payloads.

`qa/initial-native-qa-binding.json` and
`qa/requests/root539-mechanical-pose-initial-native-qa-089.json` are disabled
until Root runs the strict CPU PartVTK worker. The worker keeps the existing
finite, positive-weight/density, UID, `(Zone,Idp)`, type/Mk, count, true-3D,
zero-fluid-velocity, mass, centroid, clearance, and uniqueness checks. Its
geometry envelope is derived from the source 0.8 x 0.8 x 0.4 m body and each
case's declared XML `rotateaxis`; it therefore does not apply the old
unrotated axis-aligned box to yawed particles.

The native requests in `qualification/requests/` are all disabled and use the
Root230 Home-floor native dispatch entry with a live UUID lease selected at
enable time. They retain the reviewed mother recipe `tmax=12`, `tout=0.05`,
241 frames, and no forcing/MDBC/solver-option mutation. Root146 is retained
only as historical provenance in the source evidence and is not a future
execution entry. Future solver receipts, frames, state0 observations, and
typed outputs are null.

`floatinginfo/state0-binding.json` and `floatinginfo/state0-request.json` are
also disabled until every native request is terminal completed/0. Each state0
audit derives its expected omega from that case's own XML and canonical owner;
particle V0=0 is deliberately not used as evidence of zero angular velocity.
Physical mass 128 kg, native support mass 256 kg, and masspart 0.015625 kg
remain separate with no normalization. QA019 and semantic020 historical
evidence remains hash-bound and untouched; this package grants no visual,
Q-N, precision, or production status.

The Root539 metadata validator and the source-only builder are in `workers/`.
They are intended for metadata review and disabled request regeneration only;
they do not dispatch a solver.
