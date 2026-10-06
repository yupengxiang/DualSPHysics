# fresh105: Root638 F4 visual-review index

This small F6-owned sidecar points Root to the first two Root638 `completed/0` F4 products that are absent from the checkpoint's F4 accepted decisions. It records actual native/frame0-QA, typed, XMF, manifest, render receipt/report, contact-page, and keyframe filename metadata for:

- `F4_DROP_gap0p18000_xoff0p08000_yoff0p04000_uz0p40000`
- `F4_DROP_gap0p18000_xoff0p08000_yoff0p04000_uz0p60000`

The index is a handoff for visual inspection. It grants no visual acceptance, Q-N status, production approval, precision result, or case-count increment. The render report itself remains `visual_review=pending root inspection of the full animation and every contact sheet` and `numerical_precision_status=not accepted`.

The builder inspected JSON/XML metadata and PNG names/existence only. It did not open or hash BI4/H5/CSV/DAT/array payloads, read PNG bytes, launch or stop jobs, or edit shared state. Canonical/actual converter scope, source-owner scope, and source-plan scope remain separate; the legacy scope is explicitly not a cross-resolution physical claim.

Validate the sidecar with:

```sh
python3 workers/validate_fresh105.py
```
