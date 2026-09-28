# F8/R008 syscall policy 静态闭合 V1

状态：`static_default_deny_policy_closed_target_pin_missing`

本单元只消费已存在的小型 JSON/静态审计产物，不启动 native solver、GPU、queue 或任何 selector；不修改 gate、registry、ledger、denominator、completion 或 PLAN。

## 已闭合的静态部分

- Linux v6.8 x86-64 native syscall number 区间固定为 `0..461`，共 **462** 行。
- 462 行全部具有显式 `disposition=deny_errno`。
- 每一行的 predicate 都精确绑定 `audit_arch == 0xc000003e && raw_nr == N`，并绑定 upstream number baseline、selector-domain manifest 和 F8 静态 profile reference。
- default-deny 策略不生成 native allowlist；这一步只闭合覆盖性与拒绝边界，不声称任何 syscall 可安全执行。

## selector 边界

- 非目标 `audit_arch`：deny。
- `raw_nr`：按 signed int32 全域划分；负数非 sentinel：deny。
- `nr=-1`：在没有独立可信 tracer state 时，作为 target request deny；selector 单独不能把它归因给 tracer。
- x32 tag `0x40000000`：deny；静态 config 要求 `CONFIG_X86_X32_ABI=n`，x32 table `512..547` 共 36 项保持排除。
- ptrace/seccomp profile：使用 ptrace syscall-entry-stop 决策边；禁止 seccomp user notification/`CONTINUE`，已有 seccomp filter 时拒绝该 profile，不允许安装或替换 seccomp filter；entry 到 exit 或 broker synthetic return 必须成对。以上是静态条件，尚未做目标 kernel runtime order conformance。

## target-kernel/source/build pin 边界

当前 external target-kernel intake 仍 blocked。报告分别保留了 target pin slot 和本机 candidate：

- 本机 observed release：`6.8.0-138-generic`，仅 local candidate，不是 external target pin。
- 本机匹配 config SHA-256：`0ffca159bcee00c87b27e093889b710fe680ccfa37149e4e1ef8d5053e1e644c`，仅 local candidate。
- 本机 UAPI 只有 bounded sample inventory，不能代替完整 UAPI tree hash。
- target `source_commit`、完整 `source_tree_sha256`、完整 `uapi_sha256`、target `build_id` 目前没有可认证 external artifact，因此保持 null/未闭合。
- 已知但仅属 upstream reference 的 hash 仍单独列出：syscall table `4c30abea9a4b69f3409bea7a0c910a8c8feb9a44b22a448b5c82f2bfdd8249c8`，native rows `b1f28269d2ea1c72f6a0899b77c801f665360309309b7d8a819768d1841e85d7`；它们不被提升为 target kernel hash。

## 授权边界与后续动态缺口

本报告 `per_number_dispositions_complete=true`、`per_number_predicates_complete=true`，但 `target_kernel_pin_complete=false`、runtime conformance=false、`readiness_pass=false`、`T1_numerical=false`、`qualification_credit=0`。后续仍需真实 external source/UAPI/config/build evidence，以及目标 kernel 上 x32 rejection、`nr=-1` 语义和 ptrace/seccomp 顺序的动态验证；在这些证据到位前不得接入 solver gate 或产生 T1 credit。
