from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from scripts import f8_r008_target_kernel_evidence_intake_v1 as intake


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha1(raw: bytes) -> str:
    return hashlib.sha1(raw).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, dict]:
    source = b"external target source-tree evidence\n"
    uapi = b"external target uapi evidence\n"
    config = (
        b"CONFIG_FANOTIFY=y\n"
        b"CONFIG_FANOTIFY_ACCESS_PERMISSIONS=y\n"
        b"CONFIG_SECCOMP=y\n"
        b"CONFIG_SECCOMP_FILTER=y\n"
        b"# CONFIG_X86_X32_ABI is not set\n"
    )
    build = b"external target build provenance evidence\n"
    files = {
        "source": ("source.bin", source),
        "uapi": ("uapi.bin", uapi),
        "config": ("target.config", config),
        "build": ("build.provenance", build),
    }
    for name, raw in files.values():
        (tmp_path / name).write_bytes(raw)

    options = [
        {"name": name, "value": value}
        for name, value in sorted(intake.REQUIRED_OPTION_VALUES.items())
    ]
    manifest = {
        "schema": intake.MANIFEST_SCHEMA,
        "record_id": intake.MANIFEST_RECORD_ID,
        "evidence_origin": intake.MANIFEST_ORIGIN,
        "synthetic": False,
        "target": {
            "kernel_release": "6.8.0-target.20260928",
            "source_commit": _sha1(b"real target source commit"),
            "source_tree_sha256": _sha256(source),
            "uapi_sha256": _sha256(uapi),
            "build_id": _sha1(b"real target build id"),
            "config_sha256": _sha256(config),
            "required_options": options,
        },
        "artifacts": {
            role: {"path": name, "bytes": len(raw), "sha256": _sha256(raw)}
            for role, (name, raw) in files.items()
        },
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    return path, manifest


def _rewrite(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def test_missing_default_external_evidence_is_blocked_and_zero_credit() -> None:
    report = intake.build_report(Path("external/definitely-missing-f8-target-evidence.json"))

    assert report["status"] == intake.STATUS_BLOCKED_MISSING
    assert report["validation"]["external_target_evidence_complete"] is False
    assert all(value is False for value in report["pins"].values())
    assert report["authorization"]["readiness_pass"] is False
    assert report["authorization"]["T1_numerical"] is False
    assert report["authorization"]["qualification_credit"] == 0
    assert report["side_effects"] == intake._side_effects()


def test_complete_external_manifest_binds_all_four_artifacts_without_authority(tmp_path: Path) -> None:
    manifest_path, _ = _fixture(tmp_path)

    result = intake.intake_manifest(manifest_path)
    report = intake.build_report(manifest_path)
    intake._validate_report(report)

    assert result["target"]["kernel_release"] == "6.8.0-target.20260928"
    assert report["status"] == intake.STATUS_VALID_NON_AUTHORIZING
    assert report["validation"]["external_target_evidence_complete"] is True
    assert all(report["pins"].values())
    assert all(report["artifacts"][role]["verified"] for role in intake.ARTIFACT_ROLES)
    assert report["authorization"]["readiness_pass"] is False
    assert report["authorization"]["T1_numerical"] is False
    assert report["authorization"]["qualification_credit"] == 0
    assert report["side_effects"] == intake._side_effects()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda value: value["target"].update(source_tree_sha256="a" * 64),
            "synthetic/placeholder digest",
        ),
        (
            lambda value: value["target"].update(kernel_release="v6.8"),
            "upstream v6.8 tag",
        ),
        (
            lambda value: value["artifacts"]["source"].update(path="../source.bin"),
            "canonical relative reference",
        ),
        (
            lambda value: value["artifacts"]["uapi"].update(path="source.bin"),
            "paths must be distinct",
        ),
        (
            lambda value: value["target"]["required_options"].append(
                {"name": "CONFIG_EXTRA", "value": "y"}
            ),
            "sorted and unique",
        ),
    ],
)
def test_manifest_rejects_identity_path_and_duplicate_declarations(
    tmp_path: Path,
    mutate,
    message: str,
) -> None:
    manifest_path, manifest = _fixture(tmp_path)
    mutate(manifest)
    _rewrite(manifest_path, manifest)

    with pytest.raises(intake.TargetKernelEvidenceIntakeError, match=message):
        intake.intake_manifest(manifest_path)


def test_missing_artifact_is_partial_evidence_and_cannot_be_promoted(tmp_path: Path) -> None:
    manifest_path, manifest = _fixture(tmp_path)
    os.unlink(tmp_path / "build.provenance")

    with pytest.raises(intake.TargetKernelEvidenceIntakeError, match="build evidence artifact is missing"):
        intake.intake_manifest(manifest_path)
    report = intake.build_report(manifest_path)
    assert report["status"] == intake.STATUS_BLOCKED_MISSING
    assert report["manifest"]["exists"] is True
    assert report["validation"]["manifest_present"] is True
    assert all(value is False for value in report["pins"].values())


