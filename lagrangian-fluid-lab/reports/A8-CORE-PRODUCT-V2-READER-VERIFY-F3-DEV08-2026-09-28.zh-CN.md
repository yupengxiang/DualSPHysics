# A8 reader bundle v2 代表性 reader verify（2026-09-28）

在已发布的 `a8-full-reproduce-v2` package root 内，使用 package 自带的
`code/scripts/core_benchmark.py` 对 `F3_DEV_08_a0p953125` 做一次代表性 reader
验证：

- `passed=true`，`case_count=1`，耗时约 `2.642 s`；
- manifest SHA-256：`7da606f7177e0bb607af5d31b53ed122cd4ca88527c90c5e9fe698c0c3d892e4`；
- `full_temporal_scan=false`，这是单案例 smoke/reader execution，不是完整 32-case
  qualification；
- `qualification_inferred=false`，不产生 formal/T1/T2/reproduction credit。

机器回执：
`A8-CORE-PRODUCT-V2-READER-VERIFY-F3-DEV08-2026-09-28.json`。

