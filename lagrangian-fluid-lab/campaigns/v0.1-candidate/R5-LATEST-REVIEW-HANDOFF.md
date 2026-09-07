# R5 latest reviewer handoff

日期：2026-09-08
分支：`codex/lagrangian-fluid-exploration`
范围：云端 reviewer 下发的 F1 solver gate、F1 material task、G4 contract/smoke

## 总结决定

本轮完成了真实的 F1 九格求解、逐帧审计、一个真实材料输运任务，以及一个接入 R5 合同的 G4 GPU smoke。工具链证据可以保留，但正式 v0.1 物理数据和 development tranche 仍然不能冻结。

| 方向 | execution_status | acceptance_status | 当前结论 |
|---|---|---|---|
| F1 九格 solver gate | `completed`，9/9 actual solver attempts，9/9 HDF5 audit | `candidate_t1_only_for_qualified_backgrounds` | 仅 `plain_dam_break` 三分辨率通过 T1 诊断线；无外部/物理验收 |
| F1 material task | `completed`，4 个 CPU 配置 | `candidate_only_not_physical_acceptance` | 轨迹、来源层、目的地、壁面、支撑和质量账本已落盘；仍不是 T2 物理通过 |
| G4 input contract | `completed`，16 CPU tests | contract implementation candidate | 当前直接路线 115 维、LocalInteraction 123 维；历史 43/51 维拒绝 |
| G4 GPU smoke | `completed`，ParticleMLP seed 17 | smoke only | result/checkpoint 成对 contract 通过；不能形成四路线排行榜 |
| F6 mDBC | unchanged | candidate-only/rejected | 仍被 zero-normal/规范壁面 ghost 几何和固定体测力物理校准阻塞 |

最终门禁仍为：

```text
formal_v0.1       = NO_GO
development_tranche = NO_GO
```

## 1. F1 九格真实 solver gate

机器报告：[`r5-f1-solver-gate.json`](r5-f1-solver-gate.json)。运行入口和 attempt provenance 在 `runs/r5-f1-solver-gate/`；标准化数据在本地 `data/r5-f1-solver-gate/`，未提交大文件。

九个实际 solver 单元均使用同一控制协议：

```text
TimeMax     = 1.5 s
TimeOut     = 0.001 s
dp          = 0.035 / 0.024 / 0.014 m
Boundary    = DBC, parameter 1
Verlet      = StepAlgorithm 1, VerletSteps 40
shifting    = off
output      = 0.001 s
```

资源边界严格遵守 reviewer 计划：solver 只使用 GPU 4--7；GPU 0--3 保护；最多四个 heavy jobs。实际 nine-cell 映射使用了 GPU 4、5、6、7，其中 GPU 4 UUID 为 `GPU-74ce8a29-c3cd-1e50-a9b4-a2293f2335c9`；本轮 G4 smoke 也只使用这个授权 GPU 4。

九格共同结果：每个 HDF5 都有 1501 帧、有限状态和有效生命周期审计；闭域 wall/obstacle penetration 诊断没有报告穿透。T1 的固定尺度质量分布比较为：

| background | coarse→medium TV | medium→fine TV | 身份/审计状态 | T1 诊断 |
|---|---:|---:|---|---|
| `plain_dam_break` | 0.045000 | 0.023674 | 三档 `pass_diagnostic`，质量闭合 | candidate T1 only |
| `center_obstacle` | 0.179048 | 0.110468 | medium 缺 1、fine 缺 75；需区分合法出域和数值丢失 | blocked |
| `twin_obstacle_split_remerge` | 0.051667 | 0.140510 | fine 缺 2；需身份损失分类 | blocked |

center medium/fine 和 twin fine 的缺失身份都有 solver log 的 excluded count，但当前证据不能将其分类为合法 open-face exit 或 numerical loss，因此状态保持 `unknown`，没有按零损失或成功归一化处理。`TV <= 0.05` 只是预注册 T1 diagnostic line，不是物理真值证明。官方 Test 02 的完整压力/液面 Gold 和外部 reference gate 仍未闭合。

## 2. F1 material task

