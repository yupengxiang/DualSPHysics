# Core 续做状态（2026-09-24，UPDATE-27）

## BI4 静态合同复核结果

Terra High（`gpt-5.6-terra`, high）对 R008 BI4 静态格式审计 v3 给出 `PASS`，仅限静态合同。其确认 v3 在分配/写出前完成 same-FD no-follow/hash/fstat、bounded streaming raw/header/tree/count/bytes 检查与完整名称树校验；既拒绝有大文件预分配风险的 `LoadFile(..., true)`，也不依靠 post-run manifest 代替写前安全门。64-byte header、10,752×24-byte 数组 cap、16-MiB aggregate cap、64-MiB raw cap 与 R008 anchor/source 相容。

审查归档于 `campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/bi4-format-static-audit-review-v3/receipt.json`；它是 v1/v2 REVISE 同一 Terra High 审查线程的 follow-up。review 无编辑、无测试/构建、无运行工具，也无执行授权。

## 可以推进与仍然禁止的事项

静态格式合同阶段已完成 review PASS，可以进入 bounded streaming scanner/safe decoder 的静态实现及代码审查。当前实现还不存在；不能调用旧 `bi4_dump`。历史 decoder binary/build provenance 仍缺失；未来 safe binary 必须绑定源代码/build 输入及 invocation-time identity。R008 仍无 solver frames、per-case provenance verifier 和 15-case T1；readiness false、零信用、无 solver/decoder/GenCase/worker/GPU/queue authority。
