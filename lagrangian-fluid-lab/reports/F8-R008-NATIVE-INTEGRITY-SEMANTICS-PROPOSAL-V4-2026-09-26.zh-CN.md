# F8 R008 native-integrity semantics proposal v4

状态：待 Terra High（high）只读设计复核。v4 是已审 v3 的 additive 语义澄清；不改冻结 R008 scope、八个 gate ID、任何阈值、15-case × 8-gate 分母、既有 receipt 或执行权限。v3 原文与 review 历史保留不变。v4 不实现 gate、不读取生产 bundle/frame、不运行测试、GenCase、native decoder、solver、worker、GPU 或 queue，也不产生资格信用。

## 1. 与已审 v3 的关系

Terra High 已对 v3 设计给出 `PASS`（PLAN UPDATE-44）。该 review 有两项非阻塞建议：把排除事件采集的源码描述改准确；把每个 PART 的原生事件、RunPARTs 计数关系及最终完成/flush 条件写成可机器核对的不变量。v4 仅处理这两项；不能反向解释为 v3 当时的八 gate 已闭合或已有运行证据。

八 gate ID、顺序及原定义状态继续与 `f8_r008_native_integrity_registry_v1.py` 完全一致：

1. `native_state_finite`：open
2. `density_range`：defined
3. `mach_limit`：defined
4. `wall_penetration_limit`：open
5. `excluded_fluid_particles_zero`：open
6. `particle_overlap_absent`：open
7. `inclusive_three_period_window_complete`：defined
8. `control_no_extrapolation`：defined

每行仍只有 `defined_pass`、`defined_fail`、`open`、`missing` 四态；只有 120 项齐全且全为 `defined_pass` 才能得到 native-integrity 子聚合 `passed`，而它仍不等于 full T1。

## 2. 排除事件源的精确调用条件

将 v3 中可能被读作“每个 solver step 都采集”的描述更正为：官方 CPU `JSphCpuSingle` 与 GPU `JSphGpuSingle` cell-division 路径仅在 `CellDivSingle->GetNpfOut() != 0` 时调用 `SaveFluidOut()`。因此，源码展示的是检测到被排除 fluid 后才调用的条件路径，不是无条件逐 integration-step 事件日志。`SaveFluidOut()` 的调用本身不能证明每步覆盖，也不能证明某个 attempt 实际启用了所需的 `SDAT_Binx`/`SDAT_Info` 输出。

在 `SaveData()` 中，源码分别读取 `PartsOut` 的 position、density、movement 原因计数并求和；若合计不等于 `PartsOut->GetCount()` 即抛出异常。`StInfoPartPlus` 将这三个计数写入 `RunPARTs.csv` 的 `NpOutPos/NpOutRho/NpOutMov`，`NpOut` 为三者之和；这些字段按 PART 记录。该 CSV 仅在 `SDAT_Info` 开启时产生。`DataOutBi4` 路径将该 PART 的排除 payload 写入 `PartOut`，随后清空 `PartsOut`；`PartOut` 对 `Nout==0` 不写事件 item。

## 3. Future per-PART evidence invariants（尚未实现）

只有当 source/build/input 身份、冻结 scope 与该 attempt 的完整性均被未来独立合同验证后，才能对每个冻结执行 PART 做以下交叉核对：

- RunPARTs 中每个 expected PART 恰有一条记录，PART 序列连续、无重复、无遗漏，并绑定同一个已验证执行及其原始 CSV bytes。
- 对每个 PART，`NpOut == NpOutPos + NpOutRho + NpOutMov`。匹配的 `PartOut` payload 的 `Nout`、`Idp` 数量、`Motive` 数量必须均与该 `NpOut` 相等；`Idp` 不得重复。
- 该 payload 必须具有与 frozen `PosDouble` 选择一致的恰一位置数组（`Pos` 或 `Posd`），以及 `Vel`、`Rhop`、`Motive`；所有数组的元素数必须等于 `Nout`，且 part identity 必须精确一致。
- 每个 `Motive` 只允许源码定义的枚举：`1=invalid position`、`2=invalid density/rhop`、`3=invalid movement`。按该数组重算的三个原因频数必须分别精确等于该 PART 的 `NpOutPos/NpOutRho/NpOutMov`；未知值或计数不匹配均不得通过。
- `NpOut>0` 的 PART 必须有且只有一个身份匹配的 `PartOut` PART payload；`NpOut==0` 时可没有该 PART item，但**文件不存在或 item 缺失不是零排除证据**。跨 PART 不能以总和抵消单个 PART 的缺失、重复或错配。

