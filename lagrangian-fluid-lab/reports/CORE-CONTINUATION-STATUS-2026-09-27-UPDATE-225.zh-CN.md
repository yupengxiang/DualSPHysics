# UPDATE-225：F8 R008 syscall selector 域静态分区

日期：2026-09-27（Asia/Shanghai）

## 结果

新增 `f8_r008_syscall_selector_domain_v1.py`，将 seccomp selector 的 `raw_nr`（signed int32）完整分成五个连续、无重叠区间，并单独处理 `audit_arch`（unsigned int32）：

- 非 `AUDIT_ARCH_X86_64` 架构拒绝；仅目标架构进入 syscall-number 分类。
- `raw_nr=-1` 独立标为“仅凭 selector 无法归因为 tracer skip 或用户请求”，在无独立可信 tracer 状态时拒绝；其他负数拒绝。
- 原生 source-table 区间 `0..461` 共 462 个号码，在逐号 policy review 完成前全部拒绝；v6.8 表中 holes 和 entryless rows 也没有被误当作已许可号码。
- 非 x32 的未列号码拒绝；带 `0x40000000` x32 tag 的整个 signed-int32 正域拒绝。x32 表 dispatch 受 `CONFIG_X86_X32_ABI` 条件约束，但本地运行时拒绝行为未验证。

固定 JSON 清单 SHA-256：`6e256aac2bf3c510c66bfc6ccf0b733b6f64c0804f3e2ffcce1ae9fb15332b44`。清单绑定 UPDATE-221 的 Linux v6.8 source-table baseline 与 native-row digest；它是 selector 域静态分区，不是可执行 seccomp policy。

## 复核与边界

Terra High 配置只读 follow-up 复核未发现 P0–P3；复核确认区间覆盖、x32 与 `-1` 拒绝语义、清单绑定和未授权状态断言。Reviewer 身份未 attested。

专项测试 **6 passed**；脚本/测试 `py_compile`、artifact `--verify` 和 `git diff --check` 通过。逐 syscall disposition/predicate、目标 kernel build/config、ptrace/seccomp 顺序 conformance、runtime trace、trusted supervisor 和运行时策略仍未完成。没有执行 workload、privileged probe、solver、worker、GPU 或 queue；execution authority、readiness 均 false，qualification credit 为 0。
