# F4 supportcap R002 CPU preflight 资源门更新（2026-09-24，update 04）

这是 17:52 UTC 的新鲜、非消耗性门控快照。静态授权和绑定通过，F3 material worker 未发现，RAM、磁盘及两个 one-shot 命名空间均通过。

CPU affinity 为 128；1/5/15 分钟 load 为 `146.913 / 138.403 / 136.083`，可用 RAM `225,600,962,560` bytes，磁盘可用 `8,185,871,101,952` bytes。唯一 blocker 仍是 1 分钟 load 高于 128。17:49 UTC 的相邻探针 load1 为 `130.232`，也未达到门槛；随后负载回升。

没有调用会消耗 one-shot 的 `run_preflight()`，没有哈希或打开 10.3 GB 源 HDF5，也没有启动 tracer、solver、GPU、queue 或 worker；registry/ledger 未修改。授权仍未消耗。机器收据见[资源门快照](../campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3/cpu-native-canary-preflight-r002-v1/resource-gate-snapshot-20260923T175235Z-v5.json)。
