# fresh169: F6 full-time rigid-export metadata review

This F3-owned package records a read-only Root142 review of the F6 full-time
FloatingInfo export.  It contains no CSV, IBI4, BI4, H5, DAT, VTK, or XMF
payload.  The source-side validator opens JSON receipts and JSON worker
reports only; it never opens or hashes the official CSV or `PartFloatInfo.ibi4`.

Root1302 completed the registered 47-file `PartFloatInfo.ibi4` inventory first:
47 entries, 180,376 bytes per entry, 8,477,672 bytes total.  The registered
worker supplied the input SHA values.  This package records those producer
attestations without recomputing them from the scientific files.

The Root1303 pilot is the last F6 DZXY/S1375/YAWP18 case.  Its completed JSON
report establishes the pilot contract: `part` is `frame_index` with the
observed sequence 0 through 240; 241 rows were parsed; the required rigid
groups have 241 finite rows; and the maximum reported native-time difference
is `4.9897863618753036e-12` seconds, below the `1e-6` contract.  The review
also checks the official command (`-first:0`, `-last:240`, `-onlymk:60`,
`-savemotion:1`, `-csvsep:0`) and the inventory entry, native receipt, and
producer-reported CSV output metadata.

Root1304 subsequently completed all 46 remaining cases with return code 0.
The review snapshot records each report and receipt path, JSON SHA, case and
physical identity, rows/Part contract, finite-field count, native-time bound,
inventory producer SHA, and producer-reported output SHA.  Output CSV hashes
are reported values from the registered worker; they are not independently
read or hashed here.

Root1305 independently records the resulting 48-row F6 delivery product at
`F6-FINAL48-FULLTIME-RIGID-MOTION-DELIVERY.json` (SHA
`5456c3ba09b2ae34f1524be71bcaff0b537b9720e1a988b6c2f762120ae906ca`).  It
contains 47 new completed exports plus one reused historical full-241 row;
this package verifies that split and keeps the historical row's Part-column
validation explicitly false/null.

The existing F6 baseline is listed separately as historical full-241 evidence
from the frozen fresh167 coverage record.  It is not silently recast as a
fresh169 worker report.  No case credit, visual credit, Q-N, or Q-E credit is
granted by this package.  The last-F6 three-fluid omission and native versus
continuum mass distinction remain outside this metadata acceptance.

Run the validator from this worktree with:

```text
python3 lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_followup_169_f3_assigned_f6_fulltime_rigid_export_actual_metadata_review_v1/validate_fresh169.py
```
