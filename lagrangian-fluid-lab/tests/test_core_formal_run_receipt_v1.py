"""Synthetic pass/fail tests for the read-only formal-run receipt contract."""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from scripts.core_formal_run_receipt_v1 import (
    MILESTONES,
    MODELS,
    SEEDS,
    ReceiptContractError,
    build_synthetic_receipt,
    expected_run_ids,
    verify_formal_run_matrix,
    verify_receipt,
    verify_receipt_set,
)


def _write_fixture_files(root: Path) -> dict[str, object]:
    files: dict[str, Path] = {}
    for name, content in {
        "dataset-manifest.json": b'{"dataset":"synthetic","split":"train"}\n',
        "source-closure.json": b'{"closure":"synthetic-source-v1"}\n',
        "training-config.json": b'{"updates":32000,"centers":16,"test_included":false}\n',
    }.items():
        path = root / name
        path.write_bytes(content)
        files[name] = path
    checkpoints: dict[int, Path] = {}
    validation: dict[int, Path] = {}
    for milestone in MILESTONES:
        checkpoint = root / f"checkpoint-{milestone}.bin"
        validation_report = root / f"validation-{milestone}.json"
        checkpoint.write_bytes(f"checkpoint:{milestone}\n".encode())
        validation_report.write_bytes(f'{{"milestone":{milestone},"ok":true}}\n'.encode())
        checkpoints[milestone] = checkpoint
        validation[milestone] = validation_report
    return {
        "dataset_manifest": files["dataset-manifest.json"],
        "source_closure": files["source-closure.json"],
        "training_config": files["training-config.json"],
        "checkpoints": checkpoints,
        "validation": validation,
    }


def _receipt(tmp_path: Path, *, model: str = "mlp", seed: int = 17) -> dict:
    paths = _write_fixture_files(tmp_path)
    return build_synthetic_receipt(
        run_id=f"{model}-seed{seed}",
        model=model,
        seed=seed,
        dataset_manifest=paths["dataset_manifest"],
        source_closure=paths["source_closure"],
        training_config=paths["training_config"],
        checkpoints=paths["checkpoints"],
        validation=paths["validation"],
        artifact_root=tmp_path,
    )


def test_protocol_defines_three_models_three_seeds_and_fixed_milestones() -> None:
    assert MODELS == ("mlp", "graph_raw", "graph_residual")
    assert SEEDS == (17, 29, 43)
    assert expected_run_ids() == (
        "mlp-seed17", "mlp-seed29", "mlp-seed43",
        "graph_raw-seed17", "graph_raw-seed29", "graph_raw-seed43",
        "graph_residual-seed17", "graph_residual-seed29", "graph_residual-seed43",
    )
    assert MILESTONES == (8000, 16000, 24000, 32000)


def test_valid_synthetic_receipt_is_read_only_and_nonqualifying(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path)
    before = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in tmp_path.iterdir()
    }
    report = verify_receipt(
        receipt,
        artifact_root=tmp_path,
        expected_run_id="mlp-seed17",
        expected_model="mlp",
        expected_seed=17,
        expected_dataset_manifest_sha256=receipt["bindings"]["dataset_manifest"]["sha256"],
        expected_source_closure_sha256=receipt["bindings"]["source_closure"]["sha256"],
        expected_training_config_sha256=receipt["bindings"]["training_config"]["sha256"],
    )
    assert report["valid"] is True
    assert report["status"] == "proposal_only"
    assert report["mode"] == "diagnostic_only"
    assert report["formal_credit"] == 0
    assert report["qualification_claim"] == "none"
    assert report["qualification_credit"] == 0
    assert report["launch_allowed"] is False
    assert report["run_id"] == "mlp-seed17"
    assert [row["milestone"] for row in report["artifacts"]["checkpoints"]] == list(MILESTONES)
    assert [row["milestone"] for row in report["artifacts"]["validation"]] == list(MILESTONES)
    after = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in tmp_path.iterdir()
    }
    assert after == before


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("formal_credit", 1),
        ("launch_allowed", True),
        ("diagnostic_only", False),
        ("proposal_only", False),
        ("qualification_claim", "formal qualification"),
        ("no_future_state", False),
        ("no_qualification", False),
        ("preprofile", True),
    ],
)
def test_permission_or_provenance_mutations_fail_closed(
    tmp_path: Path, field: str, value: object
) -> None:
    receipt = _receipt(tmp_path)
    receipt[field] = value
    with pytest.raises(ReceiptContractError):
        verify_receipt(receipt, artifact_root=tmp_path)


