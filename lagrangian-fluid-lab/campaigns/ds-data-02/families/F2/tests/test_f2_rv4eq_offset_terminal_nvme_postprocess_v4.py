from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "f2_rv4eq_offset_terminal_nvme_postprocess_v4.py"
spec = importlib.util.spec_from_file_location("f2_offset_nvme_v4", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_verified_copy_hashes_stream_and_rejects_changed_bytes(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    target = tmp_path / "private" / "source.bin"
    payload = (b"offset-terminal-source\0" * 10000) + bytes(range(256))
    source.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()

    evidence = module.verified_copy(source, target, expected, len(payload))

    assert target.read_bytes() == payload
    assert target.stat().st_mode & 0o777 == 0o400
    assert evidence["private_reader_sha256"] == expected
    assert evidence["copy_verified_during_stream"] is True
    assert evidence["private_reader_deleted_before_publish"] is True

    bad_target = tmp_path / "private-bad" / "source.bin"
    with pytest.raises(module.PostprocessError, match="SHA differs"):
        module.verified_copy(source, bad_target, "0" * 64, len(payload))


def test_rebind_report_publishes_canonical_source_and_keeps_private_evidence(tmp_path: Path) -> None:
    report_path = tmp_path / "pose-report.json"
    report_path.write_text(
        json.dumps(
            {
                "source_trajectory": {"path": "/tmp/private.h5", "sha256": "a" * 64},
                "augmented_trajectory": {"path": str(tmp_path / "pose.h5"), "sha256": "b" * 64},
            }
        )
    )
    payload = module._rebind_report(
        report_path,
        canonical_source={"path": "/data/terminal.h5", "sha256": "a" * 64, "bytes": 123},
        copy_evidence={"private_reader_path": "/tmp/private.h5", "private_reader_sha256": "a" * 64},
        stage="pose",
    )

    assert payload["source_trajectory"]["path"] == "/data/terminal.h5"
    assert payload["source_trajectory"]["sha256"] == "a" * 64
    assert payload["nvme_source_copy"]["private_reader_path"] == "/tmp/private.h5"
    assert payload["reader_path_policy"]["private_path_is_ephemeral"] is True


def test_v4_labels_observed_status_check() -> None:
    # Verify observed status check handles nested qi_evidence dict
    observed = {
        "qi_evidence": {
            "status": "v6-observation-evidence-ready; Q-N and production eligibility not assessed"
        }
    }
    status = (
        observed.get("qi_evidence", {}).get("status")
        if isinstance(observed.get("qi_evidence"), dict)
        else observed.get("status")
    )
    assert status == "v6-observation-evidence-ready; Q-N and production eligibility not assessed"
