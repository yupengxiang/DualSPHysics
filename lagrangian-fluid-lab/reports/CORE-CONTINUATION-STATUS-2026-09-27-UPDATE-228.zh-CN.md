# UPDATE-228：bounded fanotify raw UAPI parser 原型

新增独立 F8 R008 fanotify raw parser v1：上限 64 KiB；重解析 Linux v6.8 x86-64 metadata 与普通 name-group 六种单事件的 DFID_NAME/FID/PIDFD 原始记录，校验严格 base64/hash/length、metadata、record headers/order、FID/name payload、零 padding 和 PIDFD sentinel，并逐字节对照 V17 redundant declarations。仅纯合成数据测试；parser 与既有 reducer 专项合计 **58 passed**，相关 `py_compile` 通过。

parser 是可复用的 bounded structural diagnostic，不认证 bytes 来源、target kernel/source、runtime event、PIDFD/task、FID/object、close-token/cookie 或 queue completeness；结果不提供 readiness/T1/execution/qualification，credit=0。其 DFID_NAME→FID→PIDFD 顺序约束来自上游 Linux v6.8 writer；V17 当前写明 multiset grammar 并保留原始 offset，因此本实现只声明为该源版本下的更窄 parser profile，不修改 V17 或泛化到 vendor kernel。FSID 全零与否留给后续 filesystem identity/conformance join 判断。

重要：本 parser **尚未接入** UPDATE-227 reducer v1；该 reducer 的 `fanotify_raw_bytes_reparsed` 仍为 false，旧 synthetic raw rows 仍仅通过声明层检查。故 raw parser 这一 join blocker 对 reducer 尚未关闭，readiness v8 blocker、F8 T1、execution authority 与 qualification credit 均不变。下一小步是新增 reducer integration version 与合法 raw vectors 的联测，再独立静态复核；close-token/cookie bridge、producer sequence coverage、causal journal binding、PIDFD/FID/census identity 与 target kernel conformance 仍 open。

上游依据：[Linux v6.8 UAPI header](https://github.com/torvalds/linux/blob/v6.8/include/uapi/linux/fanotify.h)，[Linux v6.8 writer](https://github.com/torvalds/linux/blob/v6.8/fs/notify/fanotify/fanotify_user.c)。本轮没有 fanotify init/mark、kernel capability/filesystem probe、sudo/root、worker、solver、GPU、queue、production data 或 registry/ledger/scope/denominator 改动；未运行任何 native build。

详见[parser 边界与 wire layout](F8-R008-FANOTIFY-RAW-PARSER-V1-2026-09-27.zh-CN.md)、[实现](../scripts/f8_r008_fanotify_raw_parser_v1.py)和[合成测试](../tests/test_f8_r008_fanotify_raw_parser_v1.py)。
