# F6 fresh197: F2 final48 strict metadata gate repair

Fresh197 is an F6-scoped, source-only successor for F2. It leaves fresh195 and fresh196 immutable and performs no solver, converter, renderer, QA, registry, ledger, cleanup, or case-credit operation. JSON metadata is read and hashed; XML/XMF and PNG references are only parsed/stat-checked. H5, BI4, IBI4, CSV, DAT, VTK, VTU, and PVTU payloads are rejected before open or hash.

The frozen inputs for this package are the live checkpoint 300, the current F2 progress index, Root1276's explicit frozen8/actual24/registered48 membership, and Root1330's legacy primary catalog/corrections. The current index has 46 accepted F2 decisions and 2 pending rows. Fresh197 therefore emits a readiness product; it must emit no final48 catalog until the two pending decisions and every strict primary chain gate are real. Counts are derived from the supplied checkpoint/index, so a later current46/2 or current48/0 run is supported without a hard-coded old count.

The strict per-case gate requires all of the following:

- accepted decision path and SHA are present in the explicit checkpoint accepted decisions, with matching physical/case identity and accepted status;
- native, typed, XMF, and render roles use genuine `ds02.execution-receipt.v1` terminal receipts (`completed`, return code 0), case binding, runtime worktree/cwd, and launch/after-run input-output digest closure; a `ds02.runner-request.*` object is never promoted to a receipt;
- typed metadata proves 401 frames, 3-D, the expected particle count, PartVTK pass, exact `(Zone,Idp)` identity, an initial-exclusion ledger, introduced IDs rejected/closed, observed type/Mk ledger, 401 lifecycle active/missing/type totals, finite strictly increasing times, and source provenance for the genuine GenCase receipt, generated XML, and native solver receipt;
- GenCase is recovered from typed `source_provenance`, with the real receipt/XML/solver links checked; a request alone is insufficient;
- the initial-QA role has both a genuine case/input-bound QA receipt and a separate passing QA report with direct prepared/GenCase/PartVTK/XML/input evidence. Root QI summaries do not substitute for QA;
- XMF manifest/XML/render report independently prove the exact 401 timeline, N-by-3 geometry/velocity metadata, finite active fields, identity axis, and per-frame missing/type totals. Native producer time is preserved; it is never resampled to nominal `.01`/`.05` values;
- the published render report enumerates exactly 17 contact sheets and 9 key frames, each path is present/stat-checkable, and the selected execution receipt, report, manifest and publish product are joined to the same case. An existing non-empty output directory is rejected rather than overwritten;
- the four Root1330 request-shaped render records remain historical role evidence. For RX046/ROT120, RX048/ROT065, RX048/ROT120, and RX052/ROT065, the builder binds Root1330's explicit same-attempt terminal execution receipts and records the correction provenance. It never silently changes a request into a receipt;
- P03 preserves original typed135 `running`/missing return code. Only an independently verified recovery-aware XMF197 chain may provide physical completion evidence, and that evidence remains separate from the unknown original runtime.

Per-case missing particles, UID samples, causes, locations, source-plan/canonical/legacy namespaces, physical/native mass meanings, and original-vs-recovery runtime states remain verbatim disclosures. Q-N, Q-E, numerical precision, strict containment, all-UID survival, and mass equality remain false/unclaimed.

Build into a new or empty directory. Existing non-empty product directories are rejected:

```sh
python3 scripts/build_fresh197.py \
  --checkpoint /home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/ROOT_LIVE_RESUMPTION_CHECKPOINT_300.json \
  --current-index /home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_source183_actualF2_RX049ROT075_original1009_full401QI_personal26PNG_thirtyfive_fluid_omissions_genuineQA_native_XMF_roles_visual_acceptance_1402/full336-current320-actual-final48-delivery-progress-index.json \
  --membership /home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_sources178164_actual_F2_F3_F6_first24_delivery72_correct_own_primary_XMF_PNG_8_subset24_subset48_1276/F2-ACTUAL_FIRST24_DYNAMIC_DELIVERY.json \
  --legacy-catalog /home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_source173_F2_final48_actual42_primary_401frames_baseline421566_four_request_receipt_role_corrections_P03_unknown_typed_recovery_six_pending_1330/F2-FINAL48-ACTUAL42ACCEPTED-SIXPENDING-CORRECTED-PRIMARY-DELIVERY.json \
  --output-dir /abs/path/new/fresh197-output
```

Validate the same explicit boundary. The validator runs synthetic negatives for request-as-receipt, missing frame, wrong time, missing input/output digest closure, QA receipt without a passing report, invalid typed identity/ledger, exact contact/key cardinality, wrong XMF output root, and non-empty output. It then reruns the builder in a throw-away directory and checks dynamic accepted/pending counts, 8-subset-24-subset-48 membership, Root1330 corrections, JSON SHA closure, and per-case runtime disclosures:

```sh
python3 scripts/validate_fresh197.py \
  --checkpoint /home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/ROOT_LIVE_RESUMPTION_CHECKPOINT_300.json \
  --current-index /home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_source183_actualF2_RX049ROT075_original1009_full401QI_personal26PNG_thirtyfive_fluid_omissions_genuineQA_native_XMF_roles_visual_acceptance_1402/full336-current320-actual-final48-delivery-progress-index.json \
  --membership /home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_sources178164_actual_F2_F3_F6_first24_delivery72_correct_own_primary_XMF_PNG_8_subset24_subset48_1276/F2-ACTUAL_FIRST24_DYNAMIC_DELIVERY.json \
  --legacy-catalog /home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_source173_F2_final48_actual42_primary_401frames_baseline421566_four_request_receipt_role_corrections_P03_unknown_typed_recovery_six_pending_1330/F2-FINAL48-ACTUAL42ACCEPTED-SIXPENDING-CORRECTED-PRIMARY-DELIVERY.json \
  --package-dir /abs/path/root_followup_197_f6_assigned_f2_final48_gate_repair_v2
```

The last command's `--legacy-catalog` should be the Root1330 catalog path from the build command; the shortened package-dir is shown only as a placeholder. No source package writes the shared checkpoint or current index. The package remains assigned to F6 while its physical rows are F2.
