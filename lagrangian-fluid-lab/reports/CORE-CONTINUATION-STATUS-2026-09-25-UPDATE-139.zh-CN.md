# Core 计划续推状态 UPDATE-139

## F8 R008 attempt ledger 到 B/C/D 内容链的逐 attempt 绑定

在 UPDATE-137 的 attempt-evidence binding 上增加 `bind_untrusted_attempt_evidence_with_case_bundles_v1`：以精确 `(case_id, attempt_id, nonce)` 选择 ledger attempt，调用现有 held-FD B/C/D provenance verifier，并将其 receipt SHA-256 与 ledger 引用、stage status 与 attempt projection 对照。跨 attempt 交换 bundle 会被拒绝；所有结果仍标记为 unresolved。

本次同时收紧资源边界：每次调用最多核验一个明确选择的完整 B/C/D attempt，且只接收该 attempt 的 bundle 输入；同一 ledger 中其余完整重试逐项返回为 `unverified`，不会因大映射遍历或批量循环被误记为已核验。调用方授权 bytes 与 code-review receipt 在交给 verifier 哈希前限制为最多 8 MiB。open/partial attempt 仍保留在分母中，不要求伪造 bundle，也不判 missing。

项目虚拟环境下的 8 个跨模块测试文件合计 **312 passed**；`py_compile` 与 `git diff --check` 通过。测试只构造临时合成 B/C/D bundles、ledger 和 HDF5 输入，没有读取或修改生产 bundle/frame，也没有运行 GenCase/native decoder、worker、solver、GPU 或 queue。

这只把调用方提供的 B/C/D 内容链绑定到 ledger 的每次 attempt 引用；仍不认证 authorization issuer、worker/supervisor、执行来源、runtime 或 loaded-module identity，也不将 attempt-result frame projection 与内容 verifier 交叉认定。所有案例/attempt 继续 unresolved，`T1_numerical=false`、qualification credit 为零。可信 worker/执行来源契约及完整来源验证的真实 15 行结果仍未完成，Core 计划不可 finalize。
