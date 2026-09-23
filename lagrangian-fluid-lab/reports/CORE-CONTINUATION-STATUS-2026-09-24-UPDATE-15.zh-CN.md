# Core 计划续接状态更新（2026-09-24，update 15）

本更新补强“预检／诊断回执不得授予 T1 资格或缩小正式分母”的回归覆盖；不启动任何科学运行。

- 新增 `test_preflight_or_diagnostic_cannot_claim_qualification_credit`：即使回执带有资格 schema 所需字段并声称 `T1_numerical=true`，只要它是零信用 CPU-native preflight、diagnostic、qualification-only、root-review-only 或 `formal_eligible=false`，Core completion 都必须拒绝该资格、保留完整目标分母并报告证据无效。
- 验证：`pytest tests/test_core_campaign.py`，36 passed；`git diff --check` 通过。只改测试，无生产逻辑或科学门槛变更。
- 重新读取动态状态：`can_finalize=false`；T1 为 F3/F4（2/3），宏观 T2 为 0/2，正式训练为 0/9；目标 T1/material 分母缺 432/288，实际已登记 T1 子分母缺 288，独立复现未通过。因果 lineage 与 evidence validity 通过。
- 本次没有运行 solver、GPU、worker 或 queue，也没有修改 registry、ledger、案例分母、资格矩阵或历史结果。
