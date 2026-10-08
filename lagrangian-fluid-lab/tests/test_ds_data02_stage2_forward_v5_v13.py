from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile


ROOT = Path(__file__).resolve().parents[2]
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V5 = _load("f7_external_solver_v5_test", ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_external_solver_v5.py")
V5_BUILDER = _load("f7_external_solver_request_v5_test", ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_f7_nvme_request_v5.py")
V13 = _load("f2_parent_launcher_v13_test", ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_f2_parent_launcher_v13.py")
V18 = _load("f2_external_supervisor_v18_test", ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_f2_external_supervisor_v18.py")


V4_REQUEST = ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/f7-nvme-counterpart-v4/f7-s2-same-cfl-nvme-request-v4-001.json"
V5_REQUEST = ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/f7-nvme-counterpart-v5/f7-s2-same-cfl-nvme-request-v5-001.json"
V12_REQUEST = ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v12-parent-supervised/f2-s1-parent-supervised-launch-request-v12-001.json"


def test_f7_v5_request_is_source_bound_and_preflightable_without_solver():
    value = json.loads(V5_REQUEST.read_text())
    assert value["schema"] == "ds02.stage2.external-solver-request.v5"
    assert value["forward_of"]["immutable_failure_preserved"] is True
    assert value["official_library_binding"]["required_by_native_launch"] == ["libdsphchrono.so"]
    checked = V5._validate_request(value, verify_content=False)
    assert checked["files"]
    env, audit = V5._launch_environment(value, {"uuid": "manufactured-gpu"}, V5.OFFICIAL_LIBRARY_ROOT)
    assert audit["LD_LIBRARY_PATH"].split(":")[0] == str(V5.OFFICIAL_LIBRARY_ROOT)
    assert env["LD_LIBRARY_PATH"].split(":")[0] == str(V5.OFFICIAL_LIBRARY_ROOT)
    assert value["model_invoked"] is False and value["cfd_invoked"] is False


def test_f7_v5_builder_refuses_overwrite_and_does_not_change_v4():
    before = V5_BUILDER.sha256_file(V4_REQUEST)
    with tempfile.TemporaryDirectory() as temp:
        output = Path(temp) / "request.json"
        V5_BUILDER.build(V4_REQUEST, output)
        result = json.loads(output.read_text())
        assert result["schema"].endswith(".v5")
        assert result["forward_of"]["request_sha256"] == before
        assert V5_BUILDER.sha256_file(V4_REQUEST) == before
        try:
            V5_BUILDER.build(V4_REQUEST, output)
        except ValueError as error:
            assert "overwrite" in str(error)
        else:
            raise AssertionError("builder accepted an existing destination")


def test_v13_keeps_literal_venv_and_records_resolved_target_only_as_provenance():
    value = json.loads((ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v13-venv/f2-s1-parent-supervised-launch-request-v13-001.json").read_text())
    assert value["execution"]["python"] == str(V13.VENV_PYTHON)
    assert value["execution"]["python"] != str(V13.VENV_PYTHON.resolve())
    assert value["interpreter_binding"]["resolved_target_provenance"] == str(V13.VENV_PYTHON.resolve())
    assert value["execution"]["resolved_path_must_not_be_launched"] is True
    V13._validate_launch(value, verify_content=False)


def test_v18_supervisor_preflight_uses_v13_and_literal_python():
    value = json.loads((ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v18-supervisor/f2-s1-supervisor-request-v18-001.json").read_text())
    assert value["schema"].endswith(".v18")
    assert value["execution"]["v13_cli"][0] == str(V13.VENV_PYTHON)
    assert value["execution"]["v13_cli"][0] != str(V13.VENV_PYTHON.resolve())
    V18._validate_request(value, verify_content=False)
