# F8 R008 native-integrity semantics proposal v5

状态：待 GPT-6 Luna Max 只读设计复核。v5 是已审 v3 与 v4 的 additive 修订，不改冻结 R008 scope、八个 gate ID、阈值/单位、15-case × 8-gate 分母、历史 receipt 或执行权限。v3/v4 与既有审查记录均保留不变。v5 仅修复 v4 review findings 并收紧未来证据语义；不实现 gate、不读取生产 bundle/frame、不运行 GenCase、native decoder、solver、worker、GPU 或 queue，也不产生资格信用。

## 1. 冻结 gate registry v1 的状态约束

状态与允许结果必须逐项服从 `scripts/f8_r008_native_integrity_registry_v1.py` 中冻结的 `GATE_REGISTRY`，不得仅根据科学判据定义推导状态。v1 的 outcome domain 是：

| Gate | 冻结定义状态 | v1 允许状态 |
|---|---|---|
| `native_state_finite` | open | `defined_fail` / `open` / `missing` |
| `density_range` | defined | 四种注册状态 |
| `mach_limit` | defined | 四种注册状态 |
| `wall_penetration_limit` | open | `open` / `missing` |
| `excluded_fluid_particles_zero` | open | `defined_fail` / `open` / `missing` |
| `particle_overlap_absent` | open | `open` / `missing` |
| `inclusive_three_period_window_complete` | defined | 四种注册状态 |
| `control_no_extrapolation` | defined | 四种注册状态 |

“四种注册状态”指 `defined_pass`、`defined_fail`、`open`、`missing`。因此 v1 下 `native_state_finite`、`wall_penetration_limit`、`excluded_fluid_particles_zero`、`particle_overlap_absent` 均不能得到 `defined_pass`。特别是，即使未来可信证据证明全部 PART 的排除计数为零，`excluded_fluid_particles_zero` 也只能保持 `open` 或 `missing`；若要将它定义并判 pass，必须另行提出并审查新的、版本化 registry，不能在本提案或调用端绕过 v1。

对 exclusion gate，只有经独立来源/attempt 认证且 PART 计数、PartOut payload、ID 与 Motive histogram 完整一致的正排除事件，才允许报告 `defined_fail`。若 attempt 身份或证据链不可信，即使诊断 parser 看见非零数据，也保持 `open`/`missing`。结构缺失、未知字段、证据不完整或只观察到全零，均不得升级为 pass。15×8 的固定分母不变。

## 2. 排除事件与逐 PART 对账（仅为未来证据候选）

官方 CPU `JSphCpuSingle` 和 GPU `JSphGpuSingle` cell-division 路径仅在 `CellDivSingle->GetNpfOut() != 0` 时调用 `SaveFluidOut()`；这不是每个 integration step 的无条件事件日志，也不证明 attempt 启用了 `SDAT_Binx` / `SDAT_Info`。

在 `JSph::SaveData()` 中，源码求和 `PartsOut` 的 position、density、movement 原因计数，并在总数不等于 `PartsOut->GetCount()` 时抛出异常；`StInfoPartPlus` 将三原因计数和总计写入 `RunPARTs.csv`。`SavePartData()` 仅在 `DataOutBi4 && PartsOut->GetCount()` 时调用 `SavePartOut()`，随后清空 `PartsOut`。`JPartOutBi4Save::SavePartOut()` 在 `Nout==0` 时不写 event item。因此文件或 item 缺失不是零排除证据。

未来对冻结执行 PART 做对账时，至少要求：

- 同一已认证 attempt 的 `RunPARTs` 恰含冻结输出调度所期望的 PART 序列：连续、无重复、无遗漏；逐行绑定原始 CSV bytes、PART、step/time 与执行身份。
- 每行 `NpOut == NpOutPos + NpOutRho + NpOutMov`。若 `NpOut>0`，恰有一个身份相符的 `PartOut` payload；其 `Nout`、唯一 `Idp` 数和 `Motive` 数均等于 `NpOut`。不能跨 PART 合计抵消缺失或重复。
- `Pos` 与 `Posd` 按冻结 `SvPosDouble` 恰选其一；并要求 `Vel`、`Rhop`、`Motive`。各数组首维精确等于 `Nout`，particle identity 精确一致。Motive 仅允许 `1=invalid position`、`2=invalid density/rhop`、`3=invalid movement`；重算的原因频数必须分别等于 RunPARTs 三列。
- `NpOut==0` 时可没有该 PART 的 PartOut item，但该零值仍须来自可信、完整且绑定同一 attempt 的 RunPARTs 记录，并满足本节终止条件；它单独不构成 gate pass。

