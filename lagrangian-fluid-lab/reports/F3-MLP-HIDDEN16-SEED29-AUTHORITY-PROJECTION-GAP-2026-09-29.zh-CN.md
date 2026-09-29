# F3 MLP hidden16 seed29 authority projection gap

- status: `blocked_projection_gap`
- scope: `mlp / hidden16 / seed29 / test / 500 updates / 835 transitions`
- observed plan: `dry_run_ready`; launched=`False`
- external authority verified: `False`
- resource binding verified: `False`
- launch allowed: `False`
- credit: `0`

## Exact missing requirements

- `authority_ed25519_signature_verification`
- `authority_gpu_uuid_pci_binding`
- `authority_namespace_inode_binding`
- `authority_nonce_binding`
- `authority_plan_sha256_binding`
- `authority_resource_snapshot_binding`
- `authority_source_descriptor_binding`
- `external_scheduler_authority_document`
- `external_scheduler_root`
- `independently_bound_terminal_receipt`
- `seed29_current_authority_bound_admission`
- `trusted_scheduler_ed25519_public_key`

## Blockers

- the current MLP launcher has no external scheduler authority boundary; its nonce, output namespace, and gpu_index are caller-supplied plan fields
- no producer-issued external scheduler authority document was supplied or verified
- authority verification requires a deployment-trusted Ed25519 public key and scheduler root
- a gpu_index is not a scheduler-owned GPU UUID/PCI resource snapshot and cannot satisfy resource binding
- namespace_nonce and output_namespace do not provide a namespace inode descriptor or an independent consume path
- manifest/training/checkpoint hashes in the local plan cannot substitute for signed source descriptors and plan binding
- the seed29 plan is dry-run metadata with no independently bound terminal receipt; local projection cannot make it runner-consumable
- producer-side authority-bound reissue is required before any diagnostic rollout retry

The local nonce, output namespace, gpu_index, manifest digest, and training/checkpoint metadata are not scheduler authority. A future producer-issued document must be verified with the deployment Ed25519 key and bind nonce, namespace inode, plan, source descriptors, resource snapshot, and GPU UUID/PCI identity before a seed29 rollout can be reconsidered.

No Popen/solver/worker/GPU/queue execution occurred; no registry, ledger, denominator, gate, completion, PLAN, or historical receipt was modified.
