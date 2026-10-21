# UFQ 01 完成审阅与持续建设方案的修改依据

## 1 主要判断

UFQ-01 按实际采纳的合同完成了一个有限证据周期。5 小时 18 分钟结束，不能据此判断本地 AGENT 缺少坚持；上一版把“必要诊断交付齐全”设为终点，把数据生成和后续周期放在未来重新下发的范围。加大总预算也没有自动扩大任务白名单和旧小批权限。

本次应改成一次采纳的母目标，以实际多族数据产品验收，允许主控在总范围内生成下一滚动批、切换有依据的候选、调拨未用额度、生产已通过用途准入的数据。保留科学诚实与历史边界，同时减少不产生新科学结果的重复管理步骤。

## 2 审阅范围和完整性

本次直接读取用户提供的 `COMPLETION_V1.json`、`RESOURCE_CLOSEOUT_V2.json`，以及本地恢复的新证据包；使用同一会话已有的旧审阅包核对原母例和计划。没有读其它会话文件，没有运行 solver，没有修改本地工程/账本或外部系统。

收到的 `UFQ01_REVIEW_EVIDENCE_V2.zip` 为 7,864,320 字节，声明完整包为 7,908,154 字节，相差 43,834 字节；整包 SHA256 不匹配，中央目录尾部截断、标准 ZIP 打开失败。按本地条目头安全恢复了 709 个条目，全部解压长度/CRC 通过；其中 `index.json` 列出的 708 个成员全部 bytes/SHA256 匹配。不是把截断包宣称为原整包相同。

独立的 RESOURCE_CLOSEOUT_V2 实际 SHA256 与 COMPLETION 中绑定一致，采用它作为最终费用来源；ZIP 内费用快照位于打包之前，不能用来覆盖最终 sidecar。

原始 BI4/HDF5 数组、实验工作簿和二进制未在本轮包内。这里验证的是导出证据、代码、元数据和来源链；不声称云端独立复算原始流场、实验曲线或全部字段。下一阶段的本地真实验收仍然必需。

## 3 精确证据表

路径约定：`N/` 指 UFQ01_REVIEW_EVIDENCE_V2 解出的根；`O/` 指上一轮 UPSTREAM_FIRST_NEXT_GOAL_REVIEW_20261012_V1 解出的根；`C`、`R` 分别指新附的 COMPLETION 和 RESOURCE_CLOSEOUT。原路径映射见 N/index.json。

