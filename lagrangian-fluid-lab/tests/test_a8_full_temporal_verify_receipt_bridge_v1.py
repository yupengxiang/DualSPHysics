from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from scripts import a8_full_temporal_verify_receipt_bridge_v1 as bridge


LAB_ROOT = Path(__file__).resolve().parents[1]
VERIFICATION = LAB_ROOT / "reports" / bridge.VERIFICATION_FILENAME
PACKAGE = LAB_ROOT / bridge.DEFAULT_PACKAGE_RELATIVE


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_actual(tmp_path: Path) -> tuple[dict, Path, Path, Path, Path]:
    root = tmp_path / "lab"
    report_path = root / "reports" / bridge.VERIFICATION_FILENAME
    package_path = root / "campaigns/core-v1/reproduction/a8-full-reproduce-v2"
    report_path.parent.mkdir(parents=True)
    package_path.mkdir(parents=True)
    shutil.copyfile(VERIFICATION, report_path)
    shutil.copyfile(PACKAGE / "bundle.json", package_path / "bundle.json")
    shutil.copyfile(PACKAGE / "dataset.json", package_path / "dataset.json")
    output = root / "reports/bridge.json"
    zh_output = root / "reports/bridge.zh-CN.md"
    result = bridge.build_bridge_report(
        verification_report=report_path,
        package_root=package_path,
        lab_root=root,
        output=output,
        zh_output=zh_output,
    )
    return result, root, report_path, package_path, output


def test_actual_a8_full_temporal_receipt_binds_32_of_32_and_is_zero_credit(tmp_path):
    report, root, report_path, package_path, output = _build_actual(tmp_path)

    assert report["passed"] is True
    assert report["blocked"] is False
    assert report["diagnostic_only"] is True
    assert report["qualification_inferred"] is False
    assert report["qualification_credit"] == 0
    assert report["claims"] == bridge.ZERO_CREDIT_CLAIMS
    assert report["mutations"] == bridge.ZERO_MUTATIONS
    assert report["package"]["package_root"]["path"] == "campaigns/core-v1/reproduction/a8-full-reproduce-v2"
    assert report["package"]["bundle"]["sha256"] == _sha(package_path / "bundle.json")
    assert report["package"]["dataset"]["sha256"] == _sha(package_path / "dataset.json")
    assert report["verification"]["full_temporal_case_count"] == 32
    assert report["verification"]["manifest_sha256"] == _sha(package_path / "dataset.json")
    assert report["read_boundary"]["hdf5_opened"] is False
    assert report["read_boundary"]["npz_opened"] is False
    assert report["read_boundary"]["checkpoint_opened"] is False
    assert output.exists()
    assert (root / "reports/bridge.zh-CN.md").exists()
    assert bridge.validate_report_file(
        bridge_path=output,
        verification_report=report_path,
        package_root=package_path,
        lab_root=root,
    ) == []


def test_actual_hashes_match_recorded_receipt_and_package_identity():
    report = json.loads(VERIFICATION.read_text(encoding="utf-8"))
    bundle = json.loads((PACKAGE / "bundle.json").read_text(encoding="utf-8"))
    dataset = PACKAGE / "dataset.json"
    dataset_entry = next(item for item in bundle["files"] if item["path"] == "dataset.json")
    assert report["manifest_sha256"] == _sha(dataset)
    assert dataset_entry["sha256"] == _sha(dataset)
    assert dataset_entry["bytes"] == dataset.stat().st_size


@pytest.mark.parametrize(
    ("field", "value", "needle"),
    [
        ("transition_count", 834, "verification_case_transition_count_drift"),
        ("passed", False, "verification_case_not_passed"),
        ("full_temporal_scan", False, "verification_full_temporal_scan_must_be_true"),
        ("qualification_inferred", True, "verification_qualification_inferred_must_be_false"),
    ],
)
def test_semantic_drift_is_blocked(tmp_path, field, value, needle):
    root = tmp_path / "lab"
    report_path = root / "reports" / bridge.VERIFICATION_FILENAME
    package_path = root / "campaigns/core-v1/reproduction/a8-full-reproduce-v2"
    report_path.parent.mkdir(parents=True)
    package_path.mkdir(parents=True)
    payload = json.loads(VERIFICATION.read_text(encoding="utf-8"))
    if field in {"transition_count", "passed"}:
        payload["cases"][0][field] = value
    else:
        payload[field] = value
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    shutil.copyfile(PACKAGE / "bundle.json", package_path / "bundle.json")
    shutil.copyfile(PACKAGE / "dataset.json", package_path / "dataset.json")

    result = bridge.build_bridge_report(
        verification_report=report_path,
        package_root=package_path,
        lab_root=root,
    )
    assert result["passed"] is False
    assert any(needle in blocker for blocker in result["blockers"])
    assert result["claims"]["credit"] == 0


