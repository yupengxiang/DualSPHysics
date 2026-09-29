# Core continuation status — UPDATE-414

本轮继续按并行、由粗到细和独立提交推进；所有新 subagent 固定为 `gpt-5.6-luna`、reasoning `max`，历史记录没有改写。

## 三个独立闭环

- `dac94fd8` / `ca909a59`：F3 `graph_raw/hidden16/seed17` authority projection。旧 receipt 缺少 `authority`、`identity.external_authority` 及 nonce/namespace/source/resource 绑定，且当前生产 scheduler root 不存在；新 adapter 只报告 projection gap，不伪造 authority、不生成 durable runner input；父代理按该测试文件复核 `6 passed`。
- `882f1b7d`：F8/R008 held-FD B/C/D provenance adapter，只用 `fstat + pread`，拒绝 pathname reopen、symlink/hardlink 和 source/attempt/case/time/frame digest 漂移，专项 `16 passed`。
- `0eb0bad2`：A8 full-product receipt/manifest verifier，绑定 receipt、manifest、reader、prediction、scoring 五类 artifact 的 exact digest/bytes/host/data-root/attempt 链，拒绝 self-claim、重复 host/data-root 和链路漂移，专项 `32 passed`。

父代理对三个新测试文件复核为 `36 passed`，py_compile、JSON 校验、git diff-check 通过。所有结果保持 diagnostic-only、formal/T1/T2/independent reproduction=false、credit=0；没有训练、solver/worker/queue/GPU execution、生产 bundle/HDF5 读取、registry/ledger/denominator/gate/completion 修改，也没有停止或重启已有进程。GPU0–7 各约 `48,497 MiB free`，utilization `0%`。

## Core gate

Core 仍为 `can_finalize=false`：T1 家族 `F3/F4`，macro T2 `0/2`，formal training `0/9`，observed T1/material case-runs `0/0`，目标缺口 `432/288`，independent reproduction=false，credit=0。F3 下一步需要真实 external scheduler 重新签发 current-schema authority-bound receipt；F8/A8 的新层只能接收真实可信证据，不能自行 mint capability 或资格信用。
