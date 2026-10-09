"""Small source-only tests for V38 worker-parent module co-location."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_portable_executor_v52.py"
V38_SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_portable_executor_v38.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V = _load(SCRIPT, "test_v52_executor")


def _fixture(tmp_path: Path) -> tuple[Path, dict]:
    modules = {}
    texts = {
        "raw_converter": b"raw-converter",
        "v14_operator": b"v14-operator",
        "v15_operator": b"v15-operator",
        "v16_operator": b"v16-operator",
    }
    names = {
        "raw_converter": "sources/0025-converter.py",
        "v14_operator": "sources/0026-v14.py",
        "v15_operator": "sources/0027-v15.py",
        "v16_operator": "sources/0028-v16.py",
    }
    for role, data in texts.items():
        modules[role] = {
            "module_role": role, "source_role": role,
            "source_path_provenance": str(tmp_path / "original" / Path(names[role]).name),
            "target_relative_path": names[role], "expected_sha256": hashlib.sha256(data).hexdigest(),
            "expected_bytes": len(data), "source_path_fallback": "FORBIDDEN",
        }
    literal = "/opt/f2/.venv/bin/python"
    value = {
        "schema": V.V34_SCHEMA, "status": "READY_FOR_PARENT_STAGE2_GUARD", "role": "DEVELOPMENT",
        "request_id": "fixture-v51", "model_invoked": False, "cfd_invoked": False,
        "raw_opened": False, "hdf5_opened": False, "qualification": dict(V.UNKNOWN),
        "fresh_roots": {"target_root": str(tmp_path / "old-target"), "output_root": str(tmp_path / "old-output")},
        "runtime_sources": [{"role": "python_executable", "path": literal,
                             "resolved_source_path": "/usr/bin/python3.10", "target_relative_path": "runtime/python/.venv-python",
                             "bytes": 5, "sha256": "a" * 64, "required_executable": True}],
        "source_entries": [], "forward_v51": {"schema": V.V51_SCHEMA, "module_rebinding": modules},
        "execution": {"command": [literal, "-B", "-I", "ds_data02_stage2_f2_portable_executor_v51.py", "run"]},
    }
    value["sha256"] = V.canonical_sha(value)
    path = tmp_path / "v51.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path, value


def test_build_puts_all_native_modules_under_worker_parent(tmp_path: Path) -> None:
    source, _ = _fixture(tmp_path)
    output = tmp_path / "v52.json"
    result = V.build_forward(v51_request=source, output_request=output,
                             target_root=tmp_path / "new-target", output_root=tmp_path / "new-products")
    assert result["payload_read"] is False
    value = json.loads(output.read_text(encoding="utf-8"))
    plan = value["forward_v52"]["module_rebinding"]
    assert all(row["target_relative_path"].startswith("runtime/native/") for row in plan.values())
    assert all(row["worker_parent"] == str(tmp_path / "new-target/runtime/native") for row in plan.values())
    assert set(value["forward_v52"]["runtime_alias_roles"]) == {"copied_module_raw_converter", "copied_module_v14_operator", "copied_module_v15_operator", "copied_module_v16_operator"}
    assert value["execution"]["command"][3].endswith("ds_data02_stage2_f2_portable_executor_v52.py")


def test_v38_materialize_aliases_accepts_exact_copied_worker_parent(tmp_path: Path) -> None:
    source, _ = _fixture(tmp_path)
    v52 = tmp_path / "v52.json"
    V.build_forward(v51_request=source, output_request=v52,
                    target_root=tmp_path / "new-target", output_root=tmp_path / "new-products")
    value = json.loads(v52.read_text(encoding="utf-8"))
    worker_parent = tmp_path / "new-target/runtime/native"
    worker_parent.mkdir(parents=True)
    bindings = {}
    payloads = {"raw_converter": b"raw-converter", "v14_operator": b"v14-operator",
                "v15_operator": b"v15-operator", "v16_operator": b"v16-operator"}
    for role, row in value["forward_v52"]["module_rebinding"].items():
        target = Path(row["target_path"])
        target.write_bytes(payloads[role])
        bindings[role] = {"path": str(target), "sha256": row["expected_sha256"], "bytes": row["expected_bytes"]}
    v38 = _load(V38_SCRIPT, "test_v38_alias_guard")
    records = v38._materialize_aliases(bindings, worker_parent)
    # V38's canonical alias guard covers the three operator modules.  The
    # converter is retained in the same worker-parent directory for the V40
    # import chain, but V38 does not make a canonical converter alias.
    assert len(records) == 3
    assert all(Path(item["copied_source_path"]).parent == worker_parent for item in records)
    assert all(item["state"] == "ALREADY_CANONICAL" for item in records)
    assert Path(value["forward_v52"]["module_rebinding"]["raw_converter"]["target_path"]).parent == worker_parent


def test_v52_rejects_reusing_v51_namespace(tmp_path: Path) -> None:
    source, _ = _fixture(tmp_path)
    with pytest.raises(V.PortableV52Error, match="reuse V51 namespace"):
        V.build_forward(v51_request=source, output_request=tmp_path / "out.json",
                        target_root=tmp_path / "old-target", output_root=tmp_path / "new-products")
