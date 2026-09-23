# F4 supportcap R002 CPU-native preflight 完成记录（2026-09-24，update 06）

UTC `2026-09-23T18:16:48.945969Z` 的即时环境门全部通过：CPU affinity 128、load1 `126.391`、可用 RAM `223,675,633,664` bytes、磁盘可用 `8,185,540,587,520` bytes，未发现 F3 material worker。随后按既有授权启动了唯一一次 CPU-native preflight，回执时间为 `18:17:03.404767Z`。

预检通过，状态为 `preflight_passed_runtime_not_authorized`。输入源为 `f4-tallwall120-qualification-cell-14/product/trajectory.h5`，只读核验 `10,326,356,548` bytes，SHA-256 为 `91846866c177e4c3036b7ef92c33a4e0bde7d9e8993efb01dde300811b7c096e`；仅在 hash 匹配后打开 HDF5。原生行 `0–41` 共 42 行，时间从 `0` 到 `0.1640080936314531 s` 严格递增。

机器回执见[preflight-receipt.json](../campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3/cpu-native-canary-preflight-r002-v1/preflight-receipt.json)。授权摘要绑定匹配，资源 blocker 为空；无 tracer/canary、solver、GPU、queue 或 worker 启动，无 registry/ledger 变更，qualification credit 为 0。one-shot 已消耗，不得同输入重试；该结果不授权任何 runtime 执行。相关测试：`tests/test_f4_supportcap_r002_cpu_canary_preflight_v1.py`，14 passed。
