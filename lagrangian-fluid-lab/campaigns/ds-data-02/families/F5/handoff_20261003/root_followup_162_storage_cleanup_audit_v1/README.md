# F5 fresh162 storage cleanup audit

This package is a read-only metadata audit for the user-authorized DS-DATA-02 storage review. It does not delete files, change the shared resource ledger, launch a worker, or read/hash BI4, H5, CSV, DAT, VTK, or PNG payload bytes. The reproducible entry point is `scripts/audit_fresh162.py`; the snapshot is `metadata/fresh162-audit-report.json`.

The audit saw 518 F5 `execution-receipt.json` files: 442 `completed/0`, 61 `failed/1`, 3 `failed/-15`, 4 `failed` without a return code, 8 `completed` without a return code, and one current receipt whose state changed during the audit. The ledger has 67 failed F5 attempts and no F5 `production` kind; its F5 reservation and home floor are recorded in the report. The home free space at the snapshot was 544,658,558,976 bytes against the 536,870,912,000 byte floor.

The clearest payload-only review candidates are four failed solver attempts. Each has no live PID or file descriptors, no downstream receipt reference, and exactly one `Part_0000.bi4`; the solver log says it failed before the next frame because `assets/f5_compact_packet_motion.dat` could not be opened.

| Attempt | Requested window | Actual BI4 frames | Partial BI4 bytes | Directory bytes |
|---|---:|---:|---:|---:|
| `root-compact-equilibrium-runup_coarse-full801-native-055` | 801 | 1 | 9,440,668 | 9,564,283 |
| `root-compact-equilibrium-runup_medium-full801-native-055` | 801 | 1 | 29,308,561 | 29,443,077 |
| `root-compact-equilibrium-weir_coarse-full801-native-055` | 801 | 1 | 9,490,827 | 9,614,489 |
| `root-stage1-f5-explicit-bed-repair-a-short-event-native-091` | 51 | 1 | 9,434,953 | 9,556,115 |

Their exact receipts, output roots, BI4 names, log evidence, PID/fd snapshots, and dependency scan are in the JSON report. Keep each receipt, `stdout.log`, `Run.out`, and provenance metadata before any parent-controlled payload removal.

Two old Root610 render attempts are also incomplete review candidates: A080 has 452 `frame_*.png` plus 18 `all_frames_*.png` and 27,906,633 directory bytes; A120 has 453 `frame_*.png` plus 18 `all_frames_*.png` and 28,093,868 directory bytes. Both ended `-15`; the replacement Root635 receipt references the old attempt, so retain the old receipt and failure provenance. The old Root751 M085_T080 typed attempt is a 186,468-byte ABI-import failure with no scientific output; Root753 is the successful replacement. These are review-only recommendations, not automatic deletion instructions.

The eight negative-evidence groups remain protected by default. They include the 354,894,671-byte compact geometry QA with `inside_weir_solid=240`, the 31,209,350-byte runup geometry QA with `below continuous bed=10860` and `outside bounds=300`, A061 QA failures, C082R1 unique-Y/precision negatives, C082S1 lattice-negative evidence, and the C082 thick-bed GenCase count assertion. Numeric precision negatives are not treated as cleanup justification.

The report explicitly protects M085 actual854/953/956/960, M086 actual850/864/963 plus the fresh161 adapter, M095 actual808/939 and their GenCase/QA producers, all completed/unknown receipts, accepted199/accepted-decision/verified-stock data, native0 stock, and current queue dependencies. Re-read the shared ledger and dependency graph immediately before any cleanup; this package itself performs no cleanup.
