# F3 fresh124: remaining FIRST48 terminal-native -> Root157 typed handoff

This disabled, source-only package binds the seven FIRST48 cases that were still untyped after excluding the accepted/counting set, Root974, and the twelve Root978 cases. Selected cases are:

- P0800: AY0570, AY0640
- P1200: AY0290, AY0500, AY0540, AY0570, AY0640

Each case has a terminal native `completed/0` receipt and a stat-only census of 836 `Part_*.bi4` filenames. The package never opened, copied, or hashed BI4/H5/CSV/DAT/VTK payloads. XML metadata, JSON receipts/requests, Python source, and executable metadata were checked only as declared inputs.

Root948 `actual-progress.json` was read only to select cases and freeze a small routing row inside each native-evidence JSON. It is deliberately absent from every request `input_files` and `input_sha256` map. Each request instead binds the immutable receipt JSON, native request JSON, generated XML, owner scope, converter preflight, and this package's frozen evidence.

Requests use the immutable Root157 worker (`2` CPU threads, 24 GiB private NVMe stage limit, 100 GiB reserve, 4 GiB Home publication cap, 500 GiB Home floor, global conversion cap 2). They remain disabled/source-only with future scientific/typed/XMF/render hashes null. Root must independently revalidate owner scope, current receipt bytes, ledger and storage guards before enabling.

Run metadata-only checks with the integration venv:

```text
/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python scripts/metadata_preflight_batch.py
python3 scripts/validate_fresh124.py
```
