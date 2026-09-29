# F3 graph_residual hidden16 seed43 diagnostic admission

- status: `blocked_fail_closed`
- source bound: `False`
- receipt: `None`
- admission: external scheduler signature + independent one-shot claim required
- execution: no Popen/wait path is admitted; terminal receipts are not minted
- GPU: physical GPU6 / logical cuda:0 is a snapshot binding only, never live evidence
- formal/registry/ledger/denominator/gate/completion/PLAN writes: `0`; credit: `0`

## Blockers

- fail-closed: scheduler-owned GPU UUID/PCI snapshot is required; implicit probing is disabled
