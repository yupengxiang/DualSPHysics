# Core continuation status — UPDATE-394

日期：2026-09-29

本条是独立中央文档交付。写集严格限定为 `PLAN.md`、本条机器 JSON 和本中文报告；不修改代码、测试、registry、ledger、denominator、gate、completion 或其他报告。后续 subagent 策略固定为 GPT-5.6 Luna、reasoning max，并继续允许不重叠任务并行推进。

## 本轮推进结果

- **F3 current-manifest MLP hidden16 dry-run matrix：96/96 计划完成，但没有启动实际 batch。** 32 个 case × seeds `17/29/43` 共 96 个计划，namespace、nonce、command identity 均 `96/96` 唯一；`launch_allowed=false`，真实 terminal receipts 为 `0/96`。本轮未直接裸启 batch executor，计划矩阵不计 formal training、T1/T2 或 qualification credit。

- **F4 Tallwall120 bounded intake：仍 fail-closed。** 32 个 case 已绑定，material sidecar 为 `0/32`，状态为 `blocked_fail_closed`；`T2=false`、formal=false、qualification=false、`credit=0`，没有因此授权 solver/worker/GPU/queue。

- **F3 material coarse：仍缺 fresh root/scheduler receipts。** `fresh-root-receipt.json` 与 `scheduler-host-io-reservation.json` 仍缺失，故 `launch_admitted=false`、`worker_launch_authorized=false`、`credit=0`。

- **A8 typed reproduction：结构预检通过，不等于独立复现。** structural preflight 为 pass，但 `independent_reproduction=false`、formal admission=false、`credit=0`；仍缺 trusted root review、external host attestation，以及另一台物理机和 relocated root 上的 non-diagnostic full-product evidence。

- **F8/R008 syscall static closure：静态行已闭合，运行时 pin 仍缺失。** 462/462 行已覆盖，逐行保留 `deny_errno` 与精确 `audit_arch/raw_nr` predicate；target kernel/source/build/runtime pin 与 native runtime conformance 仍缺，因此 `T1_numerical=false`、`qualification_credit=0`。

## 提交与验证

本轮相关提交：

- current-manifest matrix：`1c94fdb2`、`cba30767`、`23eeb28e`；
- F4 Tallwall120 bounded intake：`bd5deb24`、`c834fe98`、`da789451`、`a794b069`；
- 前一轮中央文档：`66e212b0`；
- 前序 F3 terminal chain：`9e343cc1`、`9a16efca`、`60d564b3`、`04e78308`、`ad563e68`、`b4179983`、`d777fab5`、`4d99cbe8`、`c118ee14`；前序 F3 material coarse：`41b542e5`、`b4fdde19`；
- 前序 A8：`733e1205`、`5747de25`、`baa26007`；前序 F8：`0b08af84`、`8394689b`、`e9714c77`、`db26e878`。

验证结果：新 matrix `7 passed`，F4 new `8 passed`，existing union `66 passed`；`py_compile`、JSON 校验和 `git diff --check` 均通过。这里保留各验证集合的原始计数，不把它们强行合并为 formal 结果。

## GPU 与执行边界

GPU 显存充足本身不是 blocker；已有 GPU 进程占用也不自动排除新任务。但未来实际执行必须经过受审计 executor，并同时满足 VRAM、CPU、scheduler-owned host-I/O reservation 和 fresh unique namespace admission。禁止直接裸启 batch executor；不停止或重启既有任务。本轮没有启动 workload、没有打开大体积 production artifact，也没有把 diagnostic 结果提升为正式证据。

## Core completion gates（保持不变）

`can_finalize=false`；T1 family 为 `2/3`；macro T2 为 `0/2`；formal training 为 `0/9`；`missing_t1_case_runs=288`；`missing_material_case_runs=288`；material case runs 为 `0/288`；`independent_reproduction=false`；formal、T1、T2 均未闭合；credit 为 `0`。

本条仅新增 PLAN 末尾、UPDATE-394 机器 JSON 和本中文报告；历史记录不改写，代码、测试、registry、ledger、denominator、gate、completion 与其他报告均未修改。机器回执：`CORE-CONTINUATION-STATUS-2026-09-29-UPDATE-394.json`。
