from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ds_data02_f6_handoff_20261002_v20.py"
SPEC = importlib.util.spec_from_file_location("ds_data02_f6_handoff_20261002_v20", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
F6 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(F6)


def test_enriched_requests_are_additive_and_xml_inertia_is_positive() -> None:
    manifest = F6.read_json(F6.POST_ROOT / "request_manifest.json")
    requests = [F6.read_json(Path(row["path"])) for row in manifest["requests"]]
    assert len(requests) == 2
    for request in requests:
        assert request["attempt_id"].endswith("_NATIVE_H5_004")
        assert request["source_sparse_attempt"].endswith("_NATIVE_H5_003")
        assert request["command"][0] == str(F6.VENV_PYTHON)
        assert request["command"][1] == str(F6.SCRIPT)
        assert request["output_contract"]["positive_inertia_required"] is True
        assert all(Path(path).is_file() for path in request["input_files"])


def test_enriched_metadata_preserves_old_h5_and_requires_pose_fit() -> None:
    evidence = F6.read_json(F6.POST_ROOT / "enriched_metadata_evidence_001.json")
    assert evidence["source_h5_003_immutable"] is True
    assert evidence["gpu_launch"] is False
    assert evidence["q_n_status"] == "pending_native_exclusion_reconciliation"
    assert "x/y/z" in evidence["repair"]
    assert "saved pose" in evidence["repair"]
