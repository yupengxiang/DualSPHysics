# Core 计划续推状态 UPDATE-108

日期：2026-09-25（Asia/Shanghai）

## 本次推进：V5 source-callgraph 结构检查与已观察 guard 调度回放

在 V5 journal-local process/thread、cache 与 driver-guard 检查之上，新增 `inspect_untrusted_v5_source_callgraph`：检查 synthetic V5 callgraph JSON exact 顶层/ref/fragment/call-edge/driver/instance 结构、函数与 source-file object ID 映射、非空半开 byte range、hash/序号格式、driver-instance partition、instance 顺序、输入数上限及 integrator/interstep 对应关系。可选的 outer source-callgraph descriptor ref 会与 raw bytes 长度/SHA-256 比对。

新增 `inspect_untrusted_v5_journal_with_source_callgraph`：按 caller 声明的 driver-instance-interstep-entry 顺序重算每个已观察 true guard 应有的 poll 序列；比较 poll 数量、callsite、integrator、interstep、instance 与 input index；检查 false guard 不产生 poll、journal 与 callgraph 的 source identity 副本一致。正测覆盖 standard CPU 路径及单个 VRes driver guard 有序覆盖两个 instance、各自 predictor/corrector；负测覆盖缺 poll、错 callsite、VRes interstep 错序、缺失 driver ID、非法/错误 fragment 映射、bool input count 与 outer raw-ref hash mismatch。

初轮 focused suite **58 passed**。Terra High/high 只读复审发现：汇总字段可能在 missing-end/exception/missing-terminal-guard 时仍为 true，以及 V5 schema 复用了 V4 object ID；已修复，改为要求 poll 正常返回、loop terminal closure、cache diagnostic 无 unresolved 状态、process lifecycle 本地诊断完整，并冻结独立 V5 object ID。partial allowlisted fragments 的状态也进一步明确为仅“声明形状”一致、coverage 未验证。新增对应负测后 focused suite **59 passed**；`py_compile` 与 `git diff --check` 通过。该 review 是代码审查反馈，没有独立 model/effort attestation，不计审计 attestation PASS。

完整 `pytest -q` 共 **2934 passed, 32 failed, 1 skipped**（约 10 分 36 秒）；这是 review 修复之前启动的全套 run，不能视为最终代码版本的全套验收。该次失败项不包含本次 `test_f8_r008_c_execution_journal_v5.py`，主要涉及其他资格/receipt/hash-closure与旧 schema 快照，其中 source-closure 固定摘要会因本次源码编辑变化。最终改动版本的 V5 focused suite 为 **59 passed**；没有为消除这些跨范围失败而重写其他证据或摘要。

## 明确边界

这是对 caller-provided JSON 的结构和跨文档局部自洽诊断，不是 source-callgraph extractor：不会从源码重算 byte range/AST/call edges，不具备 verified feature manifest，不证明 fragment 覆盖完整；不绑定 build attestation 到 runtime image 或外层 attempt/evidence nonce；不验证 trusted event-source/无漏报；也不重算 active window、table raw provenance、采样域或完整预期 loop guards/时间步转移。部分 allowlisted source fragments 仍可被结构检查，但 `source_fragment_feature_coverage_verified=false` 与 `source_fragments_reparsed_from_source=false` 固定保持。

有效 journal/callgraph 结构或 schedule match 仍不表示真实执行：`source_callgraph_verified=false`、`expected_query_completeness_verified=false`、T1 false、zero credit、`gate_state="open"`。未读取 production bundle/HDF5/one-shot receipt；未运行 planner/tick/canary/preparation/GenCase/native/solver/worker/GPU/queue。

## 后续

接收并处理 Terra High 只读审查意见；完成后跑 focused/full suite 与静态检查，更新 V5 草案/PLAN 并提交推送。后续仍需可信源码/配置 extractor、event-source completeness、active window/table provenance、外层 evidence/runtime/build 交叉绑定及 consumer integration；本轮不会替代或激活这些路径。
