# F8 R008 native-integrity semantics proposal v1

状态：Terra High（high）只读复核为 `REVISE`，已由 additive v2 取代。本文件保留该次审查的原始候选语义快照，不修改冻结的 R008 scope receipt、阈值、15-case 分母、既有证据或执行授权。它不授权生产输入读取、GenCase/native decoder、solver、worker、GPU 或 queue。

## 1. 依据与边界

冻结的 R008 scope 已登记有限状态、密度 `[950, 1050] kg/m³`、Mach `<=0.0010125`、wall penetration `<=0.001875 m`、零 excluded fluid particles、无 particle overlap 及完整三周期窗口等门，但未完整规定相应 reducer 的 population、axis、公式及端点语义。

已有实现边界：native-state finite evidence 覆盖完整 raw `Pos[d]`/`Vel`/`Rhop` 和 non-fluid 值，但固定 `native_integrity_evaluated=false`；table-v2 逐帧验证 fluid ID、位置/速度/密度和不变质量；15-case metric matrix 固定分母并聚合 metric/comparison 门，但不做 native-integrity 或最终 T1 裁决。单次 CPU/native preflight 仅是 `q=.5, dp=.0075` 的初态零信用证据，不能替代 15 个案例的 solver-state 判定或其他分辨率的 BoundNor 证明。

