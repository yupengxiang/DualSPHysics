# F4 tallwall120 T2 admission/acceptance gap audit v5（2026-09-23）

结论：acceptance validator 和逐例 sidecar wiring 已实现；这纠正了旧 v4 gap audit 的过时接口判断。科学资格仍为 `T2_macro=false`、`T2_path=false`、zero credit。

Evidence：`/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/material/evidence/f4-tallwall120-t2-admission-acceptance-gap-audit-20260923-v5.json`

## 当前 acceptance 路径

- JSON validator：`core.material.f4.tallwall120.diagnostic.v1`；validator invocation `6/6`。
- 当前 sidecar：通过 `0`，fail-closed `6`；formal receipt `0`。
- residence/censor 结构验证：`true`；F4 tolerance comparators：`true`。
- 重要区分：validator 可检查 payload 提供的 comparator 字段，但 migration spec 未注册权威 F4 CDF 或 residence 数值容差；这不构成科学 gate 通过。

## 仍未通过的科学门

- 每 source unknown mass 最大值 `1.0`，上限 `0.01`。
- 完整事件窗：`False`；6 个保留案例仍 right-censored/unresolved。
- 33-row overlay 覆盖 `15` 个 CFD cells；material matrix ready=`false`。
- content-addressed tracer generation 实现存在=`true`；但 recovery acceptance/执行授权仍未闭合。

## 阻塞项

1. all six retained F4 cases fail the fixed per-source unknown-mass gate: maximum 1.0 > 0.01
2. all six retained F4 cases are right-censored or unresolved before the required event window completes
3. the migration contract still has no authoritative F4 numerical CDF tolerance; the diagnostic comparator only checks a supplied tolerance field
4. the migration contract provides gravity time but no authoritative residence-distribution tolerance
5. the v2 sidecar preflight invoked the validator for 6 cases; 6 are blocked and 0 formal receipts exist
6. the registered overlay is not ready: 33 rows span 15 CFD cells, with resolution/substep and seed-density material overlays pending
7. the ESS32 full-source candidate remains proposal-only because its candidate-specific root review has authorized_one_cpu_only=false; this does not override the separate user authorization for the supportcap preflight
8. the diagnostic validator is not a T2 qualification collector: it does not close the full material matrix, authoritative tolerance registry, recovery receipt, or formal per-case receipts

本审计仅读取 JSON、源码和报告；未打开 H5/NPZ，未启动 solver/GPU/worker，未变更队列、账本、矩阵、科学分母、阈值或旧证据。

## 输入 SHA-256

