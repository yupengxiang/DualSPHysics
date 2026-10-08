from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_lineage_v16_cpu_metadata_v18.py"
SPEC = importlib.util.spec_from_file_location("lineage_v18_test_module", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)


REQUEST = ROOT / (
    "campaigns/ds-data-02/stage2/lineage/v18-cpu-metadata/"
    "CURRENT336-effective-lineage-audit-v16-cpu-metadata-v18-request-001.json"
)


def _load_request() -> dict:
    return json.loads(REQUEST.read_text())


def test_v18_request_binds_stable_v15_receipt_for_all_run_outs() -> None:
    value = _load_request()
    assert value["schema"] == "ds02.request.v1"
    assert value["orchestration_schema"] == worker.REQUEST_KIND
    assert value["status"] == "READY_FOR_PARENT_GUARD"
    assert value["closure_summary"]["v15_source_records"] == 2493
    assert value["closure_summary"]["run_out_sha_provenance"]["field"] == "input_hashes_after_run"
    assert value["closure_summary"]["run_out_sha_provenance"]["mapped_case_run_out_count"] == 336
    assert value["closure_summary"]["run_out_sha_provenance"]["fallback"].startswith("FORBIDDEN")
    receipt = [item for item in value["source_bindings"] if item["role"] == "v15_stable_execution_receipt"]
    assert len(receipt) == 1
    run_outs = [item for item in value["source_bindings"] if item["role"] == "v15_input:case:run_out"]
    assert len(run_outs) == 336
    assert all(isinstance(item["sha256"], str) and len(item["sha256"]) == 64 for item in run_outs)
    assert all(item["hash_provenance"]["receipt_path"] == receipt[0]["path"] for item in run_outs)
    assert all(item["hash_provenance"]["receipt_sha256"] == receipt[0]["sha256"] for item in run_outs)
    assert all(value["input_hashes"][item["path"]] for item in run_outs)
    assert value["sha256"] == worker.canonical_sha(value)


def test_v18_has_no_null_input_sha_or_scientific_array_inputs() -> None:
    value = _load_request()
    assert all(isinstance(digest, str) and len(digest) == 64 for digest in value["input_hashes"].values())
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


def test_v18_metadata_preflight_validates_full_request_without_content_hashing() -> None:
    value = _load_request()
    bound = worker._validate(value, verify_content=False)
    assert len(bound) == len(value["source_bindings"]) == len(value["input_files"])
    assert sum(item["bytes"] for item in bound) == value["resource_request"]["source_bytes_from_stat"]
    assert sum(item["sha256"] is None for item in bound) == 0


def test_v18_rejects_missing_receipt_provenance_and_promoted_h5() -> None:
    value = _load_request()
    bad = copy.deepcopy(value)
    run_out = next(item for item in bad["source_bindings"] if item["role"] == "v15_input:case:run_out")
    run_out.pop("hash_provenance")
    bad["sha256"] = worker.canonical_sha(bad)
    try:
        worker._validate(bad, verify_content=False)
    except worker.V18Error as error:
        assert "receipt provenance" in str(error)
    else:
        raise AssertionError("Run.out without stable receipt provenance must fail")

    bad = copy.deepcopy(value)
    bad["execution_contract"]["hdf5_or_bi4_read"] = True
    bad["sha256"] = worker.canonical_sha(bad)
    try:
        worker._validate(bad, verify_content=False)
    except worker.V18Error as error:
        assert "HDF5/BI4" in str(error)
    else:
        raise AssertionError("promoting HDF5/BI4 scope must fail")


def test_v18_generator_owns_child_output_and_does_not_share_attempt_root() -> None:
    root = Path("/tmp/ds02-v18-attempt")
    child = worker._generator_output_dir(root)
    assert child == root.resolve() / "generated-v16"
    assert child != root.resolve()
    assert child.parent == root.resolve()
