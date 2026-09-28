# Core continuation status — UPDATE-401

日期：2026-09-29

本轮将 F3 graph 方向从“artifact validator contract”推进到“terminal execution bridge contract”。raw 与 residual 分别完成独立 bridge，实现 fresh identity、resource re-admission、真实 Popen/wait 证据边界和独立 validator 证据的接口；当前 capability 仍未授予，因此默认 dry-run，显式 `--execute` 也在 Popen 前拒绝。

## 独立提交

- `8d3c0f65`：graph_raw current-manifest hidden16 terminal execution bridge；专项 `10 passed`，相关回归 `41 passed`。
- `65e016ef`：graph_residual current-manifest hidden16 terminal execution bridge；专项 `17 passed`，相关 residual 回归 `63 passed`。

两者均严格绑定 fresh namespace/nonce、manifest、training/checkpoint、exact command、835 transitions/836 frames、process lifecycle 与 terminal artifact identity；不接受 caller PID、return code、synthetic validator 或 fake Popen 作为真实 execution proof。

## 当前结果

- raw：`dry_run`、`blocked_fail_closed`、`launch_allowed=false`，Popen attempts/waits=`0/0`。
- residual：`source_bound=true`，terminal/validator proofs=`0/3`，`launch_allowed=false`、credit=`0`。
- 本轮没有启动真实 evaluator，也没有停止/重启任何既有 GPU job；没有写 registry、ledger、denominator、gate 或 completion。

跨模块定向回归为 `250 passed`；两个 bridge report CLI verify、`py_compile`、`git diff --check` 均通过。GPU 显存仍可作为后续 resource admission 的一个输入，但不会单独授予 execution authority。

## Core 门禁

Core 仍为 `can_finalize=false`：T1 families=`F3/F4`（2/3），macro T2=`0/2`，formal training=`0/9`；missing training runs 为 9 个，T1 case-run 缺 `288`（目标 `432`），material case-run 缺 `288`（目标 `288`），independent reproduction=false，credit=`0`。

下一步是对 bridge 的 real producer→validator→terminal receipt 连接做独立安全审计；只有真实 process exit、真实 artifact identity 和独立 HDF5 validation 同时闭合，才考虑在新 namespace 中运行一条 diagnostic canary。
