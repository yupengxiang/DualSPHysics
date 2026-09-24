# Core 接续状态更新 23（2026-09-24）

本更新完成 F8 R008 per-case provenance 的静态设计复核；没有实现验证器或运行任何 native/solver 工具。

- Terra High（`gpt-5.6-terra`, high）对设计 v1 的 `REVISE` 已逐项修订；同一 Terra High 审查线程对 v2 的结论为 `PASS`，仅代表静态设计通过，不是新开第二 reviewer，也不是实现/执行许可。只读审查归档：[design review v2 receipt](../campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/t1-per-case-provenance-design-review-v2/receipt.json)；方案见 [proposal v2](F8-R008-PER-CASE-PROVENANCE-DESIGN-PROPOSAL-V2-2026-09-24.zh-CN.md)。
- v2 分离启动前 admission 与事后已消费 namespace 验证；要求新的 adapter/table schema，qualification 入口拒绝 v1/GenCase-only/synthetic provenance；并定义 solver output manifest、decoder 输入/输出与逐帧 raw-array 绑定、全原生时间轴到 HDF5/table/window 的关系，以及 Definition 对同目录控制 CSV 的路径/哈希/内容核验。
- reviewer 特别指出当前 adapter 不具备 solver/native raw-source provenance；新版必须将 provenance、native-integrity、metric/comparison 与 T1 decision 分开。即使 15 行指标和 8 个空间比较通过，仍须重新核验完整窗口、完整性门、CFL/time-step 与 cadence comparison，才可能有最终 T1 决定；本次及 verifier PASS 都保持零资格信用。
- 未决静态前置条件：只读冻结 BI4/`bi4_dump` 的完整 binary layout、端序、metadata 语义及输出 manifest。现有 `core_cfd.native_frame()` 仅证明代码调用 decoder 并读取特定输出文件，不能替代对所有 native 输出变体的格式合同。若现有证据不足，不做 runtime probe，另立并独立审查 R008 decoder adapter。后续 verifier 对 regular-file/no-follow 校验还应显式要求 `st_nlink == 1`。
- 验证：Definition/control pack 契约测试 15 passed；review archive 测试 4 passed。v4 readiness audit 仍为 `readiness_pass=false`、零信用，原有 per-case verifier 与正式 15-row 结果阻塞仍未关闭。本次未调用 GenCase、decoder、solver、worker、GPU 或 queue；未修改 R008 scope、阈值、分母、registry 或 ledger。
