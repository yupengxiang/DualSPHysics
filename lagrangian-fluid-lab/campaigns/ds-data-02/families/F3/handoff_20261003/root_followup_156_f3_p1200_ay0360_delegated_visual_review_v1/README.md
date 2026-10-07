# Fresh156 F3 personal visual review — P1200 / AY0360

This F3-only handoff records my personal review of the terminal Root1100 published renderer for `F3_STAGE1_DP006_P1200_AY0360` / `F3_TWOAXIS_P1200_AY0360_STAGE1_FIRST48_PITCH_VARIANT`. I used `view_image` on all 35 chronological contact sheets (`all_frames_000.png` through `all_frames_034.png`) and all nine event keyframes (0, 104, 208, 312, 417, 521, 626, 730, 835). PNG paths, byte sizes, and PNG-only hashes are in `metadata/png-hashes/F3_STAGE1_DP006_P1200_AY0360.json`; the metadata chain is in `metadata/chain-audit/F3_STAGE1_DP006_P1200_AY0360.json`.

The actual completed metadata is recorded from these paths:

- Root1100 execution receipt: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_STAGE1_DP006_P1200_AY0360/root-stage1-f3-p1200-ay0360-actual1075-full836-116-023-nvme-hard2gib-root1100/execution-receipt.json`
- Root1100 render report: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_STAGE1_DP006_P1200_AY0360/root-stage1-f3-p1200-ay0360-actual1075-full836-116-023-nvme-hard2gib-root1100/render/paraview-full-animation-report.json`
- Root1100 atomic publish receipt: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_STAGE1_DP006_P1200_AY0360/root-stage1-f3-p1200-ay0360-actual1075-full836-116-023-nvme-hard2gib-root1100/render/render-publish-receipt.json`
- integration controller result: `/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_F3_P1200_AY0360_actual1075_XMF0_full836_original116_023_hard2GiB_shared2_render_1100/controller-result.json`
- upstream Root1075 XMF manifest: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_STAGE1_DP006_P1200_AY0360/root-stage1-f3-p1200-ay0360-actual978-full836-original104-XMF-root1075/xdmf/manifest.json`
- Root1248 completed-QI proof: `/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_F3_P1200_AY0360_actual1100_full836_native_UID_N3_time_scope_complete_QI_previsual_checkpoint_1248/actual1100-full836-completed-QI-UID-N3-native-scope-previsual-proof.json`

The render receipt/controller/report/publish all describe a completed/0 run, 836 source/render frames, and an atomic published output. The review found stable two-view 3-D framing and a continuous, legible sequence across the full contact set and event frames. Late right-edge cresting and small detached-looking edge features are retained as observations only; no source exclusion or physical classification was changed.

Native, typed/converter, canonical-source, SourceDef/source-plan, and legacy roles remain separate. The older 801 envelope versus actual 836 wrapper distinction is preserved; 801 is not treated as the rendered/native frame count. Precision, Q-N/Q-E, production qualification, and global case credit remain unset; this package records `case_credit: 0` and `independent_case_increment: 0`, with Root retaining deduplication and credit ownership.

This review read JSON metadata and PNG evidence only. It did not open, decode, copy, or hash H5/BI4/CSV/DAT/VTK payloads, start/restart/stop scientific jobs, or modify shared state. The exact stale fresh155 path assumptions (`render/controller-result.json`, `render/manifest.json`) are explicitly corrected in the provenance sidecar; the actual controller and XMF manifest paths above are used.

Validate with:

```text
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_fresh156.py
```
