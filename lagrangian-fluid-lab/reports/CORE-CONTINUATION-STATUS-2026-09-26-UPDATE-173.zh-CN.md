# UPDATE-173：F8 R008 RunPARTs/PartOut 接入闭合 B/C 输出清单

时间：2026-09-26（Asia/Shanghai）

## 本次推进

扩展 `f8_r008_auxiliary_output_inventory_v1.py`，现在可从已验证 C 输出 manifest 中以 no-follow、single-link held FD 读取 `RunPARTs.csv` 与 CPU 单-piece `PartOut_<block>.obi4`，按各自 manifest bytes/SHA 绑定。RunPARTs 保持现有 8 MiB 上限和 v2 26 列逐值类型/范围检查；PartOut 保持 128 block、256 MiB 聚合字节与既有 SAFE BI4 结构上限。扫描后重开文件时先核对原 identity、准确 manifest 长度及类别上限，再按 manifest 长度哈希；PartOut FD 在上限校验前即登记到统一清理路径。

每个 PartOut root 的 `CaseNp` 绑定已验证 B cohorts 的总人口；逐 PART `Nout`、`Idp` 数量/唯一性、`Motive` 码与 RunPARTs 三类原因计数继续逐项对账。每个事件 `TimeStep` 同时对照 RunPARTs `RealStr(double,16)` 的十进制表示，以及同序号 C 主帧的实际 BI4 `TimeStep` binary64 位模式。只有 RunPARTs 有非零排除计数且 PartOut 文件存在时，才为相关 C 帧执行 held-FD 原始扫描；其时间须与冻结帧轴相符，帧 identity/SHA 纳入扫描末尾复验。

对被当前 CPU R008 子集接受的 PartOut 结构，逐块扫描所有浮点 root metadata、每个 PART 的 `TimeStep`，以及 `Pos`/`Posd`、`Vel`、`Rhop` 的全部标量分量；按有界 chunk 统计有限/非有限数量并记录数组 SHA。RunPARTs/PartOut 的结构、计数、时间或输入身份不一致时返回 `missing`/扫描不完整。非有限 PartOut 数值只作为诊断，不会自动改写 native-integrity gate。未提供 C 帧参考的 standalone parser 会明确标注 C 时间关联未验证。

PartOut 缺失、RunPARTs 缺失、PartExtra 缺失都不解释为相应输出模式关闭；`PartOut_pNN_...` 多 piece 目前仍被识别但由内层 R008 CPU 单-piece parser fail-closed。PartInfo piece 命名与其他 auxiliary writer 格式仍待实现。

## 独立审查意见与复核

只读代码审查发现三项 P2：最终复验先按不受限 `st_size` 哈希、PartOut 超限拒绝前 FD 尚未进入统一清理、PartOut `TimeStep` 未与 RunPARTs/C 帧时间关联。已分别增加有界预检、FD 泄漏负测，以及 PartOut—RunPARTs 格式时间—实际 C 主帧时间链和错时负测。后续只读 follow-up 未发现具体问题，并逐项确认上述三项修复；两个审查 agent 均表示无法 attestate GPT‑6 Luna 身份，因此不记录为 GPT‑6 Luna Max verdict。

并行只读源码调查确认了下一批 writer：`Part_Head.ibi4`、`PartInfo[_pNN].ibi4`、`PartMotionRef[2].ibi4`、`PartFloatInfo[2].ibi4` 的文件码、浮点字段、单/批量布局及写出条件。相关源代码证据整理在后续任务输入中；不把源字段调查当成实现或输出模式认证。

## 验证与边界

- 项目 `.venv` 下七个相关 suite 最终结果：**146 passed**（164.10 秒）；覆盖 auxiliary bundle、PartOut/RunPARTs、PartExtra、native-state finite inventory/scan/evidence 与完整 per-case bundle verifier。
- 专项语法编译、`git diff --check` 与 43 项 PartOut/auxiliary 定向回归通过。
- 所有运行输入均来自临时合成 bundle/BI4/CSV fixture。未读取生产 bundle、frame 或 HDF5；未运行 GenCase/native decoder/solver/worker/GPU/queue；未更改 registry、ledger、资格分母或既有 receipt。
- `source_attempt_identity_verified=false`、`output_mode_verified=false`、`execution_horizon_verified=false`、`terminal_flush_verified=false`；`excluded_fluid_particles_zero` 仍只会是 `open`/`missing`，`native_integrity_evaluated=false`、`T1_numerical=false`、`readiness_pass=false`、资格信用 0。

## 后续

1. 为 `Part_Head`、`PartInfo`、MotionRef、FloatInfo 实现受限 schema-bound 浮点扫描，覆盖可选/批量字段、文件码、piece 名与实际 writer 的条件创建；缺文件继续保持期望未知。
2. 按冻结 R008 执行配置决定 PartOut 是否需要支持多 piece/`Idpd`，不能把尚未认证的格式差异静默放宽。
3. 冻结并绑定输出模式、真实 invocation/source/runtime 身份、正常覆盖 `T_end` 与最终 `SaveData`/event flush 证据；之后才可接入 native-integrity gate。R008 没有已成功 solver attempt，本轮仍仅合成静态诊断。
