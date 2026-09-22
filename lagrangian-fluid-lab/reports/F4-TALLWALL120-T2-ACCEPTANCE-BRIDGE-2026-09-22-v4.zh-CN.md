# F4 tallwall120 T2 acceptance bridge/contract（2026-09-22）

结论：工程回执为 `recorded`（仅表示输入、缺口和恢复语义已绑定）；科学 T2 qualification 为 `blocked`，credit=`0`，`T2_macro=false`、`T2_path=false`。

本次只读 bridge 只读取 JSON、源码和报告哈希；没有打开 HDF5，未启动 solver/GPU/queue，未修改既有 evidence、registry、ledger、matrix、阈值或分母。工程 receipt 与科学 qualification 是两个不同对象。

机器回执：`/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/material/evidence/f4-tallwall120-t2-acceptance-bridge-v1-20260922-v4.json`；SHA-256：`d2bcce2b32c0e0b708c21e78463a5b2d09e10a837d8db48bc358742c9fbd6f75`。

## 工程回执与科学结论边界

| 对象 | 状态 | 含义 |
|---|---|---|
| engineering receipt | `recorded` | hash-bound 的只读接口快照；6 个案例和 33 个矩阵行均已枚举 |
| formal scientific receipt | `blocked` | blocked；credit=`0`；不授予 T2 |

## 固定门

| 门 | 固定规则 | 当前 bridge 结果 |
|---|---:|---|
| 每 source unknown | `<= 0.01` | `false`；最大 `1.0` |
| F4 事件窗 | `4.34` s，必要时一次延长至 `8.68` s | `false`；0/6 完整 |
| F4 CDF 容差 | 必须由 F4 自己登记 | `false`；未借用 F3 的 `0.02` |
| residence | CDF、驻留和 right-censor 语义及 acceptance 容差 | `false` |
| 事件容差 | endpoint `1e-08` m；saved-chord crossings `0` | `false` |
| 恢复 | frame-40 resume、每 native frame checkpoint、append-only generation | contract=`true`；receipt=`false` |
| 矩阵 | 33 行均有 formal receipt | `false`；当前 `0/33` |

## 逐案例缺口

| # | case | unknown | event window | CDF fields | residence | recovery | formal receipt |
|---:|---|---:|---|---|---|---|---|
| 0 | `f4_real_material_baseline_s2` | `0.84765625` / `0.01` | false (right_censored_or_unresolved) | true | true | true | false |
| 1 | `f4_native_dense_pair_s2_s4` | `0.896484375` / `0.01` | false (right_censored_or_unresolved) | true | true | true | false |
| 2 | `f4_native_dense_pair_s2_s4` | `0.896484375` / `0.01` | false (right_censored_or_unresolved) | true | true | true | false |
| 3 | `f4_repair_canaries_ess32_and_affine_bound` | `0.923828125` / `0.01` | false (right_censored_or_unresolved) | true | true | true | false |
| 4 | `f4_repair_canaries_ess32_and_affine_bound` | `0.955078125` / `0.01` | false (right_censored_or_unresolved) | true | true | true | false |
| 5 | `f4_tallwall120_short_canary` | `1.0` / `0.01` | false (right_censored_or_unresolved) | false | false | true | false |

保留案例共 `6` 个；unknown 门通过 `False`，事件窗完整 `0/6`，CDF 字段完整 `5/6`，正式 receipt `0/6`。质量闭合 `6/6` 仍不足以抵销 unknown/right-censor。

## 逐矩阵缺口

矩阵行号沿用登记顺序：`0–23 resolution_substep`、`24–27 cadence`、`28–32 seed_density`。源 cell 可用不等于材料 overlay 完成；禁止插值、把独立 .02 s solve 当作 decimation，或把诊断行升级为 T2。

