# F4 supportcap R002 CPU preflight 资源门更新（2026-09-24）

本记录是对 [首次资源门报告](F4-SUPPORTCAP-R002-CPU-PREFLIGHT-RESOURCE-GATE-2026-09-24.zh-CN.md) 的新鲜、非消耗性复查。用户授权仍仅覆盖该候选的一次 CPU-native canary **预检**；不包括 tracer/runtime、solver、GPU、queue、T2 扩展或资格记分。

## 结果

在项目 `.venv` 中只读复核了授权与静态绑定，并重新探测当前环境。UTC `2026-09-23T17:21:34.784472Z` 快照如下：

| 项目 | 快照 | 门槛 | 结果 |
|---|---:|---:|---|
| CPU affinity | 128 | — | — |
| 1 分钟 load | 148.601 | ≤128 | **阻塞** |
| 可用 RAM | 223,770,488,832 bytes | ≥16 GiB | 通过 |
| 可用磁盘 | 8,186,020,360,192 bytes | ≥8 GiB | 通过 |
| 活跃 F3 material worker | 无 | 必须无 | 通过 |
| one-shot receipt / 输出命名空间 | 均不存在 | 必须全新 | 通过 |

唯一阻塞项仍是 1 分钟 load 高于 CPU affinity。因此没有调用会先占用 one-shot 的 `run_preflight()`，也没有哈希或打开 10.3 GB 源 HDF5；没有启动 canary/tracer/solver/GPU/queue，没有修改 registry/ledger。预检授权仍未消耗。机器可读记录为[资源门快照](../campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3/cpu-native-canary-preflight-r002-v1/resource-gate-snapshot-20260923T172134Z-v2.json)。

第一次用系统 Python 做同一只读探针时，h5py 因 NumPy ABI 不匹配在资源检查前导入失败；未触碰源文件或 one-shot 路径。之后在项目 `.venv` 成功完成资源探针，版本为 Python 3.10.12、NumPy 2.2.6、h5py 3.16.0。

后续须等新的即时快照满足全部门槛，再调用现存一次性 CPU-native 预检。若门槛仍不通过，不消耗该授权；即使预检通过，也仍不授权 runtime canary 或任何科学资格。
