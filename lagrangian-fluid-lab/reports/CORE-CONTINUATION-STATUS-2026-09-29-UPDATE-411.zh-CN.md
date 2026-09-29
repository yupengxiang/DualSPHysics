# Core continuation status — UPDATE-411

日期：2026-09-29

本轮继续按并行、由粗到细和独立提交推进；所有新 subagent 均固定为 `gpt-5.6-luna`、`max`，历史审计报告没有被改写。

## A8 package bridge 安全闭环

- `2182cb6d` 的 bounded audit 发现两个真实 projection 缺口：reader receipt 只看 `passed=true`，可能携带伪造的 formal/non-diagnostic/positive-credit authority 字段；diagnostic second-host pair 只信自报的 distinct flag，接受重复 host identity。该审计本身不授予任何资格或 credit。
- `08f4bd36` 完成最小 hardened fix：reader projection 对出现的 authority 字段做严格类型和值校验，并始终输出 diagnostic-only/zero-credit；second-host projection 强制两个非空且互不重复的 host identity。合法旧 diagnostic fixture 保持兼容，历史 pre-fix 审计 JSON 保持为不可变快照。
- A8 相关父代理回归为 `55 passed`，py_compile、JSON validator、diff-check 通过。修复没有打开大 HDF5/NPZ/checkpoint，没有启动 solver/worker/GPU/queue，也没有修改 registry、ledger、denominator、gate 或 completion。

当前 `reader_bundle.v2` 仍是 32 cases、checkpoint 数为 `0` 的 reader-only 包，因此 independent reproduction 仍为 `false`、credit 为 `0`；hardened bridge 只是关闭 projection 绕过，不等于取得 trusted root、external host 或正式模型复现证据。

## Core 正式状态

`core_campaign.py status` 仍为 `can_finalize=false`：T1 family 只有 `F3/F4`，macro T2 为 `0/2`，formal training 为 `0/9`；observed T1/material case-runs 为 `0/0`，固定需求为 `288/288`，目标缺 `432/288`，independent reproduction 为 `false`，credit 为 `0`。

本轮没有启动 production/formal workload，没有使用 GPU 执行 production/formal training，没有停止或重启已有进程。核验时 GPU0–7 每张约 `48,497 MiB free`、利用率 `0%`；显存可用不替代 trusted root、external host、formal release、terminal evidence 或固定分母。

## 下一步

A8 后续只能在获得真实 trusted-root/external-host attestation、distinct data root 和 non-diagnostic full-product receipt 后推进 independent reproduction；F3/F4 material 继续等待其 external receipts 与可靠性门槛；正式九次训练、T1/material 分母和 F8 target pins 仍需分别闭合。

详见 [UPDATE-411 JSON](CORE-CONTINUATION-STATUS-2026-09-29-UPDATE-411.json)、[A8 boundary audit](A8-PACKAGE-REPRODUCTION-READINESS-BOUNDARY-AUDIT-V1-2026-09-29.json)、[A8 bridge](../scripts/core_product_repro_bridge_v1.py) 与 [PLAN.md](../../../PLAN.md)。
