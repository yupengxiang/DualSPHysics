# F4 Reconstruction-Gate Interval Canary (2026-09-20)

结论：bounded baseline replay 成功复现实现层 reconstruction failure；没有执行 repair，也没有产生 T2 资格。

Evidence: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/material/evidence/f4-reconstruction-gate-interval-canary-v1/f4-reconstruction-gate-interval-canary-v1.json`
Evidence SHA256: `7d0a3bc520e6498ff9de26b99d458fe8f11b651cb2e9ca7e5e70f1d6398f7c97`

## Canary contract

- Source: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f4-tallwall120-archives-v2/f4-tallwall120-qualification-cell-14/product/trajectory.h5`
- Source SHA256: `91846866c177e4c3036b7ef92c33a4e0bde7d9e8993efb01dde300811b7c096e`
- Fixed seeds/q/dp/substeps: `512` / `0.5` / `0.0075` / `2`
- Saved interval: frame `40→41`, `0.160014986128→0.164008093631` s
- Unknown denominator: all 512 source seeds; fixed unknown gate `0.01`
- Reconstruction/support thresholds and event semantics: unchanged

## Observed output

The runner committed frame `41` at `0.164008093631` s with status `partial`. It is mass-closed, but the interval output is right-censored and `unknown_fraction_max=0.25`; `T2_macro=false` and `T2_path=false`.

The independent diagnosis found `128` first-failure seeds and `384` surviving seeds. Frame histogram: `{'41': 128}`. Replay mismatches: `[]`.

At the frame-40→41 transition, the component accounting was:

| substep | new failures | g0 gate failures | g1 gate failures | distance failures |
|---:|---:|---:|---:|---:|
| 0 | 125 | 0 | 125 | 0 |
| 1 | 3 | 0 | 3 | 0 |

The failure is therefore reproducible in the existing baseline implementation at the registered interval. The canary does not establish the deeper physical origin and does not validate a repair.

## Next bounded repair test

A separately versioned implementation candidate must rerun this exact frame-40→41, 512-seed interval with the same cap, support gates, full-mass unknown denominator, source geometry, and event semantics. It must produce zero new reconstruction failures and exact replay agreement before any full event horizon is considered. Passing this canary still does not grant T2.

## Resources and constraints

- Wrapper wall time: `57.161` s
- Trace runtime/RSS: `16.815` s / `654072` KiB
- Diagnosis process RSS: `670204` KiB
- Trace output: `3900b04123667712d8806b567034535c93925d831c5c7999f599617833dba3ad`
- Diagnosis output: `a84f791abf18bbd1886f8ceb2c07ab70a5d2bf25f11303ae87b6f98bf0f523e7`
- No solver, GPU, queue, registry, ledger, full horizon, or 33-row matrix was started.
