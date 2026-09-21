# Core 执行接续：2026-09-19

本记录补充 PROJECT-CONTEXT；即时状态以 `campaigns/core-v1/runtime/queue.sqlite3`、不可变 attempt 回执和资格报告为准。子 agent 统一 Luna Max；中央账本由主 agent 写入。

## 完成门仍未满足

已登记 T1 家族仅 F3（32 例）；宏观 T2 家族、正式多家族 32k 训练均为零。需要至少三个 T1 家族、两个宏观 T2 家族、九次正式训练、432 个学习模型 T1 case-run、288 个模型材料 case-run，以及完整异机复现。工程试跑和解析基线不抵扣这些分母。

## 可直接接续的证据

- F3 32 例：`campaigns/core-v1/f3-dataset-v2.json`。原 16/4/12 划分保留。`evidence/f3-legacy-hard-audit-adapter-v1.json` 复用历史硬审计语义，重新核对全部实际 H5 内容哈希；不授予材料资格。
- 正式训练：`scripts/core_formal_planner.py`。要求精确范围/配方、显式硬审计、哈希和谱系隔离、每族至少 16/4/12。`learning/formal-readiness-f3-v3.json` 正确保持 hold；不能通过将 `formal_release` 改为 true 绕过家族缺口。
- F4 固定物理黏性范围：15 个资格任务，scope `F4_drop_resting_pool_laminar_nu1e6_x_v1`。q=0 生产档已经硬审计失败，其余矩阵尚未齐全。见 `cfd/f4-laminar-q0-production-hard-failure-v1.json` 和两份局部/弦线取证；顶缘保存弦线不等于精确子步轨迹。自动生产监控只能在完整资格通过后执行 8→32。
- F2 静止装液 v2：`evidence/f2-resting-fill-static-hold-v2-h200/`。原执行产物未修改；144 个粒子缺失，最大杯外质量比例约 2.44%。重审单独存放 `observer-reaudit-v1/`。初态侧向空隙使其不能直接称静水平衡；后续独立装液候选不能只扩大运行域。
- F4 材料 MLS：`material/evidence/full003-collected/`。s2/s4 均完成 151 帧、512 seeds、0–0.3 秒，各 151 个恢复 generation 已核验。共同数值支持率 100%，终点位置最大差约 2.63e-7 m。只证明同一冻结流场下的子步一致性，不证明场重建误差、cadence/空间收敛或 T2。
- 跨机：原 float32 全时域结果仍失败并保留。`reproduction/float64-canary20-collected/` 的独立 double 推理变体通过 20 步原定容差，位置/速度差约 1e-16；特征构造仍沿用 float32 公共契约，再提升计算精度。完整 835 步与物理评分待验证，不能改写原失败结果。

以上相对证据路径均位于 `campaigns/core-v1/`。哈希应从实际回执读取，不从本摘要复制。模型变体、物理初态变化和观察算子修订分别版本化，不覆盖旧证据。

## 新增实际证据：F4 时间推进对照

`cfd/f4-laminar-internal-time-comparison-v1.json` 已核对中心生产档与收紧时间步的 audit、observations 和原生 Run.out 内容哈希。二者均覆盖 0–4.34 秒、218 个评分帧，硬完整性和事件窗通过；实际积分步数 283,655 → 501,887，公共量最大归一化差 0.00201277，小于冻结时间对照预算 0.01。该项通过不覆盖 q=0 生产档已有硬失败，也不代表尚未齐全的空间及原生输出矩阵通过。

## 全时域作业已启动

`runtime/full-window-dispatch-record-v1.json` 绑定双机 float64 residual 835 步 v2 与 F3 native-volume MLS 8.35 秒 CPU 作业的实际 attempt。rollout v1 在首帧物理评分因旧 bundle 没有 `geometry_at` 失败；v2 使用其静态 `geometry` 契约，经实际旧 bundle 的完整粒子轴物理评分调用核验后重新冻结。旧失败回执保留。这些都是诊断，不计入正式训练或材料资格。

## F2 保持通过与 F4 原生排除定位

F2 full-cup v3 实际静止 0.6 秒通过硬完整性及保持门：54,720 个粒子全部保留、杯外质量为零；见 `cfd/f2-full-cup-v3-static-hold-root-integration-v1.json`。后续必须验证规定运动与接液，不能据此宣告 F2 T1。

F4 q=0.75 细档十个丢失 ID 已经 PartVTKOut 与 RunPARTs 逐一核对，均为位置排除，位置 z=-0.60002375 至 -0.60000455，刚越过运行域底 -0.6；见 `cfd/f4-laminar-q075-native-exclusions-v1/evidence.json`。此外旧端点算子检测槽外半空间，不是有限厚度墙体占据。原冻结范围失败不改；未来修复需分别处理计算域与实体审计。中心和 q=1 空间单调对照、中心内部时间步与原生 cadence 已通过，但不能覆盖硬失败。

材料 F3 nominal 2/4 子步全 8.35 秒作业均已实际启动；数值支持诊断不等于材料资格。

## 后续实测结果（覆盖上文的进行中状态）

