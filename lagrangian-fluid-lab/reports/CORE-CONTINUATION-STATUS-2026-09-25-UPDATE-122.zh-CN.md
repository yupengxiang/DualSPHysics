# Core 计划续推状态 UPDATE-122

日期：2026-09-25（Asia/Shanghai）

## 本次推进：F8 R008 attempt-result V2 非授权结构入口

新增 `f8_r008_per_case_bundle_verifier_v2.py`，目前只实现严格的 attempt-result exact-shape/type guard，不读取 B/C/D bundle，也不解析或认证 attempt ledger。为避免把 caller 输入误当作证据，该入口只接受 `attempt_outcome="unresolved"`、`failure_class="unresolved_evidence"`、空可信失败位置、六项语义布尔全 false、qualification/T1 全 false 与零 credit；结构上全为 `passed` 的 B/C/D receipt status 仍只属于诊断值。拒绝旧 `all_stages_passed` 字段、额外字段、bool 冒充整数、非法 seq、非连续 frame prefix 和非 canonical/non-finite 时间编码。函数返回 `None`，不发放可供下游消费的 capability。

新增 17 个合成测试：覆盖 restricted schema、结构 status PASS 与 unresolved/零资格边界、caller 自报 semantic/T1/PASS 拒绝及 primitive/sequence/frame 编码负例。结果：V2 suite **17 passed**；V5 journal 合成 suite **66 passed**；现有完整合成 B/C/D reference-chain 单测 **1 passed**；`py_compile` 与 `git diff --check` 通过。现有 B/C/D fixture 本身含空的 `gencase_execution`、`safe_decode_receipt` 和 `solver_execution` 对象，因此该 reference-chain 通过只说明 v1 结构闭环可成立；v1 仍报告 readiness false、零 credit。

## 尚未完成 / 边界

这不是 V2 provenance verifier 或 aggregate：没有 ledger schema parser、trusted append-only inventory/attestation、B/C/D ref-to-event 双向闭合、V5 C execution 语义接入、15-case outcome derivation、retry denominator 或资格 adjudicator。该初始结构入口不校验 ref 指向的对象、冻结 row digest 或 caller 传入字段真实性，绝不可用于认定 receipt、execution、case outcome、missing denominator、T1/readiness 或 credit。还需逐步实现草案中其余合成验收点，并由要求的审查模型对实现作只读审查。全程未读生产 bundle/HDF5/frame/one-shot namespace，未运行 GenCase/native decoder/solver/worker/GPU/queue，也未使用 sudo；资格 credit 与执行授权边界不变。
