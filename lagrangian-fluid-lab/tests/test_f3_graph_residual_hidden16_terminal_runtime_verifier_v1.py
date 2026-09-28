"""Synthetic bounded-envelope tests for the additive runtime verifier."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import stat

import pytest

from scripts import f3_graph_residual_hidden16_terminal_completion_receipt_matrix_v1 as terminal_matrix
from scripts import f3_graph_residual_hidden16_terminal_runtime_verifier_v1 as verifier


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _artifact(path: str, label: str, *, bytes_count: int = 1000) -> dict[str, object]:
    return {"path": path, "bytes": bytes_count, "sha256": _sha(label)}


def _terminal_receipt(seed: int) -> dict[str, object]:
    checkpoint_path = f"/opaque/f3-graph-residual500-hidden16-seed{seed}-20260928-checkpoint.pt"
    training_path = f"/opaque/f3-graph-residual500-hidden16-seed{seed}-20260928-training.json"
    nonce = f"{seed:032x}"
    prefix = f"/opaque/f3-graph-residual500-hidden16-seed{seed}-full835-nonce{nonce}"
    checkpoint_sha = _sha(f"checkpoint-{seed}")
    return {
        "schema": f"core.f3.graph_residual.hidden16.seed{seed}.full835.terminal_completion_receipt.v1",
        "report_id": f"f3-graph-residual-hidden16-seed{seed}-full835-terminal-completion-receipt-v1",
        "status": "completed_diagnostic",
        "source_bound": True,
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification": False,
        "qualification_credit": 0,
        "credit": 0,
        "seed": seed,
        "model_kind": verifier.MODEL_KIND,
        "hidden": verifier.HIDDEN,
        "updates": verifier.UPDATES,
        "case_id": verifier.CASE_ID,
        "split": verifier.SPLIT,
        "transitions": verifier.TRANSITIONS,
        "frames": verifier.FRAMES,
        "terminal_markers": {
            "terminal": True,
            "execution_complete": True,
            "finite_rollout_complete": True,
            "terminal_status": "completed",
            "future_state_inputs": False,
        },
        "checkpoint": {
            **_artifact(checkpoint_path, f"checkpoint-{seed}"),
            "schema": terminal_matrix.CHECKPOINT_SCHEMA,
            "model_kind": verifier.MODEL_KIND,
            "seed": seed,
            "hidden": verifier.HIDDEN,
            "update": verifier.UPDATES,
            "content_opened": False,
            "stat_only": True,
        },
        "training_receipt": {
            **_artifact(training_path, f"training-{seed}"),
            "schema": terminal_matrix.TRAINING_SCHEMA,
            "model_kind": verifier.MODEL_KIND,
            "seed": seed,
            "hidden": verifier.HIDDEN,
            "completed_updates": verifier.UPDATES,
            "checkpoint_verified": True,
            "status": "completed",
            "checkpoint_sha256": checkpoint_sha,
            "checkpoint_update": verifier.UPDATES,
        },
        "evaluation": {
            **_artifact(prefix + "-evaluation.json", f"evaluation-{seed}"),
            "schema": terminal_matrix.EVALUATION_SCHEMA,
            "model_kind": verifier.MODEL_KIND,
            "seed": seed,
            "hidden": verifier.HIDDEN,
            "updates": verifier.UPDATES,
            "case_id": verifier.CASE_ID,
            "split": verifier.SPLIT,
            "evaluation_mode": "diagnostic",
            "diagnostic": True,
            "autonomous": True,
            "maximum_steps": verifier.TRANSITIONS,
            "transitions": verifier.TRANSITIONS,
            "frames": verifier.FRAMES,
            "execution_complete": True,
            "finite_rollout_complete": True,
            "future_state_inputs": False,
            "status": "completed",
            "namespace": prefix,
            "namespace_fresh": True,
            "namespace_nonce": nonce,
        },
        "trajectory": {
            **_artifact(prefix + "-trajectory.h5", f"trajectory-{seed}", bytes_count=2000),
            "content_opened": False,
            "stat_only": True,
        },
        "progress": {
            **_artifact(prefix + "-evaluation-progress.json", f"progress-{seed}"),
            "content_opened": False,
            "stat_only": True,
            "completion_not_inferred": True,
        },
        "side_effects": terminal_matrix._empty_side_effects(),
        "input_boundary": terminal_matrix._empty_input_boundary(),
    }


def _write_json(path: Path, value: object) -> None:
    path.write_bytes((verifier.canonical_json(value) + "\n").encode("utf-8"))


def _make_matrix(root: Path) -> tuple[Path, dict[str, object]]:
    root.mkdir(parents=True, exist_ok=True)
    receipt_paths: dict[int, Path] = {}
    for seed in verifier.SEEDS:
        path = root / f"seed{seed}-terminal-receipt.json"
        _write_json(path, _terminal_receipt(seed))
        receipt_paths[seed] = path
    report = terminal_matrix.build_report(root, terminal_paths=receipt_paths)
    assert report["source_bound"] is True
    matrix_path = root / "matrix-report.json"
    _write_json(matrix_path, report)
    return matrix_path, report


def _envelopes(root: Path, matrix_report: dict[str, object]) -> dict[str, dict[int, Path]]:
    paths: dict[str, dict[int, Path]] = {"process": {}, "evaluation": {}, "validator": {}}
    manifest_sha = _sha("f3-dataset-v2-manifest")
    for row in matrix_report["seed_matrix"]:  # type: ignore[index]
        seed = int(row["seed"])
        projection = row["projection"]
        run_id = verifier._run_id(seed)
        common = {
            "source_bound": True,
            "diagnostic_only": True,
            "formal": False,
            "formal_eligible": False,
            "T1_numerical": False,
            "T2_macro": False,
            "T2_path": False,
            "qualification": False,
            "qualification_credit": 0,
            "credit": 0,
            "seed": seed,
            "run_id": run_id,
            "namespace": projection["output_namespace"],
            "namespace_nonce": projection["namespace_nonce"],
            "model_kind": verifier.MODEL_KIND,
            "hidden": verifier.HIDDEN,
            "updates": verifier.UPDATES,
            "case_id": verifier.CASE_ID,
            "split": verifier.SPLIT,
            "transitions": verifier.TRANSITIONS,
            "frames": verifier.FRAMES,
            "manifest_sha256": manifest_sha,
            "training_receipt_sha256": projection["training_receipt"]["sha256"],
            "checkpoint": {
                key: projection["checkpoint"][key] for key in ("path", "sha256", "bytes")
            },
            "trajectory": {
                key: projection["trajectory"][key] for key in ("path", "sha256", "bytes")
            },
        }
        process = {
            "schema": f"core.f3.graph_residual.hidden16.seed{seed}.process_exit_proof.v1",
            "report_id": f"f3-graph-residual-hidden16-seed{seed}-process-exit-proof-v1",
            "status": "exited_successfully",
            **common,
            "evaluator_alive": False,
            "launcher_alive": False,
            "evaluator_returncode": 0,
            "launcher_returncode": 0,
            "returncode": 0,
        }
        evaluation = {
            "schema": f"core.f3.graph_residual.hidden16.seed{seed}.evaluation_identity.v1",
            "report_id": f"f3-graph-residual-hidden16-seed{seed}-evaluation-identity-v1",
            "status": "completed_diagnostic",
            **common,
            "evaluation_artifact": {
                key: projection["evaluation"][key] for key in ("path", "sha256", "bytes")
            },
        }
        validator = {
            "schema": f"core.f3.graph_residual.hidden16.seed{seed}.hdf5_validator_receipt.v1",
            "report_id": f"f3-graph-residual-hidden16-seed{seed}-hdf5-validator-receipt-v1",
            "status": "validated",
            "validator_schema": verifier.VALIDATOR_SCHEMA,
            **common,
            "passed": True,
            "complete": True,
            "expected_transitions": verifier.TRANSITIONS,
            "frames_executed": verifier.FRAMES,
            "trajectory_transitions": verifier.TRANSITIONS,
            "trajectory_frames": verifier.FRAMES,
            "tail_frame_count": 0,
            "production_artifacts_touched": False,
            "actual_future_state_inputs": False,
        }
        for kind, payload in (("process", process), ("evaluation", evaluation), ("validator", validator)):
            path = root / f"seed{seed}-{kind}.json"
            _write_json(path, payload)
            paths[kind][seed] = path
    return paths


def _build_complete(root: Path) -> tuple[dict[str, object], dict[str, dict[int, Path]]]:
    matrix_path, matrix_report = _make_matrix(root)
    paths = _envelopes(root, matrix_report)
    report = verifier.build_report(
        root,
        matrix_path=matrix_path,
        process_paths=paths["process"],
        evaluation_paths=paths["evaluation"],
        validator_paths=paths["validator"],
    )
    return report, paths


def test_default_report_is_blocked_and_zero_credit() -> None:
    report = verifier.build_report()
    assert report["status"] == "blocked_fail_closed"
    assert report["receipt_bound"] is False
    assert report["independently_terminal_verified"] is False
    assert report["source_bound"] is False
    assert report["formal"] is False
    assert report["T1_numerical"] is False
    assert report["T2_macro"] is False
    assert report["credit"] == 0
    assert verifier.validate_report(report) == []


def test_complete_positive_binds_all_four_evidence_classes_without_hdf5(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report, _paths = _build_complete(tmp_path)
    original_open = verifier.os.open

    def guarded_open(path: object, *args: object, **kwargs: object) -> int:
        if isinstance(path, (str, bytes, os.PathLike)) and ".h5" in os.fspath(path):
            raise AssertionError("runtime verifier must not open HDF5/trajectory")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(verifier.os, "open", guarded_open)
    # Rebuild after installing the guard: every input is JSON and all declared
    # HDF5 paths remain metadata only.
    matrix_path, matrix_report = _make_matrix(tmp_path / "second")
    paths = _envelopes(tmp_path / "second", matrix_report)
    report = verifier.build_report(
        tmp_path / "second",
        matrix_path=matrix_path,
        process_paths=paths["process"],
        evaluation_paths=paths["evaluation"],
        validator_paths=paths["validator"],
    )
    assert report["status"] == "independently_terminal_verified"
    assert report["receipt_bound"] is True
    assert report["independently_terminal_verified"] is True
    assert report["source_bound"] is True
    assert verifier.validate_report(report) == []
    assert report["side_effects"]["hdf5_opened"] is False
    assert report["input_boundary"]["hdf5_content_opened"] is False


def test_missing_exit_proof_is_not_terminal_verified(tmp_path: Path) -> None:
    complete, paths = _build_complete(tmp_path)
    paths["process"][17].unlink()
    report = verifier.build_report(
        tmp_path,
        matrix_path=tmp_path / "matrix-report.json",
        process_paths=paths["process"],
        evaluation_paths=paths["evaluation"],
        validator_paths=paths["validator"],
    )
    assert complete["source_bound"] is True
    assert report["source_bound"] is False
    assert report["seed_matrix"][0]["status"] == "missing"
    assert any("missing required evidence" in reason for reason in report["blocked_reasons"])


@pytest.mark.parametrize("field", ["evaluator_alive", "launcher_alive", "returncode", "evaluator_returncode", "launcher_returncode"])
def test_running_or_nonzero_process_proof_fails_closed(tmp_path: Path, field: str) -> None:
    _report, paths = _build_complete(tmp_path)
    payload = json.loads(paths["process"][17].read_text(encoding="utf-8"))
    payload[field] = True if field.endswith("alive") else 1
    _write_json(paths["process"][17], payload)
    report = verifier.build_report(tmp_path, matrix_path=tmp_path / "matrix-report.json", process_paths=paths["process"], evaluation_paths=paths["evaluation"], validator_paths=paths["validator"])
    assert report["source_bound"] is False
    assert any(field in reason for reason in report["blocked_reasons"])


def test_evaluation_checkpoint_identity_drift_fails_closed(tmp_path: Path) -> None:
    _report, paths = _build_complete(tmp_path)
    payload = json.loads(paths["evaluation"][29].read_text(encoding="utf-8"))
    payload["checkpoint"]["sha256"] = _sha("drifted-checkpoint")
    _write_json(paths["evaluation"][29], payload)
    report = verifier.build_report(tmp_path, matrix_path=tmp_path / "matrix-report.json", process_paths=paths["process"], evaluation_paths=paths["evaluation"], validator_paths=paths["validator"])
    assert report["source_bound"] is False
    assert any("checkpoint" in reason for reason in report["blocked_reasons"])


def test_validator_identity_and_trajectory_drift_fail_closed(tmp_path: Path) -> None:
    _report, paths = _build_complete(tmp_path)
    payload = json.loads(paths["validator"][43].read_text(encoding="utf-8"))
    payload["trajectory"]["sha256"] = _sha("drifted-trajectory")
    _write_json(paths["validator"][43], payload)
    report = verifier.build_report(tmp_path, matrix_path=tmp_path / "matrix-report.json", process_paths=paths["process"], evaluation_paths=paths["evaluation"], validator_paths=paths["validator"])
    assert report["source_bound"] is False
    assert any("trajectory" in reason for reason in report["blocked_reasons"])


@pytest.mark.parametrize("field,value", [("passed", False), ("complete", False), ("expected_transitions", 834), ("frames_executed", 835), ("qualification_credit", 1)])
def test_validator_semantics_and_credit_fail_closed(tmp_path: Path, field: str, value: object) -> None:
    _report, paths = _build_complete(tmp_path)
    payload = json.loads(paths["validator"][17].read_text(encoding="utf-8"))
    payload[field] = value
    _write_json(paths["validator"][17], payload)
    report = verifier.build_report(tmp_path, matrix_path=tmp_path / "matrix-report.json", process_paths=paths["process"], evaluation_paths=paths["evaluation"], validator_paths=paths["validator"])
    assert report["source_bound"] is False


@pytest.mark.parametrize("alias", ["formal_status", "formal_claim", "pid", "process_id", "credit_points", "credit_delta"])
def test_unknown_formal_pid_and_credit_aliases_fail_closed(tmp_path: Path, alias: str) -> None:
    _report, paths = _build_complete(tmp_path)
    payload = json.loads(paths["evaluation"][17].read_text(encoding="utf-8"))
    payload[alias] = False if "formal" in alias else 0
    _write_json(paths["evaluation"][17], payload)
    report = verifier.build_report(tmp_path, matrix_path=tmp_path / "matrix-report.json", process_paths=paths["process"], evaluation_paths=paths["evaluation"], validator_paths=paths["validator"])
    assert report["source_bound"] is False
    assert any(alias in reason for reason in report["blocked_reasons"])


def test_path_traversal_and_symlink_are_rejected(tmp_path: Path) -> None:
    _report, paths = _build_complete(tmp_path)
    outside = tmp_path.parent / "outside-process.json"
    outside.write_text(paths["process"][17].read_text(encoding="utf-8"), encoding="utf-8")
    paths["process"][17] = Path("../outside-process.json")
    report = verifier.build_report(tmp_path, matrix_path=tmp_path / "matrix-report.json", process_paths=paths["process"], evaluation_paths=paths["evaluation"], validator_paths=paths["validator"])
    assert report["source_bound"] is False
    assert any("traversal" in reason or "escapes" in reason for reason in report["blocked_reasons"])

    _report, paths = _build_complete(tmp_path / "symlink")
    real = paths["process"][17]
    link = real.with_name("process-link.json")
    real.rename(real.with_name("process-real.json"))
    link.symlink_to(real.with_name("process-real.json"))
    paths["process"][17] = link
    report = verifier.build_report(tmp_path / "symlink", matrix_path=tmp_path / "symlink" / "matrix-report.json", process_paths=paths["process"], evaluation_paths=paths["evaluation"], validator_paths=paths["validator"])
    assert report["source_bound"] is False
    assert any("symlink" in reason for reason in report["blocked_reasons"])


def test_hardlink_and_oversize_are_rejected(tmp_path: Path) -> None:
    _report, paths = _build_complete(tmp_path)
    original = paths["process"][17]
    hardlink = tmp_path / "process-hardlink.json"
    os.link(original, hardlink)
    paths["process"][17] = hardlink
    report = verifier.build_report(tmp_path, matrix_path=tmp_path / "matrix-report.json", process_paths=paths["process"], evaluation_paths=paths["evaluation"], validator_paths=paths["validator"])
    assert report["source_bound"] is False
    assert any("hard-linked" in reason for reason in report["blocked_reasons"])

    _report, paths = _build_complete(tmp_path / "oversize")
    paths["process"][17].write_bytes(b"{" + b" " * verifier.MAX_JSON_BYTES + b"}")
    report = verifier.build_report(tmp_path / "oversize", matrix_path=tmp_path / "oversize" / "matrix-report.json", process_paths=paths["process"], evaluation_paths=paths["evaluation"], validator_paths=paths["validator"])
    assert report["source_bound"] is False
    assert any("exceeds bounded" in reason for reason in report["blocked_reasons"])


def test_duplicate_nonfinite_and_toctou_are_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _report, paths = _build_complete(tmp_path)
    paths["process"][17].write_bytes(b'{"schema":"x","schema":"y"}')
    report = verifier.build_report(tmp_path, matrix_path=tmp_path / "matrix-report.json", process_paths=paths["process"], evaluation_paths=paths["evaluation"], validator_paths=paths["validator"])
    assert any("duplicate JSON" in reason for reason in report["blocked_reasons"])

    _report, paths = _build_complete(tmp_path / "nan")
    paths["process"][17].write_bytes(b'{"value":NaN}')
    report = verifier.build_report(tmp_path / "nan", matrix_path=tmp_path / "nan" / "matrix-report.json", process_paths=paths["process"], evaluation_paths=paths["evaluation"], validator_paths=paths["validator"])
    assert any("non-finite" in reason for reason in report["blocked_reasons"])

    path = tmp_path / "toctou.json"
    path.write_text("{}", encoding="utf-8")
    real_fstat = verifier.os.fstat
    regular_calls = 0

    class DriftedStat:
        def __init__(self, base: os.stat_result) -> None:
            self._base = base

        def __getattr__(self, name: str) -> object:
            if name == "st_mtime_ns":
                return self._base.st_mtime_ns + 1
            return getattr(self._base, name)

    def fstat_with_drift(fd: int) -> object:
        nonlocal regular_calls
        result = real_fstat(fd)
        if stat.S_ISREG(result.st_mode):
            regular_calls += 1
            if regular_calls == 2:
                return DriftedStat(result)
        return result

    monkeypatch.setattr(verifier.os, "fstat", fstat_with_drift)
    with pytest.raises(verifier.VerifierError, match="TOCTOU"):
        verifier._read_bounded_json(tmp_path, path, "synthetic JSON")


def test_report_writer_is_confined_to_fixed_destinations(tmp_path: Path) -> None:
    report = verifier.build_report(tmp_path, matrix_path=tmp_path / "missing-matrix.json")
    reports = tmp_path / "reports"
    reports.mkdir()
    with pytest.raises(verifier.VerifierError, match="fixed report destinations"):
        verifier.write_report(report, tmp_path / "outside.json", root=tmp_path)
    output = reports / verifier.REPORT_JSON_FILENAME
    target = tmp_path / "sentinel.json"
    target.write_text("sentinel", encoding="utf-8")
    output.symlink_to(target)
    with pytest.raises(verifier.VerifierError, match="regular file"):
        verifier.write_report(report, output, root=tmp_path)
    assert target.read_text(encoding="utf-8") == "sentinel"


def test_validate_report_rejects_unknown_top_level_alias(tmp_path: Path) -> None:
    report = verifier.build_report(tmp_path, matrix_path=tmp_path / "missing.json")
    report["formal_status"] = False
    errors = verifier.validate_report(report)
    assert errors
    assert any("formal_status" in reason for reason in errors)
