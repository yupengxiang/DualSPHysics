# F2 release-speed v2 CPU/native 负证据（2026-09-21）

结论：`F2_receiver_ballistic_catch_release_speed010_v2` 在一次全新 CPU/native
preflight 中被科学硬门关闭。该结果只验证输入闭合，不是 solver 结果，也不产生
T1、T2 或材料 credit。

本次以新的 literal Definition、scope/revision/case 和 output namespace 执行
GenCase 与 native 初始帧解码。粒子身份、XML 对齐、有限值、质量闭合、receiver
surface overlap 和 runtime domain 都通过；但外壁端点零容差门观察到 **3840** 个
流体粒子越过连续外壁范围（`tolerance=1e-8 m`），因此 `all_hard_gates_pass=false`。
这属于新的输入科学失败，不能通过放宽阈值、删粒子、重命名或重跑同一输入修复。

回执：[negative-evidence-v2.json](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-static-receiver-ballistic-catch-release010-v2/preflight-v2/negative-evidence-v2.json)。
原始 preflight：[preflight-v2.json](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-static-receiver-ballistic-catch-release010-v2/preflight-v2/preflight-v2.json)。

执行边界保持关闭：没有启动 solver/GPU/queue，没有写 registry/ledger，没有改变
F2 既有失败分母；15 行候选仍为 `executed=0`、`credit=0`，该一次 preflight
attempt 作为失败证据保留。下一步必须选择全新的物理假设和 Definition，不能在
该 candidate 上授权 protected solver。
