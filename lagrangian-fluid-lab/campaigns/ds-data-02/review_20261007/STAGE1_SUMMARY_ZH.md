# DS-DATA-02 首阶段总结与外部审阅材料

报告日期：2026-10-07（America/Los_Angeles）；机器记录使用 UTC。科学成果冻结点：checkpoint 335，提交 `fab8dd3b3ac28ef5e21efea9cc3f04afa7f116ee`。报告整理与推送不会重置资源计数，也未启动新的模拟。

## 1. 当前结论与任务边界

七个家族各 48 个独立物理案例，共 **336 例**，已完成更新后首阶段目标：真实三维运行、覆盖主要事件的完整原生时域、全帧状态转换、动态 ParaView 入口、既有视觉验收、实际输入和产物溯源。最终集合包含真实冻结的前 8 例与前 24 例；它们不追加计数。正式状态统一为 **“视觉检查通过、数值精度未验收”**。

**DS-DATA-02 当前新增数值参考验收与外部验证信用均为零（Q-N=0，Q-E=0）。** 首阶段完成不等于原始完整研究蓝图完成，不等于训练就绪的精确标签数据集，不等于数值参数域已获资格。转换报告中的 `q_i_status` 仍为 `not_granted; conversion evidence only`；个别正式 Q-I 产物有自己的收据，不能把转换成功泛化为所有阶段、所有变量的共同认证。

最初方案希望同时补齐两种机制背景、空间/时间误差预算、输运标签、划分与无模型评测。后续用户明确把当前目标改为先形成七族 8/24/48 批次的视觉可用集合，再进入精度与标签阶段。附件中的初始方案、历史工单、早期 `FAMILY_HANDOFF.md` 与旧目录计划是背景和历史记录，不覆盖当前 [已采纳 GOAL](evidence/E00016/GOAL_ZH.md)。它们中的“pending”“尚无产品”或最初两背景配置不能直接解释为当前状态。

证据入口：[最终 336 例交付索引](evidence/E00002/DS-DATA-02-STAGE1-FINAL-DELIVERY-INDEX.json)、[八项要求终审](evidence/E00004/STAGE1-FINAL-REQUIREMENT-AUDIT.json)、[checkpoint 335](evidence/E00001/ROOT_LIVE_RESUMPTION_CHECKPOINT_335.json)。本报告以可核查记录为依据，不新增一次个人动画验收或重新生成科学真值。

## 2. 实际交付与七族覆盖

| 家族 | 当前实际机制 | 独立案例 | 原生帧数 | 实际末时刻范围（s） | 粒子身份轴规模 |
|---|---|---:|---|---|---|
| F1 | 溃坝：偏心障碍与双通道 | 48 | 161 / 401 | 1.600022740–4.000211757 | 115,316–152,356 |
| F2 | 倾倒：开放杯沿与偏置接收器 | 48 | 401 | 4.000000910–4.000061898 | 418,104–421,566 |
| F3 | 双轴强迫槽体流动 | 48 | 836 | 8.350000587–8.350017322 | 179,208–179,208 |
| F4 | 液滴落下与撞击 | 48 | 1201 | 1.200002950–1.200129649 | 83,233–83,233 |
| F5 | 紧凑三维波浪爬坡/回流 | 48 | 801 | 16.000005890–16.000169394 | 194,427–194,427 |
| F6 | 浮体角速度释放与自由响应 | 48 | 241 | 12.000000726–12.000164584 | 417,505–417,505 |
| F7 | 浸水移动障碍的平滑转动 | 48 | 601 | 12.000000781–12.000101621 | 70,179–70,179 |

所有案例实际起时刻为 0 s；末时刻保留原生自适应步的实际值，不能用名义 TimeMax 替换或截断。粒子数为最终产品的身份轴规模，含不同原生类型，不能当作每帧活动流体数。F1 两条机制的实际时域不同，表中的帧数/末时刻跨度不代表一个统一的采样周期。

七族覆盖表示每个家族都有 48 例，不表示最初每族两种研究背景都已同样成熟。当前 F2 主要为偏置倾倒，F3 为双轴强迫，F4 为落滴，F5 为紧凑爬坡/回流，F6 为角速度释放，F7 为移动障碍。不能拿早期 Pump、斜碰撞、规则波、堰口等计划代替实际最终案例。后续两背景数值研究应重新核查实际覆盖与需要补充的机制。

