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

截至 2026-09-24，六项依据已按出版方论文页、arXiv 作者记录或官方项目页逐条人工复核；补充目录交叉核对及书目与主张审计见[文献来源审计](lagrangian-fluid-lab/reports/PLAN-REFERENCES-AUDIT-2026-09-24.zh-CN.md)。三源工具已验证 LagrangeBench 与 FD-Bench；FuelTank 的机器核验仍只有一个目录确认，另三篇因 arXiv API 406 待核，故六项自动核验尚未整体完成。执行回执见[首次记录](lagrangian-fluid-lab/reports/PLAN-REFERENCES-VERIFICATION-2026-09-24.json)、[第二次记录](lagrangian-fluid-lab/reports/PLAN-REFERENCES-VERIFICATION-2026-09-24-RERUN1.json)、[第三次记录](lagrangian-fluid-lab/reports/PLAN-REFERENCES-VERIFICATION-2026-09-24-RERUN2.json)、[第四次记录](lagrangian-fluid-lab/reports/PLAN-REFERENCES-VERIFICATION-2026-09-24-RERUN3.json)、[第五次记录](lagrangian-fluid-lab/reports/PLAN-REFERENCES-VERIFICATION-2026-09-24-RERUN4.json)、[第六次记录](lagrangian-fluid-lab/reports/PLAN-REFERENCES-VERIFICATION-2026-09-24-RERUN5.json)和[第七次记录](lagrangian-fluid-lab/reports/PLAN-REFERENCES-VERIFICATION-2026-09-24-RERUN6.json)。第七次仍为 2 项 `verified`、1 项 `unverified`、3 项 `verify_pending`；五个 arXiv ID 查询仍返回 HTTP 406，FluidLab 的 Crossref 请求另遇临时 TLS EOF，自动核验尚未整体通过。该会话已按规则保留机器状态，不能由人工网页核对升格。

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
- 2026-09-24：readiness audit v4 `campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/t1-execution-readiness-audit-v4/receipt.json` 是当前有效的不可变审计收据；其实现与测试哈希均匹配，`verify_audit()` 复算通过。它将 v3 六个语义 gap 映射到已审 proposal 字段、实现函数和测试；几何/端点、profile、Uref、横向 RMS 的 case-specific Uref 归一化与 0.05 门限、cycle flux/seam、跨分辨率插值均闭合，并以非零横向信号回归测试验证 RMS 比率门控；Terra High 同一审查线程的针对性 follow-up 结论为 `PASS`。adapter/review/audit 定向测试 31 项通过。仍有两项阻塞：per-case provenance verifier 未独立审查、正式 15-case T1 结果未生成；`readiness_pass=false`、零信用、无执行权限。本次推进未重新运行 GenCase/solver/worker/GPU/队列。
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