- F4 laminar 15 格现已齐全；`cfd/f4-laminar-final-qualification-v1.json` 的 `matrix_complete=true`、`T1_numerical=false`。空间、内部时间步和 cadence 对照不能抵消硬完整性失败；未启动生产批次。
- F2 full-cup 动态 canary 已结束，13,527 个原生 ID 缺失，硬完整性和事件窗均失败。`cfd/f2-side-wet-dynamic-v1-root-integration.json` 保留实际输出哈希；计算域与接液几何仍需修复，静态保持成功不继承为动态资格。
- 双机 double 完整 835 步已完成，但 `reproduction/float64-full835-collected/paired-comparison-v2.json` 判定失败。短窗精度一致性未延续到完整 rollout，不能声称异机复现通过。
- F3 nominal MLS s2 完整时域结束，见 `material/evidence/f3-native-mls-full835-s2-root-verification-v1.json`；仍仅为完整时域可执行性证据。s4 以及 coarse/fine 的 s2/s4 仍需收集比较。
- 材料范围参数明确为 `q=(drive_amplitude-0.9)/0.2`，来源和 seeds 几何固定。`material/evidence/f3-matrix-assets-v3-root-verification-v1.json` 独立核对 10 个来源资产的 50 项实际文件哈希，全部相符。中心原生 .002 秒输出存在；精确 .95/1.05 控制和高端点 dense 仍待补齐，不能借用邻近训练案例。
- `finite_wall_audit.bidirectional_face_crossing_events` 新增入/出有限容器面诊断，旧 outward-only 入口保留。新增与旧 continuation 共 11 项测试通过；保存弦段和零厚度面交点不是实体厚墙或精确求解器路径证明。

## 2026-09-20：完整材料对照与取证归档

中心三档 MLS s2 和生产档 s4 已完成并核验输出。`material/evidence/f3-nominal-fullwindow-partial-comparison-root-v1.json` 显示生产档 s2/s4 的终点平均距离约 4.16e-8 m、首次通过比例相同；细档相对生产档的一个来源首次通过比例相差 0.046875。支持率高不代表空间材料收敛，正式 CDF/删失界比较仍待完成。

高幅值端点三档×两档子步、低幅值端点生产/细档×两档子步均已提交。中心原生 .002 秒与其直接降采样 .01 秒的 v2 对照已启动；v2 源帧索引和有限容差校验经 8 项独立测试通过，运行代码冻结为 d4eb3d7d125c8753c4ca4d7fc937a14ccde2efd798c75a5adf71723e2bedc88b。旧 81ba 任务不受新版改动影响。

4096 seeds 的 20 步性能测量耗时 262.78 秒、峰值子进程内存 712.6 MiB，已据此提交完整中心求积对照（线性估计约 3.05 小时，实际随流动改变）。原生 cadence 和求积配置均不自动授予 T2。

跨机 CPU 取证支持“微小状态差异后出现特征差异、再出现 cutoff 邻居改变”的放大链条；固定状态 CPU 重放一致。`reproduction/float64-neighbor-forensics-archive-v1/manifest.json` 归档 5 项报告/脚本/扫描产物并核验哈希。快速邻居扫描并非生产算子逐帧等价证明，因此“最早检出”不能扩大为绝对首次差异。原 full835 复现失败继续保留。

F4 72 米计算域扩展提案暂缓，理由记录于 `cfd/f4-domain-extension-root-decision-v1.json`：位置排除已经直接取证，扩域不能解决独立墙面问题。CFD agent 优先修复 F2 的真实接液/外盆边界，并要求 GenCase 法向预检通过。

## 后续执行与接口修复

- 总控 PID 更新为 2518179，worker 未中断。`core_runtime.py` 在远端启动前检查输入哈希，缺失文件暂存、核验后以排他创建发布，不覆盖已有不同内容。21 项测试及 `h200-input-transfer-integration-v1` 实机验证通过；证据在 `runtime/input-transfer-integration-root-verification-v1.json`。
- F2 full-cup closed-catchment mDBC canary 的 attempt001 在求解器启动前因缺失远端资产失败；补传后同输入 attempt002 完成。4 个原生粒子丢失，杯/接液器墙面仍失败，外盆与底部检查通过；`cfd/f2-full-cup-closed-catchment-mdbc-v2-root-integration.json` 不授予资格。
- F4 独立高侧壁候选已启动：`h200-f4-tallwall120-q075-dp005-canary-v1`，墙高 1.2 m，其余初态/黏性继承作为对照，完整窗 4.34 s。737792 流体粒子、532908 边界粒子、零法向 0。旧配置 XML 字节等价已核对；新范围仍须独立观察算子校准和资格矩阵。
- `core_material_acceptance.py` 已接入 Core 材料门。范围资格必须声明 `required_source_ids`，侧车必须提供完整窗及逐来源 `initial_mass_kg/unknown_fraction_max`，不接受聚合比例替代。高幅值生产档总体未知 0.009765625，但来源0为0.015625，不能通过1%门。
- `material/evidence/f3-endpoint-spatial-root-comparisons-v1.json` 保留低/高端点实际空间对照。低端点两档未知均为0，但来源0首次通过CDF sup为0.08203125；故未知质量不是空间差异的唯一原因。
- `core_learning.py` 区分 `execution_complete`、`finite_rollout_complete` 和 `scientific_status`，未评估科学有效性时明确 `not_assessed`。科学负结果与未执行缺失分别统计。root 独立运行34项学习/科学失败/完成门测试通过；旧分数和full835失败结果未修改。

## F2 动态接触定位与 F3 数值语义核验

F2 closed-catchment mDBC v2 的取证报告及原始 RunPARTs/Run.out 哈希经 root 复核一致。首次杯壁端点异常为 0.76001146 s，运动开始前未见该异常；全部 4 个原生排除为密度原因，位置/运动排除为零。有限保存帧弦证据不能证明子步路径。后续仅检查有证据的运动壁接触修复，保留该次科学失败，未放宽门槛。

`material/evidence/f3-generated-numerical-semantics-root-v1.json` 重新核验 10 个实际生成 XML 哈希和参数，均为 ViscoTreatment=1、Visco=0.05，XML 明确标注人工黏性。分辨率相关耗散仅为长期材料差异候选解释，尚未归因；等待原生 dense 对照、求积对照及差异定位，旧 T1 与未通过的 T2 状态不变。root 独立执行 `tests/test_f3_native_volume_mls_compare.py`：4 项通过。

