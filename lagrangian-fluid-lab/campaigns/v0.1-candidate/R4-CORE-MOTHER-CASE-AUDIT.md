# R4 core mother case audit

状态：**只读资格审计；没有启动 GPU、CFD、GenCase 或 solver。**

首个候选：**`F1_obstacle_ladder`**。正式执行授权为 **`NO_GO`**；现有开发级数值轨可继续 **`GO_T1_ONLY`**，但不能称为 T2 或正式物理接受。

本审计新增两个独立产物，并只读取 W05/R3 证据、现有运行元数据和文本日志。它把官方 anchor、已执行、仅预检和缺失单元分开，不改既有报告或工作包。

## 结论摘要

- A0：SPHERIC Test 02（F1）和 Test 10（F3）均已有 W05 官方物理 anchor 与三分辨率运行；两者都是 `anchor_present_partial_not_full_gold`，不是 full-Gold 等价。
- A1：选定的 F1 三背景×三分辨率有 **5/9 执行证据、3/9 目标控制兼容**；F3 同样为 **5/9、3/9**。
- A2：W05、legacy custom、R3 custom 的 integrator/boundary/cadence/time window 不同；当前没有可以直接作为共同主矩阵的 0.001 s F1 event-window 输出。
- 单一 gate 当前不通过：形式化下一次运行保持 `NO_GO`；若只继续已有闭域数值轨，范围限定为 `GO_T1_ONLY` development candidate。

## A0：官方 Test 02/10 是否已有等价 anchor

“等价”在这里分成两层：官方物理定义/参考数据等价，以及所有观测量都可作 Gold 的科学等价。前者为是，后者为否。

| family | official test | W05 三档 | 运行控制 | 判定 |
|---|---|---|---|---|
| F1 | SPHERIC Test 02 | W05_F1_coarse, W05_F1_medium, W05_F1_fine | ['Symplectic']/['mDBC']; cadence [0.02, 0.020001] s; tmax [6.0] s | anchor_present_partial_not_full_gold |
| F3 | SPHERIC Test 10 | W05_F3_coarse, W05_F3_medium, W05_F3_fine | ['Symplectic']/['mDBC']; cadence [0.005] s; tmax [8.35] s | anchor_present_partial_not_full_gold |

W05 的直接限制必须保留：F1 只有 H2/H4 可作为开发级宏观锚点，H1/H3 与冲击压力不能被水位结果背书；F3 的压力峰值、峰时和全时程没有共同收敛。R3 也明确“不把新拓扑背景冒充等价 anchor”。

## A1：三背景×三分辨率覆盖

A1 的主矩阵是 custom same-family ladder；W05 官方 anchor 单独作为 A0 reference。F1 选 `plain_dam_break / center_obstacle / twin_obstacle_split_remerge`，F3 选 `impulse_slosh / baffled_exchange / transverse_slosh`。`F1_opposing_columns` 留作 alternate，因为它改变了初始流体源数量。

| family | 背景 | coarse | medium | fine | 执行证据 | 目标兼容 |
|---|---|---|---|---|---:|---:|
| F1 | `plain_dam_break` | existing / control or dp mismatch | missing | missing | 1/3 | 0/3 |
| F1 | `center_obstacle` | existing / control or dp mismatch | missing | missing | 1/3 | 0/3 |
| F1 | `twin_obstacle_split_remerge` | existing / target-compatible | existing / target-compatible | existing / target-compatible | 3/3 | 3/3 |
| F3 | `impulse_slosh` | existing / control or dp mismatch | missing | missing | 1/3 | 0/3 |
| F3 | `baffled_exchange` | existing / target-compatible | existing / target-compatible | existing / target-compatible | 3/3 | 3/3 |
| F3 | `transverse_slosh` | existing / control or dp mismatch | missing | missing | 1/3 | 0/3 |

要点：

- legacy custom coarse case 有 solver/Run.csv/trajectory evidence，但使用约 0.04 m、0.05 s；它是已执行证据，不是 R3 mass-matched 目标 cell。
- R3 twin/baffled 的 mass-matched 三档是当前唯一完整的 custom 3×1 background evidence；R3 把 `[0.04, 0.03, 0.02]` 的共同 dp 作为 GenCase-only preflight 拒绝，不能计作运行。
- R3 F1 twin 的终态质量分布 TV 为 coarse→medium `0.0714`、medium→fine `0.1556`，因此当前 F1 topology evidence 不能直接通过 0.05 resolution screen；R3 F3 baffled 的 `0.00365/0.00500` 仅说明数值机制稳定，不能替代外部观测。

## A2：cadence、integrator、time window、observable

现有运行 profile：

