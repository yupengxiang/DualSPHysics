from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import struct

import h5py
import numpy as np
import pytest

from scripts import f8_r008_native_fluid_table_bundle_verifier_v1 as integration
from scripts import f8_r008_native_fluid_table_v2 as table_v2
from scripts import f8_r008_native_fluid_table_schema_review_v2 as table_review
from scripts import f8_r008_per_case_bundle_verifier_v1 as bundle

from tests import test_f8_r008_per_case_bundle_verifier_v1 as fixtures


HDF5_BOOLEAN = h5py.enum_dtype({"FALSE": 0, "TRUE": 1}, basetype=np.dtype("u1"))
FLUID_IDS = np.asarray([0], dtype="<u4")
FIXTURE_MASS_BYTES = struct.pack("<d", 0.000421875)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_canonical(path: Path, value: dict) -> bytes:
    payload = fixtures._canonical(value)
    path.write_bytes(payload)
    return payload


def _refresh_d_table_manifest_binding(roots: dict[str, Path]) -> None:
    table_path = roots["D"] / "outputs/native-fluid-frame-table-v2.h5"
    table_payload = table_path.read_bytes()
    table_sha = hashlib.sha256(table_payload).hexdigest()
    outputs_manifest_path = roots["D"] / "manifests/outputs-manifest.json"
    outputs_manifest = _json(outputs_manifest_path)
    table_entry = next(
        entry for entry in outputs_manifest["files"]
        if entry["path"] == "native-fluid-frame-table-v2.h5"
    )
    table_entry["bytes"] = len(table_payload)
    table_entry["sha256"] = table_sha
    output_manifest_bytes = _write_canonical(outputs_manifest_path, outputs_manifest)

    d_receipt_path = roots["D"] / "receipt.json"
    d_receipt = _json(d_receipt_path)
    d_receipt["outputs_manifest_binding"] = {
        "path": "manifests/outputs-manifest.json",
        "bytes": len(output_manifest_bytes),
        "sha256": hashlib.sha256(output_manifest_bytes).hexdigest(),
    }
    d_receipt["native_fluid_table_binding"] = {
        "path": "outputs/native-fluid-frame-table-v2.h5",
        "bytes": len(table_payload),
        "sha256": table_sha,
    }
    _write_canonical(d_receipt_path, d_receipt)


def _freeze_b_source_bindings(roots: dict[str, Path]) -> None:
    b_path = roots["B"] / "receipt.json"
    b_receipt = _json(b_path)
    row = bundle._frozen_qualification_row(fixtures.CASE_ID)
    for field in ("definition", "control"):
        source = row[field]
        b_receipt[f"{field}_binding"] = {
            key: source[key] for key in ("path", "bytes", "sha256")
        }
    _write_canonical(b_path, b_receipt)

    c_path = roots["C"] / "receipt.json"
    c_receipt = _json(c_path)
    fixtures._update_reference(c_receipt, "materialization_receipt_binding", b_path)
    _write_canonical(c_path, c_receipt)

    d_path = roots["D"] / "receipt.json"
    d_receipt = _json(d_path)
    fixtures._update_reference(d_receipt, "solver_receipt_binding", c_path)
    _write_canonical(d_path, d_receipt)


