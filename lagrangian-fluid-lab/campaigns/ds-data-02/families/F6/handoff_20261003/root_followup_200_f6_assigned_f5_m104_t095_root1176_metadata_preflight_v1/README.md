# Fresh200 F5 M104/T095 metadata preflight

- Reviewer: `/root/f6_endpoint_initial_qa`
- Preflight observed UTC: `2026-10-07T10:32:02.681140Z`
- Assigned family: `F6`; physical family: `F5`
- Case: `F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M104_T095_NEXT34`
- Physical case: `F5_COMPACT_RUNUP_RECOVERY_C082S1_M104_T095`
- Attempt: `root-stage1-f5-m104_t095-actual1171-bed0-full801-original116023-frozen-progress-root1176`

This is a source-only metadata preflight for the already registered Root1176 render. The actual receipt was `running` at the observation time; no return code, terminal completion, atomic publish, report, PNG, or personal visual review is asserted. The receipt is a point-in-time snapshot, not a stable terminal reference.

The package binds actual bed/native/typed/XMF/XML/renderer metadata and inspects XMF structure without opening HDF data. Roles remain separate: canonical `83831d4fc2150e22f79c5bc6d4a6e655c2ab6c43b517288c531b490ed3563877`, typed legacy `c7a06c6bdcbf126b3758317aabda1815621e3b2368d9ad546c14ef95d4e0aae1`, bed SourceDef `c4e0a0ad9924c53eba206011b0bac762a8babc706fc1bf101e1ca2e1f6450965`, and XMF producer plan `83831d4fc2150e22f79c5bc6d4a6e655c2ab6c43b517288c531b490ed3563877`. Presence masks for native, typed, XMF, and bed plan fields are recorded from their own files.

Expected render contract: 801 frames, 194427 particles, 34 contact sheets, keyframes `[0,100,200,300,400,500,600,700,800]`. Future render receipt/report/PNG hashes are `null`; `case_credit=0`, Q-N/Q-E are false, and no numerical, strict-containment, or visual acceptance is claimed.

No H5, BI4, CSV, DAT, or VTK scientific payload was read, copied, or hashed. No PNG was opened. This package did not start, stop, restart, or modify any task or shared state.

Validate with `python3 scripts/validate_fresh200.py`.
