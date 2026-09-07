# R4 Latest Review Handoff

Date: 2026-09-07

## Decision

R4 的工具链、审计器和候选实验均已执行完毕，但正式 v0.1 物理数据集仍为 `NO_GO`。本轮没有授权生成每族 20–30 例 development tranche。

状态必须继续按四个维度记录：

| 方向 | execution_status | acceptance_status | 当前结论 |
|---|---|---|---|
| F1 九格核心母案例 | completed（仅 GenCase preflight） | `preflight_structural_evidence_only` | 9/9 结构生成成功；尚无 solver 轨迹、T1 或 T2 验收 |
| F1 官方 Test 02 event window | completed | `diagnostic_only_not_physical_acceptance` | 三分辨率 0–2.2 s 压力诊断完成；不能替代 Gold 验收 |
| F6 mDBC runtime normals | completed | candidate-only / rejected | 阈值化 runtime zero normals 仍存在；内缩候选不保持规范物理壁面 |
| W06 material tracer | completed | `candidate_only_rejected` | 四组真实轨迹 rollout 完成；质量账本闭合，但目标、壁面和失败语义未正式接入 |
| G4 model routes | completed | `complete_with_findings` | 当前输入契约与历史 checkpoint 不兼容；不能作四路线排行榜 |

## Evidence produced

### F1 numerical route

- 九个 `F1_obstacle_ladder` GenCase 单元全部返回成功，控制参数一致：`dp = 0.035/0.024/0.014 m`、`TimeMax = 1.5 s`、`TimeOut = 0.001 s`、Verlet `1/40`、DBC。
- 预检发现三分辨率初始流体质量为 `60.025/58.0608/58.216704 kg`，相对 spread 为 `3.342%`；该结果仅作诊断，不是通过条件。
- 官方 Test 02 的三分辨率 mDBC 运行已完成，且 MeasureTool 明确禁用 dummy support（`-kcusedummy:0`）。目前结果只能作为事件窗口诊断：压力观测、完整 6 s 压力/液面 Gold、粒子轨迹和拓扑候选验收仍未闭合。

### F6 boundary route

- `canonical-2` 和 `fine-3` 的 runtime normal 审计分别记录 `63` 和 `240` 个阈值化 zero normals，全部位于 `Mk=18`；ghost≈2×normal 与构造面重合检查通过。
- 这不是物理通过：没有新的 solver/kernel trace、penetration/force 物理观测，序列化 ghost 坐标仍是推断量。`-0.030/-0.020 m` 内缩候选继续标记为 rejected，不能用于掩盖规范壁面偏移。

### Material transport route

- W06 `W06_standard_slow_center` 的实际 release HDF5 已完成 `32/64 seeds × 1/4 substeps` 四组 CPU rollout；初始代表质量 `27.5625 kg`，四组 ledger closure error 均为 `0`。
- 最终可靠质量比例为 `93.764%/95.068%/94.898%/94.728%`。失败原因已分解为 support-distance、support-nonfinite 和 wall-crossing，但仍是候选诊断。
- 1→4 子步的最终质量最大差为 `0.859375 kg`（32 seeds）和 `0.4375 kg`（64 seeds），说明当前 materialization 尚不具备可直接冻结的子步稳定性。
- 真实 release 仍没有正式 destination specification、source-destination closure、wall-aware admission 或持久化的完整 per-step failure channel；`triangle_mk` 只是 sidecar fallback，不是显式 component registry。

### G4 model route

- 当前 sidecar-aware active input 为 `115` 维（LocalInteraction 为 `123` 维），历史 12-run 结果/checkpoint 为 `43` 维；两者不能混排。
- 最近六次小预算复跑只有 LocalInteraction 和 PhysicsResidual，各 `3` 个 seed，不能支持四路线排名。
- 必须先冻结 `input_contract_id`、canonical component slots、target semantics、trainer/config/data hashes、checkpoint state 和 CUDA determinism policy，再统一重跑四路线。

## Gate decision

```text
formal_v0.1             = NO_GO
development_tranche     = NO_GO
F1 numerical route      = GO_T1_ONLY candidate-only; solver gate still pending
F6 mDBC                 = candidate-only/rejected
material transport      = candidate-only/rejected
G4 route ranking        = blocked until contract repair and uniform rerun
```

不能把 `221 passed` 解读为物理验收通过；测试证明的是审计器和契约实现的一致性。

## Next bounded actions

1. **F1 solver gate：**在明确的 GPU 4–7 资源计划下运行九格母案例，保留 `dp/TimeMax/TimeOut/Verlet/DBC` 统一控制；逐帧审计身份、有限状态、质量损失、边界穿透和 saved-cadence，并计算 T1 的三分辨率主观测量。
2. **F1 acceptance closure：**补齐官方 Test 02 的完整物理观测（压力、液面、质量/穿透）以及相同协议下的候选障碍拓扑；若三分辨率分布仍超过 `TV <= 0.05` 筛选线，停止晋级。
3. **F6 E1：**先实现真正的 fixed-body 配置和 fixed/moving force gauge，使用 DBC 对照确认力测量语义；再在不改变规范物理壁面的前提下比较 mDBC/BI4/load-init。Chrono 接触几何与水动力边界分别验证。
4. **Tracer contract：**为一个真实案例冻结 source、destination、open-face/rim/cap 规则、wall component、support threshold、integrator/substeps 和每步 failure reason；重新生成 material artifact 后才可讨论 T2。
5. **G4 contract repair：**统一四路线、三个 seed、同一 current context builder、canonical slots、target/checkpoint/provenance semantics；只用共同 autonomous position metric 做比较。
6. **Tranche gate：**只有 F1 至少通过 T1、T2 destination closure 和对应 tracer/模型契约后，才允许生成首批 20–30 例 development tranche；否则保持 `NO_GO`。

## Reproducibility and resource boundary

- 本轮新增 CFD/GenCase/GPU 证据均记录在各自 report 和 attempt directory；F1 GPU 仅使用 `4/5/6`，`0–3` 未使用。
- W06 是 CPU-only bounded rollout；没有修改 DualSPHysics 上游目录。
- 本交接没有执行远程 push；本地改动及报告待用户确认后再提交。

## Primary reports

- [R4 core mother-case audit](./r4-core-mother-case-audit.json)
- [F1 core preflight](./r4-f1-core-preflight.json)
- [F1 official Test 02 event window](./r4-f1-test02-event-window.json)
- [F6 mDBC runtime normal audit](./cases/r3-fixed-box-force-gauge/r4-mdbc-runtime-zero-normal-audit.json)
- [Tracer actual-scenario audit](./r4-tracer-actual-scenario-audit.json)
- [W06 bounded tracer experiment](./r4-w06-tracer-bounded-experiment.json)
- [G4 training contract audit](./r4-g4-training-contract-audit.json)
