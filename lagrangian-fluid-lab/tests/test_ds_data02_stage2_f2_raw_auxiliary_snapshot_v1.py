from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_raw_auxiliary_snapshot_v1.py"
SPEC = importlib.util.spec_from_file_location("f2_raw_auxiliary_snapshot_v1", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)
V37_SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_portable_executor_v37.py"
V37_SPEC = importlib.util.spec_from_file_location("f2_portable_executor_v37", V37_SCRIPT)
assert V37_SPEC is not None and V37_SPEC.loader is not None
v37 = importlib.util.module_from_spec(V37_SPEC)
V37_SPEC.loader.exec_module(v37)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, str]:
    root = tmp_path / "producer" / "solver_output" / "data"
    root.mkdir(parents=True)
    frame_records = []
    frozen_bindings = []
    for index in range(worker.FRAME_COUNT):
        path = root / f"Part_{index:04d}.bi4"
        path.write_bytes(f"frame-{index}".encode())
        digest = _sha(path)
        frame_records.append({"path": path.name, "bytes": path.stat().st_size, "sha256": digest})
        frozen_bindings.append({
            "role": "raw_frame_input", "original_path": str(path),
            "bytes": path.stat().st_size, "content_sha256": digest,
        })
    aux_entries = []
    for name in worker.AUX_NAMES:
        path = root / name
        path.write_bytes(f"aux-{name}".encode())
        aux_entries.append({
            "filename": name, "path": str(path), "bytes": path.stat().st_size,
            "sha256": worker.PENDING,
        })
    tree_sha = worker.canonical_hash(sorted(frame_records + [
        {"path": item["filename"], "bytes": item["bytes"], "sha256": _sha(root / item["filename"])}
        for item in aux_entries
    ], key=lambda item: item["path"]))
    v2 = {
        "schema": worker.V2_SCHEMA, "case_identity": {"case_index": 78},
        "cohort": {"count": 21114, "identity_axis": ["Zone", "Idp"]},
        "raw_binding": {
            "data_root": str(root), "expected_file_count": 405,
            "expected_raw_tree_sha256": tree_sha, "frame_count": 401,
            "frame_pattern": "Part_%04d.bi4", "frames": [
                {"frame": i, "path": str(root / f"Part_{i:04d}.bi4"),
                 "bytes": (root / f"Part_{i:04d}.bi4").stat().st_size,
                 "sha256": worker.PENDING}
                for i in range(worker.FRAME_COUNT)
            ],
        },
        "resource_request": {"max_wall_seconds": 3600, "max_cpu_core_hours": 2.0},
    }
    v2_path = tmp_path / "v2-request.json"
    _write(v2_path, v2)
    bundle = {
        "schema": worker.V5_BUNDLE_SCHEMA, "role": "DEVELOPMENT",
        "qualification": dict(worker.UNKNOWN), "source_bindings": frozen_bindings,
        "raw_producer_binding": {
            "expected_file_count": 405, "expected_raw_tree_sha256": tree_sha,
            "frame_count": 401, "frame_pattern": "Part_%04d.bi4",
            "original_data_root": str(root),
        },
    }
    bundle["sha256"] = worker.canonical_hash(bundle)
    bundle_path = tmp_path / "v5-bundle.json"
    _write(bundle_path, bundle)
    aux = {
        "schema": worker.AUX_SCHEMA, "status": "PENDING_PARENT_GUARD_CONTENT_SHA256",
        "role": "DEVELOPMENT", "qualification": dict(worker.UNKNOWN),
        "content_read_during_build": False, "payload_hashes_computed": False,
        "source_data_root": str(root),
        "expected_raw_tree": {"file_count": 405, "tree_sha256": tree_sha},
        "entries": aux_entries,
    }
    aux["sha256"] = worker.canonical_hash(aux)
    aux_path = tmp_path / "aux-template.json"
    _write(aux_path, aux)
    return v2_path, bundle_path, aux_path, root, tree_sha


