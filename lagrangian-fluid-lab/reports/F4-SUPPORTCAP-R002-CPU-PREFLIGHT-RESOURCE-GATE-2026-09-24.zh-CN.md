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

## 后续资源复查

在首次快照后约每隔一分钟又做了两次同样的非消耗性环境探针；没有运行 one-shot 执行器。两次结果均只有 load 门阻塞，F3 worker 仍为空，receipt 和输出目录仍不存在。最新一次：

- CPU affinity：128；load：`134.72998046875 / 132.81787109375 / 133.74853515625`。
- 可用 RAM：`227,678,404,608` bytes；磁盘可用：`8,186,861,146,112` bytes。
- blocker：`one-minute load average exceeds the CPUs available to this task`。

因此目前仍不能调用一次性预检执行器；此结论只适用于这些快照时点，后续应在执行前重新检查。

## 后续资源复查（UTC 2026-09-23 16:59:57）

再做一次新的非消耗性快照。F4 R002 授权及全部静态绑定仍通过；CPU affinity 为 128，1 分钟 load 为 `140.03271484375`，仍高于 128。RAM 为 `222,418,374,656` bytes、可用磁盘为 `8,186,364,747,776` bytes，均高于门槛；活跃 F3 material worker 为空。receipt 和输出 namespace 均不存在。

唯一 blocker 仍是 1 分钟 load。没有调用 `run_preflight()` 或 CLI one-shot runner，没有打开或哈希 10.3 GB 源 HDF5，没有启动 tracer/solver/GPU/queue，也没有消耗一次 CPU-native preflight 授权。机器快照：[resource-gate-snapshot-20260923T165957Z-v1.json](../campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3/cpu-native-canary-preflight-r002-v1/resource-gate-snapshot-20260923T165957Z-v1.json)，SHA-256：`526a489acf35a3876b7f77cce77d68935f9f461561b8be1218045a424f6edfde`。
