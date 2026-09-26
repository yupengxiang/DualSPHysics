# UPDATE-222：F8 syscall ABI selector 静态语义核对

日期：2026-09-27（Asia/Shanghai）

## 结论

UPDATE-221 的 baseline 精确枚举的是 Linux v6.8 `syscall_64.tbl` 中 native 表号区间 `0..461`，不是 seccomp/ptrace 可见的完整原始 `nr` 整数域，也不是已完成的执行策略。其 `x32_exclusion` 的 `512..547` 是 syscall table 的行号，不是 seccomp 收到的 raw `nr`；且 x32 ABI 同时复用标记为 `common` 的行。故不能仅用 `arch == AUDIT_ARCH_X86_64` 区分 native 与 x32，也不能把“排除表内 x32 专用的 36 行”称为完整 x32 runtime rejection。

## Linux v6.8 固定源码事实

下列源码来自同一官方 `v6.8` tag；SHA-256 由本机对相应 raw bytes 计算：

| 上游文件 | SHA-256 | 本次核对的语义 |
|---|---|---|
| [syscall_64.tbl](https://github.com/torvalds/linux/blob/v6.8/arch/x86/entry/syscalls/syscall_64.tbl) | `4c30abea9a4b69f3409bea7a0c910a8c8feb9a44b22a448b5c82f2bfdd8249c8` | ABI 标签 `common/64/x32`；native 号码区间为 0..461（含 holes）；512..547 是历史 x32 专用表号；548 以上可供 non-x32 使用 |
| [x86 UAPI unistd.h](https://github.com/torvalds/linux/blob/v6.8/arch/x86/include/uapi/asm/unistd.h) | `a5dbdb6f1396798ef9ec26ccc9e465ffc85680060ec19849f2f8c265f33908fe` | `__X32_SYSCALL_BIT = 0x40000000` |
| [x86 syscall Makefile](https://github.com/torvalds/linux/blob/v6.8/arch/x86/entry/syscalls/Makefile) | `ca94c9743b5797d3e2e608e793fde32afdb31b95d6986aada831ad3470c4e178` | native 表由 `common,64` 生成；x32 表由 `common,x32` 生成且 UAPI 号码加 `__X32_SYSCALL_BIT` |
| [x86 syscall dispatch](https://github.com/torvalds/linux/blob/v6.8/arch/x86/entry/common.c) | `fda2f14a291532e00c454eee8ab5f77ea1137e2604cd4289f051b53903207ca4` | dispatch 先查 native，再从 raw `nr` 扣除 x32 bit 查 x32；`nr=-1` 是特殊 skip 路径，其余无效号码走 `ni_syscall` |
| [x86 syscall ABI helpers](https://github.com/torvalds/linux/blob/v6.8/arch/x86/include/asm/syscall.h) | `63856759fa77662576866dc2f616516a55d62289bb0f75d8d44f76d038a9030f` | syscall nr 从 `orig_ax` 低 32 位读取；x32 tasks 的 audit arch 仍为 `AUDIT_ARCH_X86_64`，i386 compat 才是 `AUDIT_ARCH_I386` |
| [seccomp UAPI](https://github.com/torvalds/linux/blob/v6.8/include/uapi/linux/seccomp.h) | `38a129b0b1e0c5cbae3b01bb159810a5cc290d7823d4c386f71d70b16e93d8dd` | `seccomp_data.nr` 为 `int`，`arch` 为 `__u32` |

据此，x32 的 raw selector 形式为 `0x40000000 | table_nr`；例如表中 x32 专用 512..547 对应 raw `0x40000200..0x40000223`，而 x32 的 `common` 调用使用相同 high-bit 编码的 common 表号。x32 与 native 共用 `AUDIT_ARCH_X86_64`，必须检查号码 ABI 位；不能只检查 arch，也不能只拒绝 raw 数值 512..547。

## 后续策略合同要求（尚未实现/批准）

静态源码支持下列 fail-closed 设计约束，但不构成可执行策略、目标 kernel pin 或 runtime conformance：

1. 先精确要求 `arch == 0xc000003e`；其他 audit arch 拒绝。
2. 将 `nr == -1` 作为 tracer 的 skip-control/sentinel 另行处理，绝不当作可允许的 target syscall；其他负号 raw `nr` 拒绝。V17 所需 `orig_rax=-1` 无副作用性质仍需对目标 kernel 做 conformance。
3. 对非负 `nr` 拒绝 `nr & 0x40000000 != 0`，覆盖整个 x32 标记域，包括共用 `common` 表号的 x32 调用及专用 512..547 范围。
4. 仅对 pinned target kernel 中逐项完成 disposition/predicate 的 native table entries 作显式判断；hole、entryless row、超出固定表范围的所有号码均由默认 deny 覆盖，不依赖 `ENOSYS` 作为安全边界。

仍缺目标 kernel build/source/config 精确 pin、每个 native 号码的具体 disposition/predicate、filter/ptrace 修改顺序与 `orig_rax=-1` 目标内核 conformance、实际 workload syscall trace、trusted supervisor 及 runtime readiness。UPDATE-221 artifact 未改写；其“x32 512..547”字段仍仅表达 table-space inventory，runtime rejection 明确为 false。F8 solver/worker/GPU/queue/privileged probe 均未运行。

本轮重新观测到 1-min load `141.52 > 128`；F4 CPU/native canary preflight 未启动，授权未消费。没有改动 registry、ledger、scope、分母、资格状态或 credit。
