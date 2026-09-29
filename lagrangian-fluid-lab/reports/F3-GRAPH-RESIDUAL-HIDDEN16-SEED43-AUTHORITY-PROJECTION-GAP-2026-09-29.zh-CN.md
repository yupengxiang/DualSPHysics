# F3 graph_residual hidden16 seed43 authority projection gap

- status: `blocked_projection_gap`
- source observed: `False`
- source receipt: `/tmp/f3-graph_residual500-hidden16-currentmanifest-seed43-full835-authority-bound/.diagnostic-admission-receipt.json`
- external authority verified: `False`
- runner consumable: `False`
- Popen allowed: `False`
- credit: `0`

## Boundary

Only a real external scheduler document with Ed25519, nonce, namespace, source and resource bindings can pass this projection. The result is in-memory, diagnostic-only and zero-credit.

## Blockers

- fail-closed: source admission receipt parent has a missing component: /tmp/f3-graph_residual500-hidden16-currentmanifest-seed43-full835-authority-bound
- producer-issued current-schema receipt is required
- projection-gap: source admission receipt is unavailable or unreadable

No Popen, solver, worker, GPU or queue execution occurs; no historical receipt or Core state is written.
