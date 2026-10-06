# F3 fresh123: terminal native -> typed157 batch handoff

This is a disabled, source-only handoff for twelve distinct F3 FIRST48 pitch/AY
conditions whose full836 native receipts were already terminal `completed/0`.
It contains metadata-only owner scope closures and one disabled Root157 typed
request per case. It grants no visual, Q-N, qualification, or production credit.

The selected cases are the seven Root884 terminal cases
`P0800_AY0290/0320/0390/0430/0460/0500/0540` and five Root948 terminal cases
`P1200_AY0320/0360/0390/0430/0460`. Root974 `P0800_AY0360` is explicitly
excluded because it was the running case when this package was built. The
completed but deferred cases `P0800_AY0570`, `P0800_AY0640`, `P1200_AY0500`, and
`P1200_AY0540` remain listed in `metadata/candidate-index.json` for a later
batch. Existing visual/accepted cases are also listed there and are not
re-counted.

Every request is bound to its own actual native receipt, actual native request,
836 saved-frame metadata, and stat-only `Part_*.bi4` filename count. The owner
uses the explicit `ds-data-02.physical-binding.v1` scope and preserves the
producer-attested 3-D counts (179208 total, 111708 fixed, 67500 fluid). The
Root157 worker, converter scope, Root142 inventory policy, 2 CPU threads, 4 GiB
Home publication cap, 500 GiB Home floor, 24 GiB private NVMe stage limit,
100 GiB NVMe reserve, and global conversion cap 2 are recorded for Root's own
runtime revalidation.

`input_files` contains only current JSON/XML/Python/metadata/executable inputs;
its absolute paths and hashes are checked by `scripts/validate_fresh123.py`.
Future solver data, CSV/BI4 inputs, H5, typed receipts, XMF, and render outputs
remain outside that map with null future hashes. No science payload was opened,
hashed, copied, or launched by this source package. Fresh118/121/122 bytes are
immutable and fresh118 is absent from every new request input map.

Run the checks with the integration venv, whose NumPy/HDF5 environment matches
the production converter:

```text
/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python scripts/metadata_preflight_batch.py
python3 scripts/validate_fresh123.py
```

The preflight imports only the converter's metadata functions and does not open
solver data. The validator hashes only the declared non-science input files,
reads JSON metadata/receipts, and never scans or decodes scientific payloads.
Both outputs are review reports under `metadata/` and are not runtime requests.
Root must independently revalidate current receipts, owner scope, resource
ledger, storage floor, and the disabled flag before enabling any request.