def test_future_state_and_qualification_guard_mutations_fail(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path)
    receipt["future_state_guards"]["future_observations"] = True
    with pytest.raises(ReceiptContractError):
        verify_receipt(receipt, artifact_root=tmp_path)

    receipt = _receipt(tmp_path)
    receipt["qualification_guards"]["counts_as_formal"] = True
    with pytest.raises(ReceiptContractError):
        verify_receipt(receipt, artifact_root=tmp_path)


@pytest.mark.parametrize(
    ("model", "seed", "run_id"),
    [
        ("not-a-model", 17, "not-a-model-seed17"),
        ("mlp", 999, "mlp-seed999"),
        ("graph_raw", 17, "mlp-seed17"),
        ("mlp", 17, "mlp-seed29"),
    ],
)
def test_wrong_model_seed_or_run_binding_is_rejected(
    tmp_path: Path, model: str, seed: int, run_id: str
) -> None:
    receipt = _receipt(tmp_path)
    receipt["model"] = model
    receipt["seed"] = seed
    receipt["run_id"] = run_id
    with pytest.raises(ReceiptContractError):
        verify_receipt(receipt, artifact_root=tmp_path)


def test_wrong_expected_identity_is_rejected(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path)
    with pytest.raises(ReceiptContractError):
        verify_receipt(receipt, artifact_root=tmp_path, expected_model="graph_raw")
    with pytest.raises(ReceiptContractError):
        verify_receipt(receipt, artifact_root=tmp_path, expected_seed=29)
    with pytest.raises(ReceiptContractError):
        verify_receipt(receipt, artifact_root=tmp_path, expected_run_id="mlp-seed29")


def test_duplicate_run_id_is_rejected_in_single_and_collection_validation(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path)
    with pytest.raises(ReceiptContractError, match="duplicate run_id"):
        verify_receipt(receipt, artifact_root=tmp_path, seen_run_ids=["mlp-seed17"])
    with pytest.raises(ReceiptContractError, match="duplicate run_id"):
        verify_receipt_set([receipt, deepcopy(receipt)], artifact_root=tmp_path)


def test_missing_or_duplicate_milestones_are_rejected(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path)
    receipt["update_milestones"] = [8000, 16000, 24000]
    with pytest.raises(ReceiptContractError, match="update_milestones"):
        verify_receipt(receipt, artifact_root=tmp_path)

    receipt = _receipt(tmp_path)
    receipt["artifacts"]["validation"] = receipt["artifacts"]["validation"][:-1]
    with pytest.raises(ReceiptContractError, match="artifacts.validation"):
        verify_receipt(receipt, artifact_root=tmp_path)

    receipt = _receipt(tmp_path)
    receipt["artifacts"]["checkpoints"][1]["milestone"] = 8000
    with pytest.raises(ReceiptContractError, match="duplicate milestone"):
        verify_receipt(receipt, artifact_root=tmp_path)


@pytest.mark.parametrize(
    "binding_path",
    [
        ("bindings", "dataset_manifest"),
        ("bindings", "source_closure"),
        ("bindings", "training_config"),
    ],
)
def test_manifest_source_and_training_hash_mismatch_is_rejected(
    tmp_path: Path, binding_path: tuple[str, str]
) -> None:
    receipt = _receipt(tmp_path)
    receipt[binding_path[0]][binding_path[1]]["sha256"] = "0" * 64
    with pytest.raises(ReceiptContractError, match="sha256"):
        verify_receipt(receipt, artifact_root=tmp_path)


