# fresh159 — M086 producer-identity adapter (disabled)

This F5-only source package addresses one metadata mismatch: the reusable fresh138 bed worker hard-codes the base case ID `F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1`, while the actual M086 GenCase/native/typed receipts use the producer ID `F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M086_T085_NEXT34`. The adapter changes only the in-memory `case_id`/identity view passed to that unchanged worker. After XMF, it permits only the actual XMF manifest/receipt/XDMF metadata references to be filled. It does not edit the fresh158 binding, any receipt, GenCase/native/typed source, geometry, thresholds, or arrays.

The actual M086 upstream metadata is already `completed/0`, 801 frames, 194427 particles, 3-D, native Mk50/source mkbound40. Canonical scope `89a891b45dae3220aaa64f9b8764645cece3164633fb45fc57c0ad8f51c734f3`, source-definition scope `85d0e0af79ae69aeb83d88a21c4b277e321169167145c74e215d3d246704cb70`, and typed H5 legacy scope `ff41cd47740e7d7532982b004ef761ec97feb4b72cbfc77bcd7b3666df0d72c1` remain separate; the legacy scope has no cross-resolution identity claim. The producer H5 digest is copied only from the existing conversion report and is never opened or rehashed by this source package.

Root materialization order:

1. Review the disabled producer-ID XMF binding and enable the XMF request only after Root fills the normal runtime registration fields. Run the unchanged exporter with `--binding ... --output-dir {attempt_root}/xmf`.
2. Bind the actual XMF manifest/receipt and XDMF paths into the bed binding. Keep the actual typed/native/GenCase/QA JSON/XML metadata and producer hashes unchanged.
3. Enable the disabled bed request only after the XMF gate. Its command is `identity_bound_bed_audit_fresh159.py --binding ... --trajectory-h5 ... --xdmf ... --output-dir ...`. The adapter validates the base binding SHA, exact producer suffix, nested receipt identities, and identity-only plus actual-XMF-metadata field changes, then delegates to the unchanged fresh138 numerical worker.
4. Keep the bed result diagnostic and visual review separate; this package grants no Q-N or case credit. Future XMF/bed/render hashes remain null here.

`M086_T085-identity-bound-xmf-binding.json` and `M086_T085-identity-bound-bed-binding.json` are disabled materializations of fresh158. `scripts/materialize_m086_identity_binding.py` can reproduce the bed identity transformation from the immutable base JSON. `scripts/test_identity_adapter_toy.py` and `scripts/validate_fresh159.py` exercise only JSON/source metadata and synthetic mismatch cases.

M095/Root939 is outside this adapter's physical identity; its terminal typed producer must be bound separately from its authoritative receipt/report when Root integrates fresh158. This package does not copy or hash that science output.
