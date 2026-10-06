# F6 fresh104: Root716 exit-143 gate diagnostic

This is a metadata-only, read-only sidecar. It records the parent-observed `tool71522` exit code 143 and the source/receipt evidence captured by fresh104.

Root716 first polls the Root670 and Root637 controller-result files, then requires all 24 Root638 render receipts to be `completed` with return code 0. Root670 has a real 24/24 result, but Root637 had no result file in the recorded evidence. Root638 has 24 requests with 8 completed/0, 2 running, and 14 without a receipt. Root716 therefore had no safe path to launch. Exit 143 has no persisted signal or stderr provenance here, so its cause remains unknown while the wait gate was unresolved.

The `/proc` snapshot records current sleeping argv entries for the Root637 and Root716 controller paths. Those PIDs are a later observation and cannot be mapped back to the historical `tool71522` handle; the earlier parent scan reported no PID for the original 716 argv.

The sidecar does not start or kill processes, read or hash BI4/H5/CSV/DAT/array payloads, modify Root716/source103, or grant visual/Q-N credit. The minimum recovery is to reconcile Root638 under the parent scheduler, obtain a real Root637 terminal result, then use a new controller/attempt directory only after all 24 receipts are terminal `completed/0`.

Run the validator from the F6 worktree:

```text
python3 /home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_104_root716_exit143_root638_gate_diagnostic_v1/workers/validate_fresh104.py
```
