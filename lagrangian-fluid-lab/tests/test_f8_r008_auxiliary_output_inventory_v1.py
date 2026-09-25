from __future__ import annotations

import hashlib
import json
import math
import os

import pytest

from scripts import f8_r008_auxiliary_output_inventory_v1 as inventory
from scripts import f8_r008_per_case_bundle_verifier_v1 as verifier
from scripts import f8_r008_safe_bi4_decoder_v1 as decoder
from tests import test_f8_r008_head_info_finite_inventory_v1 as head_info_fixture
from tests import test_f8_r008_motion_float_finite_inventory_v1 as motion_float_fixture
from tests import test_f8_r008_part_extra_finite_inventory_v1 as part_extra_fixture
from tests import test_f8_r008_partout_runparts_diagnostic_v1 as partout_fixture
from tests import test_f8_r008_per_case_bundle_verifier_v1 as bundle_fixture


def _build_pair(
    tmp_path,
    *,
    extra_output_payloads: dict[str, bytes] | None = None,
    frame_cpart_overrides: dict[int, int] | None = None,
    frame_step_overrides: dict[int, int] | None = None,
    frame_child_part_overrides: dict[int, int] | None = None,
):
    b_root, b_auth_bytes, b_auth = bundle_fixture._build_bundle(tmp_path, "B")
    c_root, c_auth_bytes, c_auth = bundle_fixture._build_bundle(
        tmp_path, "C", extra_output_payloads=extra_output_payloads,
        frame_cpart_overrides=frame_cpart_overrides,
        frame_step_overrides=frame_step_overrides,
        frame_child_part_overrides=frame_child_part_overrides,
    )
    c_receipt_path = c_root / "receipt.json"
    c_receipt = json.loads(c_receipt_path.read_bytes())
    b_receipt_bytes = (b_root / "receipt.json").read_bytes()
    c_receipt["materialization_receipt_binding"] = {
        "path": str(b_root / "receipt.json"),
        "bytes": len(b_receipt_bytes),
        "sha256": hashlib.sha256(b_receipt_bytes).hexdigest(),
    }
    c_receipt_path.write_text(json.dumps(c_receipt, sort_keys=True) + "\n")
    return {
        "bundle_roots": {"B": b_root, "C": c_root},
        "trusted_authorization_bytes": {"B": b_auth_bytes, "C": c_auth_bytes},
        "trusted_authorization_sha256": {
            "B": hashlib.sha256(b_auth_bytes).hexdigest(),
            "C": hashlib.sha256(c_auth_bytes).hexdigest(),
        },
        "expected_authorization_envelopes": {"B": b_auth, "C": c_auth},
    }


def _part_extra_payload(*, timestep: float | None = None, step: int = 1) -> bytes:
    row = verifier._frozen_qualification_row(bundle_fixture.CASE_ID)
    time_axis = verifier.expected_time_axis_hex(row)
    selected_time = float.fromhex(time_axis[1]) if timestep is None else timestep
    return part_extra_fixture._synthetic_part_extra(
        part=1,
        case_nbound=1,
        case_nfloat=0,
        timestep=selected_time,
        step=step,
        normals=(1.0, 2.0, 3.0),
    )


def _inventory(pair):
    return inventory.inventory_c_outputs_with_part_extra(**pair)


def _partout_payload(
    *,
    velocity: tuple[float, ...] | None = None,
    time_step: float = 0.1,
) -> bytes:
    float_values = {} if velocity is None else {"Vel": velocity}
    return partout_fixture._partout_block(
        0,
        (partout_fixture._partout_record(
            1, (0,), b"\x01", float_values=float_values, time_step=time_step,
        ),),
        case_np=2,
    )


def test_inventories_every_manifest_part_extra_from_verified_b_cohorts(tmp_path) -> None:
    pair = _build_pair(tmp_path, extra_output_payloads={
        "PartExtra_0001.bi4": _part_extra_payload(),
    })

    result = _inventory(pair)

    assert result["status"] == inventory.STATUS
    assert result["stage_statuses"] == {"B": "passed", "C": "passed"}
    assert result["verified_case_populations"] == {
        "case_np": 2,
        "case_nbound": 1,
        "case_nfloat": 0,
        "derived_from": "B generated XML and initial BI4 particle cohorts",
    }
    assert result["c_output_tree_closed"] is True
    assert result["part_extra_presence_expectation_resolved"] is False
    assert result["part_extra_observed_all_floating_values_finite"] is True
    assert result["all_native_auxiliary_float_sources_scanned"] is False
    assert result["partout_runparts_diagnostic"]["status"] == "diagnostic_only_missing_or_inconsistent"
    assert result["part_extra_records"][0]["primary_frame_path"] == "frames/Part_0001.bi4"
    assert result["part_extra_records"][0]["part_extra"]["floating_value_inventory"][
        "all_floating_values_finite"
    ] is True
    classes = {entry["path"]: entry["classification"] for entry in result["output_classifications"]}
    assert classes["PartExtra_0001.bi4"] == "part_extra_normals_finite_scanned"
    assert classes["frames/Part_0001.bi4"] == "primary_native_frame"


