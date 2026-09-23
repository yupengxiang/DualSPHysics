# Core 计划续接状态更新（2026-09-24，update 02）

本更新补记 A8 已存在的 Ada/H200 案例级运行及配对审计，并追加 F4 R002 的一次新鲜非消耗性资源复查。它不扩大任何 solver、worker、GPU、queue、训练或材料运行授权，也不更改 Core 登记、分母或资格。

## 新完成的探索与收据

- 找到 Ada 与 H200 上同一 F3 validation case 的既有全时域 checkpoint-backed diagnostic rollout。两边均完成 835/835 transition，output receipts 均成功、无缺失输出。此前只查看 H200 reproduction 目录时遗漏了 Ada 对照 attempt。
- 使用与两份运行报告相同 code-closure SHA 的 H200 bundle 比较器，完成 post-hoc paired report、score 和 HDF5 trajectory 检查：两台主机身份不同，输入/代码/checkpoint/case 分母一致，评分、物理统计及逐帧状态比较全部通过。机器收据与详情见 [A8 案例级异机配对审计](A8-CROSS-HOST-DIAGNOSTIC-PAIR-2026-09-24.zh-CN.md)。
- A8 进展只到一个案例的诊断级异机数值复现：checkpoint 是 seed17/update16 工程 preprofile，formal training count=0，`formal_core_case_run=false`，`full_product_reproduction=false`，科学状态 `not_assessed`。所以它没有完成 PLAN 的正式产品验收，也不改变 Core completion gate。
- F4 supportcap R002 的新鲜快照仍只有 load blocker：affinity 128、1 分钟 load `140.033`；RAM、disk、worker、授权和静态绑定均通过。receipt/output 均不存在，one-shot 预检仍未消耗。见[更新后的资源门日志](F4-SUPPORTCAP-R002-CPU-PREFLIGHT-RESOURCE-GATE-2026-09-24.zh-CN.md)及其机器快照。

## 全局 Core 门仍未变化

| 验收项 | 当前状态 |
|---|---|
| 不同 T1 家族 | 2/3（F3、F4） |
| 宏观 T2 家族 | 0/2 |
| 正式训练 | 0/9 |
| T1 目标 case-run | 0/432（缺 432） |
| 模型材料目标 case-run | 0/288（缺 288） |
| PLAN 完整产品级异机复现 | 未通过；目前只完成一个诊断 case 的 paired comparison |
| `can_finalize` | false |

F3 row30 R003 的负结果、F8 R008 的 zero-credit native preflight、F8 R002 禁止重试边界均不变。F3 row30 新 attempt 仍需 root decision 与单独运行授权；F8 native preflight 不授权 solver；F4 只保留现有一次 CPU-native preflight 范围，且必须等后续非消耗性快照满足 load 门后再调用。

## 安全与资源边界

本轮 A8 只读取已有 attempt，把 H200 已产出的 report、scores 和 trajectory 临时复制到本机 `/tmp` 用于配对比较；没有重跑模型或修改远端文件，未把大型 trajectory 纳入 Git。F4 只调用环境资源探针与静态绑定检查，没有运行 `run_preflight()`、访问 10.3 GB 源 HDF5 或写入 one-shot receipt。

下一步继续推进 PLAN 中仍可独立开展的接口/评测/候选审查工作；F4 仅在负载门通过时使用既有的一次性预检授权。正式 A8 复现须等正式 checkpoint 与登记分母就绪，不能用本次诊断 pair 代替。
