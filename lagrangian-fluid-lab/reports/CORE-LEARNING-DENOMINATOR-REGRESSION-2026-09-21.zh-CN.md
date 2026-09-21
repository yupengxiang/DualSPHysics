# Core learning/evaluation 分母合同回归证据（2026-09-21）

## 发现

`score_case` 与 `rollout_completion_semantics` 原先用 `int(...)` 规范化 frame counter。这样会接受 `4.0` 这类非整数值，并把 `3.5` 截断为 `3`；后者可能被误判为完整 actual-time execution，破坏固定分母和完成语义。

## 修复

两个入口现在只接受 Python/NumPy 整数（明确拒绝 `bool`、浮点整数和分数），再进行计数比较。该约束只影响 malformed receipt/input，不改变合法整数的评分、失败惩罚或固定分母。

## 回归验证

```text
.venv/bin/pytest -q tests/test_core_evaluation.py tests/test_core_learning.py \
  -k 'fixed_denominator_rejects_non_integer_frame_counts or completion_semantics_rejects_fractional_or_boolean_counts or failures_keep_registered_denominator or completion_semantics_separate_finite_execution' \
  --disable-warnings --maxfail=1
4 passed, 33 deselected
```

本次仅修改 Core learning/evaluation contract 与 focused tests；未读取或运行 CFD/训练/GPU/queue，也未触碰 F6、registry、ledger、matrix。
