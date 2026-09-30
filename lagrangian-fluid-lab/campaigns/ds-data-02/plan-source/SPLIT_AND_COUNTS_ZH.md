# 独立case、覆盖与split

## 数量目标
每族目标48个独立物理案例，共336；先8例（批次），再24（starter），最后48。旧32例F3仅在相同语义与split可兼容时复用，另列legacy/reused/new，不默认与本轮33轨迹引用相加。生产失败、分辨率、重启、标签配置和归档副本不算新增独立物理case。
不能靠同一控制的极密幅值采样代替几何/驱动/机制覆盖。每族原则上两个机制模板、两条主要连续轴、一个有解释的几何或控制留出。

## 48例默认角色（设计目标，非统计充分性证明）
- train 24；validation 6；ID test 6；parameter-OOD test 6；geometry/control-OOD test 6。
- 物理OOD仅超出训练支持，仍在数值参考可信范围内。几何/控制留出至少数个匹配背景，不是一个孤立特殊视频。
- 前8和前24是冻结计划的子集；先冻结候选物理注册表与role，再运行，失败留记录。最多60次生产attempt/族；持续同源失败停批，不能偷偷无限补抽。
- 仅单一模板达标可发布scope-limited starter，但不得声称该族几何泛化完备；另一个模板继续研究或明确缺口。

## 层级键
family_id：机制族；geometry_family_id：形状/拓扑族；control_family_id：规定控制模板。
physical_case_id：连续几何、物性、初态、物理驱动及随机物理扰动完整哈希。
lineage_group_id：同一物理过程的不同数值解与观测派生父组。
paired_background_id：控制其他物理变量的对照背景，可包含不同干预参数的多个physical_case。
source_provenance_id：官方模板/代码来源，只是溯源，不默认把全族锁同一split。

## 防泄漏与公平数据协议
所有窗口/labels/分辨率/重启/预览沿用父split。几何留出按geometry_family，控制留出按control_family。ID内插允许共享几何和模板但物理参数组不同。缺关键物理身份就隔离待补，不随机归组。
静态物性、几何和规定控制曲线可作为已知条件；未来真实流场、未来自由刚体状态和未来出生/死亡真值不作为因果输入。输出观测计划本身不等于未来真值。
本轮只构造公开可审查的development/test候选，不声称已经建立未受研究过程影响的隐藏测试；正式公共发布及隐藏测试另须所有者明确许可。

## 长时、分辨率与规模的附加测试
从测试父组派生多时长/多观测视图，不增加独立case计数；固定物理域改变dp为分辨率，固定局部尺度增大系统为规模。不得把两者混在一项测试中。每族合格后视预算选两个测试父组作多分辨率参考；不是所有48例都三档。

## 汇总必须同时报告
atlas_entries / trajectory_views / unique_physical_cases / qualified_scopes / Q-I_cases / Q-N_cases / split_assigned_cases / new_cases / reused_cases / failures。
33条引用不能声称33个新的独立问题；某个dp下的native ghost/duplicate也不是不同材料粒子。

既有F3的16/4/12等历史开发划分（实际以原manifest为准）不重写以凑新24/6/6/6/6；F3负责人制定兼容的新增角色，完整保留旧开发标签。各分项推荐数并非改变历史split的授权。
