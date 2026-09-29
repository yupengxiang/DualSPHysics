# Core metrics contract 审计（2026-09-29 RERUN2）

本轮仍未发现指标计算、synthetic fixture 校验或门禁逻辑回归；此前并行提交更新了 `core_metrics_contract.py` 的 source closure，导致 RERUN1 绑定过期。旧 planning bundle 与 RERUN1 additive bundle 均保持原样，并按 fail-closed 记为 stale。

新增日期化 additive bundle：`contract-2026-09-29-RERUN2.json` 与 `planning-receipt-2026-09-29-RERUN2.json`。当前 `verify_receipt()` 为 `ok=true`、`status=planning_only`、`credit=0`、`qualification_claim=none`。没有改动正式门禁、分母、registry、ledger 或任何历史 receipt。

验证：`test_core_metrics_contract.py`、py_compile、metrics verify 与 `git diff --check` 通过；全程未启动 workload、GPU 或 solver。
