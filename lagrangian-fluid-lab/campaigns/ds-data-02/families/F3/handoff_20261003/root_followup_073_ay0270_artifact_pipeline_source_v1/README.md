# F3 fresh073 AY0270 published-artifact audit and post-audit pipeline

fresh073 is a disabled source package for an independent strict CPU audit of
the already published AY0270 typed output:

- 836 saved frames and 179208 particles;
- physical case `F3_TWOAXIS_PITCH1000_AY0270_STAGE1_FIRST24_NEW`;
- canonical native receipt completed/0, actual 3D, 179208 total / 67500 fluid / 111708 fixed;
- published report output SHA `6faac15de658d415b2663099ce26c1d6c10a0e24dce4a45530b4e61ffa9cdad3`.

The original typed conversion receipt remains `status: running` with
`returncode: null`; launcher status 143 is carried separately.  The audit
worker creates a new receipt with its own returncode 0 only after Root’s strict
CPU runner checks the small receipts/report/stdout and hashes the opaque HDF5
in bounded chunks.  It never edits the source receipt, settles a reservation,
or reclassifies the converter as completed/0.  The source agent did not read or
hash the HDF5, BI4, CSV, or numerical arrays.  The request omits a source HDF5
`input_sha256` entry intentionally; its expected report hash is metadata and
must be verified by the Root worker.

`artifact_integrity_worker.py` is generalized from the fresh072 P03 worker. It
also checks the canonical completed native receipt, expected frames/particles,
canonical physical ID/condition, the report’s internal physical-condition hash,
PartVTK all-passed metadata, stdout output hash, and report-to-HDF5 path
closure.  Its result explicitly preserves `source_receipt_returncode: null`,
`source_conversion_reclassified: false`, `arrays_decoded: false`, and
`independent_case_count_increment: 0`.

`recovery_aware_pipeline_gate.py` is a JSON-only lifecycle gate for the three
prepared disabled templates. It accepts a source receipt in either
`running/null` or Root-settled `interrupted_unfinalized/null` state only when
the independent audit is completed/0 and the canonical native receipt is
completed/0. It rejects a source receipt completed/0. The normal temporal XDMF
exporter, recovered export reference, and native renderer are all bound with
direct invocation disabled because their historical entry points assert a
completed typed receipt. A reviewed lifecycle-aware adapter must consume the
gate output; no old receipt is rewritten to satisfy those assertions.

The concrete disabled inputs are:

- `requests/ay0270_artifact_integrity_request.json` (Root172 strict CPU audit);
- `requests/post_audit_case_bindings.json` (P03 and AY0270 metadata);
- `requests/post_audit_normal_prepared_disabled.json`;
- `requests/post_audit_export_prepared_disabled.json`;
- `requests/post_audit_render_prepared_disabled.json`.

Run the bounded synthetic checks with:

```text
python3 -B tests/test_fresh073_artifact_contract.py
```

No production job, HDF5 decode, array read, ledger write, shared-index write,
or GPU action is performed by this package.
