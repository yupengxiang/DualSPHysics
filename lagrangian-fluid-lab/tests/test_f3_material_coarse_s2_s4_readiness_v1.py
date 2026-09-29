"""Bounded tests for the additive F3 coarse s2/s4 readiness sidecar."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts import f3_material_coarse_s2_s4_readiness_v1 as readiness


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / readiness.DEFAULT_REPORT
ZH_REPORT = ROOT / readiness.DEFAULT_ZH_CN


def test_current_rerun_is_source_and_scheduler_bound_but_blocked() -> None:
    value = readiness.build_report(ROOT)

    assert readiness.validate_report(value) == []
    assert value["status"] == readiness.STATUS_BLOCKED
    assert value["spec_projection"]["checks"] == {
        "s2_spec_contract_valid": True,
        "s4_spec_contract_valid": True,
        "shared_source_binding_valid": True,
        "shared_cwd_valid": True,
        "normalized_s2_argv_cwd_valid": True,
        "normalized_s4_argv_cwd_valid": True,
        "s2_s4_coarse_lineage_valid": True,
    }
    assert value["validation"]["checks"]["current_source_sha_bound"] is True
    assert value["validation"]["checks"]["normalized_argv_cwd_bound"] is True
    assert value["validation"]["checks"]["scheduler_entry_contract_valid"] is True
    assert value["fresh_one_shot_namespace"]["present"] is False
    assert value["fresh_one_shot_namespace"]["valid"] is False
    assert value["host_io_reservation"]["scheduler_receipt_present"] is False
    assert value["host_io_reservation"]["scheduler_reservation_valid"] is False
    assert value["authorization"]["credit"] == 0
    assert value["execution_controls"]["source_hdf5_opened"] is False
    assert value["execution_controls"]["worker_started"] is False


def test_s2_s4_bind_the_same_source_and_only_change_substeps() -> None:
    value = readiness.build_report(ROOT)
    s2 = value["spec_projection"]["s2"]
    s4 = value["spec_projection"]["s4"]

    assert s2["source"]["sha256"] == s4["source"]["sha256"]
    assert s2["source"]["sha256"] == value["spec_projection"]["shared_source_sha256"]
    assert s2["source"]["opened_as_hdf5"] is False
    assert s4["source"]["read"] is False
    assert s2["normalized_launch"]["cwd"] == str(ROOT)
    assert s4["normalized_launch"]["cwd"] == str(ROOT)
    assert s2["normalized_launch"]["substeps"] == 2
    assert s4["normalized_launch"]["substeps"] == 4

    s2_argv = s2["normalized_launch"]["argv"]
    s4_argv = s4["normalized_launch"]["argv"]
    s2_index = s2_argv.index("--substeps")
    s4_index = s4_argv.index("--substeps")
    assert s2_argv[:s2_index] == s4_argv[:s4_index]
    assert s2_argv[s2_index + 1] == "2"
    assert s4_argv[s4_index + 1] == "4"
    assert s2_argv[s2_index + 2 :] == s4_argv[s4_index + 2 :]


def test_s4_spec_drift_is_blocked_without_source_access(tmp_path: Path) -> None:
    spec = json.loads((ROOT / readiness.S4_SPEC).read_text(encoding="utf-8"))
    spec["cwd"] = "/tmp/not-the-lab"
    mutated = tmp_path / "s4.json"
    mutated.write_text(json.dumps(spec, sort_keys=True) + "\n", encoding="utf-8")

    value = readiness.build_report(ROOT, s4_spec_path=mutated)

    assert readiness.validate_report(value) == []
    assert value["status"] == readiness.STATUS_BLOCKED
    assert value["spec_projection"]["checks"]["s4_spec_contract_valid"] is False
    assert "s4.cwd" in value["validation"]["blockers"]
    assert value["authorization"]["launch_admitted"] is False
    assert value["execution_controls"]["source_hdf5_read"] is False


def test_source_hdf5_is_never_opened_or_hashed_by_the_sidecar(monkeypatch: pytest.MonkeyPatch) -> None:
    source_path = str((ROOT / readiness.intake.SOURCE_H5).absolute())
    real_open = readiness.intake.os.open

    def guarded_open(path: object, flags: int, *args: object) -> int:
        if str(path) == source_path:
            raise AssertionError("F3 source HDF5 must not be opened")
        return real_open(path, flags, *args)

    monkeypatch.setattr(readiness.intake.os, "open", guarded_open)
    value = readiness.build_report(ROOT)

    assert value["execution_controls"]["source_hdf5_opened"] is False
    assert value["execution_controls"]["source_hdf5_read"] is False
    assert value["execution_controls"]["source_hdf5_hash_recomputed"] is False


def test_scheduler_entry_contract_is_explicitly_current_bound() -> None:
    value = readiness.build_report(ROOT)
    contract = value["scheduler_entry_contract"]

    assert contract["sha256"] == value["input_bindings"]["core_runtime"]["sha256"]
    assert all(contract["entrypoints"].values())
    assert all(contract["markers"].values())
    assert contract["checks"]["prepare_consumes_one_shot"] is True
    assert contract["checks"]["worker_revalidates_runtime_identity"] is True


def test_committed_current_report_matches_live_projection() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))

    assert report == readiness.build_report(ROOT)
    assert readiness.validate_report(report) == []
    assert report["status"] == readiness.STATUS_BLOCKED
    assert ZH_REPORT.read_text(encoding="utf-8").startswith(
        "# F3 material coarse s2/s4 readiness"
    )


def test_report_writers_are_new_file_only(tmp_path: Path) -> None:
    value = readiness.build_report(ROOT)
    output = tmp_path / "readiness.json"
    zh_output = tmp_path / "readiness.zh-CN.md"

    assert readiness.write_report(value, output) == output
    assert readiness.write_zh_cn(value, zh_output) == zh_output
    with pytest.raises(FileExistsError):
        readiness.write_report(value, output)
    with pytest.raises(FileExistsError):
        readiness.write_zh_cn(value, zh_output)


def test_tampered_readiness_boundary_is_rejected() -> None:
    value = readiness.build_report(ROOT)
    forged = deepcopy(value)
    forged["authorization"]["credit"] = 1

    assert "authorization.fail_closed" in readiness.validate_report(forged)
