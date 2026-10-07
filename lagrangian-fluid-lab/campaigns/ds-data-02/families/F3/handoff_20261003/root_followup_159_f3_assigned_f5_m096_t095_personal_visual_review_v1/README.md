# Fresh159 F3-assigned handoff — F5 M096/T095 personal visual review

This F3 worktree package records my personal visual inspection of the actual F5 case `F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M096_T095_NEXT34` / `F5_COMPACT_RUNUP_RECOVERY_C082S1_M096_T095`. The physical data family is F5; only the handoff package is stored in the F3 worktree. I viewed all 34 published chronological contact sheets and the nine requested keyframes (0, 100, 200, 300, 400, 500, 600, 700, 800) with `view_image`.

The published render is the Root1163 atomic output:

- render root: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M096_T095_NEXT34/root-stage1-f5-m096_t095-actual1140-bed0-full801-original116023-frozen-progress-root1163/render`
- execution receipt: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M096_T095_NEXT34/root-stage1-f5-m096_t095-actual1140-bed0-full801-original116023-frozen-progress-root1163/execution-receipt.json`
- report: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M096_T095_NEXT34/root-stage1-f5-m096_t095-actual1140-bed0-full801-original116023-frozen-progress-root1163/render/paraview-full-animation-report.json`
- publish receipt: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M096_T095_NEXT34/root-stage1-f5-m096_t095-actual1140-bed0-full801-original116023-frozen-progress-root1163/render/render-publish-receipt.json`
- existing independent QI proof: `/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_F5_actual1163_full801_complete_UID_N3_bed_canonical_plan_vs_SourceDef_previsual_QI_1257/actual1163-full801-independent-QI-UID-N3-bed-scope-previsual-proof.json`

The visual review found a continuous, readable two-view 3D sequence across the full contact-sheet set. The blue fluid body, gray fixed geometry, and orange boundary/marker remained visually separated; no blank, missing, or visibly truncated contact sheet or specified keyframe was observed. The review records image-level observations only. The report's precision status remains `not accepted`; historical A/B and initial-placement precision negatives remain preserved, zero bed bins are not interpreted as proof of absent sub-DP content, and Q-N/Q-E, production qualification, and case credit remain unset.

Scope roles remain separate: native canonical owner condition, actual converter/typed legacy scope, SourceDef digest, bed SourceDef role, and source-plan fields are not substituted for one another. This package does not alter source or science files and sets `case_credit: 0` / `independent_case_increment: 0`; Root owns final adoption and global counting.

The review read JSON metadata and published PNGs only. It did not open, decode, hash, copy, or modify H5/BI4/CSV/DAT/VTK payloads, start/restart/stop scientific jobs, or modify shared state.

Validate with:

```text
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_fresh159.py
```
