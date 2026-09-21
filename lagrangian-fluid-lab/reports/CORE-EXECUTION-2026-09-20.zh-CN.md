# Core 执行记录：2026-09-20

本记录只写入已经有中央运行回执或独立审计证据的状态。排队、提交和诊断作业不计入正式资格、训练或发布分母之外的成功数。

## 当前执行状态

- F3 历史范围仍是已登记的 32 例 T1 开发资产。
- F4 `F4_resting_pool_laminar_tallwall120_x_v1` 范围资格已通过；32/32 个唯一生产案例已完成并进入内容哈希归档，formal collector 对 32/32 个案例完成权威审计，全部 `scientific_status=passed`，无失败、待定或 qualification 混入。formal collection 的 `formal_eligible=true`，随后已通过 hash-bound 注册器写入 Core registry；该注册只登记 F4 T1，不授予 T2 或 Core 总完成。
- F2 慢旋转 `q=1.0` canary 已实际运行完整 `0–5 s` 窗口，`hard_integrity_pass=true`，但 `event_window_complete=false`、`qualified=false`。该结果保留为科学负结果；不放宽 settled 门槛，也不据此登记 T1。
- F1 H4 obstacle 线保留为运行域／穿透失败；没有把失败重命名为资格通过。
- F3 原生 `.002 s` cadence 修复作业实际执行成功，但权威 source audit 仍因最大 cadence 误差 `2.187135930759032e-05 s > 2e-05 s` 失败，保留为修复失败证据。
- F3 材料矩阵的 4096-seed rows 29/31 已实际完成并生成终端 summary 与约 515 MB trace；两行均保留为诊断材料，可靠性支持仍未建立，尚未升级 T2。
- 新增 `f3-adapter-rows29-31-terminal-negative-evidence-20260920.json`，把两行的 summary、trace 和 execution receipt 绑定到 SHA-256，并明确 `T2_macro=false`；row29/31 的最大 unknown fraction 为 `0.0107421875/0.014892578125`，均超过已登记的 1% 门槛。对应证据单测为 **1 passed**。
- 新增 `f3-f4-t2-cpu-only-next-step-decision-20260920.json`，对当前 F3/F4 材料状态做只读 CPU 审计：`T2_macro=false`、`T2_path=false`、`qualification_claim=none`、`t2_status=not_established`；在未解决可靠性、范围覆盖和第二家族资格前，没有安全的 T2 资格计算步骤，不能以 CPU-only 诊断替代材料资格。对应门禁单测为 **1 passed**。
- F4 资格 tick 已用当前 15-cell 归档重新只读重算：`matrix_complete=true`、`T1_numerical=true`、`missing=[]`、`failures=[]`。为避免旧 receipt 继续绑定生产批次，已生成新的 qualification-compatible tick 和两份版本化 batch rebound；重新收集 12 个已登记产品时仍严格保持 `12/32`、`formal_eligible=false`。
- 第三个 T1 family 仍未取得：F2 10 秒 DBC canary 在 hard checks 20/20 通过后仍无 settled frame，F1 H4 的同一边界配置类已耗尽。现有 F2 mDBC closed-wall 预检发现 recipe、`qualification_only`、资源规格和既有失败谱系矛盾，已明确保持 hold，未提交新科学作业。
- 新增只读 `core_f4_tallwall120_production_refresh.py`：从不可变 archive manifest 重新构造产品索引，验证 receipt、四类产品哈希、重复案例冲突和 qualification 排除，不触碰 queue/ledger。11:17 的跨两个 production archive root 刷新扫描 28 个 archive，去重得到 24 个唯一生产案例（4 个重复），collector 结果为 `24/32`、`formal_eligible=false`；产物见 `products-refresh-terminal22-v2.json` 与 `collection-refresh-terminal22-v2.json`。同一时段主 archive root 的直接刷新也独立得到 24/32，见 `products-refresh-terminal24-v1.json` 与 `collection-refresh-terminal24-v1.json`；这些是最终 32/32 刷新前的历史快照。固定分母和 16/4/6/6 划分保持不变。
- 最新只读刷新已扫描两个 production archive root 的 34 个归档，去重得到 30 个唯一生产案例（4 个完全相同重复），当前索引为 `30/32`、待补 2 例，`formal_eligible=false`，无 qualification archive 被纳入；产物见 `products-refresh-terminal30-v1.json` 与 `collection-refresh-terminal30-v1.json`。固定分母和 16/4/6/6 划分保持不变。
- 最终只读刷新扫描 36 个归档，去重得到完整 `32/32`；formal 请求重新验证了 32 个 execution/result/observations/trajectory/audit 绑定，`authoritative_audit_verified_case_count=32`、`scientifically_passed_case_count=32`、`failed=0`、`pending=0`、`qualification_evidence_verified=true`。formal collection 见 `collection-refresh-terminal32-formal-v1.json`，产品索引见 `products-refresh-terminal32-formal-v1.json`；refresh 本身仍保持 `read_only=true` 与 `formal_release=false`，没有偷偷修改 registry/ledger。
- 新增 `core_f4_tallwall120_production_register.py`，将上述 formal collection 与范围 qualification、32 个案例的轨迹/审计哈希绑定到 Core typed registry；注册证据见 `f4-tallwall120-formal-qualification-20260920.json`、`f4-tallwall120-formal-registration-20260920.json` 及 `f4-tallwall120-cases/`。注册器拒绝部分 collection、hash mismatch 和隐式 scope migration，并支持相同输入幂等重跑。
- 注册后重新运行 `core_campaign.py --lab-root . status`：`evidence_valid=true`，T1 family 已从 F3 更新为 F3/F4；`can_finalize=false` 保持不变，因为第三家族、T2、正式训练、模型评测和异机复现仍未完成。
- 从 formal collection 固化了可移动的 F4 reader manifest `f4-tallwall120-formal-reader-manifest-v1.json`（`core.dataset.v1`，SHA-256 `49143d915371ad660807f2e63f9550636bfd0ca3cbd4a039cee94da96bc7f08f`）；`core_benchmark inspect` 实际读出 32 个 F4 案例，split 为 16/4/6/6。inspection 只验证接口可读性，不替代 T1/T2 资格。
- refresh 的合成 archive/qualification exclusion 单测已通过；该入口明确写出 `formal_release=false`，不把部分产品索引当作训练 manifest。
- 公共状态契约补齐了计划中的正式语义别名：`State.velocity_native_estimate`、`KnownInputs.current_geometry`／`prescribed_control`、`StepPrediction.displacement_m`／`delta_velocity_mps` 和统一 `commit(...)` 入口；契约测试验证原生速度不会被位移差分替换，新增测试 **9 passed**。
- 材料契约保持 CPU-only 和 no-T2 边界：逐来源 unknown 覆盖、F3/F4 binding、checkpoint 恢复完整性、重复 tracer ID、H5 终态审计均已加固；相关材料／校准／负证据回归 **38 passed**，未写 registry、ledger 或启动科学作业。
- 模型与产品接口已加固：setup failure 使用固定长度分母，图模型严格验证完整场、两跳 halo 和分块等价性；新增只读 `inspect_reader_manifests(...)` 会拒绝混合 v1/v2 schema、跨 split/family lineage 和非便携路径。当前 F3/F4 预检为 `portable=true` 但 `composable=false`、`formal_eligible=false`，因此没有启动正式训练。
- 全量回归在上述改动后为 **1307 passed, 1 skipped**（309.52 s）；其中包含 F2 矩阵的 3 个准备器契约、1 个独立 closure auditor、F2 静态科学观察器和 completion 分母修复。

## F2 静态候选 CPU 输入闭合

- root review 证据 `campaigns/core-v1/cfd/f2-static-full-cup-root-review-v1.json` 只批准后续 CPU GenCase/native decode，不批准 solver、GPU、矩阵 job、queue、ledger 或 registry。其 SHA-256 为 `742a3aa1b659bda38a7470c8bed06bd4e553df871bdbf1e2f53f994ec31b490c`。
- 新增 `scripts/f2_static_full_cup_matrix_prepare.py`：从冻结候选卡读取 15 个固定 cell，逐格生成独立 Definition、零角度 motion、GenCase 输出和 native decode preflight；失败格不删除、不重命名、不改分母。参数化预备器测试 **3 passed**。
- 第一次实际尝试因 decoder 父目录未预创建而产生基础设施失败；该 attempt 保留在 `f2-static-full-cup-matrix-prepared-v1`。第二次 attempt 暴露 GenCase endpoint 计数与抽象 lattice 计数差异，8 个 cell 作为原始失败保留在 `...-v2`。修正目录创建、端点采样层数和固定 `1e-10 m` 解码表示容差后，第三个全矩阵 attempt `...-v4` 通过：**15/15 prepared，0 failed，0 unattempted**。
- v4 matrix report：`campaigns/core-v1/cfd/f2-static-full-cup-matrix-prepared-v4/matrix-preparation.json`，SHA-256 `f5bfacfc38b700aa43f7bc9b2db3cacfbd126666419b3eaa8422d45ff2056746`；逐 cell 最大实际 native-to-continuum 质量误差约 `2.12%`，所有预登记质量、身份、有限值、杯内／域内和 no-overlap 检查通过。产物约 272 个文件、`1,225,417,633` bytes；GenCase 日志累计 CPU 执行时间 `5.284 s`，本阶段只读 decode 未计 GPU。
- 独立 closure auditor `scripts/f2_static_full_cup_matrix_audit.py` 重新哈希全部 15 个 prepared/preflight 文件，并确认固定 15 行分母、`solver_invoked=false`、`gpu_invoked=false`、`matrix_jobs_materialized=false`、queue/ledger/registry mutation 均为零。审计证据 `.../matrix-preparation-audit.json` SHA-256 `bc44fbf64aff429eb9ddb5e71117548413e7db047ceabbee627a6fe0312ecc25`。
- 这一步只证明 **F2 输入矩阵已经 CPU 闭合**；审计明确 `T1_numerical=false`、`scientific_results_present=false`，静态 solver 轨迹、事件窗和空间／时间资格比较仍未执行。Core registry SHA-256 仍为 `1ddfeda5b2d3eb142f94be4bb2cbc6f1b65271d6b77efc8b65c829b94e66b38d`，Core completion 仍为 `can_finalize=false`。

## 调度器修复

`scripts/core_runtime.py` 现在支持 `host: scheduler-selected`：

1. GPU 作业优先尝试 H200，再按实测 CPU、RAM、I/O、磁盘、外部 GPU 占用和显存预留回退到 Ada；不使用固定每卡任务数。
2. 实际主机写入 `allocation._host`，协调器重启或回执核对时使用同一个有效主机。
3. 提交 spec 仍保留 `scheduler-selected` 原始声明，冻结到 worker 的 request/spec 使用实际主机。

验证：`tests/test_core_runtime_scheduler.py` 加入路由与重启语义测试；与现有 runtime、formal preprofile、F4 collector、材料测试合计 **59 passed**。证据见 `campaigns/core-v1/runtime/scheduler-selected-routing-test-v1.json`。

## 诊断训练输入修复

F4 诊断 v1 因 DEV23 轨迹文件哈希在归档移动后失配而在 worker 启动前进入 `attention`，没有产生训练输出。三项 v1 已由总控取消并释放预留，失败证据见 `learning/f4-diagnostic-profile-v1/v1-launch-failure-evidence-v1.json` 和 `v1-cancellation-root-receipt.json`。

v2 已重新冻结并提交三项 16-update 诊断：MLP、Graph raw、Graph known-force residual。三项都已执行成功。它们都不是正式 32,000-update 训练，正式训练计数仍为 0。

10 秒 horizon-extension canary 已按 `T_extension=2T_previous` 单次规则完成 CPU/native preflight，并由总控以同一科学输入重调度到当前可用 H200 GPU；执行回执、完整归档和科学审计锁均已完成：`requested_horizon_reached=true`、`hard_integrity_pass=true`、`event_window_complete=false`、`qualified=false`，因此仍不授予 F2 T1。

## 归档跟随器修复

生产归档器已兼容 `host: scheduler-selected`。它从不可变的 `allocation._host` 读取实际执行主机，在归档清单中记录该具体主机，并在未知主机或输入损坏时拒绝发布。新增调度主机测试后，归档、调度器和核心运行回归共 **31 passed**；生产跟随器已重启，当前已发布 32 个 F4 生产归档目录。

资源账本的设备并集统计也改用冻结的有效主机；即使逻辑 spec 保留 `scheduler-selected`，跨主机同名 GPU UUID 的时间段也不会被错误合并。调度、归档和资源统计定向回归为 **32 passed**。

F4 完成后的 live queue 为 `queued=0、running=0、attention=0、succeeded=275`；32 个 F4 生产作业实际落到 H200 24 个、Ada 8 个。当前完成回执账本累计 GPU process reservation `110.4876 h`、GPU device reservation union `75.1498 h`、子进程 CPU `122.0658 core-h`；两种 GPU 小时仍按“进程保留总和／设备时间并集”分开报告。

## 账本回归修复

重试 attempt 的时间戳可能来自不同主机或恢复队列，不能单独作为最终 attempt 的排序依据。B2R 账本现在沿 `retry_of` 关系选择叶节点，再用时间戳解决无关 attempt 的并列；定向 B2R 测试验证失败原 attempt 加成功 retry 会归入 `physical_pass`，而 retry 仍计入 attempt 数量。

## 验证

全量测试：**1307 passed, 1 skipped**（309.52 s）。其中包含 scheduler-selected 路由与资源并集、归档器、F4 collector/refresh、材料和 B2R 账本测试，以及新增 rows29/31 终端负结果证据绑定、T2 CPU-only 决策门禁、公共 dual-increment 别名、F2 matrix preparation/audit/observer 和 completion 分母测试。

后续定向回归（runtime、scheduler、archive、F4 collector/refresh、qualification evaluator、B2R 及 rows29/31 负结果证据）：**52 passed**。

随后补充的 F4 refresh 跨 root 重复归档测试：**2 passed**（包括 qualification 排除和完全相同 archive 去重）。

T2 CPU-only 下一步决策门禁：**1 passed**；F3/F4 T2 审计单测：**1 passed**。这两项只验证证据闭合和阻断语义，不产生新的科学资格。

F4 formal 注册器回归：**2 passed**（成功注册可重复执行；formal 不合格时 registry、qualification 和 case evidence 均保持不变）。

注册、Core completion、F4 refresh、F3/F4 T2 负结果联合定向回归：**13 passed**。

## Core 验收计数（当前）

| 门 | 当前证据 | 状态 |
|---|---|---|
| T1 家族 | F3、F4 已有完整范围与 32 例生产注册；F2 静态候选 15/15 输入已准备但没有 solver 科学结果，第三家族仍未取得 | 未完成 |
| 宏观 T2 家族 | F3 rows29/31 终端材料结果仍是诊断且可靠性支持未建立；F4 材料 canary 未知质量为 1、覆盖率为 0 | 0 |
| 正式训练 | 诊断 v2 不计入正式训练 | 0/9 |
| T1 模型 case-run | 尚未开始正式 rollout | 0/432 |
| 材料模型 case-run | 尚未开始 | 0/288 |
| 异机复现 | 尚未进入 Core release | 未完成 |

中央完成门 `core_campaign.py --lab-root . status` 当前仍为 `can_finalize=false`：当前 T1 家族为 F3/F4，第三家族、两家族宏观 T2、9 次正式训练、T1／材料分母和异机复现仍为 false；其余未注册的 case-run 继续保留在分母中。

## 证据边界

硬完整性、执行成功、T1、T2、正式训练和发布资格保持独立记录。模型诊断可以失败并仍是有效诊断；缺失输出、未执行、排队和输入身份错误仍是未完成。

## 本轮追加：F2 科学观察器、材料前置与 manifest 规划

- F2 静态满杯候选已从 CPU 输入闭合推进到只读科学观察器：`scripts/f2_static_full_cup_qualification_observer.py` 读取固定 15-cell preparation 和可选的逐 cell HDF5 runtime manifest，检查原生 identity、有限值、质量、闭合壁／开口、完整 `0–0.6 s` 窗口、末段 `0.2 s` 静止保持，以及空间、内部时间步和原生输出 cadence 对照。缺失或失败行始终留在 15 行分母；观察器固定返回 `T1_numerical=false`，不会注册 scope。
- F2 admission contract `campaigns/core-v1/cfd/f2-static-full-cup-qualification-admission-v1.json` 绑定候选卡、v4 preparation、独立 closure audit、观察器和 legacy helper 的 SHA-256。`solver_launch_allowed=false`、`gpu_launch_allowed=false`、`job_spec_creation_allowed=false`、queue/ledger/registry mutation 均为 0，后续任何 solver 提交仍需新的 root review。该 contract 不等于科学资格。
- F2 observer、matrix preparation/audit、root review、candidate contract 的定向回归为 **12 passed**；其中 synthetic 15-cell runtime 全部通过时只得到 `candidate_scope_pass=true`，不会得到 `T1_numerical`。v4 preparation/audit 哈希保持不变，未启动 solver、GPU 或队列任务。
- 材料 agent 新增只读 `campaigns/core-v1/material/evidence/f3-f4-t2-cpu-only-remediation-preflight-20260920.json`（SHA-256 `a4b957fa0e92c666e305ec9409f4128134e574214c4480552f6d067ae2ead63e`）。它固定 unknown `≤0.01`、F3 CDF `≤0.02`、原生 cadence、F4 完整 `4.34 s` 事件窗、33 行范围和第二家族门槛；当前 F3/F4 均为 `T2_macro=false`、`T2_path=false`、`qualification_claim=none`。对应测试 **4 passed**，未打开 H5、未提交材料作业、未改阈值或 registry。
- 模型/产品 agent 在 `scripts/core_package.py` 增加只读 `plan_reader_manifest_normalization(...)`。根 agent 已对真实 F3 v2 与 F4 v1 生成 `campaigns/core-v1/learning/reader-manifest-normalization-plan-f3-f4-20260920.json`（SHA-256 `74149ef6011253e8515a75473bb69f51130bc4304c53349c0db46cd6fbcb117a`）。目标 schema 为 `core.dataset.v2`，当前 `normalization_ready=false`、`formal_ready=false`、`formal_eligible=false`；阻断包括 mixed v1/v2、F4 内联输入尚未物化为紧凑 hash-bound asset、F3 source 未声明 formal release，以及仅 F3/F4 两个 validation family（8 个 validation case，缺第三家族和 12-case gate）。规划器不打开 HDF5、不读取未来状态、不写 manifest/registry、不训练。其回归 **11 passed**。
- completion 状态报告新增 `missing_registered_material_case_runs`，并把 `missing_material_case_runs` 定义为 Core 目标分母缺口；这样在尚无 T2 family 时明确显示目标仍缺 **288** 个材料 case-run，而不是把空的已登记分母显示成零缺口。`tests/test_core_campaign.py` 定向回归 **7 passed**。当前 `core_campaign status` 仍为 `can_finalize=false`、T1 families=`F3/F4`、macro T2 families=0、formal training=0、T1 missing=288、material missing=288。

## 本轮追加：F2 runtime smoke 的真实负结果

- 新增 `scripts/f2_static_full_cup_runtime.py`，只在显式 root review 后把 v4 CPU cell 物化成独立 `core.f2.static_full_cup.runtime_prepared.v1`；它重新绑定 candidate、admission、source cell、solver、decoder 和所有生成输入的 hash，随后复用现有 `core_cfd.run` 做 solver、native conversion 和原始 hard audit。准备和 job-spec 阶段不启动 solver/GPU/queue；runtime view 不允许 registry mutation。其 adapter 契约测试 **3 passed**。
- root review `campaigns/core-v1/cfd/f2-static-full-cup-runtime-root-review-smoke-v1.json` 只授权 cell 0 的一次 Ada smoke，授权 solver/GPU/job/queue/ledger，明确禁止 registry、材料和模型训练；SHA-256 为 `236df01708f694a26b9460c8b5a3e51cbb98f38d027d45fba4d6eed72e426eaf`。cell 0 runtime view 和 spec 均已 hash-bound 后提交现有 coordinator，未改 F2 candidate、v4 preparation 或 Core registry。
- `f2-static-full-cup-smoke-cell-00-v2` 在 Ada 上实际完成，31 帧到 `0.6000524537853712 s`，trajectory 约 29 MB，执行层 `succeeded`。科学 hard audit 失败：**28,786** 个闭合壁端点 particle-frame、**1,274** 条保存帧 chord crossing、**1,304** 个受影响 particle ID；`requested_horizon_reached=true`，但 `hard_integrity_pass=false`。这不是基础设施失败，而是 DBC 静态满杯候选的真实负结果。
- `f2-static-full-cup-qualification-receipt-smoke-cell-00-v1.json` 将该 trajectory 作为只读输入接入固定 15-cell observer，得到 `candidate_scope_pass=false`、`T1_numerical=false`、15 行分母保留；cell 0 分类为 `cup_closed_face_endpoint`、`cup_saved_chord_crossing`、`open_cup_escape`，其余 14 行保留为 missing runtime product。负结果绑定见 `f2-static-full-cup-runtime-smoke-negative-evidence-v1.json`（SHA-256 `299487272bd2a84cb5c517e59a2662240f8447f3b6b30543079d1e4626a37e19`）。
- 按 root review 的“先检查再扩展”策略，已停止该 DBC 配方向剩余 7 格扩展；未登记 F2 T1、未改阈值、未重试同一输入。下一步只能准备一个独立、可审计的边界修复假设（最多两类之一）并重新做 CPU/geometry preflight，不能把这次 smoke 负结果当作范围资格。
- H1 边界修复已完成 CPU/native preflight：`scripts/f2_static_full_cup_boundary_repair_prepare.py` 只把 Boundary=1 DBC 改为 Boundary=2 mDBC，并加入 `GeometryForNormals`、`hdp` shape output 和显式 normal geometry；cell 0 的 fluid lattice、连续几何、粒距、时间窗和原生质量均保持 hash-bound。产物 `campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h1-cell0-v2/prepared.json` 的 8 项检查全部通过：fluid count/identity、finite、normal count=180636、zero normals=0、mass gate 均通过；`preflight_pass=true` 但 `qualified=false`，solver/GPU/queue/ledger/registry mutation 全为 false。
- H1 CPU-only root review `campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h1-root-review-v1.json`（SHA-256 `49718164b84a2705c1d9543f4bc686685543c97e5c2e24a30c60e5fc163ae215`）明确禁止 solver/GPU/job/queue/ledger/registry；H1 预检回归 **2 passed**。只有在独立 solver root review 后才可运行一个 H1 cell-0 canary，不能把 CPU normals 通过误作科学资格。

## 本轮追加：F2 H1 mDBC canary 的真实负结果

