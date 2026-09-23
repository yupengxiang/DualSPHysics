# F4 supportcap R002 CPU preflight 资源门更新（2026-09-24，update 02）

这是继 update 01 后的另一份新鲜、非消耗性资源快照。R002 现有一次 CPU-native preflight 授权和静态绑定再次通过；one-shot receipt 与输出命名空间仍为空。

UTC `2026-09-23T17:39:42.313913Z` 的项目 `.venv` 快照为：CPU affinity 128，1/5/15 分钟 load 分别为 `138.610 / 133.234 / 135.747`，可用 RAM `224,511,868,928` bytes，可用磁盘 `8,186,041,671,680` bytes，未见活跃 F3 material worker。唯一 blocker 是 1 分钟 load 高于 128。此前 17:37 UTC 的只读探针曾短暂读到 load1 `130.555`，但仍高于门槛；此后快照回升至 `138.610`，说明不能把短暂接近门槛视作已准入。

因此没有调用会先消耗 one-shot 的 `run_preflight()`；没有哈希/打开源 HDF5，也没有启动 tracer、solver、GPU 或 queue，没有修改 registry/ledger。授权保持未消耗。机器收据见[资源门快照](../campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3/cpu-native-canary-preflight-r002-v1/resource-gate-snapshot-20260923T173942Z-v3.json)。只有新的即时快照满足 load、RAM、disk、worker 和新鲜 namespace 全部门槛后，才执行现存的一次 CPU-native preflight。
