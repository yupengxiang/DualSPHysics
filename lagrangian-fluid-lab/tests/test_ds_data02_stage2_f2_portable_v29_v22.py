from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import uuid


ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
V22_PATH = ROOT / "scripts/ds_data02_stage2_f2_external_supervisor_v22.py"
V29_PATH = ROOT / "scripts/ds_data02_stage2_f2_consistent_chain_v29.py"
V25 = ROOT / (
    "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v25-consistent/"
    "f2-s1-parent-supervised-launch-request-v13-012.json"
)
V26 = ROOT / (
    "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v26-supervised-chain/"
    "f2-s1-parent-supervised-launch-request-v14-013.json"
)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v22_binds_actual_outer_entry_and_cold_helper_grace(tmp_path: Path) -> None:
    v22 = _load("ds02_supervisor_v22_test", V22_PATH)
    out = tmp_path / "v22.json"
    external = Path("/var/tmp/ds02-stage2/ds-data-02/families/F2/STAGE2_F2_S1_PORTABLE_RAW_TO_LABEL_V5")
    root = external / ("v22-test-" + uuid.uuid4().hex)
    value = v22.build_request(
        ROOT / "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v26-supervised-chain/"
        "f2-s1-parent-supervised-launch-request-v14-013.json",
        out, output_root=root, max_wall_seconds=6000.0,
    )
    assert value["forward_runtime"]["path"] == str(V22_PATH.resolve())
    assert value["forward_runtime"]["helper_cleanup_grace_seconds"] >= 25.0
    assert any(item.get("role") == "external_supervisor_v22"
               for item in value["static_bindings"])
    checked = v22.validate_request(out, verify_content=False)
    assert checked["child_cleanup_grace_seconds"] >= 25.0
    v22._install_forward_helpers()
    assert v22.V21._run_process_group is v22._run_process_group


def test_v29_accepts_explicit_frozen_root_or_consumer_graph_paths(tmp_path: Path) -> None:
    v29 = _load("ds02_chain_v29_test", V29_PATH)
    v15 = tmp_path / "v15.json"
    v22 = tmp_path / "v22.json"
    external = Path("/var/tmp/ds02-stage2/ds-data-02/families/F2/STAGE2_F2_S1_PORTABLE_RAW_TO_LABEL_V5")
    root = external / ("v29-test-" + uuid.uuid4().hex)
    value = v29.build(v25_v13=V25, v26_v14=V26, v15_output=v15,
                      v22_output=v22, supervisor_root=root)
    request = json.loads(v22.read_text())
    assert request["sha256"] == v29.V22.canonical_sha(request)
    assert request["forward_graph_v29"]["v25_request"]["path"] == str(V25.resolve())
    assert request["forward_graph_v29"]["v26_request"]["path"] == str(V26.resolve())
    assert request["forward_graph_v29"]["no_latest_fallback"] is True
    assert request["forward_runtime"]["helper_cleanup_grace_seconds"] >= 25.0
