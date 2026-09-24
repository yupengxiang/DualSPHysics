# F8 R008 CLI、restart 与终止文件静态审计（2026-09-25）

## 结论

继续只读追踪标准 `src/source` 的启动和输入路径后，确认未来 execution evidence 至少需要分别闭合以下路径：

| 来源 | 源码解析根 | 可能影响 |
|---|---|---|
| `DsphConfig.xml` | `argv[0]` canonical path 的父目录 | 是否创建输出目录、CSV 分隔符；千位 flag 被读取/保存，但当前源码未见下游 consumer |
| 命令行与 `-OPT` | 进程 CWD；OPT 由 cwd 解析 | 求解器/边界/时间推进/输出配置、case/restart/output 路径 |
| case XML 与相对外部输入 | XML 自身的 `DirCase`；具体由各 reader 拼接规则决定 | 物理配置、控制表、其他外部数据 |
| `PARTBEGIN` restart | restart 参数给定目录（相对路径以 cwd 为根） | 初始粒子状态、时间步、PART 编号及 restart 元数据 |
| `TERMINATE` | `DirOut/TERMINATE` | 可在第一步前或运行中缩短有效 `TimeMax` |

这是源码语义，不是某个 R008 solver attempt 的调用证据。当前没有实际 R008 argv/CWD、可执行文件目录内容、OPT 文件、restart 产物、`TERMINATE` namespace 事件或 source-to-binary 绑定；运行配置真实性保持 open。

## 启动与配置来源

- `main()` 先以 `argv[0]` 和当前目录调用 `ConfigRunPaths()`，随后非 `-ver`/`-info` 路径才进入 `cfg.LoadArgv()`。`RunPath` 是进程 CWD，`ProgramPath` 是 canonical 可执行路径的父目录（`main.cpp:170-181`; `JAppInfo.cpp:107-110`）。
- 当前标准配置 `JCfgRunBase_UseDSCfg` 已启用。`LoadArgv()` reset 默认后，从 `ProgramPath/DsphConfig.xml` 读取可选 `dsphconfig.common`，然后才解析命令行。该文件可设置 `CreateDirs`、CSV separator 和 CSV thousands flag；`-createdirs`、`-csvsep` 在后续选项流中可覆盖前两者。标准 `src/source` 中 `CsvSepThou` 除读取和保存外未找到下游 consumer。文件不存在与文件存在都应作为启动输入状态绑定，不能只凭工作目录推断。
- 命令行 token 依 argv 顺序处理，case/output 可通过位置参数或 `-name`/`-dirout` 提供；`-dirdataout` 被拼接到 `DirOut`。普通重复选项没有统一 duplicate-reject 层，状态赋值按解析顺序执行；如 `-sv:none` 与其他 `-sv` 可继续改变输出开关。因而对 R008 应冻结原始 argv、解析 token 顺序与唯一 reviewed allowlist，而不只记录最终配置摘要。
- parser 可直接改变 CPU/GPU 选择、边界模式、时间算法、kernel、viscosity、CFL、density/output、`TMAX`/`TOUT`/`TOUTX`、`NSTEPS`、cell/domain 与 restart 等。即使不允许时间覆盖，也不能只拒绝 `TMAX` 而接受未审查的其余选项。递归 OPT 的词法与展开规则详见 [TMAX/OPT 审计](F8-R008-TMAX-OPT-OVERLAY-AUDIT-2026-09-25.zh-CN.md)。
- `LoadCaseConfig()` 先读 case XML，再读 XML execution parameters，随后调用 `LoadConfigCommands()` 应用 CLI/OPT config；CLI 能覆盖的项目以该源码版本实际 parser 为准。`FileXml` 由 case 路径与 basename 组成。已检查的多个外部文件 reader 以 `DirCase + XML 内相对路径` 打开输入；R008 必须枚举实际启用的每个 reader，把生成后 solver 实际读取的 XML 和引用文件纳入同一只读输入 closure，而非只绑定 GenCase 前 Definition。

源码锚点：`JCfgRunBaseDef.h:19`；`JCfgRunBase.cpp:51-58,65-103`；`JDsphConfig.cpp:60-79`；`JSphCfgRun.cpp:312-525`；`JAppInfo.cpp:107-120`；`JSph.cpp:553-612,1003-1025`。

## Restart 与初始状态

- `-partbegin:begin[:first] dir` 会将 PART 编号、首个输出编号和目录写入配置；省略 `first` 时 `PartBeginFirst=PartBegin`。restart 目录按传入路径读取，若为相对路径则依 OS/CWD 解析。
- `JPartsLoad4::LoadParticles()` 根据 `PARTBEGIN` 选择 case 初始粒子或 restart `PART` 文件；从 piece 0 读取保存时间、piece 数和模拟元信息，再加载全套 pieces。`JSph::LoadCaseParticles()` 对 restart 额外检查粒子块元信息；后续用保存时间与 `PartBeginFirst` 决定 `TimeStepIni`，并恢复部分积分器/DEM 状态。
- 因此 `PARTBEGIN` 不是可由 Definition 或 B receipt 取代的普通参数：若 R008 profile 禁止 restart，必须验证它缺席；若允许，必须对 restart directory 中实际选择的所有 PART pieces、header、必要 extra/restart data 做稳定快照、逐文件 hash 与目录清单，并绑定 CWD、命令行和读取 inode。仅绑定 restart 目录字符串不够。

