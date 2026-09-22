# F3 宏观 T2 admission/acceptance gap audit（2026-09-21）

结论：当前 `T2_macro=false`、`T2_path=false`，admission surface 为 `阻塞`；本次审计保留 `qualification_claim=none` 和 zero credit。只读取 JSON 与源码，没有打开 HDF5、启动 solver/GPU/queue，或修改 registry、ledger、matrix、T1/T2 分母及阈值。

机器回执：`/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/material/evidence/f3-t2-admission-acceptance-gap-audit-v2-20260922.json`；SHA-256：`90986f272225ac7faf08c75a1403dc19b140cd7351062ebe8aa133cb6bc1b5f0`。

## 固定门与当前证据

| 门 | 固定规则 | 审计结果 |
|---|---:|---|
| source-window / 质量闭合 | 两条完整 F3 row，hash、reader、mass、checkpoint 通过 | `true`（2/2） |
| native cadence provenance | `.002 s` source，误差容差 `5e-05` s；every-fifth 必须 direct、无插值 | `true`；短 canary 仍 right-censored |
| 每 source unknown mass | `<= 0.01` | `false`；最大 `0.015625`，3 个 source 半区失败 |
| F3 CDF sup | `<= 0.02` | `false`；最大 `0.06103515625` |
| residence CDF | 必须保留全分母与 censor bounds，并有 acceptance gate | 输出 `true`；接纳 `false` |
| event window | full source window；right-censor 不计 acceptance | bounded canary full-window `false` |

两条 4096-seed source-window 的结构审计、质量闭合、native frame/cadence 结构和 checkpoint/hash 通过；row 29 的最大 source unknown 为 `0.01220703125`，row 31 为 `0.015625`。两行 CDF comparison 都超过 `0.02`，因此完整性通过不能转化为科学资格。

## 33-row matrix

规范矩阵为 `33` 行（`0-23 resolution_substep; 24-27 cadence; 28-32 seed_density`）。当前状态计数：`{"blocked_missing_registered_source": 12, "native_dense_material_postprocess_running": 1, "related_v3_s2_diagnostic_running_not_canonical_s4_row": 1, "source_available_not_submitted": 2, "terminal_diagnostic_observed": 16, "terminal_matched_decimation_diagnostic_only": 1}`。终态诊断、matched-decimation 视图、running attempt 或 source-available-not-submitted 都不产生 acceptance receipt；当前 formal acceptance receipt 为 `0`，matrix ready 为 `false`。

精确 amp=.95/.1.05 源与 native-dense amp=1.1 源仍缺失；development case 不能重命名或插值替代。row 24 的 dense material postprocess 和 row 30 的相关 v3 s2 诊断也不能填充 canonical s4 row。

## 材料侧车接口缺口

native MLS comparator 已输出 first-passage、return 和 residence CDF bounds，并保留 unknown/right-censor 分母；基础 `core_material.py` 只提供 residence 均值摘要。`core_material_acceptance.py` 有 per-source unknown 与通用 CDF difference 检查，但没有接纳 native-MLS trace/checkpoint schema、residence-CDF gate、F3 event definition 或 native cadence gate，因此现有 native material 结果没有共享 acceptance 路径。

## 下一步最小可执行修复

先落地一个只读 native-MLS acceptance adapter/receipt bridge：绑定 trace/checkpoint schema、完整 source-window/cadence provenance、逐 source unknown、三类 CDF bounds、right-censored event semantics 和 full-window 状态；固定 unknown/CDF 门、全分母、33-row 定义与 `qualification_claim=none` 不变。随后才可按 exact source lineage 处理 source-available rows `28,32` 或 terminalize row `24`；缺失 exact source 的 rows `16–23,26,27,29,31` 仍须 root-owned CFD source。该顺序不会由本 audit 自动执行，也不会把 diagnostic 升级为 T2。

## 回执边界

本回执只新增 JSON 与中文报告；旧 evidence 未覆盖，solver/GPU/queue 未启动，registry/ledger/matrix 及任何科学分母、阈值均未改变。

