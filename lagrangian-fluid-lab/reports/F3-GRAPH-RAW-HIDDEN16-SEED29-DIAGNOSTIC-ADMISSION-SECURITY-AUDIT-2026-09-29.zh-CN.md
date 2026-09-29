# raw graph_hidden16 seed29 bounded admission security audit

状态：`closed_minimal_fail_closed`。

本次按 seed29 自己的真实调用/数据流审计了 admission 与 runner。raw seed17 已关闭的 SA-003 只作为行为级对照，没有复制字符串，也没有把本地 fixture 冒充生产 scheduler authority。

确认并最小修复了三处边界：

- admission 将 launcher 的 `RolloutPlan` snapshot/digest 写入 seed29 identity，并在 authority 校验及 namespace 状态写入前稳定重读 manifest、training receipt、checkpoint；receipt identity 再校验 snapshot 对 namespace、nonce、command、文件 descriptor/digest 的跨绑定。
- 当前 runner 没有 descriptor-bound child publication capability；pathname-only child output 在 `Popen` 前 fail closed，因此没有伪造 descriptor authority。
- 当前 runner 不产生独立 terminal receipt；`diagnostic_terminal_verified` 现在直接 fail closed，不能仅凭 report 字段升级为 terminal success。

专项测试新增 snapshot/training digest 漂移、snapshot namespace/command 跨绑定和伪造 terminal success 拒绝覆盖。seed29 admission+runner 共 `34 passed`；相关 raw hidden16 回归共 `144 passed`；两个 seed29 脚本 `py_compile` 通过。

本次未启动 GPU、`Popen`、`wait` 或 solver，未写 Core registry/ledger/denominator/gates/completion。生产 scheduler trust anchor、真实 one-shot consume witness、live GPU/child terminal proof 仍不存在，因此 launch 保持 `false`、formal credit 保持 `0`。工作树中其他 seed43/residual 改动未纳入本次 commit。
