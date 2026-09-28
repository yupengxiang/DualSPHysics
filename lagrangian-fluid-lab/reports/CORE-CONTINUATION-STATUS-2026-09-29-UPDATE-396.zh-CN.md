# Core continuation status — UPDATE-396

日期：2026-09-29

本轮只记录两条 current-manifest training-evidence intake 的独立交付和 6 条 GPU 诊断训练的中间状态；策略继续固定为 GPT-5.6 Luna、reasoning `max`，历史记录不改写。

## 新增可提交单元

- `c8388cea`：graph_raw hidden16 current-manifest bounded training-evidence intake；支持实际 `v3` receipt 路径，严格绑定 manifest raw/canonical SHA、model/config/seed/run/checkpoint 声明，running/partial/missing 一律 fail-closed。
- `90cb0424`：graph_residual hidden16 current-manifest bounded training-evidence intake；复用 residual validator，保持相同的 source/identity/zero-credit 边界。

两项都只读取有界 JSON 和小文件身份，不打开 checkpoint、HDF5、trajectory 或 progress 内容，不启动或控制 GPU。由于真实训练尚未到 500/500，两个报告当前均为 `blocked_fail_closed`、`source_bound=false`、formal training `0`、credit `0`。

## 诊断训练进度

graph_raw 和 graph_residual 的 seed `17/29/43` 六路训练均在 GPU `2/3/4/5/6/7` 的独立 PTY namespace 中自然运行，current canonical manifest 为 `5d53fd9c…c4f768`，目标 500 updates；本次观察均为 `200/500`、finite loss、neighbor truncation `0`。progress 仅用于健康检查，不是 terminal receipt；未停止/重启既有进程，未写 registry、ledger、denominator、gate、completion。

联合 matrix/intake 回归 `41 passed`，并通过 `py_compile`、JSON verify 和 `git diff --check`。训练终态后仍需逐 seed receipt/checkpoint identity intake，再决定是否进入 rollout 证据链；当前 formal training 保持 `0/9`。

## Core 门禁

`can_finalize=false`；T1 `2/3`；macro T2 `0/2`；formal training `0/9`；`missing_t1_case_runs=288`；`missing_material_case_runs=288`；`independent_reproduction=false`；credit `0`。
