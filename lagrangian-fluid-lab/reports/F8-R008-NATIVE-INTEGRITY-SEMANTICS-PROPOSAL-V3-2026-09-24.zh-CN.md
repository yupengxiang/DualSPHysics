# F8 R008 native-integrity semantics proposal v3

状态：待 Terra High（high）只读设计复核。v3 是 additive 静态合同；保留 v1/v2 与各自审查结论，不修改冻结 R008 scope、阈值、15-case 分母、已有 receipt 或执行许可。v3 不实现 gate、不读取生产 bundle/frame、不运行测试、GenCase、native decoder、solver、worker、GPU 或 queue，也不产生资格信用。

## 1. v2 复核意见与本版边界

Terra High 对 v2 给出 `REVISE`，指出三处必须保持未闭合或进一步明确的内容：

1. `native_state_finite` 仅扫描 raw `Pos[d]`、`Vel`、`Rhop`，并未完整覆盖 scope 字面要求的 `all_state_and_control_values_finite`；`control_no_extrapolation` 也不蕴含所有控制值有限。
2. 只检查已保存帧的 fluid IDs，不能证明两帧之间未发生排除；必须固定排除事件的真值来源、覆盖区间、完成标志和缺失/提前终止语义，否则此 gate 保持 open。
3. `control_no_extrapolation` 必须明确覆盖闭区间 `0..T_end`，不能使用未定义的 “required input interval”。

本版仍使用 v2 已固定的八个 gate ID 与 15×8 分母，不把 mass、`BoundNor` 或其他诊断升格为 T1 gate。以下候选语义只有 Terra High 明确审查接受后才可作为静态实现合同；审查 PASS 仍不代表任何 case 已通过。

## 2. 固定 gate registry 与状态机

八个 ID 必须逐字对应冻结 scope；不得增删或动态发现：

1. `native_state_finite`
2. `density_range`
3. `mach_limit`
4. `wall_penetration_limit`
5. `excluded_fluid_particles_zero`
6. `particle_overlap_absent`
7. `inclusive_three_period_window_complete`
8. `control_no_extrapolation`

每个 case/gate 只允许 `defined_pass`、`defined_fail`、`open`、`missing`。`defined_pass/fail` 要求语义合同已冻结且证据充分；`open` 表示算法/对象/完整性语义尚未冻结；`missing` 表示所需 receipt/字段/覆盖证据缺失或不满足绑定合同。无论状态如何，失败行必须留在冻结 15-case 分母中。

aggregate 固定为 15 cases × 8 gates：存在 `defined_fail` 时为 `failed`；没有失败但有 `open`、`missing` 或缺行时为 `incomplete`；只有 120 项齐全、所有 gate 语义已冻结且逐项 `defined_pass` 才为 `passed`。该 native-integrity 子聚合仍不等于 full T1。

## 3. Gate 候选语义

| Gate ID | v3 状态/候选语义 | 证据与 fail-closed 边界 |
|---|---|---|
| `native_state_finite` | **open**。有限性范围必须由可机读 inventory 精确枚举，至少区分每粒子 solver state、数值 metadata 与 control values；每一纳入项需绑定 raw 名称、dtype、shape/数量、population、单位/语义和来源 hash。 | 现有 finite evidence v1 覆盖已绑定帧的全 raw IDs 上 `Pos`/`Posd`、`Vel`、`Rhop`，并不扫描全部浮点扩展数组，也不形成完整 control finite 证据。metadata binder 对其绑定的浮点 metadata 拒绝非有限值，但这不定义 scope 的完整 state inventory。control pack 对数值字段的解析/比较也不能替代逐字段 finite 结果。扩展数组不得未经 scope 归类便静默跳过或一概视为 state。inventory 未冻结、某项漏扫或绑定不完整时只能 `open/missing`。候选 inventory 至少明确主状态数组及控制 CSV 全部七列在 `[0,T_end]` 的 finite 检查；是否包含其他数值 metadata/扩展数组，须经静态合同逐项定义。 |
| `density_range` | 待审候选：冻结 fluid IDs；只对 per-case 冻结 observation window 的 inclusive ordinals 检查闭区间 `950 <= Rhop <= 1050 kg/m³`。 | 不扩到 observation window 外；window 外仍由 finite gate 检有限性。未知 fluid ID、重复/缺样或窗口绑定不符不能通过。 |
| `mach_limit` | 待审候选：冻结 fluid IDs 与 observation window inclusive ordinals；计算 `max hypot(vx,vy,vz)/c0`，其中 `c0=10 m/s`，阈值 `<=0.0010125`。 | 使用实际速度，不以 `Uref` 替代；不得拟合或改变阈值。窗口外速度不进入此 gate，但仍受 finite gate 覆盖。 |
| `wall_penetration_limit` | **open**。不得把 `±H`、wall reference box 边界、wall particle centers 或 `BoundNor` 默认为实际物理墙面。 | 虽有冻结阈值 `0.001875 m`，仍缺逐例 signed-distance geometry、方向、fluid population、观察 ordinal 与闭区间比较规则。 |
| `excluded_fluid_particles_zero` | **open**。静态源码审计识别出候选事件证据：CPU/GPU 的 `SaveFluidOut()` 每步收集 fluid exclusions，`JSph::AddParticlesOut()` 累积到下一个 `SaveData()`；`PartOut` 保存非零事件记录，`RunPARTs.csv` 逐 PART 记录 `NpOut` 及三个原因计数。 | 源码证明的是记录机制候选，不是 R008 runtime 覆盖证据。`PartOut` 在零事件时不写事件 item；`RunPARTs.csv` 仅在 Info 输出开启时生成；现有 R008 C/D/finite evidence 绑定链未证明这两类记录及成功完成到 frozen `T_end`。故缺文件、零 `PartOut` 行或只检查保存帧 ID 均不能证明零排除。要将语义关闭，未来静态合同至少要求：固定 solver/source/build/input 身份；证明 Binx 与 Info 输出均开启；绑定完整 `RunPARTs.csv` PART 序列及每段 `NpOut/NpOutPos/NpOutRho/NpOutMov`；对非零计数绑定相应 `PartOut` 原生记录并校验行数、PART 与原因计数；证明执行按冻结终止语义完整到达 `T_end`，无中断、early-stop、遗漏保存段；零事件时要求完整成功运行 receipt 且全段计数均为零，不能依赖 `PartOut` 文件缺失。任一正 `NpOut` 可判 `defined_fail`；覆盖/文件/计数不一致不得判 pass，记 `missing` 或 `open`。若无法证明输出调用覆盖整个执行区间，则继续 open。 |
| `particle_overlap_absent` | **open**。 | 尚缺参与粒子集合、距离/半径阈值、周期 x/y 最小像、pair 去重、时间轴与等号语义；精确同坐标计数仅可作诊断。 |
| `inclusive_three_period_window_complete` | 待审候选：逐例引用既有冻结 inclusive window selector、row count、period seam 与原生 cadence evidence。 | 复用既有绑定 window receipt/hash，不另建 row set；缺帧、重复、错时、cadence/provenance 缺失不能 pass。 |
| `control_no_extrapolation` | 待审候选：每例 `T_end` 定义为冻结 Definition/control row 的 `TimeMax`；现有 R008 pack 将其设为 `observation_end_s`。要求 source control table 覆盖闭区间 `[0,T_end]`，起点为 0，末端按已冻结校验容差匹配 `TimeMax`，采样轴单调且符合该 row 的冻结采样步长；solver 实际 `TimeMax` 与绑定 Definition/control hash 一致，任何读取均不得落在表端点之外。 | 当前 pack 写出并验证到 exact `TimeMax` 的控制表，但 per-case native-integrity 结果仍须绑定源 CSV、Definition、实际 solver invocation/完成证据。越界、缺失端点、篡改/错绑或无法证明运行 horizon 时不得 pass。控制字段的 finite 检查单独归入 `native_state_finite`，不能由本 gate 推断。 |