def test_absent_optional_part_extra_does_not_mean_output_mode_was_disabled(tmp_path) -> None:
    result = _inventory(_build_pair(tmp_path))

    assert result["part_extra_records"] == []
    assert result["part_extra_presence"] == "no_manifest_member_observed_expectation_unknown"
    assert result["part_extra_presence_expectation_resolved"] is False
    assert result["part_extra_observed_all_floating_values_finite"] is None
    assert result["all_native_auxiliary_float_sources_scanned"] is False


def test_nonfinite_part_extra_is_reported_without_adjudicating_the_gate(tmp_path) -> None:
    row = verifier._frozen_qualification_row(bundle_fixture.CASE_ID)
    time_axis = verifier.expected_time_axis_hex(row)
    payload = part_extra_fixture._synthetic_part_extra(
        part=1,
        case_nbound=1,
        case_nfloat=0,
        timestep=float.fromhex(time_axis[1]),
        step=1,
        normals=(1.0, float("nan"), 3.0),
    )

    result = _inventory(_build_pair(tmp_path, extra_output_payloads={
        "PartExtra_0001.bi4": payload,
    }))

    assert result["part_extra_observed_all_floating_values_finite"] is False
    assert result["part_extra_records"][0]["part_extra"]["qualification_credit"] == 0
    assert result["native_integrity_evaluated"] is False
    assert result["T1_numerical"] is False
    assert result["readiness_pass"] is False


def test_known_but_unscanned_and_unknown_outputs_remain_visible(tmp_path) -> None:
    result = _inventory(_build_pair(tmp_path, extra_output_payloads={
        "RunPARTs.csv": b"synthetic-runparts-placeholder\n",
        "opaque-extension.bin": b"unclassified\n",
        "PartOut_p00_000.obi4": b"known-multipart-partout\n",
    }))

    assert result["known_but_unscanned_auxiliary_paths"] == [
        "PartOut_p00_000.obi4", "RunPARTs.csv",
    ]
    assert result["unclassified_output_paths"] == ["opaque-extension.bin"]
    assert result["all_present_output_paths_have_known_class"] is False
    assert result["all_native_auxiliary_float_sources_scanned"] is False


def test_manifest_bound_head_info_motion_float_files_are_finite_scanned(tmp_path) -> None:
    head = head_info_fixture._head_blob(blocks=(
        ("Fixed", 10, 0, 1), ("Fluid", 30, 0, 1),
    ))
    info = head_info_fixture._info_blob(cparts=(0, 1, 2))
    info_piece = head_info_fixture._info_blob(
        filename="PartInfo_p02.ibi4", piece=2, npiece=3, cparts=(0, 1, 2),
    )
    motion = motion_float_fixture._motion_payload()
    floating = motion_float_fixture._float_payload()
    result = _inventory(_build_pair(tmp_path, extra_output_payloads={
        "Part_Head.ibi4": head,
        "PartInfo.ibi4": info,
        "PartInfo_p02.ibi4": info_piece,
        "PartMotionRef.ibi4": motion,
        "PartFloatInfo.ibi4": floating,
    }))

    classes = {entry["path"]: entry for entry in result["output_classifications"]}
    assert classes["Part_Head.ibi4"]["classification"] == "part_head_float_values_scanned"
    assert classes["PartInfo.ibi4"]["classification"] == "part_info_float_values_scanned"
    assert classes["PartInfo_p02.ibi4"]["classification"] == "part_info_float_values_scanned"
    assert classes["PartMotionRef.ibi4"]["classification"] == "motion_ref_float_values_scanned"
    assert classes["PartFloatInfo.ibi4"]["classification"] == "floating_body_float_values_scanned"
    assert all(classes[name]["finite_scan_status"] is True for name in (
        "Part_Head.ibi4", "PartInfo.ibi4", "PartMotionRef.ibi4", "PartFloatInfo.ibi4",
    ))
    assert len(result["part_head_info_records"]) == 3
    assert len(result["motion_float_records"]) == 2
    assert result["native_auxiliary_presence"]["expectations_resolved"] is False
    assert result["all_native_auxiliary_float_sources_scanned"] is False
    assert result["qualification_credit"] == 0
    assert result["native_integrity_evaluated"] is False


