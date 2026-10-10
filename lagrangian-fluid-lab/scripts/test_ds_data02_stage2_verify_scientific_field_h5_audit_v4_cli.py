#!/usr/bin/env python3
"""Genuine V3-worker -> bounded V4-verifier tests.

The HDF5 is a tiny TEST_ONLY fixture.  Producer metadata is emitted in the
same terminal-proof/request/receipt/case-manifest/summary shape as the actual
producer chain, but it carries no production or scientific credit.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
WORKER = HERE / "ds_data02_stage2_scientific_field_h5_audit_v3.py"
VERIFIER = HERE / "ds_data02_stage2_verify_scientific_field_h5_audit_v4.py"
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
CURRENT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/CURRENT336.json")
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"

BASE_SPEC = importlib.util.spec_from_file_location("v3_fixture_helpers", HERE / "test_ds_data02_stage2_scientific_field_h5_audit_v3_cli.py")
assert BASE_SPEC and BASE_SPEC.loader
BASE = importlib.util.module_from_spec(BASE_SPEC)
BASE_SPEC.loader.exec_module(BASE)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stat(path: Path) -> dict[str, object]:
    value = path.stat()
    return {"path": str(path.resolve()), "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns), "st_dev": int(value.st_dev), "st_ino": int(value.st_ino)}


def write_metadata_chain(directory: Path, h5_path: Path) -> Path:
    current = json.loads(CURRENT.read_text(encoding="utf-8"))
    current_row = current["cases"][0]
    case_id = current_row["physical_case_id"]
    family_id = current_row["family_id"]
    h5_ref = {**stat(h5_path), "role": "trajectory_h5", "known_sha256": sha256(h5_path), "deferred_after_parent_reservation": True, "content_read_by_preparer": False}

    def write_json(name: str, value: dict) -> dict:
        path = directory / name
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {**stat(path), "role": name, "sha256": sha256(path), "content_read_by_preparer": True}

    case_manifest_path = directory / "case-manifest.json"
    case_manifest = {
        "schema": "ds02.stage2.typed-lifecycle-sidecar-manifest.v4",
        "status": "READY_FOR_GUARDED_TYPED_LIFECYCLE",
        "physical_case_id": case_id, "family_id": family_id,
        "current_catalog": {"path": str(CURRENT), "sha256": CURRENT_SHA},
        "trajectory_h5": {"path": str(h5_path), "sha256": h5_ref["known_sha256"]},
    }
    case_manifest_path.write_text(json.dumps(case_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    case_manifest_ref = {**stat(case_manifest_path), "role": "case_manifest", "sha256": sha256(case_manifest_path), "content_read_by_preparer": True}
    case_receipt_path = directory / "case-receipt.json"
    case_receipt = {
        "schema": "ds02.stage2.typed-lifecycle-case-receipt.v1", "status": "COMPLETED",
        "physical_case_id": case_id, "family_id": family_id,
        "case_manifest": str(case_manifest_path), "case_manifest_sha256": case_manifest_ref["sha256"],
    }
    case_receipt_path.write_text(json.dumps(case_receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    case_receipt_ref = {**stat(case_receipt_path), "role": "producer_receipt", "sha256": sha256(case_receipt_path), "content_read_by_preparer": True}
    summary_path = directory / "summary.json"
    summary = {"schema": "ds02.stage2.typed-lifecycle-sidecar.v4", "status": "COMPLETED_TYPED_LIFECYCLE_NO_PHYSICAL_CREDIT", "physical_case_id": case_id, "family_id": family_id}
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_ref = {**stat(summary_path), "role": "typed_summary", "sha256": sha256(summary_path), "content_read_by_preparer": True}

    batch_manifest_path = directory / "batch-manifest.json"
    batch_manifest = {"schema": "ds02.stage2.typed-lifecycle-batch.v1", "cases": [{"physical_case_id": case_id, "family_id": family_id}]}
    batch_manifest_path.write_text(json.dumps(batch_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    batch_manifest_sha = sha256(batch_manifest_path)
    request_path = directory / "request.json"
    request = {"schema": "ds02.request.v1", "physical_case_ids": [case_id], "case_id": "TEST_ONLY_BATCH"}
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    request_sha = sha256(request_path)
    execution_receipt_path = directory / "execution-receipt.json"
    execution_receipt = {"schema": "ds02.execution-receipt.v1", "status": "COMPLETED", "returncode": 0}
    execution_receipt_path.write_text(json.dumps(execution_receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    execution_receipt_sha = sha256(execution_receipt_path)
    proof = {
        "schema": "ds02.stage2.root-actual-verification.v1", "status": "VERIFIED_ACTUAL_TEST_ONLY",
        "counts": {"cases_requested": 1, "completed": 1, "failed": 0},
        "request": str(request_path), "request_sha256": request_sha,
        "receipt": str(execution_receipt_path), "receipt_sha256": execution_receipt_sha,
        "manifest": str(batch_manifest_path), "manifest_sha256": batch_manifest_sha,
        "case_verifications": [{
            "physical_case_id": case_id, "family_id": family_id, "status": "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY",
            "case_manifest": str(case_manifest_path), "case_manifest_sha256": case_manifest_ref["sha256"],
            "receipt": str(case_receipt_path), "receipt_sha256": case_receipt_ref["sha256"],
            "summary": str(summary_path), "summary_sha256": summary_ref["sha256"],
            "source_trajectory": {"path": str(h5_path), "known_sha256": h5_ref["known_sha256"]},
        }],
    }
    proof_path = directory / "terminal-proof.json"
    proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    proof_ref = {**stat(proof_path), "role": "producer_terminal_proof", "sha256": sha256(proof_path), "content_read_by_preparer": True}

    static_refs = [
        {**stat(CURRENT), "role": "current336", "sha256": CURRENT_SHA, "content_read_by_preparer": True},
        proof_ref, case_manifest_ref, case_receipt_ref, summary_ref,
    ]
    manifest = {
        "schema": "ds02.stage2.scientific-field-h5-audit-manifest.v2",
        "status": "READY_FOR_GUARDED_RAW_H5_FIELD_AUDIT", "test_only_fixture_context": True,
        "current_catalog": {"path": str(CURRENT), "sha256": CURRENT_SHA, "cases": 336},
        "static_source_refs": static_refs,
        "cases": [{"physical_case_id": case_id, "family_id": family_id, "producer_terminal_proof": proof_ref, "case_manifest": case_manifest_ref, "producer_receipt": case_receipt_ref, "typed_summary": summary_ref, "trajectory_h5": h5_ref, "expected_frames": 3, "expected_particles": 4, "expected_units": BASE.UNITS}],
        "worker_contract": {"missing_field_policy": "per-field NOT_EXPOSED/UNKNOWN", "physical_range_policy": "diagnostic only"},
    }
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def run_cli(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(VENV), "-B", str(script), *args], text=True, capture_output=True, check=False)


class ScientificFieldH5AuditV4CliTests(unittest.TestCase):
    def test_test_only_worker_to_v4_verifier_requires_explicit_fixture_flag(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage2-field-v4-chain-") as raw:
            directory = Path(raw)
            h5_path = directory / "fixture.h5"
            BASE.write_h5(h5_path)
            manifest = write_metadata_chain(directory, h5_path)
            report = directory / "report.json"
            worker = run_cli(WORKER, "audit", "--manifest", str(manifest), "--output", str(report), "--chunk", "2")
            self.assertEqual(worker.returncode, 0, worker.stderr)
            rejected = run_cli(VERIFIER, "verify", "--manifest", str(manifest), "--report", str(report), "--output", str(directory / "rejected.json"))
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("TEST_ONLY fixture", rejected.stderr)
            accepted = run_cli(VERIFIER, "verify", "--manifest", str(manifest), "--report", str(report), "--output", str(directory / "verified.json"), "--allow-fixture-context")
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            value = json.loads((directory / "verified.json").read_text(encoding="utf-8"))
            self.assertEqual(value["schema"], "ds02.stage2.verify-scientific-field-h5-audit.v4")
            self.assertTrue(value["test_only_fixture_context"])
            self.assertFalse(value["production_eligible"])

    def test_static_payload_size_cap_is_rejected_before_hash_admission(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage2-field-v4-cap-") as raw:
            directory = Path(raw)
            h5_path = directory / "fixture.h5"
            BASE.write_h5(h5_path)
            manifest = write_metadata_chain(directory, h5_path)
            report = directory / "report.json"
            worker = run_cli(WORKER, "audit", "--manifest", str(manifest), "--output", str(report))
            self.assertEqual(worker.returncode, 0, worker.stderr)
            oversized = directory / "oversized.json"
            oversized.write_bytes(b"x" * (10 * 1024 * 1024 + 1))
            document = json.loads(manifest.read_text(encoding="utf-8"))
            document["static_source_refs"].append({**stat(oversized), "role": "oversized-control", "sha256": sha256(oversized)})
            manifest.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            result = run_cli(VERIFIER, "verify", "--manifest", str(manifest), "--report", str(report), "--output", str(directory / "bad.json"), "--allow-fixture-context")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("10 MiB", result.stderr)

    def test_scientific_payload_suffix_is_rejected_before_hash_admission(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage2-field-v4-suffix-") as raw:
            directory = Path(raw)
            h5_path = directory / "fixture.h5"
            BASE.write_h5(h5_path)
            manifest = write_metadata_chain(directory, h5_path)
            report = directory / "report.json"
            worker = run_cli(WORKER, "audit", "--manifest", str(manifest), "--output", str(report))
            self.assertEqual(worker.returncode, 0, worker.stderr)
            payload = directory / "small.jsonl"
            payload.write_text("{}\n", encoding="utf-8")
            document = json.loads(manifest.read_text(encoding="utf-8"))
            document["static_source_refs"].append({**stat(payload), "role": "payload", "sha256": sha256(payload)})
            manifest.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            result = run_cli(VERIFIER, "verify", "--manifest", str(manifest), "--report", str(report), "--output", str(directory / "bad.json"), "--allow-fixture-context")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("scientific payload", result.stderr)


if __name__ == "__main__":
    unittest.main()
