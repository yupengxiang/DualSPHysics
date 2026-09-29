# F3 graph_raw seed17 diagnostic runner v2

- status: `blocked_fail_closed`
- mode: `dry_run`
- source bound: `True`
- admission receipt: `/tmp/f3-graph_raw500-hidden16-currentmanifest-seed17-full835-nonce1234567890abcdef1234567890abcdef/.diagnostic-admission-receipt.json`
- exact contract: graph_raw / hidden16 / seed17 / test / 835 transitions / 836 frames
- execution gate: only `--diagnostic-execute`; no `--execute` alias
- Popen/wait attempted: `False/False`
- validator: hardened descriptor/HDF5 boundary plus independent F3 HDF5 validator
- formal/registry/ledger/denominator/gate/completion/PLAN writes: `0`; credit: `0`

## Blockers

- default dry-run performs no execution
- P1 replay/one-shot capability is not independently sealed across consumers
- P1 path and artifact TOCTOU closure is not independently attested for this runner
- P1 HDF5 external/soft/VDS link closure is not granted as an execution authority
- P1 physical GPU2 UUID mapping is not externally attested
- P1 sealed real subprocess.Popen/wait witness is not independently granted
- P1 complete environment identity is not externally sealed at scheduler admission
- P1 formal isolation is diagnostic-only and has no independent scheduler attestation
- P1 terminal artifact identity closure is not authorized for a production execution
