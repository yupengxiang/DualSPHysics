# F3 graph_raw hidden16 terminal execution bridge

- status: `blocked_fail_closed`
- mode: `dry_run`
- launch_allowed: `False`
- fresh identity plans: `3/3`
- Popen attempts/waits: `0/0`; process evidence: `0`; terminal evidence: `0`
- terminal validator: existing v1 is synthetic-only and not execution authority
- formal/credit: `false/0`

## Safety boundary

- default dry-run; explicit execute is rejected before Popen
- no existing job is stopped or restarted
- no registry, ledger, denominator, gate, completion, or PLAN writes

## Blockers

- default mode is dry-run and does not attempt Popen
- existing terminal_artifact_validator_v1 is synthetic-only and cannot validate production evaluator artifacts
- no process or terminal evidence was minted
- production HDF5 validator capability is not admitted
