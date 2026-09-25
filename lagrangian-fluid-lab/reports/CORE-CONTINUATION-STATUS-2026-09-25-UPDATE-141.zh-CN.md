# Core 计划续推状态 UPDATE-141

## F8 R008 supervisor-session 身份声明桥（仅 claim consistency）

新增两个窄化、不可变的只读 projection API：attempt ledger 从完整 raw bytes 派生指定 attempt 唯一的 C `process_terminal`、opaque process-generation ID 与 journal ref；V5 journal 从已验证事件流派生 root spawn、唯一 root exec、监督者绑定摘要，以及按原事件顺序覆盖整个观测进程树的 load-event 摘要。API 不暴露内部 event list。

新增 `f8_r008_supervisor_session_claims_v1.py`：以严格 bounded canonical JSON、独立 Ed25519 domain、同一 caller-supplied candidate key 验证 ledger attestation 与 supervisor-session claim；session 逐项绑定 scope/matrix/row、ledger 和 attestation raw hash、coverage/event/loss 字段、case/attempt/nonce、ledger 派生的 C terminal/ref、V5 journal hash、candidate key fingerprint、root spawn/exec 与 observed-load 摘要。31 个初始合成测试后，按 Terra High P3 建议再补 coverage 明示字段、duplicate-key、journal-ref bool/超限、空 selector 与 child-only load 等用例；四个紧邻 suites **235 passed**，最终九个 F8/Core 跨模块测试文件 **344 passed**。`py_compile` 与 `git diff --check` 通过。

Terra High（`gpt-5.6-terra`, high）最终只读代码复核 `PASS`，无 P0/P1/P2/P3。复核范围仅为代码/合成测试；未读取生产 bundle/frame，也未运行 GenCase/native decoder/worker/solver/GPU/queue。

这仍只证明 caller-supplied candidate key 下两份签名与 ledger/journal claims 的一致性。没有 trusted root/key activation/revocation registry、supervisor identity root、真实事件源完整性或 runtime measurement；`candidate_key_is_active`、`trusted_root_capability_present`、`supervisor_identity_authenticated`、`worker_execution_authenticated`、`process_generation_identity_linked`、`event_source_completeness_verified`、`runtime_identity_verified`、`loaded_module_code_identity_verified`、attempt outcome/T1 全为 false/unresolved，资格 credit 为 0。该更新不提供 worker/solver 执行授权，也不改变 F8 R008 readiness。
