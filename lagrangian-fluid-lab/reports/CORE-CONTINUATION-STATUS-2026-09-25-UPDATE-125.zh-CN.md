# Core 计划续推状态 UPDATE-125

日期：2026-09-25（Asia/Shanghai）

## 本次推进：非授权的 F8 R008 15-case aggregate 投影

新增 `build_untrusted_attempt_aggregate_v2`，按固定 aggregate V2 shape 输出完整 15-row matrix 分母。函数要求 ledger raw bytes 与 runtime/attempt_ledger descriptor-ref 的长度和 SHA 相符；matrix/ledger 的一致性由既有 strict structural inspectors 检查；调用方提交的 unresolved V2 attempt records 必须与 ledger 中观察到的全部 attempt registrations 一一匹配，且按 registration seq 排序后嵌入每个 case row，避免 retry 历史被覆盖或遗漏。

由于当前仍无可信 matrix/ledger source、descriptor-root registry、supervisor attestation/key verifier 或 stage evidence reader，投影保守地将全部 15 行（包括空 attempts 行）标记 `unresolved`，从不推导 `missing`；所有 attempt outcome 只能是 `unresolved`，aggregate 固定 `accounting_unresolved`，`attempt_ledger_complete=false`、`qualification_adjudicated=false`、`T1_numerical=false`、credit 为零。无 attestation 对象时引用为 null；当前 helper 拒绝非 null attestation，避免把未经验证的引用消费成信任。缺少任一已观察 registration 对应的 result 时，拒绝生成 aggregate，而不将拒绝或空列表解释成 missing。

同步 remediation draft，定义 ledger descriptor-ref 与可空 attestation-ref 的边界，记录当前 helper 仅按 caller-supplied structures 做 non-authorizing 投影，不构成可信 inventory 或官方 outcome adjudication。

验证：ledger + V2 tests **61 passed**；集成 ledger + V2 + C-execution V5 + 旧 v1 synthetic B/C/D chain **128 passed**；`py_compile` 与 `git diff --check` 通过。新增测试覆盖 15-row 固定顺序、空 ledger 不产生 missing、retry 顺序/保留、registration inventory 闭合、错误 ledger ref、未经验证的 attestation 与 caller 伪报 passed。

全程仅对 synthetic JSON/对象运行结构代码及测试；未读取生产 bundle/frame/HDF5/BI4/one-shot 数据，未运行 GenCase/native decoder/solver/worker/GPU/queue，未提权或改变外部状态。此次实现没有 Terra High 独立复审，不视为 review 通过。

## 尚未闭合

可信 descriptor-root/source resolution、matrix 固定来源认证、supervisor attestation canonical/signature/active-key 校验、coverage completeness capability、stage receipt/process journal 内容重验、V5/runtime identity gates、可信 outcome/missing/failed/passed 派生、retry allowance/失败分母和 qualification/T1 adjudication 均未完成。该 aggregate 是 unresolved diagnostic，不能用于 qualification、运行授权或资格 credit。详见 [V2 remediation draft](F8-R008-PER-CASE-BUNDLE-VERIFIER-V2-REMEDIATION-DRAFT-2026-09-25.zh-CN.md)。
