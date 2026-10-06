# F3 fresh128 full-48 stage census and three typed handoffs

This isolated F3 source package records a metadata-only census for all 48 first-48 physical condition identities and prepares three disabled, zero-credit full-836 XMF/Root023 render continuations. The selected terminal typed producers are:

- `F3_STAGE1_DP006_P0800_AY0540` (Root978 typed completed/0)
- `F3_STAGE1_DP006_P1200_AY0290` (Root991 decoder-repair1 typed completed/0)
- `F3_STAGE1_DP006_P1200_AY0320` (Root978 typed completed/0)

The selection excludes Root974, source125/Root997, source126/Root1002, and fresh127 downstream cases. Existing accepted visual identities are represented by the frozen accepted-scope snapshot and never recounted. Each row in `metadata/full48-stage-census.json` links safe JSON/XML metadata paths for GenCase/native/typed/XMF/render attempts, pending requests, and visual decisions; mutable progress is evidence only and is never used as a runtime input.

The three XMF and Root023 requests remain `disabled: true`, `execution_allowed: false`, `launch_allowed: false`, `case_credit: 0`, and all future XMF/render receipt, manifest, XDMF, render-report, and visual hashes are null. The typed producer H5 digest is recorded only as the conversion report's producer attestation; this source package never opens, copies, or hashes H5/BI4/CSV/DAT/VTK payloads. Numerical precision and visual acceptance remain pending.

Validation is metadata-only:

```text
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_fresh128.py
```

No solver, converter, renderer, or shared ledger was started or modified by this package.
