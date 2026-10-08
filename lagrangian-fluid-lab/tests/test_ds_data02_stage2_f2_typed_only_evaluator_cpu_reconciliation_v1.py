from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_typed_only_evaluator_cpu_reconciliation_v1.py"
ORIGINAL = ROOT / "campaigns/ds-data-02/stage2/evaluator/v2/f2-s1-typed-evaluator-parent-v2-current-root-061-001.json"


def _load():
    spec = importlib.util.spec_from_file_location("typed_cpu_reconciliation_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R = _load()


def test_build_cpu_delta_binds_service_evidence_without_mutating_old_charge(tmp_path: Path) -> None:
    evidence = tmp_path / "systemd-cpu-evidence.json"
    value = {"schema": R.EVIDENCE_SCHEMA, "status": "OBSERVED_SERVICE_CPU",
             "cpu_usage_nanoseconds": 8_765_324_000,
             "source_scope": {"unit": "ds02-f2-typed-evaluator-current-root-061"}}
    value["sha256"] = R.canonical_sha(value)
    evidence.write_text(json.dumps(value) + "\n", encoding="utf-8")
    request = tmp_path / "reconcile-request.json"
    result = R.build_request(
        original_request=ORIGINAL, evidence=evidence, output=request,
        report_path=tmp_path / "reconcile-report.json")
    assert result["original_cpu_seconds"] == pytest.approx(0.574044)
    assert result["observed_cpu_seconds"] == pytest.approx(8.765324)
    assert result["delta_cpu_seconds"] == pytest.approx(8.19128)
    bound = json.loads(request.read_text(encoding="utf-8"))
    assert bound["accounting"]["original_charge_immutable"] is True
    assert bound["accounting"]["storage_delta_bytes"] == 0
    assert bound["qualification"] == R.UNKNOWN


def test_lower_service_cpu_is_rejected_without_a_zero_or_negative_delta(tmp_path: Path) -> None:
    evidence = tmp_path / "systemd-cpu-evidence.json"
    value = {"schema": R.EVIDENCE_SCHEMA, "status": "OBSERVED_SERVICE_CPU",
             "cpu_usage_nanoseconds": 574_043_000,
             "source_scope": {"unit": "ds02-f2-typed-evaluator-current-root-061"}}
    value["sha256"] = R.canonical_sha(value)
    evidence.write_text(json.dumps(value) + "\n", encoding="utf-8")
    with pytest.raises(R.CpuReconciliationError, match="does not exceed"):
        R.build_request(original_request=ORIGINAL, evidence=evidence,
                        output=tmp_path / "request.json",
                        report_path=tmp_path / "report.json")