| row | axis | source cell | source available | status | gap |
|---:|---|---:|---|---|---|
| 0 | `resolution_substep` | `3` | true | `blocked_pending_material_overlay` | source CFD cell is mapped, but no completed material overlay and no formal receipt exist; source availability is not qualification |
| 1 | `resolution_substep` | `3` | true | `blocked_pending_material_overlay` | source CFD cell is mapped, but no completed material overlay and no formal receipt exist; source availability is not qualification |
| 2 | `resolution_substep` | `4` | true | `blocked_pending_material_overlay` | source CFD cell is mapped, but no completed material overlay and no formal receipt exist; source availability is not qualification |
| 3 | `resolution_substep` | `4` | true | `blocked_pending_material_overlay` | source CFD cell is mapped, but no completed material overlay and no formal receipt exist; source availability is not qualification |
| 4 | `resolution_substep` | `5` | true | `blocked_pending_material_overlay` | source CFD cell is mapped, but no completed material overlay and no formal receipt exist; source availability is not qualification |
| 5 | `resolution_substep` | `5` | true | `blocked_pending_material_overlay` | source CFD cell is mapped, but no completed material overlay and no formal receipt exist; source availability is not qualification |
| 6 | `resolution_substep` | `6` | true | `blocked_pending_material_overlay` | source CFD cell is mapped, but no completed material overlay and no formal receipt exist; source availability is not qualification |
| 7 | `resolution_substep` | `6` | true | `blocked_pending_material_overlay` | source CFD cell is mapped, but no completed material overlay and no formal receipt exist; source availability is not qualification |
| 8 | `resolution_substep` | `7` | true | `blocked_pending_material_overlay` | source CFD cell is mapped, but no completed material overlay and no formal receipt exist; source availability is not qualification |
| 9 | `resolution_substep` | `7` | true | `blocked_pending_material_overlay` | source CFD cell is mapped, but no completed material overlay and no formal receipt exist; source availability is not qualification |
| 10 | `resolution_substep` | `8` | true | `blocked_pending_material_overlay` | source CFD cell is mapped, but no completed material overlay and no formal receipt exist; source availability is not qualification |
| 11 | `resolution_substep` | `8` | true | `blocked_pending_material_overlay` | source CFD cell is mapped, but no completed material overlay and no formal receipt exist; source availability is not qualification |
| 12 | `resolution_substep` | `1` | true | `blocked_pending_material_overlay` | source CFD cell is mapped, but no completed material overlay and no formal receipt exist; source availability is not qualification |
| 13 | `resolution_substep` | `1` | true | `blocked_pending_material_overlay` | source CFD cell is mapped, but no completed material overlay and no formal receipt exist; source availability is not qualification |
| 14 | `resolution_substep` | `2` | true | `blocked_pending_material_overlay` | source CFD cell is mapped, but no completed material overlay and no formal receipt exist; source availability is not qualification |
| 15 | `resolution_substep` | `2` | true | `blocked_pending_material_overlay` | source CFD cell is mapped, but no completed material overlay and no formal receipt exist; source availability is not qualification |
| 16 | `resolution_substep` | `9` | true | `blocked_pending_material_overlay` | source CFD cell is mapped, but no completed material overlay and no formal receipt exist; source availability is not qualification |
| 17 | `resolution_substep` | `9` | true | `blocked_pending_material_overlay` | source CFD cell is mapped, but no completed material overlay and no formal receipt exist; source availability is not qualification |
| 18 | `resolution_substep` | `10` | true | `blocked_pending_material_overlay` | source CFD cell is mapped, but no completed material overlay and no formal receipt exist; source availability is not qualification |
| 19 | `resolution_substep` | `10` | true | `blocked_pending_material_overlay` | source CFD cell is mapped, but no completed material overlay and no formal receipt exist; source availability is not qualification |
| 20 | `resolution_substep` | `11` | true | `blocked_pending_material_overlay` | source CFD cell is mapped, but no completed material overlay and no formal receipt exist; source availability is not qualification |
| 21 | `resolution_substep` | `11` | true | `blocked_pending_material_overlay` | source CFD cell is mapped, but no completed material overlay and no formal receipt exist; source availability is not qualification |
| 22 | `resolution_substep` | `12` | true | `blocked_pending_material_overlay` | source CFD cell is mapped, but no completed material overlay and no formal receipt exist; source availability is not qualification |
| 23 | `resolution_substep` | `12` | true | `blocked_pending_material_overlay` | source CFD cell is mapped, but no completed material overlay and no formal receipt exist; source availability is not qualification |
| 24 | `cadence` | `14` | false | `blocked_missing_exact_cfd_source` | F4 cell-14 is a real native-output solve at .004 s, not the .002 s dense control required by the 33-row template |
| 25 | `cadence` | `14` | false | `blocked_missing_exact_cfd_source` | no complete dense source is available yet; cell-13 .02 s is an independent solve, not a decimation of cell-14 |
| 26 | `cadence` | `None` | false | `blocked_missing_exact_cfd_source` | cell-07 is only the .02 s spatial solve; no q=1 native dense CFD cell |
| 27 | `cadence` | `None` | false | `blocked_missing_exact_cfd_source` | no q=1 dense parent exists to decimate |
| 28 | `seed_density` | `1` | true | `blocked_pending_seed_density_overlay` | material high-seed overlay pending; no new CFD solve required once full source H5 exists |
| 29 | `seed_density` | `9` | true | `blocked_pending_seed_density_overlay` | material high-seed overlay pending; no new CFD solve required once full source H5 exists |
| 30 | `seed_density` | `4` | true | `blocked_pending_seed_density_overlay` | material high-seed overlay pending; no new CFD solve required once full source H5 exists |
| 31 | `seed_density` | `11` | true | `blocked_pending_seed_density_overlay` | material high-seed overlay pending; no new CFD solve required once full source H5 exists |
| 32 | `seed_density` | `7` | true | `blocked_pending_seed_density_overlay` | material high-seed overlay pending; no new CFD solve required once full source H5 exists |

