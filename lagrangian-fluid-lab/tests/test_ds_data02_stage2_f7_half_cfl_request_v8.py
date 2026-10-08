from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import uuid


ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
QA = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/"
    "F7_S2_HALF_CFL_INITIAL_TYPED_QA_OUTER_V12/"
    "f7-s2-half-cfl-initial-typed-qa-outer-v12-root-001-root-forward-001/qa/"
    "f7-s2-half-cfl-initial-typed-qa-v12-outer-report.json"
)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v8_builder_binds_library_worktree_and_inner_qa_guard(tmp_path: Path) -> None:
    builder = _load("f7_half_cfl_request_v8_test", ROOT /
                    "scripts/ds_data02_stage2_f7_half_cfl_request_v8.py")
    v6 = _load("external_solver_v6_for_f7_v8_test", ROOT /
                "scripts/ds_data02_stage2_external_solver_v6.py")
    output = tmp_path / "f7-v8-request.json"
    external_root = Path("/var/tmp/ds02-stage2/F7") / ("test-v8-" + uuid.uuid4().hex)
    request = builder.build(qa_report=QA, output=output, output_root=external_root)
    assert request["worktree_root"] == str(ROOT.parent.resolve())
    library = request["official_library_binding"]
    assert library["required_by_native_launch"] == ["libdsphchrono.so", "libChronoEngine.so"]
    roles = {item["role"]: item for item in request["input_bindings"]}
    assert "v8_initial_qa_report" in roles
    assert request["qa_gate"]["v8_report_sha256"] == roles["v8_initial_qa_report"]["sha256"]
    assert request["qa_gate"]["v12_report_sha256"] == roles["v12_initial_qa_report"]["sha256"]
    checked = v6._validate_request(request, verify_content=False)
    assert checked["max_wall_seconds"] == 3600.0
    assert request["sha256"] == builder.canonical_sha(request)
    on_disk = json.loads(output.read_text(encoding="utf-8"))
    assert on_disk["sha256"] == request["sha256"]

