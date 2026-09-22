# F4 reconstruction calibration diagnosis (2026-09-19)

Qualification claim: none. The unknown budget remains 1%; support and reconstruction gates are unchanged.

## 32-row v1 result

| group | rows | unknown / queries | false alarms | false safe | true error over gate | gate failure totals |
|---|---:|---:|---:|---:|---:|---|
| source (q=.5,1 × 4 fields) | 8 | 128 / 4096 = 3.125% per row | 8 rows | 0 | 0 | ESS 128; rank 0; anisotropy 0; reconstruction 0 |
| destination/interface/closed wall | 24 | 0 / 7936 | 0 | 0 | 0 | all zero |

Every source failure is an ESS-only false alarm. True analytic error stays below the fixed 0.0469813793 m/s cap and no sample is false safe; all rows close mass.

The same 16 source locations fail at q=.5 and q=1.0. They have 96 visible neighbours, 24 retained neighbours, rank 3, anisotropy 0.4638–0.5997, support distance 0.00242052 m, and ESS 3.52067 or 3.94615. A fixed k=32 check on that geometry gives 512/512 reliable and minimum ESS 4.01309137.

## Held-out v2 validation

| candidate | held-out source rows | source unknown budget | false safe | result |
|---|---:|---:|---:|---|
| baseline24 | 6 | fails: 3.125% each | 0 | reproduces ESS false alarms |
| f4_ess32_v2 | 6 | passes: 0% each | 0 | supports H1 |
| f4_affine_bound_v2 | 6 | fails: 3.125% each | 0 | estimator calibration only; does not repair ESS |

The independent v2 set uses held-out q=.25/.75 and new constant_offset, cubic_shear, and vortex_interface fields. On held-out vortex interface queries, true p95 is 0.0139702 m/s; baseline residual p95 is 0.00127736 m/s and affine-bound p95 is 0.00933418 m/s. This supports H2 as an estimator calibration canary while retaining the same gate.

## Prepared real canaries

Both candidates bind the completed native .002 s, .3 s center q=.5 trajectory (151 frames), use 512 independent seeds and four tracer substeps, and remain CPU-only read-only overlays. They retain the 1% unknown gate, mass closure, checkpoint/resume, and right-censored event policy.

- `f4-material-repair-ess32-v2-canary-s0p3-center-q0p5.json`: fixed support-cap candidate.
- `f4-material-repair-affine-bound-v2-canary-s0p3-center-q0p5.json`: fixed affine query-bias estimator candidate.

## Provenance

Diagnosis JSON: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/material/evidence/f4-reconstruction-calibration-diagnosis-20260919.json`

- v1/v2 receipts, source and implementation hashes are recorded in the JSON artifact.
- v1 and v2 manufactured runs used CPU only; GPU, ledger, and scheduler slots were not used; real repair canaries are prepared only.
