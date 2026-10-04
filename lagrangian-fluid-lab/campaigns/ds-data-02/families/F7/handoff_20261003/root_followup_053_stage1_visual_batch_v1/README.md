# F7 stage1 visual batch 8 source handoff

This handoff defines eight independent F7 physical control tuples for later root
controlled generation and visual review. The request is disabled and source-only.
Its bounded motion builder emits JSON motion specifications; it does not write a
sampled motion table, BI4, H5, particle arrays, CSV, solver output, or a render.

The source anchor is the completed coarse-labeled explicit-wet obstacle case
`F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_COARSE`: 601 native frames over `[0, 12] s`,
two finite symmetric analytic quintic cycles active on `0..8 s`, and rest/residual
motion on `8..12 s`. The native moving body remains type 1, with the exact source
pivot `[-0.04, 0, 0.05]` to `[-0.04, 0, 1.05]` and the explicit-wet fill.

The analytic target is C2, but the native sampled motion is read by the solver as
piecewise linear and is therefore not mathematically C2. That negative regularity
finding is retained for every proposed amplitude. The source wet-fluid mass is
325.6 kg while the continuum envelope is 320.1984 kg; native weights remain the
authority and no rescaling is permitted.

All eight rows vary one amplitude dimension only. The 45 degree source mother is an
interior row; 30 and 65 degrees are the proposed bounded endpoints and require root
fresh GenCase, initial QA, motion-source review, and whole-window dynamic checks.
No extrapolated numerical or visual claim is made by this source plan.
