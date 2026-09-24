from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import struct

import pytest

from scripts import f8_r008_per_case_bundle_verifier_v1 as verifier
from scripts import f8_r008_safe_bi4_decoder_v1 as decoder
from scripts import f8_r008_safe_bi4_metadata_binding_v1 as metadata_binding


CASE_ID = "space-q0-dp0p0090"
TIMES = ("2026-09-24T00:00:00Z", "2026-09-24T00:00:01Z", "2026-09-24T00:01:00Z")


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode()


def _file_entry(path: str, payload: bytes) -> dict[str, object]:
    return {
        "path": path,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "regular_file": True,
        "link_count": 1,
    }


def _receipt_schema(stage: str) -> str:
    return verifier.STAGE_RECEIPT_SCHEMAS[stage]


def _manifest_schema(stage: str) -> str:
    return verifier.STAGE_OUTPUT_MANIFESTS[stage][2]


def _manifest_file_name(stage: str) -> str:
    return verifier.STAGE_MANIFEST_NAMES[stage][-1] if stage != "D" else "outputs-manifest.json"


def _string(value: str | bytes) -> bytes:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return struct.pack("<I", len(raw)) + raw


def _value(name: str, type_code: int, value: bytes) -> bytes:
    return _string(name) + struct.pack("<i", type_code) + value


def _array(name: str, type_code: int, payload: bytes) -> bytes:
    count = 1
    definition = (_string(decoder.CODE_ARRAY) + _string(name)
                  + struct.pack("<iiII", 0, type_code, count, len(payload)))
    return struct.pack("<I", len(definition)) + definition + payload


def _item(
    name: str,
    *,
    values: tuple[bytes, ...] = (),
    arrays: tuple[bytes, ...] = (),
    children: tuple[bytes, ...] = (),
) -> bytes:
    values_block = b""
    if values:
        values_block = _string(decoder.CODE_VALUES) + struct.pack("<I", len(values)) + b"".join(values)
    definition = (
        _string(decoder.CODE_ITEM) + _string(name) + struct.pack("<ii", 0, 0)
        + _string("%.7E") + _string("%.15E")
        + struct.pack("<III", len(arrays), len(children), len(values_block))
    )
    return (struct.pack("<I", len(definition)) + definition + values_block
            + b"".join(arrays) + b"".join(children))


def _synthetic_bi4(time_s: float) -> bytes:
    arrays = (
        _array("Idp", 8, struct.pack("<I", 0)),
        _array("Posd", 23, struct.pack("<3d", 1.0, 2.0, 3.0)),
        _array("Vel", 22, struct.pack("<3f", 0.1, 0.2, 0.3)),
        _array("Rhop", 11, struct.pack("<f", 1000.0)),
    )
    part_values = (
        _value("TimeStep", 12, struct.pack("<d", time_s)),
        _value("Npok", 8, struct.pack("<I", 1)),
    )
    part = _item("PART_0000", values=part_values, arrays=arrays)
    root_values = (
        _value("CaseNp", 10, struct.pack("<Q", 1)),
        _value("CaseNfluid", 10, struct.pack("<Q", 1)),
        _value("MassFluid", 12, struct.pack("<d", 0.000421875)),
    )
    root = _item("JPartDataBi4", values=root_values, children=(part,))
    title = decoder.FILE_PREFIX + b" " * (58 - len(decoder.FILE_PREFIX)) + b"\n\0"
    return title + b"\0\0\0\0" + root


def _trusted_code_review_receipt_bytes() -> bytes:
    relative = "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/per-case-provenance-implementation-review-v1/receipt.json"
    return (verifier.LAB / relative).read_bytes()


def _trusted_code_bindings() -> dict[str, object]:
    review_bytes = _trusted_code_review_receipt_bytes()
    review = json.loads(review_bytes)
    return {
        **review["code_bindings"],
        "independent_review_receipt_sha256": hashlib.sha256(review_bytes).hexdigest(),
    }


def _trusted_runtime_assumption() -> dict[str, bool]:
    return {key: True for key in verifier.TRUSTED_RUNTIME_ASSUMPTION_FIELDS}