| 编号 | 证据路径及字段 | 观察与本次决定 |
|---|---|---|
| E01 | C `adopted_at_utc`、`completed_at_utc` | 从 2026-10-11 17:11:44Z 到 22:29:59.648802Z，差 19095.648802 s，即 5:18:15.65。14 天是截止上限，不是必须工作时长。 |
| E02 | C `status`、`completion_matrix`、`no_necessary_ready_work_remains`、`next_cycle_active` | 终态为 completed_evidence，原队列必要工作结清、下一周期未激活。这个“无 ready 工作”不能解释为数据集产品缺口已消失。 |
| E03 | N/ufq-01/adopted-plan/GOAL_ZH.md 第三节；adopted-plan/TASK_QUEUE_V1.json 的 Q17；control/USER_AUTHORIZATION_ZH.md | 后续需重新采纳、完成停止、不自动进入 UFQ-02，属于实际执行约定。新目标需显式改变未来运行范围，不能责怪旧 agent 遵守旧合同。 |
| E04 | N/ufq-01/control/ADOPTION.json `budget_override`；control/USER_AUTHORIZATION_ZH.md | 本地记录将 8/32/384 改为 80 GPUh/3200 CPUh/512 GiB，但保留原小批和生产 0。此处看到的是包内已绑定的授权记录，未独立读取原平台消息。 |
| E05 | R `stage_usage`、`usage_in_human_units`、`solver_attempts` | 1.185526735 GPUh、682.810330815 CPUh、44.590950740 GiB、2 次 solver；总预算未因科学运行耗尽。 |
| E06 | R `conservative_preparation_cpu_core_hours`、`separately_measured_science_cpu_core_hours`、`accounting` | 681.220449138 保守准备核小时，1.589881677 单独实测科学核小时；前者占总收费 99.767%。真实准备 CPU 未测，不能声称实际总 CPU 只有 1.59。 |
| E07 | N/ufq-01/control/PREPARATION_ACCOUNTING_POLICY_V1.json、V2、V6 | 用 128×墙时，含等待与已另计子任务。新阶段前向改进测量和唯一归属，历史收费保留。 |
| E08 | R `parent_remaining.gpu_seconds`、`cpu_core_seconds` | 快照余量 369.674092258 GPUh、2440.264810364 CPUh。旧 128×墙时法约 19.06 小时可吃完 CPU 余量；只是预算推算，不是预测实际 CPU 运算。 |
| E09 | R `parent_limits.storage_policy`、`home_min_free_bytes`、`parent_remaining.new_storage_bytes` | home_free_floor、Home 500 GiB；-9,320,071,293,783 字节是名义 1 TiB 减历史的算术值，不是可用 NAS 欠额。 |
| E10 | N/ufq-01/runtime/runtime_v1.py `heavy`；R `charges` | heavy 把 kind=cpu 一律视重。35 个收费中 28 个为 0 GPU 且少于 60 CPU 秒。新调度保留真实 heavy 互斥、允许被强制限制的小任务并行。 |
| E11 | N/evidence/repository/lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py `check_reservation` 及运行循环；N/ufq-01/runtime/runtime_v1.py `check_guard` | 底层仍读共享 deadline，并把 storage 预约扣 Home；仅写新目标 JSON 或 NAS 外层 guard 不足。新采纳需前向整合真实执行链。 |
| E12 | N/RESULTS_ZH.md；N/evidence/nas/runs/F1/UF_Q01_F1_Q11_COMPARISON/q11-small-csv-evaluator-001/q11-report.json | CFL 收紧后 H1 对参考时间加权 RMSE 0.151517→0.130490 m，P1 1193.63→1687.67 Pa；不能宣称整体精度提高。 |
| E13 | 同一 q11-report.json `pairwise_qoi_differences.time_same_dp.time_weighted`、`space_fine.time_weighted` | 模拟间 H1 差异约 0.0870/0.1303 m，P1 1522.32/2808.52 Pa；现有全高度/压力预测不能直接视为稳定。应实际检验新的粗粒度输运用途。 |
| E14 | O/repository/lagrangian-fluid-lab/campaigns/ds-data-02/upstream-first/m1/f1/input/CaseDamBreak3D_Def.xml；N/ufq-01/decisions/f1-case-inputs-v1/UF_Q01_F1_FINE006667_Def.xml | 同一连续 DefTank/DefBox 与 fillbox，通过 roundpos 随 dp 离散。初态质量变化影响误差解释，但不要求把所有旧数据废弃或强行等质量。 |
| E15 | N/evidence/nas/runs/F1/UF_Q01_F1_DT010_CFL010/accepted-step-001/accepted-step-diagnostic.json；同根 UF_Q01_F1_FINE006667/accepted-step-001/accepted-step-diagnostic.json | 158516/158517、125271/125272 行/步数；完整分布/最大值未建立。先查首尾和输出语义，有依据再推导，不能凭空补行。 |
| E16 | N/evidence/nas/runs/F1/UF_Q01_F1_DT010_CFL010/native-audit-002/；UF_Q01_F1_FINE006667/native-audit-001/ 内扫描报告；N/RESULTS_ZH.md | 两个新 run 全事件 601/241 帧，position/velocity/density 已扫描、非有限为 0；最终缺失 738/1228。只覆盖实际扫描字段，不代表所有原生变量已验证。 |
| E17 | N/RESULTS_ZH.md；N/ufq-01/f5/README.md 及实际周期报告 | 已完成 ODS/时钟/周期分析，260 匹配/300 缺参考；eta=.0158907083>.015，VelX=.0542608425>.05。复用这些负结果，避免下一轮再把同一审阅当主要产出。 |
| E18 | N/ufq-01/transport/task-contract-v3.json；N/RESULTS_ZH.md | 四水深已有实际 initial_mass 端点矩阵、12 个 cohort 质量闭合、4 个身份置换对照。新增重点是全时段任务和真实数据接口。 |
| E19 | O/repository/lagrangian-fluid-lab/campaigns/ds-data-02/upstream-first/M2_PORTABLE_DATA_CARD.json | UF_PORTABLE_F1 是 161 帧、0–1.6 s 演示；不能计成全 6 s 核心。四水深全事件产品另行复用。 |
| E20 | N/ufq-01/decisions/waverunup-cost-scope-v1.json `actual_counts`、`full_original_case`、`projection`、`admission_scope` | 真实 GenCase 1,135,303 总/1,054,438 流体；完整 20 s/.02；38.255 GiB 是估计。旧 32 GiB 和只许准备的范围导致不准入，不能称物理容量耗尽。 |
| E21 | N/ufq-01/new-family/waverunup-next-cycle-contract-v2.json；new-family/source-actual-interpretation-v1.json | 15 s 控制/15.6 s 文件/20 s 求解需解释；数值输入语义与实验 gauge 对应分层。纯数值源闭合后可执行，实验用途未闭合就继续隔离。 |
| E22 | N/ufq-01/decisions/sloshing-source-nonadmission-v1.json；new-family/source-actual-interpretation-v1.json | SloshingAcc 有真实轴心/强迫疑点。保留不准入；可转 Motion 或独立命名项目派生，而不是无限等作者补说明。 |
| E23 | O/evidence/local-lab/vendor/official/DualSPHysics_v5.4/examples/main/11_Floating/CaseFloating_Def.xml | 2×2×2 m、massbody10000 kg、10 s/.1 的三维自由刚体候选。全浸没排水约8000kg，所以不能当静浮平衡例；先实际绑定和运行。 |
| E24 | C `scientific_qualification`、`evidence_limits`；N/RESULTS_ZH.md | Q-N/Q-E 未建立、独立验证和新三维族覆盖 0；两项流程事件保留。内部非作者审阅不等于外部独立数组复算。 |
| E25 | N/index.json `members`；本次恢复报告 | 708 个索引成员全部 bytes/SHA256 匹配，709 条目 CRC 通过；原整包 SHA 不匹配的截断事实保留。 |