F3 高幅值粗档 s4 已完成并核验回执全部输出哈希；`material/evidence/f3-high-coarse-s2-vs-s4-root-v1.json` 完成完整窗比较，两者总体未知均为 0.01171875，增加积分子步未修复该覆盖缺口。

F4 新增显式观察器 `fixed_015m_vertical_reference060_v2`，保持 .15 m 垂直格距及 .6 m COM 归一化尺度；1.2 m 高墙使用 64 个质量格。`cfd/f4-tallwall-observer-candidate-v2.json` 标记已实现但未校准，13 项相关测试通过。未修改在途冻结运行或赋予资格；未来矩阵必须冻结同一布局与校准。

资格比较入口 `aligned_difference` 现在拒绝 observer version、几何尺度和布局不一致的两组数据，即使向量长度和数值一致；并验证 cadence 与时间/数据轴。相关17项测试通过。旧无元数据记录仍只能与同契约记录比较，不改写旧产物。

新增收集高幅值 production/fine、低幅值 production 的 s4 完整窗产物，实际哈希核验通过，s2/s4 对照分别保存为 `material/evidence/f3-{high-production,high-fine,low-production}-s2-vs-s4-root-v1.json`。低幅值 production 两者未知均为0；高幅值逐来源失败仍保留。材料 agent 已完成 nominal 三档误差定位，开始独立的参考场时间插值诊断版本，不覆盖原算法或升级资格。

F4 高墙观察器解析校准实际执行通过，证据 `cfd/f4-tallwall-observer-calibration-v2.json`。独立双来源构造覆盖高于旧 .6 m 顶部的质量，64 格质量、COM/KE及接触→上抛→回落事件与解析值一致，最大绝对误差 1.11e-16；19 项相关测试通过。资格入口进一步要求校准与每格实际观察器的版本、几何及布局一致，不能将旧槽校准沿用到新高墙。此证据只验证观察器实现，不授予CFD或材料资格。

F3 已完成全部已启动的16项512-seed分辨率/子步诊断（中心三档、高端三档、低端生产/细档，各s2/s4）。`material/evidence/f3-completed-16-resolution-substep-root-v1.json` 汇总哈希绑定回执与逐来源覆盖；CPU子进程累计34609.94秒，进程墙钟之和41472.88秒，峰值子进程RSS729.88MiB。后者不是活动实际历时或GPU小时。低端fine s2/s4均零未知；完整33项范围矩阵仍未齐全，已有空间误差和高端覆盖失败不因执行完成而通过。

跨家族适配器 root 复核：`tests/test_core_cfd_cross_family_contract.py` 3项独立通过。当前测试以真实prepared配置加2粒子fixture验证运动几何、同步oracle、资格隔离，不能扩大为实际54720粒子全链路证明；已要求ML agent补做已完成F2 v2实测及真实未来数据替换对照。还需核对审计motion sidecar与XML所指文件的内容一致性，避免元数据冲突被静态fallback掩盖。

新增动态F2产品迁移测试：打包声明的运动几何后移动包目录，删除原数据与motion文件，以 `python -I`、无仓库PYTHONPATH的独立子进程读取 .75 s 几何；三角面和壁速与迁移前逐值一致。`tests/test_core_package.py::test_moving_geometry_survives_source_removal_and_isolated_reader` 实际通过。这证明小型动态契约的独立打包能力，不替代全数据异机模型复现验收。

F3 native .01 与 native .002每5帧的原始参考全836帧、全部11字段逐值一致，实际源H5哈希已重验；证据 `material/evidence/f3-native010-vs-dense-matched010-state-root-v1.json`。其材料v1/v2 s4输出全部24字段也逐值一致，见 `f3-v1-native010-vs-v2-matched010-regression-root-v1.json`。可排除匹配时刻CFD状态差异及新帧选择入口作为后续cadence对照的干扰，但dense材料尚未完成，不能推断其结论。

F2动态适配器验收现处于待核对状态：root在同一t=.850029s、同一motion angle下比较 `PrescribedGeometry.world_from_body_at` 与 `cup_world_from_body`，旋转符号相反，矩阵最大绝对差1.23512108。`cfd/f2-geometry-convention-conflict-root-v1.json` 保留两套矩阵。真实54720粒子oracle/自洽壁速测试不证明几何与求解器一致；CFD/ML agent须根据原生运动边界位置确定约定，后续修复和审计都以此为准。

材料时间插值 v3 已通过 root 独立6项测试并实际完成20区间短窗，wall53.666s、CPUchild46.010s、peakRSS705.824MiB、unknown0，全部输出哈希通过。`material/evidence/f3-temporal-v3-short-s2-root-verification-v1.json` 保留实测。完整835步同冻结c92db95版本已实际启动：`ada-f3-native-mls-temporal-v3-full835-s2-512-v1` / `20260920T011358-9e5aa00ce480`。线程限制为1，CPU预留2、RAM4GiB、timeout7200s；源/配方/代码哈希固定。初窗线性估算2241s不保证近壁成本，完整结果不预授T2。


### 2026-09-19T17:44:49.670353+00:00：F4 高墙 canary 完整执行

- 实际作业 `h200-f4-tallwall120-q075-dp005-canary-v1` 已完成，218 帧、737792 粒子、4.34 s，当前原有审计 hard_integrity_pass 与 event_window_complete 均为 true，零原生丢失、零保存端点/弦穿墙。
- 结果、审计和观察量已归档并逐文件匹配 runtime receipt SHA；7 GB 轨迹正在传输，尚未声称本地哈希验证完成。证据：`campaigns/core-v1/cfd/f4-tallwall120-completed-v1/root-integration.json`。
- 单例不构成 T1；下一步是独立高墙范围矩阵、v2 固定高度分箱观察量以及真正收紧 DtMin 的时间对照。
- F3 temporal v3 production 完整运行已结束，材料 agent 正核验全时域结果；coarse/fine、原生密输出与4096 seeds 的实际 PID 仍存活。