def test_manifest_bound_auxiliary_nonfinite_values_are_reported_not_promoted(tmp_path) -> None:
    head = head_info_fixture._head_blob(
        blocks=(("Fixed", 10, 0, 1), ("Fluid", 30, 0, 1)),
        overrides={"Dp": float("nan")},
    )
    info = head_info_fixture._info_blob(
        cparts=(0, 1, 2), part_bad=("TimeStep", 12, float("inf")),
    )
    motion = motion_float_fixture._motion_payload(nonfinite_pos=True)
    floating = motion_float_fixture._float_payload(fpt_count=1, nonfinite_force=True)
    result = _inventory(_build_pair(tmp_path, extra_output_payloads={
        "Part_Head.ibi4": head,
        "PartInfo.ibi4": info,
        "PartMotionRef.ibi4": motion,
        "PartFloatInfo.ibi4": floating,
    }))

    classes = {entry["path"]: entry for entry in result["output_classifications"]}
    assert all(classes[name]["finite_scan_status"] is False for name in (
        "Part_Head.ibi4", "PartInfo.ibi4", "PartMotionRef.ibi4", "PartFloatInfo.ibi4",
    ))
    assert result["qualification_credit"] == 0
    assert result["native_integrity_evaluated"] is False
    assert result["T1_numerical"] is False
    assert result["readiness_pass"] is False


def test_manifest_bound_writer_scan_rechecks_held_file_identity(tmp_path, monkeypatch) -> None:
    payload = head_info_fixture._head_blob(blocks=(
        ("Fixed", 10, 0, 1), ("Fluid", 30, 0, 1),
    ))
    pair = _build_pair(tmp_path, extra_output_payloads={"Part_Head.ibi4": payload})
    path = pair["bundle_roots"]["C"] / "outputs/Part_Head.ibi4"
    original = inventory.head_info.summarize_head_info_fd

    def summarize_then_mutate(fd, filename, digest):
        result = original(fd, filename, digest)
        file_fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
        try:
            old = os.pread(file_fd, 1, 70)
            os.pwrite(file_fd, bytes((old[0] ^ 1,)), 70)
        finally:
            os.close(file_fd)
        return result

    monkeypatch.setattr(inventory.head_info, "summarize_head_info_fd", summarize_then_mutate)
    with pytest.raises(inventory.AuxiliaryOutputInventoryError, match="identity/hash"):
        _inventory(pair)


def test_manifest_bound_runparts_and_partout_are_joined_and_float_scanned(tmp_path) -> None:
    row = verifier._frozen_qualification_row(bundle_fixture.CASE_ID)
    frame_time = float.fromhex(verifier.expected_time_axis_hex(row)[1])
    pair = _build_pair(tmp_path, extra_output_payloads={
        "RunPARTs.csv": partout_fixture._runparts(
            counts={1: (1, 0, 0)}, time_steps={1: format(frame_time, ".16g")},
        ),
        "PartOut_000.obi4": _partout_payload(time_step=frame_time),
    })

    result = _inventory(pair)

    diagnostic = result["partout_runparts_diagnostic"]
    assert diagnostic["status"] == "diagnostic_only_consistent_inputs_gate_open"
    assert diagnostic["checks"]["partout_case_np_matches_verified_b"] is True
    assert diagnostic["partout_float_value_inventory"]["all_observed_floating_values_finite"] is True
    assert diagnostic["excluded_fluid_particles_zero"] == "open"
    assert result["qualification_credit"] == 0
    assert result["native_integrity_evaluated"] is False
    classes = {entry["path"]: entry for entry in result["output_classifications"]}
    assert classes["RunPARTs.csv"]["classification"] == "runparts_numeric_fields_scanned"
    assert classes["PartOut_000.obi4"]["classification"] == "partout_structure_and_float_values_scanned"
    assert classes["PartOut_000.obi4"]["finite_scan_status"] is True


def test_manifest_bound_nonfinite_partout_is_reported_not_promoted_to_gate(tmp_path) -> None:
    row = verifier._frozen_qualification_row(bundle_fixture.CASE_ID)
    frame_time = float.fromhex(verifier.expected_time_axis_hex(row)[1])
    pair = _build_pair(tmp_path, extra_output_payloads={
        "RunPARTs.csv": partout_fixture._runparts(
            counts={1: (1, 0, 0)}, time_steps={1: format(frame_time, ".16g")},
        ),
        "PartOut_000.obi4": _partout_payload(
            velocity=(float("inf"), 0.0, 0.0), time_step=frame_time,
        ),
    })

    result = _inventory(pair)

    diagnostic = result["partout_runparts_diagnostic"]
    assert diagnostic["status"] == "diagnostic_only_consistent_inputs_gate_open"
    assert diagnostic["excluded_fluid_particles_zero"] == "open"
    assert diagnostic["partout_float_value_inventory"]["nonfinite_count"] == 1
    classes = {entry["path"]: entry for entry in result["output_classifications"]}
    assert classes["PartOut_000.obi4"]["finite_scan_status"] is False
    assert result["qualification_credit"] == 0


