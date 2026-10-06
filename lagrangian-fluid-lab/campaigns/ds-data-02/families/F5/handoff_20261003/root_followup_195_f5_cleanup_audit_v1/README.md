# F5 fresh195 cleanup audit

This is a read-only F5 storage review for the user-authorized DS-DATA-02 cleanup. It reads JSON receipts, selected small logs, the existing F5 current-48 census metadata, and filesystem names/stat sizes. It does not open, hash, copy, delete, or transform BI4/H5/CSV/DAT/VTK/PNG payloads, launch a worker, or modify the shared ledger.

The audit snapshot contains 663 F5 execution receipts: 585 `completed/0`, 8 `completed` without a return code, 62 `failed/1`, 3 `failed/-15`, 4 failed receipts without a return code, and one currently running receipt. The live receipt is the M090_T095 Root1109 bed audit and is protected. The cited current-48 metadata source has 48 physical rows; it is used only as membership evidence and is not reinterpreted as payload acceptance.

There is **no F5 payload approved for deletion in this package**. The six entries in `metadata/fresh195-audit-report.json` are bounded review items, not deletion instructions:

| Review item | Payload observed by stat | Why it stays | Exact output root |
|---|---:|---|---|
| Compact runup coarse 055 | `Part_0000.bi4` 9,440,668 bytes; directory 9,547,899 bytes | The only saved frame is the first/last diagnostic frame; retain it with receipt/log provenance. | `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050/root-compact-equilibrium-runup_coarse-full801-native-055` |
| Compact runup medium 055 | `Part_0000.bi4` 29,308,561 bytes; directory 29,426,693 bytes | Same first/last diagnostic-frame rule; failure was the missing relative motion asset. | `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP0125_EQUILIBRIUM_ROOT050/root-compact-equilibrium-runup_medium-full801-native-055` |
| Compact weir coarse 055 | `Part_0000.bi4` 9,490,827 bytes; directory 9,598,105 bytes | Same first/last diagnostic-frame rule; retain failure evidence. | `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_WEIR_DP020_EQUILIBRIUM_ROOT053/root-compact-equilibrium-weir_coarse-full801-native-055` |
| A061 short 091 | `Part_0000.bi4` 9,434,953 bytes; directory 9,539,731 bytes | This is a failed relative-asset attempt; retain its sole diagnostic frame and keep the separate A061 genuine short-event negative chain. | `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_A061/root-stage1-f5-explicit-bed-repair-a-short-event-native-091` |
| Compact geometry QA 052 | CSV payloads total 354,801,105 bytes; directory 354,890,575 bytes | Historical weir-solid-overlap evidence has request/binding references; retain raw QA until Root explicitly retires those references. | `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_COMPACT_EQUILIBRIUM_ACTUAL_COARSE_GEOMETRY_QA/root-compact-equilibrium-two-mechanism-three-dp-full-native-geometry-qa-052` |
| Compact runup geometry QA 049 | CSV payloads total 31,147,909 bytes; directory 31,205,254 bytes | Historical below-bed/outside-bounds evidence has request/binding references; retain raw QA until Root explicitly retires them. | `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_COMPACT_EQUILIBRIUM_ACTUAL_COARSE_GEOMETRY_QA/root-compact-equilibrium-runup-coarse-full-native-geometry-qa-049` |

The report preserves the exact payload filenames and stat sizes. It does not infer that any of these files is disposable from `failed` or Q-N status alone. Before a later parent-controlled cleanup, Root must freeze and reread the ledger/controller state, verify no PID/fd or downstream reference, archive the receipt/log/report/provenance files, and preserve the sole first/last diagnostic frame for each one-frame failure. This package itself performs no cleanup.

The following evidence is explicitly protected: the A061 genuine short native/typed/XMF chain and its severe penetration report; the B071 genuine short native/typed/XMF chain and its severe penetration report; A061 QA081/082 initial failures; C082R1 exact-lattice and unique-Y negatives; C082S1 exact-lattice negative; the C082 thick-bed count-mismatch geometry; and the terminated Root610 A080/A120 render provenance referenced by later replacements. The current C082S1 48-row recovery collection, all completed/unknown receipts, and the live Root1109 attempt remain protected by default.

Run the metadata-only validator with:

```text
python3 /home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_195_f5_cleanup_audit_v1/scripts/validate_fresh195.py
```
