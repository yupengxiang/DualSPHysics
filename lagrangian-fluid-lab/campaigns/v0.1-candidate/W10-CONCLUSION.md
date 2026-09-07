# W10 结论：数据、因果划分与评测契约

状态：**v0.1 候选协议已机器化，并通过 8 类对抗错误的自检。** 这冻结的是开发级接口，不代表案例物理已经全部通过发布门禁。

## 已冻结的核心语义

- 数据以完整仿真为划分原子，所有帧、窗口、粒子子集、分辨率复本和派生示踪继承 `lineage_group_id` 的 split。设计卡另有独立的 `physical_case_id` 精确标识物理状态；即使两个派生记录误用了不同的 lineage label，只要物理案例相同也不得跨 split。`study_id` 和 `paired_background_id` 只是干预/配对背景命名空间，后者可以按协议跨 split 复用，不能当作谱系键。
- 数值粒子轨迹与独立材料示踪是两条任务轨；前者评估求解状态推进，后者评估来源—路径—去向。
- 世界系和运动体坐标系必须显式声明；运动区域依赖逐帧 proper rigid transform。
- 闭域输运以初始质量为分母，目的地、域内未分类和数值丢失共同闭合，禁止只对幸存粒子重新归一化。
- 宏观探针、撞击压力和刚体位移只在各案例声明的 `validation_scope` 内作为真值评分；其余量只能做诊断。
- 长时预测必须 autonomous rollout；归一化常数只由 train 拟合，逐 seed 报告，置信区间以案例而非帧为采样单位。

## 指标层次

四个独立赛道是数值粒子 rollout、材料输运、物理观测/相互作用和终态结果分类。对应主指标包括按 `dp` 归一化的位置 RMSE、ADE/FDE、目的地质量分布 TV、首达事件准确率与时间误差、液面/压力/刚体外部观测误差。不会用一个混合总分掩盖某条能力缺失；可以另给宏平均摘要，但原始逐案例指标必须公开。

## 对抗测试

`w10-protocol-adversarial.json` 证明门禁会拒绝：非单调时间、valid 下 NaN、非法刚体变换、同 lineage 跨 split、不同 lineage 标签下的同一 physical case 跨 split、幸存质量重新归一化、撞击事件采样不足、用 NaN 隐藏预测，以及逐帧身份置换；同时验证 paired background 跨 split 重用不会被错误拒绝。最后一项通过位置—速度中点积分残差检出，与 W02 的真实身份审计使用同一物理原则。

协议文件位于 `protocol/trajectory-v0.1.md`、`protocol/release-manifest.schema.json` 和 `protocol/benchmark-tasks.json`；参考指标实现在 `scripts/protocol_metrics.py`。W11 的开发级数据必须先生成 manifest 并逐例通过这些约束。
