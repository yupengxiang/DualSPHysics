# Core continuation status — UPDATE-398

日期：2026-09-29

本轮完成 F3 current-manifest graph 训练 receipt 到 32-case × 3-seed matrix 的合同收敛。真实六路训练 receipt 已在 UPDATE-397 中绑定；本轮只更新 matrix 入口，不重写旧 matrix、旧 receipt 或 Core completion。

## 独立提交

- `138dd62d`：graph_raw matrix 使用真实 producer 的 deferred validation 配置：`evaluate_milestones=false`、`milestone_evaluation_mode=deferred`、`validation_every=0`。
- `e9e25a5f`：graph_residual matrix 接受真实 `core_learning` producer 省略的可选 top-level `status`，以 bounded `evidence_status=complete` 与 terminal status hint 完成绑定；显式非 completed status 仍 fail-closed，并补充 producer-shaped fixture 回归。
- `545ab553`：提交两组 current-manifest matrix RERUN1 JSON/中文报告。

## 当前 matrix 结果

| model | source-bound | case jobs | unique identity | terminal evaluator receipts | launch |
|---|---:|---:|---:|---:|---|
| graph_raw | true | 96 | 96/96 namespace、nonce、command | 0/96 | false |
| graph_residual | true | 96 | 99/99（含 3 个 training identity） | 0/96 | false |

- [graph_raw matrix RERUN1](F3-GRAPH-RAW-HIDDEN16-CURRENT-MANIFEST-CASE-MATRIX-2026-09-29-RERUN1.json)：`dry_run_matrix_ready`，matrix SHA `49fe72d5…9a302`。
- [graph_residual matrix RERUN1](F3-GRAPH-RESIDUAL-HIDDEN16-CURRENT-MANIFEST-CASE-MATRIX-2026-09-29-RERUN1.json)：`dry_run_matrix_ready`，matrix SHA `bc144b92…ae4f1`。

两组 matrix 只读取 bounded manifest、training receipt 和小型身份 metadata；不打开 checkpoint、HDF5、trajectory、evaluation 或 progress，不启动/停止/重启 evaluator，不写 registry/ledger/denominator/gate/completion。source-bound 仅表示训练身份已经被当前 v3 receipt 绑定，不表示 full835 已完成，也不授予 `launch_allowed`。

## 验证与门禁

raw/residual rollout contract、matrix、training intake、F1/F2 联合回归为 `72 passed`；`py_compile`、JSON verify、`git diff --check` 通过。full835 batch executor 尚未实现/启动，terminal evaluator receipts 仍为 `0/192`。

Core 仍为 `can_finalize=false`：T1 `F3/F4`（2/3），macro T2 `0/2`，formal training `0/9`；T1 case-run 缺 `288`（目标缺 `432`），material case-run 缺 `288`，independent reproduction=false，credit `0`。下一步按审计建议优先选 graph_raw 做固定代表案例的 3-seed full835 canary，但必须先通过独立 audited executor、fresh namespace、VRAM/CPU/I/O admission 与 terminal validator 闭环。
