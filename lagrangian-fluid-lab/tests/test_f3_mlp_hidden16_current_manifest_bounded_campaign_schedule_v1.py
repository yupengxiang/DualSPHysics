"""Tests for the read-only F3 MLP bounded campaign schedule planner."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import f3_mlp_hidden16_current_manifest_bounded_campaign_schedule_v1 as schedule


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_sha(value: object) -> str:
    return _sha_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())


def _write_json(path: Path, value: object) -> dict[str, object]:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"path": str(path), "bytes": len(raw), "sha256": _sha_bytes(raw)}


def _manifest_payload(case_count: int = 32) -> dict[str, object]:
    cases = []
    for index in range(case_count):
        case_id = f"F3_DEV_{index:02d}_a0p{903125 + index:06d}"
        split = "test" if index < 16 else ("validation" if index < 24 else "train")
        cases.append(
            {
                "bytes": 900000000 + index,
                "case_id": case_id,
                "evaluation_role": "development_extrapolation" if split == "test" else "development_interpolation",
                "family": "F3",
                "hdf5": f"campaigns/data/{case_id}.h5",
                "known_inputs_sha256": _sha_bytes(f"known-{index}".encode()),
                "lineage_group_id": _sha_bytes(f"lineage-{index}".encode()),
                "physical_case_id": case_id,
                "qualification_case": False,
                "scope_id": "F3_SCOPE",
                "sha256": _sha_bytes(f"artifact-{index}".encode()),
                "split": split,
            }
        )
    return {
        "case_count": case_count,
        "cases": cases,
        "dataset_id": "F3_registered32_core_native_v2",
        "formal_release": False,
        "input_asset_policy": "content_addressed_compressed_npz",
        "schema": "core.dataset.v2",
        "source_manifest_sha256": "f" * 64,
    }


def _training_payload(manifest_source: dict[str, object], manifest_sha: str, tmp_path: Path) -> dict[str, object]:
    runs = []
    for seed in schedule.SEEDS:
        run_id = f"f3-mlp500-hidden16-currentmanifest-seed{seed}-20260929"
        receipt = {
            "path": str(tmp_path / f"receipt-{seed}.json"),
            "bytes": 10000 + seed,
            "sha256": _sha_bytes(f"receipt-{seed}".encode()),
        }
        checkpoint = {
            "path": str(tmp_path / f"checkpoint-{seed}.pt"),
            "bytes": 64000 + seed,
            "sha256": _sha_bytes(f"checkpoint-{seed}".encode()),
            "schema": "core.checkpoint.v1",
            "update": schedule.UPDATES,
        }
        runs.append(
            {
                "seed": seed,
                "status": "bound",
                "source": {**receipt, "schema": "core.training.v1", "opened": True},
                "evidence": {
                    "checkpoint_identity": checkpoint,
                    "completed": True,
                    "hidden": schedule.HIDDEN,
                    "manifest_sha256": manifest_sha,
                    "model": schedule.MODEL,
                    "receipt_identity": receipt,
                    "run_id": run_id,
                    "schema": "core.training.v1",
                    "seed": seed,
                    "updates": schedule.UPDATES,
                    "zero_credit": dict(schedule.ZERO_CREDIT),
                },
            }
        )
    return {
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "authorization": dict(schedule.ZERO_CREDIT),
        "credit": 0,
        "diagnostic_only": True,
        "errors": [],
        "fail_closed": False,
        "formal": False,
        "formal_eligible": False,
        "formal_training_runs_counted": 0,
        "hidden": schedule.HIDDEN,
        "manifest": {
            "bytes": manifest_source["bytes"],
            "canonical_sha256": manifest_sha,
            "opened": True,
            "path": manifest_source["path"],
            "schema": "core.dataset.v2",
            "sha256": manifest_source["sha256"],
        },
        "model": schedule.MODEL,
        "qualification": False,
        "qualification_credit": 0,
        "report_id": "f3-mlp-hidden16-current-manifest-training-evidence-v1",
        "runs": runs,
        "schema": schedule.TRAINING_SCHEMA,
        "source_bound": True,
        "status": "diagnostic_bound",
        "t1_case_runs_counted": 0,
        "t2_macro_families_counted": 0,
        "updates": schedule.UPDATES,
    }


def _fixture(tmp_path: Path) -> dict[str, object]:
    manifest = tmp_path / "lab" / "f3-dataset-v2.json"
    payload = _manifest_payload()
    manifest_source = _write_json(manifest, payload)
    training = tmp_path / "lab" / "training-identity.json"
    _write_json(training, _training_payload(manifest_source, _canonical_sha(payload), tmp_path))
    return {"manifest": manifest, "training": training, "output_root": tmp_path / "planned"}


def _build(fixture: dict[str, object], **overrides: object) -> dict[str, object]:
    values = {
        "manifest": fixture["manifest"],
        "training_identity": fixture["training"],
        "output_root": fixture["output_root"],
        "campaign_id": "pytest-f3-bounded-20260929",
        "plan_date": "20260929",
    }
    values.update(overrides)
    return schedule.build_schedule(**values)


def test_schedule_covers_exact_32_by_3_with_seed_isolated_batches(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    report = _build(fixture)

    assert report["status"] == "dry_run_schedule_ready"
    assert report["coverage"]["job_count"] == 96
    assert report["coverage"]["batch_count"] == 12
    assert report["coverage"]["exact_case_seed_coverage"] is True
    assert all(len(batch["jobs"]) <= 8 for batch in report["batches"])
    assert {batch["seed"] for batch in report["batches"]} == set(schedule.SEEDS)
    assert all(len({job["seed"] for job in batch["jobs"]}) == 1 for batch in report["batches"])
    assert all(
        [item["gpu_index"] for item in batch["gpu_slot_mapping"]]
        == list(range(len(batch["jobs"])))
        for batch in report["batches"]
    )
    assert len({batch["batch_id"] for batch in report["batches"]}) == 12
    assert len({batch["output_report"] for batch in report["batches"]}) == 12
    assert len({job["output_namespace"] for batch in report["batches"] for job in batch["jobs"]}) == 96
    assert report["credit"] == 0
    assert report["diagnostic_only"] is True
    assert not Path(fixture["output_root"]).exists()
    schedule.validate_report(report)


def test_planner_does_not_require_hdf5_or_checkpoint_files(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    report = _build(fixture, estimated_output_bytes_per_case=1234567)
    assert report["input_boundary"]["hdf5_content_opened"] is False
    assert report["input_boundary"]["checkpoint_content_opened"] is False
    assert report["output_space"]["estimated_bytes_per_case"] == 1234567
    assert all(not Path(job["checkpoint_identity"]["path"]).exists() for batch in report["batches"] for job in batch["jobs"])


@pytest.mark.parametrize("mutation", ["formal", "wrong_case_count", "duplicate_case", "duplicate_hdf5"])
def test_manifest_fail_closed_for_formal_non32_or_duplicate_inputs(tmp_path: Path, mutation: str) -> None:
    fixture = _fixture(tmp_path)
    payload = json.loads(Path(fixture["manifest"]).read_text(encoding="utf-8"))
    if mutation == "formal":
        payload["formal_release"] = True
    elif mutation == "wrong_case_count":
        payload["case_count"] = 31
        payload["cases"] = payload["cases"][:-1]
    elif mutation == "duplicate_case":
        payload["cases"][1]["case_id"] = payload["cases"][0]["case_id"]
        payload["cases"][1]["physical_case_id"] = payload["cases"][0]["physical_case_id"]
    else:
        payload["cases"][1]["hdf5"] = payload["cases"][0]["hdf5"]
    _write_json(Path(fixture["manifest"]), payload)
    with pytest.raises(schedule.ScheduleError, match="fail-closed"):
        _build(fixture)


def test_training_duplicate_seed_and_batch_size_above_bound_are_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    payload = json.loads(Path(fixture["training"]).read_text(encoding="utf-8"))
    payload["runs"][1]["seed"] = schedule.SEEDS[0]
    _write_json(Path(fixture["training"]), payload)
    with pytest.raises(schedule.ScheduleError, match="duplicate or unexpected seed"):
        _build(fixture)

    fixture = _fixture(tmp_path / "batch-size")
    with pytest.raises(schedule.ScheduleError, match="batch_size"):
        _build(fixture, batch_size=9)


def test_existing_planned_report_is_a_path_conflict(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    first = _build(fixture)
    planned_report = Path(first["batches"][0]["output_report"])
    planned_report.parent.mkdir(parents=True)
    planned_report.write_text("occupied\n", encoding="utf-8")
    with pytest.raises(schedule.ScheduleError, match="already exists"):
        _build(fixture)


def test_cli_writes_json_markdown_and_verify_is_read_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fixture = _fixture(tmp_path)
    output = tmp_path / "schedule.json"
    markdown = tmp_path / "schedule.zh-CN.md"
    result = schedule.main(
        [
            "--manifest", str(fixture["manifest"]),
            "--training-identity", str(fixture["training"]),
            "--output-root", str(fixture["output_root"]),
            "--campaign-id", "pytest-cli-f3-bounded-20260929",
            "--plan-date", "20260929",
            "--output", str(output),
            "--markdown-output", str(markdown),
        ]
    )
    assert result == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["jobs"] == 96
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "dry_run_schedule_ready"
    assert "seed 隔离" in markdown.read_text(encoding="utf-8")
    assert not Path(fixture["output_root"]).exists()

    result = schedule.main(["--verify-report", str(output)])
    assert result == 0
    assert json.loads(capsys.readouterr().out)["status"] == "verified"
