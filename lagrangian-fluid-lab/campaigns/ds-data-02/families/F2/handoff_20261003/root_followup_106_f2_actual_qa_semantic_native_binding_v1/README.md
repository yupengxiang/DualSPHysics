# F2 fresh106: actual QA/semantic to disabled Root230 native bindings

Fresh106 is a source-only metadata handoff. It reads JSON/XML/source metadata and producer-recorded digests only. It does not open, copy, or hash CSV, DAT, BI4, H5, VTK, or solver output, and it does not call `runtime_v2.validate_request`.

The builder binds the sixteen Root417 initial-QA execution receipts and reports and the sixteen Root419 semantic execution receipts and semantic receipts. Each row requires QA `status=pass`, QA execution `completed`/`0`, all required QA checks true, semantic `completed`/`0`, semantic execution `completed`/`0`, dimension 3, and the exact producer counts `418104 total / 21114 fluid / 372840 fixed / 24150 moving / 0 floating`. The resulting native requests remain `disabled`, `execution_allowed=false`, `launch_allowed=false`; `enable_eligible` is only a review gate. Native receipt, frame, Run.out, and output hashes stay null. Root230 must resolve the live UUID lease and protect foreign GPU processes.

`owners/*actual-converter-scope-binding.json` keeps the source-plan and prospective `legacy-owner-scope.v0` values separate from an actual converter scope. `actual_converter_scope_sha256` and `canonical_physical_binding_sha256` remain null because no converter has run. BI4 and motion-DAT paths/digests are producer provenance only.

The command-closure audit checks `input_files == input_sha256`, static command inputs by content hash, and raw inputs by producer-recorded 64-hex digest without reading them. It also audits Root416/418 requests. The evidence records Root416's pre-existing missing `PartVTK_linux64` command-input binding; fresh106 does not rewrite those consumed requests. All fresh106 native request closures pass.

Run the source-only package builder or validator from this directory:

```text
python3 build_fresh106.py
python3 workers/fresh106_source_contract_validator.py
```

The authoritative generated files are `F2_STAGE1_FRESH106_ACTUAL_QA_SEMANTIC_NATIVE_BINDING_MANIFEST.json`, `evidence/upstream-actual-binding.json`, and `evidence/fresh106-source-validation.json`. No qualification, precision, production, visual, or independent case-count claim is made.
