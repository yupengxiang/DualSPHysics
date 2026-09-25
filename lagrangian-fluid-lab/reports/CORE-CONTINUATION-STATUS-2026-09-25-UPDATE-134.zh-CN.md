# Core 计划续推状态 UPDATE-134

## 本次推进：将 C V5 process journal nonce 与外层 ledger attempt 对齐

V5 非授权 parser 新增可选 `expected_attempt_nonce_hex`：先验证内层 journal nonce 与外层调用方值的格式，再比较两者；不验证该外层值的来源。F8 ledger raw-object binder 对 C `process_terminal` 引用以该事件 nonce 调用 parser，并在摘要匹配后拒绝 malformed journal 或跨 attempt nonce replay。V5 的 poll/process-local 检查仍只表示 journal 自身声明的局部一致性，不认证实际 event source。

为控制内存型 JSON parser 的资源占用，V5 journal/source-callgraph raw cap 固定为 **16 MiB**，C ledger binding 单 journal 同样 **16 MiB**，ledger 所有 caller-supplied referenced raw objects 合计不超过 **64 MiB**。这些限制均在相关对象 hash/decode/parse 前生效；超限 fail closed。大于 16 MiB 的 journal 需先实现并独立审查 streaming parser，不能绕过 cap。

Terra High（`gpt-5.6-terra` / high）首轮指出 binding 解析资源风险及字段/集成测试缺口；收紧 cap、改名 lifecycle 字段、增加 cap-before-hash、digest-matched malformed journal 与 public-parser cap 测试后，follow-up 未发现 P1/P2/P3。

## 验证与边界

- attempt-ledger、V2 attempt projection、V5 journal：**182 passed**。
- 原冻结 v1 verifier 的 D synthetic 单包及完整 B/C/D provenance chain：**2 passed**。
- 修改的脚本和测试 `py_compile`、`git diff --check` 通过。
- 仅测试内合成 ledger / receipt / journal bytes；没有读取生产 evidence 或调用任何 worker、solver、native decoder、GPU、queue 或 sudo。

本项仅证明 caller-supplied C V5 raw bytes 的结构、外层 attempt nonce 相等及有限的 journal-local consistency；ledger 的 opaque `process_generation_id` 尚未映射到 V5 的实际 generation 记录。Supervisor/source authenticity、event-source completeness、runtime identity、descriptor-root、完整 stage bundle 语义、outcome adjudication、F8 T1 与 Core T1/T2 仍未完成，所有资格信用为零。
