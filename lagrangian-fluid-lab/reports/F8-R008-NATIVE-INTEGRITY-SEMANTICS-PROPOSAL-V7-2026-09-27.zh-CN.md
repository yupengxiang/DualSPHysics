# F8 R008 native-integrity semantics proposal v7

状态：依据 GPT-5.6 Luna Max 对 v6 的只读复核作 additive 修订。v6、v5 及更早版本和既有 receipt 均保留；本版仍是未来证据合同，不是 runtime verifier、solver 授权或 T1 结果。

v7 不改变冻结 R008 scope、15-case × 8-gate 分母、阈值/单位、registry outcome domain、观察窗口、失败分母或 qualification credit。当前 PartOut/RunPARTs parser、fanotify reducer 和 attempt/journal 工具仍是 diagnostic-only；没有可信来源、worker、supervisor 或 native-integrity 结果时必须保持 `open`/`missing`、`gate_decision_eligible=false`、`T1_numerical=false`、credit `0`。

## 1. Fresh-run、restart 和有效终点边界

未来任何 CPU single-piece native-integrity attempt 必须先通过现有 terminal-completion contract v2 的 exact input/argv/OPT 绑定；v7 不用 caller 自述替代该绑定。启动前 receipt 必须逐字节绑定 Definition、control、initial-state、solver binary/build/features、cwd、argv、运行环境/locale，以及下列运行时字段：

- 实际加载的 `PartIni`、`TimeStepIni` 和初始状态身份；`PARTBEGIN`/restart/resume/append 输入必须明确为 absent 或被判 `missing`，不能从 `Part=0` 的一行反推不存在 restart。
- `NSTEPS`、`SvAllSteps`、输出 cadence 和 `OutputTime` 初始状态；值必须来自已绑定输入和源码版本，未冻结的字段不允许默认补值。
- 有效 `T_end/TimeMax` 的 binary64 bits、单位和来源。可信终点必须证明最后一个实际应用步满足 `t_before < T_end <= t_after`，而不是只比较日志文本或使用容差。
- `TERMINATE` 的创建/修改/重写观察、`NstepsBreak`、minimum-fluid stop、异常/信号和 restart/append 路径。任何可能缩短有效 horizon 的未观察分支都使全程零排除判定为 `missing`；可信正排除事件仍可按 registry 映射为 `defined_fail`。

这里的“禁止 append”只指 preexisting、跨 attempt、restart 或未经绑定的 append；同一可信 attempt 内 RunPARTs/PartOut writer 的受控 append 是合法保存语义，不能被 verifier 错误拒绝。

## 2. Writer inventory 与 terminal flush

每个 case 的启动 receipt 必须由实际 output-mode 配置导出精确 writer inventory，不能用“all required writers”作为未展开的占位词。inventory 至少逐项列出适用的 `RunPARTs`、main fluid BI4、`PartHead`/`PartInfo`、`PartOut` 及配置启用的 VTK、float/motion、extra、log/summary writer；不适用项也必须由绑定配置给出 absent 证明。R008 当前 bounded parser 仍只接受 CPU single-piece 的有限 PartOut 形状，GPU/multi-piece 继续 `open`/`missing`。

对每个 `SaveData` 事件，证据必须分别记录并复核每个适用 writer 的目标文件 identity、起始/结束长度、写入 bytes/hash、flush/close 返回和 error state；要求其后 `PartsOut->Clear()`，并覆盖 `FinishRun()` 在启用 `SDAT_Info` 时追加的 footer。退出后在同一 fresh output root 中 no-follow 重开全部文件，复核 stable inode/length/SHA-256，并交叉核对 main BI4、PartInfo/PartHead、RunPARTs、PartOut 的 Part/Step/Time。

`SaveData()` 返回、`PartsOut->Clear()`、单独存在的 RunPARTs CSV 或一份 PartOut 文件都不能证明 writer 集合完整。任一 writer 未列出、失败、close 状态不可观测、文件孤立/缺失、identity/hash 不符，结果为 `missing`，不得从剩余零计数推断全程零。该合同只表示应用层文件闭环，不声称超出已观测文件系统语义的断电耐久性。

## 3. Attempt/output binding 与跨 attempt 反例

