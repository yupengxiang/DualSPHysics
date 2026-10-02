# F6 handoff_20261002 commensurate mother

This is an additive F6 mother scope.  The consumed F6 parent, fallback-02,
repair-001, repair-002, and repair-002b files and receipts remain unchanged.
The solver has not been launched from this worktree.

The frozen continuous tank is `[0,0,0] + [4.8,2.4,2.4] m`, with finite bottom,
left, right, front, and back walls and an open top.  The frozen fluid box is
`[0.4,0.4,0.04] + [4.0,1.6,0.8] m`, so its denominator is 5.12 m3 and
5120 kg at 1000 kg/m3 for every DP.  The native floating box is
`[2.0,0.8,0.88] + [0.8,0.8,0.4] m`: volume 0.256 m3, aggregate `massbody`
128 kg, and analytic inertia diag `[8.5333333,8.5333333,13.6533333] kg m2.
Its lower face is 0.04 m above the continuous fluid top; the initial immersed
volume is zero.  The wave mechanism has an actual mk=10 moving piston and
native floatingtype=2 mk=50; the simple mechanism has no moving piston.

The earlier evidence was retained as a failure boundary.  The original
`dp|real|bound` coarse case produced 10,710 fluid particles instead of 10,000;
repair-001 `dp|bound` produced the same count.  Repair-002 reached the coarse
count but produced 39,184/77,220 at medium/fine and wave coarse lost the
paddle-overlap layer.  Repair-002b cleared the body/paddle overlap but retained
the measured medium/fine endpoint deficit.  These are not Q-N evidence.

The commensurate mother uses the measured GenCase lattice span only as a
numerical population rule: coarse keeps the passing `L-2dp+epsilon` span, and
medium/fine use `L-dp+epsilon` in x/y.  The physical faces, density, body
mass/inertia, liquid level, and finite walls are unchanged.  Shared v2 CPU
receipts show all six cases completed in 3D with these fluid counts:
The exact additive rule and preserved-manifest boundary are in
`geometry_sampling_addendum_001.json`.

| mechanism | coarse `.08` | medium `.05` | fine `.04` |
| --- | ---: | ---: | ---: |
| simple free response | 10,000 | 40,960 | 80,000 |
| wave no contact | 10,000 | 40,960 | 80,000 |

`partvtk_002/strict_partvtk_audit.json` is the Q-I initial typed audit.  It
uses the official PartVTK type/position CSV and its mass stats sidecar: every
case is 3D, has positive type-3 fluid, positive type-2 floating particles,
finite positions, declared finite walls, and strict fluid mass within 0.001%
of 5120 kg.  Wave cases contain 1,276/4,794/9,912 moving particles at
coarse/medium/fine.  `partvtk_002/rigid_state_preflight.json` additionally
computes nonzero type-2 point-cloud inertia.  At medium, for example, the
MassBound particle sum is 325.125 kg and point-cloud inertia is approximately
diag `[24.9263,24.9263,39.0150] kg m2`; this diagnostic sum is kept separate
from the native 128 kg aggregate and analytic inertia.  The additive
`native_semantics_addendum_001.json` records the corrected 0.04 m body/fluid
gap while preserving the earlier Native JSON bytes.

Root-only qualification requests are in
`partvtk_002/qualification_requests/` and indexed by
`partvtk_002/qualification_request_manifest.json`.  The two medium requests
are:

- `F6_HANDOFF_20261002_SIMPLE_FREE_RESPONSE_COMMENSURATE_MEDIUM.json`;
- `F6_HANDOFF_20261002_WAVE_NO_CONTACT_COMMENSURATE_MEDIUM.json`.

Both use the completed GenCase output directory as `cwd`, an actual generated
prefix, `-tmax:12 -tout:0.05`, and `-tout:0.05`.  Their estimates are 59,737
particles/129 GPU seconds and 64,531 particles/133 GPU seconds respectively.
The request input lists contain the actual GenCase XML/BI4/All/Fluid files,
PartVTK-002 receipt/CSV, control/native/normal files, official binaries, and
the source/audit sidecars.  They are `root_dispatch_pending`; no Q-N or
production claim is made.  FloatingInfo and ComputeForces remain required
shared CPU postprocessing for pose, orientation, linear/angular velocity,
mass, inertia, force, and torque.

The v2 runtime source is bound in every receipt by SHA-256
`5098262e26dc5560487760181466b0a93a0e66239e5e54047dce5e761ae67a60`.
The receipts are authoritative for the changing shared-runner worktree: the
GenCase launches record runner commit
`d905b8e3cf824d95ff93933df2ba2aebfa7e57a6`, and the PartVTK launches record
`196004797c4f51834cf14b42e0642e9f42b68a24` or
`ba2628b11f799f865d62e70c979c7acbdeb40189`, with no input-hash changes after
each run.
