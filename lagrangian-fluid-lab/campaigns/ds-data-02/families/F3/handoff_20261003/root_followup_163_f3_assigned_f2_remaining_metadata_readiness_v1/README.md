# F3-assigned fresh163: F2 remaining metadata readiness

This package is an F3-scoped metadata handoff for the actual F2 cases that Root1268 left without an accepted visual decision. Root1268 contains 11 unaccepted F2 rows; fresh162 already delivered `F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT075` (commit `72079b5690b966fa6541642db35accec036199b8`), so fresh163 audits the remaining ten rows. RX061/ROT105 control and lifecycle metadata are retained here, while their personal PNG review remains delegated to `f5_bed_recovery`; this package does not open PNGs.

Every audited row has its own registered GenCase prepared report, initial-QA report, native request/receipt, typed conversion report/receipt, and XMF manifest/receipt. The actual producer records close at completed/0 with 401 frames, 418104 particles, 3-D output, and measured GenCase counts of 372840 fixed, 24150 moving, 0 floating, and 21114 fluid. Those values are copied per case from the corresponding JSON reports; no source-side count was substituted.

The source controls are explicit per row: receiver x, receiver y=0.14 m, hold start=0.5 s, the row’s duration and stop time, final angle -105 degrees, full 4 s window, `dp=0.01`, `tout=0.01`, and source motion digest. Source GenCase and native launch/after attestations agree for each row. Typed lifecycle statistics are preserved per case, including exact 401-frame time bounds, frame counts with missing particles, first missing frame by type/Mk, transient omission events, and the reports’ unknown location/state reason. Missing particles are not filled or reclassified.

Nine rows have an XMF manifest and a registered renderer request but no actual render receipt/publish in the frozen metadata. RX061/ROT105 also has a completed/published renderer metadata record, but this package records it only and does not inspect its PNGs. The next root-owned action is render receipt reconciliation and delegated or root visual review; no case credit, precision, Q-N, Q-E, or production approval is granted here.

The package reads JSON metadata and records producer-attested digests only. It does not read, hash, copy, or open H5/BI4/CSV/DAT/VTK payloads, start jobs, or modify shared state. F3 is the assigned handoff family; the physical cases remain F2.

Run the validator with:

```text
python3 scripts/validate_fresh163.py
```
