from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import uuid


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v28_preserves_v25_v7_graph_and_two_filesystem_parent_contract(tmp_path: Path):
    v28 = _load("f2_chain_v28_test", ROOT / "scripts/ds_data02_stage2_f2_consistent_chain_v28.py")
    v15_path = tmp_path / "v15.json"
    v21_path = tmp_path / "v21.json"
    root = Path("/var/tmp/ds02-stage2/ds-data-02/families/F2/STAGE2_F2_S1_PORTABLE_RAW_TO_LABEL_V5") / ("v28-test-" + uuid.uuid4().hex)
    result = v28.build(v15_output=v15_path, v21_output=v21_path, supervisor_root=root)
    assert result["graph"]["v7_request"]["path"].endswith("f2-s1-portable-orchestration-request-v7-012.json")
    request = json.loads(v21_path.read_text())
    assert request["sha256"] == v28.V21.canonical_sha(request)
    assert request["forward_graph"]["load_order"][-1] == "v7_engine"
    assert request["same_parent_filesystems"]["new_data_root_or_ledger"] is False
    assert request["same_parent_filesystems"]["external_output"]["roots"]
    assert request["execution"]["child_cleanup_grace_seconds"] >= 25.0
    checked = v28.V21._validate_request(request, verify_content=False)
    assert checked["bound"]["storage_policy"] == request["same_parent_filesystems"]["storage_policy"]


def test_f7_outer_v9_freezes_case_identity_and_motion_without_bi4_read(tmp_path: Path):
    outer = _load("f7_outer_v9_test", ROOT / "scripts/ds_data02_stage2_f7_half_cfl_initial_qa_outer_v9.py")
    output = tmp_path / "outer-request.json"
    result = outer.build_request(output=output, output_dir=Path("/var/tmp/ds02-stage2/F7") / ("outer-v9-test-" + uuid.uuid4().hex))
    assert result["status"] == "READY_FOR_PARENT_CPU_GUARD"
    assert result["identity_gate"]["checks"][:3] == ["CaseNp", "Np", "Nb"]
    assert result["xml_semantics"]["half"]["np"] == 70179
    assert result["xml_semantics"]["half"]["cflnumber"] == 0.1
    assert result["xml_semantics"]["baseline"]["cflnumber"] == 0.2
    assert any(item["role"] == "half_generated_bi4" and item["sha256"] is None
               for item in result["source_bindings"])
    preflight = outer.preflight(output)
    assert preflight["status"] == "READY_FOR_PARENT_CPU_SLOT"
    assert preflight["hdf5_opened"] is False
    assert preflight["raw_opened"] is False
