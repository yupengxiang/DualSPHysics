# F4 Tallwall120 Core reader smoke（2026-09-28）

这次是对 F4 Tallwall120 production collection 的只读集成检查，不启动 solver、worker、GPU 或 queue，也不写 registry、ledger、denominator、completion 或 qualification gate。

检查入口是：

`campaigns/core-v1/cfd/f4-tallwall120-production-root-v1/collection-refresh-terminal32-formal-v1.json`

manifest SHA-256 为 `86100523e66202f567ee29da6e178702f0e3ab19c63bd0cf861ff8a5fa0f86b4`。统一 `scripts.core_cfd_dataset.open_dataset` 成功打开全部 32 个案例，并完成：

- 32/32 source SHA-256 精确校验；
- 32/32 时间轴读取与严格递增检查；每例 218 frames、217 transitions，时间范围 `0.0–4.340002980805959 s`；
- 32/32 known-input 记录读取；
- 每例首帧、中间帧（frame 109）、末帧（frame 217）状态抽样；position、velocity、mass 全部 finite，`valid == particle_count`；
- 每例 geometry 均为 10 个 triangles；
- split 分布为 train/validation/id_test/ood_test = `16/4/6/6`。

因此，F4 这一方向的 Core reader 数据路径已经走通了一个完整的 32-case 粗粒度闭环。需要明确保留的边界是：manifest 声明了 `formal_release=true` 与 `formal_eligible=true`，但本次实际 reader 结果为 `reader_formal_eligible=false`。所以本报告只是 integration diagnostic evidence，不铸造正式 reader 能力，也不给 T1、training、T2 或 qualification 分数；本次 qualification credit 为 `0`。

机器可读结果见 [JSON receipt](F4-TALLWALL120-CORE-READER-SMOKE-2026-09-28.json)。
