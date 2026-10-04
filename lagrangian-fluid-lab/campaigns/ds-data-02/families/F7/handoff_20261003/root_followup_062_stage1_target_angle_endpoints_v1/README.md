# F7 narrow target-angle endpoints — source-only handoff

This scope carries exactly the two endpoint rows from the first eight-row F7
single-axis plan:

- `F7_OBSTACLE_QUINTIC_B08_A030`, target paddle amplitude `30.0°`;
- `F7_OBSTACLE_QUINTIC_B08_A065`, target paddle amplitude `65.0°`.

Both endpoints keep the coarse source recipe at `dp=0.02 m`, `TimeMax=12 s`,
`TimeOut=0.02 s`, and the full 601-frame native window. The explicit-wet fill,
tank and paddle geometry, type-1 moving body, exact pivot
`[-0.04, 0, 0.05]` to `[-0.04, 0, 1.05]`, controls, and native release policy
are fixed. The source wet-fluid mass `325.60001628000003 kg` remains distinct
from the `320.1984 kg` continuum envelope; no mass rescale is allowed.

The 053 handoff referenced the generated all-numeric XML as its source anchor.
For a genuine fresh GenCase request this successor binds the actual source
Definition (`..._Def.xml`, hash `f45a212f...`) and keeps the generated XML as a
read-only historical anchor. The two static `source/*_Def.xml` files are byte
identical clones of that Definition. The only prospective physical variation
is the target-angle amplitude in the endpoint-specific motion file. No
geometry or numerical recipe byte is edited.

Three disabled Root-strict requests are included:

1. `f7_target_angle_motion_preparation_request.json` runs the bound motion
   builder for amplitudes 30° and 65°. If Root later launches it, it writes a
   `.001 s` two-column motion file and a Definition whose declared motion
   subtree points to that file. The builder verifies an independent
   motion-only undo and records source hashes.
2. `f7_target_angle_gencase_request.json` consumes the preceding preparation
   attempt and runs official GenCase once per endpoint. It records the actual
   `<endpoint>/<endpoint>.xml`, `.bi4`, and execution-receipt paths. This is a
   genuine fresh GenCase request, not a copied generated artifact.
3. `f7_target_angle_initial_qa_request.json` consumes those exact generated
   prefixes through the existing Root initial-native QA worker. Its checks
   cover complete UIDs, fixed/moving/fluid native types `0/1/3`, positive
   native masses, full 3-D fluid coordinates, and source/receipt lineage.

The requests remain `launch=false` and `launch_allowed=false`; their upstream
attempt paths are explicit because the strict runtime substitutes
`{attempt_root}` only for the current request. Root must run motion preparation,
then GenCase, then initial QA after review. This source handoff created no
motion table, GenCase XML/BI4, H5, arrays, CSV, solver output, or render.

The analytic quintic target is described as C2, while the native sampled
motion is read piecewise linearly and is therefore not C2. That negative
regularity finding, the historical 43.011% KE discrepancy, paired transport
and numerical unknowns, ungranted `q_n`, and pending whole-window visual
decision remain active. No precision, containment, visual, or numerical
acceptance claim is made here, and the endpoint pair adds no independent-case
credit.