def test_checkpoint_and_validation_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path)
    receipt["artifacts"]["checkpoints"][0]["sha256"] = "0" * 64
    with pytest.raises(ReceiptContractError, match="sha256"):
        verify_receipt(receipt, artifact_root=tmp_path)

    receipt = _receipt(tmp_path)
    receipt["artifacts"]["validation"][2]["sha256"] = "0" * 64
    with pytest.raises(ReceiptContractError, match="sha256"):
        verify_receipt(receipt, artifact_root=tmp_path)


def test_external_expected_hash_binding_is_enforced(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path)
    with pytest.raises(ReceiptContractError, match="expected binding"):
        verify_receipt(
            receipt,
            artifact_root=tmp_path,
            expected_dataset_manifest_sha256="1" * 64,
        )


def test_preprofile_or_diagnostic_provenance_cannot_be_relabelled_formal(
    tmp_path: Path,
) -> None:
    receipt = _receipt(tmp_path)
    receipt["provenance"]["kind"] = "preprofile"
    with pytest.raises(ReceiptContractError, match="preprofile/diagnostic"):
        verify_receipt(receipt, artifact_root=tmp_path)

    receipt = _receipt(tmp_path)
    receipt["run_type"] = "preprofile"
    with pytest.raises(ReceiptContractError):
        verify_receipt(receipt, artifact_root=tmp_path)

    receipt = _receipt(tmp_path)
    receipt["provenance"]["formal_execution"] = True
    with pytest.raises(ReceiptContractError):
        verify_receipt(receipt, artifact_root=tmp_path)


def test_nonexistent_or_relative_artifact_without_root_is_rejected(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path)
    receipt["bindings"]["dataset_manifest"]["path"] = "missing-manifest.json"
    with pytest.raises(ReceiptContractError, match="does not name"):
        verify_receipt(receipt, artifact_root=tmp_path)

    receipt = _receipt(tmp_path)
    with pytest.raises(ReceiptContractError, match="artifact_root"):
        verify_receipt(receipt)


def test_complete_three_by_three_matrix_passes_and_incomplete_matrix_fails(
    tmp_path: Path,
) -> None:
    receipts = []
    for index, (model, seed) in enumerate(
        ( (model, seed) for model in MODELS for seed in SEEDS )
    ):
        run_root = tmp_path / f"run-{index}"
        run_root.mkdir()
        paths = _write_fixture_files(run_root)
        receipts.append(
            build_synthetic_receipt(
                run_id=f"{model}-seed{seed}",
                model=model,
                seed=seed,
                dataset_manifest=paths["dataset_manifest"],
                source_closure=paths["source_closure"],
                training_config=paths["training_config"],
                checkpoints=paths["checkpoints"],
                validation=paths["validation"],
                artifact_root=tmp_path,
            )
        )
    result = verify_formal_run_matrix(receipts, artifact_root=tmp_path)
    assert result["valid"] is True
    assert result["matrix_complete"] is True
    assert result["receipt_count"] == 9
    assert result["formal_credit"] == 0
    assert result["launch_allowed"] is False

    with pytest.raises(ReceiptContractError, match="incomplete"):
        verify_formal_run_matrix(receipts[:-1], artifact_root=tmp_path)


def test_set_validation_can_check_a_partial_nonduplicated_proposal_set(tmp_path: Path) -> None:
    first = _receipt(tmp_path)
    second = deepcopy(first)
    second["run_id"] = "mlp-seed29"
    second["seed"] = 29
    result = verify_receipt_set([first, second], artifact_root=tmp_path)
    assert result["valid"] is True
    assert result["matrix_complete"] is False
    assert result["run_ids"] == ["mlp-seed17", "mlp-seed29"]


def test_file_hashes_in_the_fixture_are_actual_sha256_values(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path)
    path = tmp_path / receipt["bindings"]["dataset_manifest"]["path"]
    assert receipt["bindings"]["dataset_manifest"]["sha256"] == hashlib.sha256(
        path.read_bytes()
    ).hexdigest()
