# F8 R008 final-fput queue-barrier reducer v3

**状态：**additive synthetic diagnostic prototype。V1/V2 与冻结的 V17 contract 均保持不变；V3 仅在 V2 raw-byte/declaration consistency 检查之上，检查调用方声明的 queue barrier 与 close 顺序。它不定义或认证 runtime journal，不是 final-close、readiness、执行授权或资格证明。

## 动机与序号边界

UPDATE-230 的 Linux v6.8 upstream source audit 发现，FID/name fanotify queue 可把满足 merge 条件的连续事件合并，并对 mask 做 OR；滞留的 `FAN_MODIFY` 因而可能与后续 `FAN_CLOSE_WRITE` 形成组合 mask。当前 raw parser 有意拒绝组合 mask。静态候选方案是在全部 writer 已停止后，先将 name group 排至 EAGAIN，记录 pre-close barrier，再执行唯一 close，之后记录 close exit 与 post-close EAGAIN drain。

V16/V17 目前没有为 fanotify read/EAGAIN、cgroup-empty、supervisor close 和 raw event 定义共同 journal。V17 的 `group_seq` 仅是单 group 连续序号；`read_seq` 未定义为跨 producer 时间轴。V1 的 close syscall entry/exit seq 与 cgroup `record_seq` 也不因此成为同一序号域。V3 不比较这些原始数字：新的 `queue_journal.timeline_rows[].journal_seq` 是显式 caller claim；close marker 的单独 `syscall_seq` 只与 V1 context 对照。任何可信实现还须另行定义并认证共享、append-only、attempt-bound journal producer 与其无丢失保证。

## V3 检查

输入包装 `core.cfd.f8.r008_final_fput_join_barrier_input.v3`，内含未经修改的 V2 input 和 `f8-final-fput-queue-journal-v1`。timeline 对 V2 name-group 中每个事件按 `group_seq` 一对一列出 journal row，并以 raw event SHA-256 绑定；另需且只需各一条 cgroup-empty、pre-close EAGAIN、close entry、close exit、post-close EAGAIN marker。该专用 timeline 的 `journal_seq` 必须从 1 开始连续递增（uint64），不得缺行、重复或重排；各 marker 必须引用相同 attempt/group/close context。

检查约束包括：

- cgroup-empty marker 在 pre-close EAGAIN 之前；pre-close marker 在 close entry 之前；entry 在 exit 之前；post-close EAGAIN 在 exit 之后。
- pre-close EAGAIN 的 group watermark 精确等于其前面已列 fanotify rows 的最大 `group_seq`；若该 drain 没有事件，watermark 必须等于此次 capture `first_group_seq - 1`。
- barrier 后列出的 group events 必须严格位于 watermark 之后、close entry 之后、post-close EAGAIN 之前；末端 watermark 必须等于 V2 name-group 最后序号。
- 唯一 target `FAN_CLOSE_WRITE`（由 V2 raw parser 确认）必须处于 pre-close watermark 之后，且其 journal row 晚于 close entry。允许 reader 在 close syscall 返回前取走该事件，但最终 post-close EAGAIN marker 必须在 close exit 后。
- 两次 EAGAIN 声明的 loss/overflow/short-read counters 均为零；V2 对 raw event bytes 与冗余字段的重解析仍是前置条件，故组合/未知 mask 继续 fail closed。

timeline 中的 fanotify row 表示 reader 观察/取出事件，不是 kernel enqueue timestamp；因此其 journal 排序本身不能证明 `fsnotify_close` 与 queue enqueue 的内核因果顺序。只有 post-close drain marker 被要求位于 close exit 后，close-write row 可以在 close entry 与 exit 之间或 exit 之后出现。

这些检查只验证同一调用方对象里的声明闭合；journal id、序列、drain、loss counter、cgroup receipt 与 close marker 均未认证。输出 `queue_barrier_source_authenticated=false`、`shared_journal_contract_implemented=false`，并继承 V2 的 `trusted_observation=false`、`final_close_claim=false`、`readiness_pass=false`、`T1_numerical=false`、`execution_authority=false`、`qualification_credit=0`。

## 验证及后续门槛

新增 reducer V3 与专项 synthetic tests。raw parser、V1/V2/V3 四个测试文件合计 **78 passed**；V3 源码与测试 `py_compile` 通过。测试覆盖 close-write 在 close exit 前或后 dequeue、空 pre-close queue、错误/重复/缺失/跳号 journal row、raw digest 不符、非零 loss、watermark/attempt 错误及始终不授权结果。

V17 尚未纳入任何 barrier 或 shared-journal contract；Linux v6.8 upstream 也不是 target kernel pin。仍需独立审查的工作包括：冻结 future journal producer ABI/序号与 loss semantics、证明 cgroup quiescence 与 supervisor 所有写 token 已结束、target-kernel event-merge/queue conformance、可信 close-token↔file-cookie↔`__fput` observer bridge，以及持久化和签名/验证实现。在这些未完成前，V3 不可用于 worker admission、readiness、T1、seal 或资格 gate。

本轮只运行 synthetic pytest 与 `py_compile`；没有 fanotify/kernel/filesystem probe、sudo/特权操作、native build、生产数据读写、worker/solver/GPU/queue 操作或 ledger/registry/readiness/T1/T2 变更。
