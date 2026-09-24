# F8 R008 C 阶段 solver-execution evidence contract v2（审查草案）

状态：待 Terra (`gpt-5.6-terra`, high) 只读复审；本草案不是已冻结的执行 schema、verifier 或授权。v1 草案保留为历史记录，未覆盖。本文不修改 C v1、R008 scope、15-case 分母、阈值或资格状态；不授权/启动 solver、GenCase、native decoder、worker、GPU 或 queue。

## 1. 审查来源与本版处理范围

本版针对 v1 草案的 `REVISE` 逐项收紧。审查请求通过 `gpt-5.6-terra` / `high` 配置发送；回复未带独立的模型身份 attestation，故以下只记作该配置的技术审查结果，不声称身份已由密码学或外部机制 attested。

- P0：可信 supervisor 缺 schema/信任根；输入 TOCTOU 对象集与保护期不完整；CPU/GPU build provenance 未定义；C v1→execution evidence 的兼容与激活规则缺失。
- P1：OPT/argv grammar、所有 control-query 的源码调用图、`TERMINATE` 初态与实际 `DirOut`、cgroup/进程成员连续性需机器可验。
- P2：`T_end`/浮点容差须绑定到精确冻结对象；日志只能作有版本绑定的辅助证据。

## 2. 兼容边界与派生状态

1. `core.cfd.f8.r008_solver_attempt_receipt.v1`、raw solver manifest v1、现有 C verifier/test fixture 均保持不变。C v1 的结构状态 `passed` 只表示其既有文件/帧轴检查通过，不证明 solver execution。
2. v1 的 `solver_execution` 字段为 `{}`、任意 executor 自报字段、完整帧轴、零退出码或日志文本，均不得单独导出 `control_no_extrapolation=defined_pass`。
3. 新增的 detached sidecar 使用 schema `core.cfd.f8.r008_c_execution_evidence.v2`。它必须绑定同一 case/attempt/nonce 的 C v1 receipt、其 raw-output manifest、B materialization receipt 与 prelaunch authorization 的确切字节数和 SHA-256；任何绑定不符即 `open`。
4. 新 verifier 的派生状态恰为 `open | defined_pass | defined_fail`。缺 sidecar、schema/key/measurement 未能验证、丢事件、解析不确定或任何输入不完整均为 `open`；只有可信、完整的观测证明违反冻结硬条件才可为 `defined_fail`；只有下文全部条件机器复算为真才可为 `defined_pass`。它不能覆盖旧 receipt 或改变 gate registry。
5. v2 sidecar 位于 C v1 manifest 之外，避免 sidecar 自身 hash 的循环引用。其独立 evidence manifest 列出 sidecar、签名日志和所绑定 C v1 对象；不能把“C v1 manifest 已列出 sidecar”作为前提。

## 3. Sidecar schema / 编码 / 签名