## 输入哈希

- `core_material`：`scripts/core_material.py` — `75564f6fba20f8f3298dd6882e211ad4ad8278676c67083fb24e4ab140bb614c`
- `core_material_acceptance`：`scripts/core_material_acceptance.py` — `b9cb49cacf19590356bda4f32d32ef3d2255b9c97a8afa29a920e5a38bd6c4a7`
- `native_mls`：`scripts/f3_native_volume_mls.py` — `e1c5fc39e73781d386c7da2874c1749b5223c8209eaf8f25bb4453346df51ff9`
- `native_mls_compare`：`scripts/f3_native_volume_mls_compare.py` — `d4fc40b0b0057b4b0fc2487560d709f01c95068109a028e2664bc9f6fdf44acb`
- `native_cadence_adapter`：`scripts/f3_native_cadence_adapter_v1.py` — `746477383578df5edcef927e72aaff706d8a2621ff01f435cb9d65fd425dd42e`
- `source_window_audit`：`campaigns/core-v1/material/evidence/f3-f4-t2-cpu-source-window-audit-v1-20260920.json` — `983e15aae8e1ce4df705590c7b1cc89e27a0445c8152f4a003123392e3aaa279`
- `matrix_gap_audit`：`campaigns/core-v1/material/evidence/f3-native-mls-33-matrix-gap-audit-v1.json` — `b1cf2d4943d07e095343c664d8b704d4217ac920cd3672600da5a3e28af288a3`
- `matrix_asset_audit`：`campaigns/core-v1/material/evidence/f3-native-volume-mls-f3-matrix-asset-audit-v3-20260919.json` — `496fcbd59b2983c9a90ba2530795987b777c33f2d44a741d0c67aecbc7177f31`
- `native_cadence_preflight`：`campaigns/core-v1/material/evidence/f3-native-cadence-adapter-v1-preflight-20260920.json` — `9f2bef012459cba60a6d5c62723b567a5d56496f8436bb40d7fb4bc2fc6db651`
- `native_cadence_selection`：`campaigns/core-v1/material/evidence/f3-native-cadence-adapter-v1-every-fifth-selection-20260920.json` — `6c2c4a1059f7b43dd7235294395e574368f8d7c3649451d45a08a22cf2da3bac`
- `native_cadence_canary`：`campaigns/core-v1/material/evidence/f3-native-cadence-bounded-canary-evidence-v1.json` — `34873b663379b7ac659ff1d0c142367b3df9a1b7548f133dbbc0e764945dc634`
- `native_cadence_root_review`：`campaigns/core-v1/material/evidence/f3-native-cadence-adapter-v1-root-review-20260920.json` — `29d290763bbe93448af4b2fb4dae680f7e06b2d4711a4ba6b9401ab85a91960a`
- `comparison`：`campaigns/core-v1/material/evidence/f3-adapter-rows29-31-terminal-comparison-20260920.json` — `2db007419d5a00e91ec6dfa4ae7454dabed4e150472afc8e8835868a5c3b0e33`
- `six_row_diagnostic`：`campaigns/core-v1/material/evidence/f3-six-row-diagnostic-final.json` — `ca8a728432e89225f4ae596c60ea1d842fe5d6480f816abe7844652b61c6eb57`
- `unknown_gate_v1`：`campaigns/core-v1/material/evidence/f3-v1-seeds4096-unknown-gate-root-v1.json` — `1dbdd20abf1b7f8214a962013bc423e983cc8cd9d7a5265f0bf0efe07c1e812a`
- `unknown_gate_v3`：`campaigns/core-v1/material/evidence/f3-v3-4096-unknown-gate-root-v1.json` — `24c720edc77ec8dcb13e7b5e464c9091484f2e102b8bd535cb26677161aed912`
- `t1_qualification`：`campaigns/core-v1/evidence/f3-inherited-qualification.json` — `a28bf89e231fdb1bd7399c4ed8e2a6cbb297194c5cfee7cc93a1eb9d1d40d8a2`
