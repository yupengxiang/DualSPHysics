from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "lagrangian-fluid-lab" / "scripts"
ENTRY = SCRIPT_DIR / "ds_data02_stage2_f2_current_scoped_entry_v17.py"
V1 = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_portable_rebind_v1.py"
V2 = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_portable_rebind_v2.py"
V15 = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_portable_rebind_v15.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
CURRENT = Path(
    "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/"
    "native-reconstruction/raw-to-label-v10-hardwall-v6/"
    "f2-s1-portable-ledger-bridge-request-v10-005.json"
)
CURRENT_CATALOG = Path(
    "/home/jade/DualSPHysics-data/ds-data-02/families/infra/"
    "STAGE2_CURRENT336_CATALOG/catalog-003/CURRENT336.json"
)
CANONICAL = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX047_RY014_FILL080_ROT075"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"bytes": value.st_size, "mode_bits": value.st_mode & 0o7777,
            "mtime_ns": value.st_mtime_ns, "ctime_ns": value.st_ctime_ns,
            "st_dev": value.st_dev, "st_ino": value.st_ino}


def _canonical(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        {key: item for key, item in value.items() if key != "sha256"},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode()).hexdigest()


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def _tiny_runtime(tmp_path: Path) -> tuple[Path, Path]:
    """Run the V17 copied entry with a genuine V1 sibling in the graph.

    The V2 target is a tiny dispatch fixture here so this test remains bounded;
    the separate real V2/V8/V12/scorer test covers the scientific consumer.
    Crucially, the V1 target is the actual repository V1 source and is loaded
    before V15/V2, catching the historical V15-for-V1 alias bug.
    """
    root = tmp_path / "target"
    runtime = root / "runtime" / "v17"
    runtime.mkdir(parents=True)
    (root / "requests").mkdir()
    (root / "products").mkdir()
    current = runtime / "CURRENT336.json"
    current.write_text('{"schema":"tiny-current","case_id":"%s"}\n' % CANONICAL)
    leaf = runtime / "ds_data02_stage2_f2_current_scoped_leaf_v17.py"
    leaf.write_text("SCOPED_LEAF = True\n")
    shutil.copyfile(V1, runtime / V1.name)
    shutil.copyfile(V15, runtime / V15.name)
    # V15 imports V2 by basename.  This tiny V2 keeps that import surface but
    # does not replace the real-V2 sibling import coverage below.
    (runtime / V2.name).write_text(
        "import json\nfrom pathlib import Path\n"
        "MAX_METADATA_BYTES=32*1024*1024\n"
        "class PortableRebindV2Error(RuntimeError): pass\n"
        "def _directory_rebind(parts, root): return None\n"
        "def _rebase_runtime_json(path, **kwargs): raise PortableRebindV2Error('unused')\n"
        "def _rewrite_request(value, **kwargs): return value\n"
        "def _should_recurse(parts): return False\n"
        "def main(argv):\n"
        " output=Path(argv[argv.index('--output')+1]); output.parent.mkdir(parents=True,exist_ok=True)\n"
        " output.write_text(json.dumps({'status':'TINY_V2_MAIN_CALLED'})); return 0\n",
        encoding="utf-8")
    shutil.copyfile(ENTRY, runtime / ENTRY.name)
    paths = {
        "entrypoint": f"runtime/v17/{ENTRY.name}",
        "v1": f"runtime/v17/{V1.name}", "v2": f"runtime/v17/{V2.name}",
        "v15": f"runtime/v17/{V15.name}",
        "leaf_module": f"runtime/v17/{leaf.name}",
        "contract": "runtime/v17/current-scoped-runtime-contract.v17.json",
        "current": "runtime/v17/CURRENT336.json",
    }
    copied = {key: root / rel for key, rel in paths.items() if key != "contract"}
    contract = {
        "schema": "ds02.stage2.f2-current-scoped-runtime-contract.v17",
        "status": "READY_SCOPED_CURRENT_RUNTIME_AFTER_COPY",
        "current_binding": {"source_path_provenance": str(current), "sha256": _sha(current),
                            "source_stat_provenance": _stat(current),
                            "target_relative_path": paths["current"], "target_stat": _stat(current)},
        "case_scope": {"family_id": "F2", "physical_case_id": CANONICAL,
                        "identity_status": "CANONICAL", "selection_is_single_case": True},
        "nested_manifest_paths": {"opened": False, "allowlist": [], "policy": "SEALED_LEAF"},
        "original_path_fallback": "REJECT", "payload_read": False,
        "ledger_mutated": False,
    }
    contract["sha256"] = _canonical(contract)
    contract_path = root / paths["contract"]
    _write(contract_path, contract)
    descriptor = {
        "schema": contract["schema"], "status": contract["status"], "case_id": CANONICAL,
        "original_path_fallback": "REJECT",
        "nested_manifest_paths": {"opened": False, "allowlist": [], "policy": "SEALED_LEAF"},
        "target_relative_paths": paths, "expected_sha256": {}, "source_stat": {},
        "runtime_contract_target_relative_path": paths["contract"],
        "current_target_relative_path": paths["current"], "current_sha256": _sha(current),
        "current_source_stat": _stat(current), "entrypoint_calls_v2_main": True,
    }
    for key, path in copied.items():
        descriptor["expected_sha256"][key] = _sha(path)
        descriptor["source_stat"][key] = _stat(path)
    descriptor["expected_sha256"]["contract"] = _sha(contract_path)
    descriptor["source_stat"]["contract"] = _stat(contract_path)
    inner = {"schema": "tiny-inner-v17", "v17_scoped_runtime": descriptor}
    inner["sha256"] = _canonical(inner)
    _write(root / "requests/inner.json", inner)
    overlay = {"schema": "tiny-overlay-v17", "relocated_root": str(root),
               "request_binding": {"generated_target_relative_path": "requests/inner.json"}}
    overlay_path = root / "requests/overlay.json"
    _write(overlay_path, overlay)
    return root, overlay_path