- 独立 H1 runtime root review `campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h1-runtime-root-review-v1.json`（SHA-256 `6a782ba2d8682a720d91ea39c71544695ff4d8cc7785dc8a1e976003d0011ef3`）只授权 Ada 上 cell 0 的一次 solver canary；它绑定 H1 CPU/native preflight、v4 preparation audit、原始 DBC smoke 负证据和运行适配器，并继续禁止 registry、材料和模型训练。
- 新增 `scripts/f2_static_full_cup_boundary_repair_runtime.py`，将 H1 生成的 mDBC/native 输入包装为独立 runtime view；公共 worker 仍使用同一 `core_f2` solver/conversion/audit 路径。新增 H1 runtime adapter 测试 **7 passed**，job spec 的 23 个输入均有哈希。
- `f2-static-full-cup-boundary-repair-h1-cell-00-v1` 已在 Ada 实际完成，31 帧到 `0.6000524537853712 s`，执行层 `succeeded`。原始 hard audit 仍失败：端点越界 **10,433** particle-frame、保存帧 chord crossing **1,263** 条、受影响 fluid ID **1,094** 个；`requested_horizon_reached=true`，但 `hard_integrity_pass=false`、`event_window_complete=false`。
- H1 将端点越界从 DBC smoke 的 28,786 降到 10,433，但没有恢复预登记硬门。只读 observer 仍给出 `candidate_scope_pass=false`、`T1_numerical=false`；cell 0 分类为 `cup_closed_face_endpoint`、`cup_saved_chord_crossing`、`open_cup_escape`、`spatial_comparison_failed`，其余 14 行继续保留为 missing。
- 负证据固定在 `campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h1-negative-evidence-v1.json`（SHA-256 `bbb97817955782e787a844300e3756af248d9cc49e7ecbb43b6275f7dd6de166`）。H1 hypothesis class 计数为 1/2；不放宽阈值、不重复同输入、不扩展剩余 14 个 cell、不注册 F2 T1。后续若继续 F2，必须另立 H2 物理／几何假设与独立 root review。

## 本轮追加：F2 H2 三层法向支持 canary 的正诊断结果

- H2 使用原有 CPU/native 已闭合的三层流体、有限杯／接收器／托盘和扩展法向搜索配置；新的 root review `campaigns/core-v1/cfd/f2-h2-mdbc-boundary-repair-v2-runtime-root-review-20260920.json`（SHA-256 `0b6fbca807dfb44c4ec0c1e4040495c6db79cdfa9ab2d479044f759ceb5473c9`）只批准一个 Ada diagnostic canary，禁止 registry、材料和模型训练。
- `f2-h2-mdbc-boundary-repair-v2-rooted-canary-20260920` 已实际完成，31 帧到 `0.6000162682278867 s`，56,115 个 fluid particle；执行层 `succeeded`，hard audit 通过，0 个闭合壁端点越界、0 条保存帧 chord crossing、0 个丢失身份，native mass loss 为 0。
- static-hold 诊断的最低杯内质量保留率为 `0.96685378241112`，超过候选 `0.95` 门；但 `event_window_complete=false`，单一 canary 没有空间／时间范围资格，也没有 T1 注册资格。正诊断证据见 `campaigns/core-v1/cfd/f2-h2-mdbc-boundary-repair-v2-canary-evidence-20260920.json`（SHA-256 `6f15f9d2a6d604694d7a2572f5827ac06379fb8a13e8826f9173ffcca9793211`）。
- H2 只作为未来 F2 scope 的候选入口；没有将它并入 F2 静态 15-cell 分母、Core registry、训练或模型选择。下一步必须先冻结独立的 15-cell 设计和 CPU/native preflight，再另行 root review 后才能提交矩阵作业。新增证据单测 **2 passed**。

## 本轮追加：F4 v1→v2 compact reader materialization

- `scripts/core_dataset.py` 新增 `compactify_manifest(...)`：只解析并校验 v1 `known_inputs`，将每个 distinct geometry/control 内容写为 data-root 内的 SHA-256 命名 NPZ，并把 case 改写为 `core.dataset.v2` 的相对 `known_inputs_ref`。它保留原 HDF5 相对路径、字节数、轨迹 SHA-256 和 `known_inputs_sha256`，不打开 HDF5、不读取未来状态、不写 registry/ledger。
- 真实 F4 formal reader 已物化为 `campaigns/core-v1/cfd/f4-tallwall120-production-root-v1/f4-tallwall120-formal-reader-manifest-v2-compact.json`（SHA-256 `eb417b2774817039776b50d18e12e2500634d8c60f4465c42f5633a033c04a16`）。两个共享输入资产分别为 geometry `9f51596afa4f6f741a723d606f61e7677491f2fe40b6934eb6f0453ddcc25d8b`、control `acdacd07a058d8904c77ef5d1a4f1c9296c211d6d3e683e4bb94b5b74b152cf0`。
- `core_benchmark inspect` 实际读取 compact F4 manifest 得到 32 个案例、16/4/6/6 划分、每例 218 帧；inspection 只验证读数，不把 manifest 当成新的科学资格。
- F3 v2 与 compact F4 现在已经同为 `core.dataset.v2` 且 `portable=true/composable=true`，但 combined `formal_release=false`、`formal_ready=false` 仍保持：F3 尚未声明独立 formal release，且仍只有两个 validation family、8 个 validation cases。新的只读计划 `campaigns/core-v1/learning/reader-manifest-normalization-plan-f3-f4-compact-20260920.json`（SHA-256 `6425a1a6c8555a1c6545b1191dabd009939e1dcc5769a326859d3de38a6d8a57`）保留这三个阻断码。
- 物化证据见 `campaigns/core-v1/learning/f4-compact-reader-materialization-evidence-20260920.json`（SHA-256 `f6e760f1e53bf79efff595b575cc9471ed0784a0e7d7fd5df9f7164a0da8687a`），inspection receipt 见 `f4-compact-reader-inspection-20260920.json`（SHA-256 `c4997dddd108c9c5acc4d89d582ed6b5e4ba25aa32af8c7603587c513318f0fa`）。新增 compactifier/真实 F4 preflight 回归 **14 passed**，未启动训练。

## 本轮追加：F4 compact reader 的完整场接口 profile

- 使用 compact F4 manifest 的开发案例 `F4_resting_pool_laminar_tallwall120_x_v1_DEV_04`，以同一 `graph_raw` adapter 在 CPU 上执行 1 个完整场 autonomous step；profile 输出为 `campaigns/core-v1/learning/f4-compact-interface-profile-20260920.json`（SHA-256 `aa82e4a3e5ce9459be3e4bcd53815b0cf8b3f5618d03f115a88e8f2e85f21fd4`）。
- 实际读取 217,485 个粒子，`full_field=true`、`autonomous_state_feedback=true`、邻域半径 `2h`、最多 64 邻居、hidden 64；单步 wall time `64.2301 s`，CPU time `2924.8941 s`，峰值 RSS `1146.36 MiB`，GPU 显存为 0。
- 该 profile 只用于训练／rollout 资源里程碑和同卡并发准入，不是正式训练、checkpoint 或科学资格。它显示完整场图模型在当前 CPU 路径上的吞吐很低，正式 9 次训练必须使用 GPU，并在真实 GPU profile 后再决定并发度；不把 256 个 loss center 误写成 256 粒子模型。

## 本轮追加：H2 F2 静态范围资格设计冻结

- H2 的独立 15-cell 资格设计已冻结在 `campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v1/qualification-design.json`，SHA-256 `df92471f537d00b475df80c882fbb11eb690fbe2494408befbd344f960f45fac`。它包含 q=`0,0.5,1` 的三档分辨率、q=`0.25,0.75` 内部核验，以及独立时间推进和原生 cadence 行；即使几何相同，时间行也使用不同输入身份哈希。
- 每个 cell 都绑定 fresh Definition/motion/GenCase/native decode/preflight、mDBC 法向和数量、质量／身份、闭合面／chord、开口逃逸、静止保持、事件窗、空间／时间门；所有失败行保留在固定分母中。设计层禁止 solver、GPU、job、queue、ledger、registry 变更，固定 `qualification_only=true`、`T1_numerical=false`。
- 设计合同的 6 个测试已通过。当前 H2 canary 只证明单点 hard-integrity 和静止保持，事件窗仍不完整；因此这份设计不能授权矩阵运行，后续需新的 root review 和 CPU/native preflight 后再决定是否提交 cell 0 之外的作业。

## 本轮追加：H2 CPU/native 预备计划（只读）

- H2 候选卡 `campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-candidate-v1.json` 已冻结为设计锚点，SHA-256 `d0926ee5c0b02cc6364a7f7f40d1d245cdaa8d1543cf77c7bd02cdbc32938866`；它绑定 H2 canary 的 prepared、Definition、root review 和正诊断证据，固定 15 行分母，所有行目前均为 `unattempted`。
- 只读计划 `campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v1/preparation-plan-20260920.json` 已生成，SHA-256 `8202b0c9235c747ceff56eed544dcf649dfec57feb08c6d9f244702fd3963ffa`。计划确认 CPU GenCase/native decoder 可以用于后续 materialization，但本次 `plan_only=true`，`gen_case_run=false`、`decoder_run=false`、solver/GPU/queue/ledger/registry 均未执行或变更。
- 计划脚本同时修正了 prepared manifest 对 `config.scope_id` 的兼容读取；修正后通过 `py_compile` 并成功生成上述计划。下一步仍需独立 root review 才能执行 CPU/native materialization；不会因 H2 单点 canary 的正结果自动扩大到 15 个 cell，也不会注册 F2 T1。

## 本轮回归结果

- 完整 pytest：**1323 passed, 1 skipped**（319.89 s）。
- H2 设计、材料前置、compact reader 和 Core package 的定向回归：**20 passed**；H2 计划脚本另通过 `py_compile` 和 `plan_only` 实际执行。

## 本轮追加：H2 v4 CPU/native 矩阵审计

- 在 v4 candidate、计划和 CPU-only root review 绑定下，15 个 H2 cell 全部尝试了 GenCase 与 native decoder；矩阵报告 `campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v1/prepared-20260920-v4/matrix-preparation.json` 的 SHA-256 为 `959ef8d420ecc6a70e545cf63871c60c334dced8648e6c39e9fe63bed0ebaa03`。
- 结果为 **14 个 CPU/native preflight 通过、1 个失败、0 个未尝试**。通过项的原生身份、有限值、mDBC 法向、闭合几何距离、质量和 hash closure 均通过；solver、GPU、job、queue、ledger、registry 均未执行或变更。
- 唯一失败为固定 held-out cell 11（q=`0.75`、dp=`0.0075`）：第三来源层离散质量相对误差 `0.0280611`，超过冻结 `0.025` 门；总初始质量误差仍为 `0.0117944`。该行保留在 15 行分母，未放宽门槛、未重试同输入、未注册 F2 T1。只读汇总证据为 `campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v1/cpu-preparation-evidence-v4.json`（SHA-256 `6b39c523fe1a022b09e4b5f4a9c6985dc49f54fcc5299b1a85988fac7af57c2e`）。
- v4 仍不足以授权 solver 范围矩阵；下一步要么另立一个有独立参数卡的 F2 scope，要么接受该候选负结果并转向其他第三家族路径。

## 本轮追加：F4 完整场 GPU 接口和同卡并发 profile

- 在 Ada-0 上实际执行 F4 compact manifest 的 217,485 粒子、`graph_raw`、完整场 autonomous step。单进程 profile `f4-compact-interface-profile-ada0-20260920.json` 的 SHA-256 为 `a147c2b1dd2fd74a6e6f3e115879a8f192bd3e31a137de619fc96f5a4d1c275e`：单步 `20.9332 s`、峰值 GPU 显存 `373,622,272 B`（约 `0.348 GiB`）、峰值 RSS `1132.8 MiB`。
- 同一 Ada-0 同时运行两个独立 seed 的完整场 profile，均成功完成；单步分别为 `22.3856 s` 和 `22.4980 s`，相对单进程慢化约 6.9% 和 7.5%，无 OOM。两个产物哈希分别为 `ec46bf0871c6cce95d76c6753c05df5e9d4e153b684f013b7e8edf5355ce03c3` 与 `355a691f362fc7085d1b60995af0726a5f834337caff19a4d4d6e9bdfbe2b278`。
- 并发证据 `campaigns/core-v1/learning/f4-compact-interface-gpu-concurrency-evidence-20260920.json`（SHA-256 `4429daf190af34ec5a8d7130297b2f4f601b9e52fa3bd4c39258bda3cb9bf5d9`）建议把 **2 个同卡完整场 profile** 作为初始准入；正式训练还需代表性 optimizer／I/O canary，不能用推理显存直接推断训练并发。

## 本轮最终回归与状态

- H2 endpoint guard、第三层来源质量选层规则和新增资源证据的完整 pytest：**1325 passed, 1 skipped**（335.64 s）。
- `campaigns/core-v1/registry.json` SHA-256 仍为 `1ddfeda5b2d3eb142f94be4bb2cbc6f1b65271d6b77efc8b65c829b94e66b38d`；本轮没有任何 registry mutation。
- 当前 `core_campaign.py --lab-root . status` 仍为 `can_finalize=false`：T1 家族 F3/F4，宏观 T2 为 0，正式训练为 0，缺少 288 个 T1 case-run 和 288 个材料 case-run；第三家族、两家族 T2、正式训练和异机复现仍是后续主线。

## 本轮追加：F4 compact reader 全时域 oracle

- 对 `F4_resting_pool_laminar_tallwall120_x_v1_DEV_04` 执行了完整 217 个 transition、全粒子轴的 `core_benchmark verify --full-scan`，耗时 `136.523 s`，报告为 `passed=true`，`qualification_inferred=false`。
- 每个 transition 都通过同一公共 updater oracle：原生速度误差最大值为 `0`，位置更新误差在浮点舍入范围内（最大约 `6.94e-18`）；oracle 明确标记为 privileged reference increments，不把它当作学习模型结果。
- 验证产物 `campaigns/core-v1/learning/f4-compact-oracle-verification-dev04-20260920.json` SHA-256 为 `88ab3fa953bd8b83197b017e53d2499aaca3a88e52723d4095a216f638cb4c16`。这闭合了一个真实 F4 案例的 reader→state→update→evaluator 接口链，但还不能替代三家族正式模型评测。

## 本轮追加：F2 第三家族候选谱系和首个动态 canary

- F2 第三家族候选冻结为 `F2_dynamic_third_family_dbc_duration_x_v1`。候选卡、15 行固定矩阵、失败分母和 root-review 草案均保留 `qualification_claim=none`；q=.75、`dp=.0075` CPU/GenCase/native preflight 通过，但 preflight 不给矩阵 numerator credit。
- root 审查发现并修正了一个谱系歧义：相对 static v3 源输入，动态 closed-catchment recipe 确实新增四面 catchment side walls，故 `physical_geometry_changed_relative_to_static_source=true`；相对已有 q=.5/q=1.0 native-DBC closed-catchment 动态基线，几何、初态、边界、时域和门槛冻结，q=.75 只改变 `rotation_duration_s`。澄清记录为 `campaigns/core-v1/cfd/f2-dynamic-third-family-dbc-duration-lineage-clarification-v1.json`，SHA-256 `abed3b35ea5459f725814cad574e636d2f6dd31ec51775f1c4cb6daeb70ab6b3`。
- 主要候选文件当前哈希：candidate `bf7ee6e0fe4c45f597e65ba66d4b5ebbdea0772c5d73ecf532cad45a3199814c`、matrix `cf356f1cf7d0b02474ce7e6d215a9ff07eea0d6293aca5c87799014367c5dcf1`、failure denominator `037b22e8148c3c0f8f72f1b47550fd808072a5e3ce9810fadd0fda9fd04eda1b`、q=.75 prepared `0e20f0a1931f069b0b049a7f33b9b9e27bbc6293cd706708c9619d83e723ff9d`。
- 新增 `scripts/f2_dynamic_third_family_runtime.py`，只在独立 root approval 绑定 case、矩阵、谱系、solver/decoder 和 hash closure 后生成一个 job spec；其契约测试与候选测试合计 **9 passed**。首次 root approval `campaigns/core-v1/cfd/f2-dynamic-third-family-dbc-duration-root-review-first-row-v1.json` 的 SHA-256 为 `d263a479173401cd67952a5f5a6a4ef2043da33f73111cb442528fdf5a871f7b`，只授权 Ada 上一个 q=.75 / `dp=.0075` canary，禁止 registry、材料和模型训练。
- 该 canary 的队列 job `f2-dynamic-third-family-dbc-duration-q0p75-dp0075-canary-001` 于 Ada 完成，execution receipt 为 `succeeded`，wall `364.697 s`，GPU process reservation `0.1013 h`，CPU children `447.0 s`，峰值 GPU `606 MiB`；产物为 501 帧、54,720 个流体粒子，trajectory SHA-256 `2255c6c778656138553e4208356c89d769fee85cf39c6a3b8e7814240c4abf01`。
- 科学 hard audit 通过：无 native ID 丢失、非有限值、质量变化、闭合壁端点越界或保存帧 chord crossing；请求的 5 秒时域到达。事件仍未完成：运动完成于 `1.525 s`，receiver contact 于 `1.1000197 s`，settled 未出现，故 `event_window_complete=false`。这属于科学事件删失，不是基础设施失败。
- 本次执行使用的是独立 anchor case，case ID 以 `_anchor` 结尾，而固定矩阵第 11 行是 `_held_out`。因此按预登记规则矩阵 credit 为 **0**，第 11 行仍为 `not_started`；负证据 `campaigns/core-v1/cfd/f2-dynamic-third-family-dbc-duration-anchor-canary-negative-evidence-v1.json` SHA-256 `0bba913c75b2a716b0756154239e11595feb753b428e2b4745563c5da3ff841d` 明确禁止同输入重试、阈值放宽和时域延长，并停止该 duration scope 的自动扩展。该 canary 不能升级 F2 T1，也不改变 Core registry。

## 本轮追加：F3/F4 材料 T2 CPU-only 审计

- `scripts/f3_f4_t2_cpu_source_window_audit_v1.py` 对保留的 2 个 F3 row 和 6 个 F4 case 做了只读扫描，source/trace schema、时间轴、质量闭合、reader binding 和 checkpoint integrity 均可读取；证据 `campaigns/core-v1/material/evidence/f3-f4-t2-cpu-source-window-audit-v1-20260920.json` SHA-256 `983e15aae8e1ce4df705590c7b1cc89e27a0445c8152f4a003123392e3aaa279`，报告见 `reports/F3-F4-T2-CPU-SOURCE-WINDOW-AUDIT-2026-09-20.md`。
- 固定门仍未通过：`T2_macro=false`、`T2_path=false`；F3 per-source unknown/CDF 门失败，F4 六例 unknown mass 超过 1%，事件窗均 right-censored/unresolved。该审计未启动 solver/GPU、未提交材料作业、未改历史分数、ledger 或 registry；定向审计回归 **8 passed**。

## 本轮追加：Luna Max 正式训练准入审计

- `campaigns/core-v1/learning/formal-training-admission-readiness-luna-max-20260920.json`（SHA-256 `22296075d83c4db9049329194fb60cff71b80255a88d8202cb7c4050674f34d6`）把 3 模型 × 3 seed 的正式 9 次训练固定为 admission denominator，但当前仍为 blocked：planner 看到 F3-only、`formal_release=false`、0/9 formal jobs，32 个 production case 没有显式 hard/structural audit，旧 diagnostic preprofile 不能计入正式训练，且 16-update profile 不能证明 32,000-update 容量。该记录只绑定 Luna Max/H200 metadata，未启动 optimizer/GPU、未写 ledger/registry；新增测试 **5 passed**。

## 本轮回归和队列状态

- 在所有本轮产物写入完成后重新执行完整 pytest：**1347 passed, 1 skipped**，耗时 `333.90 s`。新增 F2 runtime adapter、anchor canary negative evidence、F2 lineage contract 和材料 source/window audit 均包含在回归中。
- 持久队列当前 `succeeded=279`、`failed=11`、`cancelled=13`、`queued/running/attention=0`；q=.75 canary 的 execution receipt 已归档，未留下孤儿进程。
- `campaigns/core-v1/registry.json` SHA-256 仍为 `1ddfeda5b2d3eb142f94be4bb2cbc6f1b65271d6b77efc8b65c829b94e66b38d`。Core 完成门仍由 `core_campaign.py --lab-root . status` 计算为 `can_finalize=false`：T1 家族仍只有 F3/F4，宏观 T2 为 0，正式训练为 0，T1 和材料目标分母仍分别缺 288 个 case-run。

## 本轮追加：F1/F2 后备路径审查结论

- 后续 Luna Max 只读审查没有生成新的可准入候选，也没有启动 solver/GPU/queue 或修改 registry/ledger。F1 H1 的域扩展在 `0.6 s` 诊断窗内通过，但完整 `2.2 s` 审计在 `t=1.040011370349697 s` 发生真实 tank-wall endpoint violation；对应审计 SHA-256 为 `28b3ecc77d5a461e1cbddb3857506386f038aed12c61302151406da020c0d93`。扩大计算域不能修复物理壁面违规，不能作为新资格机制。
- F1 H2/H3/H4 仍为既有负证据（SHA-256 分别为 `929764f6808aa60b8a0c773ad520572c6e0197a34a14b14b5ccc78c5c84302a4`、`1f12baeb7dc5e866f572bb90d90899e7d0bd3d1e0c421a6632d96effd08fdf9c`、`1926289f008c5c8a5e1c95155fa501cbf3f69939a2345a3207191afa8b9a8ff1`）；现有边界配置类不再准入重试。
- F2 H2 的 static-hold 正诊断仍明确 `qualification_scope_ready=false`，不能作为动态第三机制；F3 MLS source handoff 仍是 `prepared_only`、无 qualification claim（SHA-256 `613485e2dfa0ba45421084db6bd5b0bda9a7499846cfd95dee5388fa85b3c121`）。下一步只接受全新物理/边界机制或独立 F3 source scope，禁止重复旧输入、放宽阈值或用单点诊断代替范围资格。

## 本轮追加：因果与谱系合同审计

