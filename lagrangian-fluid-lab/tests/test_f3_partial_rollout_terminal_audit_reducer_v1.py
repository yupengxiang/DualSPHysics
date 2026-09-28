"""Focused fail-closed tests for the independent partial-rollout reducer."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts import f3_partial_rollout_terminal_audit_reducer_v1 as reducer


def _namespace(root: Path, model_kind: str, seed: int, nonce: str) -> Path:
    token = "graph-residual" if model_kind == "graph_residual" else "graph-raw"
    return root / f"f3-{token}500-hidden16-seed{seed}-full835-nonce{nonce}"


def _payload(namespace: Path, completed: int, *, status: str = "running", complete: bool = False) -> dict[str, object]:
    return {
        "schema": reducer.PROGRESS_SCHEMA,
        "case_id": reducer.CASE_ID,
        "status": status,
        "completed_frames": completed,
        "expected_frames": reducer.TRANSITIONS,
        "frames_expected": reducer.TRANSITIONS,
        "frames_executed": completed,
        "execution_complete": complete,
        "finite_rollout_complete": complete,
        "future_state_inputs": False,
        "autonomous": True,
        "trajectory_output": str(namespace) + reducer.TRAJECTORY_SUFFIX,
        "elapsed_seconds": 1.0,
    }


def _write_progress(path: Path, payload: object) -> None:
    path.write_bytes(
        (json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    )


def _fixture(tmp_path: Path) -> tuple[list[dict[str, object]], dict[tuple[str, int], Path]]:
    root = tmp_path / "fresh-runs"
    root.mkdir()
    counts = {
        ("graph_residual", 17): 250,
        ("graph_residual", 29): 250,
        ("graph_residual", 43): 225,
        ("graph_raw", 17): 150,
        ("graph_raw", 29): 150,
        ("graph_raw", 43): 125,
    }
    observations: list[dict[str, object]] = []
    progress_paths: dict[tuple[str, int], Path] = {}
    for index, ((model_kind, seed), completed) in enumerate(counts.items(), start=1):
        nonce = f"{index:032x}"
        namespace = _namespace(root, model_kind, seed, nonce)
        progress = Path(str(namespace) + reducer.PROGRESS_SUFFIX)
        trajectory = Path(str(namespace) + reducer.TRAJECTORY_SUFFIX)
        evaluation = Path(str(namespace) + reducer.EVALUATION_SUFFIX)
        _write_progress(progress, _payload(namespace, completed))
        trajectory.write_bytes(b"trajectory-lstat-fixture")
        observations.append(
            {
                "model_kind": model_kind,
                "seed": seed,
                "progress_path": str(progress),
                "trajectory_path": str(trajectory),
                "evaluation_path": str(evaluation),
                "evaluation_missing": True,
            }
        )
        progress_paths[(model_kind, seed)] = progress
    return observations, progress_paths


def _rows(report: dict[str, object]) -> dict[tuple[str, int], dict[str, object]]:
    return {
        (row["model_kind"], row["seed"]): row  # type: ignore[index]
        for row in report["seed_matrix"]  # type: ignore[union-attr]
    }


def test_six_partial_fresh_namespaces_reduce_to_blocked_zero_credit(tmp_path: Path) -> None:
    observations, _ = _fixture(tmp_path)
    report = reducer.build_report(observations, observed_at_utc="2026-09-29T00:00:00Z")
    assert reducer.validate_report(report) == []
    assert report["status"] == reducer.STATUS
    assert report["credit"] == 0
    assert report["source_bound"] is False
    rows = _rows(report)
    assert {
        key: rows[key]["observed_completed_frames"]
        for key in rows
    } == {
        ("graph_residual", 17): 250,
        ("graph_residual", 29): 250,
        ("graph_residual", 43): 225,
        ("graph_raw", 17): 150,
        ("graph_raw", 29): 150,
        ("graph_raw", 43): 125,
    }
    for row in rows.values():
        assert row["status"] == "blocked_partial_or_missing_terminal"
        assert row["execution_complete"] is False
        assert row["finite_rollout_complete"] is False
        assert row["evaluation_missing"] is True
        assert row["process_proof_missing"] is True
        assert row["terminal_promotion"] is False
        assert row["credit"] == 0
        assert row["trajectory"]["lstat_only"] is True  # type: ignore[index]
        assert row["trajectory"]["opened"] is False  # type: ignore[index]
        assert row["evaluation"]["opened"] is False  # type: ignore[index]
        assert "evaluation_missing" in row["blocked_reasons"]  # type: ignore[operator]
        progress_path = Path(row["progress_path"])  # type: ignore[arg-type]
        assert row["progress"]["sha256"] == hashlib.sha256(progress_path.read_bytes()).hexdigest()  # type: ignore[index]


def test_default_contract_has_fixed_models_seeds_and_no_runtime_side_effects() -> None:
    report = reducer.build_report(observed_at_utc="2026-09-29T00:00:00Z")
    contract = report["expected_contract"]
    assert contract["models"] == ["graph_residual", "graph_raw"]  # type: ignore[index]
    assert contract["seeds"] == [17, 29, 43]  # type: ignore[index]
    assert contract["hidden"] == 16  # type: ignore[index]
    assert contract["updates"] == 500  # type: ignore[index]
    assert contract["case_id"] == reducer.CASE_ID  # type: ignore[index]
    assert contract["transitions"] == 835  # type: ignore[index]
    assert report["side_effects"]["hdf5_opened"] is False  # type: ignore[index]
    assert report["side_effects"]["checkpoint_opened"] is False  # type: ignore[index]
    assert report["side_effects"]["evaluation_opened"] is False  # type: ignore[index]
    assert report["side_effects"]["live_pid_observed"] is False  # type: ignore[index]


@pytest.mark.parametrize("marker", ["partial", "legacy", "unknown"])
def test_partial_legacy_unknown_namespace_cannot_be_terminal(tmp_path: Path, marker: str) -> None:
    observations, _ = _fixture(tmp_path)
    candidate = copy.deepcopy(observations[0])
    candidate["progress_path"] = str(candidate["progress_path"]).replace(
        "-full835-nonce", f"-{marker}-full835-nonce"
    )
    report = reducer.build_report([candidate] + observations[1:])
    row = _rows(report)[("graph_residual", 17)]
    assert row["status"] == reducer.STATUS
    assert row["terminal_promotion"] is False
    assert row["observed_completed_frames"] is None
    assert row["execution_complete"] is False
    assert row["finite_rollout_complete"] is False
    assert "completed" not in str(row["terminal_status"])


def test_terminal_progress_markers_are_forced_nonterminal(tmp_path: Path) -> None:
    observations, _ = _fixture(tmp_path)
    candidate = copy.deepcopy(observations[0])
    progress_path = Path(candidate["progress_path"])
    namespace = progress_path.with_name(progress_path.name[: -len(reducer.PROGRESS_SUFFIX)])
    _write_progress(progress_path, _payload(namespace, 835, status="completed", complete=True))
    report = reducer.build_report([candidate] + observations[1:])
    row = _rows(report)[("graph_residual", 17)]
    assert row["observed_completed_frames"] == 835
    assert row["status"] == reducer.STATUS
    assert row["execution_complete"] is False
    assert row["finite_rollout_complete"] is False
    assert row["terminal_promotion"] is False
    assert "progress_completed_status_cannot_promote_terminal" in row["blocked_reasons"]  # type: ignore[operator]


def test_progress_json_is_the_only_content_file_opened(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    observations, _ = _fixture(tmp_path)
    original_open = reducer.os.open
    opened: list[str] = []

    def spy(path: object, flags: int, *args: object) -> int:
        opened.append(str(path))
        return original_open(path, flags, *args)

    monkeypatch.setattr(reducer.os, "open", spy)
    reducer.build_report(observations)
    assert len(opened) == 6
    assert all(path.endswith(reducer.PROGRESS_SUFFIX) for path in opened)
    assert not any(path.endswith(".h5") or path.endswith(".pt") or path.endswith("-evaluation.json") for path in opened)


def test_existing_evaluation_is_lstat_only_and_claim_drift_blocks(tmp_path: Path) -> None:
    observations, _ = _fixture(tmp_path)
    candidate = copy.deepcopy(observations[0])
    evaluation = Path(candidate["evaluation_path"])
    evaluation.write_bytes(b"evaluation-content-must-not-be-opened")
    report = reducer.build_report([candidate] + observations[1:])
    row = _rows(report)[("graph_residual", 17)]
    assert row["evaluation_missing"] is False
    assert row["evaluation"]["exists"] is True  # type: ignore[index]
    assert row["evaluation"]["opened"] is False  # type: ignore[index]
    assert row["evaluation"]["content_opened"] is False  # type: ignore[index]
    assert "evaluation_present_but_never_opened" in row["blocked_reasons"]  # type: ignore[operator]

    candidate["evaluation_missing"] = True
    report = reducer.build_report([candidate] + observations[1:])
    row = _rows(report)[("graph_residual", 17)]
    assert "evaluation_missing_fact_drift" in row["blocked_reasons"]  # type: ignore[operator]
    assert row["status"] == reducer.STATUS


def test_trajectory_symlink_is_not_opened_or_promoted(tmp_path: Path) -> None:
    observations, _ = _fixture(tmp_path)
    candidate = copy.deepcopy(observations[0])
    trajectory = Path(candidate["trajectory_path"])
    target = trajectory.with_name("trajectory-target.bin")
    target.write_bytes(b"target")
    trajectory.unlink()
    trajectory.symlink_to(target)
    report = reducer.build_report([candidate] + observations[1:])
    row = _rows(report)[("graph_residual", 17)]
    assert row["trajectory"]["symlink"] is True  # type: ignore[index]
    assert row["trajectory"]["opened"] is False  # type: ignore[index]
    assert "trajectory_lstat_not_safe_regular_single_link" in row["blocked_reasons"]  # type: ignore[operator]
    assert row["status"] == reducer.STATUS


def test_trajectory_hardlink_is_not_opened_or_promoted(tmp_path: Path) -> None:
    observations, _ = _fixture(tmp_path)
    candidate = copy.deepcopy(observations[0])
    trajectory = Path(candidate["trajectory_path"])
    target = trajectory.with_name("trajectory-target.bin")
    target.write_bytes(b"target")
    trajectory.unlink()
    trajectory.hardlink_to(target)
    report = reducer.build_report([candidate] + observations[1:])
    row = _rows(report)[("graph_residual", 17)]
    assert row["trajectory"]["hardlink"] is True  # type: ignore[index]
    assert row["trajectory"]["opened"] is False  # type: ignore[index]
    assert row["status"] == reducer.STATUS


def test_duplicate_progress_key_fails_closed(tmp_path: Path) -> None:
    observations, _ = _fixture(tmp_path)
    candidate = copy.deepcopy(observations[0])
    progress_path = Path(candidate["progress_path"])
    payload = _payload(progress_path.with_name(progress_path.name[: -len(reducer.PROGRESS_SUFFIX)]), 250)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    progress_path.write_text(encoded[:-1] + ',"completed_frames":251}', encoding="utf-8")
    report = reducer.build_report([candidate] + observations[1:])
    row = _rows(report)[("graph_residual", 17)]
    assert row["observed_completed_frames"] is None
    assert row["status"] == reducer.STATUS
    assert "duplicate JSON object key" in row["blocked_reasons"][0]  # type: ignore[index]


def test_nonfinite_progress_fails_closed(tmp_path: Path) -> None:
    observations, _ = _fixture(tmp_path)
    candidate = copy.deepcopy(observations[0])
    progress_path = Path(candidate["progress_path"])
    payload = _payload(progress_path.with_name(progress_path.name[: -len(reducer.PROGRESS_SUFFIX)]), 250)
    payload["elapsed_seconds"] = float("nan")
    progress_path.write_text(json.dumps(payload, allow_nan=True), encoding="utf-8")
    report = reducer.build_report([candidate] + observations[1:])
    row = _rows(report)[("graph_residual", 17)]
    assert row["observed_completed_frames"] is None
    assert row["status"] == reducer.STATUS
    assert "non-finite JSON constant" in row["blocked_reasons"][0]  # type: ignore[index]


def test_deeply_nested_progress_is_blocked_without_recursion_error(tmp_path: Path) -> None:
    observations, _ = _fixture(tmp_path)
    candidate = copy.deepcopy(observations[0])
    progress_path = Path(candidate["progress_path"])
    depth = 1500
    progress_path.write_text(
        ("{\"nested\":" * depth) + "null" + ("}" * depth), encoding="utf-8"
    )
    report = reducer.build_report([candidate] + observations[1:])
    row = _rows(report)[("graph_residual", 17)]
    assert row["status"] == reducer.STATUS
    assert row["observed_completed_frames"] is None
    assert row["formal"] is False
    assert row["credit"] == 0
    assert any("nesting depth" in reason.lower() for reason in row["blocked_reasons"])


def test_progress_parent_symlink_is_rejected_without_following_it(tmp_path: Path) -> None:
    observations, _ = _fixture(tmp_path)
    candidate = copy.deepcopy(observations[0])
    source_root = tmp_path / "fresh-runs"
    symlink_root = tmp_path / "fresh-runs-alias"
    symlink_root.symlink_to(source_root, target_is_directory=True)
    for field in ("progress_path", "trajectory_path", "evaluation_path"):
        candidate[field] = str(symlink_root / Path(candidate[field]).name)
    report = reducer.build_report([candidate] + observations[1:])
    row = _rows(report)[("graph_residual", 17)]
    assert row["status"] == reducer.STATUS
    assert row["observed_completed_frames"] is None
    assert any("symlink path component" in reason for reason in row["blocked_reasons"])


def test_lexical_out_of_bounds_progress_path_is_rejected(tmp_path: Path) -> None:
    observations, _ = _fixture(tmp_path)
    candidate = copy.deepcopy(observations[0])
    progress_path = Path(candidate["progress_path"])
    candidate["progress_path"] = str(
        progress_path.parent / "nested" / ".." / progress_path.name
    )
    report = reducer.build_report([candidate] + observations[1:])
    row = _rows(report)[("graph_residual", 17)]
    assert row["status"] == reducer.STATUS
    assert row["observed_completed_frames"] is None
    assert any("normalized lexical path" in reason for reason in row["blocked_reasons"])


def test_missing_observation_and_unknown_record_do_not_change_fixed_matrix(tmp_path: Path) -> None:
    observations, _ = _fixture(tmp_path)
    report = reducer.build_report(observations[:2] + [{"model_kind": "unknown", "seed": 99}])
    assert len(report["seed_matrix"]) == 6  # type: ignore[arg-type]
    rows = _rows(report)
    assert rows[("graph_residual", 17)]["observed_completed_frames"] == 250
    assert rows[("graph_residual", 29)]["observed_completed_frames"] == 250
    assert rows[("graph_residual", 43)]["blocked_reasons"] == ["observation_missing", "process_proof_missing", "evaluation_missing"]
    assert "observation[2]_unknown_model_or_seed" in report["blocked_reasons"]  # type: ignore[operator]
    assert all(row["status"] == reducer.STATUS for row in rows.values())


def test_validate_report_rejects_forged_completed_row(tmp_path: Path) -> None:
    observations, _ = _fixture(tmp_path)
    report = reducer.build_report(observations)
    forged = copy.deepcopy(report)
    row = forged["seed_matrix"][0]
    row["status"] = "completed"
    row["terminal_status"] = "completed"
    row["terminal_promotion"] = True
    row["execution_complete"] = True
    row["finite_rollout_complete"] = True
    assert reducer.validate_report(forged)


@pytest.mark.parametrize(
    ("field", "forged_value"),
    [
        ("formal", True),
        ("formal_eligible", True),
        ("T1_numerical", True),
        ("T2_macro", True),
        ("T2_path", True),
        ("qualification", True),
        ("qualification_credit", 1),
        ("credit", 1),
    ],
)
def test_validate_report_rejects_forged_row_authority_fields(
    tmp_path: Path, field: str, forged_value: object
) -> None:
    observations, _ = _fixture(tmp_path)
    report = reducer.build_report(observations)
    forged = copy.deepcopy(report)
    forged["seed_matrix"][0][field] = forged_value  # type: ignore[index]
    errors = reducer.validate_report(forged)
    assert any(f"seed_matrix[0].{field}" in error for error in errors)


def test_validate_report_rejects_missing_and_unknown_row_fields(tmp_path: Path) -> None:
    observations, _ = _fixture(tmp_path)
    report = reducer.build_report(observations)

    missing = copy.deepcopy(report)
    del missing["seed_matrix"][0]["T1_numerical"]  # type: ignore[index]
    missing_errors = reducer.validate_report(missing)
    assert any("seed_matrix[0] is missing fields" in error for error in missing_errors)

    unknown = copy.deepcopy(report)
    unknown["seed_matrix"][0]["untrusted_permission_alias"] = True  # type: ignore[index]
    unknown_errors = reducer.validate_report(unknown)
    assert any("unknown fields" in error for error in unknown_errors)


def test_input_bundle_and_cli_write_only_a_new_small_report(tmp_path: Path) -> None:
    observations, _ = _fixture(tmp_path)
    bundle = tmp_path / "input.json"
    _write_progress(bundle, {"schema": reducer.INPUT_SCHEMA, "observations": observations})
    output = tmp_path / "report.json"
    assert reducer.main(["--input", str(bundle), "--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == reducer.STATUS
    assert reducer.main(["--input", str(bundle), "--output", str(output)]) == 2