外层 JSON 仅允许字段 `schema`, `payload`, `signature`。`schema` 必须等于上述字面值；`signature` 仅允许 `algorithm`, `key_id_sha256`, `signature_base64`。`algorithm` 固定 `Ed25519`；`key_id_sha256` 是 raw 32-byte 公钥的 SHA-256 小写十六进制；签名严格采用 [RFC 8032 Ed25519](https://www.rfc-editor.org/rfc/rfc8032.html)。签名对象使用 [RFC 8785 JCS](https://www.rfc-editor.org/rfc/rfc8785.html) canonical UTF-8 字节，签名输入为 ASCII 域分隔前缀 `F8-R008-C-EXEC-EVIDENCE-V2\n` 后接 payload 的 JCS 字节。拒绝重复 JSON key、非 I-JSON、非规范/非法编码、未知字段、NUL、NaN/Infinity、超限字段或不匹配签名。

`payload` 的顶层 exact-field 集：

`payload_schema`, `scope_id`, `case_id`, `attempt_id`, `nonce_hex`, `authorization_binding`, `c_v1_receipt_binding`, `raw_manifest_binding`, `b_receipt_binding`, `supervisor_identity`, `host_identity`, `namespace_identity`, `runtime_image_binding`, `input_snapshot_binding`, `build_provenance_binding`, `invocation`, `configuration_audit`, `control_horizon_audit`, `process_journal_binding`, `input_journal_binding`, `termination_monitor`, `cgroup_snapshot`, `terminal_state`, `log_bindings`, `started_monotonic_ns`, `ended_monotonic_ns`。所有 binding 对象均 exact-field：`path`, `bytes`, `sha256`；路径相对 C attempt root，不允许 `..`、符号链接解析逃逸或绝对路径。

硬边界：payload canonical 编码最多 8 MiB；`invocation.argv` 最多 256 项且合计不超过 1 MiB；environment 最多 256 项且合计不超过 64 KiB；input inventory 最多 65,536 项；process journal 最多 4,096 个进程事件；输入审计 journal 最多 1,000,000 条且每条最多 8 KiB、单文件最多 1 GiB；路径最多 4,096 UTF-8 bytes。超限、截断或丢事件一律 `open`，不允许采样后声称完整。超限值若不适用于最终 R008 profile，必须在另一个 reviewed schema revision 明文调整，不能由 executor 临时放宽。

### 3.1 外部信任根

- Ed25519 只认证被签名字节，不证明 signer 的测量正确。验签公钥不得从 sidecar、C output bundle 或同一 executor 可写目录中取信。
- verifier 需由独立 admission 输入提供机器 trust bundle：公钥、`key_id_sha256`、允许的 supervisor/build-signer 身份、有效期与撤销状态；该 bundle 的 digest 必须由受信任的 parent/root decision 在执行前固定。签名须覆盖 nonce、attempt、host boot ID、启动/结束单调时钟和全部 evidence-file hashes，抵抗跨 case/attempt 重放。
- supervisor 必须以 solver 不可修改的身份/隔离域运行；其 executable、配置、事件源和验证器自身须由预先固定的 trust anchor 认证。sidecar 中自签的 bundle、repo 内未经独立 pin 的公钥、rootless `bwrap` 能力探针都不是信任根。
- 当前仓库未提供 supervisor 实现、签名密钥的隔离/生命周期、受信任 key registry 或可信 admission root。除非另行建立并审查这一 TCB，所有真实 attempt 的 execution gate 必须保持 `open`；合成测试 key 永不允许进入资格证据。

## 4. 输入闭包、TOCTOU 与运行隔离

`runtime_image_binding` 绑定只读、内容寻址的用户态 runtime image digest；`input_snapshot_binding` 绑定 B attempt materialized tree、generated XML、solver 实际引用的 control CSV、所有间接配置/数据对象的 Merkle root，以及 mount namespace 与 read-only snapshot identity。初始 BI4 只有在 C solver 实际读取时才列入 C 输入；不能把“B 曾使用”误作“C 使用”。

启动前，可信 supervisor 必须在同一受限 namespace 中通过 descriptor-relative、no-follow 打开输入对象；逐项记录 logical path、bytes、SHA-256、device/inode/mount-id、file type、link count 和只读属性，并在核验前后复查 fd 身份。solver 运行期间输入必须来自不可变文件系统 snapshot/content-addressed image，而不是仅靠 chmod 或记录一次 inode/hash。保护从首次核验前开始，直到 solver 及全部 descendant reaped 后结束；每次成功打开的 case/config/library 对象都必须能映射到冻结 snapshot。未列入闭包的读取/路径解析逃逸、可写 alias、hardlink、symlink escape、mount 重绑定或 snapshot 不可证明均 fail-closed。

namespace 根文件系统仅包含绑定的 runtime image；网络、宿主 home、任意宿主路径与未登记 mount 默认不可见。输出写入只允许 C output mount；临时目录独立且有界。记录 PID/mount/user namespace identity 与 mount table digest。supervisor 还必须证明这些约束没有被 solver 或同 UID 的外部写者绕过；rootless mount namespace 本身不能证明 backing snapshot 在 namespace 外不可变。

## 5. supervisor event 与进程/资源 evidence

`process_journal_binding` 和 `input_journal_binding` 指向签名覆盖的 append-only、逐条 sequence 连续日志。记录至少覆盖 supervisor 启动、真实 exec、每次 fork/clone/exit/reap、cgroup membership、可执行文件及动态加载对象、case/config file open、被拒绝的路径、`TERMINATE` 名称事件、cgroup limit/oom/pressure 事件。event schema/version/hash 必须由 payload 绑定；序号缺口、时钟倒退、缓冲区 overflow、journal hash/bytes/count 不符、监测早停、未 reaped descendant 或未知 exec/load 均使 gate `open`。

`invocation` 必须包含直接执行的完整 argv vector（无未绑定 shell expansion）、cwd、精确 allowlisted environment、executable dev/inode/hash、wrapper hash（如确实需要）、execve monotonic time 和 process identity。R008 CPU/GPU candidate 只允许一个 solver invocation；出现额外 solver exec、未登记 wrapper 或未经允许 child process 立即 fail-closed。OpenMP threads 不算新的 process，但必须处在同一受限 cgroup。

`cgroup_snapshot` 必须绑定 cgroup v2 mount/device/inode/id、父级、冻结的 CPU/memory/pids/io limits，以及启动到 reaping 的 membership 事件；成员不得迁移，`cgroup.events: populated` 最终必须为 0。记录并复算 `cpu.stat`、`memory.peak`、`memory.events`、`pids.events`、`io.stat` 和压力/oom 事件；峰值、限制、计数与预登记资源授权必须一致。仅事后读取一个 peak 值、仅检查主 PID 或布尔 `process_tree_clean=true` 不足。

## 6. Source-to-binary / dynamically loaded code

`build_provenance_binding` 必须指向独立签名的 builder attestation，包含：DualSPHysics 完整 source-tree manifest/root digest（commit、dirty/untracked/submodule 状态）、所有参与构建的源码/生成文件、build scripts、compiler/linker/toolchain 与依赖 image digest、宏/feature flags、编译/链接命令的 canonical digest、产物清单及主程序 SHA-256。CPU 与 GPU variant 分开认证；GPU 还要绑定 CUDA compiler/toolkit、driver/runtime 与加载的 PTX/cubin/device code identity。

运行 supervisor 记录实际 exec 的主程序和所有加载库/device code 的路径、mount/device/inode 与 SHA-256，并逐项与 builder attestation 匹配。可接受路径仅为独立受信 builder 对该固定源和工具链签发的 provenance，或独立重建且产物 hash 完全一致的可复核结果；只有 executable SHA、Git commit 或未经认证的 `ldd` 输出均不能证明 source-to-binary。当前历史 `bi4_dump` binary provenance 的 open finding 不自动污染/替代未来 solver provenance；未来 solver binary 自身必须另行闭合。无可信 build attestation/重建时 gate 保持 `open`。

## 7. argv / OPT / generated XML 解析和规范化

`configuration_audit` 绑定 solver source commit/tree hash、`JSphCfgRun` 与 XML parser 源码 hash、CPU/GPU feature set、grammar revision、canonical normalized-config artifact 及其 verifier hash。解析必须遵循该精确源码版本的参数 tokenization、大小写、重复键、覆盖顺序、路径根和递归行为；`-OPT` 图必须检查 cycles、最大十层、所有目标文件的 snapshot binding 和覆盖顺序。未知/重复/歧义选项、路径逃逸、未登记外部配置或解析器不支持的语法 fail-closed。

R008 首个 execution profile 提议禁止所有 `-OPT` / `DsphConfig.xml` 外部覆盖、restart/`PARTBEGIN`、`NstepsBreak`、以及任何 `TMAX`/`TOUT`/`TOUTX`/`NSTEPS`/`DIROUT`/`DIRDATAOUT` override；允许的完整 argv 必须由独立 reviewed profile 精确列出，profile 未冻结前不得执行。若 DualSPHysics 该版本会隐式读取这些文件，则必须将其加入完整 snapshot 和 parser contract，不能假设不存在。生成后的 XML 必须绑定 B receipt/hash，并核对实际读取的 `TimeMax`、`TimeOut`、accinput control reference 与冻结 control CSV。

## 8. 所有 control-query 时域、horizon 与终止

静态源码审计产物必须绑定确切 source tree/build flags，并列举所有 `JDsAccInput::RunCpu/RunGpu` 及 `JDsAccInputMk::GetAccValues` 可达调用点、实际 timestep 表达式（含预测器/子步）、初始化/恢复/终止路径和配置条件。当前源码检索发现 `JSphCpu.cpp`、`JSphGpu.cpp` 分别以 `TimeStep` 调用 `AccInput->RunCpu/RunGpu`，继而在 `JDsAccInput.cpp` 中调用 `GetAccValues(c,timestep)`；该枚举尚未形成经审计的完整调用图，不可仅以主循环片段声称覆盖所有 query。

`T_end` 取冻结 qualification row 的 `observation_end_s` binary64 值（与 `expected_time_axis_hex` 最后一项相同），不是从日志或最后输出帧推断；native expected-axis 算法按 `float(index)*dt` 构造中间点并将最后点绑定到该 endpoint。control CSV 最后采样时刻须以 solver 实际使用的、由 source/build hash 锁定的 parser 解析为 binary64；控制表起点必须为 `0`，最后时刻必须数值上 `>= T_end`，不得用 tolerance 把短于 endpoint 的表格算作覆盖。R008 的 `duration_check_atol_s=1e-12` 只属于三周期 observation-window duration 检查，不得放宽 execution horizon/query 上界。`configuration_audit` 必须给出 XML →（若允许）OPT/config → argv 的唯一 overlay 后 `TimeMax`/`TimeOut`/`TimeIni`/`TimeEnd`/控制文件引用规范值及 binary64 bits；须满足 `TimeIni=0`、`TimeMax<=T_end`、`TimeEnd>=TimeMax`，且不得有 runtime horizon 扩展。

只有在完整、source-bound call graph 证明每个实际控制读取点均位于受控循环内，且 supervisor 证明所有可改变 horizon 的路径时，才允许用 `0 <= t_query < effective_TimeMax <= min(T_end, control_table_end)` 证明不外推；比较按实际 parsed binary64 数值严格执行，不做 tolerance 扩张。`effective_TimeMax` 的算法必须以绑定的解析后 XML/config 和源码版本定义；未知 override、query 可能发生于 horizon check 外、binary source mapping 不闭合时均 `open`。完整 raw frame axis 仍是必要证据，不替代 query-site 证明。

CPU 的 `TERMINATE` 文件在实际解析后的 `DirOut` 下必须于 exec 前通过 descriptor-relative 检查确认不存在。`termination_monitor` 必须绑定该 DirOut 的 namespace/mount/inode、exec 前状态、从 exec 前至全进程 reaped 的完整事件源与零 overflow，并能证明外部写者无法创建/改写/删除该名字；只靠事后不存在、mtime 快照、日志或普通 inotify 不足以证明未被读取。任何出现或监测缺口都不得 pass。CPU/GPU `CheckTermination` 差异按绑定源码 variant 处理。

另须 machine-prove：`NstepsBreak=0`、无 restart、无 signal/timeout/异常、无 minimum-fluid 提前停机；正常终止由解析后 `TimeMax` 的自然控制流到达。CPU/GPU finish log、退出码与逐帧 axis 仅作交叉校验，不能单独定案。

## 9. 日志、输出绑定与 verifier 规则

每个 solver log 绑定 bytes/SHA、parser source/version hash 与有限 grammar；只接受已列举的终止/错误记录。日志与 supervisor 状态冲突、未知 completion 文本或 parse 不完整时 `open`；日志永不作为 horizon、process-tree 或 clean-exit 的唯一来源。C v1 raw output manifest 继续独立验证全冻结帧轴与文件；v2 evidence manifest 再精确绑定 sidecar、签名 journals 与 C v1/B/authorization digest，避免循环哈希。

新 verifier 需纯离线验证 exact schema、canonical bytes、签名/trust bundle、所有 byte/hash bindings、journal 序列/limits、config/audit artifact 和终态派生。缺少外部 pinned trust root、builder provenance、source call-graph audit 或任一运行事件时，一律 `open`；synthetic fixture 的密钥只能用于负例测试，不能用于资格流程。

## 10. 当前能否闭合

当前只有 C v1 structural verifier；`solver_execution={}` synthetic fixture 能通过该层结构检查。仓库无可信 supervisor、其受保护签名 key/trust registry、完整 C execution event recorder、CPU/GPU solver builder provenance 或 C-execution v2 verifier。此前 rootless `bwrap` smoke test 证明了候选只读 mount/temp tmpfs 原语，但不证明不可变 backing snapshot、namespace 外写者隔离、签名信任根、加载代码测量或完整事件捕获。

因此当前只能冻结“缺项即 `open`”的设计边界，不能证明该主机可产生 pass evidence，也不能因此启动 solver。任何实现先限于纯 synthetic fixtures，并须经 Terra follow-up 设计/静态复核；不得先造一个同 UID 自签脚本再把其结果称为可信 execution attestation。