def test_bundle_dataset_sha_drift_and_case_set_drift_are_blocked(tmp_path):
    root = tmp_path / "lab"
    report_path = root / "reports" / bridge.VERIFICATION_FILENAME
    package_path = root / "campaigns/core-v1/reproduction/a8-full-reproduce-v2"
    report_path.parent.mkdir(parents=True)
    package_path.mkdir(parents=True)
    shutil.copyfile(VERIFICATION, report_path)
    shutil.copyfile(PACKAGE / "bundle.json", package_path / "bundle.json")
    dataset = json.loads((PACKAGE / "dataset.json").read_text(encoding="utf-8"))
    dataset["cases"][0]["case_id"] = "F3_DEV_DRIFTED"
    (package_path / "dataset.json").write_text(json.dumps(dataset), encoding="utf-8")

    result = bridge.build_bridge_report(
        verification_report=report_path,
        package_root=package_path,
        lab_root=root,
    )
    assert result["passed"] is False
    assert any("bundle_dataset_sha256_drift" in item for item in result["blockers"])
    assert any("verification_case_not_in_dataset" in item for item in result["blockers"])


def test_duplicate_keys_nonfinite_values_and_size_limits_are_rejected(tmp_path):
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema":"x","schema":"y"}', encoding="utf-8")
    raw, _ = bridge._read_raw(duplicate, label="duplicate", max_bytes=1024)
    with pytest.raises(bridge.BridgeContractError, match="strict JSON"):
        bridge._parse_json(raw, label="duplicate", max_bytes=1024)

    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text('{"value":NaN}', encoding="utf-8")
    raw, _ = bridge._read_raw(nonfinite, label="nonfinite", max_bytes=1024)
    with pytest.raises(bridge.BridgeContractError, match="strict JSON"):
        bridge._parse_json(raw, label="nonfinite", max_bytes=1024)

    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b"{" + b"a" * 32 + b"}")
    with pytest.raises(bridge.BridgeContractError, match="exceeds"):
        bridge._read_raw(oversized, label="oversized", max_bytes=16)


def test_symlinked_inputs_and_non_json_assets_are_never_opened(tmp_path):
    target = tmp_path / "target.json"
    target.write_text('{"schema":"x"}', encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(bridge.BridgeContractError, match="symlink"):
        bridge._read_raw(link, label="symlink", max_bytes=1024)

    report, *_ = _build_actual(tmp_path / "actual")
    boundary = report["read_boundary"]
    assert boundary["verification_json_opened"] is True
    assert boundary["bundle_json_opened"] is True
    assert boundary["dataset_json_opened"] is True
    assert all(boundary[key] is False for key in (
        "hdf5_opened", "npz_opened", "checkpoint_opened", "training_started",
        "solver_started", "worker_or_queue_started", "gpu_started",
    ))


def test_missing_input_builds_blocked_report_and_cli_returns_nonzero(tmp_path):
    root = tmp_path / "lab"
    package_path = root / "campaigns/core-v1/reproduction/a8-full-reproduce-v2"
    package_path.mkdir(parents=True)
    shutil.copyfile(PACKAGE / "bundle.json", package_path / "bundle.json")
    shutil.copyfile(PACKAGE / "dataset.json", package_path / "dataset.json")
    output = root / "reports/blocked.json"
    zh_output = root / "reports/blocked.md"

    result = bridge.build_bridge_report(
        verification_report=root / "reports" / bridge.VERIFICATION_FILENAME,
        package_root=package_path,
        lab_root=root,
        output=output,
        zh_output=zh_output,
    )
    assert result["passed"] is False
    assert result["claims"]["credit"] == 0
    assert output.exists()
    assert zh_output.exists()
    assert bridge.main([
        "validate",
        "--lab-root", str(root),
        "--bridge", str(output),
        "--verification", str(root / "reports" / bridge.VERIFICATION_FILENAME),
        "--package-root", str(package_path),
    ]) == 2


def test_validate_report_rejects_claim_and_boundary_drift(tmp_path):
    report, *_ = _build_actual(tmp_path)
    mutated = copy.deepcopy(report)
    mutated["claims"]["credit"] = 1
    assert any("claims drift" in item for item in bridge.validate_report(mutated))
    mutated = copy.deepcopy(report)
    mutated["read_boundary"]["hdf5_opened"] = True
    assert any("hdf5_opened" in item for item in bridge.validate_report(mutated))
