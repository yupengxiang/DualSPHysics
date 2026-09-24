# UPDATE-71：V10 复核整改与 consumer capability 完整性

V10 只读技术复核为 `REVISE`（reviewer model/effort 无独立 attestation，仅作为技术意见）。发现：F4 batch-decision 漏掉 production design 和 optional audits；collector envelope 的嵌套对象同时被当作 inline 与独立 raw bytes；formal planner manifest-row 可自带 T1/audit marker；V10 所述 root-tick→validate_evaluation 调用图不符合当前源码；`production_qualification_binding.v1` 无 scope_id。

新增 [V11 草案](F8-R008-SYNTHETIC-NON-QUALIFYING-CONTROL-HARNESS-V11-DRAFT-2026-09-25.zh-CN.md)：collector envelope 改用独立 role/hash references；planner 明确拒绝 manifest-row 内联资格与审计字段；batch decision 改为 design + qualification + audit-set 三类不可变 capabilities；分别列拒绝节点；将当前调用图与待实现目标图区分，并规定不改 v1 schema、scope 由 trusted endpoint 与 evaluation 交叉绑定，必要时另起 v2。

所有增补仍为设计草案，未实现、未测试，也未运行 planner、训练、collector、solver、worker、GPU、queue、native 或 GenCase；不改历史 one-shot F3/F4 授权或 evidence。F8 gate open、T1 false、零信用。
