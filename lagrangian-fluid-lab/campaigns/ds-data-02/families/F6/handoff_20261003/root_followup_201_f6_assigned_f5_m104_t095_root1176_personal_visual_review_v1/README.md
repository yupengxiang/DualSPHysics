# Fresh201 F5 M104/T095 personal visual review

- Reviewer: `/root/f6_endpoint_initial_qa`
- Model: `gpt-5.6-luna/max`
- Review completed UTC: `2026-10-07T10:47:55.810936Z`
- Assigned family: `F6`; physical family: `F5`
- Case: `F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M104_T095_NEXT34`
- Physical case: `F5_COMPACT_RUNUP_RECOVERY_C082S1_M104_T095`
- Attempt: `root-stage1-f5-m104_t095-actual1171-bed0-full801-original116023-frozen-progress-root1176`

Root1176 is independently terminal `completed` with return code 0 and the output is atomically published. Root QI1423 is a separate completed metadata proof; it is referenced here and is not replaced by this personal image review. The producer reports 801 frames and the actual time window `[0, 16.00012550006781] s`; `16.0 s` is retained only as the nominal window.

I personally opened every published contact sheet (`all_frames_000.png` through `all_frames_033.png`) and the nine published key frames `0,100,200,300,400,500,600,700,800` with `view_image`. The full sequence shows a blue fluid runup/flow profile along the grey sloped channel, with a visible orange boundary feature. The fluid remains visually inside the rendered domain in the inspected views, and the sequence has no blank tail, obvious camera clipping, severe wall-through geometry, or explosive scatter. No floating body is visible, consistent with the producer count of zero floating particles. Later changes are subtle at the displayed scale, so this review does not infer particle-level or numerical behavior from pixels.

Canonical native condition, typed legacy scope, XMF physical-plan namespace, bed SourceDef XML, and source-plan JSON are listed separately in `metadata/visual-review.json`. The native/XMF condition-plan field is absent/null while their physical-plan field carries the canonical role; the bed SourceDef remains a distinct XML role. The producer's initial-QA precision negative, no strict-containment/sub-DP/numerical certification, `Q-N=false`, `Q-E=false`, and `case_credit=0` are preserved.

PNG entries record path, file stat, and the producer-attested SHA from `render-publish-receipt.json`; this package does not independently hash PNGs. No H5, BI4, CSV, DAT, or VTK scientific payload was read, copied, or hashed, and no scientific job or shared state was changed.

Run the read-only validator with:

```text
python3 scripts/validate_fresh201.py
```
