# F3 fresh nonce partial rollout terminal audit（2026-09-29）

## 结论

使用已提交的 `f3_partial_rollout_terminal_audit_reducer_v1.py` 对 residual 与 graph_raw 的六个 fresh nonce namespace 做了 fail-closed 审计。六条记录均为 `blocked_partial_or_missing_terminal`，`terminal_status=not_terminal`，`source_bound=false`，`qualification_credit=0`，`credit=0`；本报告不把 progress sidecar 或 trajectory 文件提升为终态证据。

观测到的 progress frame 数如下（合约要求为 835 transitions / 836 frames）：

| 模型 | seed 17 | seed 29 | seed 43 |
| --- | ---: | ---: | ---: |
| graph_residual | 250 | 250 | 225 |
| graph_raw | 150 | 150 | 125 |

六个 evaluation JSON 均不存在。六个 trajectory 路径均存在，且仅通过 `lstat` 确认为 regular、single-link 文件（每个 723,148,320 bytes）；没有读取任何 HDF5 内容。六个条目均缺少 process proof。

## 输入 namespace

- residual / seed 17：`/tmp/f3-graph-residual500-hidden16-seed17-full835-noncef4b93914eea211e957eafa63b577c57b`
- residual / seed 29：`/tmp/f3-graph-residual500-hidden16-seed29-full835-nonce1ec294efc2e953eafba49f2c161ba4e5`
- residual / seed 43：`/tmp/f3-graph-residual500-hidden16-seed43-full835-noncebb7d2304f4896d5e37ac9d5ffb1c795e`
- graph_raw / seed 17：`/tmp/f3-graph-raw500-hidden16-seed17-full835-nonced8f2a6c0b4e97135f0c2d8a4e6b1937c`
- graph_raw / seed 29：`/tmp/f3-graph-raw500-hidden16-seed29-full835-noncea9c3e7f1b5d02864e2a6c9f3b7d10485`
- graph_raw / seed 43：`/tmp/f3-graph-raw500-hidden16-seed43-full835-noncee1b7d4a9c2f60835b9e3d7a1c5f02468`

每个 namespace 的输入是对应的 `-evaluation-progress.json`、`-trajectory.h5` 和派生的 `-evaluation.json` 路径；未使用 checkpoint、PID 或 process proof。

## Fail-closed 边界

本次 reducer 运行确认：

- bounded read-only 读取 progress JSON；
- trajectory 只做 `lstat`，`hdf5_content_opened=false`、`trajectory_opened=false`；
- evaluation 只做 `lstat`，`evaluation_content_opened=false`；
- 未观察或使用 live PID，未消费 process proof；
- 未启动、停止或重启 evaluator/solver/worker/GPU；
- 未修改 registry、ledger、gate 或 denominator；
- 未进行 terminal promotion，也未铸造 qualification credit。

## 运行命令与产物

运行命令：

```text
lagrangian-fluid-lab/.venv/bin/python lagrangian-fluid-lab/scripts/f3_partial_rollout_terminal_audit_reducer_v1.py --output /home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-PARTIAL-ROLLOUT-TERMINAL-AUDIT-2026-09-29.json
```

Machine report：[`F3-PARTIAL-ROLLOUT-TERMINAL-AUDIT-2026-09-29.json`](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-PARTIAL-ROLLOUT-TERMINAL-AUDIT-2026-09-29.json)

- schema：`core.f3.partial_rollout_terminal_audit_reducer.v1`
- reducer observed_at：`2026-09-28T16:56:12.624631+00:00`
- machine report bytes：`21571`
- SHA-256：`1f04486dc3558bd6e19070c7d98627b3f6a5fa662e626d665add120f1c7e1a87`
