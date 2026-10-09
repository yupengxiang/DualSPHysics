from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_build_generic_native_extract_v1.py"
ROOT256 = ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_build_root256_f6_typed_lifecycle_batch.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("generic_native_extract_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )


def test_generic_native_self_test_is_source_only() -> None:
    result = _run(SCRIPT, "self-test")
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "PASS"
    assert payload["launch_allowed"] is False
    assert payload["payload_opened"] is False
    assert "ROOT253/ROOT256 proof edge shapes" in payload["checks"]


def test_generic_prepare_accepts_root256_request_without_payload(tmp_path: Path) -> None:
    lifecycle_root = tmp_path / "lifecycle"
    lifecycle = _run(ROOT256, "prepare", "--output-root", str(lifecycle_root))
    assert lifecycle.returncode == 0, lifecycle.stderr + lifecycle.stdout
    lifecycle_payload = json.loads(lifecycle.stdout)

    output_root = tmp_path / "native"
    request_path = output_root / "generic-request.json"
    result = _run(
        SCRIPT,
        "prepare",
        "--namespace",
        "ROOT257",
        "--lifecycle-request",
        lifecycle_payload["request"],
        "--output-root",
        str(output_root),
        "--request-output",
        str(request_path),
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["family_id"] == "F6"
    assert payload["case_ids"] == lifecycle_payload["case_ids"]
    assert payload["terminal_proof_bound"] is False
    assert payload["launch_allowed"] is False
    manifest = json.loads(Path(payload["manifest"]).read_text(encoding="utf-8"))
    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert manifest["physical_case_ids"] == lifecycle_payload["case_ids"]
    assert manifest["official_sources"]["partvtkout"]["path"].startswith("/home/jade/Projects/DualSPHysics/")
    assert request["launch_allowed"] is False
    assert len(request["physical_case_ids"]) == len(set(request["physical_case_ids"]))
    forbidden = {".h5", ".hdf5", ".bi4", ".obi4", ".jsonl"}
    assert not any(Path(path).suffix.lower() in forbidden for path in request["input_files"])


def test_generic_proof_adapter_requires_unique_exact_case_and_real_edges(tmp_path: Path) -> None:
    module = _load_module()
    summary = tmp_path / "summary.json"
    summary.write_text('{"physical_case_id":"F6_CASE","family_id":"F6"}\n', encoding="utf-8")
    records = tmp_path / "records.jsonl"
    records.write_text('{"record_fields":"one row per static (Zone, Idp); saved-frame lifecycle only"}\n', encoding="utf-8")
    batch = tmp_path / "batch.json"
    batch.write_text('{"completed":1}\n', encoding="utf-8")
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    proof = tmp_path / "proof.json"
    proof.write_text(
        json.dumps(
            {
                "schema": module.PROOF_SCHEMA,
                "status": "VERIFIED_ACTUAL_F6_TYPED_LIFECYCLE_BATCH_SAVED_MASK_DIAGNOSTICS_NO_PHYSICAL_CREDIT",
                "counts": {"completed": 1, "failed": 0},
                "batch_summary": str(batch),
                "batch_summary_sha256": digest(batch),
                "report": str(batch),
                "report_sha256": digest(batch),
                "case_verifications": [
                    {
                        "physical_case_id": "F6_CASE",
                        "family_id": "F6",
                        "status": "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY",
                        "source_H5_prepost_known_SHA_and_current_stat_equal": True,
                        "summary": str(summary),
                        "summary_sha256": digest(summary),
                        "records_stat_only": {"path": str(records), "sha256": digest(records), "bytes": records.stat().st_size, "rows": 1},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    value, rows, edges = module._validate_proof(proof, ["F6_CASE"], "F6")
    assert value["counts"]["completed"] == 1
    assert set(rows) == {"F6_CASE"}
    assert edges["batch_summary"]["sha256"] == digest(batch)

    duplicate = json.loads(proof.read_text(encoding="utf-8"))
    duplicate["case_verifications"].append(dict(duplicate["case_verifications"][0]))
    proof.write_text(json.dumps(duplicate), encoding="utf-8")
    with pytest.raises(module.GenericExtractError, match="duplicates case ID"):
        module._validate_proof(proof, ["F6_CASE"], "F6")
