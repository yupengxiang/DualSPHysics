# F8 R008 native-integrity semantics proposal v2

状态：待 Terra High（high）只读设计复核。v2 是仅限静态合同的 additive 修订，不改写或覆盖 v1 与 Terra High 的 `REVISE` 历史，不修改冻结 R008 scope receipt、阈值、case 分母或既有产物。任何 `PASS` 最多允许后续静态实现/合成测试，不是用户对科学取舍的隐式批准，也不授权生产 bundle、GenCase/native decoder、solver、worker、GPU 或 queue。

## 1. v1 审查结果与修订边界

Terra High（`gpt-5.6-terra`, high）对 v1 的只读设计审查指出：

1. scope 冻结的是每例完整三周期 observation window，而非完整 `0..T_end` 保存帧集合；不能把密度、Mach、penetration 悄然扩展到全保存轴。
2. `z=±H` 只明确流体盒边界；冻结几何还存在延伸到流体区外的 wall reference boxes，尚不能把 `±H` 直接认定为实际 signed-distance 墙面。
3. scope hard-gate 列表没有独立 total-mass gate；既有 `MassFluid` bit-invariance 是 provenance/不变量证据，不能升格为新 T1 gate。
4. 15-case 聚合要用固定、机器可判定的 gate registry，不能依赖未定义的“所有必需门”。

审查认可的范围分离：全 raw finite 与 fluid-only 的 density/Mach 可分开定义；`BoundNor` 和 overlap 在证据/算法不足时保持 open；固定 15-case denominator 与零 credit 边界正确。

## 2. 注册的 T1 gate ID 集合

以下集合逐字对应冻结 scope 的 per-case gate 清单，共八项；实现不得增删，也不得把单项证据当作完整 native-integrity adjudication：

1. `native_state_finite`
2. `density_range`
3. `mach_limit`
4. `wall_penetration_limit`
5. `excluded_fluid_particles_zero`
6. `particle_overlap_absent`
7. `inclusive_three_period_window_complete`
8. `control_no_extrapolation`

`BoundNor`、总质量/连续体质量误差均不属于本 scope 清单中的独立 T1 gate。若以后希望新增，必须走独立的 root scope revision；不能由实现者在 adapter 中增加。

每个 gate 结果只允许 `defined_pass`、`defined_fail`、`open`、`missing` 四态。`defined_fail` 保留为科学负结果；`open` 表示算法/几何语义尚未冻结；`missing` 表示证据缺失或不符合绑定合同。只有 15 行全部存在、八个 gate 的定义均已冻结且每项均为 `defined_pass`，native-integrity aggregate 才可为 pass。任何 `open`/`missing` 都令 aggregate incomplete/open；任何已定义失败令 aggregate failed。不得删除、替换或缩小失败分母。

## 3. 候选逐项语义

| Gate ID | v2 候选/状态 | 适用样本与既有证据 | 未决边界 |
|---|---|---|---|
| `native_state_finite` | `defined` 的证据算法：逐个已绑定 raw solver 帧检查完整 `Pos[d]`、`Vel`、`Rhop`，覆盖全部 raw IDs（含 non-fluid）；它只提供该 gate 的逐例输入证据，不独自宣布 native-integrity pass。 | finite evidence v1 完整扫描其实际绑定的 C manifest 帧；保持 `native_integrity_evaluated=false`。 | `C` manifest 的 completeness/cadence 由 provenance 与 native output audit 证明；本 gate 不自行发明全保存轴或补帧规则。 |
| `density_range` | 候选定义：仅 fluid ID 的 `Rhop`；只对冻结 case row 指定 observation window 的 inclusive start/end ordinals 检查闭区间 `950 <= rho <= 1050 kg/m³`。窗口外 raw `Rhop` 仍必须 finite，但不额外套用此范围门。 | fluid cohort 由 B 固定；table-v2 在已绑定帧上复算 fluid density；scope 冻结三周期窗口和数值区间。 | 这是待审候选；只有 review 明确确认 population、窗口与闭区间相容后方可静态实现。 |
| `mach_limit` | 候选定义：fluid ID 在冻结 observation-window inclusive ordinals 上的实际最大速度范数 `max hypot(vx,vy,vz)/c0`；`c0=10 m/s`、门限 `<=0.0010125` 沿用冻结 parameter/scope，不拟合频率、不使用 `Uref` 替代观测速度。 | fluid ID 与 native velocity 已由 table 绑定；官方 DualSPHysics 公式把 fluid speed 与声速用于弱可压性约束。 | 该 estimator 与时间窗仍待审查；窗口之外速度不进入此注册 gate，但 raw finite 和其他完整性检查不因此跳过。 |
| `wall_penetration_limit` | `open`；不以流体盒 `±H`、wall reference box 边界、wall particle centers 或 `BoundNor` 隐式指定 physical surface。 | frozen threshold 为 `0.001875 m`；静态 geometry audit 只证明声明与公式，不证明 runtime wall surface/normal realization。 | 每个 case 必须先绑定明确 signed-distance geometry、法向方向、物理墙面位置、fluid population、观察 ordinal 与闭区间比较规则；之后再单独复核。 |
| `excluded_fluid_particles_zero` | `defined` 的候选判据：在 provenance 已证明完整的 raw solver frame 中，B 预期 fluid IDs 必须各出现一次且仅一次；missing/duplicate/unknown/unclassified ID 均失败，目标排除数为 0。 | per-case bundle/table chain 已检查精确 ID universe/cohort；不可把 table `valid` 单独当证据。 | 必须由正式 gate result 绑定逐帧 raw-ID audit 与 full-axis provenance，而不是只复用 unverified summary。 |
| `particle_overlap_absent` | `open`；exact duplicate-position 可以作为诊断统计，但不能等同于已通过 overlap gate。 | scope 只冻结布尔结果 `false`，未定义空间判据。 | 需冻结粒子/实体比较对象、距离/半径阈值、周期 x/y 最小像距离、粒子对去重、轴/时间范围及等号语义。 |
| `inclusive_three_period_window_complete` | `defined` 的候选判据：严格使用冻结 scope 的 case-specific inclusive window selector、row count、周期 seam 与原生采样 cadence；不得外推，缺失/重复/错时样本失败。 | observation-window parser、单案例 metric adapter 与 15-case metric matrix 已绑定并审核这些指标语义。 | native-integrity record 必须引用同一窗口 evidence/hash，不自行重建另一个 row set。 |
| `control_no_extrapolation` | `defined` 的候选判据：冻结 control table 全程覆盖所需输入时间区间；禁止将超出源控制表的插值外推记作有效控制。 | Definition/control pack 与现有 parser 绑定冻结控制源、单位、轴及 observation semantics。 | native-integrity result 需引用已验证的控制覆盖 receipt；不得仅因 metric result 存在便推断通过。 |

