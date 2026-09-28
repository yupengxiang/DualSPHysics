"""Bounded post-terminal process-proof normalizer tests."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from scripts import f3_graph_residual_hidden16_process_exit_proof_builder_v1 as builder
from scripts import f3_graph_residual_hidden16_terminal_runtime_verifier_v1 as verifier


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_bytes((builder.canonical_json(value) + "\n").encode("utf-8"))


def _attestation(path: Path, digest: str, byte_count: int) -> dict[str, object]:
    producer = {
        "role": "producer",
        "identity": f"producer:{path.name}",
        "source": "producer_receipt",
        "independent": False,
        "artifact_path": str(path),
        "artifact_sha256": digest,
        "artifact_bytes": byte_count,
    }
    producer["binding_sha256"] = builder._canonical_digest(producer)
    validator = {
        "role": "validator",
        "identity": f"validator:{path.name}",
        "source": "independent_validator_receipt",
        "independent": True,
        "artifact_path": str(path),
        "artifact_sha256": digest,
        "artifact_bytes": byte_count,
    }
    validator["binding_sha256"] = builder._canonical_digest(validator)
    binding = {
        "schema": builder.ARTIFACT_ATTESTATION_SCHEMA,
        "mode": builder.ARTIFACT_ATTESTATION_MODE,
        "artifact_path": str(path),
        "artifact_sha256": digest,
        "artifact_bytes": byte_count,
        "producer_binding_sha256": producer["binding_sha256"],
        "validator_binding_sha256": validator["binding_sha256"],
        "producer": producer,
        "validator": validator,
    }
    # The builder's outer digest excludes the full role records and binds only
    # their independently recomputed binding digests.
    binding["binding_sha256"] = builder._canonical_digest(
        {
            "schema": builder.ARTIFACT_ATTESTATION_SCHEMA,
            "mode": builder.ARTIFACT_ATTESTATION_MODE,
            "artifact_path": str(path),
            "artifact_sha256": digest,
            "artifact_bytes": byte_count,
            "producer_binding_sha256": producer["binding_sha256"],
            "validator_binding_sha256": validator["binding_sha256"],
        }
    )
    return binding


def _write_artifact(path: Path, content: bytes) -> dict[str, object]:
    path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    return {
        "path": str(path),
        "sha256": digest,
        "bytes": len(content),
        "content_opened": False,
        "stat_only": True,
        "attestation": _attestation(path, digest, len(content)),
    }


def _observation(root: Path, *, seed: int = 17, nonce: str = "17" * 16) -> dict[str, object]:
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    run_id = f"f3-graph-residual500-hidden16-seed{seed}-20260928"
    namespace = artifacts / f"f3-graph-residual500-hidden16-seed{seed}-full835-nonce{nonce}"
    checkpoint = _write_artifact(artifacts / f"{run_id}-checkpoint.pt", b"checkpoint")
    training = _write_artifact(artifacts / f"{run_id}-training.json", b"training")
    trajectory = _write_artifact(Path(str(namespace) + "-trajectory.h5"), b"trajectory")
    evaluation = _write_artifact(Path(str(namespace) + "-evaluation.json"), b"evaluation")
    evaluator_command = [
        builder.CANONICAL_INTERPRETER,
        builder.CANONICAL_CORE_LEARNING,
        "evaluate",
        "--manifest",
        "campaigns/core-v1/f3-dataset-v2.json",
        "--data-root",
        ".",
        "--checkpoint",
        checkpoint["path"],
        "--case-id",
        builder.CASE_ID,
        "--split",
        builder.SPLIT,
        "--maximum-steps",
        str(builder.TRANSITIONS),
        "--chunk-size",
        "34560",
        "--device",
        "cuda:0",
        "--progress-every",
        "25",
        "--trajectory-output",
        trajectory["path"],
        "--progress-output",
        str(namespace) + "-evaluation-progress.json",
        "--output",
        evaluation["path"],
        "--diagnostic",
    ]
    launcher_command = ["/usr/bin/env", "PYTHONDONTWRITEBYTECODE=1", *evaluator_command]
    return {
        "schema": builder.INPUT_SCHEMA,
        "report_id": builder.INPUT_REPORT_ID,
        "status": "post_terminal_observed",
        "seed": seed,
        "run_id": run_id,
        "namespace": str(namespace),
        "namespace_nonce": nonce,
        "model_kind": builder.MODEL_KIND,
        "hidden": builder.HIDDEN,
        "updates": builder.UPDATES,
        "case_id": builder.CASE_ID,
        "split": builder.SPLIT,
        "transitions": builder.TRANSITIONS,
        "frames": builder.FRAMES,
        "manifest_sha256": _sha("dataset-v2-manifest"),
        "training_receipt": training,
        "checkpoint": checkpoint,
        "trajectory": trajectory,
        "evaluation_artifact": evaluation,
        "process": {
            "evaluator": {
                "alive": False,
                "returncode": 0,
                "reaped": True,
                "command": evaluator_command,
                "command_sha256": builder._command_sha256(evaluator_command),
            },
            "launcher": {
                "alive": False,
                "returncode": 0,
                "reaped": True,
                "command": launcher_command,
                "command_sha256": builder._command_sha256(launcher_command),
            },
        },
        "exit_observation": {"natural_exit": True, "observed_after_exit": True},
    }


def test_positive_normalization_matches_the_existing_strict_verifier(tmp_path: Path) -> None:
    payload = _observation(tmp_path)
    envelope = builder.build_envelope(payload)

    assert envelope["schema"] == "core.f3.graph_residual.hidden16.seed17.process_exit_proof.v1"
    assert envelope["status"] == "exited_successfully"
    assert envelope["credit"] == 0
    assert envelope["command_binding"]["evaluator"]["argv"] == payload["process"]["evaluator"]["command"]  # type: ignore[index]
    assert envelope["command_binding"]["evaluator"]["sha256"] == builder._command_sha256(envelope["command_binding"]["evaluator"]["argv"])
    assert envelope["command_sha256"] == envelope["command_binding"]["evaluator"]["sha256"]
    assert envelope["launcher_command_sha256"] == envelope["command_binding"]["launcher"]["sha256"]
    assert builder.validate_envelope(envelope) == []
    assert "pid" not in builder.canonical_json(envelope).lower()
    assert verifier._validate_process(
        builder._legacy_verifier_projection(envelope),
        17,
        "synthetic normalized proof",
    )["returncode"] == 0


def test_default_is_blocked_and_reports_writer_only_publishes_that_sample(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "reports").mkdir(parents=True)
    report = builder.build_default_blocked_report()
    assert report["status"] == "blocked_fail_closed"
    assert report["source_bound"] is False
    assert report["process_exit_proof"] is None
    assert builder.validate_blocked_report(report) == []

    output = builder.write_default_blocked_report(root)
    assert output == root / "reports" / builder.DEFAULT_BLOCKED_FILENAME
    assert builder.validate_blocked_report(json.loads(output.read_text(encoding="utf-8"))) == []

    with pytest.raises(builder.BuilderError, match="only reports output"):
        builder.write_default_blocked_report(root, root / "reports" / "positive.json")


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("process", "pid", 123),
        ("process", "formal_claim", False),
        ("process", "credit_points", 0),
        ("top", "process_id", 123),
    ],
)
def test_pid_formal_and_credit_aliases_fail_closed(tmp_path: Path, section: str, field: str, value: object) -> None:
    payload = _observation(tmp_path)
    if section == "process":
        payload["process"]["evaluator"][field] = value  # type: ignore[index]
    else:
        payload[field] = value
    with pytest.raises(builder.BuilderError, match="forbidden PID/formal/credit alias"):
        builder.build_envelope(payload)


@pytest.mark.parametrize(
    ("component", "field", "value"),
    [
        ("evaluator", "alive", True),
        ("evaluator", "returncode", 1),
        ("launcher", "reaped", False),
    ],
)
def test_nonterminal_or_nonzero_process_observations_fail_closed(tmp_path: Path, component: str, field: str, value: object) -> None:
    payload = _observation(tmp_path)
    payload["process"][component][field] = value  # type: ignore[index]
    with pytest.raises(builder.BuilderError):
        builder.build_envelope(payload)


def test_all_zero_namespace_nonce_is_rejected(tmp_path: Path) -> None:
    payload = _observation(tmp_path, nonce="0" * 32)
    with pytest.raises(builder.BuilderError, match="namespace_nonce must be non-zero"):
        builder.build_envelope(payload)


def test_command_identity_and_fixed_contract_are_checked(tmp_path: Path) -> None:
    payload = _observation(tmp_path)
    payload["process"]["evaluator"]["command"][payload["process"]["evaluator"]["command"].index("835")] = "834"  # type: ignore[index]
    payload["process"]["evaluator"]["command_sha256"] = builder._command_sha256(payload["process"]["evaluator"]["command"])  # type: ignore[index]
    with pytest.raises(builder.BuilderError, match="canonical evaluator argv|token/flag/path drift"):
        builder.build_envelope(payload)

    payload = _observation(tmp_path / "second")
    payload["namespace"] = str(Path(payload["namespace"]).parent / "../unsafe")  # type: ignore[index]
    with pytest.raises(builder.BuilderError, match="traversal"):
        builder.build_envelope(payload)


@pytest.mark.parametrize("artifact_key", ["checkpoint", "trajectory", "evaluation_artifact", "training_receipt"])
def test_symlink_and_hardlink_artifact_metadata_are_rejected(tmp_path: Path, artifact_key: str) -> None:
    payload = _observation(tmp_path)
    original = Path(payload[artifact_key]["path"])  # type: ignore[index]
    if artifact_key == "trajectory":
        target = tmp_path / "symlink-target.bin"
        target.write_bytes(original.read_bytes())
        original.unlink()
        original.symlink_to(target)
        expected = "symlink"
    else:
        hardlink = tmp_path / f"{artifact_key}-hardlink.bin"
        os.link(original, hardlink)
        expected = "hard-linked"
    with pytest.raises(builder.BuilderError, match=expected):
        builder.build_envelope(payload)


def test_input_json_reader_rejects_traversal_symlink_and_hardlink(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    payload = {"schema": builder.INPUT_SCHEMA}
    real = root / "post_terminal_observation.json"
    _write_json(real, payload)
    assert builder.load_observation(root, real)["schema"] == builder.INPUT_SCHEMA

    link = root / "observation-link.json"
    link.symlink_to(real)
    with pytest.raises(builder.BuilderError, match="symlink"):
        builder.load_observation(root, link)

    hardlink = root / "observation-hardlink.json"
    os.link(real, hardlink)
    with pytest.raises(builder.BuilderError, match="hard-linked"):
        builder.load_observation(root, hardlink)

    with pytest.raises(builder.BuilderError, match="traversal|escapes"):
        builder.load_observation(root, Path("../post_terminal_observation.json"))


def test_artifact_content_is_never_opened_and_positive_reports_are_forbidden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _observation(tmp_path)
    real_open = builder.os.open
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    calls: list[tuple[object, int]] = []

    def guarded_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
        calls.append((path, flags))
        if directory_flag and not (flags & directory_flag):
            raise AssertionError("builder attempted to open a non-directory artifact")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(builder.os, "open", guarded_open)
    envelope = builder.build_envelope(payload)
    assert envelope["trajectory"]["path"].endswith("-trajectory.h5")
    assert calls

    root = tmp_path / "root"
    (root / "reports").mkdir(parents=True)
    with pytest.raises(builder.BuilderError, match="below reports"):
        builder.write_normalized_envelope(root, root / "reports" / "proof.json", envelope)


def test_bounded_json_duplicate_and_nonfinite_values_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    duplicate = root / "duplicate.json"
    duplicate.write_bytes(b'{"schema":"x","schema":"y"}\n')
    with pytest.raises(builder.BuilderError, match="duplicate JSON"):
        builder.load_observation(root, duplicate)
    nonfinite = root / "nonfinite.json"
    nonfinite.write_bytes(b'{"schema":NaN}\n')
    with pytest.raises(builder.BuilderError, match="non-finite"):
        builder.load_observation(root, nonfinite)


def test_writer_refuses_symlink_and_hardlink_outputs(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "reports").mkdir(parents=True)
    envelope = builder.build_envelope(_observation(tmp_path / "artifacts"))
    target = root / "sentinel.json"
    target.write_text("sentinel", encoding="utf-8")
    output = root / "proof.json"
    output.symlink_to(target)
    with pytest.raises(builder.BuilderError, match="symlink"):
        builder.write_normalized_envelope(root, output, envelope)
    output.unlink()
    os.link(target, output)
    with pytest.raises(builder.BuilderError, match="hard-linked"):
        builder.write_normalized_envelope(root, output, envelope)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload["process"]["evaluator"]["command"].__setitem__(0, "/tmp/python"),
        lambda payload: payload["process"]["evaluator"]["command"].__setitem__(1, "/tmp/else/core_learning.py"),
        lambda payload: payload["process"]["evaluator"]["command"].__setitem__(4, "wrong-manifest.json"),
        lambda payload: payload["process"]["evaluator"]["command"].__setitem__(14, "834"),
        lambda payload: payload["process"]["evaluator"]["command"].__setitem__(16, "34561"),
        lambda payload: payload["process"]["evaluator"]["command"].__setitem__(26, "/tmp/other-evaluation.json"),
    ],
)
def test_canonical_evaluator_rejects_interpreter_script_flag_and_path_drift(tmp_path: Path, mutator) -> None:
    payload = _observation(tmp_path)
    mutator(payload)
    payload["process"]["evaluator"]["command_sha256"] = builder._command_sha256(payload["process"]["evaluator"]["command"])  # type: ignore[index]
    with pytest.raises(builder.BuilderError, match="canonical evaluator argv|token/flag/path drift"):
        builder.build_envelope(payload)


def test_suspicious_launcher_is_rejected_even_when_it_has_the_evaluator_as_a_suffix(tmp_path: Path) -> None:
    payload = _observation(tmp_path)
    evaluator = payload["process"]["evaluator"]["command"]  # type: ignore[index]
    launcher = ["/bin/sh", "-c", "exec", *evaluator]
    payload["process"]["launcher"]["command"] = launcher  # type: ignore[index]
    payload["process"]["launcher"]["command_sha256"] = builder._command_sha256(launcher)  # type: ignore[index]
    with pytest.raises(builder.BuilderError, match="suspicious launcher"):
        builder.build_envelope(payload)


def test_command_binding_is_revalidated_after_normalization(tmp_path: Path) -> None:
    envelope = builder.build_envelope(_observation(tmp_path))
    envelope["command_binding"]["evaluator"]["argv"][-1] = "--not-diagnostic"  # type: ignore[index]
    assert builder.validate_envelope(envelope)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda artifact: artifact.pop("attestation"),
        lambda artifact: artifact["attestation"]["validator"].__setitem__("artifact_sha256", "0" * 64),
        lambda artifact: artifact["attestation"].__setitem__("binding_sha256", "0" * 64),
    ],
)
def test_missing_or_inconsistent_artifact_attestation_fails_closed(tmp_path: Path, mutation) -> None:
    payload = _observation(tmp_path)
    mutation(payload["checkpoint"])  # type: ignore[index]
    with pytest.raises(builder.BuilderError, match="attestation|binding"):
        builder.build_envelope(payload)