- 新增只读审计脚本 `scripts/core_causal_contract_audit.py`，实际校验 F3 v2 与 F4 compact v2 manifest 的 schema、哈希引用、physical case／lineage split 隔离和 known-input 字段；同时对 `rollout_case` 做 AST 接口审计，确认 predictor 只接收 `previous`, `known`, `dt`，未来参考帧读取位于预测之后的 evaluator 路径，并要求 progress／rollout 回执显式声明 `future_state_inputs=false`。
- 审计证据 `campaigns/core-v1/evidence/causal-lineage-contract-audit-20260920.json` 的 SHA-256 为 `a79c093973d12a649d9e6f5e921e9b3752f8787186e9e571e12050cf02a2eab9`；两个已有跨机 A8 全时域诊断回执也通过了未来输入标记检查。该证据明确声明它不是未来 CFD 置换干预、模型质量或 CFD 资格证明。
- 新增合同测试 **2 passed**，并把哈希引用写入独立的 `campaigns/core-v1/contract-evidence.json` 索引；历史 Core registry 保持不变，SHA-256 仍为 `1ddfeda5b2d3eb142f94be4bb2cbc6f1b65271d6b77efc8b65c829b94e66b38d`。`core_campaign status` 的 `causal_lineage_contracts` 已变为 `true`，其余 Core 完成门保持原阻塞状态。

## 本轮追加：F3/F4 材料最小修复审计

- 只读 CPU 审计 `scripts/f3_f4_t2_minimal_repair_audit_v1.py` 没有发现可以直接晋级 T2 的修复；证据 `campaigns/core-v1/material/evidence/f3-f4-t2-minimal-repair-audit-20260920.json` SHA-256 为 `9a9799abd9e8f8f46b34496b61e60bf5cbab873336fb6d5c469748b72dcf4c20`，报告见 `reports/F3-F4-T2-MINIMAL-REPAIR-AUDIT-2026-09-20.md`。
- 该审计量化了下一次真正需要的工作：F3 至少补 26 个 seed，且两个 source 的 CDF 上界分别还需降低 85、83 个分母单位；F4 六例共需恢复 2796 个 seed，事件窗仍缺 3.94–4.04 s。所有 checkpoint 可用于 restart，但不能修复 permanent unknown 或补齐 CFD 事件窗。
- F4 两个修复探针的首个失败均在 frame 81（约 `0.162004 s`），64 个 seed 首先触发 reconstruction-error gate，后期还出现 support-distance failure；因此 ESS32／affine 诊断仍不能作为资格证据。定向材料回归 **83 passed**，未启动 solver/GPU、大矩阵或 registry/ledger 写入。

## 本轮追加：第三 T1 家族候选——F3 内部挡板交换

- Luna Max 形成了一个可送 root review 的独立 source scope：`F3_baffle_exchange_native_mdbc_x_v1`。它在有限槽内加入 `mkbound=1` 的固定内部挡板，使用 native mDBC/no-slip 和新的初始 x 冲量轴；相对 plain F3 MLS handoff 改变了真实边界机制、几何和输入谱系，也没有复用旧 `.04/.65/.9 s/.05 s` 探针的输入、BI4 或轨迹。
- 候选卡 `campaigns/core-v1/cfd/f3-baffle-exchange-source-scope-v1/candidate-card-v1.json` SHA-256 为 `4a0d6e07` 开头；anchor prepared SHA-256 为 `09b85018` 开头，33120 个 fluid particle，原生质量误差 `-0.862%`。固定资格矩阵 15 行、失败分母 15 行且当前分子为 0；preflight 不给资格分母 credit。
- 专用合同测试 **5 passed**。当前状态是 `candidate_handoff_root_review_only`、`qualified=false`；尚未启动 solver/GPU/queue，也未写 registry/ledger。只有 root review 和新的运行时审计通过后，才能提交一个独立 canary；单点通过也不能替代 15 行资格矩阵。

## 本轮追加：正式训练准入审计

- `scripts/core_formal_admission_audit.py` 对当前 F3/F4 production denominator 做了只读闭环，证据为 `campaigns/core-v1/learning/formal-admission-audit-f3-f4-20260920.json`，报告见 `reports/CORE-FORMAL-ADMISSION-2026-09-20.md`。64 个 production case 的 hard audit 为 **64/64**，但 structural audit 只有 **32/64**，F3 的 32 个案例缺结构审计绑定；formal audit pass 为 **32/64**。
- 准入仍为 **0/9**：T1 family 为 2（要求 3），validation 为 8（要求 12），所有 source manifest 尚未完成 `formal_release=true` 和 source closure 刷新，已有 3 个 diagnostic profile 不能计入正式训练。明确阻塞码为 `STALE_SOURCE_CLOSURE`、`FORMAL_RELEASE_REQUIRED`、`STRUCTURAL_AUDIT_GAP`、`THIRD_FAMILY_REQUIRED`、`VALIDATION_DENOMINATOR`、`RESOURCE_FRONTIER_UNPROVEN`。
- 新增及回归测试 **24 passed**；未启动 optimizer/GPU/solver/training，未写 registry/ledger。最小依赖是第三 T1 family、F3 structural audit receipt、manifest formal release/source closure 和覆盖 32,000 updates 的资源证据。

## 本轮追加：F3 挡板 runtime 兼容性阻塞

- 对 F3 baffle anchor 做了 root-review 前的 runtime 审查，没有生成 root review，也没有启动 Ada canary。该 prepared 使用 `core.f3.baffled_source_scope.preflight.v1` 的顶层 `solver_binary`、`decoder`、`generated_prefix`，而现有 `core_cfd.run`、`convert_native`、`audit` 依赖 F4 风格的 `prepared["config"]`、`recipe_id`、`wall_bounds` 等字段；直接调用会失败或产生错误审计。
- 现有 F3 audit v2 只覆盖 plain F3 wall，没有内部挡板 obstacle 和 exchange event/time contract。因此不能把 F4 runner 强行套到该候选上。候选卡、15 行矩阵、失败分母和 anchor preflight 均保持不变，专用 preflight 测试仍为 **5 passed**；下一轮最小依赖是专用 F3 baffle runner、障碍感知 hard audit 和事件窗口定义。

## 本轮最终回归（合同索引修复后）

- 完整 pytest：**1364 passed, 1 skipped**，耗时约 314 s。该回归包含因果/谱系合同、F3 挡板候选、材料最小修复审计和正式训练准入审计。
- F2 root review 保护的历史 registry 快照已恢复；`campaigns/core-v1/registry.json` SHA-256 为 `1ddfeda5b2d3eb142f94be4bb2cbc6f1b65271d6b77efc8b65c829b94e66b38d`。因果合同通过独立 `contract-evidence.json` 索引加载，不改变科学 registry。

- 在补充 contract-catalog 回归后再次执行完整 pytest：**1365 passed, 1 skipped**，耗时约 312 s；队列和 registry 状态未被测试改变。

## 本轮追加：F3 挡板 normals v2 运行时 canary

- 对 `F3_baffle_exchange_native_mdbc_x_v1` 的 normals-aware v2 版本完成了新的 root review、输入 hash closure 和唯一 Ada anchor canary。原 v1 的 `No normal data for mDBC` 启动阻塞没有重试；v2 使用 `GeometryForNormals`、`*_hdp_Actual.vtk` 和 mainlist runlist，并绑定新的 prepared revision。
- v2 solver 以 return code 0 完成完整 `0–8.35 s` native 输出，得到 836 帧，cadence 最大误差 `3.60225e-05 s`，请求时域到达。执行回执的 GPU process reservation 为 `0.078180 h`，Ada GPU 0，wall `281.448 s`，子进程 CPU `283.176 s`。
- 科学审计仍失败：`hard_integrity_pass=false`，fluid validity 不完整，外壁和内部挡板穿透；首次挡板穿透在 `0.0100356 s`，保存 chord crossing `20,990`。solver 仍报告 `26,732/131,403` fixed particles 没有 normal data，并在后期排除超过 10% 粒子。
- 事件门也失败：挡板 encounter 通过，但 forward exchange 为 `0`、reverse exchange 为 `5`，所以 `event_window_complete=false`。该结果是完整且可读取的负诊断，matrix credit、T1 注册和 registry mutation 均为 `0`；不得在相同输入上重试。
- 关键证据：prepared `f4ba57f1ceeeaa76b657acfc6f444402cf356830b4cedeb0ed0a1730bd42f17c`，root review `1df5dfacd5ccaa6df52894326bb684c4eb7b6d5b55fad64363ca6fb08b992208`，job spec `8002daa39ea1f358f7bb10ec01bb8ae5c6ec0f6afd6c420121169b05d6857bec`，execution receipt `400ce32b2ee711cdbe95e0fc9cfe0ffbcc2d9310a41efcda6b2233583808e62c`，trajectory `ed9ace54ca19d668ba11312fd7a0fce466d1887e58729fd3c56b72e116c7ab8a`，机器报告 `51e4855330f022e172a33118a95f6ecce05c3a5b913e06b2cbe2d88dbb34033e`。

## 本轮追加：F3 高 seed 材料恢复诊断

- 对 F3 row29 的两侧来源实际运行了 8192-seed（每侧 4096）quadrature canary，并故意中断后从 checkpoint resume；恢复后 5 帧、`0.040019958626 s` 窗口内 unknown 为 `0`，质量闭合误差为 `0`，但没有 first-passage 或 return 事件，因此不支持完整 CDF 或 T2 结论。
- 既有完整窗口 row29/row31 仍分别出现 per-source unknown `(0.012207, 0.009277)` 与 `(0.015625, 0.014160)`，CDF 最大误差约 `0.061035/0.060059`，超过固定 unknown `0.01` 和 CDF `0.02` 门。完整 8192-seed 窗口估计约 `11.63 h`，未启动该长任务。
- 这一步只增加恢复一致性和资源证据；未改阈值、未覆盖永久 unknown、未写 T2 registry。后续合法路径仍是同一物理输入的原生 `.002 s` CFD、匹配 frame map 和可复用空间索引，然后逐行重新评估。

## 本轮追加：F4 宏观 T2 sidecar 只读前置审计

- 对保留的 F4 material negative evidence、native004 exact-stride view、33-row overlay template 和静态 CFD evaluator 做了只读 hash-bound preflight。exact-stride view 每五帧抽取、无插值且与同一 terminal lineage 一致，因此 `sidecar_provenance_pass=true`；它不是独立 CFD，也不给 T2 credit。
- 五类保留 canary 的 unknown 最大值为 `0.84765625、0.896484375、0.923828125、0.955078125、1.0`，全部超过固定 per-source `0.01` 门；事件窗也全部 right-censored/unresolved。33-row template 仍缺 4 个 exact cadence rows、24 个 resolution overlays 和 5 个 seed-density overlays，静态 F4 evaluator `matrix_complete=false`。
- preflight 结论是 `status=blocked_for_qualification`、`T2_macro=false`、`T2_path=false`；没有打开 active H5、提交 job、启动 solver/GPU、改变历史分数、threshold、ledger 或 registry。机器证据为 `campaigns/core-v1/material/evidence/f4-macro-t2-sidecar-preflight-20260920.json`，SHA-256 `636b212081852921c209fe4b4124a99f64eac975c67b054b2fa2f48ab1172cb8`；报告 SHA-256 `7cab469476df1d926c3a01185e2af41501b2d444b4877235ee97d0ef9ccaf293`。
- 最小下一步是先在固定 reconstruction gate 的首个失效时间段做一个单 source、固定 seed 的实现修复 canary；不得提高 cap、把 unknown 重标为 reliable，或把 exact-stride sidecar 当作独立实验。

## 本轮追加：F2 static full-cup CPU/native 闭合复核

- 对既有 F2 zero-angle resting full-cup 候选的 15 个固定 cell 重新做了只读 closure audit；每行的 prepared receipt、Definition、motion、BI4、decoded directory 和 23 个声明输入均通过 hash closure，结果为 `15/15 passed`、`0 failed/unresolved`。总输入产物约 `1168.60 MiB`，最大单行约 `137.19 MiB`。
- 该审计没有重新运行 GenCase/decoder，也没有启动 solver/GPU/queue、写 ledger 或 registry。它只说明输入矩阵可执行，不提供静态轨迹或 T1 credit。已有同一候选的 cell-0 runtime smoke 已发生闭合壁 endpoint/chord crossing 负结果，因此不会把这次 preflight 当成新的 solver 许可或重复同输入运行。
- 证据为 `campaigns/core-v1/evidence/f2-static-full-cup-cpu-preflight-v1.json`，SHA-256 `6f5fbe8bef63db9f2cb64c26698bd27a3b597d03763a4995bfa71b5315010115`；报告 SHA-256 `bac7094ba4c8dab84507164a20bb9f94e80c9dc56d6c272c05a1437a886464f7`。该 scope 仍是 resting numerical F2 candidate，不能解释为动态 pouring/receiving/overflow 资格。

## 本轮追加：Luna Max 正式训练准入 v4

- F3/F4 的 64-case structural、hard 和 formal audits 现在均为 `64/64`，但正式 release 仍关闭：只有两个 T1 family、8 个 validation case，F3 manifest 仍未声明 `formal_release=true`，旧 preprofile 与当前 source closure 不一致，且 full-field graph 只有 4-update diagnostic probe。
- candidate v4 保持 `data_contract_ready=true`、`formal_training_ready=false`、`formal_job_count=0`；阻塞码为 `STALE_SOURCE_CLOSURE`、`FORMAL_RELEASE_REQUIRED`、`THIRD_FAMILY_REQUIRED`、`VALIDATION_DENOMINATOR`、`RESOURCE_FRONTIER_UNPROVEN`。4-update graph probe 的 217,086 粒子峰值 GPU 为 `579.38 MiB`，但保守 32,000-update full-pipeline 外推约 `122.90 h`，不计入正式容量证据。
- 因而 3 配置 × 3 seed 的正式训练仍为 `0/9`；不得用 CPU synthetic 32,000-update 或短 graph probe 替代真实正式 checkpoint。

## 本轮最终验证与 Core 状态

- `compileall` 通过；在本轮新增 F3 v2、F3 high-seed、F4 sidecar、F2 preflight 和 formal v4 产物后，全量回归为 **1390 passed, 1 skipped**（`317.45 s`）。
- 当前持久队列已收录 F3 v2 canary，队列计数为 `succeeded=280、failed=12、cancelled=13、queued/running/attention=0`；科学负结果和基础设施失败均保留在 attempt 分母中。
- Core registry SHA-256 仍为 `1ddfeda5b2d3eb142f94be4bb2cbc6f1b65271d6b77efc8b65c829b94e66b38d`，未发生 registry mutation。`core_campaign status` 仍为 `can_finalize=false`：T1 family=`F3/F4`，macro T2 family=`0`，formal training=`0/9`，T1 与材料目标分母分别缺 `288` 个 case-run；异机复现尚未完成。

## 本轮追加：F4 reconstruction gate interval canary

- 在固定 native004 cell-14、`q=0.5`、`dp=0.0075 m`、512 seeds、2 个积分子步和 frame `40→41`（`0.160014986128→0.164008093631 s`）上完成了有界 baseline replay。源轨迹 SHA-256 为 `91846866c177e4c3036b7ef92c33a4e0bde7d9e8993efb01dde300811b7c096e`；回放无 replay mismatch，提交到 frame 41，质量闭合，但状态为 `partial`，`unknown_fraction_max=0.25`、共同可靠路径覆盖率 `0.75`，事件窗仍 right-censored/unresolved。
- 独立诊断复现了 **128/512** 个 seed 的首个重建门失败，全部落在 frame 41；两个子步新增失败分别为 125 和 3，未改变 support cap、阈值或未知质量分母。这是实现层失败的可重复证据，不判定更深层物理根因，也没有验证修复。
- 证据与报告：`campaigns/core-v1/material/evidence/f4-reconstruction-gate-interval-canary-v1/f4-reconstruction-gate-interval-canary-v1.json`（SHA-256 `7d0a3bc520e6498ff9de26b99d458fe8f11b651cb2e9ca7e5e70f1d6398f7c97`）以及同目录 `F4-RECONSTRUCTION-GATE-INTERVAL-CANARY-2026-09-20.md`。该 canary 明确 `qualification_claim=none`、`T2_macro=false`、`T2_path=false`；未启动 solver/GPU/队列、未改 registry/ledger，也没有把有限回放计入 T2 分母。

## 本轮追加：最终回归

- 修正 interval canary 的测试契约后，完整 pytest 为 **1402 passed, 1 skipped**（`450.38 s`）；包含该有界回放的 schema、输入绑定、失败分母和只诊断语义测试。回归没有修改 registry、ledger 或持久队列状态。

## 本轮追加：F4 reconstruction gate 的有界修复诊断

- 在同一 native004、`q=0.5`、`dp=0.0075 m`、512 seeds、2 个积分子步和 frame `40→41` 上，执行了独立的 `f4_native_velocity_zoh_query_v1` 诊断。候选仅改变查询时间语义：位置在线性插值，区间起点原生速度采用 causal ZOH；邻域、support gate、未知质量分母、事件定义和全部阈值保持不变。
- 当前证据 [f4-reconstruction-gate-interval-repair-canary-v1.json](../campaigns/core-v1/material/evidence/f4-reconstruction-gate-interval-repair-canary-v1-current-20260920/f4-reconstruction-gate-interval-repair-canary-v1.json) SHA-256 为 `bfe74b66ef2517e78485f22a0a051c31f4b692f222fd80043480706849089272`；修复实现 SHA-256 为 `a6205352352fddc50e4de64bfbad90b6f519a4428edfac0e66fa40120ffd531e`。精确 replay 无 mismatch，两个子步均无 reconstruction、support 或 distance gate 失败，512/512 seeds 存活，unknown fraction 为 `0`，共同可靠路径覆盖率为 `1.0`，质量闭合。
- 这只是实现级、有界、可复现的正诊断：只提交到 `0.1640080936314531 s`，事件窗仍未完成，`T2_macro=false`、`T2_path=false`、`qualification_eligible=false`。没有启动 solver/GPU/队列，没有修改历史分数、阈值、ledger 或 registry；不能把它解释为材料资格或范围资格。

## 本轮追加：F2 H2 mDBC v5 CPU/native 输入闭合

- 新候选 `F2_H2_mdbc_static_range_qualification_v5` 由独立 materializer [f2_h2_mdbc_static_range_v5_prepare.py](../scripts/f2_h2_mdbc_static_range_v5_prepare.py) 生成。它只改变顶层液层的横向整数格点；cell 11 (`q=.75`, `dp=.0075`) 使用 `[42,29,16]`，连续几何和 native `rho*dp^3` 质量策略保持不变，并保留 v4 失败作为谱系父证据。
- 固定 15 行矩阵 [matrix-preparation.json](../campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5/prepared-20260920-v5-all/matrix-preparation.json) SHA-256 为 `d82e019cd59d26dbed6846912371062206b6e6ef4b83568537d822a9fa8f0495`：`15/15` CPU GenCase/native decode 通过，`0` failed、`0` unattempted。cell 11 第三层误差为 `0.004152671755724757`，总 native 质量误差为 `0.0036100658513640305`，mDBC normals 为 `319608/319608`，零法向为 `0`。
- 该候选仍是 `qualification_only=true`、`qualified=false`、`T1_numerical=false`，资格分子 credit 为 `0`。CPU preflight 没有读取或哈希 solver，也没有启动 solver/GPU/queue、写入 ledger 或 registry；因此它只证明输入可以进入下一次独立 runtime review，不能升级 F2 T1。

## 本轮追加：F2 H2 mDBC v5 单 cell runtime canary

- 在新的 root review、admission contract 和 hash-bound runtime adapter 通过定向测试后，只提交了固定矩阵第 11 行（`q=.75`、`dp=.0075`）一个 Ada canary。root review SHA-256 为 `e1411397f1dfe97da5feb8c5c8953ca90e09f07c90a43b0479b0e094ddf75e75`，runtime adapter SHA-256 为 `6e65078ec7756d0f485d837578dac1fd299e1ae7c0728a5f11ff4815863aa97b`，prepared view SHA-256 为 `77d2314fc2fdda38874ffa6c06ae554a156c980adc1806da81bd51b6c67985c2`。
- job `f2-h2-v5-cell11-runtime-smoke-002` 在 Ada GPU 3 上 `succeeded`，wall `33.1678 s`、GPU process reservation `0.00980549 h`、峰值显存 `566 MiB`。native 转换输出 31 帧和 56898 个流体粒子，达到 `0.6000085214 s`；结构、有限值、身份、质量、壁面 endpoint 和保存帧 chord crossing 全部通过，质量最大相对变化为 `0`。
- 证据 [runtime-canary-evidence-cell11-v1.json](../campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5/runtime-canary-evidence-cell11-v1.json) SHA-256 为 `28bb42c91cc00c293a0be7d17570cf39c6e080e66c37f86447fe5a8cbe792735`。这是完整可读取的正 runtime/hard-integrity canary，但仍是 `qualification_claim=none`、`qualified=false`、`T1_numerical=false`，矩阵 credit 为 `0`；静止保持场景事件窗为 `not_assessed`。没有扩大矩阵，没有写入 registry／ledger，也没有启动材料侧车或模型训练。
- runtime adapter、evidence collector 与 v5 preparation 的定向合同测试合计 **9 passed**。本次执行不改变 Core 门：F2 仍未获得 T1 资格，Core 仍只有 F3/F4 两个 T1 family。

## 本轮追加：A8 同机 relocated full-product reproduction 收尾

- 独立复现 receipt [independent-reproduction-receipt.json](../campaigns/core-v1/reproduction/a8-independent-relocated-v1/independent-reproduction-receipt.json) SHA-256 为 `57d7869d72f0058fbee3cbdba22c702f5640e1cb2799f545475567aea02f23e3`。它在不同 `data_root` `/home/jade/.cache/core-a8-independent-relocated-v1-20260920` 上，使用同一 hash-bound bundle 和 CPU，完成 F3 case `F3_DEV_08_a0p953125` 的完整 835 个 rollout frames（终点 `8.3500128282 s`），`future_state_inputs=false`，无科学失败分类；模型报告和 score 也已复制到项目证据目录。
- 模型 rollout 通过的是诊断级 full-product reproduction：checkpoint 是 engineering/preprofile artifact，oracle 的未来参考状态只用于完整性／评分，不能当作预测输入。此次运行在同一主机上，因此 receipt 明确 `cross_host_claim=false`；不能把它写成 H200→Ada 的跨主机复现。F4 reader manifest 中有一条选定轨迹的 declared hash 尚未重新观测，故也不扩大为全数据包科学复现。
- scope 为 `same_host_relocated_data_root_with_external_hash_bound_assets`，`independent_data_root=true`，没有启动 GPU、solver、训练、ledger 或 registry。`core_gate_status=blocked_for_full_product_release; diagnostic_model_reproduction_only`，所以 Core 的 `independent_reproduction` 仍由正式 gate 判定为 false，等待真正的跨机和完整发布条件。

## 本轮最终回归与状态

