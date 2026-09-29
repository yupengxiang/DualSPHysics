# F3 graph_raw seed17 diagnostic runner v2

- status: `dry_run_ready`
- mode: `dry_run`
- source bound: `True`
- admission receipt: `/tmp/f3-graph_raw500-hidden16-currentmanifest-seed17-full835-nonce1234567890abcdef1234567890abcdef/.diagnostic-admission-receipt.json`
- exact contract: graph_raw / hidden16 / seed17 / test / 835 transitions / 836 frames
- execution gate: only `--diagnostic-execute`; no `--execute` alias
- Popen/wait attempted: `False/False`
- validator: hardened descriptor/HDF5 boundary plus independent F3 HDF5 validator
- formal/registry/ledger/denominator/gate/completion/PLAN writes: `0`; credit: `0`

## Blockers

- real Popen/wait is reachable only through --diagnostic-execute
