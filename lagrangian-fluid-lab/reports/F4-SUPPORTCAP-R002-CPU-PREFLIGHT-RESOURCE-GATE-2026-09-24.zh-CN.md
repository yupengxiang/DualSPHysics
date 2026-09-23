# F4 supportcap R002 CPU preflight 资源门快照（2026-09-24）

本记录只保存一次非消耗性的资源准入检查。用户此前仅授权 F4 supportcap 新候选的一次 CPU-native canary 预检；该授权不包含 tracer/solver、GPU、队列、T2 扩展或资格记分。

## 检查结果

通过已绑定脚本只读验证了授权、静态设计 recipe、独立 review、候选卡、root review 及相关代码/测试哈希；随后调用执行器的环境探针函数，没有调用 `run_preflight()`，没有写入 one-shot receipt，也没有读取或哈希大型 HDF5 源文件。

| 门 | 快照 | 判定 |
|---|---:|---|
| 当前可用 CPU | 128 | — |
| 1 分钟 load average | 135.7822 | **阻塞**（须不高于可用 CPU 数） |
| 可用 RAM | 225,616,523,264 bytes | 通过（下限 17,179,869,184） |
| 文件系统可用空间 | 8,186,858,048,960 bytes | 通过（下限 8,589,934,592） |
| 活跃 F3 material worker | 无 | 通过 |
| r002 preflight receipt / 输出目录 | 均不存在 | 单次授权尚未消耗 |

## 状态与下一步

- 总体状态：`deferred_resource_gate_not_started`；唯一阻塞项是 1 分钟负载超过 CPU affinity 数。
- 本次没有启动 canary、tracer、solver、GPU、worker 或 scheduler；没有修改 registry、ledger 或资格矩阵；credit 仍为 0。
- 当前授权的一次性执行器会在检查资源前先持久写入 start receipt，所以资源门失败时也会消耗机会。不得在上述阻塞仍存在时调用它。
- 只有之后一份新的非消耗性快照确认所有资源门通过且 receipt/输出空间仍为空时，才调用这次已授权的预检。若失败，保留失败回执，不对同一 scope 重试；无论预检结果如何，都不因此获得 runtime 授权。

## 回执摘要

- `authorization_static_bindings`: pass
- `available_cpu_count`: 128
- `load_average_1_5_15_min`: `[135.7822265625, 135.3095703125, 134.94873046875]`
- `active_f3_material_worker_pids`: `[]`
- `resource_blockers`: `one-minute load average exceeds the CPUs available to this task`
- `receipt_exists`: false
- `output_exists`: false
- `solver_started` / `gpu_started` / `queue_or_scheduler_started`: false
- `registry_mutation` / `ledger_mutation` / `qualification_credit`: 0