def _materialize_synthetic_v2_table(roots: dict[str, Path]) -> None:
    b_receipt = _json(roots["B"] / "receipt.json")
    c_manifest_path = roots["C"] / "manifests/raw-solver-manifest.json"
    c_manifest_bytes = c_manifest_path.read_bytes()
    c_manifest = json.loads(c_manifest_bytes)
    table_attributes = table_v2.expected_root_attributes(
        case_id=fixtures.CASE_ID,
        generated_xml_sha256=b_receipt["generated_xml_path"]["sha256"],
        definition_sha256=b_receipt["definition_binding"]["sha256"],
        materialization_receipt_sha256=hashlib.sha256(
            (roots["B"] / "receipt.json").read_bytes()
        ).hexdigest(),
        raw_solver_manifest_sha256=hashlib.sha256(c_manifest_bytes).hexdigest(),
        scope_receipt_sha256=bundle.FROZEN_INPUT_SHA256["scope"],
        parameter_contract_sha256=integration.PARAMETER_CONTRACT_SHA256,
    )
    source_frames = []
    for entry in c_manifest["frames"]:
        raw_path = roots["C"] / "outputs" / entry["path"]
        fd = os.open(raw_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            source_frames.append(table_v2.read_native_source_frame_fd(
                fd, entry["sha256"], expected_bytes=entry["bytes"],
            ))
        finally:
            os.close(fd)

    time_values = np.asarray(
        [float.fromhex(frame.time_ieee754_hex) for frame in source_frames], dtype="<f8",
    )
    positions = []
    velocities = []
    densities = []
    for frame in source_frames:
        order = np.argsort(frame.particle_id, kind="stable")
        fluid_index = order[FLUID_IDS.astype(np.int64)]
        positions.append(frame.position_m[fluid_index].astype("<f8"))
        velocities.append(frame.velocity_m_s[fluid_index].astype("<f4"))
        densities.append(frame.density_kg_m3[fluid_index].astype("<f4"))
    position_values = np.stack(positions)
    velocity_values = np.stack(velocities)
    density_values = np.stack(densities)
    mass_f32 = np.asarray([struct.unpack("<d", FIXTURE_MASS_BYTES)[0]], dtype="<f4")[0]
    mass_values = np.full((len(source_frames), len(FLUID_IDS)), mass_f32, dtype="<f4")
    valid_values = np.ones((len(source_frames), len(FLUID_IDS)), dtype="u1")

    table_path = roots["D"] / "outputs/native-fluid-frame-table-v2.h5"
    with h5py.File(table_path, "w") as handle:
        for name, value in table_attributes.items():
            if name == "schema_version":
                handle.attrs.create(name, np.asarray(value, dtype="<u4"), dtype="<u4")
            elif name == "conversion_complete":
                handle.attrs.create(name, np.asarray(value, dtype="u1"), dtype=HDF5_BOOLEAN)
            else:
                handle.attrs.create(
                    name, value,
                    dtype=h5py.string_dtype("utf-8", length=len(value.encode("utf-8"))),
                )
        handle.create_dataset("time", data=time_values, dtype="<f8")
        handle.create_dataset("particle_id", data=FLUID_IDS, dtype="<u4")
        for name, values in (
            ("position", position_values), ("velocity", velocity_values),
            ("density", density_values), ("mass", mass_values),
        ):
            chunks = (1, len(FLUID_IDS), 3) if name == "position" or name == "velocity" else (1, len(FLUID_IDS))
            handle.create_dataset(name, data=values, dtype=values.dtype,
                                  chunks=chunks, compression="lzf")
        handle.create_dataset("valid", data=valid_values, dtype=HDF5_BOOLEAN,
                              chunks=(1, len(FLUID_IDS)), compression="lzf")

    _refresh_d_table_manifest_binding(roots)


def _verification_inputs(roots, auth_bytes, auth):
    table_review_bytes = table_review.OUTPUT.read_bytes()
    return {
        "bundle_roots": roots,
        "trusted_authorization_bytes": auth_bytes,
        "trusted_authorization_sha256": {
            stage: hashlib.sha256(payload).hexdigest()
            for stage, payload in auth_bytes.items()
        },
        "expected_authorization_envelopes": auth,
        "trusted_table_review_receipt_bytes": table_review_bytes,
        "trusted_table_review_receipt_sha256": hashlib.sha256(table_review_bytes).hexdigest(),
        "trusted_code_review_receipt_bytes": fixtures._trusted_code_review_receipt_bytes(),
        "trusted_runtime_assumption": fixtures._trusted_runtime_assumption(),
    }


def test_bundle_verifier_recomputes_a_complete_synthetic_b_c_d_table(tmp_path) -> None:
    roots, auth_bytes, auth, _d_frames = fixtures._build_chain(tmp_path)
    _freeze_b_source_bindings(roots)
    _materialize_synthetic_v2_table(roots)

    result = integration.verify_native_fluid_table_chain(**_verification_inputs(roots, auth_bytes, auth))

    assert result["case_id"] == fixtures.CASE_ID
    assert result["definition_control_bindings_match_frozen_pack_and_source_bytes"] is True
    assert result["provenance_chain_references_closed"] is True
    assert result["native_fluid_table"]["raw_frames_recomputed"] == 321
    assert result["native_fluid_table"]["fluid_particle_count"] == 1
    assert result["T1_numerical"] is False
    assert result["qualification_credit"] == 0


@pytest.mark.parametrize("field", ["definition", "control"])
def test_definition_control_binding_rejects_frozen_pack_substitution(field: str) -> None:
    row = bundle._frozen_qualification_row(fixtures.CASE_ID)
    bad_binding = {
        key: row[field][key] for key in ("path", "bytes", "sha256")
    }
    bad_binding["sha256"] = "0" * 64
    lab_fd, _absolute = bundle._open_absolute_directory(bundle.LAB)
    try:
        with pytest.raises(integration.NativeFluidBundleVerificationError,
                           match="differs from the exact frozen R008 pack row"):
            integration._check_frozen_source_binding(
                {f"{field}_binding": bad_binding}, row, field, lab_fd,
            )
    finally:
        os.close(lab_fd)


def test_bundle_verifier_requires_the_caller_trusted_table_review_binding() -> None:
    with pytest.raises(integration.NativeFluidBundleVerificationError,
                       match="review receipt SHA-256 mismatch"):
        integration.verify_native_fluid_table_chain(
            bundle_roots={},
            trusted_authorization_bytes={},
            trusted_authorization_sha256={},
            expected_authorization_envelopes={},
            trusted_table_review_receipt_bytes=b"not-a-trusted-review",
            trusted_table_review_receipt_sha256="0" * 64,
            trusted_code_review_receipt_bytes=b"",
            trusted_runtime_assumption={},
        )


def test_bundle_verifier_checks_review_bound_table_source_bytes() -> None:
    receipt = _json(table_review.OUTPUT)
    binding = next(item for item in receipt["evidence"]
                   if item["path"] == integration.TABLE_V2_CODE_RELATIVE)
    binding["sha256"] = "0" * 64
    review_bytes = json.dumps(receipt, indent=2, sort_keys=True).encode("utf-8")
    source_binding = integration._validate_table_review_document(
        review_bytes, hashlib.sha256(review_bytes).hexdigest(),
    )
    lab_fd, _absolute = bundle._open_absolute_directory(bundle.LAB)
    try:
        with pytest.raises(integration.NativeFluidBundleVerificationError,
                           match="differs from its trusted review receipt"):
            integration._verify_table_review_source(source_binding, lab_fd)
    finally:
        os.close(lab_fd)


def test_bundle_verifier_rejects_parameter_contract_hash_drift(tmp_path, monkeypatch) -> None:
    roots, auth_bytes, auth, _frames = fixtures._build_chain(tmp_path)
    _freeze_b_source_bindings(roots)
    monkeypatch.setattr(integration, "PARAMETER_CONTRACT_SHA256", "0" * 64)

    with pytest.raises(integration.NativeFluidBundleVerificationError,
                       match="parameter contract differs from its pinned SHA-256"):
        integration.verify_native_fluid_table_chain(**_verification_inputs(roots, auth_bytes, auth))


def test_bundle_verifier_rejects_mutated_d_table_binding(tmp_path) -> None:
    roots, auth_bytes, auth, _frames = fixtures._build_chain(tmp_path)
    _freeze_b_source_bindings(roots)
    d_receipt_path = roots["D"] / "receipt.json"
    d_receipt = _json(d_receipt_path)
    d_receipt["native_fluid_table_binding"]["sha256"] = "0" * 64
    _write_canonical(d_receipt_path, d_receipt)

    with pytest.raises(ValueError, match="does not equal the detached outputs manifest"):
        integration.verify_native_fluid_table_chain(**_verification_inputs(roots, auth_bytes, auth))


def test_bundle_verifier_rejects_table_root_provenance_hash_drift(tmp_path) -> None:
    roots, auth_bytes, auth, _frames = fixtures._build_chain(tmp_path)
    _freeze_b_source_bindings(roots)
    _materialize_synthetic_v2_table(roots)
    table_path = roots["D"] / "outputs/native-fluid-frame-table-v2.h5"
    with h5py.File(table_path, "r+") as handle:
        handle.attrs.modify("generated_xml_sha256", "0" * 64)
    _refresh_d_table_manifest_binding(roots)

    with pytest.raises(table_v2.NativeFluidTableError,
                       match="generated_xml_sha256 is not the exact UTF-8 byte sequence"):
        integration.verify_native_fluid_table_chain(**_verification_inputs(roots, auth_bytes, auth))


def test_bundle_verifier_rejects_post_snapshot_chain_digest_drift(tmp_path, monkeypatch) -> None:
    roots, auth_bytes, auth, _frames = fixtures._build_chain(tmp_path)
    _freeze_b_source_bindings(roots)
    _materialize_synthetic_v2_table(roots)
    original_verify_chain = bundle.verify_provenance_chain

    def changed_summary(*args, **kwargs):
        result = original_verify_chain(*args, **kwargs)
        result["manifest_sha256"]["C"] = "0" * 64
        return result

    monkeypatch.setattr(integration.bundle, "verify_provenance_chain", changed_summary)
    with pytest.raises(integration.NativeFluidBundleVerificationError,
                       match="receipt/manifest changed during v2 table verification"):
        integration.verify_native_fluid_table_chain(**_verification_inputs(roots, auth_bytes, auth))


def test_bundle_verifier_closes_current_raw_fd_if_table_check_fails_midstream(tmp_path, monkeypatch) -> None:
    roots, auth_bytes, auth, _frames = fixtures._build_chain(tmp_path)
    _freeze_b_source_bindings(roots)
    _materialize_synthetic_v2_table(roots)
    source_generators = []
    source_fds = []
    original_read_source = table_v2.read_native_source_frame_fd

    def capture_source_fd(fd, *args, **kwargs):
        source_fds.append(fd)
        return original_read_source(fd, *args, **kwargs)

    def fail_after_first_source(_table_fd, **kwargs):
        generator = kwargs["source_frames"]
        source_generators.append(generator)
        next(generator)
        raise table_v2.NativeFluidTableError("synthetic failure after first source frame")

    monkeypatch.setattr(integration.table_v2, "read_native_source_frame_fd", capture_source_fd)
    monkeypatch.setattr(integration.table_v2, "verify_native_fluid_table_fd", fail_after_first_source)
    with pytest.raises(table_v2.NativeFluidTableError,
                       match="after first source frame"):
        integration.verify_native_fluid_table_chain(**_verification_inputs(roots, auth_bytes, auth))

    assert len(source_generators) == 1 and source_generators[0].gi_frame is None
    assert len(source_fds) == 1
    with pytest.raises(OSError):
        os.fstat(source_fds[0])
