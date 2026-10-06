# F1 Root781 original-seven visual decisions (fresh093)

This F3-local handoff records delegated visual reviews for the remaining two cases:

- `F1_STAGE1_DUAL_H240_DP020_VX010`
- `F1_STAGE1_DUAL_H280_DP020`

Each case has actual GenCase, pre-native QA, native, native-frame-0 QA, legacy-scope typed, XMF, and Root023 render metadata bindings. All 17 chronological two-camera contact sheets and full-size frames 0, 65, 115, and 400 were inspected with `view_image`. The render report's `xdmf` path and SHA are checked against `manifest.json`'s `xdmf` binding; no stale XMF path is copied.

Both visual decisions retain the historical failed 088 typed attempt as failed/1 and use only the actual completed 089 legacy-scope typed receipt for the downstream product. These are delegated visual decisions only: no Q-N, precision, production, or global-count grant.

Only JSON metadata and rendered PNG artifacts were read/hashed. No H5, BI4, CSV, DAT, or VTK scientific payload was read, copied, or hashed; no solver, converter, render, registry, ledger, or shared-state mutation was performed.
