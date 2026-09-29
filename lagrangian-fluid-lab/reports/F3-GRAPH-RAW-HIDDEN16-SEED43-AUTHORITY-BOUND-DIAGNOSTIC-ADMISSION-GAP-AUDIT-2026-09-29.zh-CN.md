# F3 graph_raw hidden16 seed43 authority-bound diagnostic admission gap audit

状态：`blocked_fail_closed`。这是 gap artifact，不是 scheduler receipt。

现有 seed43 admission 已覆盖的契约：

- `admission_module_has_no_process_launch_surface`：`covered`
- `caller_self_claim_rejected`：`covered`
- `current_manifest_binding`：`covered`
- `ed25519_signature_verification`：`covered`
- `external_scheduler_authority_input`：`covered`
- `graph_raw_hidden16_seed43_identity`：`covered`
- `namespace_inode_binding`：`covered`
- `nonce_binding`：`covered`
- `one_shot_claim_validation`：`covered`
- `plan_digest_binding`：`covered`
- `resource_digest_binding`：`covered`
- `source_digest_binding`：`covered`
- `zero_credit_diagnostic_boundary`：`covered`

生产 authority 观察（只读 metadata，未打开 manifest/training/checkpoint/trajectory）：

- trusted key available：`False`
- scheduler root available：`False`
- signed authority document available：`False`
- independent one-shot claim available：`False`
- production authority verified：`False`

精确剩余缺口：

- `F3-S43-AUTH-ROOT-001` **生产 scheduler trust root 不可用**：trusted Ed25519 public key 或 external scheduler root 未同时提供；后果：无法把任何 caller-supplied authority document 认证为真实 external scheduler authority。
  - 下一证据：由部署外部安装 owner-only 32-byte Ed25519 public key 与受保护 scheduler root，并提供其 inode/权限证明。
- `F3-S43-AUTH-DOC-002` **真实 signed authority document 未提供**：没有可验证的 seed43 issued one-shot authority document；后果：nonce、namespace inode、plan/source/resource/GPU binding 尚未获得真实 scheduler 签名见证。
  - 下一证据：由 external scheduler 签发当前 manifest seed43 authority，并由 admission 以 Ed25519 验签后留存不可变 digest。
- `F3-S43-AUTH-CLAIM-003` **独立 one-shot consume claim 未提供**：scheduler consume_path 下没有 durable consumed claim witness；后果：不能证明 authority reservation 未被其他 consumer 使用，也不能完成一次性消费闭环。
  - 下一证据：提供与 authority_id、document digest、receipt/identity digest、nonce、namespace descriptor 交叉绑定的外部 claim。
- `F3-S43-AUTH-VERIFY-004` **本次 gap audit 不执行生产 authority 验签**：本审计只读小型 source/test 与 trust-path metadata，不接收或重放生产 authority；后果：synthetic pytest fixture 不能升级为生产 authority；launch 和 credit 必须继续关闭。
  - 下一证据：在真实 scheduler authority、key、namespace、resource snapshot 同时存在后，由受控 admission 重新完成签名/文件/消费验证并生成 terminal evidence。

安全边界：未调用 Popen/solver/worker/GPU/queue，未读取生产大文件，未写 registry、ledger、denominator、gate、completion 或 PLAN；`launch_allowed=false`、`formal=false`、`credit=0`。

pytest synthetic authority fixture 仅证明 fail-closed contract，不构成生产 scheduler authority。
