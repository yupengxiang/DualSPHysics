# UPDATE-226：F8 R002 新静态复核与 R008 readiness v8

日期：2026-09-27（Asia/Shanghai）

## F8 R002 新一轮只读静态复核

按本轮授权，对冻结的 R002 输入和历史失败证据重新作只读复核；没有重跑 GenCase、decoder、solver 或任何 worker。当前 Definition SHA-256 仍为 `086fa1cab8019c39c2d22fdfbee069441663b0615cdf9246c4383fd51b1b0bea`，控制 CSV 为 `bd623b5681f449804a3a2bdf61cded339e180065cf37e2d5d8b6ac92f9e3cfc1`，均与 v4 静态回执绑定一致。

结论仍为 **FAIL / scope closed / no retry**：Definition 缺少 `hswl`，同一冻结输入的保留 GenCase 日志报告该字段缺失并以 code 1 退出。`rhopgradient`、`gamma`、`speedsystem`、`coefsound` 是官方 Poiseuille 模板兼容缺口，不声称已被引擎逐项拒绝。CSV 的 705 行、有限值、单调时间和时间覆盖静态有效；这不证明 GenCase 成功复制/加载控制文件，也不构成运行证据。仅凭本轮静态材料没有可安全消除该 blocker 的修复；改输入或重新尝试需另立 revision/scope 与相应授权。

Terra High/high 配置只读复核未发现 P0–P2。P3 指出既有目录 `static-design-review-v4` 内的 schema、record ID 和 status 仍标为 v2，可能令自动化审计混淆“v2 方法版本”与“v4 复审实例”；现有 UPDATE-202 已说明该回执由 v2 builder 重算，因此不影响 FAIL/no-retry 结论。Reviewer 身份与所请求模型配置均未 attested。未改动 R001/R002、未重试任一 scope。

## F8 R008 readiness v8

新增 [readiness v8 receipt](../campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/t1-execution-readiness-audit-v8/receipt.json)，在保留 v7 历史的同时，将 UPDATE-225 selector-domain manifest、Linux v6.8 syscall-number baseline、对应 verifier/tests 和 UPDATE-221–223/225 来源审计纳入传递证据闭包。v8 明确 signed-int32 selector partition 完整，但它仍不是执行策略；462 个 native table numbers 尚无逐号 disposition/predicate，target kernel build/config 未 pin，x32、`nr=-1` 与 ptrace/seccomp 顺序的目标内核 conformance 未验证。

readiness v8 新增上述两项 syscall blockers，并保留 v7 的 trusted worker/runtime identity、真实来源验证 15-case T1、native-integrity/timestep adjudication、fanotify target-kernel conformance、trusted supervisor/final-fput observer 五项 blocker。`readiness_pass=false`、`T1_numerical=false`、solver/worker/GPU/queue/privileged-probe authority 均 false，qualification credit=0。Terra High/high 最终只读复核未发现 P0–P3；reviewer identity 未 attested。

v8 专项 **7 passed**；脚本/测试 `py_compile`、固定 receipt `--verify`、`git diff --check` 通过。另 v8 从固定 receipt 目录读取时执行 held-dirfd、no-follow、single-link、身份稳定性与 32 MiB 上限检查；非 canonical/含 `..` 的路径、重复 JSON key、`NaN/Infinity` 和覆盖写入均拒绝。没有运行目标 workload、privileged probe 或更改任何执行/资格账本。

## 只读 Core 总控快照

执行 `scripts/core_campaign.py status`（只读，不写 completion snapshot）：`can_finalize=false`；T1 家族 F3/F4 为 2/3；宏观 T2 为 0/2；正式训练为 0/9；T1 固定目标缺 432（其中已登记目标缺 288、另有 144 尚未登记）；材料目标缺 288；观测 T1/material case-run 均为 0；异机独立复现未通过。因果谱系与 evidence-validity 检查为 true、`issues=[]`，但这不代表 Core 完成。
