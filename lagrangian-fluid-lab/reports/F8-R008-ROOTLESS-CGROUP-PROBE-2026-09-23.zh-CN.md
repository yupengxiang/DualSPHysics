# F8 R008 rootless cgroup 内存限制探针（2026-09-23）

## 结果

在本机以 rootless `systemd-run --user --scope` 启动一个短暂的 4 GiB 内存限制 scope。scope 存活期间，systemd 报告的 `MemoryMax` 与 cgroup v2 的 `memory.max` 均为 `4294967296` bytes。一个 Python 父进程及其 `/usr/bin/sleep` 子进程同时出现在该 scope 的 `cgroup.procs` 中，且 `/proc/<pid>/cgroup` 指向相同 scope。读到的 `memory.peak` 为 `4657152` bytes；`memory.events` 中 `max`、`oom`、`oom_kill` 和 `oom_group_kill` 均为 0。

结构化回执：[receipt.json](../campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/resource-capability-probe-v1/receipt.json)。

## 结论边界

这验证了当前 user systemd scope 可把指定 `MemoryMax` 写入 cgroup，且父子进程共享受限 cgroup；因此 4 GiB 进程树限制存在一个可用的 rootless 执行机制。它没有施加内存压力，也没有运行 R008 的 GenCase 或 native decoder，所以不能代替原生工具的峰值 RSS／OOM 观测，不能单独解除 R008 资源准入，更不构成运行授权或资格证据。

F8 R008 当前仍是 request-only。F3 material row30 R003 仍在运行且主机负载超过可用 CPU 数，故本次没有启动 R008 原生工具，也没有消耗 F4 一次性 CPU 预检授权。
