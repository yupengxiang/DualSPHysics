"""Tests for the additive F3 MLP hidden16 current-manifest case matrix."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest

from scripts import f3_mlp_hidden16_current_manifest_case_matrix_v1 as matrix


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_sha(value: object) -> str:
    return _sha_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())


def _write_json(path: Path, value: object) -> dict[str, object]:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"path": str(path), "sha256": _sha_bytes(raw), "bytes": len(raw)}


def _manifest_payload() -> dict[str, object]:
    cases = []
    for index in range(matrix.EXPECTED_CASE_COUNT):
        split = "test" if index < 6 or index >= 26 else ("validation" if index in {8, 13, 18, 23} else "train")
        case_id = f"F3_DEV_{index:02d}_a{903125 + index * 6250 // 1000}p{(index * 625) % 1000:03d}"
        case_digest = hashlib.sha256(f"case-{index}".encode()).hexdigest()
        cases.append({
            "bytes": 900000000 + index,
            "case_id": case_id,
            "evaluation_role": "development_extrapolation" if split == "test" else ("development_interpolation" if split == "validation" else "training"),
            "family": "F3",
            "hdf5": f"campaigns/core-v1/data/{case_id}.h5",
            "known_inputs_sha256": hashlib.sha256(f"inputs-{index}".encode()).hexdigest(),
            "lineage_group_id": hashlib.sha256(f"lineage-{index}".encode()).hexdigest(),
            "physical_case_id": case_id,
            "qualification_case": False,
            "scope_id": "F3_CELL3_NS_visco1_native_nopen_revision075_ref0081818",
            "semantics": {"units": "SI"},
            "sha256": case_digest,
            "split": split,
        })
    return {
        "case_count": matrix.EXPECTED_CASE_COUNT,
        "cases": cases,
        "dataset_id": "F3_registered32_core_native_v2",
        "formal_release": False,
        "input_asset_policy": "content_addressed_compressed_npz",
        "schema": "core.dataset.v2",
        "source_manifest_sha256": "f" * 64,
        "source_qualification_claims": {"learning": "negative_baseline_only"},
    }


def _training_payload(manifest_path: Path, manifest_sha: str, manifest_raw: dict[str, object]) -> dict[str, object]:
    runs = []
    for seed in matrix.SEEDS:
        run_id = f"f3-mlp500-hidden16-currentmanifest-seed{seed}-20260929"
        receipt_path = Path(f"/tmp/training-seed{seed}.json")
        checkpoint_path = Path(f"/tmp/checkpoint-seed{seed}.pt")
        receipt_sha = hashlib.sha256(f"receipt-{seed}".encode()).hexdigest()
        checkpoint_sha = hashlib.sha256(f"checkpoint-{seed}".encode()).hexdigest()
        checkpoint = {
            "bytes": 64000 + seed,
            "path": str(checkpoint_path),
            "schema": "core.checkpoint.v1",
            "sha256": checkpoint_sha,
            "update": matrix.UPDATES,
        }
        runs.append({
            "seed": seed,
            "status": "bound",
            "source": {
                "bytes": 10000 + seed,
                "opened": True,
                "path": str(receipt_path),
                "schema": "core.training.v1",
                "sha256": receipt_sha,
            },
            "evidence": {
                "checkpoint_identity": checkpoint,
                "completed": True,
                "hidden": matrix.HIDDEN,
                "manifest_sha256": manifest_sha,
                "model": matrix.MODEL,
                "receipt_identity": {
                    "bytes": 10000 + seed,
                    "path": str(receipt_path),
                    "sha256": receipt_sha,
                },
                "run_id": run_id,
                "schema": "core.training.v1",
                "seed": seed,
                "updates": matrix.UPDATES,
                "zero_credit": dict(matrix.ZERO_CREDIT),
            },
        })
    return {
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "authorization": dict(matrix.ZERO_CREDIT),
        "credit": 0,
        "diagnostic_only": True,
        "errors": [],
        "fail_closed": False,
        "formal": False,
        "formal_eligible": False,
        "formal_training_runs_counted": 0,
        "hidden": matrix.HIDDEN,
        "input_boundary": {
            "checkpoint_content_opened": False,
            "gpu_started": False,
            "hdf5_content_opened": False,
            "manifest_content_opened": True,
            "solver_started": False,
        },
        "manifest": {
            "bytes": manifest_raw["bytes"],
            "canonical_sha256": manifest_sha,
            "opened": True,
            "path": str(manifest_path),
            "schema": "core.dataset.v2",
            "sha256": manifest_raw["sha256"],
        },
        "model": matrix.MODEL,
        "qualification": False,
        "qualification_credit": 0,
        "report_id": "f3-mlp-hidden16-current-manifest-training-evidence-v1",
        "runs": runs,
        "schema": matrix.TRAINING_SCHEMA,
        "side_effects": {
            "checkpoint_opened": False,
            "denominator_mutation": 0,
            "gate_mutation": 0,
            "hdf5_opened": False,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "runtime_started": False,
        },
        "source_bound": True,
        "status": "diagnostic_bound",
        "t1_case_runs_counted": 0,
        "t2_macro_families_counted": 0,
        "updates": matrix.UPDATES,
    }


def _fixture(tmp_path: Path) -> dict[str, object]:
    root = tmp_path / "lab"
    manifest = root / "campaigns" / "core-v1" / "f3-dataset-v2.json"
    payload = _manifest_payload()
    manifest_raw = _write_json(manifest, payload)
    manifest_sha = _canonical_sha(payload)
    identity = {
        "schema": matrix.MANIFEST_IDENTITY_SCHEMA,
        "status": "bound",
        "source_bound": True,
        **matrix.ZERO_CREDIT,
        "manifest": {
            "raw": manifest_raw,
            "canonical": {"sha256": manifest_sha},
        },
    }
    identity_path = root / "reports" / "manifest-identity.json"
    _write_json(identity_path, identity)
    training_path = root / "reports" / "training-evidence.json"
    training_payload = _training_payload(manifest, manifest_sha, manifest_raw)
    _write_json(training_path, training_payload)
    return {
        "root": root,
        "manifest": manifest,
        "manifest_identity": identity_path,
        "training": training_path,
        "manifest_sha": manifest_sha,
    }


def _build(fixture: dict[str, object]) -> dict[str, object]:
    return matrix.build_report(
        root=fixture["root"],
        manifest=fixture["manifest"],
        manifest_identity=fixture["manifest_identity"],
        training_evidence=fixture["training"],
        plan_date="20260929",
        python_executable=Path("/tmp/fake-python"),
    )


def test_build_report_covers_exact_32_case_by_3_seed_matrix(tmp_path: Path) -> None:
    report = _build(_fixture(tmp_path))

    assert report["status"] == "dry_run_matrix_ready"
    assert report["coverage"]["exact_case_seed_coverage"] is True
    assert report["coverage"]["jobs"] == 96
    assert report["coverage"]["unique_namespaces"] == 96
    assert report["coverage"]["unique_nonces"] == 96
    assert report["coverage"]["unique_command_identities"] == 96
    assert len(report["cases"]) == 32
    assert len(report["plans"]) == 96
    assert {(plan["case_id"], plan["seed"]) for plan in report["plans"]} == {
        (case["case_id"], seed) for case in report["cases"] for seed in matrix.SEEDS
    }
    assert all(plan["launch_allowed"] is False for plan in report["plans"])
    assert all(plan["credit"] == 0 and plan["diagnostic_only"] for plan in report["plans"])
    assert report["terminal_receipts"]["missing_count"] == 96
    matrix.validate_report(report)


def test_training_authorization_may_omit_redundant_diagnostic_flag(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    payload = json.loads(Path(fixture["training"]).read_text(encoding="utf-8"))
    payload["authorization"].pop("diagnostic_only")
    _write_json(Path(fixture["training"]), payload)
    report = _build(fixture)
    assert report["training_identity"]["source_bound"] is True


def test_plan_commands_bind_case_split_outputs_and_gpu_slot(tmp_path: Path) -> None:
    report = _build(_fixture(tmp_path))
    first = report["plans"][0]
    assert first["command"][first["command"].index("--case-id") + 1] == first["case_id"]
    assert first["command"][first["command"].index("--split") + 1] == first["split"]
    assert first["command"][first["command"].index("--maximum-steps") + 1] == "835"
    assert "--diagnostic" in first["command"]
    assert first["env_overrides"]["CUDA_VISIBLE_DEVICES"] == "0"
    assert first["namespace_freshness_attested"] is False
    assert first["namespace_reuse_allowed"] is False
    assert first["outputs"]["evaluation"].startswith(first["output_namespace"] + "/")
    assert first["outputs"]["process_proof"].startswith(str(report["root"]) + "/reports/")


def test_cli_writes_json_markdown_and_verify_is_read_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fixture = _fixture(tmp_path)
    output = fixture["root"] / "reports" / "case-matrix.json"
    markdown = fixture["root"] / "reports" / "case-matrix.zh-CN.md"
    result = matrix.main([
        "--root", str(fixture["root"]),
        "--manifest", str(fixture["manifest"]),
        "--manifest-identity", str(fixture["manifest_identity"]),
        "--training-evidence", str(fixture["training"]),
        "--python-executable", "/tmp/fake-python",
        "--output", str(output),
        "--markdown-output", str(markdown),
    ])
    assert result == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["jobs"] == 96
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "dry_run_matrix_ready"
    assert "32-case" in markdown.read_text(encoding="utf-8")
    before = output.read_bytes()
    result = matrix.main(["--verify-report", str(output)])
    assert result == 0
    assert output.read_bytes() == before


def test_manifest_case_count_drift_fails_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    payload = json.loads(Path(fixture["manifest"]).read_text(encoding="utf-8"))
    payload["cases"] = payload["cases"][:-1]
    payload["case_count"] = 31
    manifest_raw = _write_json(Path(fixture["manifest"]), payload)
    identity = json.loads(Path(fixture["manifest_identity"]).read_text(encoding="utf-8"))
    identity["manifest"]["raw"] = manifest_raw
    identity["manifest"]["canonical"] = {"sha256": _canonical_sha(payload)}
    _write_json(Path(fixture["manifest_identity"]), identity)
    with pytest.raises(matrix.MatrixError, match="32"):
        _build(fixture)


def test_training_manifest_drift_and_nonzero_credit_fail_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    payload = json.loads(Path(fixture["training"]).read_text(encoding="utf-8"))
    payload["manifest"]["canonical_sha256"] = "a" * 64
    _write_json(Path(fixture["training"]), payload)
    with pytest.raises(matrix.MatrixError, match="canonical_sha256"):
        _build(fixture)

    fixture = _fixture(tmp_path / "credit")
    payload = json.loads(Path(fixture["training"]).read_text(encoding="utf-8"))
    payload["credit"] = 1
    _write_json(Path(fixture["training"]), payload)
    with pytest.raises(matrix.MatrixError, match="credit"):
        _build(fixture)


def test_production_artifact_paths_are_metadata_only(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    report = _build(fixture)
    assert report["input_boundary"]["hdf5_content_opened"] is False
    assert report["input_boundary"]["hdf5_lstat_performed"] is False
    assert report["input_boundary"]["checkpoint_content_opened"] is False
    assert report["input_boundary"]["checkpoint_lstat_performed"] is False
    assert not any((tmp_path / "lab").rglob("*.h5"))
    assert not any((tmp_path / "lab").rglob("*.pt"))