def test_auxiliary_input_identity_is_rechecked_after_join(tmp_path, monkeypatch) -> None:
    row = verifier._frozen_qualification_row(bundle_fixture.CASE_ID)
    frame_time = float.fromhex(verifier.expected_time_axis_hex(row)[1])
    pair = _build_pair(tmp_path, extra_output_payloads={
        "RunPARTs.csv": partout_fixture._runparts(
            counts={1: (1, 0, 0)}, time_steps={1: format(frame_time, ".16g")},
        ),
        "PartOut_000.obi4": _partout_payload(time_step=frame_time),
    })
    runparts_path = pair["bundle_roots"]["C"] / "outputs/RunPARTs.csv"
    original_diagnose = inventory.partout.diagnose

    def diagnose_then_mutate_and_restore(*args, **kwargs):
        result = original_diagnose(*args, **kwargs)
        fd = os.open(runparts_path, os.O_RDWR)
        try:
            original_byte = os.pread(fd, 1, 0)
            os.pwrite(fd, bytes((original_byte[0] ^ 1,)), 0)
            os.pwrite(fd, original_byte, 0)
        finally:
            os.close(fd)
        return result

    monkeypatch.setattr(inventory.partout, "diagnose", diagnose_then_mutate_and_restore)

    with pytest.raises(inventory.AuxiliaryOutputInventoryError, match="RunPARTs.csv identity/size differs"):
        _inventory(pair)


def test_partout_time_must_match_the_manifest_bound_c_frame_axis(tmp_path) -> None:
    row = verifier._frozen_qualification_row(bundle_fixture.CASE_ID)
    frame_time = float.fromhex(verifier.expected_time_axis_hex(row)[1])
    mismatched_time = math.nextafter(frame_time, float("inf"))
    pair = _build_pair(tmp_path, extra_output_payloads={
        "RunPARTs.csv": partout_fixture._runparts(
            counts={1: (1, 0, 0)}, time_steps={1: format(mismatched_time, ".16g")},
        ),
        "PartOut_000.obi4": _partout_payload(time_step=mismatched_time),
    })

    result = _inventory(pair)

    assert result["partout_runparts_diagnostic"]["status"] == "diagnostic_only_missing_or_inconsistent"
    assert "C frame reference" in result["partout_runparts_diagnostic"]["diagnostic_findings"][0]["detail"]
    assert result["qualification_credit"] == 0


def test_final_auxiliary_recheck_rejects_changed_size_before_hash(tmp_path, monkeypatch) -> None:
    output_root = tmp_path / "outputs"
    output_root.mkdir()
    path = output_root / "RunPARTs.csv"
    path.write_bytes(b"x" * 4096)
    outputs_fd = os.open(output_root, os.O_RDONLY | os.O_DIRECTORY)
    fd, identity = inventory._open_root_output(outputs_fd, path.name)
    os.close(fd)

    def forbidden_hash():
        raise AssertionError("size mismatch must be rejected before reading/hashing")

    monkeypatch.setattr(inventory.hashlib, "sha256", forbidden_hash)
    try:
        with pytest.raises(inventory.AuxiliaryOutputInventoryError, match="identity/size differs"):
            inventory._recheck_manifest_file(
                outputs_fd, path.name, {"bytes": 1, "sha256": "0" * 64}, identity,
            )
    finally:
        os.close(outputs_fd)


def test_oversized_partout_descriptor_is_closed_on_early_rejection(tmp_path, monkeypatch) -> None:
    pair = _build_pair(tmp_path, extra_output_payloads={
        "PartOut_000.obi4": b"x" * 128,
    })
    monkeypatch.setattr(inventory.partout, "MAX_PARTOUT_TOTAL_BYTES", 64)
    opened_fds: list[int] = []
    original_open = inventory._open_root_output

    def track_open(outputs_fd: int, path: str):
        fd, identity = original_open(outputs_fd, path)
        opened_fds.append(fd)
        return fd, identity

    monkeypatch.setattr(inventory, "_open_root_output", track_open)
    with pytest.raises(inventory.AuxiliaryOutputInventoryError, match="aggregate cap"):
        _inventory(pair)

    assert len(opened_fds) == 1
    with pytest.raises(OSError):
        os.fstat(opened_fds[0])