- F4 7 GB轨迹已归档并匹配 receipt SHA256 `0fe1bc40687d7d1cb50c383df8a8c58aee58446faa9539782fc3baf7c4cd305a`。完整218帧 v2观察量重算完成，固定4×2×8格、事件与源质量门通过；校准元数据与代码hash完全匹配，旧事件序列逐项不变。新产物 `cfd/f4-tallwall120-completed-v1/observations-v2.json`，原始产物保留。

- F3同源 v1/v3 全835步材料比较已由root独立重核所有必要输出、receipt、provenance和比较器hash，比较器16测试通过。两来源首次通过/回流CDF最坏差异0.0234375–0.03125，超过0.02诊断界；终点比例一致不能替代时间分布收敛。保留T2未合格，继续v3自身子步与三档空间对照。证据 `material/evidence/f3-temporal-v3-v1-full835-root-integration-v1.json`。

- F2 CFL010单变量canary已由root核验19项输入hash与六组基线几何/初态字段后冻结提交：`f2-resting-fill-side-wet-full-cup-closed-catchment-mdbc-cfl010-canary-v2-001`，snapshot `f23dd524a4dcd1dde111d185ed68d85e6522bc3ee2a1ee2c42a15f9bf2bef292`。仅时间分辨率修复假设，不授予资格。
- 移动壁面saved-step实现physics+learning 23测试独立通过；root将共享 `passive_tracers.py` 纳入portable bundle，agent继续隔离环境真实调用验证和F2实际窗口诊断。

- v3 自身时间积分子步对照已冻结提交 `ada-f3-native-mls-temporal-v3-full835-s4-512-v1`：相同 c92db95 快照、源H5/初态/XML/512种子/完整835步，只把substeps 2改4。所有输入再次SHA核验，CPU2、RAM4096MiB、timeout7200s，依据s2实测wall1675.42s估计s4约3350.84s；实际耗时另由receipt记录。

- F2 CFL010全量产物已归档，4项必需输出逐一匹配receipt SHA/字节数。科学负结果：原生排除0，但cup首次端点穿墙0.840023s、receiver0.960004s，hard_integrity与event_window均false。保留全部失败分母，不同输入盲重试或资格升级均未进行；详见 `cfd/f2-cfl010-completed-v1/root-integration.json`。

- F4 tallwall120 v2 全部15格已静态核验，14个新作业正式提交；cell12保留等待既有q=.75细档canary等价复用，不重复计算。代码统一snapshot `2c850d81b842146b825acb6e263ca28301c8091f1459e5dffe1fe849541cb8e6`。资源计划、全部冻结spec和submission位于 `cfd/f4-tallwall120-root-scheduled-v2/`。H200实时RAM/GPU/I/O准入，现有GPU1大显存作业不干扰。

- H200两个CFD并行时IO/内存PSI均0，原默认io_capacity=2成为准入瓶颈。root将其提高至4开始下一阶段吞吐试验，hosts `runtime/hosts-mixed-qualification-v5.json`；仅替换总控PID2518179→2590277，保留全部worker并由PID/回执核对恢复。证据 `runtime/h200-io-capacity-step-v5.json`。

- 公开运动0→90→0折返漏检已修复：按公开控制knot和≤90°角增量分段，沿同一保存粒子弦检查。root重现例整窗/半窗均检出1粒子，physics+learning+package独立32测试通过。证据 `evidence/moving-wall-public-control-reversal-root-v2.json`，原失败v1保留；仍不是精确连续路径证明。

- H200三作业并发时IO/内存PSI仍全0，准入权重4→6进入下一阶试验；总控PID2592735，配置 `runtime/hosts-mixed-qualification-v6.json`。保留全部现有worker。权重4下20秒分作业吞吐已记录，异质/阶段性速率不能当作受控扩展结论。

- F3 v3 nominal三档空间比较全部完成，root逐条核验三trace与runtime receipt及所有pair输出/provenance SHA。production-fine首次通过CDF界0.0546875/0.046875，production-coarse0.0390625/0.0234375；未消除v1既有空间差异，不授予T2。证据 `material/evidence/f3-temporal-v3-three-scope-comparison-v2/root-verification.json`。继续v3 s4和已运行4096求积研究，不放宽阈值。

- F4 v2 cell03中心粗档完整执行通过hard/event/source-mass门，全部4项输出已本地归档并匹配receipt SHA/字节数；observer校准geometry/layout/version一致。证据 `cfd/f4-tallwall120-results-v2/cell-03/root-integration.json`。单点通过不授予范围T1，cell06已自动接续。

- v3 production/fine各4096总示踪点（每源2048）完整835步s2求积诊断已冻结提交；相同c92快照，输入逐项SHA重核，CPU各2/RAM各8192MiB。与各自512比较，再做同4096轴跨分辨率比较，不扩粗档或其他参数；不授予资格。

- 新增 `scripts/core_archive.py`：只归档succeeded回执登记产物与原生日志，逐文件SHA/字节数核验后原子发布，不写中央账本、不推断科学资格。3项测试覆盖损坏/非终态/路径越界/幂等，实际H200 cell00六文件跨机归档成功。collector PID2597934持续运行，根目录 `cfd/f4-tallwall120-archives-v2`；cell03已单独归档而显式排除。cell00 hard/event/source-mass全部通过，仍为范围未完成。

- 移动壁面算子向量化后真实F2 .75–.78三步共54720全粒子检查已执行，报告输入/代码哈希由root重核；physics/package/passive-tracer独立25测试通过。证据 `evidence/f2-closed-catchment-v2-h200/core-physics-public-saved-step-full-axis-root-verification-v1.json`。正在准备F2/F4完整时域接口oracle，保持特权诊断标记。


