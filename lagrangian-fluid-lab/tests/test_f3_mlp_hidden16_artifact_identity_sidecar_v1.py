"""Focused tests for the independent F3 MLP artifact-identity sidecar."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import os

import pytest

from scripts import f3_mlp_hidden16_artifact_identity_sidecar_v1 as sidecar


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_json(path: Path, payload: object) -> tuple[int, str]:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return len(raw), _sha_bytes(raw)


def _zero_fields() -> dict[str, object]:
    return dict(sidecar.ZERO_CREDIT_FIELDS)


def _fresh_paths(seed: int, nonce: str) -> dict[str, Path]:
    return sidecar._fresh_paths(seed, nonce)


def _validator_payload(paths: dict[str, Path], *, mutation: str | None = None) -> dict[str, object]:
    checks: dict[str, object] = {
        "case_binding": True,
        "shape": True,
        "time": True,
        "valid": True,
        "future_state_inputs": True,
        "completion_semantics": True,
        "trajectory_frames": 836,
        "trajectory_transitions": 835,
        "executed_frame_count": 836,
        "tail_frame_count": 0,
    }
    payload: dict[str, object] = {
        "schema": sidecar.VALIDATOR_SCHEMA,
        "passed": True,
        "fail_closed": False,
        "diagnostic_only": True,
        "synthetic_only": False,
        "production_artifacts_touched": False,
        "qualification_credit": 0,
        "case_id": sidecar.CASE_ID,
        "evaluation_json": str(paths["evaluation"]),
        "trajectory_hdf5": str(paths["trajectory"]),
        "expected_transitions": 835,
        "frames_executed": 835,
        "complete": True,
        "incomplete": False,
        "failure_category": None,
        "checks": checks,
        "row_fields_checked": ["case_id", "frames_executed"],
    }
    if mutation == "passed":
        payload["passed"] = False
    elif mutation == "complete":
        payload["complete"] = False
    elif mutation == "transitions":
        payload["expected_transitions"] = 834
    elif mutation == "frames":
        checks["trajectory_frames"] = 835
    elif mutation == "alias":
        payload["credit"] = 0
    elif mutation == "path":
        payload["evaluation_json"] = str(paths["evaluation"]) + ".drift"
    return payload


def _make_fixture(tmp_path: Path, *, seed: int = 17, nonce: str | None = None) -> tuple[Path, int, str, dict[str, Path]]:
    root = tmp_path / "lab"
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    nonce = nonce or hashlib.sha256(str(tmp_path).encode()).hexdigest()[:32]
    paths = _fresh_paths(seed, nonce)
    cleanup = [paths[key] for key in ("evaluation", "trajectory", "validator", "sidecar")]
    for path in cleanup:
        path.unlink(missing_ok=True)

    training_rows: list[dict[str, object]] = []
    for row_seed in sidecar.SEEDS:
        checkpoint_path = tmp_path / f"checkpoint-{row_seed}.pt"
        checkpoint_bytes = f"checkpoint-{row_seed}".encode()
        checkpoint_path.write_bytes(checkpoint_bytes)
        training_path = tmp_path / f"training-{row_seed}.json"
        training_path.write_bytes(b"{}\n")
        training_rows.append(
            {
                "seed": row_seed,
                "status": "bound_complete",
                "source": {
                    "path": str(training_path),
                    "sha256": "1" * 64,
                    "bytes": training_path.stat().st_size,
                    "schema": "core.training.v1",
                },
                "evidence": {
                    "model_kind": "mlp",
                    "hidden": 16,
                    "updates": 500,
                    "run_id": f"f3-mlp500-hidden16-seed{row_seed}-20260928",
                    "evidence_status": "complete",
                    "formal_eligible": False,
                    "manifest_sha256": "2" * 64,
                    "checkpoint": {
                        "path": str(checkpoint_path),
                        "sha256": _sha_bytes(checkpoint_bytes),
                        "bytes": len(checkpoint_bytes),
                        "schema": "core.checkpoint.v1",
                        "update": 500,
                    },
                },
            }
        )
    matrix = {
        "schema": sidecar.TRAINING_SCHEMA,
        "source_bound": True,
        "diagnostic_only": True,
        **_zero_fields(),
        "shared_config": {"model_kind": "mlp", "hidden": 16, "updates": 500},
        "runs": training_rows,
    }
    _write_json(reports / sidecar.TRAINING_MATRIX_FILENAME, matrix)

    for row_seed in sidecar.SEEDS:
        row = next(row for row in training_rows if row["seed"] == row_seed)
        checkpoint = row["evidence"]["checkpoint"]
        history = {
            "schema": f"core.f3.mlp.hidden16.seed{row_seed}.full835_rollout_diagnostic.summary.v1",
            "status": "completed",
            "diagnostic_only": True,
            **_zero_fields(),
            "source": {"manifest": {"sha256": "3" * 64}},
            "protocol": {
                "model": "mlp",
                "seed": row_seed,
                "training_updates": 500,
                "hidden": 16,
                "case_id": sidecar.CASE_ID,
                "split": "test",
                "maximum_steps": 835,
                "diagnostic": True,
                "autonomous": True,
                "future_state_inputs": False,
            },
            "evaluation": {
                "status": "completed",
                "transitions_executed": 835,
                "trajectory_frames_including_initial": 836,
                "finite_rollout_complete": True,
                "future_state_inputs": False,
            },
            "checkpoint": checkpoint,
        }
        _write_json(reports / sidecar.HISTORY_FILENAME.format(seed=row_seed), history)

    paths["evaluation"].write_bytes(b"opaque evaluation bytes; intentionally not JSON")
    paths["trajectory"].write_bytes(b"opaque HDF5 bytes; intentionally not parsed")
    _write_json(paths["validator"], _validator_payload(paths))
    return root, seed, nonce, paths


def _cleanup(paths: dict[str, Path]) -> None:
    for path in paths.values():
        if path.is_symlink() or path.exists():
            path.unlink()


def test_build_identity_streams_three_fresh_artifacts_and_rejects_no_content_format(tmp_path: Path):
    root, seed, nonce, paths = _make_fixture(tmp_path)
    try:
        identity = sidecar.build_identity(root, seed=seed, nonce=nonce)
        assert identity["schema"] == f"core.f3.mlp.hidden16.seed{seed}.evaluator_artifact_identity.v1"
        assert identity["namespace"] == str(paths["namespace"])
        assert identity["diagnostic_only"] is True
        assert identity["credit"] == 0
        assert identity["evaluation"]["sha256"] == _sha_bytes(paths["evaluation"].read_bytes())
        assert identity["trajectory"]["bytes"] == paths["trajectory"].stat().st_size
        assert identity["validator"]["sha256"] == _sha_bytes(paths["validator"].read_bytes())
        assert sidecar.validate_identity(identity, root=root, seed=seed, nonce=nonce) == {
            key: identity[key] for key in ("checkpoint", "evaluation", "trajectory", "validator")
        }
    finally:
        _cleanup(paths)


def test_missing_fresh_artifact_is_blocked(tmp_path: Path):
    root, seed, nonce, paths = _make_fixture(tmp_path)
    paths["evaluation"].unlink()
    try:
        with pytest.raises(sidecar.SidecarError, match="evaluation_json"):
            sidecar.build_identity(root, seed=seed, nonce=nonce)
    finally:
        _cleanup(paths)


def test_canonical_path_drift_and_parent_traversal_are_blocked(tmp_path: Path):
    root, seed, nonce, paths = _make_fixture(tmp_path)
    try:
        with pytest.raises(sidecar.SidecarError, match="canonical fresh namespace"):
            sidecar.build_identity(root, seed=seed, nonce=nonce, evaluation_json=paths["evaluation"].with_name("other-evaluation.json"))
        with pytest.raises(sidecar.SidecarError, match="lexical path alias"):
            sidecar.build_identity(root, seed=seed, nonce=nonce, evaluation_json=Path("/tmp/../tmp") / paths["evaluation"].name)
    finally:
        _cleanup(paths)


def test_checkpoint_path_is_bound_to_training_matrix_for_validate_and_write(tmp_path: Path):
    root, seed, nonce, paths = _make_fixture(tmp_path)
    checkpoint = tmp_path / f"checkpoint-{seed}.pt"
    replacement = tmp_path / "replacement-checkpoint.pt"
    replacement.write_bytes(checkpoint.read_bytes())
    identity = sidecar.build_identity(root, seed=seed, nonce=nonce)
    try:
        drifted = json.loads(json.dumps(identity))
        drifted["checkpoint"]["path"] = str(replacement)
        with pytest.raises(sidecar.SidecarError, match="training-matrix checkpoint path"):
            sidecar.validate_identity(drifted, root=root, seed=seed, nonce=nonce)
        with pytest.raises(sidecar.SidecarError, match="training-matrix checkpoint path"):
            sidecar.write_identity(drifted, root=root, seed=seed, nonce=nonce)

        alias = json.loads(json.dumps(identity))
        alias["checkpoint"]["path"] = str(checkpoint.parent) + "/./" + checkpoint.name
        with pytest.raises(sidecar.SidecarError, match="lexical path alias"):
            sidecar.validate_identity(alias, root=root, seed=seed, nonce=nonce)

        traversal = json.loads(json.dumps(identity))
        traversal["checkpoint"]["path"] = str(checkpoint.parent) + "/../" + checkpoint.parent.name + "/" + checkpoint.name
        with pytest.raises(sidecar.SidecarError, match="lexical path alias"):
            sidecar.write_identity(traversal, root=root, seed=seed, nonce=nonce)
    finally:
        _cleanup(paths)


def test_checkpoint_symlink_and_hardlink_replacements_are_blocked(tmp_path: Path):
    root, seed, nonce, paths = _make_fixture(tmp_path)
    checkpoint = tmp_path / f"checkpoint-{seed}.pt"
    target = tmp_path / "checkpoint-replacement.pt"
    target.write_bytes(checkpoint.read_bytes())
    identity = sidecar.build_identity(root, seed=seed, nonce=nonce)
    try:
        checkpoint.unlink()
        checkpoint.symlink_to(target)
        with pytest.raises(sidecar.SidecarError, match="symlink"):
            sidecar.validate_identity(identity, root=root, seed=seed, nonce=nonce)
        checkpoint.unlink()

        os.link(target, checkpoint)
        with pytest.raises(sidecar.SidecarError, match="hardlink"):
            sidecar.write_identity(identity, root=root, seed=seed, nonce=nonce)
    finally:
        checkpoint.unlink(missing_ok=True)
        _cleanup(paths)


@pytest.mark.parametrize("nonce", ["0" * 32, "A" * 32, "a" * 31])
def test_zero_or_noncanonical_nonce_is_blocked(tmp_path: Path, nonce: str):
    root, _seed, _valid_nonce, _paths = _make_fixture(tmp_path)
    with pytest.raises(sidecar.SidecarError, match="namespace_nonce"):
        sidecar.build_identity(root, seed=17, nonce=nonce)


@pytest.mark.parametrize("mutation,pattern", [
    ("passed", "passed"),
    ("complete", "complete"),
    ("transitions", "expected_transitions"),
    ("frames", "trajectory_frames"),
    ("alias", "unknown fields|authority aliases"),
    ("path", "drifts from fresh namespace"),
])
def test_validator_drift_is_fail_closed(tmp_path: Path, mutation: str, pattern: str):
    root, seed, nonce, paths = _make_fixture(tmp_path)
    _write_json(paths["validator"], _validator_payload(paths, mutation=mutation))
    try:
        with pytest.raises(sidecar.SidecarError, match=pattern):
            sidecar.build_identity(root, seed=seed, nonce=nonce)
    finally:
        _cleanup(paths)


def test_symlink_and_hardlink_inputs_are_rejected(tmp_path: Path):
    root, seed, nonce, paths = _make_fixture(tmp_path)
    target = tmp_path / "evaluation-target.bin"
    target.write_bytes(b"target")
    paths["evaluation"].unlink()
    paths["evaluation"].symlink_to(target)
    try:
        with pytest.raises(sidecar.SidecarError, match="symlink"):
            sidecar.build_identity(root, seed=seed, nonce=nonce)
    finally:
        _cleanup(paths)

    root, seed, nonce, paths = _make_fixture(tmp_path, nonce=hashlib.sha256(b"hardlink").hexdigest()[:32])
    alias = tmp_path / "evaluation-hardlink-alias.bin"
    try:
        os.link(paths["evaluation"], alias)
        with pytest.raises(sidecar.SidecarError, match="hardlink"):
            sidecar.build_identity(root, seed=seed, nonce=nonce)
    finally:
        alias.unlink(missing_ok=True)
        _cleanup(paths)


def test_hash_and_bytes_drift_is_detected_by_identity_revalidation(tmp_path: Path):
    root, seed, nonce, paths = _make_fixture(tmp_path)
    try:
        identity = sidecar.build_identity(root, seed=seed, nonce=nonce)
        paths["trajectory"].write_bytes(paths["trajectory"].read_bytes() + b"drift")
        with pytest.raises(sidecar.SidecarError, match="identity.trajectory.(sha256|bytes) drift"):
            sidecar.validate_identity(identity, root=root, seed=seed, nonce=nonce)
    finally:
        _cleanup(paths)


def test_default_cli_is_dry_run_and_write_is_canonical_only(tmp_path: Path, capsys):
    root, seed, nonce, paths = _make_fixture(tmp_path)
    try:
        assert sidecar.main(["--root", str(root), "--seed", str(seed), "--nonce", nonce]) == 0
        dry_run = json.loads(capsys.readouterr().out)
        assert dry_run["status"] == "dry_run_ready"
        assert not paths["sidecar"].exists()
        assert sidecar.main(["--root", str(root), "--seed", str(seed), "--nonce", nonce, "--write"]) == 0
        written = json.loads(capsys.readouterr().out)
        assert written["status"] == "written"
        assert json.loads(paths["sidecar"].read_text(encoding="utf-8")) == written["identity"]
        with pytest.raises(sidecar.SidecarError, match="overwrite"):
            sidecar.write_identity(written["identity"], root=root, seed=seed, nonce=nonce)
    finally:
        _cleanup(paths)
