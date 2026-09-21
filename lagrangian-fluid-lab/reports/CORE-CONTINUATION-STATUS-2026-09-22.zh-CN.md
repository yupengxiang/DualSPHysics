# Core 接续状态快照（2026-09-22）

本快照用于接续被中断的 Core 执行任务。它不替换此前的计划、失败记录或
`CORE-IMPLEMENTATION-STATUS-2026-09-21.zh-CN.md`；科学资格仍以
`campaigns/core-v1/completion.json`、registry 和不可变 execution receipt 为准。

## 当前总门

截至本次接续，`core_campaign.py status --registry campaigns/core-v1/registry.json`
仍报告：

- T1 家族为 F3、F4，共 2 个，第三个尚未建立；
- 宏观 T2 家族为 0 个；
- 正式训练为 0/9；
- 缺失 T1 case-run 为 288/432，缺失材料 case-run 为 288/288；
- independent reproduction、causal lineage contracts 和 evidence validity 通过；
- `can_finalize=false`。

因此本轮没有启动正式训练，也没有把任何 CPU/native 或材料诊断证据升级为
T1/T2 credit。

## 接续中发现并闭合的 F2 v4 证据

工作区中保留了一条在上一轮状态快照之后完成、但尚未写入总状态的
`F2 submerged-orifice normal-remediation v4` 尝试。它是新的 literal recipe
假设：重新镜像 outer/gate `GeometryForNormals` 层，并用预测的 `86×56×48`
源格点修正离散质量闭合。该假设已经取得 exact-one CPU/native root authority，
并实际完成了 GenCase/native decode；它不是尚未执行的 proposal。

结果为硬失败：

- `zero_boundnor=29,484`，`zero_normal_size=29,484`；
- finite、粒子 ID 对齐和端点门通过；
- native mass 相对误差约 `0.78125%`，质量门通过；
- 总体 `preflight_pass=false`，solver/GPU/queue/ledger/registry/matrix 均未启动，
  qualification 与 matrix credit 都是 0；
- 同一输入禁止重试，父 scope 的 15 行分母仍保持 `executed=0,
  unattempted=15`，因为 CPU/native 初始完整性不等于已提交科学矩阵。

对应证据：

- [v4 root-review-only audit](F2-SUBMERGED-ORIFICE-NORMAL-REMEDIATION-V4-ROOT-REVIEW-2026-09-21.zh-CN.md)
- [v4 T2 boundary review](F2-SUBMERGED-ORIFICE-V4-T2-MATERIAL-REVIEW-V2-2026-09-21.zh-CN.md)
- `campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v4/preflight-v4/preflight.json`
- `campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v4/v4-current-failure-partition-audit-v1.json`

该证据把 F2 normal-remediation v2/v3/v4 路线收束为零 credit 负结果；不改变
registry、Core completion 或 F2 父分母，也不授权后续 v5 或同输入修复。

## F3/F4 材料侧接续状态

F3 最新 source-side closure 已确认：rows 28/32 的 lineage、窗口和 cadence
metadata 可复核，但没有独立 source-window、per-source unknown、CDF 和
residence-CDF acceptance receipts；仍为 `T2_macro=false`、`T2_path=false`。

F4 tallwall120 仍受每 source unknown mass、完整事件窗、F4 专用 CDF/residence
容差和逐矩阵 acceptance 接口阻塞；已有诊断与恢复回执不构成 T2。

## 本次验证

- F3 source-closure 定向回归：4 passed；
- Core campaign/formal-readiness 定向回归：12 passed；
- F2 v4 route/preflight/material boundary 定向回归：16 passed；
- 所有检查均未启动 solver/GPU/queue，也未修改 registry、ledger、matrix 或阈值。

下一执行门仍是：先取得一个真正独立、可证伪且通过静态/root 审查的新 T1
物理家族；在此之前不得生成或启动 9 个正式训练作业。