def test_symlink_hardlink_and_declared_oversize_are_rejected(tmp_path: Path) -> None:
    manifest_path, manifest = _fixture(tmp_path)
    os.symlink(tmp_path / "source.bin", tmp_path / "source-link.bin")
    manifest["artifacts"]["source"]["path"] = "source-link.bin"
    _rewrite(manifest_path, manifest)
    with pytest.raises(intake.TargetKernelEvidenceIntakeError, match="symlink"):
        intake.intake_manifest(manifest_path)

    manifest_path, manifest = _fixture(tmp_path)
    os.link(tmp_path / "source.bin", tmp_path / "source-hardlink.bin")
    manifest["artifacts"]["source"]["path"] = "source-hardlink.bin"
    _rewrite(manifest_path, manifest)
    with pytest.raises(intake.TargetKernelEvidenceIntakeError, match="hard link"):
        intake.intake_manifest(manifest_path)

    manifest_path, manifest = _fixture(tmp_path)
    manifest["artifacts"]["source"]["bytes"] = intake.MAX_SMALL_FILE_BYTES + 1
    _rewrite(manifest_path, manifest)
    with pytest.raises(intake.TargetKernelEvidenceIntakeError, match="bounded domain"):
        intake.intake_manifest(manifest_path)


def test_parent_directory_swap_after_component_check_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path, manifest = _fixture(tmp_path)
    trusted_dir = tmp_path / "trusted"
    evil_dir = tmp_path / "evil"
    trusted_dir.mkdir()
    evil_dir.mkdir()
    source_path = tmp_path / "source.bin"
    trusted_source = trusted_dir / source_path.name
    source_path.rename(trusted_source)
    (evil_dir / trusted_source.name).write_bytes(trusted_source.read_bytes())
    manifest["artifacts"]["source"]["path"] = "trusted/source.bin"
    _rewrite(manifest_path, manifest)

    original_open = intake.os.open
    swapped = False

    def race_open(path, flags, *args, **kwargs):
        nonlocal swapped
        is_target_component = kwargs.get("dir_fd") is not None and path == trusted_dir.name
        is_legacy_target_open = kwargs.get("dir_fd") is None and path == os.fspath(trusted_source)
        if not swapped and (is_target_component or is_legacy_target_open):
            real_dir = tmp_path / "trusted-real"
            trusted_dir.rename(real_dir)
            trusted_dir.symlink_to(evil_dir, target_is_directory=True)
            swapped = True
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(intake.os, "open", race_open)
    with pytest.raises(intake.TargetKernelEvidenceIntakeError, match="cannot be opened safely|symlink"):
        intake.intake_manifest(manifest_path)
    assert swapped is True


def test_duplicate_json_keys_and_nonstandard_json_are_rejected(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_bytes(b'{"schema":"one","schema":"two"}')
    with pytest.raises(intake.TargetKernelEvidenceIntakeError, match="duplicate JSON object key"):
        intake.intake_manifest(duplicate)

    nonstandard = tmp_path / "nonstandard.json"
    nonstandard.write_bytes(b'{"schema":NaN}')
    with pytest.raises(intake.TargetKernelEvidenceIntakeError, match="non-standard JSON constant"):
        intake.intake_manifest(nonstandard)


def test_config_artifact_must_bind_declared_required_options(tmp_path: Path) -> None:
    manifest_path, manifest = _fixture(tmp_path)
    config = b"CONFIG_FANOTIFY=y\n"
    (tmp_path / "target.config").write_bytes(config)
    manifest["target"]["config_sha256"] = _sha256(config)
    manifest["artifacts"]["config"] = {
        "path": "target.config",
        "bytes": len(config),
        "sha256": _sha256(config),
    }
    _rewrite(manifest_path, manifest)

    with pytest.raises(intake.TargetKernelEvidenceIntakeError, match="does not prove"):
        intake.intake_manifest(manifest_path)


def test_report_binding_and_checked_in_report_are_strict() -> None:
    expected = intake.build_report()
    checked_in = intake.verify_report()

    assert checked_in == expected
    assert checked_in["status"] == intake.STATUS_BLOCKED_MISSING
    assert checked_in["manifest"]["exists"] is False
    assert all(value is False for value in checked_in["pins"].values())
    assert checked_in["authorization"]["readiness_pass"] is False
    assert checked_in["authorization"]["T1_numerical"] is False
    assert checked_in["authorization"]["qualification_credit"] == 0


def test_report_validator_rejects_promoted_pin_or_credit() -> None:
    value = intake.build_report(Path("external/another-missing-evidence.json"))
    promoted = copy.deepcopy(value)
    promoted["pins"]["source_tree_pinned"] = True
    with pytest.raises(intake.TargetKernelEvidenceIntakeError, match="blocked report"):
        intake._validate_report(promoted)

    promoted = copy.deepcopy(value)
    promoted["authorization"]["qualification_credit"] = 1
    with pytest.raises(intake.TargetKernelEvidenceIntakeError, match="authorization boundary"):
        intake._validate_report(promoted)
