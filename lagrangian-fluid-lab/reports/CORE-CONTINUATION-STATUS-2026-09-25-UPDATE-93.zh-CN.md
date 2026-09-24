# Core continuation status — UPDATE-93

日期：2026-09-25

## 本轮推进

F4 tall-wall connector `validate_evaluation()` 经 `_receipt_summary()` 进入时，先由 `_require_evaluation_schema()` 单次读取并验证 exact builtin `core.f4.tallwall120.qualification_evaluation.v2`；unknown/missing/synthetic schema 在 scope/revision/T1/cells 派生和 manifest 路径访问前被拒绝。新增 synthetic read-probe public-entry 回归。

## 验证与边界

- synthetic evaluation 拒绝与合成 bound-audit 8→24 connector 回归：2 passed。
- connector/测试 `py_compile` 与 `git diff --check` 通过。
- 没有读取正式 evaluation、archive、HDF5 或一次性授权回执；未运行 proposal/prepare、worker、solver、GPU、queue 或 GenCase。
- `validate_evaluation()` 仍接受调用方 Mapping，正确 schema 可由调用方伪造；ordinary JSON/raw-byte/duplicate-key/root/source/runtime capability 与 trusted reevaluation producer 仍缺。schema guard 不开放 T1/T2。Terra High/high 外部复核因 agent thread limit 未启动，不记 PASS。
