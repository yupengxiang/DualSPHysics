# F8 R008 control query source call-graph audit（2026-09-25）

## 范围和结论

只读追踪 DualSPHysics 标准 `src/source` 的 accinput 构造、时间查询、CPU/GPU 力更新、主时间循环和运行时 `TimeMax`/终止边界，并检查一份冻结 R008 Definition/control 输入。没有改源码、构建/执行 solver，或读取 solver attempt evidence。

标准源码链已能确定：控制输入在每个 CPU/GPU 力预处理阶段以**当前 `TimeStep`** 求值；Symplectic predictor 与 corrector 都在外层循环推进 `TimeStep` 前发生，所以一宏步可能有两次相同时间的 RunCpu/RunGpu 调用，不存在此处的 `TimeStep+dt` 控制查询。外层条件是 `TimeStep < TimeMax`，且 `TimeStep += stepdt` 在 `ComputeStep()` 返回后。因此时间表检查应针对**实际调用的活动查询集合**，而非把 XML 声明的 `[TimeIni, TimeEnd]` 未裁剪地当作实际 solver query interval。

不过实际有效 `TimeMax` 可由运行参数覆盖并被输出目录中的 `TERMINATE` 修改；最小流体数也会停机，`NstepsBreak` 会按步数提前退出。`TERMINATE` 只在 `SaveData()` 后轮询。构建可执行文件所用源码树、宏/功能集、完整 CPU/GPU 动态调用闭包、multi-GPU 终止传播及运行期配置尚未与任何 R008 binary 绑定，所以**真实 no-extrapolation gate 仍 open**。

## 可复核的源码链

1. `JSph::LoadCaseParticles()` 仅当 `case.execution.special.accinputs` 节点存在时构造 `JDsAccInput`：`src/source/JSph.cpp:1048-1051`。
2. `JDsAccInput::ReadXml()` 按 active `<accinput>` 顺序解析；缺失 `time.start/end` 分别用 `0` / `DBL_MAX` 默认。`mkfluid`/`mkbound` range 会扩成若干连续 MK segment，并逐段 push 到 runtime `Inputs`。表来自二选一的 inline `<acctimes>` 或 `<acctimesfile>`；随后从加速度样本另算 velocity 表：`JDsAccInput.cpp:168-228, 238-275`。类型默认时间见 `JDsAccInput.h:59-68`。
3. 每项 `JDsAccInputMk::GetAccValues(t)` 先用精确 `double` 比较命中缓存，否则仅在 `TimeIni <= t && t <= TimeEnd` 时分别调用 `AceData->GetValue3d3d(t,...)` 和 `VelData->GetValue3d3d(t,...)`；不在窗口内则标记该项 inactive：`JDsAccInput.cpp:99-112`。`RunCpu`/`RunGpu` 对每个 `Inputs` 读取这条值并作用于粒子/调用 GPU `cuaccin::AddAccInput`：`JDsAccInput.cpp:343-414`。
4. CPU `JSphCpu::PreInteraction_Forces()` 在清零加速度后调用 `AccInput->RunCpu(TimeStep,...)`；GPU 对应地调用 `RunGpu(TimeStep,...)`：`JSphCpu.cpp:488-535`、`JSphGpu.cpp:846-893`。GPU 路径在 host 侧先按 double 时间读取/插值，再将结果交给 CUDA 加速度应用函数。
5. 外层 `JSphCpuSingle`/`JSphGpuSingle` 的 `ComputeStep_Ver()` 每步做一次 force preprocessing；`ComputeStep_Sym()` 的 predictor、corrector 各做一次，均未在两次 force 查询之间更新 `TimeStep`：CPU `JSphCpuSingle.cpp:873-931`，GPU `JSphGpuSingle.cpp:761-820`。外层循环 `while(TimeStep<TimeMax)`、调用 `ComputeStep()`、随后才 `TimeStep+=stepdt`：CPU `JSphCpuSingle.cpp:1187-1198`，GPU `JSphGpuSingle.cpp:998-1009`。
6. `JLinearValue::GetValue3d3d()` 在首/末采样区间外 endpoint-hold，在表内线性插值：`JLinearValue.cpp:344-365`。通用类有 `ConfigLoopTime()`，但在检查的 `src/source` 与 `src_mphase/DSPH_v5.0_NNewtonian/source` 中未找到调用点；loop 语义仍必须随最终构建源码身份确认，不能仅凭类能力推断启用。

## 查询时间域：修正先前合同过严假设

对 runtime entry `j`，应定义：

```text
Q_j = { t | t 实际传给该 entry 的 GetAccValues，且 TimeIni_j <= t <= TimeEnd_j }
```

这些 `t` 来自实际 CPU/GPU 力预处理调用点，时间步由主循环约束在每次调用时 `TimeStep < TimeMax_effective(t)`；一个 symplectic step 可重复查询同一个 `t`。因此可用保守上界审查活动区间：