- 在加入 F2 v5 runtime adapter、canary evidence collector、同机 full-horizon reproduction 合同和相应测试后，全量 pytest 为 **1411 passed, 1 skipped**，耗时 `730.92 s`。
- 持久队列保持 `succeeded=281、failed=12、cancelled=13、queued/running/attention=0`；F2 v5 单点 canary 的成功执行已计入队列资源账本，但没有改变科学 registry。当前 registry SHA-256 仍为 `1ddfeda5b2d3eb142f94be4bb2cbc6f1b65271d6b77efc8b65c829b94e66b38d`。
- `core_campaign.py status` 仍为 `can_finalize=false`：T1 family 只有 F3/F4，宏观 T2 为 0，正式训练为 0/9，T1 与材料目标分母分别还缺 288 个 case-run；同机 relocated reproduction 不能满足独立复现 gate。新增实现和证据没有把局部成功升级成 Core 完成。

## 本轮追加：跨机模型复现合同接入

- 复核了既有 H200 端完整 835-transition MLP 复现及 relocated 端逐案例比较。模型报告 `campaigns/core-v1/reproduction/a8-independent-relocated-v1/model-reproduction-report.json` 的 SHA-256 为 `41cfedfcd858acd63023406b38044053eb8f26cf9b6ae849edb11a3d0988e006`，报告明确 `passed=true`、`full_horizon_reproduction=true`、`full_product_reproduction=true`、`cross_host_reproduction=true`，观测主机为 `a8-prior-h200-model-report` 与 `user-SYS-421GE-TNRT`，未来参考状态没有作为预测输入。
- 新增 typed wrapper `campaigns/core-v1/evidence/independent-reproduction-contract-20260920.json`，SHA-256 为 `b33efab150d35b0c0cdc36a77a88ffc8c9ec2bf1dee2c2f4b6712d465016ae84`，并将其加入独立 `contract-evidence.json`（catalog SHA-256 `73b7c10a1b4fb1c826207ea39727693a5840e2c479bd8f44a9025ec8f1ae8e51`）。中心科学 registry 未改变，仍为 `1ddfeda5b2d3eb142f94be4bb2cbc6f1b65271d6b77efc8b65c829b94e66b38d`。
- `core_campaign status` 的 `independent_reproduction` 已变为 `true`。这只接入模型级跨机复现证据；完整 F3/F4 数据包在另一台机器上的移动、外部实验真实性和 T1/T2 资格仍分别验收，不能合并解释。

## 本轮追加：F4 ZOH 材料修复路线关闭

- 在固定 F4 native004、512 seeds、2 substeps、frame 0–50 的有界 replay 上，causal ZOH 查询在 frame 40→41 全部通过，但从 frame 42 起出现 `218/512` 永久 unknown（`0.42578125`），共同可靠覆盖率降至 `0.57421875`；质量闭合仍为真。
- 观测只到 `0.2000072582 s`，事件窗仍缺 `4.1399927418 s`，因此是 right-censored；固定 unknown `0.01`、CDF `0.02` 和事件门均未改变，`T2_macro=false`、`T2_path=false`。证据 [f4-reconstruction-gate-zoh-short-canary-v1.json](../campaigns/core-v1/material/evidence/f4-reconstruction-gate-zoh-short-canary-v1-20260920/f4-reconstruction-gate-zoh-short-canary-v1.json) SHA-256 为 `84716e29db57091420e85191de731b11eadb30ac31ab2b88b41a235f57a354a9`，相关测试 **14 passed**。
- 该结果关闭“仅改变区间速度查询语义即可取得 F4 T2”的假设；没有提交 solver/GPU/queue，没有修改 registry/ledger，也没有启动长矩阵。

## 本轮追加：F2 H2 v5 批量准入审查

- 静态 H2 v5 的 15/15 CPU/native closure 和 cell-11 runtime hard-integrity canary 仍只提供 zero-credit diagnostic。root review 仅授权 cell 11，因此未把其余 8 行提交成 solver 任务；批量 review、8 个受保护 job spec、15 行失败分母和 evidence collector 已准备，但全部保持 `qualification_only`，无 solver/queue/ledger/registry 权限。
- 既有 dynamic DBC q=.75 anchor 是 event-censored，且历史证据含 ledger mutation，不能扩展成 15-row 第三 T1 family。批量审查报告 [F2-H2-MDBC-STATIC-RANGE-V5-BATCH8-ROOT-REVIEW-2026-09-20.zh-CN.md](../reports/F2-H2-MDBC-STATIC-RANGE-V5-BATCH8-ROOT-REVIEW-2026-09-20.zh-CN.md) SHA-256 为 `5d4a95e876ec99e9f5f9e9fdd08c781dd8e41b21a813ecd518280e386722fe85`。
- 因而 F2 仍没有 T1 资格；下一条第三家族主线继续放在独立动态机制或已修复的 F1/F2 候选上，而不是用静态保持场景凑家族数。

## 本轮追加：跨机 float64 frontier canary

- 在同一 F3 validation case `F3_DEV_08_a0p953125`、同一 hash-bound checkpoint/manifest、同一确定性设置下，Ada 与 H200 各完成 20 步 float64 inference canary。Ada 回执 [float64-canary.json](../campaigns/core-v1/reproduction/a8-cross-host-frontier-canary20-v2/ada/float64-canary.json) SHA-256 为 `e4e545dc3f41d4e9fdf748dfd6ebfc22b7ee36e6e1036330cee01d347719fed0`；H200 回执 SHA-256 为 `cea0b364cf0606e59b5ecf1c85799d64b8b6d7b0043a56285be9692ed065cdf9`。
- 配对比较 [paired-float64-comparison.json](../campaigns/core-v1/reproduction/a8-cross-host-frontier-canary20-v2/paired-float64-comparison.json) SHA-256 为 `b8c1ba1412abd9af112654a61cbffb53a26ac4a61d1da22e2b07d9504ea750dc`，状态 `pass`：21 帧、34560 粒子，位置最大绝对差 `2.220446049250313e-16 m`，速度最大绝对差 `6.938893903907228e-16 m/s`，零 tolerance violation。它是定位数值后端差异的诊断，不是 835 帧科学复现，也不改变 Core 训练或 T1/T2 门。
- 该 frontier 结果支持下一步优先比较 float32 与 float64 的首个 mismatch，而不是盲目更换模型或放宽评测阈值；正式训练仍需第三个 T1 family、formal release/source closure 和真实 32000-update 资源证据。

## 本轮追加：A8 跨机 root review 收紧证据边界

- 新的只读 root review [root-review-v1.json](../campaigns/core-v1/reproduction/a8-cross-host-frontier-canary20-v2/root-review-v1.json) SHA-256 为 `7c10327486f799b18d7609e6b8eeb41a3dc5210ff8fe648885437289f878fc03`。它同时核对了 Ada/H200 的真实物理主机名、互不重叠的 GPU UUID、Python/Torch/CUDA/package/module closure、20 步 float64 配对结果以及 835-transition A8 配对结果。
- root review 的决定是：`true_cross_host_canary=true`、`full_horizon_paired_diagnostic=true`、`full_product_reproduction=false`、`formal_training_count=0`。也就是说，跨机诊断和完整时域配对已经真实完成，但不能把它升级成公开产品或科学资格。
- 新 typed wrapper [cross-host-reproduction-contract-20260920.json](../campaigns/core-v1/evidence/cross-host-reproduction-contract-20260920.json) SHA-256 为 `a2a49f76ee282649227b40cc6c2388b597e53145417ec0469535c305ad4f9f79`，已替换 catalog 中较宽泛的同机/模型引用；`contract-evidence.json` 当前 SHA-256 为 `65ca8410650a3c66224b6a1e46b71c71a3ff90c3bf845e7d04b7867364cef6a3`。Core 的 `independent_reproduction=true` 现在明确表示“跨机配对诊断通过”，而不是 T1/T2 或最终发布通过。
- root review 明确 `submitted=false`、formal runs `0`、registry/ledger mutation `0`；它没有启动正式训练，也没有改变中心科学 registry。

## 本轮最终回归与当前门状态

- 在加入跨机 root-review 适配器、F2 v5 batch admission、F4 ZOH canary 和两个 typed reproduction wrapper 后，完整 pytest 为 **1424 passed, 1 skipped**，耗时 `360.86 s`。
- 跨机 agent 的正式训练 frontier 结论保持 blocked：真实 32,000-update CPU dryrun 和 4-update full-field graph probe 都不计正式容量；正式训练仍 `0/9`，没有启动正式 optimizer、没有写入 training registry。
- 持久队列仍无活动任务；当前为 `succeeded=281、failed=12、cancelled=13、queued/reserved/launching/running/attention=0`。中心科学 registry SHA-256 仍为 `1ddfeda5b2d3eb142f94be4bb2cbc6f1b65271d6b77efc8b65c829b94e66b38d`。
- 最新 `core_campaign status`：`independent_reproduction=true`、`causal_lineage_contracts=true`、`evidence_valid=true`；Core 仍未完成，原因是 T1 只有 F3/F4、宏观 T2 为 0、正式训练为 0/9，T1 和目标材料分母各缺 288 个 case-run。

## 本轮追加：F3 原生 0.002 s cadence 适配器只读预检

- 新增 [f3_native_cadence_adapter_v1.py](../scripts/f3_native_cadence_adapter_v1.py)，只读绑定真实 solver 原生 HDF5 源、prepared receipt、候选 Definition、MLS 后端和逐五帧直接抽取视图。适配器 SHA-256 为 `746477383578df5edcef927e72aaff706d8a2621ff01f435cb9d65fd425dd42e`，契约测试 **5 passed**。
- 真实源确认 4176 帧、`0–8.350012828223477 s`，原生步长中位数 `0.0019910427180569457 s`，最大区间误差 `1.3165414925133193e-05 s`，没有插值。源 HDF5 SHA-256 为 `571ddf4ba1878730ff80d20bca49361a7f3fff841f3ac618dd983894364c7e63`，lineage SHA-256 为 `fb0f7704eddb2b99ed71fdf4141cf5e3c106eceb4f871fee81cdd065fcad6d39`。
- 每五个原生帧形成的 836 帧 `.01 s` 视图只作为同一 native-.002 source 的匹配诊断，不是独立 `.01 s` CFD。选择证据 [f3-native-cadence-adapter-v1-every-fifth-selection-20260920.json](../campaigns/core-v1/material/evidence/f3-native-cadence-adapter-v1-every-fifth-selection-20260920.json) SHA-256 为 `6c2c4a1059f7b43dd7235294395e574368f8d7c3649451d45a08a22cf2da3bac`。
- 预检证据 [f3-native-cadence-adapter-v1-preflight-20260920.json](../campaigns/core-v1/material/evidence/f3-native-cadence-adapter-v1-preflight-20260920.json) SHA-256 为 `9f2bef012459cba60a6d5c62723b567a5d56496f8436bb40d7fb4bc2fc6db651`，状态为 `ready_for_bounded_canary`。它保持 unknown `0.01`、CDF `0.02`、完整事件窗和全 seed 分母，`qualification_claim=none`；没有启动 solver/GPU/queue，没有写 registry/ledger。下一步需先做 root review，再执行约 5 帧的可恢复 bounded canary，不能把现有预检或历史长跑直接升级成 T2。

## 本轮追加：正式训练资源前沿审查收尾

- formal release frontier 只读审查已刷新当前 source closure；`admission-audit.json` SHA-256 为 `de0d9a2662533eb5e707a4ef4054700122dea27bd75a60d18e39b9e2a812a4b4`。新的 `core.formal_capacity_evidence.v1` 适配器只有在真实 CUDA/full-field `core.training.v1` 回执、当前 closure、released manifest、双增量模型适配器和 `8000/16000/24000/32000` 检查点全部绑定时才会计入容量证据。
- 当前仍为 `formal_training_ready=false`、`formal_job_count=0`、`formal_runs_counted=0`、capacity `bound=false`。保留的 4-update full-field graph probe 和 CPU synthetic 32000-update 都继续是诊断证据，不能替代正式训练；Ada 诊断路径对 32000 update 的约 `122.9002 h` 外推也不构成容量证明。
- 阻塞码仍为 `STALE_SOURCE_CLOSURE`、`FORMAL_RELEASE_REQUIRED`、`THIRD_FAMILY_REQUIRED`、`VALIDATION_DENOMINATOR`、`RESOURCE_FRONTIER_UNPROVEN`。本审查没有启动 optimizer/GPU/training，也没有写入 training registry 或中央 ledger；定向容量与 admission 测试已通过，正式 9-run 矩阵仍保持 `0/9`。

## 本轮追加：F1 悬空障碍物第三家族候选卡

- 新增 F1 物理几何 scope `F1_suspended_obstacle_gap_v1`：固定障碍物从槽底抬高 `0.06 m`，形成真实流体通道，保留 gravity-driven approach/split/rejoin、native mDBC 和 no-slip 语义。该 scope 与已耗尽的贴底 H1–H4 接触拓扑不同，也不与 F3 挡板交换或 F4 落池机制合并计数。
- anchor CPU/native preflight 已通过：`120658` fluid、`142446` boundary、zero normals、zero exact fluid-boundary overlap、六个障碍物面符号通过、gap geometry 通过；只覆盖 `q=.5, dp=.0075` 一个输入点，仍无 solver/event credit。
- 候选卡 [candidate-card-v1.json](../campaigns/core-v1/cfd/f1-suspended-obstacle-gap-scope-v1/candidate-card-v1.json) SHA-256 为 `e419ab8acc78861e17e8ea8f672358c1819f918bb997813ce7edf4b23f098978`；固定 15 行矩阵 [fixed-matrix-v1.json](../campaigns/core-v1/cfd/f1-suspended-obstacle-gap-scope-v1/fixed-matrix-v1.json) SHA-256 为 `136151eafbec649f4361e5a8416efa70adbced9cf58221e2d025c2f8673d9f4d`；失败分母 [failure-denominator-v1.json](../campaigns/core-v1/cfd/f1-suspended-obstacle-gap-scope-v1/failure-denominator-v1.json) SHA-256 为 `7aa6afe3659133a2478172873159266f9cb69b2d51b0df6fddfd6a793eeb0d8e`，15 行目前全部 `unattempted`，credit 为 `0`。
- 受保护 anchor job spec [protected-anchor-job-spec-v1.json](../campaigns/core-v1/cfd/f1-suspended-obstacle-gap-scope-v1/protected-anchor-job-spec-v1.json) SHA-256 为 `7cf6d8028aba1862adef3201847484d09f663c69b57536262a3feb98e0aee469`，明确 `solver_launch=forbidden_until_root_review_approval`、queue/ledger/registry mutation 为 false。当前仍是 root-review-only，尚未提交 solver；只有 anchor 的 hard integrity 与完整事件窗均通过后，才可决定是否运行整套 15 行资格矩阵。

## 本轮追加：正式 release candidate v2 与容量证据边界

- release candidate [release-candidate.json](../campaigns/core-v1/learning/formal-release-frontier-v2/release-candidate.json) SHA-256 为 `62100ec4f23a8ee6b8fe89e3bfe26f873319f5430be5ebf72a928a31800c653b`。它把真实 full-field CUDA 32000-update receipt、四个 milestone checkpoint、当前 source closure、正式 release manifest、Core dual-increment model adapter 和资源指标设为硬准入条件。
- 当前容量适配器 [capacity-evidence-from-1000-pilot.json](../campaigns/core-v1/learning/formal-release-frontier-v1/capacity-evidence-from-1000-pilot.json) SHA-256 为 `6e4641eee0eb02ba2cad8e8677ecde66e992c9891424a12181db28e5b0b5a32d`，明确 `formal_capacity_evidence=false`、observed frontier `1000`、formal runs `0`。4-step graph probe 和 synthetic 32000-update 不能计入容量证明；当前五个阻塞码保持不变。
- 本轮 formal focused tests **36 passed**；没有启动 optimizer/GPU/training，registry/ledger mutation 为 `0`。因此正式 9-run 矩阵仍为 `0/9`，不会因为资源估算或旧诊断文件存在而提前开放。

## 本轮追加：F1 G1 动态 anchor 负结果与失败分母保留

- 在 root review [root-review-v1.json](../campaigns/core-v1/cfd/f1-suspended-obstacle-gap-scope-v1/root-review-v1.json)（SHA-256 `0a78f497a48138832e43a18a96f0880d34a732f4e9f2fbd6ed6a2b5dee9b6855`）批准的唯一 `q=.5, dp=.0075` anchor 上，Ada solver code 0 完成 `0–2.200017615565436 s`、111 帧、120658 fluid particles。运行 job spec SHA-256 为 `22deb3fc1a8871b69f92aae0dfbdba326dffeae0104cb8ce93760dcce1cf8652`，队列回执保留在 attempt 目录。
- 事件观察窗完整（approach/downstream/return contract 通过），但 hard integrity 失败：84 个 closed-wall endpoint particle-frames、615 个 obstacle-penetration particle-frames、1700 个保存帧 chord crossings；结构审计报告 `lifecycle:closed_transition`，最终有效粒子 `120577/120658`。因此该 scope 的 anchor 是可读取的科学负结果，不能进入 T1 分子，不能扩展到 15 行矩阵。
- 负证据 [f1-suspended-obstacle-gap-g1-anchor-negative-evidence-v1.json](../campaigns/core-v1/evidence/f1-suspended-obstacle-gap-g1-anchor-negative-evidence-v1.json) SHA-256 为 `d9bd24ead4064b1e4f87aa8194be668370b0a3648835309791399ae3194a37e2`，由 [f1_suspended_obstacle_gap_negative_evidence_v1.py](../scripts/f1_suspended_obstacle_gap_negative_evidence_v1.py)（SHA-256 `fae202f9cf1424068e43bece5643dc472a08b6830ba5584fa71ace627cd2e3df`）收集；它明确 `T1_numerical=false`、`matrix_credit=0`、science failure 而非 infrastructure error，且 registry/ledger mutation、材料侧车和训练均为 0。相同输入不重试，15 行失败分母保持 `executed=0`，后续第三家族需另立物理／边界机制。

## 本轮最终回归与当前门状态

- 在加入 F1 root-review runtime lock、G1 negative-evidence collector、F3 native cadence preflight、formal capacity adapter 和对应测试后，全量 pytest 为 **1437 passed, 1 skipped**，耗时 `333.66 s`。
- F1 G1 anchor 已作为一条科学失败写入持久队列分母：`succeeded=281、failed=13、cancelled=13、queued/reserved/launching/running/attention=0`。本次失败有完整 solver/native/HDF5/observations/audit 产物，属于 hard-integrity failure，不是基础设施缺失。
- 中央科学 registry SHA-256 仍为 `1ddfeda5b2d3eb142f94be4bb2cbc6f1b65271d6b77efc8b65c829b94e66b38d`。`core_campaign status` 仍为 `can_finalize=false`：T1 家族只有 F3/F4，宏观 T2 为 0，正式训练为 0/9，T1 与材料目标分母各缺 288 个 case-run；跨机配对诊断和因果谱系合同保持通过。

## 本轮追加：F3 原生 cadence bounded canary 恢复通过

- 在 root review [f3-native-cadence-adapter-v1-root-review-20260920.json](../campaigns/core-v1/material/evidence/f3-native-cadence-adapter-v1-root-review-20260920.json)（SHA-256 `29d290763bbe93448af4b2fb4dae680f7e06b2d4711a4ba6b9401ab85a91960a`）约束下，运行 512 seeds、4 substeps、4 个 native `.002 s` intervals；第一次在已提交 frame 2 后按协议中断，第二次用同一 lineage `--resume` 完成 5 帧到 `0.04001995862593706 s`。
- 恢复产物保持 `unknown_fraction_max=0`、共同可靠路径覆盖率为短窗诊断值、质量闭合，checkpoint generation 和 HDF5 输出均可读。cadence adapter receipt [trace.cadence-adapter.json](../campaigns/core-v1/material/derived/f3-native-cadence-bounded-canary-v1/trace.cadence-adapter.json) SHA-256 为 `8b4dad9882778d70f8bc4e24a6382cde15b24e250bccd790a8febab7d87b5d79`；汇总 trace SHA-256 为 `29ee87b6a1cb7c0c77e7225e13a42b3801a693f897b1e6bb0d86f5eb5b1b7fe1`。
- 负责任的解释记录在 [f3-native-cadence-bounded-canary-evidence-v1.json](../campaigns/core-v1/material/evidence/f3-native-cadence-bounded-canary-evidence-v1.json)（SHA-256 `34873b663379b7ac659ff1d0c142367b3df9a1b7548f133dbbc0e764945dc634`）：这是 source cadence、checkpoint/resume 和当前 MLS 后端的正诊断，不是完整事件窗、CDF、T2 或材料资格。该过程没有 solver/GPU/queue/ledger/registry mutation，也没有把短窗结果放入 acceptance 分母。

## 本轮追加：F2 动态第三家族 root-review 关闭

- Luna Max 对 F2 dynamic third-family candidate 做了只读审查，定向合同测试 **9 passed**、`py_compile` 通过；candidate、15-row matrix 和 failure denominator 均仍为 `0/15`、全部 `not_started`、anchor credit `0`。相关 runtime SHA-256 为 `cf381aad39ba69925b3cd43367e4d23b267e6462a94945abfdcdddc4a427d889`，candidate 为 `bf7ee6e0fe4c45f597e65ba66d4b5ebbdea0772c5d73ecf532cad45a3199814c`，matrix 为 `cf356f1cf7d0b02474ce7e6d215a9ff07eea0d6293aca5c87799014367c5dcf1`。
- 该路线本轮不能批准新的 anchor：历史已有一次同候选执行，证据 [f2-dynamic-third-family-dbc-duration-anchor-canary-negative-evidence-v1.json](../campaigns/core-v1/cfd/f2-dynamic-third-family-dbc-duration-anchor-canary-negative-evidence-v1.json) SHA-256 `0b213c75ba2b716b0756154239e11595feb753b428e2b4745563c5da3ff841d` 显示 hard integrity 通过但事件窗未完成、settled 未判定，且历史 execution controls 已发生 solver/GPU、queue/ledger mutation。它只能作为 event-censored negative evidence，不能重跑、不能计入 15-row 分母，也不能凭“未登记”重新授权。
- 现有 root review 还同时授权了 formal held-out row 和 anchor，缺少 exact-one-row、matrix index、全量 candidate/matrix/failure/prepared/runtime/tool hash binding，且 queue/ledger/solver/GPU 权限与当前只读审查目标冲突。后续若要继续 F2，必须换成新的预注册物理假设和 case identity，并先补齐强 hash-bound root-review lock。

## 本轮追加：F2 接液/溢流堰第三家族候选设计

