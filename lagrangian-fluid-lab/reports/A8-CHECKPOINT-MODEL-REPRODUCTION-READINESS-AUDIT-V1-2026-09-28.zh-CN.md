# A8 checkpoint/model reproduction readiness bounded audit V1

- 状态：blocked_missing_trusted_checkpoint_binding
- 结论：passed=false；本回执不是 independent reproduction、T1/T2、formal training 或 credit 证据。

## 比较对象

- 当前包：core.reader_bundle.v2，checkpoint_count=0，model support=False。
- 历史包：core.reader_bundle.v1，checkpoint_count=1；历史 registry 身份不会转移成当前绑定。
- dataset raw SHA 相同：False；相对路径相同：False。
- 当前模型身份已绑定：False。
- 本边界未接收 trusted root、distinct physical host、reader 或 scoring receipt；metadata-only claim 不被接受为 readiness。

## 关键阻塞

- checkpoint_content_hash_not_verified_by_this_boundary
- code_identity_sha_mismatch_common_paths:10
- current_bundle.model_entrypoint_checkpoint_missing:models/checkpoint-000.pt:FileNotFoundError
- current_bundle_model_entrypoint_checkpoint_unregistered:models/checkpoint-000.pt
- current_checkpoint_count_zero
- current_model_entrypoint_has_no_trusted_registry_row:models/checkpoint-000.pt
- current_trusted_checkpoint_binding_missing
- dataset_source_raw_sha_mismatch_current_vs_historical
- distinct_data_root_receipt_not_supplied_to_this_boundary
- distinct_physical_host_receipt_not_supplied_to_this_boundary
- historical_bundle_absolute_reused_from:65
- historical_bundle_schema_legacy_or_different:'core.reader_bundle.v1'
- historical_checkpoint_provenance_absolute_checkpoint_source_path
- historical_checkpoint_provenance_absolute_dataset_source_path
- historical_checkpoint_provenance_checkpoint_source_path_not_authoritative
- historical_checkpoint_provenance_is_diagnostic_only
- historical_portable_package_has_absolute_reused_from_paths
- independent_reproduction_requires_fresh_current_v2_binding_and_distinct_host_receipt
- reader_reproduction_lineage_not_supplied_to_this_boundary
- scoring_lineage_not_supplied_to_this_boundary
- trusted_root_review_not_supplied_to_this_boundary

## 下一步需要的 trusted checkpoint binding

1. 为当前 v2 bundle 提供 bounded checkpoints.json，逐项绑定 model_kind、seed、update、规范化相对路径与 SHA-256 claim。
2. 将 checkpoint registry 行、bundle artifact row、lstat/bytes、训练 receipt、model/config identity 和 formal/diagnostic 状态由可信生产者闭合；本审计不验证 checkpoint 内容。
3. 清除 portable package 中的绝对 source/reuse 路径，并在 distinct host 上生成新的 independent reproduction receipt。

## 读取边界

仅读取有界 strict JSON；所有 checkpoint、HDF5、NPZ、source/model bytes 均未打开或重哈希，只做 lstat。未训练、rollout、占用 GPU、启动 solver/worker/queue，也未修改 registry、ledger、denominator、gate 或 completion。
