from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/ds_data02_stage2_f2_s1_native_source_closure_118_v2.py"
SPEC = importlib.util.spec_from_file_location("f2_s1_native_source_closure_118_v2", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_producer_fixture(tmp_path: Path, *, bad_output: bool = False, unstable: bool = False,
                           forbidden_input: bool = False):
    output_root = tmp_path / "producer-attempt"
    output_root.mkdir(parents=True)
    manifest = tmp_path / "producer-manifest.json"
    manifest.write_text("{\"case\":\"F2-S1\"}\n", encoding="utf-8")
    report = output_root / "adapter-report.json"
    report.write_text(json.dumps({
        "manifest": {"path": str(manifest), "sha256": _sha(manifest), "bytes": manifest.stat().st_size},
    }) + "\n", encoding="utf-8")
    input_path = tmp_path / ("Part_0000.bi4" if forbidden_input else "small-source.json")
    input_path.write_text("source\n", encoding="utf-8")
    command_output = "{attempt_root}/other.json" if bad_output else "{attempt_root}/adapter-report.json"
    command = ["/usr/bin/python3.10", "adapter.py", "run", "--manifest", str(manifest), "--output", command_output]
    paths = [manifest, input_path]
    hashes = {str(path): _sha(path) for path in paths}
    receipt = {
        "status": "completed",
        "returncode": 0,
        "output_root": str(output_root),
        "request": {"case_id": "F2-S1-V3", "command": command,
                     "input_files": [str(path) for path in paths], "input_sha256": hashes},
        "input_hashes_at_launch": dict(hashes),
        "input_hashes_after_run": dict(hashes),
    }
    if unstable:
        receipt["input_hashes_after_run"][str(input_path)] = "0" * 64
    return report, receipt


def test_producer_receipt_binds_report_manifest_and_stable_inputs(tmp_path: Path):
    report, receipt = _make_producer_fixture(tmp_path)
    result = MODULE._validate_singleton_producer(report, json.loads(report.read_text()), receipt)
    assert result["expanded_output"] == str(report)
    assert result["expanded_manifest"] == receipt["request"]["command"][4]
    assert result["stable_input_count"] == 2


def test_producer_output_alias_is_rejected(tmp_path: Path):
    report, receipt = _make_producer_fixture(tmp_path, bad_output=True)
    with pytest.raises(MODULE.ClosureError, match="--output does not identify"):
        MODULE._validate_singleton_producer(report, json.loads(report.read_text()), receipt)


def test_producer_unstable_or_trajectory_input_is_rejected(tmp_path: Path):
    report, receipt = _make_producer_fixture(tmp_path, unstable=True)
    with pytest.raises(MODULE.ClosureError, match="not stable"):
        MODULE._validate_singleton_producer(report, json.loads(report.read_text()), receipt)
    report, receipt = _make_producer_fixture(tmp_path / "forbidden", forbidden_input=True)
    with pytest.raises(MODULE.ClosureError, match="forbidden trajectory"):
        MODULE._validate_singleton_producer(report, json.loads(report.read_text()), receipt)
