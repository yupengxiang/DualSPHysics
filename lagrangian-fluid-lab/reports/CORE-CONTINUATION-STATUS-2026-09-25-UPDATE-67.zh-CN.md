# UPDATE-67：V6 REVISE 后拆分 synthetic harness 的设计与运行 gate

V6 直接技术审查为 `REVISE`。Reviewer 确认 parser 错误映射和 scanner 优先级基本闭合，但发现五项：输入 shape 的章节引用错误；Diagnostic validator 未限制为精确 builtin dict；production consumer 仍缺可执行的 raw-bytes→固定 schema/verifier/version→source-bound record 谓词；consumer 清单未把 schema/verifier/test-node ID 做逐项阻断映射；“实现前必须测试通过”与“尚未实现”相互矛盾。Reviewer 无法 attestation model/effort，故只作普通技术意见，不记 Terra High review/PASS。

新增 [V7 草案](F8-R008-SYNTHETIC-NON-QUALIFYING-CONTROL-HARNESS-V7-DRAFT-2026-09-25.zh-CN.md)：修正 input-shape 章节引用，限定 `type(value) is dict` 与一次性 snapshot 校验；要求生产 ingress 仅由原始 bytes + exact schema + 固定 verifier/version 产生受限记录；建立逐 consumer 四元组与当前 FAIL 状态；区分实现前设计批准和实现后、任何输出使用前的机器测试 gate。

继续只读核对归档 formal-admission receipt 和当前 F3/F4 T1 evidence 顶层 schema，二者使用 `core.qualification.v1`；据此将 Core global evidence consumer 的 exact-schema 候选补入 V7，并明确专用 strict/source-bound verifier 仍不存在。仅检查了必要 JSON 顶层身份字段，没有修改或重新解释资格结论。

本轮只有文档变更，没有消费者实现/测试/parser 修改或运行。V7 尚未复审；四元组清单仍是首轮 direct consumer 子集，新增测试节点目前都不存在，gate 明确为 FAIL。R008 execution gate 仍 open、T1 false、零信用，无 solver/worker/GPU/queue。
