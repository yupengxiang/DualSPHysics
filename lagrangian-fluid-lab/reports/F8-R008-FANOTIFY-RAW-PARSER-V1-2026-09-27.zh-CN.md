# F8 R008 bounded fanotify raw parser v1

**状态：**独立、纯内存、diagnostic-only parser；尚未接入 UPDATE-227 reducer，也不是运行时事件验证器。

## 输入与解析范围

`scripts/f8_r008_fanotify_raw_parser_v1.py::parse_declared_name_event()` 接受 V17 `raw_record`、redundant `metadata` 和 `info_records` 三部分。单条原始 event 上限 64 KiB；raw/base64、长度、SHA-256、精确字段集合及 canonical base64 都在 parser 内复核。当前只接受 V17 name-group 的六种单事件 mask：CREATE、MODIFY、CLOSE_WRITE、OPEN、ACCESS、CLOSE_NOWRITE；合并/未知 mask、permission group、rename、溢出、其他 info grammar 均拒绝。

解析按 Linux v6.8 x86-64 wire layout：24-byte little-endian metadata；FID 类 record 解析 info header、8-byte FSID、`handle_bytes`/`handle_type`、有界 file handle、DFID_NAME 的 NUL 结尾 basename 与零对齐字节；PIDFD 为精确 8-byte record 且拒绝负 sentinel。raw stream 必须恰好由三项 info records 全部消费。derived metadata 与 info-record 的类型、顺序、长度和完整 bytes 逐项比较调用方冗余声明。

对该 pinned upstream writer 的普通 name event，parser 检查原始 wire 次序 `DFID_NAME → FID → PIDFD`（目录/name、child FID、PIDFD）；V17 合同则规定 record multiset 并要求保留原始 offset 次序。此项是实现对 Linux v6.8 writer 的更窄约束，不修改 V17 合同，也不代表任何未 pin 的 vendor kernel 与其一致。UAPI 的 metadata/info layouts 见 [Linux v6.8 fanotify UAPI](https://github.com/torvalds/linux/blob/v6.8/include/uapi/linux/fanotify.h)；alignment、FID payload/padding 与 writer emission order 见 [Linux v6.8 fanotify writer](https://github.com/torvalds/linux/blob/v6.8/fs/notify/fanotify/fanotify_user.c)。

FSID 按 8 个原始字节解析并只输出摘要；parser 不自行判定全零 FSID 是否能形成有效 filesystem/object identity。该决定属于后续 mount/FSID/FID/object-generation join 与 pinned-filesystem conformance。

## 输出边界

成功仅表示 `raw_bytes_reparsed=true`、原始 bytes 与 redundant declared fields 结构一致。输出仍固定标记为未认证输入、未 pin target kernel source、未认证 runtime event、未认证 PIDFD-task/FID-object join、未验证 close-token-cookie bridge、无 readiness/qualification claim、credit=0。parser 不采集事件、读取文件或初始化 fanotify，也不证明 raw bytes 是内核产生、完整无丢失、来自指定 attempt/group，或与 observer、close syscall、output object、cgroup census 对应。

UPDATE-227 的 reducer v1 **没有调用本 parser**，仍将 `fanotify_raw_bytes_reparsed=false`；它的旧 synthetic raw rows 仍只满足 v1 声明层检查。因此本增量不撤销 UPDATE-227 的 REVISE 状态，也不消除 readiness blocker。下一步应新增/评审 reducer 集成版本、以真实 wire-shape synthetic rows 覆盖联测，并保留所有 trust/final-close/readiness/T1/credit claims 为 false/0。

## 验证

`tests/test_f8_r008_fanotify_raw_parser_v1.py` 与既有 reducer 专项测试合计 **58 passed**；parser 与测试 `py_compile` 通过。测试只构造 synthetic byte vectors，覆盖六种允许 mask、声明值逐项绑定、metadata/header/FID/PIDFD grammar、writer 顺序、padding/长度边界、base64/hash/size 与始终不授权的输出标记。没有独立 Terra High 审阅、运行时 kernel conformance、fanotify probe、production data 或 privileged action。
