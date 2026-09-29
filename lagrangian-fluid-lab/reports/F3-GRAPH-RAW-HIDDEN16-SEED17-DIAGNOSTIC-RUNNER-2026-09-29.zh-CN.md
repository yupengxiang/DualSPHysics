# F3 graph_raw seed17 diagnostic runner

- status: `dry_run_ready`
- mode: `dry_run`
- source bound: `True`
- GPU admission: `admitted`
- namespace reserved: `/tmp/f3-graph_raw500-hidden16-currentmanifest-seed17-full835-nonce1f13fb3d52631d9f1cf1b526a5842165`
- exact contract: graph_raw / hidden16 / seed17 / test / 835 transitions / 836 frames
- command: `core_learning.py evaluate ... --diagnostic`, env `CUDA_VISIBLE_DEVICES=2`
- real workload started: `0`; Popen/wait attempted: `0/0`; credit: `0`
- independent HDF5 validator and hardened artifact capability: not admitted

## Blockers

- diagnostic execute capability is not admitted
- independent terminal HDF5/artifact execution authority is not installed
- zero-credit diagnostic receipts require real Popen/wait and are not self-authorized
