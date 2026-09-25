# Core 计划续推状态 UPDATE-105

日期：2026-09-25（Asia/Shanghai）

## 本次推进：V5 journal-local process/thread lifecycle replay

在 UPDATE-104 的 strict structural parser 上新增 `_observe_process_lifecycle()`，按全局 journal seq 重算：

- 唯一 root `spawn` 建立 created generation；必须在 root 首次 `exec` 后，才接受该 generation 的 loop guard/query event。
- `fork` / `clone_process` 只允许从已知 running parent 建立 child generation；child 从创建事件起进入 running。
- `thread_create` 只允许关联到 running process；`thread_exit` 必须匹配仍存活且归属同一 process 的 thread。process exit 前，该 process 的 threads 必须全部已退出。
- process 必须按 running→exit→reap 转移；未知 generation、重复 root/创建、退出后事件、错误顺序均拒绝。
- PID namespace 内 PID 必须等旧 process generation reaped 后才可复用；同一 namespace 的 TID 必须等旧 thread generation 退出后才可复用（包括跨 process 的 TID 冲突）。
- journal 截断导致进程未 reap/thread 未退出时，返回 `observed_process_lifecycle_complete=false`，但永远保持 `process_lifecycle_verified=false` 与 `gate_state="open"`。

Terra High/high 只读审查未发现此状态迁移切片内可复现的绕过或误拒；其运行时测试快照为 26 passed。此后我只新增一个“旧 PID 已 reap 后允许创建新 generation”正例，当前 focused suite 为 27 passed；`py_compile` 与 `git diff --check` 通过。

## 安全边界与未完成项

这里仅重算 caller-provided event bytes 内部的一致性；它不是可信 supervisor 证据。未验证 PID namespace/kernel task handle 的真实性、事件覆盖完整性、source-to-loaded-runtime、fork/clone flags 语义、process↔query source-callgraph 因果、完整终止边界或 V5 `LastTimestepInput` 单槽 cache replay。外层 evidence/attempt nonce、descriptor-root binding 与 producer capability 也未接入。

parser 不连接 solver/qualification public entry，成功仍输出 `execution_semantics_verified=false`、`qualification_adjudicated=false`、`T1_numerical=false`、`qualification_credit=0`。本轮仅内存合成 journal；未读 production campaign/bundle/HDF5/solver frame/one-shot，未运行 planner/tick/canary/preparation/GenCase/native/solver/worker/GPU/queue。