### F4 高墙矩阵新增 cell01/06 归档复核

主控独立重新校验两个归档的全部 12 个注册产物哈希及字节数。q=0 生产档 217485 粒子及 q=1 粗档 92224 粒子均完成 218 帧、4.34 s；硬完整性、事件窗、来源质量门通过。范围矩阵未完整，不授予 T1。证据：`campaigns/core-v1/cfd/f4-tallwall120-cells01-06-root-verification-v1.json`。调度器 PID 2592735 与归档器 PID 2597934 本轮确认存活，cell02/04/05 正在运行。


### 全时域 oracle 提交前审查

主控发现候选 runner 将 updater 结果全部覆盖为未来参考状态，且评分 RMSE 写死为零；已退回 ML agent 修正，两个 oracle 作业尚未提交。要求连续传播真实 commit、参考增量独立生成、实际评分及故障注入测试。证据 `campaigns/core-v1/evidence/privileged-oracle/root-review-v1.json`。共享材料 current-field 接口独立运行 7 项测试通过，但尚不代表模型材料端到端完成或 T2 资格。


### F2/F4 全时域 privileged oracle 已登记

修复版本独立 3 tests 通过；坏 updater 注入得到非零 selection score 0.1823421093，执行完成而 oracle_accuracy_pass=false。root 逐项复核所有 prepared 间接依赖、H5 和 runner 哈希后，冻结 snapshot c0b989af7cfc78109afa532bec878b630013343e0735555e58849c429ffc266c，登记 ada-privileged-oracle-f2-baseline-fulltime-v1 与 ada-privileged-oracle-f4-cell03-fulltime-v1。各 CPU2/RAM4GiB/IO0.5，timeout1800s，无GPU。输出限定各自attempt。F2 251×54720、F4 218×92224；仅接口诊断，排除训练、资格、正式模型分母。


### F4 完整粒子轴全时域 oracle 已通过接口精度检查

217 个预测步全部执行，92224 粒子，位置帧均 RMSE 1.7864e-19 m，原生速度误差零；217 帧静态墙弦检查无穿墙，validity mismatch 为零。主控核对终止成功回执及全部输出字节数/哈希。该结果只证明此案例的读取→增量→提交→评分接口；不授予 F4 T1、不计入正式模型评测。证据 `campaigns/core-v1/evidence/privileged-oracle/f4-cell03-root-completion-v1.json`。


### 材料完整链路与子步对照推进

`cpu-f3-model-material-rho0-full835-seeds512-v2` 与 `cpu-f3-reference-rho0-full835-seeds512-v2` 已登记并启动；各读取完整34560粒子流场，512 seeds，835 intervals，公开rho0=1000及同一后端策略。512×20实测模型26.64s、参考17.41s，取代4点直接线性外推；各CPU2/RAM4GiB/IO0.25，timeout3600/2700s。-m入口cwd固定到source snapshot，避免live tree导入。仍为诊断，不授予T2。

F3 temporal-v3 s2/s4两条完整轨迹均核对终态哈希；首次通过/回流CDF最坏差异界均0.0078125，未知质量不变，共同完整路径覆盖511/512。空间收敛失败仍未解决。证据 `material/evidence/f3-temporal-v3-s2-s4-root-comparison-review-v1.json`。

F4 cell04中心生产档已归档核验，通过硬完整性/事件窗/来源质量门。新v2 evaluator独立复跑接入6/15格，T1=false。证据 `cfd/f4-tallwall120-qualification-independent-root-six-cells-v1.json`。


### H200 并发容量 6→8 试验

测得 RAM available229269MiB，IO/memory PSI均0后，root将hosts版本提升v7，仅重启coordinator（新PID2620539），保留所有worker。cell08已启动native GPU进程1345480，并与cell07 GPU进程1336306同卡共享；显存分别884/656MiB。启动后IO PSI avg10=0.04、avg60=0.02，memory PSI0。尚不声称吞吐改善；后续据相同工作阶段的实际产出率判断。


### 2026-09-19T19:16:27.838361+00:00：三配置训练预运行入队

Root 在 H200 对完整 16 个 train 案例的 33 个唯一 H5/control/geometry 文件重新计算 SHA256，全部与登记值一致。MLP、Graph raw、Graph residual 的 seed17 / 16 update 诊断作业已提交中央账本，共用冻结快照 `37c71ea264b3819a4a6a198b5fbeeacb7d6a93fc78304d0c9ee9a5ae39c56bc6`。证据位于 `campaigns/core-v1/learning/formal-preprofile-v2/root-frozen/remote-input-verification.json` 和 `root-submission.json`。作业由持久调度器按现有资源余量接纳；不计入正式九次训练。已实际核对总控 PID 2620539、归档进程 PID 2597934 和三个材料进程存活。


### 2026-09-19T19:18:23.179042+00:00：F2 DBC 五秒事件窗正式启动

独立检查 16 项输入 SHA、连续几何/初态/静置门、XML 非时间字段、原 motion 文件前缀均一致后，提交预登记的一次 2.5→5.0 s 延长。Job `f2-resting-fill-side-wet-full-cup-closed-catchment-dbc-boundary-extension5s-v2-001`，attempt `20260920T031752-07b411be288d`，冻结代码 `93f49c0da7d153c73685ba3695e5341c7fff025715aad7e4a8c1340e7c99a319`。当前 worker 已启动，心跳显示 GPU 606 MiB。证据 `campaigns/core-v1/cfd/f2-dbc-extension5s-root-preflight-v1.json`。此为资格前 canary，未授予 T1；仍须全时域 hard gate 和事件完整性。Luna CFD 准备终态评估及条件式范围矩阵，Luna material 独立审查 512/4096 求积差异，Luna ML 修复公开运动控制静止区间的几何评测。


