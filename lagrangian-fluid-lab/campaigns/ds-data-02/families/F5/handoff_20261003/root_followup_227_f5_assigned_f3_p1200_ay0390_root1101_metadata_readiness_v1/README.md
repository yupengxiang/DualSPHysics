# Fresh227 F3 original1101 metadata readiness handoff

This source-only package is stored in the F5 worktree for the delegated handoff of scientific family F3 case `F3_STAGE1_DP006_P1200_AY0390` / physical case `F3_TWOAXIS_P1200_AY0390_STAGE1_FIRST48_PITCH_VARIANT`. It records the real completed upstream GenCase, parent initial-QA, native, typed, and XMF metadata chain and the current original1101 full836 render state.

At package creation the original1101 execution receipt is still `status=running`, with no terminal return code, atomic publish, or Root1427 own-QI proof. The package therefore remains a readiness/pending handoff. It does not convert a live controller observation into a completed render. The main process must execute the durable entry only after a real completed/0 receipt and atomic publication.

The actual plan namespaces are preserved from the producer metadata: native condition and physical plan fields are genuinely absent; XMF `source_plan_condition_sha256` is present as `7560a18fa29742681ee567b06567ed4052da8ceb138b601e94b5223df22660f5` and XMF physical-plan is absent. These values are not inferred from the canonical physical condition `6785314266d78e2247839c32a986838025663f371a65081ce5d42dc38eb80cac`.

Completed upstream metadata includes the genuine parent-QA and GenCase preparation refs, native/typed/XMF receipts, the actual typed report, the actual XMF manifest and XML, the generated case XML, and the owner metadata. The direct completed upstream ParaView input is:

`/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_STAGE1_DP006_P1200_AY0390/root-stage1-f3-p1200-ay0390-actual978-full836-original104-XMF-root1075/xdmf/case.xmf`

Expected original1101 scope is 836 frames / 179208 particles / 3-D over 0–8.350008849684302 s, with 35 contacts and keyframes `[0, 104, 208, 312, 417, 521, 626, 730, 835]`. Future render report, publish receipt, and Root1427 own-QI hashes remain null until a producer creates them.

Run the metadata-only validator from the worktree root:

```text
python3 lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_227_f5_assigned_f3_p1200_ay0390_root1101_metadata_readiness_v1/scripts/validate_fresh227.py
```

Fresh227 read only JSON/XML/Python metadata and source-role information. It did not read, copy, or hash H5/BI4/CSV/DAT/VTK/science payloads or PNGs; it did not start or restart a job, mutate shared state, claim case credit, or perform personal visual review.
