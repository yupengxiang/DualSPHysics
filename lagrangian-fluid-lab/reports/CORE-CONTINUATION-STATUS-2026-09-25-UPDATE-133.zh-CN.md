# Core 计划续推状态 UPDATE-133

## 本次推进：把 B/C/D receipt envelope 与 ledger attempt 身份对齐

在 UPDATE-132 的 caller-supplied raw object 精确集合、长度与 SHA-256 绑定之上，ledger 诊断入口现在对 `b_receipt`、`c_v1_receipt`、`d_receipt` 只做 bounded strict-JSON envelope 检查：复用冻结 stage verifier 中的 schema/required-field/status/time 合同，并将 scope、case、attempt、nonce 与对应 ledger event 比较。返回的 receipt status 仍明确是 caller-provided claim；`stage_bundle_verified=false`、完整 stage 语义未验证、producer/root 未认证、ledger incomplete、outcome unresolved、T1=false、credit=0。

Terra High（`gpt-5.6-terra` / high）只读复核未发现 P1/P2，给出两项 P3：接口说明与新增 envelope 解析不一致，以及单 receipt 上限/schema/scope/timestamp/status 缺专测。说明已修正；增加 identity、malformed JSON、8 MiB 单 receipt cap、schema/scope/status/time/required-field 负测。

实现刻意不修改 `f8_r008_per_case_bundle_verifier_v1.py`：一次宽测试明确证明该文件被 D-stage code-review receipt 固定摘要绑定，编辑会使既有 review binding 失效。最初尝试编辑时四文件 suite 有 13 项因该摘要不匹配而失败；修改已全部还原，并确认 D 单包与完整合成 B/C/D 链可在原冻结源码上通过。该历史失败不计入最终通过数。

## 验证与边界

- `test_f8_r008_attempt_ledger_v1.py`、`test_f8_r008_per_case_bundle_verifier_v2.py`、`test_f8_r008_c_execution_journal_v5.py`：**177 passed**。
- 原冻结 v1 verifier 的 D synthetic bundle 与 full B/C/D provenance-chain 两个定向测试：**2 passed**。
- 修改的脚本和测试 `py_compile`、`git diff --check` 通过。
- 所有新增 reader 输入均为测试内合成 raw bytes；未读取生产 evidence、未查路径对象，也未运行 B/C/D、solver、worker、native decoder、GPU、queue 或 sudo。

此项仅证明调用方提供的 receipt 原始字节满足浅层 envelope 合同并与 ledger 注册身份相符，不验证授权、one-shot lock、完整输出清单、receipt 内嵌产物绑定、文件树、执行过程或可信来源。完整 stage bundle verification、journal 内容与过程关联、descriptor-root / producer / supervisor 信任、F8 T1 和 Core T1/T2 仍未完成，资格信用保持为零。
