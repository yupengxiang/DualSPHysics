"""Source-only tests for the V51 post-terminal parent hand-off."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_v50_postterminal_guard_request_v1.py"


def _load():
    spec = importlib.util.spec_from_file_location("test_v50_postterminal_guard", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V = _load()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    literal_python = "/opt/lagrangian-fluid-lab/.venv/bin/python"
    roles = [
        ("raw_converter", "sources/0025-converter.py", "raw-converter"),
        ("v14_operator", "sources/0026-v14.py", "v14"),
        ("v15_operator", "sources/0027-v15.py", "v15"),
        ("v16_operator", "sources/0028-v16.py", "v16"),
    ]
    plan = {}
    for module_role, relative, text in roles:
        data = text.encode()
        plan[module_role] = {
            "module_role": module_role,
            "source_role": module_role,
            "source_path_provenance": f"/original/worktree/{Path(relative).name}",
            "target_relative_path": relative,
            "expected_sha256": hashlib.sha256(data).hexdigest(),
            "expected_bytes": len(data),
            "source_path_fallback": "FORBIDDEN",
        }
    executor = {
        "schema": V.V34_SCHEMA,
        "status": "READY_FOR_PARENT_STAGE2_GUARD",
        "role": "DEVELOPMENT",
        "request_id": "fixture-v50",
        "family_id": "F2",
        "case_id": "fixture-case",
        "model_invoked": False,
        "cfd_invoked": False,
        "raw_opened": False,
        "hdf5_opened": False,
        "qualification": dict(V.UNKNOWN),
        "fresh_roots": {"target_root": str(tmp_path / "old-target"),
                         "output_root": str(tmp_path / "old-output")},
        "runtime_sources": [{
            "role": "python_executable", "path": literal_python,
            "resolved_source_path": "/usr/bin/python3.10",
            "target_relative_path": "runtime/python/.venv-python",
            "bytes": 5941864, "sha256": "a" * 64, "required_executable": True,
        }],
        "source_entries": [],
        "forward_v51": {"schema": V.V51_SCHEMA, "module_rebinding": plan},
        "execution": {"command": [literal_python, "-B", "-I", "old-v45.py", "run"]},
    }
    executor["sha256"] = V.canonical_sha(executor)
    parent = {
        "schema": V.PARENT_SCHEMA,
        "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT",
        "family_id": "F2",
        "case_id": "fixture-case",
        "qualification": dict(V.UNKNOWN),
        "static_bindings": [],
        "parent_resource_binding": {"same_parent_ledger": True, "ledger_reset": False,
                                     "no_new_data_root": True, "storage_policy": "home_free_floor"},
        "storage_scope": {"source_copy_bytes": 1000, "declared_typed_output_budget_bytes": 2000,
                           "declared_decoder_scratch_bytes": 3000, "external_filesystem": "/var/tmp",
                           "external_reservation_bytes": 4000, "home_min_free_bytes": 500,
                           "supervisor_output_root": str(tmp_path / "old-supervisor")},
    }
    parent["sha256"] = V.canonical_sha(parent)
    preflight = {
        "schema": V.PREFLIGHT_SCHEMA,
        "status": "ACTUAL_PARENT_V3_METADATA_VALIDATOR_PASS",
        "array_payload_read": False,
        "qualification_credit": "NONE",
        "content_hash_phase": "AFTER_ATOMIC_PARENT_RESERVATION",
        "request_binding": {"executor_request_sha256": executor["sha256"],
                             "parent_request_sha256": parent["sha256"]},
    }
    epath = tmp_path / "executor.json"; epath.write_text(json.dumps(executor), encoding="utf-8")
    ppath = tmp_path / "parent.json"; ppath.write_text(json.dumps(parent), encoding="utf-8")
    qpath = tmp_path / "preflight.json"; qpath.write_text(json.dumps(preflight), encoding="utf-8")
    return epath, ppath, qpath


def test_build_preserves_copied_module_paths_and_pending_products(tmp_path: Path) -> None:
    executor, parent, preflight = _fixture(tmp_path)
    target = tmp_path / "new-target"
    products = tmp_path / "new-products"
    output = tmp_path / "handoff.json"
    result = V.build_request(executor_request=executor, parent_request=parent,
                             v50_preflight=preflight, target_root=target,
                             output_root=products, output=output)
    assert result["payload_read"] is False
    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["status"] == "READY_FOR_PARENT_POSTTERMINAL_GUARD"
    assert value["qualification"] == V.UNKNOWN
    assert value["copied_module_import_contract"]["module_paths"]["v14_operator"]["target_path"] == str(target / "sources/0026-v14.py")
    assert value["copied_module_import_contract"]["module_paths"]["v14_operator"]["source_path_fallback"] == "FORBIDDEN"
    assert value["runtime_closure"]["literal_interpreter"]["argv0"].endswith(".venv/bin/python")
    roles = [row["role"] for row in value["runtime_closure"]["roles"]]
    assert len(roles) == len(set(roles))
    assert value["artifacts"]["new_typed_hdf5"] == {"status": "PENDING", "path": None, "sha256": None}
    assert value["execution"]["postterminal_commands"]["evaluator_adapter"]["model_invoked"] is False
    copied = {row["role"]: row for row in value["copied_metadata_inputs"]}
    assert copied["v51_executor_request"]["source_path_fallback"] == "FORBIDDEN"
    closure_cmd = value["execution"]["postterminal_commands"]["runtime_closure"]["command_template"]
    assert closure_cmd[closure_cmd.index("--executor-request") + 1] == copied["v51_executor_request"]["target_path"]
    assert not target.exists() and not products.exists()


def test_rejects_failed_v50_namespace_reuse(tmp_path: Path) -> None:
    executor, parent, preflight = _fixture(tmp_path)
    with pytest.raises(V.PostterminalRequestError, match="reuse the failed V50 namespace"):
        V.build_request(executor_request=executor, parent_request=parent,
                        v50_preflight=preflight, target_root=tmp_path / "old-target",
                        output_root=tmp_path / "new-products", output=tmp_path / "handoff.json")


def test_rejects_direct_v50_without_v51_module_rebinding(tmp_path: Path) -> None:
    executor, parent, preflight = _fixture(tmp_path)
    value = json.loads(executor.read_text(encoding="utf-8"))
    value.pop("forward_v51")
    value["sha256"] = V.canonical_sha(value)
    executor.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(V.PostterminalRequestError, match="V51 copied-module forward marker"):
        V.build_request(executor_request=executor, parent_request=parent,
                        v50_preflight=preflight, target_root=tmp_path / "new-target",
                        output_root=tmp_path / "new-products", output=tmp_path / "handoff.json")


def test_rejects_existing_output_namespace(tmp_path: Path) -> None:
    executor, parent, preflight = _fixture(tmp_path)
    target = tmp_path / "new-target"; target.mkdir()
    with pytest.raises(V.PostterminalRequestError, match="namespace must not already exist"):
        V.build_request(executor_request=executor, parent_request=parent,
                        v50_preflight=preflight, target_root=target,
                        output_root=tmp_path / "new-products", output=tmp_path / "handoff.json")
