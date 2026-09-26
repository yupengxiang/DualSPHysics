# F8 R008 final-fput declared-link reducer v2

**状态：**additive synthetic diagnostic integration。v1 保持不变；v2 在 v1 的全部 declared-link 检查之后，为每条 name-group event 调用 bounded fanotify parser，并继续恒定不授权。

## v2 增量

`scripts/f8_r008_final_fput_join_reducer_v2.py::build_diagnostic_receipt()` 先执行 v1 的 schema、observer、loss、close-context、cgroup 声明、group sequence、PIDFD action、对象声明与唯一 `FAN_CLOSE_WRITE` 检查；再对每个 raw event 重新解析 Linux v6.8 x86-64 wire bytes，并和 metadata/info-record 声明逐项比较。

v2 额外检查：

- raw PIDFD descriptor number 与 PIDFD action 声明一致，info index 为解析所得 PIDFD row；raw metadata PID 与 action 声明一致；
- parent DFID_NAME 与 child FID 的 raw FSID bytes 一致；
- child FID 的 FSID/file-handle SHA-256 与该 event `object_ref` 声明的 digest 一致。

该实现将 `file_handle_sha256` 定义为对 UAPI `file_handle` 中 opaque handle bytes 单独求 SHA-256；不包含 `handle_bytes`、`handle_type`、FSID、info header、name 或 alignment padding。这是 v2 diagnostic 的明确字节约定，不替代 filesystem-specific handle 语义。

这些只是跨声明/原始字节的 consistency checks。FSID/hash 相同不认证 filesystem、mount、inode generation 或 object；PIDFD number/PID 相同也不认证 descriptor lifecycle、进程身份或 task generation。DFID_NAME 摘要仍未和 `marked_parent_refs` 的独立身份记录相连；fanotify event 仍未由可信 observer 与 close token/cookie 因果桥接。

输出 schema 为 `core.cfd.f8.r008_final_fput_join_diagnostic.v2`，`fanotify_raw_bytes_reparsed=true` 只表示本次函数确实解析并比对了每条调用方 bytes；其余 `trusted_observation`、`kernel_source_pinned`、`observer_runtime_authenticated`、`fid_object_join_authenticated`、`parent_mark_identity_join_authenticated`、`pidfd_task_join_authenticated`、`close_token_cookie_bridge_authenticated`、`runtime_observation_authenticated`、final-close/readiness/T1/execution 均 false，qualification credit=0。输入仍是普通 Python dict；没有签名、trust root、bounded file parser、kernel hook/source authentication 或 runtime collector。

v2 拒绝 UPDATE-227 v1 测试中的任意 bytes 假阳性，因为那些旧 fixture 不符合 UAPI wire grammar；v1 仍保留历史 diagnostic 行为、继续标记 raw reparse=false。V17 合同和 readiness v8 均未改写，旧 receipt 不被重新解释。

## 验证与未解决项

v2 专项以合法 Linux v6.8 wire-shape synthetic events 测试 positive chain、raw info payload 篡改、错误 PIDFD number、错误 target-FID digest、parent/target FSID mismatch、writer record order 和 v1 schema rejection。parser、v1 reducer、v2 reducer 三个测试文件合计 **65 passed**，相关 `py_compile` 和 `git diff --check` 通过。没有独立 Terra High 审阅；也没有 source/build pin、runtime/fanotify event、kernel capability probe、production data、privileged action、worker/solver/GPU/queue 或 readiness/T1 操作。

后续 hard-open：close-token↔file-cookie bridge、producer sequence/loss coverage、causal journal order/object/epoch binding、PIDFD↔task-census 身份、parent FID↔marked directory identity、pinned target-kernel conformance，以及整个 observer/supervisor runtime provenance。v2 不能替代任何这些证明。
