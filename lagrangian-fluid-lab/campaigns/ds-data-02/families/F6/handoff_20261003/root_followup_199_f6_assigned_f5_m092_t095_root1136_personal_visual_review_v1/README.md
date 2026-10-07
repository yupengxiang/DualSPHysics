# Fresh199 F5 M092/T095 delegated visual review

- Reviewer: `/root/f6_endpoint_initial_qa`
- Review UTC: `2026-10-07T10:07:52.520895027Z`
- Assigned family: F6; physical family: F5
- Case: `F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M092_T095_NEXT34`
- Physical case: `F5_COMPACT_RUNUP_RECOVERY_C082S1_M092_T095`
- Actual render: completed/0 with atomic publish; main own-QI proof: `/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_F5_M092T095_actual1136_full801_complete_UID_N3_bed_actual_native_XMF_SourceDef_namespace_previsual_QI_1412/actual1136-full801-independent-QI-UID-N3-bed-scope-previsual-proof.json`
- Main proof SHA256: `38166ff90e8e09af3619de83264a5cadd0e8789b7ec8554ee5664499c58d3643`

I used `view_image` on all 34 published contact sheets (`all_frames_000.png` through `all_frames_033.png`) and all 9 requested key frames (`0,100,200,300,400,500,600,700,800`). The rendered sequence shows the blue fluid runup/profile evolving along the inclined bed within the grey channel. The full sequence keeps the same framing and visible geometry; I saw no black/blank products, obvious camera clipping, severe visible wall penetration, explosive scatter, or premature visual termination. The visual decision is `visual-approved-by-delegated-agent` for main integration only, with `case_credit=0`.

Producer metadata remains authoritative for 801 frames, 194427 particles, fixed=158559, moving=4210, floating=0, fluid=31658, and the actual 0–16.00014188025401 s window. The initial-QA precision negative, diagnostic bed depth bins, sub-DP uncertainty, and all scope-role distinctions are retained. Native canonical `5adae02901dfdd5e70f7de3b62694c5f7f62f5d76ade14b0a8688ae9c2d0d273`, typed legacy `04b4720db5456a4e01f5c5cbc3af67d2d1cedb15d784689ed7175c060a959fa8`, native/XMF physical plan `5adae02901dfdd5e70f7de3b62694c5f7f62f5d76ade14b0a8688ae9c2d0d273`, and bed SourceDef `6a56496593d43b8ca6f1910c3a934202c493db1a071e286f28c10488f38adeb9` are separate roles.

The package contains only JSON/README/Python metadata. It records image paths and file sizes but does not copy or hash PNGs and does not read or hash H5/BI4/CSV/DAT/VTK scientific payloads.

Validate from this directory with:

```sh
python3 scripts/validate_fresh199.py
```