- Luna Max 完成了新的 F2 物理路线设计：固定上游连续液库在重力下越过有限高度内堰，进入同一封闭外槽内的下游接液区。该机制没有旋转杯、DBC duration、悬空障碍物、F5 波源或 run-up 测线，q 只改变堰高 `0.20+0.12q m`，因此与已有失败谱系保持独立。
- 最终只绑定 `generated_v4` 的 anchor 输入。v1、v2、v3 的离散初始质量误差约为 `+6.35%`、`+6.48%`、`+6.35%`，超过预登记 3% gate，全部排除且 zero credit。v4 的 GenCase/BIFileInfo/native decode 通过：`228480` fluid、`245667` boundary、`474147` total、zero normals、native IDs 唯一且数组有限；连续源质量 `96.768 kg`、native 质量 `96.39 kg`、相对误差 `-0.00390625`。
- 15 行资格矩阵已经冻结（13 个空间研究格，加中心的 internal-time 与 native-output 对照），但当前仍为 `executed=0`、`passed=0`、`event_censored=0`、`unattempted=15`、`matrix_credit=0`。CPU/native preflight 不提供 T1 credit，也没有 materialize 生产矩阵。
- root-review-only spec 明确 `submit_allowed=false`、`solver_launch=false`、`gpu_launch=false`、queue/ledger/registry mutation 均为 `0`，并绑定 candidate、matrix、failure denominator、lineage、preflight 及 v4 XML/BI4/log 的 hash。当前唯一 blocker 是尚无经 root 审查的 receiver/crest runtime adapter 和 crest-crossing/receiver-contact observer；该候选不能算第三个 T1 family。
- 证据目录：[F2 receiver overflow weir scope](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-receiver-overflow-weir-scope-v1)，报告 [CORE-F2-RECEIVER-OVERFLOW-WEIR-CANDIDATE-2026-09-20.zh-CN.md](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-receiver-overflow-weir-scope-v1/reports/CORE-F2-RECEIVER-OVERFLOW-WEIR-CANDIDATE-2026-09-20.zh-CN.md)。候选卡 SHA-256 为 `7820661d6e2921137c3e6fc3306e2312ec5f9e532dd0233c5f88325434e26abc`，15 行矩阵为 `c90ee044c3e7305fcc9a94326eaf49f9ec1ffc8c5da4a149effdb68cab3b628e`，failure denominator 为 `ff8a1443ea4d8075bf75e51be5a0bc84dded62f7dc1a834ba79736635d7d0a1f`，preflight 为 `b1507eca9120d85a6ea620d7be2c42321b3eff3deb29267be25f6fcc00d45127`，root spec 为 `5e37e66b7f9b4c0bd3dede5228c7688a0fdbed18a524475e9a80ca6b2b8483f2`。

## 本轮最终回归与当前门状态

- 新增 F2 候选契约测试后，包含 F1/F3/F2/formal 相关合同的定向回归为 **10 passed**；它验证 15 行分母、v4 preflight、root-review-only 状态和所有关键 hash binding。
- 持久协调器仍在运行但没有活动任务；队列为 `succeeded=281、failed=13、cancelled=13、queued/reserved/launching/running/attention=0`。中央科学 registry SHA-256 仍为 `1ddfeda5b2d3eb142f94be4bb2cbc6f1b65271d6b77efc8b65c829b94e66b38d`。
- 当前 `core_campaign status` 仍为 `can_finalize=false`：T1 家族只有 F3/F4，宏观 T2 为 `0`，正式训练为 `0/9`，T1 与材料目标分母各缺 `288` 个 case-run。新的 F2 候选只推进了第三家族的可审计设计和输入前置条件，没有改变完成门，也没有启动正式 solver、材料或训练工作。

## 本轮完整回归

- 在候选测试加入后执行全量 pytest：**1439 passed, 1 skipped in 420.16 s**。没有启动 solver/GPU/queue 作业，也没有改变 registry、ledger 或完成矩阵。

## 本轮追加：F2 receiver/crest adapter 合同

- 为解除候选的唯一设计 blocker，新增只读 [core_f2_receiver_overflow_weir_v1.py](../scripts/core_f2_receiver_overflow_weir_v1.py)。它验证 v4 native 输入、15 行固定分母、zero-credit 资格策略和版本化 root-review hash closure，并提供纯函数形式的 crest-crossing、receiver-contact 与持续接液 observer。它不调用 solver/decoder，不读取未来真值，也不写 queue、ledger 或 registry。
- adapter contract preflight [adapter-contract-preflight-v1.json](../campaigns/core-v1/cfd/f2-receiver-overflow-weir-scope-v1/adapter-contract-preflight-v1.json) SHA-256 为 `157a0f99a5ca79a3f90d6ee8d6e6f7c6dd9330093113b2b2898f6779e2cdfc7a`；adapter SHA-256 为 `cb21fffbf8de336361e451504e1ea81f580250680d124b1847d0fffc74673721`。新的 [root-review-only-job-spec-v2.json](../campaigns/core-v1/cfd/f2-receiver-overflow-weir-scope-v1/root-review-only-job-spec-v2.json) SHA-256 为 `94d645b571e723515bbb60adee32e726f8bd097012deb8bc290e834a9ef029f8`，只记录 adapter 已实现，仍禁止 runtime preparation、solver、GPU 和 queue。
- adapter 与候选契约定向测试为 **4 passed**，包含 synthetic crossing/contact 语义和篡改拒绝。它仍没有产生任何物理轨迹或 T1 credit；下一步仍需 root review 明确批准唯一 protected anchor，之后才能准备 runtime 输入。

- adapter-only root review [root-review-adapter-contract-v1.json](../campaigns/core-v1/cfd/f2-receiver-overflow-weir-scope-v1/root-review-adapter-contract-v1.json) SHA-256 为 `742e41517ad20ae679a4f435af763e83a2c75f2a3462d7eb748f20a5f3c01f69`。它只批准静态合同与纯 observer 定义，明确 `authorized_anchor=false`、`authorized_runtime_preparation=false`，solver/GPU/queue/ledger/registry 全部禁止；因此下一步仍是实现并审查 solver-integrated prepared manifest 和内部堰 hard audit。

## 本轮完整回归更新

- 在 adapter 合同、v2 root-review spec、adapter-only root review 和对应测试全部接入后，定向回归为 **5 passed**；上一轮全量 pytest 为 **1442 passed, 1 skipped in 375.64 s**。本次只新增静态 root-review 证据和一个合同测试，未启动 solver/GPU/queue，也没有改变 registry、ledger、科学失败分母或 Core 完成矩阵。

## 本轮追加：F2 proposal-only runtime manifest 与有限堰 HDF5 审计

- 在 adapter-only root review 明确 `authorized_runtime_preparation=false` 后，root 直接实现了 [f2_receiver_overflow_runtime_v1.py](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/scripts/f2_receiver_overflow_runtime_v1.py)。它只做 hash-bound v4 native 输入探针、有限外槽／内部堰几何记录、proposal manifest 生成，以及对未来 HDF5 trajectory 的有限墙、内部障碍物、保存帧 chord crossing、有限值、身份和质量闭合审计。它没有 solver submit 入口；临时 decoder 目录也不会写入可复用 manifest。
- [runtime-prepared-proposal-v1.json](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-receiver-overflow-weir-scope-v1/runtime-prepared-proposal-v1.json) SHA-256 为 `98f63576ef981dd554ed8dd9a1103d56334c154dd622893f877e9d88dffb535e`，实现 SHA-256 为 `b3b18d275f16cb71bfe59c2383433f00b712d4e5486b600ef49ee2b6acb360fa`。proposal 状态为 `prepared_proposal_not_runtime_authorized`、`qualification_claim=none`、`matrix_credit=0`，solver/GPU/queue/ledger/registry 均为未调用或零；它继续绑定 candidate、15-row matrix、failure denominator、lineage、v4 preflight/native、v2 root spec 和纯 observer adapter，并保留 `root_review_required=true`。
- [anchor-job-proposal-v1.json](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-receiver-overflow-weir-scope-v1/anchor-job-proposal-v1.json) SHA-256 为 `0dccdeb7d5b445ccd9176bdf0d824185d4b1eff93f2bdb3ece95ce4d703703ca`。它是 `proposal_only_not_submitted` 的单 anchor 描述，`argv=[]`、`submit_allowed=false`、solver/GPU/queue/ledger/registry mutation 全部关闭；它不是持久队列任务。
- 新增 runtime proposal、job proposal 和 synthetic HDF5 hard-audit 合同测试，定向回归 **8 passed**。测试覆盖跨堰事件、持续接液、有限墙与内部堰几何、质量闭合、临时路径不泄漏和禁止提交语义。没有启动 solver/GPU/queue，也没有改变 registry、ledger、失败分母或 Core 完成矩阵；F2 仍为 `0/15`、zero credit，T1 family 仍只有 F3/F4。

## 本轮追加：F2 receiver/overflow exact-one-anchor 实际运行与负证据

- proposal-only 链路完成后，新增 [f2_receiver_overflow_solver_v1.py](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/scripts/f2_receiver_overflow_solver_v1.py)，实现 exact-one-row root review、hash-bound `core.cfd.job.v1`、单 CUDA worker、原生转换和 receiver/weir HDF5 hard audit。实现 SHA-256 为 `165adff2ad20070d817549699ced10a3e56e32db3c6e311c4f212bb402556e78`；solver worker 定向测试与 proposal 测试合计 **11 passed**（含后续负证据 collector）。
- [root-review-one-anchor-v2.json](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-receiver-overflow-weir-scope-v1/root-review-one-anchor-v2.json) SHA-256 为 `cfb561d4fe8f542bb46088624cd2a42d49df5bfd19bbbd73bda910df34511ccf`，只授权 row 4（`q=.5, dp=.0075, spatial`）；registry 和 matrix mutation 禁止，`matrix_credit=0`。首个 job 因 worker 字段查找错误在 solver 启动前失败，失败 receipt 保留；v2 job 明确 `retry_of` 并作为一次基础设施重试提交。
- v2 anchor 完成实际 Ada solver：151 帧至 `1.500016 s`，solver `84.260696 s`，队列 wall `313.262003 s`，峰值采样 GPU `558 MiB`、峰值采样进程树 RSS `2035.25 MiB`，trajectory SHA-256 `fe337808de19c091ebfbc1ae4bdc76ad3e4607d9c32f3ac8c6900e02589c66a6`。它是可读取的科学负结果：`hard_integrity_pass=false`，`74` 个 closed-wall endpoint particle-frames，`1,490,604` 个内部堰 penetration particle-frames，`1,490,609` 个保存帧 chord crossings，质量最大相对变化 `0.0004989495798319865`；注册时域通过，但 crest crossing 未观测到，事件不完整。receiver contact 在 `0.4100556764 s` 达到 1%，持续接触 `1.0899899818 s`。
- 负证据 [f2-receiver-overflow-weir-anchor-negative-evidence-v1.json](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/evidence/f2-receiver-overflow-weir-anchor-negative-evidence-v1.json) SHA-256 为 `844bb4c6e41b1000205b875d8efd540dd8c0438131c74f1b2324168cdb53d608`；终态 matrix [terminal-matrix-v1.json](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-receiver-overflow-weir-scope-v1/terminal-matrix-v1.json) SHA-256 为 `8089ceb988ee8ed0e51bfb135939affe237741478f368cf7d6acc4f1367e12e4`，记录 `executed=1, failed=1, event_censored=1, unattempted=14, credit=0`。原始 preregistered matrix 未原地修改，其余 14 行未启动；不把该负结果计为第三 T1 family。

## 本轮追加：材料 T2 与模型因果接口并行推进

- 材料 agent 复用现有 F3/F4 source-window 和修复证据，新增 [F3-F4-T2-MINIMAL-REPAIR-AUDIT-2026-09-20.zh-CN.md](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-F4-T2-MINIMAL-REPAIR-AUDIT-2026-09-20.zh-CN.md) 与 [f3-f4-t2-minimal-repair-audit-20260920.json](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/material/evidence/f3-f4-t2-minimal-repair-audit-20260920.json)。receipt SHA-256 `9a9799abd9e8f8f46b34496b61e60bf5cbab873336fb6d5c469748b72dcf4c20`；它量化 F3/F4 仍需合法可靠路径、CDF 和完整事件窗的缺口，未启动 solver/GPU/queue，`T2_macro=false`、`T2_path=false`、zero credit；定向材料测试 **19 passed**。
- 模型 agent 修复 `KnownInputs` 的递归因果边界，拒绝大小写和下划线变体的 `future_state`、`future_velocity`、reference/target state 与 trajectory 键，同时保留合法 `reference_density_kgm3` 元数据。新 receipt [core-interface-causal-contract-repair-20260920.json](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/learning/core-interface-causal-contract-repair-20260920.json) SHA-256 `df509e10f73f209064e4fcb98d82b1d40c1d7d20dcea3b3bfc73300180f0d7b0`；实现 `core_contract.py` SHA-256 `57ffb15cea1e9a8510a5c66b2ef11fec9214c8416ab574f286cee16ebded3523`。因果/模型/learning 定向测试已通过，formal training 仍为 `0/9`，旧 preprofile 的过时 source closure 被明确拒绝，不会借修复自动升级正式训练准入。

## 本轮最终回归与门状态

- 在接入 F2 exact-one-anchor worker、负证据 collector、材料最小 T2 审计和 KnownInputs 因果修复后，完整 pytest 为 **1451 passed, 1 skipped in 1814.32 s**。F2 新增合同/负证据定向测试为 **11 passed**；formal readiness 旧 receipt 的过时 source closure 被显式检测并通过新 repair receipt 绑定，未覆盖旧证据。
- 持久队列无活动任务：`succeeded=282、failed=14、cancelled=13、queued/reserved/launching/running/attention=0`。累计 completed process reservation `110.822604 h`、设备占用并集 `75.484802 h`、CPU children `122.414944 core-h`；这些是执行账本读数，不是科学完成判据。F2 v2 anchor 的 queue success 是“worker 完成并生成负证据”，不是资格通过。
- 中央 registry SHA-256 仍为 `1ddfeda5b2d3eb142f94be4bb2cbc6f1b65271d6b77efc8b65c829b94e66b38d`，本轮没有 registry mutation。最新 `core_campaign status` 仍为 `can_finalize=false`：T1 family 只有 `F3/F4`，宏观 T2 为 `0`，正式训练为 `0/9`，T1 与材料目标分母分别缺 `288` 个 case-run；`independent_reproduction=true`、`causal_lineage_contracts=true`、`evidence_valid=true`。

## 本轮追加：bundle 相对 manifest 的可移植性修复

- `scripts/core_package.py` 现在把相对 manifest 路径统一解析为显式 `data_root/<manifest>`，与 `open_dataset()` 和 reader preflight 的路径语义一致。这样从不同当前工作目录构建 bundle 时，不会意外读取调用目录下的同名 manifest。
- 新增跨当前目录构建、bundle 搬迁后 verify 的回归覆盖；修复 receipt [core-package-relative-root-repair-20260921.json](../campaigns/core-v1/learning/core-package-relative-root-repair-20260921.json) SHA-256 为 `2fa27072e93c2fd4dd3e9f044c0531176ff18cc683e10aa411c141aa3362f4a9`，报告 [CORE-PACKAGE-RELATIVE-ROOT-2026-09-21.md](CORE-PACKAGE-RELATIVE-ROOT-2026-09-21.md)。相关 package/benchmark/contract 回归为 **26 passed**。
- 该修复只改变读取路径解析和可移植性验证；没有启动 solver、材料、optimizer 或 GPU 训练，没有写入科学 registry/ledger，也不改变当前 Core 门状态。正式训练仍 `0/9`，T1/T2 分母仍不完整。

## 本轮追加：F2 submerged-orifice 新机制合同

- 为继续寻找真正独立的第三家族，新增 `F2_submerged_orifice_transfer_v1`：静止上游液库通过固定上闸板下方的低位 submerged aperture 向下游接液区输运。`q` 只改变开口顶高 `0.10 + 0.16q m`，不复用 receiver/weir、旋转杯、悬空障碍物或 F3 impulse 输入。
- 已冻结 15 行矩阵、完整失败分母、谱系澄清和 root-review contract；当前 `15 planned / 0 executed / 0 credit`，没有新的 Definition/native BI4、trajectory、solver 或 queue 任务。契约报告 [F2-SUBMERGED-ORIFICE-ROUTE-2026-09-21.zh-CN.md](F2-SUBMERGED-ORIFICE-ROUTE-2026-09-21.zh-CN.md) 记录所有 hash 和下一步限制；经过几何绑定修订后的候选卡 SHA-256 为 `0726648a24db7b0889870b7c35f852503dca42288cf88cd780408eb1167fac1d`，固定矩阵为 `d3a275b6e6dc130bdf249f6d01a69d54c7f651831dd6a6ea289f70fd18c916eb`，合同测试 **4 passed**。
- 这只是新的 root-review-only 设计，不能计为 T1。若后续批准，下一步最多准备一个 `q=.5, dp=.0075` 的全新 CPU/native anchor，并重新审查输入质量、墙面和事件完整性。

## 本轮追加：F2 submerged-orifice root review 与 CPU/native 负前置结果

- 独立 root review [root-review-cpu-preflight-v1.json](../campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/root-review-cpu-preflight-v1.json) SHA-256 为 `df130049034494078a2fc780ac90d6afb19052ac34391b42d71f4be153391a9e`。它重新核对 15 行矩阵、失败分母、谱系、候选和适配器 hash，确认旧 Definition/BI4/trajectory 未复用；只授权一个 `q=.5, dp=.0075` 的 CPU GenCase/native decode，solver/GPU/job/queue/ledger/registry 全部关闭。
- 新 Definition/GenCase/native decode 实际完成，但 preflight 被 `BoundNor` 硬门拒绝：264,228 个 boundary 粒子中有 63,161 个零法向（23.9%）。质量相对误差 `0.78125%`、ID 唯一、数组有限、外壁端点和闸板穿透均通过。preflight [preflight.json](../campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/anchor-q0p5-dp0p0075/preflight.json) SHA-256 为 `a29673207eba9cf2d3e62ad3693a0224b749e3cdfc95a9c50eb5733d375837dc`，因此没有 solver/event 结果、T1 credit 或 matrix credit。
- 该结果把第三家族当前阻塞具体化为新版本化的法向/几何 contract；不得在同一 anchor 上重试或放宽法向门。相关 CPU/native preflight 测试 **7 passed**，Core 门仍为 T1 `F3/F4`、宏观 T2 `0`、正式训练 `0/9`。

## 本轮追加：统一 phase-plan 与固定评测分母

- `scripts/core_benchmark.py phase-plan` 现在以显式 `data_root` 解析 manifest，并按 `verify → inspect → train → rollout → evaluate → reproduce` 输出统一阶段合同；train/rollout/evaluate 的委托入口在 `core_learning.py` 中使用同一相对路径语义。
- 对每个登记案例，分母固定为 `expected_frames = len(time)-1`、轨迹帧数为 `expected_frames+1`。失败、提前失稳或缺帧不能删减该分母；phase-plan 只读时间轴，F3 32 例均为 835 个 future transition、836 帧轨迹，缺失分母为 0，读取 state frame 数为 0。
- 回执 [core-phase-plan-denominator-receipt-20260921.json](../campaigns/core-v1/learning/core-phase-plan-denominator-receipt-20260921.json) SHA-256 为 `f0da900c30c42fae7709bc7d179da31df9f753f2291f1fe042c2b2ef7f3fc71f`；phase-plan/cross-cwd/学习和评测相关回归 **52 passed**。该改动没有启动 optimizer/GPU/solver，也没有写 registry/ledger；正式训练仍 `0/9`。

## 本轮追加：F4 qualified source 的材料 CPU-only bounded preflight

- 对 T1 已 qualified 的 `F4_resting_pool_laminar_tallwall120_x_v1` cell-14 原生轨迹执行了固定 baseline24 可见邻居 Shepard sidecar。512 个 seed 使用相邻 native frame 的线性 `x/v` 插值、每个 native interval 两个 RK2 子步，并从 frame 20 恢复到 frame 70；源轨迹没有 stride、合成 cadence 或未来真值读取。
- 结果为明确负 canary：committed frame/time `70 / 0.280007101649063 s`，质量闭合为真；511/512 seeds 失效（首次 reliability loss 在 frame 41，`0.1640080936314531 s`），unknown `0.998046875`，共同可靠路径覆盖率 `0.001953125`，事件窗 `right_censored_or_unresolved`。固定 unknown 门 `0.01` 不通过，因此 `T2_macro=false`、`T2_path=false`、credit 为 0。
- 回执 [f4-tallwall120-native-cell14-material-preflight-20260921.json](../campaigns/core-v1/material/evidence/f4-tallwall120-native-cell14-material-preflight-20260921.json) SHA-256 为 `f5e6dc499e19349324799f36a154b5bfc7c6bb9be03b0c0e9df27a4acd7fc9bf`；报告 [F4-TALLWALL120-MATERIAL-PREFLIGHT-2026-09-21.zh-CN.md](F4-TALLWALL120-MATERIAL-PREFLIGHT-2026-09-21.zh-CN.md) SHA-256 为 `5cb367d06e2940d4945305f870a6e72c0aabec49ee77de88d4a9b606f5efc5f9`；针对性测试 **4 passed**。该结果没有启动 solver/GPU/queue，没有修改 registry/ledger 或材料分母，不能把 F4 计为宏观 T2。

## 本轮集成回归与状态

- phase-plan、学习/评测、package portability 相关回归 **52 passed**；F2 submerged-orifice scope/preflight **7 passed**；F4 材料 preflight **4 passed**；新增脚本均通过 `py_compile`。此前完整回归仍为 **1451 passed, 1 skipped**，本轮没有发现回归失败。
- 新增只读 formal-readiness audit：它把 phase-plan、F3/F4 admission 观察、Core completion status 和 live evaluator penalty 绑定到同一份阻塞报告。回执 [core-formal-readiness-audit-20260921.json](../campaigns/core-v1/learning/core-formal-readiness-audit-20260921.json) SHA-256 为 `2553c81ea57ded94a9419bd09a2567f4b16203e4d390b80a36d34ee710ff69f6`，测试 **3 passed**；阻塞码为第三 T1 family、12 validation denominator、9 formal runs 和 288 material case-runs，审计自身没有发出 formal job。
- 持久协调器 PID `2809995` 仍在运行，当前队列 `succeeded=282、failed=14、cancelled=13、queued/reserved/launching/running/attention=0`。科学 registry SHA-256 仍为 `1ddfeda5b2d3eb142f94be4bb2cbc6f1b65271d6b77efc8b65c829b94e66b38d`。
- 最新 `core_campaign status` 仍为 `can_finalize=false`：T1 家族只有 F3/F4，宏观 T2 为 0，正式训练为 0/9，T1 与材料目标分母各缺 288 个 case-run；跨机复现、因果谱系和证据有效性仍为 true。F2 的新法向失败和 F4 的材料负 canary 都保留为可审计失败证据，不被计作资格或训练分母。

