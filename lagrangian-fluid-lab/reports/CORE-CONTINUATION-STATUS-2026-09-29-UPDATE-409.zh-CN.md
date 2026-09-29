# Core continuation status — UPDATE-409

日期：2026-09-29

本轮继续按“并行、由粗到细、每个可提交单元及时提交”推进；所有新 subagent 均固定为 `gpt-5.6-luna`、`max`，历史记录没有被改写。GPU 策略保持不变：独立准入的 VRAM/CPU/I-O 预算充足时允许共享 GPU，但不停止或重启已有进程。

## F3 material coarse 已完成两条真实侧车

- `47ece642`：新增 s2 RERUN1 scheduler spec；随后由已有常驻 `core_runtime` 自然执行，attempt 为 `20260929T122016-16ac698caed1`。
- `63495d58`：新增并提交 s2 terminal-result intake；实际 execution 成功、return code `0`，完整 `836 frames / 835 transitions`，mass closure 与 unknown monotonicity 通过，但最大 unknown 为 `0.0625`，coverage 为 `0.947265625`，超过 `1%` gate，因此是 `negative_diagnostic`，不授予 T1/T2/credit。
- `0f664d5d`：新增独立 s4 RERUN1 scheduler spec；随后由同一个常驻 `core_runtime` 自然执行，attempt 为 `20260929T122756-ab18fca003d8`。
- `0be6f516`：新增并提交 s4 terminal-result intake；实际 execution 成功、return code `0`，完整 `836 frames / 835 transitions`，mass closure 与 unknown monotonicity 通过，但最大 unknown 仍为 `0.0625`，coverage 为 `0.947265625`，同样明确为 `negative_diagnostic`。

两次 job 都是 `2 CPU / 4096 MiB / 0 GPU`，scheduler receipt 的 GPU reservation 为 `0`；两次都绑定了新的 scheduler-generated attempt namespace。runtime attempt 位于 git-ignore 的 scheduler-owned 路径，intake 明确将其视为 runtime receipt reference，而不是可携带的 static formal receipt。没有把缺失的 fresh-root、host-I/O 或外部 trust anchor 伪装成正式 admission，也没有修改 registry、ledger、denominator、gate 或 completion。

## 当前正式状态

`core_campaign.py status` 仍为 `can_finalize=false`：T1 family 只有 `F3/F4`，macro T2 为 `0/2`，formal training 为 `0/9`；当前 observed T1/material case-runs 为 `0/0`，固定需求为 `288/288`，目标需求缺 `432/288`，independent reproduction 为 `false`，credit 为 `0`。两次真实侧车把 F3 coarse 的“提交→常驻 scheduler→terminal receipt→fail-closed intake”路径走通了，但因为共享的 unknown gate 失败，不能直接扩展到 `8→32`，也不能晋级正式分母。

本轮 scheduler 在两次任务完成后为 `running=0、queued=0、succeeded=294、failed=19、cancelled=13`。没有启动 production workload，未使用 GPU 执行 production，未停止或重启已有进程；核验时 GPU0–7 每张约 `48,497 MiB free`、利用率 `0%`。诊断侧车没有改变任何正式门禁。

## 下一步

先保留 s2/s4 两份 negative diagnostic，针对共同的 unknown-path failure 设计唯一的新 setup variant，并在取得 fresh one-shot root 与 scheduler-owned host-I/O receipt 后再次通过常驻 scheduler 执行；只有完整 temporal unknown gate 通过，才扩展到 `8→32` 并复制到 F4。正式训练九次、T1/material 终端分母、F8 target pins、A8 independent reproduction 等外部硬门槛仍需分别闭合。

详见 [UPDATE-409 JSON](CORE-CONTINUATION-STATUS-2026-09-29-UPDATE-409.json)、[s2 intake](F3-MATERIAL-COARSE-TERMINAL-RESULT-INTAKE-2026-09-29-RERUN1.json)、[s4 intake](F3-MATERIAL-COARSE-S4-TERMINAL-RESULT-INTAKE-2026-09-29-RERUN1.json) 与 [PLAN.md](../../../PLAN.md)。
