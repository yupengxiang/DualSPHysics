from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ds_data02_f6_handoff_20261002_v19.py"
SPEC = importlib.util.spec_from_file_location("ds_data02_f6_handoff_20261002_v19", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
F6 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(F6)


def test_sparse_retry_is_additive_and_uses_literal_venv() -> None:
    manifest = F6.read_json(F6.POST_ROOT / "request_manifest.json")
    conversions = [F6.read_json(Path(row["path"])) for row in manifest["requests"] if row["kind"] == "conversion"]
    assert len(conversions) == 2
    for request in conversions:
        assert request["attempt_id"].endswith("_NATIVE_H5_003")
        assert request["command"][0] == str(F6.VENV_PYTHON)
        assert request["supersedes_attempt"].endswith("_NATIVE_H5_002")
        assert "--motion-csv" in request["command"]
        assert str(F6.VENV_PYTHON) in request["input_files"]
        assert str(F6.VENV_PYTHON.resolve()) not in request["input_files"]
        assert all(Path(path).is_file() for path in request["input_files"])


def test_sparse_retry_records_identity_loss_without_granting_qn() -> None:
    evidence = F6.read_json(F6.POST_ROOT / "sparse_conversion_retry_evidence_001.json")
    assert evidence["old_attempts_immutable"] is True
    assert "Part_0009.bi4" in evidence["source_failure"]
    assert evidence["gpu_launch"] is False
    assert evidence["q_n_status"] == "pending_native_exclusion_reconciliation"
    labels = [F6.read_json(Path(row["path"])) for row in F6.read_json(F6.POST_ROOT / "request_manifest.json")["requests"] if row["kind"] == "labels"]
    assert len(labels) == 2
    assert all(row["deferred_until_attempt"].endswith("_NATIVE_H5_003") for row in labels)

