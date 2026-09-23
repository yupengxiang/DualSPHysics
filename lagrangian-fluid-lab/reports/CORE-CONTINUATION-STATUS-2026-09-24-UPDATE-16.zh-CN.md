# Core 计划续接状态更新（2026-09-24，update 16）

本更新核验 A8 产品化与异机复现链路；验证的是接口/样例能力，不把诊断产物升级为 Core 发布。

- `core_package.py` 已覆盖可搬迁 bundle、清单与文件哈希、可选 checkpoint、独立 Python 路径下的 reader/reproduce 入口，以及损坏资产和未知版本拒绝；`core_benchmark.py` 阶段计划包含 `verify → inspect → train → rollout → evaluate → reproduce`。
- 本次验证相关 A8 测试：`pytest tests/test_core_package.py tests/test_core_benchmark.py tests/test_core_independent_reproduction.py tests/test_core_reproduction_check.py tests/test_core_cross_host_root_review.py`，47 passed。
- 当前登记的跨机 reproduction contract `campaigns/core-v1/evidence/cross-host-reproduction-contract-20260920.json` 明确为 `diagnostic_only=true`、`full_product_reproduction=false`。动态 `core_campaign.py status` 仍为 `can_finalize=false`、independent reproduction=false；正式训练 0/9，故样例 bundle/诊断复现不能满足发布级异机验收。
- 本次未改 bundle、registry、ledger 或任何资格分母；没有启动训练、solver、GPU、worker 或 queue。A8 剩余验收依赖正式模型/完整登记数据，以及另一台物理主机和独立数据根上的 reader→prediction→scoring 复现。
