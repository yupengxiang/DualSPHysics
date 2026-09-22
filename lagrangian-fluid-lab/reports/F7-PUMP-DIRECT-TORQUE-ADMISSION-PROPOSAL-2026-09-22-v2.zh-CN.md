# F7 直接力矩锚点 Root Admission 提案 v2（2026-09-22）

本提案已补齐真实 Pump 运动轴、独立 Definition/输出命名空间、精确权限计数、ComputeForces 命令、native BI4 完整性要求、结果字段语义、数值门槛和失败策略；它仍然是待 root review 的提案，不是授权收据。

## 真实输入与命令

官方 `CasePump_Def.xml` 的轴点为：

- `p1=(-0.0176,-0.29,-0.7275) m`
- `p2=(-0.0176,-0.49,-0.7275) m`
- 世界 Cartesian 坐标，右手定则沿 `p1 -> p2`
- prescribed motion 从 `t=0.5 s` 开始；计划检查 `0.5–2.5 s` 的 active interval

计划中的唯一 ComputeForces 调用为：

```text
ComputeForces_linux64 \
  -dirdata campaigns/core-v1/cfd/f7-pump-direct-torque-anchor-v1/native/data \
  -filexml campaigns/core-v1/cfd/f7-pump-direct-torque-anchor-v1/input/F7_pump_torque_anchor_Def.xml \
  -first:0 -last:300 -onlymk:2 -viscoauto \
  -momentaxisin:-0.0176:-0.29:-0.7275:-0.0176:-0.49:-0.7275:pump_axis_in \
  -momentaxisex:-0.0176:-0.29:-0.7275:-0.0176:-0.49:-0.7275:pump_axis_ex \
  -savecsv campaigns/core-v1/cfd/f7-pump-direct-torque-anchor-v1/compute-forces/pump-force-moment.csv \
  -saveascii campaigns/core-v1/cfd/f7-pump-direct-torque-anchor-v1/compute-forces/pump-force-moment.asc
```

该命令目前没有执行。计划中的 301 个 native frame 必须包含 `mk=1` 流体和 `mk=2` 移动边界；粒子 ID 数量、质量元数据、frame 范围和 decoder 哈希必须在接受前写入不可变 integrity receipt。

## 权限边界

root 若批准，只能批准一次 fresh CPU anchor：GenCase=1、native CPU solver=1、native decode=1、ComputeForces=1；GPU、job submission、queue、registry、ledger、matrix、T1/T2 denominator 和 training 均为 0。即使诊断门全部通过，也不产生任何 Core credit、T1/T2 注册或训练释放。

## 预注册门槛

- 时间轴必须唯一、无缺帧/重复帧，并与 native/control sidecar 在 `1e-9 s` 内对齐。
- `-onlymk:2` 必须严格成立；空选择、缺字段、NaN 或非有限力矩直接失败。
- active interval 内至少 2 个 frame 满足 `|tau_axis| >= 1e-8 N·m`。
- 能量收据必须提供 `tau·omega` 与流体机械能变化、黏性/重力项的同轴比较；相对残差阈值为 `0.10`，绝对能量底限为 `1e-12 J`。
- 官方帮助中的 `[Nn]` 标记若无法被结果解析器无歧义映射为 `N·m`，则拒绝接受，不静默改名。

任何门失败均为 zero credit，保留失败分母，禁止同输入重试；重试必须换 scope/revision/case/namespace 并重新 root review。当前仍保持 `proposal_pending_root_review_not_authorized`，没有执行求解器、解码或 ComputeForces。
