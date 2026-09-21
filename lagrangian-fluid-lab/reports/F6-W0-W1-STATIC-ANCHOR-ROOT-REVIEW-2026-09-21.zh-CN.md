# F6 W0/W1 单刚体 zero-force 静态 anchor root review

审查身份：`F6_W0_W1_static_anchor_root_review_only_20260921`。本轮只执行
Python XML/JSON 写入、解析和几何质量检查；没有调用 GenCase、solver、GPU
或 queue，也没有写入 registry、ledger、matrix。

## 新输入合同

新合同目录为
`campaigns/core-v1/cfd/f6-fluid-rigid-body-w0-w1-static-anchor-v1/`，其
Definition stem 是
`CORE_F6_W0_W1_single_body_no_contact_anchor_20260921_Def.xml`。它由
`scripts/f6_w0_w1_static_contract.py` 从本轮常量直接生成，未复制或解析旧
F6 XML。旧 `F6_floating_box`、`F6_heavy_box_entry`、`F6_twin_floaters`
的 XML/HDF5 以及 parent proposal 只以 SHA-256 provenance 写入合同，均标记
`hash_only=true`、`reused_as_input=false`。

本轮 W0/W1 明确是 `gravity=(0,0,0)` 的 zero-force/units/inertia anchor。
这是为验证单位、几何、质量、惯量、身份和输出合同而设的静态控制；它不
模拟浮力、自由落体或 F6 物理响应，不能提供 F6 qualification。

合同冻结了以下单刚体、无接触 anchor：

- fluid density `1000 kg/m³`，fluid box low `(0.15, 0.05, 0.05) m`、size
  `(1.10, 0.40, 0.23) m`，free surface `z=0.28 m`；
- body `body_id=F6_W0_W1_body_alpha_20260921`、`mkbound=7`，density
  `780 kg/m³`，box size `(0.18, 0.14, 0.12) m`，COM `(0.70, 0.25, 0.65) m`，
  volume `0.003024 m³`，mass `2.35872 kg`；
- body-frame/world-aligned COM inertia tensor
  `diag(0.00668304, 0.009199008, 0.01022112) kg·m²`，初始线速度和角速度
  都为零；
- tank size `(1.40, 0.50, 0.80) m`，closed faces
  `bottom/left/right/front/back`，open face `top`；
- 最小所有声明面间距 `0.09 m`，要求为 `3*dp=0.06 m`，body 完全高于
  fluid free surface，初始 contact 明确为 false。

## W1 状态 sidecar 和事件窗

新建的 `body-state-sidecar-schema.json` 要求固定 `body_id`，并要求每个
frame 提供时间、位置、四元数、线/角速度、fluid force、fluid torque、
contact count、penetration depth 和 valid。粒子 `particle_id` 不能替代
刚体身份，particle mass 也不能替代 body mass/inertia。

`event-window-contract.json` 冻结 zero-force 模式下的 `0.0–1.5 s`、`0.01 s` 输出间隔和 151 个
期望 frame，末段 `[1.0, 1.5] s` 为 settle hold。完整事件窗必须满足严格
递增时间轴、全 frame、有限 body state/force/torque、零 contact、penetration
不超过 `1e-12`、body 留在 tank 内且保持高于 fluid free surface。当前没有
runtime sidecar，因此 receipt 保持 `event_window_complete=false`、
`event_window_status=pending_runtime_event_window`。

## CPU static gate 结果

[`preflight.json`](../campaigns/core-v1/cfd/f6-fluid-rigid-body-w0-w1-static-anchor-v1/preflight.json)
状态为 `cpu_static_gate_pass`。通过项包括：

- XML root、fresh `dp=0.02`、`mkbound/rhopbody` 和零初速绑定；
- `TimeMax=1.5`、`TimeOut=0.01`；
- body mass 与 `rho*volume` 一致；
- inertia tensor 与 box COM 公式一致且正对角；
- body 位于 tank 内、完全脱离 fluid，clearance 超过 `3*dp`；
- sidecar schema 的 body identity/字段集合完整；
- 事件窗 frame 数、cadence、uncensored/completion 要求完整。

这个 pass 只表示新 Definition/contract 在 CPU 上自洽。它不表示 solver
运行成功，不提供 body force/torque 或真实 event completion，也不产生任何
qualification credit；zero gravity 也明确不代表 F6 物理资格。

## 执行和资格边界

机器可读 proposal 为
[`proposal.json`](../campaigns/core-v1/cfd/f6-fluid-rigid-body-w0-w1-static-anchor-v1/proposal.json)。其中
`qualification_claim` 为 `none`、`qualification_credit` 为 `0`，并明确
`gencase_invoked=false`、`solver_invoked=false`、`gpu_invoked=false`、
`queue_mutation=0`、`registry_mutation=0`、`ledger_mutation=0`、
`matrix_submission=false`。

任何 static gate 失败都应保留失败 receipt 并终止，不得通过复用旧 XML/BI4/
HDF5 修复，也不得继续到 GenCase 或 solver。当前 gate 虽通过，仍只完成 W0
定义和 W1 contract，F6 仍不宣称 T1。
