# Core continuation status — UPDATE-393

日期：2026-09-29

本条是独立中央文档交付。写集严格限定为 `PLAN.md`、本条机器 JSON 和本中文报告；历史记录不改写。后续 subagent 策略固定为 GPT-5.6 Luna、reasoning max，并继续允许不重叠任务并行推进。

## 本轮完成的四个方向

- **F3 current-manifest MLP hidden16 terminal intake：成功，但只作诊断证据。** 三个 seed（17、29、43）均完成 500/500 updates，并在 `F3_DEV_00_a0p903125` / `test` 上自然完成 835 transitions、836 frames。terminal report 为 `terminal_diagnostic_verified`，`source_bound=true`，三路均 `terminal_verified`，但永久保持 `diagnostic_only=true`、formal/T1/T2/qualification=false、`credit=0`，不进入 formal matrix、registry、ledger、denominator 或 gate。intake 只消费 bounded projection JSON 与小文件元数据，没有打开 checkpoint、evaluation、trajectory 或 HDF5 内容。

- **F3 material coarse admission：仍 blocked。** 2026-09-29 rerun 状态为 `blocked_missing_fresh_root_scheduler_receipts`；`fresh-root-receipt.json` 和 `scheduler-host-io-reservation.json` 都不存在，因此 `launch_admitted=false`、`worker_launch_authorized=false`、`credit=0`。本轮没有打开或重哈希生产 HDF5，没有启动 worker、solver、GPU 或 queue。

- **A8 typed reproduction preflight：结构预检通过，不等于独立复现。** typed reader → autonomous prediction → scoring 链、两个 data root 与 host projection 的结构绑定通过，报告为 `status=pass`、`structural_preflight_passed=true`；但 `independent_reproduction=false`、`full_product_reproduction=false`、formal admission=false、`credit=0`。仍缺 trusted root review、external host attestation，以及另一台物理机和 relocated root 上的 non-diagnostic full-product reproduction evidence。

- **F8/R008 syscall static closure：462 行静态策略闭合，但运行时 pin 缺失。** 462/462 行均覆盖，逐行有 `deny_errno` 和精确 `audit_arch/raw_nr` predicate，并覆盖 ptrace/seccomp、x32、`nr=-1`、错误 audit arch 与负 raw nr 条件。target kernel/source/build/runtime identity 和 native runtime conformance 仍缺，故 `readiness_pass=false`、`T1_numerical=false`、`qualification_credit=0`；没有启动 privileged probe、native、solver、worker、GPU 或 queue。

## 本轮提交与联合测试

按方向记录本轮独立提交：

- MLP terminal chain：`9e343cc1`、`9a16efca`、`60d564b3`、`04e78308`、`ad563e68`、`b4179983`、`d777fab5`、`4d99cbe8`、`c118ee14`。
- F3 material coarse：`41b542e5`、`b4fdde19`。
- F8/R008 static closure：`0b08af84`、`8394689b`、`e9714c77`、`db26e878`。
- A8 typed reproduction preflight：`733e1205`、`5747de25`、`baa26007`。

使用仓库 `.venv` 的总控专项复核结果：

- MLP terminal evidence + training evidence + rollout launcher：`39 passed`；
- F3 material coarse intake：`12 passed`；
- A8 typed reproduction preflight：`6 passed`；
- F8/R008 syscall static closure：`9 passed`；
- 合计：`66 passed`。

这些测试只验证 bounded evidence/contracts 和 synthetic/diagnostic 边界，不把诊断结果提升为正式训练、T1/T2 或 qualification credit。

## Core completion gates（保持不变）

`can_finalize=false`；T1 family 为 `2/3`；macro T2 为 `0/2`；formal training 为 `0/9`；`missing_t1_case_runs=288`；`missing_material_case_runs=288`；`independent_reproduction=false`；formal、T1、T2 均未闭合；credit 为 `0`。

本条没有修改脚本、测试、registry、ledger、denominator、gate、completion 或其他报告；没有重启 live job；没有改写历史模型、receipt 或 continuation 记录。机器回执：`CORE-CONTINUATION-STATUS-2026-09-29-UPDATE-393.json`。
