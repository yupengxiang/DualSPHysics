# UPDATE-70：V9 复审遗漏补齐与 F4 ingress schema 纠正

V9 Terra 配置请求下的只读复核结论为 `REVISE`；reviewer model/effort 无独立 attestation，故只作为技术意见。发现五项问题：未列出 `core_formal_planner` 从 evidence 读正向 T1 并生成可启动 formal training plan；F4 production collector 的外层 qualification receipt 当前无 schema 且支持 inline Mapping；F4 range-root 实际 schema 是 `core.qualification.v1` 而非 unresolved；共享 verifier helper 必须不可导出且不可让调用方选 consumer identity；F4 connector evaluation 与 batch-decision 需分别有拒绝测试。

新增 [V10 规范性增补草案](F8-R008-SYNTHETIC-NON-QUALIFYING-CONTROL-HARNESS-V10-DRAFT-2026-09-25.zh-CN.md)：加入 Core formal planner 入口；为 F4 collector 设计新的精确 outer envelope，并分别约束 preparation/formal 两条验证路径；修正 range-root schema，同时保留 source-trust closure 为 BLOCKED；consumer ID 固定到不可导出的 per-consumer wrapper；拆分 connector evaluation 与 batch decision capability/test。未实现 parser/verifier/consumer/test，未启动训练或消费训练 plan；未改资格 evidence、已消耗 one-shot F3/F4 授权或历史 receipt。F8 R008 execution gate 仍 open、T1 false、零信用；无 solver/worker/GPU/queue/native/GenCase。