每例入口见 [CASES_336.json](CASES_336.json)：真实物理 ID、运行别名、批次成员、帧/时间/身份数、物理输入、原产品行、视觉记录、scope 限制。原始服务器 XMF 地址用于在服务器打开；本审阅包未携带科学 HDF5，因此云端不能直接播放那些服务器绝对路径。

当前主产物的绑定分别来自 F1/F4/F7 root1261、F2 root1444、F3 root1449、F5 root1450、F6 root1353，最终 root1464 把这些实际产物逐例合并。旧恢复副本、相同分辨率视图、复跑、时间切片、预览和派生标签都不构成新增独立物理案例。

## 3. 物理输入与参数范围

| 家族 | 已运行且视觉可用的物理输入范围 | 已知值覆盖 |
|---|---|---|
| F1 | `fluid_depth_m`: 0.11–0.34<br>`initial_fluid_vx_m_s`: 0–0.2 | `fluid_depth_m`: 48/48<br>`initial_fluid_vx_m_s`: 48/48 |
| F2 | `fluid_height_m`: 0.264–0.32<br>`receiver_x_m`: 0.45–0.65<br>`receiver_y_m`: 0.14–0.14<br>`rotation_duration_s`: 0.65–1.2 | `fluid_height_m`: 48/48<br>`receiver_x_m`: 47/48<br>`receiver_y_m`: 47/48<br>`rotation_duration_s`: 47/48 |
| F3 | `forcing_amplitude_x_scale`: 0.8–1.2<br>`transverse_amplitude_m_s2`: 0.25–0.75 | `forcing_amplitude_x_scale`: 48/48<br>`transverse_amplitude_m_s2`: 48/48 |
| F4 | `gap_m`: 0.18–0.26<br>`speed_m_per_s`: 0.4–0.6<br>`x_offset_m`: -0.08–0.08<br>`y_offset_m`: -0.04–0.04 | `gap_m`: 48/48<br>`speed_m_per_s`: 48/48<br>`x_offset_m`: 48/48<br>`y_offset_m`: 48/48 |
| F5 | `amplitude_scale`: 0.8–1.2<br>`time_scale`: 0.8–1.0 | `amplitude_scale`: 48/48<br>`time_scale`: 46/48 |
| F6 | `initial_angular_velocity_x_rad_s`: 0.02–0.195<br>`initial_angular_velocity_y_rad_s`: 0.0225–0.24<br>`initial_angular_velocity_z_rad_s`: 0.015–0.195 | `initial_angular_velocity_x_rad_s`: 48/48<br>`initial_angular_velocity_y_rad_s`: 48/48<br>`initial_angular_velocity_z_rad_s`: 48/48 |
| F7 | `amplitude_deg`: 30.0–65.0 | `amplitude_deg`: 48/48 |

单位由字段名给出；`forcing_amplitude_x_scale`、`amplitude_scale`、`time_scale` 为缩放因子。以上为已实际运行、视觉接受的**离散样本覆盖范围**，不是保证区间内所有组合可运行、收敛或物理可信的连续资格域；F6 三分量极值不组成已验证的笛卡尔积。

F2 旧基线仅有已知液深 0.32 m，不能补造其接收器坐标或旋转时长。其余 47 例液深 0.264 m；F5 两个幅值端点的 `time_scale` 原始字段未知，故只有 46/48；未知值不参与独立性判断。F6 旧基线请求缺失角速度字段时，以真实启动绑定的 XML 与 case-definition 中 `(0.08,0.12,0.06)` rad/s 为证据，不从缺失 yaw 推断数值。

每族 48 个案例的全部 **1128 对**，均有至少一个双方已知、相同语义的数值物理输入差异。ID、路径、哈希、字段是否缺失、dp、时间窗和视图不作为物理独立性。证据为 [336 例实际物理参数汇总](evidence/E00005/all336-final-known-physical-parameters-and-visual-sample-ranges.json)，及 root1452(F2/F7)、1459(F4/F5)、1460(F6)、1461(F3)、1462(F1)。

溯源检查的关键修正：F1 液深与速度分别绑定各自字段来源，不能把同一父树当作两字段的通用证据；F3 使用实际 prepared forcing report 的 x 缩放/y 加速度与 XML 解析后的实际 forcing 文件，保留端点旧绑定中的名义值；F5 用实际 amplitude/time 值，不从名称推断缺失参数；F6 保留旧请求缺失并直接引用真实 XML；F7 使用实际运动幅值与原生输入绑定。科学控制 CSV、BI4 的哈希沿用生产者收据，本次主进程没有重新计算其科学真值。

