# UPDATE-66：按未认证技术审查修订 synthetic harness v6 草案

对 V5 的直接只读技术审查结论为 `REVISE`，审查者明确无法提供模型身份或 effort attestation，故只记录普通技术意见、不计为 Terra High review。意见指出五类可复现缺口：输入 discriminator 常量只有示例而缺逐字段约束；JSON/shape 与 unexpected exception 的映射边界不精确；生产 consumer 可被重标/重封装对象混淆；调用端未逐字段检查返回 schema/type/常量；错误优先级冲突矩阵和每个 consumer 的拒绝 corpus 未锁定。审查另要求把流程 attestation 与技术 release gate 分离。

新增 [V6 草案](F8-R008-SYNTHETIC-NON-QUALIFYING-CONTROL-HARNESS-V6-DRAFT-2026-09-25.zh-CN.md)，逐字段固定输入与输出 schema、限定异常到 diagnostic code 的映射、要求 strict duplicate-rejecting/no-normalization decoder 和来源绑定 verifier 类型、定义完整调用端 validator，并增加冲突矩阵及消费者负向测试 gate。结合 [UPDATE-65 消费者盘点](F8-R008-SYNTHETIC-CONSUMER-INVENTORY-2026-09-25.zh-CN.md)，将 `core_formal_readiness` 与 generic admission evidence 的 schema guard 缺口保留为前置 remediation 项。

本轮只有文档变更；未改消费者实现/测试，未实现 parser，未运行 pytest 或 production evidence 流程。V6 仍待有效静态设计审查和测试 gate；R008 execution gate 仍 `open`、`T1_numerical=false`、零资格信用。未启动 solver/worker/GPU/queue。
