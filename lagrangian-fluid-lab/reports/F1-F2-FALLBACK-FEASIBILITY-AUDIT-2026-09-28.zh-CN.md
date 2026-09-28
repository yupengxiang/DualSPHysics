# F1/F2 后备路线只读可行性审计（2026-09-28）

结论先说：F1 和 F2 都有可复用入口与数据，但当前都不能算第三个 T1 家族，也不能产生 qualification credit。F1 的输入准备链更完整，F2 的静态 full-cup volume-hold 物理场景更独立；两者的立即阻塞分别是“F1 旧修复谱系已关闭、缺 runtime matrix”和“F2 静态 cell-00 已硬失败、其余 14 个 runtime product 缺失”。

本审计只读检查现有 `PLAN.md`、scripts、campaign JSON、reports、XML/CSV/既有 receipt；没有启动 GenCase、native decoder、solver、worker、GPU 或 queue，没有修改 registry、completion、ledger、denominator、gate 或 `PLAN.md`。GPU 显存不是本轮阻塞；当前阻塞是科学硬门、谱系、授权和可审计运行产物。

## 与 PLAN 的关系

`PLAN.md` 明确把 F1/F2 放在 F8 之后的后备位置：F1 是溃坝/绕障，已有 native exclusion/runtime-domain 修复取证，但排除尚未归零且还缺完整参考研究；F2 有生成/诊断入口，但静止保持、运动杯壁、杯口和数值参考接入仍未闭合。资格-only 案例不得进入训练、归一化或模型选择。

当前 Core 仍只有 `F3/F4` 两个登记 T1 family；本报告没有改变这一状态。

## F1：可复用资产与阻塞

可复用入口：

- `scripts/core_f1.py`：`prepare`、`write-design`、`prepare-reference`、`validate-reference`、`make-reference-job`、`run`。
- `scripts/core_f1_qualification.py`：F1 geometry-aware observer、manufactured calibration、formal design、matrix preparation、job construction、evaluation 和 failed-canary forensics。
- `scripts/finite_wall_audit.py`：closed-wall endpoint、saved-chord、finite-geometry 检查。
- `scripts/core_cfd_dataset.py`：未来将 F1 轨迹接入 Core HDF5/manifest 的公共入口；当前 raw F1 资产还没有正式 Core dataset manifest。

资格设计已经相当具体：15 行，9 个 `q={0,.5,1}` × `dp={.01,.0075,.005}` 空间行，4 个 `q={.25,.75}` held-out 行，2 个 `q=.5, dp=.0075` 的 internal-time/native-output comparator；初始窗口 2.2 s，可按冻结规则一次延长到 4.4 s，输出间隔 0.02 s。candidate card 的 15/15 native mass gate 通过且不做 mass rescaling；observer calibration 也通过。

实际可复用程度：

- `campaigns/core-v1/cfd/prepared/F1_H1_qualification` 中有 15 个 `prepared.json`，本次只读解析显示 15/15 `preflight_pass=true`。
- `f1-reference-qualification-jobs.json` 有 15 个 job spec，但状态是 `prepared_only; canary gate required before qualification`；每行仍缺 `result.json`、`trajectory.h5`、`audit.json`、`observations.json` 这一整套 runtime product。
- `f1-qualification-evaluation.json` 明确 `T1_numerical=false`、`qualified=false`、15 行 missing，不能把 prepared 误读成 qualification。

历史失败可以复用为谱系和停止证据，但不能复用为资格：

- H1/H2 mDBC summary：`hard_integrity_pass=false`，53742 个 endpoint-violation particle frames，6689 个 native deaths，最终 mass fraction `0.9445623166304762`；结论是停止该 F1 repair mechanism。
- G1 suspended-obstacle anchor：event window complete，但 `hard_integrity_pass=false`；84 个 closed-wall endpoint frames、615 个 obstacle-penetration frames、1700 个 saved-chord crossings，且 valid count 从 120658 变为 120577。
- H3 forensic：302558 个 obstacle-penetration particle frames、302559 个 chord crossings、246 个 endpoint frames，仍是 terminal scientific failure。
- H4 只有静态候选和解释，没有 H4 solver result；不能当作运行通过。

因此 F1 当前不是“缺脚本”，而是：必须先提出一个超出 H1/H2/H3/G1 关闭谱系的新、可证伪、hash-bound Definition，并经过新的 root review。只改 CFL、observer、输出名字或重复旧输入，都不足以重开。重开后仍需全 15 行 runtime、Core HDF5/manifest、空间/时间/cadence/事件硬门和独立 campaign review；再往后还需 32 个独立开发案例，才能成为 Core 产品家族。

## F2：可复用资产与阻塞

入口分为静态和动态两层：

- `scripts/core_f2.py`：`prepare-static-hold`、`make-job`、`run`，是静态 substitute/canary 路径。
- `scripts/core_f2_resting_fill.py`：静态 full-cup observer，包括 `observe_static_hold`。
- `scripts/core_f2_qualification.py`：动态 rotating-cup design/matrix/canary/observer/evaluate/forensics 入口。
- `scripts/f2_resting_fill_side_wet_v3.py`：静态 full-cup CPU preparation lineage。
- `scripts/core_cfd_dataset.py`：未来 F2 HDF5/manifest adapter 的公共入口。

### 静态 full-cup volume-hold

