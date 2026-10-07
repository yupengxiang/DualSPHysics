# fresh233 numeric tuple and native pin audit

This is a standalone, read-only metadata audit for the 96 current F1/F6
physical rows in the authoritative Root1451 delivery index. It certifies
pairwise uniqueness within each family from the requested numeric tuples only:

- F1: `(fluid_depth_m, initial_fluid_vx_m_s)`. Forty rows use the fresh090
  source-plan fields `grid.nominal_physical_fluid_depth_m` plus the declared
  initial-velocity field. The eight unchanged-mother rows use the exact
  JSON physical-binding document selected from the native request inputs.
- F6: `initial_angular_velocity_rad_s` as a three-component vector. Forty-seven
  rows use the exact canonical-owner JSON field
  `physical_binding.parameters.initial_angular_velocity_rad_s`. The baseline
  uses only the exact `angularvelini@x/y/z` values from
  `F6_ANGULAR_RELEASE_DP025.xml`, yielding `[0.08, 0.12, 0.06]`.

`case_ref`, path, hash value, geometry-tree shape, and yaw are excluded from
the uniqueness key. The baseline request's angular-vector field remains
absent and is recorded as absent; yaw is neither read nor compared.

For every row the validator reads the native `execution-receipt.json`, checks
completed/returncode 0 and exact equality of `input_hashes_at_launch` and
`input_hashes_after_run`, then hashes only the selected JSON/XML metadata
source. The selected source path and its current SHA256 must be present with
the same value in both receipt maps. No BI4/H5/CSV/DAT/VTK/XMF, PNG, solver,
job, shared-state, or scientific-payload operation is performed.

The generated report is the evidence snapshot: 96 rows (F1=48, F6=48), zero
numeric duplicate groups, and 96/96 native metadata pins. This is a numeric
uniqueness/provenance check only. It does not grant case credit, Q-N, Q-E,
precision, strict containment, or sub-DP certification. The known all-F6
small fluid-omission observation and its unknown causes remain outside this
tuple audit.

Configured profile: `gpt-5.6-luna/max`; no recursive delegation.

Read-only commands:

```sh
python3 validate_numeric_tuples.py --output numeric-tuple-pin-report.json
python3 validate_numeric_tuples.py --validate numeric-tuple-pin-report.json
```
