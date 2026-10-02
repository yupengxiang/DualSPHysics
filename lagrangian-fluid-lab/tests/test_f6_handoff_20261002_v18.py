from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ds_data02_f6_handoff_20261002_v18.py"
SPEC = importlib.util.spec_from_file_location("ds_data02_f6_handoff_20261002_v18", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
F6 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(F6)


def test_conversion_retry_keeps_virtualenv_interpreter_literal_and_old_failure_immutable() -> None:
    manifest = F6.read_json(F6.POST_ROOT / "request_manifest.json")
    requests = [F6.read_json(Path(row["path"])) for row in manifest["requests"] if row["kind"] == "conversion"]
    assert len(requests) == 2
    for request in requests:
        assert request["attempt_id"].endswith("_NATIVE_H5_002")
        assert request["command"][0] == str(F6.VENV_PYTHON)
        assert str(F6.VENV_PYTHON) != str(F6.VENV_PYTHON.resolve())
        assert request["supersedes_attempt"].endswith("_NATIVE_H5_001")
        assert all(Path(path).is_file() for path in request["input_files"])

    evidence = F6.read_json(F6.POST_ROOT / "conversion_retry_evidence_001.json")
    assert evidence["old_attempts_immutable"] is True
    assert "ABI" in evidence["root_cause"]


def test_retry_labels_remain_deferred_until_h5_receipt() -> None:
    manifest = F6.read_json(F6.POST_ROOT / "request_manifest.json")
    labels = [F6.read_json(Path(row["path"])) for row in manifest["requests"] if row["kind"] == "labels"]
    assert len(labels) == 2
    for request in labels:
        assert request["deferred_until_attempt"].endswith("_NATIVE_H5_002")
        assert request["source_trajectory_sha256"] == "deferred_until_native_h5_002_receipt"
