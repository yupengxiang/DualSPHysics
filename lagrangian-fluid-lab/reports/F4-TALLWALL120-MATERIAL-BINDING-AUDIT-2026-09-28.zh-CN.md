# F4 tallwall120 材料绑定审计（2026-09-28）

结论：本次严格 fail-closed，未运行 `f4_tallwall120_material_diagnosis.py`。目标真实 CFD 产物 `production-dev-07` 可读，但现有 material trace/manifest 均没有明确绑定到它，不能把其他 case 的 baseline24 结果转移过来。

| 项目 | 实际绑定 |
|---|---|
| 目标 source | `f4-tallwall120-production-dev-07/product/trajectory.h5`，SHA-256 `6ae8ca…`，218 帧、217485 粒子 |
| 现有 native004 material trace | `tallwall120_native004_material.h5`，绑定 source SHA-256 `918468…` |
| 现有 trace source | `f4-tallwall120-qualification-cell-14/product/trajectory.h5` |
| derived view manifest | `f4-tallwall120-native004-stride5/trajectory.h5.manifest.json`，同样绑定 cell-14 |

关键缺口：evidence 下对 `production-dev-07` 路径、case-id 和目标 SHA-256 均无命中；native004 trace 只有 101/1086 个 native frame，且 `event_window_complete=false`。因此 baseline24 的 unknown、首次失效和 coverage 均为“未计算”，不是零，也不是 cell-14 结果。

本次记录明确为 `diagnostic-only`：`T1=false`、`T2=false`、`credit=0`。未修改阈值、算法、registry、ledger、qualification 或 `PLAN.md`。

针对性检查：JSON 校验通过；诊断脚本 `--help` 通过；`tests/test_f4_tallwall120_material.py` 与 `tests/test_f4_tallwall120_cadence_terminal_diagnosis.py` 共 `6 passed`。

后续候选：当前 dev-07 方向不可作为候选。需要先生成带有 dev-07 精确 source path/SHA-256 的完整 material trace，再用未修改的 baseline24 诊断脚本重跑。

机器 receipt：`F4-TALLWALL120-MATERIAL-BINDING-AUDIT-2026-09-28.json`。
