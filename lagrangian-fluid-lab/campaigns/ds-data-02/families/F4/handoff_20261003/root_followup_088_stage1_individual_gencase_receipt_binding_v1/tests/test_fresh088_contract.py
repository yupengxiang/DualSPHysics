from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace


HERE = Path(__file__).resolve().parent.parent
FRESH087 = HERE.parent / "root_followup_087_stage1_drop_gap_lattice_aligned_fallback6_source_v1"
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
INDEX = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f4_six_lattice_aligned_genuine_gencase_227/root-source-review-and-request-index.json"
BINDER = HERE / "workers/bind_f4_individual_gencase_v1.py"
QA_WORKER = FRESH087 / "workers/run_f4_fallback_native_initial_qa_v1.py"


def module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_disabled_requests_and_deferred_arrays():
    requests = list((HERE / "requests").glob("*.request.json"))
    assert len(requests) == 2
    for path in requests:
        value = json.loads(path.read_text())
        assert value["launch"] is False
        assert value["launch_allowed"] is False
        assert value["independent_case_count_increment"] == 0
        assert all(Path(item).suffix.lower() not in {".bi4", ".h5", ".vtk", ".csv"} for item in value["input_files"])
        assert all(value["deferred_input_sha256"].get(item) is None for item in value["deferred_input_files"])
    binder = json.loads((HERE / "requests/bind-individual-gencase.request.json").read_text())
    assert binder["cpu_task_kind"] == "audit"
    assert len([item for item in binder["deferred_input_files"] if item.endswith(".bi4")]) == 6
    qa = json.loads((HERE / "requests/root227-six-case-native-qa.request.json").read_text())
    assert qa["cpu_task_kind"] == "audit"
    assert "{attempt_root}" in qa["command"]


def test_registered_binding_is_compatible_with_fresh087_worker_without_audit():
    assert INDEX.is_file(), INDEX
    binder = module(BINDER, "fresh088_binder_test")
    plan = FRESH087 / "source-plan.json"
    arguments = SimpleNamespace(
        plan=plan,
        owner_root=FRESH087 / "owners",
        registered_index=INDEX,
    )
    with TemporaryDirectory(prefix="ds02-f4-fresh088-test-") as temporary:
        result = binder.bind_registered_root_index(arguments)
        output = Path(temporary) / "individual-gencase-binding.json"
        binder.dump(output, result)
        bound = json.loads(output.read_text())
        assert bound["case_count"] == 6
        assert bound["arrays_read_by_source"] is False
        assert bound["bi4_bytes_read_by_source"] is False
        assert bound["bi4_hashes_computed_by_source"] is False
        assert bound["root216_promoted"] is False
        qa_worker = module(QA_WORKER, "fresh087_worker_shape_test")
        endpoints = json.loads(plan.read_text())["endpoints"]
        rows = qa_worker.rows_from_binding(bound, endpoints)
        assert len(rows) == 6
        assert all(row["row"]["generated_bi4"]["content_rehashed_by_source"] is False for row in rows.values())


if __name__ == "__main__":
    test_disabled_requests_and_deferred_arrays()
    test_registered_binding_is_compatible_with_fresh087_worker_without_audit()
    print("fresh088 contract: PASS")
