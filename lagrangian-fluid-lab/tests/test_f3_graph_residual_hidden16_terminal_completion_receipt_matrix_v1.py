"""Synthetic bounded-input tests for the residual hidden16 terminal matrix."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import stat

import pytest

from scripts import f3_graph_residual_hidden16_terminal_completion_receipt_matrix_v1 as matrix


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _artifact(path: str, label: str, *, suffix: str | None = None) -> dict[str, object]:
    if suffix is not None:
        assert path.endswith(suffix)
    return {"path": path, "bytes": 1000, "sha256": _sha(label)}


def _receipt(seed: int, *, validator: bool = False) -> dict[str, object]:
    checkpoint_path = f"/opaque/f3-graph-residual500-hidden16-seed{seed}-checkpoint.pt"
    training_path = f"/opaque/f3-graph-residual500-hidden16-seed{seed}-training.json"
    nonce = f"{seed:032x}"
    prefix = f"/opaque/f3-graph-residual500-hidden16-seed{seed}-full835-nonce{nonce}"
    checkpoint_sha = _sha(f"checkpoint-{seed}")
    payload: dict[str, object] = {
        "schema": (
            f"core.f3.graph_residual.hidden16.seed{seed}."
            "full835.terminal_completion_receipt.v1"
        ),
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
        "model_kind": matrix.MODEL_KIND,
        "hidden": matrix.HIDDEN,
        "updates": matrix.UPDATES,
        "case_id": matrix.CASE_ID,
        "split": matrix.SPLIT,
        "transitions": matrix.TRANSITIONS,
        "frames": matrix.FRAMES,
        "terminal_markers": {
            "terminal": True,
            "execution_complete": True,
            "finite_rollout_complete": True,
            "terminal_status": "completed",
            "future_state_inputs": False,
        },
        "checkpoint": {
            **_artifact(checkpoint_path, f"checkpoint-{seed}"),
            "schema": matrix.CHECKPOINT_SCHEMA,
            "model_kind": matrix.MODEL_KIND,
            "seed": seed,
            "hidden": matrix.HIDDEN,
            "update": matrix.UPDATES,
            "content_opened": False,
            "stat_only": True,
        },
        "training_receipt": {
            **_artifact(training_path, f"training-{seed}", suffix=".json"),
            "schema": matrix.TRAINING_SCHEMA,
            "model_kind": matrix.MODEL_KIND,
            "seed": seed,
            "hidden": matrix.HIDDEN,
            "completed_updates": matrix.UPDATES,
            "checkpoint_verified": True,
            "status": "completed",
            "checkpoint_sha256": checkpoint_sha,
            "checkpoint_update": matrix.UPDATES,
        },
        "evaluation": {
            **_artifact(prefix + "-evaluation.json", f"evaluation-{seed}", suffix=".json"),
            "schema": matrix.EVALUATION_SCHEMA,
            "model_kind": matrix.MODEL_KIND,
            "seed": seed,
            "hidden": matrix.HIDDEN,
            "updates": matrix.UPDATES,
            "case_id": matrix.CASE_ID,
            "split": matrix.SPLIT,
            "evaluation_mode": "diagnostic",
            "diagnostic": True,
            "autonomous": True,
            "maximum_steps": matrix.TRANSITIONS,
            "transitions": matrix.TRANSITIONS,
            "frames": matrix.FRAMES,
            "execution_complete": True,
            "finite_rollout_complete": True,
            "future_state_inputs": False,
            "status": "completed",
            "namespace": prefix,
            "namespace_fresh": True,
            "namespace_nonce": nonce,
        },
        "trajectory": {
            **_artifact(prefix + "-trajectory.h5", f"trajectory-{seed}", suffix=".h5"),
            "content_opened": False,
            "stat_only": True,
        },
        "progress": {
            **_artifact(prefix + "-evaluation-progress.json", f"progress-{seed}", suffix=".json"),
            "content_opened": False,
            "stat_only": True,
            "completion_not_inferred": True,
        },
        "side_effects": matrix._empty_side_effects(),
        "input_boundary": matrix._empty_input_boundary(),
    }
    if validator:
        payload["hdf5_validator"] = {
            **_artifact(f"/opaque/f3-graph-residual500-hidden16-seed{seed}-hdf5-validator.json", f"validator-{seed}", suffix=".json"),
            "schema": matrix.VALIDATOR_SCHEMA,
            "passed": True,
            "complete": True,
            "diagnostic_only": True,
            "case_id": matrix.CASE_ID,
            "expected_transitions": matrix.TRANSITIONS,
            "frames_executed": matrix.FRAMES,
            "trajectory_frames": matrix.FRAMES,
            "trajectory_transitions": matrix.TRANSITIONS,
            "tail_frame_count": 0,
            "qualification_credit": 0,
            "production_artifacts_touched": False,
            "actual_future_state_inputs": False,
        }
    return payload


def _write_receipts(root: Path, receipts: dict[int, dict[str, object]]) -> dict[int, Path]:
    paths: dict[int, Path] = {}
    for seed, payload in receipts.items():
        path = root / f"seed{seed}-terminal-receipt.json"
        path.write_bytes((matrix.canonical_json(payload) + "\n").encode("utf-8"))
        paths[seed] = path
    return paths


def _report(root: Path, receipts: dict[int, dict[str, object]]) -> dict:
    paths = _write_receipts(root, receipts)
    return matrix.build_report(root, terminal_paths=paths)


def test_default_future_receipts_are_blocked(tmp_path: Path) -> None:
    paths = {seed: tmp_path / f"future-seed{seed}-terminal-receipt.json" for seed in matrix.SEEDS}
    report = matrix.build_report(tmp_path, terminal_paths=paths)
    assert report["status"] == "blocked_fail_closed"
    assert report["source_bound"] is False
    assert all(row["status"] == "missing" for row in report["seed_matrix"])
    assert matrix.validate_report(report) == []


def test_complete_matrix_binds_all_seeds_without_opening_hdf5(tmp_path: Path) -> None:
    report = _report(tmp_path, {seed: _receipt(seed) for seed in matrix.SEEDS})
    assert report["status"] == "bound_terminal_diagnostic"
    assert report["source_bound"] is True
    assert all(row["projection"]["validator_bound"] is False for row in report["seed_matrix"])
    assert matrix.validate_report(report) == []
    # The declared trajectory and validator artifacts do not need to exist;
    # the adapter never opens either one.
    assert not any(tmp_path.rglob("*.h5"))


def test_optional_validator_receipt_is_bound_but_hdf5_is_not_opened(tmp_path: Path) -> None:
    receipts = {seed: _receipt(seed, validator=(seed == 17)) for seed in matrix.SEEDS}
    report = _report(tmp_path, receipts)
    assert report["source_bound"] is True
    assert report["checks"][5]["passed"] is True
    assert report["seed_matrix"][0]["projection"]["validator_bound"] is True
    assert report["seed_matrix"][1]["projection"]["validator_bound"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "running"),
        ("status", "partial"),
        ("status", "legacy_completed"),
        ("hidden", 8),
        ("model_kind", "graph_raw"),
        ("updates", 250),
        ("case_id", "F3_OTHER"),
        ("frames", 835),
        ("credit", 1),
    ],
)
def test_pending_partial_running_legacy_drift_and_nonzero_credit_fail_closed(
    tmp_path: Path, field: str, value: object
) -> None:
    receipts = {seed: _receipt(seed) for seed in matrix.SEEDS}
    receipts[17][field] = value
    report = _report(tmp_path, receipts)
    assert report["source_bound"] is False
    assert report["status"] == "blocked_fail_closed"
    assert matrix.validate_report(report) == []


def test_wrong_nested_configuration_fails_closed(tmp_path: Path) -> None:
    receipts = {seed: _receipt(seed) for seed in matrix.SEEDS}
    receipts[29]["evaluation"] = copy.deepcopy(receipts[29]["evaluation"])
    receipts[29]["evaluation"]["maximum_steps"] = 50  # type: ignore[index]
    report = _report(tmp_path, receipts)
    assert report["source_bound"] is False
    assert any("maximum_steps" in reason for reason in report["blocked_reasons"])


@pytest.mark.parametrize(
    "alias",
    [
        "formal_claim",
        "formal_status",
        "pid",
        "process_id",
        "evaluator_pid",
        "credit_points",
        "credit_delta",
    ],
)
def test_unknown_top_level_promotion_aliases_fail_closed(
    tmp_path: Path, alias: str
) -> None:
    receipts = {seed: _receipt(seed) for seed in matrix.SEEDS}
    receipts[17][alias] = False if "formal" in alias else 0
    report = _report(tmp_path, receipts)
    assert report["source_bound"] is False
    assert any(alias in reason for reason in report["blocked_reasons"])


def test_checkpoint_path_and_sha_are_independently_unique(tmp_path: Path) -> None:
    receipts = {seed: _receipt(seed) for seed in matrix.SEEDS}
    receipts[29]["checkpoint"] = copy.deepcopy(receipts[29]["checkpoint"])
    shared_checkpoint_path = "/opaque/f3-graph-residual500-hidden16-seed17-seed29-checkpoint.pt"
    receipts[17]["checkpoint"] = copy.deepcopy(receipts[17]["checkpoint"])
    receipts[17]["checkpoint"]["path"] = shared_checkpoint_path  # type: ignore[index]
    receipts[29]["checkpoint"]["path"] = shared_checkpoint_path  # type: ignore[index]
    report = _report(tmp_path, receipts)
    assert report["source_bound"] is False
    assert any("checkpoint path or SHA identity" in reason for reason in report["blocked_reasons"])

    receipts = {seed: _receipt(seed) for seed in matrix.SEEDS}
    receipts[29]["training_receipt"] = copy.deepcopy(receipts[29]["training_receipt"])
    receipts[29]["training_receipt"]["sha256"] = receipts[17]["training_receipt"]["sha256"]  # type: ignore[index]
    report = _report(tmp_path, receipts)
    assert report["source_bound"] is False
    assert any("training path or SHA identity" in reason for reason in report["blocked_reasons"])


def test_namespace_requires_explicit_fresh_marker(tmp_path: Path) -> None:
    receipts = {seed: _receipt(seed) for seed in matrix.SEEDS}
    receipts[17]["evaluation"] = copy.deepcopy(receipts[17]["evaluation"])
    receipts[17]["evaluation"].pop("namespace_fresh")  # type: ignore[index]
    report = _report(tmp_path, receipts)
    assert report["source_bound"] is False
    assert any("namespace_fresh" in reason for reason in report["blocked_reasons"])


def _blocked_report(tmp_path: Path) -> dict:
    return matrix.build_report(
        tmp_path,
        terminal_paths={
            seed: tmp_path / f"future-seed{seed}-terminal-receipt.json"
            for seed in matrix.SEEDS
        },
    )


@pytest.mark.parametrize("alias", ["formal_claim", "pid", "credit_points"])
def test_unknown_top_level_report_aliases_fail_validation(tmp_path: Path, alias: str) -> None:
    report = _blocked_report(tmp_path)
    report[alias] = False if "formal" in alias else 0
    errors = matrix.validate_report(report)
    assert errors
    assert any(alias in reason for reason in errors)


def test_report_output_is_confined_to_fixed_reports_destinations(tmp_path: Path) -> None:
    (tmp_path / "reports").mkdir()
    report = _blocked_report(tmp_path)
    with pytest.raises(matrix.MatrixError, match="fixed report filenames"):
        matrix.write_report(report, tmp_path / "reports" / "unexpected.json", root=tmp_path)
    with pytest.raises(matrix.MatrixError, match="reports"):
        matrix.write_report(report, tmp_path / "outside.json", root=tmp_path)
    with pytest.raises(matrix.MatrixError, match="fixed report filenames"):
        matrix.write_report(report, tmp_path / "reports" / "unexpected.txt", root=tmp_path)


def test_report_output_rejects_symlink_and_hardlink_destinations(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    report = _blocked_report(tmp_path)
    output = reports / matrix.REPORT_JSON_FILENAME

    symlink_target = tmp_path / "symlink-target.json"
    symlink_target.write_text("sentinel", encoding="utf-8")
    output.symlink_to(symlink_target)
    with pytest.raises(matrix.MatrixError, match="symlink"):
        matrix.write_report(report, output, root=tmp_path)
    assert symlink_target.read_text(encoding="utf-8") == "sentinel"

    output.unlink()
    hardlink_target = tmp_path / "hardlink-target.json"
    hardlink_target.write_text("sentinel", encoding="utf-8")
    os.link(hardlink_target, output)
    with pytest.raises(matrix.MatrixError, match="hard-linked"):
        matrix.write_report(report, output, root=tmp_path)
    assert hardlink_target.read_text(encoding="utf-8") == "sentinel"


def test_report_output_does_not_overwrite_unexpected_regular_file(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    report = _blocked_report(tmp_path)
    output = reports / matrix.REPORT_JSON_FILENAME
    output.write_text("unexpected", encoding="utf-8")
    with pytest.raises(matrix.MatrixError, match="expected validated report"):
        matrix.write_report(report, output, root=tmp_path)
    assert output.read_text(encoding="utf-8") == "unexpected"


def test_report_output_writes_json_and_markdown_only_at_fixed_paths(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    report = _blocked_report(tmp_path)
    json_output = reports / matrix.REPORT_JSON_FILENAME
    markdown_output = reports / matrix.REPORT_MARKDOWN_FILENAME
    matrix.write_report(report, json_output, root=tmp_path)
    matrix.write_report(report, markdown_output, root=tmp_path)
    assert json.loads(json_output.read_text(encoding="utf-8"))["status"] == "blocked_fail_closed"
    assert markdown_output.read_text(encoding="utf-8").startswith("# F3 graph_residual")


def test_duplicate_json_is_rejected(tmp_path: Path) -> None:
    receipts = {seed: _receipt(seed) for seed in matrix.SEEDS}
    paths = _write_receipts(tmp_path, receipts)
    duplicate = b'{"schema":"x","schema":"y"}'
    paths[17].write_bytes(duplicate)
    report = matrix.build_report(tmp_path, terminal_paths=paths)
    assert report["source_bound"] is False
    assert any("duplicate JSON" in reason for reason in report["blocked_reasons"])


def test_nonfinite_json_is_rejected(tmp_path: Path) -> None:
    receipts = {seed: _receipt(seed) for seed in matrix.SEEDS}
    paths = _write_receipts(tmp_path, receipts)
    paths[17].write_bytes(b'{"schema":"x","value":NaN}')
    report = matrix.build_report(tmp_path, terminal_paths=paths)
    assert report["source_bound"] is False
    assert any("non-finite" in reason for reason in report["blocked_reasons"])


def test_path_traversal_is_rejected_without_reading_outside_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "seed17-terminal-receipt-outside.json"
    outside.write_text("{}", encoding="utf-8")
    paths = {seed: tmp_path / f"seed{seed}-terminal-receipt.json" for seed in matrix.SEEDS}
    paths[17] = Path("../seed17-terminal-receipt-outside.json")
    report = matrix.build_report(tmp_path, terminal_paths=paths)
    assert report["source_bound"] is False
    assert report["seed_matrix"][0]["status"] == "rejected"
    assert outside.read_text(encoding="utf-8") == "{}"


def test_symlink_receipt_is_rejected(tmp_path: Path) -> None:
    payload = _receipt(17)
    target = tmp_path / "real-seed17-terminal-receipt.json"
    target.write_bytes((matrix.canonical_json(payload) + "\n").encode("utf-8"))
    link = tmp_path / "seed17-terminal-receipt.json"
    link.symlink_to(target)
    report = matrix.build_report(tmp_path, terminal_paths={17: link})
    assert report["source_bound"] is False
    assert report["seed_matrix"][0]["status"] == "rejected"
    assert report["seed_matrix"][0]["source"]["opened"] is False


def test_oversize_receipt_is_rejected(tmp_path: Path) -> None:
    paths = {seed: tmp_path / f"seed{seed}-terminal-receipt.json" for seed in matrix.SEEDS}
    paths[17].write_bytes(b"{" + b" " * matrix.MAX_JSON_BYTES + b"}")
    report = matrix.build_report(tmp_path, terminal_paths=paths)
    assert report["source_bound"] is False
    assert any("exceeds bounded" in reason for reason in report["blocked_reasons"])


def test_descriptor_identity_change_is_rejected_as_toctou(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "seed17-terminal-receipt.json"
    path.write_text("{}", encoding="utf-8")
    real_fstat = matrix.os.fstat
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

    monkeypatch.setattr(matrix.os, "fstat", fstat_with_drift)
    with pytest.raises(matrix.MatrixError, match="TOCTOU"):
        matrix._read_bounded_json(tmp_path, path, "synthetic receipt")


def test_cli_default_writes_blocked_report(tmp_path: Path) -> None:
    (tmp_path / "reports").mkdir()
    output = tmp_path / "reports" / matrix.REPORT_JSON_FILENAME
    report = matrix.build_report(
        tmp_path,
        terminal_paths={seed: tmp_path / f"future-seed{seed}-terminal-receipt.json" for seed in matrix.SEEDS},
    )
    matrix.write_report(report, output, root=tmp_path)
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["status"] == "blocked_fail_closed"
    assert matrix.validate_report(saved) == []
