"""One copied-runtime test for V17 -> real V2 -> V8/V12/scorer.

The older V17 tests intentionally keep a tiny V2 dispatch fixture and run the
real V2 fixture separately.  This test installs the V17 entrypoint into that
same real relocated bundle, so the subprocess imported by the outer V2 guard
is V17, V17 loads the real V1/V15/V2 siblings, and V2 then executes the real
V8/V12/typed scorer path.  No production payload is involved: the underlying
fixture is the existing bounded manufactured result.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "lagrangian-fluid-lab" / "scripts"
ENTRY = SCRIPTS / "ds_data02_stage2_f2_current_scoped_entry_v17.py"
V1 = SCRIPTS / "ds_data02_stage2_f2_typed_only_portable_rebind_v1.py"
V2 = SCRIPTS / "ds_data02_stage2_f2_typed_only_portable_rebind_v2.py"
V15 = SCRIPTS / "ds_data02_stage2_f2_typed_only_portable_rebind_v15.py"


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
    return {"bytes": int(value.st_size), "mode_bits": int(value.st_mode & 0o7777),
            "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns),
            "st_dev": int(value.st_dev), "st_ino": int(value.st_ino)}


def _canonical(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        {key: item for key, item in value.items() if key != "sha256"},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode()).hexdigest()


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _install_v17_into_real_bundle(request_path: Path) -> None:
    """Replace only the copied child entrypoint and add its sealed V17 graph."""
    v2 = _load(V2, "v17_joint_outer_v2")
    entry = _load(ENTRY, "v17_joint_entry_module")
    outer = json.loads(request_path.read_text(encoding="utf-8"))
    root = Path(outer["relocated_root"])
    contract_path = Path(outer["contract_binding"]["path"])
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    by_role = {item["logical_role"]: item for item in contract["roles"]}
    child_role = by_role["portable_rebind_v2_entrypoint"]
    child_target = root / child_role["target_relative_path"]
    original_v2_target = root / "runtime" / "v17" / V2.name
    original_v2_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(child_target, original_v2_target)

    v17_root = root / "runtime" / "v17"
    v17_root.mkdir(parents=True, exist_ok=True)
    v17_entry_target = child_target
    shutil.copy2(ENTRY, v17_entry_target)
    v17_v1 = v17_root / V1.name
    v17_v15 = v17_root / V15.name
    shutil.copy2(V1, v17_v1)
    shutil.copy2(V15, v17_v15)
    v17_v2 = original_v2_target
    leaf = v17_root / "ds_data02_stage2_f2_current_scoped_leaf_v17.py"
    leaf.write_text("SCOPED_CURRENT_LEAF = True\n", encoding="utf-8")
    current_role = by_role["current336_actionable_metadata"]
    copied_current = root / current_role["target_relative_path"]
    v17_current = v17_root / "CURRENT336.json"
    shutil.copy2(copied_current, v17_current)

    contract_v17 = {
        "schema": "ds02.stage2.f2-current-scoped-runtime-contract.v17",
        "status": "READY_SCOPED_CURRENT_RUNTIME_AFTER_COPY",
        "case_scope": {"family_id": "F2", "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX047_RY014_FILL080_ROT075",
                        "identity_status": "MANUFACTURED_FIXTURE", "selection_is_single_case": True},
        "nested_manifest_paths": {"opened": False, "allowlist": [], "policy": "SEALED_LEAF"},
        "original_path_fallback": "REJECT", "payload_read": False, "ledger_mutated": False,
        "current_binding": {"target_relative_path": str(v17_current.relative_to(root)),
                            "sha256": _sha(v17_current), "target_stat": _stat(v17_current)},
    }
    contract_v17["sha256"] = _canonical(contract_v17)
    v17_contract = v17_root / "current-scoped-runtime-contract.v17.json"
    _write_json(v17_contract, contract_v17)

    targets = {
        "entrypoint": v17_entry_target, "v1": v17_v1, "v2": v17_v2,
        "v15": v17_v15, "leaf_module": leaf, "contract": v17_contract,
        "current": v17_current,
    }
    descriptor = {
        "schema": contract_v17["schema"], "status": contract_v17["status"],
        "case_id": contract_v17["case_scope"]["physical_case_id"],
        "original_path_fallback": "REJECT",
        "nested_manifest_paths": {"opened": False, "allowlist": [], "policy": "SEALED_LEAF"},
        "target_relative_paths": {key: str(path.relative_to(root)) for key, path in targets.items()},
        "expected_sha256": {key: _sha(path) for key, path in targets.items()},
        "source_stat": {key: _stat(path) for key, path in targets.items()},
        "current_target_relative_path": str(v17_current.relative_to(root)),
        "current_sha256": _sha(v17_current), "current_source_stat": _stat(v17_current),
        "entrypoint_calls_v2_main": True,
    }
    generated_rel = outer["request_binding"]["generated_target_relative_path"]
    generated = root / generated_rel
    inner = json.loads(generated.read_text(encoding="utf-8"))
    inner["v17_scoped_runtime"] = descriptor
    inner["sha256"] = v2._canonical(inner)
    _write_json(generated, inner)

    # The outer V2 request starts the child through this role.  Point that
    # sealed role at V17 while keeping the genuine V2 sibling in the V17 graph.
    child_role["source_path_provenance"] = str(ENTRY)
    child_role["source_sha256"] = _sha(ENTRY)
    child_role["source_stat_provenance"] = _stat(ENTRY)
    child_role["target_stat"] = _stat(child_target)
    contract["sha256"] = v2._canonical(contract)
    _write_json(contract_path, contract)
    outer["contract_binding"]["sha256"] = contract["sha256"]
    for binding in outer["runtime_bindings"].values():
        if binding.get("logical_role") == "portable_rebind_v2_entrypoint":
            binding["source_sha256"] = _sha(ENTRY)
            binding["source_stat_provenance"] = _stat(ENTRY)
            binding["target_stat"] = _stat(child_target)
    outer["request_binding"]["generated_file_sha256"] = _sha(generated)
    outer["request_binding"]["generated_target_stat"] = _stat(generated)
    outer["sha256"] = v2._canonical(outer)
    _write_json(request_path, outer)


def test_v17_entry_routes_real_v2_v8_v12_scorer_fixture(tmp_path: Path) -> None:
    fixture = _load(
        Path(__file__).with_name("test_ds_data02_stage2_f2_typed_only_portable_rebind_v2_real.py"),
        "ds02_v17_joint_real_fixture",
    )
    original = fixture.V2.run_guard
    installed: dict[str, Path] = {}

    def wrapped_run_guard(*, request_path, output_relative, parent_pid, python_path, max_wall_seconds):
        request = Path(request_path)
        _install_v17_into_real_bundle(request)
        installed["overlay"] = request
        return original(request_path=request, output_relative=output_relative,
                         parent_pid=parent_pid, python_path=python_path,
                         max_wall_seconds=max_wall_seconds)

    fixture.V2.run_guard = wrapped_run_guard
    try:
        fixture.test_v2_real_relocated_v8_v12_typed_scorer_without_source(tmp_path / "joint")
    finally:
        fixture.V2.run_guard = original
    assert installed["overlay"].is_file()
    overlay = json.loads(installed["overlay"].read_text(encoding="utf-8"))
    root = Path(overlay["relocated_root"])
    contract = json.loads(Path(overlay["contract_binding"]["path"]).read_text(encoding="utf-8"))
    child = next(item for item in contract["roles"]
                 if item["logical_role"] == "portable_rebind_v2_entrypoint")
    assert Path(child["target_path"] if "target_path" in child else child["target_relative_path"]).name.endswith(".py")
    generated = root / overlay["request_binding"]["generated_target_relative_path"]
    inner = json.loads(generated.read_text(encoding="utf-8"))
    assert inner["v17_scoped_runtime"]["nested_manifest_paths"]["allowlist"] == []
    assert inner["v17_scoped_runtime"]["original_path_fallback"] == "REJECT"


def test_real_joint_overlay_rejects_unbound_nested_current_manifest(tmp_path: Path) -> None:
    """The real V2 recursive gate rejects an unregistered CURRENT manifest path."""
    fixture = _load(
        Path(__file__).with_name("test_ds_data02_stage2_f2_typed_only_portable_rebind_v2_real.py"),
        "ds02_v17_joint_negative_fixture",
    )
    # Build a real bundle and let the V17 injection happen, then poison the
    # generated inner request after the successful child has finished.  This
    # exercises the same recursive V2 validator used by the joint subprocess;
    # the original source tree is already absent at this point.
    original = fixture.V2.run_guard
    installed: dict[str, Path] = {}

    def wrapped(*, request_path, output_relative, parent_pid, python_path, max_wall_seconds):
        request = Path(request_path)
        _install_v17_into_real_bundle(request)
        installed["overlay"] = request
        return original(request_path=request, output_relative=output_relative,
                         parent_pid=parent_pid, python_path=python_path,
                         max_wall_seconds=max_wall_seconds)

    fixture.V2.run_guard = wrapped
    try:
        fixture.test_v2_real_relocated_v8_v12_typed_scorer_without_source(tmp_path / "negative")
    finally:
        fixture.V2.run_guard = original
    overlay_path = installed["overlay"]
    overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
    root = Path(overlay["relocated_root"])
    generated = root / overlay["request_binding"]["generated_target_relative_path"]
    inner = json.loads(generated.read_text(encoding="utf-8"))
    inner["current_manifest_binding"] = {"path": str(tmp_path / "original" / "CURRENT.json"),
                                         "sha256": "f" * 64}
    inner["sha256"] = _canonical(inner)
    _write_json(generated, inner)
    v2 = fixture.V2
    overlay["request_binding"]["generated_file_sha256"] = _sha(generated)
    overlay["request_binding"]["generated_target_stat"] = _stat(generated)
    overlay["sha256"] = v2._canonical(overlay)
    _write_json(overlay_path, overlay)
    with pytest.raises(v2.PortableRebindV2Error, match="escapes target root|unregistered actionable"):
        v2.validate_request_overlay(overlay_path)
