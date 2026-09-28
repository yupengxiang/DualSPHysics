"""Synthetic/bounded safety tests for the terminal artifact validator contract."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from scripts import f3_graph_raw_hidden16_current_manifest_terminal_artifact_validator_v1 as validator


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _artifact(path: Path, payload: bytes) -> dict[str, object]:
    path.write_bytes(payload)
    return {"path": str(path), "sha256": _sha_bytes(payload), "bytes": len(payload)}


def _proof(kind: str) -> dict[str, object]:
    core: dict[str, object] = {
        "schema": validator.PROOF_SCHEMA,
        "kind": kind,
        "status": "synthetic_fixture_only",
        "source_bound": True,
        "synthetic_only": True,
        "real_proof": False,
    }
    return {**core, "proof_sha256": validator.canonical_digest(core)}


def _terminal(identity: dict[str, object]) -> dict[str, object]:
    core: dict[str, object] = {
        "schema": validator.TERMINAL_IDENTITY_SCHEMA,
        "status": "completed",
        "model_kind": identity["model_kind"],
        "hidden": identity["hidden"],
        "seed": identity["seed"],
        "case_id": identity["case_id"],
        "split": identity["split"],
        "transitions": identity["transitions"],
        "frames": identity["frames"],
        "frames_executed": validator.FRAMES,
        "trajectory_transitions": validator.TRANSITIONS,
        "trajectory_frames": validator.FRAMES,
        "terminal": True,
        "execution_complete": True,
        "finite_rollout_complete": True,
        "future_state_inputs": False,
        "source_bound": True,
        "synthetic_only": True,
        "producer_proof": _proof("producer"),
        "terminal_proof": _proof("terminal"),
    }
    return {**core, "identity_sha256": validator.canonical_digest(core)}


def _refresh_validator_metadata(metadata: dict[str, object]) -> None:
    artifacts = metadata["artifacts"]
    trajectory = artifacts["trajectory"]
    independent = metadata["validator_metadata"]
    independent["artifact"] = copy.deepcopy(trajectory)
    observed = independent["observed"]
    identity = metadata["identity"]
    for key in ("model_kind", "hidden", "seed", "case_id", "split", "transitions", "frames", "nonce"):
        observed[key] = identity[key]
    observed["trajectory_sha256"] = trajectory["sha256"]
    observed["trajectory_bytes"] = trajectory["bytes"]
    observed["terminal_identity_sha256"] = metadata["terminal_identity"]["identity_sha256"]
    independent_core = dict(independent)
    independent_core.pop("metadata_sha256", None)
    independent["metadata_sha256"] = validator.canonical_digest(independent_core)


def _fixture(tmp_path: Path, *, seed: int = 17) -> tuple[Path, Path, dict[str, object]]:
    root = tmp_path / "synthetic-fixture"
    root.mkdir()
    (root / validator.SYNTHETIC_MARKER_NAME).write_text(
        validator.SYNTHETIC_MARKER_CONTENT, encoding="utf-8"
    )
    nonce = f"{seed:032x}"
    identity = {
        "model_kind": validator.MODEL_KIND,
        "hidden": validator.HIDDEN,
        "seed": seed,
        "case_id": validator.CASE_ID,
        "split": validator.SPLIT,
        "transitions": validator.TRANSITIONS,
        "frames": validator.FRAMES,
        "nonce": nonce,
        "run_id": validator.RUN_ID_TEMPLATE.format(seed=seed),
        "namespace": str(root / validator.NAMESPACE_TEMPLATE.format(seed=seed, nonce=nonce)),
    }
    trajectory = root / "synthetic-terminal-trajectory.h5"
    frames = validator.FRAMES
    particles = 2
    with h5py.File(trajectory, "w") as handle:
        handle.create_dataset("time", data=np.arange(frames, dtype=np.float64))
        handle.create_dataset(
            "position",
            data=np.zeros((frames, particles, 3), dtype=np.float32),
        )
        handle.create_dataset(
            "velocity",
            data=np.ones((frames, particles, 3), dtype=np.float32),
        )
        handle.create_dataset("particle_id", data=np.arange(particles, dtype=np.int64))
        handle.create_dataset("particle_zone", data=np.zeros(particles, dtype=np.int64))
        handle.create_dataset("mass", data=np.ones(particles, dtype=np.float64))
        handle.create_dataset("valid", data=np.ones((frames, particles), dtype=np.uint8))
        for key, value in (
            ("model_kind", identity["model_kind"]),
            ("case_id", identity["case_id"]),
            ("split", identity["split"]),
            ("seed", identity["seed"]),
            ("transitions", validator.TRANSITIONS),
            ("frames", validator.FRAMES),
            ("nonce", identity["nonce"]),
            ("future_state_inputs", False),
            ("autonomous_prediction", True),
            ("synthetic_fixture", True),
            ("terminal", True),
            ("execution_complete", True),
            ("finite_rollout_complete", True),
        ):
            handle.attrs[key] = value

    artifacts = {
        "manifest": _artifact(root / "manifest.json", b"synthetic manifest\n"),
        "training_receipt": _artifact(root / "training.json", b"synthetic training receipt\n"),
        "checkpoint": _artifact(root / "checkpoint.pt", b"synthetic checkpoint\n"),
        "evaluation_artifact": _artifact(root / "evaluation.json", b"synthetic evaluation\n"),
        "trajectory": {
            "path": str(trajectory),
            "sha256": _sha_bytes(trajectory.read_bytes()),
            "bytes": trajectory.stat().st_size,
        },
    }
    terminal_identity = _terminal(identity)
    validator_core: dict[str, object] = {
        "schema": validator.VALIDATOR_METADATA_SCHEMA,
        "producer_id": "independent-synthetic-hdf5-validator-v1",
        "producer_version": "synthetic-bounded-v1",
        "independent": True,
        "source_bound": True,
        "synthetic_only": True,
        "artifact": copy.deepcopy(artifacts["trajectory"]),
        "observed": {
            "model_kind": identity["model_kind"],
            "hidden": identity["hidden"],
            "seed": identity["seed"],
            "case_id": identity["case_id"],
            "split": identity["split"],
            "transitions": identity["transitions"],
            "frames": identity["frames"],
            "nonce": identity["nonce"],
            "trajectory_sha256": artifacts["trajectory"]["sha256"],
            "trajectory_bytes": artifacts["trajectory"]["bytes"],
            "terminal_identity_sha256": terminal_identity["identity_sha256"],
        },
    }
    validator_metadata = {
        **validator_core,
        "metadata_sha256": validator.canonical_digest(validator_core),
    }
    metadata: dict[str, object] = {
        "schema": validator.INPUT_SCHEMA,
        "identity": identity,
        "artifacts": artifacts,
        "terminal_identity": terminal_identity,
        "validator_metadata": validator_metadata,
    }
    return root, trajectory, metadata


def test_default_report_is_blocked_and_zero_credit() -> None:
    report = validator.build_report()
    assert report["status"] == "blocked_fail_closed"
    assert report["launch_allowed"] is False
    assert report["capability_admitted"] is False
    assert report["credit"] == 0
    assert validator.validate_report(report) == []


def test_synthetic_hdf5_is_structurally_observed_but_never_authorizes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, trajectory, metadata = _fixture(tmp_path)
    real_file = validator.h5py.File
    opened: list[Path] = []

    def guarded_file(path: object, *args: object, **kwargs: object):
        opened.append(Path(path))
        assert Path(path) == trajectory
        return real_file(path, *args, **kwargs)

    monkeypatch.setattr(validator.h5py, "File", guarded_file)
    report = validator.build_report(metadata, trajectory_hdf5=trajectory, fixture_root=root)
    assert opened == [trajectory]
    assert report["hdf5_validation"]["status"] == "validated_bounded_synthetic"
    assert report["hdf5_validation"]["transitions"] == validator.TRANSITIONS
    assert report["hdf5_validation"]["frames"] == validator.FRAMES
    assert report["terminal_identity_bound"] is True
    assert report["independent_validator_metadata_bound"] is True
    assert report["real_producer_proof"] is False
    assert report["real_terminal_proof"] is False
    assert report["launch_allowed"] is False
    assert report["credit"] == 0
    assert validator.validate_report(report) == []


def test_missing_producer_proof_fails_before_hdf5_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, trajectory, metadata = _fixture(tmp_path)
    del metadata["terminal_identity"]["producer_proof"]
    monkeypatch.setattr(
        validator.h5py,
        "File",
        lambda *args, **kwargs: pytest.fail("HDF5 must not open when producer proof is missing"),
    )
    report = validator.build_report(metadata, trajectory_hdf5=trajectory, fixture_root=root)
    assert report["hdf5_validation"]["status"] == "not_run"
    assert any("producer_proof" in reason for reason in report["blocked_reasons"])
    assert report["launch_allowed"] is False


def test_missing_terminal_proof_fails_closed_before_hdf5_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, trajectory, metadata = _fixture(tmp_path)
    del metadata["terminal_identity"]["terminal_proof"]
    monkeypatch.setattr(
        validator.h5py,
        "File",
        lambda *args, **kwargs: pytest.fail("HDF5 must not open when terminal proof is missing"),
    )
    report = validator.build_report(metadata, trajectory_hdf5=trajectory, fixture_root=root)
    assert report["hdf5_validation"]["status"] == "not_run"
    assert any("terminal_proof" in reason for reason in report["blocked_reasons"])


def test_missing_independent_validator_metadata_fails_closed_before_hdf5_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, trajectory, metadata = _fixture(tmp_path)
    del metadata["validator_metadata"]
    monkeypatch.setattr(
        validator.h5py,
        "File",
        lambda *args, **kwargs: pytest.fail("HDF5 must not open without independent metadata"),
    )
    report = validator.build_report(metadata, trajectory_hdf5=trajectory, fixture_root=root)
    assert report["hdf5_validation"]["status"] == "not_run"
    assert any("validator_metadata" in reason for reason in report["blocked_reasons"])


def test_validator_metadata_digest_drift_fails_closed(tmp_path: Path) -> None:
    root, trajectory, metadata = _fixture(tmp_path)
    metadata["validator_metadata"]["metadata_sha256"] = "a" * 64
    report = validator.build_report(metadata, trajectory_hdf5=trajectory, fixture_root=root)
    assert report["hdf5_validation"]["status"] == "not_run"
    assert any("metadata_sha256" in reason for reason in report["blocked_reasons"])


def test_hdf5_outside_marked_fixture_is_never_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, trajectory, metadata = _fixture(tmp_path)
    outside = tmp_path / "outside" / "production-looking-trajectory.h5"
    outside.parent.mkdir()
    outside.write_bytes(trajectory.read_bytes())
    metadata["artifacts"]["trajectory"] = {
        "path": str(outside),
        "sha256": _sha_bytes(outside.read_bytes()),
        "bytes": outside.stat().st_size,
    }
    _refresh_validator_metadata(metadata)
    monkeypatch.setattr(
        validator.h5py,
        "File",
        lambda *args, **kwargs: pytest.fail("outside HDF5 must not be opened"),
    )
    report = validator.build_report(metadata, trajectory_hdf5=outside, fixture_root=root)
    assert report["hdf5_validation"]["status"] == "not_run"
    assert any("inside the marked synthetic fixture root" in reason for reason in report["blocked_reasons"])


def test_fixture_without_exact_marker_is_rejected_before_hdf5_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, trajectory, metadata = _fixture(tmp_path)
    (root / validator.SYNTHETIC_MARKER_NAME).unlink()
    monkeypatch.setattr(
        validator.h5py,
        "File",
        lambda *args, **kwargs: pytest.fail("unmarked HDF5 must not be opened"),
    )
    report = validator.build_report(metadata, trajectory_hdf5=trajectory, fixture_root=root)
    assert report["hdf5_validation"]["status"] == "not_run"
    assert any("marker" in reason for reason in report["blocked_reasons"])


def test_trajectory_sha_or_bytes_drift_fails_closed(tmp_path: Path) -> None:
    root, trajectory, metadata = _fixture(tmp_path)
    trajectory.write_bytes(trajectory.read_bytes() + b"drift")
    report = validator.build_report(metadata, trajectory_hdf5=trajectory, fixture_root=root)
    assert report["hdf5_validation"]["status"] == "not_run"
    assert any("bytes" in reason or "SHA-256" in reason for reason in report["blocked_reasons"])


def test_hdf5_attribute_drift_is_detected_after_identity_rebind(tmp_path: Path) -> None:
    root, trajectory, metadata = _fixture(tmp_path)
    with h5py.File(trajectory, "r+") as handle:
        handle.attrs["case_id"] = "wrong-case"
    metadata["artifacts"]["trajectory"] = {
        "path": str(trajectory),
        "sha256": _sha_bytes(trajectory.read_bytes()),
        "bytes": trajectory.stat().st_size,
    }
    _refresh_validator_metadata(metadata)
    report = validator.build_report(metadata, trajectory_hdf5=trajectory, fixture_root=root)
    assert report["hdf5_validation"]["status"] == "not_run"
    assert any("case_id" in reason for reason in report["blocked_reasons"])


def test_identity_nonce_drift_cannot_be_self_consistent_without_all_bindings(tmp_path: Path) -> None:
    root, trajectory, metadata = _fixture(tmp_path)
    metadata["identity"]["nonce"] = "b" * 32
    report = validator.build_report(metadata, trajectory_hdf5=trajectory, fixture_root=root)
    assert report["hdf5_validation"]["status"] == "not_run"
    assert any("namespace" in reason or "terminal_identity" in reason for reason in report["blocked_reasons"])


def test_synthetic_real_proof_claim_is_rejected(tmp_path: Path) -> None:
    root, trajectory, metadata = _fixture(tmp_path)
    proof = metadata["terminal_identity"]["producer_proof"]
    proof["real_proof"] = True
    proof["synthetic_only"] = False
    proof_core = dict(proof)
    proof_core.pop("proof_sha256")
    proof["proof_sha256"] = validator.canonical_digest(proof_core)
    report = validator.build_report(metadata, trajectory_hdf5=trajectory, fixture_root=root)
    assert report["hdf5_validation"]["status"] == "not_run"
    assert any("synthetic_only" in reason or "real_proof" in reason for reason in report["blocked_reasons"])


def test_report_validator_rejects_forged_launch_or_credit(tmp_path: Path) -> None:
    report = validator.build_report()
    forged = copy.deepcopy(report)
    forged["launch_allowed"] = True
    assert validator.validate_report(forged)
    forged = copy.deepcopy(report)
    forged["credit"] = 1
    assert validator.validate_report(forged)


def test_cli_verifies_a_bounded_zero_credit_report(tmp_path: Path) -> None:
    report = validator.build_report()
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")
    assert validator.main(["--verify-report", str(report_path)]) == 0


def test_cli_runs_only_against_explicit_synthetic_fixture(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, trajectory, metadata = _fixture(tmp_path)
    metadata_path = root / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, sort_keys=True) + "\n", encoding="utf-8")
    report_path = tmp_path / "cli-report.json"
    assert validator.main(
        [
            "--metadata",
            str(metadata_path),
            "--fixture-root",
            str(root),
            "--trajectory",
            str(trajectory),
            "--report-output",
            str(report_path),
        ]
    ) == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["hdf5_validation"]["status"] == "validated_bounded_synthetic"
    assert report["launch_allowed"] is False
    assert report["credit"] == 0
    assert "synthetic" in capsys.readouterr().out
