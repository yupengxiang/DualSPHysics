"""Tests for the additive current-manifest F3 MLP diagnostic batch boundary."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

from scripts import f3_mlp_hidden16_current_manifest_diagnostic_batch_v1 as batch


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_sha(value: object) -> str:
    return _sha_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode()
        + b"\n"
    )


def _fixture(tmp_path: Path) -> dict[str, object]:
    root = tmp_path / "lab"
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "reports").mkdir()
    python_path = root / ".venv" / "bin" / "python"
    python_path.write_bytes(Path(sys.executable).resolve().read_bytes())
    python_path.chmod(0o755)
    (root / "scripts" / "core_learning.py").write_text("# fixture\n", encoding="utf-8")

    cases = []
    data_root = root / "campaigns" / "core-v1" / "data"
    for index in range(batch.EXPECTED_CASE_COUNT):
        case_id = f"F3_DEV_{index:02d}_a0p{903125 + index:06d}"
        split = "test" if index < 16 else ("validation" if index < 24 else "train")
        hdf5 = data_root / f"{case_id}.h5"
        raw = bytes([index + 1]) * (64 + index)
        hdf5.parent.mkdir(parents=True, exist_ok=True)
        hdf5.write_bytes(raw)
        cases.append(
            {
                "bytes": len(raw),
                "case_id": case_id,
                "evaluation_role": "development_extrapolation" if split == "test" else "development_interpolation",
                "family": "F3",
                "hdf5": str(hdf5.relative_to(root)),
                "known_inputs_sha256": _sha_bytes(f"known-{index}".encode()),
                "lineage_group_id": _sha_bytes(f"lineage-{index}".encode()),
                "physical_case_id": case_id,
                "qualification_case": False,
                "scope_id": "F3_CELL3_NS_visco1_native_nopen_revision075_ref0081818",
                "sha256": _sha_bytes(f"artifact-{index}".encode()),
                "split": split,
            }
        )
    manifest_payload = {
        "case_count": batch.EXPECTED_CASE_COUNT,
        "cases": cases,
        "dataset_id": "F3_registered32_core_native_v2",
        "formal_release": False,
        "input_asset_policy": "content_addressed_compressed_npz",
        "schema": "core.dataset.v2",
        "source_manifest_sha256": "f" * 64,
    }
    manifest = root / "campaigns" / "core-v1" / "f3-dataset-v2.json"
    _write_json(manifest, manifest_payload)
    manifest_sha = _canonical_sha(manifest_payload)

    checkpoint = tmp_path / "f3-seed17-checkpoint.pt"
    checkpoint_raw = b"real-bound-checkpoint"
    checkpoint.write_bytes(checkpoint_raw)
    run_id = "f3-mlp500-hidden16-currentmanifest-seed17-20260929"
    training = tmp_path / "f3-seed17-training.json"
    checkpoint_identity = {
        "schema": "core.checkpoint.v1",
        "path": str(checkpoint),
        "sha256": _sha_bytes(checkpoint_raw),
        "bytes": len(checkpoint_raw),
        "update": batch.UPDATES,
    }
    _write_json(
        training,
        {
            "schema": "core.training.v1",
            "evidence_status": "complete",
            "checkpoint_verified": True,
            "model_kind": batch.MODEL,
            "seed": 17,
            "completed_updates": batch.UPDATES,
            "run_id": run_id,
            "checkpoint": checkpoint_identity,
            "checkpoints": [checkpoint_identity],
            "config": {
                "manifest_sha256": manifest_sha,
                "model_kind": batch.MODEL,
                "hidden": batch.HIDDEN,
                "updates": batch.UPDATES,
                "run_id": run_id,
                "seed": 17,
                "paired_seed": 17,
                "sampler_seed": 17,
                "manifest_formal_release": False,
                "validation_formal_eligible": False,
            },
            **batch.ZERO_CREDIT,
        },
    )
    return {
        "root": root,
        "manifest": manifest,
        "checkpoint": checkpoint,
        "training": training,
        "run_id": run_id,
        "case_ids": tuple(case["case_id"] for case in cases),
    }


def _plans(fixture: dict[str, object], tmp_path: Path, *, cases: tuple[str, ...] = ()):
    selected = cases or (fixture["case_ids"][0], fixture["case_ids"][1])
    output_root = tmp_path / "outputs"
    output_root.mkdir(parents=True, exist_ok=True)
    return batch.build_plans(
        root=fixture["root"],
        manifest=fixture["manifest"],
        checkpoint=fixture["checkpoint"],
        training_receipt=fixture["training"],
        run_id=fixture["run_id"],
        seed=17,
        case_ids=selected,
        batch_id="pytest-batch-20260929",
        output_root=output_root,
        gpu_indices=(2, 3),
    )


def test_build_plans_bind_real_manifest_receipt_checkpoint_and_multiple_cases(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plans = _plans(fixture, tmp_path)

    assert len(plans) == 2
    assert [plan.case["case_id"] for plan in plans] == list(fixture["case_ids"][:2])
    assert [plan.gpu_index for plan in plans] == [2, 3]
    assert len({str(plan.output_namespace) for plan in plans}) == 2
    assert len({plan.nonce for plan in plans}) == 2
    assert all("--diagnostic" in plan.command for plan in plans)
    assert all(plan.command[plan.command.index("--maximum-steps") + 1] == "835" for plan in plans)
    assert all(plan.manifest_sha256 for plan in plans)
    assert all(plan.checkpoint["path"] == str(fixture["checkpoint"]) for plan in plans)
    assert all(plan.training_receipt_sha256 for plan in plans)
    assert all(plan.as_dict()["launch_allowed"] is False for plan in plans)
    assert all(plan.as_dict()["credit"] == 0 for plan in plans)
    assert all(plan.case["hdf5"].is_file() for plan in plans)


def test_hdf5_hardlinks_are_allowed_but_symlink_case_input_fails_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    case0 = Path(fixture["root"]) / "campaigns" / "core-v1" / "data" / f"{fixture['case_ids'][0]}.h5"
    hardlink = tmp_path / "hardlink.h5"
    os.link(case0, hardlink)
    assert case0.stat().st_nlink >= 2
    assert _plans(fixture, tmp_path)[0].case["hdf5_bytes"] == case0.stat().st_size

    case1 = Path(fixture["root"]) / "campaigns" / "core-v1" / "data" / f"{fixture['case_ids'][1]}.h5"
    replacement = tmp_path / "case1-real.h5"
    replacement.write_bytes(case1.read_bytes())
    case1.unlink()
    case1.symlink_to(replacement)
    with pytest.raises(batch.BatchError, match="symlink"):
        _plans(fixture, tmp_path)


def test_unknown_case_and_formal_manifest_are_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    with pytest.raises(batch.BatchError, match="absent"):
        _plans(fixture, tmp_path, cases=("F3_DEV_99_a9p999999",))

    manifest_payload = json.loads(Path(fixture["manifest"]).read_text(encoding="utf-8"))
    manifest_payload["formal_release"] = True
    _write_json(Path(fixture["manifest"]), manifest_payload)
    with pytest.raises(batch.BatchError, match="formal_release"):
        _plans(fixture, tmp_path)


def test_dry_report_is_bounded_multi_case_zero_credit(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plans = _plans(fixture, tmp_path)
    report = batch._report_for(
        plans,
        results=None,
        batch_id="pytest-batch-20260929",
        min_free_mib=batch.MIN_FREE_MIB,
        initial_gpu_snapshot={},
    )

    assert report["status"] == "dry_run_ready"
    assert report["coverage"]["selected_case_count"] == 2
    assert report["coverage"]["terminal_receipts_observed"] == 0
    assert report["terminal_receipts"]["missing_count"] == 2
    assert report["diagnostic_only"] is True
    assert report["credit"] == 0
    assert report["side_effects"]["registry_writes"] == 0
    assert report["side_effects"]["processes_stopped"] == 0
    batch._validate_report(report)


def test_injectable_batch_worker_preserves_case_order_without_gpu_or_process_side_effects(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plans = _plans(fixture, tmp_path)
    observed: list[str] = []

    def fake_worker(plan, min_free_mib):
        observed.append(plan.case["case_id"])
        return {
            "status": "exited_successfully",
            "case_id": plan.case["case_id"],
            "diagnostic_only": True,
            "formal": False,
            "formal_eligible": False,
            "T1_numerical": False,
            "T2_macro": False,
            "T2_path": False,
            "qualification": False,
            "qualification_credit": 0,
            "credit": 0,
        }

    results = batch.execute_batch(plans, worker_factory=fake_worker)
    assert observed == [plan.case["case_id"] for plan in plans]
    assert [result["status"] for result in results] == ["exited_successfully", "exited_successfully"]
    assert all(result["credit"] == 0 for result in results)


def test_gpu_snapshot_parser_accepts_shared_occupied_device() -> None:
    snapshots = batch._parse_nvidia_smi(
        "0, 12000, 37140, 49140, 83\n"
        "1, 15, 49125, 49140, 0\n"
    )
    assert snapshots[0]["memory_used_mib"] == 12000
    assert snapshots[0]["memory_free_mib"] == 37140
    assert snapshots[1]["memory_free_mib"] == 49125