def test_v17_real_v1_sibling_is_loaded_before_v15_v2(tmp_path: Path) -> None:
    root, overlay = _tiny_runtime(tmp_path)
    output = root / "products/report.json"
    proc = subprocess.run(
        [str(PYTHON), "-B", "-I", str(root / "runtime/v17" / ENTRY.name),
         "worker", "--request", str(overlay), "--output", str(output),
         "--parent-pid", str(__import__("os").getpid())],
        cwd=str(root), text=True, capture_output=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["v2_main_called"] is True
    assert (root / "runtime/v17" / V1.name).is_file()


def test_v17_actual_v2_import_requires_copied_v1(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    root.mkdir()
    shutil.copyfile(V1, root / V1.name)
    shutil.copyfile(V2, root / V2.name)
    script = (
        "import importlib.util\n"
        "p='ds_data02_stage2_f2_typed_only_portable_rebind_v2.py'\n"
        "s=importlib.util.spec_from_file_location('copied_v2',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)\n"
        "assert m.V1_SCRIPT.name == 'ds_data02_stage2_f2_typed_only_portable_rebind_v1.py'\n"
        "print('REAL_V2_V1_SIBLING_IMPORT_PASS')\n"
    )
    proc = subprocess.run([str(PYTHON), "-B", "-I", "-c", script], cwd=root,
                          text=True, capture_output=True, check=False)
    assert proc.returncode == 0, proc.stderr
    assert "REAL_V2_V1_SIBLING_IMPORT_PASS" in proc.stdout
    (root / V1.name).unlink()
    proc = subprocess.run([str(PYTHON), "-B", "-I", "-c", script], cwd=root,
                          text=True, capture_output=True, check=False)
    assert proc.returncode != 0
    assert "V1 dependency is unavailable" in proc.stderr


def test_v17_keeps_real_v2_v8_v12_scorer_fixture(tmp_path: Path) -> None:
    """Run the existing genuine relocated V2 consumer fixture as a guard.

    This is deliberately separate from the tiny V17 entry dispatch test: the
    fixture constructs a complete small V8/V12/typed-scorer bundle, removes
    its source tree, and executes the real V2 worker.  Keeping it in the V17
    suite prevents the sibling-closure fix from regressing into another tiny
    V2 stub while production payloads remain deferred.
    """
    fixture = _load(
        Path(__file__).with_name("test_ds_data02_stage2_f2_typed_only_portable_rebind_v2_real.py"),
        "ds02_v17_real_v2_v8_v12_fixture",
    )
    fixture.test_v2_real_relocated_v8_v12_typed_scorer_without_source(tmp_path / "real-v2")


def test_v17_identity_manifest_rejects_row78_relabel(tmp_path: Path) -> None:
    builder = _load(SCRIPT_DIR / "ds_data02_stage2_f2_current_scoped_source_request_v17.py",
                    "ds02_v17_builder_identity_test")
    old = Path(
        "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
        "portable-typed-root242-v15-root-forward-242-006.json"
    )
    clone = json.loads(old.read_text())
    clone["case_id"] = CANONICAL
    clone["identity_status"] = "CANONICAL"
    source_request = tmp_path / "laundered.json"
    _write(source_request, clone)
    source_contract = tmp_path / "source-contract.json"
    _write(source_contract, {"root242_source_binding": {"roles": []}})
    report = tmp_path / "preflight.json"
    _write(report, {"schema": builder.PREFLIGHT_SCHEMA,
                    "status": "READY_FOR_PARENT_GUARD_METADATA_ONLY",
                    "roles": [], "unbound_actionable_paths": [], "graph_errors": [],
                    "rewrite": {"errors": []}})
    with pytest.raises(builder.CurrentScopedSourceRequestError, match="identity_join_rejected"):
        builder.build_request(
            source_contract=source_contract,
            source_request=source_request, preflight_report=report,
            output_contract=tmp_path / "out-contract.json", output_request=tmp_path / "out-request.json",
            fresh_root=tmp_path / "fresh", home_receipt=tmp_path / "receipt.json",
            case_id=CANONICAL, attempt_id="v17-negative", primary_scripts_root=ROOT,
            current_path=CURRENT_CATALOG, identity_manifest=tmp_path / "identity.json",
        )


def test_v17_identity_manifest_requires_all_exact_roles(tmp_path: Path) -> None:
    builder = _load(SCRIPT_DIR / "ds_data02_stage2_f2_current_scoped_source_request_v17.py",
                    "ds02_v17_identity_manifest_test")
    current = tmp_path / "current.json"
    current.write_text(json.dumps({"physical_case_id": CANONICAL}) + "\n")
    request = tmp_path / "request.json"; _write(request, {"case_id": CANONICAL})
    contract = tmp_path / "contract.json"
    contract_value = {"case_id": CANONICAL, "root242_source_binding": {"roles": []}}
    manifest = tmp_path / "identity.json"
    refs = []
    for role in sorted(builder.IDENTITY_REF_ROLES):
        ref = current if role == "current_row" else tmp_path / f"{role}.json"
        _write(ref, {"physical_case_id": CANONICAL})
        refs.append({"role": role, "path": str(ref), "sha256": _sha(ref)})
        if role != "current_row":
            contract_value["root242_source_binding"]["roles"].append({
                "source_path_provenance": str(ref), "source_sha256": _sha(ref)})
    _write(contract, contract_value)
    value = {"schema": builder.IDENTITY_MANIFEST_SCHEMA, "family_id": "F2",
             "physical_case_id": CANONICAL, "identity_status": "CANONICAL",
             "current_catalog_sha256": _sha(current),
             "source_request_sha256": _sha(request), "source_contract_sha256": _sha(contract),
             "references": refs}
    _write(manifest, value)
    # The CURRENT SHA pin is production-bound; this tiny test exercises the
    # role-join logic without pretending its manufactured catalog is production.
    old_sha = builder.CURRENT_SHA
    builder.CURRENT_SHA = _sha(current)
    try:
        result = builder._validate_identity_manifest(
            manifest, source_request=request, source_contract=contract,
            source_contract_value=contract_value,
            current=current, case_id=CANONICAL, family_id="F2")
    finally:
        builder.CURRENT_SHA = old_sha
    assert result["identity_status"] == "CANONICAL"
    assert len(result["references"]) == 7
