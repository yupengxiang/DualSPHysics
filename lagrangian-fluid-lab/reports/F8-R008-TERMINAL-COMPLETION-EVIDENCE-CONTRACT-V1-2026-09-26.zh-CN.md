# F8 R008 terminal completion and flush evidence contract v1

状态：只读设计提案，待独立复核。它是 native-integrity semantics proposal v5 所留 P3 的具体化，不实现 verifier、不增加 gate、不修改 registry/scope/分母或权限，不读取生产数据、不执行 GenCase/native decoder/solver/worker/GPU/queue。即使本合同未来获审查通过，也仅定义证据判读条件，不提供 trusted worker/source attestation，也不使任何 R008 gate 获得 `defined_pass`。

## 1. 目标与固定适用域

目标是定义一种从 DualSPHysics v5.4 现有 CPU 单-piece 输出推导“最后一帧确由最终应用 timestep 的成功 `SaveData()` 写出，随后程序正常结束”的可复算证据，不增加 solver instrumentation。证据仍必须由未来可信 supervisor 绑定到确切 attempt；未经认证的日志、CSV、BI4、argv 和退出码只是 caller-supplied claims。

适用域严格限于：新鲜 `PartIni=0`、`TimeStepIni=0` 的 R008 CPU 单 piece run；同一个 solver process；无 restart/append；冻结 Definition/control 与单一输出目录；`SDAT_Info`、`SDAT_Binx` 和需要的 `DataOutBi4` writer 均按冻结执行合同启用。GPU、多-piece、restart、append、其他 writer/source 语义一律 `open/missing`。

## 2. 官方源码给出的可观测对应关系

- CPU 初始化阶段先调用一次 `SaveData()`，随后 `PartNstep=0`；该首行 `RunPARTs.Steps` 为零。主循环每次保存后将 `PartNstep=Nstep`，所以每条后续 `RunPARTs.Steps` 是本次与上次保存之间的 integration-step 增量。
- `RunPARTs.csv` 每次 `SaveData()` 由 `SDAT_Info` 分支写一行，字段含 `Part`、`TimeStep [s]`、`Steps`；`TimeStep` 使用官方 `RealStr(double)` 16 位文本。正常 `FinishRun()` 再追加 final footer。
- 同一个 `SavePartData()` 以 `Part`、binary64 `TimeStep` 与 `Nstep` 写入主 BI4 的 `PART_####` metadata：`Cpart`、`TimeStep`、`Step`。主 BI4 实际 PartInfo/particle writer 由 `SDAT_Info`、`SDAT_Binx` 控制。
- `SavePartData()` 写 RunPARTs 和主 BI4 后，在有非零排除数且 `DataOutBi4` 启用时写对应 `PartOut`，返回到 `JSph::SaveData()` 后执行 `PartsOut->Clear()`；之后 CPU loop 更新 PART 调度状态。
- CPU 正常总结包含 `Simulation finished`、`Steps of simulation: Nstep`、`PART files: count`；minimum-fluid stop 会以 `Simulation INTERRUPTED` 结束并有对应 warning。Debug `NSTEPS` 则可在 horizon 前 break，却仍沿用 `FinishRun(false)`，所以不能只靠 `Simulation finished` 排除它。

上述源码描述的复核定位为 `JSphCpuSingle.cpp` 1163–1176、1211–1220、1328–1342；`JSph.cpp` 2981–3017、3062–3082、3187–3203、3522–3547；`JPartDataBi4.cpp` 316–333；`JSphCfgRun.cpp` 501–507。未来实现须绑定这些源文件和实际 solver build 的完整 SHA，不得只引用行号。

## 3. 未来 receipt 的最小严格形状

receipt 外层采用版本化 exact-field schema `core.cfd.f8.r008_terminal_completion_evidence.v1`。未知字段拒绝；消费端必须从绑定的原始 bytes 重算所有 derived 值，不能信任 caller 预先填写的 `pass/complete/flush` 标志。最小字段分组为：

- `identity`：固定 `scope_id/case_id`、raw scope receipt 与 Definition/control pack SHA-256、attempt ID/nonce、`PartIni=0`/fresh-run 声明。
- `solver`：官方 source-file→SHA-256 map、实际 executable SHA-256、build/config identity、CPU-single-piece 声明。
- `invocation`：原始 argv bytes/SHA-256、cwd 身份、OPT 原始 bytes/SHA-256、从 frozen Definition 推导的 `T_end` IEEE-754 hex；明示 `TMAX` override、`NSTEPS`、`SVSTEPS` 的解析结果，以及 `SDAT_Info`、`SDAT_Binx`、PartOut/DataOutBi4 的实际启用状态。
- `process`：supervisor task/worker identity reference、PID 与 OS process-start identity、单调时钟起止、raw wait status、exit code 与 terminating signal；只能有一个执行 attempt 和一个 output writer。
- `termination_watch`：运行期间保留的 `TERMINATE` 路径 create/write/rename/unlink 事件清单；若 supervisor 无法覆盖该路径的完整存活区间，则终止来源为 `unresolved`，不得当作空事件集。
- `artifacts`：原始 solver log、RunPARTs.csv、每个预期主 BI4 与 PartOut piece 的相对路径、文件类型/大小、SHA-256、设备/inode/link metadata；末端以 held-FD 重新校验 identity/hash。绝对路径不是身份。
- `derived_terminal`：由 raw artifacts 重算的 simulation terminal text、terminal `Nstep`、`PART files` 数、RunPARTs row count/`Steps` sum/last row、final main-BI4 `Cpart/Step/TimeStep`、各等式布尔值、`TimeStep >= T_end`；任何 bool/状态字段不得由 caller 覆盖计算结果。

