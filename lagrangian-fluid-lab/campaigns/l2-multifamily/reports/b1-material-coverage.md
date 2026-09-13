# B1 材料覆盖与成本审计

状态：**complete**。本报告只审计保留的两份 F3 T2 候选；不改变旧 L1 结论，也不把候选提升为 `qualified_T2`。

## 原始数据表

| config | substeps | seeds | historical CPU s | aligned H5 GB | reliable seed fraction | support-gate failures | wall crossings |
|---|---:|---:|---:|---:|---:|---:|---:|
| REF008-0075-NOMINAL-s2 | 2 | 512 | 297.448 | 1.385 | 0.939453 | 347 | 0 |
| REF008-0075-NOMINAL-s4 | 4 | 512 | 493.799 | 1.385 | 0.939453 | 360 | 0 |

## 关键发现

- Both retained candidates have the same 512-seed reliability fraction: 481/512 = 0.939453125; 31 seeds are censored before the end.
- The s2 and s4 bundles share the same first-failure set at the recorded resolution of this audit; support-gate failure counts differ slightly (347 versus 360 frame-seed pairs), so extra substeps do not repair coverage.
- Per-source unknown mass reaches 0.0625 for source 0 and 0.05859375 for source 1, above the 0.01 candidate budget; terminal and first-passage bound differences also exceed the candidate limits.
- Observed event timing is numerically small in the surviving common subset (source-wise weighted MAE about 0.000258–0.000360 s), but this does not compensate for the approximately 6% censored mass and missing path qualification.
- The aligned HDF5 structural scans and source hashes are retained; neither candidate is reclassified as T2_macro or T2_path qualified.

## 下一步实验

- Do not spend the remaining material matrix on more s2/s4 repetitions of the same nominal source until the failure window is instrumented.
- Run one bounded diagnostic at the first-failure window with near-wall distance, visible-neighbour/support statistics, source visibility, and mass/identity loss recorded together.
- If that diagnostic identifies a deterministic coverage repair, spend at most one canary configuration on the repair and compare common-observed, coverage-loss, and worst-case uncertainty separately.
- Keep T2_path blocked until a full-coverage or explicitly interval-censored path reference exists; a smaller event-time error alone is not a path pass.

## 单位与统计语义

- `unknown_fraction`、reliable fraction 和 failure fraction 是无量纲质量/种子比例；事件时间用秒，路径误差用米，存储用字节，历史 CPU 用 CPU 秒。
- 每个配置有 512 个 tracer seed；这里的 mean/std 是在 s2/s4 配置之间计算的配置级统计，不把 512 个 tracer 当成 512 次独立 CFD 实验。
- 路径 RMS/P95 未计算，因为两份候选均有 wall/support 失败；缺失项保持 `unknown`，不能按零填充。
