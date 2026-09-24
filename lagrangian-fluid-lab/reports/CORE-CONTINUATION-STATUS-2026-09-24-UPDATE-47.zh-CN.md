# Core continuation status — 2026-09-24 UPDATE-47

## F8 R002、F3 row30 与 F4 supportcap 的有限授权事项核对

- **F8 R002 静态设计审查：**现有审查结论为 `FAIL`，原因是 Definition 缺少 `hswl`；R002 保持关闭，R001/R002 均未重试。审查报告注明当时虽请求 `gpt-5.6-terra, high`，但 reviewer 未提供模型身份 attestation，因此不将该次身份描述为已独立验证。不得据此改写旧 Definition；若继续，须是新的 revision/namespace/scope。
- **F3 material row30：**按一次性授权，生成新鲜只读资源/调度预检回执 `campaigns/core-v1/material/evidence/f3-material-row30-resource-preflight-recheck-20260924-v1/receipt.json`，SHA-256 `4226115132211af96f23d78ff932db19c0d180c1fb5ac1c5b0ad89562318da53`。状态 `blocked_no_worker_authorized`；当前无匹配 worker、无活动 scheduler job，RAM/磁盘/当前 load 门均未触发阻断；硬阻断为历史资源账本于 2026-09-16 过期，且既有 CPU 上界 `911.957951 core-hours` 已高于 `896` 上限，row30 预计还需 `11.893361 core-hours`。因此源 HDF5/Prepared 哈希按脚本设计短路未复核。回执将 worker/solver/GPU 启动和 queue/ledger/registry mutation 全记为 false/0；没有启动 worker。root decision 仍待决，且本预检不授权 worker。
- **F4 supportcap：**既有 R002 CPU-native canary preflight 已通过，状态 `preflight_passed_runtime_not_authorized`，但 one-shot 已消费；本次没有重跑，也没有启动 tracer/canary、solver、GPU、queue 或 worker。

F3 preflight builder 定向测试 **4 passed**。此更新仅记录用户授权范围内的预检和既有审查状态，不代表 F3 T2、F4 T2 或 F8 T1 通过，也未写入资源账本或调度队列。
