# UPDATE-229：F8 final-fput diagnostic reducer v2 接入 raw UAPI parser

在不改写已提交 reducer v1 的前提下新增 additive v2：v2 先复用 v1 所有 strict declared-link checks，再解析 name-group 每条 Linux v6.8 x86-64 synthetic fanotify event，逐字节对照 raw metadata/info rows。另核对 raw PIDFD descriptor 与 action claim、parent/target FID FSID、target FID 的 FSID/handle digest 与 event object-ref 声明；v2 将 `file_handle_sha256` 定义为仅对 opaque handle bytes 求摘要。v2 专项覆盖合法 wire fixture、原始 bytes/declaration 不匹配、错误 PIDFD/FID joins、FSID 分歧、writer order 和 v1 fail-closed 行为。parser/v1/v2 专项合计 **65 passed**，`py_compile`/`git diff --check` 通过。

该版本的结果只表示 synthetic/caller-provided bytes 与声明在结构上相符；目标 kernel/source 和 runtime event 不可信，FID/object-generation、parent mark、PIDFD/task census、close-token/cookie、observer source 与 causal order 均未认证。v2 `fanotify_raw_bytes_reparsed=true` 仅指原始 bytes 已在此调用中重解析，非可信观察证明；final-close/readiness/T1/execution 均 false、credit=0。旧 v1 fixture 不符合 wire grammar，v1 仍标 false 并保留旧行为；V17 contract、readiness v8 与历史 receipts 均未改写。

无独立 Terra High 审查、source/runtime conformance、fanotify/capability probe、生产数据、sudo/root、native build、worker/solver/GPU/queue 或 registry/ledger/scope/denominator 变更。下一步继续关闭 cookie bridge、producer continuity、causal journal/epoch、PIDFD/census 和 filesystem identity joins，仍不能接入 worker/readiness。

详见[实现边界](F8-R008-FINAL-FPUT-JOIN-REDUCER-V2-2026-09-27.zh-CN.md)、[v2 reducer](../scripts/f8_r008_final_fput_join_reducer_v2.py)、[parser](../scripts/f8_r008_fanotify_raw_parser_v1.py)与[v2 测试](../tests/test_f8_r008_final_fput_join_reducer_v2.py)。
