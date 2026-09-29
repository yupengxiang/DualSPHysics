# F8 R008 preflight → diagnostic Core / selector coverage audit V1

- 日期：2026-09-29
- JSON：`reports/F8-R008-PREFLIGHT-DIAGNOSTIC-CORE-TRAJECTORY-COVERAGE-AUDIT-V1-2026-09-29.json`
- 状态：`preflight_verified_diagnostic_core_selector_coverage_blocked`

## 结论

已完成的 CPU/native preflight 证据闭合为一次 zero-credit 的 GenCase + 初始 BI4/native decode。它没有产生 solver 时间序列、verified native-fluid table 或 Core trajectory，因此不能直接计入 diagnostic trajectory coverage，也不能成为 T1 证据。现有 trajectory/case/matrix bridge 均保持 fail-closed。

本审计没有启动 solver、worker、queue 或 GPU，没有重用 preflight namespace，也没有写 formal registry、ledger、gate、denominator 或 PLAN。

## 证据链

| 边界 | 当前证据 | 结论 |
| --- | --- | --- |
| CPU/native preflight | `cpu_native_preflight_passed_zero_credit`；GenCase/native decode 均通过；credit=0 | 已验证，但仅为初始输入/几何诊断 |
| preflight → native-fluid table | preflight namespace 无 `native-fluid-frame-table-v2.h5` | 未闭合；缺 solver frames/B/C/D |
| native-fluid table → Core trajectory | adapter 要求 v2 table、raw source-frame factory、至少两帧 | 静态能力存在，当前没有 observed artifact |
| Core trajectory selector | 静态固定分母 15 cases；observed=0 | coverage=0/15 |
| syscall selector | signed-int32 partition/default-deny 静态闭合；runtime/pin 未闭合 | 不是可执行 authority |

## Case selector coverage

preflight 选择的 case 是 `space-q0p5-dp0p0075`，属于冻结 15-case 分母；但当前 R008 campaign 下 observed `core-trajectory-v1.h5` 为 0 个，缺少 15 个 case。现有 15-case matrix worker 只能说明输入键集和 fail-closed 编排能力，不能替代实际 provenance-verified 输出。

## Syscall selector coverage

静态 manifest 状态为 `static_selector_domain_partition_only_not_execution_policy`；raw selector partition complete=True，native interval count=462，default-deny=True。但 per-number policy、runtime conformance、target-kernel build/config pin 均未完成，x32 rejection 与 nr=-1 attribution 也未得到 runtime authority 证明。

## 仍缺失的外部权威证据

- trusted authority issuer and worker/supervisor runtime identity
- source/build/loaded-module identity bound to a real solver attempt
- provenance-verified real 15-case B/C/D/terminal result matrix
- native finite/integrity and effective timestep adjudication
- trusted terminal/final-fput completion observation
- target kernel build/config pin and runtime syscall/fanotify conformance

## 安全边界

- `diagnostic_only=true`、`formal_eligible=false`、`T1_numerical=false`、`readiness_pass=false`、`qualification_credit=0`。
- 本报告只读取 bounded JSON、源码和 artifact size/SHA；不解释 BI4/HDF5 内容，不调用 native tool。
- 失败或缺失继续保持 fail-closed；不得通过改 manifest、复用 namespace 或补写 formal accounting 来提升 coverage。

## 验证入口

- `tests/test_f8_r008_preflight_diagnostic_coverage_audit_v1.py`
- `scripts/f8_r008_preflight_diagnostic_coverage_audit_v1.py`