在任何 gate 计算之前，未来 verifier 必须消费一个独立的 trusted attempt/output-root binder。其 exact projection 绑定：唯一 attempt nonce/ID、PID start-time generation、exec epoch、精确 argv/cwd、solver binary/build/features、Definition/control/initial-state 摘要、fresh output-root 的 namespace 内 dev/inode 和 no-follow 打开对象，以及每个 writer 文件的 dev/inode、single-link、长度、raw bytes/hash、writer generation 和对应 SaveData/PART。

输出根目录不得预存、复用、别名指向、包含旧 restart/append 产物或被第二次启动消费；退出后的复核必须使用同一 root object。合成反例必须覆盖：attempt A 的 RunPARTs 与 attempt B 的 PartOut 具有相同文件名、CaseNp、root metadata 或 caller attempt label 时，仍判 `missing`/`open`，绝不拼接；不同 inode、config、binary、generation 或 retry 也同样拒绝。仅有 caller-supplied nonce、摘要、签名或路径名不是 source authentication。

当前新增 binder 只能作为 bounded diagnostic adapter，输出 `source_authenticated=false`，不得向 registry mint capability；在 trusted producer/supervisor/runtime identity 未实现前，旧 parser/reducer 不得消费它作为 T1 gate 证据。

## 4. PART cadence、raw token 和 PartOut 对账

预期 PART 序列必须冻结 `JSphCpuSingle.cpp`/`JSph.cpp`、`JDsOutputTime.cpp` 及相关 OutputTime 配置和 initial state 的源码摘要。verifier 保留 RunPARTs 的原始 CSV cells，不只保留解析后的 float；每行按实际 binary64 `TimeStep`、`TimePartNext` 和 `OutputTime->GetNextTime(TimeStep)` 的 stateful 递归生成，单步跨多个名义 cadence 时不虚构缺失 PART。

RunPARTs 的时间 token 必须按已 pin 的 C++ `RealStr` 格式化语义逐字匹配；PartOut binary64 `TimeStep` 必须 bitwise 匹配同一可信保存事件。测试必须覆盖多 cadence crossing、特殊 OutputTime 序列、最后应用步未触发 SaveData、重复/遗漏/乱序 PART、同 PART 跨 block 重复 payload 和 raw token 数值相同但文本不同的反例。当前 v2 parser 仍只做 diagnostic numeric parsing，直到该实现和独立复核闭合，相关 gate 保持 `open`/`missing`。

每个 `NpOut` 必须与 `NpOutPos + NpOutRho + NpOutMov` 相等；非零行必须恰有一个跨 block 的 PartOut payload，`Cpart`、`PART_####`、`Nout`、Idp 数、Motive histogram、PartOut/RunPARTs 时间和已认证身份域逐项相等。`NpOut==0` 时 PartOut 可缺席，但该行不能单独建立全程零排除。

## 5. Registry mapping 与当前边界

`excluded_fluid_particles_zero` 仍服从 v1 registry：可信完整正排除事件为 `defined_fail`；完整可信 attempt、完整 PART/终止/writer 闭环且所有 `NpOut==0` 只能为 `open`；没有可信正事件但 attempt、输出、PART 或终止闭环任一缺失/不可信/不完整为 `missing`。四个 open gate 不得被升格为 `defined_pass`。若要定义零排除 pass，必须新建 registry 版本并独立审查。

本版仅收紧 v6 的输入边界、writer inventory、合法 append 语义和 diagnostic binder 接口；不读取生产 bundle/frame，不运行 GenCase/native decoder/solver/worker/GPU/queue，不更新 registry/ledger/分母或 credit。v7 需要在 binder、raw PART/RealStr verifier、writer inventory/terminal evidence 实现后重新进行独立只读审查。

## 6. Review provenance

GPT-5.6 Luna Max 对 v6 的只读复核结论为 **REVISE**，无 P0。P1 为 fresh/restart/`PARTBEGIN`/有效 `T_end` 边界和具体 writer inventory；P2 为 trusted attempt/output binder 及 raw PART cadence/`RealStr`/binary64 terminal 实现；P3 为区分同 attempt 合法 append 与跨 attempt append。reviewer identity 未由密码学机制 attested；审查不构成 runtime、T1 或资格结论。
