from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_v64_terminal_cpu_delta_adapter_v4.py"
V3_TEST = Path(__file__).with_name("test_ds_data02_stage2_f2_v64_terminal_cpu_delta_adapter_v3.py")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V4 = _load("v64_terminal_delta_v4", SCRIPT)
V3_TEST_MODULE = _load("v64_terminal_delta_v3_test_fixture", V3_TEST)


def _dump(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _set_external_contract(paths: tuple[Path, Path, Path, Path, Path], *, current: int,
                           peak: int, charged: int, second_peak: int | None = None) -> None:
    request, report, receipt, evidence, ledger = paths
    report_value = json.loads(report.read_text(encoding="utf-8"))
    report_value["external_bytes"] = current
    report_value["external_charge_bytes"] = peak
    if second_peak is not None:
        report_value["external_peak_bytes"] = second_peak
    else:
        report_value.pop("external_peak_bytes", None)
    report_value["charge"]["charge"]["external_storage_bytes"] = charged
    _dump(report, report_value)

    ledger_value = json.loads(ledger.read_text(encoding="utf-8"))
    ledger_value["charges"][0]["external_storage_bytes"] = charged
    _dump(ledger, ledger_value)

    evidence_value = json.loads(evidence.read_text(encoding="utf-8"))
    evidence_value["actual_returned_report_sha256"] = V4.sha256_file(report)
    _dump(evidence, evidence_value)


def test_legacy_equal_current_contract_remains_valid(tmp_path: Path) -> None:
    paths = V3_TEST_MODULE._fixture(tmp_path)
    value = V4.inspect_binding(request_path=paths[0], report_path=paths[1],
                               receipt_path=paths[2], evidence_path=paths[3],
                               ledger_path=paths[4])
    assert value["status"] == "READY_FOR_SAME_PARENT_TERMINAL_DELTA"
    assert value["returned_parent_report"]["external_current_bytes"] == 10
    assert value["returned_parent_report"]["external_peak_bytes"] == 10
    assert value["returned_parent_report"]["external_charge_bytes"] == 10


def test_actual_current_and_conservative_peak_split_is_accepted(tmp_path: Path) -> None:
    paths = V3_TEST_MODULE._fixture(tmp_path)
    _set_external_contract(paths, current=1_318_998_748, peak=1_337_396_745,
                           charged=1_337_396_745)
    value = V4.inspect_binding(request_path=paths[0], report_path=paths[1],
                               receipt_path=paths[2], evidence_path=paths[3],
                               ledger_path=paths[4])
    returned = value["returned_parent_report"]
    assert returned["external_current_bytes"] == 1_318_998_748
    assert returned["external_peak_bytes"] == 1_337_396_745
    assert returned["external_charge_bytes"] == 1_337_396_745


def test_peak_below_current_is_rejected(tmp_path: Path) -> None:
    paths = V3_TEST_MODULE._fixture(tmp_path)
    _set_external_contract(paths, current=101, peak=100, charged=100)
    with pytest.raises(V4.ReconciliationError, match="peak is below"):
        V4.inspect_binding(request_path=paths[0], report_path=paths[1],
                           receipt_path=paths[2], evidence_path=paths[3],
                           ledger_path=paths[4])


def test_charge_below_declared_peak_is_rejected(tmp_path: Path) -> None:
    paths = V3_TEST_MODULE._fixture(tmp_path)
    _set_external_contract(paths, current=100, peak=125, charged=120)
    with pytest.raises(V4.ReconciliationError, match="exact external peak"):
        V4.inspect_binding(request_path=paths[0], report_path=paths[1],
                           receipt_path=paths[2], evidence_path=paths[3],
                           ledger_path=paths[4])


def test_duplicate_peak_fields_must_agree(tmp_path: Path) -> None:
    paths = V3_TEST_MODULE._fixture(tmp_path)
    _set_external_contract(paths, current=100, peak=125, charged=125, second_peak=124)
    with pytest.raises(V4.ReconciliationError, match="peak fields differ"):
        V4.inspect_binding(request_path=paths[0], report_path=paths[1],
                           receipt_path=paths[2], evidence_path=paths[3],
                           ledger_path=paths[4])
