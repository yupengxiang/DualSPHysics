# UPDATE-208：F3 row30 新鲜资源/调度预检 v7

时间：2026-09-26（Asia/Shanghai）

按用户新授权建立独立 v7 one-shot namespace，并执行一次只读资源/调度预检。新 receipt 绑定 v6 历史，不覆盖或重写 v1–v6。

| 项目 | 观测 | 门限/判定 |
|---|---:|---|
| 可用 CPU | 128 | — |
| 1 分钟 load | 276.693 | 超 128，阻塞 |
| RAM 可用 | 176,974,540,800 bytes | 满足既有下限 |
| 文件系统可用 | 8,172,279,738,368 bytes | 满足既有下限 |
| 活动 row30 worker / scheduler job | 0 / 0 | 无活动任务 |
| 历史 CPU 上界 | 911.958 core-hours | 超旧上限 896，且旧 ledger 于 2026-09-16 过期 |

结果为 `blocked_no_worker_authorized`。因活动资源门、过期 ledger 与历史 CPU cap 三项均阻止 admission，源 HDF5 和 PREPARED 的 SHA 重核按合同短路；本轮未 rehash/open HDF5，未启动 worker/solver/GPU/queue，未改 registry/ledger/T2/资格信用。worker 启动仍需新的 root resource decision 与单独 worker-launch authority。

新增 [v7 immutable receipt](../campaigns/core-v1/material/evidence/f3-material-row30-resource-preflight-v7/receipt.json)、v7 one-shot wrapper 与负例测试。v7 专项 **3 passed**，`py_compile` 与 `git diff --check` 通过。一次性授权已消费，不能对 v7 namespace 重试。

这只更新 F3 资源观察，不接受 R003、不更改 row30 candidate、gate、分母或 T2 credit；Core 总体 plan 仍未完成。
