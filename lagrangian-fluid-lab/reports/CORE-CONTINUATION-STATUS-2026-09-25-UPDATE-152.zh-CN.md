# Core 计划续推状态 UPDATE-152

## F8 R002 静态复核与 F3 row30 新资源/调度预检

### F8 R002

按本轮明确授权，对 R002 当前 Definition、控制 CSV、官方 GenCase 兼容性及保留失败证据做了一次新的只读复核。Definition、CSV 和既有 GenCase stdout 的 SHA-256 均与 `static-design-review-v3` 完全相同；GenCase v5.4.354.01 仍以退出码 1 报告 Definition 第 5 行缺 `hswl`。控制 CSV 的 705 行/7 列和严格递增时间轴没有新问题。该结果只是确认旧失败，没有输入漂移或新的独立原因；没有访问或改动 R001，也没有修改 R002 Definition、重跑 GenCase 或改变 one-shot 锁。复核 agent 被请求为 `gpt-5.6-terra/high`，但其最终说明未能 attestate Terra 身份，因此仅记录证据复核，不把它记作 Terra High PASS。R002 保持关闭；不能靠重复静态审查解锁执行。

### F3 material row30

消耗用户授权的一次新资源/调度预检，在独立 v3 namespace 写入不可覆盖 receipt 和 one-shot lock。即时快照为 128 个可用 CPU、load1 `97.81`、可用 RAM `230,882,861,056` bytes、可用磁盘 `8,175,342,002,176` bytes；未发现活动 row30 worker，scheduler active count 为 0。仍有两个硬阻塞：历史 resource ledger 已于 `2026-09-16T00:00:00Z` 过期，且 CPU core-hour upper bound `911.958` 超过 `896` 上限。结果为 `blocked_no_worker_authorized`。因此没有哈希 production source HDF5 或 PREPARED 文件；没有 worker、solver、GPU、queue、ledger 或 registry 写入，T2 credit 为 0。receipt：[v3 预检回执](../campaigns/core-v1/material/evidence/f3-material-row30-resource-preflight-v3/receipt.json)。

v3 builder 复用已审阅的只读 v2 probes，为输出单独版本化 schema、锁和来源绑定。v2+v3 定向测试 **6 passed**，`py_compile` 与 `git diff --check` 通过。新的 root resource decision 和独立 worker-launch authorization 仍是后续必要条件；这次预检不授予它们。

### F4 supportcap

当前仓库只有 `f4_supportcap_affine_query_bound_v3` 候选。它已存在不可变 R002 CPU-native canary preflight receipt，结果 `preflight_passed_runtime_not_authorized`，且明确 `same_scope_retry_allowed=false`；本轮没有新建另一份候选输入。因此不重复消耗旧 one-shot，也不通过改名复用旧范围。旧预检只证明当时输入与环境门通过，不授权 runtime、solver、GPU、queue 或 T2；本轮 F4 新候选预检没有实际消费用户授权，需有独立候选版本后才能实施。
