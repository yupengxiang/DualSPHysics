# Core 计划续接收口状态（2026-09-22）

本报告记录从附加 `PLAN.md`、原中断任务和当前工作区继续推进后的收口状态。计划中的验收门槛作为约束参考；历史 receipt、v4/v5 source closure 和未跟踪 CFD 产物均未被覆盖或清理。

## 本轮完成

- F2 submerged-orifice normal-remediation v4 的最新边界已固定：`BoundNor=0` 和 `NormalSize=0` 各 `29484`，全部在 `Mk=18` gate；CPU/native hard failure，solver product、matrix credit 和资格 credit 均为 0。
- F3/F4 material minimal-repair audit 已切换到 20260922 版本化 evidence；`T2_macro=false`、`T2_path=false`，没有 registry、ledger 或分母变更。
- F4 tallwall120 新建只读 acceptance bridge。engineering receipt 仅绑定输入、6 个案例、33 个矩阵行和恢复语义；科学 receipt 仍 `blocked`、`credit=0`，未借用 F3 的 CDF 阈值。
- 第三个 T1 家族 bounded route audit 完成。F1/F2/F5/F6 既有路线已去重；没有新的、证据充分的独立假设进入 root review，因此第三家族仍未建立。
- 正式源闭环建立独立 v6 namespace，重新绑定当前 8 个必需源文件。v5 保持历史快照且对当前源变更 fail-closed；v6 `closure_sha256` 为 `d692701964bfd4d0ddaa2db437b8870a2ea71e4ffbb428282398573aa89a05ba`。

## 当前 Core 门

`can_finalize=false`。当前 `t1_families=[F3,F4]`，`macro_t2_families=[]`，`training_runs=[]`；缺少 `288` 个 T1 case-runs、`288` 个材料 case-runs，另有 `144` 个尚未登记的 T1 case-runs 和 `288` 个尚未登记的材料 case-runs。

formal v6 明确保持：`formal_release=false`、`formal_training_allowed=false`、`formal_job_count=0`、`launch_allowed=false`、`root_admission.granted=false`。没有启动训练、GPU、solver 或 queue。

## 验证

- 新增和受影响的定向测试：`32 passed`。
- 完整回归：`1776 passed, 1 skipped`。
- v6 read-only verifier：`ok=true`；当前源文件、v6 audit、readiness、launch contract 和 receipt 哈希均闭合。

## 下一步边界

下一步只能由 root review 接受一个真正独立的第三 T1 物理／数值机制，并冻结新的 scope、Definition、hard gates 和失败分母后再进行资格研究。不得把 F2 v4 同输入重跑、改用未经证明的 DBC 变体、阈值放宽、survivor renormalization 或 F3 改名当作第三家族；在第三 T1 和两个宏观 T2 家族出现前，不得启动 9 次正式训练。
