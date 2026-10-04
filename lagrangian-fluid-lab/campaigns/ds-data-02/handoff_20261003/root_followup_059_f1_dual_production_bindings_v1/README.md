# F1 DUAL Stage 1 source-only production bindings

This package binds Root072's four-row DUAL visual domain:

- observed `F1_STAGE1_DUAL_H220_DP020`, historical mother `F1_FALLBACK_DUAL_COARSE`, and observed `F1_STAGE1_DUAL_H340_DP020`;
- prospective genuine `F1_STAGE1_DUAL_H260_DP020`.

The builder reads bounded Root072, DUAL220 native032, H260 GenCase027, prepared-input, and QA031 metadata, then hashes referenced files. It does not launch GenCase, DualSPHysics, conversion, ParaView, or any new job. Generated fixtures and requests use `execution_allowed=false`; the fixture index is not the shared approval index.

The H260 recipe copies the actual DUAL220 native032 command and execution parameters. It changes only the genuine H260 prefix and `{attempt_root}/solver_output`. The exact options remain `-tmax:4 -tout:0.01`, with `dp=0.02`, Boundary `1`, a complete `[0,4]` window, and 401 saved frames. No mDBC command-line option is added.

H260 identity is bound to actual GenCase027/QA031 values `total=120316`, `fluid=32500`, actual 3-D, and the generated XML/BI4 hashes. The continuum reference mass `260.0 kg` comes from the Root072 owner physical metadata only. Native particle weight and native mass difference remain unset until the Root strict CPU worker reads the actual input and emits the mass report plus four evidence sidecars.

After that worker completes, `derive_f1_dual_sidecars.py` validates the worker identity/check contract, binds the five actual sidecars, and can refresh a copied request with immutable hashes:

```text
python3 derive_f1_dual_sidecars.py \
  --manifest F1_DUAL_STAGE1_CASE_MANIFEST.json \
  --audit-result /path/to/strict-cpu-audit.json \
  --output-dir /path/to/worker-bindings \
  --request requests/F1_STAGE1_DUAL_H260_DP020.json
```

The adapter copies provenance only; it does not decode BI4/XML arrays, compute mass, or claim an independent experiment.
