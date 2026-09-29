# Core continuation status — UPDATE-413

本轮按并行、由粗到细和独立提交推进；所有新 subagent 固定为 `gpt-5.6-luna`、reasoning `max`，历史模型和 receipt 没有改写。

## 已完成的独立闭环

- `f18f8907` / `21404f9c`：尝试 F3 `graph_raw/hidden16/seed17` diagnostic rollout，现有 admission receipt 缺少 `authority` 对象，在 Popen 前 fail-closed；没有启动真实 workload，专项 runner/terminal 回归 `61 passed`。
- `dc11f0fc`：F4 Tallwall120 DEV_07 CPU diagnostic intake。历史输入为 218 frames、unknown `1.0`、coverage `0.0`；fresh-root、scheduler host-I/O、terminal、sidecar、32-case matrix 和 source/reader drift 均未闭合，专项 `24 passed`。
- `e8dd34cd`：F2 static/full-cup、dynamic DBC/open-top、pour/catch 三类边界 contract；cell-00 hard failure、14 个 runtime 缺失及 dynamic/catch blocker 均保持 fail-closed，新测试 `8 passed`、相关回归 `21 passed`。
- `671b972b`：F1 prepared→runtime admission boundary，15 个 prepared rows 均绑定但 runtime admitted `0`，专项 `43 passed`。
- `800ca22a`：F8/R008 solver-output→Core input gate，逐案例绑定 case/attempt/nonce/artifact/frame/time-axis/digest；专项 `11 passed`、相邻回归 `27 passed`。

父代理对四个新测试文件复核为 `37 passed`，脚本 `py_compile`、JSON 校验和 `git diff --check` 通过。上述结果都保持 diagnostic-only、formal/T1/T2 false、credit=0；没有训练、solver/worker/queue/GPU execution、生产大文件读取、registry/ledger/denominator/gate/completion 修改，也没有停止或重启既有进程。GPU0–7 各约 `48,497 MiB free`，utilization `0%`。

## Core gate

Core 仍为 `can_finalize=false`：T1 家族 `F3/F4`，macro T2 `0/2`，formal training `0/9`，observed T1/material case-runs `0/0`，目标缺口 `432/288`，independent reproduction=false，credit=0。下一步只能在真实 external authority、fresh-root/host-I/O、terminal、B/C/D、trusted runtime 和 release/root-trust 证据闭合后，沿现有受控入口继续；不绕过 fail-closed 边界。
