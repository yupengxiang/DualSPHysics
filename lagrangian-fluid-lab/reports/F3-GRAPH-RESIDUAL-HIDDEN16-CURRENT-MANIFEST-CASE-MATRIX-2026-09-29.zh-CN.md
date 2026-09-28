# F3 graph_residual hidden16 current-manifest case matrix

- 状态：`blocked_fail_closed`；source-bound=`False`；fail-closed=`True`
- 覆盖：training `3` + case `32 × 3 = 96`，总计划 `99`
- 唯一性：namespace `99/99`，nonce `99/99`，command SHA `99/99`
- 运行权限：所有 training/case plan 均 `launch_allowed=false`；diagnostic-only；formal/T1/T2/qualification=false；credit=0
- current-manifest training receipts：需要 `3`，已绑定 `0`，缺失/拒绝 `3`
- terminal receipts：需要 `96`，当前 `0`，缺失 `96`；本轮未启动 GPU/queue/runtime

## 绑定来源

- current canonical manifest：`5d53fd9c1bfed991027f23464d9d11f533bf7d766c960aab6986e91c83f4c768`；raw bytes `93710`
- historical graph_residual matrix：`/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-GRAPH-RESIDUAL-HIDDEN16-SEEDS17-29-43-TRAINING-2026-09-28.json`；只作为 hidden16/500-update/config reference，不冒充 current receipt
- checkpoint、case HDF5、trajectory、evaluation、progress 均未打开、未 stat、未 hash

## Training identity

| seed | 状态 | run_id | receipt | checkpoint |
|---:|---|---|---|---|
| 17 | `running` | `f3-graph_residual500-hidden16-currentmanifest-seed17-20260929-v3` | `missing` | `planned-only` |
| 29 | `running` | `f3-graph_residual500-hidden16-currentmanifest-seed29-20260929-v3` | `missing` | `planned-only` |
| 43 | `running` | `f3-graph_residual500-hidden16-currentmanifest-seed43-20260929-v3` | `missing` | `planned-only` |

## 32-case coverage

| # | case | split | role | HDF5 metadata bytes |
|---:|---|---|---|---:|
| 00 | `F3_DEV_00_a0p903125` | `test` | `development_extrapolation` | 899562494 |
| 01 | `F3_DEV_01_a0p909375` | `test` | `development_extrapolation` | 899502944 |
| 02 | `F3_DEV_02_a0p915625` | `test` | `development_extrapolation` | 899257415 |
| 03 | `F3_DEV_03_a0p921875` | `test` | `development_extrapolation` | 899285381 |
| 04 | `F3_DEV_04_a0p928125` | `test` | `development_extrapolation` | 899600874 |
| 05 | `F3_DEV_05_a0p934375` | `test` | `development_extrapolation` | 899139420 |
| 06 | `F3_DEV_06_a0p940625` | `train` | `training` | 899634806 |
| 07 | `F3_DEV_07_a0p946875` | `train` | `training` | 899585032 |
| 08 | `F3_DEV_08_a0p953125` | `validation` | `development_interpolation` | 899512487 |
| 09 | `F3_DEV_09_a0p959375` | `train` | `training` | 899701103 |
| 10 | `F3_DEV_10_a0p965625` | `train` | `training` | 899786474 |
| 11 | `F3_DEV_11_a0p971875` | `train` | `training` | 899739060 |
| 12 | `F3_DEV_12_a0p978125` | `train` | `training` | 899800349 |
| 13 | `F3_DEV_13_a0p984375` | `validation` | `development_interpolation` | 899576772 |
| 14 | `F3_DEV_14_a0p990625` | `train` | `training` | 900082956 |
| 15 | `F3_DEV_15_a0p996875` | `train` | `training` | 900176936 |
| 16 | `F3_DEV_16_a1p003125` | `train` | `training` | 899978242 |
| 17 | `F3_DEV_17_a1p009375` | `train` | `training` | 900503563 |
| 18 | `F3_DEV_18_a1p015625` | `validation` | `development_interpolation` | 900394799 |
| 19 | `F3_DEV_19_a1p021875` | `train` | `training` | 900242210 |
| 20 | `F3_DEV_20_a1p028125` | `train` | `training` | 900624967 |
| 21 | `F3_DEV_21_a1p034375` | `train` | `training` | 901118248 |
| 22 | `F3_DEV_22_a1p040625` | `train` | `training` | 900796925 |
| 23 | `F3_DEV_23_a1p046875` | `validation` | `development_interpolation` | 901226878 |
| 24 | `F3_DEV_24_a1p053125` | `train` | `training` | 900920008 |
| 25 | `F3_DEV_25_a1p059375` | `train` | `training` | 901319562 |
| 26 | `F3_DEV_26_a1p065625` | `test` | `development_extrapolation` | 901286606 |
| 27 | `F3_DEV_27_a1p071875` | `test` | `development_extrapolation` | 901823189 |
| 28 | `F3_DEV_28_a1p078125` | `test` | `development_extrapolation` | 901640992 |
| 29 | `F3_DEV_29_a1p084375` | `test` | `development_extrapolation` | 901526081 |
| 30 | `F3_DEV_30_a1p090625` | `test` | `development_extrapolation` | 901574649 |
| 31 | `F3_DEV_31_a1p096875` | `test` | `development_extrapolation` | 901526961 |

## 边界

这是只读 bounded JSON identity binding 和 dry-run matrix。缺少真实 current-manifest training receipt 时整体 fail-closed；即使 training identity 完整，96 个 case 仍等待独立自然退出、evaluation、HDF5 validator、artifact identity 与 process proof，不能直接计入 Core。
