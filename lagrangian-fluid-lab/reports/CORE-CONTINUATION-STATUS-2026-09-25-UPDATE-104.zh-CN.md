# Core 计划续推状态 UPDATE-104

日期：2026-09-25（Asia/Shanghai）

## 本次推进：F8 R008 C-execution V5 journal structural parser

新增 `scripts/f8_r008_c_execution_journal_v5.py` 与 synthetic-only tests。当前切片只解析单 journal 字节对象，不读取路径或外部材料：

- strict UTF-8/JSON，拒绝 duplicate keys、非有限浮点、unknown/missing top-level 或 event-union 字段；验证 V5 journal 与 process/query event 的 exact key sets。
- 验证 builtin 类型、固定 32 位小写 hex attempt nonce、64 位摘要、16 位时间/IEEE-754 finite 编码、process/thread generation 基础结构、连续 event seq、coverage 区间及非递减 monotonic timestamp。
- 对 poll-end 做 journal 内局部引用检查；没有 end 的 begin 保留为 `unterminated_poll_count`，exception 仍是 terminal 但不会报告所有 observed poll 都 returned。
- 根据 Terra High 首轮 review，V5 合同明确 process `exit_code` 是 `0..255` 的 exact builtin int；负值、256 与 bool 均拒绝。
- parser 所有有效返回都固定 `gate_state="open"`、`execution_semantics_verified=false`、`qualification_adjudicated=false`、`T1_numerical=false`、`qualification_credit=0`。

focused 合成测试 21 passed；`py_compile` 与 `git diff --check` 通过。Terra High/high 的修复 follow-up 正在进行。

## 不能据此声称的事项

本 parser 只验证 journal 内部格式/顺序，不验证 event source 完整性、runtime identity、process-generation 生命周期/可达性、solver callgraph/query 因果、V5 LastTimestepInput 单槽 cache replay、table provenance 或真实执行。它没有读取 evidence payload/V2 attempt，不能验证 journal nonce 与外层 attempt nonce 相等；该 cross-binding 仍待未来固定 consumer。嵌套 supervisor/executable/table binding 目前只要求 object 容器，未验证其 descriptor-root 内容。

V5 trusted producer、process/query causal verifier、callgraph extractor、cache replay、supervisor/event-source trust、active key/root/runtime closure 仍未实现，parser 未接入任何 solver/qualification public API；不产生 solver 许可、F8 readiness、资格信用或 T1。未读 production campaign/bundle/HDF5/solver frame/one-shot；未运行 planner/tick/canary/preparation/GenCase/native/solver/worker/GPU/queue。
