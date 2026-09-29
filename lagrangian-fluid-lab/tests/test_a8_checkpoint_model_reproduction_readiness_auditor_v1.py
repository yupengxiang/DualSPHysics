import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts import a8_checkpoint_model_reproduction_readiness_auditor_v1 as auditor


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact(
    path: Path, *, relative: str, sha256: str | None = None
) -> dict:
    return {
        "path": relative,
        "bytes": path.stat().st_size,
        "sha256": sha256 or _sha(path),
    }


def _fixture(tmp_path: Path) -> dict[str, Path]:
    lab_root = tmp_path / "lab"
    current_root = lab_root / "current"
    historical_root = lab_root / "historical"
    for root in (current_root, historical_root):
        (root / "code/scripts").mkdir(parents=True)
        (root / "code/scripts/core.py").write_text("current\n" if root == current_root else "historical\n")
        (root / "environment.json").write_text("{}\n")
        (root / "README.md").write_text("fixture\n")
        _write_json(
            root / "dataset.json",
            {
                "schema": "core.dataset.v2",
                "cases": [
                    {
                        "case_id": (
                            "current-fixture"
                            if root == current_root
                            else "historical-fixture"
                        )
                    }
                ],
            },
        )

    current_rows = [
        _artifact(current_root / "dataset.json", relative="dataset.json"),
        _artifact(
            current_root / "code/scripts/core.py",
            relative="code/scripts/core.py",
            sha256="1" * 64,
        ),
        _artifact(current_root / "environment.json", relative="environment.json"),
        _artifact(current_root / "README.md", relative="README.md"),
    ]
    current_bundle = _write_json(
        current_root / "bundle.json",
        {
            "schema": "core.reader_bundle.v2",
            "case_count": 1,
            "checkpoint_count": 0,
            "entrypoint": "python code/scripts/core.py",
            "model_entrypoint": (
                "python code/scripts/core.py --checkpoint "
                "models/checkpoint-000.pt"
            ),
            "model_reproduction_supported": False,
            "full_core_release": False,
            "physical_storage": "independent copies",
            "files": current_rows,
        },
    )

    checkpoint = historical_root / "models/checkpoint-000.pt"
    checkpoint.parent.mkdir()
    checkpoint.write_bytes(b"checkpoint bytes must not be opened")
    registry = _write_json(
        historical_root / "checkpoints.json",
        {
            "schema": "core.bundled_checkpoints.v1",
            "formal_training_qualification": "not_inferred_from_packaging",
            "checkpoints": [
                {
                    "model_kind": "mlp",
                    "path": "models/checkpoint-000.pt",
                    "seed": 17,
                    "update": 16,
                    "sha256": "2" * 64,
                }
            ],
        },
    )
    historical_rows = [
        _artifact(
            historical_root / "dataset.json", relative="dataset.json"
        ),
        _artifact(
            historical_root / "code/scripts/core.py",
            relative="code/scripts/core.py",
            sha256="3" * 64,
        ),
        _artifact(
            historical_root / "environment.json", relative="environment.json"
        ),
        _artifact(historical_root / "README.md", relative="README.md"),
        {
            "path": "models/checkpoint-000.pt",
            "bytes": checkpoint.stat().st_size,
            "sha256": "2" * 64,
        },
        _artifact(registry, relative="checkpoints.json"),
    ]
    historical_bundle = _write_json(
        historical_root / "bundle.json",
        {
            "schema": "core.reader_bundle.v1",
            "case_count": 1,
            "checkpoint_count": 1,
            "entrypoint": "python code/scripts/core.py",
            "model_entrypoint": (
                "python code/scripts/core.py --checkpoint "
                "models/checkpoint-000.pt"
            ),
            "model_reproduction_supported": True,
            "full_core_release": False,
            "physical_storage": "independent copies",
            "files": historical_rows,
        },
    )
    return {
        "lab_root": lab_root,
        "current_bundle": current_bundle,
        "historical_bundle": historical_bundle,
        "historical_registry": registry,
    }


def _build(fixture: dict[str, Path]) -> dict:
    return auditor.build_audit(
        lab_root=fixture["lab_root"],
        current_bundle=fixture["current_bundle"],
        historical_bundle=fixture["historical_bundle"],
        historical_registry=fixture["historical_registry"],
        historical_provenance=None,
    )


def test_current_v2_checkpoint_free_bundle_stays_blocked(tmp_path):
    fixture = _fixture(tmp_path)
    report = _build(fixture)

    assert report["status"] == "blocked_missing_trusted_checkpoint_binding"
    assert report["passed"] is False
    assert report["current_bundle"]["schema"] == auditor.CURRENT_BUNDLE_SCHEMA
    assert report["current_bundle"]["checkpoint_count"] == 0
    assert report["historical_bundle"]["checkpoint_count"] == 1
    assert report["historical_checkpoint_registry"]["declared_count"] == 1
    assert report["comparisons"]["model_identity"]["current_identity_bound"] is False
    assert report["claims"] == auditor.FALSE_CLAIMS
    assert report["mutations"] == auditor.ZERO_MUTATIONS
    assert report["read_boundary"]["json_inputs_opened"] == 5
    assert "current_trusted_checkpoint_binding_missing" in report["blockers"]
    assert "dataset_source_raw_sha_mismatch_current_vs_historical" in report["blockers"]
    assert auditor.validate_report(report) == []


def test_invalid_checkpoint_payload_is_not_opened(tmp_path):
    fixture = _fixture(tmp_path)
    checkpoint = fixture["historical_bundle"].parent / "models/checkpoint-000.pt"
    checkpoint.write_bytes(b"not a valid torch file and never read")

    report = _build(fixture)
    record = report["historical_checkpoint_registry"]["identities"][0]["lstat"]

    assert record["exists"] is True
    assert record["lstat_only"] is True
    assert record["content_opened"] is False
    assert record["content_hash_verified"] is False
    assert report["read_boundary"]["checkpoint_opened"] is False
    assert report["read_boundary"]["non_json_files_opened"] is False


