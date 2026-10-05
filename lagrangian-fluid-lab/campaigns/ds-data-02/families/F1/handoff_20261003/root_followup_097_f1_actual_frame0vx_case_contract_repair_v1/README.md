# F1 fresh097: frame-0 VX worker case-contract repair

fresh096 and Root490 remain immutable historical evidence. Root490 registered the first fresh096 frame-0 request and failed before PartVTK because the worker requires `case["partvtk"]`, while fresh096 placed the same official PartVTK path only at binding top level. The failure is preserved in `metadata/root490-frame0vx-failure-review.json` and carries no frame-0 credit.

This package is a source-only fresh097 repair. Every one-case binding now exposes the worker's complete AST-derived case contract, including `partvtk` and `partvtk_sha256`, with the same official binary path and SHA as fresh096. The worker bytes, PartVTK checks, thresholds, actual Root480 native receipts, full time windows, and raw GenCase velocity exclusion are unchanged.

All 24 requests remain disabled (`execution_allowed=false`, `launch_allowed=false`, `launch=false`). Root492 may register/enable them after review. Native Root480 completion remains separate from saved-frame-0 VX proof; future PartVTK audit reports and scientific payload hashes remain null. No typed NVMe/XMF/render request is included until Root492 actually completes zero.

Static verifier (metadata/source only):

```text
python3 /home/jade/.codex/worktrees/ds-data-02-f1/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/root_followup_097_f1_actual_frame0vx_case_contract_repair_v1/scripts/verify_actual_native480_frame0_case_contract.py --package /home/jade/.codex/worktrees/ds-data-02-f1/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/root_followup_097_f1_actual_frame0vx_case_contract_repair_v1
```

The verifier AST-checks all ten worker case keys, confirms `cases[*].partvtk` equals the top-level binding path/SHA, verifies Root480 receipt/request identity and disabled closures, and does not read or hash BI4/H5/CSV/DAT/VTK payloads.
