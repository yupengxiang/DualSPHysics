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
| 评测与产品 | 协议、审计、manifest、若干打包脚本 | 模型更新语义不统一、路径不便携、完成判据过弱 |

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
- 本轮完成调研和计划；下一轮按 W0 启动并行实施，后续波次由总控根据依赖自动推进。
