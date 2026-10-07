from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_lineage_v16_cpu_metadata_v17.py"
SPEC = importlib.util.spec_from_file_location("lineage_v17_test_module", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)


REQUEST = ROOT / (
    "campaigns/ds-data-02/stage2/lineage/v17-cpu-metadata/"
    "CURRENT336-effective-lineage-audit-v16-cpu-metadata-v17-request-001.json"
)


def _canonical(value: dict) -> str:
    return worker.canonical_sha(value)


def test_v17_request_binds_full_v15_small_closure_and_actual_v4_guards() -> None:
    value = json.loads(REQUEST.read_text())
    assert value["schema"] == "ds02.request.v1"
    assert value["orchestration_schema"] == worker.REQUEST_KIND
    assert value["status"] == "READY_FOR_PARENT_GUARD"
    assert value["lineage_scope"] == {
        "case_count": 336,
        "family_case_counts": {f"F{i}": 48 for i in range(1, 8)},
        "semantic_closure": "PENDING",
        "split_safe": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    assert value["closure_summary"]["v15_source_records"] == 2493
    assert value["closure_summary"]["actual_shared_guard_roles"] == [
        "shared_guard:runtime_v2",
        "shared_guard:runtime_v4",
        "shared_guard:stage2_dispatch_v4",
        "shared_guard:strict_dispatch_v4",
    ]
    assert value["closure_summary"]["mutable_scan_batch_receipts"] == "EXCLUDED_AND_REJECTED"
    assert value["execution_contract"]["hdf5_or_bi4_read"] is False
    assert value["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    assert value["sha256"] == _canonical(value)


def test_v17_has_no_scientific_array_or_mutable_scan_inputs() -> None:
    value = json.loads(REQUEST.read_text())
    for item in value["source_bindings"]:
        path = str(item["path"]).lower()
        role = str(item["role"]).lower()
        assert not any(path.endswith(suffix) for suffix in worker.FORBIDDEN_SUFFIXES), (role, path)
        assert "scan" not in role and "batch" not in role, role
    guards = {item["role"]: item for item in value["source_bindings"] if item["role"].startswith("shared_guard:")}
    assert set(guards) == set(value["closure_summary"]["actual_shared_guard_roles"])
    assert guards["shared_guard:runtime_v4"]["path"].endswith("ds_data02_runtime_v4.py")
    assert guards["shared_guard:stage2_dispatch_v4"]["path"].endswith("ds_data02_stage2_dispatch_v4.py")
    assert guards["shared_guard:strict_dispatch_v4"]["path"].endswith("ds_data02_strict_dispatch_v4.py")


def test_v17_metadata_preflight_validates_request_without_content_reads() -> None:
    value = json.loads(REQUEST.read_text())
    bound = worker._validate(value, verify_content=False)
    assert len(bound) == len(value["source_bindings"]) == len(value["input_files"])
    assert sum(item["bytes"] for item in bound) == value["resource_request"]["source_bytes_from_stat"]
    assert sum(item["sha256"] is None for item in bound) == 336


def test_v17_rejects_promoted_h5_or_batch_scope(tmp_path: Path) -> None:
    value = json.loads(REQUEST.read_text())
    bad = copy.deepcopy(value)
    bad["execution_contract"]["hdf5_or_bi4_read"] = True
    bad["sha256"] = _canonical(bad)
    try:
        worker._validate(bad, verify_content=False)
    except worker.V17Error as error:
        assert "HDF5/BI4" in str(error)
    else:
        raise AssertionError("promoting HDF5/BI4 scope must fail")

    bad = copy.deepcopy(value)
    run_out = next(item for item in bad["source_bindings"] if item["role"] == "v15_input:case:run_out")
    run_out["role"] = "v15_input:mutable_scan_batch_receipt"
    bad["sha256"] = _canonical(bad)
    try:
        worker._validate(bad, verify_content=False)
    except worker.V17Error as error:
        assert "forbidden source role" in str(error)
    else:
        raise AssertionError("mutable batch receipt must fail")

