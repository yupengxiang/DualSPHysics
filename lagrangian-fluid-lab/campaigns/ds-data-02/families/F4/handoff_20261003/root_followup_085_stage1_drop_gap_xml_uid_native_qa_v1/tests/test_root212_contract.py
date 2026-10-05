#!/usr/bin/env python3
"""Static/source checks for the disabled Root212 F4 audit request."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
REQUEST = ROOT / "requests/root212-native-initial-qa.request.json"
SOURCE_BINDING = ROOT / "source-binding.json"
EVIDENCE = ROOT / "evidence/root195-root196-root210-root211-root212-binding.json"
WORKER = ROOT / "workers/run_f4_native_initial_qa_xml_uid_v1.py"
INTEGRATION = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/"
    "DualSPHysics/lagrangian-fluid-lab/scripts"
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_request_is_disabled_and_strictly_closed() -> None:
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    assert request["attempt_id"] == "root-stage1-f4-internal8-native-initial-qa-212"
    assert request["cpu_task_kind"] == "audit"
    assert request["launch"] is False
    assert request["launch_allowed"] is False
    assert request["status"] == "source_only_disabled"
    assert request["command"][request["command"].index("--output-root") + 1] == "{attempt_root}"
    assert len(request["input_files"]) == 64
    assert all(Path(path).suffix.lower() != ".bi4" for path in request["input_files"])
    assert len(request["deferred_input_files"]) == 8
    assert all(Path(path).suffix.lower() == ".bi4" for path in request["deferred_input_files"])
    assert all(value is None for value in request["deferred_input_sha256"].values())
    assert all(len(value) == 64 for value in request["deferred_bi4_producer_sha256"].values())
    for path, expected in request["input_sha256"].items():
        assert digest(Path(path).resolve()) == expected

    sys.path.insert(0, str(INTEGRATION))
    import ds_data02_strict_dispatch_v1 as strict  # noqa: PLC0415

    strict.validate_request(request)


def test_actual_and_failed_evidence_bound_without_promotion() -> None:
    binding = json.loads(SOURCE_BINDING.read_text(encoding="utf-8"))
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert len(binding["root195_case_bindings"]) == 8
    assert len(evidence["root195"]["per_case"]) == 8
    assert binding["root195_aggregate"]["status"] == "failed"
    assert binding["root195_aggregate"]["returncode"] == 0
    assert binding["root195_aggregate"]["error"] == "GenCase actual particle count missing"
    assert len(binding["failed_prior_native_qa_attempts"]) == 3
    assert binding["failed_prior_native_qa_attempts"][-1]["attempt_id"].endswith("-211")
    assert "Mk" in binding["failed_prior_native_qa_attempts"][-1]["observed_error"]
    assert "Type" in binding["failed_prior_native_qa_attempts"][-1]["observed_error"]
    assert binding["audit_contract"]["observed_native_arrays"] == ["Posd", "Idp"]
    assert binding["audit_contract"]["raw_native_arrays_not_required"] == ["Mk", "Type"]
    assert evidence["root212_required_method"]["raw_mk_type_observed"] is False


def test_worker_is_metadata_adapter_and_compiles_without_execution() -> None:
    source = WORKER.read_text(encoding="utf-8")
    ast.parse(source, filename=str(WORKER))
    assert "numpy" not in source
    assert "memmap" not in source
    assert "raw_native_mk_observed\": False" in source
    assert "raw_native_type_observed\": False" in source
    assert "subprocess.run" in source
    assert "output_root.mkdir(parents=True, exist_ok=True)" in source


if __name__ == "__main__":
    test_request_is_disabled_and_strictly_closed()
    test_actual_and_failed_evidence_bound_without_promotion()
    test_worker_is_metadata_adapter_and_compiles_without_execution()
    print("F4 Root212 source contract: PASS")
