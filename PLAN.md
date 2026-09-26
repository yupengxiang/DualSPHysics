# 拉格朗日流体标准数据集：多 Agent 全流程推进计划

## 一、目标、现状与研究定位

### 1. 下一轮要交付什么

下一轮以一个**可以独立使用、复现和扩展的多家族内部 benchmark**为交付目标，贯通：

**场景生成 → CFD 数值资格验证 → 数据生产 → 材料标注 → 数据划分 → 模型训练 → 自主 rollout → 统一评测 → 异机复现。**

保留现有 L2-R 的资产、失败记录和资源账本，按上述完整链路重新组织工作包。

首个内部版本，以下称 **Core**，采用这些验收目标：

| 方面 | Core 目标 |
|---|---|
| 数值参考 T1 | 至少三个不同机制家族；保留已合格 F3/F4，第三家族按用户决策优先验证 F8 全充满体力驱动通道，F1/F2作为后备路线 |
| 数据量 | 每个纳入 Core 的家族至少一个合格范围、32个独立开发案例；最低96例 |
| 宏观材料 T2 | 至少两个不同家族的登记范围通过资格验证，并完成相应32例材料侧车 |
| 精确材料路径 | 独立分级、独立报告，不作为宏观 T2 的隐含保证 |
| 学习基线 | 两类架构及一个物理先验对照，共三种配置、三个种子，最低9次正式训练 |
| 模型评测 | 全粒子场自主预测，完成全部登记验证／测试案例的评分与失败分类 |
| 可复现性 | 在另一台机器、不同数据根目录下，通过统一入口复现读数、预测和评分 |
| 发布定位 | 内部开发版本；后续另建最终隐藏测试和公开发布版本 |

**模型预测得不好，可以成为有效 benchmark 结果；参考不可信、接口不通、评测缺失，不能算产品完成。**

### 2. 已有资产与真正需要补齐的部分

本次已接续云端完整对话和另一个任务，并检查代码、登记记录与两台机器资源。当前判断如下：

| 方向 | 可复用资产 | 下一步核心缺口 |
|---|---|---|
| F3 晃荡 | 已登记数值配方、32例开发数据、完整控制记录 | 新控制／几何不能直接继承原范围资格 |
| F4 落池／碰撞 | 中心、偏置两背景，三档分辨率，共6次已有运行 | 细档穿墙、初态质量差异、事件窗过短 |
| F1 溃坝／绕障 | 原生排除取证和运行域修复 | 排除尚未归零，修复后还需完整参考研究 |
| F2 倾倒／接液 | 生成与诊断入口 | 静止保持、运动杯壁、杯口及数值参考接入 |
| 材料系统 | 示踪积分、实体墙可见性、可靠性诊断 | 未知质量偏高、原生输出 cadence 检验、缓存与恢复 |
| 学习系统 | 图模型和若干实际训练尝试 | 旧实验只有128粒子、少量 transition，尚未证明完整场学习能力 |
| 评测与产品 | 协议、审计、manifest；reader bundle v2 现含自足的已哈希 Python 依赖闭包 | 完整三家族产品包的异机读数、预测、评分链仍未通过；Core 总完成判据仍保持严格 |

现有 F3 应继续保留其明确范围：

- 配方：`F3_CELL3_NS_visco1_native_nopen_revision075_ref0081818`。
- 生产粒距 `0.0075 m`，参考档 `0.008181818… / 0.0075 / 0.006 m`。
- 时域 `0–8.35 s`，评分间隔 `0.01 s`，控制幅值 `[0.9, 1.1]`。
- 固定槽体计算坐标、数值粒子身份；材料身份与材料路径另行验收。
- 原有32例保持原划分：16训练、4验证、12开发外推测试。

背景依据继续保存在[项目接续记录](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/PROJECT-CONTEXT-2026-09-19.zh-CN.md)，后续状态以新执行记录为准。

### 3. 调研如何影响设计

截至 2026-09-24，六项依据已按出版方论文页、arXiv 作者记录或官方项目页逐条人工复核；补充目录交叉核对及书目与主张审计见[文献来源审计](lagrangian-fluid-lab/reports/PLAN-REFERENCES-AUDIT-2026-09-24.zh-CN.md)。三源工具已验证 LagrangeBench 与 FD-Bench；FuelTank 的机器核验仍只有一个目录确认，另三篇因 arXiv API 406 待核，故六项自动核验尚未整体完成。执行回执见[首次记录](lagrangian-fluid-lab/reports/PLAN-REFERENCES-VERIFICATION-2026-09-24.json)、[第二次记录](lagrangian-fluid-lab/reports/PLAN-REFERENCES-VERIFICATION-2026-09-24-RERUN1.json)、[第三次记录](lagrangian-fluid-lab/reports/PLAN-REFERENCES-VERIFICATION-2026-09-24-RERUN2.json)、[第四次记录](lagrangian-fluid-lab/reports/PLAN-REFERENCES-VERIFICATION-2026-09-24-RERUN3.json)、[第五次记录](lagrangian-fluid-lab/reports/PLAN-REFERENCES-VERIFICATION-2026-09-24-RERUN4.json)、[第六次记录](lagrangian-fluid-lab/reports/PLAN-REFERENCES-VERIFICATION-2026-09-24-RERUN5.json)和[第七次记录](lagrangian-fluid-lab/reports/PLAN-REFERENCES-VERIFICATION-2026-09-24-RERUN6.json)。第七次仍为 2 项 `verified`、1 项 `unverified`、3 项 `verify_pending`；五个 arXiv ID 查询仍返回 HTTP 406，FluidLab 的 Crossref 请求另遇临时 TLS EOF，自动核验尚未整体通过。该会话已按规则保留机器状态，不能由人工网页核对升格。2026-09-25 上海时间又按原判据执行一次并新增[候选输入](lagrangian-fluid-lab/reports/PLAN-REFERENCES-CANDIDATES-2026-09-25.json)及[第八份回执](lagrangian-fluid-lab/reports/PLAN-REFERENCES-VERIFICATION-2026-09-25-RERUN7.json)：计数未变（2 verified、1 unverified、3 pending），arXiv 仍 HTTP 406，Neural SPH Crossref 临时 TLS EOF；详见[UPDATE-51](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-51.zh-CN.md)。

2026-09-25 新增[第九份回执 RERUN8](lagrangian-fluid-lab/reports/PLAN-REFERENCES-VERIFICATION-2026-09-25-RERUN8.json)：原判据下 5 项 `verified`、1 项 `unverified`、0 项 pending；此前 arXiv 406 在本轮消失并匹配五篇 arXiv 标题。FuelTank 仍只有 Crossref 精确命中；Semantic Scholar title-match 收到 429，DBLP 查询遇 bot challenge，均未重试或替代机器 verdict。故自动核验仍未整体通过，详见[UPDATE-62](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-62.zh-CN.md)。

随后一次新会话按原三源工具重跑，仅新增[RERUN9 回执](lagrangian-fluid-lab/reports/PLAN-REFERENCES-VERIFICATION-2026-09-25-RERUN9.json)：0 项 `verified`、0 项 `unverified`、6 项 `verify_pending`。六项 Semantic Scholar 请求均为 HTTP 429；五个 arXiv 请求均为 HTTP 406；Crossref 对 LagrangeBench、FD-Bench、FuelTank 仍精确命中。按工具规则，API 暂时错误使项目保持 pending；本会话不再重试，人工来源核对不替代机器状态，自动核验仍未整体完成。详见[UPDATE-130](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-130.zh-CN.md)及[文献来源审计](lagrangian-fluid-lab/reports/PLAN-REFERENCES-AUDIT-2026-09-24.zh-CN.md)中的逐轮记录。

2026-09-25 后续续推轮次按相同候选输入和原判据新增[RERUN10 回执](lagrangian-fluid-lab/reports/PLAN-REFERENCES-VERIFICATION-2026-09-25-RERUN10.json)：2 项 `verified`（LagrangeBench、FD-Bench）、1 项 `unverified`（FuelTank）、3 项 `verify_pending`（GNS、Neural SPH、FluidLab）。arXiv 的五个 ID 查询仍为 HTTP 406；Semantic Scholar 恢复并匹配其中五篇，Crossref 匹配 LagrangeBench、FD-Bench、FuelTank。pending 保持原状态，人工来源不替代机器 verdict，六项整体核验仍未完成。详见[UPDATE-142](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-142.zh-CN.md)。