- `core_material`：`scripts/core_material.py` — `9e294e64c431c725717caf86eb001dc3a3505a312e279386796b6a472b5ee94e`
- `core_material_acceptance`：`scripts/core_material_acceptance.py` — `b9cb49cacf19590356bda4f32d32ef3d2255b9c97a8afa29a920e5a38bd6c4a7`
- `macro_sidecar_preflight_code`：`scripts/f4_macro_t2_sidecar_preflight_v2.py` — `bcbfe026ed4e4d71294755b1f478b1b530bf8f9862c6df7e9c6ab279fd59133b`
- `tallwall_material_code`：`scripts/f4_tallwall120_material.py` — `dc3c06e5b689eb64b7c3c7ee87b022699cfed19483d38662031570ea24b66f26`
- `tallwall_preflight_code`：`scripts/f4_tallwall120_material_preflight_v1.py` — `872daf5a8f3a5cf1e5cccc55d599c21396b4da3634d6a0ffdefddb335ddbcbd2`
- `migration_spec`：`campaigns/core-v1/material/evidence/f4-resting-pool-migration-spec-2026-09-19.json` — `76dfc5fe035ddcfa374fa09fec5b3f2472199ee58e9e13496f88f4c04d25b562`
- `matrix_review`：`campaigns/core-v1/material/evidence/f4-resting-pool-33-to-15-matrix-review-2026-09-19.json` — `7fd6c5f5c8f42a28a424a3a30e528eef549b6787895c3c9216b0c246d88710ff`
- `macro_sidecar_preflight`：`campaigns/core-v1/material/evidence/f4-macro-t2-sidecar-preflight-v2-20260923.json` — `e098e26cc6db8186789b6b8165b6f6a6686bd374a02f0f5d18b4b59d2608d078`
- `negative_evidence`：`campaigns/core-v1/material/evidence/f4-material-negative-evidence-audit-20260920.json` — `6aa41b16acdf6562a7b40c4e79f1e3ee18b59db080c2fd8ce642d04749bf33dd`
- `source_window_audit`：`campaigns/core-v1/material/evidence/f3-f4-t2-cpu-source-window-audit-v1-20260920.json` — `983e15aae8e1ce4df705590c7b1cc89e27a0445c8152f4a003123392e3aaa279`
- `tallwall_preflight`：`campaigns/core-v1/material/evidence/f4-tallwall120-native-cell14-material-preflight-20260921.json` — `f5e6dc499e19349324799f36a154b5bfc7c6bb9be03b0c0e9df27a4acd7fc9bf`
- `tallwall_trace_result`：`campaigns/core-v1/material/evidence/f4-tallwall120-native-cell14-material-preflight-20260921.trace.json` — `b12a0e4a26a61e226f386776c54b90b6752a668b642b13e2b4f5a704f2c4973c`
- `full_source_contract`：`campaigns/core-v1/material/evidence/f4-tallwall120-native-cell14-f4-ess32-full-source-canary-contract-20260921.json` — `cfb7f20c8e5276d1148f21b32980ae2ef55afdf656924dc72aeddc06631a8f91`
- `root_review`：`campaigns/core-v1/material/evidence/f4-tallwall120-native-cell14-f4-ess32-root-review-20260921.json` — `b6e7e92435179d25cc524e006b53c482259dc22065e30b5297d6ed4975dc7b7a`
- `candidate_contract`：`campaigns/core-v1/material/evidence/f4-tallwall120-native-cell14-candidate-contract-20260921.json` — `566d39c8c32f42859d7f2b1b93ef087dbf6e01d1666bead10d740d9ca2709d6d`
- `admission_contract`：`campaigns/core-v1/material/evidence/f3-f4-t2-admission-root-review-contract-20260921.json` — `04e02868af86d65758fb739ff4630fec658e384b7325bbdf66abd55d60edafac`
- `report_material_preflight`：`reports/F4-TALLWALL120-MATERIAL-PREFLIGHT-2026-09-21.zh-CN.md` — `5cb367d06e2940d4945305f870a6e72c0aabec49ee77de88d4a9b606f5efc5f9`
- `report_full_source_contract`：`reports/F4-TALLWALL120-FULL-SOURCE-CANARY-CONTRACT-2026-09-21.zh-CN.md` — `4902365c6e0695ef1ec3fe4a4e1bc70ef1e971403cca93e51e64e4e64c90cd2e`
- `report_admission_contract`：`reports/F3-F4-T2-ADMISSION-CONTRACT-2026-09-21.zh-CN.md` — `91392c03c66b2c0674c91c4997409dd3497ac157111b29b399eeb8da4d163952`
- `report_root_cause`：`reports/F4-TALLWALL120-MATERIAL-ROOT-CAUSE-AUDIT-2026-09-21.zh-CN.md` — `b96922076db10d43c023a5875f83ef4a42531d82a10654f49ce289305063e986`
- `macro_sidecar_preflight_v1_code`：`scripts/f4_macro_t2_sidecar_preflight_v1.py` — `54dd170ca74be0160c70f2667779ebaeacc884fe614aa9927128167a77b66c0b`
- `macro_sidecar_preflight_v1_evidence`：`campaigns/core-v1/material/evidence/f4-macro-t2-sidecar-preflight-20260920.json` — `636b212081852921c209fe4b4124a99f64eac975c67b054b2fa2f48ab1172cb8`
- `gap_audit_implementation`：`scripts/f4_tallwall120_t2_admission_acceptance_gap_audit_v4.py` — `6a02c77127f21c09e8f876e724b3c5f0e5103f3236546e207df8d0bae5f8746e`
