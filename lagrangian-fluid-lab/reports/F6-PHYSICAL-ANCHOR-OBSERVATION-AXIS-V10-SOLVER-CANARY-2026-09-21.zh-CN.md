# F6 v10 observation-axis CPU solver canary（2026-09-21）

v10 使用已经通过 fresh GenCase/native preflight 的 Definition、XML 和 BI4，按
root review 只执行了一次本地 CPU DualSPHysics solver。`CUDA_VISIBLE_DEVICES` 为空，
没有 runtime queue、GPU、registry、ledger 或 matrix 操作；同一输入禁止 retry、resume
和第二次执行。

## 运行结果

- solver return code 为 0，Run.out 报告 `TimeMax=1.5`、`TimePart=0.005`，无排除粒子，
  native `Part_0000..Part_0300` 共 301 帧。
- 评分时间轴使用 solver 报告的实际 `TimeStep`。首帧为 `0`，末帧为
  `1.500144461103 s`；最大相邻间隔为 `0.0051872955753 s`，满足预登记的
  `<=0.0055 s` 和 `[1.5,1.5005] s` 终端覆盖门。
- 11,806 fixed、693 floating、15,048 fluid 粒子的数量和身份在全部 native 帧中固定，
  body sidecar 的位置、速度、角速度、力和力矩有限。
- 接触时间为 `0.2150725530666 s`，落在独立解析窗口
  `[0.1869141263,0.2269141263] s`；闭合面接触／穿透为零，开顶质量流为零。
- `[1.0,1.5] s` 已被 native 时间轴 bracket，记录为 `observation_hold`。
  该区间不声称位置、速度、角速度或力达到平衡；例如线速度范数最大约
  `2.20 m/s`、角速度范数最大约 `4.11 rad/s`，因此不能把它报告成 settle/equilibrium。

## 科学状态

receipt 状态为 `solver_completed_sidecar_pass_pending_scientific_review`，所有 v10
runtime hard gates 通过，但 `qualification_claim=none`、`qualification_credit=0`、
`T1=false`。这只是一个完整事件窗的物理锚点 canary；F6 仍需要预登记的空间／时间／
cadence 资格矩阵、逐格科学审查和固定 8→32 生产批次，不能凭一次 canary 进入 Core
第三 T1 家族或模型分母。

证据：[execution receipt](../campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-solver-canary-20260921/attempt-001/execution-receipt.json)、
[body sidecar](../campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-solver-canary-20260921/attempt-001/body-state-force-torque-sidecar.json)、
[root job](../campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-solver-canary-20260921/job.json)。
