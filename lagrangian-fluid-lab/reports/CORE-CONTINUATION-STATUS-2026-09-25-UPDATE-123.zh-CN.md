# Core 计划续推状态 UPDATE-123

日期：2026-09-25（Asia/Shanghai）

## 本次推进：F8 R008 append-only attempt ledger 结构解析

新增 `f8_r008_attempt_ledger_v1.py`，对 raw bytes 使用共享 bounded strict-JSON reader，执行精确 ledger/event 字段、固定 schema/scope、64 MiB 上限、digest/ID/nonce/时间编码、连续全局 seq、单调时钟与 coverage 窗口检查。按 attempt 绑定 case/row/ID/nonce，要求唯一 registration 在首位、ID 与 nonce 在 scope 内不复用、stage root/receipt/process-terminal 对应且局部顺序满足 B→C→D；保留未结束 attempt 与 terminal 的 caller 声称值，但其 `attempt_outcome` 只输出 `unresolved`。增加 V2 attempt projection 检查，要求 registration seq、全量且仅有的 ledger event seq、case/row 身份和 stage receipt refs 与 ledger 双向吻合，并拒绝 PASS stage 没有对应 receipt ref、或 `not_run` 与 ref 冲突。

所有入口均非授权：无 descriptor-root reader、stage/terminal registry lookup、process journal/receipt 内容重验、trusted supervisor key/attestation 或 scope coverage activation；`supervisor_attestation_verified=false`、`attempt_ledger_complete=false`、T1 false、零 credit 固定。空 ledger 不推导任何 row 为 missing；结构 terminal 自称 `passed` 也只保留为 `claimed_terminal_outcome`，不派生通过。打开的 spawn/缺 terminal 以 `attempt_events_closed=false` 保留，不从 attempt inventory 删除。

验证：ledger + V2 attempt suites **43 passed**；C journal V5 suite **66 passed**；旧 v1 完整合成 B/C/D reference-chain **1 passed**；`py_compile`、`git diff --check` 通过。测试只用合成内存 JSON；未读取生产 bundle/HDF5/frame/one-shot namespace，未运行 GenCase/native decoder/solver/worker/GPU/queue，未提权。

## 尚未完成

ledger 的 supervisor completeness 签名、out-of-band active/revocation key registry、descriptor-root/固定 role resolution、stage receipt 与 process-journal generation 的真实内容闭合仍缺。attempt-result 的帧轴尚未与冻结 qualification row 逐位对照；B/C/D 语义 verifier、case/15-row aggregate、missing/failed/pass 派生、retry policy/失败分母、native table FD binding、qualification adjudication 与 T1 均未实现。此实现是 ledger 序列及引用形状检查，不足以声明事件 inventory 完整或监督进程真实执行。无受保护 workload 或资格信用。
