# F2 RV4-equivalent floor-safe postprocess handoff

This handoff records the two completed `DP005` reduced-step solver views:

- `CENTER`: 401 native save frames through `4.000001455861041 s`, with
  `NpOut=2185`, `NpOutPos=2184`, `NpOutRho=1`, and `NpOutMov=0` summed over
  the complete `RunPARTs.csv` window.
- `OFFSET`: 401 native save frames through `4.000000823955854 s`, with
  `NpOut=2158`, `NpOutPos=2158`, `NpOutRho=0`, and `NpOutMov=0` summed over
  the complete window.

The official `PartVTKOut_linux64` audit is recorded at
`/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_FLOORSAFE_NATIVE_PARTVTKOUT_20261003_V1/rv4-floorsafe-native-preflight-001/rv4-floorsafe-native-partvtkout-diagnostic.json`.
Its report has SHA256
`46ccef2c7fee65a351711a608a0ca05b1b0b3dcfa731a617b82be2b0479bf588`.
All decoded rows remain `native_solver_excluded_numerical_unknown`; the
position/domain-face information is evidence only.  Moving-body pose and
finite-surface fate remain deferred to full-state conversion.

The generated conversion requests are root-dispatch-only and use the official
`PartVTK_linux64` full-frame path.  They bind the actual XML, BI4, copied
motion, GenCase receipt, solver receipt, RunPARTs, PartInfo, PartMotionRef,
PartOut, and first/middle/last native frames.  Labels are disabled until an
actual terminal trajectory H5, conversion report, and receipt are bound.  This
handoff does not claim Q-I, Q-N, or production readiness and does not reuse
adaptive-baseline exclusion IDs or Motive totals.
