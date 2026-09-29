# F4 Tallwall120 archive-v2 inventory audit

本报告是 bounded、只读的 archive inventory 审计；没有打开、读取或重新哈希任何 HDF5，没有复制/转换 archive，也没有修改 formal gate、registry、ledger 或 PLAN。

## 结论

- 状态：`blocked_fail_closed`；qualification credit=`0`。
- `production-archives-v1`：32/32 个 case directory，32/32 个 bounded archive bundle 完整。
- `production-archives-v2`：4/32 个 case directory，观察到的 bundle 为 4/4；这 4 个条目均与 v1 共享同一 attempt/receipt/artifact identity，不构成新增独立覆盖。
- immutable publication marker：v1 root `.archive.lock` 存在；v2 root `.archive.lock` 缺失，因此 v2 没有同等的 collector lock 证据。
- collection manifest 仍是 `archives-v1`（32/32），而 material contract 要求 `archives-v2`；collection 的 source SHA/bytes 与 v1 archive metadata 均为 32/32 匹配，但路径 variant 仍漂移。
- material sidecar bounded namespace：0/32 complete，目录存在=`False`。
- qualification-v2 archive：13/15 个 cell bundle，缺失：`f4-tallwall120-qualification-cell-03, f4-tallwall120-qualification-cell-12`。

## 文件级边界

每个 archive 的 `archive.json` 与 `execution-receipt.json` 只按 JSON 读取；archive 内的 HDF5 只用 `stat` 比较存在性和声明字节数，`content_read=false`、`hash_recomputed=false`。非 HDF5 小输出在 8 MiB 上限内重新计算 SHA-256。

本审计只产生本报告和测试，不授权新的 solver/worker/GPU/queue 执行，也不把 CFD archive 自动升级为 material sidecar 或 T1/T2。
