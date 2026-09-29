# Core continuation status — UPDATE-412

日期：2026-09-29

本轮继续按并行、由粗到细和独立提交推进；所有新 subagent 均固定为 `gpt-5.6-luna`、`max`，历史记录没有被改写。

## 三个独立单元

- `c158533e`：A8 package bridge post-fix RERUN1。5 项测试确认 authority mutation 与重复 host mutation 都被拒绝；当前 v2 包仍为 reader-only、0 checkpoint、zero-credit。
- `b5f69279`：建立九个 formal training run 的共同 readiness matrix（graph_raw/graph_residual/mlp × seed17/29/43）。9/9 均为 `blocked_fail_closed`，formal spec/release/root trust/terminal evidence/credit 全部缺失；没有创建 spec、没有 launch，专项 `8 passed`。
- `b2ea07dc`：F4 Tallwall120 material/T2 RERUN3 gap audit。material sidecar 为 `0/32`，fresh-root、scheduler host-I/O、terminal sidecar 和 source/reader drift prerequisites 均未闭合，因此仍禁止创建/提交新 spec；专项 `5 passed`。

## Core 正式状态与安全边界

`core_campaign.py status` 仍为 `can_finalize=false`：T1 family 只有 `F3/F4`，macro T2 为 `0/2`，formal training 为 `0/9`；observed T1/material case-runs 为 `0/0`，固定需求为 `288/288`，目标缺 `432/288`，independent reproduction 为 `false`，credit 为 `0`。

本轮没有训练、solver/worker/queue/GPU execution，没有打开大文件，没有修改 registry、ledger、denominator、gate、completion，也没有停止或重启已有进程。核验时 GPU0–7 每张约 `48,497 MiB free`、利用率 `0%`；显存可用不替代 external trust anchor、formal release、terminal evidence 或固定分母。

## 下一步

A8 继续等待真实 trusted-root/external-host/distinct-data-root/full-product receipt；F4 继续等待 fresh-root/host-I/O/source-reader/terminal sidecar prerequisites；九个 formal run 统一等待 formal release/root trust/terminal contract。所有这些门槛闭合前，不创建新 formal spec、不提交未经准入的 workload，也不把 diagnostic/readiness 结果计入正式分母。

详见 [UPDATE-412 JSON](CORE-CONTINUATION-STATUS-2026-09-29-UPDATE-412.json)、[A8 post-fix RERUN1](A8-PACKAGE-REPRO-BRIDGE-POST-FIX-SECURITY-RERUN1-2026-09-29.json)、[formal readiness matrix](CORE-FORMAL-TRAINING-READINESS-MATRIX-2026-09-29.json)、[F4 RERUN3 gap](F4-TALLWALL120-MATERIAL-COARSE-T2-RERUN3-GAP-2026-09-29.json) 与 [PLAN.md](../../../PLAN.md)。
