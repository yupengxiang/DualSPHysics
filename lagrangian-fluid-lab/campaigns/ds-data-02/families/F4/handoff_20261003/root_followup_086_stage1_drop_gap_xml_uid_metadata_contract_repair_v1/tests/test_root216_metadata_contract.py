#!/usr/bin/env python3
"""Static and metadata-only checks for the disabled Root216 repair."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
REQUEST = ROOT / "requests/root216-native-initial-qa.request.json"
WORKER = ROOT / "workers/run_f4_native_initial_qa_xml_uid_v2.py"
BINDER = ROOT.parent / "root_followup_084_stage1_drop_gap_full1201_qualification_binder_v1/workers/build_f4_root200_native_qualification_bindings_v1.py"
INTEGRATION = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/"
    "DualSPHysics/lagrangian-fluid-lab/scripts"
)
PLAN = ROOT.parent / "root_followup_081_stage1_drop_gap_internal8_source_v1/source-plan.json"
ROOT195_BINDING = ROOT.parent / "root_followup_083_stage1_drop_gap_native_qa_producer_v1/evidence/root195-producer-input-binding.json"
OWNER_ROOT = ROOT.parent / "root_followup_081_stage1_drop_gap_internal8_source_v1/owners"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_request_is_replacement_disabled_and_hash_closed() -> None:
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    assert request["attempt_id"].endswith("-216")
    assert request["cpu_task_kind"] == "audit"
    assert request["launch"] is False
    assert request["launch_allowed"] is False
    assert request["status"] == "source_only_disabled"
    assert request["supersedes"]["attempt_id"] == "root-stage1-f4-internal8-native-initial-qa-212"
    assert all(Path(path).suffix.lower() != ".bi4" for path in request["input_files"])
    assert len(request["deferred_input_files"]) == 8
    assert all(Path(path).suffix.lower() == ".bi4" for path in request["deferred_input_files"])
    assert all(value is None for value in request["deferred_input_sha256"].values())
    for path, expected in request["input_sha256"].items():
        assert digest(Path(path).resolve()) == expected
    sys.path.insert(0, str(INTEGRATION))
    import ds_data02_strict_dispatch_v1 as strict  # noqa: PLC0415

    strict.validate_request(request)


def test_flattened_producer_rows_and_metadata_preflight() -> None:
    sys.path.insert(0, str(ROOT / "workers"))
    spec_source = WORKER.read_text(encoding="utf-8")
    ast.parse(spec_source, filename=str(WORKER))
    assert "metadata[\"physical_binding\"]" in spec_source
    assert "generated_bi4" in spec_source
    assert "metadata_preflight" in spec_source
    assert "BI4" in spec_source
    assert "memmap" not in spec_source
    assert "numpy" not in spec_source

    import importlib.util

    spec = importlib.util.spec_from_file_location("f4_root216_worker", WORKER)
    assert spec and spec.loader
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    rows = worker.root195_rows_v2(json.loads(ROOT195_BINDING.read_text(encoding="utf-8")))
    assert len(rows) == 8
    assert all("generated_bi4" in row and "generated_xml" in row for row in rows.values())
    assert all(row["generated_bi4"]["producer_sha256"] for row in rows.values())


def test_root200_binder_accepts_root216() -> None:
    source = BINDER.read_text(encoding="utf-8")
    assert "ROOT216_ATTEMPT" in source
    assert "ROOT212_ATTEMPT" in source
    assert "ACCEPTED_QA_ATTEMPTS" in source


if __name__ == "__main__":
    test_request_is_replacement_disabled_and_hash_closed()
    test_flattened_producer_rows_and_metadata_preflight()
    test_root200_binder_accepts_root216()
    print("F4 Root216 metadata contract: PASS")
