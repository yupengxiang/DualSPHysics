# Core 计划续推状态 UPDATE-112

日期：2026-09-25（Asia/Shanghai）

## 本次推进：formal planner path JSON strict codec

在 `core_formal_planner.py` 增加 bounded raw-byte JSON reader，并应用于 path-backed manifest、environment/profile/evidence、referenced audit 与 source-snapshot 输入：

- 单文件读取上限 64 MiB；使用同一已打开 regular-file FD 读取，核对读前/读后 `(dev,inode,size,mtime_ns,ctime_ns)`，拒绝超限或读取期间变化。
- strict UTF-8 与 JSON 解析；拒绝嵌套 duplicate keys、`NaN`/`Infinity`、float 转换溢出、超过 128 位十进制位数的 JSON integer，以及非 object 顶层。
- referenced audit SHA-256 现在基于经过界限检查的同一 raw bytes；source snapshot path 也不再普通 `read_text()` 解析。
- 普通 in-memory `Mapping` 仍然接收为诊断输入，但无法提供 raw-byte duplicate-key 证明；固定的 `trusted formal admission capability unavailable` hold 仍在，`formal_eligible=false`、`launch_allowed=false`、0 formal jobs/specs。

新增负测覆盖 manifest duplicate key、`NaN`、float overflow、过长整数、非法 UTF-8、可配置字节上限，以及带有效 raw SHA 但内部重复键的 referenced audit。仓库 `.venv` 下 `test_core_formal_planner.py` 与 `test_core_formal_admission_readiness.py` **31 passed**；`py_compile` 与 `git diff --check` 通过。tests 中保留的 F3 compact manifest 只作既有元数据诊断；未读 HDF5/one-shot receipt，未创建 specs、训练或调度任务。

## 信任边界与仍未完成项

这是 V13 所需 strict serialization 的一个 path-input 子项，不是 root reader/capability：仓库现有 V3 codec 只实现内存 serialization/digest，未发现可验证的 trusted root、producer/supervisor、descriptor registry、runtime/import identity 或 fs-verity snapshot implementation。此修改不认证路径根、不确认输入由可信 producer 产生、不完成 source/build/runtime 闭包，也不允许规划器从 Mapping 或 JSON marker 获得正向 admission。无可验证信任锚时不能 mint 正 capability；Core formal training 仍被 fail-closed，F8 T1/T2 与整个 PLAN Core 验收状态不变。
