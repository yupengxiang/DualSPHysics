# Core 异机复现缺口审计（2026-09-28）

结论：`independent_reproduction` 仍不能通过，但已有部分证据可以复用。本轮只做只读合同核验，不启动 workload、不修改 registry/ledger/gate。

已有证据包括：真实 H200/Ada 双主机的 835-transition 配对收据（仍标记 `diagnostic_only=true`、`full_product_reproduction=false`）；一个 distinct data root 的 relocated receipt（但 same-host、`cross_host_claim=false`）；以及一个旧 wrapper。旧 wrapper 缺当前合同要求的五类 typed supporting evidence、source/reproduction data-root 绑定和 hash-bound root review，不能升格。

当前 gate 仍为 `can_finalize=false`、`independent_reproduction=false`、`issues=[]`。历史候选直接核验均未通过，相关合同测试 `56 passed`。本轮没有 F3 rollout、F4 denominator audit、solver、worker、GPU、root/sudo 或特权 workload；保护文件无变更。

下一步应先做不启动 workload 的 evidence assembly：将已有输出绑定到 source/reproduction host、两个 distinct data roots、reader、autonomous prediction、scoring 五类 typed evidence，再做独立 root review。任何可信绑定缺失时保持 fail-closed。
