#!/usr/bin/env python3
from __future__ import annotations
import ast
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
REQ = HERE / "requests/initial-native-qa-196-producer.request.json"
BIND = HERE / "source-binding.json"
EVID = HERE / "evidence/root195-producer-input-binding.json"
WORKER = HERE / "workers/run_f4_native_initial_qa_producer_v1.py"

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def test_request_contract():
    d = json.loads(REQ.read_text())
    assert d["kind"] == "cpu" and d["cpu_task_kind"] == "audit" and d["cpu_threads"] == 2
    assert d["launch"] is False and d["launch_allowed"] is False and d["status"] == "source_only_disabled"
    assert d["input_files"] and len(d["input_files"]) == len(d["input_sha256"])
    for path, digest in d["input_sha256"].items():
        assert sha(Path(path)) == digest, path
        assert Path(path).suffix.lower() not in {".bi4", ".h5", ".vtk", ".csv"}
    assert any(Path(path).suffix.lower() == ".bi4" for path in d["deferred_input_files"])
    for path in d["deferred_input_files"]:
        if path.endswith(".bi4"):
            assert d["deferred_input_sha256"][path] is None
            assert d["deferred_bi4_producer_sha256"][path]
    assert d["expected_output"]["sha256"] is None
    assert d["independent_case_count_increment"] == 0

def test_preserved_root195_evidence():
    b = json.loads(BIND.read_text())
    e = json.loads(EVID.read_text())
    assert b["upstream_adopted_commit"] == "805f36c8"
    assert b["upstream_source_commit"] == "ae0d8a25"
    assert e["aggregate_execution_receipt"]["status"] == "failed"
    assert e["aggregate_execution_receipt"]["returncode"] == 0
    assert e["aggregate_execution_receipt"]["error"] == "GenCase actual particle count missing"
    assert e["aggregate_execution_receipt"]["preserved_without_promotion"] is True
    rows = e["per_case_actual_gencase_receipts"]
    assert len(rows) == 8
    assert all(r["gencase_receipt"]["status"] == "completed" and r["gencase_receipt"]["returncode"] == 0 for r in rows)
    assert all(r["solver_dimension_from_gencase"] == 3 for r in rows)
    assert all(r["generated_bi4"]["content_rehashed_by_source"] is False for r in rows)
    assert all(r["generated_bi4"]["producer_sha256"] for r in rows)

def test_worker_is_actual_decoder_producer_source():
    tree = ast.parse(WORKER.read_text(), filename=str(WORKER))
    source = WORKER.read_text()
    assert "scan_bi4_fd" in source and "np.memmap" in source and "Mk" in source and "Type" in source
    assert "GenCase_linux64" not in source and "solver" in source
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"system", "popen"} for node in ast.walk(tree))

if __name__ == "__main__":
    test_request_contract(); test_preserved_root195_evidence(); test_worker_is_actual_decoder_producer_source(); print("fresh083 contract: PASS")
