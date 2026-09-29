# F3 graph_residual hidden16 seed17 diagnostic runner v2

- status: `blocked_fail_closed`
- mode: `dry_run`
- source bound: `True`
- admission receipt: `/tmp/residual-admission-8x00b2ro/f3-graph-residual500-hidden16-currentmanifest-seed17-full835-noncef27dc4cc5c7036e734692ec790de41bc/.diagnostic-admission-receipt.json`
- exact contract: graph_residual / hidden16 / seed17 / test / 835 transitions / 836 frames
- default: dry-run; explicit diagnostic execute remains fail-closed
- Popen/wait attempted: `False/False`
- terminal receipt: producer is absent; declarations cannot be promoted
- formal/registry/ledger/denominator/gate/completion/PLAN writes: `0`; credit: `0`

## Blockers

- trusted one-shot receipt consumer is not independently admitted for execution
- source/runtime identity closure is diagnostic-only and has no external scheduler attestation
- GPU UUID/PCI mapping is a scheduler snapshot, not a trusted runtime proof
- sealed real subprocess.Popen/wait witness is not admitted
- stable-FD output lifecycle and independent HDF5 validator capability is not admitted
- terminal receipt minting is forbidden in this runner
- formal/credit promotion is permanently isolated
