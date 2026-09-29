# raw graph_hidden16 seed43 bounded admission security audit

状态：`closed_minimal_fail_closed`。

本次按 seed43 自己的真实调用与数据流审计 admission 和 runner。raw seed17 已关闭的 SA-003 只作为行为级对照，没有复制字符串，也没有把测试 fixture 冒充生产 scheduler authority。

确认并最小修复了 seed43 的 SA-003 缺口：

- `RolloutPlan` snapshot/digest 现在进入 seed43 的 plan binding 和 identity。
- admission 在 external authority 校验及 namespace 状态写入前，稳定重读 manifest、training receipt、checkpoint，并调用 launcher reconciliation；漂移会 fail closed。
- receipt 校验会再次校验 snapshot、digest、descriptor、seed/run_id/root/namespace/nonce/command/environment 绑定；runner 的 `build_plan` 先经过这条 receipt 校验再使用 plan。

descriptor/terminal 结论：seed43 runner 原有的稳定 descriptor 与 terminal artifact 边界已保持 fail closed；当前内部 execution capability 不存在，runner 不会凭 report 字段推断 terminal success，也不会铸造独立 production terminal proof，因此不需要修改 seed43 runner 生产脚本。

seed43 admission+runner 测试共 `35 passed`；raw seed17/seed29/seed43 admission+runner 相关回归共 `101 passed`。直接 CLI admission 返回 `blocked_fail_closed`（exit 2，缺少 scheduler-owned GPU snapshot），直接 CLI runner 返回 `blocked_fail_closed`（exit 2，未提供 admission receipt）。

本次没有启动 GPU、`Popen`、`wait` 或 solver，没有写 Core registry/ledger/denominator/gates/completion/PLAN，也没有伪造生产 authority。测试中的签名 scheduler authority 仅是测试 fixture，不能作为生产证据；生产 trust anchor、one-shot consume witness、live GPU/child terminal proof 仍未提供，因此 launch 保持 `false`、formal credit 保持 `0`。

本次写集仅限 seed43 admission、seed43 专属测试和本报告；未修改 seed17、seed29、residual、launcher/Core registry/ledger/denominator/gates/completion。