def test_build_request_joins_frozen_frames_without_payload_hashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    v2, bundle, aux, _, tree_sha = _fixture(tmp_path)
    real_hash = worker.sha256_file

    def no_bi4_hash(path: Path | str) -> str:
        assert Path(path).suffix != ".bi4"
        return real_hash(path)

    monkeypatch.setattr(worker, "sha256_file", no_bi4_hash)
    output = tmp_path / "snapshot-request.json"
    result = worker.build_request(v2_request=v2, v5_bundle=bundle,
                                  auxiliary_template=aux, output=output)
    assert result["content_read"] is False
    request = json.loads(output.read_text(encoding="utf-8"))
    assert len(request["frame_bindings"]) == 401
    assert len(request["auxiliary_bindings"]) == 4
    assert request["expected_raw_tree"]["expected_raw_tree_sha256"] == tree_sha
    assert request["sha256"] == worker.canonical_hash(request)


def test_preflight_is_stat_only_and_run_requires_parent_approval(tmp_path: Path,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    v2, bundle, aux, _, _ = _fixture(tmp_path)
    request_path = tmp_path / "request.json"
    worker.build_request(v2_request=v2, v5_bundle=bundle,
                         auxiliary_template=aux, output=request_path)
    real_hash = worker.sha256_file

    def no_bi4_hash(path: Path | str) -> str:
        assert Path(path).suffix != ".bi4"
        return real_hash(path)

    monkeypatch.setattr(worker, "sha256_file", no_bi4_hash)
    preflight_path = tmp_path / "preflight.json"
    report = worker.preflight(request_path, preflight_path)
    assert report["status"] == "READY_FOR_PARENT_IO_SLOT"
    assert report["payload_read"] is False
    with pytest.raises(worker.AuxiliarySnapshotError, match="io-slot-approved"):
        worker.run(request_path, tmp_path / "run.json", io_slot_approved=False)


def test_parent_approved_run_writes_complete_joined_aux_manifest(tmp_path: Path) -> None:
    v2, bundle, aux, source_root, tree_sha = _fixture(tmp_path)
    request_path = tmp_path / "request.json"
    worker.build_request(v2_request=v2, v5_bundle=bundle,
                         auxiliary_template=aux, output=request_path)
    output = tmp_path / "auxiliary-snapshot.json"
    report = worker.run(request_path, output, io_slot_approved=True, parent_pid=os.getpid())
    assert report["status"] == "COMPLETE_PARENT_GUARDED"
    assert report["schema"] == worker.AUX_SCHEMA
    assert report["snapshot_schema"] == worker.REPORT_SCHEMA
    assert report["expected_raw_tree"] == {
        "file_count": 405, "tree_sha256": tree_sha,
    }
    assert report["raw_manifest"]["file_count"] == 405
    assert report["raw_manifest"]["tree_sha256"] == tree_sha
    assert len(report["frozen_frame_manifest"]) == 401
    assert len(report["entries"]) == 4
    assert report["stat_pre_post"]["stable"] is True
    assert report["execution_boundary"]["hdf5_opened"] is False
    assert report["sha256"] == worker.canonical_hash(report)
    accepted = v37._load_auxiliary_manifest(
        output,
        producer={"expected_file_count": 405, "expected_raw_tree_sha256": tree_sha},
        source_root=source_root,
    )
    assert len(accepted) == 4


def test_wrong_expected_tree_preserves_failed_snapshot_and_no_success_credit(tmp_path: Path) -> None:
    v2, bundle, aux, _, _ = _fixture(tmp_path)
    request_path = tmp_path / "request.json"
    worker.build_request(v2_request=v2, v5_bundle=bundle,
                         auxiliary_template=aux, output=request_path)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["expected_raw_tree"]["expected_raw_tree_sha256"] = "b" * 64
    request["sha256"] = worker.canonical_hash(request)
    wrong_request = tmp_path / "wrong-request.json"
    _write(wrong_request, request)
    output = tmp_path / "failed-snapshot.json"
    report = worker.run(wrong_request, output, io_slot_approved=True, parent_pid=os.getpid())
    assert report["status"] == "FAILED_PARENT_GUARDED_SNAPSHOT"
    assert "joined raw tree SHA differs" in report["error"]
    assert report["qualification"] == worker.UNKNOWN