| profile | output cadence | tmax | integrator | boundary |
|---|---|---|---|---|
| W05 official F1/F3 anchors | 0.005000008383233533–0.020000553333333334 s (median 0.012500148183632733) | 6.0–8.35 s | ['Symplectic'] | ['mDBC'] |
| legacy custom one-resolution probes | 0.050005–0.05002061111111111 s (median 0.05000683080808081) | 0.55–0.9 s | ['Verlet'] | ['DBC'] |
| R3 selected custom three-resolution backgrounds | 0.010000073333333333–0.010001644444444444 s (median 0.010001166666666665) | 0.9–1.5 s | ['Verlet'] | ['DBC'] |

首个 F1 core 的最小 bounded protocol：

- 空间档：`{'coarse': 0.035, 'medium': 0.024, 'fine': 0.014}` m；integrator `Verlet` (`StepAlgorithm=1`, `VerletSteps=40`)，边界 `DBC`。
- 全时窗：`0.0–1.5 s`；基础保存 cadence：`0.001 s`。固定 event window：`0.35–0.55 s`，依据 Test 02 P1–P4 首次实验峰约 0.415–0.459 s。
- T1 primary：身份保持、位置/速度轨迹、path occupancy；T2 primary：每背景显式 destination 的初始质量分母、分流/重汇质量向量和 closure。
- 外部观测：只把官方 F1 的 H2/H4 作为 limited macro anchor；压力必须新增 peak time、peak amplitude、impulse，不能继续只看低频全时程 RMSE。

未闭合缺口：

- `integrator_and_boundary_mismatch`：one frozen protocol per A1 matrix; do not pool W05 mDBC/Symplectic with custom DBC/Verlet as if identical（现状：{'W05_anchor': {'integrator': ['Symplectic'], 'boundary': ['mDBC']}, 'legacy_custom': {'integrator': ['Verlet'], 'boundary': ['DBC']}, 'R3_custom': {'integrator': ['Verlet'], 'boundary': ['DBC']}}）。
- `event_output_cadence`：0.001 s base output for the first F1 event window; R3 downsampling 0.01 to 0.05 s cannot recreate omitted solver states（现状：{'W05_F1_s': {'median': 0.012500148183632733, 'min': 0.005000008383233533, 'max': 0.020000553333333334}, 'legacy_custom_s': {'median': 0.05000683080808081, 'min': 0.050005, 'max': 0.05002061111111111}, 'R3_custom_s': {'median': 0.010001166666666665, 'min': 0.010000073333333333, 'max': 0.010001644444444444}}）。
- `time_window_alignment`：first-core bounded window [0, 1.5] s plus fixed event scoring window [0.35, 0.55] s; 0-6 s is needed only for a full Test 02 trace claim（现状：{'W05_F1_s': {'min': 6.0, 'max': 8.35}, 'legacy_custom_s': {'min': 0.55, 'max': 0.9}, 'R3_custom_s': {'min': 0.9, 'max': 1.5}}）。
- `external_observable_scope`：declare H2/H4 as limited macro anchors, add event peak/time/impulse for F1 pressure, and never transfer A0 truth to custom topologies（现状：W05 F1 has H1-H4 and P1-P8 metrics; R3 custom backgrounds have no compatible external observation）。
- `f1_resolution_stability`：top-two-resolution primary path/destination observable within the pre-registered 0.05 screening threshold; R3 twin currently reports TV 0.0714 and 0.1556（现状：{'background': 'twin_obstacle_split_remerge', 'resolution_change': {'coarse_to_medium_mass_fraction_tv': 0.07142857142857142, 'medium_to_fine_mass_fraction_tv': 0.1556464124111183}, 'interpretation': 'numerical resolution and mechanism only; no external experiment'}）。
- `t2_destination_contract`：explicit per-background destination regions, wall/open-face/rim policy, initial-mass denominator and closure evidence; this audit does not modify tracer or transport files（现状：{'destination_spec_linked_count': 0, 't2_contract_ready_count': 0, 'wall_visibility_true_count': 0}）。

## 单一 acceptance gate 与三态判定

Gate：**`R4_CORE_MOTHER_CASE_GATE_v1`**。它是一个 AND gate；所有 required condition 都通过才可接受。`GO_T1_T2` 还必须有 T2 destination closure；若 T1 数值部分通过而 T2 仍 candidate-only，最多只能 `GO_T1_ONLY`。

