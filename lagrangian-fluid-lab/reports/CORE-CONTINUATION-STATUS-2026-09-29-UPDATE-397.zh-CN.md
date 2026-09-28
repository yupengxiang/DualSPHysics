# Core continuation status — UPDATE-397

日期：2026-09-29

本轮沿 F3 current-manifest graph 方向由粗到细推进：先完成 raw/residual hidden16 full835 的 bounded rollout contract，再完成六路真实 diagnostic training 的终态 intake。所有后续 subagent 策略入口已核对为精确 `gpt-5.6-luna`、reasoning `max`；历史 GPT-6、Terra 或其他模型记录保持不动。

## 已完成的独立可提交单元

- `1a0bb38a`：graph_raw hidden16 current-manifest full835 rollout contract；固定 case/835 transitions/836 frames/seed 17/29/43，nonce、namespace、command identity 全部 bounded，默认 `launch_allowed=false`、terminal receipts `0/3`、zero-credit。
- `2a7aee4e`：graph_residual 对应 full835 rollout contract，边界相同，未启动、停止或重启任何 rollout。
- `92ca5674`：隔离 residual case-matrix 测试 fixture，生产 `/tmp/f3-graph_*currentmanifest...v3-training.json` 不再被测试写入；专项 graph raw/residual matrix 共 `17 passed`。先前产生的合成 residual fixture 已移至可恢复 `/tmp/f3-evidence-quarantine-20260929/`，未与真实 receipt 混用。
- `7ea82487`：raw training intake 对齐真实诊断命令的 deferred-validation 配置：`evaluate_milestones=false`、`milestone_evaluation_mode=deferred`、`validation_every=0`；专项 `13 passed`。
- `3108b151`：residual training intake 对齐真实 `core_learning` receipt 的 producer metadata、normalization 明细、`resume_semantics` 与省略可选 top-level `status` 合同；未知字段、路径/identity 漂移和非零权限仍 fail-closed；专项 `14 passed`。

## 六路真实训练终态

六路任务在 GPU `2/3/4/5/6/7` 的独立 PTY namespace 中自然完成，每路均为 500/500 updates、finite loss、neighbor truncation `0`，没有停止或重启既有任务：

| model | seed | loss MSE | elapsed (s) | terminal receipt |
|---|---:|---:|---:|---|
| graph_raw | 17 | 0.0772837251 | 2340.34 | completed |
| graph_raw | 29 | 0.2717114687 | 2318.35 | completed |
| graph_raw | 43 | 0.1758372784 | 2323.18 | completed |
| graph_residual | 17 | 0.0528972261 | 2484.69 | completed |
| graph_residual | 29 | 0.2109590471 | 2274.75 | completed |
| graph_residual | 43 | 0.2622066140 | 2281.90 | completed |

当前 manifest raw SHA 为 `8d87da6a…e680`，canonical SHA 为 `5d53fd9c…c768`。两组 bounded intake 均已成功绑定三 seed：

- [graph_raw RERUN2 JSON](F3-GRAPH-RAW-HIDDEN16-CURRENT-MANIFEST-TRAINING-EVIDENCE-2026-09-29-RERUN2.json)：`diagnostic_bound`、`source_bound=true`、formal training `0`、credit `0`。
- [graph_residual RERUN5 JSON](F3-GRAPH-RESIDUAL-HIDDEN16-CURRENT-MANIFEST-TRAINING-EVIDENCE-2026-09-29-RERUN5.json)：`diagnostic_bound`、`source_bound=true`、formal training `0`、credit `0`。

Intake 只打开 bounded manifest/receipt JSON；不打开 checkpoint、HDF5、trajectory、evaluation 或 progress，不启动 GPU，不写 registry/ledger/denominator/gate/completion。`diagnostic_bound` 不是 formal training 证据，也不授权 full835 batch rollout。

## 验证与 Core 门禁

本轮 raw/residual rollout contract、case matrix、training intake、F1/F2 回归联合通过 `71 passed`；`py_compile`、JSON verify、`git diff --check` 均通过。full835 contract 仍保持 `launch_allowed=false`，尚未裸启 96-case batch。

Core completion 仍为 `can_finalize=false`：T1 家族 `F3/F4`（2/3），macro T2 `0/2`，formal training `0/9`；缺失 T1 case-run `288`、material case-run `288`，目标 T1 `432`、目标 material `288`，independent reproduction=false，credit `0`。本轮不修改 registry、ledger、分母、completion 或任何历史 receipt。