def _build_bundle(tmp_path: Path, stage: str, *, tamper_axis: bool = False) -> tuple[Path, bytes, dict]:
    root = tmp_path / f"bundle-{stage}"
    root.mkdir()
    outputs_root = root / "outputs"
    manifests_root = root / "manifests"
    outputs_root.mkdir()
    manifests_root.mkdir()
    output_payloads: dict[str, bytes] = {}
    frames: list[dict] = []
    directories: list[str] = []
    if stage == "B":
        initial_payload = _synthetic_bi4(0.0)
        output_payloads = {
            "materialized/generated.xml": b"synthetic-xml",
            "materialized/initial.bi4": initial_payload,
        }
        directories = ["materialized"]
    elif stage == "C":
        row = verifier._frozen_qualification_row(CASE_ID)
        times = verifier.expected_time_axis_hex(row)
        for ordinal, time_hex in enumerate(times):
            path = f"frames/Part_{ordinal:04d}.bi4"
            payload = _synthetic_bi4(float.fromhex(time_hex))
            output_payloads[path] = payload
            frames.append({
                "ordinal": ordinal,
                "expected_time_s_ieee754_hex": time_hex if not (tamper_axis and ordinal == 3)
                else float.fromhex(time_hex).hex().replace("0x", "0x1", 1),
                "path": path,
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            })
        directories = ["frames"]
    else:
        output_payloads["native-fluid-frame-table-v2.h5"] = b"synthetic-table-placeholder"
        for directory in ("decode-receipts", "metadata-bindings", "decoded"):
            target = outputs_root / directory
            target.mkdir(mode=0o700 if directory == "decoded" else 0o755)
        row = verifier._frozen_qualification_row(CASE_ID)
        expected_axis = verifier.expected_time_axis_hex(row)
        raw_manifest_sha = "a" * 64
        for ordinal, time_hex in enumerate(expected_axis):
            raw_payload = _synthetic_bi4(float.fromhex(time_hex))
            raw_path = tmp_path / f"synthetic-D-frame-{ordinal:04d}.bi4"
            raw_path.write_bytes(raw_payload)
            raw_fd = os.open(raw_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                raw_sha = hashlib.sha256(raw_payload).hexdigest()
                metadata_result = metadata_binding.bind_metadata_fd(raw_fd, raw_sha)
                decoded_name = f"frame-{ordinal:04d}"
                decoded_parent_fd = os.open(
                    outputs_root / "decoded",
                    os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
                )
                try:
                    safe_receipt = decoder.decode_bi4_fd(
                        raw_fd, raw_sha, decoded_parent_fd, decoded_name,
                    )
                finally:
                    os.close(decoded_parent_fd)
            finally:
                os.close(raw_fd)

            safe_path = f"decode-receipts/frame-{ordinal:04d}.json"
            metadata_path = f"metadata-bindings/frame-{ordinal:04d}.json"
            safe_bytes = _canonical(safe_receipt)
            metadata_bytes = metadata_result["manifest_bytes"]
            (outputs_root / safe_path).write_bytes(safe_bytes)
            (outputs_root / metadata_path).write_bytes(metadata_bytes)
            frames.append({
                "ordinal": ordinal,
                "expected_time_s_ieee754_hex": time_hex,
                "parser_observed_time_s_ieee754_hex": time_hex,
                "raw_solver_manifest_sha256": raw_manifest_sha,
                "raw_solver_ordinal": ordinal,
                "raw_path": f"frames/Part_{ordinal:04d}.bi4",
                "raw_bytes": len(raw_payload),
                "raw_sha256": raw_sha,
                "safe_decode_input_sha256": raw_sha,
                "safe_decode_receipt_path": safe_path,
                "safe_decode_receipt_bytes": len(safe_bytes),
                "safe_decode_receipt_sha256": hashlib.sha256(safe_bytes).hexdigest(),
                "metadata_binding_manifest_path": metadata_path,
                "metadata_binding_manifest_bytes": len(metadata_bytes),
                "metadata_binding_manifest_sha256": metadata_result["manifest_sha256"],
                "decoded_output_parent_relative_path": "decoded",
                "decoded_output_name": decoded_name,
            })
        for relative, payload in output_payloads.items():
            target = outputs_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)

    if stage != "D":
        for directory in directories:
            (outputs_root / directory).mkdir(parents=True, exist_ok=True)
        for relative, payload in output_payloads.items():
            target = outputs_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)

    output_payloads = {
        path.relative_to(outputs_root).as_posix(): path.read_bytes()
        for path in outputs_root.rglob("*") if path.is_file()
    }
    directories = sorted(
        path.relative_to(outputs_root).as_posix()
        for path in outputs_root.rglob("*") if path.is_dir()
    )
    files = [_file_entry(path, output_payloads[path]) for path in sorted(output_payloads)]
    output_manifest = {
        "schema": _manifest_schema(stage),
        "stage": stage,
        "files": files,
        "directories": sorted(directories),
    }
    if stage == "C":
        output_manifest["frames"] = frames

    manifest_objects: dict[str, dict] = {}
    if stage == "D":
        decoded = {
            "schema": "core.cfd.f8.r008_decoded_frame_manifest.v1",
            "stage": "D",
            "case_id": CASE_ID,
            "attempt_id": f"attempt-{stage.lower()}",
            "raw_solver_manifest_sha256": "a" * 64,
            "frames": frames,
        }
        manifest_objects["decoded-frame-manifest.json"] = decoded
    manifest_objects[_manifest_file_name(stage)] = output_manifest
    for name, value in manifest_objects.items():
        (manifests_root / name).write_bytes(_canonical(value))

    auth = {
        "schema": "core.cfd.f8.r008_execution_authorization.v1",
        "authority_id": f"authority-{stage.lower()}",
        "stage": stage,
        "scope_id": verifier.SCOPE_ID,
        "case_id": CASE_ID,
        "attempt_id": f"attempt-{stage.lower()}",
        "nonce": f"nonce-{stage.lower()}",
        "exclusive_output_root": str(root),
        "executable_sha256": "1" * 64,
        "wrapper_sha256": "2" * 64,
        "argv": ["/synthetic/tool", "--bounded"],
        "input_bindings": {"fixture": {"sha256": "3" * 64}},
        "invocation_budget": 1,
        "resource_limits": {"cpu_seconds": 10, "memory_bytes": 1048576},
        "issued_at_utc": TIMES[0],
        "expires_at_utc": TIMES[2],
    }
    auth_bytes = _canonical(auth)
    auth_sha = hashlib.sha256(auth_bytes).hexdigest()
    (root / "authorization.json").write_bytes(auth_bytes)
    lock = {
        "schema": "core.cfd.f8.r008_one_shot_lock.v1",
        "authority_sha256": auth_sha,
        "stage": stage,
        "scope_id": verifier.SCOPE_ID,
        "case_id": CASE_ID,
        "attempt_id": auth["attempt_id"],
        "nonce": auth["nonce"],
        "exclusive_output_root": str(root),
        "created_at_utc": TIMES[0],
        "exclusive_create_succeeded": True,
    }
    lock_bytes = _canonical(lock)
    (root / "one-shot-lock.json").write_bytes(lock_bytes)

    manifest_bindings = {
        name: {"path": f"manifests/{name}", "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        for name in manifest_objects
        for payload in [(manifests_root / name).read_bytes()]
    }
    receipt = {
        "schema": _receipt_schema(stage),
        "scope_id": verifier.SCOPE_ID,
        "case_id": CASE_ID,
        "attempt_id": auth["attempt_id"],
        "nonce": auth["nonce"],
        "status": "passed",
        "started_at_utc": TIMES[1],
        "ended_at_utc": TIMES[1],
        "authorization_binding": {
            "path": "authorization.json", "bytes": len(auth_bytes), "sha256": auth_sha,
        },
        "one_shot_lock_binding": {
            "path": "one-shot-lock.json", "bytes": len(lock_bytes),
            "sha256": hashlib.sha256(lock_bytes).hexdigest(),
        },
        "execution_controls": {},
    }
    if stage == "B":
        initial_payload = output_payloads["materialized/initial.bi4"]
        initial_fd = os.open(outputs_root / "materialized/initial.bi4", os.O_RDONLY)
        try:
            b_metadata = metadata_binding.bind_metadata_fd(
                initial_fd, hashlib.sha256(initial_payload).hexdigest(),
            )
        finally:
            os.close(initial_fd)
        receipt.update({
            "definition_binding": {}, "control_binding": {}, "gencase_execution": {},
            "generated_xml_path": {
                "path": "outputs/materialized/generated.xml",
                "bytes": len(output_payloads["materialized/generated.xml"]),
                "sha256": hashlib.sha256(output_payloads["materialized/generated.xml"]).hexdigest(),
            },
            "initial_bi4_path": {
                "path": "outputs/materialized/initial.bi4", "bytes": len(initial_payload),
                "sha256": hashlib.sha256(initial_payload).hexdigest(),
            },
            "safe_decode_receipt": {},
            "metadata_binding": {
                "manifest": b_metadata["manifest"],
                "manifest_sha256": b_metadata["manifest_sha256"],
            },
            "particle_cohorts": {},
            "output_manifest": manifest_bindings["materialization-output-manifest.json"],
        })
    elif stage == "C":
        receipt.update({
            "materialization_receipt_binding": {"path": "../B/receipt.json", "bytes": 1, "sha256": "4" * 64},
            "solver_execution": {},
            "raw_output_manifest": manifest_bindings["raw-solver-manifest.json"],
        })
    else:
        receipt.update({
            "solver_receipt_binding": {"path": "../C/receipt.json", "bytes": 1, "sha256": "5" * 64},
            "decoder_code_binding": _trusted_code_bindings(),
            "decoded_frame_manifest_binding": manifest_bindings["decoded-frame-manifest.json"],
            "outputs_manifest_binding": manifest_bindings["outputs-manifest.json"],
            "frame_mappings": frames if stage == "D" else [],
            "native_fluid_table_binding": {
                "path": "outputs/native-fluid-frame-table-v2.h5",
                "bytes": len(output_payloads["native-fluid-frame-table-v2.h5"]),
                "sha256": hashlib.sha256(output_payloads["native-fluid-frame-table-v2.h5"]).hexdigest(),
            },
        })
    (root / "receipt.json").write_text(json.dumps(receipt, sort_keys=True) + "\n")
    return root, auth_bytes, auth


def _update_reference(target: dict, field: str, reference_path: Path) -> None:
    payload = reference_path.read_bytes()
    target[field] = {
        "path": str(reference_path),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _build_chain(tmp_path: Path) -> tuple[dict, dict, dict, dict]:
    roots: dict[str, Path] = {}
    auth_bytes: dict[str, bytes] = {}
    auth: dict[str, dict] = {}
    for stage in ("B", "C", "D"):
        roots[stage], auth_bytes[stage], auth[stage] = _build_bundle(tmp_path, stage)

    c_receipt_path = roots["C"] / "receipt.json"
    c_receipt = json.loads(c_receipt_path.read_text())
    _update_reference(c_receipt, "materialization_receipt_binding", roots["B"] / "receipt.json")
    c_receipt_path.write_text(json.dumps(c_receipt, sort_keys=True) + "\n")

    c_raw_path = roots["C"] / "manifests" / "raw-solver-manifest.json"
    c_raw_bytes = c_raw_path.read_bytes()
    c_raw_sha = hashlib.sha256(c_raw_bytes).hexdigest()
    c_raw = json.loads(c_raw_bytes)
    d_manifest_path = roots["D"] / "manifests" / "decoded-frame-manifest.json"
    d_manifest = json.loads(d_manifest_path.read_text())
    d_frames = []
    for d_entry, c_entry in zip(d_manifest["frames"], c_raw["frames"]):
        d_frames.append({
            **d_entry,
            "expected_time_s_ieee754_hex": c_entry["expected_time_s_ieee754_hex"],
            "parser_observed_time_s_ieee754_hex": c_entry["expected_time_s_ieee754_hex"],
            "raw_solver_manifest_sha256": c_raw_sha,
            "raw_solver_ordinal": c_entry["ordinal"],
            "raw_path": c_entry["path"],
            "raw_bytes": c_entry["bytes"],
            "raw_sha256": c_entry["sha256"],
            "safe_decode_input_sha256": c_entry["sha256"],
        })
    d_manifest["raw_solver_manifest_sha256"] = c_raw_sha
    d_manifest["frames"] = d_frames
    d_manifest_bytes = _canonical(d_manifest)
    d_manifest_path.write_bytes(d_manifest_bytes)

    d_receipt_path = roots["D"] / "receipt.json"
    d_receipt = json.loads(d_receipt_path.read_text())
    _update_reference(d_receipt, "solver_receipt_binding", c_receipt_path)
    _update_reference(d_receipt, "decoded_frame_manifest_binding", d_manifest_path)
    d_receipt["decoded_frame_manifest_binding"]["path"] = "manifests/decoded-frame-manifest.json"
    d_receipt["frame_mappings"] = d_frames
    d_receipt_path.write_text(json.dumps(d_receipt, sort_keys=True) + "\n")
    return roots, auth_bytes, auth, d_frames


def _refresh_d_bundle_after_tamper(root: Path, frames: list[dict], changed_paths: set[str]) -> None:
    outputs_root = root / "outputs"
    outputs_manifest_path = root / "manifests" / "outputs-manifest.json"
    outputs_manifest = json.loads(outputs_manifest_path.read_text())
    file_entries = {entry["path"]: entry for entry in outputs_manifest["files"]}
    for relative in changed_paths:
        payload = (outputs_root / relative).read_bytes()
        file_entries[relative]["bytes"] = len(payload)
        file_entries[relative]["sha256"] = hashlib.sha256(payload).hexdigest()
    outputs_manifest["files"] = [file_entries[path] for path in sorted(file_entries)]
    outputs_payload = _canonical(outputs_manifest)
    outputs_manifest_path.write_bytes(outputs_payload)

    d_manifest_path = root / "manifests" / "decoded-frame-manifest.json"
    d_manifest = json.loads(d_manifest_path.read_text())
    d_manifest["frames"] = frames
    d_payload = _canonical(d_manifest)
    d_manifest_path.write_bytes(d_payload)

    receipt_path = root / "receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["outputs_manifest_binding"] = {
        "path": "manifests/outputs-manifest.json",
        "bytes": len(outputs_payload),
        "sha256": hashlib.sha256(outputs_payload).hexdigest(),
    }
    receipt["decoded_frame_manifest_binding"] = {
        "path": "manifests/decoded-frame-manifest.json",
        "bytes": len(d_payload),
        "sha256": hashlib.sha256(d_payload).hexdigest(),
    }
    receipt["frame_mappings"] = frames
    receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n")


def test_expected_time_axis_is_binary64_non_cumulative_and_ends_at_frozen_endpoint() -> None:
    row = verifier._frozen_qualification_row(CASE_ID)
    result = verifier.expected_time_axis_hex(row)
    dt = float(row["native_output_dt_s"])
    count = row["full_native_output_rows_to_timemax"]
    endpoint = float(row["observation_end_s"])
    assert len(result) == count
    assert result[0] == 0.0.hex()
    assert result[1] == (1.0 * dt).hex()
    assert result[-1] == endpoint.hex()
    assert result[-1] == (float(count - 1) * dt).hex()


def test_expected_time_axis_builds_all_fifteen_frozen_qualification_rows() -> None:
    pack = json.loads(verifier.FROZEN_DEFINITION_PACK.read_text())
    rows = [row for row in pack["cases"] if row.get("qualification_only") is True]
    assert len(rows) == 15
    for row in rows:
        axis = verifier.expected_time_axis_hex(row)
        assert len(axis) == row["full_native_output_rows_to_timemax"]
        assert axis[0] == 0.0.hex()
        assert axis[-1] == float(row["observation_end_s"]).hex()
        assert all(float.fromhex(left) < float.fromhex(right) for left, right in zip(axis, axis[1:]))


@pytest.mark.parametrize("stage", ["B", "C", "D"])
def test_synthetic_stage_bundle_closes_without_granting_authority_or_credit(
    tmp_path: Path, stage: str,
) -> None:
    root, auth_bytes, auth = _build_bundle(tmp_path, stage)
    result = verifier.verify_stage_bundle(
        root, stage,
        trusted_authorization_bytes=auth_bytes,
        trusted_authorization_sha256=hashlib.sha256(auth_bytes).hexdigest(),
        expected_authorization_envelope=auth,
        trusted_code_review_receipt_bytes=(
            _trusted_code_review_receipt_bytes() if stage == "D" else None
        ),
        trusted_runtime_assumption=_trusted_runtime_assumption() if stage == "D" else None,
    )
    assert result["bundle_structure_closed"] is True
    assert result["authority_bytes_match_caller_trusted_binding"] is True
    assert result["authority_authenticity"] == "external_gate_not_checked_here"
    assert result["readiness_pass"] is False
    assert result["qualification_credit"] == 0
    assert result["native_integrity_evaluated"] is False


def test_raw_solver_manifest_must_match_frozen_full_axis(tmp_path: Path) -> None:
    root, auth_bytes, auth = _build_bundle(tmp_path, "C", tamper_axis=True)
    with pytest.raises(verifier.BundleVerificationError, match="frozen expected axis"):
        verifier.verify_stage_bundle(
            root, "C",
            trusted_authorization_bytes=auth_bytes,
            trusted_authorization_sha256=hashlib.sha256(auth_bytes).hexdigest(),
            expected_authorization_envelope=auth,
        )


def test_extra_unmanifested_output_and_omitted_directory_fail_closed(tmp_path: Path) -> None:
    root, auth_bytes, auth = _build_bundle(tmp_path, "B")
    (root / "outputs" / "materialized" / "extra.bin").write_bytes(b"extra")
    with pytest.raises(verifier.BundleVerificationError, match="recursive outputs file tree"):
        verifier.verify_stage_bundle(
            root, "B", trusted_authorization_bytes=auth_bytes,
            trusted_authorization_sha256=hashlib.sha256(auth_bytes).hexdigest(),
            expected_authorization_envelope=auth,
        )

    shutil.rmtree(root)
    root, auth_bytes, auth = _build_bundle(tmp_path, "B")
    manifest_path = root / "manifests" / "materialization-output-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["directories"] = []
    manifest_bytes = _canonical(manifest)
    manifest_path.write_bytes(manifest_bytes)
    receipt_path = root / "receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["output_manifest"]["bytes"] = len(manifest_bytes)
    receipt["output_manifest"]["sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
    receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n")
    with pytest.raises(verifier.BundleVerificationError, match="missing a parent directory|directory tree"):
        verifier.verify_stage_bundle(
            root, "B", trusted_authorization_bytes=auth_bytes,
            trusted_authorization_sha256=hashlib.sha256(auth_bytes).hexdigest(),
            expected_authorization_envelope=auth,
        )


def test_authorization_mismatch_and_downstream_digest_in_lock_are_rejected(tmp_path: Path) -> None:
    root, auth_bytes, auth = _build_bundle(tmp_path, "B")
    altered = dict(auth, resource_limits={"cpu_seconds": 999})
    with pytest.raises(verifier.BundleVerificationError, match="caller-supplied exact envelope"):
        verifier.verify_stage_bundle(
            root, "B", trusted_authorization_bytes=auth_bytes,
            trusted_authorization_sha256=hashlib.sha256(auth_bytes).hexdigest(),
            expected_authorization_envelope=altered,
        )

    lock_path = root / "one-shot-lock.json"
    lock = json.loads(lock_path.read_text())
    lock["table_sha256"] = "a" * 64
    lock_bytes = _canonical(lock)
    lock_path.write_bytes(lock_bytes)
    receipt = json.loads((root / "receipt.json").read_text())
    receipt["one_shot_lock_binding"]["bytes"] = len(lock_bytes)
    receipt["one_shot_lock_binding"]["sha256"] = hashlib.sha256(lock_bytes).hexdigest()
    (root / "receipt.json").write_text(json.dumps(receipt, sort_keys=True) + "\n")
    with pytest.raises(verifier.BundleVerificationError, match="forbidden downstream digest"):
        verifier.verify_stage_bundle(
            root, "B", trusted_authorization_bytes=auth_bytes,
            trusted_authorization_sha256=hashlib.sha256(auth_bytes).hexdigest(),
            expected_authorization_envelope=auth,
        )


def test_expired_or_late_lock_cannot_claim_a_started_stage(tmp_path: Path) -> None:
    root, auth_bytes, auth = _build_bundle(tmp_path, "B")
    lock_path = root / "one-shot-lock.json"
    lock = json.loads(lock_path.read_text())
    lock["created_at_utc"] = TIMES[2]
    lock_bytes = _canonical(lock)
    lock_path.write_bytes(lock_bytes)
    receipt = json.loads((root / "receipt.json").read_text())
    receipt["one_shot_lock_binding"]["bytes"] = len(lock_bytes)
    receipt["one_shot_lock_binding"]["sha256"] = hashlib.sha256(lock_bytes).hexdigest()
    (root / "receipt.json").write_text(json.dumps(receipt, sort_keys=True) + "\n")
    with pytest.raises(verifier.BundleVerificationError, match="within authority validity|strictly before stage start"):
        verifier.verify_stage_bundle(
            root, "B", trusted_authorization_bytes=auth_bytes,
            trusted_authorization_sha256=hashlib.sha256(auth_bytes).hexdigest(),
            expected_authorization_envelope=auth,
        )


def test_full_b_c_d_reference_chain_closes_without_t1_authority(tmp_path: Path) -> None:
    roots, auth_bytes, auth, d_frames = _build_chain(tmp_path)
    result = verifier.verify_provenance_chain(
        roots,
        trusted_authorization_bytes=auth_bytes,
        trusted_authorization_sha256={stage: hashlib.sha256(value).hexdigest()
                                      for stage, value in auth_bytes.items()},
        expected_authorization_envelopes=auth,
        trusted_code_review_receipt_bytes=_trusted_code_review_receipt_bytes(),
        trusted_runtime_assumption=_trusted_runtime_assumption(),
    )
    assert result["provenance_chain_references_closed"] is True
    assert result["frames_paired"] == len(d_frames) == 321
    assert result["all_stages_passed"] is True
    assert result["readiness_pass"] is False
    assert result["qualification_credit"] == 0


@pytest.mark.parametrize("kind", ["metadata", "xml", "array"])
def test_chain_recomputes_metadata_XML_and_array_bytes_from_C_raw_BI4(
    tmp_path: Path, kind: str,
) -> None:
    roots, auth_bytes, auth, frames = _build_chain(tmp_path)
    changed_paths: set[str] = set()
    if kind == "metadata":
        frame = frames[0]
        relative = frame["metadata_binding_manifest_path"]
        path = roots["D"] / "outputs" / relative
        document = json.loads(path.read_text())
        mass = next(record for record in document["metadata_records"]
                    if record["item_path"] == ["JPartDataBi4"]
                    and record["metadata_name"] == "MassFluid")
        mass["raw_value_bytes_hex"] = struct.pack("<d", 0.5).hex()
        mass["float_hex_components"] = [0.5.hex()]
        payload = _canonical(document)
        path.write_bytes(payload)
        frame["metadata_binding_manifest_bytes"] = len(payload)
        frame["metadata_binding_manifest_sha256"] = hashlib.sha256(payload).hexdigest()
        changed_paths.add(relative)
        message = "does not exactly recompute from its C raw BI4"
    else:
        frame = frames[0]
        safe_relative = frame["safe_decode_receipt_path"]
        safe_path = roots["D"] / "outputs" / safe_relative
        safe_receipt = json.loads(safe_path.read_text())
        if kind == "xml":
            output_relative = "decoded/frame-0000.xml"
            output_path = roots["D"] / "outputs" / output_relative
            altered = bytearray(output_path.read_bytes())
            altered[0] ^= 1
            output_path.write_bytes(altered)
            safe_receipt["xml"]["sha256"] = hashlib.sha256(altered).hexdigest()
            message = "raw-to-decoded XML"
        else:
            array = next(entry for entry in safe_receipt["arrays"]
                         if entry["path"] == "PART_0000/Posd.bin")
            output_relative = f"{frame['decoded_output_parent_relative_path']}/{frame['decoded_output_name']}/{array['path']}"
            output_path = roots["D"] / "outputs" / output_relative
            altered = bytearray(output_path.read_bytes())
            altered[0] ^= 1
            output_path.write_bytes(altered)
            array["sha256"] = hashlib.sha256(altered).hexdigest()
            message = "raw-to-decoded array"
        safe_payload = _canonical(safe_receipt)
        safe_path.write_bytes(safe_payload)
        frame["safe_decode_receipt_bytes"] = len(safe_payload)
        frame["safe_decode_receipt_sha256"] = hashlib.sha256(safe_payload).hexdigest()
        changed_paths.update({safe_relative, output_relative})

    _refresh_d_bundle_after_tamper(roots["D"], frames, changed_paths)
    with pytest.raises(verifier.BundleVerificationError, match=message):
        verifier.verify_provenance_chain(
            roots,
            trusted_authorization_bytes=auth_bytes,
            trusted_authorization_sha256={stage: hashlib.sha256(value).hexdigest()
                                          for stage, value in auth_bytes.items()},
            expected_authorization_envelopes=auth,
            trusted_code_review_receipt_bytes=_trusted_code_review_receipt_bytes(),
            trusted_runtime_assumption=_trusted_runtime_assumption(),
        )


def test_runtime_assumption_discloses_that_loaded_module_identity_is_not_proven(
    tmp_path: Path, monkeypatch,
) -> None:
    roots, auth_bytes, auth, _frames = _build_chain(tmp_path)
    original = decoder._xml_document

    def swapped_module_function(scan):
        return original(scan)

    monkeypatch.setattr(decoder, "_xml_document", swapped_module_function)
    result = verifier.verify_provenance_chain(
        roots,
        trusted_authorization_bytes=auth_bytes,
        trusted_authorization_sha256={stage: hashlib.sha256(value).hexdigest()
                                      for stage, value in auth_bytes.items()},
        expected_authorization_envelopes=auth,
        trusted_code_review_receipt_bytes=_trusted_code_review_receipt_bytes(),
        trusted_runtime_assumption=_trusted_runtime_assumption(),
    )
    assert result["code_bindings_match_caller_trusted_independent_review"] is True
    assert result["loaded_module_code_identity_verified"] is False
    assert result["runtime_environment_assumption"] == "caller_attested_not_independently_verified"


def test_chain_rejects_decoded_time_drift_even_when_receipt_and_manifest_agree(tmp_path: Path) -> None:
    roots, auth_bytes, auth, frames = _build_chain(tmp_path)
    frames[7]["parser_observed_time_s_ieee754_hex"] = (float.fromhex(frames[7]["expected_time_s_ieee754_hex"]) + 1e-12).hex()
    manifest_path = roots["D"] / "manifests" / "decoded-frame-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["frames"] = frames
    manifest_bytes = _canonical(manifest)
    manifest_path.write_bytes(manifest_bytes)
    receipt_path = roots["D"] / "receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["decoded_frame_manifest_binding"]["bytes"] = len(manifest_bytes)
    receipt["decoded_frame_manifest_binding"]["sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
    receipt["frame_mappings"] = frames
    receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n")
    with pytest.raises(verifier.BundleVerificationError, match="observed TimeStep|binary64 axis"):
        verifier.verify_provenance_chain(
            roots,
            trusted_authorization_bytes=auth_bytes,
            trusted_authorization_sha256={stage: hashlib.sha256(value).hexdigest()
                                          for stage, value in auth_bytes.items()},
            expected_authorization_envelopes=auth,
            trusted_code_review_receipt_bytes=_trusted_code_review_receipt_bytes(),
            trusted_runtime_assumption=_trusted_runtime_assumption(),
        )


@pytest.mark.parametrize("kind", ["file_symlink", "directory_symlink", "hardlink"])
def test_symlinked_or_hardlinked_output_objects_fail_closed(tmp_path: Path, kind: str) -> None:
    root, auth_bytes, auth = _build_bundle(tmp_path, "B")
    external = tmp_path / "external.bin"
    external.write_bytes(b"outside")
    if kind == "file_symlink":
        output = root / "outputs" / "materialized" / "generated.xml"
        output.unlink()
        output.symlink_to(external)
    elif kind == "directory_symlink":
        shutil.rmtree(root / "outputs" / "materialized")
        (root / "outputs" / "materialized").symlink_to(tmp_path, target_is_directory=True)
    else:
        external.unlink()
        os.link(root / "outputs" / "materialized" / "generated.xml", external)
    with pytest.raises(verifier.BundleVerificationError, match="symlink|hard links|single-link"):
        verifier.verify_stage_bundle(
            root, "B", trusted_authorization_bytes=auth_bytes,
            trusted_authorization_sha256=hashlib.sha256(auth_bytes).hexdigest(),
            expected_authorization_envelope=auth,
        )


@pytest.mark.parametrize("encoding", ["duplicate", "noncanonical"])
def test_duplicate_keys_and_noncanonical_manifests_fail_closed(
    tmp_path: Path, encoding: str,
) -> None:
    root, auth_bytes, auth = _build_bundle(tmp_path, "B")
    manifest_path = root / "manifests" / "materialization-output-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if encoding == "duplicate":
        payload = _canonical(manifest).replace(b'"stage":"B"', b'"stage":"B","stage":"B"')
        message = "duplicate JSON"
    else:
        payload = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
        message = "canonical JSON"
    manifest_path.write_bytes(payload)
    receipt_path = root / "receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["output_manifest"]["bytes"] = len(payload)
    receipt["output_manifest"]["sha256"] = hashlib.sha256(payload).hexdigest()
    receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n")
    with pytest.raises(verifier.BundleVerificationError, match=message):
        verifier.verify_stage_bundle(
            root, "B", trusted_authorization_bytes=auth_bytes,
            trusted_authorization_sha256=hashlib.sha256(auth_bytes).hexdigest(),
            expected_authorization_envelope=auth,
        )


@pytest.mark.parametrize("tamper", ["extra_top_level", "nested_cycle_digest"])
def test_manifest_exact_fields_and_recursive_cycle_keys_fail_closed(
    tmp_path: Path, tamper: str,
) -> None:
    root, auth_bytes, auth = _build_bundle(tmp_path, "B")
    manifest_path = root / "manifests" / "materialization-output-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if tamper == "extra_top_level":
        manifest["unrecognized_extension"] = True
        message = "top-level fields are not exact"
    else:
        manifest["files"][0]["receipt_sha256"] = "a" * 64
        message = "forbidden self/enclosing/downstream digest"
    manifest_bytes = _canonical(manifest)
    manifest_path.write_bytes(manifest_bytes)
    receipt_path = root / "receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["output_manifest"] = {
        "path": "manifests/materialization-output-manifest.json",
        "bytes": len(manifest_bytes),
        "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
    }
    receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n")
    with pytest.raises(verifier.BundleVerificationError, match=message):
        verifier.verify_stage_bundle(
            root, "B", trusted_authorization_bytes=auth_bytes,
            trusted_authorization_sha256=hashlib.sha256(auth_bytes).hexdigest(),
            expected_authorization_envelope=auth,
        )


@pytest.mark.parametrize("artifact", ["safe_decode_receipt", "metadata_binding_manifest"])
def test_D_safe_decode_and_metadata_hashes_must_bind_real_outputs(
    tmp_path: Path, artifact: str,
) -> None:
    root, auth_bytes, auth = _build_bundle(tmp_path, "D")
    trusted_review_bytes = _trusted_code_review_receipt_bytes()
    mismatched_trust = trusted_review_bytes + b" "
    with pytest.raises(verifier.BundleVerificationError, match="caller-trusted independent review"):
        verifier.verify_stage_bundle(
            root, "D", trusted_authorization_bytes=auth_bytes,
            trusted_authorization_sha256=hashlib.sha256(auth_bytes).hexdigest(),
            expected_authorization_envelope=auth,
            trusted_code_review_receipt_bytes=mismatched_trust,
            trusted_runtime_assumption=_trusted_runtime_assumption(),
        )
    with pytest.raises(verifier.BundleVerificationError, match="runtime/module-state TCB"):
        verifier.verify_stage_bundle(
            root, "D", trusted_authorization_bytes=auth_bytes,
            trusted_authorization_sha256=hashlib.sha256(auth_bytes).hexdigest(),
            expected_authorization_envelope=auth,
            trusted_code_review_receipt_bytes=trusted_review_bytes,
        )
    manifest_path = root / "manifests" / "decoded-frame-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    field = "safe_decode_receipt_sha256" if artifact == "safe_decode_receipt" \
        else "metadata_binding_manifest_sha256"
    manifest["frames"][0][field] = "f" * 64
    payload = _canonical(manifest)
    manifest_path.write_bytes(payload)
    receipt_path = root / "receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["decoded_frame_manifest_binding"]["bytes"] = len(payload)
    receipt["decoded_frame_manifest_binding"]["sha256"] = hashlib.sha256(payload).hexdigest()
    receipt["frame_mappings"] = manifest["frames"]
    receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n")
    with pytest.raises(verifier.BundleVerificationError, match="closed D outputs manifest"):
        verifier.verify_stage_bundle(
            root, "D", trusted_authorization_bytes=auth_bytes,
            trusted_authorization_sha256=hashlib.sha256(auth_bytes).hexdigest(),
            expected_authorization_envelope=auth,
            trusted_code_review_receipt_bytes=trusted_review_bytes,
            trusted_runtime_assumption=_trusted_runtime_assumption(),
        )


@pytest.mark.parametrize("kind", ["xml", "array"])
def test_D_decoded_XML_and_array_payloads_are_content_bound_to_raw_BI4(
    tmp_path: Path, kind: str,
) -> None:
    root, auth_bytes, auth = _build_bundle(tmp_path, "D")
    output_path = (root / "outputs" / "decoded" / "frame-0000.xml") if kind == "xml" else (
        root / "outputs" / "decoded" / "frame-0000" / "PART_0000" / "Posd.bin"
    )
    payload = bytearray(output_path.read_bytes())
    payload[0] ^= 1
    output_path.write_bytes(payload)
    with pytest.raises(verifier.BundleVerificationError, match="detached manifest files"):
        verifier.verify_stage_bundle(
            root, "D", trusted_authorization_bytes=auth_bytes,
            trusted_authorization_sha256=hashlib.sha256(auth_bytes).hexdigest(),
            expected_authorization_envelope=auth,
            trusted_code_review_receipt_bytes=_trusted_code_review_receipt_bytes(),
            trusted_runtime_assumption=_trusted_runtime_assumption(),
        )


def test_directory_mutation_during_inventory_is_detected(tmp_path: Path, monkeypatch) -> None:
    root, auth_bytes, auth = _build_bundle(tmp_path, "B")
    original = verifier._hash_file_at
    changed = False

    def mutate_after_hash(parent_fd, name, max_bytes, expected_stat=None):
        nonlocal changed
        value = original(parent_fd, name, max_bytes, expected_stat)
        if not changed:
            (root / "outputs" / "materialized" / "raced.bin").write_bytes(b"raced")
            changed = True
        return value

    monkeypatch.setattr(verifier, "_hash_file_at", mutate_after_hash)
    with pytest.raises(verifier.BundleVerificationError, match="directory changed while enumerating"):
        verifier.verify_stage_bundle(
            root, "B", trusted_authorization_bytes=auth_bytes,
            trusted_authorization_sha256=hashlib.sha256(auth_bytes).hexdigest(),
            expected_authorization_envelope=auth,
        )


def test_directory_fanout_limit_is_enforced_incrementally(monkeypatch) -> None:
    class Entry:
        def __init__(self, name: str) -> None:
            self.name = name

    class Entries:
        def __init__(self) -> None:
            self.yielded = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def __iter__(self):
            while True:
                self.yielded += 1
                yield Entry(f"entry-{self.yielded}")

    entries = Entries()
    monkeypatch.setattr(verifier.os, "scandir", lambda _fd: entries)
    with pytest.raises(verifier.BundleVerificationError, match="directory-entry cap"):
        verifier._bounded_directory_names(123, 5, "test directory")
    assert entries.yielded == 6


def test_inventory_tree_enforces_combined_file_and_directory_cap(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "bounded-tree"
    root.mkdir()
    (root / "first.bin").write_bytes(b"1")
    (root / "second.bin").write_bytes(b"2")
    child = root / "nested"
    child.mkdir()
    (child / "third.bin").write_bytes(b"3")
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0))
    monkeypatch.setattr(verifier, "MAX_FILE_COUNT", 3)
    try:
        with pytest.raises(verifier.BundleVerificationError, match="combined per-stage file/directory entry cap"):
            verifier._inventory_tree(root_fd)
    finally:
        os.close(root_fd)


def test_passed_stage_cannot_finish_after_authorization_expiry(tmp_path: Path) -> None:
    root, auth_bytes, auth = _build_bundle(tmp_path, "B")
    receipt_path = root / "receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["ended_at_utc"] = "2026-09-25T00:00:00Z"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n")
    with pytest.raises(verifier.BundleVerificationError, match="completion exceeded"):
        verifier.verify_stage_bundle(
            root, "B", trusted_authorization_bytes=auth_bytes,
            trusted_authorization_sha256=hashlib.sha256(auth_bytes).hexdigest(),
            expected_authorization_envelope=auth,
        )


