# F6 fresh198: F5 M092/T095 original1136 visual-review handoff

This package is assigned to F6 for review while the physical case belongs to F5:

- `case_id`: `F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M092_T095_NEXT34`
- `physical_case_id`: `F5_COMPACT_RUNUP_RECOVERY_C082S1_M092_T095`
- original render attempt: `root-stage1-f5-m092_t095-actual1112-bed0-full801-original116023-frozen-progress-root1136`

The metadata preflight found the upstream bed, native, typed, and XMF roles with their own JSON receipts/reports. The original1136 render receipt is genuine `ds02.execution-receipt.v1`, but it is still `status=running` with no return code or after-run digest. Its controller and registered render worker were present at preflight. No published render report or main-process own-QI proof exists in this snapshot, so this package records a wait state and starts no image review.

The expected physical metadata is 801 frames, 194427 particles, fixed158559, moving4210, floating0, fluid31658, 16 seconds, 34 contact sheets, and 9 key frames. Those are input expectations and producer metadata; they do not grant bed, sub-DP, precision, Q-N/Q-E, or visual acceptance. Native, typed, XMF, bed SourceDef, canonical, and legacy scopes remain separate. The package does not inherit another F5 case's values.

`metadata/preflight.json` contains only JSON metadata observations and stat-only XML/log references. It does not read or hash H5, BI4, IBI4, CSV, DAT, VTK, VTU, or PVTU payloads. `scripts/validate_fresh198.py` rechecks JSON SHA/identity/status, the original live PID/start ticks, expected frame/count metadata, and the required terminal/publish/QI boundary without sending signals or starting work.

Do not open PNGs until the same original attempt has an atomic completed/0 receipt and the main process supplies its own-QI proof. After that gate, a successor review package may record personal viewing of the actual 34 contact sheets and keys `[0,100,200,300,400,500,600,700,800]`. This preflight has `case_credit=0`, `QN=0`, `QE=0`, and `visual_review_started=false`.
