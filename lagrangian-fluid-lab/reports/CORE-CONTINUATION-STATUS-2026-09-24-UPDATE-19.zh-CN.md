# Core 计划续接状态更新（2026-09-24，update 19）

本更新审查并补强计划第 5.1 节评测失败分母边界；仅运行本地合成测试，不启动正式评测或科学作业。

- 真实 NaN 预测现在由 `rollout_case` 检出，并经 `evaluate` 验证仍保留已登记帧数、`nonfinite_prediction` 分类及满额失败罚分。
- Python `TimeoutError` 与 `subprocess.TimeoutExpired` 现在归类为 `rollout_timeout`；评测回执逐帧保留 null、固定分母和满额罚分，并计入缺失执行汇总，不因超时丢弃案例。
- 既有覆盖还包括 rollout 提前失败与空帧、诊断短时域的 null 尾帧、科学负结果汇总、注册分母上的缺失执行惩罚。Runtime 子进程超时测试另验证超时 receipt 与 child 清理。
- 验证：`tests/test_core_learning.py tests/test_core_evaluation.py tests/test_core_benchmark.py`，70 passed；`tests/test_core_runtime.py tests/test_core_runtime_scheduler.py`，40 passed；`git diff --check` 通过。
- 边界：这些是合成/单元回归，不代表 432 个 T1 case-run 或 288 个材料 case-run 已执行；若监督器直接杀死整个评测进程，本次评测函数不会产出逐案例评分回执，仍由运行器的 timeout receipt 与预登记矩阵共同保留未完成执行状态。正式评测仍未启动。
