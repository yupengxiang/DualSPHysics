# UPDATE-183：F4R 的 pointref 是全局几何定义输入

时间：2026-09-26（Asia/Shanghai）

为判断是否能构造“只移动池体离散相位、保持液滴格点不变”的静态对照，核对随包 XML 模板、本地官方变更记录与 DualSPHysics 官方预处理说明：

- 官方变更记录将 `<pointref>` 描述为 `<definition>` 内的可选项，用 reference position 与 `Dp` 拟合；随包 [GenCase XML 模板](../../doc/xml_format/GenCase_CaseTemplate.xml) 将它与 `<pointmin>/<pointmax>` 一起放在 `<geometry><definition>` 中，draw 命令则位于其后的 `<geometry><commands>`。[官方变更记录](https://github.com/DualSPHysics/DualSPHysics/blob/ef3721a861fda961f0e2f9ec4cd317b19de99086/CHANGES.txt#L263-L265)；[官方 XML 模板](https://github.com/DualSPHysics/DualSPHysics/blob/ef3721a861fda961f0e2f9ec4cd317b19de99086/doc/xml_format/GenCase_CaseTemplate.xml#L54-L61)
- 官方预处理说明称 GenCase 在 3-D Cartesian mesh 节点上生成粒子；draw commands 用于构造不同 shape，但没有记载一个 per-shape lattice phase 输入。[官方 preprocessing 说明](https://github.com/DualSPHysics/DualSPHysics/wiki/5.-Running-DualSPHysics#53-preprocessing)
- 本地 `GenCase_CaseTemplate.xml`、F4R 六份原始 Definition 和探针输入与上述结构一致。本地仓库没有 GenCase 普通 drawbox/boxfill 的 parser 实现可供静态确认。

**基于上述公开接口结构的推断：**标准、已记录的 `<pointref>` 控制的是整个 case geometry definition 的全局格点相位，而不是单个池体 drawbox 的相位。现有证据不足以断言闭源 GenCase parser 绝不接受任何未文档化的 shape-local 扩展；但不应把这种未证实语法当作 F4 候选输入。

因此 UPDATE-182 的 inward pointref 方案应准确称为“全局初态格点相位候选”。它把液滴和池体一起重新离散，六例总质量虽都更接近 `52.416 kg` 连续质量，却也移动液滴质心、改变液滴粒数与部分边界人口；它不能单独证明池边界离散导致旧轨迹穿墙。若研究目标必须隔离池边界，需要另立具有明示连续几何变化/人口效应的候选设计；若接受全局相位作为干预，则该全局初态变更本身就是研究因素，不能包装为 pool-only 修复。

本轮仅查阅文档，没有 GenCase、solver 或 worker 执行，也未修改输入、注册表或账本。F4 仍未闭合旧穿墙因果与完整 `T₀=4.34 s` 事件窗；`T1/T2=false`，credit=0。
