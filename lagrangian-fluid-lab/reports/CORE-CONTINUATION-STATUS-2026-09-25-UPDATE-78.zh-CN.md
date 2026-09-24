# Core 计划续推状态 UPDATE-78

日期：2026-09-25（Asia/Shanghai）

## 本次完成

为 V8 consumer 清单中的 T1 metric matrix adapter 新增 `test_synthetic_or_rewrapped_result_rejected_before_metric_parse`。测试把 exact V8 synthetic Diagnostic，以及一个由完整有效 per-case v2 记录出发、仅覆盖为 synthetic schema 的 gate-shaped rewrap，分别放入 15-case mapping，经 `evaluate_metric_matrix_v2()` 断言在 metric 解析前以 schema/shape 错误拒绝。`_validate_case_metrics` sentinel 被设置为立即失败，确保后续 metric parser 未被调用。

## 复核与验证

- 仓库 `.venv` 下完整 `tests/test_f8_r008_t1_metric_matrix_adapter_v2.py`：23 passed。
- 首次用系统 pytest 收集时遇到系统 h5py 3.6.0 与 NumPy 2.2.6 ABI 不兼容；使用仓库已有 `.venv`（h5py 3.16.0）重跑通过，未安装或升级依赖。
- 指定 Terra High/high 静态复核通过，无本范围 P0/P1；无独立身份/effort attestation，不作为可审计身份或资格证明。

## 边界与未完成项

该测试证明 synthetic schema/re-wrap 不被当成 per-case v2 result，而不证明 result 来源可信。它没有独立验证 Diagnostic producer、raw bytes、签名/可信根、loader 或 runtime identity；正确的 per-case schema 伪造仍可能进入 metric validation。native integrity 与正式 T1 adjudication 继续分离；R008 gate open、`T1_numerical=false`、零资格信用。仅构造临时 synthetic matrix/audit/log；未读取 production bundle/solver frame，也未运行 GenCase/native/solver/worker/GPU/queue。
