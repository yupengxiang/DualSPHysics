# F6 v9 protected CPU solver canary（2026-09-21）

这次运行是 F6 显式刚体物理锚点 v9 的一次独立 root-authorized canary。它只验证
solver 输出、body-state/force/torque 侧车和事件窗接口，不提供 F6 T1 或任何生产
资格 credit。

## 授权和输入

- root review：`root_review_authorized_one_cpu_solver_canary`。
- job：`F6_explicit_body_v9_protected_solver_canary_20260921`，`attempt=1`，
  `input_count=1`，`same_input_retry=false`，`resume=false`。
- solver：官方 `DualSPHysics5.4CPU_linux64`，32 threads，
  `CUDA_VISIBLE_DEVICES=""`，`tmax=1.5 s`，`tout=0.005 s`。
- 没有 GPU 启动、队列提交、registry、ledger 或 matrix 写入。
- 授权 job、root review、输入哈希和单次 worker 哈希都保存在
  `campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-solver-canary-v9-20260921/`。

## 运行结果

总回执是 `solver_completed_hard_failure`。求解器本身返回 0，`Run.out` 报告
`TimeMax=1.5`、`TimePart=0.005`、`PART files=301`、排除粒子为 0。原生帧审计
得到编号 `0..300` 的 301 个帧，所有帧的粒子数组有限、身份唯一且固定；fluid
数量为 15048、floating body 数量为 693；没有粒子越过开顶。

body 侧车也成功生成 301 行。首次接触时间为 `0.2150725530666 s`，位于预登记
窗口 `[0.18691412628791773, 0.2269141262879177] s` 内。闭合面接触、闭合面
穿透和开顶质量流的硬门均为零，body identity 和力／力矩字段均有限。

## 为什么保留为 hard failure

DualSPHysics 实际按照 `TimePart` 保存“达到下一个输出目标后的第一帧”，所以
原生物理时间不是逐帧恰好相差 `0.005 s`。本次实测相邻时间差范围为
`0.004808909248646298--0.005187295575296902 s`，末帧为
`1.500144461103044 s`。因此严格的 `native_time_cadence_exact` 和侧车
`sidecar_cadence_exact` 未通过。

同一原因使严格闭区间 `[1.0,1.5] s` 内有 100 个实际帧（从约 `1.00014` 到
`1.49505 s`），第 301 帧位于 `1.500144 s`；`settle_hold_complete` 和
`settle_hold_uncensored` 因而未通过。这个回执不能被解释为“物理资格通过”，也
不能通过放宽本次回执的门槛来补发 credit。

此外，sidecar 中从 `t>=1.0 s` 开始使用的 `settle_hold` 只是当前实现的时间段
标签，并没有证明刚体已经达到物理平衡。该段的线速度范数约为
`0.025--0.252 m/s`、角速度约为 `0.109--0.731 rad/s`；因此 v9 没有通过、也
没有尝试声明 equilibrium gate。下一版必须把这段改称 observation hold，或者
另行预登记位置、速度、角速度及力／力矩的稳定阈值和持续时间。

## 结论和后续边界

本次唯一 solver attempt 已执行并保留全部失败分母；不进行同输入重试、resume 或
科学矩阵登记。F6 仍然是 `T1=false`、`qualification_claim=none`、
`qualification_credit=0`，Core 的第三 T1 家族和两个宏观 T2 家族门仍未满足。

若继续 F6，必须另立新的 Definition／事件合同，明确采用 DualSPHysics 的实际
自适应 `TimePart` 时间轴并重新做独立 root 评审；当前 v9 输入不能因为这次运行
产生完整帧而重跑或改判。

已准备一个不执行计算的 v10 root-review-only 合同草案：
`campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-cadence-revision-v10-20260921/proposal.json`。
它只把 v9 回执作为 hash-only 负证据，要求全新的 Definition/XML/BI4 和新的
case identity；它把 `settle_hold` 改为不声称平衡的 `observation_hold`，并预先
规定实际 `TimeStep` 的最大间隔、末帧 overshoot 和 bracket 覆盖门。该草案尚未
获得 root solver 授权，也没有启动 GenCase、solver、GPU 或队列。

原始回执和侧车：

- `campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-solver-canary-v9-20260921/attempt-001/execution-receipt.json`
- `campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-solver-canary-v9-20260921/attempt-001/native-frame-audit.json`
- `campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-solver-canary-v9-20260921/attempt-001/body-state-force-torque-sidecar.json`
