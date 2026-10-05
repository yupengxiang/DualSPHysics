# F3 fresh071 Root owned typed conversion recovery contract

This source package defines a disabled Root owned recovery application for the
two orphaned CPU conversions observed by the fresh070 bounded diagnostic. It
does not run a converter, read BI4/H5/CSV payloads, signal a process, release a
lease, or write the shared ledger. The only live application entry point is
the library function in `reconcile_typed_conversion.py`; its explicit
authorization gate is closed in this package and the command line exits
closed.

The contract is deliberately narrower than the ordinary runtime settlement:
it accepts only a reservation whose exact canonical row hash, CPU conversion
kind, reservation id, and hostname match the Root supplied binding. It rejects
GPU reservations and any row with GPU identity. Root must supply two complete
qualified host samples. Each sample must prove, from `/proc/<pid>/stat`, that
the recorded launcher PID, conversion child PID, and process-group leader are
absent, that the exact process group scan is complete and empty, and that the
original PID/start-tick/boot-id anchors cannot have been replaced by a reused
PID. AY0270 is therefore refused while child `2367325` is in `D` state.

After Root review, `apply_reconciliation()` uses the unchanged runtime v2
`ledger_locked()` and `atomic_json()` interfaces. It first preserves the exact
old receipt bytes as an exclusive sidecar and writes a durable prepared
journal. Under the runtime ledger lock it removes only the exact dead CPU
reservation, appends one idempotent charge for the full original reserved
`cpu_core_seconds`, and changes only that attempt to
`interrupted_unfinalized`. It keeps child returncode `null`, records tool
status 143 separately, and never claims OS exit 0. A second invocation is a
no-op after matching the transaction id and charge. The journal is committed
after the runtime ledger's atomic write and directory fsync; replay resolves a
crash between those two writes without double charging. GPU leases, other
reservations, counters, adoption state, limits, and deadline are checked for
byte-equivalent preservation.

`artifact_integrity_worker.py` and
`requests/p03_artifact_integrity_request.json` are a separate disabled strict
CPU audit design for the already published P03 full401 output. That worker's
own returncode 0 is written to a new audit output only; it cannot rewrite the
old conversion receipt or convert its unknown child returncode into OS exit 0.
The worker hashes the existing H5 as an opaque artifact and checks the already
recorded report, stdout, and PartVTK facts. It does not decode particle
arrays.

The package binds the immutable runtime-v2 source (`5098262e…ae67a60`), the
current reservation snapshots, Root's qualified host diagnostic, and the
actual P03/AY0270 receipt/report metadata. The package records current facts
only; the required two-sample `/proc` proof remains future input and no
future hash is fabricated.

Run the synthetic semantic checks with:

```text
python3 -B tests/test_fresh071_reconciliation.py
```
