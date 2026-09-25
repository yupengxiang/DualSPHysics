# Core 计划续推状态 UPDATE-106

日期：2026-09-25（Asia/Shanghai）

## 本次推进：V5 journal-local guard/cache 诊断

只读核对 `src/source/JDsAccInput.cpp::JDsAccInputMk::GetAccValues()` 与 `Reset()`，确认 `LastTimestepInput` 初始化为 `-1`；源码先检查 `LastTimestepInput>=0 && timestep==LastTimestepInput`，命中即 early return；miss 先写 timestep，再在 active 分支读取表并填充 `LastOutput`。因此 `+0/-0` 数值相等、负时间重复调用仍 miss、miss exception/缺失 end 会留下 output-unknown 状态，而缺失 end 的 cache hit 不改写原 cache value（但该 poll/attempt 仍 incomplete）。

在 synthetic-only V5 parser 新增以下 caller-bytes 局部诊断：

- poll 必须引用同 process generation、同 driver、condition=true 且 timestep 位型完全相同的 guard；guard 与 poll 绑定当前 process exec epoch，旧 epoch guard 不可跨 exec 复用。
- 对 `(process_generation_id, solver_instance_id, input_entry_index)` 按源码数值比较重放一个槽；miss、当前 miss seq、active table binding 对象存在性，以及 active hit 与其当前 miss 的 JSON 类型敏感绑定相等性均检查。该比较仅为 journal 内自洽检查，并非 raw table descriptor/provenance 验证。
- poll end 不可跨同 generation 后续 exec；可见同槽 begin/end 重叠拒绝。前一同槽 poll 缺 end、其后又有调用时标记 `unresolved_call_order`；journal 末尾未终结 hit 标记 `incomplete_poll_state`，但按 C++ early return 保留先前 cache value。
- exec 清空该 process 的 journal-local cache epoch；fork/clone child 在 exec 前可能继承普通 C++ 对象内存，故其 cache 初态不假定为 `-1`，query 标记 `unresolved_fork_cache_state`。仍固定 `query_causality_verified=false`、`cache_replay_verified=false`、`execution_semantics_verified=false`、`qualification_adjudicated=false`、T1 false、zero credit、gate open。

Terra High/high 配置的只读技术复核发现并促成修正 poll 跨 exec、exec 前后 cache 串用、unterminated hit 被错误污染、同槽调用交叠、旧 guard 跨 exec、fork cache 初值假设及 incomplete-hit 诊断标签等问题。没有独立身份/effort attestation，故不记为审计 attestation PASS。最终本地 focused suite **43 passed**；`py_compile` 与 `git diff --check` 通过。

## 边界与后续

本轮只读取求解器源码和 synthetic-only 设计文本，并使用内存合成 journal；未读取 production bundle、HDF5、solver frame 或 one-shot receipt；未运行 planner/tick/canary/preparation/GenCase/native/solver/worker/GPU/queue。尚未实现可信 source-callgraph 重算、完整 poll 覆盖/顺序、active window 重算、entry→raw-table/sample provenance 验证、trusted producer/event-source completeness、runtime identity、外层 evidence/attempt nonce 交叉绑定及 consumer 集成。因此本地一致诊断不授权执行、不产生 F8 T1/资格信用，不能代替后续可信 V5 producer/verifier。
