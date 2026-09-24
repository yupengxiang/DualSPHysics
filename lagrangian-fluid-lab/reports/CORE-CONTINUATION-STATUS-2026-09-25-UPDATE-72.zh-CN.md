# UPDATE-72：F4 synthetic harness V11 复核与 V12 exact-contract 修订

V11 只读技术复核为 `REVISE`（按 Terra/high 配置请求，但无独立 model/effort attestation，不记为可验证 Terra PASS）。剩余意见聚焦五项：`prepare_production_batch` 的 template/status/receipt digest/prepared-template digest 会改变产物或放行，却未进入 capability；collector ref 缺精确域与 target wrapper schema、outer key policy；dataset v2 sanitized projection 缺 exact recursive validator；raw-byte hash 与 canonical JSON digest 语义混用；旧 preparation public Mapping 入口及 collector mismatch 缺实际入口时序负测。

新增 [V12 草案](F8-R008-SYNTHETIC-NON-QUALIFYING-CONTROL-HARNESS-V12-DRAFT-2026-09-25.zh-CN.md)：明确 raw/canonical 两种 digest、strict collector envelope 与当前 tick wrapper/evaluation 对象形状；给 formal manifest→dataset v2 投影列 exact 顶层/case/nested known-input schema 和专用 recursive validator；将纯 batch decision capability 与包含受信 template/digests/目录 descriptors 的 preparation capability 分离，并关闭 legacy Mapping/path fallback，补列 public-entry negative nodes。

V12 为设计草案；无 parser/verifier/consumer/test 实现，未运行 planner、collector、prepare、GenCase、training、solver、worker、GPU、queue 或 native 任务。F8 execution gate 仍 open、T1 false、零信用。既有 F3/F4 one-shot 授权、历史回执与 namespace 均未改写或重试。

V12/C-v4 后续按 Terra/high 配置的只读复审（无独立 reviewer/effort attestation）确认 admission/hash 与 cache/XML 等前轮问题已实质补齐，但仍为 `REVISE`：C ref 将 V3 五字段误称七字段；VRes 多实例实际共用 driver-level guard；cache miss 样本表未强制等于对应 entry 表；`clone` 未区分 process 与 OpenMP/pthread thread；F4 `promotion_status` 缺精确派生公式。草案已改为明确继承五字段 ref、driver→多实例拓扑、entry/table provenance 等值校验、独立 thread-generation create/exit event，以及基于固定 14 scheduled indices 与 reused cell-12 的状态派生。再一轮只读复核认为 V12 无新确定性阻塞，但指出 C `source_callgraph_binding` 缺 exact schema/runtime-build closure，`scope_digest` 与 `qualification_row_digest` 未绑定 payload refs；V4 已补 fixed callgraph role/schema/object ID、instance/driver/host-call schedule 结构及 raw-digest 等值规则，尚待复核。实现与测试仍 BLOCKED。
最新复核确认上述绑定与 V12 摘要闭环明确，但指出 callgraph JSON 仍不能自证其 topology；V4 草案现要求从 verified source manifest、build flags、runtime/config/input refs 以 verifier 内固定 AST/extractor 重新计算并比较 function ranges/call edges、driver 与实例调度，并将 extractor 纳入 future root-pinned verifier hash。该要求尚无实现；草案等待再审。

最终限定只读复核确认 `input_count=0` 的 instance 与 `entries` 集合关系已改为 `entries IDs == input_count>0 instance IDs`，且 callgraph/exact digest 修订未引入新阻塞。该结果只是按 Terra/high 配置的技术审阅，无独立身份/effort attestation；实现与测试仍 BLOCKED。