### 2026-09-19T19:20:54.960013+00:00：F2 全时域 oracle 几何复核 v3

Root 检查 public schedule 平坦段的静态 saved-chord 分支修复，并实际运行 physics/oracle 13 项测试全部通过。提交 `ada-privileged-oracle-f2-baseline-fulltime-v3`，冻结快照 `cf03b29111eba9371afcac991f1cd75d240082711c02aa46fbcaac7ab17544ca`，attempt `20260920T031940-f74162e981c2`。实际 PID 2632489 存活，进度 75/250，无失败；完整结论待终态。F2 五秒延长 worker PID 2631470 仍存活，已进入求解后的处理阶段。保留 v2 的61区间 unsupported 证据，不以单测替代全时域验收。


### 2026-09-19T19:23:46.249743+00:00：F2 oracle 全时域几何覆盖完成

`ada-privileged-oracle-f2-baseline-fulltime-v3` 终态成功，Root 校验两个输出字节数与 SHA256。全部250步完成，164个静态 saved-chord区间、86个规定运动区间，unsupported=0（v2为61）。位置帧均RMSE 9.436960071144714e-19 m，原生速度RMSE 0；这证明接口/更新器及登记几何诊断链路在该案例可执行，不证明学习模型或CFD资格。证据 `campaigns/core-v1/evidence/privileged-oracle/f2-root-completion-v3.json`。F2五秒CFD求解已code=0，后处理仍待终态。


### 2026-09-19T19:25:10.207164+00:00：F2 五秒候选终态为事件不完整

Root 对四个正式输出完成 SHA256 与字节数核验，worker succeeded，wall 366.975 s、GPU peak 606 MiB。20项硬完整性均通过，全部54,720原生粒子保留；5秒内仍无登记 settled 事件，event_window_complete=false，qualified=false。预登记的一次延长已用尽，不继续自动延长或放宽门。证据 `campaigns/core-v1/cfd/f2-dbc-extension5s-root-completion-v1.json`。已交 Luna CFD 检查实际末段运动、事件观察器与 spill_or_escape=0 的语义并接续 F1 证据审查；任何观察器修复须独立反例和版本化验证。


### 2026-09-19T19:26:52.831789+00:00：H200 混合任务并发准入

H200 四个CFD占用登记IO额度8，实际IO/memory PSI avg10/60/300均0、磁盘412GiB可用。将主机IO额度提高到8.75以准入三项各0.25的训练诊断；不增加CFD并发。仅重启总控，PID2620539→2635584，原worker保持。新配置 `hosts-mixed-qualification-v8.json`。三项preprofile均已running：raw `20260920T032603-bdb52c7c7795`，residual `20260920T032607-1429ff129f84`，MLP `20260920T032609-08c25ddfdd78`。启动后IO和memory PSI仍0；需继续测实际训练吞吐，不声称已证明并发提速。


### 2026-09-19T19:29:14.504019+00:00：三模型诊断预运行完成

三项 H200 preprofile succeeded，Root 逐项传回并校验 training.json/training-progress.json/checkpoint.pt 的 SHA 与字节数。证据 `campaigns/core-v1/learning/formal-preprofile-v2/collected/root-verification.json`。全worker wall raw90.764s/residual101.260s/MLP94.432s；训练段33.506/39.515/34.382s。进程显存采样峰值9150/9150/912MiB，高于框架allocated指标，资源预留须使用进程峰值。每项仅16updates，formal_training_count=0；已交Luna ML核验真实配对协议和canonical manifest hash。


### 2026-09-19T19:31:13.782130+00:00：F4 第一组三档空间比较通过

F4 cell02细档终态并归档，Root重新执行v2 evaluator。已有7格证据（含cell12复用），缺8格，未授予T1。q=0生产/细档公共观察量最大归一化差异0.004633861，三档呈monotone_refinement，当前比较passed；完整时域0–4.34s，218评分帧。报告 `campaigns/core-v1/cfd/f4-tallwall120-qualification-independent-root-seven-cells-v1.json`。三份模型诊断报告的数据canonical哈希一致、normalization完全相同；checkpoint内部配对核验仍待Luna ML。材料agent已获任务准备缺失精确CFD源，不再用近似训练点替代资格点。


### 2026-09-19T19:34:51.177103+00:00：真实checkpoint配对审计及后续证据补齐

Root复核collector实现，4项定向测试通过，并独立执行三份真实checkpoint收集，status=pass/failure_count=0。normalization、target scale、sampler state和raw/residual结构一致；明确限制：终态权重未保留初始参数摘要，normalization采样计数依赖冻结spec，残差先验实际执行未独立记录。已交Luna ML补未来正式训练证据及resume保护，不回填旧记录。F2 agent发现首帧outside观察器反例并版本化重审；修正后运动后speed_p95最低仍0.399684>0.10，原候选保持不合格。已交Luna CFD针对F1最早底板穿透做法向/ghost/厚度/实际配置有界取证，避免无依据重复试跑。


### 2026-09-19T19:46:46.708721+00:00：F4中心细档完成并重新评估

cell05终态成功并自动归档，worker wall4588.405s、GPU peak890MiB。Root运行v2 evaluator，报告 `campaigns/core-v1/cfd/f4-tallwall120-qualification-independent-root-eight-cells-v1.json`，当前8/15格、缺7格。空间比较摘要：[{"q": 0.0, "passed": true, "maximum": 0.004633861182864407, "monotone_refinement": true}, {"q": 0.5, "passed": true, "maximum": 0.0044926356985194454, "monotone_refinement": true}]。T1仍false，尚待端点、独立内点、内部时间和原生cadence完整证据。


### 2026-09-19T19:49:28.042284+00:00：训练执行证据独立检查