def test_part_extra_population_must_match_verified_b_cohorts(tmp_path) -> None:
    wrong_population = part_extra_fixture._synthetic_part_extra(
        part=1, case_nbound=2, case_nfloat=0,
        step=1,
        timestep=float.fromhex(
            verifier.expected_time_axis_hex(
                verifier._frozen_qualification_row(bundle_fixture.CASE_ID),
            )[1]
        ),
        normals=(1.0, 2.0, 3.0, 4.0, 5.0, 6.0),
    )
    pair = _build_pair(tmp_path, extra_output_payloads={"PartExtra_0001.bi4": wrong_population})

    with pytest.raises(inventory.AuxiliaryOutputInventoryError, match="populations differ"):
        _inventory(pair)


def test_part_extra_time_must_match_its_same_ordinal_primary_frame(tmp_path) -> None:
    row = verifier._frozen_qualification_row(bundle_fixture.CASE_ID)
    time_axis = verifier.expected_time_axis_hex(row)
    pair = _build_pair(tmp_path, extra_output_payloads={
        "PartExtra_0001.bi4": _part_extra_payload(timestep=float.fromhex(time_axis[2])),
    })

    with pytest.raises(inventory.AuxiliaryOutputInventoryError, match="TimeStep differs"):
        _inventory(pair)


@pytest.mark.parametrize(
    ("bundle_override", "message"),
    [
        ({"frame_cpart_overrides": {1: 2}}, "Cpart differs"),
        ({"frame_child_part_overrides": {1: 0}}, "PART item does not match"),
        ({"frame_step_overrides": {1: 99}}, "Step differs"),
    ],
)
def test_part_extra_pairing_requires_primary_cpart_name_and_step(
    tmp_path, bundle_override, message,
) -> None:
    pair = _build_pair(
        tmp_path,
        extra_output_payloads={"PartExtra_0001.bi4": _part_extra_payload()},
        **bundle_override,
    )

    with pytest.raises(inventory.AuxiliaryOutputInventoryError, match=message):
        _inventory(pair)


def test_peer_frame_identity_is_rechecked_after_auxiliary_scan(tmp_path, monkeypatch) -> None:
    pair = _build_pair(tmp_path, extra_output_payloads={
        "PartExtra_0001.bi4": _part_extra_payload(),
    })
    frame_path = pair["bundle_roots"]["C"] / "outputs/frames/Part_0001.bi4"
    original_scan = inventory._raw_frame_identity

    def scan_then_change_and_restore(*args, **kwargs):
        identity = original_scan(*args, **kwargs)
        fd = os.open(frame_path, os.O_RDWR)
        try:
            offset = os.fstat(fd).st_size - 1
            original_byte = os.pread(fd, 1, offset)
            os.pwrite(fd, bytes((original_byte[0] ^ 1,)), offset)
            os.pwrite(fd, original_byte, offset)
        finally:
            os.close(fd)
        return identity

    monkeypatch.setattr(inventory, "_raw_frame_identity", scan_then_change_and_restore)

    with pytest.raises(inventory.AuxiliaryOutputInventoryError, match="peer-frame inode/bytes"):
        _inventory(pair)


@pytest.mark.parametrize(("name", "type_code"), [
    ("CaseNfloat", 10), ("Cpart", 8), ("Step", 8),
])
def test_native_integer_reader_rejects_duplicate_metadata(name: str, type_code: int) -> None:
    value = decoder.ValueRecord(name=name, type_code=type_code, value=1)
    item = decoder.ItemRecord(
        name="JPartDataBi4", hidden=False, hide_values=False,
        float_format="%.7E", double_format="%.15E",
        values=(value, value), arrays=(), children=(),
    )

    with pytest.raises(inventory.AuxiliaryOutputInventoryError, match="unique unsigned integer"):
        inventory._one_native_integer(item, name, type_code)


def test_c_bundle_must_bind_the_exact_b_materialization_receipt(tmp_path) -> None:
    pair = _build_pair(tmp_path)
    c_root = pair["bundle_roots"]["C"]
    receipt = json.loads((c_root / "receipt.json").read_bytes())
    receipt["materialization_receipt_binding"]["sha256"] = "0" * 64
    (c_root / "receipt.json").write_text(json.dumps(receipt, sort_keys=True) + "\n")

    with pytest.raises(inventory.AuxiliaryOutputInventoryError, match="C-to-B materialization receipt"):
        _inventory(pair)
