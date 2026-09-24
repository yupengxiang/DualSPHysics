# Core 计划续推状态 UPDATE-80

日期：2026-09-25（Asia/Shanghai）

## 本次完成

为 native-integrity registry 增加 `test_synthetic_gate_diagnostic_rejected_before_aggregation`，覆盖 exact V8 Diagnostic 与附加有效 case/gate 外形的重包装对象；二者均在 row exact-field check 处失败。读取探针证明拒绝早于 `case_id`/`gate_results` 值访问、8-gate 校验和状态聚合。测试 monkeypatch 固定 15-case 常量，因此不读取冻结 receipt。

## 复核与验证

- 仓库 `.venv` 下 `tests/test_f8_r008_native_integrity_registry_v1.py`：26 passed。
- py_compile 与 `git diff --check` 通过。
- 指定 Terra High/high 静态复核通过，无 P0/P1；无独立身份/effort attestation，不作为可审计身份或资格证明。

## 明确未完成与状态边界

V8 要求的“unbound gate rows 在聚合前拒绝”仍未实现。registry 目前是状态聚合器：结构正确的 `{case_id, gate_results}` 行即使来源未绑定，也可产生聚合摘要，但输出固定 `evidence_bindings_verified=false`、`T1_numerical=false`、`readiness_pass=false`、`qualification_credit=0`。当前没有 per-case source-bound gate verifier/capability，也没有 receipt/raw-byte/trust-root/runtime 认证；因此只能声称 exact Diagnostic 形状不会冒充 case row，不能声称 registry consumer gate 通过。

测试全程使用内存状态行和固定 case-ID 常量；未读取生产收据、bundle 或 solver frame，未运行 GenCase/native/solver/worker/GPU/queue。R008 gate open、T1 false、零资格信用。
