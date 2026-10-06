# F6 fresh141 — delegated F4 visual acceptance

This package records a delegated visual review of three Root951 F4 gap-0.26, xoff=-0.08 cases:

- F4_DROP_gap0p26000_xoffm0p08000_yoff0p04000_uz0p40000
- F4_DROP_gap0p26000_xoffm0p08000_yoff0p04000_uz0p60000
- F4_DROP_gap0p26000_xoffm0p08000_yoffm0p04000_uz0p60000

The reviewer personally opened all 51 chronological contact sheets and the nine key frames (0, 150, 300, 450, 600, 750, 900, 1050, 1200) for each case with `view_image`. The status is `visual-approved-by-delegated-agent`; `case_credit` remains 0 and no global decision or ledger was changed.

The package binds each case to its own terminal Root951 receipt, 1201-frame renderer report, publish receipt, initial-QA metadata, typed conversion report, XMF manifest/case file and PNG SHA-256 inventory. Canonical-owner, source-plan/template and actual-converter scope fields are preserved as separate roles; equality is not inferred. Producer lifecycle fields distinguish transient missing-frame count from maximum missing particles and final-frame missing particles. No final UID is inferred from images.

The renderer reports retain `numerical_precision_status=not accepted`; this package makes no Q-N/Q-I, precision, or production claim. No BI4/H5/CSV/DAT/VTK scientific payload was read, copied or hashed, and no job or shared state was modified.

Run the metadata-only validator with:

```text
python3 workers/validate_fresh141.py
```
