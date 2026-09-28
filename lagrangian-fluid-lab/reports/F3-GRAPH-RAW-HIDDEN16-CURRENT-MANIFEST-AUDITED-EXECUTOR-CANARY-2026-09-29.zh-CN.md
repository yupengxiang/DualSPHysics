# F3 graph_raw hidden16 current-manifest audited executor/canary

- status: `blocked_fail_closed`
- launch_allowed: `False`
- plan identities: `3/3`
- process proofs: `0/3`; terminal HDF5/artifact capability: `not admitted`
- protocol: `graph_raw`, hidden `16`, updates `500`, case `F3_DEV_00_a0p903125`, split `test`, `835 transitions / 836 frames`
- boundary: bounded JSON/stat-only identity checks, read-only GPU/CPU/I/O admission, diagnostic-only, zero-credit

| seed | GPU | namespace | status |
|---:|---:|---|---|
| 17 | 4 | `/tmp/f3-graph_raw500-hidden16-currentmanifest-seed17-full835-noncec7365ea2f55d8e44f6a05374b4394490` | `blocked_fail_closed` |
| 29 | 5 | `/tmp/f3-graph_raw500-hidden16-currentmanifest-seed29-full835-nonce239d174ddeb00412dc7e1b5fdb338ddd` | `blocked_fail_closed` |
| 43 | 6 | `/tmp/f3-graph_raw500-hidden16-currentmanifest-seed43-full835-nonce1174159e662529817d6da02d1d4ae8c7` | `blocked_fail_closed` |

## Blockers

- core.f3.graph_raw.hidden16.current_manifest.terminal_hdf5_artifact_capability.v1 is not implemented/admitted
- no evaluator was started and no synthetic terminal/process receipt was minted