## 本轮追加：F2 submerged-orifice BoundNor 分区根因与 v2 修复合同

- 对失败 anchor 的现有 `*_Bound.vtk` 做了只读分区审计，没有读取或复用 Definition/BI4，也没有调用 decoder、GenCase、solver、GPU、queue、ledger 或 registry。全局 `264,228` 个 boundary 粒子中有 `63,161` 个零法向（23.9040%）；其中 Mk17 外壁为 `43,526/226,422`，Mk18 gate 为 `19,635/37,806`。诊断 [generated-boundnor-partition-audit-v1.json](../campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v2/generated-boundnor-partition-audit-v1.json) SHA-256 为 `f2ea5a2db069298041d560e893ff907ae5e63eef2c86c3326ac3d23d30e7f22a`。
- 已形成全新输入身份 `F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v2`。v2 把 `GeometryForNormals` 改为中心层 `vdp=0`，外槽使用 `all^top`，gate 采用 expanded `setmkvoid` precursor 与实体侧 `vdp=0,-1,-2` 壳层；零法向、零 `NormalSize`、非有限数组、ID/质量/端点和 gate 穿透继续作为硬门。候选 [normal-remediation-candidate-v2.json](../campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v2/normal-remediation-candidate-v2.json) SHA-256 为 `d653c684726bb2f5114b3a3b0f7e59e73a4733778c7c6b6c1f49b6982e8e114e`，root-review-only contract SHA-256 为 `90c5d7bc956f1d0dce2032c6c9feb413b5aff2173b93706a7d38ce92b7125168`。
- v2 仍是 proposal-only：未授权 CPU/native preparation，15 行 failure denominator 保持 `planned=15, executed=0, unattempted=15`，zero T1/qualification/matrix credit，禁止同输入重试、阈值放宽和 survivor renormalization。新增 normal-remediation 合同与真实 Bound.vtk 分区测试为 **10 passed**（直接文件回归 **3 passed**）。因此第三 T1 family 仍未取得。

## 本轮追加：F4 材料可靠性根因审计

- 只读复用既有 F4 frame-70 negative preflight trace，在 native transition `frame 40→41` 定位首失效 cohort。`128/128` 个 seed 的唯一触发均为下一 support field 的 `field1 reconstruction_error` gate；其中 125 个在第一个 RK2 子步、3 个在第二个子步失效。ESS、rank、anisotropy、support distance、wall visibility 和 finite velocity 均未触发。`g1` reconstruction error 的 p50 为 `0.1806703396 m/s`、max 为 `0.3062661856 m/s`，固定门为 `0.04698137929 m/s`；baseline24 replay 与既有 trace exact match。
- 两个一步 counterfactual（`f4_ess32_v2`、`f4_affine_bound_v2`）的首失效 cohort survivor 均为 `0/128`，只是 proposal-only support audit，没有改变 unknown `0.01`、CDF、事件门或科学分母。根因回执 [f4-tallwall120-native-cell14-root-cause-audit-20260921.json](../campaigns/core-v1/material/evidence/f4-tallwall120-native-cell14-root-cause-audit-20260921.json) SHA-256 为 `a4fa8e9283b4588f8ff25ace474ef57705191ba27c84a5ec9fbceefca935d0e6`，候选合同 SHA-256 为 `566d39c8c32f42859d7f2b1b93ef087dbf6e01d1666bead10d740d9ca2709d6d`。
- 资格状态仍为 `T2_macro=false`、`T2_path=false`、`qualification_credit=none`。根因审计与候选合同测试合计 **7 passed**；没有重算旧 trace，没有启动 solver/GPU/queue，也没有写 registry/ledger。下一步若执行修复，必须使用新 output stem 和完整 bounded source window，不能把一步 counterfactual 当作材料资格。

## 本轮 formal readiness 收口与回归

- formal readiness 脚本和测试已固定为独立可执行的只读审计：`scripts/core_formal_readiness.py` SHA-256 `b396eb2a049e797e0c419652fde8e5031bb879c0c2c4f18eb32002c57b2f938b`，测试 SHA-256 `dbfa6d0fc2da72cb8d403a8f0bc4f85914cdaa70eb1bdc0cbbaae6dddf3c17d3`。CLI 在当前阻塞状态返回预期 exit code `2`，不发出 formal job。
- 审计当前观察到 T1=`2/3`、validation=`8/12`、formal runs=`0/9`、material case-runs=`0/288`；phase-plan denominator 和 evaluator failure penalty contract 通过，失败 case 保留固定分母。新增三组回归（F2 normal remediation、F4 material root cause、formal readiness）合计 **9 passed**，并已更新总报告中的 formal receipt hash。
- Core 仍不能 finalize。持久协调器继续运行但队列空闲；registry 不变，以上所有失败和 proposal 证据都被保留为不可升级的审计记录。下一步依赖仍是：取得真正第三 T1 family、完成12个 validation case、在 source closure 和 release gate 通过后启动9次正式训练，并为两个宏观 T2 family 补齐288个 material case-run。

## 本轮追加：F2 v2 root review 明确关闭 runtime 权限

- root review 已对 v2 candidate、CPU proposal、BoundNor 分区、父 scope 的 15 行 matrix、完整 failure denominator、lineage、失败 anchor preflight 及 adapter/test hash 做逐项重核。结果为 `hash_review_passed_runtime_authority_closed`，receipt [root-review-receipt-v2.json](../campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v2/root-review-receipt-v2.json) SHA-256 为 `c57914722d8a08916252b0e4c445e09d8a93401033e845dcb8d1fad66358aa6f`。
- 本次不授权 CPU/native preflight，原因是 v2 仍只有 recipe/proposal，没有 hash-bound 的 fresh literal Definition writer，也没有 fresh XML、native BI4 或 CPU/native 结果。`cpu_gencase/native_decode/solver/GPU/job/queue/ledger/registry` 权限全部关闭；15 行分母仍为 `planned=15, executed=0, unattempted=15`，zero credit。root-review 报告 [F2-SUBMERGED-ORIFICE-NORMAL-REMEDIATION-ROOT-REVIEW-V2-2026-09-21.zh-CN.md](F2-SUBMERGED-ORIFICE-NORMAL-REMEDIATION-ROOT-REVIEW-V2-2026-09-21.zh-CN.md) 的定向审查合计 **13 passed**。
- 下一步仅实现并 hash-bind全新 v2 literal Definition writer，再申请新的 root review；不得在当前失败 anchor 上重试、复用旧 Definition/BI4 或放宽零法向门。第三 T1 family 状态不变。

## 本轮追加：F4 ESS32 full-source canary 合同（延后执行）

- 针对 F4 材料根因，形成了新的 `f4_ckdtree_visible_shepard_ess32_v2` full-source canary contract。它绑定新 output stem，从 frame 0 开始并在 frame 40 建立不可变 checkpoint，再恢复到原生 frame 1085（`4.340002980805959 s`），512 seeds、每 native interval 两个 RK2 子步；旧 negative trace 仅作为 provenance binding，不复制 candidate state。
- contract 保持 unknown `0.01`、CDF、事件门、完整 native cadence 和科学分母不变；预算为单进程 CPU、1 worker、最大 RSS `1 GiB`、最大 wall `1800 s`、新盘上限 `512 MiB`，失败即停止。receipt [f4-tallwall120-native-cell14-f4-ess32-full-source-canary-contract-20260921.json](../campaigns/core-v1/material/evidence/f4-tallwall120-native-cell14-f4-ess32-full-source-canary-contract-20260921.json) SHA-256 为 `cfb7f20c8e5276d1148f21b32980ae2ef55afdf656924dc72aeddc06631a8f91`。
- 由于 ESS32 与 affine 一步 counterfactual 对首失效 cohort 均为 `0/128` survivor，route decision 保持 `deferred`、proposal-only、zero credit；没有启动 solver/GPU/queue，也没有修改旧 trace、registry、ledger 或材料分母。新增 contract 回归 **3 passed**；只有后续明确 review 才可执行该全源诊断。

## 本轮追加：F2 fresh literal Definition writer

- 按 v2 root review 的唯一输入闭合要求，生成了全新 Definition 文本和 hash-bound 静态 contract。Definition [F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v2_Def.xml](../campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v2/fresh-definition-v2/F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v2_Def.xml) SHA-256 为 `1ff8cd118f31fc3a05c4e538c72c43f0b036cd0b640d597d9e2ca534d10d6e81`；writer [f2_submerged_orifice_definition_writer_v2.py](../scripts/f2_submerged_orifice_definition_writer_v2.py) SHA-256 为 `b88c7e53bf377b4dd12e3df575f2264113be7b85da8375c597f23c47717df1ea`。
- 新 Definition 保持物理场景不变，显式绑定 outer `all^top`、gate 六面法向、`GeometryForNormals vdp=0`、outer 主壳 `0,1,2`、gate void precursor 和实体侧 `0,-1,-2`；`runlist`、source 未分层、零法向硬门及旧输入禁止复用均写入 contract。proposal SHA-256 为 `5d740d09add150d213c6ed034cf6f433880039688231271b3258edaaded7fd65`，contract SHA-256 为 `0ad110108f76394af9778af08d8b5ddbc33eabbe0bd1ec04d45bb8f724aa0f94`。
- 这一步只写 Definition，不调用 GenCase/native decoder；`preflight=not_run`、15 行分母仍 `0/15`、zero T1/qualification/matrix credit，solver/GPU/queue/ledger/registry 全部关闭。writer 合同测试 **5 passed**；后续仍需新的 root review 才能考虑单一 CPU/native preflight。

## 本轮追加：正式训练 proposal-only 启动合同

## 本轮追加：F2 fresh Definition 的 v3 root review

- v3 对 fresh Definition、writer、proposal、静态 contract、v2 root receipt、父 scope 15 行 matrix、lineage、失败 anchor 和 BoundNor audit 做了完整 hash 复核。静态审查通过，fresh Definition SHA-256 仍为 `1ff8cd118f31fc3a05c4e538c72c43f0b036cd0b640d597d9e2ca534d10d6e81`；v3 receipt [root-review-receipt-v3.json](../campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v2/root-review-receipt-v3.json) SHA-256 为 `789ba8e926e266f324f57f4ce2d066a6493c9ce218ba53d6c9dabf7f1252eebb`。
- v3 仍明确 `authorized_for_one_fresh_cpu_native_preflight=false`。没有 fresh XML/BI4，尚未运行 GenCase/native decoder；solver、GPU、job、queue、ledger、registry 和 matrix submission 全部关闭。zero T1/qualification/matrix credit，15 行分母仍 `0/15`。v3 报告 [F2-SUBMERGED-ORIFICE-FRESH-DEFINITION-ROOT-REVIEW-V3-2026-09-21.zh-CN.md](F2-SUBMERGED-ORIFICE-FRESH-DEFINITION-ROOT-REVIEW-V3-2026-09-21.zh-CN.md)；相关 v3/writer/root-review 定向回归 **9 passed**。
- 当前下一步是单独审查 v3 后，最多授权一个全新 `q=.5, dp=.0075` CPU/native preflight，并把 `zero BoundNor`、`NormalSize`、ID/有限值、质量和端点 hard gate 写入新 receipt；任何失败都保持 zero credit，不能自动进入 solver 或 Core registry。

## 本轮最终资源与回归快照

## 本轮追加：F2 v3 CPU/native preflight proposal contract

- 为避免把旧 preflight adapter 误用于新 v3 Definition，新增静态 contract verifier。它绑定 v3 root receipt、fresh Definition、fresh Definition contract/proposal 和新的 generated prefix，列出 `BoundNor`、`NormalSize`、ID 对齐、有限值、质量和端点六组 hard gate；所有 gate 仍为 pending，所有 runtime 权限关闭。
- contract [preflight-contract-v3.json](../campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v2/preflight-contract-v3.json) SHA-256 为 `123356e7e843ca3a885d0f11baf7802ac00de844f353ad7203d540b03f950009`；verifier [f2_submerged_orifice_preflight_contract_v3.py](../scripts/f2_submerged_orifice_preflight_contract_v3.py) SHA-256 为 `32087a5b12d80136d084484cc87f65bf013d1fe181518f3763e4d78c22544396`，测试 SHA-256 为 `4435d8fd98b4d093a2facbe196e28e36136959d5afe4c0174a9fb9e23d1790a9`。
- 当前 contract 明确 `cpu_gencase=false`、`native_decode=false`、`solver/gpu/job=false`，queue/ledger/registry/matrix 均不变，15 行分母仍 `0/15`、zero credit；直接 contract 回归 **4 passed**。下一步仍需独立 root authorization，才能执行唯一 fresh CPU/native preflight。

## 本轮追加：formal source closure 新审计

- 新的只读审计重新计算 formal 所需 8 个源码文件的闭合哈希，当前 closure SHA-256 为 `17e06aab45536b9df5f2a00dc347be05231d4f7c6196f07698976b86bea7ede0`。相对旧 release-candidate-v4 snapshot，`scripts/core_contract.py` 和 `scripts/core_learning.py` 已变化，因此旧 source closure 不能继续作为正式训练输入。
- 审计 [core-formal-source-closure-audit-20260921.json](../campaigns/core-v1/learning/core-formal-source-closure-audit-20260921.json) SHA-256 为 `642374180a15e8919f1835852b35ab22f2d0a26f0f138e90f5cd81a0f86478a3`；实现 SHA-256 为 `b26aac8bb494f535832078733f99e09eeff8bae9290a73a14a84503c526b84b7`，测试 SHA-256 为 `981d7f691ae2467c3b78ea7aab4cb7fcee2b9b6e7a92d9eca0be994bce053845`。
- 该审计保持 `formal_job_count=0`、`launch_allowed=false`，没有写 source snapshot、registry、ledger，也没有启动训练。正式训练前仍必须由 root 接纳 fresh closure、重绑 admission/readiness、取得第三 T1 family 与 12 个 validation cases，并完成 live GPU/RAM/PSI 同卡准入。

- 最新队列状态由持久协调器读取为：`succeeded=282、failed=14、cancelled=13、queued/reserved/launching/running/attention=0`；completed process reservation `110.822604 h`，设备占用并集 `75.884826 h`，CPU children `122.414944 core-h`。队列读数只描述执行资源，不推断科学完成。
- registry SHA-256 仍为 `1ddfeda5b2d3eb142f94be4bb2cbc6f1b65271d6b77efc8b65c829b94e66b38d`，PID `2809995` 的协调器仍存活。新一轮 F2、F4、formal proposal 合并回归为 **27 passed**，另有新增脚本 `py_compile` 通过；没有提交训练或 solver 作业。
- `core_campaign status` 仍为 `can_finalize=false`：T1 `F3/F4`（2/3）、宏观 T2 `0`、正式训练 `0/9`、T1 与材料目标分母各缺 `288`；`independent_reproduction=true`、`causal_lineage_contracts=true`、`evidence_valid=true`。本轮推进的是可审计的输入闭合、失败定位和 proposal 合同，尚未把任何负结果或静态 proposal 升格为资格。

- 已生成 3 个模型 × 3 个种子的 9 行正式训练 contract。每行固定 32,000 optimizer updates、8k/16k/24k/32k 四个 checkpoint、全 validation rollout/evaluation sidecars、checkpoint selection、固定 failure denominator/unit penalty 和 selected checkpoint 的跨机 reproduce 依赖；`formal_job_count=0`、`launch_allowed=false`，没有生成 formal job/spec。
- 资源估算使用 16-update H200 profile 加 1.2 margin：graph worker 10,240 MiB GPU/8,192 MiB RAM/4 CPU，MLP worker 1,024 MiB GPU/8,192 MiB RAM/4 CPU；9 行外推约 `379.55 GPU-hours`，三模型各并发一个的 reservation 为 `21,504 MiB GPU、24,576 MiB RAM、12 CPU`。这是诊断外推，不是 32k-update capacity proof；same-card concurrency 仍须启动前按实时显存、PSI、进程和吞吐准入。
- contract [core-formal-launch-contract-20260921.json](../campaigns/core-v1/learning/core-formal-launch-contract-20260921.json) SHA-256 为 `eb1451fe6bde2ba9a80bf7742b6e2aa7df3ee76806e20edfc05a8f99b806bc5a`，实现 SHA-256 为 `3a188b937d5c16a5de0bcd08c4a71a5e78099d7add8d1240f68c127ca7ef5dc`，测试 SHA-256 为 `35475305b8ddd78a7ce2b935ebd01d81f9d2638115ab1617c7b36e5d24a2128b`；联合定向测试 **43 passed**。当前 T1 `2/3`、validation `8/12`、formal `0/9`、material `0/288`，source snapshot 仍 stale，故没有任何训练提交。

## 本轮追加：formal source closure v5 规划快照

- 在当前工作区重新物化 formal 所需八个源码文件，得到 [source-closure.json](../campaigns/core-v1/learning/formal-release-candidate-v5/source-closure.json)。文件 SHA-256 为 `7d59dc277b79c2cd77f226570ced030a3839134ee4f9052abb6f26b0095b677d`，closure SHA-256 为 `17e06aab45536b9df5f2a00dc347be05231d4f7c6196f07698976b86bea7ede0`。逐文件哈希与顺序均重算，没有继续使用 v4 的旧 closure。
- [root-admission-receipt.json](../campaigns/core-v1/learning/formal-release-candidate-v5/root-admission-receipt.json) 文件 SHA-256 为 `c6108d93a29dae0d6b606d0f9d7613bf0df7bc0a7558caf99b63eb2b62a2a628`。它接纳 v5 作为当前 planning 输入的候选，但保持 `formal_release=false`、`planning_only=true`、`formal_training_allowed=false`、`formal_job_count=0`、`launch_allowed=false`，root admission 对正式训练仍为 hold。
- verifier [core_formal_source_closure_admission.py](../scripts/core_formal_source_closure_admission.py) SHA-256 为 `bf8a59b13009230e605f401ea1a746303db49d76e66b8a16de8a26bd11ae44c4`；直接回归为 **3 passed**，与本轮 F2/第三家族/closure 组合回归共 **23 passed**。验证包含逐文件重哈希、receipt 绑定、篡改拒绝和 registry 不变性；本步骤没有启动 optimizer、GPU、solver、训练或 ledger/registry 写入。
- v5 仍明确记录 T1 `2/3`、validation `8/12`、formal runs `0/9`、material case-runs `0/288`、资源 frontier 未证明。它修复了源码闭合陈旧问题的证据链，但没有把任何正式准入门槛自动升级为通过。

## 本轮追加：F1/F2 第三 T1 路线审计与 F2 v4 CPU/native 结果

- 只读路线审计 [f1-f2-third-t1-route-audit-v1.json](../campaigns/core-v1/cfd/f1-f2-third-t1-route-audit-v1.json) SHA-256 为 `12b182a57f53b67b50c91ffea9fe592934ddaa2e0d26958bfad23efd01413084`。它按 F1 → F2 receiver/weir → F2 submerged-orifice 的顺序保留失败证据：F1 H1/H2 修复线停止，receiver/weir anchor 有 `1,490,604` 个堰穿透 particle-frames 且 event-censored；因此不重试这些输入，选择独立 submerged-orifice 作为最小下一步。该审计本身仍是 proposal-only，第三 T1 family 和 registry 均未改变。
- v4 root receipt [root-review-receipt-v4.json](../campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v2/root-review-receipt-v4.json) SHA-256 为 `c72bfed5327bd405d0664ae97922095ec74f0643bcce5742e940dbdf9beb9f3d`；实现 [f2_submerged_orifice_root_review_v4.py](../scripts/f2_submerged_orifice_root_review_v4.py) SHA-256 为 `e37810d54306c0814416b05e37b3a58087f63bd809576cc694dc3db3f6cae365`。它只授权一个新的 `F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v2` CPU GenCase/native decode，明确禁止 solver、GPU、job、queue、ledger、registry 和 matrix submission。
- 该 exact-one preflight 已实际执行并写出 [preflight.json](../campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v2/preflight-v4/preflight.json)，SHA-256 为 `90123f1c0ab3b776a306729c92d1d5dbb6281190e19511245a724f83036e1113`。输入生成了 `496,104` 个粒子（`255,906` boundary、`240,198` fluid），ID 对齐和所有数组有限，闭合外壁／闸板 endpoint 均为 `0`；但 `64,899` 个 BoundNor/NormalSize 为零，超过零法向硬门，离散源质量相对误差 `0.04718017578125` 也超过 `0.025`。因此状态为 `cpu_native_preflight_failed_hard_audit`、`qualified=false`、`matrix_credit=0`，没有 solver trajectory，也没有 T1 credit；该 exact-one 输出不重试。
- v4 runner [f2_submerged_orifice_preflight_v4.py](../scripts/f2_submerged_orifice_preflight_v4.py) SHA-256 为 `d5991953cd863c5a6bcaf71c91a20121d6e1d8e676dc5c6f398393f718512cab`；静态 contract [preflight-contract-v4.json](../campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v2/preflight-contract-v4.json) SHA-256 为 `0dc75676e2291feb1d734db7773730493d550296fd376389bb81acea4b55bede`。F2 v4/root-review/preflight/route 相关定向回归在 immutable one-shot 输出适配后为 **14 passed**；这只是接口和失败证据闭环，不会把失败 preflight 自动升级为资格。

## 本轮追加：H2 static-range 质量修复合同

- 对既有 H2 mDBC static-range v4 的唯一失败行做了只读谱系审计：固定 15 行中 14 行 CPU/native 通过，held-out cell 11（`q=0.75`、`dp=0.0075`）第三源层质量误差为 `0.02806106870228997 > 0.025`。该失败继续保留在原始 15 行分母，没有重跑同一输入、删除失败或放宽阈值。
- 新合同 [f2-h2-mdbc-static-range-repair-preflight-contract-20260921.json](../campaigns/core-v1/cfd/f2-h2-mdbc-static-range-repair-preflight-contract-20260921.json) SHA-256 `81be89887567287134ed2874bda433dcf1629066f4778bdd3b0999729b2ddb9f` 只接受一类有证据修复：`H2_v5_top_layer_lateral_lattice_balance`。它把 cell 11 的第三层格点从 `[43,29,16]` 改成独立输入身份 `[42,29,16]`，不改连续几何，不做质量重标定；实测第三层误差 `0.004152671755724757`，总误差 `0.0036100658513640305`。
- v5 full-scope CPU/native 历史产物为 `15/15` hard preflight 通过，mDBC zero-normal、ID、有限值和质量门均通过，但其 `qualification_credit=0`，没有 solver trajectory。合同实现 [f2_h2_mdbc_static_range_repair_contract_v1.py](../scripts/f2_h2_mdbc_static_range_repair_contract_v1.py) SHA-256 `29e2bc01ae596c7cf134ab6f1ee78455d121f7e469bcc87b2512f6c3cf2e3258`；对应回归 **16 passed**（含 v5 preparation、batch、runtime）。
- 合同明确禁止 solver/GPU/queue、ledger/registry mutation，并要求下一步由独立 root review 审查完整 v5 closure 后才可生成新的 runtime view。该修复没有建立第三 T1 family，Core gate 仍为 T1 `F3/F4`、宏观 T2 `0`、正式训练 `0/9`。

