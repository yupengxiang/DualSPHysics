# F4 tallwall120 dev-07 baseline24 真实材料诊断（2026-09-28）

## 结论

精确绑定 `production-dev-07/product/trajectory.h5` 的完整真实 source trace 已完成：218 frames、217 transitions，实际运行耗时 95.85227325093001 s。结果是 **diagnostic negative**：baseline24 support/unknown gate 不通过，事件窗口为右删失/未解析。

该结果固定为：`diagnostic_only=true`、`T1=false`、`T2=false`、`credit=0`。它不授予任何正式材料资格、T1/T2 或 ledger credit，也不改变阈值、registry、ledger、denominator、PLAN 或 F3 文件。

## 精确 source 与绑定

- source：`campaigns/core-v1/cfd/f4-tallwall120-production-archives-v2/f4-tallwall120-production-dev-07/product/trajectory.h5`
- case identity：`job_id=f4-tallwall120-production-dev-07`；`case_id=F4_resting_pool_laminar_tallwall120_x_v1_DEV_07`
- source：217485 particles，218 frames，`0.0–4.340002980805959 s`
- 运行前后大小均为 `2067911708` bytes；运行前后 SHA-256 均为 `6ae8ca7062e1fa15779fc9ad491d1117455700315c6a1ef4a12326458f0976ae`
- 参数：`q=0.5`、`dp_m=0.0075`、`seeds=512`、`substeps=2`、`neighbour_variant=baseline24`、24 neighbours

trace result、HDF5 attribute 与 checkpoint 的 source binding 已交叉核对：

- result/HDF5 `source_sha256` 都是 `6ae8ca…f0976ae`
- checkpoint `binding_sha256=2a56101d…9e27c`，与 canonical binding digest 一致
- 未使用 qualification-cell-14，也未覆盖仓库内历史材料产物

## Trace 与 diagnosis 结果

| 项目 | 结果 |
| --- | --- |
| trace status | `completed` |
| 实际 frames / transitions | `218 / 217` |
| committed frame | `217` |
| elapsed | `95.85227325093001 s` |
| mass closed | `true`；closure error `0.0` |
| event window | `complete=false`；`right_censored_or_unresolved` |
| unknown fraction max | `1.0` |
| common reliable-path coverage | `0.0` |
| unknown gate | `false` |
| contact / destination mass fraction | `0.0 / 0.0` |

只读 diagnosis 对完整 trace 重放无 mismatch：`replay_mismatches=[]`。512 个 seed 中 448 个首次在 frame 9–14 失效，64 个幸存；初始 support gate 本身已有 64 个 seed fail（448 pass / 64 fail）。这支持“baseline24 diagnostic negative”的结论，但不把首次失效时间解释为精确连续事件时间。

## 产物

machine receipt：`F4-TALLWALL120-DEV07-MATERIAL-BASELINE24-DIAGNOSTIC-2026-09-28.json`

临时运行产物：

- `/tmp/f4-dev07-material-baseline24-20260928.h5`，7050960 bytes，SHA-256 `75ab6f7f…0acf3`
- `/tmp/f4-dev07-material-baseline24-20260928.json`，SHA-256 `7fe80e13…4e73c`
- `/tmp/f4-dev07-material-baseline24-20260928.h5.checkpoint.json`，SHA-256 `34b29a8d…67208`
- `/tmp/f4-dev07-material-baseline24-20260928-diagnosis.json`，SHA-256 `9aeab222…61b55`

本次提交只包含 machine receipt 与本中文报告；没有修改 PLAN、F3 文件、阈值、registry、ledger 或 denominator。