此形状描述数据与证明职责，不指定尚不存在的 trusted issuer/key。`process.worker_identity_ref` 与任何签名/attestation 只有在未来正式 trust registry 可验证其发行者、有效期、撤销状态和签名覆盖的 canonical receipt bytes 时才有来源权威；当前没有这样的已登记 supervisor，因此该字段缺失或不可验证时整份结果永久 diagnostic-only。

## 4. 最终 PART 可复算的必要等式

对同一冻结、无 restart/append 的 attempt，必须同时成立：

1. `RunPARTs.csv` 通过已审 bounded parser；行序及 Part ID 与冻结输出 cadence 完全相符，初始 Part/time/Steps 为 `0/0/0`，无重复、遗漏或尾部未提交行，final footer 存在。
2. 将每一行非负整数 `Steps` 精确求和（先按 parser 规则移除官方千位分隔符），结果等于最终 solver log 中 `Steps of simulation` 的 `Nstep`；行数与终端 `PART files` 计数相符。
3. 最后主 BI4 frame 的 `PART_####` metadata 满足 `Cpart == RunPARTs.Part`、`Step == Nstep`，且 `TimeStep` 以 BI4 原生 binary64 解码；它与 RunPARTs 的官方 `RealStr(16)` 时间文本按已审 parser 规则一致，并且精确满足 `TimeStep >= frozen T_end`，不使用容差。
4. 冻结 Definition 的有效 `TimeMax` 精确为冻结 `T_end`；执行 argv/OPT 无 TimeMax 覆盖、`NSTEPS` 非零值或 `SVSTEPS` 改变 cadence；从 frozen initial state 开始，非 restart/append。CPU 源码因此保证末步是在 `TimeStep < T_end` 时进入主循环、应用完整正 `stepdt` 后跨至 `TimeStep >= T_end`；最后 PartInfo 的 `Step == Nstep` 且 RunPARTs 增量总和闭合，证明最后一次 `SaveData()` 正发生于末个已应用步。
5. log 为 `Simulation finished`，不是 `INTERRUPTED`；不存在 minimum-fluid、`TERMINATE` horizon update、非零 `NSTEPS` 等 warning/claim。trusted supervisor 记录该唯一进程以 exit code 0 正常退出、未收到 signal/cancel，没有第二写入者或 retry，并监视其存活期间 `TERMINATE` 路径未被创建/修改。
6. supervisor 的最终 output manifest 绑定原始 log、RunPARTs、全部主 BI4/PartOut 文件的名字、大小、类型、inode/link 条件与 SHA-256；结束后 held-FD/hash 复验无变化。主 BI4/PartOut 的 per-PART 时间/计数/identity 再按已审 B/C/auxiliary diagnostics 交叉核验。

只有这组同时闭合，才可把它作为“最终 `SaveData()` 已完成且经过 `PartsOut->Clear()`”的未来 source-derived completion evidence。论据是：每次保存的步增量覆盖至终端 `Nstep`；末主 BI4 metadata 与 RunPARTs 是同一次 SaveData 的 `Part/TimeStep/Nstep`；正常进程继续越过该调用及其后清空路径并完成结束 footer。若输出模式缺失、任一来源身份/调用身份不可信、日志被截断、计数不相等、termination 输入不可审计、writer append 不闭合或某文件缺失，一律 `open/missing`，不得用其他 PART 的证据外推。

## 5. Gate 解释与安全边界

- 本合同不新增 terminal gate，也不改变八个 frozen gate。verified non-zero exclusion 仍按 semantics v5 可证明 `defined_fail`；所有 PART 零事件仍因 registry v1 状态域限制为 `open/missing`，绝不能 `defined_pass`。
- 本合同只定义未来需要验证的记录和派生等式。当前没有可信 supervisor/worker 身份、runtime artifact manifest 或 15-case 真实执行输出，因此 `terminal_completion_evidence` 仍未得到任何生产证据，native-integrity/T1/readiness/资格信用均不变。
- 要求 supervisor 证明独占输出树、进程 wait status、终止文件访问及 artifact source binding；现有普通日志和文件本身无法证明其调用者、来源或未发生的外部事件。若未来无法取得这类可信 witness，本合同只能用于诊断，不能接入 qualification gate。

## 6. 请求只读复核

1. `RunPARTs.Steps` telescoping sum 与终端 `Nstep` 的等式，是否由 CPU 初始化/保存调度源码充分推出？
2. `PartInfo.Step/TimeStep`、最后 PART、RunPARTs 与 console summary 的联结，是否足以证明最后一次保存位于最后已应用 timestep，而非只是此前某个 PART？
3. `NSTEPS`、`SVSTEPS`、minimum-fluid、`TERMINATE`、restart/append、process signal/exit 和输出模式遗漏的 fail-closed 条件是否完整？
4. 所列普通 artifact 与可信 supervisor witness 的职责边界是否明确，且没有把未认证数据升格为 gate pass？

只做只读设计复核；不编辑文件、不运行测试或工具、不读取生产 bundle/HDF5/frame，不运行 GenCase/native decoder/solver/worker/GPU/queue。
