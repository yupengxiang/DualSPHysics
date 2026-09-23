# Core 计划续接状态更新（2026-09-24，update 03）

本更新承接 update 02，修正 F8 R008 frontier 对预检状态的陈旧描述，并追加 F4 supportcap R002 的新鲜资源门探测。只记录已完成证据，不扩大任何 solver、worker、GPU、queue、训练或资格授权。

## 本轮新增

- 新增 [第三 T1 frontier v4](../campaigns/core-v1/evidence/core-third-t1-frontier-audit-20260924-v4.json) 及只读构建器。它保留 v1–v3 为历史快照，绑定 R008 immutable CPU/native receipt、one-shot lock 与 postrun audit，并明确记录：GenCase/native decode 各一次且成功、授权已消耗、同输入重试禁止、solver/GPU/worker/training 未运行、分母和资格 credit 均为零。F8 仍未成为第三 T1 家族。
- F4 supportcap R002 完成一次新鲜、非消耗性资源快照：affinity 128、1 分钟 load 148.601、RAM 与磁盘充足、无 F3 worker、receipt/output namespace 仍为空。唯一 blocker 是 load 超限；CPU-native canary 预检授权未消耗。细节见[资源门更新](F4-SUPPORTCAP-R002-CPU-PREFLIGHT-RESOURCE-GATE-2026-09-24-UPDATE-01.zh-CN.md)。
- F3 material row30 的一次新资源/调度预检已由既有 v2 immutable receipt 消耗；当时 worker 与 scheduler 均活跃、load 超限，且历史 CPU 资源 ledger 过期/超 cap。它没有启动 worker，也不授权新 attempt。R003 负结果保留；新 attempt 仍需新的 root decision 和独立运行授权。
- v4 frontier、v1–v3 历史审计、F8 postrun 审计及 F4 R002 preflight-contract 相关测试：**27 passed**。F4 本轮只执行环境与静态门探针，没有执行其 one-shot preflight。

## Core 全局门

| 验收项 | 状态 |
|---|---|
| 不同 T1 家族 | 2/3（F3、F4） |
| 宏观 T2 家族 | 0/2 |
| 正式训练 | 0/9 |
| T1 目标 case-run | 0/432，缺 432 |
| 模型材料目标 case-run | 0/288，缺 288 |
| 完整产品级异机复现 | 未通过；一个诊断 case 的配对审计不等于产品验收 |
| `can_finalize` | false |

F8 R008 后验 CPU/native 通过不是 T1 资格；F4 当前授权仅允许在实时资源门满足后做一次 CPU-native preflight。计划中的训练、材料、全量评测、产品化和 Core 完成判据仍未闭合。
