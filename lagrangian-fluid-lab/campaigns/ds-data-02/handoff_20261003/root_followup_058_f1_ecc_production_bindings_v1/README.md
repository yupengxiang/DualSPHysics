# F1 ECC Stage 1 source-only production bindings

This package binds the Root062 four-row F1 ECC visual domain:

- observed `F1_STAGE1_ECC_H110_DP010`, historical mother `F1_FALLBACK_ECC_COARSE`, and observed `F1_STAGE1_ECC_H190_DP010`;
- prospective genuine `F1_STAGE1_ECC_H130_DP010`.

The builder reads bounded Root062, GenCase027, prepared-input, QA031, and H110 native032 metadata, then hashes the referenced files. It does not launch GenCase, DualSPHysics, conversion, ParaView, or any new job. Every generated fixture and request has `execution_allowed=false`; the fixture index is not the shared approval index.

The H130 solver recipe is copied from the actual H110 native032 receipt. Only the genuine H130 prefix and `{attempt_root}/solver_output` are substituted. The command keeps the receipt's exact options `-tmax:1.6 -tout:0.01`; there is no added mDBC command-line option. The receipt's `Boundary=1`, `dp=0.01`, 161-frame window, and `mDBC no-slip` runtime feature record are retained as bounded metadata.

H130 identity is bound to the actual GenCase027 and QA031 values `total=136276`, `fluid=34840`, actual 3-D, and the generated XML/BI4 hashes. The package records the continuum reference mass `34.84 kg` only as the Root062 physical reference. It never asserts a native particle weight or native mass difference. `F1_ECC_H130_STRICT_CPU_AUDIT_REQUEST.json` is the Root-owned handoff for a reviewed strict CPU worker to read those values and emit the mass discrepancy plus four evidence sidecars.

After that worker completes, `derive_f1_ecc_sidecars.py` validates the worker identity/check contract, binds the five actual sidecar files, and can refresh a copied request with their immutable hashes:

```text
python3 derive_f1_ecc_sidecars.py \
  --manifest F1_ECC_STAGE1_CASE_MANIFEST.json \
  --audit-result /path/to/strict-cpu-audit.json \
  --output-dir /path/to/worker-bindings \
  --request requests/F1_STAGE1_ECC_H130_DP010.json
```

The sidecar adapter copies provenance only; it does not decode BI4/XML arrays, compute mass, or claim an independent experiment.
