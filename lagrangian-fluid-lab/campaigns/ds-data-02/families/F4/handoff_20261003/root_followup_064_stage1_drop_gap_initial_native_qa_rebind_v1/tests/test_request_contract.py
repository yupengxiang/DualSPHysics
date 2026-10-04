#!/usr/bin/env python3
"""Source-only checks for the Root 064 QA rebind request."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_SCRIPTS = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts"
)
sys.path.insert(0, str(INTEGRATION_SCRIPTS))
import ds_data02_strict_dispatch_v1 as strict  # noqa: E402


WORKER_PATH = ROOT / "workers/run_f4_initial_native_qa_v3.py"
REQUEST_PATH = ROOT / "requests/f4_drop_gap_initial_native_qa_request.json"
METADATA_ROOT = ROOT.parent / "root_followup_062_stage1_drop_gap_request_readiness_v1/metadata"
DATA_ROOT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/"
    "F4_DROP_GAP_ENDPOINTS/root-stage1-f4-gap0180-0260-genuine-gencase-063"
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_worker():
    spec = importlib.util.spec_from_file_location("f4_qa_rebind_worker", WORKER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_request_is_disabled_and_strictly_bound() -> None:
    request = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    assert request["cpu_task_kind"] == "audit"
    assert request["launch"] is False
    assert request["launch_allowed"] is False
    assert request["status"] == "source_only_disabled"
    assert request["command"][request["command"].index("--output-root") + 1] == "{attempt_root}/initial-qa"
    assert "--gencase-result" in request["command"]
    assert "--original-execution-receipt" in request["command"]
    assert len(strict.validate_request(request)) == len(request["input_files"])


def test_original_shared_receipt_failure_is_preserved() -> None:
    receipt = json.loads((DATA_ROOT / "execution-receipt.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "failed"
    assert receipt["returncode"] == 0
    assert receipt["error"] == "GenCase actual particle count missing"
    assert digest(DATA_ROOT / "execution-receipt.json") == request_hash(
        "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/"
        "F4_DROP_GAP_ENDPOINTS/root-stage1-f4-gap0180-0260-genuine-gencase-063/execution-receipt.json"
    )


def request_hash(path: str) -> str:
    request = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    expected = request["input_sha256"]
    return expected[str(Path(path).resolve())]


def test_counts_are_read_from_actual_xml() -> None:
    worker = load_worker()
    for endpoint_id in (
        "F4_DROP_ENDPOINT_GAP0p18000_DP010",
        "F4_DROP_ENDPOINT_GAP0p26000_DP010",
    ):
        metadata = json.loads(
            (METADATA_ROOT / f"{endpoint_id}.metadata.json").read_text(encoding="utf-8")
        )
        xml = DATA_ROOT / "gencase" / endpoint_id / f"{endpoint_id}.xml"
        counts = worker.generated_particle_counts(xml, metadata)
        assert counts["source"] == "generated_xml_execution_particles"
        assert counts["total_particles"] == 83233
        assert counts["fixed_particles"] == 24161
        assert counts["fluid_particles"] == 59072
        assert counts["counts_by_source"] == {"drop": 5824, "pool": 53248}


def test_worker_compiles_without_execution() -> None:
    load_worker()


if __name__ == "__main__":
    test_request_is_disabled_and_strictly_bound()
    test_original_shared_receipt_failure_is_preserved()
    test_counts_are_read_from_actual_xml()
    test_worker_compiles_without_execution()
    print("F4 Root 064 QA request contract: PASS")