## 4 哪些旧要求保留 哪些未来规则改变

| 项目 | 保留内容 | LFD-01 变化 |
|---|---|---|
| 历史终态 | upstream-first、UFQ-01 完成和全部负结果 | 新建母目标，不复活旧目标 |
| 成功条件 | 实证、版本、费用可追溯 | 数据产品实际达到才成功，子任务证据结清只关闭子任务 |
| 期限 | 每个正式目标有固定 T0/截止 | 一次采纳 T0+42 天，内部 14/28 天检查自动继续 |
| 任务队列 | 具体任务有依赖与成本 | 从产品缺口滚动生成，种子清空不是停止条件 |
| 生产 | 未通过用途门槛不进入核心 | 明确授权合格配方小批内部数据生成，不继承旧生产 0 |
| 资源 | 父累计限制、历史收费和实时更紧余额 | 新外层256GPU/1200CPU/4TiB/128次，小批可自动重分配 |
| CPU | 未知费用不能抹掉 | 未来实测与有界未知段分离、等待不按整机计费、子树不重收 |
| 并行 | 真实 heavy 全局最多一个 | 受限小任务与子代理工作可并行，复用分析模板 |
| 存储 | Home500GiB、NAS真实挂载、原始数据不入Git | 按真实池预约，完整事件可用64/128/256GiB档 |
| 科学边界 | Q-N/Q-E、实验来源、删失与材料身份分开 | 数值用途可先形成；实验列未映射不阻所有数值建设 |
| 复现 | 实际读取、负例和独立角色审阅 | 加真实自动唤醒/恢复与多族全事件产品复现 |

## 5 三条继续建设的路线

**F1：现存全事件数据转产品，同时资格辨因。**初态/日志问题按来源和用途分析，不默认重跑全部。把全时间控制区占据、初始来源质量和保存样本历史任务接到真实轨迹，冻结用途尺度，再用新未消费条件复核。

**WaveRunup：完整三维数值母例真正执行。**解释实际运动输入和时间规则，在足够且受控的 NAS 预约下运行20s；实验映射另行工作，不能用它阻止已经明确配置的数值任务，也不能因此宣称实验通过。

**第三物理族：尽早实际验证自由刚体耦合或备选。**先确认源、刚体状态与成本，再有限资格和小批。24 条里程碑前就取得第三族真实全事件用途证据；如果不能，及时换路径。

七族登记同时进行，但未闭合的族不拖住已通过用途的族生产。任何路径失败都保留；当全部可承受科学路线真实穷尽仍未达产品，先交付可用子集，再用准确的部分终态结束。

## 6 新资源方案为何这样设

256 GPUh、1200 CPU 核小时总计费分别约占本次父快照余量的 69.25% 和 49.18%。它们是授权天花板，不是耗费预测；未研究族不能套用 F1 的每例成本保证。

名义 20% 中央预留保证有资源做修复、至少12条最终留出、完整复现和收尾；工作池内按 4–8 条逐批自动拨款。所有实际上限仍取实时父余额更紧值，分类尝试不因换批号重置。

完整 48 条、三族、每族至少 8 条和至多 64 条扩展，都是本次可审阅产品目标，不是统计代表性或物理真实性保证。资源或科学条件不足时不强造数据，通过具体产品差距报告最大可用交付。

## 7 一手方法参考

- [NASA 空间收敛指南](https://www.grc.nasa.gov/www/wind/valid/tutorial/spatconv.html)：支持按实际条件评估多档离散及收敛前提，不支持单凭细化就宣称真值。
- [DualSPHysics 官方方法说明](https://github.com/DualSPHysics/DualSPHysics/wiki/3.-SPH-formulation)：密度/EOS、粒子 shifting、实际时间推进与刚体耦合的通用背景；执行依据仍是本地冻结版本。
- [SPHERIC Test 10](https://www.spheric-sph.org/tests/test-10)：晃荡运动、压力和重复性来源；具体官方案例的对应关系需本地核查。
- [LagrangeBench 原论文](https://papers.neurips.cc/paper_files/paper/2023/hash/ccac3b120c7dc86d45f56830732b62be-Abstract-Datasets_and_Benchmarks.html)：多机制拉格朗日数据与基准接口的参照。外部数据不计作本目标自有新增条件。

本方案的资源、数量、用途分辨尺度和代理组织是依据当前工程状态制定的规划选择，不能归因成上述文献的标准。
