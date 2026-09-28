# Core continuation status — UPDATE-395

日期：2026-09-29

本轮继续按照 GPT-5.6 Luna、reasoning `max`、可并行且不重叠的子代理策略推进，并保持由粗到细：先把 F3 current-manifest 的三种模型方向接通，再等待真实训练终态，最后才做终态 intake。历史模型记录和历史 receipt 均未改写。

## 本轮已提交

- **F1/F2 当前快照修复：** `9b0c3520` 刷新 v3 card/receipt 到当前 `completion.json`；`d4c150da` 将 v2 验证器和测试明确改为 historical immutable semantics。v2 card/receipt、completion、registry、ledger、分母和 gate 均未改动；F1/F2 v2/v3 套件 `7 passed`，credit 仍为 `0`。
- **F3 graph_raw current-manifest matrix：** `a2b843ea` 完成 32 cases × 3 seeds 的 96 个 bounded dry-run 计划，namespace、nonce、command identity 均 `96/96` 唯一；`launch_allowed=false`、terminal receipts `0/96`、`blocked_fail_closed`、credit `0`。
- **F3 graph_residual current-manifest matrix：** `776eaa1c` 完成同等 96 个计划，并支持实际 `-v3` training receipt 的显式状态绑定；当前仍 `blocked_fail_closed`、terminal receipts `0/96`、credit `0`。

两个 graph matrix 都只消费有界 JSON/小文件身份，不打开 checkpoint、HDF5、trajectory 或 progress 大文件，也不启动/控制 GPU。各自专项及历史联合回归均为 `55 passed`。

## 当前真实诊断训练

在正确的持久 PTY 会话中启动了 6 条独立 current-manifest 诊断训练：`graph_raw` 与 `graph_residual`，hidden16，seed `17/29/43`，每条 500 updates，GPU `2/3/4/5/6/7`，唯一 `v3` run-id 和 `/tmp` 输出 namespace。GPU 2–7 均保留显存余量；GPU6 原已有占用，但仍有足够显存，未停止或重启任何既有进程。

截至本回执，六条均到 update `100/500`，loss 全部 finite，`neighbor_truncation_fraction=0`，仍为 `running`。这些 progress/PID 只用于健康观察，不能作为 terminal receipt；training receipt、checkpoint identity 和 terminal status 尚未生成，因此 formal training 仍计 `0/9`。本轮实际训练是 diagnostic-only，不写 registry、ledger、denominator、gate、completion，不产生资格信用。

## 验证与边界

F1/F2 `7 passed`；graph_raw matrix `55 passed`；graph_residual matrix `55 passed`；`py_compile`、JSON verify、`git diff --check` 均通过。没有启动裸 batch executor；只启动了 6 条有唯一 namespace 的 diagnostic training。训练自然完成后，下一步是逐 seed 校验 `core.training.v1` receipt、checkpoint identity 和 current-manifest SHA，再生成 bounded training-evidence intake；未完成前不做 rollout/正式分母晋级。

## Core 门禁

`can_finalize=false`；T1 family `2/3`；macro T2 `0/2`；formal training `0/9`；`missing_t1_case_runs=288`；`missing_material_case_runs=288`；`independent_reproduction=false`；credit `0`。F3 material coarse 的 fresh root/scheduler receipts、F4 sidecar、A8 异机 non-diagnostic evidence、F8 target kernel/build/runtime pins 等既有 blocker 均保持不变。

本轮新增两个 graph matrix 报告、F1/F2 当前快照修复和 6 条 diagnostic training 的运行记录；不把进行中的训练或 dry-run matrix 宣称为 Core formal 完成。
