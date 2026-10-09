"""Metadata-only regression tests for the V51 copied-module rebinding."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_portable_executor_v51.py"


def _load():
    spec = importlib.util.spec_from_file_location("test_v51_executor", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V = _load()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _request(tmp_path: Path) -> tuple[Path, dict, Path]:
    source_roles = {
        "raw_converter": ("sources/0025-converter.py", b"converter"),
        "v14_operator": ("sources/0026-v14.py", b"v14"),
        "v15_operator": ("sources/0027-v15.py", b"v15"),
        "v16_operator": ("sources/0028-v16.py", b"v16"),
    }
    entries = []
    for role, (relative, payload) in source_roles.items():
        path = tmp_path / "original" / Path(relative).name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        entries.append({"role": role, "path": str(path), "target_relative_path": relative,
                        "bytes": len(payload), "sha256": _sha(payload)})
    value = {
        "schema": V.V34_SCHEMA, "role": "DEVELOPMENT",
        "status": "READY_FOR_PARENT_STAGE2_GUARD", "model_invoked": False,
        "cfd_invoked": False, "qualification": dict(V.UNKNOWN),
        "forward_v50": {"schema": "ds02.stage2.f2-portable-executor-v50-forward.v1"},
        "fresh_roots": {"target_root": str(tmp_path / "old-target"),
                         "output_root": str(tmp_path / "old-output")},
        "source_entries": entries, "runtime_sources": [],
        "execution": {"command": ["/pinned/.venv/bin/python", "-B", "-I",
                                     "ds_data02_stage2_f2_portable_executor_v45.py", "run"]},
    }
    value["sha256"] = V.canonical_sha(value)
    path = tmp_path / "v50.json"
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return path, value, tmp_path / "new-target"


def test_build_forward_maps_modules_to_copied_source_entries(tmp_path: Path) -> None:
    source, _, target = _request(tmp_path)
    output = tmp_path / "v51.json"
    result = V.build_forward(v50_request=source, output_request=output,
                             target_root=target, output_root=tmp_path / "new-output")
    assert result["payload_read"] is False
    value = json.loads(output.read_text(encoding="utf-8"))
    plan = value["forward_v51"]["module_rebinding"]
    assert plan["v14_operator"]["target_path"] == str(target / "sources/0026-v14.py")
    assert plan["v14_operator"]["source_path_fallback"] == "FORBIDDEN"
    assert value["execution"]["command"][3].endswith("ds_data02_stage2_f2_portable_executor_v51.py")
    assert value["qualification"] == V.UNKNOWN


def test_target_binding_rejects_original_path_and_requires_copied_target(tmp_path: Path) -> None:
    source, value, target = _request(tmp_path)
    plan = V.module_rebinding_plan(value, target)
    base = tmp_path / "base.json"
    base.write_text(json.dumps({"modules": {
        role: {"path": row["source_path_provenance"], "sha256": row["expected_sha256"]}
        for role, row in plan.items()}}), encoding="utf-8")
    with pytest.raises(V.PortableV51Error, match="copied module target is missing"):
        V._target_module_bindings(value, base, target)


def test_target_binding_uses_existing_copy_and_never_original(tmp_path: Path) -> None:
    source, value, target = _request(tmp_path)
    for row in V.module_rebinding_plan(value, target).values():
        path = Path(row["target_path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        original = Path(row["source_path_provenance"])
        path.write_bytes(original.read_bytes())
    plan = V.module_rebinding_plan(value, target)
    base = tmp_path / "base.json"
    base.write_text(json.dumps({"modules": {
        role: {"path": row["source_path_provenance"], "sha256": row["expected_sha256"]}
        for role, row in plan.items()}}), encoding="utf-8")
    bound = V._target_module_bindings(value, base, target)
    assert all(Path(row["path"]).is_relative_to(target) for row in bound.values())
    assert all(row["source_path_fallback"] == "FORBIDDEN" for row in bound.values())
