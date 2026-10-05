# F5 C082S1 fresh094 conversion owner

This source-only handoff gives Root a concrete owner metadata file for the already completed C082S1 GenCase 293 and short native 316 chain. It does not modify fresh093. The owner is bound to the actual C082S1 generated XML, producer receipts, placement/Mk50 report, and short solver receipt. The actual native counts are `194427 = 158559 fixed + 4210 moving + 0 floating + 31658 fluid`, dimension 3; these values are producer metadata, not a prediction.

## Physical hash semantics

The package deliberately keeps three identities separate:

- canonical owner physical identity: `e691d030eda575b9cfabe62f295c9bdc142e5a04cb4357c9fe2790aaec549dbf`;
- source plan/generated-XML identity: `5bad3ec9f9a71aa87da8272003c357f4523d4ffa164d3f06e5d25fee1a4fbfa6`;
- the exact hash returned by the real `ds_data02_direct_convert._physical_condition_scope`: `3cd1ceab16be11428bbc1011a1b4e297c384d8c7926432c222c254064744ccd0`.

The direct converter sees no `physical_binding` object here, so it returns `legacy-owner-scope.v0` with status `legacy_incomplete; no cross-resolution physical claim`. The preflight calls that real function through the integration venv and confirms the hashes are distinct. It does not call `convert_direct`. Native Mk50 and the C082S1 native counts stay in producer metadata; no native mass is invented and no mass is rescaled from the legacy continuum value `325.7142857142857 kg`.

## Root execution handoff

1. Review `requests/typed317-owner-bound-request.json`. It is a disabled copy of the fresh093 typed request whose `--owner-metadata` argument is the concrete `conversion-owner-metadata.json` path. The fresh093 request remains untouched.
2. Root may enable only the actual typed317 conversion after the short316 receipt and all existing gates are accepted. The source package makes no claim about a future H5, conversion report, XMF, render, or dynamic audit; those fields remain null.
3. After typed317 actually completes, run the metadata-only binder request in `requests/post-typed317-metadata-binder-request.json` with the real JSON receipt and real `conversion-report.json`:

```text
/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python \
  lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_094_stage1_f5_c082s1_conversion_owner_v1/scripts/bind_typed317_metadata.py \
  --owner /home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_094_stage1_f5_c082s1_conversion_owner_v1/conversion-owner-metadata.json \
  --typed-receipt <actual typed317 execution-receipt.json> \
  --conversion-report <actual conversion-report.json> \
  --output <fresh094 post-typed binding JSON>
```

The binder reads only JSON metadata, verifies the nested receipt identity, actual frame/particle/dimension values, source provenance hashes, and the legacy physical scope. It leaves H5/XMF/manifest byte hashes null and never enables a runner request. Its output is the input binding for separate Root-reviewed dynamic bed audit, XMF, and Root023 render requests. Full801 remains disabled until those actual short-event physical and visual checks pass.

The source agent did not read, open, or hash BI4/H5/CSV science arrays and did not start GenCase, solver, conversion, or shared-ledger work.
