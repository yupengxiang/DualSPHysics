# UPDATE-68：V7 REVISE 后明确 verifier 入口与输出契约

V7 只读技术复核结论 `REVISE`，reviewer 无可独立验证身份/effort attestation，故只记技术意见。问题包括：allowlist predicate 含未定义的 decoded bytes/provenance 规则；Diagnostic key set 未逐项列全且验证后仍可能读取可变原对象；错误路径不可能保证输入携带 discriminator；BOM 未明确 decode 前判定；consumer 表中 schema/verifier/version/node ID 有非机器化描述与未闭合行；pre/post implementation gate 有授权循环；`VerifiedRecord` 缺可验证的来源绑定机制。

新增 [V8 草案](F8-R008-SYNTHETIC-NON-QUALIFYING-CONTROL-HARNESS-V8-DRAFT-2026-09-25.zh-CN.md)：定义 raw bytes→decoded value→精确 allowlist triple→固定 verifier→SHA-256/source-bound record 的步骤；列出完整 output key/type/value 表并只消费 validator 返回 snapshot；固定 BOM 的 raw-prefix 检查与各类异常映射；consumer 四元组按 exact schema、verifier/version digest、pytest node ID逐行拆分，缺 verifier/test 的行显式 `BLOCKED`；并将实现前设计 gate 与实现后消费前测试 gate 分开，允许的最小 consumer hardening 范围也明示。

本轮仅新增文档，未改消费者实现/测试/parser，未运行 solver/worker/GPU/queue；F8 execution gate 仍 open、T1 false、零信用。V8 仍待技术复审，consumer 表仍未完成全仓 sweep，所有缺实现/负向测试的行均为 BLOCKED。