在上述证据全部完整且 source/attempt 身份可信时，任一 PART 的 `NpOut>0` 足以把 `excluded_fluid_particles_zero` 判为 `defined_fail`。若 PART 记录、event payload、原因直方图或引用 bytes 不一致/缺失，结果为 `missing` 或 `open`，不能据部分正计数以外的证据判 pass。只有所有 PART 对账为零并满足下节完整终止/flush 条件，才可能把该 gate 判为 `defined_pass`。

## 4. 到达冻结 `T_end` 与最后事件 flush

“完整运行到 `T_end`”必须由绑定执行的可信终止证据证明，不能只看 RunPARTs footer、文件存在、零退出码或最后一个已保存普通状态帧。Future evidence contract 至少需要同时证明：

1. 原始 argv/cwd/OPT、输入、solver/build/features 与实际执行身份对应冻结 Definition/control；相关输出模式确实启用。
2. 执行达到该 frozen row 的 `T_end`，没有 early-stop、restart/append、缺 PART 段或未登记 horizon override。最后一个已完成 PART 时间必须在冻结容差内覆盖 `T_end`；若 solver 的输出调度使最后 PART 时间不能直接满足该比较，则须由经审查的同源 runtime event trace 明确覆盖 PART 末端至 `T_end` 的区间。
3. 所有截至 `T_end` 的排除事件/原因计数在最终 `SaveData()` 中完成序列化；终止回执证明最终 flush 已完成、计数与 payload 对账成功，且没有未落盘的 pending `PartsOut`。仅因最后没有 `PartOut` item、文件缺失或 `RunPARTs` 零计数，不能推断 pending buffer 为空。

若执行证据不能证明最终时间覆盖或最后事件 flush，15×8 registry 中该 case 的 exclusion gate 必须是 `missing` 或 `open`；不得缩减分母，也不得把其他 PART 的完整性外推到终止段。

## 5. 保持不变的边界

- `native_state_finite` 仍 open：当前 evidence v1 只扫全 raw ID 上的 `Pos[d]`、`Vel`、`Rhop`，不是所有 state/control 数值 inventory 的 finite adjudication。
- `wall_penetration_limit` 与 `particle_overlap_absent` 仍 open；v4 不定义墙面几何、signed distance、periodic minimum-image、pair 去重或距离阈值。
- density/Mach 仍只适用于 v3 所定义的冻结 fluid IDs 与 inclusive observation window；control no-extrapolation 仍精确覆盖 `[0,T_end]`，不替代 finite gate。
- 总质量/MassFluid 与 `BoundNor` 仍是 provenance/其他诊断，不增加 gate。
- 即使 v4 获得 PASS，也仅解锁静态实现及合成测试；不读取生产帧、不证明任何 R008 attempt 已满足输出模式或完整终止，不授权 solver/worker/GPU/queue，不改变 `native_integrity_evaluated=false`、`T1_numerical=false`、`readiness_pass=false` 或 qualification credit `0`。

## 6. 请求 Terra High 复核

1. `SaveFluidOut()` 的 cell-division 条件调用描述是否与 CPU/GPU 源码的实际控制流一致？
2. 逐 PART `NpOut`、三个原因计数、`PartOut.Nout`、ID/Motive 数组和 reason histogram 的等式、文件/记录缺失语义是否准确且无错误 pass 路径？
3. PART 连续性、末段对 `T_end` 的覆盖、最终 `SaveData`/event flush 和 pending buffer 证据是否足够保守但可实现？是否有其他源码终止路径必须显式记 open？
4. v4 是否严格保持 v3 的八 gate、单位/阈值、窗口、15×8 分母、mass/BoundNor 排除和执行/资格边界？

只做只读设计复核；不编辑文件、不运行测试或执行工具、不读取生产 bundle/HDF5/frame，不运行 GenCase/native decoder/solver/worker/GPU/queue。
