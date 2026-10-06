# F3 fresh119 failed-output cleanup audit

This package is a read-only cleanup candidate audit. It does not delete files,
edit the shared ledger, alter receipts, launch workers, or inspect scientific
payload contents. The audit opens JSON ledger/receipt metadata and uses
`stat(2)` plus filename-extension counts for output trees; BI4, IBI4, OBI4,
H5, CSV, DAT, VTK, and related files are never opened or hashed.

The generated report found 60 failed, interrupted, or reserved F3 receipt
records and 76 successful native solver receipts. All successful native
receipts are preservation stock, including the six Root884/Root948 receipts;
QN or precision status is not used as a deletion criterion. The F3 ledger
summary records 17 failed qualification attempts, 4
`native-output-recovered-runtime-finalization-unavailable` production records,
45 failed CPU records, one interrupted CPU record, and two reserved CPU
records. The ledger has 62 failed charge records while the receipt walk found
60 failed/interrupted/reserved receipt records; that accounting difference is
preserved for Root reconciliation rather than guessed away. The current
ledger reservation observed during this audit belongs to F2, not F3.

There is one stat-visible failed solver raw-output candidate:

* `F3_DUAL_AXIS_PHASE_PARENT_SOLVER_QUAL_01` at
  `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_DUAL_AXIS_PHASE_PARENT/F3_DUAL_AXIS_PHASE_PARENT_SOLVER_QUAL_01`
  is failed with return code `-15`. Its tree has 1,800 files and
  10,309,161,954 bytes, including 1,788 BI4 files (10,298,394,240 bytes),
  two IBI4 files, one OBI4 file, four VTK files, and one CSV. The recorded PID
  `2350838` is absent, no current ledger reservation matches it, and the
  recorded output is referenced by the existing F3 execution queue and two
  qualification request JSON files. A successful sibling
  `F3_DUAL_AXIS_PHASE_PARENT_SOLVER_QUAL_02` also exists. The report therefore
  marks this candidate **hold for Root dependency review**; it is not a delete
  authorization.

The largest non-solver failure is the old CPU conversion
`direct-half_save-20261002-003` (13,229,641,085 stat bytes, including H5),
but it is explicitly excluded from the solver-raw candidate set and has six
current metadata references. Other failed CPU/GenCase/PartVTK/render records
are listed with their exact stat breakdown and are not silently promoted to
cleanup candidates.

The current checkpoint is
`ROOT_LIVE_RESUMPTION_CHECKPOINT_127.json` (199 accepted, F3=12). Its twelve
F3 decision paths and all successful native receipts are recorded in the
preservation section. No F3-specific `root_followup_130` or
`root_followup_131` path was found in the integration family tree, so the
audit makes no assumption that pending 130/131 work is disposable.

Root must independently recheck current queue/lease/dependency state immediately
before any bounded cleanup. This package intentionally performs no cleanup.
