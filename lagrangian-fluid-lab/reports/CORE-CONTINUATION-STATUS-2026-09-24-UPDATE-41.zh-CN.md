# Core continuation status — 2026-09-24 UPDATE-41

## 只读总控状态

在未请求写入 completion snapshot 的前提下运行 `scripts/core_campaign.py status`。当前 `can_finalize=false`；因果 lineage 合同与 evidence validity 检查通过，但六项 Core 完成门中仅这两项为 true。

| 完成门 | 当前状态 |
|---|---|
| T1 家族 | 2/3：F3、F4；F8 尚未取得资格 |
| 宏观 T2 家族 | 0/2 |
| 正式训练 | 0/9；全部登记模型/seed 运行缺失 |
| T1 评测 | 0/432；当前已登记分母 288 项缺失，第三家族还对应 144 项未登记目标分母 |
| 材料评测 | 0/288；全部目标分母缺失 |
| 独立产品复现 | 未通过；需要另一主机、不同数据根目录上的完整非诊断 reader/prediction/scoring receipt 及 root review |
| 因果 lineage / evidence validity | 通过 / 通过 |

当前登记的四个 F4 scope 中，一个通过 T1，其余三个保留为已完成负结果；这不把 F4 计作多个家族。命令返回 `issues=[]` 只表示现有登记结构无内部错误，不代表 Core 完成或分母满足。

本次为只读状态检查，没有写 snapshot、启动计算、修改分母或资源/资格账本。此快照用于确定后续推进顺序，不改变 `PLAN.md` 的验收目标或执行门。
