# R3 F6 E0/E1 execution policy

This file records the bounded next gate requested by the external review.  It
is an execution policy and does not, by itself, admit a case to the benchmark.

## Scope

The only physical closure being pursued in this gate is a fixed, submerged
Float1 body in a static water column:

1. **E0 geometry gate:** inspect the generated boundary and ghost geometry for
   the canonical mDBC construction and the explicitly named inward-offset
   candidates.  The audit must report boundary/ghost positions, the effective
   interface `x_gamma=(x_b+x_g)/2`, normal direction and magnitude, zero-normal
   locations, component and corner coverage, wetting coverage, and displaced
   volume.  A zero count of serialized normals is necessary but not sufficient.
2. **E1 hydrostatic gate:** only an E0-passing mDBC geometry may enter the
   fixed-body force matrix.  Run nominal, deeper, and shallower submerged
   heights with DBC as a control and mDBC as the candidate.  A finer-resolution
   mDBC repeat is allowed only for geometries that pass E0.  The total budget is
   six main runs plus at most three fine repeats.

The body is fixed during E1.  Chrono integration is a separate follow-up and
must not be mixed into the hydrostatic comparison.  DBC is a control, not a
requirement for mDBC acceptance; conversely, an mDBC improvement over DBC is
not sufficient for physical acceptance.

## Evidence and status rules

Every run has an immutable attempt record, solver and conversion logs, and a
machine-readable result.  The authoritative status is the tuple
`execution_status`, `acceptance_status`, `validation_scope`, and
`open_blockers`; the historical `status=complete` field is not an acceptance
claim.  Missing evidence is `unknown`, never zero.

The initial hydrostatic screens are:

- no unexplained zero normals or wall/ghost geometry failures;
- late-window mean vertical force within 5% of `rho*g*V_sub`;
- medium/fine force difference no greater than 3% when a fine repeat exists;
- symmetric horizontal force no greater than 1% of `m*g`;
- no numerical mass loss, wall penetration, or required-field omission;
- report more than one late-time window and the actual displaced volume.

Away from the nominal equilibrium height, the expected buoyant force is
`rho*g*V_sub`; the body need not satisfy `F_z=m*g`.  These screens are
necessary evidence for a candidate physical reference, not an automatic claim
of formal v0.1 readiness.

## Deliberate non-goals

This gate does not expand the six mechanism families, execute the 204 W08
continuous cards, or repeat the small G4 route reruns.  Open-boundary and
variable-resolution material lineage remain extension tracks.  Dynamic tracer
visibility and model-input boundary geometry are audited separately with
synthetic CPU diagnostics so that their contracts cannot be conflated with the
F6 hydrostatic result.

