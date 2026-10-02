# F2 CENTER baseline terminal-bound product

This handoff binds the completed CENTER baseline conversion at

`/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_DP005_CENTER_V1_BASELINE_SAVE001/conversion-f2_rv4eq_dp005_center_v1_baseline_save001-fullstate-root-reviewed-004`.

The terminal receipt is code 0 and the conversion report records 401 frames,
1,668,869 particles, a 3D solver, and a 0 to 4.000012141361291 s increasing
time axis.  The H5 contains full position/velocity/type/valid/mass/density/
pressure state and fixed `(particle_zone, particle_id)` identity arrays.  It
does not contain a derived rigid-body dataset.  The labels request therefore
fits `rigid_body_state` from the actual saved Type=1 moving nodes and checks it
against the copied motion control and `PartMotionRef.ibi4`.

The existing typed identity correction is bound as an independent sidecar.  It
retains all 2,123 native exclusions as numerical unknowns with corrected fluid
mk totals `{1: 929, 2: 296, 3: 898}`.  The sidecar preserves the native Motive and
domain evidence, and does not infer physical spill or wall penetration.

The XML `MassFluid` text and the converter's native header/float32 adapter mass
are recorded separately.  The continuous 24.576 kg denominator and the frozen
1e-12 native mass criterion are unchanged; no normalization or post-result
threshold change is made.

The labels request is CPU-only, root-dispatch-only, and launch-disabled.  It
passes the corrected exclusion CSV explicitly to the v6 event operator, keeps
unknown mass in the denominator, and declares no Q-I, Q-N, or production
status.  No solver, GenCase, conversion, or labels task was started here.