机器报告（提交的摘要）：[`r5-f1-material-task-summary.json`](r5-f1-material-task-summary.json)；完整本地报告为 [`artifacts/r5-f1-material-task/r5-f1-material-task.json`](artifacts/r5-f1-material-task/r5-f1-material-task.json)。输入是实际的 `R4_F1_center_obstacle_medium` HDF5 与对应 sidecar；solver 未重跑，任务本身 CPU-only。四个配置为 `128/256 seeds × 2/4 substeps`，均由同一单进程、同一 evaluator 版本重建。

四个 bundle 的可见性模式均为 `adaptive_exact_visible_top_k`，search width 为 96；完整 sidecar 仍用于 swept collision，interpolation visibility 只使用单 obstacle component，并记录 tank convexity 的限定理由。所有四组 mass ledger closure error 都为 0，且不做 survivor renormalization。

- 128 seeds × 2/4：最终 tracer mass fraction 均为 1.0；无 failure；47 个 seed 观察到目标首次通过，81 个为窗口末端 right-censored。
- 256 seeds × 2/4：最终 tracer mass fraction 为 `0.990238`；每组 1 个 wall crossing、2 个 support-distance exceedance，另有一个 tracer 被记为 unknown/censored；两组均保留 `closure_error=0`，没有把失败样本伪装成 negative label。
- `source_label` 只有 lower/middle/upper 初始深度测量分层，不是材料身份；身份仍由 `(Zone, Idp)` reference pair 绑定。
- `destination`、open-face/rim/wall-crossing、support threshold、failure channel 和初始质量分母已经持久化，但物理 destination closure 和外部观测尚未验收。

因此本任务证明了 R5 material artifact 可以消费真实 F1 轨迹并保留失败/质量语义，但不授权正式 T2，也不授权 tranche。W06 negative control 本轮没有重跑，仍保持 reviewer 指定的 negative-control 状态。

## 3. G4 contract 与 GPU smoke

合同文件：[`experiments/r5_g4_contract.py`](../../experiments/r5_g4_contract.py)、[`r5-g4-contract/input-contract.json`](r5-g4-contract/input-contract.json)，CPU contract tests 为 16 passed。合同固定：

- sidecar-aware base block 为 115 维；direct routes 为 115，LocalInteraction 为 123；
- component slot 按 `(type, component_id)` 字典序 canonicalize，缺失 mask 显式 zero-fill；
- target、rollout integrator、current control、future-state prohibition 明确记录；
- trainer/config/data SHA、contract hash、checkpoint mode 和 CUDA determinism policy 成对绑定；
- historical 43/51-wide artifacts 不是兼容输入，必须拒绝。

实际 smoke 使用 ParticleMLP、seed 17、1 epoch、授权 GPU 4。结果：

```text
one-step validation RMSE       = 0.255079 dp
autonomous validation RMSE     = 32.731199 dp
test rollout                   = 3/3 completed
peak GPU memory                = 70,786,560 bytes
```

结果 JSON 为 [`particle_mlp_seed17.json`](../../experiments/r5-g4-smoke/particle_mlp_seed17.json)，本地 checkpoint 为 inference-only artifact；result/checkpoint contract pair 验证通过。one-step 与 autonomous 的差异再次说明不能用单步误差代替长时 rollout。四路线 × 三种子尚未执行，历史 43/51 维结果不能混入。

## 4. 当前阻塞与下一步

1. 为 `plain_dam_break` 补官方 Test 02/外部 reference anchor；只有 T1 与 reference 共同通过，才可把它放入候选 development tranche。
2. 对 center/twin 重新核查开放边界/身份生命周期，分类 excluded particle 是合法出域、数值丢失还是导出语义问题；在 TV 和身份状态达标前不晋级。
3. 在同一 material evaluator 上补 F1 single-obstacle fine artifact，并比较 resolution/substep stability；仍需物理 destination closure 才能过 T2。
4. 以当前 115/123 contract 做 G4 四路线×三种子统一实验；只比较共同 autonomous position metric，不引用旧 43/51-wide artifacts。
5. F6 继续按 fixed-body/force-gauge 物理校准路线推进；不以 mDBC zero-normal candidate 代替规范物理壁面验证。
6. 只有相关 family 通过 T1、T2 和对应 reference/contract gates 后，才允许生成 20--30 例 development tranche；当前仍保持 `NO_GO`。

本轮未修改 DualSPHysics 上游目录，未提交 solver raw BI4/CSV、约 2.2 GB F1 HDF5、material bundle 或 G4 checkpoint binary。