所有 density/Mach 的时间集合是冻结观察窗口，而非无限扩展到所有保存帧。`native_state_finite` 仍按其独立合同覆盖被绑定 raw 帧的全 raw state。若 B/C/D provenance 不能证明足够完整的输入帧，相关 gate 必须为 `missing/open`，不能把有限值扫描自身当成 cadence/full-axis 证明。

## 4. 非 gate 证据及执行准备

- **质量**：现有 verifier 从 B 绑定 fluid ID 数与 binary64 `MassFluid`，并逐帧验证 raw metadata bits 不变。这作为 provenance/质量不变量证据记录，不增加 T1 gate，也不做浮点乘法容差比较。若用户/独立 root 以后要求连续体质量误差或其他 total-mass T1 gate，须新增 scope revision、明确基准和容差后再实现。
- **`BoundNor`**：是 GenCase 初始几何/边界输入验证候选，不是当前八项 solver-window native-integrity gate。现有 q=.5、dp=.0075 preflight 不可推广。若未来作为 execution-admission 检查，须逐 case 证明 normal-to-boundary-ID 映射、各 dp 覆盖数、有限/方向/量纲门，并单独审查；当前不运行或复用旧 preflight。
- **overlap**：当前继续 open；不允许用精确重复坐标计数替代缺失的数值阈值。
- **wall**：当前继续 open；不能用 `±H` 公式提交数值结论。

## 5. 15-case aggregate 状态机

Aggregate 绑定冻结的 15 个 qualification case ID 列表和本节八个 gate ID registry。每个 case 必须有 B/C/D、raw-frame manifest、table、finite evidence、metric/window/control references 的精确 hash 绑定及八个 gate 状态；额外案例、重复案例、缺失案例均拒绝。

1. 任一 gate `defined_fail`：aggregate=`failed`，失败 case 留在 15 行中。
2. 无 `defined_fail`，但任一 gate 为 `open` 或 `missing`，或任一 case 缺失：aggregate=`incomplete`。
3. 仅当 15×8 项齐全、每项语义有 frozen/reviewed contract 且全为 `defined_pass`，aggregate=`passed`。

这只是 native-integrity 子聚合，不等于 full T1。即使它为 `passed`，还须由既有 metric matrix 证明 profile/cross-resolution/CFL/cadence/window 等门通过，再由单独 final T1 adjudicator 汇总；本提案不实现 final adjudicator，不改 `readiness_pass=false` 或 qualification credit=0。

## 6. 请求审查

请 Terra High 复核：

1. v2 是否严格限制在原先八项 per-case gate，而未加入 mass 或 BoundNor T1 gate；
2. density/Mach 使用已冻结的三周期 inclusive observation window，且 finite 子证据不冒充 cadence 证明，是否消除了 v1 的全轴扩张；
3. 是否应维持 wall、overlap 为 open，直到 signed-distance geometry 与 pair-distance rule 真正冻结；
4. 四态与 15×8 registry 是否能 fail-closed 保持失败分母，且不会静默漏掉/增加 gate；
5. 任何剩余单位、population、ordinal、seam、provenance 或 authority 缺陷。

审查后即使 PASS，也只可静态实现 registry、单例 evidence consumer 与 synthetic tests；仍无 production/native/solver/worker/GPU/queue 权限，无资格信用。