## 4. 生成、转换和验收链

实际流程为“物理场景/控制定义 → CPU GenCase 初态与三维检查 → 共享 runner 注册请求/预算/GPU 租约 → 原生完整模拟 → typed state/身份/生命周期转换 → ParaView XMF 与完整渲染报告 → 接触表/关键事件视觉验收 → 实际主产物与字段来源汇总”。失败与恢复使用单独的工单、收据和产物角色，不把恢复版本改写回原始历史记录。

实际求解使用官方 DualSPHysics v5.4 原生程序；不同家族、母例、修复与批次的 dp、边界、积分、输出间隔和控制配方可能不同。**不存在一个可从当前通用脚本默认值推断出的“全 336 例统一配方”。** 每例应从真正启动收据的 command、`git_at_launch`、runner/binary SHA、启动与结束输入哈希、对应 XML/metadata 读取实际设置。仓库当前代码版本、早期 reference_matrix 与最新计划不覆盖启动时版本。以下 [NUMERICAL_RECIPE_INDEX.json](NUMERICAL_RECIPE_INDEX.json) 为实际启动收据与可用 XML 设置索引，CLI 覆盖单独保留；缺失/原始运行中状态不会补写。

动态产品逐例绑定位置 XYZ 与速度 N×3、完整原生时间序列和 `(Zone,Idp)` 身份轴；状态字段包括粒子 ID/zone、初始 type/mk/mass、valid、mass、velocity、density、pressure、type。坐标/状态有限性、原生维度与全帧渲染由已有生产者报告给出，[状态字段与文件可用性证明](evidence/E00008/all336-actual-UID-state-fields-and-file-availability-proof.json) 与 [终审](evidence/E00004/STAGE1-FINAL-REQUIREMENT-AUDIT.json)记录了证据来源。**本次材料整理没有读取 HDF5 或原生 BI4/IBI4 来独立复算这些结论**，文件存在性、元数据哈希、报告相互绑定与数值正确性应分别判断。

F6 全 48 例具有官方 FloatingInfo 全 241 帧刚体历史；47 例对应已核查的 17 项有限字段及原生 Part/时刻一致性，旧基线的原始表头、Part/质量缺项保持不变，不能宣称全 48 例都补齐相同 17 字段。刚体状态来自真实官方导出，不由粒子速度代推。F5 的真实底床使用全 801 帧初态/床面核查；它是当前几何与运行筛查证据，不是床面相关精确标签资格。

当前 336 条视觉接受记录中，90 条沿用主进程历史直接检查，246 条为委派视觉检查；最新政策允许子代理直接查看完整接触表及原始关键事件帧，主进程负责不可变绑定和案例计数，只对未决问题介入。不能把委派记录写成主进程亲自观看。[视觉记录与当前主产物关联](evidence/E00009/all336-current-visual-decisions-full-time-primary-join.json) 给出完整对应。代表性预览按首条记录与已知参数极值选择，见 [PREVIEW_GALLERY.md](PREVIEW_GALLERY.md)；它们不是重新作出的接受判定。

## 5. 已知限制、失败与恢复

| 家族 | 有流体缺失的案例 | 单例任一帧最大缺失数 | 最大占初始流体比例 |
|---|---:|---:|---:|
| F1 | 0/48 | 0 | 0.00000000% |
| F2 | 48/48 | 118 | 0.48014323% |
| F3 | 0/48 | 0 | 0.00000000% |
| F4 | 22/48 | 6 | 0.01015710% |
| F5 | 0/48 | 0 | 0.00000000% |
| F6 | 48/48 | 7 | 0.00213623% |
| F7 | 0/48 | 0 | 0.00000000% |

上述比例以初始流体身份数为分母、取单例任一帧最大缺失；与累计 particle-frame omissions、最后一帧缺失或所有类型总质量不同。生产者生命周期记录显示固定/移动/浮体身份始终活动。F2/F4/F6 的缺失流体位置、缺失后的状态、原因仍未知；本报告不把小比例当作守恒证明，也未新增允许损失阈值。F1/F3/F5/F7 的零遗漏只针对真实生产者生命周期报告，不代表数值误差为零。参见 [全生命周期遗漏证明](evidence/E00007/all336-full-lifecycle-relative-fluid-omission-proof.json)。

