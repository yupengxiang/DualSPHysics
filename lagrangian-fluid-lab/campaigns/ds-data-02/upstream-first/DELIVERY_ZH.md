# 本轮交付说明

已按正式采纳目标完成 M1–M4，交付用途为内部数据建设和模型无关数值诊断。窗口起点与14天截止没有重算；达到验收标准后结束，不继续扩张来消耗窗口。

从 [统一交付索引](/home/jade/.codex/worktrees/upstream-first/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/upstream-first/DELIVERY_INDEX_V1.json) 开始；四工况的 [数据卡](/home/jade/.codex/worktrees/upstream-first/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/upstream-first/M4_DATA_CARD_FINAL_ZH.md) 提供字段、用途、真实搬迁路径和读取示例。完整 [验收报告](/home/jade/.codex/worktrees/upstream-first/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/upstream-first/GOAL_COMPLETION_AUDIT_V2.json) 与 [资源审计](/home/jade/.codex/worktrees/upstream-first/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/upstream-first/m4-cost-audit/checkpoints/M4-resource-audit-final-v1.json) 分别记录产品和结算证据。

| 交付 | 已验证的范围 |
| --- | --- |
| M1 | F1官方三维mDBC溃坝与F5二维规则造波两套实际参考包；真实主/辅助观测比较，修正清单哈希与路径；旧结果保留 |
| M2 | LagrangeBench外部归档9个读取窗口及3个反例；自有三维161帧全字段、几何/控制、标签、评分、原路径不可访问时的重放与两项实际篡改检测 |
| M3 | H050/H060两个水深派生的全事件观测比较和241帧原生审计；七族来源/缺口与336条用途索引 |
| M4 | 0.50/0.52/0.58/0.60 m四个独立三维条件，每例241帧完整初始身份轴、全空间状态、几何/控制、数值输运标签；四次实际隔离重放与八项重新计算哈希的篡改检测 |

所有大文件保存在 `/data/nas/jade/Simulation/DualSPHysics/upstream-first/`，代码和控制文档在本隔离工作区。统一索引为各个包附上 [来源与许可侧车](/home/jade/.codex/worktrees/upstream-first/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/upstream-first/SOURCE_AND_LICENSES_V1.json)；许可原文与上游记录快照在 `licenses/`。搬迁交付时保留该许可侧车及对应许可原文。原始数值文件、已经消费的HDF5及验收包未因补充元数据被改写。

LagrangeBench原始数据记录为 CC-BY-4.0，来源和署名见 [Zenodo v2](https://zenodo.org/records/10491868)。DualSPHysics软件许可原文保留；实验参考或生成数据的许可不从软件许可自动推定，没有新授予公共发布许可。

| 资源 | 本轮终态计费增量 | 父账本累计 | 原上限 |
| --- | ---: | ---: | ---: |
| GPU小时 | 0.923396 | 141.140381 | 512 |
| CPU核小时 | 3.621712 | 716.924859 | 3840 |
| 持久数据计费字节 | 167,263,921,180（155.777 GiB） | 10,371,703,752,778 | 按既有Home空闲保护与有界批次策略 |

CPU计费含母例全帧审计的3600核秒保守上限结算，不能称为全部实测耗时。字节计费包括失败产物与搬迁副本，不等同于RAM或瞬时磁盘峰值。H060失败direct001保留并收费；H050外部搬迁副本的5,354,865,799字节已一次性补入账本。历史费用、上限及1024资格/720生产次数限制均保留，本任务活动预约为空。

四个条件同属一条官方母例谱系，全部用于development，validation为空。F1与母例的实际差异保留；F5 ODS仅覆盖[2,15]秒，300个请求样本没有完整参考，解析波比较负结果保留。旧库未扫描、别名和缺件仍如实记录。本版本不宣称数值收敛、实验真值、连续材料轨迹、物理归宿或留出泛化。未运行训练、学习推理或隐藏模型测试，也未公开发布。
