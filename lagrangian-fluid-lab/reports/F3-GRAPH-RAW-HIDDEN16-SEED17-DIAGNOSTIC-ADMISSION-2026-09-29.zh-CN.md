# F3 graph_raw seed17 diagnostic admission

- status: `blocked_fail_closed`
- admission granted: `False`
- external scheduler authority: required, but no production trust anchor/reservation was supplied
- one-shot consumption: independent scheduler-ledger claim required before local lock/marker
- execute/Popen/wait: not admitted or attempted
- formal state, registry, ledger, gate, completion and PLAN: untouched
- credit: `0`

## Blockers

- local receipt fields and GPU snapshot are not authority;
- owner/host, namespace dev/ino, nonce, plan digest and GPU identity require a scheduler-signed reservation;
- replay protection requires an external claim that survives local namespace deletion/recreation.
