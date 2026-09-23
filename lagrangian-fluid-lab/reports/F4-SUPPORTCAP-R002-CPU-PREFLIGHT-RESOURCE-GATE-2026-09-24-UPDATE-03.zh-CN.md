# F4 supportcap R002 CPU preflight 资源门更新（2026-09-24，update 03）

这是一次新的非消耗性即时资源探针。授权摘要与全部静态绑定通过复核；one-shot receipt 和输出命名空间仍为空。

UTC `2026-09-23T17:44:44.695724Z` 的项目 `.venv` 快照：CPU affinity 128；1/5/15 分钟 load 为 `134.535 / 132.588 / 134.718`；可用 RAM `224,653,561,856` bytes；可用磁盘 `8,186,033,131,520` bytes；未发现 F3 material worker。唯一 blocker 仍是 1 分钟 load 高于 128。较早的 17:42:22 探针读到 `129.251`，同样未达到门槛；最新值回升，故不能据接近门槛的瞬时读数准入。

没有调用会消耗 one-shot 的预检入口；没有哈希或打开源 HDF5，也没有启动 tracer、solver、GPU、queue 或 worker，没有修改 registry/ledger。授权保持未消耗。完整机器收据见[资源门快照](../campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3/cpu-native-canary-preflight-r002-v1/resource-gate-snapshot-20260923T174444Z-v4.json)。仅当新的即时快照中 load、RAM、disk、worker 和空闲命名空间全部通过时，才可执行现有的一次 CPU-native preflight。