源码锚点：`JSphCfgRun.cpp:462-470`；`JPartsLoad4.cpp:164-245`；`JSph.cpp:2151-2159,2213-2229`。

## `TERMINATE` 首次读取时机的更正

CPU 与 GPU 单卡 `Run()` 都在初始化完成、进入主时间循环前先调用一次 `SaveData()`（`JSphCpuSingle.cpp:1155-1174`; `JSphGpuSingle.cpp:965-986`）。基础 `JSph::SaveData()` 在保存后调用 `CheckTermination()`；它读取 `DirOut/TERMINATE`，若修改时间非零且变化，则最多读取 127 bytes，以 `atof` 解释数值，再将请求值夹到当前 `TimeStep`。非 multi-GPU 路径把该值直接写回 `TimeMax`。因此**在首次积分之前已存在的 TERMINATE 文件也可能将 horizon 收到初始/恢复时刻，使主循环零步退出**，不是只有运行中人工创建才影响资格证据。

之后每次保存也会轮询该文件；外部写入发生在两次保存之间时，生效时间受保存 cadence 限制。`TERMINATE` 解析不是严格数值语法；文件状态/mtime 的单次事后目录检查不能证明运行中无人写入。R008 execution profile 应使用全新、受控 `DirOut`，在 exec 前证明该路径下 TERMINATE 缺席并维持受控 namespace；如任何运行期 TERMINATE 被允许，则需可信写者身份与完整事件记录覆盖首个初始化 `SaveData` 到所有进程退出/reap。只靠 `Run.out` 文本或最终 frame 不足。

源码锚点：`JSphCpuSingle.cpp:1163-1174`；`JSphGpuSingle.cpp:973-986`；`JSph.cpp:3293-3327`。停止时间仍同时受 XML/正值 CLI `TimeMax`、runtime TERMINATE、minimum-fluid stop 和 `NstepsBreak` 影响，后两者语义见 UPDATE-57/58。

## 对 execution contract 的最小要求

1. 绑定进程 `argv[0]`、真实 executable path/hash、CWD 身份和 build/source/features；单独的版本字符串或 `Run.out` 路径日志不是执行见证。
2. 对 executable-parent `DsphConfig.xml` 记录精确解析路径、存在/缺席、稳定字节/hash；对完整 CLI token stream 与递归 OPT 图执行版本绑定 parser 和 exact allowlist，并证明无未登记 config/restart/output override。
3. 绑定 case XML、全部 solver 实际打开的相对输入、GenCase initial particle files，或在允许 restart 时绑定完整 PART/restart 文件组；路径与 bytes/inode 必须保持同一 attempt 闭包。
4. 在 solver exec 前审计唯一新 `DirOut` 的 inode/namespace、确认 `TERMINATE` 缺席；运行期间监视并保留覆盖首次 SaveData 的事件证据，直到所有 solver 子进程退出并回收。
5. 将实际解析值、实际输入 FD、有效 horizon 变化、所有 control query、输出帧和退出/早停分类绑定到同一 source/build 锁定 attempt。无可信见证时保持 gate open。

本次仅阅读标准源码、核对历史审计和当前 source hashes；未修改 solver 源码、未读取生产 solver bundle/frame/large HDF5、未运行 GenCase/native decoder/solver/worker/GPU/queue，也未写 registry、ledger 或调度状态。R008 `control_no_extrapolation` 仍不能判 pass，`T1_numerical=false`、资格信用 0。

## 源码 SHA-256

| 文件 | SHA-256 |
|---|---|
| `src/source/main.cpp` | `43ce552b8177dad089148f7f552bc44f9467220eb0da6503964f6bfd6c888b4c` |
| `src/source/JAppInfo.cpp` | `4a66e0a37eb753ff2b19f7d7255b5f5e27c76610793494cd976cb2f6dae6d5a3` |
| `src/source/JCfgRunBaseDef.h` | `cba6a088ef08dc82e22ff5299cf013ddc9d93788167499d90b4012f511e1370c` |
| `src/source/JCfgRunBase.cpp` | `cc0ffda27854411af2dc0e52e054df46ef95bb850e613146367748e6150a2362` |
| `src/source/JSphCfgRun.cpp` | `51b8dc214181edc0518e4c7de42a71b9248dee891064de3efb74aa8b095a2c96` |
| `src/source/JDsphConfig.cpp` | `0fd98ec44a0716776a895b07d2a9218d27a3df6127d1796feb01f6c96f743e43` |
| `src/source/JSph.cpp` | `206e4486a3a0d304e02da1a73d2e7c7ed96354d559ce481275d09f5245b8c9e7` |
| `src/source/JPartsLoad4.cpp` | `50926bd6c47bfb9a3807bc98b85f6784f8d4d92c318ad7dd5722d4592935735b` |
| `src/source/JSphCpuSingle.cpp` | `a261620354e4970f99e8314ddfede1349acef5de236af32e9921af324c021608` |
| `src/source/JSphGpuSingle.cpp` | `a8652f2422e1c7656f39aaac526c432ed992fc506e48de297410bb36cabe0361` |
