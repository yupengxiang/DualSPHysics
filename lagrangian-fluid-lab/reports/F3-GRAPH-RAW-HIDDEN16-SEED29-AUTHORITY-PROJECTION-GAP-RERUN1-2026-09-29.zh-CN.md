# F3 graph_raw hidden16 seed29 authority projection gap

- status: `blocked_projection_gap`
- scope: `graph_raw / hidden16 / seed29 / test / 500 updates / 835 transitions / 836 frames`
- current admission source-bound: `False`
- external authority verified: `False`
- resource binding verified: `False`
- terminal receipt present: `False`
- safe local projection: `False`
- credit: `0`

## Exact missing requirements

- `current_authority_bound_receipt`
- `external_scheduler_authority_document`
- `external_scheduler_root`
- `independently_bound_terminal_receipt`
- `receipt.identity.external_authority`
- `receipt.identity.namespace_descriptor`
- `receipt.identity.nonce`
- `receipt.identity.plan_sha256`
- `receipt.identity.resource_snapshot`
- `receipt.identity.source_sha256`
- `scheduler_owned_resource_snapshot.gpu_uuid_pci`
- `trusted_scheduler_ed25519_public_key`

## Blockers

- no producer-issued external scheduler authority document was supplied or verified
- authority verification requires a deployment-trusted Ed25519 public key and scheduler root
- nonce, namespace inode, plan, source descriptors, resource snapshot, and GPU identity cannot be reconstructed locally
- seed29 admission report is not source-bound because the scheduler-owned GPU UUID/PCI snapshot is absent
- seed29 runner requires an explicit authority-bound admission receipt and has no independent terminal receipt
- producer-issued current-schema receipt/reissue is required before any runner retry
- observed admission report: fail-closed: scheduler-owned GPU UUID/PCI snapshot is required; implicit probing is disabled

This seed29-only inventory does not mint or project authority. A future producer-issued receipt must carry a real external scheduler signature and exact nonce, namespace, source, plan, resource, and GPU bindings before the runner can be reconsidered.

No Popen/solver/worker/GPU/queue execution occurred; no PLAN, registry, ledger, denominator, gate, completion, or historical receipt was modified.
