# F1 Root095 runtime request adapter

Root094’s ECC H130 and DUAL H260 requests passed the Stage1 visual authorizer, but the shared `ds_data02_runtime_v2.validate_request` contract rejected both before launch. The runtime validator uses `Path(request["gencase_receipt"])` (runtime source line 232) and later hashes that value (line 244), so it requires a receipt path string. Root094 supplied the valid `{path, sha256}` binding object and omitted the companion `gencase_receipt_sha256` field.

This fresh061 package contains a metadata-only adapter. It reads the two existing Root094 request JSON files and the referenced actual GenCase receipt JSON only to verify the declared receipt hash. It writes two concrete Root095-compatible request files. The Stage1 authorizer’s `_actual_case_bindings` also compares the normalized request string and optional SHA (`ds_data02_stage1_production_f1.py` lines 534-537), while its `build_request` helper performs this exact normalization (lines 1007-1010). The only semantic mutations are:

- `gencase_receipt`: binding object → its path string;
- `gencase_receipt_sha256`: added from the binding SHA-256.

The command, cwd, solver recipe, event window, attempt ID, input file list, input SHA map, worktree root, Stage1 profile, adapter path, approval fields, and all other request fields remain unchanged. The output attempt IDs intentionally remain the Root094 IDs because the failed launches stopped during validation before resource reservation or solver execution.

The adapter does not import the runtime or authorizer, invoke a runner, execute GenCase/PartVTK/DualSPHysics, inspect BI4/CSV/H5/arrays, or touch the mutable approval registry. Use the generated request files for the next Root launch; leave the original Root094 requests unchanged.

```text
/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python -B build_root095_runtime_request_adapter.py
```

The contract report records the exact missing/incompatible fields before and after adaptation. Root must still perform the normal Stage1 authorization/runtime validation and actual production launch.
