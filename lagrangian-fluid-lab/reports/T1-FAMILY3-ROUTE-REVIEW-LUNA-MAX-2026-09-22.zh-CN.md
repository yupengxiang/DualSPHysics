# 第三个 T1 家族 bounded route audit（Luna Max，2026-09-22）

## 结论

本轮按 bounded route audit 收束，不重开 F1/F2/F5/F6 已关闭路线，也没有找到证据足以支持一个新的、可立即进入 root review 的独立假设。因此结论为：

`route_closed_negative_no_new_hypothesis`。

当前 Core 仍只有 `F3/F4`，第三个 T1 family 未建立；`qualification_credit=0`。本轮没有修改 registry、ledger、matrix、任何分母或 Core completion 状态，没有启动 GPU、solver、queue，也没有重跑任何关闭输入。

## 最新 F2 v4 事实

F2 submerged-orifice normal-remediation v4 已作为最新闭包负证据绑定：

- case：`F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v4`；
- `preflight_pass=false`；
- `zero BoundNor=29484`、`zero NormalSize=29484`；
- 分区审计显示这 29,484 个零值全部属于 `Mk=18` gate，`Mk=17` outer wall 的零值为 0；
- finite、ID/XML 对齐、outer/gate endpoint、质量门均通过，质量相对误差为 `0.007812500000000222`；
- `solver_product_present=false`、`matrix_credit=0`、`same_input_retry=false`、`no_route_authorization=true`。

这条证据只能支持“当前 mDBC gate normal construction/formulation 仍未闭合”的诊断边界，不能把 v4 解释成通过，也不能授权 v5 或同类修复。

## 历史假设去重

| 家族 | 已审计假设 | 去重结论 | 当前 disposition |
|---|---|---|---|
| F1 | H1/H2/H3/H4 边界、ghost、normal、底面和 G1 悬空障碍物 | 仍是固定障碍物/dam-break 拓扑的修复谱系；G1 有完整事件窗但 hard-integrity 失败 | 关闭，保留失败证据 |
| F2 | DBC duration、receiver/weir、ballistic catch、distributed slot、submerged-orifice v2/v3/v4、H2 static hold | 既有变体分别是时长/事件窗、接收器拓扑、端点/释放、normal-layer/source-lattice 或静态诊断；v4 是同一 orifice 线的最新硬失败 | 关闭，不重试 |
| F5 | v3 explicit-void、v4 autofill、contact-band diagnostic | 同一 WaveRunup 活塞/斜坡/块体物理；v3/v4 都留下 `fluid_first_id=94622` 的 block 内端点 | 关闭，不重跑 |
| F6 | observation-axis v4；既有 explicit-body v9/v10 cadence/body-state 谱系 | v4 的 cell-08 排除粒子硬失败已闭包；v9/v10 是已有 proposal/canary lineage，不是本轮新假设 | 关闭或保持既有 qualification-only 状态 |

## 被筛掉但未提交的 F2 想法

基于 v4 的 gate-only zero-normal 分区，曾检查“同一静止 submerged-orifice 几何改用 native DBC Boundary=1、去除 mDBC BoundNor 依赖”的数值想法。

它表面上不同于 v2/v3/v4 的 sign/layer/source-lattice 修复，但当前证据仍不足以把它作为独立 bounded route：已有 DBC 证据来自不同的 full-cup moving-catchment 拓扑，没有证明 native DBC 在该 aperture 上保持相同的 underflow 语义，也没有 component-level boundary contract。此时物化 Definition 或 candidate card 会扩大搜索而不是由现有证据推出新路线。

因此本轮明确没有写入该 candidate card、Definition 或 static preflight contract；它仅作为“需要新信息才能重新打开”的候选屏查记录在 route audit 中，不具备 root review 条件。

## 重新打开所需的新信息

必须先获得真正独立的物理/数值机制证据，以及新的 scope/case/output 身份。对于上面的 DBC 想法，至少还需要：

1. 权威 solver/source contract 证明 native DBC 能表示该静止 aperture，且不改变 underflow 的物理语义；
2. 独立 root review 接受新的边界物理定义，而不仅是把 `Boundary=2` 改为 `Boundary=1`；
3. 新 Definition、固定 hard gates 和失败分母合同；任何未来 preflight 仍为 zero credit；
4. 明确禁止阈值放宽、survivor renormalization、同输入重试和分母改写。

在这些信息出现前，不具备 root review 条件；下一步应是补充上述外部/源码语义信息，而不是继续创建路线输入或运行作业。

## 证据与实现

机器可读审计：[route-audit-v1.json](../campaigns/core-v1/cfd/t1-family3-route-review-luna-max-v1/route-audit-v1.json)。只读校验脚本：[t1_family3_route_review_luna_max_v1.py](../scripts/t1_family3_route_review_luna_max_v1.py)。

脚本只读取小型 receipt/JSON 和 hash，不打开大场轨迹，没有任何 GenCase/native decoder/solver/GPU/queue/registry/ledger/matrix 写入口。

本轮新建内容仅属于独立审计命名空间、测试和报告；已有 F1/F2/F5/F6 证据未被修改或改判。

## 最终校验

- `scripts/t1_family3_route_review_luna_max_v1.py --check`：通过；所有 source receipt hash 一致，没有 stale hash。
- `pytest -q tests/test_t1_family3_route_review_luna_max_v1.py`：`4 passed`。
- route audit JSON 结构校验：通过。
- 本轮没有启动 solver、GPU 或 queue，也没有重跑任何已关闭输入。
