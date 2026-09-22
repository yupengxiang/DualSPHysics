# F4 Reconstruction-Gate Interval Repair Canary (2026-09-20)

结论：单一 temporal support-query repair 在固定 native004 cell14 frame 40→41 bounded interval 通过；这不是 T2 资格，也不是完整 event-window 结果。

Evidence: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/material/evidence/f4-reconstruction-gate-interval-repair-canary-v1/f4-reconstruction-gate-interval-repair-canary-v1.json`
Evidence SHA256: `556f8ffc8b81914352161c0e20529b254a560ed5da94c18c9dd68766ebea7d75`

## Candidate and fixed contract

- Candidate: `f4_native_velocity_zoh_query_v1` / `F4_tallwall120_material_velocity_zoh_query_v1`
- Temporal query: `linear_native_position_interval_start_velocity_zoh`
- Native source: `40→41`, q=`0.5`, dp=`0.0075`, seeds=`512`, substeps=`2`
- Support: baseline24 k=`24`, fixed cap=`0.04698137929009748`, distance cap=`0.03` m
- Unknown denominator: all 512 independent source seeds; no unknown removal or renormalization

## Pre-registered checks

- Retained baseline negative evidence: `128/512` failures, replay mismatches `[]`
- Candidate exact replay: `True`; mismatches `[]`
- Candidate diagnosis replay mismatches: `[]`

## Result

- Candidate first-failure seeds: `0`; surviving seeds: `512`
- Candidate unknown fraction max: `0.0`; mass closed: `True`
- Zero new g0/g1 reconstruction failures: `True`
- Reliable path coverage: `1.0`

The candidate changes only the temporal support query: positions remain linearly interpolated between the two native frames, while velocity is held at the interval-start native value. The fixed support cap, ESS/rank/anisotropy gates, reconstruction cap, distance cap, event semantics, and full unknown denominator remain bound to baseline values.

The bounded result supports this implementation hypothesis for the retained interval. It does not establish physical material fidelity, a full event window, matrix coverage, or T2 qualification. No solver, GPU, queue, registry, ledger, or full-horizon run was started.