## 恢复语义

contract bound=`true`；frame `0..1085`；required end `4.340002980805959` s；recovery boundary=`40`；每 native frame checkpoint=`true`。

恢复规则：`verify manifest binding/generation SHA and resume latest committed frame`；generation=`content-addressed append-only; never overwrite or delete prior generation`；从零重跑禁止=`true`。root review 当前授权=`false`，candidate 状态=`proposal_only_deferred_after_one_transition_failure`，one-transition survivors=`0`。旧 trace 只作 binding，不复制 candidate state；本 bridge 不执行恢复。

## 阻塞原因

1. per-case unknown gate fails: maximum observed 1.0 > 0.01
2. full event window fails: 0/6 retained cases are complete; right-censored paths remain in the denominator
3. F4 has no registered numerical CDF tolerance; the F3 bridge's 0.02 threshold is reference-only and is not applied
4. only 5/6 case sidecars expose all CDF fields, and no F4 reference comparison is available
5. residence output/tolerance acceptance is incomplete; residence fields alone do not qualify a path
6. registered endpoint/saved-chord event tolerances are not enforced by the existing acceptance surface
7. formal per-case acceptance receipts are 0/6
8. the registered 33-row matrix has 33 explicit gaps and zero formal material receipts
9. the full-source recovery contract is bound but root review has not authorized execution; the one-transition candidate cohort has zero survivors
10. engineering receipt binding does not grant scientific T2 qualification or partial credit

## 输入哈希

