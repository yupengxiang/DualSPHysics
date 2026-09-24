# Core 续做状态（2026-09-24，UPDATE-25）

## 本轮新增发现

Terra High（high）对 BI4 静态格式审计 v1 只读审查为 `REVISE`。除了 v1 `verify_receipt()` 未对完整 canonical receipt 作比较，reviewer 发现现有 `scripts/native/bi4_dump.cpp` 把 BI4 内部 item/array 名直接拼到 `mkdir` 与输出路径。恶意或损坏 BI4 名称可能越出 decode namespace；事后 exact manifest 无法防止已经发生的写入。

v1 代码、报告、回执完整保留，不回写。v2 新增完整 payload 比较和“禁止用现有 `bi4_dump` 解码新输入”的执行门。未来 decoder 必须先验证完整名称树，再以 held dirfd + `openat/mkdirat`、`O_NOFOLLOW/O_EXCL` 在独占输出目录安全落盘，并检查类型/尺寸/资源上限及每个 I/O 错误；仍需事后 exact manifest。机器回执在 `campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/bi4-format-static-audit-v2/receipt.json`，说明在 `reports/F8-R008-BI4-FORMAT-STATIC-AUDIT-V2-2026-09-24.zh-CN.md`。

v2 定向测试与此前关联测试共 25 项通过，静态审计命令复算通过，`git diff --check` 通过。v2 Terra High follow-up 已提交，等待结论；审查范围包含 receipt 完整比较和安全 decoder 最低要求。只有 reviewer 后续 PASS 后才进入安全 adapter 实现审查。

## 权限与剩余状态

本轮未运行 decoder、GenCase、solver、worker、GPU 或 queue，也未编译任何程序。R008 仍无 solver 输出，历史 decoder binary 与源码构建来源仍未绑定；安全 decoder adapter 尚未实现。`readiness_pass=false`、资格信用为零、没有 solver 执行授权；正式 15-case T1 和 per-case provenance verifier 仍未完成。
