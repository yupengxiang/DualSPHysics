#!/usr/bin/env python3
"""Synthetic contract tests; no production receipt or HDF5 payload is read."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile


HERE = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


W = load_module("fresh073_worker", HERE / "artifact_integrity_worker.py")
G = load_module("fresh073_gate", HERE / "recovery_aware_pipeline_gate.py")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def build_fixture(root: Path) -> dict[str, Path | str | int]:
    h5 = root / "trajectory.h5"
    h5.write_bytes(b"opaque-test-bytes; no dataset decoding\n")
    output_hash = digest(h5)
    physical_case = "F3_TWOAXIS_PITCH1000_AY0270_STAGE1_FIRST24_NEW"
    physical_condition = "a6a7dfcc6a3c45b895ae096d652c4bf4d203b6b3b9d228e40c7c7518e8d109e9"
    report_condition = "217fbe56b0a884a75199c2aabef347872558260395688dcaee30c0c9a3719413"
    receipt = root / "execution-receipt.json"
    report = root / "conversion-report.json"
    stdout = root / "stdout.log"
    native = root / "native-receipt.json"
    write_json(receipt, {
        "schema": "ds02.execution-receipt.v1",
        "status": "running",
        "returncode": None,
        "request": {
            "attempt_id": "typed-154",
            "physical_case_id": physical_case,
            "physical_condition_sha256": physical_condition,
            "expected_saved_frames": 836,
        },
    })
    write_json(report, {
        "conversion_status": "completed",
        "conversion_claim": "streaming BI4 adapter evidence only; no Q-N or production claim",
        "frames": 836,
        "particles": 179208,
        "output_sha256": output_hash,
        "output_hdf5": str(h5),
        "partvtk_validation": {"all_passed": True},
        "storage_protocol": {"verified_published_output_sha256": output_hash},
        "hash_scopes": {
            "physical_condition": {"physical_case_id": physical_case},
            "physical_condition_sha256": report_condition,
        },
    })
    stdout.write_text(f"published output sha256={output_hash}\n", encoding="utf-8")
    write_json(native, {
        "status": "completed",
        "returncode": 0,
        "request": {
            "physical_case_id": physical_case,
            "physical_condition_sha256": physical_condition,
            "expected_saved_frames": 836,
        },
    })
    return {
        "receipt": receipt, "report": report, "stdout": stdout,
        "h5": h5, "native": native, "physical_case": physical_case,
        "physical_condition": physical_condition,
        "report_condition": report_condition,
        "frames": 836, "particles": 179208, "output_hash": output_hash,
    }


def audit_fixture(fixture: dict) -> dict:
    result = W.audit(
        receipt_path=fixture["receipt"],
        report_path=fixture["report"],
        stdout_path=fixture["stdout"],
        trajectory_path=fixture["h5"],
        native_receipt_path=fixture["native"],
        expected_receipt_sha256=digest(fixture["receipt"]),
        expected_report_sha256=digest(fixture["report"]),
        expected_native_receipt_sha256=digest(fixture["native"]),
        expected_output_sha256=fixture["output_hash"],
        expected_report_physical_condition_sha256=fixture["report_condition"],
        expected_frames=fixture["frames"],
        expected_particles=fixture["particles"],
        physical_case_id=fixture["physical_case"],
        physical_condition_sha256=fixture["physical_condition"],
        old_tool_status=143,
    )
    assert result["worker_returncode"] == 0
    assert result["source_conversion_lifecycle"]["receipt_returncode"] is None
    assert result["source_conversion_lifecycle"]["source_conversion_reclassified"] is False
    assert result["source_receipt_edited"] is False
    return result


def test_independent_audit_and_lifecycle_gate() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        fixture = build_fixture(root)
        audit = audit_fixture(fixture)
        audit_path = root / "artifact-integrity-audit.json"
        write_json(audit_path, audit)
        for stage in ("normal", "export", "render"):
            binding = G.prepare(
                stage=stage,
                source_receipt_path=fixture["receipt"],
                report_path=fixture["report"],
                audit_path=audit_path,
                native_receipt_path=fixture["native"],
                physical_case_id=fixture["physical_case"],
                physical_condition_sha256=fixture["physical_condition"],
                expected_frames=fixture["frames"],
                expected_particles=fixture["particles"],
            )
            assert binding["output_contract"]["status"] == "prepared_disabled"
            assert binding["source_conversion_lifecycle"]["receipt_returncode"] is None
            assert binding["source_conversion_lifecycle"]["converter_completed_claim"] is False
            assert binding["independent_artifact_audit"]["worker_returncode"] == 0


def test_interrupted_unfinalized_allowed_but_converter_completed_rejected() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        fixture = build_fixture(root)
        audit = audit_fixture(fixture)
        audit_path = root / "artifact-integrity-audit.json"
        write_json(audit_path, audit)
        source = json.loads(fixture["receipt"].read_text())
        source["status"] = "interrupted_unfinalized"
        write_json(fixture["receipt"], source)
        binding = G.prepare(
            stage="normal",
            source_receipt_path=fixture["receipt"],
            report_path=fixture["report"],
            audit_path=audit_path,
            native_receipt_path=fixture["native"],
            physical_case_id=fixture["physical_case"],
            physical_condition_sha256=fixture["physical_condition"],
            expected_frames=fixture["frames"],
            expected_particles=fixture["particles"],
        )
        assert binding["source_conversion_lifecycle"]["receipt_status"] == "interrupted_unfinalized"
        source["status"] = "completed"
        source["returncode"] = 0
        write_json(fixture["receipt"], source)
        try:
            G.prepare(
                stage="normal",
                source_receipt_path=fixture["receipt"],
                report_path=fixture["report"],
                audit_path=audit_path,
                native_receipt_path=fixture["native"],
                physical_case_id=fixture["physical_case"],
                physical_condition_sha256=fixture["physical_condition"],
                expected_frames=fixture["frames"],
                expected_particles=fixture["particles"],
            )
        except G.PipelineGateError as error:
            assert "lifecycle" in str(error)
        else:
            raise AssertionError("converter completed/0 was incorrectly accepted")


def test_source_package_contains_no_payload_artifact() -> None:
    assert not any(
        path.is_file() and path.suffix.lower() in {".h5", ".bi4", ".csv", ".npy", ".npz"}
        for path in HERE.rglob("*")
    )


def main() -> int:
    test_independent_audit_and_lifecycle_gate()
    test_interrupted_unfinalized_allowed_but_converter_completed_rejected()
    test_source_package_contains_no_payload_artifact()
    print("fresh073 semantic contract: PASS (independent audit0, null source returncode, interrupted lifecycle allowed, converter completion rejected)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
