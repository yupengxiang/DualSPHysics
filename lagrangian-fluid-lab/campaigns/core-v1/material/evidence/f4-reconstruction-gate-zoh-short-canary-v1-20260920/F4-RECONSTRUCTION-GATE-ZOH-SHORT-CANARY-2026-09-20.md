# F4 ZOH short continuation canary (2026-09-20)

结论：同一 native004 cell-14、同一 512-seed 全分母和固定 gate 下，causal interval-start velocity ZOH 从 frame 40→41 延伸到 frame 50；该 CPU-only replay 用于验证修复持续性，仍不构成 T2 或完整事件窗资格。

Evidence: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/material/evidence/f4-reconstruction-gate-zoh-short-canary-v1-20260920/f4-reconstruction-gate-zoh-short-canary-v1.json`
Evidence SHA256: `84716e29db57091420e85191de731b11eadb30ac31ab2b88b41a235f57a354a9`

## Fixed contract

- Candidate: `f4_native_velocity_zoh_query_v1` / `F4_tallwall120_material_velocity_zoh_query_v1`
- Source: native cell-14, SHA-256 `91846866c177e4c3036b7ef92c33a4e0bde7d9e8993efb01dde300811b7c096e`
- Window: frame `40→50` (`0.160014986127815`→`0.200007258214058` s)
- Seeds/steps: `512` independent geometric seeds, `2` RK2 substeps
- Fixed reconstruction cap: `0.04698137929009748` m/s; support distance cap `0.03` m
- Unknown denominator: all 512 source seeds; permanent unknown is retained; no survivor renormalization
- Registered event window: `4.34` s; observed `0.2000072582140577` s; right-censor status remains `right_censored_or_unresolved`

## Result

- Candidate first-failure count: `218`; surviving seeds: `294`
- First-failure histogram: `{'42': 128, '43': 41, '44': 12, '45': 10, '46': 5, '47': 5, '48': 9, '49': 2, '50': 6}`
- Unknown fraction max: `0.42578125`; unknown gate pass: `False`
- Common reliable path coverage: `0.57421875`; mass closed: `True`
- Exact replay: `True`; diagnosis replay mismatches: `[]`
- Frame-40→41 ZOH transition has zero new reconstruction/support/distance failures: `True`

The extension preserves the source, support model, thresholds, event definitions, source/destination mass semantics, and full unknown denominator. A short CPU replay cannot supply the missing 4.34 s event window or F3 CDF agreement. Any solver-backed canary requires a separate root review that binds the hashes below; no solver/GPU/queue job was submitted here.
