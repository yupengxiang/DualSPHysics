# Core continuation status — UPDATE-415

本轮继续按并行、由粗到细和独立提交推进；所有新 subagent 固定为 `gpt-5.6-luna`、reasoning `max`，历史记录没有改写。

## 两个正式入口边界

- `a708ad5a`：formal training release/root admission。dataset manifest→matrix 和 source-closure→matrix 可以绑定，但 trusted-root role、terminal-evidence role、formal dataset release、root authentication、source-closure root gate 及 9-run terminal matrix 仍缺；专项 `6 passed`、相关 `35 passed`，`launch_allowed=false`、`formal_eligible=false`、credit=0。
- `175af561`：T1 observed model case-run evidence binding gap inventory。固定 432 行投影，其中 F3 `288`、F4 `144`；当前 observed `0`，缺少 `family/scope/case/seed → model identity → source-reader → terminal receipt → artifact digests` 的完整绑定。专项 `4 passed`，T1/credit 仍为 false/0。

父代理两个新测试文件共 `10 passed`，py_compile、JSON 校验、git diff-check 通过。没有训练、solver/worker/queue/GPU execution、生产 HDF5/checkpoint/trajectory 读取、registry/ledger/denominator/gate/completion 修改，也没有停止或重启已有进程。GPU0–7 各约 `48,497 MiB free`，utilization `0%`。

## Core gate

Core 仍为 `can_finalize=false`：T1 家族 `F3/F4`，macro T2 `0/2`，formal training `0/9`，observed T1/material case-runs `0/0`，目标缺口 `432/288`，independent reproduction=false，credit=0。下一步只能接入真实 release/root-trust/terminal/source-reader/artifact 证据，不能把固定投影行数或准备态数据当成 observed case-runs。
