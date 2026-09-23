# F4 supportcap R002 CPU preflight 资源门更新（2026-09-24，update 05）

UTC `2026-09-23T18:06:06.954827Z` 的新鲜、非消耗性快照。CPU affinity 128；1/5/15 分钟 load 为 `138.582 / 141.832 / 139.913`；RAM 可用 `224,310,546,432` bytes；磁盘可用 `8,185,707,143,168` bytes；未发现 F3 material worker。静态绑定和 one-shot receipt/output 空位通过。唯一 blocker 仍是 1 分钟 load 高于 128。

本轮没有调用 `run_preflight()`，没有哈希/打开源 HDF5，也没有启动 tracer、solver、GPU、queue 或 worker；registry/ledger 未修改，F4 一次性授权保持未消耗。机器收据见[资源门快照](../campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3/cpu-native-canary-preflight-r002-v1/resource-gate-snapshot-20260923T180606Z-v6.json)。下一次仅在负载有机会越过门槛后重探；不得将低于前一快照但仍超限视作准入。