Root执行 learning/collector/formal-preprofile 32项测试全部通过。进一步review发现 training_evidence prior_complete 将已执行prior calls与目标总updates比较，会令正常中间checkpoint标incomplete；已交Luna ML改按当前已完成步数并补中间checkpoint/resume测试，修复后再冻结v3诊断。另检查已有 `core_production_dispatch.py` 提供qualification→8→24入口；后续需确认与当前tallwall120 v2 evaluator及归档路径接线，不能仅因旧入口存在就认定自动生产已接通。


### 2026-09-19T19:50:24.217236+00:00：F4自动生产接线缺口确认

实际调用旧production matrix inspector被scope guard拒绝，当前tallwall120不在旧SCOPE_PROTOCOLS中。旧生产生成器基于默认f4_config，不可仅加入scope名字而继承旧墙高；旧qualification receipt格式与当前v2 evaluator亦需明确适配。已登记 `campaigns/core-v1/cfd/f4-tallwall120-production-integration-gap-root-v1.json`，生产未放行。


### 2026-09-19T19:53:25.210294+00:00：F4独立内点生产档完成

cell09终态并归档后Root重跑v2 evaluator：当前9/15格证据，缺6格，failures为空。报告 `campaigns/core-v1/cfd/f4-tallwall120-qualification-independent-root-nine-cells-v1.json`。独立内点仍需配对细档完成后才可判断空间误差；T1保持false。


### 2026-09-19T19:57:16.414942+00:00：首个精确材料资格补源提交

Root审核Core五源runner、执行4项定向测试通过，首个amp=.95/dp=.0075/native.01完整8.35s作业10个输入哈希通过。提交 `cfd-f3_production_amp0p95_native010-v1`，冻结快照ad1c2b0b0fc0e4027783dd774d84200708209316fae31c13c17a00fd51a0d1b0。先验证solver→转换→审计→hash实际链路再提交其余4项。审计现有有限值/身份/总质量/时窗检查不足以宣称实体墙完整；已交agent增加流式墙/开口、逐粒子质量、首尾/cadence审计，首终态须独立补审，不覆盖冻结版本。


### 2026-09-19T20:00:43.228267+00:00：evidence v3 三模型预运行入队

Root再次运行35项learning/collector/preprofile测试全部通过。三份v3 spec各18输入哈希校验通过，共同冻结快照 `e0f001cbc8daf4d7d4aec5a70ea69d415e97e2e7be7dac12577603db2a94486d`，已提交 `h200-core-preprofile-{graph_raw,graph_residual,mlp}-seed17-v3`。仍仅16updates，formal_training_count=0。补入实际构造初始digest、normalization采样及prior执行证据；中间checkpoint已按实际完成update判定。随后验证真实16→18恢复，并需连续18步对照方可声称恢复等价。


### 2026-09-19T20:03:48.312862+00:00：evidence v3真实三模型严格核验通过

三项v3诊断均完成16updates，root传回全部checkpoint/progress/report并核验SHA及bytes，evidence_status均complete。严格collector真实产物结果pass、failure_count=0；证据 `campaigns/core-v1/learning/formal-preprofile-v3/collected/root-verification.json` 与 `strict-root-collection.json`。下一步基于实际checkpoint核验16→18恢复及连续18步对照，formal_training_count仍0。


### 2026-09-19T20:09:10.105898+00:00：首材料补源终态及F4第10格

F3 amp.95生产档终态836帧×34560粒子，基础审计pass；Root全部输出SHA/bytes核验通过，wall660.765s，GPU peak460MiB。独立墙/逐粒子质量补审待完成。证据 `campaigns/core-v1/cfd/f3-native-mls-sources/root-frozen-v2/first-canary-completion.json`。F4重新执行v2 evaluator：10/15格，缺5格，当前failures为空，T1保持false。专用生产连接器已交付，root仍需review，不提前放行生产。


### 2026-09-19T20:10:17.574236+00:00：F4生产连接器负例揭示未闭合验收

Root对当前10格receipt做仅内存变异：matrix_complete/T1=true，cells/missing/failures清空，validate_evaluation仍接受。反例 `campaigns/core-v1/cfd/f4-tallwall120-production-connector-negative-root-v1.json`。实际原receipt未修改，无生产启动。已交Luna CFD改为实际15格证据和完整科学checks推导资格，并补ledger回执驱动8→24的root tick及篡改拒绝测试；仅有proposal/布尔值不足以放行。


### 2026-09-19T20:13:02.840561+00:00：原生密集材料终态与补源批次放行

4175interval原生.002材料积分终态，Root核验全部输出SHA/bytes，trace737a5ff8e5d5f09254b1b7fcd224a6722272d91060067e0b671dcb9d859bffa8，完整路径覆盖.998046875；尚待cadence科学比较。首补源独立流式审计pass及7项定向测试通过，报告/代码/prepared哈希复核后提交余下四个CFD源，共同快照bae983d8ca4ce3a21bd20629ab84ee7c7c4c760931fae802f2604c5b25d9c94a。每例终态后仍需独立补审，不授予T2。

### 2026-09-20 CUDA 训练恢复实际失败与 cadence 证据

总控核验三个恢复配置各 19 个输入哈希及 e0f001 代码快照，5 项比较器/配置测试通过后提交三次 16→18 更新诊断。三次实际 H200 执行均在恢复 RNG 时出现 `TypeError: RNG state must be a torch.ByteTensor`，尚不能证明恢复正确；失败日志与执行回执保存于 `campaigns/core-v1/learning/formal-preprofile-v3/resume-canary-v1/root-failure-evidence/`。模型 agent 正修复设备恢复语义，须使用新快照重新诊断。正式训练数仍为 0。