必须保留的历史缺口：

- F3 四份原 native059 收据仍是原来的 running/缺失 returncode 与 after pins；另有注册的完成恢复、完整 836 帧产物与接受记录。不能回填成原收据 completed。
- 若旧 typed 收据状态未知，而后续完成产物存在，两个角色分别引用；例如 F2 旧 P03 与 F3 typed154。旧发布的 atomic publication receipt 缺失也保留（F2 24 条、F5 4 条），不能因新索引完整而删除限制。
- F3 部分真实初态 QA 是几何共享复用，不能称作每个 forcing 条件都进行了独立初态实验。F6 基线原生 condition 字段、F2/F4/F7 部分真实旧基线 condition 缺失均保留；331 个可用 digest 与 5 个真实缺失不等于物理案例计数或物理独立性证明。
- 5 条旧 F3 视觉记录的复制末时刻与当前真实 manifest 相差约 1.5e-6–1.15e-5 s；以当前原生 manifest 为时刻权威，保留旧记录与差异，不宣称逐条字符串完全一致或把差异算作时间精度达标。
- 全帧无 nonfinite、视觉合理、流程结束均不能证明空间/积分收敛、长期粒子轨迹一致性、可信输运事件标签或外部实验符合。

失败流程保留根因分类、有限次修复与合法后备，不靠扩大排除阈值、压制 abort 或伪造 completed 来放行。当前还存在历史数值研究、标签/evaluator 草稿和未验收脚本；[WORKTREE_SNAPSHOT_MANIFEST.json](WORKTREE_SNAPSHOT_MANIFEST.json) 的 snapshot 提交只保存工作现场，不把它们提升为正式科学成果。`ds_data02_batch_runner.py` 是待审草稿，尤其需核查长日志管道阻塞与调度行为；不能用当前报告的 18 项资源测试给它背书。

## 6. 代码、分支与发布范围

基线：`0081645116664386f76f2bfa2ef428bcd74e846e`。科学完成点与本次发布前的额外工作树快照分开记录；总集成的快照提交为 `0699da83eff21cd4d60e61292a23a6178892099d`。此前尚未提交的 DS02 代码、JSON/XML 与文档在 integration/F2/F5/F6 中分别形成明确快照，原始科学数据、科学日志、环境/vendor 链接未纳入这批新增提交。

