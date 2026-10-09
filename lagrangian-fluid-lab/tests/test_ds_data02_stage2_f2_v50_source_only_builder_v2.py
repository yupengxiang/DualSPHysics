"""Source-only tests for the split real parent-v3 terminal records."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import stat

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
BUILDER_PATH = SCRIPTS / "ds_data02_stage2_f2_v50_source_only_postterminal_builder_v3.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


B = _load(BUILDER_PATH, "test_v50_source_only_builder_v2")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    return path


def _bytes(path: Path, data: bytes = b"bounded source\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _canonical(value: dict) -> dict:
    value["sha256"] = B.canonical_sha(value)
    return value


def _binding(path: Path) -> dict:
    return {"path": str(path), "sha256": _sha(path), "bytes": path.stat().st_size,
            "stat": {"bytes": path.stat().st_size,
                     "mtime_ns": path.stat().st_mtime_ns,
                     "mode_bits": stat.S_IMODE(path.stat().st_mode)}}


def _fixture(tmp_path: Path) -> dict:
    executor = _canonical({
        "schema": "ds02.stage2.f2-portable-executor-request.v34",
        "execution": {"raw_tree_binding": {
            "tree_sha256": B.V1.RAW_TREE_SHA, "file_count": B.V1.RAW_TREE_FILES,
            "frame_count": B.V1.RAW_TREE_FRAMES}},
        "runtime_sources": [],
    })
    executor_path = _write(tmp_path / "requests" / "executor.json", executor)
    parent = _canonical({"schema": "ds02.stage2.f2-portable-executor-parent-request.v3",
                         "request_id": "split-parent"})
    parent_path = _write(tmp_path / "requests" / "parent.json", parent)
    preflight = _write(tmp_path / "requests" / "preflight.json", {
        "schema": "ds02.stage2.root.v50-metadata-preflight.v1",
        "status": "ACTUAL_PARENT_V3_METADATA_VALIDATOR_PASS",
        "array_payload_read": False, "qualification_credit": "NONE",
        "content_hash_phase": "AFTER_ATOMIC_PARENT_RESERVATION",
        "namespace_absent": True,
        "executor": {"request": str(executor_path), "request_sha256": _sha(executor_path)},
        "parent": {"parent_request": str(parent_path), "parent_physical_sha256": _sha(parent_path)},
    })
    namespace = tmp_path / "fresh"
    output = namespace / "products"
    output.mkdir(parents=True)
    source_contract = _write(namespace / "fresh-source-contract.json", _canonical({
        "schema": "ds02.stage2.f2-fresh-source-contract.v4",
        "expected": {"source_binding": {
            "current_catalog_sha256": "c" * 64,
            "binding_status": "RELOCATED_RUNTIME_CURRENT_VIEW_SOURCE_BOUND",
            "source_files": {"current_catalog": "c" * 64}}},
        "current_catalog_provenance": {
            "actual_current_catalog": {"sha256": B.V1.CURRENT_SHA},
            "relocated_runtime_view": {"sha256": "c" * 64}},
    }))
    relocated = _write(output / "relocated-v15.json", {"schema": "v15"})
    current = _write(output / "current-view.json", {"schema": "current"})
    engine = _write(output / "engine-report.json", {"schema": "engine", "status": "complete"})
    typed = _bytes(output / "typed.fixture", b"typed metadata fixture")
    v15 = _write(output / "v15.json", {"schema": "v15-result"})
    v16 = _write(output / "v16.json", {"schema": "v16-result"})
    converter = _write(output / "converter.json", {"schema": "converter"})
    worker = _write(namespace / "worker-report.json", {
        "schema": B.V1.WORKER_REPORT_SCHEMA,
        "status": "COMPLETE_DEVELOPMENT_UNKNOWN",
        "execution_boundary": {"raw_opened": True, "hdf5_opened": True,
                                "model_invoked": False, "cfd_invoked": False},
        "typed_output": _binding(typed),
        "typed_to_label": {
            "status": "V15_LABEL_REPLAY_COMPLETE_DEVELOPMENT_UNKNOWN",
            "result": str(v15), "result_sha256": _sha(v15),
            "v16_forward": {"status": "COMPLETE_DEVELOPMENT_UNKNOWN",
                             "result": str(v16), "result_sha256": _sha(v16)}},
        "raw_to_typed": {"converter_report": str(converter)},
    })
    attempt = "attempt-split"
    charge = "charge-split"
    home = {
        "schema": B.PARENT_REPORT_SCHEMA,
        "status": "COMPLETED_PARENT_EXECUTOR_RAW_TYPED_LABEL_UNKNOWN",
        "request": {"path": str(parent_path), "sha256": _sha(parent_path)},
        "executor": {"path": str(executor_path), "sha256": _sha(executor_path)},
        "execution": {"hard_wall_covers": ["metadata/stat preflight", "same-parent reservation",
                                             "v34 child copy/hash/worker/evaluator"]},
        "parent": {"same_parent_ledger": True, "attempt_id": attempt},
        "accounting": {"reservation_applied": True, "reservation_id": "reserve-split",
                        "attempt_id": attempt, "charge_id": charge,
                        "same_parent_ledger": True,
                        "charge_status_at_report_write": "pending_same_parent_charge"},
        "filesystem": {"external_bytes_before_parent_charge": 10, "trace_bytes": 2,
                        "copy_hash_bytes": 5},
        "model_invoked": False, "cfd_invoked": False,
    }
    home_path = _write(tmp_path / "parent-home-receipt.json", home)
    returned = {
        "schema": B.PARENT_REPORT_SCHEMA,
        "status": "COMPLETED_PARENT_EXECUTOR_RAW_TYPED_LABEL_UNKNOWN",
        "report_path": str(home_path), "request_sha256": _sha(parent_path),
        "ledger_mutated": True, "external_bytes": 10,
        "home_bytes": home_path.stat().st_size, "trace_bytes": 2,
        "copy_hash_bytes": 5, "model_invoked": False, "cfd_invoked": False,
        "charge": {"status": "PARENT_CHARGE_APPLIED", "ledger_mutated": True,
                   "charge": {"id": charge, "parent_attempt_id": attempt,
                              "status": "completed", "cpu_core_seconds": 1.25}},
    }
    returned_path = _write(tmp_path / "returned-parent-report.json", returned)
    pinned = _bytes(tmp_path / "runtime" / "worker.py", b"# pinned worker\n")
    return locals()


def test_split_parent_receipt_and_returned_report_are_cross_bound(tmp_path: Path) -> None:
    f = _fixture(tmp_path)
    static = tmp_path / "static.json"
    manifest = tmp_path / "manifest.json"
    result = B.build_terminal_inputs_split(
        executor_request=f["executor_path"], parent_request=f["parent_path"],
        preflight=f["preflight"], parent_receipt=f["home_path"],
        returned_parent_report=f["returned_path"], worker_report=f["worker"],
        source_contract=f["source_contract"], output_root=f["output"],
        namespace_root=f["namespace"], static_output=static,
        manifest_output=manifest, pinned_sources=[f"worker={f['pinned']}"],
        artifact_bindings=[f"current_runtime_view={f['current']}",
                           f"relocated_v15_request={f['relocated']}",
                           f"engine_report={f['engine']}"])
    static_value = json.loads(static.read_text(encoding="utf-8"))
    manifest_value = json.loads(manifest.read_text(encoding="utf-8"))
    assert result["derived_sidecar"] is True
    assert static_value["instrumented_receipt"] is False
    assert static_value["completed_parent_report"]["home_receipt"]["path"] == str(f["home_path"])
    assert static_value["completed_parent_report"]["returned_report"]["path"] == str(f["returned_path"])
    assert static_value["derivation"]["home_receipt_charge_status_at_write"] == "pending_same_parent_charge"
    assert manifest_value["terminal"]["charge_closed"] is True
    assert manifest_value["parent_terminal_evidence"]["returned_charge"]["id"] == "charge-split"


def test_split_builder_rejects_mixed_attempt_charge_report(tmp_path: Path) -> None:
    f = _fixture(tmp_path)
    mixed = json.loads(f["returned_path"].read_text(encoding="utf-8"))
    mixed["request_sha256"] = "0" * 64
    mixed_path = _write(tmp_path / "mixed-returned.json", mixed)
    with pytest.raises(B.BuilderV2Error, match="request SHA differs"):
        B._validate_returned_report(
            mixed_path, home_path=f["home_path"], parent_path=f["parent_path"],
            parent_sha=_sha(f["parent_path"]), expected_attempt="attempt-split",
            expected_charge="charge-split",
            home=json.loads(f["home_path"].read_text(encoding="utf-8")))


def test_split_builder_rejects_precharge_only_as_terminal_summary(tmp_path: Path) -> None:
    f = _fixture(tmp_path)
    precharge = json.loads(f["returned_path"].read_text(encoding="utf-8"))
    precharge["ledger_mutated"] = False
    precharge["charge"]["ledger_mutated"] = False
    precharge_path = _write(tmp_path / "precharge-returned.json", precharge)
    with pytest.raises(B.BuilderV2Error, match="ledger_mutated"):
        B._validate_returned_report(
            precharge_path, home_path=f["home_path"], parent_path=f["parent_path"],
            parent_sha=_sha(f["parent_path"]), expected_attempt="attempt-split",
            expected_charge="charge-split",
            home=json.loads(f["home_path"].read_text(encoding="utf-8")))
