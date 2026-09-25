# Core 计划续推状态 UPDATE-135

## 本次推进：锁定 C V5 局部 lifecycle 不替代 attempt outcome

Terra High 对一个临时测试实现提出两项 P2：V5 的结构化 process generation 与 ledger opaque ID 没有映射；强制 `observed_process_lifecycle_complete=true` 会丢失失败或尚未闭合 attempt 的诊断记录。最终实现不施加该 hard requirement，仅保留 `journal_local_observed_process_lifecycle_complete_unverified`，并继续固定 `process_generation_identity_linked=false`、`event_source_completeness_verified=false`。

新增回归覆盖所有适用的 terminal outcome（`passed`、`failed`、`incomplete`、`timeout`、`oom`、`signaled`、`unresolved`）与无 `attempt_terminal` 的开放 attempt。即便 ledger 和 B/C/D receipts 都自称 `passed`、V5 journal 的本地 lifecycle 尚未闭合，binding 仍只返回 unresolved diagnostic，不擅自拒绝分母案例或将其升级为可信通过。Terra High follow-up 确认先前 P2/P3 已解决，无新问题。

## 验证与边界

- attempt-ledger、V2 attempt projection、V5 journal：**190 passed**。
- 修改的测试文件 `py_compile` 与 `git diff --check` 通过。
- 只使用 synthetic ledger/receipt/journal bytes；未读生产 evidence，也未启动 worker、solver、native decoder、GPU、queue 或 sudo。

未建立真实进程身份映射或 event-source 完整性；outer ledger outcome 和 receipt status 仍是 caller claims，所有结果保留 unresolved、T1=false、资格信用为零。
