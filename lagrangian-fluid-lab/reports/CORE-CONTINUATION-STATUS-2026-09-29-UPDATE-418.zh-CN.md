# Core continuation status — UPDATE-418

本轮继续按并行、由粗到细和独立提交推进；所有新 subagent 固定为 `gpt-5.6-luna`、reasoning `max`，历史记录没有改写。

## 五个独立边界

- `565ba305`：F3 hidden16 九个 model×seed authority-gap 的只读聚合，覆盖 `9/9`、唯一完整，专项 `7 passed`。
- `0a6ca907`：F4 Tallwall120 material T2 sidecar aggregate gap。确认已有 source-bound 32-case contract 已足够，不重复造 matrix；当前 sidecar `0/32`、complete `0/32`、source drift `32`，相关 contract 回归 `37 passed`。
- `37e829f5`：形式 release→observed T1 case-run aggregate join，固定 `432` 个目标行（每个 9 个 formal run 为 F3 `32` + F4 `16`），当前 observed `0`，专项 `5 passed`。
- `2a4717b7`：F8/R008 target-kernel/source/build/runtime pin authority reconciliation，`6` 个 required pin 中跨合同匹配 `0`，专项 `14 passed`。
- `7b811d59`：A8 full-product reader/prediction/scoring 与 trusted-root/external-host/distinct-data-root 的 join gap，专项 `16 passed`。

父代理新单元专项合计 `42 passed`；F8 `--verify`、A8 `validate`、T1 重新生成检查、py_compile、JSON 校验和 git diff-check 均通过。F4 审计确认已有聚合合同，不读取生产 HDF5。五个方向都保持 fail-closed/zero-credit，没有启动 Popen、solver、worker、GPU 或 queue，也没有停止/重启既有进程。scheduler 只读状态为 `queued=0、reserved=0、launching=0、running=0、attention=0、succeeded=294、failed=19、cancelled=13`；GPU0–7 各约 `48,497 MiB free`，utilization `0%`。

## Core gate

Core 仍为 `can_finalize=false`：T1 家族 `F3/F4`，macro T2 `0/2`，formal training `0/9`，observed T1/material case-runs `0/0`，目标缺口 `432/288`，independent reproduction=false，credit=0。F3 九路聚合完整只说明 admission/gap identity 覆盖完整，不是 formal terminal evidence；F8 的本地 kernel 观察不是 trusted target pin；A8 的 synthetic join 不是异机复现。下一步仍需要真实外部 authority、terminal receipts 和对应 gate 消费，不能由本地报告自授资格。
