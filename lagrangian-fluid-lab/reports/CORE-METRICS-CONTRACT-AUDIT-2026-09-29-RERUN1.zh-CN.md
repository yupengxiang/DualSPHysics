# Core metrics contract 审计（2026-09-29 RERUN1）

本轮结论是：`core_metrics_contract.py` 的指标计算与 synthetic fixture 校验没有代码回归；全局失败来自历史 planning receipt 的 source-closure 已过期。旧的 `contract.json`、`planning-receipt.json` 及其 sidecar 保持原样，没有被覆盖或重写。

旧 receipt 当前仍为 `credit=0`、`qualification_claim=none`，但相对于推进后的 `PLAN.md` 与当前 `core_metrics_contract.py`，其 source binding 已 stale。该 stale 状态按 fail-closed 处理，不得被当作当前绑定或资格证据。

本轮新增日期化 additive bundle：

- `contract-2026-09-29-RERUN1.json`
- `planning-receipt-2026-09-29-RERUN1.json`

当前 rerun 通过 `verify_receipt()`，状态为 `planning_only`，`credit=0`，`qualification_claim=none`；只更新模块专属默认常量与测试入口，使默认验证指向该 additive rerun。没有改动任何正式门禁、分母、registry、ledger 或历史 receipt。

验证：专项 `test_core_metrics_contract.py` 全部通过；`py_compile` 与 `git diff --check` 通过。全程未启动 workload、GPU 或 solver。
