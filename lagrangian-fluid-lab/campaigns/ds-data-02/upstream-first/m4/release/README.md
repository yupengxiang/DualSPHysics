# M4 receipt-gated release card

`m4_release.py` assembles a candidate data card for the four distinct F1
initial-depth conditions:

* `UF_F1_MDBC_DP010_H050` (`0.50 m`)
* `UF_F1_MDBC_DP010_H052` (`0.52 m`)
* `UF_F1_MDBC_DP010_H058` (`0.58 m`)
* `UF_F1_MDBC_DP010_H060` (`0.60 m`)

The input is a new JSON document with schema
`ds-data-02.m4.release-input.v1`. It must contain those four rows and a
separate `mother_reference` object. Each actual row may use this shape:

```json
{
  "case_id": "UF_F1_MDBC_DP010_H050",
  "depth_m": 0.5,
  "direct_conversion": {
    "receipt": "/data/nas/.../m4-direct-conversion-001/execution-receipt.json",
    "report": "/data/nas/.../m4-direct-conversion-001/direct-conversion-report.json"
  },
  "enrichment": {
    "receipt": "/data/nas/.../m4-enrichment-001/product/enrichment-receipt.json",
    "execution_receipt": "/data/nas/.../m4-enrichment-001/execution-receipt.json"
  },
  "portable_build": {
    "execution_receipt": "/data/nas/.../m4-portable-build-001/execution-receipt.json",
    "bundle_root": "/data/nas/.../m4-portable-build-001/bundle"
  },
  "actual_validation": {
    "receipt": "/data/nas/.../m4-actual-validation-001/actual-validation-receipt.json"
  },
  "cost_reconciliation": "/data/nas/.../completed-cost-reconciliation.json"
}
```

Rows whose actual paths do not exist remain `pending_actual_receipts`; they
are included in the four-row development candidate list with
`credit_status: not_credited`. The assembler does not fill in future hashes
or claim that a prepared GenCase/solver condition is an M4 product. A final
root-reviewed card should be written with `--require-complete`, which returns
nonzero unless every row has a completed direct conversion, enrichment,
portable build, positive isolated relocation replay, and both actual
rehashed semantic negatives. If a row supplies `cost_reconciliation`, that
receipt must use schema
`ds02.upstream-first.external-storage-reconciliation.v1`, identify the same
case, use the deterministic first-copy charge ID
`F1/<CASE>/m4-actual-validation-001::external-nas-copy-delta`, bind the actual
validation receipt by path/bytes/hash, and reconcile a positive byte delta to
`relocation.bytes`. The receipt hash is retained in the row's lineage. The
relocation destination is always taken from the completed actual-validation
receipt, so an independent NAS attempt root can be bound even when the
runner's preparation path differs.

Example command:

```sh
/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python \
  m4_release.py \
  --input /data/nas/.../m4-release-input.json \
  --output /data/nas/.../m4-release-card.json \
  --require-complete
```

The output schema is `ds-data-02.m4.release.v1`. It records all normalized
root fields, the `(Zone,Idp)` identity axis, native exclusion semantics,
endpoint labels and unknown/censored policy, geometry/control sidecars,
reader/evaluator/runtime bindings, physical-condition and generated-XML/owner
hash lineage, and source plus independently relocated bundle manifests. The
validation partition is always empty. The official mother is recorded in a
separate reference-only object and receives no held-out or physical-condition
credit. Q-N, Q-E, convergence, physical fate, and held-out validation claims
are explicitly false.

This is a metadata-only assembler. It hashes JSON/XML/code artifacts and uses
`stat` for declared HDF5 sizes, but never opens, hashes, or scans any HDF5;
full scientific validation belongs to the producing worker and actual
relocation runner.
