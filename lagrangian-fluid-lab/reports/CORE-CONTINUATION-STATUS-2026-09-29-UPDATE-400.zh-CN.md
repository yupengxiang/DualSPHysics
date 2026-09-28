# Core continuation status — UPDATE-400

日期：2026-09-29

本轮继续按模块并行推进 terminal evidence 与外部可信边界，完成 F3 graph_raw validator、F3 graph_residual terminal identity、F4 fresh-root/scheduler receipt contract、A8 trusted-root/external-host attestation contract 四个可提交单元。所有 subagent 均使用当前策略 `gpt-5.6-luna`、reasoning `max`；历史记录未改写。

## 独立提交

- `06d85f50`：F3 graph_raw current-manifest hidden16 terminal artifact validator。只允许带 marker 的临时 synthetic HDF5，禁止读取生产 trajectory/checkpoint/evaluation；缺少真实 producer/terminal proof 时保持 `blocked_fail_closed`、`launch_allowed=false`、credit `0`。专项 `15 passed`。
- `bfa1f841`：F3 graph_residual current-manifest hidden16 terminal artifact identity canary。绑定三 seed、835 transitions/836 frames、fresh nonce、精确 command、Popen/wait proof 与独立 HDF5 validator；terminal proof `0/3`，credit `0`。专项 `48 passed`。
- `ccde6234`：F4 fresh-root/scheduler receipt bounded contract。覆盖一次性 nonce、owner/inode/path、argv/hash、capability 与 pair commitment；没有伪造 fresh receipt，状态仍 `blocked_missing_fresh_root_scheduler_receipts`。专项 `8 passed`，相关 F4 回归 `24 passed`。
- `016a660f`：A8 trusted-root/external-host attestation contract。绑定 trusted root、external host、distinct data-root 与 non-diagnostic full-product receipt 的 synthetic identity consistency；不代表真实 attestation。专项 `15 passed`，readiness/independent reproduction/credit=`false/false/0`。

## 验证结果

本轮跨模块定向回归为 `223 passed`；新报告 CLI verify、`py_compile`、`git diff --check` 全部通过。未读取生产数据，未启动 solver/worker/native/GPU/queue，未写 registry、ledger、denominator、gate 或 completion。

Raw validator 仍是 capability contract，不是 production terminal receipt；residual 只达到 source-bound，terminal proof 仍为 `0/3`。F4 仍缺 fresh root 与 scheduler-owned host-I/O reservation；A8 仍缺可信 root review、外部主机 attestation 和另一台物理机的 non-diagnostic full-product receipt。故本轮没有将任意 synthetic、PID、progress、resource admission 或 GPU 显存观察升级为资格信用。

## Core 门禁

Core 仍为 `can_finalize=false`：T1 families=`F3/F4`（2/3），macro T2=`0/2`，formal training=`0/9`；missing training runs 为 9 个，T1 case-run 缺 `288`（目标 `432`），material case-run 缺 `288`（目标 `288`），independent reproduction=false，credit=`0`。

下一步是将 raw/residual terminal artifact contract 与真实、独立产生的 evaluator/process/validator receipts 接起来；在真实 producer、fresh namespace、terminal HDF5 identity、F4 root/scheduler receipt 或 A8 外部 attestation 未闭合前，继续 fail-closed，不启动裸 batch executor。
