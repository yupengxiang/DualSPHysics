# Core 计划续推状态 UPDATE-127

## 本次推进：F8 R008 attempt-ledger / aggregate V2 静态边界收紧

承接 [UPDATE-125](CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-125.zh-CN.md) 与 [UPDATE-126](CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-126.zh-CN.md)，根据两轮只读实现复核完成以下修正：

- Matrix inspector 将 scope matrix 原始 bytes SHA-256 固定为 `65671b42523cd3a5f82338cc7e2d88890af634195d7013ad969311166ab36ac8`，并以仓库冻结 `receipt.json` 作为真实测试 fixture。字段/语义结构错误仍优先产生具体错误；语义有效但 bytes 不同的矩阵被拒绝。该摘要只钉定内容，不认证调用方、加载代码、receipt producer 或运行时；输出继续明确 `frozen_matrix_source_authenticated=false`。
- 非 `not_started` 的 `attempt_terminal.terminal_ref` 限定为 `stage="runtime"` 且 `role="attempt_terminal"`。
- C 阶段 receipt role 由此前不受契约支持的 `c_receipt` 改为 C v3 合同列出的 `c_v1_receipt`。B/D 名称仍是本诊断编码；尤其不声称已有 live descriptor registry。补充负例，确认旧 `c_receipt` 被拒绝。
- remediation draft 和根目录计划记录同步上述内容，并保留来源/运行时信任缺口说明。

## 独立复核与验证

配置为 `gpt-5.6-terra` / high 的只读复核最终为 `PASS`，无 P1/P2。此前出现的“草案仍写 `C/c_receipt`”结论对应旧快照；按当前工作树及当前文件行号重核后，草案、实现、测试均为 `C/c_v1_receipt`，`c_receipt` 仅保留为预期拒绝的负例输入。

以下四个测试文件合计 **202 passed**：

```text
tests/test_f8_r008_attempt_ledger_v1.py
tests/test_f8_r008_per_case_bundle_verifier_v2.py
tests/test_f8_r008_c_execution_journal_v5.py
tests/test_f8_r008_per_case_bundle_verifier_v1.py
```

另有两个修改脚本 `py_compile` 通过，`git diff --check` 通过；冻结 scope receipt 的实际 SHA 与代码 pin 一致。

## 边界与未完成项

本次只解析冻结 scope receipt 和合成 ledger/aggregate，不读取生产 bundle、HDF5、BI4 或 solver frames，不运行 B/C/D、native decoder、GenCase、solver、worker、GPU 或 queue。未引入 root/sudo 操作。没有可信 descriptor registry、scope/ledger producer authentication、active supervisor attestation verifier 或 runtime/code identity 闭环；因此 `frozen_matrix_source_authenticated=false`、ledger/aggregate 仍属 untrusted diagnostic、attempt 与 case outcome unresolved、`qualification_adjudicated=false`、`T1_numerical=false`、`qualification_credit=0`。F8 R008 的生产 gate 仍未关闭，Core 计划仍未完成。
