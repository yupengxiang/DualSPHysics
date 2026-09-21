# F6 v10 v4 solver canary（2026-09-21）

v4 的 15 格 native preflight 聚合审计通过后，按独立 root review 选择了 8 个 CPU
solver canary：索引 `0,4,5,8,9,12,13,14`。它们覆盖三个空间锚点、中心细档、两个
独立内点，以及内部时间推进和原生输出 cadence 对照。每格使用独立 job、attempt-001、
输入哈希和输出目录；`CUDA_VISIBLE_DEVICES` 为空，queue、registry、ledger 和
qualification matrix 均关闭。

中心生产格（index 4）已经完成。求解器生成 301 个 native 帧，实际时间轴最大间隔、
终端覆盖、接触窗口、固定粒子身份、闭合面接触／穿透、开顶质量通量和 `[1.0,1.5] s`
observation hold 均通过，sidecar 没有 equilibrium claim。运行结果仍为
`qualification_only`、`qualification_claim=none`、`qualification_credit=0`、
`T1=false`。

首次 worker 在 solver 正常返回并写出 sidecar 后，因 job 早期缺少 `case_id` 只在构造
回执时抛出 `KeyError`。该 attempt 的 solver 没有重跑；独立 finalize 程序重新读取同一
Run.out、301 个 BI4 帧和 sidecar，写入 recovery 标记和完整硬门回执。这个恢复只计为
一次基础设施元数据修复，不改变科学输入或放宽门槛。

其余 7 个 attempt-001 已全部完成并逐格审计。8 格中 7 格通过全部硬门；cell-08
（`q=1`、细档、`dp=0.015`）求解器返回 0 且产生 301 帧，但末端少 1 个流体粒子，
因此 `excluded_particles_zero`、`native_identity_fixed` 和 `fluid_group_count_fixed`
均失败。它被记录为 `scientific_hard_gate_failure`，没有重试，也没有从分母删除。
cell-14 的原生输出对照产生 601 帧并通过对应 cadence 门；cell-04 的 worker 元数据
缺失只做了一次只读 finalize，solver 没有重跑。aggregate audit 的状态是
`all_selected_canaries_audited`、`scientific_pass_count=7/8`，且仍为
`qualification_claim=none`、`qualification_credit=0`、`T1=false`。

这组结果只完成了 canary 证据闭包，不足以授权剩余 7 个矩阵格，也不能把 v4 scope
升级为 F6 T1。下一步必须由新的 root review 决定：保留该 scope 的负结果并转向替补
家族，或者提出一个改变科学输入的新 scope；不得对 cell-08 做同输入重跑。

证据：

- [8 格 canary plan](../campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-solver-canary-v4-20260921/plan.json)
- [中心格 execution receipt](../campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-solver-canary-v4-20260921/cell-04/attempt-001/execution-receipt.json)
- [中心格 sidecar](../campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-solver-canary-v4-20260921/cell-04/attempt-001/body-state-force-torque-sidecar.json)
- [8 格 aggregate audit](../campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-solver-canary-v4-20260921/canary-audit.json)
- [cell-08 失败回执](../campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-solver-canary-v4-20260921/cell-08/attempt-001/execution-receipt.json)
- [cell solver worker](../scripts/f6_physical_anchor_observation_axis_v10_cell_solver_canary.py)
- [post-solver finalize](../scripts/f6_physical_anchor_observation_axis_v10_cell_solver_canary_finalize.py)
