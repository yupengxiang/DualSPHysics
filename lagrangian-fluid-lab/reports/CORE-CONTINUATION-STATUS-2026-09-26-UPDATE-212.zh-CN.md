# UPDATE-212：F8 terminal completion contract v7 复审与 v8 修订

时间：2026-09-26（Asia/Shanghai）

## V7 独立复审

Terra High 配置 reviewer 对 V7 与 V3/V4/V6 及提供的源码节选做了只读复核，结论 `REVISE`、无 P0；reviewer 未独立 attestate 模型身份。其确认 V7 已消除 seal 后 verifier reopen/read 的矛盾，`DsphConfig.xml` 作为自动配置输入的方向正确，且没有放宽 fresh-run、正时长、末次主循环 SaveData、零 credit 或 no-execution 边界。

未闭合问题：

- **P1：** watcher 没有定义可重放的 syscall-record schema；仅 `FAN_REPORT_PIDFD` 不提供 rename old/new pathname，fanotify init/profile 缺 FID/name report mode 与确定性路径解析。
- **P1：** process-group evidence 与 runtime_guard 各个对象/数组仍无完整 nested exact schema、字段 bounds、枚举和排序规则。
- **P1：** 把首次 kernel `write(2)` 假设为恰好 64 字节没有源码依据；C++ stream 可能缓冲/合并，应绑定 source-level logical header emission 并允许 kernel writes 分片或合并。
- **P2：** held ProgramPath directory 必须按 `main(argv[0])`、`JAppInfo::ConfigRunPaths` 和 `GetCanonicalPath` 的实际词法规则绑定，不能误称为 `/proc/self/exe` 解析出的二进制目录。
- **P2：** `LittleEndian=0` 与 writer 实际调用 `GetByteOrder` 的证据须补入审查包。

## V8 additive proposal

新增 [terminal completion evidence contract v8](F8-R008-TERMINAL-COMPLETION-EVIDENCE-CONTRACT-V8-2026-09-26.zh-CN.md)，保持 V1–V7 不可变。V8 新增签名的闭合 syscall/event 记录 schema，并以 fanotify raw event 与 syscall path records 互证；为避免权限事件与 FID/name mode 不兼容，拆成 `FAN_CLASS_CONTENT` permission group 和 `FAN_CLASS_NOTIF|FAN_REPORT_DFID_NAME_TARGET` name group。为 process-group/cgroup 和 runtime_guard 所有数组补充精确 schema；按实际源码修正 DsphConfig 的 ProgramPath 绑定为 argv[0]+启动 cwd 的词法路径，并纳入 child `stat`/`FileSize` fallback 的 absent 轨迹；区分 `MakeFileHead/GetByteOrder` 的逻辑 64-byte header emission 与可能合并/拆分的 kernel writes。

本轮只做合成 F4 weight 参数的 CPU 数组试探：固定 k=32、保留 v3 gate/support 观测，仅改变预测器 Shepard 权重 regularization；在 5 个 q × 两个解析场上共 14,080 个 analytic queries 中，0.00025 m 试探值两场 RMSE 均低于 v3（quintic shear `0.00095343` vs `0.00095973 m/s`；Gaussian interface `0.00268202` vs `0.00283130 m/s`）。该参数是在原 calibration corpus 上探索后选出，额外 q 只属诊断性 synthetic screen，不构成独立调参外验证或候选通过；尚未创建 candidate、receipt 或消费 CPU/native one-shot。无生产数据、native/tracer/solver/worker/GPU/queue 或 registry/ledger 变更。
