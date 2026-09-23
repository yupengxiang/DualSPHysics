# Core 计划续接状态更新（2026-09-24，update 17）

本更新补齐计划第 4.3、5.1 节中的控制器重启／孤儿进程资源保留回归覆盖；不运行科研作业。

- 在 `test_core_runtime_scheduler.py` 增加重启后的两种活进程分支：worker 存活但 heartbeat 文件缺失；worker PID 已失效但 heartbeat 绑定的 child 仍存活。两种情况下均要求保留相同 attempt 与 GPU reservation，不得启动竞争作业。
- 用临时 sleep 子进程和临时 SQLite 状态验证，未接触正式 runtime、队列或 campaign。验证：`pytest tests/test_core_runtime.py tests/test_core_runtime_scheduler.py`，39 passed。
- `core_runtime.py` 生产逻辑未改；无 registry、ledger、分母或科学阈值变更。本测试补的是自动恢复契约覆盖，不等同于两台正式主机上的端到端调度验收，也不改变 Core 完成状态。
