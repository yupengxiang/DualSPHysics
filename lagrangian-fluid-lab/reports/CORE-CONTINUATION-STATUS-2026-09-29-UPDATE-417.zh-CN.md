# Core continuation status — UPDATE-417

本轮继续按并行、由粗到细和独立提交推进；所有新 subagent 固定为 `gpt-5.6-luna`、reasoning `max`，历史记录没有改写。

## F3 当前 hidden16 模型矩阵的剩余五个入口

- `0441b971`：graph_residual/hidden16/seed29 authority projection gap，专项 `20 passed`。
- `9f789ece`：graph_residual/hidden16/seed43 authority projection gap，专项 `9 passed`。
- `fdccd5dc`：MLP/hidden16/seed17 authority projection gap，专项 `5 passed`。
- `e740fbd8`：MLP/hidden16/seed29 authority projection gap，专项 `55 passed`。
- `acab56f2`：MLP/hidden16/seed43 authority-bound admission gap，专项 `6 passed`。

五条路径均在真实 external scheduler authority、trusted Ed25519 root/key、producer-issued receipt、one-shot claim、nonce/namespace/source/resource/GPU 绑定或 terminal receipt 缺失处 fail-closed；没有从本地声明伪造 authority，也没有启动 Popen、solver、worker、GPU 或 queue。父代理复核五个新测试文件共 `36 passed`，py_compile、JSON 校验和 git diff-check 通过。当前 scheduler 只读状态为 `queued=0、reserved=0、launching=0、running=0、attention=0、succeeded=294、failed=19、cancelled=13`；GPU0–7 各约 `48,497 MiB free`，utilization `0%`。

## Core gate

Core 仍为 `can_finalize=false`：T1 家族 `F3/F4`，macro T2 `0/2`，formal training `0/9`，observed T1/material case-runs `0/0`，目标缺口 `432/288`，independent reproduction=false，credit=0。当前 F3 的九个 model×seed 入口都已有独立的 admission/gap 边界记录，但这不等于 formal terminal evidence，也不授予训练、T1 或 T2 信用。下一步仍是取得真实 scheduler authority-bound receipts 后沿 sealed runner 继续；显存充足本身不替代外部授权。
