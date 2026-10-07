# fresh234 F1 field provenance supplement

Fresh234 is an additive F1-only correction to fresh233. Fresh233 remains
immutable and its F6 result is not rebuilt. This package independently checks
all 48 F1 rows using only the numeric pair
`(fluid_depth_m, initial_fluid_vx_m_s)` for uniqueness.

The report records separate provenance for both values. Each field has its
own absolute JSON path, JSON pointer, numeric value, current metadata SHA256,
and an exact launch/after-run receipt-map match. The native receipt must also
be `completed` with return code 0 and have identical launch/after-run maps.

Depth resolution is explicit:

- source090 and other plans with the field use
  `/grid/nominal_physical_fluid_depth_m`;
- VX010/VX020 plans whose grid depth is absent use the own canonical-owner
  `/physical_binding/parameters/fluid_depth_m`;
- the two mother fallback bindings use
  `/physical_binding/geometry/fluid_reservoir_size_m/2`;
- the remaining owner/binding JSON uses its exact
  `/physical_binding/parameters/fluid_depth_m` field.

Initial `v_x` is read from the own source plan's
`/initial_velocity_declaration_m_per_s/0` or `/axis/velocity_m_per_s/0` when
present. Mother and fallback bindings use their exact
`/physical_binding/initial_state/velocities_m_per_s/fluid/0` or
`/physical_binding/initialization/velocity_m_s/0` field. Thus a VX010 plan
with no grid nominal depth reports depth from its pinned owner JSON and
velocity from its pinned source plan; it never labels the plan as the depth
source.

The uniqueness key ignores case IDs, paths, hashes, geometry-tree shape, and
yaw. Those values are retained only as field-level provenance evidence. The
result is 48 rows, zero duplicate numeric pairs, 48 native pins, and 96 field
pins. This is a provenance/uniqueness audit only: no case credit, Q-N, Q-E,
precision, strict-containment, or sub-DP claim is made.

Only JSON metadata and their bytes are read. No BI4/H5/CSV/DAT/VTK/XMF/PNG,
scientific payload, job, solver, or shared-state operation is performed.
Configured profile: `gpt-5.6-luna/max`; no recursive delegation.

```sh
python3 validate_f1_field_provenance.py --output f1-field-provenance-report.json
python3 validate_f1_field_provenance.py --validate f1-field-provenance-report.json
```
