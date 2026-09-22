# F4 tallwall120 宏观 T2 材料 admission/acceptance gap audit（2026-09-21）

结论：当前 `T2_macro=false`、`T2_path=false`，材料资格仍被科学门、逐例侧车闭合、矩阵覆盖和 acceptance 接口缺口共同阻塞。本次只读检查没有打开 terminal H5，也没有启动 solver/GPU/queue。

机器回执：`/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/material/evidence/f4-tallwall120-t2-admission-acceptance-gap-audit-20260923-v4.json`；SHA-256：`e547429d9b3af466992e0778ceca749715844bc6b9e1df96e40fab38c33c20ea`。

## 固定门与当前证据

| 门 | 注册计划 | 当前审计结果 |
|---|---:|---|
| 每 source 未知质量 | `<= 0.01` | 最大 `1.0`，6/6 case 不通过 |
| F3 CDF sup（仅 F3 命名） | `<= 0.02` | preflight 的 `0.02` 没有被登记为 F4 CDF 容差 |
| F4 事件窗 | `4.34` s，必要时一次延长至 `8.68` s | 6/6 case right-censored/unresolved |
| residence | gravity-time `0.3497487083913345` s；输出 residence CDF | 只有 `5/6` 结果侧车含完整字段，无 acceptance 容差 |
| 事件容差 | endpoint `1e-08` m；saved-chord crossings `0` | migration spec 已登记，acceptance/preflight 未执行 |

质量闭合在保留的六个 case 中为 true，但质量闭合不能抵销未知质量和 right-censor。所有几何 seed 继续留在 source 分母中。

## 逐例侧车与恢复

| case | result 侧车 | CDF/residence | event 字段 | checkpoint integrity | generation |
|---|---|---|---|---|---|
| `f4_real_material_baseline_s2` | true | true | true | true | false |
| `f4_native_dense_pair_s2_s4` | true | true | true | true | false |
| `f4_native_dense_pair_s2_s4` | true | true | true | true | false |
| `f4_repair_canaries_ess32_and_affine_bound` | true | true | true | true | false |
| `f4_repair_canaries_ess32_and_affine_bound` | true | true | true | true | false |
| `f4_tallwall120_short_canary` | true | false | false | true | true |

source-window audit 记录了 `6` 个 case 和 `6` 个 checkpoint hash pass；但只有 `0` 个结果带 `core.material.acceptance.v1` 回执。checkpoint 可恢复性证据不等于材料 acceptance。

full-source contract 要求 frame `0..1085`、frame-40 recovery、每 native frame checkpoint 和 content-addressed append-only generation。当前 root review 的 `authorized_one_cpu_only=false`，候选 output stem 仍为空；这次 audit 不会执行它。

## 接口缺口

- `core_material.py` 已产生 F4 `residence_cdf` 和 event-window 摘要，但没有 tallwall120 schema 或 content-addressed generation checkpoint；版本化 tallwall tracer 自己具备 schema/checkpoint-v2/generation。
- `core_material_acceptance.py` 的 per-source unknown 与通用 CDF difference 检查存在，且已有 checkpoint-v2 validator surface；但尚未形成完整 tallwall120 schema、residence CDF、F4 event tolerance、generation history 或逐矩阵 case acceptance。
- `f4_macro_t2_sidecar_preflight_v1.py` 保留 unknown/event/matrix negative 状态和 sidecar provenance，但没有调用 `audit_material_h5`，也没有逐例 residence/CDF、事件容差或 recovery receipt 汇总。

## 仍阻塞宏观 T2 的条件

1. all six retained F4 cases fail the fixed per-source unknown-mass gate: maximum 1.0 > 0.01
2. all six retained F4 cases are right-censored or unresolved before the required event window completes
3. the migration spec declares contact/upward/return/residence CDF outputs, but no F4 CDF numerical tolerance is registered; the preflight's 0.02 value is explicitly an F3 CDF limit
4. residence CDF and right-censored residence are emitted by the tracer result, but core_material_acceptance has no residence acceptance gate or tolerance
5. closed-wall endpoint and saved-chord event tolerances are registered in the migration spec but are not enforced by core_material_acceptance or the macro sidecar preflight
6. the six retained case rows have checkpoint integrity evidence, but only 5 case result sidecars expose complete CDF/residence fields and 0 carry a formal acceptance receipt
7. the registered overlay is not ready: 33 rows are planned over 15 CFD cells, with 24 resolution/substep and 5 seed-density overlays pending
8. the ESS32 full-source candidate is proposal-only and root review has authorized_one_cpu_only=false; its counterfactual first-loss cohort has zero survivors
9. core_material_acceptance contains the checkpoint-v2 validator surface, but does not yet expose a complete shared tallwall120 acceptance route (schema, residence/event tolerances, generation, per-case, and matrix gates)

本回执只新增一份 JSON 和中文报告；registry、ledger、T1/T2 分母、阈值和旧 evidence 均未修改。

## 输入哈希

- `core_material`：`scripts/core_material.py` — `9e294e64c431c725717caf86eb001dc3a3505a312e279386796b6a472b5ee94e`
- `core_material_acceptance`：`scripts/core_material_acceptance.py` — `b9cb49cacf19590356bda4f32d32ef3d2255b9c97a8afa29a920e5a38bd6c4a7`
- `macro_sidecar_preflight_code`：`scripts/f4_macro_t2_sidecar_preflight_v1.py` — `54dd170ca74be0160c70f2667779ebaeacc884fe614aa9927128167a77b66c0b`
- `tallwall_material_code`：`scripts/f4_tallwall120_material.py` — `22881496c7fd961c8ffcc51fa100a52af99a0115970a78dc23497b362a525ce2`
- `tallwall_preflight_code`：`scripts/f4_tallwall120_material_preflight_v1.py` — `872daf5a8f3a5cf1e5cccc55d599c21396b4da3634d6a0ffdefddb335ddbcbd2`
- `migration_spec`：`campaigns/core-v1/material/evidence/f4-resting-pool-migration-spec-2026-09-19.json` — `76dfc5fe035ddcfa374fa09fec5b3f2472199ee58e9e13496f88f4c04d25b562`
- `matrix_review`：`campaigns/core-v1/material/evidence/f4-resting-pool-33-to-15-matrix-review-2026-09-19.json` — `7fd6c5f5c8f42a28a424a3a30e528eef549b6787895c3c9216b0c246d88710ff`
- `macro_sidecar_preflight`：`campaigns/core-v1/material/evidence/f4-macro-t2-sidecar-preflight-20260920.json` — `636b212081852921c209fe4b4124a99f64eac975c67b054b2fa2f48ab1172cb8`
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