## 本轮追加：H2 v5 前八行 runtime 科学失败与固定分母收口

- 新 root review [f2-h2-mdbc-static-range-qualification-v5-runtime-root-review-batch8-v1.json](../campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5-runtime-root-review-batch8-v1.json) SHA-256 `c7059bb4d52998af1da31297fc035fd4304c2e7204dea1511f0bc0db0dca5e30` 只批准固定 15 行中的 `0..7` 做一次 solver/GPU canary；仍禁止 registry、ledger、材料和模型训练。8 个 Ada 作业均实际完成，队列没有遗留运行任务。
- 每个 worker 都达到约 `0.6 s`、31 帧，原生身份、有限值和生命周期闭合；独立静态保持 observer [f2_h2_mdbc_static_range_v5_observer.py](../scripts/f2_h2_mdbc_static_range_v5_observer.py) SHA-256 `834355e5548603427ab8ac1d48f07f779debe37bd173cad48ac343b5fb5ff092` 按登记门重新计算速度、动能、杯内质量、receiver/tray 质量、闭壁 endpoint 和 chord crossing。
- 结果为 `8/8` scientific failure：速度 P95 为 `1.5725–2.2859 m/s`，动能/初始势能为 `0.3026–0.3415`，杯外质量为 `1.934%–4.532%`；部分细档还有 closed-wall endpoint 或 saved-frame chord crossing。8 行没有一行通过 static-hold event，因而没有资格分子，也不能把剩余 7 行当成 survivor 继续执行。
- 固定分母证据 [observation-evidence-v1.json](../campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5/runtime-batch8-v3/observation-evidence-v1.json) SHA-256 `80dc85b33a26fdda592bc301a6dbfeb4d8ff6c8f616868e119a4f57da5995de3`：`planned=15, attempted=8, scientific_failed=8, unattempted=7, passed_zero_credit=0`，失败行未删除、未 survivor renormalization、`matrix_credit=0`。剩余行停止，下一步必须是新的有证据修复假设和新的 root review；不能延长时域或放宽 static gate。
- 本次完整回归新增 observer/evidence 相关 **20 passed**；observer 和 collector 均只写侧车证据，不改 worker trajectory、Core registry 或 ledger。H2 不能建立第三 T1 family，Core 仍为 T1 `F3/F4`、宏观 T2 `0`、正式训练 `0/9`。
- 本批 8 个 Ada 作业的 worker wall time 为 `22.39–103.44 s`，总完成队列读数为 `succeeded=290、failed=14、cancelled=13、queued/reserved/launching/running/attention=0`；累计 process reservation `110.926883 h`、GPU device union `75.589080 h`、CPU children `122.513699 core-h`。这些是执行资源记录，不是科学通过数。

## 本轮追加：完整场／halo 与双增量 updater oracle 诊断

- 新的 CPU-only 接口诊断 [core-fullfield-halo-oracle-diagnostic-20260921.json](../campaigns/core-v1/learning/core-fullfield-halo-oracle-diagnostic-20260921.json) SHA-256 `a8a41fcff61ab0cb1dda99a338dcb6c36f8e8826a850b4dd9fdf35db3f1801c1` 使用 8 粒子、固定 seed 17 的未训练 `graph_raw`，把所有 loss center 分成四个 chunk；每个 chunk 仍读取完整 field neighbor table 和 exact two-hop halo。全场与分块输出最大绝对误差 `2.98e-8`，commit 后位置误差同量级、速度误差为 `0`。
- 独立 privileged oracle 同时给出 displacement 与 native `delta_velocity`，`max(|dx/dt-dv|)=0.038`，因此没有把保存帧位移差分冒充原生速度；`predict→commit` 和 `updater_oracle` 的位置/速度误差均为 `0`。递归注入 `nested.future_state` 被拒绝，没有把未来状态传给 predictor。
- 实现 [core_fullfield_halo_oracle.py](../scripts/core_fullfield_halo_oracle.py) SHA-256 `9821a68dc3e485fa79c5b7b37e8b7f433943972f418e6ffa42103106404e1c0f`，测试 SHA-256 `1312bf86a79c56e5d9e3eeb0f504fb9d497d45bce3558601d8f61668b2d15045`；定向接口回归 **59 passed**。receipt 明确 `diagnostic_only=true`、`formal_job_count=0`、training/qualification excluded，没有写 registry/ledger；该结果不能计入正式 9 次训练。

## 本轮追加：H2 v5 static-hold 负结果的根因审计与路线收口

- 对固定分母中的 8 个 H2 v5 runtime observer/worker sidecar 做了只读、hash-bound 审计，没有重新打开或重哈希既有 HDF5，也没有重跑 solver、GPU、queue 或修改 registry/ledger。审计实现 [f2_h2_mdbc_static_hold_negative_audit_v1.py](../scripts/f2_h2_mdbc_static_hold_negative_audit_v1.py) SHA-256 `4186cae438191d7c0f9a61c5f191b6efb6385da42a07e7c96531ca2ea9f6477d`，测试 SHA-256 `76fc11429578a6a9b15f370d6ed44848cbff2003b16a4f175e2cdcb00a111580`。
- 审计确认 8/8 都是科学失败而非基础设施失败：P95 速度 `1.5725–2.2859 m/s`、动能/初始势能 `0.3026–0.3415`、杯外质量 `1.934%–4.532%`，末端稳定保持时间均为 `0`；CPU/native 输入侧记录初始零速度、零法向和不重缩放，但没有把这些输入事实扩展成运行时正确性的证明。root-review-only contract [f2-h2-mdbc-static-hold-negative-audit-root-review-contract-20260921.json](../campaigns/core-v1/cfd/f2-h2-mdbc-static-hold-negative-audit-root-review-contract-20260921.json) SHA-256 `61f9e214c86bc7ed5c7e9b35e117c8395191af1001c2b5742b0ca9209154f4e4`。
- 仅保留两类有证据的后续假设：新的 Definition/output 身份下检查运行时初始静止到 mDBC 壁面冲量的交接；以及把 worker 结构完整性和静态 observer 物理门分栏记录。两者均为 `proposal_only`，仍固定原有时域、cadence、阈值和 zero-credit 规则，禁止重跑 batch8 同输入、延长窗口或放宽门槛。H2 v5 lineage 关闭 T1 晋级，matrix credit 仍为 `0`。
- 下一独立候选仍是 F2 submerged-orifice normal-remediation v2；它保持单独 root review、CPU/native preflight 和 15 行分母，不因 H2 失败而自动获得执行权限。当前 Core gate 没有变化：T1 只有 F3/F4，宏观 T2 为 `0`，正式训练为 `0/9`。

## 本轮追加：A6/A7 改动后的 formal source binding 修复

- 完整回归在 `1092 passed, 1 skipped` 后发现旧的 `formal-training-admission-readiness-luna-max-20260920.json` 仍把 `scripts/core_learning.py` 绑定到旧 hash；这是历史 readiness receipt 的陈旧闭合，不是把训练当成已执行。没有启动 formal job，也没有写 registry/ledger。
- 测试 [test_core_formal_admission_readiness.py](../tests/test_core_formal_admission_readiness.py)（SHA-256 `c6f07a695ca9d7621a2e4aeb9bd75ed0e0742bee80640b462a1f20477eae8786`）现在明确区分两种历史绑定：`core_contract.py` 由 causal-repair receipt 校验，`core_learning.py` 由新的完整场／halo oracle receipt 校验。保留旧 readiness artifact 与其 `preprofile_mismatch_count=7` 历史字段，不覆盖旧证据。
- source closure 当前 hash 继续以 formal-release-candidate-v5 为准；针对正式准入、source closure、A6/A7 oracle、H2 observer/collector、H2 repair、prepare/runtime 的定向回归为 **69 passed**。该修复只恢复证据链一致性，formal release 仍关闭，Core gate 不变。

## 本轮追加：F2 submerged-orifice v4 BoundNor 失败分区审计

- 只读审计脚本 [f2_submerged_orifice_v4_failure_audit_v1.py](../scripts/f2_submerged_orifice_v4_failure_audit_v1.py) SHA-256 `b189aa69dd8b8fd9cfb0bbecae0d5f0bd81ca75b94a711ea7afe53ac0939e74c` 读取既有 v4 `preflight.json` 和 `Bound.vtk`，不读取 Definition/BI4，不调用 decoder、GenCase、solver、GPU、queue，也不写 registry/ledger。
- 审计输出 [v4-boundnor-failure-audit-v1.json](../campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v3/v4-boundnor-failure-audit-v1.json) SHA-256 `56960219cc28687d5e7233f48485f242b014082c3b965f7f9eee1f2f6742ca47` 将 `64,899` 个零 `BoundNor/NormalSize` 全部定位到 `Mk=17` outer-wall 分区，`Mk=18` gate 为 `0`；零法向和质量相对误差 `0.04718017578125` 的硬门均保持失败。
- 目前只支持一个新的 geometry/normal coverage 假设：v4 以单一 outer `vdp=0` 法向源覆盖了实际 `0,1,2` shell layers，且生成边界粒子计数 `86×57×49` 解释了质量偏差。该假设仍须新的 literal Definition、独立 candidate 和 root review；当前不授权 CPU/native、solver 或 T1/matrix credit，也不重试 v4 输入。

## 本轮追加：F2 submerged-orifice v3 静态候选与 root-review-only 合同

- 基于上述唯一分区证据，生成全新 case/output 身份的 v3 literal Definition、candidate 和合同。v3 把 outer 法向层显式闭合为 `vdp=0,1,2`，gate 保持 `vdp=0,-1,-2`，并把源 lattice 从失败的 `86×57×49` 改为 count-closed `86×56×48`；预计离散质量相对误差为 `0.0078125`，仍需实际 CPU/native 验证。
- candidate [normal-remediation-candidate-v3.json](../campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v3/normal-remediation-candidate-v3.json) SHA-256 `0368f5fdc11b089cad3664f9c8c1d2f88a645165c5233774e7f90b4704de8852`，fresh Definition SHA-256 `a8db3f6f3d5d47851e30e005daa4d0b3434630c78f70446428fe56710234c6da`，adapter [f2_submerged_orifice_normal_remediation_v3.py](../scripts/f2_submerged_orifice_normal_remediation_v3.py) SHA-256 `c2c03bf543a03d181769661ed34d07a6d8d643684222a0ddf465ed460df0d2db`。
- root-review-only contract [root-review-only-contract-v3.json](../campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v3/root-review-only-contract-v3.json) SHA-256 `f1927012839fd9c84cf8d13a3d6ebea6c251ca9d6d9f8d1cbfb2107378413e18` 明确 `authorized_now=false`：未调用 GenCase/native decoder，没有 solver/GPU/job/queue/ledger/registry/matrix 写入，15 行分母仍 `planned=15, executed=0, unattempted=15`，zero credit。定向 v3/v4 回归 **14 passed**。
- 报告 [F2-SUBMERGED-ORIFICE-NORMAL-REMEDIATION-V3-ROOT-REVIEW-2026-09-21.zh-CN.md](F2-SUBMERGED-ORIFICE-NORMAL-REMEDIATION-V3-ROOT-REVIEW-2026-09-21.zh-CN.md) 记录了当前边界：候选只可进入新的 root review；在 root review 之前不生成 native 输入，不把静态预测当成质量或 T1 证据。

## 本轮追加：F2 v3 独立 root review 授权边界

- 独立 receipt [root-review-receipt-v3.json](../campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v3/root-review-receipt-v3.json) SHA-256 `adce91758b4d564f3a95db8c61df4248899c3534905198a968700458582819b5`；root-review adapter SHA-256 `8ee68b2ac508058e7c9a9b198c7dfc9e41925d5bdcc6f1584bfe6aacce962300`，测试 SHA-256 `c5f574ef228dac5225a54b823e31469974f0ba96cf1fe2b3ab565559b682fb77`。
- 该 review 重新校验 v4 失败证据、v3 fresh Definition、candidate、父 scope 15 行 matrix、denominator、lineage 和静态合同，结果为 `authorized_one_fresh_cpu_native_preflight_only`。只打开 case `F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v3` 的 CPU GenCase/native decode；solver、GPU、job、queue、ledger、registry、matrix submission 仍关闭，credit 仍为 `0`。
- root review 定向回归 **17 passed**。下一步只能按 receipt 的 exact case/output prefix 执行一次 CPU/native preflight；任何 hard gate 失败都保留、停止，不自动转 solver 或资格。

## 本轮追加：F2 v3 CPU/native exact-one preflight 失败与 post-run hash closure

- 按 v3 root review receipt 的唯一授权，实际执行了一个全新的 `F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v3` CPU GenCase/native decode；没有调用 solver、GPU、job、queue、ledger、registry 或 matrix submission。输出 [preflight.json](../campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v3/preflight-v3/preflight.json) 当前 SHA-256 为 `90b8c460262ad1424aab42dbc0046f1bf3b511478ddc0b5e240fd83b87485dd7`，状态为 `cpu_native_preflight_failed_hard_audit`，`qualified=false`、`matrix_credit=0`、`solver_product_present=false`。
- 生成物共有 `475,631` 个粒子，其中 `255,906` 个边界粒子、`219,725` 个流体粒子；ID、有限值和外壁／闸板 endpoint（`0 / 0`）通过。硬门仍失败：`83,443` 个 `BoundNor` 为零且 `83,443` 个 `NormalSize` 为零；离散流体质量 `92.696484375 kg` 对连续质量 `96.768 kg` 的相对误差为 `-0.04207502092633919`，超过 `0.025` 门槛。该 exact-one 运行立即停止，不能转成 T1 或资格矩阵证据。
- 为避免“运行后修 verifier 就伪造运行时 hash”的歧义，新增 [postrun-verifier-rebind-v1.json](../campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v3/postrun-verifier-rebind-v1.json)，SHA-256 为 `f963946a527df9168a6f277ad7156aa3de4bf3a9ac6456c44340fb6b4a1c598f`。它保留执行时 receipt/contract/preflight 的旧 hash（分别为 `adce917…`, `8d9e1b…`, `fdeb1a…`），并记录只针对 verifier 读取路径的当前 hash（receipt `5672f5…`、contract `c4a8db…`、preflight `90b8c4…`）；`changed_science_fields=[]`，所有 solver/GPU/队列/账本/registry/matrix 控制仍关闭。相同输入的再次执行由 freshness guard 拒绝。
- 现行 runner [f2_submerged_orifice_preflight_v3.py](../scripts/f2_submerged_orifice_preflight_v3.py) SHA-256 `65efd638a3a4af2e7cb9e20195f0910c5c3a16dd1e9de79cf7eab1c1534b0940`，root-review verifier [f2_submerged_orifice_normal_remediation_root_review_v3.py](../scripts/f2_submerged_orifice_normal_remediation_root_review_v3.py) SHA-256 `ff6d89822caffb28fe702391d9c4f062e9f3799fe2be659c0ed46a5e99485eee`；只读 receipt/contract/preflight/rebind 回归为 **18 passed**。`verify-preflight` 的非零退出仅表示预登记硬门失败，不是 verifier 例外；结构化输出仍通过只读校验。
- 该失败不会改变 Core 现状：T1 仍只有 F3/F4，宏观 T2 为 `0`，正式训练为 `0/9`，T1 与材料分母各缺 `288`；队列保持空闲，失败输入不重跑。下一步需要新的、由 v3 零法向分区和质量失败共同支持的修复假设及独立 root review，不能放宽门槛或删掉失败行。

## 本轮追加：F3/F4 宏观 T2 admission 审计与唯一 deferred 候选

- 新的只读合同 [f3-f4-t2-admission-root-review-contract-20260921.json](../campaigns/core-v1/material/evidence/f3-f4-t2-admission-root-review-contract-20260921.json) SHA-256 为 `04e02868af86d65758fb739ff4630fec658e384b7325bbdf66abd55d60edafac`；实现 [f3_f4_t2_admission_contract_v1.py](../scripts/f3_f4_t2_admission_contract_v1.py) SHA-256 为 `d3ad0ddc477b9e599b7af6339c23e269ac98d8e18f629dcfd3b9513730ee532d`，测试 SHA-256 为 `dc80c4160f88db4015f9a89bff47a12cf86cceed08e218aa2f3fcba86288de08`。当前合同状态是 `proposal_only_root_review_required`，不是当前授权。
- F3 的 source/window 与质量闭合部分通过，但保留的 unknown 最大值为 `0.015625 > 0.01`，CDF 最大绝对差为 `0.06103515625 > 0.02`；所以 F3 仍是 `T2_macro=false`、`T2_path=false`。F4 的 6 个材料 canary 全部是 right-censored/unresolved，unknown 最大值 `0.84765625–1.0`，同样不能给 T2 credit。
- 唯一选择的最小候选是 F4 `f4_ess32_v2` full-source material sidecar：绑定已有 T1 原生窗口 `1086` 帧、`217485` 粒子、`4.340002980805959 s`，512 seeds、单进程、frame `0–1085`。但其 one-transition 反事实 survivor 为 `0`，因此合同把它标为 `deferred_proposal_only`，不暗示通过概率，也不提前使用现有负 trace。
- 当前唯一未来边界仍是 `authorized_now=false`：若之后取得独立批准，只能执行一次 CPU-only 材料 sidecar；禁止重跑旧 CFD、solver/GPU/queue、matrix、registry、ledger，禁止改变 unknown/CDF/reconstruction/event-window/denominator 门槛，unknown/right-censored 一律保留 zero credit。Core gate 保持 T2 `0`。

## 本轮追加：F4 ESS32 独立 root review 与 F2 v4 新输入授权

- F4 `f4_ess32_v2` 已完成独立 root review。receipt [f4-tallwall120-native-cell14-f4-ess32-root-review-20260921.json](../campaigns/core-v1/material/evidence/f4-tallwall120-native-cell14-f4-ess32-root-review-20260921.json) SHA-256 为 `b6e7e92435179d25cc524e006b53c482259dc22065e30b5297d6ed4975dc7b7a`，定向回归 **4 passed**。审查确认 source 为 1086 个 native frames、217485 particles、0–4.340002980805959 s；frame 40→41 的 ESS32 counterfactual survivor 为 `0/128`，因此 `authorized_one_cpu_only=false`，没有生成 sidecar，也没有改变 T2 门、分母或 Core 状态。报告 [F4-ESS32-ROOT-REVIEW-2026-09-21.zh-CN.md](F4-ESS32-ROOT-REVIEW-2026-09-21.zh-CN.md) SHA-256 为 `56ebb89ad7970b12b618f5ea0af6ecff2dec4c4c812f56691beebe80fb0e8ce5`。
- F2 v4 是针对 v3 `83,443` 个零 `BoundNor/NormalSize` 与 `-4.207502092633919%` 质量误差的新输入假设。它把 `GeometryForNormals` 外层改为 `vdp=0,-1,-2`、gate 改为 `vdp=0,1,2`，保留主边界层方向，并将源格点闭合为 `86×56×48`；预测质量误差 `+0.78125%`，物理几何和所有 hard gate 不变。candidate SHA-256 为 `a80e1f91bb31575c6967bb02f5daf69fdb161edd98a1f0eb7ccfdabbbbe0bce6`，fresh Definition SHA-256 为 `a138d65a9a87acea2664eb640ebd74bca06f8890259fb93a7224ea582d52fd07`，静态 contract SHA-256 为 `b15c66507baeefd9b5ccd44dcc51167f57103d35473224efdacfec18030ce739`。
- 独立 F2 v4 root review receipt [root-review-receipt-v4.json](../campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v4/root-review-receipt-v4.json) SHA-256 为 `645136a7eaa138db0dae6da372ac29cdc27f0e4445567cf45311d97878f8bbc5`；review adapter SHA-256 为 `3b70f2fa184bee541083e5f2bc93b5dea1db5fa3f8e631af2fe9d6df956c449b`，报告 SHA-256 为 `d50f36921bb8fa52f2198c4fc2f7a7f63e83bb1d5e9c0c45dc693ea04337c966`。receipt 只授权一次全新 v4 CPU GenCase/native decode，`qualification_credit=0`、`matrix_credit=0`，solver/GPU/job/queue/ledger/registry/matrix submission 全部关闭；输入前缀仍未物化，15 行父分母保持 `0/15`。
- 因此本轮尚未把 F2 v4 计入 T1，也没有启动 v4 solver 或模型任务；下一步只有在 runner 与 receipt hash closure 完成后执行该 exact-one CPU/native preflight，任何零法向、非有限值、ID、端点或质量门失败都立即停止并保留 zero credit。Core gate 仍为 T1 `F3/F4`、宏观 T2 `0`、正式训练 `0/9`。

## 本轮追加：F2 v4 CPU/native exact-one 负结果与不可重试收口

- 按 v4 receipt 唯一授权，实际只运行了一次全新 CPU GenCase/native decode，未启动 solver、GPU、job、queue、ledger、registry 或 matrix submission。生成结果为 `487,074` 粒子，其中 boundary `255,906`、fluid `231,168`；输出 [preflight.json](../campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v4/preflight-v4/preflight.json) 当前 SHA-256 为 `1bb7c27d0d1565a8be274bed95e1915277230471c8bdd5c18fc0b2499b3ac481`。
- 该 preflight 状态为 `cpu_native_preflight_failed_hard_audit`、`qualified=false`、`matrix_credit=0`。ID 唯一且与 XML 对齐，全部数组有限，外壁 endpoint 与 gate penetration 均为 `0`，源质量相对误差为 `0.007812500000000222`（门槛 `0.025`）；但 `zero_boundnor_count=29,484`、`zero_normal_size_count=29,484`，所以法向硬门仍失败。该结果不能进入 solver、T1 或 Core 分母，v4 输入禁止同输入重试。
- 由于 runner 在运行后完成了只影响验证绑定的源文件整理，新增 [postrun-verifier-rebind-v1.json](../campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v4/postrun-verifier-rebind-v1.json) SHA-256 `ea4fbe40d53617354f587528a3a1c9d196631870a293e36046ba8eea7df5a49a`。它保留运行前的 receipt/contract/preflight/runner/test hash，记录 `changed_science_fields=[]`，并把当前 verifier 引用更新到 contract SHA `9317b090a7f8736b9c7e23206138240bbfc4d3f752efa2a26afec9e76313e5a1` 和 runner SHA `c296d3197abd3e2b9198b35b735c89c3214fc19bbd018868c26b5fcbc4bd2313`；post-run rebind 与 preflight verifier 均通过，只因 `preflight_pass=false` 按预登记规则返回负结果退出码。
- v4 runner [f2_submerged_orifice_preflight_v4.py](../scripts/f2_submerged_orifice_preflight_v4.py) SHA-256 为 `c296d3197abd3e2b9198b35b735c89c3214fc19bbd018868c26b5fcbc4bd2313`，rebind 实现 SHA-256 为 `53578dd9b59113de69e4735d3e1890f2f59a56bb9b8efd854a8bcf8c9c3f79f8`，相关定向回归为 **13 passed**（含 root review、静态 contract、preflight hard audit 与 rebind）。F2 submerged-orifice 这条 v2→v4 修复线现在有闭合的失败分母和四个版本化负证据，不能再从同一机制继续无证据重试；Core gate 仍是 T1 `F3/F4`、宏观 T2 `0`、正式训练 `0/9`。

