"""Tests for the bounded graph_raw hidden16 current-manifest case matrix."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts import f3_graph_raw_hidden16_current_manifest_case_matrix_v1 as matrix


def _digest(seed: int, label: str) -> str:
    return hashlib.sha256(f"{label}-{seed}".encode()).hexdigest()


def _write_json(path: Path, payload: object) -> dict[str, object]:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _manifest_payload() -> dict[str, object]:
    cases = []
    for index in range(matrix.EXPECTED_CASE_COUNT):
        split = "test" if index < 6 or index >= 26 else ("validation" if index in {8, 13, 18, 23} else "train")
        case_id = f"F3_DEV_{index:02d}_a{903125 + index * 6250 // 1000}p{(index * 625) % 1000:03d}"
        cases.append(
            {
                "bytes": 899000000 + index,
                "case_id": case_id,
                "evaluation_role": "development_extrapolation" if split == "test" else ("development_interpolation" if split == "validation" else "training"),
                "family": "F3",
                "hdf5": f"campaigns/l1-resume/data/continuation/{case_id}.h5",
                "known_inputs_sha256": _digest(index, "inputs"),
                "lineage_group_id": _digest(index, "lineage"),
                "physical_case_id": case_id,
                "qualification_case": False,
                "scope_id": "F3_CELL3_NS_visco1_native_nopen_revision075_ref0081818",
                "sha256": _digest(index, "hdf5"),
                "split": split,
            }
        )
    return {
        "case_count": matrix.EXPECTED_CASE_COUNT,
        "cases": cases,
        "dataset_id": "F3_registered32_core_native_v2",
        "formal_release": False,
        "input_asset_policy": "content_addressed_compressed_npz",
        "schema": "core.dataset.v2",
        "source_manifest_sha256": _digest(0, "source-manifest"),
    }


def _training_payload(manifest_sha256: str) -> dict[str, object]:
    runs = []
    for seed in matrix.SEEDS:
        receipt_path = f"/tmp/f3-graph-raw500-hidden16-seed{seed}-20260928-training.json"
        checkpoint_path = f"/tmp/f3-graph-raw500-hidden16-seed{seed}-20260928-checkpoint.pt"
        shared_config = copy.deepcopy(matrix.STATIC_CONFIG)
        runs.append(
            {
                "seed": seed,
                "status": "bound_complete",
                "source": {
                    "bytes": 10600 + seed,
                    "exists": True,
                    "opened": True,
                    "path": receipt_path,
                    "schema": "core.training.v1",
                    "sha256": _digest(seed, "receipt"),
                },
                "evidence": {
                    "checkpoint": {
                        "path": checkpoint_path,
                        "schema": "core.checkpoint.v1",
                        "sha256": _digest(seed, "checkpoint"),
                        "update": matrix.UPDATES,
                    },
                    "evidence_status": "complete",
                    "formal_eligible": False,
                    "hidden": matrix.HIDDEN,
                    "initialization": {
                        "parameter_count": 6086,
                        "parameter_digest": _digest(seed, "initialization"),
                        "schema": "core.training.initialization_evidence.v1",
                        "status": "captured",
                    },
                    "manifest_sha256": manifest_sha256,
                    "model_kind": matrix.MODEL_KIND,
                    "normalization": {
                        "requested_maximum_transitions": 16,
                        "schema": "core.training.normalization_evidence.v1",
                        "selected_transition_count": 16,
                        "selection_policy": matrix.STATIC_CONFIG["normalization_selection_policy"],
                        "selection_seed": seed,
                        "source_split": "train",
                        "target_reference": matrix.STATIC_CONFIG["normalization_target_reference"],
                    },
                    "parameter_count": 6086,
                    "qualification_credit": 0,
                    "run_id": f"graph_raw-hidden16-seed{seed}",
                    "schema": "core.training.v1",
                    "seed": seed,
                    "shared_config": shared_config,
                    "updates": matrix.UPDATES,
                },
            }
        )
    return {
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "authorization": {"credit": 0, "formal": False, "formal_eligible": False, "qualification": False, "qualification_credit": 0},
        "credit": 0,
        "diagnostic_only": True,
        "errors": [],
        "expected_contract": {
            "evidence_status": "complete",
            "hidden": matrix.HIDDEN,
            "model_kind": matrix.MODEL_KIND,
            "seeds": list(matrix.SEEDS),
            "shared_config": copy.deepcopy(matrix.STATIC_CONFIG),
            "updates": matrix.UPDATES,
        },
        "fail_closed": False,
        "formal": False,
        "formal_eligible": False,
        "formal_training_runs_counted": 0,
        "model": matrix.MODEL_KIND,
        "qualification": False,
        "qualification_credit": 0,
        "report_id": matrix.TRAINING_REPORT_ID,
        "runs": runs,
        "schema": matrix.TRAINING_SCHEMA,
        "shared_config": copy.deepcopy(matrix.STATIC_CONFIG),
        "source_bound": True,
        "status": "training_evidence_bound_diagnostic_only",
        "t1_case_runs_counted": 0,
        "t2_macro_families_counted": 0,
        "training_evidence_counted_as_formal_runs": 0,
    }


def _explicit_receipt(seed: int, manifest_sha256: str) -> dict[str, object]:
    run_id = f"f3-graph_raw500-hidden16-currentmanifest-seed{seed}-20260929-v3"
    config = copy.deepcopy(matrix.STATIC_CONFIG)
    config.update(
        {
            "manifest_sha256": manifest_sha256,
            "paired_seed": seed,
            "run_id": run_id,
            "sampler_seed": seed,
            "seed": seed,
        }
    )
    return {
        "schema": "core.training.v1",
        "evidence_status": "complete",
        "model_kind": matrix.MODEL_KIND,
        "seed": seed,
        "run_id": run_id,
        "completed_updates": matrix.UPDATES,
        "parameter_count": 6086,
        "checkpoint_verified": True,
        "config": config,
        "checkpoint": {
            "schema": "core.checkpoint.v1",
            "path": f"/tmp/f3-graph_raw500-hidden16-currentmanifest-seed{seed}-20260929-v3-checkpoint.pt",
            "sha256": _digest(seed, "explicit-checkpoint"),
            "update": matrix.UPDATES,
        },
        "evidence": {
            "schema": "core.training.evidence.v1",
            "status": "complete",
            "initialization": {
                "schema": "core.training.initialization_evidence.v1",
                "status": "captured",
                "parameter_count": 6086,
                "parameter_digest": _digest(seed, "explicit-initialization"),
            },
            "normalization": {
                "schema": "core.training.normalization_evidence.v1",
                "requested_maximum_transitions": 16,
                "selected_transition_count": 16,
                "selection_policy": matrix.STATIC_CONFIG["normalization_selection_policy"],
                "selection_seed": seed,
                "source_split": "train",
                "target_reference": matrix.STATIC_CONFIG["normalization_target_reference"],
            },
        },
    }


def _fixture(tmp_path: Path) -> dict[str, object]:
    root = tmp_path / "lab"
    manifest = root / "campaigns" / "core-v1" / "f3-dataset-v2.json"
    manifest_payload = _manifest_payload()
    manifest_source = _write_json(manifest, manifest_payload)
    manifest_sha256 = matrix._canonical_sha(manifest_payload)
    training = root / "reports" / "F3-GRAPH-RAW-HIDDEN16-TRAINING-EVIDENCE-MATRIX.json"
    _write_json(training, _training_payload(manifest_sha256))
    return {"root": root, "manifest": manifest, "training": training, "manifest_source": manifest_source, "manifest_sha256": manifest_sha256}


def _build(fixture: dict[str, object]) -> dict[str, object]:
    return matrix.build_report(
        root=fixture["root"],
        manifest=fixture["manifest"],
        training_evidence=fixture["training"],
        plan_date="20260929",
        python_executable=Path("/tmp/fake-python"),
    )


def test_build_report_covers_exact_32_cases_by_three_graph_raw_seeds(tmp_path: Path) -> None:
    report = _build(_fixture(tmp_path))

    assert report["status"] == "dry_run_matrix_ready"
    assert report["source_bound"] is True
    assert report["launch_allowed"] is False
    assert report["manifest"]["canonical_sha256"] == report["training_identity"]["manifest_sha256"]
    assert report["coverage"]["jobs"] == 96
    assert report["coverage"]["unique_namespaces"] == 96
    assert report["coverage"]["unique_nonces"] == 96
    assert report["coverage"]["unique_command_identities"] == 96
    assert len(report["cases"]) == 32
    assert len(report["plans"]) == 96
    assert {(plan["case_id"], plan["seed"]) for plan in report["plans"]} == {
        (case["case_id"], seed) for case in report["cases"] for seed in matrix.SEEDS
    }
    assert all(plan["model_kind"] == "graph_raw" and plan["hidden"] == 16 for plan in report["plans"])
    assert all(plan["launch_allowed"] is False and plan["credit"] == 0 for plan in report["plans"])
    assert report["terminal_receipts"]["status"] == "missing_real_terminal_receipts_fail_closed"
    assert report["terminal_receipts"]["missing_count"] == 96
    matrix.validate_report(report)


def test_plan_commands_bind_graph_raw_case_seed_checkpoint_and_split(tmp_path: Path) -> None:
    report = _build(_fixture(tmp_path))
    first = report["plans"][0]
    command = first["command"]
    assert "evaluate" in command
    assert command[command.index("--case-id") + 1] == first["case_id"]
    assert command[command.index("--split") + 1] == first["split"]
    assert command[command.index("--checkpoint") + 1] == first["checkpoint"]["path"]
    assert command[command.index("--maximum-steps") + 1] == str(matrix.TRANSITIONS)
    assert "--diagnostic" in command
    assert first["env_overrides"]["CUDA_VISIBLE_DEVICES"] == "0"
    assert first["namespace_freshness_attested"] is False
    assert first["namespace_reuse_allowed"] is False
    assert first["outputs"]["evaluation"].startswith(first["output_namespace"] + "/")
    assert first["outputs"]["process_proof"].startswith(str(report["root"]) + "/reports/")


def test_missing_terminal_receipts_keep_every_plan_fail_closed(tmp_path: Path) -> None:
    report = _build(_fixture(tmp_path))
    assert report["terminal_receipts"]["observed_count"] == 0
    assert report["terminal_receipts"]["launch_allowed"] is False
    assert all(plan["terminal_receipt_observed"] is False for plan in report["plans"])
    assert all(plan["launch_allowed"] is False for plan in report["plans"])
    assert report["credit"] == 0
    assert report["blocked_reasons"]


def test_manifest_drift_from_training_identity_fails_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    payload = json.loads(Path(fixture["manifest"]).read_text(encoding="utf-8"))
    payload["source_manifest_sha256"] = _digest(999, "different-source")
    _write_json(Path(fixture["manifest"]), payload)
    with pytest.raises(matrix.MatrixError, match="manifest_sha256"):
        _build(fixture)


def test_training_seed_coverage_drift_fails_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    payload = json.loads(Path(fixture["training"]).read_text(encoding="utf-8"))
    payload["runs"] = payload["runs"][:2]
    _write_json(Path(fixture["training"]), payload)
    with pytest.raises(matrix.MatrixError, match="exactly three runs"):
        _build(fixture)


def test_checkpoint_content_is_not_required_or_opened(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    report = _build(fixture)
    assert report["input_boundary"]["checkpoint_content_opened"] is False
    assert report["input_boundary"]["checkpoint_lstat_performed"] is False
    assert all(plan["checkpoint"]["path"].startswith("/tmp/") for plan in report["plans"])


def test_explicit_nonterminal_status_fails_before_receipt_reads(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    missing_paths = {seed: tmp_path / f"missing-seed{seed}.json" for seed in matrix.SEEDS}
    statuses = {seed: "running" for seed in matrix.SEEDS}
    with pytest.raises(matrix.MatrixError, match="non-terminal"):
        matrix.build_report(
            root=fixture["root"],
            manifest=fixture["manifest"],
            training_evidence=fixture["training"],
            plan_date="20260929",
            python_executable=Path("/tmp/fake-python"),
            seed_receipts=missing_paths,
            seed_statuses=statuses,
        )


def test_explicit_terminal_v3_receipts_are_bounded_and_bound(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    receipts: dict[int, Path] = {}
    statuses = {seed: "completed" for seed in matrix.SEEDS}
    for seed in matrix.SEEDS:
        path = Path(fixture["root"]) / "reports" / f"explicit-seed{seed}.json"
        _write_json(path, _explicit_receipt(seed, fixture["manifest_sha256"]))
        receipts[seed] = path
    report = matrix.build_report(
        root=fixture["root"],
        manifest=fixture["manifest"],
        training_evidence=fixture["training"],
        plan_date="20260929",
        python_executable=Path("/tmp/fake-python"),
        seed_receipts=receipts,
        seed_statuses=statuses,
    )
    assert report["training_binding"]["mode"] == "explicit_seed_receipts"
    assert report["input_boundary"]["bounded_explicit_training_receipts_json_opened"] is True
    assert {run["run_id"] for run in report["training_identity"]["runs"]} == {
        f"f3-graph_raw500-hidden16-currentmanifest-seed{seed}-20260929-v3" for seed in matrix.SEEDS
    }
    assert report["launch_allowed"] is False
    assert report["credit"] == 0
    matrix.validate_report(report)


def test_tampered_namespace_or_command_identity_is_rejected(tmp_path: Path) -> None:
    report = _build(_fixture(tmp_path))
    tampered = copy.deepcopy(report)
    tampered["plans"][0]["command"][0] = "/tmp/other-python"
    with pytest.raises(matrix.MatrixError, match="command_sha256"):
        matrix.validate_report(tampered)

    tampered = copy.deepcopy(report)
    tampered["plans"][1]["namespace_nonce"] = tampered["plans"][0]["namespace_nonce"]
    with pytest.raises(matrix.MatrixError, match="output_namespace"):
        matrix.validate_report(tampered)


def test_duplicate_json_keys_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema":"x","schema":"y"}\n', encoding="utf-8")
    with pytest.raises(matrix.MatrixError, match="duplicate JSON key"):
        matrix._read_bounded_json(path, name="duplicate", max_bytes=1024)


def test_cli_writes_and_verifies_graph_raw_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fixture = _fixture(tmp_path)
    output = Path(fixture["root"]) / "reports" / "graph-raw-case-matrix.json"
    markdown = Path(fixture["root"]) / "reports" / "graph-raw-case-matrix.zh-CN.md"
    result = matrix.main(
        [
            "--root", str(fixture["root"]),
            "--manifest", str(fixture["manifest"]),
            "--training-evidence", str(fixture["training"]),
            "--python-executable", "/tmp/fake-python",
            "--output", str(output),
            "--markdown-output", str(markdown),
        ]
    )
    assert result == 0
    assert output.is_file() and markdown.is_file()
    capsys.readouterr()
    assert matrix.main(["--verify-report", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["launch_allowed"] is False