- `t2_gap_audit`：`campaigns/core-v1/material/evidence/f4-tallwall120-t2-admission-acceptance-gap-audit-20260922-v3.json` — `db79c0f3199cd664e81b30d687c340d2fb1fc4cdbdb4cd7bf477de32421d67cc`
- `macro_sidecar_preflight`：`campaigns/core-v1/material/evidence/f4-macro-t2-sidecar-preflight-20260920.json` — `636b212081852921c209fe4b4124a99f64eac975c67b054b2fa2f48ab1172cb8`
- `migration_spec`：`campaigns/core-v1/material/evidence/f4-resting-pool-migration-spec-2026-09-19.json` — `76dfc5fe035ddcfa374fa09fec5b3f2472199ee58e9e13496f88f4c04d25b562`
- `matrix_review`：`campaigns/core-v1/material/evidence/f4-resting-pool-33-to-15-matrix-review-2026-09-19.json` — `7fd6c5f5c8f42a28a424a3a30e528eef549b6787895c3c9216b0c246d88710ff`
- `material_preflight`：`campaigns/core-v1/material/evidence/f4-tallwall120-native-cell14-material-preflight-20260921.json` — `f5e6dc499e19349324799f36a154b5bfc7c6bb9be03b0c0e9df27a4acd7fc9bf`
- `trace_result`：`campaigns/core-v1/material/evidence/f4-tallwall120-native-cell14-material-preflight-20260921.trace.json` — `b12a0e4a26a61e226f386776c54b90b6752a668b642b13e2b4f5a704f2c4973c`
- `trace_diagnosis`：`campaigns/core-v1/material/evidence/f4-tallwall120-native-cell14-material-preflight-20260921.diagnosis.json` — `b0c59379eb5cad9363a504fed9ead64d9385d5777aa32206c3649e52e537542a`
- `full_source_contract`：`campaigns/core-v1/material/evidence/f4-tallwall120-native-cell14-f4-ess32-full-source-canary-contract-20260921.json` — `cfb7f20c8e5276d1148f21b32980ae2ef55afdf656924dc72aeddc06631a8f91`
- `root_review`：`campaigns/core-v1/material/evidence/f4-tallwall120-native-cell14-f4-ess32-root-review-20260921.json` — `b6e7e92435179d25cc524e006b53c482259dc22065e30b5297d6ed4975dc7b7a`
- `candidate_contract`：`campaigns/core-v1/material/evidence/f4-tallwall120-native-cell14-candidate-contract-20260921.json` — `566d39c8c32f42859d7f2b1b93ef087dbf6e01d1666bead10d740d9ca2709d6d`
- `negative_evidence`：`campaigns/core-v1/material/evidence/f4-material-negative-evidence-audit-20260920.json` — `6aa41b16acdf6562a7b40c4e79f1e3ee18b59db080c2fd8ce642d04749bf33dd`
- `admission_contract`：`campaigns/core-v1/material/evidence/f3-f4-t2-admission-root-review-contract-20260921.json` — `04e02868af86d65758fb739ff4630fec658e384b7325bbdf66abd55d60edafac`
- `core_material`：`scripts/core_material.py` — `431fe2a355037423e01629412315a7d5e73f3b259bee262e1384ebb33168cf3e`
- `core_material_acceptance`：`scripts/core_material_acceptance.py` — `b9cb49cacf19590356bda4f32d32ef3d2255b9c97a8afa29a920e5a38bd6c4a7`
- `macro_sidecar_preflight_code`：`scripts/f4_macro_t2_sidecar_preflight_v1.py` — `54dd170ca74be0160c70f2667779ebaeacc884fe614aa9927128167a77b66c0b`
- `tallwall_material_code`：`scripts/f4_tallwall120_material.py` — `22881496c7fd961c8ffcc51fa100a52af99a0115970a78dc23497b362a525ce2`
- `tallwall_preflight_code`：`scripts/f4_tallwall120_material_preflight_v1.py` — `872daf5a8f3a5cf1e5cccc55d599c21396b4da3634d6a0ffdefddb335ddbcbd2`
- `t1_evaluator_manifest`：`campaigns/core-v1/cfd/f4-tallwall120-qualification-evaluator-v2.json` — `dc6ebde73388ab69d2eb2ba5df8cd52f511f378dc2655e68c17a356547a8bbfe`
- `t1_evaluator_code`：`scripts/f4_tallwall_qualification_evaluator_v2.py` — `ee2673cda352558884177c2bb10c7c57d92589de5645c5ffebe215007c5b6eb8`
- `f3_bridge_reference`：`scripts/f3_native_mls_acceptance_bridge_v1.py` — `10832aeffeb9a06a994a56056849df34c646b54711747832e6de298b357cc14d`
- `f3_bridge_reference_receipt`：`campaigns/core-v1/material/evidence/f3-native-mls-acceptance-bridge-v1-20260921.json` — `837460299660f005f0d6d72f0d6302a916d765f5afff864686b7ce1370a66594`
- `f3_bridge_report_reference`：`reports/F3-NATIVE-MLS-ACCEPTANCE-BRIDGE-2026-09-21.zh-CN.md` — `4ac6156e29d7a6b5b83302c6d88aeb373934d82698d427d7a7fe9340d910eeff`
- `gap_audit_report_reference`：`reports/F4-TALLWALL120-T2-ADMISSION-ACCEPTANCE-GAP-AUDIT-2026-09-22-v3.zh-CN.md` — `6a73164da183e83bc87ed563113039a9547d072377398c4feca6451ac0ee3691`
- `material_root_cause_report_reference`：`reports/F4-TALLWALL120-MATERIAL-ROOT-CAUSE-AUDIT-2026-09-21.zh-CN.md` — `b96922076db10d43c023a5875f83ef4a42531d82a10654f49ce289305063e986`
- `macro_preflight_report_reference`：`reports/F4-MACRO-T2-SIDECAR-PREFLIGHT-2026-09-20.md` — `7cab469476df1d926c3a01185e2af41501b2d444b4877235ee97d0ef9ccaf293`
- `admission_report_reference`：`reports/F3-F4-T2-ADMISSION-CONTRACT-2026-09-21.zh-CN.md` — `91392c03c66b2c0674c91c4997409dd3497ac157111b29b399eeb8da4d163952`
- `bridge_implementation`：`scripts/f4_tallwall120_t2_acceptance_bridge_v2.py` — `8d84fad1067115531686b6ac0c56d0a0fa6ae05a782fd29812d04da3a1532c9a`

另绑定逐案例结果 `6` 个、checkpoint manifest `6` 个；HDF5 路径/哈希仅继承上游证据，本 bridge 未重新打开或 rehash。

该报告与 JSON 均属于新的 `f4-tallwall120-t2-acceptance-bridge-v1` 命名空间；旧 gap audit、registry、ledger、matrix、阈值、分母和历史 evidence 保持不变。
