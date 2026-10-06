# fresh106: Root638 typed-manifest closure supplement

This is an additive successor sidecar for [fresh105](../root_followup_105_f4_root638_visual_review_index_v1). It leaves fresh105 and all consumed products immutable. For the same two non-accepted Root638 F4 cases, it reads each actual XMF `manifest.json` and records its absolute `typed_receipt` and `conversion_report` fields, manifest producer SHA values, metadata-file SHA values, terminal receipt status, conversion metadata pass, and the exact UID-missing/lifecycle status.

`conversion_report.partvtk_validation.all_passed=true` is reported as producer metadata. The sidecar keeps `production_eligibility`, Q-N, precision, and visual review statuses unchanged; it does not grant acceptance. A nonzero lifecycle missing report is retained rather than hidden.

Only JSON metadata was read. No BI4/H5/CSV/DAT/array payload was opened or hashed, and no job or shared state was changed.

Validate with:

```sh
python3 workers/validate_fresh106.py
```
