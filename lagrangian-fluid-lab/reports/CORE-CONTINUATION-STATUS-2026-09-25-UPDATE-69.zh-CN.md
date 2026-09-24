# UPDATE-69：V8 复核整改与资格消费者入口扩展盘点

按 `gpt-5.6-terra` / high 配置请求的 V8 synthetic non-qualifying harness 只读技术复核结论为 `REVISE`；工具未提供 reviewer model/effort 独立 attestation，故只记录技术意见、不声称可验证的 Terra High PASS。六项意见为：实现前 gate 把缺失测试节点判 FAIL、同时又要求先闭合测试表才可实现，形成死锁；parser 对外 `dict` 与“consumer 只读 tuple”冲突；production accept 未将三元组固定到 verifier/artifact/root/role capability 的不可变调度；consumer matrix 没有逐入口规定旧 Mapping/API 处置、验证前禁止读取字段和验证后类型；源码 SHA 只是 review anchor，不能证明 loaded-code identity；output key order 未列为 validator 可执行条件。

新增 [V9 草案](F8-R008-SYNTHETIC-NON-QUALIFYING-CONTROL-HARNESS-V9-DRAFT-2026-09-25.zh-CN.md)，逐项修订以上问题：parser 只返回经完整顺序检查的不可变 tuple；移除 parser-local result slot；production ingress 由 trusted bootstrap 内固定 dispatch 绑定 verifier callable、artifact digest、root capability、role contract 和 scope capability；说明源码 SHA 不等于运行时 attestation，且当前没有可用 trusted launcher/root capability，故 production acceptance 仍整体禁用；预实现 gate 只要求设计审查与测试计划/node ID 完整，不要求测试先存在/通过；实现后再要求节点实际存在并通过。

此外，针对 scripts/tests 中 qualification/admission schemas、所有正向 `T1_numerical` 分支与 F8 reducer/registry 入口检索，补入 Core campaign/production、F4 qualification runner/collector/registry/dispatch/connector、F3 material readiness 与 row30 root packet、F3/F4 T2 contract、F4 material preflight 和 F4 supportcap canary authorization 等入口。每项指定禁止提前读取字段、旧 Mapping/API 处置、成功 capability 和专用负向 pytest node；F4 range-root 的 exact schema/source verifier 明确仍未找到并列为 BLOCKED。所有新增 verifier、测试与 trusted runtime 均未实现；完整生产 consumer gate 仍 BLOCKED。已消耗的一次性 F3 row30/F4 supportcap 授权及历史收据明确禁止因设计通过而改写、重试；root capability 是可信 key/descriptor 能力，不是 sudo 请求。该范围是静态源代码入口盘点，不声称运行时全数据流穷尽。

本轮未改生产消费者、parser、测试或资格数据，未读取生产 solver evidence，未运行 solver/worker/GPU/queue/native/GenCase。F8 gate open，`T1_numerical=false`，零信用。V9 待只读技术复核。
