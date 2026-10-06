# F6 fresh147 failed-artifact storage audit

This is a metadata-only, non-destructive storage audit. It inventories failed `execution-receipt.json` attempts, records directory/file `stat` totals, and closes a bounded dependency check for failed attempts at least 50 MiB and all failed `typed`, `render`, `XMF`, and `XDMF` paths.

The audit did not open, copy, or hash H5, BI4, CSV, DAT, VTK, or other scientific payloads. It did not delete files, alter receipts, change the resource ledger, launch work, or change case credit. Receipt/log/initial-last-failure evidence remains protected.

There is no safe large deletion candidate. The two large failed downstream trees are F5 A080/A120 render attempts, 26.8 MiB each, with `returncode=-15` and `termination_reason=reserved_cpu_budget_exceeded`; they remain referenced by root610/root635 requests, the root634 reservation review, WAIT decisions, and later checkpoints. The recent F3 root981 typed failure is a small receipt/report failure with an explicit decoder-path error and is retained by its repair/audit lineage. The largest historical failed trees (F4 74.22 GiB, F3 12.32 GiB, F2 8.09/8.04 GiB) retain historical/current dependency references and are review-only, not deletable by this package.

Root965's already authorized cleanup is recorded as a baseline only: 14 attempts, 15,995 files, and 439.00610971078277 GiB deleted, with the two F6 medium native attempts retained because domain-audit receipts reference them. Fresh147 performs no repeat cleanup.

`metadata/large-failure-review.json` contains exact receipt paths, stat totals, failure causes, and bounded reference paths. `scripts/validate_fresh147.py` validates the package without touching the data root.
