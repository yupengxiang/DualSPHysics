from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_canonical65_executor_v1.py"
SPEC = importlib.util.spec_from_file_location("canonical65_executor_v1_test_module", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> Path:
    raw = tmp_path / "raw"
    raw.mkdir()
    for index in range(401):
        (raw / f"Part_{index:04d}.bi4").write_bytes(f"frame-{index}\n".encode())
    for name in ("PartInfo.ibi4", "PartOut_000.obi4", "Run.out", "Head.xml"):
        (raw / name).write_bytes(name.encode())

    converter = tmp_path / "raw_converter.py"
    converter.write_text(
        "from pathlib import Path\n"
        "import hashlib, json\n"
        "def raw_tree_manifest(root):\n"
        "    rows=[]\n"
        "    for p in sorted(Path(root).rglob('*')):\n"
        "        if p.is_file():\n"
        "            rows.append({'path': p.relative_to(root).as_posix(), 'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()})\n"
        "    tree=hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()\n"
        "    return {'schema':'fixture.raw-tree.v1','file_count':len(rows),'files':rows,'tree_sha256':tree}\n",
        encoding="utf-8",
    )
    modules: dict[str, Path] = {"raw_converter": converter}
    for name in ("v14_operator", "v15_operator", "v16_operator", "worker"):
        path = tmp_path / f"{name}.py"
        path.write_text(f"ROLE = {name!r}\n", encoding="utf-8")
        modules[name] = path
    decoder = tmp_path / "decoder"
    decoder.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    decoder.chmod(decoder.stat().st_mode | stat.S_IXUSR)
    sources: list[dict[str, str]] = []
    roles = (
        "current_catalog", "generated_xml", "motion_dat", "gencase_receipt",
        "solver_receipt", "owner_metadata", "initial_csv", "conversion_report",
        "native_partout", "native_runparts",
    )
    for role in roles:
        path = tmp_path / f"{role}.source"
        path.write_text(role, encoding="utf-8")
        sources.append({"role": role, "path": str(path)})
    current = tmp_path / "CURRENT336.json"
    current.write_text("{}\n", encoding="utf-8")
    phase: dict[str, object] = {
        "phase_request_schema": MODULE.PHASE_SCHEMA,
        "schema": MODULE.WORKER_SCHEMA,
        "status": MODULE.PENDING,
        "case_identity": {
            "current_case_index": 65,
            "physical_case_id": MODULE.CANONICAL_ID,
            "identity_status": "CANONICAL_CURRENT_SAVED_MASK",
        },
        "current_binding": {"sha256": MODULE.CURRENT_SHA, "path": str(current)},
        "raw_binding": {
            "data_root": str(raw), "expected_file_count": 405, "frame_count": 401,
            "expected_raw_tree_sha256": MODULE.PENDING,
            "frames": [{"path": f"Part_{index:04d}.bi4", "sha256": MODULE.PENDING}
                        for index in range(401)],
        },
        "source_hashes_preverified_by_parent": False,
        "worker_ready": False, "launch_allowed": False,
        "qualification": dict(MODULE.UNKNOWN),
        "source_files": sources,
        "modules": {role: {"path": str(path), "sha256": _sha(path)}
                    for role, path in modules.items()},
        "decoder": {"path": str(decoder), "sha256": _sha(decoder)},
        "request_id": "fixture-canonical65",
    }
    phase["phase_request_canonical_sha256"] = MODULE._phase_body_digest(phase)
    path = tmp_path / "phase.json"
    path.write_text(json.dumps(phase, sort_keys=True), encoding="utf-8")
    return path


def test_materialize_binds_all_sources_and_exact_raw_scope(tmp_path: Path) -> None:
    phase = _fixture(tmp_path)
    output = tmp_path / "attempt" / "canonical65-raw-to-typed"
    request_path, details = MODULE.materialize_worker_request(phase, output)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert request["schema"] == MODULE.WORKER_SCHEMA
    assert request["status"] == "READY_FOR_PARENT_GUARD"
    assert request["source_hashes_preverified_by_parent"] is True
    assert request["raw_binding"]["expected_raw_tree_sha256"] == details["raw_manifest"]["tree_sha256"]
    assert details["raw_manifest"]["file_count"] == 405
    assert len(request["source_files"]) == 10
    assert all(len(row["sha256"]) == 64 for row in request["source_files"])
    assert request["parent_materialization"]["reservation_before_content_hash"] is True


def test_build_emits_v10_light_validated_parent_request(tmp_path: Path) -> None:
    phase = _fixture(tmp_path)
    data_root = tmp_path / "data"
    data_root.mkdir()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    output = tmp_path / "parent-request.json"
    result = MODULE.build_request(
        phase_request=phase, output=output, repo_root=repo_root,
        data_root=data_root, runtime_v10=ROOT / "scripts" / "ds_data02_runtime_v10_git_bound.py",
        worker=tmp_path / "worker.py", attempt_id="fixture-parent",
    )
    assert result["status"] == "READY_FOR_PARENT_GUARD"
    assert result["worker_ready"] is True
    request = json.loads(output.read_text(encoding="utf-8"))
    runtime_path = ROOT / "scripts" / "ds_data02_runtime_v10_git_bound.py"
    runtime_spec = importlib.util.spec_from_file_location("canonical65_runtime_for_test", runtime_path)
    assert runtime_spec is not None and runtime_spec.loader is not None
    runtime = importlib.util.module_from_spec(runtime_spec)
    runtime_spec.loader.exec_module(runtime)
    runtime.v8._light_validate(request, data_root=data_root)
    assert request["data_root_binding"]["path"] == str(data_root.resolve())
    assert request["verifier_binding"]["schema"] == MODULE.VERIFY_SCHEMA
    assert len(request["input_files"]) >= 400


def test_phase_rejects_old_alias_even_when_digest_is_resealed(tmp_path: Path) -> None:
    phase = _fixture(tmp_path)
    value = json.loads(phase.read_text(encoding="utf-8"))
    value["case_identity"]["physical_case_id"] = MODULE.HISTORICAL_ALIAS_ID
    value["phase_request_canonical_sha256"] = MODULE._phase_body_digest(value)
    phase.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    with pytest.raises(MODULE.Canonical65Error, match="exact CURRENT row 65"):
        MODULE._phase(phase)


def test_phase_rejects_symlink_in_raw_scope(tmp_path: Path) -> None:
    phase = _fixture(tmp_path)
    raw = tmp_path / "raw"
    link = raw / "symlink.bi4"
    link.symlink_to(raw / "Part_0000.bi4")
    with pytest.raises(MODULE.Canonical65Error, match="symlink"):
        MODULE._phase(phase)
