# Core 续做状态（2026-09-24，UPDATE-26）

## BI4 安全解析合同 v3

Terra High 对 v2 的 follow-up 结论为 `REVISE`：只在 `LoadFile(..., true)` 之后检查路径名仍太迟，全文件 buffer 和递归对象/array/value 分配可能先触发资源耗尽。

v3 基于官方 JBinaryData v5.4 编码与 R008 冻结 cohort 加入有界预解析顺序及数值上限：同一 no-follow、regular、single-link input descriptor 上 hash/fstat；header 恰 64 bytes、raw input ≤64 MiB、R008 支持 little-endian non-si64；最多 2 个 item 节点/深度 2、64 个数组、每项 metadata ≤128、名称 ≤128 bytes、单字符串 ≤4096 bytes、metadata 总计 ≤2 MiB、数组 count ≤10,752、固定类型宽度≤24 bytes、单数组≤258,048 bytes、数组 payload 总计≤16 MiB、解码输出≤24 MiB。parser 必须先流式验证所有上述值、overflow 与完整 EOF，再验证完整名称树，最后才可用 held dirfd 和 no-follow/exclusive 操作进行二次流式解码；原始输入需在同一 descriptor 上前后核对。

`LoadFile(memory=true)` 和 `OpenFileStructure()` 均不能直接充当有界 adversarial preflight；v3 要求新增 bounded streaming scanner。机器回执及说明分别在 `campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/bi4-format-static-audit-v3/receipt.json` 与 `reports/F8-R008-BI4-FORMAT-STATIC-AUDIT-V3-2026-09-24.zh-CN.md`。v1/v2 的 `REVISE` 记录和回执都保留。关联定向回归 28 项通过，v3 reviewer 正在进行。

## 状态

本轮未编译或运行程序；未调用 decoder、GenCase、solver、worker、GPU 或 queue。v3 是尚待独立审查的静态设计，不是安全 decoder 实现。R008 per-case provenance verifier、完整 15-case solver/T1 仍未完成；readiness 仍 false、零资格信用、无 solver 执行授权。
