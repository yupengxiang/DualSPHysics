# F4 fresh099: Root533 typed JSON to Root023 render handoff

This F4-local package polls the Root533 JSON execution receipts and
`conversion-report.json` files, then prepares one disabled Root023 full-frame
render request per case. It is rerunnable: a later invocation refreshes JSON
state and preserves the same Root533 and Root547 attempt identities.

The report summary records the observed 1201-frame/3-D contract, time range,
N3 velocity contract, Mk/Type/UID identity axis, and the report's fluid
lifecycle omissions. `first_missing_frame_by_mk`,
`first_missing_frame_by_type`, transient omission counts, and the initial
exclusion ledger are copied as evidence. The builder does not add particles,
change a type, rescale mass, or turn an omission into a failure.

Root547 XMF requests and bindings are used when Root has registered them; the
fresh098 disabled request and binding remain recorded as immutable provenance
for every case. Root547 output receipts and manifests are only polled as JSON.
The fresh099 render request points to the actual Root547 manifest when one is
available, otherwise to the fresh098 expected path and remains `WAIT`.

All fresh099 render requests have `disabled: true`, `execution_allowed: false`,
`launch: false`, and `launch_allowed: false`. They do not relaunch typed
conversion or XMF export. Future typed, XMF, and render product hashes are
explicitly `null`; the source builder never recomputes an H5 digest.

The source boundary is enforced in `build_fresh099.py`: JSON/XML/Python
metadata may be read or hashed, while BI4/H5/VTK/CSV/DAT payload reads and
hashes raise immediately. No jobs, arrays, shared registry, or ledger are
modified by this package.

To refresh the handoff after Root changes JSON state, run:

```text
python3 build_fresh099.py
python3 tests/validate_fresh099_source_contract.py
```

The package carries no visual acceptance, precision, Q-N, or production claim.