def test_passed_D_bundle_requires_full_exact_frame_manifest(tmp_path: Path) -> None:
    root, auth_bytes, auth = _build_bundle(tmp_path, "D")
    manifest_path = root / "manifests" / "decoded-frame-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["frames"] = manifest["frames"][:1]
    payload = _canonical(manifest)
    manifest_path.write_bytes(payload)
    receipt_path = root / "receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["decoded_frame_manifest_binding"]["bytes"] = len(payload)
    receipt["decoded_frame_manifest_binding"]["sha256"] = hashlib.sha256(payload).hexdigest()
    receipt["frame_mappings"] = manifest["frames"]
    receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n")
    with pytest.raises(verifier.BundleVerificationError, match="full frozen native frame axis"):
        verifier.verify_stage_bundle(
            root, "D", trusted_authorization_bytes=auth_bytes,
            trusted_authorization_sha256=hashlib.sha256(auth_bytes).hexdigest(),
            expected_authorization_envelope=auth,
            trusted_code_review_receipt_bytes=_trusted_code_review_receipt_bytes(),
            trusted_runtime_assumption=_trusted_runtime_assumption(),
        )


def test_chain_rejects_d_frame_raw_binding_that_disagrees_with_c_manifest(tmp_path: Path) -> None:
    roots, auth_bytes, auth, frames = _build_chain(tmp_path)
    frames[12]["raw_sha256"] = "e" * 64
    frames[12]["safe_decode_input_sha256"] = "e" * 64
    manifest_path = roots["D"] / "manifests" / "decoded-frame-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["frames"] = frames
    payload = _canonical(manifest)
    manifest_path.write_bytes(payload)
    receipt_path = roots["D"] / "receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["decoded_frame_manifest_binding"]["bytes"] = len(payload)
    receipt["decoded_frame_manifest_binding"]["sha256"] = hashlib.sha256(payload).hexdigest()
    receipt["frame_mappings"] = frames
    receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n")
    with pytest.raises(verifier.BundleVerificationError, match="differs from C manifest"):
        verifier.verify_provenance_chain(
            roots,
            trusted_authorization_bytes=auth_bytes,
            trusted_authorization_sha256={stage: hashlib.sha256(value).hexdigest()
                                          for stage, value in auth_bytes.items()},
            expected_authorization_envelopes=auth,
            trusted_code_review_receipt_bytes=_trusted_code_review_receipt_bytes(),
            trusted_runtime_assumption=_trusted_runtime_assumption(),
        )
