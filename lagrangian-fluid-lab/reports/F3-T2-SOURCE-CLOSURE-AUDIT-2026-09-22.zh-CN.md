# F3 T2 source-side closure audit（2026-09-22）

本报告由 `f3_t2_source_closure_audit_v1.py` 生成，审计范围是 source-side closure。审计只读取 JSON、准备记录和小型 receipt 文本；未打开 HDF5，未启动 solver/GPU，未提交 queue，也未修改 registry、ledger、matrix、denominator 或阈值。审计绑定模型标识为 `gpt-5.6-luna`。

## 判定

T2 macro/path 均为 `false`，qualification claim 为 `none`，qualification credit 为 `0`。Diagnostic completion、terminal execution receipt 与 source metadata 不会自动升级为 T2。

## rows 28/32

row 28（f3_production_amp0p9_native010）的 exact prepared/H5/XML/control lineage 与 `.01`、836-frame、8.35 s source metadata 可复核；row 32（f3_production_amp1p1_native010）同样如此。但二者都没有独立 immutable source-window receipt，也没有 per-source unknown、CDF 或 residence-CDF acceptance receipt。因此 exact lineage/declared window/cadence 存在，source-side closure 仍为 `false`，credit 为 `0`。

## row 24 terminalization

row 24 的 execution receipt 为 `succeeded`，required outputs 完整且小型 receipt hash 可复核；summary 为 completed，source window 为 4176 帧（0..4175），覆盖到 8.350012828223477 s，identity native frame selection，无 interpolation，checkpoint committed frame 为 4175。这些条件构成合法的 terminal engineering receipt：`True`。

它仍是 native dense `.002` 的 material diagnostic，`qualification_claim=none`、credit 为 `0`。summary 中存在 unknown/residence quantiles，但没有 formal CDF 或 residence-CDF acceptance receipt，因此 material acceptance 仍为 `false`。source-preflight 的 `native_output_interval_nominal_s=0.01` 与 spec/registered dense source/frame map 的 `.002` 不一致，已作为 warning 保留，不能被忽略或升级为 acceptance。

## 缺失的 root-owned CFD source

以下 rows 仍按 gap audit 要求 exact root-owned CFD source closure；template/development source 不能替代，所有项 qualification claim 均为 `none`：

- row 16: `F3_REV075_MATERIAL-AMP0P95-0075`，asset `f3_production_amp0p95_native010`，amp=0.95，dp=0.0075，native output=0.01 s。
- row 17: `F3_REV075_MATERIAL-AMP0P95-0075`，asset `f3_production_amp0p95_native010`，amp=0.95，dp=0.0075，native output=0.01 s。
- row 18: `F3_REV075_MATERIAL-AMP0P95-006`，asset `f3_fine_amp0p95_native010`，amp=0.95，dp=0.006，native output=0.01 s。
- row 19: `F3_REV075_MATERIAL-AMP0P95-006`，asset `f3_fine_amp0p95_native010`，amp=0.95，dp=0.006，native output=0.01 s。
- row 20: `F3_REV075_MATERIAL-AMP1P05-0075`，asset `f3_production_amp1p05_native010`，amp=1.05，dp=0.0075，native output=0.01 s。
- row 21: `F3_REV075_MATERIAL-AMP1P05-0075`，asset `f3_production_amp1p05_native010`，amp=1.05，dp=0.0075，native output=0.01 s。
- row 22: `F3_REV075_MATERIAL-AMP1P05-006`，asset `f3_fine_amp1p05_native010`，amp=1.05，dp=0.006，native output=0.01 s。
- row 23: `F3_REV075_MATERIAL-AMP1P05-006`，asset `f3_fine_amp1p05_native010`，amp=1.05，dp=0.006，native output=0.01 s。
- row 26: `F3_REV075_MATERIAL-AMP1P1-0075-DENSE002`，asset `f3_production_amp1p1_native002`，amp=1.1，dp=0.0075，native output=0.002 s。
- row 27: `F3_REV075_MATERIAL-AMP1P1-0075-DENSE002`，asset `f3_production_amp1p1_native002`，amp=1.1，dp=0.0075，native output=0.002 s。
- row 29: `F3_REV075_MATERIAL-AMP0P95-0075`，asset `f3_production_amp0p95_native010`，amp=0.95，dp=0.0075，native output=0.01 s。
- row 31: `F3_REV075_MATERIAL-AMP1P05-0075`，asset `f3_production_amp1p05_native010`，amp=1.05，dp=0.0075，native output=0.01 s。

## CPU-only 与边界

本次未执行 HDF5 source audit（invocation count 0）；已有 JSON/source receipt 足以完成 closure 分类，无需重新打开长 H5。没有 solver/GPU/queue 动作，所有 qualification credit 保持零。

审计结果是 fail-closed：补齐 exact CFD source、terminal source audit 以及每 source unknown/CDF/residence receipt 后，仍需通过既有固定 gate 和 acceptance bridge 才能重新评估；本报告本身不改变任何资格状态。
