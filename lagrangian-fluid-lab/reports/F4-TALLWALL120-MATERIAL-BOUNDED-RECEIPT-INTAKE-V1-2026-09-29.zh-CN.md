# F4 Tallwall120 material bounded receipt intake V1

- 状态：`blocked_fail_closed`。
- structural intake：`False`；这是静态结构结论，不是 launch 授权。
- 固定矩阵：`32` cases；observed sidecars=`0`；complete=`0`。
- blockers：dev07_case_sidecar_not_bound, missing_or_incomplete_32_case_sidecars, missing_or_incomplete_terminal_evidence, missing_or_invalid_root_scheduler_receipts, missing_required_material_markers, reader_manifest_sha_stale, receipt_consistency_archives_path_drift, source_collection_archives_v1_vs_archives_v2_drift, source_drift_reconciliation_blocked。

## 不可变授权边界

- `launch_admitted=False`，`worker_launch_authorized=False`。
- `T2_macro=False`，`T2_path=False`，`credit=0`。
- 本 intake 不启动 solver、worker、native、GPU、queue，也不写 registry、ledger、denominator、gate 或 completion。

## 当前仍缺的外部 receipt

- `corrected_archives_v2_collection_and_reader_binding`：present=`False`。all 32 collection rows and the reader receipt must bind the current archives-v2 path and manifest SHA
- `fresh_root_receipt`：present=`False`。
- `scheduler_owned_host_io_reservation`：present=`False`。
- `fresh_dev07_terminal_evidence`：present=`False`。a fresh full 8.68 s terminal sidecar is required; the 4.34 s native diagnostic is not imputed
- `all_32_material_sidecars`：present=`False`。one source-bound, terminal, marker-complete sidecar per fixed case is required

## 32-case sidecar binding

每个 case 都必须以唯一 case_id、固定 split、archives-v2 source path/SHA、fresh namespace、完整 terminal event window 和四类 material marker 绑定；缺失、重复、partial 或 right-censored 都不能形成 T2 credit。

| case | split | sidecar | source path | blockers |
|---|---|---|---|---|
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_00` | `ood_test` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_01` | `ood_test` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_02` | `ood_test` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_03` | `train` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_04` | `train` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_05` | `id_test` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_06` | `train` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_07` | `train` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_08` | `validation` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_09` | `id_test` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_10` | `train` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_11` | `train` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_12` | `train` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_13` | `validation` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_14` | `id_test` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_15` | `train` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_16` | `train` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_17` | `id_test` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_18` | `validation` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_19` | `train` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_20` | `train` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_21` | `train` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_22` | `id_test` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_23` | `validation` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_24` | `train` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_25` | `train` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_26` | `id_test` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_27` | `train` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_28` | `train` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_29` | `ood_test` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_30` | `ood_test` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |
| `F4_resting_pool_laminar_tallwall120_x_v1_DEV_31` | `ood_test` | `missing` | `path_exact=False, sha_exact=True` | missing_or_incomplete_material_sidecar, missing_required_material_markers, source_path_drift |

## 输入边界

- 只读取 reports 下的 bounded JSON，并做 strict JSON、大小、inode、hardlink、symlink 和 TOCTOU 检查。
- production HDF5 仅作为历史 receipt 中的声明存在；本 intake 不跟随路径、不打开、不读取、不重哈希。
- 历史 diagnostic 的短窗口不能被补全或推断为 8.68 s terminal evidence。

