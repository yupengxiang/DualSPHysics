# Core continuation status — UPDATE-410

日期：2026-09-29

本轮继续按“并行、由粗到细、每个可提交单元及时提交”推进；所有新 subagent 均固定为 `gpt-5.6-luna`、`max`，历史记录没有被改写。

## 三条并行审计结果

- `09391672`：修复 s4 spec 测试中一个与真实 scheduler 生命周期冲突的断言。s4 attempt 已经正确创建 scheduler-owned namespace，测试不应在执行后要求该目录不存在；F3 coarse 定向集合复核为 `48 passed`。
- `0c8d0901`：完成 setup variant diagnosis。现有 H2 `k48` 仍有 `4.6875%` unknown，H1 更差为 `6.640625%`；s2/s4 的共同问题指向 support/reconstruction/visibility reliability predicate，当前没有安全的新 scheduler variant，不能盲目扩展到 `8→32`。
- `deb55991`：完成 external-admission security audit。确认 root/scheduler fresh receipt、host-I/O authorization 和 one-shot namespace 仍缺失；篡改 terminal intake 的 promotion 字段会被拒绝，没有发现从 diagnostic receipt 晋级 formal 的绕过。代理回归 `51 passed`，父代理相邻集合 `19 passed`。
- `a7559f1b`：完成 `graph_raw-seed17` formal-training readiness audit。当前 scheduler matching records 均为 diagnostic/preprofile，formal spec 数量 `0`、formal terminal evidence 不存在、registry training runs 仍为 `0`，报告记录 `14` 项精确 blocker；readiness 专项 `5 passed`，代理宽回归 `69 passed`。

## 正式状态与安全边界

`core_campaign.py status` 仍为 `can_finalize=false`：T1 family 只有 `F3/F4`，macro T2 为 `0/2`，formal training 为 `0/9`；observed T1/material case-runs 为 `0/0`，固定需求为 `288/288`，目标缺 `432/288`，independent reproduction 为 `false`，credit 为 `0`。

本轮没有创建 formal training spec，没有训练、GPU/queue/worker submit，没有新 scheduler workload；没有修改 registry、ledger、denominator、gate、completion，也没有停止或重启已有进程。核验时 GPU0–7 每张约 `48,497 MiB free`、利用率 `0%`；显存充足不替代 formal root trust anchor、source closure、host-I/O receipt 或 terminal evidence。

## 下一步

F3 material 先保留 s2/s4 与 H1/H2 的 negative diagnostics，解决共同 reliability predicate，并补齐 fresh one-shot root 与 scheduler-owned host-I/O receipts；未满足前不再提交未经验证的 variant，也不扩展到 `8→32`。正式训练先补齐 formal dataset release、当前 source bindings、root trust anchor、formal scheduler spec 和 terminal contract，再考虑 `graph_raw-seed17` 的最小正式执行单元。

详见 [UPDATE-410 JSON](CORE-CONTINUATION-STATUS-2026-09-29-UPDATE-410.json)、[F3 setup diagnosis](F3-MATERIAL-COARSE-SETUP-VARIANT-DIAGNOSIS-2026-09-29.json)、[admission security audit](F3-MATERIAL-COARSE-RERUN1-EXTERNAL-ADMISSION-BOUNDARY-SECURITY-AUDIT-2026-09-29.json)、[training readiness](F3-GRAPH-RAW-SEED17-FORMAL-TRAINING-READINESS-2026-09-29.json) 与 [PLAN.md](../../../PLAN.md)。
