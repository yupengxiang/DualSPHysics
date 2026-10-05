#!/usr/bin/env python3
import importlib.util, json, sys
from pathlib import Path
DIRECT = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_direct_convert.py")
def load(p): return json.loads(Path(p).read_text())
def main():
    if len(sys.argv) != 3: raise SystemExit("usage: verify_converter_scope.py OWNER_JSON OUTPUT_JSON")
    owner = load(sys.argv[1])
    source_ref = owner.get("source_owner")
    source_owner = load(source_ref["path"]) if isinstance(source_ref, dict) and source_ref.get("path") else owner
    spec = importlib.util.spec_from_file_location("ds02_direct_convert_scope_review", DIRECT)
    mod = importlib.util.module_from_spec(spec); sys.modules[spec.name] = mod; spec.loader.exec_module(mod)
    original = mod._physical_condition_scope(source_owner)
    original_scope = "legacy-owner-scope.v0" if "physical_binding" not in source_owner else source_owner["physical_binding"].get("schema")
    derived = owner["physical_binding"]
    mod._validate_physical_binding(derived)
    result = {"schema": "ds02.f4.fresh104.converter-scope-verifier.v1", "original_owner": source_ref, "original_scope": original_scope, "legacy_scope_sha256": mod.canonical_hash(original), "derived_scope_sha256": mod.canonical_hash(derived), "validated": True, "arrays_read_or_hashed": False, "jobs_started": False}
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
if __name__ == "__main__": main()
