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

其余 7 个 attempt-001 已启动，完成后须逐格审计实际时间轴和 sidecar；任一科学失败都
保留在 8 格 canary 分母中。只有 8 格 canary 的输入、求解器和事件门均得到证据后，才
会考虑授权剩余 7 格并评估 F6 T1；当前不能把单个通过格升级成资格。

证据：

- [8 格 canary plan](../campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-solver-canary-v4-20260921/plan.json)
- [中心格 execution receipt](../campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-solver-canary-v4-20260921/cell-04/attempt-001/execution-receipt.json)
- [中心格 sidecar](../campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-solver-canary-v4-20260921/cell-04/attempt-001/body-state-force-torque-sidecar.json)
- [cell solver worker](../scripts/f6_physical_anchor_observation_axis_v10_cell_solver_canary.py)
- [post-solver finalize](../scripts/f6_physical_anchor_observation_axis_v10_cell_solver_canary_finalize.py)