总控独立核验原生 .002 与直接抽帧 .01 材料轨迹、比较结果及脚本哈希；来源 1 首次通过 CDF 差异 0.03125，共同全路径覆盖 511/512。当前 detection_budget 仅描述 unknown 掩码时间，尚非事件检测误差预算证据。核验记录位于 `campaigns/core-v1/material/evidence/f3-cadence-comparisons/root-verification-v1.json`。不授予 T2。

### 2026-09-20 三种模型实际 CUDA 短程恢复等价性

修复后的118050代码快照完成三个16→18恢复与三个连续18更新对照。总控核验所有输出哈希，并比较参数、Adam状态、RNG、采样器、归一化、初始化摘要和训练历史，三种配置全部一致。比较器新增优化器单独篡改反例，4项测试通过。汇总 `campaigns/core-v1/learning/formal-preprofile-v3/resume-equivalence-root-v1.json`。此证据范围为seed17的短程诊断，不替代32000更新正式训练或其长程恢复；正式训练数仍为0。

### 2026-09-20 F1 底面修复 canary 负结果

冻结4fdcf9f快照运行 `f1-h3-obstacle-bottom-face-mdbc-canary-001`，求解器完成，但完整审计失败：246个墙越界粒子帧，302558个障碍物内部粒子帧，首墙越界约0.440002秒。总控核验回执中3项实际输出哈希，保留缺失观察量和非零执行状态，不把求解器结束等同于通过。证据 `campaigns/core-v1/cfd/f1-h2-bottom-contact-forensics-v1/candidate/root-frozen/terminal-negative-result.json`。仅继续只读根因比较，不自动扩窗、改CFL或开始范围生产。


### 2026-09-19T21:11:42.063364+00:00 — 资格矩阵与 A8 接续

- F4 独立核验新增 cell13，现有 14/15 项；missing 仅原生输出 cell14，failures 为空，T1 仍为 false。证据：`campaigns/core-v1/cfd/f4-tallwall120-qualification-independent-root-fourteen-cells-v1.json`。
- v3 production 4096 seeds 全时域任务成功，四项输出已哈希核验；fine 对照进程仍实际存活。十项材料矩阵任务保持运行，不重复提交。
- A8 checkpoint-backed reproduce 的 root 定向测试 9 passed；真实异机全时域复现待执行，未升级产品完成状态。证据：`campaigns/core-v1/learning/a8-reproduction-root-review-v1.json`。


### 2026-09-19T21:29:37.331869+00:00 — F4 范围资格通过并提交首8生产

- 完整15项空间/时间/原生cadence矩阵通过，missing=0、failures=0；证据 `campaigns/core-v1/cfd/f4-tallwall120-qualification-independent-root-complete-v1.json`。资格已登记为独立scope_study，旧失败范围保留；规范参数名为 drop_left_x_m。
- 固定32例生产设计已冻结，首8例索引00/04/08/13/18/23/27/31完成GenCase并提交H200。91个独立输入哈希已核验，core_cfd.py与合格配方快照一致。提交回执 `campaigns/core-v1/cfd/f4-tallwall120-production-root-v1/root-frozen/submission.json`。
- 每例资源2 CPU、24GiB RAM、6GiB GPU峰值预留基础、I/O权重2；实测同档存储约6.55GB/例，H200空闲341GB，首8预计52.4GB（另预留20%）。按实时准入运行，不影响已有训练。
- connector定向测试15通过；1个旧测试硬编码资格未完成状态而失败，agent正在固定fixture。实际fresh evaluator与prepare均已通过，未据此扩大科学结论。材料T2和Core产品仍未完成。


### 2026-09-19T22:02:07.969996+00:00 — 异机复现启动与F1输入闭包修复

- A8 Ada/H200两端均完成84文件bundle校验。H200独立data_root通过65个原始数据硬链接复用；两端MLP seed17 update16完整835步诊断复现均已提交并运行，正式训练计数仍为0。回执在 `campaigns/core-v1/reproduction/a8-full-reproduce-v1/root-frozen/`。
- F4首8中的DEV_08已完成218帧/217485粒子并通过产物、执行回执及完整性绑定；审计 `campaigns/core-v1/cfd/f4-tallwall120-production-root-v1/case-audits/case-08.json`。剩余24尚未准入。connector16项测试通过。
- F4材料短窗20interval完成但unknown=100%，保留负结果；首失效在池面附近，重建残差门超限，未见墙/距离/ESS/rank失败。尚未提交同配置全时域，下一对照采用相同dense原生源及其匹配降采样并控制积分步长。
- F1 H4首attempt在solver前因prepared.inputs引用live脚本路径而失败；未覆盖远端已有脚本。新prepared副本仅将脚本路径定位到同哈希冻结快照，配置和GenCase输入不变，已执行唯一基础设施重试。重试solver已运行，早期出现particles-out，尚待终态科学审计。
- Ada本地IO竞争已实测记录；避免额外全库扫描，优先在H200已有源上执行后续工作。


### F4 同源 cadence 配对 canary 已登记（root）

两个 qualification-only 作业已提交：`core-f4-tallwall120-material-cadence-native004-s2-canary-v1` 和 `core-f4-tallwall120-material-cadence-stride5-s10-canary-v1`。共同源为 cell14 原生 0.004 s 输出，抽样视图为精确每 5 帧选取；材料子步分别为 2 和 10，保持约 0.002 s 积分步长，观察窗约 0.4 s。冻结快照 `50457227dfcf6b9625855b24eae9f3ac83eaf0986587045610c8c9b2982db102`。

提交证据：`campaigns/core-v1/material/jobs/f4-native004-cadence-root-v1/submission.json`。小输入已逐项核验，大 H5 由 worker 启动前强制校验登记哈希。保留 Ada 调度以复用本地源与视图，避免额外复制；不修改可靠性阈值，不声明 T2。