当前 `f8_r008_partout_runparts_diagnostic_v1.py` 的 bounded parser 只接受 `PartOut_<block>.obi4` 文件名及 root `Piece=0,Npiece=1`，不解析 `_pNN` 多-piece 输出。故 v5 的 parser 证据适用域最多为 CPU 单 piece 诊断路径；不得据此声称覆盖 GPU 或多-piece。若未来冻结执行使用 GPU/多-piece，相关 gate 必须为 `open`/`missing`，直至新的 parser 版本实现并审查完整 piece 清单、跨 piece 的 PART 唯一性/汇总关系及身份绑定。

## 3. `T_end`、实际 timestep、终止及最终 flush

不为 PART 终点臆造浮点容差。冻结 scope 的 `1e-12` 只用于已定义的观测窗口语义，不是 `T_end` 运行完成容差。官方 CPU 单步循环先计算并应用 `stepdt`，更新 `TimeStep`，再检查是否达到 `TimePartNext` 并调用 `SaveData()`；dt 不因 `TimeMax` 而截断。`TimeStep>=TimePartNext` 或 minimum-fluid 条件触发才保存主 PART；minimum-fluid 会改写 `TimeMax`。循环后 `FinishRun()` 不保证补做最终 `SaveData()`。因此“日志末行接近 T_end”、footer、零退出码或普通状态帧均不足以证明完成。

未来可信 runtime trace 必须至少共同证明：

1. 精确 argv/cwd/OPT、Definition/control、输入、solver/build/features 和启动状态绑定同一冻结 case；完整输出模式证明 `SDAT_Info`、`DataOutBi4` 等所需 writer 实际启用。多次启动、restart/append、未登记 horizon override 或 GPU/multi-piece 超出已验证 parser 域时，不能沿用本合同判 pass/fail。
2. 运行时有效 `TimeMax` 未被 TERMINATE 请求、minimum-fluid stop、debug `NstepsBreak` 或其他路径改写，且没有 early-stop。逐步时间证据应显示最后一个应用步从 `t_before < T_end` 前进到 `t_after >= T_end`（按实际 binary64 值比较，不加新容差），随后是正常 horizon termination；仅声明“覆盖到 T_end”不够。
3. 最后应用步对应的最后一次成功 `SaveData()` 有可验证调用/完成记录，并与 RunPARTs 的末 PART、原始输出及该 PART 的排除计数绑定。若输出 cadence 使最后应用步没有触发主 PART 保存，则 `FinishRun()` 不会自动补存，terminal exclusion gate 必须为 `open`/`missing`。
4. 对最终 `SaveData()`，证据必须证明 `DataOutBi4` 写入（当该路径应有非零 event 时）、RunPARTs 行落盘/闭合、成功完成 `PartsOut->Clear()`，且不存在未落盘 pending event。PartOut 零事件时无 item 是允许格式，但只有可信零计数的 RunPARTs 和成功终止/flush 轨迹可保留为诊断零；仍不能突破 v1 的 gate outcome domain。

源码中 `CheckTermination()` 可在 `SaveData()` 路径处理动态终止请求，CPU loop 也可由 minimum-fluid/debug break 改变退出方式；任一相关条件未被运行轨迹明确排除时，case 的 exclusion gate 记 `open` 或 `missing`。以上合同仍需实际审查可采集的 runtime trace 格式；静态源码和 parser 输出本身不能满足这些执行证据条件。

## 4. 保持不变的边界

- 八 gate 的语义、单位/阈值、15×8 分母、失败分母、观测窗口、mass/`BoundNor` 排除及 full-T1 聚合逻辑均不变；v5 不修改冻结 scope、registry 或历史 receipt。
- `native_state_finite` 仍未定义全 native state/control inventory；wall penetration 与 overlap 仍缺经审查的几何/距离判据，不能通过。
- density/Mach、inclusive window 与 control no-extrapolation 仍只按各自已审合同定义；一个 gate 的通过不替代另一个 gate。
- 仅静态设计语义，无生产 attempt、可信执行源/身份、运行轨迹或 native-integrity evidence；不改变 `native_integrity_evaluated=false`、`T1_numerical=false`、`readiness_pass=false`、qualification credit `0`，也不授权 solver、worker、GPU 或 queue。

## 5. 请求 GPT-6 Luna Max 复核

1. v1 registry 每个 open gate 的允许 outcome domain 与“全零 exclusion 仍不能 pass”是否精确一致？
2. CPU loop 的 timestep crossing、动态 `TimeMax`/early-stop 路径、`SaveData()` 调度、`FinishRun()` 不补最终 PART 的描述是否准确？
3. CPU 单-piece parser 边界、逐 PART 事件/RunPARTs 对账与缺失语义是否足够保守，是否仍存在未排除的 false-pass 路径？
4. v5 是否严格保持冻结 scope、八 gate/15×8 分母、阈值与执行/资格边界，且没有把未来 runtime 条件写成已有证据？

只做只读设计复核；不编辑文件、不运行测试或工具、不读取生产 bundle/HDF5/frame，不运行 GenCase/native decoder/solver/worker/GPU/queue。
