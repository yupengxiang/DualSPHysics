# F3 fresh064: first24 source variants

This isolated F3 package adds exactly sixteen amplitudes: 0.27, 0.29, 0.3, 0.34, 0.36, 0.37, 0.41, 0.43, 0.44, 0.48, 0.52, 0.54, 0.59, 0.61, 0.67, 0.71 m/s². The first8 rows are embedded unchanged from working056v3, including the original AY=.50 mother case ID. Production selection contains only the sixteen new IDs.

Root can review `requests/batch-source-preparation-request.json` and, when authorized, run the one batch CPU source entry:

```text
/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python /home/jade/.codex/worktrees/ds-data-02-f3/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_followup_064_stage1_first24_source_variants_v1/source_builder.py --binding /home/jade/.codex/worktrees/ds-data-02-f3/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_followup_064_stage1_first24_source_variants_v1/source-binding.json --output-dir {attempt_root}/prepared
```

`source_builder.py` calls the existing preparation012-compatible `prepare.py` and frozen transformer once. It has no solver, GenCase, conversion, ParaView, GPU, or array-reader path. New forcing and physical-condition hashes stay null until Root CPU preparation emits actual reports.

The sixteen disabled requests under `requests/` keep the exact consumed solver argv: `DualSPHysics5.4_linux64 -mdbc_noslip:1 <prepared-prefix> {attempt_root}/solver_output -tmax:8.35 -tout:0.01`. All remain launch-disabled, production-approval-none, Q-N-ungranted, and precision-unaccepted until Root binds actual preparation, typed/native/full836 evidence, and case-level visual authorization.

Only this isolated F3 package is written. No F6, shared registry/runtime, ledger, solver, GenCase, conversion, or array task was run.
