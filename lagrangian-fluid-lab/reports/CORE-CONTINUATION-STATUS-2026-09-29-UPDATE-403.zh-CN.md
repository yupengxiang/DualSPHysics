# Core continuation status — UPDATE-403

日期：2026-09-29

本轮按“先一条代表案例走通，再扩展”的原则推进 graph_raw seed17 diagnostic path。完成了命令审计、v1 dry-run、receipt-bound admission 与 v2 runner；独立安全审计随后发现 8 个 P1，因此 v2 最终保持 blocked，未启动真实 workload。

## 交付与审计结论

- `51fe8fb6`：seed17 command audit，绑定 current manifest、core_learning SHA、835/836、GPU 映射和 fresh output namespace；专项 `7 passed`。
- `ebbde91b`：seed17 diagnostic runner v1；GPU2 resource admission 通过，但 launch=false、Popen/wait=`0/0`；专项 `10 passed`。
- `3ecc999a`：diagnostic admission v2 security audit，发现 8 个 P1：receipt replay、全路径 TOCTOU/HDF5 link、GPU UUID/PCI 映射、sealed Popen、环境/可执行文件 identity、formal/credit 隔离等；专项 `17 passed`。
- `e43f445e`、`3a67dcf7`、`7503f172`、`ea373032`：receipt-bound admission 与 runner v2 的最小收口。结构化 admission receipt 的一致性为 true，但安全审计 gate 使 `diagnostic_execute_allowed=false`；runner 仍 `launch_allowed=false`、Popen/wait=`0/0`，专项合计 `11 passed`。

## 边界

GPU2 的 resource admission 通过并不等于 execution authority。当前没有真实 evaluator/Popen/GPU workload，未停止或重启任何已有任务，未读取生产 trajectory/evaluation，未修改 registry、ledger、denominator、gate 或 completion。绝对路径下 admission、runner、security-audit 报告 CLI verify 均通过；相对路径 verify 被预期的 lexical-path fail-closed 拒绝。

本轮新增受影响测试 `106 passed`；前一轮安全全套回归 `388 passed`。代码仍保持 zero-credit，不能把 receipt structural admission、GPU free VRAM、PID/progress 或命令审计当成终端完成证据。

## Core 门禁

Core 仍为 `can_finalize=false`：T1 families=`F3/F4`（2/3），macro T2=`0/2`，formal training=`0/9`；missing training runs 为 9 个，T1 case-run 缺 `288`（目标 `432`），material case-run 缺 `288`（目标 `288`），independent reproduction=false，credit=`0`。

下一步必须先关闭 8 个 P1（尤其 replay consumption、GPU UUID/PCI identity 和 sealed Popen/artifact proof），再重新进行独立审计；在审计通过前不执行 seed17，更不扩展到 96-case batch。
