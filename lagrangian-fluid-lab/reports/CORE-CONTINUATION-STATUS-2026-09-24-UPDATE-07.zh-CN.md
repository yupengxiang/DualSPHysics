# Core 计划续接状态更新（2026-09-24，update 07）

本更新汇总此前三项窄范围授权的实际状态，并固化最新 F4 资源快照；不扩大 solver、worker、GPU、queue、训练或资格授权。

| 授权任务 | 当前证据与状态 | 可继续动作 |
|---|---|---|
| F8 R002 全新静态设计审查 | 已在 [独立审查收据](../campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r002/static-design-review-v2/receipt.json) 记录 `FAIL_static_GenCase_readiness`：Definition 缺少 GenCase 必需的 `hswl`，并有官方常量兼容缺口。R002 已封闭；不得修改或重试，也不触碰失败的 R001。 | 保留失败结论；任何新方案须是独立新 revision/namespace 和新的 scope 授权。 |
| F3 material row30 资源/调度预检 | [一次性 v2 回执](../campaigns/core-v1/material/evidence/f3-material-row30-resource-preflight-v2/receipt.json) 已消耗，状态 `blocked_no_worker_authorized`。当时负载过高、已有 row30 worker 与调度预留、历史资源台账过期且预计超 CPU core-hour cap；实际未启动 worker，T2 credit 为 0。 | 同 scope 不重试；新尝试需要新的 root resource decision 和独立 worker-launch 授权。 |
| F4 supportcap R002 CPU-native preflight | 最新 17:52:35 UTC 资源快照的唯一 blocker 是 1 分钟 load `146.913 > 128`；静态绑定、RAM、磁盘、F3 worker 和空闲命名空间通过。one-shot 尚未消耗，也未读取源 HDF5。 | 仅在未来即时快照全部通过后执行现有的一次 CPU-native preflight。 |

F8 被接受为第三机制家族候选，但不是已获 T1 资格的家族；F8 R008 的 native preflight 仍为 zero-credit，solver 没有启动。Core live status 与已提交 `completion.json` 一致：`can_finalize=false`，T1 家族 2/3，目标 T1 case-run 缺 432、材料 case-run 缺 288、正式训练缺 9/9、独立完整产品复现未通过；`issues=[]` 仅表示当前登记证据结构有效，不代表计划完成。

F4 本次机器收据见[资源门快照](../campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3/cpu-native-canary-preflight-r002-v1/resource-gate-snapshot-20260923T175235Z-v5.json)。
