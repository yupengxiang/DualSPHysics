# F3 fresh076 recovery-aware audits and pending typed handoff

fresh076 is a source-only package. It binds the actual Root184 settlements for
P03 and AY0270, prepares two independent strict CPU artifact audits, carries
fourteen completed native full836 cases into disabled typed-conversion requests,
and binds Root154 AY0290/AY0300 typed outputs to disabled normal-XMF and
Root023 full836 renderer requests.

Root184 facts are immutable provenance: P03 is charged 10,800 CPU core-seconds
and AY0270 21,600, both conservatively charged as `interrupted_unfinalized`.
The original conversion receipts remain `status: running`, `returncode: null`;
tool status 143 and child returncode null remain separate facts. The settlement
sidecars and journals are referenced by SHA; this package does not apply or
rewrite a ledger or receipt.

`requests/p03_artifact_integrity_request.json` and
`requests/ay0270_artifact_integrity_request.json` are `cpu_task_kind: audit`
requests. Root's strict worker may hash each published H5 as opaque bytes and
validate report/native provenance. The worker output is a new audit fact with
future SHA null. It cannot turn the old converter into completed/0 or increment
case count. The source agent did not read H5, BI4, CSV, or numerical arrays.

`requests/pending_native_typed_bindings.json` indexes fourteen concrete disabled
CPU conversion requests under `requests/pending_typed/`, each with CPU 2,
NVMe staging cap 24 GiB, free-space floor 100 GiB, and conversion concurrency
cap 2. Their exact native command, geometry/forcing/XML/BI4 registered hashes,
particle counts, native mass, genuine GenCase receipt, and owner metadata come
from the completed native receipt. Typed outputs remain null and no new
physics, GenCase, solver, or visual approval is introduced.

`requests/actual_typed_ay0290_ay0300_xmf_render_bindings.json` carries the two
new Root154 actual typed full836 outputs. Their H5 SHA values are copied from
the immutable conversion reports supplied by Root; this source package does
not rehash H5. Normal XMF export and the Root023 automatic-native-bounds
renderer are both disabled until Root runs and binds their own completed/0
receipts, manifests, case.xmf, and render outputs. The render contract covers
all 836 frames (35 contact pages at capacity 24), retains native fields, and
forbids fixed camera bounds.

Run the bounded semantic checks:

```text
python3 -B tests/test_fresh076_artifact_contract.py
```

No solver, converter, XMF exporter, renderer, HDF5 decode, array read, ledger
write, shared-index write, or GPU action is performed by this package.
