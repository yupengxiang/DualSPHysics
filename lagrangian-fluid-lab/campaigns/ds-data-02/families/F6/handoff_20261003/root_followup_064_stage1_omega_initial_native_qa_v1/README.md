# F6 fresh064 initial-native QA

This handoff is the F6 source package for a fresh initial-native integrity
audit of the two genuine GenCase 073 angular endpoints:

- `F6_STAGE1_ANGULAR_RELEASE_OMEGA_S025_DP025`, with
  `angularvelini=[0.02, 0.03, 0.015] rad/s`;
- `F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025`, with
  `angularvelini=[0.16, 0.24, 0.12] rad/s`.

The exact generated XML and BI4 files, their completed 073 execution receipts,
the endpoint owners, and the source-only 063 plan are hash-bound in
`qa-binding.json`. The 073 evidence is consumed as an immutable input. This
package does not regenerate GenCase outputs and does not read BI4, H5, or
particle arrays itself.

The disabled request gives Root strict CPU a concrete worker entry point. When
Root enables that request, the worker invokes the official PartVTK helper on
each exact XML/BI4 pair and writes a new per-endpoint CSV and JSON audit under
the fresh `{attempt_root}` output root. The worker never invokes a solver,
converter, renderer, GenCase, or FloatingInfo reader. Its output directory must
be new; it never writes into the 073 attempt.

The native contract is explicit:

- total/fixed/moving/floating/fluid counts are
  `417505/73441/0/16384/327680`;
- all native UID, type, marker, position, velocity, weight, and density
  values must parse as finite values, with complete unique UID range and
  positive weights/densities;
- generated XML must declare true 3D (`data2d=false`), center
  `[2.4,1.2,1.08] m`, physical body mass `128 kg`, and `masspart
  0.015625 kg`;
- the type-2 native support sum is checked as `256 kg` and remains separate
  from the declared physical mass and `masspart`; no normalization is applied;
- the initial fluid velocities and serialized GenCase body particle velocities
  are checked as finite and zero, while the floating support geometry is
  checked for unique coordinates and gross-overlap exclusion.

The serialized GenCase particle `V0=0` check is deliberately scoped to that
serialization. It does not prove that angular velocity is absent. Full native
`FloatingInfo` state-0 inspection remains a separate Root follow-up required
to observe angular propagation for each endpoint. The historical QA019 failure
and semantic020 report are hash-bound and retained without rejudgment.

This package carries `launch=false`, `launch_allowed=false`,
`q_n_status=not_assessed`, `precision_status=not_accepted`, and
`production_approval=none`. It creates no numerical acceptance or production
claim and increments the independent case count by zero.
