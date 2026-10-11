# M4 metadata resource audit

`run_m4_resource_audit.py` is a read-only, root-reviewable checkpoint helper.
It validates the immutable batch-2 admission with the existing batch-2 runtime
history checks, compares the shared parent ledger against the accepted M1–M3
baseline, and verifies every post-admission UF charge and reservation from
small execution or reconciliation metadata.

The audit keeps CPU charge rows separate from reserved CPU ceilings. GPU and
storage values come from the ledger's actual charge rows; reservations are
reported separately. It checks the fixed deadline and parent limits, preserves
historical cumulative usage, and inventories the four final actual-validation
receipts from `M4_RELEASE_INPUT_V1.json`.

It does not launch work or write requests, grants, the ledger, global status,
or leases. It does not walk the NAS or read/hash HDF5 or BI4 payloads. A
successful invocation writes one fresh immutable checkpoint at
`checkpoints/M4-resource-audit-v1.json`; missing product receipts leave the
checkpoint in `pending_actual_product_receipts` status for the root final
release audit.

```sh
/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python \
  lagrangian-fluid-lab/campaigns/ds-data-02/upstream-first/m4-cost-audit/run_m4_resource_audit.py
```