这是目前最值得保留的 F2 物理候选：它与失败的 rotating-cup/receiver transfer 场景不同，参数轴是 initial liquid volume，15 行设计为 9 个 qualification spatial、4 个 held-out、2 个 temporal comparator，窗口 0.6 s、static settle hold 0.2 s。名义 full-cup anchor 已有 hard integrity、event complete、无 outside-cup mass，最大 kinetic fraction `0.00019179944700252995`，mass error `-0.021614748887476387`；但 anchor 明确只能作为 preparation/geometry anchor，不能进入 15 行 numerator，也不能证明动态 F2。

CPU preparation 的历史演进很重要：v1 是 `0 prepared/15 failed`，v2/v3 是 `7 prepared/8 failed`，v4 达到 `15 prepared/0 failed`。v4 的报告同时明确 `matrix_jobs_materialized=false`、`solver_invoked=false`、`gpu_invoked=false`、queue/registry/ledger mutation 为 0。因此 v4 证明了“输入准备可行”，没有证明 runtime 或 T1。candidate card/plan 层仍然是 root-review-only、未提交。

既有 runtime receipt 反而保留了明确阻塞：cell-00 一次 runtime 失败，类别包括 `cup_closed_face_endpoint`、`cup_saved_chord_crossing`、`open_cup_escape` 和 `spatial_comparison_failed`；其余 14 行没有 runtime product。后续 boundary-repair receipt 保留同一个失败分母和同类失败，`candidate_scope_pass=false`、`T1_numerical=false`。所以不能把 v4 的 15/15 prepared 升格为静态资格。

如果未来决定真正重开，首先要做的是一个新的、hash-bound boundary/open-mouth Definition 或独立物理 Definition，并取得 root review；不能对 cell-00 做同输入重试。之后才是 15/15 独立 trajectory、hard/static/spatial/temporal/held-out gate，以及正式 Core interface。现有 `f2-real-qualification-interface.json` 只有 1 个 canary case 且 `formal_release=false`。

### 动态/接液路线

这些路线可作为负证据和失败分母复用，不是当前可运行后备：

- `F2_pour_duration_x_v1` 的 15-cell matrix 已 withdrawn before submission；有限 runtime envelope 无法满足 2.5 s no-missing-native-ID gate，旧 job manifest 禁止重新 queue。
- DBC 5 s/后续延长 canary 保持 hard identity，但 event window 未完成，未 settled；5 s 末 `speed_p95=0.3996844587968333 m/s`、最大 kinetic fraction `1.1561968036999586`，不能晋级。
- receiver/overflow-weir 固定 15 行中 `executed=1, failed=1, event_censored=1, unattempted=14`；hard integrity 失败，不能 retry。
- receiver ballistic v1/v2、distributed-slot v1/v2、submerged-orifice normal-remediation v2/v3/v4 和 H2 static-hold 都已有保留的 hard/input failure；例如 zero BoundNor 为 124608→76095，orifice v2/v3/v4 为 64899/83443/29484，H2 static-hold 有 8 个 scientific failures。

这些 evidence 可以帮助我们避免重复旧拓扑、保持固定 denominator、写新 root review；不能变成 F2 T1、不能替代新 Definition、也不能成为训练数据。

## 可读 raw 资产的边界

仓库中 legacy `cases/F1` 有 4 个 XML、`runs/F1_*` 有 4 个运行；legacy `cases/F2` 有 3 个 XML、`runs/F2_*` 有 3 个运行。本次只读 CSV 检查显示：

- F1：每个 run 的 CSV/BI4/VTK 可读，`dp=.04`，时长约 0.55–0.65 s，首尾 fluid rows 保持，位置/速度/质量 finite，native IDs 唯一，solver log code=0。
- F2：3 个 raw run 可读、`dp=.04`、约 0.65 s；centered 和 offset 运行分别从 175 丢到 173/174 个 fluid rows，two-source 从 200 保持 200。这是有用的 exploratory failure/smoke 证据，不是 formal Core truth。

这些 raw folders 没有 Core 所需的正式 source-bound trajectory-HDF5/known-input/manifest/split 闭包；不能直接填补 F1/F2 的 Core runtime matrix。

## 当前授权与最小先行实现

全局 `f1-f2-third-t1-route-closed-v3.json` 是 `route_closed_no_new_hypothesis`：`authorized_now=false`、第三家族未建立、credit=0、registry/ledger/denominator mutation=0。GPU 资源充足不改变这个授权判断。

优先级如下：

1. F1：先完成新的物理 Definition、root review 和新 canary；不允许同类旧输入 retry。
2. F2-static：先处理 cell-00 boundary/open-mouth hard failure，形成新的 Definition/namespace/root review；不能只复用 v4 prepared 或 anchor trajectory。
3. F1/F2 共同：补齐 Core HDF5/manifest/known-input/source hash/split adapter，再做完整固定矩阵 runtime。
4. 只有 T1 真的通过后，才补 32 个独立开发案例、材料侧车、训练/rollout/评测和复现链。

## 交付与校验

本审计新增：

- [机器报告 JSON](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F1-F2-FALLBACK-FEASIBILITY-AUDIT-2026-09-28.json)
- [本中文报告](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F1-F2-FALLBACK-FEASIBILITY-AUDIT-2026-09-28.zh-CN.md)

JSON parse 和 `git diff --check` 在提交前执行；提交只包含这两个新文件，不包含并行 F4 工作树中的文件。
