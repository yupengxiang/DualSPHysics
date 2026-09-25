# UPDATE-177：v5.4 格点/绘制模式语义与 F4R 细档人口一致性

时间：2026-09-26（Asia/Shanghai）

## 官方 XML 指南补充

只读检查随 vendored DualSPHysics v5.4 包提供的 `doc/guides/XML_GUIDE_v5.4.pdf`（SHA-256 `b2def1a1fa920390f1d3a308b191ff7d680ce7045982059e96baec8fe9a15fd1`）：

- §2.2 将 `lattice=1` 定义为每个格点一个粒子、`lattice=2` 为每点两个粒子。F4R Definition 没显式写 `<lattice>`；包内 GenCase XML 模板把 `fluid=1` 标作默认值。
- §2.4.2 将 `<setdrawmode mode="full"/>` 定义为 face 与 solid 模式的组合；`<boxfill>` 用来指定 solid/face 以及隐藏哪些面。
- 同一指南的 REDRAW 说明 GenCase 以 3-D Cartesian lattice 定位粒子并在格点上创建粒子。现有中心/偏置 Definition 是 `boxfill=solid`，但指南没有公布点落在几何边界之间时的精确纳入/取整实现。

## 细档池体人口一致性检查

不重开 HDF5，使用 UPDATE-175 已绑定的取证质量和 Definition：`dp=0.006 m`、`rho=1000 kg/m³`，所以单粒子名义质量为 `rho·dp³=0.000216 kg`。池源离散质量 `48.9888000826 kg` 对应约 `226,800` 个粒子。

若按每个连续 box 端点取最近 Cartesian 节点，池体三轴格点索引分别为 `x=13…187`（175 点）、`y=7…60`（54 点）、`z=7…30`（24 点），乘积恰为 `226,800`。已校验的四角坐标直接落在 x 索引 13/187，并分别对应 y=7/60、z=8。这个聚合人口与边角坐标相互吻合，强烈支持细档有效离散结果采用了最近格点端点；但它不是对所有初始点的逐点闭合，也不是 GenCase 内部实现源码证明。关键现象是 x 端点格点位于连续池箱外 `dp/3`；这解释了“初始质量/体积表示差异”至少一部分来自离散人口，不意味着可重缩放粒子质量。

## 结论与边界

至此可区分三层证据：连续 box 输入边界是确定的；四个记录角点在 Cartesian `dp` 格点上的位置已直接验证；细档总人口与最近格点端点模型一致。仍未获得 GenCase 的具体边界归属代码，不能将该一致性升级为精确 tie-breaking/boxfill 算法证明，也不能证明它导致后续流体穿墙。数值更新、边界生成及其因果贡献仍需有控制的单参数对照。

本次只读 PDF、XML 和既有取证回执，没有运行 GenCase/solver、没有重读 HDF5；没有消耗 F4 CPU-native canary 预检授权。T1/T2=false、credit=0。下一步先核对 `<pointref>`/lattice phase 在公开输入合同中的定义，再判断是否能冻结一个保持连续几何、控制与粒子质量规则不变的独立研究参数；在此之前不预设变更可行。
