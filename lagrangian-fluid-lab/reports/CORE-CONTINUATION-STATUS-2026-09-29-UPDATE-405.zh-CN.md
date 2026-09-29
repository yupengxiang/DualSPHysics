# Core continuation status — UPDATE-405

日期：2026-09-29

本轮继续按“先走通一个方向，再细化安全边界”并行推进 F3 graph hidden16。raw seed17 的 SA-003 经行为级跨模块 AST/data-flow 复核后确认是审计启发式误报；residual seed29/43 已补齐与 seed17 对称的 receipt-bound admission 和 secure runner v2；MLP current-manifest 的 source-lineage drift 则确认是 producer/intake hash-domain 契约缺口，继续 fail-closed。没有因为 GPU 显存充足而绕过可信 scheduler、runtime identity 或 terminal 证据门禁。

## 已提交的可交付单元

- `6b8b40e1`：raw seed17 v3 security re-audit 改用可验证的跨模块行为检查，确认 rollout snapshot、training raw/canonical digest 在 admission 前完成稳定重读与交叉绑定；SA-003 关闭。raw hidden16 全量回归 `332 passed`，仍剩生产 scheduler trust anchor/one-shot consume witness 与真实 runtime GPU/terminal observation 两个 P1。
- `f059eab5`：MLP hidden16 current-manifest source-lineage blocker receipt。`5d53…` canonical SHA 与 `8d87…` raw-file SHA 的 hash domain 不一致，现有证据不能安全修 producer/intake，因此拒绝旧 receipt 冒充 current receipt；MLP 专项 `158 passed`，credit=`0`。
- `e376881f`：residual seed29 receipt-bound admission、secure runner v2、专项报告和测试。receipt/descriptor/terminal binding、一次性 external claim 和 fail-closed 边界均已覆盖，专项 `12 passed`；没有伪造 scheduler、GPU、Popen 或 HDF5 production evidence。
- `863398e7`：residual seed43 对称 admission/secure runner v2、专项报告和测试。专项 `9 passed`；seed29/43 均保持 `blocked_fail_closed`、credit=`0`。

## 回归与执行边界

本轮验证 raw hidden16 `332 passed`、residual hidden16 `187 passed`、MLP hidden16 `158 passed`、F4 Tallwall120 相关过滤集 `229 passed`、F8 trusted target pin/库存/readiness 相关 `31 passed`。新增脚本和测试通过 `py_compile`，提交范围通过 `git diff --check`，相关 JSON 报告均可读取并通过各自校验。所有本轮 workload/Popen/GPU 启动次数为 `0`，没有停止或重启已有进程，没有读取 production trajectory/evaluation，也没有修改 registry、ledger、denominator、gate 或 completion。

当前 GPU 快照为 GPU0/1 各约 `31,226 MiB` free，GPU2–7 各约 `48,494 MiB` free。允许在已有任务共存且独立 admission 确认显存/CPU/I-O 足够时使用空闲或共享 GPU，但显存充足本身不构成可信执行授权；本轮没有裸启 batch executor。

## Core 门禁

Core 仍为 `can_finalize=false`：T1 families=`F3/F4`（2/3），macro T2=`0/2`，formal training=`0/9`；9 个 registered model/seed formal runs 均缺失，T1 case-run 缺 `288`（目标 `432`），material case-run 缺 `288`（目标 `288`），independent reproduction=false，credit=`0`。raw seed17 的静态绑定缺口已关闭，但真实生产 scheduler authority/consume witness、真实 GPU/child identity observation、MLP source-lineage producer 修复和 formal terminal receipts 仍未形成，因此不得提升为正式训练或资格证据。

下一步继续优先补齐真实外部 scheduler-owned trust anchor/one-shot consume witness；在该证据与 runtime GPU/terminal proof 到位前，不启动新的 GPU workload、不扩展 96-case batch，也不修改 Core formal registry、ledger、分母或 gate。
