# Core 计划续推状态 UPDATE-107

日期：2026-09-25（Asia/Shanghai）

## 本次推进：V5 journal-local driver guard closure

只读核对 CPU、GPU 与 VRes driver 的时间循环条件，均为严格 `TimeStep < TimeMax`。V5 synthetic parser 据有限 IEEE-754 binary64 值重算提交的 `condition_result`；对每个 `(process generation, exec epoch, driver)` 检查 iteration ID 不重复、false terminal guard 后不再出现 guard；poll 必须绑定当前最新 true guard，不能在下一 iteration 或 terminal false 后挂回旧 guard。

同时纳入 poll terminal 顺序：同一 driver 的后续 poll/guard 之前，前一 `poll_begin` 必须有更早的 `poll_end`；end 落在边界之后则拒绝。若 end 缺失，parser 不将 journal 判为完整：累计 `driver_unclosed_poll_count`、令 `observed_driver_loops_complete=false`，并标记 `unresolved_call_order`。缺少 terminal false guard 也只产生 incomplete 观察，不得作成功语义。

补充 VRes 正向合成例：同一外层 guard 覆盖两个按序实例各自 predictor/corrector polls；另有旧 guard、false 后 poll、poll_end 越过 terminal guard、缺 end 后 terminal guard等负测。Terra High/high 配置的只读复核初轮发现 poll 可越过 terminal guard 的序列，已修复并复核确认；没有独立 model/effort attestation，故不记审计 attestation PASS。focused suite **49 passed**；`py_compile` 与 `git diff --check` 通过。

## 边界与后续

本轮仅检查 CPU/GPU/VRes driver 源码、V5 合同草案与内存合成 journal；未读生产 bundle/HDF5/one-shot receipt，未运行 planner/tick/canary/preparation/GenCase/native/solver/worker/GPU/queue。`driver_loop_termination_verified=false`、`query_causality_verified=false`、`cache_replay_verified=false`、T1 false、zero credit、gate open 保持不变。没有 source-callgraph extractor，故无法证明预期 driver 全集、guard/iteration 数值转移、每 guard 的完整 host-call × entry 覆盖、active window、table provenance 或 event-source completeness；journal 自报“闭合”不升级为可信正常执行。
