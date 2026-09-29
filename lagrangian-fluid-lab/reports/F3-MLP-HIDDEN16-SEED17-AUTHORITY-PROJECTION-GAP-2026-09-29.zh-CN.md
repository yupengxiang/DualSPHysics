# F3 MLP hidden16 seed17 authority projection gap

- 状态：`blocked_projection_gap`
- 范围：`mlp/hidden16/seed17/test/500 updates/835 transitions/836 frames`
- 外部 scheduler authority：`verified=False`；签名算法要求 `Ed25519`
- scheduler-owned resource/GPU binding：`False/False`
- producer/local nonce：`True`；namespace：`True`（二者不等于 authority）
- safe local projection：`False`；producer reissue required：`True`
- credit：`0`

## 缺失准入条件

- `authority_bound_consume_once_path`
- `authority_bound_gpu_identity`
- `authority_bound_plan_sha256`
- `authority_bound_resource_snapshot`
- `authority_bound_source_descriptors`
- `current_mlp_seed17_authority_bound_admission_receipt`
- `external_scheduler_authority_document`
- `independent_terminal_receipt_with_authority_binding`
- `scheduler_owned_resource_snapshot.gpu_uuid_pci_vram`
- `trusted_scheduler_ed25519_public_key`

## 阻塞原因

- no real external scheduler authority document was supplied or verified
- no deployment-trusted Ed25519 public key or configured scheduler root is available for this MLP seed17 boundary
- the current nonce and namespace are producer/local declarations; they are not scheduler authority or namespace-inode attestation
- the rollout plan GPU index and local artifact hashes are not a scheduler-owned resource snapshot or GPU identity proof
- local JSON fields cannot reconstruct the missing plan/source/resource/consume-once bindings
- producer-issued current-schema authority-bound admission receipt and independently bound terminal receipt are required before any runner retry

本报告只记录 MLP seed17 的 bounded projection gap；不把本地 GPU index、nonce、namespace、artifact hash 或历史 JSON 字段升级为 scheduler authority。

本轮未启动 Popen/solver/worker/GPU/queue，未读取 checkpoint、evaluation、trajectory/HDF5 内容，未写入 registry、ledger、denominator、gate、completion 或历史 receipt。
