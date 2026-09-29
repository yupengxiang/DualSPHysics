# F3 graph_residual hidden16 seed43 diagnostic runner v2

- status: `blocked_fail_closed`
- mode: `dry_run`
- source bound: `False`
- admission receipt: `None`
- exact contract: graph_residual / hidden16 / seed43 / test / 835 transitions / 836 frames
- default and explicit diagnostic execution remain fail-closed; no Popen/wait is attempted
- terminal receipt producer is absent; GPU6 is a scheduler snapshot only
- formal/Core registry/ledger/denominator/gate/PLAN writes: `0`; credit: `0`

## Blockers

- --admission-receipt is required; no implicit admission is minted
- trusted one-shot runtime consumer is not independently admitted for execution
- descriptor-bound child output publication is not available for the current evaluator
- GPU6 UUID/PCI mapping is a scheduler snapshot, not live GPU evidence
- sealed real subprocess.Popen/wait witness is not admitted
- independent HDF5 terminal validator capability is not admitted
- terminal receipt minting is forbidden in this runner
- formal/Core registry, ledger, denominator, gate and PLAN promotion is isolated
