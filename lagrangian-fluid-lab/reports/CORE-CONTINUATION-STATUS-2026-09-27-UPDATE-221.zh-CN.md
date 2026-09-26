# UPDATE-221：F8 R008 x86-64 syscall universe 上游基线

日期：2026-09-27（Asia/Shanghai）

## 本轮完成

针对 V17 §5 的完整 syscall-number universe 缺口，新增 v1 parser 与一个只引用上游源的 baseline。它固定 Linus Torvalds Linux v6.8 `arch/x86/entry/syscalls/syscall_64.tbl` 的 SHA-256 为 `4c30abea9a4b69f3409bea7a0c910a8c8feb9a44b22a448b5c82f2bfdd8249c8`，通过[官方 v6.8 syscall table](https://github.com/torvalds/linux/blob/v6.8/arch/x86/entry/syscalls/syscall_64.tbl)确认 `common`/`64`/`x32` 格式及 native/x32 分界。固定原生号码区间 `0..461`，逐号列出 462 行，其中 89 个未分配 hole、357 个有 entry point 的表项、16 个表内无 entry point 的保留行；x32 `512..547` 共 36 项单独记为排除，不混入原生号域。

产物为 [syscall universe baseline v1](F8-R008-SYSCALL-UNIVERSE-LINUX-V6.8-X86_64-BASELINE-V1.json)，生成器为 [f8_r008_syscall_universe_baseline_v1.py](../scripts/f8_r008_syscall_universe_baseline_v1.py)。它只提供源码映射，不是目标 kernel pin 或执行策略：所有 462 行的 `disposition`、`predicate` 均为 null；`per_number_dispositions_complete=false`、`per_number_predicates_complete=false`、`target_kernel_build_pinned=false`、runtime conformance/readiness=false、credit=0。x32 runtime rejection 也未验证。下一步仍须确定目标 kernel build，再为每个号码实现并审查精确 predicate/disposition；不得把本 baseline 接入 solver gate。

## 验证与边界

命令 `lagrangian-fluid-lab/.venv/bin/python -m pytest -q lagrangian-fluid-lab/tests/test_f8_r008_syscall_universe_baseline_v1.py`：**9 passed**；固定产物 verifier 报告 universe=462、holes=89、所有 462 行未分类；`py_compile` 与 `git diff --check` 通过。除 builder 对原始上游 bytes 校验 pin SHA 外，又以独立的一次性解析实现复算 canonical rows SHA `b1f28269d2ea1c72f6a0899b77c801f665360309309b7d8a819768d1841e85d7`；此摘要现由 builder/verifier 双侧固定，负测确认改名后即使重算 artifact 内摘要仍会拒绝。GPT-6 Luna Max 配置只读复核确认该 P2 已关闭且未发现新增 P0–P2；reviewer 提醒的非标准 `NaN/Infinity` 严格性也已通过拒绝常量的 decoder 和负测加固。reviewer identity 未 attested。

本轮只下载/解析固定的公开 syscall table 并读取/写入仓库静态文件；没有执行任何被列出的 syscall、host capability/filesystem probe、fanotify、root/sudo、生产数据/HDF5/PART/BI4 读取或 GenCase/native/solver/worker/GPU/queue。scope、registry、ledger、分母与资格信用不变。
