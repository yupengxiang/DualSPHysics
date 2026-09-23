# Core 计划续接状态更新（2026-09-24，update 18）

本更新补齐计划第 5.1 节“调度／OOM 后有界恢复”的决策层回归覆盖；不触发真实 OOM 或扩大作业并发。

- 新测试 `test_oom_at_higher_concurrency_stops_upscaling_despite_throughput_gain` 构造高并发虽报告吞吐上升但发生 OOM 的测量记录，要求 `concurrency_decision()` 优先返回 `increase=false`、`reason=failure_or_oom`。
- 验证：`pytest tests/test_core_runtime.py tests/test_core_runtime_scheduler.py`，40 passed；`git diff --check` 通过。
- 这是合成决策输入测试，不证明真实 GPU OOM/cgroup 恢复或 workload 重试；无生产逻辑、科学门槛、queue、registry、ledger 或分母变更。
