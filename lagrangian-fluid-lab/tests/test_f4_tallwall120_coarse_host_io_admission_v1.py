"""Synthetic/source-bound tests for the F4 coarse host-I/O projection."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts import f4_tallwall120_coarse_host_io_admission_v1 as adapter


ROOT = Path(__file__).resolve().parents[1]
PROPOSAL = ROOT / adapter.PROPOSAL
HOST_IO = ROOT / adapter.HOST_IO_RECEIPT
JOB_SPEC = ROOT / adapter.JOB_SPEC
REPORT = ROOT / (
    "reports/F4-TALLWALL120-COARSE-HOST-IO-ADMISSION-PROJECTION-2026-09-28.json"
)
ZH_REPORT = ROOT / (
    "reports/F4-TALLWALL120-COARSE-HOST-IO-ADMISSION-PROJECTION-2026-09-28.zh-CN.md"
)


def _write_json(path: Path, value: dict) -> Path:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture(scope="module")
def current_projection() -> dict:
    return adapter.build_projection(ROOT)


def test_current_f4_projection_is_bound_but_never_authorizing(
    current_projection: dict,
) -> None:
    assert adapter.validate_projection(current_projection) == []
    assert current_projection["status"] == "diagnostic_admission_blocked"
    assert current_projection["synthetic_only"] is True
    assert current_projection["diagnostic_only"] is True

    checks = current_projection["checks"]
    for name in (
        "proposal_contract_valid",
        "f4_scope_binding",
        "host_io_receipt_valid",
        "host_probe_pass",
        "host_f4_scope",
        "f4_job_contract_valid",
        "f4_job_normalized_argv",
        "f4_job_cwd",
        "fresh_output_namespace_absent",
        "resource_projection_shape",
        "resource_disk_headroom_observed",
        "resource_gpu_declaration_shape",
        "input_contract_valid",
    ):
        assert checks[name] is True, name

    assert current_projection["scope"] == {
        "family": "F4",
        "scope_id": adapter.SCOPE_ID,
        "case_id": adapter.CASE_ID,
        "job_id": adapter.JOB_ID,
    }
    assert current_projection["authorization_boundary"]["authorization_missing"] is True
    assert current_projection["authorization_boundary"]["root_authorization_present"] is False
    assert current_projection["authorization_boundary"]["scheduler_authorization_present"] is False
    assert current_projection["decision"]["launch_admitted"] is False
    assert current_projection["decision"]["worker_launch_authorized"] is False
    assert current_projection["decision"]["formal"] is False
    assert current_projection["decision"]["credit"] == 0
    assert current_projection["resource_projection"]["job_resources"] == {
        "cpu_cores": 2,
        "ram_mib": 24576,
        "gpu_peak_mib": 6144,
        "io_weight": 2,
    }
    assert current_projection["resource_projection"]["gpu"]["allocation_observed"] is False
    assert current_projection["resource_projection"]["gpu"]["scheduler_authorized"] is False


def test_proposal_scope_drift_fails_closed(tmp_path: Path) -> None:
    proposal = json.loads(PROPOSAL.read_text(encoding="utf-8"))
    proposal["target"]["scope_id"] = "F4_wrong_scope"
    report = adapter.build_projection(
        ROOT, proposal_path=_write_json(tmp_path / "scope-drift.json", proposal)
    )

    assert report["status"] == "failed_closed"
    assert report["checks"]["f4_scope_binding"] is False
    assert report["decision"]["launch_admitted"] is False
    assert report["credit"] == 0


def test_host_family_scope_drift_fails_closed(tmp_path: Path) -> None:
    receipt = json.loads(HOST_IO.read_text(encoding="utf-8"))
    receipt["request"]["family_scope"] = ["F3"]
    report = adapter.build_projection(
        ROOT, host_io_receipt_path=_write_json(tmp_path / "host-scope-drift.json", receipt)
    )

    assert report["status"] == "failed_closed"
    assert report["checks"]["host_f4_scope"] is False
    assert report["checks"]["host_io_receipt_valid"] is False
    assert report["authorization_boundary"]["worker_launch_authorized"] is False


def test_job_cwd_and_normalized_argv_drift_fail_closed(tmp_path: Path) -> None:
    job = json.loads(JOB_SPEC.read_text(encoding="utf-8"))
    job["cwd"] = "/tmp/not-the-lab"
    job["argv"][job["argv"].index("--output") + 1] = "{attempt_dir}/reused"
    report = adapter.build_projection(
        ROOT, job_spec_path=_write_json(tmp_path / "job-drift.json", job)
    )

    assert report["status"] == "failed_closed"
    assert report["checks"]["f4_job_cwd"] is False
    assert report["checks"]["f4_job_normalized_argv"] is False
    assert report["checks"]["f4_job_fresh_attempt_output"] is False
    assert report["launch_admitted"] is False


def test_job_resource_drift_does_not_become_a_capacity_claim(tmp_path: Path) -> None:
    job = json.loads(JOB_SPEC.read_text(encoding="utf-8"))
    job["resources"]["gpu_peak_mib"] = 12288
    report = adapter.build_projection(
        ROOT, job_spec_path=_write_json(tmp_path / "resource-drift.json", job)
    )

    assert report["status"] == "failed_closed"
    assert report["checks"]["f4_job_spec_resources"] is False
    assert report["checks"]["resource_projection_shape"] is False
    assert report["resource_projection"]["capacity_or_authorization_claim"] is False
    assert report["resource_projection"]["gpu"]["scheduler_authorized"] is False


def test_fresh_namespace_policy_drift_fails_closed(tmp_path: Path) -> None:
    proposal = json.loads(PROPOSAL.read_text(encoding="utf-8"))
    proposal["planned_output_namespace"]["overwrite_allowed"] = True
    report = adapter.build_projection(
        ROOT, proposal_path=_write_json(tmp_path / "namespace-drift.json", proposal)
    )

    assert report["status"] == "failed_closed"
    assert report["checks"]["fresh_output_namespace_contract"] is False
    assert report["checks"]["fresh_output_namespace_absent"] is False
    assert report["decision"]["worker_launch_authorized"] is False


def test_projection_never_opens_or_hashes_large_hdf5(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_open = Path.open

    def guarded_open(path: Path, *args, **kwargs):
        if path.suffix.lower() in {".h5", ".hdf5"}:
            raise AssertionError(f"projection attempted HDF5 access: {path}")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    report = adapter.build_projection(ROOT)

    assert report["input_boundary"]["large_hdf5_opened"] is False
    assert report["input_boundary"]["large_hdf5_hashed"] is False
    assert report["input_boundary"]["large_hdf5_content_read"] is False


def test_serialized_non_authorizing_markers_cannot_drift(
    current_projection: dict,
) -> None:
    bad = deepcopy(current_projection)
    bad["formal"] = True
    bad["decision"]["credit"] = 1
    bad["authorization_boundary"]["root_authorization_present"] = True
    bad["execution_controls"]["gate_mutations"] = 1

    errors = adapter.validate_projection(bad)
    assert "formal" in errors
    assert "decision.credit" in errors
    assert "authorization_boundary.root_authorization_present" in errors
    assert "execution_controls.gate_mutations" in errors


def test_committed_json_and_chinese_reports_bind_current_projection(
    current_projection: dict,
) -> None:
    committed = json.loads(REPORT.read_text(encoding="utf-8"))
    assert adapter.validate_projection(committed) == []
    assert committed == current_projection
    text = ZH_REPORT.read_text(encoding="utf-8")
    assert text.startswith("# F4 Tallwall120 coarse host-I/O admission projection")
    assert "fresh_root_authorization_missing" in text
    assert "未解析、打开、哈希或读取" in text


def test_report_writers_never_overwrite(tmp_path: Path, current_projection: dict) -> None:
    output = tmp_path / "projection.json"
    zh_output = tmp_path / "projection.zh-CN.md"
    assert adapter.write_report(current_projection, output) == output
    assert adapter.write_zh_cn(current_projection, zh_output) == zh_output
    with pytest.raises(FileExistsError):
        adapter.write_report(current_projection, output)
    with pytest.raises(FileExistsError):
        adapter.write_zh_cn(current_projection, zh_output)