| condition | 当前状态 |
|---|---|
| `A0_official_anchor` | **partial_pass** — W05 F1 Test 02 anchor exists at three resolutions; full Gold observable equivalence is explicitly false |
| `A1_nine_executed_cells` | **fail** — F1 selected ladder has 5/9 executed-evidence cells and 3/9 target-compatible cells |
| `A2_common_control_protocol` | **fail** — W05 is mDBC/Symplectic at 0.02 s, legacy custom is DBC/Verlet at 0.05 s, and R3 custom is DBC/Verlet at 0.01 s |
| `A2_event_sampling_and_window` | **fail** — no existing F1 matrix has the proposed 0.001 s output and fixed [0.35,0.55] s event window |
| `closed_trajectory_quality_and_resolution` | **fail** — R3 F1 twin reports coarse-medium TV=0.07142857142857142 and medium-fine TV=0.1556464124111183; the 0.05 screening threshold is exceeded |
| `T2_destination_closure` | **fail** — linked destination specs=0, wall_visibility_true=0, T2-ready=0 |

判定所需证据：

- `GO_T1_T2`：9/9 同一控制协议的不可变完成记录；闭域 identity/time/finite-state 与零 unexplained numerical loss；每背景 top-two resolution 的主 path/destination observable 通过预注册 0.05 screen；0.001 s event-capable cadence 与固定时窗；以及 destination/wall/open-face/质量 closure 完整。
- `GO_T1_ONLY`：上述 T1 数值结构与分辨率证据通过，但 T2 仍只允许 candidate-only；不能把目的地标签或 wall visibility 说成已接受真值。当前已有开发轨可以继续这个范围，但形式化 R4 9-cell gate 尚未通过。
- `NO_GO`：正式执行遇到 missing/prepared-only cell、混合控制未重跑、identity/time/finite-state 失败或主 observable 分辨率不稳定时触发。当前正式下一次运行保持 `NO_GO`，这是 gate hold，不是对所有开发轨的永久否定。

## 建议下一次真正运行的最多 9 个工况

以下 9 个是**规范化重跑清单**，全部 `execute=false`。因为已有 W05/R3/legacy 工况的 integrator、边界、dp、cadence 和 tmax 不一致，建议用同一 R4 protocol 重建 3×3；若资源需要缩减，最低填缺是 plain/center 的 medium/fine 四格，但那仍不能通过共同控制 gate。

| # | case | background | level | dp (m) | tmax (s) | tout (s) | integrator |
|---:|---|---|---|---:|---:|---:|---|
| 1 | `R4_F1_plain_dam_break_coarse` | `plain_dam_break` | coarse | 0.035 | 1.5 | 0.001 | Verlet |
| 2 | `R4_F1_plain_dam_break_medium` | `plain_dam_break` | medium | 0.024 | 1.5 | 0.001 | Verlet |
| 3 | `R4_F1_plain_dam_break_fine` | `plain_dam_break` | fine | 0.014 | 1.5 | 0.001 | Verlet |
| 4 | `R4_F1_center_obstacle_coarse` | `center_obstacle` | coarse | 0.035 | 1.5 | 0.001 | Verlet |
| 5 | `R4_F1_center_obstacle_medium` | `center_obstacle` | medium | 0.024 | 1.5 | 0.001 | Verlet |
| 6 | `R4_F1_center_obstacle_fine` | `center_obstacle` | fine | 0.014 | 1.5 | 0.001 | Verlet |
| 7 | `R4_F1_twin_obstacle_split_remerge_coarse` | `twin_obstacle_split_remerge` | coarse | 0.035 | 1.5 | 0.001 | Verlet |
| 8 | `R4_F1_twin_obstacle_split_remerge_medium` | `twin_obstacle_split_remerge` | medium | 0.024 | 1.5 | 0.001 | Verlet |
| 9 | `R4_F1_twin_obstacle_split_remerge_fine` | `twin_obstacle_split_remerge` | fine | 0.014 | 1.5 | 0.001 | Verlet |

每个工况还必须输出：Part trajectory、Run.csv/solver log、source-conditioned path/destination observable，以及固定 F1 event-window 的 pressure peak/time/impulse。执行前另需完成同 background 的 CPU GenCase mass/geometry preflight；本审计不执行该 preflight。

## 可复核入口

- `campaigns/v0.1-candidate/W05-CONCLUSION.md` 与 `w05-validation-anchors.json`：官方 F1/F3 anchor 及限制。
- `campaigns/v0.1-candidate/R3-G2-F1-F3-CONCLUSION.md` 与 `r3-g2-f1-f3-matrix.json`：R3 两背景×三分辨率、cadence 下采样、TV 和 blocker。
- `reports/runtime/run-summary.json`、`quality-gates.json`、`trajectory-audit.json`：legacy custom 执行/质量/轨迹证据。
- `campaigns/v0.1-candidate/r3-g2-transport-spec-audit.json`：当前 T2 linked destination 与 wall visibility 为 0 的契约证据。

审计产物本身只允许写入：`scripts/r4_core_mother_case_audit.py`、`r4-core-mother-case-audit.json`、`R4-CORE-MOTHER-CASE-AUDIT.md` 和 `test_r4_core_mother_case_*.py`。
