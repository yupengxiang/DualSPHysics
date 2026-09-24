# F8 R008 BI4 / bi4_dump 格式静态审计（2026-09-24）

状态：静态格式合同已收窄到 R008 使用的 DualSPHysics v5.4 writer/reader 路径；历史 decoder 的编译来源以及完整 solver 帧 manifest 仍未证明。机器回执：`campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/bi4-format-static-audit-v1/receipt.json`。本次未运行 decoder、GenCase、solver、worker、GPU 或 queue。

## 已由源码与既有产物支持的合同

- 官方 `JPartDataBi4::AddPartData()` 写入 `Idp:uint` 或 `Idpd:ullong`、`Pos:float3` 或 `Posd:double3`、`Vel:float3`、`Rhop:float`。solver 的 `JSph::SavePartData()` 核验 `Idp` 为 `TypeUint`，按有效 `SavePosDouble`/extra-data 路径选择位置精度，并把其他 `JDataArrays` 作为命名扩展数组追加。每个 part 元数据由 `AddPartInfo()` 写入 `Cpart/TimeStep/Npok/Nout/Step/RunTime/DomainMin/DomainMax`；全局 header 含 EOS 与粒子数信息。R008 没有 solver 帧，因此评分代码必须按 solver receipt/日志绑定实际位置变体，不能从 GenCase 初态猜测。
- `JBinaryData` 的 type enum 和 `SizeOfType()` 给出元素大小；`tfloat3`/`tdouble3` 是三个连续标量。BI4 header 记录 byte order，loader 拒绝与本机不同序的输入；`bi4_dump` 将 `GetDataPointer()` 的原生内存直接写盘，不转换端序。因此当前固定到 x86-64 little-endian decoder 的未来消费器应显式用 `<u4/<f4/<f8`，并拒绝非 little-endian host。
- `bi4_dump` 输出 metadata-only `<decode-base>.xml`，递归为每个 item 建目录，再为每个 array 写 `<name>.bin`；字节数为 `count * SizeOfType(type)`。它不清理目标、不检查 `mkdir`/文件流写错误，所以未来必须要求 fresh namespace，并在事后验证 XML 声明与完整递归文件 manifest 精确闭合，拒绝遗漏、额外/陈旧文件、路径异常、非普通文件及 `st_nlink != 1`。
- 已存在 R008 GenCase initial anchor 的 `PART_0000` 恰含五个文件：`Idp` 10752×u32（43008 B）、`Posd` 10752×3×f64（258048 B）、`Vel` 10752×3×f32（129024 B）、`Rhop` 10752×f32（43008 B）、`BoundNor` 4096×3×f32（49152 B）。已存在 decoder stdout 明确报告 type code、count 与字节数；XML 声明相符。Q1 先前独立 PartVTK 交叉核验 identity 精确，位置/速度/密度/EOS 压力误差分别低于其登记容差；它只支持一个初始帧，不证明 R008 solver 输出集。

因此新 per-case verifier 可冻结最低评分字段为 `Idp`、`Vel`、`Rhop` 与且仅且一个 `Pos`/`Posd`；所有 XML 中其他数组仍须出现在完整 manifest 中并逐项哈希，未支持类型 fail-closed，不可静默丢弃。必须从原始 Definition 绑定 exact particle cohort；`TimeStep` 必须来自正确 `PART` 节点并与每个 raw BI4 一一映射。上述静态合同不等于已实现 verifier、solver 结果或 T1。

## 明确保留的来源缺口

当前 `campaigns/l1-resume/artifacts/bi4_dump` 为 SHA-256 `b8ac8cf4…aa8b2e`、ELF Build ID `849e881d39081e58f81acfef8faa3951612fe226` 的 x86-64 binary，但它在仓库中被 ignore、未跟踪。代码 `scripts/native/bi4_dump.cpp` 与外部 `/home/jade/Projects/DualSPHysics/src/source/JBinaryData.cpp/.h` 均可哈希；然而仓库未找到编译命令，Q1 回执绑定 decoder `.cpp` 与外部 JBinaryData `.cpp`（不含 header/binary），R008 预检也只记录 decoder 命令路径而没有 invocation-time binary hash。故不能声称现存 historical decode 是由这些已审源码构建。

这不阻止 future verifier 把 decoder 作为固定的、按内容哈希识别的 opaque executable 使用，但历史 initial anchor 不能补写成 binary provenance。任何新 decode receipt 必须在调用时绑定 binary SHA-256、ELF/build identity、精确 argv、host byte order，并记录调用前后可执行文件身份/哈希；当前未授予新的 decode 或 solver 执行权限。

## 结果与后续

机器审计记录 `format_contract_bounded_historical_binary_build_linkage_unverified`，并保留 `readiness_pass=false`、zero credit、无 solver authority。Terra High 对本次机器合同及“opaque pinned executable 与历史编译来源缺口”的边界作独立只读 follow-up 后，才进入 per-case verifier/schema 的实现审查；15-case T1 和 R008 solver 仍未运行。