```text
[max(TimeStepIni, TimeIni_j), min(TimeEnd_j, TimeMax_effective))
    ⊆ [table_first_time_j, table_last_time_j]
```

空活动区间需单独标注为 inactive，不能默认为目标驱动已生效。上界 `TimeMax_effective` 是动态状态，必须把 CLI/OPT overlay、运行中 horizon change、停止事件和全部查询事件绑定到同一 attempt。控制表的两个端点均须覆盖所有实际活动查询；不能使用容差掩盖越界。完整逐事件 `Q_j` 记录可替代该保守区间，前提是 source/build-bound call graph 证明日志没有漏掉调用。

这点修正了早先草案中要求有限 XML `TimeEnd` 并令整个 `[TimeIni,TimeEnd]` 落在表域内的过度约束。检查的 R008 `prod-i13` Definition 省略 `<time>`，按源码会取 `TimeIni=0`、`TimeEnd=DBL_MAX`；其 XML `TimeMax` 为 `11.832052282049933`，同目录控制 CSV 最后时刻为 `11.832052282049935`。默认 `DBL_MAX` 本身不是已发生 extrapolation 的证据；只有绑定最终运行 `TimeMax` 并证明未被扩大，才能说明实际 query 集位于控制表内。CSV/Definition 是冻结静态输入，不是 solver 运行证据。

## horizon 和终止覆盖

- `JSph::LoadConfig` 从运行 XML 读取 `TimeMax` (`JSph.cpp:786`)；`JSphCfgRun` 的 `TMAX` 可覆盖它 (`JSphCfgRun.cpp:486-489`)，`LoadConfig` 在 `cfg->TimeMax>0` 时再应用该覆盖 (`JSph.cpp:961-965`)。故只看 Definition 中 `TimeMax` 不足。
- `NstepsBreak` 在完成一个 `ComputeStep` 后按步数 break；它可令资格时域不完整，但不会在同一宏步内引入 `t+dt` 控制查询。minimum-fluid 分支在该步后把 `TimeMax=TimeStep` (`JSphCpuSingle.cpp:1207-1215`；GPU 对应 1019-1027)。两者仍须进入终态完整性证据。
- `CheckTermination()` 从 `DirOut/TERMINATE` 读取最多 127 bytes，以 `atof` 得到新时间并 clamp 到当前 `TimeStep`；它是在 `SaveData()` 后调用，不是每个宏步轮询 (`JSph.cpp:3293-3327`)。单 GPU/CPU 分支直接改 `TimeMax`；当 `Mgpu` 时只写 `TerminateTimeMax`。在所查标准源码树中 `TerminateTimeMax` 无读取点，因此 multi-GPU 的完整传播语义仍未证实。运行期监督必须监视实际 `DirOut`/文件创建与变化，并证明任何 horizon 扩展不超过冻结 endpoint。
- `TimeOut` 会影响 SaveData/终止轮询频率；不能用最后 native 输出帧反推最后一个控制查询，也不能让日志替代逐调用证明。

## 来源边界与未闭合项

本次定位文件 SHA-256：

| 文件 | SHA-256 |
|---|---|
| `src/source/JSphCpu.cpp` | `7c7c01b3a5e6809b8f6f5129f30c8aac0a4b35f1bff2e1776af4a11e8442a617` |
| `src/source/JSphGpu.cpp` | `768570e7256168632d9d93ec8d4ac70ff751572a6f1b0fc14fb5a372e873309b` |
| `src/source/JSphCpuSingle.cpp` | `a261620354e4970f99e8314ddfede1349acef5de236af32e9921af324c021608` |
| `src/source/JSphGpuSingle.cpp` | `a8652f2422e1c7656f39aaac526c432ed992fc506e48de297410bb36cabe0361` |
| `src/source/JDsAccInput.cpp` | `ea0f534e89b158fd86e41d9ea2f7a2587b6310b93350d211a3ce6169007e5423` |
| `src/source/JLinearValue.cpp` | `5059ea7113f2b5ae051f9cf37990ee0197927b9648b88e7cd957ef5d637b5f27` |

Newtonian/non-Newtonian source variants have separate copies and different hashes. 本次没有 source-to-binary build attestation，也没有冻结 R008 实际 solver executable、宏、动态库/加载代码、OPT 最终 overlay 或 supervisor 的 query event producer；因此该链只是标准源码静态链，不是对任何特定可执行文件的完整控制查询调用图。

结论：把真实 gate 保持 `open`。实现下一版合同前，应采用实际 active query set 与动态有效 horizon 的交集语义，精确绑定实际选定的 source/build/features，并覆盖全部 RunCpu/RunGpu 调用、OPT、SaveData-bound `TERMINATE`、multi-GPU/早停与全部子进程终态。没有执行 solver 或资格作业。
