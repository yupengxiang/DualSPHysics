# Core 接续状态更新 28（2026-09-24）

本更新完成 F8 R008 bounded safe BI4 scanner/materializer v1 的 Terra High 静态代码审查；不运行任何 native/solver 工具。

- Terra High（`gpt-5.6-terra`, high）同一审查线程先给出 `REVISE`，要求收窄输出父目录威胁模型、修正 item/array hide 标志和按官方格式序列化浮点 metadata。修订后结论 `PASS`。实现显式要求专用且 POSIX mode-private 的 output parent，并把 ACL/特权/跨 UID 写者列为调用方排除条件；同 UID 写者视为可信。官方 float/double defaults 固定为 `%.7E`/`%.15E`，不接受非 canonical format。审查机器回执：[safe decoder review v1](../campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/safe-bi4-decoder-review-v1/receipt.json)。
- bounded scanner 在完整结构/名称/计数/type 校验通过后才创建输出；有界 cap、同 FD 哈希与 fstat、no-follow input、独占输出、`st_nlink==1`、完整数组 manifest/hash/tree 复核均进入实现。该模块不是既有 `bi4_dump` 的来源证明或 wrapper，也不是 per-case source verifier。
- 验证：合成 BI4 decoder suite 17 passed；R008 相关测试 128 passed、5 deselected、0 failed。五项 deselected request/authorization builder 仅要求已消费的一次性 runtime namespace 为空；没有删除或重置它。Python bytecode validation 通过。合成夹具只在临时目录生成；没有读取/解码生产 BI4，也没有调用 GenCase、solver、worker、GPU 或 queue。
- 此前三项明确授权的一次性探索任务均以既有 immutable receipt 闭合，本次未重试：F8 R002 静态审查失败并关闭该 scope；F3 row30 资源/调度预检被阻塞且 worker 未启动；F4 supportcap CPU-native canary 预检通过但 canary/runtime 未启动。见 [F8 R002](../campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r002/static-design-review-v3/receipt.json)、[F3 row30](../campaigns/core-v1/material/evidence/f3-material-row30-resource-preflight-v2/receipt.json)、[F4 supportcap](../campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3/cpu-native-canary-preflight-r002-v1/preflight-receipt.json)。
- 未关闭：历史 `bi4_dump` build/source lineage、R008 solver frames、逐案例 provenance B/C/D verifier、provenance-v2 table、正式 15-case T1。readiness 仍 false、qualification credit 为 0；本次仅解锁下一步静态 schema/verifier 实现与审查。

详细说明：[F8 R008 安全 BI4 scanner 审查](F8-R008-SAFE-BI4-DECODER-REVIEW-2026-09-24.zh-CN.md)。
