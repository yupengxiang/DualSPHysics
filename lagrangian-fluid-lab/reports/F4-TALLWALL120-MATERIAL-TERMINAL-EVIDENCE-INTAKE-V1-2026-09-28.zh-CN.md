# F4 Tallwall120 material terminal evidence intake V1

- 状态：`blocked_fail_closed`
- schema：`core.material.f4.tallwall120.terminal_evidence_intake.v1`
- target：`F4_resting_pool_laminar_tallwall120_x_v1_DEV_07`
- source trajectory SHA-256：`6ae8ca7062e1fa15779fc9ad491d1117455700315c6a1ef4a12326458f0976ae`

## 合同边界

本 intake 只读取有界 JSON 和文件系统元数据；不打开或重哈希目标 HDF5，不启动、停止或重启 solver/worker/GPU/queue，也不修改 PLAN、registry、ledger、分母或 gate。

固定配置为 `q=0.23437500000000008`、`dp_m=0.0075`、`512 seeds`、`substeps=2`、`baseline24`；必须保留至少 `218 frames / 217 transitions`，并完整达到 `8.68 s` event window。

## 当前证据

- fresh terminal sidecar：`missing`；阻塞：`missing_fresh_terminal_evidence`
- 已有 diagnostic：event window=`right_censored_or_unresolved`，unknown=`1.0`，common reliable coverage=`0.0`；仅为 negative provenance。
- collection 的 DEV_07 行仍声明 archives-v1，而 proposal target 是 archives-v2；reader smoke 的 manifest SHA 也已漂移，trusted reader formal gate 保持关闭。

## Qualification boundary

`diagnostic_only=True`、`formal=False`、`T1=False`、`T2=False`、`qualification=False`、`credit=0`。

## 阻塞

- `fresh_terminal_evidence_missing_at_planned_output_namespace`
- `terminal_evidence_intake_is_not_an_execution_authorization`
- `current_dev07_material_diagnostic_is_right_censored_or_unresolved`
- `current_dev07_material_diagnostic_unknown_fraction_is_1.0`
- `current_dev07_material_diagnostic_common_reliable_path_coverage_is_0.0`
- `historical_material_diagnostic_is_not_a_fresh_attempt_and_must_not_be_reused`
- `collection_manifest_archives_v1_vs_proposal_archives_v2_path_drift`
- `reader_smoke_manifest_sha_is_stale_against_current_collection`
- `reader_trusted_formal_gate_is_closed`
- `fresh_root_resource_runtime_authorization_is_absent`
- `known_material_diagnostic_event_window_is_incomplete`
- `missing_fresh_terminal_evidence`
- `collection_case_archives_v1_path_does_not_match_archives_v2_target`
- `reader_smoke_manifest_sha_does_not_match_current_collection`
- `historical_diagnostic_material_config_drifts_from_fresh_proposal`

下一安全动作是取得新的 root/resource/runtime authorization，在固定 fresh namespace 中产生完整 terminal sidecar；在此之前不得把历史 `/tmp` trace、native source event flag 或 reader manifest 声明提升为 material T2。
