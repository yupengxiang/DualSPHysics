from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import os

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_canonical_raw_anchor_rebind_v1.py"
SPEC = importlib.util.spec_from_file_location("f2_canonical_rebind_v1_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"st_dev": int(value.st_dev), "st_ino": int(value.st_ino),
            "st_size": int(value.st_size), "st_mtime_ns": int(value.st_mtime_ns),
            "st_ctime_ns": int(value.st_ctime_ns),
            "mode_bits": int(value.st_mode & 0o7777)}


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    old = tmp_path / "old-source"
    namespace = tmp_path / "attempt" / "bundle"
    old.mkdir()
    namespace.mkdir(parents=True)
    old_raw = old / "raw"
    new_raw = namespace / "raw"
    old_raw.mkdir()
    new_raw.mkdir()
    module_roles = list(MODULE.MODULE_ROLES)
    old_modules = {}
    new_modules = {}
    for role in module_roles:
        old_path = old / (role + ".py")
        old_path.write_text("# bound " + role + "\n", encoding="utf-8")
        new_path = namespace / (role + ".py")
        new_path.write_bytes(old_path.read_bytes())
        old_modules[role] = {"path": str(old_path), "sha256": _sha(old_path)}
        new_modules[role] = {"path": str(new_path), "sha256": _sha(old_path),
                             "target_stat": _stat(new_path),
                             "content_status": "PARENT_GUARD_REQUIRED"}
    decoder_old = old / "decoder"
    decoder_old.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    decoder_new = namespace / "decoder"
    decoder_new.write_bytes(decoder_old.read_bytes())
    decoder_new.chmod(0o755)
    decoder = {"path": str(decoder_new), "sha256": _sha(decoder_old),
               "target_stat": _stat(decoder_new), "content_status": "PARENT_GUARD_REQUIRED"}

    old_sources = []
    new_sources = []
    for index, role in enumerate(MODULE.REQUIRED_SOURCE_ROLES):
        old_path = old / (role + ".json")
        old_path.write_text(json.dumps({"role": role, "index": index}) + "\n", encoding="utf-8")
        new_path = namespace / (role + ".json")
        new_path.write_bytes(old_path.read_bytes())
        old_sources.append({"role": role, "path": str(old_path), "sha256": _sha(old_path),
                            "bytes": old_path.stat().st_size})
        new_sources.append({"role": role, "path": str(new_path), "sha256": _sha(old_path),
                            "target_stat": _stat(new_path), "content_status": "PARENT_GUARD_REQUIRED"})

    old_frames = []
    new_frames = []
    for index in range(2):
        old_path = old_raw / f"Part_{index:04d}.bi4"
        old_path.write_bytes((f"frame-{index}\n").encode())
        new_path = new_raw / old_path.name
        new_path.write_bytes(old_path.read_bytes())
        old_frames.append({"frame": index, "path": str(old_path), "bytes": old_path.stat().st_size,
                           "sha256": MODULE.PENDING})
        new_frames.append({"frame": index, "path": str(new_path), "sha256": MODULE.PENDING,
                           "target_stat": _stat(new_path), "content_status": "PARENT_GUARD_REQUIRED"})
    old_request = {
        "schema": MODULE.REQUEST_SCHEMA,
        "request_id": "old-request",
        "role": "DEVELOPMENT", "status": "PENDING_PARENT_GUARD",
        "case_identity": {"current_case_index": 65, "family_id": "F2",
                           "manifest_case_id": "canonical", "physical_case_id": "canonical"},
        "modules": old_modules, "source_files": old_sources,
        "raw_binding": {"data_root": str(old_raw), "frames": old_frames,
                         "expected_raw_tree_sha256": MODULE.PENDING,
                         "expected_file_count": 2},
        "source_hashes_preverified_by_parent": False,
        "model_invoked": False, "cfd_invoked": False,
        "qualification": dict(MODULE.UNKNOWN if hasattr(MODULE, "UNKNOWN") else {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}),
        "current_binding": {"path": str(old / "CURRENT336.json"), "sha256": "a" * 64},
        "execution": {"python": "/old/python", "command_template": ["/old/python", "-I", "<worker>"]},
        "v15_request": {"status": "PARENT_GUARD_SOURCE_REBIND_REQUIRED",
                         "source_fallback": "REJECT", "input_files": [str(old / "v15.json")]},
    }
    plan = {
        "schema": MODULE.PLAN_SCHEMA,
        "selection": {"current_index": 65, "physical_case_id": "canonical"},
        "raw_binding": {"expected_raw_tree_sha256": MODULE.PENDING},
        "request_overlay": {"request": old_request},
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    binding = {
        "schema": MODULE.BINDING_SCHEMA,
        "namespace_root": str(namespace),
        "request_id": "rebound-request",
        "python_executable": "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
        "modules": new_modules,
        "source_files": new_sources,
        "raw_binding": {"data_root": str(new_raw), "frames": new_frames,
                         "expected_raw_tree_sha256": MODULE.PENDING,
                         "expected_file_count": 2},
        "decoder": decoder,
        "v15_request": {"status": "PARENT_GUARD_SOURCE_REBIND_REQUIRED",
                         "source_fallback": "REJECT",
                         "input_files": [str(namespace / "v15.json")]},
    }
    binding_path = tmp_path / "binding.json"
    binding_path.write_text(json.dumps(binding, indent=2) + "\n", encoding="utf-8")
    return plan_path, binding_path, namespace


def test_rebind_emits_new_parent_namespace_request_and_keeps_hashes_deferred(tmp_path: Path) -> None:
    plan, binding, namespace = _fixture(tmp_path)
    output = tmp_path / "out"
    report = MODULE.rebind(plan_path=plan, binding_path=binding, output_dir=output)
    assert report["status"] == "PENDING_PARENT_GUARD"
    request = json.loads((output / "f2-s1-canonical-rebound-request-v1.json").read_text())
    assert request["status"] == "PENDING_PARENT_GUARD"
    assert request["source_hashes_preverified_by_parent"] is False
    assert request["execution"]["old_root_open"] == "FORBIDDEN"
    assert request["execution"]["python"].endswith("/.venv/bin/python")
    assert all(Path(item["path"]).is_relative_to(namespace) for item in request["source_files"])
    assert all(Path(item["path"]).is_relative_to(namespace) for item in request["modules"].values())
    assert request["raw_binding"]["expected_raw_tree_sha256"] == MODULE.PENDING
    assert json.loads((output / "f2-s1-canonical-rebound-report-v1.json").read_text())["content_contract"]["scientific_payload_read_by_rebinder"] is False


def test_rebind_rejects_missing_role_and_outside_namespace(tmp_path: Path) -> None:
    plan, binding, _namespace = _fixture(tmp_path)
    value = json.loads(binding.read_text())
    value["source_files"] = [item for item in value["source_files"] if item["role"] != "motion_dat"]
    missing = tmp_path / "missing.json"
    missing.write_text(json.dumps(value))
    with pytest.raises(MODULE.RebindError, match="complete F2 source role"):
        MODULE.rebind(plan_path=plan, binding_path=missing, output_dir=tmp_path / "missing-out")

    value = json.loads(binding.read_text())
    value["modules"]["worker"]["path"] = str(tmp_path / "outside-worker.py")
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(value))
    with pytest.raises(MODULE.RebindError, match="escapes the copied namespace"):
        MODULE.rebind(plan_path=plan, binding_path=outside, output_dir=tmp_path / "outside-out")


def test_rebind_rejects_actionable_v15_path_fallback(tmp_path: Path) -> None:
    plan, binding, _namespace = _fixture(tmp_path)
    value = json.loads(binding.read_text())
    value["v15_request"]["input_files"] = ["/old/worktree/old-v15.json"]
    bad = tmp_path / "bad-v15.json"
    bad.write_text(json.dumps(value))
    with pytest.raises(MODULE.RebindError, match="v15_request retains an actionable path"):
        MODULE.rebind(plan_path=plan, binding_path=bad, output_dir=tmp_path / "bad-out")
