"""V4 result-boundary tests.

The subprocess fixture uses the real V8 request validator, result reader, and
semantic validator.  It is explicitly fixture-only and does not stand in for
the ROOT200/V12 production request.  Production V4 keeps the real V12 and
typed-only scorer path in ``run``.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_root191_typed_only_no_model_evaluator_v4.py"
V8_TEST = ROOT / "tests/test_ds_data02_stage2_f2_fresh_v16_proof_consumer_v8.py"


def _load_v8_test():
    spec = importlib.util.spec_from_file_location("root191_v4_v8_fixture", V8_TEST)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture_request(tmp_path: Path) -> tuple[Path, Path]:
    fixture = _load_v8_test()
    request_path, _result_path, request, _result = fixture._fixture(tmp_path)
    request["fixture_only"] = True
    request["sha256"] = fixture.v8.canonical_sha(request)
    request_path.write_text(json.dumps(request, sort_keys=True, allow_nan=False), encoding="utf-8")
    return request_path, request_path.parent / "relocated/output/fresh-v4-fixture-report.json"


def test_real_v8_fixture_subprocess_reports_full_pre_post_stat(tmp_path: Path) -> None:
    request_path, output = _fixture_request(tmp_path)
    command = [sys.executable, str(SCRIPT), "run-v8-fixture", "--request", str(request_path),
               "--output", str(output), "--parent-pid", str(__import__("os").getpid())]
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    assert completed.returncode == 0, completed.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "PASS_REAL_V8_VALIDATOR_FIXTURE_ONLY"
    source = report["result_source"]
    assert set(("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino")) <= set(source["pre_stat"])
    assert source["pre_stat"] == source["post_stat"]
    assert report["execution"]["subprocess_cli"] is True
    assert report["execution"]["v8_validator"] is True
    assert report["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


def test_real_v8_fixture_rejects_changed_content_sha(tmp_path: Path) -> None:
    request_path, output = _fixture_request(tmp_path)
    result_path = Path(json.loads(request_path.read_text())["result"]["path"])
    result_path.write_text(result_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    command = [sys.executable, str(SCRIPT), "run-v8-fixture", "--request", str(request_path),
               "--output", str(output), "--parent-pid", str(__import__("os").getpid())]
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    assert completed.returncode != 0
    assert "fixture validation failed" in completed.stderr or "stat differs" in completed.stderr
    assert not output.exists()


def test_v4_metadata_entrypoint_is_importable() -> None:
    spec = importlib.util.spec_from_file_location("root191_v4_import_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.REQUEST_SCHEMA == "ds02.stage2.f2-root191-typed-only-no-model-evaluator-request.v3"