def test_symlinked_checkpoint_is_fail_closed(tmp_path):
    fixture = _fixture(tmp_path)
    root = fixture["historical_bundle"].parent
    checkpoint = root / "models/checkpoint-000.pt"
    target = root / "models/target.pt"
    target.write_bytes(b"target")
    checkpoint.unlink()
    checkpoint.symlink_to(target.name)

    report = _build(fixture)

    assert any("symlink_forbidden" in item for item in report["blockers"])
    assert report["claims"]["credit"] == 0
    assert report["trusted_checkpoint_binding"]["ready"] is False


def test_validate_report_rejects_claim_drift(tmp_path):
    report = _build(_fixture(tmp_path))
    mutated = copy.deepcopy(report)
    mutated["claims"]["credit"] = 1

    errors = auditor.validate_report(mutated)

    assert "report.claims drift" in errors


def test_metadata_claims_cannot_close_current_checkpoint_binding(tmp_path):
    fixture = _fixture(tmp_path)
    current_payload = json.loads(fixture["current_bundle"].read_text())
    current_payload["checkpoint_count"] = 1
    current_payload["model_reproduction_supported"] = True
    _write_json(fixture["current_bundle"], current_payload)

    report = _build(fixture)

    assert report["passed"] is False
    assert report["claims"] == auditor.FALSE_CLAIMS
    assert report["trusted_checkpoint_binding"]["ready"] is False
    assert "current_trusted_checkpoint_binding_missing" in report["blockers"]
    assert "current_bundle.checkpoint_count is not zero" in auditor.validate_report(report)


def test_provenance_checkpoint_path_must_match_registry_and_bundle_identity(tmp_path):
    fixture = _fixture(tmp_path)
    historical_root = fixture["historical_bundle"].parent
    dataset = historical_root / "dataset.json"
    provenance = _write_json(
        tmp_path / "provenance.json",
        {
            "schema": auditor.CHECKPOINT_PROVENANCE_SCHEMA,
            "bundle": {
                "bundle_json_sha256": _sha(fixture["historical_bundle"]),
                "checkpoint_registry_sha256": _sha(fixture["historical_registry"]),
                "dataset_json_sha256": _sha(dataset),
            },
            "checkpoint": {
                "bundle_path": "models/forged-checkpoint.pt",
                "bytes": 7,
                "path": "models/checkpoint-000.pt",
                "sha256": "2" * 64,
            },
            "dataset_binding": {
                "canonical_sha256": "4" * 64,
                "dataset_id": "synthetic-fixture",
                "path": "dataset.json",
                "sha256": _sha(dataset),
            },
            "diagnostic_only": True,
            "formal_training_count": 0,
            "model_kind": "mlp",
            "qualification_note": "synthetic diagnostic only",
            "schema_version_note": "not an authority",
            "seed": 17,
            "training": {
                "completed_updates": 16,
                "initialization_evidence": {"hidden": 64},
                "run_id": "synthetic-fixture",
            },
            "update": 16,
        },
    )

    report = auditor.build_audit(
        lab_root=fixture["lab_root"],
        current_bundle=fixture["current_bundle"],
        historical_bundle=fixture["historical_bundle"],
        historical_registry=fixture["historical_registry"],
        historical_provenance=provenance,
    )

    assert "historical_checkpoint_provenance_bundle_checkpoint_path_mismatch" in report[
        "blockers"
    ]
    assert "historical_checkpoint_provenance_checkpoint_source_path_not_authoritative" in report[
        "blockers"
    ]
    assert report["comparisons"]["model_identity"]["current_identity_bound"] is False
    assert auditor.validate_report(report) == []


def test_report_validator_rejects_forged_lineage_receipts(tmp_path):
    report = _build(_fixture(tmp_path))
    mutated = copy.deepcopy(report)
    mutated["lineage_boundary"]["reader"]["receipt_supplied_to_this_boundary"] = True

    errors = auditor.validate_report(mutated)

    assert "lineage_boundary.reader receipt must be absent" in errors


def test_cli_writes_and_validates_diagnostic_outputs(tmp_path):
    fixture = _fixture(tmp_path)
    report_path = tmp_path / "audit.json"
    zh_path = tmp_path / "audit.zh-CN.md"
    provenance = _write_json(tmp_path / "provenance.json", {})

    assert auditor.main(
        [
            "audit",
            "--lab-root",
            str(fixture["lab_root"]),
            "--current-bundle",
            str(fixture["current_bundle"]),
            "--historical-bundle",
            str(fixture["historical_bundle"]),
            "--historical-registry",
            str(fixture["historical_registry"]),
            "--historical-provenance",
            str(provenance),
            "--report",
            str(report_path),
            "--zh-report",
            str(zh_path),
        ]
    ) == 0
    assert report_path.is_file()
    assert zh_path.is_file()
    assert json.loads(report_path.read_text())["read_boundary"]["json_inputs_opened"] == 6
    assert auditor.main(
        [
            "validate",
            "--lab-root",
            str(fixture["lab_root"]),
            "--report",
            str(report_path),
        ]
    ) == 0


def test_non_json_artifacts_are_not_accepted_as_json_inputs(tmp_path):
    fixture = _fixture(tmp_path)
    with pytest.raises(auditor.AuditContractError, match="JSON input"):
        auditor._json_ref(
            fixture["historical_bundle"].parent / "models/checkpoint-000.pt",
            lab_root=fixture["lab_root"],
            label="checkpoint",
        )
