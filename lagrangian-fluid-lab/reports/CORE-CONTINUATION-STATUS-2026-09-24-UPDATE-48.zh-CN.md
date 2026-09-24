# Core continuation status — 2026-09-24 UPDATE-48

## F8 R008 C 阶段 solver 执行证据边界

只读核查发现，当前 per-case verifier 的 C 分支验证 raw solver manifest 与冻结 full-axis 的 ordinal/time 对应，以及每帧与输出文件 manifest 的 path/bytes/SHA 对应；它没有解析或校验 `solver_execution` 的内部字段。当前 synthetic fixture 将 `solver_execution` 设为 `{}`，仍可通过阶段结构验证及完整 B→C→D 结构链测试。定向命令运行结果为 **4 passed**；这些测试只证明结构验证器按现有实现工作，不代表 solver 执行证据充分。

机器可读 provenance schema 已声明 C 应记录 exact executable/wrapper/argv/input、退出状态、cgroup cap/peak/events、timeout/signal、process-tree 与 logs，但当前 verifier 尚未落实这些语义校验。故即使将来某个结构闭合的 C receipt 标为 `passed`，也不能仅凭当前链路把 `control_no_extrapolation` 置为 `defined_pass`。

当前 R008 `resource-admission-v1/receipt.json` 与 `cpu-native-preflight-v3/receipt.json` 均记载 `solver_invocations: 0`，one-shot lock 的 `solver_invocation_budget` 也是 0；目前 campaign 下没有 qualification solver-attempt bundle。静态 Definition/control pack 虽绑定并覆盖 `[0, TimeMax]`，但尚无实际 solver input/horizon/正常终止证据。因此 control gate 继续保持未裁决，不生成 pass；R008 `T1_numerical=false`、readiness false、资格信用为 0。

下一步先静态冻结一个 C solver-execution evidence contract，明确 exact argv/input 与 B Definition/control 的连接、可信日志绑定、终止/超时/信号、资源证据和完整运行 horizon 的可验证字段，再实现 additive verifier 与 synthetic-only negative tests。该设计需 Terra High 只读复核；它不修改冻结的 v1 回执、不启动 solver，也不扩大执行授权。在合同与复核完成前，不把现有 fluid reducer 的局部结果升级为完整 per-case native-integrity evidence。

本次未读取生产 solver bundle/frame，未运行 GenCase/native decoder/solver/worker/GPU/queue，未更改 scope、阈值、分母、registry 或资源账本。