## 本轮追加：F2 v4 post-run verifier 的最终 hash closure

- 执行后仅更新了 verifier 侧的 hash 引用，没有改动 native arrays、hard-gate 观测、执行控制或 credit。当前 preflight contract SHA-256 为 `d2b87fb32610e05455d813b148c79a47adfa4f44411f761a0e3ed6a425e53f16`，preflight SHA-256 为 `db18863a97cb0a6d17a2cbb877e7b3df94368c96be4176728bd7b15b8a698685`，post-run rebind SHA-256 为 `8bc1723221f82c87d28b932fdc461119480963e6da60edbc7c1f3382ef7c2c7e`。
- 当前 runner SHA-256 为 `90f6008af9c03955032f85d2e7bf33f0fc428ccb031d633facbafb38368c7190`，preflight verifier 记录 `preflight_pass=false` 并按负结果返回退出码 `1`；只读 `verify-preflight` 结构校验通过。四组 F2 v4 定向测试最终为 **13 passed**，同输入执行仍由 freshness guard 拒绝。
- 最终 root-review-only contract SHA-256 为 `9d008edadbf1de83eb3fda4a0fdf32e762d0a83ae265e04da93117135f5e22d7`，root receipt SHA-256 为 `a2f0a54d8a95ca06b16daf282c72faeb2a89f6cc90bd9094867cb495eaeb1d3f`。这两个 hash 只反映 verifier/test binding 的 post-run 更新；授权内容仍是一次 CPU/native、zero credit，未把任何失败证据升级为 T1。

## 本轮追加：F2 v4 零法向分区审计

- 只读审计 [v4-current-failure-partition-audit-v1.json](../campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v4/v4-current-failure-partition-audit-v1.json) SHA-256 为 `74d7395e697db199d05e70b2795540812fae8170c2e69247f26258c1e2141bdd`，实现 SHA-256 为 `946fe07d365fd350a80682845312696d10fae648d7bf52540e279ed43e391ef6`，测试 **2 passed**。它只读取本次 `preflight.json` 与 `Bound.vtk`，没有读取 Definition/BI4，也没有调用 GenCase、native decoder、solver、GPU 或任何队列／账本／registry 接口。
- 分区结果为：外槽 `Mk=17` 的 `226,422/226,422` 个边界粒子法向有效；闸板 `Mk=18` 的 `29,484/29,484` 个边界粒子 `BoundNor/NormalSize` 均为零。这个证据把 v4 的失败责任从外槽转移到 gate normal coverage，但目前只足以支持后续提出一个独立、可证伪的 gate 假设，不能授权 v4 重试或直接写成 v5 资格。

## 本轮追加：F2 v4 T2 boundary review（当前 hash 版本）

- 材料侧独立复核 [f2-submerged-orifice-v4-t2-material-review-20260921-v2.json](../campaigns/core-v1/material/evidence/f2-submerged-orifice-v4-t2-material-review-20260921-v2.json) SHA-256 为 `2066040c363a41a7348c0d01a3aa7ef733117d011d1c5292c46891a7f3ff83c9`，报告 [F2-SUBMERGED-ORIFICE-V4-T2-MATERIAL-REVIEW-V2-2026-09-21.zh-CN.md](F2-SUBMERGED-ORIFICE-V4-T2-MATERIAL-REVIEW-V2-2026-09-21.zh-CN.md) SHA-256 为 `b9d0ff717a04a379658a806715cac5b8491b6c7e9dded8c27655782c656f708a`。它绑定当前 root receipt、preflight contract 和 post-run preflight，确认 `T2_macro=false`、`T2_path=false`、材料验收未开始、父 F2 15 行分母仍 `0/15`。
- 该 review 把 CPU/native hard failure 和材料资格分开：即使初始完整性硬门通过，也不能解释为材料 T2；当前 zero-normal 失败更不能作为材料侧证据。review 只读完成，没有 solver/GPU/queue/ledger/registry/matrix 操作，也没有改变 Core gate。

当前 hash closure 修订后，T2 boundary receipt SHA-256 为 `a27eda0ba6abbf58c0977018148cbac07b531d073f74fe86eec955913db0813d`，报告 SHA-256 为 `df87d8edb2e1502da4f6bf48592b6b65198ee2b277d05d3ec8a461e4778d8854`；修订仅更新测试与 post-run 文件引用，科学结论不变。

## 本轮追加：第三 T1 路线审查收口

- 独立路线审查确认现有 F1/F2 候选没有可安全重开项：F1 H3 有 `302,558` obstacle-penetration particle-frames、`302,559` saved-chord crossings 和 `774` native IDs lost；F1 H4 有 `265,270` endpoint frames、`1,358` obstacle penetrations 和 `12.95 kg` 质量损失；suspended-gap G1 仍有 endpoint/penetration/chord-crossing 失败。F2 DBC 5 s extension 虽硬完整性通过，但事件仍截断（terminal `speed_p95=0.399684 m/s`，门为 `0.10`），进一步延长和复用 canary 已被合同禁止。
- 这些结果对应 [F1-F2-THIRD-T1-ROUTE-AUDIT-2026-09-21.zh-CN.md](F1-F2-THIRD-T1-ROUTE-AUDIT-2026-09-21.zh-CN.md) 和 [f1-f2-third-t1-route-audit-v1.json](../campaigns/core-v1/cfd/f1-f2-third-t1-route-audit-v1.json)。审查结论是：没有旧输入可直接进入 solver；下一条第三 T1 路线必须是新的物理机制和新的输入谱系，先做 root-review-only contract，再申请一次 CPU/native canary。F2 submerged-orifice v2→v4 已完成其独立失败链，不能把 v4 gate-only 负结果当作下一轮授权。
- 因此 Core 的真实状态继续为 T1 `F3/F4`（`2/3`）、宏观 T2 `0/2`、正式训练 `0/9`；缺失的固定分母仍为 T1 `288` 个 case-run 和材料 `288` 个 case-run。当前阶段交付的是可复现的接口、审计、失败证据和路线边界，不提前伪造 benchmark 完成度。

## 本轮追加：F5 第三 T1 候选、输入闭合与唯一 solver anchor

- 新候选为 F5 `F5_prescribed_wave_runup_x_v1`，机制是规定活塞造波在斜坡和块体上的爬坡、回落与外部波高计观测，和已收口的 F1 溃坝／绕障、F2 接液／孔口机制独立。候选审计 [f5-wave-runup-third-t1-proposal-audit-v1.json](../campaigns/core-v1/cfd/f5-wave-runup-third-t1-proposal-audit-v1.json) SHA-256 为 `2a72700b40c08c4a11ac38b55cccb40a85b7fecf940f612bc974dd88fc3a3760`；固定 15 行资格矩阵、`16 s` 观察窗、`0.02 s` 输出和四个外部 WG 观测列为 proposal-only，旧 R3 轨迹不复用为 Core 真值。
- F5 v1 fresh Definition 的第一次 CPU GenCase 在输入闭合处失败：输出 [preflight-v1/preflight.json](../campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v1/preflight-v1/preflight.json) 状态为 `cpu_native_preflight_failed_hard_audit`、`GenCase returned nonzero`，日志指出 Definition-relative `Slope.stl` 无法打开。该 attempt 没有 native decode、solver、GPU、队列、账本、registry 或 matrix 变更；v1 output stem 保留且禁止同输入重试，科学信用为零。
- v2 只修复资产闭合：把 `Slope.stl`、`Blocks_3D_scaled.stl`、运动文件和几何输入置于 Definition 相邻的新目录，并绑定新的 contract [fresh-definition-contract-v2.json](../campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2/fresh-definition-contract-v2.json) SHA-256 `5fd1b6561bc495db53ac6e60a1e07e3abf79a1ff286a2e882e13a93a53893206`。独立 root receipt [preflight-root-review-v2.json](../campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2/preflight-root-review-v2.json) SHA-256 `7b398d071742b39b27043a7619b84e4ed5562daf2997e56f9efd4c2b4f0368e9` 只授权一次全新 CPU/native preflight，solver/GPU/queue/registry/matrix 均关闭。
- v2 preflight [preflight.json](../campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2/preflight-v2/preflight.json) SHA-256 `12895e9364f6be3fda4c1c5629ac0d6f58cbf710fb0443e8c9b51976851a8225` 通过静态输入硬门但明确 `qualified=false`、`matrix_credit=0`：native 总粒子 `1,374,477`，fixed `86,270`，fluid `1,279,855`，moving `8,352`，`dp=0.0075 m`，初始 fluid mass `539.938828125 kg`，ID、有限值、XML/BI4、质量和几何 VTK 对齐。边界语义只读审计 [preflight-boundary-semantics-audit-v1.json](../campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2/preflight-boundary-semantics-audit-v1.json) SHA-256 `c922f98949dec2848ecf615a765e5bdf642d48cde91605f2d9b8a4555a7813fa` 确认 native fixed 与 generated fixed 语义一致；它没有打开 HDF5，也没有启动 solver/GPU。
- 独立 solver root receipt [solver-anchor-root-review-v1.json](../campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2/solver-anchor-root-review-v1.json) 当前 SHA-256 `fa4074cac0b5f4808ec5a5e6bc6046205440180cda847810760067f4883d1a8d` 只授权一个受保护的 Ada GPU anchor 和一次队列提交，仍禁止 registry、ledger、matrix 写入。job spec [solver-anchor-job-spec-v1.json](../campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2/solver-anchor-job-spec-v1.json) SHA-256 `71797e50e402aef5bed008acee1956004e0d0c3950c7d84921b95e82192db470` 绑定全新输出 stem、generated XML/BI4、solver 二进制和运行器；queue spec 已以同一 hash closure 提交一次，`qualification_claim=none`、`matrix_credit=0`。
- 资源调度器把该唯一作业分配到 Ada GPU0（实时外部占用下仍保留约 `29,492 MiB` GPU reservation），attempt 为 `20260921T061057-efc149b14810`。截至本节记录时 solver 正在写入完整 `16 s` 窗口，已保存 `131` 个 `Part_*.bi4`、约 `5.4 GiB`；这只是运行中证据，不代表事件完整、T1 资格或 Core 分子增加。运行完成后仍须读取 Run.out、全帧数量、端点 native identity/有限值、波高计 cadence 和独立几何／事件审查；任何失败都保留 zero credit 且不重试同一输入。

## 本轮追加：F5 唯一 solver anchor 完整 raw 产物与 worker 基础设施失败

- 受保护队列作业 `f5-wave-runup-third-t1-q05-dp0075-v2-protected-gpu-anchor` 已在 Ada GPU0 完成唯一一次 solver 执行。attempt `20260921T061057-efc149b14810` 的实际 GPU process reservation 为 `1.2086876717540953 h`，墙钟 `4351.275618314743 s`（约 `72.52 min`），子进程 CPU `3904.856961 s`，峰值采样显存 `814 MiB`、峰值树 RSS `517.77 MiB`；同输入没有重试。
- 原生 solver 产物完整。Run.out SHA-256 为 `c5b5e3964f05449cabc3772beabe13e51979116e6bc490d081cffb5437f43d8a`，明确记录 `TimeMax=16`、原生 `Output ... dt:0.02`、`Excluded particles=0` 和 `Finished execution (code=0)`。raw data 有恰好 `801` 个 `Part_*.bi4`，索引 `0..800`，每帧 `1,374,477` 粒子；首末帧 native decode 均通过有限值、唯一 ID、流体数 `1,279,855` 和首末 ID 一致性检查。
- 只读后审 [f5-wave-runup-solver-anchor-postrun-audit-v1.py](../scripts/f5_wave_runup_solver_anchor_postrun_audit_v1.py) 生成 [postrun-audit.json](../campaigns/core-v1/runtime/attempts/f5-wave-runup-third-t1-q05-dp0075-v2-protected-gpu-anchor/20260921T061057-efc149b14810/product/postrun-audit.json)，SHA-256 为 `badf1432199e5e0d92f580c090feb8c5f14f5a86ddd4cb944304b7341168d123`，状态为 `raw_solver_product_complete_worker_cadence_parser_failure`。11 个 gauge（`WG1..WG4`、`Run-up1..Run-up7`）全部存在、时间序列结构门通过；该后审只读，没有启动 solver/GPU、队列、ledger、registry 或 matrix，也没有把 anchor 晋级为 T1。
- 队列 receipt [result.json](../campaigns/core-v1/runtime/attempts/f5-wave-runup-third-t1-q05-dp0075-v2-protected-gpu-anchor/20260921T061057-efc149b14810/result.json) SHA-256 为 `3a26f4c06118952d116f5f24fa63f2cfb0494e94df101ed4b3e4db90217a5211`，状态为 `failed`，`returncode=1`，缺少 `product/audit.json` 与 `product/observations.json`。冻结 runtime worker 在 solver 正常退出后先会因只解析不存在的 `TimeOut=` 而无法通过 cadence gate，随后在 `_parse_gauge()` 对真实 attempt 路径调用 snapshot-relative `rel()` 时抛出 `ValueError`；这两项均属于执行器基础设施失败，不能改写为科学失败或资格通过。
- 本次 raw product 保留为候选观察证据，但科学门仍待独立几何／实体穿透／事件完整性与外部参考审查；`qualification_claim=none`、`matrix_credit=0`，F5 仍未进入 Core T1 registry 或 15 行资格矩阵。隔离 cadence parser [f5_wave_runup_solver_anchor_cadence_parser_v1.py](../scripts/f5_wave_runup_solver_anchor_cadence_parser_v1.py) 已在 commit `8b654b4` 中实现并通过 3 项 parser 测试；它只作为后续新 root review 的修复候选，不回写本次冻结运行。
- 资源账本在作业完成后为 GPU process reservation `112.13557023233844 h`、device reservation union `76.79776740716564 h`、CPU children `123.5983816636111 core-h`、indexed replica `1,219,589,011,653 bytes`、indexed unique content `1,138,195,266,869 bytes`。与作业前快照相比，本次新增的约 `1.2086876717540953 GPU-h` 和约 `35.2 GB` unique raw content 归属于该唯一 anchor；进程时长与设备占用分别记录，不能混为 kernel-active 时间。
- Core 科学状态没有变化：T1 仍为 F3/F4 两个家族，宏观 T2 为 `0/2`，正式训练为 `0/9`；F5 anchor 的完整 raw 产物不增加任何分子，固定分母也不因 worker 失败而删除。下一步只能在保留该失败证据的前提下，为全新输入身份建立修复后的 root review；不得对本次输入重试或把 postrun 观察直接注册为资格。

## 本轮追加：F5 raw 产物的只读科学抽样后审

- 只读审查器 [f5_wave_runup_solver_anchor_scientific_review_v1.py](../scripts/f5_wave_runup_solver_anchor_scientific_review_v1.py) 及其 5 项回归测试，读取冻结 contract、Definition、静态 MkCells、Slope/Blocks STL、11 个 gauge、外部 CIEMito 表和已完成 native 帧；审查本身没有 solver/CUDA、队列、root review、ledger、registry 或 matrix 写入。抽样报告 [scientific-review-sampled-v1.json](../campaigns/core-v1/runtime/attempts/f5-wave-runup-third-t1-q05-dp0075-v2-protected-gpu-anchor/20260921T061057-efc149b14810/product/scientific-review-sampled-v1.json) SHA-256 为 `2b93d7f826e1cdd2a8502a7fe7e49270a7cdcd627ece70afcd704bee9033685f`。
- 报告抽查帧 `0,100,200,…,800` 共9帧，保存帧之间按 stride `32` 检查共同流体粒子；因此状态严格是 `scientific_review_sampled_pending_zero_credit`，不能解释成完整时域通过。抽样已经观察到 `3,354` 个实体穿透粒子帧（Slope `891`、Blocks `2,463`）、`1,435` 个保存帧 chord crossings，以及 `103,552` 个超出生成包络的粒子帧；这足以阻止该候选直接进入15行资格矩阵，后续必须先建立新的可证伪几何假设或完整审计，不能把抽样失败删掉。
- 抽样 native identity、native 时间轴和有限值均通过，9 个样本的流体质量保持在约 `539.9388421305049 kg`；这些只是输入／执行诊断。事件阈值和外部参考接受包络没有在当前 F5 contract 中预登记，WG1–WG4 对外部表的 RMSE `0.0056603–0.0078241 m`、最大绝对差 `0.0182533–0.0231902 m` 仅作诊断，不能变成 T1 或 external validation credit。
- 结合 worker 的 cadence/path 基础设施失败，F5 目前同时有“raw solver 完整”“执行器 receipt 失败”“抽样科学几何门观察到负证据”三类独立事实；三者均保留，资格状态仍为 `none`，Core gate 仍只有 T1 F3/F4、T2 `0/2`、formal training `0/9`。

## 本轮追加：F5 runtime v2 修复已准备但尚未授权

- 独立 runtime v2 [f5_wave_runup_solver_anchor_runtime_v2.py](../scripts/f5_wave_runup_solver_anchor_runtime_v2.py) SHA-256 为 `84a9fe5620df956bcbff8e9979a21a318b4004837ca3b30cb505cc3186b79b2b`，测试 SHA-256 为 `ec64751aa739dcb60edc8442910a4d1d0fce0652bd53a9d8d1f40695e4054cf5`。它把真实 `Output..... dt:` 作为 cadence gate，保留 `TimeOut=` 仅作诊断，并对 snapshot 外部 attempt 路径安全回退；exact-one、固定15行分母、zero credit、solver/GPU 各一次以及 queue/ledger/registry/matrix mutation 全部保持关闭。
- v2 隔离回归 **6 passed**，F5 anchor 相关回归合计 **20 passed**，真实完成 Run.out 仅读检查得到 `TimeMax=16`、`output_dt=[0.02]`、`Excluded=0`、`Steps=138258`；没有启动新的 solver/GPU/queue，也没有修改当前 v1 attempt。v2 明确拒绝当前 v1 job，下一次必须使用全新输入／输出身份和独立 root review 重新绑定 v2 runtime、job、queue 及 hash closure。
- 这只是基础设施修复准备，不是授权或科学结果；在几何抽样负证据解决之前，不提交新的 F5 资格矩阵，不对当前 anchor 做同输入重试。Core gate 保持 T1 F3/F4、宏观 T2 `0/2`、正式训练 `0/9`。

## 本轮追加：第三 T1 候选路线审计 v2

- 独立路线报告 [CORE-THIRD-T1-CANDIDATE-AUDIT-2026-09-21-v2.zh-CN.md](CORE-THIRD-T1-CANDIDATE-AUDIT-2026-09-21-v2.zh-CN.md) 重新核对 F1、F2 和 F5 的现有谱系，没有启动 GenCase、solver、GPU、queue，也没有写 registry、ledger 或 matrix。报告 SHA-256 为 `68047248a4830be798ee8db6a40520eb1c6db80a736500c330d3f904d62c6bff`，对应 commit `1ce3d4a9e5d4472eda245ae23a8e22ef157dff92`。
- F2 submerged-orifice 的 v2/v3/v4 依次保留 `64,899`、`83,443` 和 `29,484` 个 zero `BoundNor/NormalSize`；v4 的零法向全部位于 `Mk=18` gate，虽然质量误差已回到门槛内，hard gate 仍失败。三条输入均 `credit=0`，禁止同输入重试或直接进入 solver。
- F1 G1、F2 receiver/weir 和当前修复谱系已关闭。F5 仍是最可执行的第三家族候选，但当前 anchor 的抽样几何负证据必须先转成新的、可证伪的 Definition/output 身份和独立 root review；在此之前不授权新的 F5 runtime、solver 或资格矩阵。

## 本轮追加：F5 几何修复 proposal-only 审计

- 只读审计 [geometry-repair-proposal-audit-v1.json](../campaigns/core-v1/cfd/f5-wave-runup-third-t1/geometry-repair-audit-v1/geometry-repair-proposal-audit-v1.json) SHA-256 为 `3163d6e1d75b3ffacbda61afeb18e9e35a98e5e575ded254c6b7b86733ebee42`，commit `52acd00e7146e836f0584ecfa378db457cca2f45`。它重算并复现了九帧、fluid-only、stride-32 的 `891` 个 slope endpoint、`2463` 个 block endpoint 和 `1435` 个 saved-chord crossings；没有启动 GenCase、solver、GPU、queue，也没有修改现有 attempt/root/job、registry、ledger 或 matrix。
- 当前只保留两个有证据的假设：H1 为 fillbox 前缺少显式 closed-solid/void 排除，导致块体初态和后续接触穿透；H2 为严格连续 STL 判定与离散 `MkCells` 接触带的差异使浅层计数偏高。H2 不能解释约 `2.3–2.8 dp` 的 block 深部尾部，也不能作为放宽几何硬门的依据。
- 最小候选是全新 `F5_wave_runup_q0p50_dp0p0075_geomrepair_v3` 输入／输出身份：只改变几何排除的物化顺序或新 hash 的一层壳资产，保留 q、粒距、运动、时域、cadence、观察量和15行分母。proposal 明确 `qualification_claim=none`、`matrix_credit=0`、禁止 same-input retry；必须先由 root review 选择合法 GenCase 排除语法，再授权一次全新 CPU/native preflight，之后还需独立 solver review。
- JSON 校验及 F5 相关回归共 **42 passed**。在 root review 之前不写 v3 Definition/资产，不执行 GenCase/native decode，不提交 solver/GPU 作业；Core gate 仍只有 T1 F3/F4、宏观 T2 `0/2`、正式训练 `0/9`。
