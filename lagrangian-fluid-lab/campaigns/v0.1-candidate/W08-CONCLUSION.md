# W08 结论：受控单轴/双轴泛化协议

状态：**已形成 12 个受控研究和无跨划分泄漏的机器可读设计；身份层次已与 W10 统一。204 个连续轴 execution unit 仍未批量求解；另行声明的四个 topology holdout 均已有独立 candidate 证据，其中 F1/F2/F3 完成归一化结构链，F6 仅完成微时域 solver structural probe，均未升级为正式数据。**

## 研究结构

对 W07 准许继续开发的 F1、F2、F3、F6，每族设置两个单轴研究和一个双轴研究：

- F1：湿床比、阻塞比，以及二者联合变化。
- F2：旋转时长、接收器横向偏置，以及接收距离×偏置。
- F3：强迫频率比、挡板相对高度，以及振幅×频率。
- F6：刚体密度比、入水 Froude 数，以及二者联合变化。

单轴研究每组 5 个训练点、4 个严格位于训练区间内的内插点、2 个位于训练区间外但仍在物理设计域内的外推点。双轴研究使用 3×3 内部训练网格、4 个单元中心内插点、12 个单轴外推点和 4 个联合外推角点。

总计 204 张研究卡，对应 196 个唯一 physical case / execution unit。它们包含少量可复用的相同物理状态；生成器用规范化物理参数哈希得到 `physical_case_id` 和 execution unit，并允许不同研究引用同一个物理案例。实际求解时应只运行唯一 execution unit，而不是机械地运行每张研究卡。

四个身份字段有严格不同的含义：`study_id` 是单轴或双轴因果干预协议；`paired_background_id` 是一个族内各研究共享的固定基线背景，可以有意跨 split 重用；`physical_case_id` 是精确物理参数状态；`lineage_group_id` 是从该物理状态派生的发布谱系，负责把不同分辨率、输出窗口、数值版本和示踪产品绑在同一 split。当前设计中四个家族各有一个 paired background，4 个 exact physical case 被多个 study 复用。

## 防泄漏原则

划分的原子单位是**完整物理仿真及其物理谱系**，不是帧、时间窗口或粒子。一个仿真派生的所有窗口、材料子集、被动示踪和监督目标继承同一 split；分辨率复本及数值方法配对还要按 `lineage_group_id` 成组。`physical_case_id` 也必须保持单一 split，即使错误实现给派生版本分配了不同的 lineage label，W08 审计和 W10 的 `validate_split_lineage` 仍会拒绝它。否则，相邻时间帧或同一初值的不同分辨率会让测试误差虚假偏低。

机器可读审计记录了 `cross_split_physical_case_leakage` 和 `cross_split_lineage_leakage` 两类结果，当前均为空；它不会把有意跨 split 复用的 `paired_background_id` 误报为泄漏。

连续参数外推和拓扑外推必须分别报告。每族另记录一个拓扑留出（F1 twin、F2 spout、F3 perforated proxy、F6 twin free），不把它们混进连续轴成绩。四张独立声明卡均使用独立 `physical_case_id`/`lineage_group_id`，其 definition、GenCase、solver/structural 证据和 candidate-only 验收状态由各自 materialization manifest 追溯；F1/F2/F3 另有归一化 HDF5，F6 明确没有归一化轨迹，`formal_production_authorized=false`。

## 为什么连续矩阵仍不运行

W08 的目的已经达到：把“随机切分看看泛化”替换成了可证伪的因果干预设计。现在执行 204 张连续轴卡仍不合理，因为它们应按唯一 execution unit 去重，且四个 topology 候选均尚未通过分辨率/参考验收；F6 还缺归一化轨迹。W10 的单位、事件采样、有效掩码和指标语义也仍需作为发布约束。先完成候选的科学验收与 F6 轨迹化，再决定小规模开发 tranche，避免一次性转换全部数据。