| 分支 | 报告前代码快照 | 用途 |
|---|---|---|
| [codex/ds-data-02-f1](https://github.com/yupengxiang/DualSPHysics/tree/codex/ds-data-02-f1) | [f2967fcc00f7](https://github.com/yupengxiang/DualSPHysics/commit/f2967fcc00f75d7b756a4625ba2449d8ad665de6) | 溃坝：偏心障碍与双通道 |
| [codex/ds-data-02-f2](https://github.com/yupengxiang/DualSPHysics/tree/codex/ds-data-02-f2) | [2189937fe7a8](https://github.com/yupengxiang/DualSPHysics/commit/2189937fe7a8c321b696a45077ac159a77fcff40) | 倾倒：开放杯沿与偏置接收器 |
| [codex/ds-data-02-f3](https://github.com/yupengxiang/DualSPHysics/tree/codex/ds-data-02-f3) | [b19f20e4f6de](https://github.com/yupengxiang/DualSPHysics/commit/b19f20e4f6defa803b6ac05b7c6b5bb439e6c045) | 双轴强迫槽体流动 |
| [codex/ds-data-02-f4](https://github.com/yupengxiang/DualSPHysics/tree/codex/ds-data-02-f4) | [2b24b5476609](https://github.com/yupengxiang/DualSPHysics/commit/2b24b5476609b4fb2d1afabeda1f8209438d886a) | 液滴落下与撞击 |
| [codex/ds-data-02-f5](https://github.com/yupengxiang/DualSPHysics/tree/codex/ds-data-02-f5) | [730fdebe61b6](https://github.com/yupengxiang/DualSPHysics/commit/730fdebe61b63314b73badd93a5b05647d56f771) | 紧凑三维波浪爬坡/回流 |
| [codex/ds-data-02-f6](https://github.com/yupengxiang/DualSPHysics/tree/codex/ds-data-02-f6) | [f46bb39f256b](https://github.com/yupengxiang/DualSPHysics/commit/f46bb39f256be782bee00c9d3af98539f0620a9e) | 浮体角速度释放与自由响应 |
| [codex/ds-data-02-f7](https://github.com/yupengxiang/DualSPHysics/tree/codex/ds-data-02-f7) | [61a08753593b](https://github.com/yupengxiang/DualSPHysics/commit/61a08753593b9a5323dcee0bb518d0579adc8abb) | 浸水移动障碍的平滑转动 |
| [codex/ds-data-02-infra](https://github.com/yupengxiang/DualSPHysics/tree/codex/ds-data-02-infra) | [aa1423cae28b](https://github.com/yupengxiang/DualSPHysics/commit/aa1423cae28b38868ec8bb81b68d057659298fbb) | 共享运行、资源与产物基础设施 |
| [codex/ds-data-02-integration](https://github.com/yupengxiang/DualSPHysics/tree/codex/ds-data-02-integration) | [0699da83eff2](https://github.com/yupengxiang/DualSPHysics/commit/0699da83eff21cd4d60e61292a23a6178892099d) | 总集成、验收与证据 |
| [codex/lagrangian-core-pipeline](https://github.com/yupengxiang/DualSPHysics/tree/codex/lagrangian-core-pipeline) | [1ef78a446276](https://github.com/yupengxiang/DualSPHysics/commit/1ef78a446276cca8664d5e586d2e42e6e8f7e448) | 原核心流水线后续提交 |

审阅分支为 `codex/ds-data-02-stage1-review-20261007`，与发布后的总集成包含本报告及证据导航。家族活动分支保留各自工作历史，**并非互不重叠的干净补丁集**；各自从基线的 compare 可很大，含累积共享历史。不能把它们未经筛选直接重复合入默认分支。审阅应先看本报告与目标文件，再沿具体 commit/receipt 和实际变更追踪。默认主分支未合并，未强推。

代码职责：场景和数值定义见 `scripts/ds_data02_f*.py` 与 `campaigns/ds-data-02/families/F*/`；预算/资源保护见 `ds_data02_runtime*.py`、`ds_data02_strict_dispatch_v1.py`；实际注册工单、启动与恢复、转换、底床/刚体核查、视觉来源与合并证明见 handoff_20261003 中对应 root/source 包。每次重跑必须恢复官方程序依赖、原始输入、共享数据根与相同版本；下载 GitHub 仓库并不意味着云端已经拥有所有原生文件或可复跑全部科学实验。

[BRANCH_INDEX.json](BRANCH_INDEX.json) 固定报告前源代码快照；最终远程实际 HEAD 与推送核对在上传包的 `PUBLICATION_RECEIPT.json`，避免报告 commit 自引用。所有科学数组留在服务器；本次是代码/证据审阅材料发布，不是整个原始数据集公开分发。

## 7. 资源、存储与验证

已批准累计窗口：512 GPU·h、3840 CPU core·h、1024 次资格尝试、720 次生产尝试。冻结时累计消耗约 **134.3862 GPU·h、689.6787 CPU core·h**，资格 624 次、生产 23 次、CPU 作业 3376 次；冻结时无活动预算 reservation。剩余额度按相同计数口径约 377.61 GPU·h、3150.32 CPU core·h、400 次资格和 697 次生产尝试。23 次“production”是 runner 工单分类，336 是独立物理案例数，两者不能直接比较或互相换算。

原采纳时间为 2026-09-30T07:23:48Z，原截止时间为 2026-10-14T07:23:48Z；报告/推送不重置期限。Home 最低保留 500 GiB，取代旧新增 1 TiB 限制。已获授权的失败产物清理累计释放约 **534.4086 GiB**，删除 17203 个文件、4 个注册任务；保留 38 个诊断样本和 21 份失败收据，最新核对共 399 次失败尝试的记录未被改判。检查点 Home 空闲约 779 GiB，当前值见 [RESOURCE_STATUS.json](RESOURCE_STATUS.json)。删除对象不包括合格的正式主产物。

GPU 以实时 UUID 检查、外部进程隔离、共享租约及累计预算原子 reservation 控制；本次 snapshot 中旧 runtime 的设备偏好更改为 [2,5,6,7]，它不替换已完成任务收据中的启动 runner SHA。严格 dispatch、runtime v2 等保护来源的哈希仍在 checkpoint 中。新报告不需要新的计算窗口。

本轮检查了 scoped 新增/修改 Python 的语法；资源预算、存储最低空闲、GPU 可见性/外部进程保护、GenCase 收据与启动输入一致性的三个测试模块共 **18 项通过**。没有执行全家族回归、依赖服务器原生数据的 stage8 测试或旧学习模型测试；18 项通过仅支持所列工程行为。另有审阅包自身的哈希、336 例/批次/字段差异、来源指针完整性验证，结果见 `PACKAGE_VALIDATION.json`。没有新增数值实验，也没有以测试通过授予 Q-N/Q-E。

## 8. 给下一阶段的建议与决策点

以下是待外部审阅者评估的计划，尚未启动，不构成新的实验授权或新的精度声称。

1. **先冻结首阶段版本。** 保持 336 例 identity、原生时间、失败/恢复角色、已消费字节和输入来源不变；定义正式版本清单与可运输的科学数据包，区分代码可下载、元数据可核验、科学数组可访问三个层次。
2. **挑选机制和可观测量做最小精度闭环。** 每族核查原计划两背景是否实际成立，优先选母例/端点及风险高条件；对共享连续物理几何/控制做三分辨率，并独立改变积分步/稳定控制、保存频率。先估算内存/时间/储存与失败概率，再登记预算，不以重跑 336 例替代研究设计。
3. **处理 F2/F4/F6 缺失及旧状态限制。** 把遗漏身份、时刻、位置/状态与边界/压力/密度退出原因分别审查；允许 unknown 与明确 scope exclusion，不把开放/缺失自动归为“spilled”。刚体原始字段、F5 底床与 F3 forcing 绑定应继续保留各自资格域。
4. **精确标签和误差预算一起建立。** 给来源→去向、首次通过、停留时间、净通量、回流/重复周期定义几何面、分母、插值规则、采样误差和 unknown 分桶；抽样人工/独立计算交叉核对，再运行全批次，不让未收敛事件标签冒充高精度真值。
5. **划分与无模型评测。** 围绕物理 parent、背景、控制模板和近邻参数防泄漏；冻结 development/test，禁止分辨率/复跑/派生视图泄漏。先跑无模型守恒、事件、统计一致性评测；不启动流体学习模型训练、推理或权重重放。
6. **最后决定数值参数域与外部验证。** 达到预先约定误差/观测标准再授予有限 recipe/domain/window/observable 的 Q-N；有独立实验再讨论 Q-E。维持首阶段标签与第二阶段资格分离，明确失败、回退和新增计算窗口申请条件。

审阅者应给出优先级、最小实验矩阵、可执行验收阈值及反证，不仅点评材料完整性。当前最大的风险是把视觉可用、流程/哈希闭环、元数据比较或生成脚本存在误当作科学准确性。

## 9. 云端材料如何使用

先读本报告、[RESEARCH_REVIEW_REQUEST.md](RESEARCH_REVIEW_REQUEST.md)、[CASES_336.json](CASES_336.json)、[FAMILY_SUMMARIES.json](FAMILY_SUMMARIES.json)。随后按 [EVIDENCE_INDEX.json](EVIDENCE_INDEX.json) 的 role、source_path 和 package_path 找原始元数据；文件保持原始字节，服务器绝对路径未伪装成可公开下载的地址。哈希只能证明复制/绑定一致，不能单独证明科学正确。

上传 ZIP 包带有便携 DS02 源码副本 `source/`（以 [SOURCE_INDEX.json](SOURCE_INDEX.json) 固定）、代表性实际 PNG、元数据和独立校验脚本。远程仓库直接查看实际 source 路径，因此源码副本只在上传包中携带，不在 Git 中重复保存。完整 XMF 和 HDF5、原生 BI4/IBI4、科学 DAT/CSV/JSONL 与 solver stdout 不在审阅包中；缺少这些数据时，云端只能做材料/代码/设计审阅，不能宣称已经独立重算全部 336 例。

为减少冗余，没有把完整 XMF 时间系列逐例重复打包；其真实地址、SHA 声明和字段/帧/时间核查报告已保留。整理过程中发现两份引用的 JSONL 属于逐粒子诊断记录，已从临时复制目录和最终审阅材料中移除；不作为本次可发布元数据。最终包内容以文件清单和校验结果为准。
