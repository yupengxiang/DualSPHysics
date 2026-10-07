# F5-assigned personal visual review: F3 P1200/AY0390 Root1101

This source-only handoff records the completed, atomically published F3 case `F3_STAGE1_DP006_P1200_AY0390` (`F3_TWOAXIS_P1200_AY0390_STAGE1_FIRST48_PITCH_VARIANT`), stored in the F5 worktree because this review was assigned to `f5_bed_recovery`. The producer receipt reports 836 saved frames, 179208 particles (111708 fixed, 67500 fluid, moving/floating 0), 3D output, and the exact saved interval 0–8.350008849684302 s.

I personally viewed all 35 published contact sheets (`all_frames_000.png` through `all_frames_034.png`) and all 9 published keyframes at indices `[0, 104, 208, 312, 417, 521, 626, 730, 835]`. Review completion UTC is `2026-10-07T12:00:20.848637Z`. The early, middle, and late sequence is continuous: a low initial surface response develops into localized crests and troughs, then evolves through repeated waves and a late right-side rise. No gross explosion, abrupt termination, broad visible escape, or whole-domain visual failure was seen. Localized edge/crest sparsity is disclosed.

This is a first-stage visual screen. It does not certify large runup or inundation, strict containment, sub-DP penetration absence, or numerical precision. The producer render report marks numerical precision as not accepted; the exact-lattice negative and no-threshold-relaxation rule remain retained. Q-N, Q-E, and independent case credit remain zero.

The physical scope is `6785314266d78e2247839c32a986838025663f371a65081ce5d42dc38eb80cac`. Native condition and physical plan fields are genuinely absent/null. XMF has its own present condition-plan value `7560a18fa29742681ee567b06567ed4052da8ceb138b601e94b5223df22660f5` and no physical-plan field; it is retained as a separate namespace and is not promoted to the native canonical condition. No SourceDef or typed legacy value is invented.

Only published PNG derivatives were opened for the visual review. PNG byte sizes and SHA values are producer attestations copied from `render-publish-receipt.json`; this agent did not compute PNG hashes. No H5, BI4, CSV, DAT, VTK, or other raw scientific payload was read, hashed, copied, or transformed; no job or shared state was started or modified.

Run the metadata-only validator:

    python3 scripts/validate_fresh229.py
