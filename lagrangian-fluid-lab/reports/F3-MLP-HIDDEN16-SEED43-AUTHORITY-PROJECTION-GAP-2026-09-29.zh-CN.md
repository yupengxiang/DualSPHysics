# F3 MLP hidden16 seed43 authority projection gap

状态：`blocked_fail_closed`；这是 bounded gap artifact，不是 scheduler authority receipt。

范围：MLP / hidden16 / seed43 / current-manifest / test / 500 updates / 835 transitions / 836 frames。

现有本地契约观察：

- `authority_gate_before_execute`：`False`
- `current_manifest_identity_binding`：`True`
- `diagnostic_zero_credit_boundary`：`True`
- `ed25519_signature_verification`：`False`
- `external_scheduler_authority_contract`：`False`
- `local_namespace_binding`：`True`
- `local_nonce_binding`：`True`
- `local_source_digest_binding`：`True`
- `one_shot_external_consume_witness`：`False`
- `scheduler_owned_gpu_uuid_pci_binding`：`False`
- `seed43_parameter_binding`：`True`

外部 authority 观察（仅 metadata，未打开 manifest/training/checkpoint/trajectory/HDF5）：

- trusted Ed25519 key available：`False`
- scheduler root available：`False`
- signed authority document available：`False`
- one-shot consume claim available：`False`
- production authority verified：`False`

精确缺口：

- `F3-MLP43-AUTH-ROOT-001` **MLP seed43 scheduler trust root unavailable**：a deployment-owned Ed25519 public key and external scheduler root are not both present；后果：no caller-supplied authority can be authenticated as a real scheduler authority。
  - 下一证据：install the owner-controlled 32-byte Ed25519 public key and protected scheduler root, then provide metadata/permission evidence。
- `F3-MLP43-AUTH-DOC-002` **signed external authority document unavailable**：no current-manifest MLP seed43 one-shot authority document is available under the configured root；后果：nonce, namespace inode, source/plan/resource and GPU identity bindings have no external scheduler witness。
  - 下一证据：obtain a scheduler-issued authority document and validate its Ed25519 signature against the deployment key。
- `F3-MLP43-AUTH-CLAIM-003` **one-shot consume claim unavailable**：no durable scheduler consume-path claim is available；后果：the reservation cannot be shown to be unused by another consumer。
  - 下一证据：obtain an external claim bound to authority id, document digest, receipt identity, nonce and namespace descriptor。
- `F3-MLP43-AUTH-IMPL-004` **current MLP launcher has no external-authority admission gate**：the current-manifest launcher accepts a local plan and exposes --execute without an external authority envelope；后果：a local nonce/namespace/GPU-index plan cannot authorize diagnostic execution or be promoted to Core evidence。
  - 下一证据：add a producer-issued, fail-closed seed43 admission boundary before any retry; do not widen the existing launcher locally。
- `F3-MLP43-AUTH-RESOURCE-005` **scheduler-owned GPU identity binding unavailable**：the MLP plan contains a local GPU index but no scheduler-owned UUID/PCI snapshot binding；后果：GPU index availability cannot prove that the reserved physical resource is the one used by the evaluator。
  - 下一证据：obtain a scheduler-owned resource snapshot bound by digest to the authority, nonce, namespace and command plan。
- `F3-MLP43-AUTH-VERIFY-006` **this gap audit does not verify production authority**：the audit reads only bounded source files and trust-path metadata; it does not consume or replay authority documents；后果：synthetic fixtures or present filenames cannot promote launch, terminal status or Core credit。
  - 下一证据：after all external evidence exists, a dedicated admission verifier must perform signature, nonce, namespace, source, resource and one-shot checks。

安全边界：未调用 Popen/solver/worker/GPU/queue，未打开生产大文件，未写 registry、ledger、denominator、gate、completion 或 PLAN；`launch_allowed=false`、`formal=false`、`credit=0`。

现有 current-manifest terminal/training reports 即使存在，也不能替代外部 scheduler authority 或产生 Core credit。