### 3.1 排除事件源的源码依据和未证范围

只读查看官方 solver 源码：`JSphCpuSingle::SaveFluidOut()` 与 `JSphGpuSingle::SaveFluidOut()` 在调用 `AddParticlesOut()` 前取得当前被排除 fluid；`JDsPartsOut` 注释说明缓存到下一份 `PART`；`JSph::SaveData()` 汇总缓存的原因计数，保存非零 `PartOut` 后清空缓存；`JPartOutBi4Save::SavePartOut()` 在 `Nout==0` 时不写 item；`SaveRunPartsCsv()` 的 `NpOut` 注释是“自上一个 PART 以来的排除 fluid 数”，但该 CSV 受 `SDAT_Info` 控制。故未来候选应以“每段计数 + 非零原生事件记录 + 完整执行终止证据”联合证明，而不是仅凭 `PartOut` 是否存在。

本段只证明源码中的静态机制。它不证明冻结 R008 实际启用了 `SDAT_Binx`/`SDAT_Info`，不证明所有 solver step 均被正确积累/发布，不证明 R008 的运行到达 `T_end`，也不把历史其他 case 的 `PartOut` 产物转用为 R008 证据。source hash/build/invocation、输出完整性与终止收据仍须逐 case 绑定后另行审查。

## 4. 非 gate 项与固定排除项

- 总质量与 `MassFluid` bit invariance 保持 provenance/不变量证据，不新增 T1 gate；新增质量门须另行 root scope revision。
- `BoundNor` 仍非本八项 solver-window T1 gate；任何 future prelaunch gate 需单独逐例合同与授权审查。
- density/Mach 不扩展到完整保存轴；wall 与 overlap 继续 open，直到对象和算法真的冻结。
- 不从静态源码、旧 preflight 或其他案例推断 R008 运行结果。

## 5. 资格与执行边界

本提案及其静态审查不改 `native_integrity_evaluated=false`、`T1_numerical=false`、`readiness_pass=false` 或 qualification credit `0`。即使 Terra High 对 v3 给出 PASS，下一步至多是静态实现及临时合成测试；不得读取生产 bundles/frames、调用 GenCase/native decoder、启动 solver/worker/GPU/queue 或扩大资源范围。wall/overlap/native-state inventory/exclusion event contract 若仍为 open，则对应 gates 与 aggregate 必须保持 open/incomplete。

## 6. 请求 Terra High 复核

1. 是否准确处理 v2 关于 `all_state_and_control_values_finite` 的缺口：gate 显式保持 open，并要求冻结完整机读 inventory，而没有把当前三数组扫描说成完整 pass？
2. `PartOut` + 全段 `RunPARTs.csv` + source/input/build 绑定 + 完整至 `T_end` 终止证据是否是排除 fluid 的合理候选；零事件不依赖缺失的 `PartOut` 文件这一点是否充分？是否仍有源码路径会丢失/延迟事件或计数口径差异？
3. control gate 是否精确覆盖闭区间 `[0,T_end]`，且把 control finite 与 no-extrapolation 分开？
4. 八 gate registry、15×8 fail-closed denominator、mass/BoundNor 排除项及 wall/overlap open 是否全部保持不变？
5. 是否存在其他定义、完整性、单位、时间窗口或权限边界缺陷？

只做只读静态设计复核；不改文件、不运行测试或工具、不读取生产数据，也不执行任何 GenCase/native/solver/worker/GPU/queue 作业。
