# F1R evidence audit

- status: `complete_with_findings`
- new GPU jobs: `0`
- native PartOut join: `85/85`
- native reasons: `{'position': 85}`
- runtime-domain ceiling match: `85`
- H1: `supported_but_unconfirmed`; repair: `implemented_not_run`

## Evidence decision

The retained canary is not promoted. Missing identities remain a closed-lifecycle failure even though inactive padding is allowed to be non-finite.

## Blocking evidence

- `plain_release`: **blocked_initial_artifact_only** — only GenCase input/initial-state evidence exists; no solver trajectory/reference result is present
- `center_obstacle`: **blocked_single_canary_not_reference_matrix** — one nominal canary exists, but the required two-background by three-resolution matrix is absent
- `F1-EXT-3D-DAMBREAK`: **blocked_external** — matched actual three-dimensional dam-break experiment assets

## Next GPU step

Run one H1 repair canary on an explicitly allowlisted idle GPU, then rejoin PartOut/HDF5 evidence before any matrix launch. H2 is conditional and remains unrun.