DualSPHysics 官方 SPH formulation 将流体与边界粒子作为不同集合，并说明弱可压 SPH 中粒子质量保持不变、密度随时间变化，声速参与 EOS 及时间步控制（[官方 SPH formulation](https://github.com/DualSPHysics/DualSPHysics/wiki/3.-SPH-formulation)）。这支持下列候选 population/质量语义，但不替代 R008 的独立审查或 root 对新语义的接受。

## 2. 候选逐案例语义

除明确写为初态几何的 `BoundNor` 外，所有时序 gate 均检查该案例完整、连续、已验证的 solver native output axis `t=0..T_end`，而非只检查观察窗口；缺帧、未知 ID、非有限输入或不完整时间轴均 fail-closed。有限值证据仍扫描全部 raw ID。任何候选 gate 失败保留为负结果，不删帧、不改分母、不重试同输入。

| Gate | 候选定义 | 既有合同可复用部分 | 尚待审查/未冻结点 |
|---|---|---|---|
| 有限状态 | 每个 raw solver 帧的全部位置、速度、密度标量均有限，包含 fluid 与 non-fluid | UPDATE-38 finite evidence 的原生 dtype 全轴扫描 | 仍是子证据，不单独产生 integrity PASS |
| 密度 | 仅对 B 冻结的 fluid ID，在完整 solver axis 检查闭区间 `950 <= rho <= 1050 kg/m³`；non-fluid 只受 raw finite gate | table-v2 已按 fluid ID 重算 density；threshold 已冻结 | 是否明确接受 fluid-only 与闭区间语义 |
| Mach | `max_(t, i∈fluid) hypot(vx, vy, vz) / c0`；`c0=10 m/s` 取冻结参数合同；完整 axis 最大值 `<=0.0010125` | fluid ID、速度、声速及 threshold 均有冻结来源 | 是否接受实际速度最大范数作为 estimator；数值累计精度/溢出处理 |
| excluded fluid | 每一 raw 帧都必须恰含 B 登记的完整 fluid ID 集各一次；缺失、重复、未知或未分类 ID 计为失败，目标 excluded 数为 0 | B/C/D 与 table-v2 已实现精确 ID/cohort 核验 | 将现有 cohort 证据映射为独立 native-integrity gate 的 receipt 字段 |
| 总流体质量 | `M(t)=N_fluid * MassFluid_B`；每帧原始 `MassFluid` binary64 bits 必须与 B 初值完全相等，故 `M(t)==M(0)`，容差为 0。此 gate 表示 fixed-mass particle conservation，不是与连续体体积质量的比较 | B/C/D 已绑定 `MassFluid`，table verifier 已核对每帧 bit-invariant provenance；粒子质量不随时间变化有官方公式背景 | 是否接受精确 metadata/invariant-mass 作为唯一总质量门；若另需连续体离散质量误差，必须单独定义且不能借用单一 baseline preflight 的值 |
| wall penetration | 对 fluid 粒子中心及冻结局部 z 轴墙面 `z=±H`，定义 `p_i=max(0, z_i-H, -H-z_i)`；报告完整 solver axis 最大值并要求 `<=0.001875 m`。周期 x/y 不作为实体墙；只声称保存帧中心位置，不声称检测未保存 timestep 的瞬态穿越 | frozen geometry、坐标系、H、周期边界和 threshold 已绑定 | 是否接受无限平面 signed-distance、fluid-only population 及仅对保存帧作结论 |
| particle overlap | 当前不提议通过条件。输出 exact duplicate-position 计数只可作诊断，不能冒充“无 overlap” | 无充分冻结定义 | 必须先定义等效粒子半径/距离阈值、周期最小像距离、比较 population、跨帧范围及精确等号规则；在此之前 gate 保持 open |
| `BoundNor` | 候选仅针对每个案例的 B/GenCase 初始几何；要求边界 cohort 的 normal 记录完整且可证明一一映射、finite、非零，并指向流体域；不要求静态壁面在 solver 帧中重复输出该数组 | 单次 baseline preflight 证明了一个 `q=.5, dp=.0075` 初态；静态审计已绑定几何声明 | 正式门限、各分辨率预期覆盖数、BI4 normal-to-ID 顺序/身份映射及逐案例 B 证据必须先冻结；现有单例结果不可推广 |

### 全矩阵聚合候选

- 消费且仅消费冻结清单中的 15 个 qualification case；每例须有唯一、通过 provenance/table/finite 结构验证的 native-integrity record。
- 每例状态区分 `passed`、`failed`、`open`、`missing`；任一已定义门失败使对应 case 为负结果，任一必需证据缺失或语义未冻结使矩阵保持 incomplete/open。
- 总 native-integrity 只有在全部 15 行完整、所有必需算法均已冻结且每个 gate 通过时才为 `passed`。不得从 15 行中移除 failed/missing/open 案例，不能用已有的 metric-matrix PASS 替代 native-integrity。
- 本聚合仍不等于最终 T1：T1 还须同时消费完整空间比较、CFL/timestep、cadence、窗口及所有已登记门，并由独立 final adjudicator 明确执行固定失败政策。所有输出继续零资格信用，直到正式执行门与实际 solver 证据分别满足。

## 3. 提请 Terra High 复核的问题

1. fluid-only density/Mach 与全 raw finite 的 population 分离是否符合冻结的 single-phase、固定壁面 R008 物理合同？
2. 按实际速度范数除以冻结声速计算完整 solver axis 最大 Mach，是否与预登记的 Mach 上限含义一致？
3. 以 exact B-bound `MassFluid × N_fluid` 作为无容差守恒门是否足够；是否应把 continuum/discretization mass error 视作另一独立 gate？
4. 固定平面墙 signed-distance 是否正确操作化 wall penetration 阈值，且报告边界是否清楚限制在保存帧？
5. `BoundNor` 是否应限于每案例 GenCase 初态；哪些既有来源能证明各 dp 的覆盖数和 normal-to-ID 映射？
6. 当前为何不能安全闭合 overlap；是否还遗漏一个已冻结的距离/碰撞定义？
7. 15-case aggregation 是否保留全部分母和失败语义且不越权形成 T1/readiness/credit？

## 4. 明确禁止的解释

这份提案不宣称设计已接受，也不授权实现以外的任何执行。Terra High `PASS`（若获得）最多解锁静态实现与合成测试；它不构成用户对算法取舍的隐式授权，不修改冻结 scope、不关闭 overlap/BoundNor 未决项、不允许生产数据、solver、worker、GPU 或 queue。正式 native-integrity/T1/readiness 仍为 false、qualification credit 为 0。
