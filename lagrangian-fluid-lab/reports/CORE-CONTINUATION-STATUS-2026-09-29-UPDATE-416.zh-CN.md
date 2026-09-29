# Core continuation status — UPDATE-416

本轮继续按并行、由粗到细和独立提交推进；所有新 subagent 固定为 `gpt-5.6-luna`、reasoning `max`，历史记录没有改写。

## F3 三条 seed/模型入口

- `bf9d33bb`：graph_raw/hidden16/seed29 authority projection gap，专项 `5 passed`。
- `ab07f276`：graph_raw/hidden16/seed43 authority-bound diagnostic admission gap，专项 `4 passed`。
- `1c4e4b84`：graph_residual/hidden16/seed17 authority projection gap，专项 `8 passed`。

三条路径都在真实 external scheduler authority、trusted Ed25519 key、nonce/namespace/source/resource binding 或 terminal receipt 缺失处 fail-closed；没有伪造 authority，也没有启动 Popen、solver、worker、GPU、queue。父代理复核共 `17 passed`，py_compile、JSON verify、git diff-check 通过。当前 scheduler 只读状态为 `queued=0、running=0、succeeded=294、failed=19、cancelled=13`；GPU0–7 各约 `48,497 MiB free`，utilization `0%`。

## Core gate

Core 仍为 `can_finalize=false`：T1 家族 `F3/F4`，macro T2 `0/2`，formal training `0/9`，observed T1/material case-runs `0/0`，目标缺口 `432/288`，independent reproduction=false，credit=0。下一步是取得真实 scheduler authority-bound receipts 后再沿三个现有 sealed runner 继续；本地 projection gap 不能替代外部 authority，也不能授予资格信用。
