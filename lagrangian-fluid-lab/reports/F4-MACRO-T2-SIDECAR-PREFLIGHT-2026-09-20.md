# F4 Macro-T2 Sidecar Preflight (2026-09-20)

结论：当前没有可接受的、独立于 F3 新原生 cadence 的 F4 宏观 T2 闭合路径。
本次是只读 CPU preflight；`T2_macro=false`、`T2_path=false`，没有把 sidecar 或 right-censored canary 当作资格证据。

Evidence: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/material/evidence/f4-macro-t2-sidecar-preflight-20260920.json`
Evidence SHA256: `636b212081852921c209fe4b4124a99f64eac975c67b054b2fa2f48ab1172cb8`

## 固定门值与 retained canaries

| canary | unknown max | common reliable coverage | mass closed | event window |
|---|---:|---:|---|---|
| `f4_real_material_baseline_s2` | 0.84765625 | 0.15234375 | true | right_censored_or_unresolved |
| `f4_native_dense_pair_s2_s4` | 0.896484375 | 0.103515625 | true | right_censored_or_unresolved |
| `f4_repair_canaries_ess32_and_affine_bound:f4_ess32_v2` | 0.923828125 | 0.076171875 | true | right_censored_or_unresolved |
| `f4_repair_canaries_ess32_and_affine_bound:f4_affine_bound_v2` | 0.955078125 | 0.044921875 | true | right_censored_or_unresolved |
| `f4_tallwall120_short_canary` | 1 | 0 | true | right_censored_or_unresolved |

The fixed unknown limit is `0.01`. All retained material rows fail it; mass closure alone does not qualify an event result.

## Sidecar/source status

The native004 source has a hash-bound exact-stride (every fifth row) view with no interpolation and matching terminal lineage. The audit also records that this view is not an independent CFD solve, the material reliability status is `uncalibrated`, and the qualification claim is `none`. It is usable for cadence/source provenance only.

The retained native and stride terminal diagnosis places the first failure in the reconstruction gate (native interval `[0.1600149861278153, 0.1640080936314531]` s; stride interval `[0.1600149861278153, 0.1800111221709365]` s). Cadence alone does not resolve it, while support distance/wall is not the dominant failure.

## Matrix status

The 33-row template has `4` exact cadence rows unavailable, `24` resolution overlays pending, and `5` high-seed overlays pending. The static 15-cell CFD evaluator contract is valid but `matrix_complete=false`; source-cell availability is not material T2 evidence.

## Smallest executable repair path

1. Run one fixed-seed, one-source-cell canary only across the native first-loss interval (~0.1600–0.1640 s), with the existing fixed reconstruction cap and unknown denominator.
2. Require the corrected implementation to pass the fixed reconstruction gate at that interval while preserving source/destination mass closure and failure-event semantics.
3. Only after that canary passes, resume one full 4.34 s F4 event window (extend to 8.68 s only under the registered right-censor policy) and require terminal unknown, CDF, residence, return, and coverage outputs.
4. Then produce the missing exact cadence sources and the registered 33-row material overlays; a sidecar alone cannot substitute for these products.

Thresholds, source/destination mass semantics, event-window semantics, historical scores, registry, and ledger remain unchanged.

## Evidence inputs

- `campaigns/core-v1/material/evidence/f4-material-negative-evidence-audit-20260920.json` — `6aa41b16acdf6562a7b40c4e79f1e3ee18b59db080c2fd8ce642d04749bf33dd`
- `campaigns/core-v1/material/evidence/f4-native004-cadence-terminal-diagnosis-v1/cadence-terminal-diagnosis-v2.json` — `f139ce0f6d88702db3d0ef910608f79ea6eab6eb41912bd91af144316e65f967`
- `campaigns/core-v1/material/evidence/f4-tallwall120-native004-cadence-source-audit-v1.json` — `9cbad0aea665c886e8e9b51d4c540bf42ca7f1e521ade291e6482cda2b4c5298`
- `campaigns/core-v1/material/evidence/f4-resting-pool-33-to-15-matrix-review-2026-09-19.json` — `7fd6c5f5c8f42a28a424a3a30e528eef549b6787895c3c9216b0c246d88710ff`
- `campaigns/core-v1/cfd/f4-tallwall120-qualification-evaluator-v2.json` — `dc6ebde73388ab69d2eb2ba5df8cd52f511f378dc2655e68c17a356547a8bbfe`
- `scripts/f4_tallwall_qualification_evaluator_v2.py` — `ee2673cda352558884177c2bb10c7c57d92589de5645c5ffebe215007c5b6eb8`

The detailed machine-readable record is the evidence JSON above; its execution constraints and resource account explicitly record that no long task or active H5 read was started.
