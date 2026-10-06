# fresh139 F3 remaining-14 pipeline census

This source-only package freezes a metadata census against CP172. CP172 records F3 at 34 accepted cases; the full48 source census leaves 15 rows outside the accepted decision set, of which the declared P1000/AY0500 visual alias is not an independent case. The package therefore tracks 14 remaining physical conditions.

The census reads JSON receipt metadata and integration request JSON only. It does not open, copy, decode, or hash BI4/H5/CSV/DAT/VTK payloads, and it starts no job or shared controller. Receipt SHA values in this package are hashes of the JSON receipt files themselves; payload hashes are intentionally excluded.

Current actionable downstream gaps are Root023 render registrations for P1200/AY0500 and AY0540 after their terminal root1076 XMF receipts, plus P1200/AY0570 and AY0640 after their already-registered-but-not-yet-terminal XMF requests. P1000/AY0270 remains blocked on its live typed attempt root154 and must wait for that exact terminal receipt before any XMF/render request. Other remaining cases already have integration render requests, but no local terminal full-animation report was present at census time, so no visual decision is made here.

See `metadata/remaining14-census.json` for per-case stage states, `metadata/downstream-gap-report.json` for the bounded main handoff, and `metadata/visual-review-readiness.json` for the explicit no-review result.