随后同日新增[RERUN11 回执](lagrangian-fluid-lab/reports/PLAN-REFERENCES-VERIFICATION-2026-09-25-RERUN11.json)：仍为 2 项 `verified`、1 项 `unverified`、3 项 `verify_pending`；五个 arXiv 查询均 HTTP 406，Semantic Scholar 命中五篇（FuelTank `not_found`），Crossref 命中 LagrangeBench、FD-Bench、FuelTank。2026-09-26 检查官方[arXiv 状态页](https://status.arxiv.org/)和[Crossref 状态页](https://status.crossref.org/)均显示服务可用；这只是系统级状态，未证明本机此前失败的具体请求已恢复，Semantic Scholar 状态页本轮无法由浏览工具访问。未见 endpoint、API 行为或验证规则已改变的证据，因此未重复机器请求；六篇整体自动核验仍未完成。

2026-09-26 后续新增不可覆盖的 [RERUN12](lagrangian-fluid-lab/reports/PLAN-REFERENCES-VERIFICATION-2026-09-26-RERUN12.json) 与 [RERUN13](lagrangian-fluid-lab/reports/PLAN-REFERENCES-VERIFICATION-2026-09-26-RERUN13.json)。RERUN12 仍为 6 项 pending；对同一五 ID arXiv 查询作单 ID及批量传输对照后，观察到 Python `urllib` 批量请求省略 `Accept` 返回 406，而同查询使用 `Accept: */*` 返回 200。验证器现仅对 arXiv 请求显式发送通配 Accept，离线专项 7 passed。RERUN13 为 2 项 `verified`（LagrangeBench、FD-Bench）、0 项 `unverified`、4 项 `verify_pending`；arXiv 可用并匹配五篇有 ID 的论文，但 Semantic Scholar 六项均 HTTP 429，GNS、Neural SPH、FluidLab 另缺第二个目录精确命中，FuelTank 仍只有 Crossref 匹配。机器核验规则与候选输入未变；六篇整体自动核验仍未完成，详见 [UPDATE-197](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-197.zh-CN.md)。

随后新增不可覆盖的 [RERUN14](lagrangian-fluid-lab/reports/PLAN-REFERENCES-VERIFICATION-2026-09-26-RERUN14.json)，在原“至少两个独立目录精确匹配规范化标题、且无目录冲突”门槛下，将 OpenAlex 作为第四个目录，以候选 DOI（未提供 DOI 时使用规范 arXiv DOI）做单条目查询；候选与精确匹配判据未变。六篇均 `verified`、0 项 `unverified`、0 项 `verify_pending`：GNS、Neural SPH、FluidLab 为 arXiv+Semantic Scholar+OpenAlex；LagrangeBench、FD-Bench 四目录均匹配；FuelTank 为 Crossref+OpenAlex。详见 [UPDATE-198](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-198.zh-CN.md)；此结果只闭合文献身份机器核验，不影响 Core 科学门。

| 工作 | 对本项目的直接启示 |
|---|---|
| [GNS](https://proceedings.mlr.press/v119/sanchez-gonzalez20a.html) | 图消息传递和长期误差积累必须纳入基线设计；单步误差不足以说明模拟能力 |
| [LagrangeBench](https://proceedings.neurips.cc/paper_files/paper/2023/hash/ccac3b120c7dc86d45f56830732b62be-Abstract.html) | 已有多类 SPH 拉格朗日数据集、JAX API、GNS／SEGNN 基线和动能／点云距离指标；我们的贡献不能只表述为“粒子轨迹数据集” |
| [Neural SPH](https://proceedings.mlr.press/v235/toshev24a.html) | 该工作指出张力不稳定导致的粒子聚团，并将压力、黏性、外力等 SPH 成分加入 GNN；当前已知外力残差模型不能冒称完整 Neural SPH |
| [FD-Bench](https://arxiv.org/abs/2505.20349) | 作者 arXiv v2 记录标注已被 KDD 2026 接收；其空间、时间、损失模块对照及传统求解器比较提示应分别控制变量 |
| [Fueltank：A Pioneering Neural Network Method for Efficient and Robust Fuel Sloshing Simulation in Aircraft](https://ojs.aaai.org/index.php/AAAI/article/view/33752) | 已有航空燃油晃荡数据集覆盖多方向旋转工况；不能据此直接主张相关晃荡／多方向驱动问题具有创新性 |
| [FluidLab](https://fluidlab2023.github.io/) | 流体任务可以围绕输运和交互设计，但其模拟数据不能直接充当本项目的 CFD 真值 |

据此，本项目重点验证的贡献是：**在有明确数值可信范围的三维自由表面流动中，建立材料来源、通过、驻留、回流和终点任务，并与动力学预测、泛化能力及计算成本统一评估。**

---

## 二、先冻结公共接口与证据规则

这一部分是并行开发的共同基础。接口先形成小型可运行样例，其他 agent 随后按同一版本接入。

### 1. 数据与资格采用分层记录

每个案例必须分别关联：

| 对象 | 最少记录内容 |
|---|---|
| 物理案例 | 连续几何、初态、物理参数、完整规定控制、坐标系 |
| 数值实现 | 求解器／二进制哈希、边界设置、粒距、时间推进、输出 cadence |
| 物理谱系 | 同一物理过程的分辨率、重启、裁剪和采样视图归属 |
| T1 资格 | 验证对象、参数点／范围、观察窗、观察量、误差门与实际证据 |
| 材料资格 | 来源与目的区域、重建后端、积分方法、未知质量及误差预算 |
| 数据划分 | 训练、验证、ID、OOD、qualification-only |
| 执行记录 | 实际输入、产物哈希、运行状态、失败原因和资源消耗 |

资格状态至少区分：

- `T1_numerical`
- `T2_macro`
- `T2_path`
- `external_physical_validation`

四者独立，不能根据某一项通过自动升级其他项。

所有资格、校准和修复诊断案例登记为 `qualification_only`，其全部派生视图都不能进入模型训练、归一化统计或模型选择。

### 2. 统一模型状态与更新语义

公共模型接口固定为：

```text
State:
  time
  position[N, 3]
  velocity_native_estimate[N, 3]
  particle_id[N]
  particle_zone[N]
  mass[N]
  valid[N]

KnownInputs:
  physics
  numerics
  current_geometry
  prescribed_control
  coordinate_frame
  contract_version

predict_step(state, known_inputs, dt) ->
  displacement_m[N, 3]
  delta_velocity_mps[N, 3]
  diagnostics

commit:
  position_next = position + displacement_m
  velocity_next = velocity_native_estimate + delta_velocity_mps
```

默认学习基线分别学习：

- `x[t+1] − x[t]`
- `v_native[t+1] − v_native[t]`

不把保存帧之间的位移差分直接改名为原生瞬时速度，也不强制两者满足某个简化积分公式。不同模型可用自己的积分器构造这两个返回值。

公共几何输入采用有限实体表面、组件 ID、开口／实体属性、法向、当前姿态和壁面速度。保留历史 F3 特征适配器，但不把硬编码的“五面槽壁、48维特征”提升为所有家族的标准。

### 3. 参考流场和模型流场共享格式，隔离权限

材料重建器可以读取两类来源：

- **参考来源**：登记 CFD 状态。
- **模型来源**：初态、当前预测状态、公开物理参数、公开几何及规定控制。

模型来源不能访问未来 CFD 的速度、密度、压力、存活掩码或自由刚体状态。

首版公共重建后端沿用并校准现有 **Shepard 距离加权插值**。该实现依赖位置和速度，不应描述为已经实现 SPH 体积加权。若以后引入 `m/ρ` 或其他体积近似，另立后端版本并重新验证。[DualSPHysics SPH 公式](https://github.com/DualSPHysics/DualSPHysics/wiki/3.-SPH-formulation)

### 4. 执行状态与科学结论分开

任务至少同时记录：

- 是否实现并实际执行；
- 预登记矩阵是否完整；
- 参考／模型是否通过科学门；
- 产物是否可读取和复现。

总控不能再以“报告文件存在”或“有一次训练 attempt”判定整个工作包完成。

模型失稳可记为已完成的负结果；未实现、未执行、缺失输出和无法解释的基础设施错误仍是未完成。

---

## 三、可直接分配给 Agent 的工作包

### 1. 角色、所有权与交付物

这些是逻辑角色，不要求同时启动同样数量的 agent。

| Agent | 职责与代码所有权 | 主要交付物 | 主要依赖 |
|---|---|---|---|
| C：总控与集成 | 队列、资源准入、账本、依赖、合并 | 持久调度器、完成矩阵、统一执行入口 | 无 |
| A1：协议与数据 | 公共 schema、reader、输入适配、谱系与 split | 版本化接口、小型标准样例、迁移器 | 现有资产 |
| A2：F3 扩展 | 合格配方派生的新控制／几何 | 新 scope 候选卡、资格研究、生产批次 | A1 接口 |
| A3：F4 参考 | 初态、穿墙、事件窗和范围研究 | 第二家族 T1 候选与32例批次 | 可立即取证 |
| A4：F8／F1／F2 | 优先推进用户接受的 F8 第三家族候选；F8 不合格时再转 F1/F2 后备路线 | F8 独立 T1 资格与生产批次；必要时 F1/F2 后备资格 | 静态接口与候选设计已具备；运行须经资源与执行门 |
| A5：材料 | 重建、可靠性、性能、恢复与 T2 矩阵 | 两家族宏观材料参考、材料侧车 | 已有 F3；随后新增 T1 |
| A6：模型 | 模型实现、完整场训练、checkpoint | 9次正式训练及模型适配器 | A1、接口 oracle |
| A7：评测与审计 | rollout、指标、因果检查、失败分母 | 全部模型评测表、独立验收报告 | 接口可先行；模型随后接入 |
| A8：产品与复现 | 打包、CLI、文档、异机复现 | 可移植 Core 包和复现报告 | 样例可先行；完整产物随后接入 |
| A9：后续扩展 | 强基线、F5／F6、外部实验锚点 | 后续版本候选及验证结果 | 不阻塞 Core |

每个工作包统一交付：**代码版本、配置、实际产物、验证结果、资源消耗、未解决问题、下游使用说明**。不能只提交总结文档。

公共 schema 由 A1 维护，评测定义由 A7 维护，中央账本仅由 C 写入。其他 agent 通过提案和版本化接口协作。

### 2. CFD：资格研究与生产分开推进

#### F3：保留旧资产，新增控制和几何分别立项

- 原32例先接入新 reader、模型和评测链路，不等待新增场景。
- 新双轴驱动必须写入实际规定控制；旧代码中的横向初速度扰动不算双轴驱动。
- 新隔板／侧向通路必须基于登记槽体生成。
- 当前观察算子仅适用于原矩形槽，新增实体障碍必须补充几何感知观察算子。
- 控制变化、几何变化各自形成 scope；同时改变两者时只能称综合迁移。
- F3 material row30 的 R003 仍未接受、T2 credit=0。对其 40 个首个 `wall_occluded` seed 的受约束 no-slip replay 已完成 1–16 倍时间细化和 0.25–1.9h 边界层剖面；时间端点已收敛，但每档仍有 16/40 seed 超出冻结 residual 门，近壁约束拟合在所有采样层也持续超限。该候选不用于 retry；历史 unknown/阈值不变。详见[离线 sweep 报告](lagrangian-fluid-lab/reports/F3-ROW30-R003-NOSLIP-REFINEMENT-SWEEP-2026-09-25.zh-CN.md)。

新增 scope 先交付候选参数卡，列明生成器约束、可解析尺度、控制模板和单一研究参数。候选卡经过静态检查、有限 canary 后冻结，再进入范围资格矩阵。尚无证据的物理幅值不能直接填写成已合格范围。

#### F4：先处理已有失败，再延长完整事件窗

- 复核细档的4个初始池角粒子及其后续穿墙，定位边界生成、初态离散与数值更新的责任。
- 统一连续初态定义，量化跨分辨率约5%的初始质量差异；不能通过随意改粒子质量强行对齐。
- 现有 `0–0.6 s` 只能支持早期诊断，需要覆盖接触、上抛／横向传播、回落及后续观察。

窗口初值按连续输入计算：

\[
T_0=\left\lceil
\frac{t_b+4\max(\sqrt{L/g},\,L/\sqrt{gh_p})}
{\Delta t_{\mathrm{out}}}
\right\rceil\Delta t_{\mathrm{out}}
\]

其中 \(t_b\) 为液团最高点到初始池面的解析飞行时间，\(L\) 为相关水平传播距离，\(h_p\) 为初始池深。对整个 scope 使用上界。

系数4是研究设计默认，不是事件完整性的证明。硬完整性通过但事件仍被截断时，整个 scope 统一延长到 `2T₀` 一次；仍不完整则判该候选不足以支持目标机制。

#### F8：用户接受的第三机制家族候选，仍须独立取得 T1

- 候选为**全充满、周期横向边界、固定无滑移壁面、规定振荡体力驱动的通道流**；用户接受其作为第三个不同机制家族的优先候选，不等于接受其数值资格。
- 现行独立候选是 `F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008`。R008 的 15 项资格矩阵、47 组 Definition／控制静态闭合和独立静态设计审查已完成；一次 CPU GenCase/native-decode 预检成功，但资格信用为零。
- R001/R002 已关闭，不得重试。R008 的 solver 尚未运行，`T1_numerical=false`；必须完整执行并审查其预登记 15 项资格矩阵，所有硬门通过后才能把 F8 计入第三家族。运行前仍须遵守当前资源准入与正式执行门，不能把 CPU/native 预检当作 solver 授权。
- R008 生产候选固定为 32 例 `q_i=(i+0.5)/32`，分为 16 train、4 validation、6 ID test、6 OOD test；只有范围资格通过后才按既定 8→32 规则生产。
- 2026-09-24 只读复核重新验证了 CPU/native post-run audit、15+32 输入合同、周期图适配和跨家族数据合同，共 64 项静态回归测试通过。另有 5 项仅适用于预执行空命名空间的 request/authorization builder 测试，在 R008 一次性目录已被占用后按设计 fail-closed；没有删除、覆盖或重试任何证据。相关 post-consumption 与 immutable-audit 测试通过。
- 更正后的只读就绪审计 v3 `campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/t1-execution-readiness-audit-v3/receipt.json` 发现六项执行前语义阻塞。v2 曾把 R001 专用的旧授权构建器误认成 R008 消费者；v3 绑定并核对了 R008 自己的授权与预检链，两者均预期 6,656 个粒子，和保留 Fluid.vtk 的 13 个 z 平面相符。合同记录 `2H/dp=12`，因此“12 个间隔、含两端共13个平面”与实际几何相容；但合同没有明文固定 interval/plane 关系，R001 旧 helper 算出的 6,144 不能归属到 R008。其余五项是 profile z 采样规则、`Uref`、横向速度 RMS、周期平均通量的归一化分母及 CFD 到门控标量的映射、跨分辨率 profile 对齐规则未冻结（Womersley oracle 已有单位跨度面通量积分和零均值周期判据）。v3 保持 `readiness_pass=false`、零资格信用且无执行权限；这不是数值资格失败，也不授权改写 R008 冻结输入。v1/v2 收据均保留为更正链上的历史记录。
- 执行工程仍有明确缺口：当前 `scripts/core_cfd.py` 仅提供 F4 专用 `prepare-f4`/矩阵与 F4 观察审计；虽然 F8 reader、控制合同和周期邻接图已接入，仍没有将 R008 solver 输出转换成 Core 轨迹并按 Womersley oracle 完成 15 格 T1 判定的 F8 worker/调度适配器。只读提案 v1 收到 Terra High（high）独立审查结论 `REVISE`：要求固定谐波正余弦系数接口、严格 native fluid 帧／ID 输入合同、以及三周期共享 seam 的精确分段。追加提案 v2 `campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/t1-metric-semantics-proposal-v2/receipt.json` 已逐项定义这三项，绑定了 fluid-only table schema，并明确现有通用 converter 尚不拒绝所有未知 raw ID，故不能宣称当前实现已满足。Terra High 对 v2 独立只读审查为 `PASS`，审查回执 `campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/t1-metric-semantics-review-v2/receipt.json` 将这些追加语义冻结为仅供静态实现的合同；15格、窗口、阈值、失败分母均未变化，solver/GPU/worker/queue 权限和资格信用仍为零。静态 metric adapter 已进入实现与复核阶段；其后仍须通过资源和正式执行门，不能把静态闭合视为可调度资格作业。
- 2026-09-24：F8 R008 metric adapter v1 已实现，Terra High 静态复核结论 `PASS`，父代理归档于 `t1-metric-adapter-review-v1/receipt.json`。适配器固定校验 scope、参数、Definition pack、语义提案/审查、anchor preflight、GenCase wrapper/binary 及 observation-window parser/Womersley oracle 的哈希；H/dp 固定到冻结行，矩阵对绑定 HDF5 表重读并重算，输出仍为 `full_t1_decision=false`、零资格信用。18 项 adapter 测试通过；此前一次 F8 过滤回归为 275 项通过、7 项因已消费的一次性命名空间或 root-scope packet 历史绑定问题而排除；该 broad run 早于下述最终 RMS 回归测试，未宣称它是当前全量结果。
- 2026-09-24：readiness audit v4 `campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/t1-execution-readiness-audit-v4/receipt.json` 是当时有效的不可变审计收据；其实现与测试哈希均匹配，`verify_audit()` 复算通过。它将 v3 六个语义 gap 映射到已审 proposal 字段、实现函数和测试；几何/端点、profile、Uref、横向 RMS 的 case-specific Uref 归一化与 0.05 门限、cycle flux/seam、跨分辨率插值均闭合，并以非零横向信号回归测试验证 RMS 比率门控；Terra High 同一审查线程的针对性 follow-up 结论为 `PASS`。adapter/review/audit 定向测试 31 项通过。后续 UPDATE-96 对 per-case provenance verifier 的独立静态复核为 `REVISE`，且 15-case T1 结果仍未生成；`readiness_pass=false`、零信用、无执行权限。本次 audit 当时未重新运行 GenCase/solver/worker/GPU/队列。
- 2026-09-24：Terra High（high）对 per-case provenance 设计 v1 给出 `REVISE` 后，同一审查线程对 v2 仅作静态设计 `PASS`，机器归档为 `t1-per-case-provenance-design-review-v2/receipt.json`。v2 明确拆分启动前 admission 与事后已消费 receipt 验证，要求升级 adapter/table provenance schema、绑定逐案例 Definition/control CSV、solver output 与逐帧 decoder/table manifest，并将 provenance、native integrity、15 行/8 个空间比较/CFL/cadence 门和最终 T1 adjudication 分开。尚未实现验证器：首先必须只读冻结 BI4/`bi4_dump` 的完整输出清单、布局、端序和 metadata 合同；若无法由现有代码/产物/文档证明，须单独设计 R008 decoder adapter 再审查。实现还须按 review note 明确检查 `st_nlink == 1`。该设计审查不授权 GenCase/native decode/solver/worker/GPU/queue，不改变 R008 零信用和执行门。
- 2026-09-24：完成 R008 BI4/`bi4_dump` 静态格式审计 v1，机器回执 `campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/bi4-format-static-audit-v1/receipt.json`、说明 `reports/F8-R008-BI4-FORMAT-STATIC-AUDIT-2026-09-24.zh-CN.md`。官方 writer、JBinaryData type/byteorder 代码及已存在 GenCase initial anchor 将评分必需字段收窄为 `Idp/Vel/Rhop` 和依实际 solver 配置恰一 `Pos`/`Posd`；扩展数组必须纳入递归 exact manifest，fresh namespace、no-follow、普通文件及 `st_nlink==1` 为硬条件。R008 尚无 solver frame，且历史 `bi4_dump` binary 未跟踪、无可定位 build 命令，Q1/R008 旧回执未绑定 invocation-time binary hash；报告明确该来源链仍 open，不把初态格式证据升级为 solver provenance。静态审计回归 3 项通过；Terra High follow-up review 待回，不运行任何 native/solver 工具；`readiness_pass=false`、零信用、无 solver 授权。
- 随后的 Terra High（high）只读 follow-up 对 BI4 静态审计 v1 给出 `REVISE`：v1 receipt verifier 未比较完整规范合同；更关键的是，旧 `bi4_dump` 直接拼接 BI4 内部 item/array 名，事后 manifest 不能预防路径逃逸写入。v1 回执保留为历史，未覆盖。v2 receipt `bi4-format-static-audit-v2/receipt.json` 改为完整 canonical payload 比较，并规定当前 decoder 禁止用于新输入；未来必须先全量验证名称，再用 dirfd/openat、no-follow/exclusive、资源上限与完整写错误检查的独立安全 adapter。v2 机器审计及 25 项定向回归通过；Terra High v2 follow-up 待回。安全 adapter 尚未实现/编译，R008 无 solver 帧、历史 binary provenance 仍 open，readiness/credit/solver authority 均不变。
- Terra High（high）v2 follow-up 也为 `REVISE`：指出必须在完整 `LoadFile(..., true)`/大规模分配及任何写入前，对 raw BI4 头、递归深度、节点/数组数量、元素 count、单数组与总字节做有界预检。v3 回执 `bi4-format-static-audit-v3/receipt.json` 已按官方 JBinaryData 结构冻结同一 descriptor 上的 no-follow/hash/fstat、64 MiB raw cap、64-byte header、R008 树深/count/type/name/数组和总输出上限，以及“stream-scan 完整通过后才能二次流式写出”的顺序；超过冻结上限一律 fail-closed。v1/v2 REVISE 历史保留；关联静态测试 28 项通过。Terra High v3 follow-up 待回；scanner/safe decoder 未实现、未编译、未运行，历史 binary linkage 与 R008 solver frames 仍 open，readiness false、零信用、无 solver authority。
- Terra High（high）v3 follow-up 结论 `PASS`（仅静态合同），回执 `campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/bi4-format-static-audit-review-v3/receipt.json`。review 确认有界预解析顺序、R008 数值上限与官方格式相容，v1/v2 缺陷已被合同层处理，且未把历史 binary/source linkage、safe scanner 实现、solver frames、per-case verifier、T1 或信用声称为完成。该 PASS 仅解锁下一步静态实现/代码审查，不授予 decoder/GenCase/solver/worker/GPU/queue 执行权限。
- 2026-09-24：F8 R008 有界 Python BI4 scanner/materializer v1 已实现，并经 Terra High（`gpt-5.6-terra`, high）同一审查线程静态代码复核为 `PASS`；机器归档 `safe-bi4-decoder-review-v1/receipt.json`。首轮 REVISE 的输出父目录威胁模型、item/array 可见标志与官方浮点 XML 格式问题均已修订。合成 BI4 suite 17 passed；R008 相关回归 128 passed、5 项因已消费的一次性 prelaunch namespace 而 deselected。只用临时合成字节样例；未读/解码生产 BI4，未调用 native decoder、GenCase、solver、worker、GPU 或 queue。历史 `bi4_dump` source/build lineage、B/C/D per-case provenance verifier、solver frames 和 15-case T1 仍未完成；readiness false、零信用、无执行权限。
- 2026-09-24 UPDATE-31：在 UPDATE-30 的 B/C 身份闭环之后，新增 additive native-fluid-table schema v2 与 standalone 语义 verifier；v1 schema SHA `2258f903146ee1e0a2b09b616864b770d928270818128826b327aeb625e7a8a8` 未变。Terra High 首轮 REVISE 后的 focused follow-up 为 `PASS`，机器回执 `campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/native-fluid-table-schema-v2/design-review-v2/receipt.json`。定向测试 32 passed，含 archive tests 共 34 passed；仅 synthetic BI4/HDF5。该实现依赖调用方先验验证并绑定 B/C/D 上下文，尚非端到端 provenance orchestration；v2 table producer/metric-adapter 接入、Definition/control 与几何/边界/法向完整审计、生产 solver frames 和 15-case T1 仍未完成。未读生产 bundle 或 solver frames，未调用 GenCase/native decoder/solver/worker/GPU/queue；readiness false、零信用、无执行授权。详细见 [UPDATE-31](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-24-UPDATE-31.zh-CN.md)。
- 2026-09-24 UPDATE-32：新增独立 B/C/D native-fluid-table v2 集成验证层；除阶段回执链外，也核对 B Definition/control 与冻结 pack 及实际源字节、固定参数合同，按持有 fd 流式检查 C 原始 BI4 与 D table，并在结束后重新闭合 provenance。Terra High（high）静态代码复核 `PASS`，机器回执 `campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/native-fluid-table-schema-v2/bundle-review-v1/receipt.json`。跨模块回归 119 passed，归档完整性 2 passed；仅临时 synthetic B/C/D、BI4、HDF5。生产 bundle/solver frames 未读，未调用 GenCase/native decoder/solver/worker/GPU/queue；调用方 authorization authenticity、代码身份与 runtime 假设仍未由工具认证。几何/边界/法向独立审计、v2 producer/metric adapter、生产帧与 15-case T1 仍未完成，readiness false、零信用、无执行权限。详见 [UPDATE-32](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-24-UPDATE-32.zh-CN.md)。
- 2026-09-24 UPDATE-33：新增 F8 R008 冻结 Definition 47 行全量几何静态审计及 Terra High（high）`PASS` 回执 `campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/definition-geometry-audit-v1/receipt.json`。哈希闭环后逐份复算流体盒、壁面参考盒、四层请求、domain margin、支持厚度及 normal 生成声明；DP 覆盖 `.006×5/.0075×39/.009×3`。明确按 frozen scope 和 presence semantics 解释 `XYPeriodic=0`。定向 reviewer 报告 11 passed，几何/pack/B/C/D 文件读取器回归 71 passed，最终 table v2/B/C/D/geometry 联合回归 149 passed，归档/审计 13 passed。未证明生成粒子数、hdp 网格或 `BoundNor` 向量/覆盖率；没有读取 production bundle/solver frame 或运行 GenCase/native/solver/worker/GPU/queue。v2 table producer/metric-adapter 接入、原生几何/法向门禁及 15-case T1 仍未完成，readiness false、零信用、无执行权限。详见 [UPDATE-33](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-24-UPDATE-33.zh-CN.md)。
- 2026-09-24 UPDATE-34：新增 F8 R008 native-fluid-table v2 单案例指标适配器与 B/C/D 持有 FD 编排层。Terra High（`gpt-5.6-terra`, high）经两轮 `REVISE` 后最终只读代码复核 `PASS`，不可变回执 `campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/native-fluid-table-schema-v2/metric-review-v2/receipt.json`。适配器要求 table-v2 已完整验证（含 density/valid/raw frames），只读同一 D-table FD，重验 B/C/D 后 no-follow 重开表路径并确认同一 single-link inode/hash；逐点校验 frozen observation cadence、Uref、profile 和门限返回值。最终定向合成回归父代理及 Terra High 各 14 passed，既有 v1/table/B/C/D/review 回归 68 passed。未读 production bundle/solver frame，未运行 GenCase/native/solver/worker/GPU/queue。仍缺 v2 table producer、15-case/8 空间比较/timestep/cadence matrix adjudicator、solver timestep audit、native-integrity gates 及生产 solver frames；结果仍非 T1，readiness false、零信用。调用方授权/审查真实性和 loaded-module/runtime 身份未认证。详见 [UPDATE-34](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-24-UPDATE-34.zh-CN.md)。
- 2026-09-24 UPDATE-35：新增 bounded streaming v2 table producer primitive 与 15-case v2 matrix metric consumer。producer 在 dirfd 下双遍读取 caller 提供的 source stream，先在临时文件构建并保持 `conversion_complete=false`，完成全表后翻为 true、独立调用 table-v2 verifier，再通过 no-replace link 原子发布；不认证调用方 B/C provenance 或 source-factory 重开/hash 行为。matrix 固定 15-case 分母、8 项空间比较、solver timestep 与 cadence 控制，audit JSON 限 1 MiB 并以 no-follow/nonblocking 打开，所有结果仍 `native_integrity=false`、`T1=false`、`readiness=false`、零信用。Terra High（`gpt-5.6-terra`, high）静态实现审查均为 `PASS`，机器回执分别为 `native-fluid-table-schema-v2/producer-review-v2/receipt.json` 和 `native-fluid-table-schema-v2/metric-matrix-review-v2/receipt.json`。producer 合成 suite 7 passed、matrix 合成 suite 22 passed；包含 table/metric/B-C-D v2、v1 adapters 和两份 review archive 的最终联合 synthetic 回归 96 passed；`py_compile` 与 `git diff --check` 通过。所有输入均为临时合成源帧、HDF5、B/C/D 和 audit 日志，未读 production bundle/solver frame，未运行 GenCase/native decoder/solver/worker/GPU/queue。仍缺 producer 与真实 D-stage/逐案例回执的端到端接线、source/authenticity/runtime 身份闭环、native-integrity gates、solver audit 真实证据和正式 15-case T1；现无生产 solver frames，执行授权门保持关闭。详见 [UPDATE-35](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-24-UPDATE-35.zh-CN.md)。
- 2026-09-24 UPDATE-36：新增 F8 R008 D artifact producer v2，将 safe-BI4 decode、metadata binding 和 native-fluid-table v2 接入冻结的 D v1 receipt / manifest；没有改动 v1 schema。发布前验证 authorization/lock、完整 D 输出树/权限、B/C 绑定、逐帧安全解码与 metadata，并独立重算 table-v2 语义；`receipt.json` 由完整 fsync 临时文件经 `renameat2(RENAME_NOREPLACE)` 原子发布，post-commit close/目录 fsync 错误只返回状态标志。Terra High（`gpt-5.6-terra`, high；agent `01a0d33f-d33b-7552-a92a-22d96ca4d329`）修订版静态复审 `PASS`；D 定向测试 20 passed，包含 v1 authorization、权限、table 预提交拒绝和发布后 I/O 故障；D producer、per-case verifier、table chain/metric、table producer/schema 联合回归 96 passed。仅使用临时合成 B/C/D、BI4、HDF5；未读 production bundle/solver frame，未运行 GenCase/native decoder/solver/worker/GPU/queue。该 producer 不自行执行 receipt 发布后的独立 v1/provenance/table-chain 验证，授权/审查真实性及 loaded-module/runtime identity 仍依赖调用方，新 orchestrator 代码身份未纳入冻结 v1 receipt；group/world 读取仍允许。状态仍 `native_integrity_evaluated=false`、`T1_numerical=false`、`readiness_pass=false`、零资格信用，R008 未取得数值资格。详见 [UPDATE-36](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-24-UPDATE-36.zh-CN.md)。
- 2026-09-24 UPDATE-37：完成 F8 R008 native-state finite evidence v1 静态设计合同，范围仅为 full-axis、全 raw `Pos[d]`/`Vel`/`Rhop`（含 non-fluid）有限值证据，不是 native-integrity adjudication。冻结 exact JSON schema、dtype/type/shape、float extrema 位级规则、B/C/D `passed` 与同一 held-FD provenance/table 快照要求；只接纳 15 个 qualification rows 中逐例的完整证据，不能缩减分母。Terra High（`gpt-5.6-terra`, high；agent `01a0d376-e477-7ab0-be6e-55325dc9de10`）最终只读静态复审 `PASS`。本次无实现、无 pytest；仅静态检查，未读 production bundles/solver frames，未运行 GenCase/native decoder/solver/worker/GPU/queue。状态保持 `native_integrity_evaluated=false`、`T1_numerical=false`、`readiness_pass=false`、零资格信用。下一步仅用临时合成 BI4 实现 FD-preserving finite evidence producer 和测试。详见 [UPDATE-37](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-24-UPDATE-37.zh-CN.md) 与 [设计合同](lagrangian-fluid-lab/reports/F8-R008-NATIVE-STATE-FINITE-EVIDENCE-CONTRACT-V1-2026-09-24.zh-CN.md)。
- 2026-09-24 UPDATE-38：实现 F8 R008 native-state finite evidence v1 synthetic-only scanner/producer，逐帧扫描全 raw `Pos[d]`/`Vel`/`Rhop`（含 non-fluid），直接以同一 BI4 `ScanResult` 复核 D safe-decode receipt、数组/文件 SHA 与输出清单，并在收集前后复验 B/C/D 与 metric-free table-v2 chain。独立 evidence 以 unnamed `O_TMPFILE` + procfs FD hard-link no-replace 发布，提交后验证/持久化/路径身份分别报告；固定零 integrity/T1/readiness/资格信用。最终新增模块 23 项通过，先前相邻链路回归 161 项通过（在最终发布硬化之前）；无生产文件/native/solver/worker/GPU/queue 访问。Terra High 首轮实现复核 `REVISE` 后已修订指出项，但跟进复审因模型容量不足未完成，因此不声称最终 `PASS`；重试待容量可用。path-based verifier 的 TOCTOU、授权/审查真实性和 loaded-module/runtime 身份仍开放。详见 [UPDATE-38](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-24-UPDATE-38.zh-CN.md) 与[实现合同](lagrangian-fluid-lab/reports/F8-R008-NATIVE-STATE-FINITE-EVIDENCE-CONTRACT-V1-2026-09-24.zh-CN.md)。
- 2026-09-24 UPDATE-40：Terra High（`gpt-5.6-terra`, high）对 UPDATE-38 实现的只读跟进审查 `PASS`，无 P0/P1 findings；确认同一扫描结果绑定、冻结资源上限、no-replace 临时文件发布及提交后状态、目录重绑定检查和相应合成负例。该 reviewer 未运行测试；最终实现针对性结果仍为 23 passed。审查关闭实现复审待办，不关闭 native-integrity 算法缺口或执行门。path-based verifier 的并发 TOCTOU、`O_TMPFILE`/procfs 能力依赖及调用方信任边界仍开放；密度/Mach/质量/穿墙/重叠/`BoundNor`/15-case 聚合算法仍未冻结。生产 bundle/solver frame 未读，未运行 native/GenCase/solver/worker/GPU/queue；readiness false、零信用、无 solver authority。详见 [UPDATE-40](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-24-UPDATE-40.zh-CN.md)。
- 2026-09-24 UPDATE-42：Terra High 只读盘点确认现有 finite 子证据不能代替 native-integrity/T1。native gate 语义提案 v1 因全轴扩张、未经证明的 `±H` 墙面、把 mass provenance 升格为新增 T1 gate，以及非机器固定的 aggregate registry 而收到 `REVISE`；additive v2 正在只读复审。density/Mach 人群/窗口、wall signed-distance、overlap 距离定义仍须审查；BoundNor 不得由一个 baseline 初态预检推广。proposal 仅作静态设计，不改 scope/threshold/denominator/authority。详见 [UPDATE-42](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-24-UPDATE-42.zh-CN.md)、[proposal v1](lagrangian-fluid-lab/reports/F8-R008-NATIVE-INTEGRITY-SEMANTICS-PROPOSAL-V1-2026-09-24.zh-CN.md) 与 [proposal v2](lagrangian-fluid-lab/reports/F8-R008-NATIVE-INTEGRITY-SEMANTICS-PROPOSAL-V2-2026-09-24.zh-CN.md)。
- 2026-09-24 UPDATE-43：Terra High 对 native-integrity proposal v2 给出 `REVISE`，要求补齐 `all_state_and_control_values_finite` 语义、排除事件的跨保存间隔完整性证明，并把 control coverage 明确为 `[0,T_end]`。官方 CPU/GPU 源码静态核对发现 `PartOut` 非零事件记录与逐 PART `RunPARTs.csv` 计数可构成未来证据候选，但零事件不写 PartOut、RunPARTs 依赖 Info 输出，且 R008 C/D 链尚未绑定这些记录和完整运行终止证明；因此 v3 将 excluded-fluid 和 all-state finite gate 均保持 `open`。v3 只读复审待 Terra High，未改 scope、八 gate/15×8 分母、阈值、执行许可或资格信用。详见 [UPDATE-43](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-24-UPDATE-43.zh-CN.md) 与 [proposal v3](lagrangian-fluid-lab/reports/F8-R008-NATIVE-INTEGRITY-SEMANTICS-PROPOSAL-V3-2026-09-24.zh-CN.md)。
- 2026-09-24 UPDATE-44：Terra High 对 F8 R008 native-integrity proposal v3 只读静态复核 `PASS`；确认有限值 inventory 与 excluded-fluid gate 均正确保持 open，`PartOut`/`RunPARTs.csv`/完整到 `T_end` 的回执只是未来联合证据候选，control 覆盖为 `[0,T_end]`，八 gate/15×8 分母及权限/信用边界无回归。reviewer 建议后续实现精确表述 cell-division 的 `NpfOut` 条件收集，以及按 PART item/Nout/ID/原因计数校验。PASS 仅解锁固定 registry/aggregate 的静态实现和合成测试；无生产数据、GenCase/native/solver/worker/GPU/queue 权限。详见 [UPDATE-44](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-24-UPDATE-44.zh-CN.md)。
- 2026-09-24 UPDATE-45：新增 F8 R008 native-integrity 固定 registry/aggregate v1 与 synthetic-only tests。registry 深度不可变，锁定八 gate/四态及双冻结 receipt 的 15-case 顺序/hash；open gate 不接受 `defined_pass`，且 incomplete/failure 均保留 120 格。Terra High 首轮 `REVISE` 的可变 registry、摘要不可复算和冻结输入负例缺口均已修复，follow-up 静态代码复核 `PASS`；registry 定向测试 24 passed。产物明确不验证证据字节、不评估 native integrity/T1/readiness，也不授予资格信用。全 state/control finite 和 excluded-fluid 语义仍 open，wall/overlap 仍 open；未运行生产/native/GenCase/solver/worker/GPU/queue。详见 [UPDATE-45](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-24-UPDATE-45.zh-CN.md)。
- 2026-09-24 UPDATE-46：新增 F8 R008 native-fluid gate reducer v1 与合成测试，只计算同一只读 held table FD 上的密度闭区间、Mach 上限和完整包含端点三周期窗口三项；严格绑定表字节摘要，剩余五项 registry gate 保持未评估。Terra High 只读静态复核 `PASS`；focused 12 passed，相邻回归 82 passed，py_compile 通过。调用方仍负责认证 table 语义及重验 B/C/D 来源链，reducer 不验证证据绑定、不产生 native-integrity/T1/readiness 或资格信用。仅临时 synthetic HDF5；未读生产数据、未运行 GenCase/native decoder/solver/worker/GPU/queue。详见 [UPDATE-46](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-24-UPDATE-46.zh-CN.md)。
- 2026-09-24 UPDATE-47：核对有限授权事项：F8 R002 的既有静态审查为 `FAIL`（Definition 缺 `hswl`），候选保持关闭且未重试；既有报告说明其 reviewer 身份未独立 attested。按用户授权另做一次 F3 row30 资源/调度预检，新增不可覆盖回执，结果 `blocked_no_worker_authorized`：无活动 worker/job，但资源账本已过期且历史 CPU 上界超过总上限，故源哈希复核短路；没有 worker/solver/GPU 启动或队列/账本/registry 写入。F4 supportcap R002 CPU-native preflight 既有结果为通过、runtime 未授权，one-shot 已消耗，本轮不重跑。F3 preflight 定向测试 4 passed。以上不改变任何 T1/T2/资格状态。详见 [UPDATE-47](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-24-UPDATE-47.zh-CN.md)。
- 2026-09-24 UPDATE-48：只读核查确认当前 per-case verifier 不验证 C receipt 的 `solver_execution` 内容；合成 fixture 用空对象 `{}` 仍可通过结构验证，C 分支只校验 raw manifest/full-axis 与文件绑定。现有 schema 虽列出执行证据要求，尚无对应语义校验。R008 现存回执记录 solver invocation 为 0，且无 qualification solver-attempt bundle，因此 `control_no_extrapolation` 不得由 Definition/control 静态覆盖推为 pass。下一步先冻结 exact argv/input、日志、资源/终态及 horizon 的 C 执行证据合同，待 Terra High 只读复核后再实现 additive verifier；不改冻结 v1、不启动 solver、不扩大授权。详见 [UPDATE-48](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-24-UPDATE-48.zh-CN.md)。
- 2026-09-24 UPDATE-49：DualSPHysics 源码审计确认控制表越界会端点保持；accinput 默认有效到 `DBL_MAX`，CLI/递归 `OPT` 可覆盖 `TMAX/TOUT/TOUTX/NSTEPS`，CPU `TERMINATE` 与 minimum-fluid 分支也可能改变 horizon/终止。另发现现有 B generated-XML parser 未核对 solver 实际读取 XML 的 `TimeMax`、`TimeOut` 和 control reference。故 full-axis、C `passed` 或零退出码均不足以证明 control-no-extrapolation。新增待审草案列出 C solver-execution 的输入/horizon/终止/资源证据及未决 parser 边界；待 Terra High 只读设计复核后才可实现 verifier，未授权/运行 solver。详见 [UPDATE-49](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-24-UPDATE-49.zh-CN.md) 与[合同草案](lagrangian-fluid-lab/reports/F8-R008-C-SOLVER-EXECUTION-EVIDENCE-CONTRACT-V1-DRAFT-2026-09-24.zh-CN.md)。
- 2026-09-25 UPDATE-50：合同草案的独立只读检查为 `REVISE`，但 reviewer 身份未 attested，明确不记作 Terra High。发现并补入 execve/进程环境/动态代码与输入 inode 的可信见证及 TOCTOU 防护、所有 control query 时刻（非最终帧）的上界证明、CPU `TERMINATE` 运行期完整监控、递归 `OPT`/外部配置 allowlist、restart/path override、CPU/GPU source-to-binary 闭合等要求。当前主机 rootless bubblewrap mount/PID namespace 可提供只读输入 mount 与临时 tmpfs 的候选隔离原语，但不闭合可信见证。Terra High 只读设计复核仍待完成；当前不得据此合同推导 control gate pass，未授权/运行 solver。详见 [UPDATE-50](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-50.zh-CN.md)。
- 2026-09-25 UPDATE-51：按原三目录精确标题规则完成文献机器核验的一次新会话重试，新增固定候选清单及不可覆盖 RERUN7。结果仍为 2 项 `verified`、1 项 `unverified`、3 项 `verify_pending`；五条 arXiv 查询仍 HTTP 406，Neural SPH Crossref 临时 TLS EOF，FuelTank 仍只获 Crossref 确认。离线测试 7 passed；本会话不再重试、不由人工来源升格。该调研子项仍未闭环。详见 [UPDATE-51](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-51.zh-CN.md)。
- 2026-09-25 UPDATE-52：对 F8 R008 C-execution v1 草案的 Terra 配置（`gpt-5.6-terra`, high）只读审查结果为 `REVISE`；没有独立模型身份 attestation，按技术意见记录。核对确认 C v1 verifier 不验证 `solver_execution`，并以 `{}` fixture 通过结构层；当前 CPU/GPU control-query 直接调用链已定位但完整 build/features 调用图未闭合。新增 execution-evidence v2 草案，明确 detached sidecar 与 v1 激活边界、JCS/Ed25519 签名候选、外部 trust-root、输入快照、source-to-binary、配置/horizon/event 证据要求；当前无可信 supervisor/key/builder，真实 gate 必须保持 `open`。未改代码或冻结输入，未运行 solver/worker/GPU/queue。详见 [UPDATE-52](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-52.zh-CN.md) 与 [v2 草案](lagrangian-fluid-lab/reports/F8-R008-C-SOLVER-EXECUTION-EVIDENCE-CONTRACT-V2-DRAFT-2026-09-25.zh-CN.md)。
- 2026-09-25 UPDATE-53：对 v3 synthetic schema 的审查请求指定 `gpt-5.6-terra` / high，但回复自述为 GPT-5 基础配置且无独立身份 attestation，故不计作 Terra High；技术结论为 `REVISE`。发现对象 allowlist/root 配对、exact nested schema/有界值、无环证据图、异常路径永久 open、scope/row 摘要直连及逐 entry `accinput`/cgroup/event 语义仍有缺口。更正 C→B 完整链使用绝对规范化路径，`../B/receipt.json` 只是 synthetic fixture 占位值。新增纯内存 open-only harness v1 草案，不消费 execution evidence；后续按上述技术意见收敛为 v2。生产 execution gate 仍未闭合，R008 `T1_numerical=false`，未运行 solver/worker/GPU/queue。详见 [UPDATE-53](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-53.zh-CN.md)。
- 2026-09-25 UPDATE-54：吸收 UPDATE-53 的未认证技术审查意见，新增 synthetic non-qualifying harness v2 草案：给出输入验证顺序、五个布尔量与全部 diagnostic 状态的唯一映射；将 scope/row token 明确限定为彼此独立的不透明字符串比较；区分 harness 自身 I/O 与调用者输入来源；列出依赖 allowlist、异常可恢复边界及纯内存副作用测试。v2 请求 Terra High 只读复审；未实现代码或测试，不消费 C-v1/production evidence，不运行 solver/worker/GPU/queue；真实 execution gate 仍为 `open`、T1 false、零信用。详见 [UPDATE-54](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-54.zh-CN.md) 与 [v2 草案](lagrangian-fluid-lab/reports/F8-R008-SYNTHETIC-NON-QUALIFYING-CONTROL-HARNESS-V2-DRAFT-2026-09-25.zh-CN.md)。
- 2026-09-25 UPDATE-55：v2 审查请求指定 Terra High，但回复自述为 GPT-5 且无法调用 Terra High，故不计为 Terra 审查；技术意见 `REVISE` 聚焦嵌套重复键保留、深度扫描与 malformed JSON precedence、`MemoryError` 异常边界。新增待审 v3，明确 pair-list `object_pairs_hook`、bounded depth scanner 状态机和错误优先级，并将 `MemoryError` 作为不可恢复边界。未实现/测试 harness，真实 execution gate 保持 open、T1 false、零信用；无 solver/worker/GPU/queue。详见 [UPDATE-55](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-55.zh-CN.md) 与 [v3 草案](lagrangian-fluid-lab/reports/F8-R008-SYNTHETIC-NON-QUALIFYING-CONTROL-HARNESS-V3-DRAFT-2026-09-25.zh-CN.md)。
- 2026-09-25 UPDATE-56：新增 F3 row30 首失败区间 no-slip 1/2/4/8/16 倍时间细化与 0.25–1.9h 边界层离线 sweep。40/40 短区间均完成且端点收敛，但每档仍有 16/40 seed 超原 residual 门，最大约 0.224 m/s；近壁 profile 仍有 16–20/40 seed 越门。拒绝将单墙 no-slip 视为 row30 修复，不变更 R003 unknown、CDF/residence gate、T2 credit 或 root decision。仅只读 native frame/trace；定向 tests 2 passed；未启动 worker/solver/GPU/queue。详见 [UPDATE-56](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-56.zh-CN.md) 与 [报告](lagrangian-fluid-lab/reports/F3-ROW30-R003-NOSLIP-REFINEMENT-SWEEP-2026-09-25.zh-CN.md)。
- 2026-09-25 UPDATE-57：标准 `src/source` 的 CPU/GPU accinput 调用链静态复核确认查询使用当前 `TimeStep`；Symplectic predictor/corrector 都在时间增量前调用，loop 满足 `TimeStep<TimeMax`。因此修正早先对整个 `[TimeIni,TimeEnd]` 的过严要求为每个 entry 的实际活动 query 集与动态有效 horizon 的交集。R008 冻结示例省略 `<time>`、默认 `TimeEnd=DBL_MAX`，但 `TimeMax` 略小于 CSV endpoint；这需由运行时 horizon 证据而非默认值单独判断。CLI/OPT、SaveData 后轮询的 `TERMINATE`、早停、multi-GPU TerminateTimeMax 传播及 source-to-binary/build/features 仍未闭合；gate 继续 open、T1 false、零信用。详见 [UPDATE-57](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-57.zh-CN.md) 与[审计](lagrangian-fluid-lab/reports/F8-R008-CONTROL-QUERY-SOURCE-CALLGRAPH-AUDIT-2026-09-25.zh-CN.md)。
- 2026-09-25 UPDATE-58：继续只读追踪 standard parser，确认 argv 原序解析、`-OPT` 在当前位置递归展开、depth-first 展开顺序中最后一次 `TMAX` 赋值优先；OPT 路径按 cwd 打开，受每文件 50 token/最多 10 层约束。解析后正值 cfg `TimeMax` 覆盖 XML；运行时 `TERMINATE`/minimum-fluid stop 再改变 horizon，`NstepsBreak` 单独早退。尚无 R008 attempt 绑定原始 argv、cwd、OPT bytes/hash/展开序列或实际 binary；因此不能只以单个最终 `TimeMax` 声称无 extrapolation。未实现 parser 或运行 solver；gate open、T1 false、零信用。详见 [UPDATE-58](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-58.zh-CN.md) 与[审计](lagrangian-fluid-lab/reports/F8-R008-TMAX-OPT-OVERLAY-AUDIT-2026-09-25.zh-CN.md)。
- 2026-09-25 UPDATE-59：v3 synthetic non-qualifying harness 收到一轮 Terra 配置请求下的只读技术审查 `REVISE`；reviewer 自述身份仍为 Codex/GPT-5，故不记为 Terra High。v4 草案据实修正 object/payload 字段类型、增加恒 false 的资格/执行授权字段、定义私有 object-pair wrapper 与重复键转换算法、固定非标准 JSON 常量异常映射并删除不可达的深度分支。未实现/测试，未接入 C-v1/生产证据；R008 gate 仍 open、T1 false、零信用。详见 [UPDATE-59](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-59.zh-CN.md) 与[v4 草案](lagrangian-fluid-lab/reports/F8-R008-SYNTHETIC-NON-QUALIFYING-CONTROL-HARNESS-V4-DRAFT-2026-09-25.zh-CN.md)。
- 2026-09-25 UPDATE-60：静态闭合 DualSPHysics 标准启动链的 `DsphConfig.xml` 查找根、CLI/OPT 参数覆盖、case/restart/output 路径解析和 PART restart 多文件/时间语义；确认 CPU/GPU 单卡在主循环前的初始化 `SaveData()` 已调用 `CheckTermination()`，所以 exec 前遗留的 `DirOut/TERMINATE` 可在首步前缩短 horizon。R008 execution evidence 必须绑定 executable-parent config 状态、完整 argv/CWD/OPT、实际 case/restart 输入、唯一 output namespace 和覆盖 startup poll 的运行事件。未运行 solver/worker/GPU/queue；R008 gate open、T1 false、零信用。详见 [UPDATE-60](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-60.zh-CN.md) 与[静态审计](lagrangian-fluid-lab/reports/F8-R008-CLI-RESTART-TERMINATE-STATIC-AUDIT-2026-09-25.zh-CN.md)。
- 2026-09-25 UPDATE-61：静态比较 CPU Makefile、GPU Makefile、CMake 与独立 v5.0.164 non-Newtonian build tree，确认宏/flags/CUDA architectures/输出 target 不唯一，版本注释也不能代表 `main.cpp` 实际版本。`bin/linux` 当前无 DualSPHysics solver binary；该默认输出目录已有 tracked `DsphConfig.xml`，未来 solver 会自动读取。库清单/hash 与 build scripts 不提供实际 builder/executable/load-map attestation；需完整干净构建闭包和可信 source-to-binary/supervisor 绑定，否则 execution gate 保持 open。未编译或运行 solver/worker/GPU/queue。详见 [UPDATE-61](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-61.zh-CN.md) 与[构建审计](lagrangian-fluid-lab/reports/F8-R008-SOURCE-BUILD-PROVENANCE-STATIC-AUDIT-2026-09-25.zh-CN.md)。
- 2026-09-25 UPDATE-62：一次全量文献机器复核将 arXiv API 从此前 406 转为成功，保存 RERUN8：5 项 `verified`、1 项 `unverified`、0 项 pending；FuelTank 仍仅 Crossref 命中，Semantic Scholar 对 DOI 返回 not found，补充 title-match 请求遇 429，未再试；DBLP API 请求受 bot challenge 阻断，未据此改变判据。另以 `/usr/bin/bwrap` 成功运行只读系统挂载/临时 tmpfs 的 rootless namespace 探针，但这不提供 supervisor、可信签名根或 builder 见证。两份指定 Terra High 的只读审查请求均未获得 reviewer 身份 attestation，技术意见为 REVISE（C execution v3 的 ref/journal/schema 缺口及 harness v4 的 non-qualifying 隔离/异常闭合缺口）；故不记为 Terra High PASS，尚未实现相关 parser，也未运行 solver/worker/GPU/queue。详见 [UPDATE-62](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-62.zh-CN.md)。
- 2026-09-25 UPDATE-63：只读闭合标准 `src/source` 中 AccInput 的 CPU/GPU/VRes 调用图及采样时序。常规 Verlet 每个 `ComputeStep` 一次力查询；Symplectic predictor/corrector 各调用一次但共享尚未递增的 `TimeStep`，第二次每 entry 命中 timestep cache；VRes 对各对象同样走 Symplectic 路径。`TimeIni/TimeEnd` 为含端点活动窗，而 `JLinearValue` 在表格范围外端点保持，因此未来 no-extrapolation 应逐 active entry/逐实际 query 证明 `table_first <= t <= table_last`，不能要求 `TimeMax <= table_last`。完成的是 tracked-source 静态调用图，不是 actual binary/build/runtime 绑定；v3 C-execution 草案未改，R008 gate 仍 open、T1 false、零信用。未编译或运行 solver/worker/GPU/queue。详见 [UPDATE-63](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-63.zh-CN.md) 与[调用图审计](lagrangian-fluid-lab/reports/F8-R008-ACCINPUT-QUERY-CALLGRAPH-AUDIT-2026-09-25.zh-CN.md)。
- 2026-09-25 UPDATE-64：继续修订 F8 R008 synthetic non-qualifying harness v5 草案，明定 bounded lexical depth scanner 如何处理 unmatched close、字符串 escape 与 EOF，以固定 malformed JSON 的诊断优先级。Terra High/high 审查请求未获得实际审查或可验证 attestation，故不记为 Terra review；草案仍未审、未实现、未测试，也未接入生产消费者。R008 gate 仍 open、T1 false、零信用；无 production evidence 读取或 GenCase/native/solver/worker/GPU/queue 执行。详见 [UPDATE-64](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-64.zh-CN.md) 与 [v5 草案](lagrangian-fluid-lab/reports/F8-R008-SYNTHETIC-NON-QUALIFYING-CONTROL-HARNESS-V5-DRAFT-2026-09-25.zh-CN.md)。
- 2026-09-25 UPDATE-65：完成 V5 前置要求中的首轮资格消费者代码盘点。确认 `core_formal_readiness._admission_observation` 虽声明 `ADMISSION_SCHEMA`，却未先校验 schema/mode/evidence class；非变更式 helper 探针表明带 synthetic schema 标记和额外伪造 gate 字段的输入会被抽取为 3 个 T1 family/12 个 validation case。该 wrapper 不符合 V5 exact schema，故只证明 helper 缺显式 schema gate，不声称最终 release 可绕过。通用 admission evidence 也没有统一 synthetic-marker 拒绝层；F8 per-case、metric matrix、reducer、registry 各有局部 exact contract，但尚无专门 V5 负向测试。因 V5 未获有效 Terra High 审查，本轮只记录盘点，不改代码/测试、不实现 harness。详见 [消费者盘点](lagrangian-fluid-lab/reports/F8-R008-SYNTHETIC-CONSUMER-INVENTORY-2026-09-25.zh-CN.md)。
- 2026-09-25 UPDATE-66：V5 直接技术审查为 `REVISE`，但 reviewer 无可验证身份/effort attestation，故只计普通技术意见。新增 V6 草案，补全输入 discriminator 逐字段约束、JSON/内部异常映射、production strict decoder 与 source-bound verifier 类型要求、Diagnostic 全字段调用端 validator、优先级冲突矩阵及逐 consumer 拒绝 corpus；流程 attestation 与可测试技术 gate 分离。V6 未实现/未测试，consumer schema guard 未修；R008 gate open、T1 false、零信用，无 solver/worker/GPU/queue。详见 [UPDATE-66](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-66.zh-CN.md) 与 [V6 草案](lagrangian-fluid-lab/reports/F8-R008-SYNTHETIC-NON-QUALIFYING-CONTROL-HARNESS-V6-DRAFT-2026-09-25.zh-CN.md)。
- 2026-09-25 UPDATE-67：V6 direct review 为 `REVISE`（无可独立验证 Terra/effort attestation，仅记技术意见）。V7 修正 shape 章节引用，规定 Diagnostic validator 仅接受精确 builtin dict + 单次 snapshot；production ingress 定义 raw bytes/schema/verifier/version/source-binding 谓词；要求逐 consumer 映射 exact schema、verifier/version、negative pytest node ID，并将实现前设计 gate 与实现后使用前测试 gate 分离。当前清单只覆盖已知 direct consumers，测试节点未实现，consumer gate 明确 FAIL；无代码/parser/consumer/test 变更。R008 gate open、T1 false、零信用，无 solver/worker/GPU/queue。详见 [UPDATE-67](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-67.zh-CN.md) 与 [V7 草案](lagrangian-fluid-lab/reports/F8-R008-SYNTHETIC-NON-QUALIFYING-CONTROL-HARNESS-V7-DRAFT-2026-09-25.zh-CN.md)。
- 2026-09-25 UPDATE-68：V7 直接技术审查 `REVISE`（attestation 不可验证）。V8 修正 allowlist 谓词及原始字节 SHA-256 来源、完整列出 Diagnostic keys/类型并要求只消费 validator 返回 snapshot、将 BOM 明确为 decode 前检测、逐阶段固定异常映射；consumer matrix 现逐条列 exact schema、verifier/source hash 与负向 test node，未实现者明确 BLOCKED；实现前/实现后 gate 拆开并说明最小 fail-closed consumer hardening 范围。V8 未实现/未测试，consumer sweep 未闭合；R008 gate open、T1 false、零信用，无 solver/worker/GPU/queue。详见 [UPDATE-68](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-68.zh-CN.md) 与 [V8 草案](lagrangian-fluid-lab/reports/F8-R008-SYNTHETIC-NON-QUALIFYING-CONTROL-HARNESS-V8-DRAFT-2026-09-25.zh-CN.md)。
- 2026-09-25 UPDATE-69：V8 直接审查 `REVISE`，指出实现前测试 gate 死锁、dict/tuple API 冲突、verifier/root/role trusted dispatch 未定义、consumer 旧 Mapping 入口与 pre-read 字段未逐项约束、源码 SHA 不是 runtime attestation、key order 未被 validator 检查。V9 逐项修订；按所有正向 `T1_numerical` 分支再搜后，补入 Core campaign/production、F4 runner/collector/register/dispatch/connector、F3 material readiness/row30 packet、F3/F4 T2 contract、F4 material preflight 与 supportcap canary authorization 等入口，并显式标记 F4 range-root schema/verifier 未闭合。区分 review-anchor hash 与 trusted launcher runtime identity；当前因无 trusted launcher/root capability 禁止 production acceptance。已消耗的一次性 F3/F4 授权及历史回执不重写/重试；root capability 不等于 sudo。V9 未实现/未测试，新增 consumer verifiers 与负向节点均 BLOCKED；R008 gate open、T1 false、零信用，无 solver/worker/GPU/queue。详见 [UPDATE-69](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-69.zh-CN.md) 与 [V9 草案](lagrangian-fluid-lab/reports/F8-R008-SYNTHETIC-NON-QUALIFYING-CONTROL-HARNESS-V9-DRAFT-2026-09-25.zh-CN.md)。
- 2026-09-25 UPDATE-70：V9 复核 `REVISE`（无独立 model/effort attestation），指出漏列 `core_formal_planner` 正向 T1→formal training plan ingress；F4 collector outer qualification envelope 当前无 schema；F4 range-root schema 实为 `core.qualification.v1`；dispatch helper 不可接受 caller-selected consumer ID；connector evaluation 与 batch decision 必须分别测试。新增 V10 增补：加入 planner、为 collector 定义新 outer schema 且拆 preparation/formal tests、修正 range-root schema、将 consumer identity 固定于 per-consumer wrapper、拆分 connector capabilities/tests。V10 未实现/未测试；training plan 不运行，F8 gate open、T1 false、零信用；不改已消耗 F3/F4 one-shot receipts，无 solver/worker/GPU/queue/native/GenCase。详见 [UPDATE-70](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-70.zh-CN.md) 与 [V10 增补草案](lagrangian-fluid-lab/reports/F8-R008-SYNTHETIC-NON-QUALIFYING-CONTROL-HARNESS-V10-DRAFT-2026-09-25.zh-CN.md)。
- 2026-09-25 UPDATE-71：V10 复核 `REVISE`（无独立 model/effort attestation），指出 batch decision 漏 production design/optional audits、collector nested JSON 缺独立 raw-byte 边界、planner manifest row 可内联 T1/audit、目标调用图与当前实现不符、qualification binding v1 无 scope_id。新增 V11：collector 使用独立 role/hash refs；planner 拒绝 manifest 内联 gate markers；batch decision 改接 design/qualification/audit-set capabilities 并分别设负测；区分当前/目标调用图，不改 v1 schema并定义 scope 交叉绑定。V11 未实现/未测试；无 planner/训练/collector/solver/worker/GPU/queue 执行；F8 gate open、T1 false、零信用，不改 F3/F4 one-shot。详见 [UPDATE-71](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-71.zh-CN.md) 与 [V11 增补草案](lagrangian-fluid-lab/reports/F8-R008-SYNTHETIC-NON-QUALIFYING-CONTROL-HARNESS-V11-DRAFT-2026-09-25.zh-CN.md)。
- 2026-09-25 UPDATE-72：V11 复核 `REVISE`，指出 F4 prepare capability 漏 caller template/status/digest、collector ref/wrapper schema不够 exact、dataset-v2 projection 缺 strict recursive schema 与 raw/canonical digest 混用。V12 补入 admission-v2/v1 strict schemas、双副本等值绑定、旧 tick wrapper fail-closed、KnownInputs contract hash 重算与 decision/preparation capability 分层。后续复核推动 C ref、VRes driver、cache/table、process/thread、promotion-status 与 source-callgraph/extractor 设计修订；最终限定技术复核认为 V12 摘要/状态映射无新阻塞、V4 `input_count=0` 集合矛盾已修正。仍未实现/测试 extractor 或 admission producer；无 planner/collector/prepare/solver 运行，F8 gate open、T1 false、零信用，不改 F3/F4 one-shot。详见 [UPDATE-72](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-72.zh-CN.md)、[V12 草案](lagrangian-fluid-lab/reports/F8-R008-SYNTHETIC-NON-QUALIFYING-CONTROL-HARNESS-V12-DRAFT-2026-09-25.zh-CN.md) 与 [C V4 草案](lagrangian-fluid-lab/reports/F8-R008-C-SOLVER-EXECUTION-EVIDENCE-CONTRACT-V4-SYNTHETIC-ONLY-DRAFT-2026-09-25.zh-CN.md)。
- 2026-09-25 UPDATE-73：新增 C execution-evidence synthetic schema V4 草案，以逐 entry/逐 query journal 替代不准确的全局 horizon 判据，并定义 table/XML raw binding、cache provenance、VRes shared-driver 拓扑、process/thread lifecycle、source-callgraph AST 重算及 scope/row digest 绑定。Terra/high 配置最终限定复核确认 callgraph extractor/digest 规则与零输入实例集合修订在文档层无新阻塞；review 不是独立 attestation。extractor、trusted producer、build/runtime closure、R008 query journal 均未实现，未测试/未运行 solver；gate open、资格信用零。详见 [UPDATE-73](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-73.zh-CN.md) 与 [C execution V4 草案](lagrangian-fluid-lab/reports/F8-R008-C-SOLVER-EXECUTION-EVIDENCE-CONTRACT-V4-SYNTHETIC-ONLY-DRAFT-2026-09-25.zh-CN.md)。
- 2026-09-25 UPDATE-74：为 Core readiness admission helper 增加前置 schema discriminator；unknown/missing/F8 synthetic schema 在 helper 中只读取 `schema` 即返回中性 observation，builder 加入 `ADMISSION_SCHEMA` blocker。纯内存探针与临时 JSON 集成测试覆盖 gate-shaped 伪造字段不污染 T1/validation 汇总；定向测试 6 passed，py_compile 与 diff check 通过。指定 Terra High/high 静态复核认为本范围行为成立且无 P0，但无独立身份/effort attestation，不计作可审计 PASS。此为跨 schema 污染防线，不是 producer/source/runtime 身份验证：普通 JSON parse、duplicate-key/raw-byte/root-bound verifier、capability ingress 仍缺，V8/V12 consumer gate 继续 FAIL。R008 execution gate open、T1 false、零信用；未读 production bundle/frame，未运行 GenCase/native/solver/worker/GPU/queue，未更改 F3/F4 one-shot 授权。详见 [UPDATE-74](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-74.zh-CN.md)。
- 2026-09-25 UPDATE-75：为通用 Core admission auditor 的 global T1 extraction 限定 exact `core.qualification.v1` schema；synthetic、unknown、missing schema 不进入 family/scope/T1 全局判定；既有 F3/F4 该 schema 路径以测试确认保持。admission/readiness 定向回归 15 passed，py_compile 与 diff check 通过；指定 Terra High/high 静态复核无本范围 P0/P1，但无独立身份/effort attestation。该 discriminator 不认证 producer：正确 schema 标签仍可伪造，nested case-level evidence 仍走旧路径，strict raw-byte/root-bound verifier 与 runtime identity 均缺，V8/V12 consumer gate 继续 FAIL。R008 gate open、T1 false、零信用；未读 production bundle/solver frame或运行 GenCase/native/solver/worker/GPU/queue；F3/F4 one-shot 授权未变。详见 [UPDATE-75](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-75.zh-CN.md)。
- 2026-09-25 UPDATE-76：补充 Core release-candidate consumer 负测，使用一个除 schema 外完整有效的 in-memory ready admission fixture，只替换为 exact F8 synthetic Diagnostic schema；validator 唯一错误为 schema，`build_candidate()` 仍 blocked、`formal_release=false`、零 job，mocked campaign completion 有效。测试 5 passed；Terra High/high 静态复核认为 schema 拒绝路径通过，无独立身份/effort attestation。该测试 monkeypatch producer、未覆盖 `generate()` materialization；正确 production schema 的伪造 Mapping 仍未被识别，raw-byte/root-bound source verifier 与 runtime identity 缺失，V8/V12 consumer gate 继续 FAIL。R008 gate open、T1 false、零信用，无 production bundle/solver frame 或 GenCase/native/solver/worker/GPU/queue 操作。详见 [UPDATE-76](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-76.zh-CN.md)。
- 2026-09-25 UPDATE-77：完成 V8 清单中 F8 B/C/D per-case consumer 的 synthetic Diagnostic 拒绝节点：精确 V8 Diagnostic 分别注入临时 B/C/D receipt，经 `verify_stage_bundle()` 在 stage schema gate 拒绝。定向节点 3 passed，per-case verifier 合成测试文件 48 passed；指定 Terra High/high 静态复核确认拒绝顺序，无独立身份/effort attestation。该测试不认证 producer/source，不防伪造的正确 B/C/D schema，也不闭合 C `solver_execution` 语义或 V4 trusted producer/build-runtime 身份；V8/V12 consumer gate 仍 FAIL，R008 gate open、T1 false、零信用。仅临时 synthetic B/C/D、BI4/HDF5；未读 production bundle/solver frame、未运行 GenCase/native/solver/worker/GPU/queue。详见 [UPDATE-77](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-77.zh-CN.md)。
- 2026-09-25 UPDATE-78：新增 V8 T1 metric matrix consumer 的 synthetic/re-wrapped case-result negative test；由完整有效 per-case v2 fixture 仅替换 schema 构造 gate-shaped spoof，并用 parser sentinel 证明在 metric parsing 前拒绝。仓库 `.venv` 完整 adapter suite 23 passed；系统 pytest 的 NumPy/h5py ABI 不匹配由现存 `.venv` 绕开，未改依赖。指定 Terra High/high 静态复核通过、无独立身份/effort attestation。仅证明 schema 隔离，正确 schema 伪造与 source/runtime identity 仍未解决；native integrity/T1 分离，R008 gate open、T1 false、零信用。仅临时 synthetic matrix/audit/log，无 production bundle/frame 或受保护执行。详见 [UPDATE-78](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-78.zh-CN.md)。
- 2026-09-25 UPDATE-79：新增 native-fluid gate reducer 的 synthetic verification negative test，覆盖裸 V8 Diagnostic、table-verification 字段重包装和有效 verification 的 schema relabel；分别断言身份缺失、exact fields 与 schema 错误，并用 `_reduce_window` sentinel 阻止进入数值 reduction。仓库 `.venv` reducer suite 13 passed；指定 Terra High/high 静态复核确认拒绝先于 HDF5 打开/采样，无独立身份/effort attestation。测试仅在 tmp_path 创建 synthetic HDF5；不认证 producer/source，也不防伪造正确 verification schema。native integrity/T1 与 R008 gate 仍未闭合，T1 false、零信用；无 production bundle/frame 或受保护执行。详见 [UPDATE-79](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-79.zh-CN.md)。
- 2026-09-25 UPDATE-80：为 native-integrity registry 增加 exact V8 Diagnostic 与 gate-shaped rewrap 拒绝测试；二者在 row exact-field check 失败，GateReadProbe 证明在任何 case/gate value 访问和聚合前拒绝。固定分母 monkeypatch 避免读取冻结 receipts；registry suite 26 passed，py_compile/diff check 通过。指定 Terra High/high 复核通过，无独立身份/effort attestation。重要未完成：结构正确但未绑定的 `{case_id,gate_results}` 仍能生成 diagnostic aggregate；只有 `evidence_bindings_verified=false`、T1/readiness false、zero credit 保持保护，缺 source-bound per-case verifier/capability，故 V8 registry consumer gate 继续 FAIL。纯内存 fixture，无生产 receipt/bundle/frame 或受保护执行。详见 [UPDATE-80](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-80.zh-CN.md)。
- 2026-09-25 UPDATE-81：对 `core_formal_planner` 做静态调用路径盘点并由指定 Terra High/high 只读复核：入口仍接受任意 Mapping 与 legacy/nested dataset row；manifest inline T1/audit 和无 schema 验证的外部 evidence 可流入 family/T1/audit 判定；manifest/evidence schema 未作 exact discriminator，synthetic Diagnostic 本身不被显式拒绝；无 hold 时 planner 会生成 9 个 job spec 并置 `launch_allowed=true`，spec 仍绑定原 manifest 而非 V12 sanitized projection。该轮未运行 planner、pytest planner tests 或生成 job spec。仅加 schema 标签比较不足以安全开放；在 strict raw-byte/root-bound verifier 与可信 admission capability 缺失时，应维持 fail-closed。Terra review 为范围内技术意见，无独立身份/effort attestation。training planner V11/V12 consumer gate 仍 BLOCKED；无训练/solver/worker/GPU/queue/native/GenCase 操作。详见 [UPDATE-81](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-81.zh-CN.md)。
- 2026-09-25 UPDATE-82：关闭 Core formal admission auditor 中任意 schema 的 raw `cases/rows` 被直接提取为逐案 hard/structural audit markers 的旁路；无已注册的 case-audit-set schema/source-bound capability 时，通用 raw mapping 不再产出 `by_case`，版本化 adapter 与 manifest audit reference 仍走各自路径。纯内存合成 Diagnostic-rewrap 端到端负测断言 hard/structural bound count 为 0、T1 false、formal job count 为 0；连同 global T1 schema 回归共 2 passed，py_compile/diff check 通过。指定 Terra High/high 只读复核未发现本范围隔离回归，无独立身份/effort attestation。仍未认证正确 `core.qualification.v1` 的 producer/source；legacy adapter 与 manifest-reference audit 的独立 verifier/schema gap 未闭合。只用临时 manifest/evidence，未读 production receipt/frame，未运行 planner/训练/solver/worker/GPU/queue/native/GenCase。详见 [UPDATE-82](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-82.zh-CN.md)。
- 2026-09-25 UPDATE-83：将 `core_campaign.completion()` 的 `scope_studies` 与 registered `scopes` 两个 T1 consumer 调整为先检查精确 builtin `core.qualification.v1` discriminator，再访问 diagnostic/formal/root/identity/T1/matrix 字段。读探针参数化负测断言 synthetic V8 schema 路径只读取 `schema` 即拒绝。8 个纯合成定向回归通过，覆盖两入口、既有 negative qualification 与范围身份；py_compile/diff check 通过。指定 Terra High/high 静态复核范围内通过，无独立身份/effort attestation。schema 与 registry-provided hash 不认证 producer；未解决共同伪造 JSON+registry、duplicate-key/raw-byte/source/runtime identity。仅 tmp_path synthetic receipts，无生产 receipt、campaign 命令、训练或受保护执行。详见 [UPDATE-83](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-83.zh-CN.md)。
- 2026-09-25 UPDATE-84：为 `core_production.next_batch()` 增加 exact builtin `core.qualification.v1` 前置 discriminator，并以单次 schema 读取拒绝 synthetic Diagnostic 输入；positive/waiting/wrong-scope fixtures 同步正式 schema，新增读探针负测。定向测试 3 passed，py_compile 与 diff check 通过。Terra High/high 复核请求因 agent thread limit 未能启动，本轮无外部 reviewer 结论。正确 schema 仍可由任意 Mapping 伪造；raw-byte/duplicate-key、source-bound capability 与 producer/runtime identity 未解决，V9/V12 consumer gate 仍 BLOCKED。只用内存 synthetic fixture；未运行 runner、batch/job preparation、worker、solver、GPU、queue、native 或 GenCase。详见 [UPDATE-84](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-84.zh-CN.md)。
- 2026-09-25 UPDATE-85：F4 `verify_qualification_receipt()` 现先快照并验证 exact builtin `core.qualification.v1` schema，再读取 family/scope；synthetic 与 missing-schema 临时回执在错误 scope/matrix 处理前被拒绝。兼容性审计发现 tall-wall connector evaluator summary 缺少该顶层标签，故 `_receipt_summary()` 加上现有 qualification schema，合成 bound-audit 8→24 路径保持有效。合并定向回归 8 passed，py_compile/diff check 通过。Terra High/high 复核因 agent thread limit 未启动。本轮仅静态矩阵与临时合成回执/审计，无 one-shot 回执读取、proposal/prepare、GenCase、worker、solver、GPU 或 queue。schema 不认证 raw bytes/source/producer/runtime；T1 与 V9/V12 capability gate 仍未闭合。详见 [UPDATE-85](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-85.zh-CN.md)。
- 2026-09-25 UPDATE-86：F4 tall-wall connector `batch_decision()` 增加单次 exact builtin `core.qualification.v1` 前置门；synthetic/missing schema fail-closed，拒绝前不读取 binding/family/scope/T1 或遍历 audits。读探针覆盖 qualification 与 audits，partial-matrix fixture 保留原分支；有效 8→24、partial-matrix、tampered-registration 联合回归 8 passed，py_compile/diff check 通过。未获 Terra High/high 外部复核（agent thread limit），不记 reviewer PASS。只使用静态设计与临时合成审计，无 proposal/prepare、GenCase、worker、solver、GPU、queue。正确 schema/binding 仍可伪造；raw-byte/source/root/runtime identity、可信 capability 和正式 T1 gate 未闭合。详见 [UPDATE-86](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-86.zh-CN.md)。
- 2026-09-25 UPDATE-87：F4 tall-wall collector public ingress 对 qualification 外层对象增加 exact legacy-schema discriminator；inline Mapping 在 deepcopy 前拒绝 missing/unknown/synthetic schema，path JSON 在后续 binding/eligibility 读取前拒绝。public-entry 读探针与有效 synthetic diagnostic-reader 回归 2 passed，py_compile/diff check 通过。该 `core.f4.tallwall120.production_qualification_binding.v1` 明确仍是 legacy wrapper，不是 V12 admission schema；correct legacy 标签仍不认证 source、nested summary 或 runtime，V12 exact raw-reference envelope/root verifier 缺失，formal/T1 不得开放。仅固定静态 design/template 与 tmp_path 合成产品，无 production tick/one-shot receipt 或受保护执行。未获 Terra High/high 外部复核（agent thread limit），不记 PASS。详见 [UPDATE-87](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-87.zh-CN.md)。
- 2026-09-25 UPDATE-88：F4 dispatch coordinator 将 qualification JSON 的 T1 读取收敛到 `_qualification_t1_claim()`，先要求 object/exact builtin `core.qualification.v1`，再访问 `T1_numerical`；synthetic Diagnostic 读探针、有效 true/false、pending 与 negative no-submit 回归共 4 passed，py_compile/diff check 通过。未调用 succeeded-gate tick 或触发 runtime/queue/job submit。ordinary `json.loads`、duplicate-key/raw-byte/root/source/runtime 身份及 trusted dispatch capability 仍缺；未获 Terra High/high 复核（agent thread limit）。详见 [UPDATE-88](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-88.zh-CN.md)。
- 2026-09-25 UPDATE-89：F3 material T2 readiness 在 inherited qualification JSON 加载后、读取 T1/T2 summary 前增加 exact builtin `core.qualification.v1` discriminator；synthetic Diagnostic read-probe 证明仅访问 schema 即拒绝。1 项 helper 测试通过，py_compile/diff check 通过。未调用 `build_audit()`，未读取资格/evidence 文件或 row30 one-shot receipt，也无调度/worker/solver/GPU/queue/状态写入。普通 JSON/raw-byte/duplicate-key/source/runtime identity 与 trusted capability 仍缺；T2 readiness/授权不变。未获 Terra High/high 外部复核（agent thread limit）。详见 [UPDATE-89](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-89.zh-CN.md)。
- 2026-09-25 UPDATE-90：F3 row30 root-decision packet 在 candidate/status 或 T1/T2 marker 读取前分别验证 exact builtin readiness 与 `core.qualification.v1` schema；synthetic Diagnostic 对两个入口的读探针共 2 passed，py_compile/diff check 通过。未调用 `build_packet()`/`write_packet()`，未读 row30 readiness/qualification 固定文件或 one-shot 回执，亦无预检/调度/worker。schema 仍不认证 raw bytes/source/runtime；row30 执行授权状态未变。未获 Terra High/high 外部复核（agent thread limit）。详见 [UPDATE-90](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-90.zh-CN.md)。
- 2026-09-25 UPDATE-91：F3/F4 T2 admission contract 的两份 qualification loader 增加 `core.qualification.v1` 前置 discriminator；synthetic Diagnostic 对 F3/F4 的读探针共覆盖 2 家族，目标 node 1 passed，py_compile/diff check 通过。未调用 `build_contract()`/`verify()`，未读固定 qualification、材料历史审计或 HDF5；无 solver/worker/GPU/queue/registry/ledger 写入。ordinary JSON、duplicate-key、source/runtime capability 与 scope-bound producer 仍缺，T2 false、zero credit。未获 Terra High/high 外部复核（agent thread limit）。详见 [UPDATE-91](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-91.zh-CN.md)。
- 2026-09-25 UPDATE-92：只读复核 F4 material preflight `inspect_source()` 调用序：archive outputs、audit/result gates、completion scope T1 和无 schema 的 range-root T1/matrix 会在完整 trusted verifier 前被读取；后续会打开固定大型 HDF5。本轮不运行 inspect/test、不读取 receipt/HDF5、不改历史单次 generator。因 range-root exact schema/source producer 与 trusted raw-byte/root capability 均未定义，消费者维持 BLOCKED，不猜测 schema 接纳路径。无 pytest/代码变更；未获 Terra High/high 外部复核（agent thread limit）。详见 [UPDATE-92](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-92.zh-CN.md)。
- 2026-09-25 UPDATE-93：F4 tall-wall connector `validate_evaluation()` 经 `_receipt_summary()` 先用单次 exact builtin evaluation-schema discriminator，synthetic Diagnostic 在 scope/revision/T1/cells 派生及 manifest 路径访问前被拒绝。public-entry read-probe 与合成 8→24 connector 回归 2 passed，py_compile/diff check 通过。未读正式 evaluation/archive/HDF5/one-shot receipt，未运行 proposal/prepare/worker/solver/GPU/queue/GenCase。调用方 Mapping/正确 schema 伪造、raw-byte/root/source/runtime capability 与 trusted reevaluation producer 仍未解决；无 T1/T2 credit。未获 Terra High/high 外部复核（agent thread limit）。详见 [UPDATE-93](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-93.zh-CN.md)。
- 2026-09-25 UPDATE-94：F4 registry writer 的 `_validate_range_qualification()` 与 `_validate_collection()` 新增 monkeypatched synthetic read-probe 回归；两处均在 scope/family/T1/formal/evidence/case marker 读取前拒绝 Diagnostic schema。测试 2 passed，`py_compile`/diff check 通过。未调用 `register_f4()`、未写 registry/qualification/case records、未读生产 evidence/HDF5。这里只验证既有 schema-first 顺序；ordinary JSON 与 source/root/runtime capability 仍缺，public writer 的可信 admission 仍 BLOCKED。未获 Terra High/high 外部复核（agent thread limit）。详见 [UPDATE-94](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-94.zh-CN.md)。
- 2026-09-25 UPDATE-95：Core formal admission `_bound_adapter_cases()` 将 adapter schema 单次快照并要求 exact builtin registered schema，再读取 manifest hash/rows；synthetic Diagnostic 在 case binding 前被忽略。新 read-probe 1 passed，py_compile/diff check 通过。未运行全量 audit、未读真实 manifest/结构回执/resource profile/graph probe，亦无 planner/job spec/训练/worker/solver/GPU/queue。正确 registered-schema mapping、ordinary JSON 与 source/root/runtime capability 仍不可信，formal admission 仍 blocked。未获 Terra High/high 外部复核（agent thread limit）。详见 [UPDATE-95](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-95.zh-CN.md)。
- 2026-09-25 UPDATE-96：按用户最新要求配置 GPT 6 Luna Max 完成两项只读技术审查，均为 `REVISE`。F8 per-case verifier 的 B/C/D 实际语义没有被完整重算，空 `solver_execution` 等合成字段仍可能得到 `all_stages_passed=true`；V12/C-v4 还缺资格对象/摘要唯一绑定、同 FD/snapshot 验证与消费、planner 前 HDF5 内容绑定、query 事件与 solver process generation 生命周期因果绑定及完整 cache 状态机。未读生产 bundle/solver frame，未运行测试或任何执行链，T1 false/zero credit 不变。下一步先修订 V13/V5 静态合同并限定 per-case 旧接口为结构检查。详见 [UPDATE-96](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-96.zh-CN.md)。
- 2026-09-25 UPDATE-97：继续修订 F8 R008 的 V13/V5/per-case V2 **synthetic-only 设计草案**。GPT 6 Luna Max 首轮总体 `REVISE` 后，新增 raw/canonical digest golden vector 与 fs-verity 同 FD contract、V5 poll begin/end/正常循环终止及异常/中断 cache invalidation、exact 15-row/append-only trusted ledger schema、B/C/D attempt/root/nonce/ref/seq 交叉闭合和未来 15/15 T1 正向谓词。focused follow-up 确认 V5 无 `poll_end` 缓存规则及 V2 最后补入的 stage/process identity、root-generation equality 与严格 seq 次序在文本层面闭合；这不是实现/资格结论。旧 `core_dataset` Mapping/path reader 与 F4 connector ingress 尚未关闭；trusted root/supervisor、event source、key activation、runtime closure、parser/producer 与 F8 worker/T1 均未实现。未运行测试、planner/collector/preparation、GenCase/native/solver/worker/GPU/queue，未读 R008 production bundle/frame/one-shot；仅 `git diff --check` 和一次内存 SHA-256 vector 计算。`readiness_pass=false`、`T1_numerical=false`、零信用不变。详见 [UPDATE-97](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-97.zh-CN.md) 及三份 F8 synthetic-only 草案。
- 2026-09-25 UPDATE-98：关闭旧 `CoreDataset` Mapping/path reader 仅凭 `formal_release=true` 晋升正式资格的旁路；strict integrity 仍保留，但 V13 verified-reader capability 缺席时，learning 训练验证与评测入口 fail closed/diagnostic-only。Core contract/learning 71 passed，campaign/package 55 passed；使用仓库 `.venv`（系统 Python 的 h5py/NumPy ABI 不兼容），未改依赖。只运行本地合成回归，无 production bundle/frame/one-shot 读取，无 planner/collector/preparation/GenCase/native/solver/worker/GPU/queue。仍未实现 trusted-reader capability；legacy reader 的 pathname/snapshot 缺口、`core_formal_planner` 任意 Mapping/path ingress 和 F4 connector ingress 分别待推进，不计 T1/T2/生产信用。详见 [UPDATE-98](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-98.zh-CN.md)。
- 2026-09-25 UPDATE-99：`core_formal_planner.inspect_inputs()` 缺少 source-bound trusted admission capability 时将所有 Mapping/JSON 输入锁为 `metadata_only_untrusted`：`formal_eligible=false`、`family_t1=null`；`build_plan()` 保留 9-run 分母但始终 0 job/0 spec/`launch_allowed=false`。complete inline metadata 与普通 JSON path 的正向伪造 fixture 均验证 hold；源码快照正确也不能越过 capability 门。planner/admission readiness 定向测试 24 passed，py_compile/diff check 通过。测试只读 F3 manifest/evidence/resource/environment 与 admission/source-closure fixture，并仅在临时目录写 hold report/synthetic snapshot；无 HDF5、训练、spec/ledger/campaign 写入或 solver/worker/GPU/queue。formal planner 暂不能发正式 specs，须先实现并独立验证 raw-byte/duplicate-key、trusted-root/runtime 闭合的 verifier/capability；F4 ingress、V13 snapshot reader、F8 T1 与 Core T1/T2 仍待完成，零资格信用。详见 [UPDATE-99](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-99.zh-CN.md)。
- 2026-09-25 UPDATE-100：F4 connector 旧 Mapping ingress 在 V3 trusted qualification bundle capability 未实现时统一 fail closed：`batch_decision()` 不读取 gate/audit 字段且不报 ready；`prepare_production_batch()` / `production_job_spec()` 在 root tick、executor import、path 读取或输出创建前拒绝。proposal 将输入中的 T1/hash 结果仅保留为 `observed_*`，正式 qualification 字段保持 false。F4 connector focused suite 21 passed，py_compile/diff check 通过。proposal 测试用 synthetic tick/evaluation stub，未重跑 root tick；仅读冻结 F4 JSON/config metadata 和临时 synthetic audit，未读/改 HDF5/archive。无 CPU canary、GenCase/native/solver/worker/GPU/queue、batch/job/ledger/registry 写入。V3 root reader/bundle/broker/runtime capability 与独立审查仍缺，F4 正式 admission 零信用；一次性 canary 边界不变。详见 [UPDATE-100](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-100.zh-CN.md)。
- 2026-09-25 UPDATE-101：新增纯内存、non-authorizing V3 serialization codec：strict UTF-8/JSON、嵌套 duplicate-key/非有限数拒绝、V12 canonical byte 规则、raw/canonical 双摘要、固定 role order/domain-separated U64/U16 digest 与 exact positive builtin-int（拒 bool）。golden vector、canonical digest 与 duplicate/nonfinite/type/role/int 边界共 13 passed，py_compile/diff check 通过。未读/写固定生产文件、HDF5 或 F3/F4 one-shot；未运行 planner/tick/canary/preparation/GenCase/native/solver/worker/GPU/queue。此 codec 不验证 ref/schema 交叉关系、FD/fs-verity、producer/root/runtime 身份，不 mint capability、不开放 batch，零资格信用。V13 trusted reader/supervisor/broker/worker 与独立审查仍待完成。详见 [UPDATE-101](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-101.zh-CN.md)。
- 2026-09-25 UPDATE-102：在 V3 codec 中补充纯内存、non-authorizing V12/V13 reference-graph consistency 检查：exact schema/ref、raw/canonical digest、binding/evaluation/source 交叉绑定、索引 partition、T1 与 promotion-status 派生；合成 raw-hash 回归使用等长但 raw bytes 不同的 JSON，明确命中 raw SHA 检查。focused suite 18 passed，py_compile/diff check 通过；Terra High 只读审查未发现 ref-consistency 接受绕过，并指出且帮助定位原测试的长度校验假阳性。未读取生产 campaign/HDF5/one-shot，未运行 planner/tick/canary/preparation/GenCase/native/solver/worker/GPU/queue。检查结果仍明确是 untrusted metadata consistency：不验证 evaluation-source 语义、固定 object allowlist、descriptor root、producer/runtime 身份或 fs-verity，不 mint capability、不授权 batch、不贡献资格信用；trusted root reader/supervisor/broker/same-FD worker 与独立实现审查仍待完成。详见 [UPDATE-102](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-102.zh-CN.md)。
- 2026-09-25 UPDATE-103：在 V3 untrusted inspector 中按 evaluator v2 源码的三个返回分支加入 evaluation-source **exact top-level variant** 与高层类型检查（base、含 cells/missing/failures、再含 comparisons/checks），并拒绝未知顶层字段、错分母/索引及 bool-as-int。Terra High 只读审查抓到 `promotion_status` 为 JSON list/object 会先触发 set-membership `TypeError`；已改为先验 exact string 并覆盖两类负测。focused suite 23 passed，py_compile/diff check 通过。nested source records 仍只验证容器类型，raw evaluator 自述不用于 qualification/capability；`evaluation_source_semantics_verified=false` 保持不变。只查 evaluator 源码与内存合成值，未读生产 campaign/HDF5/one-shot，未运行 planner/tick/canary/preparation/GenCase/native/solver/worker/GPU/queue。trusted producer/root/snapshot/same-FD worker 等仍缺。详见 [UPDATE-103](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-103.zh-CN.md)。
- 2026-09-25 UPDATE-104：新增 synthetic-only C-execution V5 单 journal structural parser：strict UTF-8/JSON、V5 exact top-level 与 process/query event union、基本字段/IEEE-754 finite-hex 域、journal 内 nonce copy、连续 seq、coverage/非递减单调时钟及 poll begin/end 局部关联；未终结 poll 保留为 incomplete diagnostic，exception poll 不标 returned。review 发现 exit code 缺范围限制后，合同冻结为 exact builtin int `0..255` 并补 `-1/256/bool` 负测。21 项合成测试通过，py_compile/diff check 通过；Terra High 修复 follow-up 待回。parser 即使成功仍固定 `gate_state=open`、event-source/runtime/process/query/cache semantics 与 execution/T1 false、zero credit；尚未与 evidence/attempt 外层 nonce 交叉绑定，不接 producer/consumer。只读设计/源码，纯内存/合成测试；未读 production bundle/solver frame/one-shot，未运行 solver/native/GenCase/worker/GPU/queue/canary/planner/preparation。详见 [UPDATE-104](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-104.zh-CN.md)。
- 2026-09-25 UPDATE-105：在 V5 parser 中增加 journal-local process/thread generation 状态机：唯一 root spawn→exec、fork/clone parent 必须 running、query 类事件只在 running generation、thread 创建/退出归属、process exit 前无活跃线程、exit→reap 顺序，以及 PID/TID 仅在先前 generation/thread 终止后复用。截断但结构合法的 journal 返回 lifecycle incomplete 诊断，而非通过；所有资格/trust flags 仍固定 false/open。Terra High/high 只读代码审查未发现本范围可复现绕过/误拒，reviewer 当时测试 26 passed；随后增加 reap 后 PID reuse 正例后当前 suite 27 passed，py_compile/diff check 通过。状态机仅重算 caller bytes 的自洽性，不认证 supervisor/event-source、完整覆盖、loaded runtime、source callgraph/query/cache 语义；未与 producer/consumer 集成，不产生 solver 权限、F8 T1 或资格信用。只用内存合成 journal，未读生产 bundle/solver frame/one-shot，未运行 solver/native/GenCase/worker/GPU/queue/canary/planner/preparation。详见 [UPDATE-105](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-105.zh-CN.md)。
- 2026-09-25 UPDATE-106：依据 `JDsAccInputMk::Reset/GetAccValues()` 补 V5 journal-local poll→guard/exec-epoch 因果、单槽 cache 数值 replay、当前 miss seq、异常/缺失 end、active binding 局部相等；拒绝 poll 跨 exec 收尾、exec epoch 旧 cache、可见同槽重叠调用。修正缺失 end 的 hit 语义：C++ early return 不污染先前 cache 值，但 attempt 保持 incomplete；同槽后续调用标 unresolved call order。fork/clone child 在 exec 前 cache 因内存继承可能性明确 unresolved。Terra High/high 配置只读复核促成多项修正；无独立身份/effort attestation，不计审计 PASS。focused suite 43 passed，py_compile/diff check 通过。source-callgraph 完整重算、active/table raw provenance、producer/event-source/runtime identity、外层 nonce 与 consumer 集成仍未完成；所有信任/资格标志 false/open/零信用。只读源码与 synthetic-only 草案/内存 journal，未读 production bundle/HDF5/one-shot，未运行 solver/worker/GPU/queue/canary/planner/preparation/native/GenCase。详见 [UPDATE-106](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-106.zh-CN.md) 与 [V5 草案](lagrangian-fluid-lab/reports/F8-R008-C-SOLVER-EXECUTION-EVIDENCE-CONTRACT-V5-SYNTHETIC-ONLY-DRAFT-2026-09-25.zh-CN.md)。
- 2026-09-25 UPDATE-107：继续补 V5 journal-local guard/terminal 顺序诊断：按 binary64 strict `<` 重算 condition；限制每个 process/exec-epoch/driver 的唯一 iteration ID、false terminal guard 后不再有 guard；poll 只能引用当前最新 guard，不能跨 iteration/termination 复用。下一同 driver poll/guard 前必须已有 poll_end；end 越界拒绝，缺失 end 令 `driver_unclosed_poll_count>0`、`observed_driver_loops_complete=false`、`unresolved_call_order`。VRes 单 guard 多实例/多 interstep 正例及 terminal/stale/incomplete 负例加入。Terra High/high 配置只读复核发现并促成 terminal guard 顺序修正，follow-up 复核通过；无独立 model/effort attestation，不计审计 PASS。focused suite 49 passed，py_compile/diff check 通过。所观测到的 loop closure 不认证 callgraph 预期 driver/host-call 完整性、时间步转移、active/table provenance、event source 或 runtime；source-callgraph extractor 和全部资格/trust 边界仍未闭合，T1 false、zero credit、gate open。只读 CPU/GPU/VRes source 与 synthetic 草案/内存 journal；未读生产 bundle/HDF5/one-shot，未运行 solver/worker/GPU/queue/canary/planner/preparation/native/GenCase。详见 [UPDATE-107](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-107.zh-CN.md) 与 [V5 草案](lagrangian-fluid-lab/reports/F8-R008-C-SOLVER-EXECUTION-EVIDENCE-CONTRACT-V5-SYNTHETIC-ONLY-DRAFT-2026-09-25.zh-CN.md)。
- 2026-09-25 UPDATE-108：新增 V5 source-callgraph caller-JSON 结构检查及 observed true guard 的声明式 host-call×entry schedule replay；校验 fragment/function-file allowlist、hash/range/edge ordinal、single standard/VRes driver-instance partition、input count、intersteps，并可核对 outer ref raw bytes/SHA。Terra High/high 只读复审发现 missing-end/exception/missing-terminal guard 汇总仍可能为 true及 V5 schema 复用 V4 object ID；已修复并加负测，V5 ref 改用独立 `f8-r008-source-callgraph-v5`，partial fragment 状态明确为声明形状而非完整 coverage。schedule 测试覆盖 main CPU poll、VRes 单 guard 多实例 predictor/corrector、缺 poll/terminal、错 callsite、错序、driver mismatch 与坏 fragment/ref；最终 V5 focused suite 59 passed，py_compile/diff check 通过。review 修复之前启动的完整 suite 2934 passed、32 failed、1 skipped（非最终版本全套验收）；该次失败不含 V5 parser 测试，涉及其他 receipt/hash-closure/legacy-schema snapshots（源码固定摘要会随本次编辑改变），未重写跨范围证据。复审无独立 model/effort attestation，不计审计 PASS。实现不重解析源码/AST/运行配置，不证明 feature fragment 完整、event source 无漏报、预期 guard/horizon、outer evidence nonce、build/runtime 信任、active/table provenance；所有可信/资格标志 false/open/零信用。仅使用合成 journal/callgraph 字节；未读 production bundle/HDF5/one-shot，未运行 solver/worker/GPU/queue/canary/planner/preparation/native/GenCase。详见 [UPDATE-108](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-108.zh-CN.md) 与 [V5 草案](lagrangian-fluid-lab/reports/F8-R008-C-SOLVER-EXECUTION-EVIDENCE-CONTRACT-V5-SYNTHETIC-ONLY-DRAFT-2026-09-25.zh-CN.md)。
- 2026-09-25 UPDATE-109：新增 source-callgraph declared raw fragment SHA 与本地 Git HEAD blob 的逐字节复核：固定 object-ID/path allowlist、tracked regular blob、Git source path 无 dirty delta、dirfd/O_NOFOLLOW 读取工作树并要求与 HEAD 一致、范围检查与 slice SHA 重算。合成临时 Git repo 测正确 hash、错误 hash、工作树偏离。V5 focused suite 60 passed，py_compile 通过；GPT‑6 Luna Max 只读安全审查与最终 diff check 待完成。输出明确不验证 function-definition range、AST/call edges、feature closure、source tree↔build attestation 或 loaded binary；源码/调用图/运行时仍 untrusted，T1 false、zero credit、gate open。环境仅有 GCC 11/cpp，无 Clang/Tree-Sitter/GCC plugin headers，本轮未声称完整 C++ AST extractor。只用合成 Git repo与源 bytes；未读 production bundle/HDF5/one-shot，未运行 solver/worker/GPU/queue/canary/planner/preparation/native/GenCase。详见 [UPDATE-109](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-109.zh-CN.md) 与 [V5 草案](lagrangian-fluid-lab/reports/F8-R008-C-SOLVER-EXECUTION-EVIDENCE-CONTRACT-V5-SYNTHETIC-ONLY-DRAFT-2026-09-25.zh-CN.md)。
- 2026-09-25 UPDATE-110：依据 GPT‑6 Luna Max 安全复审，替换 UPDATE-109 的 clean-worktree/status 断言为 pinned Git HEAD snapshot 对照：清理继承的 `GIT_*` 环境、固定 commit 与 blob OID 并复算 Git object ID、检查开始/结束 HEAD 相同；Git 子进程 cwd 与 no-follow worktree 读取绑定同一已打开仓库目录 FD，并检查根路径 inode 未替换。不运行 `git status`，工作树逐字节比较且 index 可独立变更。设置每文件 1 MiB、聚合 2 MiB 上限，单 blob 有界处理；增加环境重定向/fsmonitor/HEAD 移动/根路径替换/单文件与聚合上限/symlink/暂存 index 测试。V5 focused suite 65 passed，py_compile/diff check 通过。该层仍只验证 caller slice raw bytes，不验证函数范围/AST/callgraph/build/runtime，gate open、zero credit。详见 [UPDATE-110](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-110.zh-CN.md)。
- 2026-09-25 UPDATE-111：补强 UPDATE-110 复审 follow-up：Git 每条命令禁用 replacement refs，并设置 `GIT_NO_REPLACE_OBJECTS=1`、`GIT_NO_LAZY_FETCH=1`，防止同一 commit ID 被 `refs/replace` 改写或 missing promisor object 触发网络取回；把 root-path replacement 测试推迟到 `ls-tree` 后，覆盖后续 Git 与 worktree 读取仍绑定原 FD 并最终拒绝改向。V5 focused suite 66 passed，py_compile/diff check 通过；只用合成仓库，未做网络/partial-clone fetch，未运行 solver 等任务。相关边界与限制见 [UPDATE-111](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-111.zh-CN.md)。
- 2026-09-25 UPDATE-112：formal planner 的 path-backed manifest、evidence、referenced audit、source-snapshot JSON 改为 bounded raw-byte strict parser：上限 64 MiB，strict UTF-8、duplicate-key/NaN/Infinity/float overflow/超 128 位整数拒绝，要求 object 顶层；audit 引用摘要基于同一 bounded-read bytes。内存 Mapping 仍仅 diagnostic，硬 hold 与 0-job 行为不变。planner + admission-readiness tests 31 passed；无 specs/HDF5/训练或 scheduler。只关闭 strict serialization 子项，不产生 trusted capability；详见 [UPDATE-112](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-112.zh-CN.md)。
- 2026-09-25 UPDATE-113：复核修复 bounded JSON reader 的 FIFO 阻塞、symlink 跟随及 parse-bytes 与二次 path-hash 竞态：使用 nonblocking/no-follow regular-file FD，所有 path-backed 引用摘要绑定同一 bounded raw bytes。另在 `train_model()` 最前置拒绝 legacy reader 上 `formal_release=true` 的训练请求，保证拒绝早于帧读取/normalization/model 初始化；非 formal 诊断训练不变。planner + admission-readiness 34 passed，learning 47 passed，py_compile/diff check 通过；无 production HDF5、formal specs 或训练任务。仍无 trusted root/supervisor/snapshot/broker/fs-verity/runtime closure，capability 不存在，T1/T2 零信用；详见 [UPDATE-113](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-113.zh-CN.md)。
- 2026-09-25 UPDATE-114：将 bounded strict JSON/no-follow regular-file reader 提取为共享 `core_strict_json.py`，接入 `CoreDataset`、CFD adapter manifest/prepared-record 及 learning CLI manifest path；CFD source-manifest SHA 与解析的同一 raw bytes 绑定。helper 纳入当前 planner/admission/capacity formal source closure；既有 v5/v6 八文件收据保留原状并按缺少 helper 判为 stale/fail-closed，旧 diagnostic preprofile snapshot 仍按其冻结清单验证。admission auditor/capacity evidence 直接复用 planner required-file tuple 防漂移。合成覆盖重复键、非法 UTF-8、非有限数/float overflow、>128 位整数、64 MiB 上限、symlink、prepared JSON 与路径替换。跨 reader/planner suite 144 passed，扩展 closure/admission/capacity/preprofile + 历史 closure suite 76 passed；direct planner/auditor/capacity CLI、py_compile、diff check 通过。HDF5 仅临时合成测试，无生产数据/solver/GenCase/worker/GPU/queue。仍无 trusted capability；V13/HDF5 snapshot/runtime closure、F8 T1、Core T1/T2 未完成、零资格信用；详见 [UPDATE-114](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-114.zh-CN.md)。
- 2026-09-25 UPDATE-115：将共享 bounded strict JSON/no-follow reader 扩展到全部 `core_formal_*` path-backed JSON 入口：admission/capacity/readiness、release candidate、launch contract、CPU dry-run 与 graph probe candidate，以及 v5/v6 source-closure admission verifier。解析摘要均绑定单次 bounded raw bytes；graph probe 对 reader manifest 先作严格解析与 raw-hash 绑定，再把同一解析对象交给 `CoreDataset`，不重开 manifest 路径。readiness source bindings 纳入 shared parser；历史收据未重写、formal gate 仍 fail-closed/0-job。相关合成与历史 closure suite 70 passed，九个 formal CLI `--help`、py_compile、无路径 `json.loads/read_text` 残留检查及 `git diff --check` 通过。未运行 CPU 32k dry-run、graph probe 工作负载、solver/GenCase/worker/GPU/queue，未打开生产 HDF5；资格信用仍为零，V13 trusted reader/runtime closure、F8 T1、Core T1/T2 未完成。详见 [UPDATE-115](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-115.zh-CN.md)。
- 2026-09-25 UPDATE-116：为 V13 trusted snapshot 路线做只读主机能力盘点。Linux 6.8.0-138-generic、`CONFIG_FS_VERITY=y`、workspace mount 为 ext4 rw；rootless bubblewrap 0.6.1 成功运行 user/PID namespace + 整根只读 bind 的 `/bin/true` smoke probe。`fsverity` CLI 不在 PATH；普通用户无法读取 `/dev/sdc1` superblock，因此未能确认此 ext4 superblock 是否已启用 verity feature。未调用 sudo、未创建/启用 verity file、未改系统状态。Linux kernel fs-verity 文档指出单文件 enable ioctl 校验的是 inode write access（但必须经 O_RDONLY FD 且无并存 writable FD）；fs-verity 自身只提供完整性，trusted digest/authentication 另需锚定。V13 可继续设计 rootless snapshot/supervisor 原型，但 verity backend 在确认 superblock feature 前必须保持 fail-closed。详见 [UPDATE-116](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-116.zh-CN.md)。
- 2026-09-25 UPDATE-117：将 V13 descriptor-transport 前置条件固化为 Linux synthetic 回归测试：Unix `SCM_RIGHTS` 接收 FD 与发送端为同一 dev/inode 和 open-file-description（共享 seek offset），接收端保持 O_RDONLY/CLOEXEC；替换原 pathname 后仍从既有 FD 读到原数据，link count 保持 1。`tests/test_core_fd_snapshot_transport.py` 1 passed，`py_compile` / `git diff --check` 通过。另对 `/dev/sdc1` 执行的非交互只读 `sudo -n tune2fs -l` 因需密码退出，未做提权操作、未改变状态；ext4 superblock verity feature 仍未确认。该测试仅验证内核 FD 传输语义，不验证 peer 身份、supervisor/registry 生命周期、fs-verity、HDF5 同 FD reader 或 trusted capability；T1/T2/资格状态不变。详见 [UPDATE-117](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-117.zh-CN.md)。
- 2026-09-25 UPDATE-118：在 UPDATE-117 的 synthetic FD 测试基础上，增加 rootless bubblewrap user/PID namespace worker→host Unix socket peer 身份探测。`SO_PEERCRED` 给出 worker 对应的宿主 PID 与映射 UID；宿主 `/proc/<pid>/status` 的 `NSpid` 可见，`pidfd_open(peer_pid)` 成功并返回 CLOEXEC pidfd。针对性 suite 2 passed。该结果支持 host broker 固定进程实例，但 UID 仍映射为当前宿主 UID；peer credentials/pidfd 不认证 executable、loaded module 或 runtime，也不隔离同 UID 恶意进程。supervisor 必须继续依赖经固定 launcher/runtime 闭合的身份根；不能据 rootless probe mint capability。未访问生产数据或执行 solver/worker/GPU/queue。详见 [UPDATE-118](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-118.zh-CN.md)。
- 2026-09-25 UPDATE-119：为 `CoreDataset` 增加显式 all-case `snapshot_fds` diagnostic reader：检查只读 regular FD、unlinked/single-link inode 与 manifest 字节数；通过 held FD 的 `pread()` 绑定 SHA-256，再用 `h5py` file-object 驱动读取同一 open-file description 的 duplicate；descriptor-only 模式绝不 pathname fallback。合成 HDF5 原 pathname unlink 并放置替代文件后，reader 仍验证并读回原 snapshot；只读/覆盖/strict 负测通过。reader 始终 `formal_eligible=false`；无 producer/root、immutability/fs-verity、broker registry/peer nonce、launcher/runtime identity 或 capability，无法防并存 writer，不能用于 qualification/formal ingress。synthetic reader/compact tests 37 passed、1 deselected，FD transport suite 2 passed，py_compile/diff check 通过。初次 broad run 在 registered F3 metadata import 时中断，尚未到 CoreDataset/HDF5 read；所有 HDF5 内容测试仅使用 `tmp_path` 合成文件。未启动受保护 workload 或外部 review。详见 [UPDATE-119](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-119.zh-CN.md)。
- 2026-09-25 UPDATE-120：新增 Linux fs-verity `FS_IOC_ENABLE_VERITY` / `FS_IOC_MEASURE_VERITY` FD 原语：只读/CLOEXEC/single-link regular FD、bounded mount-ID 读取、完整 algorithm+digest 编码、identity/measurement 复验；ioctl ABI 限定为经实测的 Linux x86_64，其他架构与 filesystem/kernel 不支持时 fail closed。仅对两个临时 synthetic 文件分别在 `/home` ext4 `/dev/sdc1` 与 `/tmp` 所在 root ext4 `/dev/nvme0n1p2` 发起 enable ioctl，均返回 `EOPNOTSUPP`；`/sys/fs/ext4/features/verity=supported` 只证明 driver 能力，不能证明两 superblock 开启 feature，未读取/修改 superblock，未调用 sudo。fs-verity suite 5 passed，reader/compact/FD transport suite 39 passed、1 deselected，py_compile/diff check 通过；本机没有成功启用 positive filesystem 路径。V13 要求不降级；需管理员维护专用 verity filesystem 或提供已启用且受支持的本地挂载，trusted producer/snapshot registry/broker-worker/runtime/capability 链仍未完成，F8 readiness/T1 false、零信用。未运行受保护 workload，无独立 GPT 6 Luna Max review。详见 [UPDATE-120](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-120.zh-CN.md)。
- 2026-09-25 UPDATE-121：把 `snapshot_measurements` exact all-case map 接入 descriptor-only `CoreDataset`：measurements 要求只读/CLOEXEC/single-link FD，在 constructor pin identity，raw SHA 哈希前后、HDF5 轴解析后及每次 `times()`/`read_state()` 后都用同一 FD 重测 fs-verity 并比较身份；HDF5 file-object 使用 `F_DUPFD_CLOEXEC` duplicate，错误时绝不 pathname fallback。reader 仍为 diagnostic、`formal_eligible=false`。本机未启用 FS 无法完成 kernel positive；实际 unsupported test 证明 fail closed，另一个明确 stubbed test 只证明接线顺序/HDF5 同 FD，不计 fs-verity 证明。synthetic contract/compact/FD-transport/fsverity suite 46 passed、1 deselected；learning 47 passed；py_compile/diff check 通过。GPT 6 Luna Max 独立审查、trusted producer/supervisor/registry/broker/runtime capability 与正式 consumer、F8 T1/Core T1/T2 均未完成，零信用，无受保护任务。详见 [UPDATE-121](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-121.zh-CN.md)。
- 2026-09-25 UPDATE-122：新增 F8 R008 attempt-result V2 非授权 exact-shape/type guard。只接受 `attempt_outcome=unresolved`、全部六项语义布尔 false、`qualification_adjudicated=false`、`T1_numerical=false`、零 credit，并校验 exact fields、ID/digest/nonce、descriptor-ref 形状、strict seq、receipt status enum 与连续 frame/time 编码；返回 `None`，不 mint capability。17 项合成 V2 测试、V5 journal suite 66 项、旧 v1 完整合成 B/C/D chain 1 项通过，py_compile/diff check 通过。v1 chain fixture 的 `gencase_execution`、`safe_decode_receipt`、`solver_execution` 为空仍可结构通过，明确只闭合 receipt/reference 树且 readiness false、零 credit。ledger parser/trust/attestation、event/ref 双向闭合、V5 execution semantics、15-case aggregate/retry/T1 均未实现；该 guard 不认证任何输入引用或来源。全程 synthetic-only，未读 production bundle/HDF5/frame/one-shot、未运行 GenCase/native/solver/worker/GPU/queue、未提权。详见 [UPDATE-122](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-122.zh-CN.md)。
- 2026-09-25 UPDATE-123：新增 F8 R008 raw attempt ledger V1 的非授权结构 inspector 与 V2 attempt projection 检查：严格 bounded JSON/schema/event union、连续 seq/非递减 monotonic clock/coverage、unique attempt ID+nonce+row binding、registration/stage/process terminal 顺序、B→C→D transitions、完整 attempt event seq 与 stage receipt refs 精确对账；open process history 不删除，terminal 的 caller outcome 仅作为 claim 保留且 derived outcome 固定 unresolved。结构通过不等于 ledger completeness：无 descriptor-root/registry/supervisor attestation/key activation，`attempt_ledger_complete=false`、T1 false、零 credit 固定；空 ledger 不得推导 missing。ledger+V2 suites 43 passed、V5 suite 66 passed、v1 synthetic B/C/D chain 1 passed，py_compile/diff check 通过。全程合成 JSON，无生产证据或受保护 workload。scope aggregate、可信 ledger completeness、stage/raw/frame 内容验证、retry/资格门仍待实现。详见 [UPDATE-123](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-123.zh-CN.md)。
- 2026-09-25 UPDATE-124：修补 V2 remediation 草案中未定义的 `qualification_row_sha256`，固定为 scope receipt `matrix.rows[i]` 完整 row object 的 V12 canonical JSON bytes SHA-256（默认 ASCII escaping、key 排序、紧凑分隔符、无尾 LF）；matrix receipt raw SHA 独立绑定。新增 exact 15-row frozen-matrix structural inspector，ledger raw SHA 必须等于 matrix 声明，所有 attempt case/row digest 与矩阵 row 逐行匹配；attempt projection 必须传入同一 matrix raw bytes。输出明确 `frozen_matrix_source_authenticated=false`，无 trusted source capability。ledger+V2 suites 50 passed、V5 66 passed、v1 合成 chain 1 passed，合计 117 passed；py_compile/diff check 通过。另经 bounded strict reader 对实际静态 scope receipt 做兼容性探测，15 行及既有 raw hash 一致；未读生产 bundle/frame 或运行受保护 workload。该算法补充与实现尚无 Terra/GPT 6 Luna Max 独立审查；attestation/root trust、官方 15-row aggregate、outcome/retry/T1 仍待完成。详见 [UPDATE-124](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-124.zh-CN.md)。
- 2026-09-25 UPDATE-125：新增 F8 R008 aggregate V2 的 non-authorizing 投影：固定 15-row matrix 顺序与分母，ledger ref raw bytes/SHA 对账，要求所有 observed registration 都有 unresolved V2 result 一一对应，并按 registration seq 保留 retry history；attestation 缺失时为 null，当前拒绝非 null attestation。来源与 ledger completeness 未认证，故所有 rows（包括空行）和 attempts 均 unresolved、绝不推 missing，aggregate accounting_unresolved、T1/资格 false、credit 0。remediation draft 已明确 descriptor/attestation 边界及此 helper 的诊断性质。ledger+V2 61 passed；加 V5 与旧 v1 synthetic chain 集成回归共 128 passed；py_compile/diff check 通过。全程 synthetic-only，未运行受保护 workload；尚无 Terra High 独立审查，也没有可信 source/attestation/outcome/T1 path。详见 [UPDATE-125](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-125.zh-CN.md)。
- 2026-09-25 UPDATE-126：新增 aggregate V2 non-authorizing validator，从 case rows 重建所有 attempt results 并重新调用受限投影，按 canonical JSON bytes 与候选 aggregate 比较；覆盖精确 fields、15-row 顺序/身份、registration inventory、retry 归属/count、ref SHA、attestation 缺失以及全部 false/zero gate。canonical bytes 比较可拒绝 `False` 冒充 integer zero。validator 仅证明 caller-supplied inputs 的结构自洽，不认证 matrix/ledger 来源、不 mint capability。ledger+V2 70 passed；加 V5 与旧 v1 synthetic chain 集成回归共 137 passed；py_compile 通过。未读生产证据、未运行受保护 workload；无 Terra High 独立审查，trusted ledger/outcome/T1 path 仍未完成。详见 [UPDATE-126](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-126.zh-CN.md)。
- F8 未能取得 T1 时，按计划转向 F1，再以 F2 为替补；不得将 F8 的 canary、预检或静态通过记为资格信用。

#### F1／F2：主线与替补同时准备

仅当优先 F8 路线无法取得资格时，F1/F2 才承担第三家族后备路线。F1优先完成运行域问题，并检查真正的实体边界和原生排除。切换边界方案时必须验证法向、ghost 和完整配置，不能仅改变 CFL 就声称完成边界修复。

F2依次验证：

1. 静止容器保持；
2. 有限厚度杯壁、杯口与真实规定运动；
3. 接液、保留、溢出任务；
4. 数值参考 manifest 接入。

外部物理验证与数值 T1 分开登记，避免因为暂缺外部实验数据而永久禁止数值候选研究。

#### 新一维范围的统一资格矩阵

将主参数规范化为 \(q∈[0,1]\)：

| 用途 | 参数点 | 分辨率 |
|---|---|---|
| 空间研究锚点 | 0、1/2、1 | 三档 |
| 独立内部核验 | 1/4、3/4 | 生产档、细档 |
| 时间推进对照 | 1/2 | 生产档，收紧内部时间推进 |
| 输出 cadence 对照 | 1/2 | 生产档，加密原生输出 |

即每个全新范围最低 **13个空间研究格＋2个时间／输出对照**。输入、二进制和原始产物完全一致的旧格可以复用。

内部核验点一旦参与配方或阈值调整，就转为开发证据，并从预登记候补点补充独立核验。

这些结果支持有限采样下的范围资格，所有生产案例仍须逐例硬审计。首轮不把二维矩形范围作为默认目标。

#### 生产采用固定的8→32规则

范围冻结后，一次登记全部32例及其划分，先执行其中8例。

- 8例必须完成完整事件窗、转换、硬审计与谱系绑定。
- 共同生成／转换错误暂停该 scope。
- 新物理完整性失败触发范围复核。
- 保留失败分母，不删难点后补简单点凑数。
- 通过后自动执行剩余24例，无需逐案例确认。

### 3. 材料：先解决可靠性和吞吐，再生产标签

#### 修正材料语义

- 来源区域使用连续几何定义，并记录离散求积权重；不能使用观测粒子极值悄悄改写来源。
- 独立 tracer 的可靠性由当前位置的场支持、墙可见性和积分诊断决定。
- 初始锚定的某个数值粒子后来失效，不能自动判定独立 tracer 同时失效。
- 保留旧结果，新语义使用新版本，避免历史分数被覆盖。

材料输出至少包括：

- 来源质量、目的区域质量及转移矩阵；
- 首次通过的 CDF 和删失区间；
- 驻留时间、回流比例；
- 未知质量及其最坏界；
- 可评分路径误差和对应质量覆盖率。

路径误差在共同可靠集合上计算，同时报告覆盖率。不能因为路径误差较小就忽略大量未覆盖材料。

#### 性能与恢复作为正式交付

先测初始窗口、首次近壁失效窗口和回流窗口，分解：

`读取 → 时间插值 → 邻居索引 → 查询 → 实体墙可见性 → 积分 → 可靠性判断 → 写出`

实现：

- 有界帧缓存与可复用空间索引；
- 静态边界索引；
- 分块 tracer 计算和流式写出；
- 包含位置、可靠性、累计事件、驻留量、写出位置及版本哈希的恢复状态。

验收既包含短窗 profiling，也包含**完整源、完整时域的耗时、峰值 RAM 和输出大小**。独立进程 kill／resume 后必须与连续执行一致。

#### 先做 F3，再复制到第二家族

F3先执行15项诊断矩阵：

- 名义背景、困难端点，各三档分辨率 × 两档积分子步，共12项；
- 真正原生加密输出与其降采样对照，共2项；
- 512与4096 seeds 的求积对照新增1项。

“把已有0.01秒数据插值成0.002秒”不算加密原生输出。

若目标是整个生产参数范围的宏观 T2，继续补足端点、中心、两个独立内点的覆盖。默认完整矩阵为：

- 中心及一个困难端点：三档分辨率 × 两档子步，12项；
- 其余三个范围核验点：生产／细档 × 两档子步，12项；
- 中心及困难端点：原生密集输出／匹配降采样，4项；
- 五个参数点：增加高密度 seeds 求积对照，5项。

合计 **33个逻辑配置／scope**，哈希一致的结果复用；执行失败与恢复另计 attempt。

第二家族优先 F4，其次已取得 T1 的 F1、F2。第二家族必须重新定义来源、目的区域、事件和观察窗，不能照搬 F3 左右半区与8.35秒设置。

#### 宏观门槛与范围

F3保留已登记门槛。新家族采用以下预登记起点，并在独立资格矩阵前冻结：

- 每来源未知质量比例不超过1%；
- 终点比例／CDF 的最坏界差异不超过0.02；
- 驻留误差不超过 `0.02T`；
- 事件科学容差固定为 `0.0025T`，检测误差预算不超过其20%。

输出太稀时应加密或标记未解析，不能扩大事件容差。共同观察事件不存在时，事件 MAE 记为不适用，不填零。

范围资格通过后生产该 scope 的32例材料侧车，逐例执行覆盖与完整性门。模型材料评估可以按4→8→全部16个验证／测试案例逐批开展；**Core 全量指标必须补齐全部16例，前面的子集结果只作诊断。**

### 4. 学习与评测：先通接口，再进行正式比较

#### 拆开依赖，消除等待环

执行顺序固定为：

**接口与 oracle 验证 → 正式训练 → checkpoint 自主 rollout → 物理和材料评分。**

接口验证不依赖训练好的 checkpoint。参考位移 oracle 必须走同一 adapter、更新器和 evaluator；直接读取下一帧仅作为明确标记的特权诊断。

#### 首轮正式模型矩阵

| 配置 | 用途 | 种子 |
|---|---|---|
| 局部 MLP | 弱学习基线 | 17、29、43 |
| Graph raw | 图交互基线 | 17、29、43 |
| Graph known-force residual | 已知物理／控制先验对照 | 17、29、43 |

另执行常速度、已知外力更新两种无训练基线。

残差先验固定为：

\[
\Delta x_{\mathrm{prior}}=v\Delta t+\tfrac12a_{\mathrm{known}}\Delta t^2,\qquad
\Delta v_{\mathrm{prior}}=a_{\mathrm{known}}\Delta t
\]

`a_known` 必须来自公开、版本化的物理和坐标变换定义。

raw 与 residual 使用相同图主干、初始化、采样顺序、训练预算及两头归一化尺度。该先验不包含尚未实现的压力、黏性或墙面约束。

#### 固定训练默认

- 每次正式训练32,000次 optimizer update。
- 一个当前状态作为输入历史，包含原生语义位置和速度。
- 按“家族→scope→案例→transition”等权采样。
- 每次从完整有效粒子轴选256个 loss 中心；始终保留全场邻居信息。
- 图模型采用 hidden 64、两层消息传递。
- 邻域半径 `2h`，每目标最多64个邻居，按距离与粒子 ID 确定并列顺序；报告截断率。
- 两个输出头采用训练集统计归一化，MSE 等权。
- Adam，学习率 `1e-3`；首轮不加入未校准的数据噪声。
- 在模型构造前设置种子；保存 optimizer、RNG 和采样进度。

这里的256是损失采样中心数，**不是把流体删成256个粒子**。

完整两跳 halo 保留梯度；推理分块读取同一旧状态，全部预测完成后统一提交下一状态。必须通过与全图输出、loss 和梯度的等价测试。

#### 模型选择

- 每1,000步做固定验证 transition 的单步诊断。
- 在8k、16k、24k、32k执行全部验证案例的全时域自主 rollout。
- 从这四个 checkpoint 中选择：完整完成率优先，其次固定分母的归一化误差，最后较早训练步。
- 失败帧使用预登记罚值，不通过删帧改善分数；原始误差、失败时间另外报告。
- 测试结果不参与 checkpoint 选择。

#### 评测分母

最低三个家族、每族4验证＋12测试、9个模型运行，对应 **432个 T1 case-run**。

其中至少两个取得材料资格的家族，对应 **288个模型材料 case-run**。参考材料预处理可以缓存，模型预测流场的材料评估仍须逐运行执行。

指标至少覆盖：

- 位置、原生速度误差；
- 完成率、失稳时间、穿墙、质量与有效状态；
- 动能、几何感知场量；
- 材料转移、首次通过、驻留、回流和未知质量界；
- 训练成本、rollout 吞吐、峰值显存。

逐案例统计后做家族宏平均；置信区间按独立物理案例重采样，不能把粒子或帧当成独立样本。

不同分辨率的传统 SPH 对照主要比较公共物理量和材料任务，不强行按不对应的粒子 ID 算位置误差。

### 5. 数据划分与产品化

新一维 scope 使用：

\[
p_i=p_{\min}+(i+0.5)(p_{\max}-p_{\min})/32,\quad i=0,\dots,31
\]

固定划分：

| 集合 | 索引 |
|---|---|
| Train，16例 | 3、4、6、7、10、11、12、15、16、19、20、21、24、25、27、28 |
| Validation，4例 | 8、13、18、23 |
| ID，6例 | 5、9、14、17、22、26 |
| 参数 OOD，6例 | 0、1、2、29、30、31 |

OOD 表示超出模型训练参数支撑，仍处于 CFD 资格范围内。生产点若与资格物理谱系碰撞，停止注册并修订整版设计。

现有 F3 保持原始划分，不事后制造 ID 测试。

产品接口继续落在现有 [实验目录](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab)，新增统一入口覆盖：

`verify → inspect → train → rollout → evaluate → reproduce`

reader 使用 `data_root + 相对路径`，包中携带单位、坐标系、schema、配方、资格、split、输入适配器和文件哈希。

旧数据通过版本化迁移器生成新副本；保留原始证据及旧分数。

---

## 四、两台机器的调度、资源计量与推进顺序

### 1. 已核对的资源与分工

| 机器 | GPU | 本次检查的情况 | 默认用途 |
|---|---|---|---|
| 本地 Ada | 8 × RTX 6000 Ada，约48 GiB／卡 | 基本空闲；本地磁盘约8.3 TiB可用 | CFD批次、转换、材料计算、长期归档 |
| H200 | 4 × H200 NVL，约140 GiB／卡 | GPU1已有约107 GiB显存的训练进程；其他卡较空闲 | 完整图训练、大场 rollout、显存需求较大的作业 |

两台均约128逻辑 CPU、251 GiB RAM。H200 磁盘当时仅约586 GB空闲，因此采用有限工作缓存，原始数据优先归档在本地。

这些是规划时快照，启动前重新探测。既有进程作为占用计入；不固定排除整张卡，也不干扰已有任务。

### 2. 同卡多任务的准入规则

取消旧的“每卡一个任务”“最多两个任务”等固定限制。

调度按以下原则执行：

1. 新 workload 先测单任务峰值显存、CPU／RAM、I/O和耗时。
2. 显存预留按测得峰值的1.2倍；每卡保留 `max(4 GiB, 10%容量)` 的公共余量。
3. 根据实时外部占用和已登记任务峰值，继续接纳同卡任务。
4. 同时检查主机 RAM、CPU和磁盘吞吐，避免 GPU 等待数据。
5. 对同类 workload 逐级增加并发，比较总有效吞吐；显存允许且吞吐改善就继续增加。
6. 连续两级增加并发的吞吐收益不足10%，停止继续堆同类任务，尝试混合其他类型。
7. 初始使用普通多进程 CUDA，不把修改 MPS／MIG／驱动配置作为前置条件。

CUDA 多进程可共享设备，但并发是否提升吞吐仍需实测。[NVIDIA MPS 使用说明](https://docs.nvidia.com/deploy/mps/when-to-use-mps.html)

运行目标是每小时完成更多合格产物，同时保持机器可用。

### 3. 总控和 worker 的运行契约

中央持久状态使用单写者事务数据库及追加事件日志。所有旧 runner 的写账入口接入：

`reserve → launch receipt → heartbeat → finalize usage`

worker 只写自己的不可变 attempt 目录和结果回执。

必须支持：

- 幂等提交，重复回执不会重复计数；
- 总控重启后核对实际 PID、GPU进程和产物；
- worker 已启动但总控中断时，恢复登记；
- 心跳暂失不直接释放仍在运行的任务资源；
- 基础设施重试、科学修复和恢复执行分别计数；
- 同一任务不被两个协调进程重复启动。

每个作业固定代码、输入、二进制及环境版本。跨机传输按内容哈希校验后发布，不覆盖运行中的目录或整个 `.git`。

### 4. 资源预算按实测里程碑形成

按用户选择，不预设一个缺少依据的全项目 GPU 小时总额。

每个里程碑启动前，总控根据代表性实测生成：

- 逻辑配置数、执行 attempt 数；
- 预计 GPU／CPU消耗和关键路径时间；
- 峰值显存、RAM、暂存和归档空间；
- 失败重试与恢复余量；
- 在当前并发下的预计完成时间。

并行作业同时报告：

- 各进程运行 GPU 小时之和；
- 实际设备被占用时间的并集。

两者不能混用。CPU计量包含子进程，存储区分唯一内容与副本。

历史 L2 预算、期限和已用资源保留；下一轮正式登记本计划的里程碑资源策略，不能通过清零旧账或沿用旧活动名称掩盖范围变化。

### 5. Agent 波次与 GPU 作业解耦

当前最多同时运行四个 agent，采用“总控＋三个专职 agent”，计算进程数量由资源调度器独立决定。

| 波次 | 并行工作 | 汇合条件 |
|---|---|---|
| W0：打底 | C建立调度／账本；A1公共接口；A3复核F4；A5材料诊断与性能 | 小型公共样例、旧资产接入、资源实测 |
| W1：主线展开 | A6模型实现；A4推进F1／F2；A5材料资格；已准备CFD持续运行 | 接口oracle通过；修复候选进入资格研究 |
| W2：增加范围 | A2 F3扩展；A7评测；A8打包；CFD／训练／材料作业持续 | 各scope通过后自动8→32 |
| W3：补齐产品 | 正式9次训练、全部T1／T2评估、异机复现 | 分母完整、资格证据齐全、可移植包通过 |
| W4：扩大覆盖 | 强基线、额外泛化轴、F5／F6和外部实验锚点 | 独立版本和独立验收 |

agent 提交持久作业后即可继续实现或接手其他工作，不必占着名额等待进程结束。

### 6. 自动失败处理

- 每个明确失败机制最多两类有证据的修复假设，每类先做一次修复 canary。
- 已修好的偶发基础设施故障允许一次同输入重试。
- 改变边界、初态、时间推进或重建后端时，重新判断资格失效范围。
- F1或F4无法取得资格时，自动提升F2；第二个材料家族按 F4→F1→F2顺序选择已合格对象。
- 某个 scope 失败不停止其他独立方向。
- 若最终仍不足三个 T1 家族或两个宏观 T2 家族，保留 Core 未完成状态；不能通过给 F3 多个 scope 改名凑数。

---

## 五、验收、后续扩展与默认边界

### 1. 必须覆盖的验收场景

| 类别 | 必须验证 |
|---|---|
| 数据完整性 | 原生身份、有限值、单位、时间轴、质量、合法生命周期、实体墙／开口区分 |
| 范围资格 | 三档空间、时间推进、原生 cadence、独立内点与完整事件窗 |
| 谱系隔离 | 分辨率、重启、裁剪、材料侧车不能跨训练和评测集合 |
| 因果性 | 替换未来 CFD 后，模型输出完全不变 |
| 材料辨识力 | 点云相同但材料 ID 置换时，材料指标能够识别错误 |
| 场重建 | 墙、开口、自由表面、分离液团、局部支持不足与删失 |
| 图模型 | 全图与 halo 的输出、loss、梯度一致；分块推理同步提交 |
| 更新语义 | 位移与原生速度分别核对，oracle走真实模型接口 |
| 恢复 | 材料和训练中断恢复；总控重启；重复回执；孤儿进程核对 |
| 调度 | 同卡并发、最后一份资源竞争、外部占用变化、OOM后的有界恢复 |
| 产品 | 数据移动目录、另一台机器读取、损坏文件拒绝、版本不匹配拒绝 |
| 评测 | NaN、提前失稳、缺帧、超时均留在预登记分母中 |

### 2. Core 完成判据

必须同时满足：

- 至少三个真正不同家族完成 T1 资格和登记生产批次。
- 至少两个家族完成范围明确的宏观 T2 资格及逐例材料侧车检查。
- 9次正式学习运行具有完整训练记录和可用 checkpoint。
- 所有登记评测都有实际执行证据，`missing=0`；模型失稳明确分类。
- 无未来真值泄漏、谱系泄漏或接口语义混用。
- 包内相对路径、版本、哈希和统一命令可用。
- 异机复现通过，并输出科学结果与资源消耗。
- 总控根据实际产物语义计算完成状态，报告数量和测试数量不替代上述条件。

2026-09-24 的只读总控快照仍为 `can_finalize=false`：T1 家族 2/3（F3、F4）、宏观 T2 0/2、正式训练 0/9、目标 T1/material case-run 分母分别缺 432/288，独立完整产品复现未通过；因果 lineage 与 evidence validity 检查通过。`issues=[]` 不代表计划完成。详细状态见[UPDATE-41](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-24-UPDATE-41.zh-CN.md)。

### 3. Core 之后怎样走向“全面 benchmark”

后续扩展保持同一接口，分别建立实验，不把 Core 已有结果扩大解释。

| 扩展方向 | 具体工作 |
|---|---|
| 模型覆盖 | 接入标准 GNS、SEGNN，各三个种子；随后增加完整物理混合方法 |
| 几何泛化 | 固定控制，留出障碍／通路 scope，重新训练并评估 |
| 控制泛化 | 固定几何，留出驱动模板；区分幅值外推和控制机制变化 |
| 组合泛化 | 训练见过单因素，测试未见组合；提前冻结组合表 |
| 时间泛化 | 明确限制训练时间窗，使用更长参考时域；与普通长 rollout 分开 |
| 分辨率／规模 | 新物理谱系与配对分辨率设计，公共场量和材料任务统一评分 |
| 部分观测 | 固定传感／采样协议，独立定义状态恢复任务 |
| F5／F6 | 波浪、越堤与自由刚体分别取得资格，不阻塞前三族 |
| 外部验证 | 接入原始实验观测，核对几何、传感器、误差和许可 |
| 公开发布 | 新隐藏测试、数据卡、许可证、归档版本、提交与评分协议 |

三档 CFD 资格研究本身不等于模型分辨率泛化实验；多家族联合训练也不等于留一家族泛化。

### 4. 本计划采用的默认边界

- 首版聚焦单相牛顿液体及当前可解析的宏观自由表面机制。
- 优先完成宏观材料输运；精确路径与外部物理真实性分别验收。
- 现有32例 F3 属于开发资产，其历史角色与失败证据保留。
- H200和Ada均可使用，同卡多任务由实测显存与吞吐准入。
- 数值阈值和范围先登记再研究，不能观察失败后放宽。
- 初始调研和计划阶段已结束，现按依赖进入实施续推；后续波次由总控根据依赖自动推进。2026-09-25 已完成 F8 R008 非授权 attempt-ledger / 15-case aggregate 静态验证器加固及 Terra High 复核（见 [UPDATE-127](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-127.zh-CN.md)）；这不代表可信来源认证、运行准入或资格完成。
- 2026-09-25 UPDATE-128 新增 F8 R008 attempt-ledger attestation 的非授权 Ed25519 verifier：严格 canonical JSON / Base64 / exact schema 校验、matrix/ledger/coverage bindings 复核和临时 key 合成测试均已实现；GPT-6 Luna Max 独立只读安全复核 PASS、无 P1/P2。即便签名有效也不认证 candidate key、不验证 descriptor-root/supervisor/runtime，不 mint capability，T1 false、credit 0。attestation、ledger、V2 attempt projection 与 V5 journal 定向测试合计 173 passed；详见 [UPDATE-128](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-128.zh-CN.md)。
- 2026-09-25 UPDATE-129 增加 F8 native-fluid-table 到 Core HDF5 的诊断转换原语，补 `particle_zone=0` 并保留资格 split；source table 经 held-FD/raw-frame 复核，输出分块复验并 no-replace 发布。GPT-6 Luna Max 针对 size-cap 与最终路径 rebind 修订复核 PASS。75 项定向 F8/Core 测试通过；当前仍无 trusted provenance、worker/scheduler 或 15-case T1，T1 false、credit 0。详见 [UPDATE-129](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-129.zh-CN.md)。
- 2026-09-25 UPDATE-130 按原三源文献核验规则新增 RERUN9：0 verified、0 unverified、6 verify_pending。arXiv HTTP 406 与 Semantic Scholar HTTP 429 为本轮 API 错误；Crossref 仍精确命中三项。遵循规则未在本会话重试、未以人工页面核对升格机器 verdict；详见 [UPDATE-130](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-130.zh-CN.md)。
- 2026-09-25 UPDATE-131：收紧 `CoreDataset` descriptor-only compact 输入边界：HDF5 `times()` / `read_state()` 继续经 held FD 诊断读取，但 geometry/control path-backed refs 不再被重开；`known_inputs()` 与 whole-source `verify_sources()` 在资产访问前拒绝，避免不完整输入验证。Terra High/high 只读 follow-up 无 P1/P2；定向 synthetic/compact/FD tests 40 passed，1 个既有生产 F3 全轴用例排除，py_compile/diff check 通过。只读挂载盘点未发现现成的本地 fs-verity positive mount；不提供可信 producer/root/runtime、capability 或 T1，`formal_eligible=false`、资格信用为零。详见 [UPDATE-131](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-131.zh-CN.md)。
- 2026-09-25 UPDATE-132：新增 F8 attempt-ledger caller-supplied raw-object binding：所有非空引用与 `(stage, role, object_id)` 原始 bytes map 精确闭合，并核对字节数/SHA-256、拒绝缺项/多项/冲突 identity，增加对象数与累计字节上限。Terra High/high 只读复核无 P1/P2，仅建议补 fail-closed 负测；已覆盖冲突描述符、错误 key、长度、空 `not_started` 和资源边界。ledger/V2/V5 定向测试 166 passed，py_compile/diff check 通过。该 API 不访问路径、不解析对象内容、不认证来源；ledger completeness、B/C/D 语义、outcome、F8 T1 均未闭合、零信用。详见 [UPDATE-132](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-132.zh-CN.md)。
- 2026-09-25 UPDATE-133：在 raw-reference binding 上新增纯内存 B/C/D receipt envelope 核验：bounded strict JSON、冻结 stage schema/required fields/status/time 检查，并核对 scope/case/attempt/nonce 与 ledger event；明确只保留 untrusted status claim，不等同完整 bundle verification。Terra High/high 无 P1/P2，所提 P3 文案/覆盖缺口已修订补测。ledger/V2/V5 三文件 177 passed，另原冻结 v1 verifier 的 D synthetic 单包和 B/C/D 完整链 2 passed；py_compile/diff check 通过。确认不可修改的 v1 stage verifier 源文件保持原样，以免破坏 D code-review receipt 固定摘要。完整 stage tree、producer/root/attestation/runtime、journal-proc 绑定、F8 T1 仍未完成，零信用。详见 [UPDATE-133](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-133.zh-CN.md)。
- 2026-09-25 UPDATE-134：C `process_terminal` 引用接入 V5 journal shape parser 并对照外层 ledger attempt nonce，拒绝跨 attempt nonce replay；局部 process-lifecycle 汇总字段标注为 unverified，不映射 opaque ledger generation ID。Terra High/high 指出 1 GiB 内存 JSON 输入的资源风险，随后 16 MiB V5 / C-journal 上限与 64 MiB raw-object aggregate cap 均在 hash/decode 前 fail-closed；malformed、超限及 nonce 负测补齐，最终 follow-up 无 P1/P2/P3。ledger/V2/V5 182 passed，另 D synthetic 单包和完整 B/C/D chain 2 passed，py_compile/diff check 通过。更大 journal 须另行实现 streaming parser；event-source completeness、runtime/source trust、generation identity、stage bundle semantic 与 F8 T1 仍开放、零信用。详见 [UPDATE-134](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-134.zh-CN.md)。
- 2026-09-25 UPDATE-135：撤回对 C V5 journal local lifecycle complete 的跨层硬拒绝：V5 structured generation 未与 ledger opaque ID 建立映射，且失败/开放 attempt 必须留在 unresolved 分母中。新增所有适用 terminal outcome（含 caller `passed` claim）和 open attempt 的保留测试；局部 lifecycle 仅以 unverified 诊断呈现，source completeness 与 process identity 仍 false。Terra High/high follow-up 无剩余 P1/P2/P3；ledger/V2/V5 190 passed，py_compile/diff check 通过。真实进程/事件源闭环和任何资格信用仍未取得。详见 [UPDATE-135](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-135.zh-CN.md)。
- 2026-09-25 UPDATE-136：按项目锁定环境复核 Core 总控与材料候选：`can_finalize=false`，T1 为 F3/F4 两族，宏观 T2 `0/2`、正式训练 `0/9`；已登记 T1 case-run 缺 288，第三族另有 144 尚未登记，固定最低分母 432；材料 case-run 目标 288 全缺。F4 support-cap R002 CPU/native 预检为 pass，但 runtime 未授权、六份资源快照均 deferred；静态/合成回归 50 passed，零资格信用。F3 row30 R003 保持失败并禁止重试。F8 R008 仍缺经独立审查的逐案例 materialization verifier/worker evidence contract 与来源验证的 15 行结果。没有启动 GenCase/native decoder、worker、solver、GPU、queue 或改变 registry/ledger。详见 [UPDATE-136](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-136.zh-CN.md)。
- 2026-09-25 UPDATE-137：新增 F8 R008 逐案例 attempt-evidence binding，连接 15 行矩阵、ledger 全部注册/重试、V2 attempt projection 和 B/C/D raw receipt envelope；精确核对 receipt identity、digest、status claim 和 inventory，未绑定 failure status 显式计数，所有案例与 attempt 仍 unresolved。attempt JSON 字节预算采用增量计数，event-seq 与 time-hex 字段设固定上限；open/not-started、status mismatch 与 retry 集成测试补齐。跨模块定向回归 296 passed，`py_compile`、`git diff --check` 通过；仅合成输入，无 worker、GenCase/native、solver、GPU 或 queue 执行。该绑定不认证来源/producer/runtime，不提供 T1 eligibility 或信用；Core 仍未完成。详见 [UPDATE-137](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-137.zh-CN.md)。
- 2026-09-25 UPDATE-138：更正 UPDATE-136 的缺口措辞：F8 R008 已有 Terra High 静态审查 PASS 的 B/C/D per-case provenance verifier，以及 table metric bundle verifier v2、15-row metric adapter；它们只验证调用方证据/合成材料，不认证 worker、authority issuer、supervisor、runtime 或 loaded-module identity。implementation-review、bundle verifier、metric bundle verifier、matrix adapter 回归 82 passed。真正剩余项是可信 worker/执行来源契约与完整来源验证的真实 15-case solver 结果；没有 production bundle/solver frame 或受保护 workload 运行。详见 [UPDATE-138](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-138.zh-CN.md)。
- 2026-09-25 UPDATE-139：将 F8 attempt ledger 的每次完整 B/C/D receipt refs 接到既有 held-FD 内容 verifier，核对 receipt digest/status 并拒绝跨 retry 换包；每次只接收且最多核验一个明示选择的 attempt，其余 retry 显式返回 unverified，authorization/code-review bytes 在 hash 前限为 8 MiB。8 个跨模块测试文件 312 passed，`py_compile`、`git diff --check` 通过。仅合成输入；不认证 authority/worker/runtime，也不解析出 T1，所有 attempt unresolved、零 credit；可信 worker/执行来源和真实 15 行结果仍缺。详见 [UPDATE-139](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-139.zh-CN.md)。
- 2026-09-25 UPDATE-140：把 V2 attempt-result observation prefix 与经验证的 full native B/C/D 轴按冻结窗口映射：full axis 321 帧，observation indices `[128,320]` 共 193 帧；本地 ordinal `j` 对应 full-axis `128+j`。projection 时间值只与冻结 observation-axis prefix 逐位比对，并要求已验证链覆盖完整 full axis；明确这不认证 projection 来源，frame projection/source trust/T1 仍未闭合。8 个跨模块测试文件 312 passed，含完整 observation-prefix 与错误时间轴负测；仅临时合成输入，无生产 workload。详见 [UPDATE-140](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-140.zh-CN.md)。
- 2026-09-25 UPDATE-141：新增 F8 R008 supervisor-session claim-consistency bridge：ledger 从 raw bytes 派生唯一 C process-terminal/journal ref；V5 以不可变窄 projection 摘要 root spawn/exec 及进程树 observed-load；两份独立 Ed25519 domain 签名绑定矩阵/行、ledger/coverage、attempt/nonce、C journal、candidate-key fingerprint 与 runtime observations。Terra High/high 最终只读复核 PASS，无 P0–P3；四个紧邻 suites 235 passed，九文件 F8/Core 回归 344 passed。此接口不认证 candidate key/root/supervisor/runtime/event-source completeness，仍固定 unresolved、T1 false、credit 0；仅合成输入，无生产 workload。详见 [UPDATE-141](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-141.zh-CN.md)。
- 2026-09-25 UPDATE-142：按原三源机器判据新增文献 RERUN10，结果 2 verified、1 unverified、3 pending；LagrangeBench 与 FD-Bench 双源精确匹配，FuelTank 仍单源，GNS/Neural SPH/FluidLab 因 arXiv HTTP 406 保持 pending。未改验证器或候选/匹配规则，未以人工来源升格机器 verdict；离线 verifier tests 7 passed。整体文献机器核验仍未完成。详见 [UPDATE-142](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-142.zh-CN.md) 与 [RERUN10 回执](lagrangian-fluid-lab/reports/PLAN-REFERENCES-VERIFICATION-2026-09-25-RERUN10.json)。
- 2026-09-25 UPDATE-143：只读 Core completion 账本仍为 `can_finalize=false`：T1 家族 2/3、宏观 T2 0/2、训练 0/9、目标 T1 case-run 缺 432（其中 144 尚未登记）、材料缺 288、异机复现未通过；`issues=[]`、证据结构和因果 lineage 检查通过。rootless synthetic 探测确认 Linux 6.8 可对 anonymous memfd 施加完整写/扩容/缩容/再封印 seals，h5py 从同一 sealed FD 重读成功，但不提供 fs-verity measurement 或来源/签名信任。此项只记录替代方案研究线索，不修改 V13 fs-verity gate、不接正式 reader/worker、不授予执行或资格信用。详见 [UPDATE-143](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-143.zh-CN.md)。
- 2026-09-25 UPDATE-144：预检 rootless ext4 verity-image 路径：unprivileged user namespace 可创建，但 `/dev/loop-control` 与 `/dev/loop5` 当前用户不可访问；在创建镜像或尝试挂载前停止，未改动设备、文件系统或挂载。ext4 的 verity feature 必须由格式化选项或管理员操作预设，user namespace 本身不能提供此能力。结果排除当前环境下的 rootless loopback 方案，但不声称排除其他已配置的 verity mount；V13 hard gate 不变。详见 [UPDATE-144](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-144.zh-CN.md)。
- 2026-09-25 UPDATE-145：将 `core_formal_planner` 计划态与执行权分离：顶层新增 `plan_ready`，`launch_allowed` 恒为 false；job spec 中 `launch_allowed_by_planner` 和 `launch_allowed` 也恒为 false。合成测试覆盖当前 diagnostic hold、私有 job builder 与 stubbed ready 序列化分支，证明 planner 即使 ready 也不自授执行权。六个相关 planner/admission/launch/source-closure suites 52 passed，py_compile/diff check 通过；source-closure audit 的当前摘要基线更新，历史收据保留。此修改不实现 trusted admission capability、不解除 formal hold、不启动 training/GPU/queue。详见 [UPDATE-145](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-145.zh-CN.md)。
- 2026-09-25 UPDATE-146：关闭 F4 collector 与 multifamily assembler 旧 Mapping/path public API 的 formal-release 请求；二者在读取/解析调用方输入前 fail closed，diagnostic `formal_release_requested=false` 行为保留。F4 collector/connector、V3 codec 与 formal readiness 定向测试 60 passed、1 个既有真实首八例收据夹具因旧顶层 schema 契约不匹配而 deselected；py_compile/diff check 通过。未改历史收据、未放宽 schema 或 formal gate，未启动 worker/solver/GPU/queue。trusted root、V3 capability-only consumer、snapshot/fs-verity/runtime 闭环仍未实现；不增加 T1/T2 或资格信用。详见 [UPDATE-146](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-146.zh-CN.md)。
- 2026-09-25 UPDATE-147：将过时的 F4 “real first eight”测试改为明确断言无 outer schema 的历史 `qualification-tick.json` 被拒绝，遵守 UPDATE-87 的精确 legacy-schema 门；不改生产 reader 或历史收据，diagnostic 正向行为继续由 synthetic suite 覆盖。F4 collector/connector、V3 codec 与 formal-readiness 定向回归 61 passed，无 deselect。此项只修正测试合同，不代表收据迁移、执行或资格状态变化。详见 [UPDATE-147](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-147.zh-CN.md)。
- 2026-09-25 UPDATE-148：新增 F8 R008 execution-readiness audit v5，确认后续已有源绑定 PASS 的 B/C/D per-case 与 metric-bundle 静态审查，替代 v4 已过时的“缺少逐案例 verifier”表述；同时发现 15-case matrix 的归档审查仅因测试绑定变化而过期，故不计作当前 PASS。可信 worker/来源与 runtime identity、真实来源验证的 15-case 结果、native integrity/timestep adjudication 仍缺。v5 readiness/T1/执行权限均 false、credit 0；未运行生产 workload 或更改分母/账本。新回归 4 passed，py_compile/diff check 通过。总控仍 `can_finalize=false`（T1 2/3、宏观 T2 0/2、训练 0/9，目标 T1/material 缺 432/288）。详见 [UPDATE-148](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-148.zh-CN.md)。
- 2026-09-25 UPDATE-149：按冻结候选、原始三源判据新增文献核验 RERUN11，结果仍为 2 verified、1 unverified、3 verify_pending；三篇 arXiv 请求仍 HTTP 406，未以网页人工核对替换机器 verdict。核验器/候选哈希保持不变，离线回归 7 passed，新增回执 SHA `f7b3dd8e…c94be48`。该轮提供新的有时间戳审计记录但未改善机器状态；API 或预登记规则变化前不立即重试。详见 [UPDATE-149](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-149.zh-CN.md) 与 [RERUN11 回执](lagrangian-fluid-lab/reports/PLAN-REFERENCES-VERIFICATION-2026-09-25-RERUN11.json)。
- 2026-09-25 UPDATE-150：修复 F8 R008 metric-matrix source-log 任意路径/无界读取 P2，并将受限路径语义明确版本为 `solver_timestep_audit.v2`，不暗改旧 v1；audit/日志经逐级 no-follow dirfd 读取，日志只允许 sibling basename、single-link、稳定绑定及 256 MiB 上限。per-case matrix result 改为 exact field set，拒绝伪 diagnostic wrapper/正向信任声明；外层/table/metric credit 严格要求整数零。合成 matrix 44 passed，三组联合回归 77 passed，未修改的旧 v1 reader 回归 18 passed，py_compile/diff-check 通过；没有 production/runtime/T1 运行。旧 review-v2/readiness-v5 收据保留历史，GPT‑6 Luna Max follow-up 正在审查，尚不声称当前 PASS。详见 [UPDATE-150](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-150.zh-CN.md)。
- 2026-09-25 UPDATE-151：Terra High/high 对 F8 R008 `solver_timestep_audit.v2` 只读复核为 `REVISE`：matrix adapter 未解析绑定文件，仍直接信任 JSON 声明的 `max_solver_dt_s`；RunPARTs CSV 本身也不能证明完整、正常的冻结运行，且 append/提前停止与 Symplectic 语义须纳入执行闭环。本地仅收紧 audit 数字类型与 exact checks 键集（matrix 49 passed、未改旧 v1 adapter 18 passed、py_compile/diff-check 通过），不宣称 P1 已修复或 review PASS。后续需新版本 parser/producer + 同源重算 + 专属 attempt/定义/命令/成功终止绑定；未运行任何生产 workload，零资格信用。详见 [UPDATE-151](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-151.zh-CN.md)。
- 2026-09-25 UPDATE-152：按用户授权对 F8 R002 做新一轮只读设计复核；Definition/control/log 哈希与旧 v3 完全一致，官方 GenCase 仍因缺 `hswl` 退出码 1，故仅重复确认失败、不改输入、不重试 R001/R002 或执行。reviewer 未 attestate Terra 身份，不记 Terra High PASS。F3 row30 新资源/调度预检 v3 已消费唯一授权：当前 load、worker、scheduler、RAM、disk 均通过，但历史 ledger 已过期且 CPU 上界 `911.958>896`，结果 `blocked_no_worker_authorized`；源 HDF5 未哈希，未启动 worker。F4 当前唯一 supportcap v3 候选的 R002 CPU/native preflight 已通过且同 scope one-shot 已消耗、runtime 未授权；没有第二份新候选，故未重复使用旧 scope。F3 v2+v3 tests 6 passed，py_compile/diff-check 通过。T1/T2 与资格状态不变。详见 [UPDATE-152](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-152.zh-CN.md)。
- 2026-09-25 UPDATE-153：为 F8 R008 v2 timestep caller claim 加 fail-closed：保留最大步长仅作明确标注的未验证 claim，移除带 `passed` 语义的 caller 布尔字段；v2 timestep `passed` 与总 comparison gate 恒 false，并标明 attempt identity/正常终止未验证。Terra High/gpt-5.6-terra/high 窄范围 follow-up `PASS`，但无密码学模型身份 attestation；不等于完整 matrix implementation review PASS。matrix v2 + 旧 v1 adapter 联合回归 67 passed，py_compile/diff-check 通过。历史 review/readiness receipts 不覆盖。RunPARTs 源内容、attempt identity、算法配置和正常完整终止仍未验证，故 T1/readiness/资格信用不变。详见 [UPDATE-153](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-153.zh-CN.md)。
- 2026-09-25 UPDATE-154：新增 F8 R008 RunPARTs diagnostic parser v1 与 matrix adapter v3，从固定 `RunPARTs.csv` 重算最大已记录 PART `DtMax`，严格匹配 `JSph.cpp` 26 列表头与 final footer，并采用 no-follow/single-link/stable-FD 和 8 MiB、20,000 行硬上限；restart 首行允许非零 PART/time 起点。matrix v3 明确不认证 attempt/config/正常完整结束，time-step/aggregate gate 恒 false、T1/readiness false、credit 0。Terra High 初轮 REVISE（两项 P2、无 P0/P1）后，restart 与资源上限 follow-up PASS；固定容量依据已注释，review 无密码学身份 attestation。parser+matrix v2/v3+旧 v1 adapter 定向测试 100 passed，py_compile/diff-check 通过；仅 synthetic 输入，未读生产 RunPARTs/bundle/frame，未运行 GenCase/native decoder/solver/worker/GPU/queue。旧 review/readiness 收据未刷新；可信执行来源、完整结束验证及 15-case T1 仍未完成。详见 [UPDATE-154](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-154.zh-CN.md)。
- 2026-09-25 UPDATE-155：新建 F8 R008 RunPARTs diagnostic parser v2 与 matrix adapter v4；诊断输入策略限定为单段 Part 0/time 0，restart/append fail-closed，但不证明实际 invocation 遵守该策略；全部 26 列逐项做类型/范围检查，不声称跨列原生运行语义。Terra High/high 初轮 REVISE 后最终 follow-up PASS，无剩余 P3；parent-authored matrix review v3 绑定 parser/matrix/writer/tests，readiness audit v6 仅移除旧 stale-review blocker，保留可信执行来源、真实 15-case 结果、native integrity/timestep adjudication 三项阻塞，T1/readiness false、credit 0。reviewer 未跑测试、无密码学模型 attestation；v6 另有只读一致性 PASS，但不计独立 Terra High review。v1/v2 parser、matrix v2/v4、旧 metric adapter、review v3 与 readiness v6 联合回归 153 passed，py_compile/diff-check 通过。仅 synthetic 输入，未读生产 RunPARTs/bundle/frame，未运行 GenCase/native/solver/worker/GPU/queue；Core completion 只读复核仍 `can_finalize=false`、T1 2/3、T2 0/2、训练 0/9、case-run 缺 432/288。详见 [UPDATE-155](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-155.zh-CN.md)、[matrix review v3](lagrangian-fluid-lab/campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/native-fluid-table-schema-v2/metric-matrix-review-v3/receipt.json) 与 [readiness v6](lagrangian-fluid-lab/campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/t1-execution-readiness-audit-v6/receipt.json)。
- 2026-09-25 UPDATE-156：对 RERUN11 的 arXiv 406 做三次单条只读诊断：核验器同 UA 的 HTTPS、官方文档所示 HTTP（重定向到 HTTPS）、Python 默认 UA 均返回空响应体 HTTP 406；响应头见 Varnish，无法归因源站或网络路径。官方文档确认 GET/`id_list` 形式有效，官方状态页当前报 export API Up，但无前后状态变更证据。没有运行全量 verifier、没有新增 RERUN12 或改机器 verdict；保留 2 verified、1 unverified、3 pending。详见 [UPDATE-156](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-156.zh-CN.md)。
- 2026-09-25 UPDATE-157：新增 F8 R008 CPU single timestep 源码语义诊断，函数级核验配置覆盖、Verlet/Symplectic DtMax 差异、NstepsBreak/minimum-fluid/TERMINATE 终止路径及 RunPARTs footer 局限；runtime evidence 有机器字段，但仅 untrusted 诊断。Terra High/high 对抗性只读复核确认最后的 TERMINATE 分支绑定修复，允许以“不发布 receipt”的实现保留/提交。定向 39 passed，既有 F8 RunPARTs/metric/matrix/readiness 联合回归 192 passed，py_compile/diff-check 通过。目标 ancestry 为 `775 jade:jade` group-writable，故 no-follow writer 按设计拒绝发布；未创建 receipt、未改权限。无 solver/worker/GPU/queue、runtime identity、15-case T1 或资格信用；readiness v6 与 Core 状态不变。详见 [UPDATE-157](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-157.zh-CN.md)。
- 2026-09-25 UPDATE-158：新增逐案例 F8 R008 diagnostic-only runtime/timestep 联合检查，组合 RunPARTs v2 原始 CSV、当前 CPU 源码语义审计和未认证 completion claims；Verlet 记录值只在未验证的算法声明条件下可解释为应用步候选，Symplectic `PartDtMax` 明确为 corrector 候选而非本步实际 timestep；footer 不证明正常完成，较晚日志时间报不一致、较早时间在缺少 cadence/coverage 时保持未充分判定。所有身份/completion/timestep/T1/readiness 仍 false、credit 0，不发布 receipt。同步令源码审计 JSON reader 拒绝 NaN/Infinity。GPT-6 Luna Max 初审 `REVISE` 后修复 endpoint/健壮性问题，follow-up 代码审查 `PASS`、无 P0–P2；保留未认证 tolerance claim 的 P3 提示，无密码学模型身份 attestation。兼容 Conda 环境五组联合回归 158 passed，py_compile/diff-check 通过。未读生产 RunPARTs/bundle/HDF5/frame，未运行 solver/worker/GPU/queue，未改 registry/ledger/分母。详见 [UPDATE-158](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-158.zh-CN.md)。
- 2026-09-25 UPDATE-159：新增 F8 R008 冻结 baseline/refined 时间步配对诊断；按 matrix v2 的固定 pair 与 `0.05 rad` 门限，仅在两侧未认证 completion claims、RunPARTs endpoint relation 和 CPU-single Verlet 候选全部满足时比较记录 `DtMax`。Terra High 初轮 P2/P3 已修正：四个上游安全标志与 schema/state 强制固定，超大整数 fail-closed，精确阈值边界有测试；follow-up `PASS`、无 P0–P2。专属回归 25 passed，py_compile/diff-check 通过。全部 provenance/completion/timestep/T1/readiness 仍未验证、credit 0；只用合成字节，无生产 workload/solver/worker/GPU/queue，也未改 registry/ledger/分母。详见 [UPDATE-159](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-159.zh-CN.md)。
- 2026-09-25 UPDATE-160：修复 GNU CPU CMake 目标的隔离输出目录、可选 MoorDynPlus 依赖和 CUDA-only fast-math 标志，并为 `SIZE_MAX` 加入 `<cstdint>`。在 CMake 4.3.0/GNU 13.4.0、CUDA/Chrono/WaveGen/MoorDynPlus 均关闭的临时 Release build 中，`DualSPHysics5.4CPU_linux64` 编译链接成功；独立 configure-only 检查确认默认产物路径仍为 `bin/linux`。只用 `file`/`readelf` 检查 ELF 与哈希，没有执行 binary 或运行任何 workload。Terra High 审查调用被当前账户策略拒绝，未获得独立 review verdict；此构建不绑定 R008 runtime/provenance，不改变 readiness/T1/资格信用。详见 [UPDATE-160](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-160.zh-CN.md)。
- 2026-09-26 UPDATE-161：新增 F8 R008 T1 metric matrix adapter v5，直接重算 matrix v4 并为冻结 15 行逐项组合原始 RunPARTs、runtime/timestep 诊断和 horizon claim 对齐；v4 pair raw SHA/DtMax 与逐案例重算一致，phase 只取 v4 重算。v4 status/bindings、B/C/D digest 子映射、v2 RunPARTs schema/scope/26 列标志及 tolerance 公式均 fail-closed；所有信任、完整完成、native integrity、T1/readiness 仍 false、credit 0。Terra High/gpt-5.6-terra/max 初审 findings 修复后 follow-up PASS，无 P0–P3；新专项 27 passed，五组相邻 F8 回归 141 passed，py_compile 通过。仅临时合成数据，未运行 solver/worker/GPU/queue，也未改 registry/ledger/分母；真实 provenance-verified 15-case 结果及 readiness-v6 三项阻塞仍未完成。详见 [UPDATE-161](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-161.zh-CN.md)。
- 2026-09-26 UPDATE-162：新增 F8 R008 单案例纯 post-run bridge，前后完整复核 B/C/D+metric v2 链，绑定 stage refs、D table bytes/SHA、case metrics，并用 verified C frames/held D FD 物化 qualification-only Core trajectory。修复 CoreDataset 对 HDF5 split 与 manifest 的首开/缓存一致性检查；adapter 改用 O_TMPFILE + held-proc-FD `linkat(AT_SYMLINK_FOLLOW)` 原子 no-replace 发布，不再使用命名临时源或按名清理。GPT-6 Luna Max 只读 follow-up PASS、无 P0–P2；三个 synthetic suites 17 passed、py_compile/diff-check 通过。O_TMPFILE/procfs 不支持时 fail-closed；发布后异常保留产物，调用方须先核查再重试。未运行生产/native/solver/worker/GPU/queue，未改 registry/ledger/分母，资格信用为 0。Core 总门仍 false；旧 formal source-closure 快照绑定的 core_dataset.py 哈希现已过期，未重写，正式入口继续 fail-closed。详见 [UPDATE-162](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-162.zh-CN.md)。
- 2026-09-26 UPDATE-163：新增 F8 R008 固定 15-case post-run 编排，逐例运行单案例 bridge 后重新取得完整 B/C/D+metric v2 结果，再与 matrix-v5 的 15 组 metric/ref/table bindings 精确交叉绑定；固定分母、不同 output-directory inode、资格 false/zero 及轨迹最终 SHA/inode 复验均 fail-closed。Terra High/high 首轮 REVISE 指出的两个 P2 已修复，same-content inode 原子替换测试关闭最后 P3，最终 follow-up PASS、无 P0–P3。联合回归 52 passed，最终专项 19 passed，py_compile/diff-check 通过。仅合成输入；没有读取生产 bundle/frame 或运行 GenCase/native/solver/worker/GPU/queue，也未写 receipt/registry/ledger/分母。全批非全局事务，失败时保留已发布产物；额外完整 v2 重验证会增加后处理 I/O，尚未用生产数据测量。静态接线不认证 source/runtime，也不改变 F8 readiness/T1/资格信用。详见 [UPDATE-163](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-163.zh-CN.md)。
- 2026-09-26 UPDATE-164：确认 native-integrity proposal v3 已在 UPDATE-44 记为 PASS，v3 首页 pending 字样是历史状态；不改写 v3，新增 additive proposal v4 补充 `SaveFluidOut()` 的 `GetNpfOut()!=0` 条件调用、逐 PART `RunPARTs`/`PartOut`/`Nout`/ID/Motive 精确计数关系，以及 `T_end` 最终 flush/pending-buffer 的完成证据。Terra High/high 只读设计复核 PASS、无 P0–P3；八 gate、15×8、阈值/单位、权限与资格边界完全不变。v4 只冻结未来证据合同；native-state finite、排除事件、wall、overlap 仍 open，当前没有 production attempt 或终端证据。未读取生产 bundle/frame，未运行测试或任何 workload。下一步仅实现 synthetic PartOut/RunPARTs 结构解析，未认证数据仍不得 pass。详见 [UPDATE-164](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-164.zh-CN.md) 与 [proposal v4](lagrangian-fluid-lab/reports/F8-R008-NATIVE-INTEGRITY-SEMANTICS-PROPOSAL-V4-2026-09-26.zh-CN.md)。
- 2026-09-26 UPDATE-165：完成 synthetic-only F8 R008 PartOut/RunPARTs 逐 PART 诊断解析；校验 NpOut 原因和、CPU `Idp` uint32/五数组/Nout、ID 唯一性、Motive histogram、file-list block/Part identity，并对 held FD 做输入哈希/稳定性复核。Terra High/high 首轮指出 Idpd uint64 不属于当前 R008 CPU 路径，已收窄并增加负测；follow-up PASS、无 P0–P3。新专项 16 passed，SAFE BI4/RunPARTs 定向回归 59 passed，native-state/bundle/SAFE decoder 相邻联合套件 146 passed，py_compile/diff-check 通过。旧 source-hash 绑定 SAFE decoder 文件保持不变。解析输出只可能 open/missing，零信用，未认证输入永不形成 gate pass/fail；无生产帧/bundle读取、GenCase/native binary/solver/worker/GPU/queue，也未改 registry/ledger/分母。Core 总账仍 `can_finalize=false`。详见 [UPDATE-165](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-165.zh-CN.md)。
- 2026-09-26 UPDATE-166：只读复核封存的 Core formal source-closure v6；当前 9 文件清单与旧快照不符（`core_strict_json.py` 新增，另 7 文件哈希变化），live closure SHA 为 `857ca65f44562a0ed4614b6635547274da2a9cc7d14a518599e614737b48ceec`。v6 验证按设计 fail-closed，formal release/training/jobs 与 root admission 均保持关闭；另有第三 T1 家族、validation/material 分母及 32000-update resource frontier 未通过。没有覆写 immutable v6 凭据、创建 admission 或启动工作负载。详见 [UPDATE-166](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-166.zh-CN.md)。
- 2026-09-26 UPDATE-167：PartOut 诊断解析器现要求原生 uint64 `CaseNp` 为正，逐块根元数据一致，并核对 `Nout <= CaseNp`、每个 `Idp < CaseNp`；负测拒绝 `Idp == CaseNp`。GPT-6 Luna Max/high 独立只读复核 PASS（限 R008 15 行；动态 InOut/VRes 案例不可套用此初始 CaseNp 界）。专项 18 passed、相邻 SAFE BI4/RunPARTs/native-state/bundle suites 75 passed、py_compile/diff-check 通过。只用 synthetic 输入，诊断仍只能 open/missing，未读生产输入或启动 workload，也未改资格/ledger/分母。详见 [UPDATE-167](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-167.zh-CN.md)。
- 2026-09-26 UPDATE-168：新增待审 F8 R008 native finite inventory 诊断，覆盖 `Pos[d]`/`Vel`/`Rhop` 全粒子浮点值、`Idp` uint32 identity、root/PART 全部浮点 metadata 与 control CSV 七列的逐列 finite 计数；未知帧数组 fail-closed，独立 `PartExtra` 文件仍明确 unresolved。15 个冻结 qualification case 的 T/64 control horizon 最大为 1,497 行；扩大回归暴露并纠正了最初 321 行上限误判。最终专项 34 passed；扩展七文件回归其余 137 项通过、初始唯一失败为该边界测试并由专项修复复验。诊断未接 gate，`native_state_finite` 继续 open，需独立复核及全 bundle/output/source/runtime 绑定才能继续。详见 [UPDATE-168](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-168.zh-CN.md)。
- 2026-09-26 UPDATE-169：加固 finite inventory 的 held-FD 原始字节绑定，移除 caller-supplied `ScanResult` 入口；补齐 state/metadata/control 逐项 dtype、单位、语义、population 与来源 SHA，处理 T/64 下溢和 horizon 数值边界。未知数组负测现在由真实合成 BI4 字节触发，冻结 15 行 control renderer 全覆盖；只读审查 PASS、未报 P0–P3。定向 36 passed，八文件相邻回归 198 passed，py_compile/diff-check 通过。只用 synthetic 输入，未读取生产数据或启动 workload；PartExtra/auxiliary 全输出清点、source/runtime 认证与 evidence/gate 接线仍未完成，资格信用为零。详见 [UPDATE-169](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-169.zh-CN.md)。
- 2026-09-26 UPDATE-170：新增单文件 `JPartExtraBi4` finite 诊断，按 CPU writer 合同检查 8 项 metadata、`FormatVer`、唯一 `Normals` float3 数组及 `UseNormalsFt` 决定的精确 population；held-FD parse/payload scan 均复核原始 identity/SHA。定向回归 49 passed，PartExtra parser/test `py_compile` 与 diff-check 通过。只读代码复核 PASS 但未 attestate Terra High；该解析器不做 bundle membership/closed-world 输出完整性判断，`native_state_finite` 仍 open、资格信用为零。仅 synthetic 输入，未读生产 PartExtra/bundle/HDF5/frame、未运行 workload。详见 [UPDATE-170](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-170.zh-CN.md)。
- 2026-09-26 UPDATE-171：F8 R002 新一轮只读复核仍 `FAIL/closed/credit=0`：`hswl` 缺失由保留 GenCase 日志直接佐证，其余四项是官方模板兼容性差距；控制 CSV 的 705 行有限值/时间轴有效。复核 agent 未 attestate Terra High；没有改写或重试 R001/R002。F3 row30 新鲜 v4 资源预检一次性回执为 `blocked_no_worker_authorized`：load 超 128 CPU、历史 ledger 过期、CPU 上界 911.958 超 896；worker/scheduler 均为 0，HDF5/PREPARED rehash 按阻塞短路。F4 新候选尚不存在，旧 v3 R002 one-shot 不重用，因此该新候选预检授权保留未消费。联合回归 54 passed，v4 回执/锁与代码 SHA 核验通过。详见 [UPDATE-171](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-171.zh-CN.md)。
- 2026-09-26 UPDATE-172：新增只读 B/C 闭合 bundle auxiliary-output 诊断，C receipt 必须精确绑定 B receipt；边界人口从已验证 B cohorts 推导；每个 manifest-bound `PartExtra_####.bi4` 均以 held FD/SHA 校验，并将 `PART_####`/`Cpart`/`Step`/人口/时间与同序号 C 主帧交叉绑定，扫描末尾复验主帧 identity/SHA。C 清单文件逐项归类，`RunPARTs`、`PartOut`、`Part_Head`、`PartInfo`、motion/floating 输出被明确列为已知但尚未 finite-scan，未知文件保留 unclassified；没有 PartExtra 不能推断输出模式关闭，source/output-mode 完整性与 gate 仍 open、credit 0。Terra High/high 配置只读复核的初轮 P1/P2/P3 已修复，follow-up 无 P0–P3；reviewer 不能 attestate Terra 身份，因此不记为 Terra High verdict。项目 `.venv` 下六个相关 suite **117 passed**；仅合成 bundle，未读取生产 bundle/frame/HDF5，也未运行 workload。详见 [UPDATE-172](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-172.zh-CN.md)。
- 2026-09-26 UPDATE-173：将 manifest-bound `RunPARTs.csv`/CPU 单-piece `PartOut` 接入 B/C auxiliary inventory；校验 PartOut `CaseNp` 与 B cohort、逐 PART 原因计数/ID/Motive、RunPARTs 原生 16 位时间文本及同序号 C 帧实际 binary64 时间；有限扫描 PartOut 所有浮点 root metadata 和位置/速度/密度数组。补复验前长度/上限、早拒绝 FD 清理及错时等负测。代码审查提出的 3 项 P2 均已修正，后续只读 follow-up 无新发现；两次审查均无法 attestate GPT‑6 Luna 身份，不记模型 verdict。最终七套回归 **146 passed**。当前仍仅 synthetic，source/output-mode/T_end/final flush 未认证，native-integrity/T1/readiness false、credit 0。下一步静态扫描 Part_Head、PartInfo、MotionRef、FloatInfo 等 writer 格式，仍不得把文件缺失解释为 feature 关闭。详见 [UPDATE-173](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-173.zh-CN.md)。
- 2026-09-26 UPDATE-174：完成 `Part_Head`、`PartInfo[_pNN]`、`PartMotionRef[2]`、`PartFloatInfo[2]` 的有界 writer-schema finite scanner，并接入 manifest-bound B/C auxiliary inventory；覆盖 piece/filecode、PartInfo 可选 metadata、Motion/Float 单条与批量追加、FptCount force-point 数组及 held-FD/SHA 前后复核。Terra High/high 配置首轮发现 list-appended 长流错误共用 64-array cap 的 P2，已按 64 MiB raw/file、bounded items/metadata 和 writer schema 修复；新增长流正测，follow-up 无新具体发现。十套相关回归 **219 passed**，`py_compile`/`git diff --check` 通过。基于绑定 CPU preflight initial XML (`Npiece=1`, uint32 `Idp`) 及官方 `JSph` CPU 调用，不扩展当前 R008 PartOut 到多-piece/`Idpd`；其他 writer overload 不属于冻结执行路径。仅使用合成 bundle/BI4 与既有 initial XML、静态源，未读生产 bundle/frame/HDF5、未启动任何 workload。缺文件仍不说明 mode disabled；source/runtime、output-mode、`T_end` 与 final flush 未认证，`native_integrity_evaluated/T1/readiness=false`、credit 0。详见 [UPDATE-174](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-174.zh-CN.md)。
- 2026-09-26 UPDATE-175：完成旧 F4R 六例绑定下两份 `dp=0.006 m` HDF5 的有界角粒子复核；同一 held FD 先整文件 SHA-256，再只读冻结四 ID 轨迹切片。初始粒子中心偏出连续池箱约 `dp/3`；两背景的四条轨迹均在保存帧 8→9 弦线上穿越左右有限壁面，但生成机制及因果仍未证明。六例离散总质量 spread：center 4.441%、offset 4.994%、合并 4.994%，未缩放质量。按六份 Definition 静态推导 `t_b=0.22469856 s`、`L=1.2 m` scope 上界、`h_p=0.14 m`、`Δt_out=0.02 s`，得到 `T₀=4.34 s`，条件式单次上界 `2T₀=8.68 s`；没有启动延长求解。两套回归 14 passed；复核发现均已修正，但 reviewer 无法 attestate Terra High 身份，不记 Terra High verdict。T1/T2 false、credit 0；supportcap/F3/F8 一次性状态未改变。详见 [UPDATE-175](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-175.zh-CN.md) 与 [F4R 审计报告](lagrangian-fluid-lab/campaigns/core-v1/cfd/f4r-corner-penetration-audit-v2/report.zh-CN.md)。
- 2026-09-26 UPDATE-176：只读复用已绑定的八个细档角点坐标核对 lattice 索引，四角在 center/offset 中均为 `(13/187, 7/60, 8) × dp`，x 边界位于 `13⅓/186⅔ dp`，与 `dp/3` 外偏及官方 Cartesian lattice-node 文档一致。两个 XML 使用 `boxfill=solid`，未显式列 `<lattice>`/`<pointref>`；默认值/文档不足以确定精确节点纳入算法。故初态全局格点相位得到支持，但与后续穿墙的因果、边界生成算法及压力/推进责任仍未证明。未读新 HDF5、未运行 GenCase/solver，F4 CPU canary 授权未消费；T1/T2 false、credit 0。详见 [UPDATE-176](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-176.zh-CN.md)。
- 2026-09-26 UPDATE-177：核对 v5.4 XML 指南：`lattice=1` 每格点一粒子，`full=face+solid`；`boxfill` 区分 solid/face，但未写边界格点 tie-breaking。复用绑定质量计算细档池粒子数约 226,800，恰与最近端点格点范围 `175×54×24` 一致，四个已验证 corner ID 也落在相应外侧 x 节点。由此强烈支持 dp/3 初态外偏来自有效格点人口表示，但仍不是全部点逐点闭合或 GenCase 源码证明，也不证明其导致动态穿墙。无 HDF5 重读/GenCase/solver 执行；F4 canary 未消费，T1/T2 false、credit 0。详见 [UPDATE-177](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-177.zh-CN.md)。
- 2026-09-26 UPDATE-178：核验官方 v5.4 变更记录：`<pointref>` 是依据参考位置和 `Dp` 拟合的可选项，但没有给出普通 `fillbox/boxfill` 边界纳点细则。本地 v5.4.355 源码展示的是 `JCaseVRes` buffer-zone 子域拟合：`CalcRoundPos` 按参考点/间距舍入并向外扩域；该路径不能外推为 F4R 普通 fluid box-fill 算法。GenCase 源码缺席，本轮未运行随附二进制。F4R `pointref=0→dp/2` 仍只是待研究相位，不冻结候选、不消费独立 F4 supportcap canary 授权；未重读 HDF5/运行 workload，T1/T2=false、credit=0。详见 [UPDATE-178](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-178.zh-CN.md)。
- 2026-09-26 UPDATE-179：绑定当前 F8 R008 15 份 qualification Definition SHA 与 pack receipt，重算 `TimeMax/TimeOut`：11 例与名义末 tick binary64 完全相等，另 4 例偏 1 ULP（q=.25 晚、q=.75 早）；receipt 预测 row count 仍均为 `k+1`。CPU 源码显示 dt 不截断到输出/终止时刻，主 PART 仅在跨 `TimePartNext`/minimum-fluid 时保存，`FinishRun` 不强制补末帧；保存模式也未由冻结 XML 固定。故设计输出窗基本相容，但末 tick 跨越、正常结束、最终 native PART 持久性只能由实际运行证据证明。无 Definition 修改、无 solver/worker/GPU/queue/admission，readiness/T1/资格 credit 不变。详见 [UPDATE-179](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-179.zh-CN.md)。
- 2026-09-26 UPDATE-180：对 F4 supportcap 证据表做静态对照：R001 的 512/512 unknown 与全部支持距离超 0.03 m 和 t=0 种子错配到 native frame 40 相符；R002 已在同一 v3 中定义 0→40 推进后评估 40→41，但其 v3 CPU/native preflight one-shot 已消费且 tracer/canary 未启动。合成 held-out 结果不含 native R002 成效，故目前没有证据支持一个实质不同的新算法候选；不通过改名、改 cap 或改 gate 消耗新候选预检授权。该授权保留，T1/T2=false、credit=0。详见 [UPDATE-180](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-180.zh-CN.md)。
- 2026-09-26 UPDATE-181：在隔离目录用捆绑 GenCase v5.4.354.01 对 F4R pool-only `drawbox/solid` 合成输入做四组格点相位探针。默认省略 `<pointref>` 与显式零相位 VTK 字节相同，均精确产生 `175×54×24=226800` 点并复现细档池计数；统一 `0.5dp` 相位产生 239,250 点且 Y/Z 越界、未缩放质量增 5.4894%。细档 axis-wise reference `(0.5,0.75,0.75)dp` 产生 225,504 点且全部点位于池盒内，质量降 0.5714%；该值仅为单格档探针，不冻结候选。三档 `1e-4` normalized-phase 扫描未找到各轴共同内收相位；完整六例 population/质量矩阵与 solver 因果仍开放。仅 GenCase、未读 production HDF5/运行 solver，T1/T2=false、credit=0。详见 [UPDATE-181](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-181.zh-CN.md) 与 [机器回执](lagrangian-fluid-lab/campaigns/core-v1/cfd/f4r-gencase-lattice-probe-v1/receipt.json)。
- 2026-09-26 UPDATE-182：完成 F4R center/offset × 三档分辨率六例 GenCase-only 相位矩阵；基线 `.bi4` 与旧矩阵逐字节一致。全局 `<pointref>` 候选使池体粒子中心落入连续池盒，且六例离散流体质量均更接近 52.416 kg 连续目标，但同时改变液滴质心、人口及壁面人口，中档流体质量仍约低 6.4%，故不冻结候选、不启动 solver。详见 [UPDATE-182](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-182.zh-CN.md) 与 [campaign 报告/回执](lagrangian-fluid-lab/campaigns/core-v1/cfd/f4r-pointref-phase-matrix-v1/report.zh-CN.md)。
- 2026-09-26 UPDATE-183：核对官方模板、变更记录与预处理说明后，判断有文档依据的 `<pointref>` 位于全局 geometry definition，未发现 per-drawbox phase 接口；这是基于公开接口的推断，不是对闭源 parser 的证明。因此 UPDATE-182 只能作为全局初态格点相位诊断，不能称为 pool-only 修复或穿墙因果证据。F4 旧穿墙因果和完整 `T₀=4.34 s` 窗口仍未闭合，T1/T2=false、credit=0。详见 [UPDATE-183](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-183.zh-CN.md)。
- 2026-09-26 UPDATE-184：修复逻辑 `test` split 对新 scope held-out 分母的漏选：评测现在合并 `test/id_test/ood_test`，正式分母按每族完整12例计，回执保留原始 split 标签，validation 与 checkpoint 选择不变。新 CLI 回归及 training-contract 相关测试 12 项通过；邻接全套先前 101 passed，唯一两项旧 v1 训练计划收据断言因源码哈希过期失败，已改为验证其仍 fail-closed、零训练授权/信用，旧收据未覆写。未运行训练/solver/worker/GPU/queue。Core 的真实评测、训练和资格缺口仍在。详见 [UPDATE-184](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-184.zh-CN.md)。
- 2026-09-26 UPDATE-185：新增 F3 model-material v2 流式 HDF5 trace 与 hash-chained 行级恢复；Terra High/high 初审发现的传递依赖绑定 P1 已修复，现绑定数据 reader、State contract、墙面/邻居支持依赖路径与 SHA 及 SciPy 版本；follow-up 无 actionable finding。v1 合成科学摘要与连续/恢复 dataset parity、来源/参数/依赖不匹配、前缀损坏及尾部恢复等专项 **7 passed**，`py_compile`/diff-check 通过。输出仍为诊断、资格声明 none；不承诺 HDF5 任意断电损坏恢复。未运行真实 F3 数据、solver/worker/GPU/queue/profile/training；T2 和全局 Core 缺口未改变。详见 [UPDATE-185](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-185.zh-CN.md)。
- 2026-09-26 UPDATE-186：新增 F4 Tallwall120 配对诊断比较器 v2，固定活动 case/scope/revision/recipe，校验外部 source SHA、generation/checkpoint、coverage 与 frame/cadence 可达性；逐 tracer canonical record 重算 all-initial-mass unknown、contact/upward/return/residence CDF 全 change points 及驻留均值区间，并要求 unknown tracer 有首次不可靠时刻、其后的事件不可冒充已观测。manifest 绑定 generation/checkpoint/trace digest，summary 绑定完整 digest envelope 与 manifest；但 API 无法认证调用方外部 digest 的独立来源，故不得接入 admission/qualification，仍严格 diagnostic-only。明确 `T=4.34 s` 为归一化基准，单次 `8.68 s` 扩窗与 `0.3497487083913345 s` return follow 分离；CDF `0.02`、驻留 `0.0868 s`、event MAE `0.01085 s`、检测预算 `0.00217 s` 均为待科学审定的提案值，不继承 F3 gate，状态 `proposed_not_registered`、无资格权威。Terra High/high subagent 只读静态审查为诊断范围内 PASS、无 P0/P1；external digest 来源认证保留为明确 P2 边界，冻结绑定下 tracer/CDF/residence 篡改及 coverage digest 负测覆盖。新专项 **25 passed**；与 10 个相邻 F4/material/admission/collector/sidecar suites 合计 **131 passed**；`py_compile`/diff-check 通过。只用合成 JSON，未读真实 source/HDF5、未启动 solver/worker/GPU/queue、未改 registry/ledger/旧回执；尚未接入真实 summary/preflight/matrix/collector。详见 [UPDATE-186](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-186.zh-CN.md)。
- 2026-09-26 UPDATE-187：按新的明确授权消费 F3 material row30 v5 resource/scheduler one-shot preflight。当前无 worker/active jobs，CPU/RAM/disk 条件通过；但历史资源 ledger 过期且累计 CPU 上界 `911.958 > 896`，receipt 为 `blocked_no_worker_authorized`，因此 source/PREPARED rehash 短路，需新的 root resource decision 与单独 worker 授权。v1–v5 preflight 专项 **14 passed**；未启动 worker/solver/GPU/queue，也未改 ledger/registry/T2。并对封存 F8 R002 做只读静态复核：文件 SHA 与既有 v3 receipt 一致，保留 GenCase log 证明 Definition 缺 `<hswl>` 后退出码 1；其他四个官方模板字段差异只记为静态兼容缺口，CSV 合同有效但未证明曾被加载。R002 维持 closed/no retry/credit=0。新请求的 reviewer 未 attestate 实际 Terra 身份，不声称 Terra High verdict；未改或重试 R001/R002。详见 [UPDATE-187](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-187.zh-CN.md) 与 [F3 v5 不可变回执](lagrangian-fluid-lab/campaigns/core-v1/material/evidence/f3-material-row30-resource-preflight-v5/receipt.json)。
- 2026-09-26 UPDATE-188：新增 F4 array-only 局部仿射 predictor v4 候选，仍固定 k=32、Shepard 几何权重、支持距离及全部 gate；5,632 个解析场 query 上 gate 判定与 v3 完全一致且真值误差均低于冻结上限，但 shear 更准、Gaussian 界面更差，故仅 proposal、未接入 tracer。按用户授权执行的一次 CPU/native 预检因 1 分钟负载 `173.876 > 128` deferred；18 项静态绑定、专项 15 tests 通过。one-shot 已消费且不可重试；receipt 未打开 HDF5，但绑定准备阶段曾只读 `sha256sum` 流过完整源文件，未用 h5py 读取帧。未运行候选/tracer/canary/solver/GPU/worker，T1/T2=false、credit=0。详见 [UPDATE-188](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-188.zh-CN.md) 与 [预检回执](lagrangian-fluid-lab/campaigns/core-v1/material/candidates/f4-supportcap-local-affine-reconstruction-v4/cpu-native-preflight-v1/preflight-receipt.json)。
- 2026-09-26 UPDATE-189：修复 F3 model-material v2 在 RK4 前序 stage 失败、k4 恢复可靠时仍记录 `reliable` 的诊断错误；逐 seed 保留最早失败 stage，trace row 读取同一状态原因，非有限 candidate 另行标记。RK4 stage、candidate/位置更新、事件、永久 unknown 和 denominator 语义不变，temporal-v3/v1 与历史收据保持原样。四个相邻 suite **23 passed**，其中新增完整合成 trace 写入验证；`py_compile`/`git diff --check` 通过。仅合成输入、零资格信用；阶段性能剖析与真实材料运行仍未完成。详见 [UPDATE-189](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-189.zh-CN.md)。
- 2026-09-26 UPDATE-190：明确并合成验证 F3 model-material v2 的保守闭壁/RK-stage 边界：任何 stage 失败均不修补位置或猜测反射，而是冻结该步并永久删失；后续 stage 恢复也不复活，质量仍保留在全量 unknown 分母。k1 `wall_occluded`、k4 恢复、下一 interval 全 stage 恢复的端到端回归 **1 passed**，确认两帧仍 unknown、首次原因保留、分母不缩小。受当前 load `241.94 > 128 CPUs` 限制，未重跑完整四套回归；此前实现版完整回归 23 passed。本边界仅适用于诊断性 v2，不证明 native 闭壁物理准确性；v1/v3 不变。阶段性能 profiling、真实材料运行和全局 Core 目标仍未完成。详见 [UPDATE-190](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-190.zh-CN.md)。
- 2026-09-26 UPDATE-191：新增 v2 synthetic-only 阶段 profiler，测量 provider 初始化/field、MLS、RK4、hash-chained HDF5 append、recovery、summary 与 SHA-256；默认 512×4096×20，固定合成上限、无 source-path 参数，临时输入/trace 自动清理，load 超 process-visible CPUs 或 load 不可读时均 fail-closed。专项 **4 passed**，覆盖 load gate、模型/reference provider、小型 trace 计时闭合及 CLI 拒绝路径；`py_compile`/diff-check 通过。默认运行实测于 1 分钟 load `172.387 > 128` 时在生成临时 HDF5 前 deferred，故真实规模 synthetic profile 仍未执行，本更新不提供 v2 性能数字或资源上界。详见 [UPDATE-191](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-191.zh-CN.md)。
- 2026-09-26 UPDATE-192：补齐 v2 synthetic profiler 的 source/trace 实际文件字节数，和 SHA-256 一同记录；在临时目录清理前取值。4 seeds × 64 particles × 1 interval 的合成 profile 回归验证输出均为正整数，专项 **4 passed**，`py_compile`/`git diff --check` 通过。该微型 fixture 不能推算默认 512×4096×20 的性能或输出大小；默认 profile、生产全时域性能、独立进程 kill/resume parity 与材料资格仍未完成。详见 [UPDATE-192](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-192.zh-CN.md)。
- 2026-09-26 UPDATE-193：补上 F3 model-material v2 独立进程 kill/resume parity 测试：子 Python 进程在首个 RK 子步行、checkpoint、hash-chain 和 `committed_rows` 提交后由父进程 SIGKILL；新 Python 进程恢复后，所有 HDF5 数据集/journal 与连续 synthetic trace 逐项相同。完整 v2 合成套件 **11 passed**。只证明系统仍运行且 HDF5 文件可读时的已提交行边界恢复，不覆盖断电/内核崩溃/存储缓存丢失/元数据损坏；未使用生产数据或启动 workload，T2/资格不变。详见 [UPDATE-193](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-193.zh-CN.md)。
- 2026-09-26 UPDATE-194：补齐计划中的全图/分块 two-hop halo 训练等价检查：在 `graph_raw` 与 `graph_residual` 上，比较同一完整字段、非连续抽样 loss centers 的全中心前向与分块 halo 前向，预测、MSE 及所有模型参数梯度均在固定容差内一致。完整 `test_core_models.py` **15 passed**，`py_compile`/diff-check 通过。只验证小型 CPU 合成 batch，不代替正式训练/训练恢复或规模化资源测量；9 次正式训练及 Core 其他资格/评测交付仍未完成。详见 [UPDATE-194](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-194.zh-CN.md)。
- 2026-09-26 UPDATE-195：按计划复核评测固定失败分母，NaN/提前发散、两类 timeout、缺帧尾部及 setup failure 的 7 个定向回归通过；无重复代码改动。加强 Core 独立进程 SIGKILL 后训练恢复测试：在同一 validation fixture 上比较连续与恢复训练的模型、optimizer、sampler、归一化、Python/NumPy/Torch RNG、validation/history；定向恢复用例 **2 passed**。锁定 Python 3.12 CPU 环境、CUDA disabled。只证明可读原子 checkpoint 后的进程恢复，不覆盖断电/内核崩溃，也不替代正式 32k 训练或 9 次运行。详见 [UPDATE-195](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-195.zh-CN.md)。
- 2026-09-26 UPDATE-196：只读刷新 `core_campaign.py status`：`can_finalize=false`、T1 2/3、macro T2 0/2、训练 0/9，T1 目标缺 432、材料缺 288；因果/证据结构有效，`issues=[]`。独立全产品复现为 false：已登记跨机 receipt 是 diagnostic-only；另一份 835-transition 单案例比较未证明可搬运全产品链及绑定 root review。runtime scheduler 无 live/queued job。未写 completion snapshot、未运行 workload、未改 registry/ledger。详见 [UPDATE-196](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-196.zh-CN.md)。
- 2026-09-26 UPDATE-197：定位并修复 arXiv 批量 API 请求的 HTTP 406：同一批量查询在 `urllib` 未带 `Accept` 时返回 406，带 `Accept: */*` 时返回 200；仅对 arXiv 请求增加该 header。离线文献核验测试 7 passed；不可覆盖 RERUN12 保留修复前结果，RERUN13 按原三源规则得到 2 verified、0 unverified、4 pending。Semantic Scholar 六项仍 HTTP 429，三个无 DOI 候选缺第二独立匹配，故本机目标仍未闭环；未放宽验证标准或升格人工来源。详见 [UPDATE-197](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-197.zh-CN.md)。
- 2026-09-26 UPDATE-198：为不改变“至少两目录精确匹配且无冲突”门槛，给机器核验器增加 OpenAlex DOI 精确查询作为第四个目录；新增 10 项离线测试。RERUN14 按冻结的六条候选记录得到 6 verified、0 unverified、0 pending，S2 在本次也对五篇 arXiv 文献成功响应。详见 [UPDATE-198](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-198.zh-CN.md) 与 [文献来源审计更新](lagrangian-fluid-lab/reports/PLAN-REFERENCES-AUDIT-2026-09-24.zh-CN.md)。
- 2026-09-26 UPDATE-199：现有 portable-bundle suite 首轮发现 3 个 standalone reader/reproducer import failure：新 `core_dataset.py` 依赖的 `core_fsverity.py` 与 `core_strict_json.py` 未纳入旧 bundle 代码闭包。builder 已升为 `core.reader_bundle.v2`，复制并完整登记这两个依赖，verifier 对构建器代码清单要求全闭合；`core_benchmark` reproduction code hash closure 也纳入 helper。新 v2 synthetic bundle package suite 21 passed，benchmark/independent-reproduction/campaign gate 相邻测试 55 passed，fullfield/halo oracle suites 6 passed；旧 v1 与实际历史 bundles 保持未改，且不能由新 verifier 冒充为 v2。此项修复只闭合开发包 standalone portability，不等于三家族完整产品异机复现或 Core 完成。详见 [UPDATE-199](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-199.zh-CN.md)。
- 2026-09-26 UPDATE-200：按锁定 DualSPHysics v5.4 writer 源码静态核对 F8 R008 辅助输出条件，并绑定既有 CPU preflight XML：`CaseNmoving=0`、`CaseNfloat=0`，因此一致的 C run 不会创建 `PartMotionRef*`/`PartFloatInfo*`；冻结 15 份 Definition 均为 `Boundary=2`（mDBC），将 `PartExtra` 未决条件收窄为 `SvExtraParts`/精确 argv。`Part_Head`、`PartInfo`、`RunPARTs`、`PartOut` 仍依赖实际保存模式/执行事件。精确 solver argv、output mode、终止与输出树仍需一次获准真实执行证明。只读源码静态审计，无 GenCase/native/solver/worker/GPU/queue、无 registry/ledger/receipt 写入；T1/readiness/credit 不变。详见 [UPDATE-200](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-200.zh-CN.md)。
- 2026-09-26 UPDATE-201：将 UPDATE-200 的 DualSPHysics v5.4 CPU writer 条件接入 F8 R008 auxiliary inventory：held-root 安全读取并 SHA-256 锁定五份输出 writer；根据 B 已验证 moving/floating cohorts 与 C 非空 BI4 frame axis 拒绝零群体下不可能的 `PartMotionRef*`/`PartFloatInfo*`，非零群体则要求 main file，extra stream 仍不作配置推断。auxiliary suite 30 passed，相邻 Head/Info、Motion/Float、PartExtra、RunPARTs/PartOut suites 82 passed，`py_compile`/diff-check 通过。仅临时合成 bundle；无生产读取或 GenCase/native/solver/worker/GPU/queue。总控仍 `can_finalize=false`、T1 2/3、macro T2 0/2、训练 0/9、T1 target 缺 432、material target 缺 288、独立复现 false。可信执行来源、实际 argv/output tree 与真实 15-case solver 证据未闭合，qualification/readiness/credit 不变。详见 [UPDATE-201](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-201.zh-CN.md)。
- 2026-09-26 UPDATE-202：完成授权的 F8 R002 新静态复核，新增不可变 v4 receipt，仍因 `hswl` 缺失及历史 GenCase 明确失败而 FAIL/closed；其余四字段只记模板兼容差距，CSV 结构通过，R001/R002 均未改写或重试。F3 row30 新鲜 v6 资源/调度 one-shot 预检绑定 v5 历史，因 load `245.712 > 128`、账本过期及 CPU 上界 `911.958 > 896` 得 `blocked_no_worker_authorized`；source/PREPARED 重哈希短路，无 worker/queue/solver/GPU。F4 新候选 v4 的 CPU/native canary preflight one-shot 已在 UPDATE-188 消费并因 load `173.876 > 128` deferred；同 scope retry 禁止，本轮不重试。R002+F3 v6 专项 7 passed，`py_compile`/diff-check 通过；无资格信用或 runtime 授权。详见 [UPDATE-202](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-202.zh-CN.md)。
- 2026-09-26 UPDATE-203：GPT-6 Luna Max 对 F8 R008 native-integrity semantics proposal v4 只读审查为 `REVISE`：发现全零 exclusion `defined_pass` 超出冻结 registry v1 outcome domain、`T_end` 使用未定义 PART 容差且缺少最后成功 `SaveData`/flush 的精确证明、以及当前 bounded PartOut parser 不支持 GPU/multi-piece。新增 additive proposal v5：全零仍只能 `open/missing`；运行完成须由实际 timestep 跨越、有效 horizon、无 early-stop、末次 SaveData 与清空 PartsOut 的可信轨迹证明；当前 parser scope 限为 CPU 单 piece，GPU/multi-piece 保持 open/missing。v5 待 GPT-6 Luna Max 只读复核，未改 registry/scope/分母或实现；四个现有 synthetic diagnostic suites 78 passed（不验证生产执行或 v5 文档）。无生产数据、GenCase/native/solver/worker/GPU/queue，T1/readiness/credit 不变。详见 [UPDATE-203](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-203.zh-CN.md) 与 [proposal v5](lagrangian-fluid-lab/reports/F8-R008-NATIVE-INTEGRITY-SEMANTICS-PROPOSAL-V5-2026-09-26.zh-CN.md)。
- 2026-09-26 UPDATE-204：完成 v5 一轮只读源码/合同技术审阅，内容结论 `PASS`、无 P0–P2；审阅未 attestate 模型身份，不记为 GPT-6 Luna Max/Terra High 正式签核。仅留 P3：runtime trace 可采集格式与执行身份认证尚未冻结；其未审完前不得将轨迹接入 gate。只读刷新 Core 总控仍 `can_finalize=false`、`issues=[]`、T1 家族 F3/F4、宏观 T2 0/2、训练 0/9、目标分母缺 T1 432/材料 288。未读生产数据或运行 workload，未更改 scope/registry/分母/信用。详见 [UPDATE-204](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-204.zh-CN.md)。
- 2026-09-26 UPDATE-205：为 v5 留下的 runtime trace-format P3 完成 CPU v5.4 源码探索，提出通过 `RunPARTs.Steps` telescoping sum、终端日志 `Nstep`、同末帧 BI4 `Step/TimeStep`、正常退出与可信 supervisor 状态证明最后一次 `SaveData()` 确在最后已应用 timestep，并由其后源码路径清空 `PartsOut`。新增 CPU 单-piece terminal completion/flush evidence contract v1，待只读复核；它不添加 gate、不认证普通文件、不改变全零 `open/missing` 限制。无生产数据/测试/workload、无 solver/registry/分母/资格更改。详见 [UPDATE-205](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-205.zh-CN.md) 和 [证据合同](lagrangian-fluid-lab/reports/F8-R008-TERMINAL-COMPLETION-EVIDENCE-CONTRACT-V1-2026-09-26.zh-CN.md)。
- 2026-09-26 UPDATE-206：terminal completion evidence v1 只读审查为 `REVISE`（审阅者未 attestate 模型身份）：P1 指出 `PARTBEGIN:12:0:<dir>` 可在 `PartIni=0/TimeStepIni=0` 时加载 restart；P2 要求冻结 receipt exact fields/types、canonical/signature bytes 与 `RealStr(16)` 文本映射；P3 要求区分 post-exit 文件可见性与掉电 durability。新增 additive v2，绑定实际 frozen initial source、禁止 restart/append、定义 wire schema/canonical JSON/Ed25519 domain/payload、精确时间文本规则，并明确不承诺 fsync/durability；待新一轮只读复核。无测试、生产数据或 workload；无 solver/scope/registry/分母/资格更改。详见 [UPDATE-206](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-206.zh-CN.md) 与 [证据合同 v2](lagrangian-fluid-lab/reports/F8-R008-TERMINAL-COMPLETION-EVIDENCE-CONTRACT-V2-2026-09-26.zh-CN.md)。
- 2026-09-26 UPDATE-207：F8 terminal completion evidence v2 经 Terra High 配置只读复核为 `REVISE`（reviewer 未 attestate 模型身份）：指出 OPT/argv 未机械绑定实际 Definition/control/initial-state 打开、`TMAX:0` 覆盖语义与 C-locale atof、运行时 locale 与 source/dependency/output/supervisor pins。新增 additive v3，禁用 OPT、要求 syscall input trace、精确定义有效 TMAX/argv profile、运行环境与依赖 pins。v3 为 proposal-only，缺少 trust/supervisor/trace/build/output 工件及 verifier；无测试/生产数据/workload/权限或资格变化。详见 [UPDATE-207](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-207.zh-CN.md)。
- 2026-09-26 UPDATE-208：按授权消费 F3 material row30 全新 v7 资源/调度 one-shot 预检，结果 `blocked_no_worker_authorized`：当前 1-min load `276.693 > 128`、历史 ledger 过期且 CPU 上界 `911.958 > 896`；无 worker/job。源 HDF5/PREPARED 哈希按阻塞短路，无 HDF5 打开/重哈希、worker/solver/GPU/queue 或 registry/ledger/T2 写入。v7 专项 3 passed，py_compile/diff-check 通过。详见 [UPDATE-208](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-208.zh-CN.md)。
- 2026-09-26 UPDATE-209：F8 terminal completion evidence v3/v4 经只读复核分别为 `REVISE`，发现正时长/自动 `DsphConfig.xml`/退出后写竞态/trust bootstrap、registry 自身 hash 循环、output seal wire schema、locale schema 与 BI4 profile 缺口；新增 additive v4/v5 proposal，v5 当前待有效独立复审。F4 新 proposal-only blend v5 在 5,632 个 analytic-array queries 上保持 gate decisions 全 pass，但 quintic shear RMSE `0.0004431404 m/s`、Gaussian interface `0.0048028608 m/s`，后者仍较 v3 基线高 `69.64%`；故不进入 CPU/native 预检，本次一次预检授权未消费。F4 专项 4 passed；无生产/native/solver/worker/GPU/queue/registry/ledger，T1/T2/credit 不变。详见 [UPDATE-209](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-209.zh-CN.md)。
- 2026-09-26 UPDATE-210：F8 terminal completion evidence v5 独立复审为 `REVISE`；新增 additive v6 固定外部 task policy/registry snapshot、补充签名 seal/kernel observations、locale ABI 与小端/SI64=0 BI4 grammar，并修正 BoundNor 属于独立 PartExtra。详见 [UPDATE-210](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-210.zh-CN.md)。
- 2026-09-26 UPDATE-211：Terra High 配置对 V6 只读复审为 `REVISE`、无 P0；指出 seal 后 verifier 只读访问规则矛盾、process-group/cgroup/mount_setattr 缺原始绑定、loader/进程创建覆盖不闭合、DsphConfig runtime_config role 与 absent proof 缺失、BI4 producer probe 未绑定每个实际文件首次 header write。新增 additive V7 proposal，等待新一轮独立只读复核；仍不授权 F8 solver/worker/GPU/queue，也不改 gate/registry/ledger/qualification。F4 v5 interface synthetic RMSE 较 v3 高 69.64%，不进入 CPU/native preflight，预检一次性授权未消费。详见 [UPDATE-211](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-211.zh-CN.md) 与 [合同 v7](lagrangian-fluid-lab/reports/F8-R008-TERMINAL-COMPLETION-EVIDENCE-CONTRACT-V7-2026-09-26.zh-CN.md)。
- 2026-09-26 UPDATE-212：Terra High 配置对 V7 只读复核为 `REVISE`、无 P0，确认 seal 后只读/hash 与授权边界正确，仍缺闭合 syscall/fanotify event wire schema、runtime_guard/process-group nested schema、BI4 source logical-vs-kernel write 绑定，以及实际 ProgramPath 与 endian/callsite 来源。新增 additive V8 proposal 逐项修订；依据 Linux man-pages 将 permission 与 FID/name monitoring 拆成兼容的两个 fanotify groups，等待独立复核。另作仅 synthetic 的 F4 regularization 诊断：5 个 q × 两场共 14,080 queries 上，0.00025m predictor 权重试探两场 RMSE 低于 v3；因参数已由原 calibration corpus 探索选出且无独立外验证，不登记候选、不消费 CPU/native preflight one-shot。无生产/native/tracer/solver/worker/GPU/queue、registry/ledger 或资格改动。详见 [UPDATE-212](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-212.zh-CN.md) 和 [合同 v8](lagrangian-fluid-lab/reports/F8-R008-TERMINAL-COMPLETION-EVIDENCE-CONTRACT-V8-2026-09-26.zh-CN.md)。
- 2026-09-26 UPDATE-213：A8 portability/diagnostic gate 修复后，Core benchmark/package/campaign suites 78 passed；F4 v6 synthetic suite 4 passed，但 candidate gate 重算有 3,680 个回归，保持 `not_justified`，未消费一次性 CPU/native canary 预检授权。只读总控 `can_finalize=false`、T1 缺 432、材料缺 288、正式训练缺 9，未写 registry/ledger。F8 V13–V16 经 Terra High 配置只读复核均为 `REVISE`、无 P0；V16 复核发现 mount/FID mask 冲突、launcher pre-exec/tracer handshake 缺失、final-fput observer 未实现，并指出 `cgroup_empty` causal-ref 与 event schema 归属问题。V17 proposal-only 修订为封闭目录树逐目录 inode marks、pinned trampoline + `PTRACE_TRACEME`/`PTRACE_O_TRACEEXEC`、显式 child writer-close + parent-only authorization gate、typed `cgroup_empty`、current-vs-historical fanotify schema 与 observer-row contract。V17 定点 Terra High 配置复核由首轮 `REVISE` 修正后为 **focused static PASS**（reviewer 身份未 attestate；不代表实现或运行时通过）。固定内核 conformance、FID filesystem/permission capability、完整 syscall policy、trusted supervisor、fanotify responder 与 final-fput observer 均仍未实现/验证，runtime-readiness=false。未启动 GenCase/native/solver/worker/GPU/queue、未做 root/sudo 或 host capability/filesystem probe。详见 [UPDATE-213](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-213.zh-CN.md)、[合同 v14](lagrangian-fluid-lab/reports/F8-R008-TERMINAL-COMPLETION-EVIDENCE-CONTRACT-V14-2026-09-26.zh-CN.md)、[合同 v15](lagrangian-fluid-lab/reports/F8-R008-TERMINAL-COMPLETION-EVIDENCE-CONTRACT-V15-2026-09-26.zh-CN.md)、[合同 v16](lagrangian-fluid-lab/reports/F8-R008-TERMINAL-COMPLETION-EVIDENCE-CONTRACT-V16-2026-09-26.zh-CN.md) 与 [合同 v17](lagrangian-fluid-lab/reports/F8-R008-TERMINAL-COMPLETION-EVIDENCE-CONTRACT-V17-2026-09-26.zh-CN.md)。
- 2026-09-26 UPDATE-215：F4 v6 合成校准总体 RMSE 较同域 v3 略降，但 gate 有 3,680/14,080 regressions（26.14%），且参数来自已检查 analytic corpus、无独立验证；回归覆盖两场、五个 q，destination/interface/source 分别 50.00%/16.67%/9.375%。v6 保持 `not_justified`，不消费 F4 一次性 CPU/native canary 预检；v4/v5 的旧域 gate pass 同样不能替代独立验证。F3 默认 v2 synthetic profile 受实时 load gate 拒绝（134.278 > 128，`profile_started=false`），未生成临时数据或性能数字。无代码/资格/分母/credit 改动；详见 [UPDATE-215](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-215.zh-CN.md)。
- 2026-09-26 UPDATE-216：F4 v5 最终 prospective synthetic holdout v2-review1 先冻结再评分；q=`0.05,0.975` 经绑定的历史 calibration/candidate/旧未评分设计记录审计无重叠。复核意见指出的 `.95` 复用及 truth-error 标签歧义均已修正。负载 gate 通过时仅运行 2,816 个 CPU analytic-array queries：v5 对新制造盒域场的 truth-vector RMSE 较 v3 低 53.93%；gate/support 完全一致，2,816/2,816 pass，source unknown 0%，固定 synthetic screen 条件全通过。此项不是外部/物理验证或优越性证据，资格零信用；最终 revision 尚无 Terra High 复审，因此未启动一次性 CPU/native preflight。未启动 native/tracer/solver/GPU/worker/queue，未写 registry/ledger；运行后 load 回升 135.11，停止额外负载任务。详见 [UPDATE-216](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-216.zh-CN.md)。
- 2026-09-26 UPDATE-217：Terra High（配置 `gpt-5.6-terra`/high）对 F4 v5 最终设计、评分脚本、测试、回执及 UPDATE-216 只读复核，无 P0–P2；确认 19 项代码/审计来源摘要、q 域 audit、盒模态数学性质、screen 语义与 synthetic-only 边界一致。reviewer 身份无法 attestation。仅留 P3：脚本重复定义两个相同的设计验证 helper；为保持已评分 receipt 与冻结代码 hash 一致，本轮不清理。此复核不授权执行；尚需核对 v5 candidate-specific preflight 合同与实时资源门。无测试、holdout 或 workload 重跑。详见 [UPDATE-217](lagrangian-fluid-lab/reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-217.zh-CN.md)。
