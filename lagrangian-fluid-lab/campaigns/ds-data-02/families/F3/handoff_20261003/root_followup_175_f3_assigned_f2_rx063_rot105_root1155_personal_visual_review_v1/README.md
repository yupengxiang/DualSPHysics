# Fresh175 F3-assigned handoff — F2 RX063/ROT105 personal visual review

This package records a personal image review of the completed Root1155 render for F2 case `F2_STAGE1_FIRST48_EXPANSION_RX063_RY014_FILL080_ROT105_DP010_SPATIAL_REFERENCE_SAVE010` / physical case `F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX063_RY014_FILL080_ROT105`. The scientific family is F2; this handoff is stored in the assigned F3 worktree.

I viewed all 17 published chronological contact sheets (`all_frames_000.png` through `all_frames_016.png`) and the nine requested keyframes (`frame_0000.png`, `0050`, `0100`, `0150`, `0200`, `0250`, `0300`, `0350`, `0400`) with `view_image`. The producer SHA256 values in the PNG evidence file are copied from the Root-owned `render-publish-receipt.json`; this package does not hash PNGs or scientific payloads.

The Root1155 render is terminal and atomically published:

- render root: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_STAGE1_FIRST48_EXPANSION_RX063_RY014_FILL080_ROT105_DP010_SPATIAL_REFERENCE_SAVE010/root-stage1-f2-rx063-rot105-actual1145-full401-116-023-nvme-hard2gib-root1155/render`
- execution receipt: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_STAGE1_FIRST48_EXPANSION_RX063_RY014_FILL080_ROT105_DP010_SPATIAL_REFERENCE_SAVE010/root-stage1-f2-rx063-rot105-actual1145-full401-116-023-nvme-hard2gib-root1155/execution-receipt.json`
- report: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_STAGE1_FIRST48_EXPANSION_RX063_RY014_FILL080_ROT105_DP010_SPATIAL_REFERENCE_SAVE010/root-stage1-f2-rx063-rot105-actual1145-full401-116-023-nvme-hard2gib-root1155/render/paraview-full-animation-report.json`
- publish receipt: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_STAGE1_FIRST48_EXPANSION_RX063_RY014_FILL080_ROT105_DP010_SPATIAL_REFERENCE_SAVE010/root-stage1-f2-rx063-rot105-actual1145-full401-116-023-nvme-hard2gib-root1155/render/render-publish-receipt.json`
- Root1346 QI proof: `/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_F2_RX063ROT105_actual1155_full401_UID_N3_times_nativecanonical_typedlegacy_three_fluid_omissions_actual_plan_namespaces_previsual_QI_1346/actual1155-full401-own-QI-UID-N3-native-typed-role-three-fluid-omissions-previsual-proof.json` (SHA256 `ce3d6b14fbf34d6a682c374af5293f188d53daf4440c6426daadb32ab5484689`)

The sequence is visually populated and readable. It begins with a compact fluid body, develops impact and splash, and then shows lateral spreading and a thin floor-level sheet around the fixed geometry. Isolated blue points are visible in several contact/key views. I observed no blank sheet, missing tile, visibly truncated output, abrupt render cutoff, or whole-render display corruption. These are image-level observations; they do not establish strict containment, absence of penetration, numerical precision, or physical validity.

The Root1346 lifecycle evidence remains authoritative: initial fluid count 21114, terminal fluid count 21111, three final missing fluid UIDs, first missing frame 165, and 652 cumulative particle-frame omissions with cause/location unknown. The package preserves this evidence and does not reinterpret it from the images. Native canonical scope (`5fd9915c…99987`) and typed/XMF legacy scope (`0cbdc38…a4d`) remain separate. Native source-plan condition is absent while native physical-plan is present; both XMF plan fields are absent.

This package records `case_credit: 0`, `Q-N: false`, `Q-E: false`, and numerical precision/production qualification as unaccepted. Root owns final adoption and global counting. No shared state, ledger, request, source, or scientific output was modified.

Validate with:

```text
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_fresh175.py
```
