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
ENTRY_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_current_scoped_entry_v16.py"
BUILDER_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_current_scoped_source_request_v16.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
CURRENT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/infra/"
    "STAGE2_CURRENT336_CATALOG/catalog-003/CURRENT336.json"
)
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
CANONICAL_CASE = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX047_RY014_FILL080_ROT075"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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


def _tiny_runtime(tmp_path: Path) -> tuple[Path, dict, Path]:
    """Make a copied runtime with real V15 source and a tiny V2 main.

    The V2 main is a bounded interface fixture: V16 dynamically loads the
    actual copied V15 module, validates all target bindings, and then invokes
    this local main.  Production V2/V8/V12 execution is covered by the real
    source-builder role map; this test avoids reading a production result.
    """
    source = tmp_path / "source"
    root = tmp_path / "target"
    source.mkdir()
    (root / "runtime" / "v16").mkdir(parents=True)
    (root / "requests").mkdir()
    (root / "products").mkdir()
    current_source = source / "CURRENT336.json"
    current_source.write_text(json.dumps({"schema": "tiny-current", "cases": []}) + "\n")
    current_target = root / "runtime" / "v16" / "CURRENT336.json"
    shutil.copyfile(current_source, current_target)

    # V15 is the actual repository rebinder.  Its sibling V2 is a tiny module
    # exposing the symbols V15 imports and a real main dispatch.
    v15_target = root / "runtime" / "v16" / "ds_data02_stage2_f2_typed_only_portable_rebind_v15.py"
    shutil.copyfile(SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_portable_rebind_v15.py", v15_target)
    v2_source = source / "tiny_v2.py"
    v2_source.write_text(
        """import json\nfrom pathlib import Path\nMAX_METADATA_BYTES=32*1024*1024\nclass PortableRebindV2Error(RuntimeError): pass\ndef _directory_rebind(parts, root): return None\ndef _rebase_runtime_json(path, **kwargs): raise PortableRebindV2Error('unused')\ndef _rewrite_request(value, **kwargs): return value\ndef _json(path, role): return json.loads(Path(path).read_text())\ndef _safe_relative(value, role): return value\ndef _full_stat(path): return {}\ndef _sha(path): return '0'*64\ndef main(argv):\n    output=Path(argv[argv.index('--output')+1])\n    output.parent.mkdir(parents=True,exist_ok=True)\n    output.write_text(json.dumps({'status':'TINY_V2_MAIN_CALLED','argv':list(argv)}))\n    return 0\n""",
        encoding="utf-8",
    )
    v2_target = root / "runtime" / "v16" / "ds_data02_stage2_f2_typed_only_portable_rebind_v2.py"
    shutil.copyfile(v2_source, v2_target)
    leaf_source = source / "leaf.py"
    leaf_source.write_text("SCOPED_LEAF = True\n", encoding="utf-8")
    leaf_target = root / "runtime" / "v16" / "ds_data02_stage2_f2_current_scoped_leaf_v16.py"
    shutil.copyfile(leaf_source, leaf_target)
    entry_target = root / "runtime" / "v16" / ENTRY_SCRIPT.name
    shutil.copyfile(ENTRY_SCRIPT, entry_target)

    paths = {
        "entrypoint": str(entry_target.relative_to(root)),
        "v2": str(v2_target.relative_to(root)),
        "v15": str(v15_target.relative_to(root)),
        "leaf_module": str(leaf_target.relative_to(root)),
        "contract": "runtime/v16/current-scoped-runtime-contract.v16.json",
        "current": str(current_target.relative_to(root)),
    }
    sources = {
        "entrypoint": entry_target, "v2": v2_target, "v15": v15_target,
        "leaf_module": leaf_target, "current": current_target,
    }
    contract = {
        "schema": "ds02.stage2.f2-current-scoped-runtime-contract.v16",
        "status": "READY_SCOPED_CURRENT_RUNTIME_AFTER_COPY",
        "current_binding": {
            "source_path_provenance": str(current_source), "sha256": _sha(current_source),
            "source_stat_provenance": _stat(current_source),
            "target_relative_path": paths["current"], "target_stat": _stat(current_target),
        },
        "nested_manifest_paths": {"opened": False, "allowlist": [], "policy": "SEALED_LEAF"},
        "original_path_fallback": "REJECT", "payload_read": False,
        "case_scope": {"family_id": "F2", "physical_case_id": CANONICAL_CASE,
                        "identity_status": "CANONICAL"},
    }
    contract["sha256"] = _canonical(contract)
    contract_source = source / "contract.json"
    _write(contract_source, contract)
    contract_target = root / paths["contract"]
    shutil.copyfile(contract_source, contract_target)
    descriptor = {
        "schema": "ds02.stage2.f2-current-scoped-runtime-contract.v16",
        "status": "READY_SCOPED_CURRENT_RUNTIME_AFTER_COPY",
        "case_id": CANONICAL_CASE, "original_path_fallback": "REJECT",
        "nested_manifest_paths": {"opened": False, "allowlist": [], "policy": "SEALED_LEAF"},
        "target_relative_paths": paths,
        "expected_sha256": {key: _sha(path) for key, path in sources.items()},
        "source_stat": {key: _stat(path) for key, path in sources.items()},
        "current_sha256": _sha(current_source),
        "current_source_stat": _stat(current_source),
        "current_target_relative_path": paths["current"],
        "runtime_contract_target_relative_path": paths["contract"],
        "entrypoint_calls_v2_main": True,
    }
    descriptor["expected_sha256"]["contract"] = _sha(contract_target)
    descriptor["source_stat"]["contract"] = _stat(contract_source)
    inner = {"schema": "tiny-inner-v16", "v16_scoped_runtime": descriptor}
    inner["sha256"] = _canonical(inner)
    inner_target = root / "requests" / "inner.json"
    _write(inner_target, inner)
    overlay = {
        "schema": "tiny-overlay-v16", "relocated_root": str(root),
        "request_binding": {"generated_target_relative_path": "requests/inner.json"},
    }
    overlay_path = root / "requests" / "overlay.json"
    _write(overlay_path, overlay)
    return root, descriptor, overlay_path


def test_v16_entry_runs_real_copied_v15_and_dispatches_v2_main(tmp_path: Path) -> None:
    root, _descriptor, overlay = _tiny_runtime(tmp_path)
    output = root / "reports" / "tiny.json"
    proc = subprocess.run(
        [str(PYTHON), "-B", "-I", str(root / "runtime/v16" / ENTRY_SCRIPT.name),
         "worker", "--request", str(overlay), "--output", str(output),
         "--parent-pid", str(__import__("os").getpid())],
        cwd=str(root), text=True, capture_output=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["status"] == "PASS_V16_SCOPED_ENTRY_DISPATCHED_V2_MAIN"
    assert result["v2_main_called"] is True
    assert json.loads(output.read_text())["status"] == "TINY_V2_MAIN_CALLED"


def test_v16_entry_rejects_changed_copied_sibling(tmp_path: Path) -> None:
    root, _descriptor, overlay = _tiny_runtime(tmp_path)
    target = root / "runtime/v16/ds_data02_stage2_f2_typed_only_portable_rebind_v2.py"
    target.write_text(target.read_text() + "\n# mutation\n")
    proc = subprocess.run(
        [str(PYTHON), "-B", "-I", str(root / "runtime/v16" / ENTRY_SCRIPT.name),
         "worker", "--request", str(overlay), "--output", str(root / "reports.json"),
         "--parent-pid", str(__import__("os").getpid())],
        cwd=str(root), text=True, capture_output=True, check=False,
    )
    assert proc.returncode != 0
    assert "copied SHA differs" in proc.stderr


def test_v16_source_builder_rejects_legacy_row78(tmp_path: Path) -> None:
    builder = _load(BUILDER_SCRIPT, "ds02_v16_source_builder_test")
    base = Path(
        "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests"
    )
    request = base / "portable-typed-root242-v15-root-forward-242-006.json"
    contract = base / "root242-v15-list-string-primary-prepared-006/source-contract.json"
    report = Path(
        "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/"
        "ROOT242_V15_ACTUAL_METADATA_RECURSIVE_SOURCE_PREFLIGHT_V1.json"
    )
    current = CURRENT
    with pytest.raises(builder.CurrentScopedSourceRequestError, match="legacy_row78_rejected"):
        builder.build_request(
            source_contract=contract, source_request=request, preflight_report=report,
            output_contract=tmp_path / "contract.json", output_request=tmp_path / "request.json",
            fresh_root=tmp_path / "fresh", home_receipt=tmp_path / "receipt.json",
            case_id=CANONICAL_CASE, attempt_id="tiny-v16", primary_scripts_root=ROOT,
            current_path=current,
        )


def test_v16_source_builder_binds_new_runtime_roles_from_canonicalized_base(tmp_path: Path) -> None:
    builder = _load(BUILDER_SCRIPT, "ds02_v16_source_builder_positive_test")
    base = Path(
        "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests"
    )
    request = base / "portable-typed-root242-v15-root-forward-242-006.json"
    contract = base / "root242-v15-list-string-primary-prepared-006/source-contract.json"
    report = Path(
        "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/"
        "ROOT242_V15_ACTUAL_METADATA_RECURSIVE_SOURCE_PREFLIGHT_V1.json"
    )
    # Make a bounded cloned base request whose identity is canonical.  The
    # production row78 request remains untouched and the builder still binds
    # the real V14/V13/V11 role table and source report.
    clone = json.loads(request.read_text())
    clone["case_id"] = "CANONICAL_BASE_FOR_V16_INTERFACE_TEST"
    clone["identity_status"] = "CANONICAL"
    clone["sha256"] = builder._canonical(clone)
    source_request = tmp_path / "canonical-base-request.json"
    _write(source_request, clone)
    result = builder.build_request(
        source_contract=contract, source_request=source_request, preflight_report=report,
        output_contract=tmp_path / "contract.json", output_request=tmp_path / "request.json",
        fresh_root=tmp_path / "fresh", home_receipt=tmp_path / "receipt.json",
        case_id=CANONICAL_CASE, attempt_id="tiny-v16-positive", primary_scripts_root=ROOT,
        current_path=CURRENT,
    )
    assert result["status"] == "READY_FOR_PARENT_STAGE2_GUARD_V16_SCOPED_CURRENT_RUNTIME"
    contract_value = json.loads((tmp_path / "contract.json").read_text())
    request_value = json.loads((tmp_path / "request.json").read_text())
    names = {row["logical_role"] for row in contract_value["root242_source_binding"]["roles"]}
    assert {"current_scoped_leaf_v16", "current_scoped_runtime_contract_v16",
            "current_catalog_exact_leaf"} <= names
    assert request_value["root242_v16_source_binding"]["entrypoint_calls_v2_main"] is True
    assert request_value["scope"]["original_path_fallback"] == "REJECT"
    assert result["preflight"]["role_count"] == 492
    v11 = _load(
        SCRIPT_DIR / "ds_data02_stage2_f2_root242_v11_source_request.py",
        "ds02_v16_v11_validator_positive_test",
    )
    v11_result = v11.validate_request(request=tmp_path / "request.json",
                                      contract=tmp_path / "contract.json")
    assert v11_result["selected_role_count"] == 494
    v14 = _load(
        SCRIPT_DIR / "ds_data02_stage2_f2_root242_portable_typed_executor_v14.py",
        "ds02_v16_v14_validator_positive_test",
    )
    # V14 binds its own launcher source to the primary checkout.  The test
    # exercises that same source identity without executing a parent/worker.
    primary_v14 = Path(
        "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
        "lagrangian-fluid-lab/scripts/ds_data02_stage2_f2_root242_portable_typed_executor_v14.py"
    )
    old_script = v14.SCRIPT
    v14.SCRIPT = primary_v14
    try:
        outer = v14._validate_v14(tmp_path / "request.json")
    finally:
        v14.SCRIPT = old_script
    assert outer[4]["status"] == "READY_FOR_PARENT_GUARD_METADATA_ONLY"
