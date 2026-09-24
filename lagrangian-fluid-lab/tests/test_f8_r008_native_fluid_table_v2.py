from __future__ import annotations

import hashlib
import os
from pathlib import Path
import struct

import h5py
import numpy as np
import pytest

from scripts.f8_r008_native_fluid_table_v2 import (
    NativeFluidTableError,
    NativeSourceFrame,
    expected_root_attributes,
    read_native_source_frame_fd,
    verify_native_fluid_table_fd,
)
from scripts import f8_r008_safe_bi4_decoder_v1 as decoder


CASE_ID = "space-q0-dp0p0090"
HDF5_BOOLEAN = h5py.enum_dtype({"FALSE": 0, "TRUE": 1}, basetype=np.dtype("u1"))
FLUID_IDS = np.asarray([0, 2, 3], dtype="<u4")
RAW_IDS = np.asarray([3, 1, 0, 2], dtype="<u4")
MASS_BYTES = struct.pack("<d", 0.25)
ATTRS = expected_root_attributes(
    case_id=CASE_ID,
    generated_xml_sha256="1" * 64,
    definition_sha256="2" * 64,
    materialization_receipt_sha256="3" * 64,
    raw_solver_manifest_sha256="4" * 64,
    scope_receipt_sha256="5" * 64,
    parameter_contract_sha256="6" * 64,
)


def _frame(time_s: float, *, mass_bytes: bytes = MASS_BYTES,
           particle_id: np.ndarray = RAW_IDS) -> NativeSourceFrame:
    base = np.arange(12, dtype="<f4").reshape(4, 3)
    return NativeSourceFrame(
        time_ieee754_hex=float(time_s).hex(),
        particle_id=particle_id.copy(),
        position_m=(base + np.float32(time_s)).astype("<f4"),
        velocity_m_s=(base / np.float32(10) + np.float32(time_s)).astype("<f4"),
        density_kg_m3=(np.asarray([1000, 1001, 1002, 1003], dtype="<f4") + np.float32(time_s)),
        massfluid_binary64_le=mass_bytes,
        case_np=4,
    )


def _expected_tables(frames: list[NativeSourceFrame]) -> dict[str, np.ndarray]:
    order = np.argsort(RAW_IDS, kind="stable")
    indices = order[FLUID_IDS.astype(np.int64)]
    massfluid = struct.unpack("<d", frames[0].massfluid_binary64_le)[0]
    mass_f32 = np.asarray([massfluid], dtype="<f4")[0]
    return {
        "time": np.asarray([float.fromhex(frame.time_ieee754_hex) for frame in frames], dtype="<f8"),
        "particle_id": FLUID_IDS,
        "position": np.stack([frame.position_m[indices].astype("<f8") for frame in frames]),
        "velocity": np.stack([frame.velocity_m_s[indices].astype("<f4") for frame in frames]),
        "density": np.stack([frame.density_kg_m3[indices].astype("<f4") for frame in frames]),
        "mass": np.full((len(frames), len(FLUID_IDS)), mass_f32, dtype="<f4"),
        "valid": np.ones((len(frames), len(FLUID_IDS)), dtype="?"),
    }


def _write_table(path: Path, frames: list[NativeSourceFrame], *,
                 mutate: tuple[str, str] | None = None) -> None:
    arrays = _expected_tables(frames)
    if mutate is not None:
        name, kind = mutate
        if kind == "wrong_value":
            arrays[name] = arrays[name].copy()
            if name == "position":
                arrays[name][0, 0, 0] += 1.0
            elif name in {"velocity", "density", "mass"}:
                arrays[name][0, 0] += 1.0
            elif name == "valid":
                arrays[name][0, 0] = False
        elif kind == "wrong_id_order":
            arrays[name] = arrays[name][::-1].copy()
        elif kind == "wrong_time":
            arrays[name] = arrays[name].copy()
            arrays[name][1] += 0.125

    with h5py.File(path, "x") as handle:
        for name, value in ATTRS.items():
            if name == "schema_version":
                handle.attrs.create(name, np.asarray(value, dtype="<u4"), dtype="<u4")
            elif name == "conversion_complete":
                handle.attrs.create(name, np.asarray(value, dtype="u1"), dtype=HDF5_BOOLEAN)
            else:
                encoded = value.encode("utf-8")
                handle.attrs.create(
                    name, value,
                    dtype=h5py.string_dtype(encoding="utf-8", length=len(encoded)),
                )
        handle.create_dataset("time", data=arrays["time"], dtype="<f8")
        handle.create_dataset("particle_id", data=arrays["particle_id"], dtype="<u4")
        for name in ("position", "velocity", "density", "mass", "valid"):
            data = arrays[name]
            chunk_particles = min(len(FLUID_IDS), 65536)
            chunks = ((1, chunk_particles, 3) if name in {"position", "velocity"}
                      else (1, chunk_particles))
            dataset_dtype = HDF5_BOOLEAN if name == "valid" else data.dtype
            dataset_data = data.astype("u1") if name == "valid" else data
            handle.create_dataset(name, data=dataset_data, dtype=dataset_dtype,
                                  chunks=chunks, compression="lzf")


def _verify(path: Path, frames: list[NativeSourceFrame], *,
            fluid_ids: np.ndarray = FLUID_IDS, expected_mass: bytes = MASS_BYTES,
            expected_attributes: dict = ATTRS) -> dict:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        size = os.fstat(fd).st_size
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        return verify_native_fluid_table_fd(
            fd,
            expected_table_bytes=size,
            expected_table_sha256=sha,
            expected_attributes=expected_attributes,
            expected_time_axis_hex=[frame.time_ieee754_hex for frame in frames],
            expected_fluid_ids=fluid_ids,
            expected_case_np=4,
            initial_massfluid_binary64_le=expected_mass,
            source_frames=frames,
        )
    finally:
        os.close(fd)


def _string(value: str | bytes) -> bytes:
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    return struct.pack("<I", len(raw)) + raw


def _value(name: str, type_code: int, payload: bytes) -> bytes:
    return _string(name) + struct.pack("<i", type_code) + payload


def _array(name: str, type_code: int, payload: bytes) -> bytes:
    element_bytes = {8: 4, 11: 4, 22: 12, 23: 24}[type_code]
    count = len(payload) // element_bytes
    definition = (_string(decoder.CODE_ARRAY) + _string(name)
                  + struct.pack("<iiII", 0, type_code, count, len(payload)))
    return struct.pack("<I", len(definition)) + definition + payload


def _item(name: str, *, values: tuple[bytes, ...] = (), arrays: tuple[bytes, ...] = (),
          children: tuple[bytes, ...] = ()) -> bytes:
    values_block = b""
    if values:
        values_block = (_string(decoder.CODE_VALUES) + struct.pack("<I", len(values))
                        + b"".join(values))
    definition = (
        _string(decoder.CODE_ITEM) + _string(name) + struct.pack("<ii", 0, 0)
        + _string("%.7E") + _string("%.15E")
        + struct.pack("<III", len(arrays), len(children), len(values_block))
    )
    return (struct.pack("<I", len(definition)) + definition + values_block
            + b"".join(arrays) + b"".join(children))


def _synthetic_bi4(time_s: float, *, position_type: str = "Posd") -> bytes:
    ids = np.asarray([3, 1, 0, 2], dtype="<u4")
    pos = np.arange(12, dtype="<f8").reshape(4, 3)
    vel = np.arange(12, dtype="<f4").reshape(4, 3) / np.float32(10)
    rho = np.asarray([1000, 1001, 1002, 1003], dtype="<f4")
    if position_type == "Pos":
        pos_array = _array("Pos", 22, pos.astype("<f4").tobytes())
    else:
        pos_array = _array("Posd", 23, pos.tobytes())
    arrays = (
        _array("Idp", 8, ids.tobytes()),
        pos_array,
        _array("Vel", 22, vel.tobytes()),
        _array("Rhop", 11, rho.tobytes()),
    )
    part = _item("PART_0000", values=(
        _value("TimeStep", 12, struct.pack("<d", time_s)),
        _value("Npok", 8, struct.pack("<I", 4)),
    ), arrays=arrays)
    root = _item("JPartDataBi4", values=(
        _value("CaseNp", 10, struct.pack("<Q", 4)),
        _value("CaseNfluid", 10, struct.pack("<Q", 3)),
        _value("CaseNfixed", 10, struct.pack("<Q", 1)),
        _value("CaseNmoving", 10, struct.pack("<Q", 0)),
        _value("CaseNfloat", 10, struct.pack("<Q", 0)),
        _value("MassFluid", 12, MASS_BYTES),
    ), children=(part,))
    title = decoder.FILE_PREFIX + b" " * (58 - len(decoder.FILE_PREFIX)) + b"\n\0"
    return title + b"\0\0\0\0" + root


def test_semantic_verifier_accepts_exact_full_axis_fluid_projection_and_sources(tmp_path) -> None:
    frames = [_frame(0.0), _frame(0.5)]
    path = tmp_path / "native-fluid-frame-table-v2.h5"
    _write_table(path, frames)

    result = _verify(path, frames)

    assert result["time_rows"] == 2
    assert result["fluid_particle_count"] == 3
    assert result["raw_frames_recomputed"] == 2
    assert result["position_velocity_density_mass_recomputed"] is True
    assert result["T1_numerical"] is False
    assert result["qualification_credit"] == 0


def test_bounded_bi4_reader_recomputes_required_native_source_arrays(tmp_path) -> None:
    payload = _synthetic_bi4(0.5)
    path = tmp_path / "source.bi4"
    path.write_bytes(payload)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        frame = read_native_source_frame_fd(
            fd, hashlib.sha256(payload).hexdigest(), expected_bytes=len(payload),
        )
    finally:
        os.close(fd)

    assert frame.time_ieee754_hex == 0.5.hex()
    assert frame.case_np == 4
    assert frame.particle_id.tolist() == [3, 1, 0, 2]
    assert frame.position_m.dtype == np.dtype("<f8")
    assert frame.velocity_m_s.dtype == np.dtype("<f4")
    assert frame.density_kg_m3.tolist() == [1000.0, 1001.0, 1002.0, 1003.0]
    assert frame.massfluid_binary64_le == MASS_BYTES


def test_bounded_bi4_reader_accepts_native_float32_pos_and_promotes_exactly(tmp_path) -> None:
    payload = _synthetic_bi4(0.5, position_type="Pos")
    path = tmp_path / "source-float32-pos.bi4"
    path.write_bytes(payload)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        frame = read_native_source_frame_fd(fd, hashlib.sha256(payload).hexdigest())
    finally:
        os.close(fd)
    assert frame.position_m.dtype == np.dtype("<f4")
    assert np.array_equal(frame.position_m.astype("<f8"), np.arange(12, dtype="<f4").reshape(4, 3))


@pytest.mark.parametrize("dataset", ["position", "velocity", "density", "mass", "valid"])
def test_semantic_verifier_rejects_any_field_not_recomputed_from_native_frames(tmp_path, dataset) -> None:
    frames = [_frame(0.0), _frame(0.5)]
    path = tmp_path / f"wrong-{dataset}.h5"
    _write_table(path, frames, mutate=(dataset, "wrong_value"))

    with pytest.raises(NativeFluidTableError):
        _verify(path, frames)


@pytest.mark.parametrize("dataset,kind", [("time", "wrong_time"), ("particle_id", "wrong_id_order")])
def test_semantic_verifier_rejects_time_or_particle_axis_drift(tmp_path, dataset, kind) -> None:
    frames = [_frame(0.0), _frame(0.5)]
    path = tmp_path / f"wrong-{dataset}.h5"
    _write_table(path, frames, mutate=(dataset, kind))

    with pytest.raises(NativeFluidTableError):
        _verify(path, frames)


def test_semantic_verifier_requires_complete_unique_raw_id_universe(tmp_path) -> None:
    frames = [_frame(0.0), _frame(0.5, particle_id=np.asarray([3, 1, 1, 2], dtype="<u4"))]
    path = tmp_path / "raw-id-gap.h5"
    _write_table(path, frames)

    with pytest.raises(NativeFluidTableError, match="missing, duplicate, unknown, or changed IDs"):
        _verify(path, frames)


def test_massfluid_must_match_binary64_before_float32_rounding(tmp_path) -> None:
    frames = [_frame(0.0), _frame(0.5, mass_bytes=struct.pack("<d", 0.2500000001))]
    path = tmp_path / "massfluid-binary64-drift.h5"
    _write_table(path, [_frame(0.0), _frame(0.5)])

    with pytest.raises(NativeFluidTableError, match="MassFluid binary64 bits differ"):
        _verify(path, frames)


@pytest.mark.parametrize(
    "mass_value,expected_f32",
    [
        (1.0 + 2.0**-24, np.float32(1.0)),
        (1.0 + 3.0 * 2.0**-24, np.float32(1.0 + 2.0**-22)),
    ],
)
def test_massfluid_conversion_uses_ieee754_round_ties_to_even(
    tmp_path, mass_value: float, expected_f32: np.float32,
) -> None:
    mass_bytes = struct.pack("<d", mass_value)
    frames = [_frame(0.0, mass_bytes=mass_bytes), _frame(0.5, mass_bytes=mass_bytes)]
    path = tmp_path / "mass-tie-even.h5"
    _write_table(path, frames)
    result = _verify(path, frames, expected_mass=mass_bytes)
    assert result["position_velocity_density_mass_recomputed"] is True
    arrays = _expected_tables(frames)
    assert np.all(arrays["mass"] == expected_f32)


def test_semantic_verifier_rejects_density_that_is_not_positive_finite(tmp_path) -> None:
    source = _frame(0.0)
    density = source.density_kg_m3.copy()
    density[2] = np.nan
    frames = [NativeSourceFrame(
        source.time_ieee754_hex, source.particle_id, source.position_m,
        source.velocity_m_s, density, source.massfluid_binary64_le, source.case_np,
    ), _frame(0.5)]
    path = tmp_path / "density-nan.h5"
    _write_table(path, [_frame(0.0), _frame(0.5)])

    with pytest.raises(NativeFluidTableError, match="density is not positive finite"):
        _verify(path, frames)


def test_semantic_verifier_rejects_table_hash_and_shape_mismatch(tmp_path) -> None:
    frames = [_frame(0.0), _frame(0.5)]
    path = tmp_path / "shape-mismatch.h5"
    _write_table(path, frames)

    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        with pytest.raises(NativeFluidTableError, match="D output manifest"):
            verify_native_fluid_table_fd(
                fd, expected_table_bytes=os.fstat(fd).st_size,
                expected_table_sha256="0" * 64, expected_attributes=ATTRS,
                expected_time_axis_hex=[frame.time_ieee754_hex for frame in frames],
                expected_fluid_ids=FLUID_IDS, expected_case_np=4,
                initial_massfluid_binary64_le=MASS_BYTES, source_frames=frames,
            )
    finally:
        os.close(fd)

    with h5py.File(path, "r+") as handle:
        del handle["density"]
        handle.create_dataset("density", data=np.ones((1, 3), dtype="<f4"),
                              chunks=(1, 3), compression="lzf")
    with pytest.raises(NativeFluidTableError, match="wrong dimensions"):
        _verify(path, frames)


@pytest.mark.parametrize("target", ["root_boolean", "valid_boolean"])
def test_verifier_rejects_noncanonical_signed_hdf5_boolean_enum(tmp_path, target) -> None:
    frames = [_frame(0.0), _frame(0.5)]
    path = tmp_path / f"signed-bool-{target}.h5"
    _write_table(path, frames)
    with h5py.File(path, "r+") as handle:
        if target == "root_boolean":
            del handle.attrs["conversion_complete"]
            handle.attrs.create("conversion_complete", np.asarray(True, dtype="?"), dtype="?")
        else:
            del handle["valid"]
            handle.create_dataset(
                "valid", data=np.ones((2, len(FLUID_IDS)), dtype="?"), dtype="?",
                chunks=(1, len(FLUID_IDS)), compression="lzf",
            )
    with pytest.raises(NativeFluidTableError, match="exact boolean enum|FALSE=0/TRUE=1"):
        _verify(path, frames)


def test_verifier_rejects_vlen_attributes_and_non_scalar_numeric_attributes(tmp_path) -> None:
    frames = [_frame(0.0), _frame(0.5)]
    path = tmp_path / "unbounded-attributes.h5"
    _write_table(path, frames)
    with h5py.File(path, "r+") as handle:
        del handle.attrs["identity_key"]
        handle.attrs.create("identity_key", "particle_id", dtype=h5py.string_dtype("utf-8"))
    with pytest.raises(NativeFluidTableError, match="fixed-size scalar UTF-8"):
        _verify(path, frames)

    _write_table(path := tmp_path / "nonscalar-version.h5", frames)
    with h5py.File(path, "r+") as handle:
        del handle.attrs["schema_version"]
        handle.attrs.create("schema_version", np.asarray([3], dtype="<u4"), dtype="<u4")
    with pytest.raises(NativeFluidTableError, match="little-endian uint32 scalar"):
        _verify(path, frames)


def test_verifier_rejects_missing_particle_data_chunks(tmp_path) -> None:
    frames = [_frame(0.0), _frame(0.5)]
    path = tmp_path / "missing-chunk.h5"
    _write_table(path, frames)
    with h5py.File(path, "r+") as handle:
        del handle["mass"]
        handle.create_dataset("mass", shape=(2, len(FLUID_IDS)), dtype="<f4",
                              chunks=(1, len(FLUID_IDS)), compression="lzf")
    with pytest.raises(NativeFluidTableError, match="exactly one complete chunk"):
        _verify(path, frames)


@pytest.mark.parametrize("link_kind", ["hard", "group", "soft", "external"])
def test_verifier_rejects_every_unregistered_root_link_kind(tmp_path, link_kind: str) -> None:
    frames = [_frame(0.0), _frame(0.5)]
    path = tmp_path / f"extra-root-{link_kind}.h5"
    _write_table(path, frames)
    with h5py.File(path, "r+") as handle:
        if link_kind == "hard":
            handle["rogue"] = handle["time"]
        elif link_kind == "group":
            handle.create_group("rogue")
        elif link_kind == "soft":
            handle["rogue"] = h5py.SoftLink("/time")
        else:
            handle["rogue"] = h5py.ExternalLink("missing-target.h5", "/time")
    with pytest.raises(NativeFluidTableError, match="root object or attribute count"):
        _verify(path, frames)


def test_verifier_rejects_matching_caller_and_table_overrides_of_fixed_contract(tmp_path) -> None:
    frames = [_frame(0.0), _frame(0.5)]
    path = tmp_path / "caller-overrides-schema.h5"
    _write_table(path, frames)
    with h5py.File(path, "r+") as handle:
        del handle.attrs["schema"]
        value = "core.cfd.v2"
        handle.attrs.create("schema", value, dtype=h5py.string_dtype("utf-8", length=len(value)))
    overridden = {**ATTRS, "schema": "core.cfd.v2"}
    with pytest.raises(NativeFluidTableError, match="override a fixed v2 contract value"):
        _verify(path, frames, expected_attributes=overridden)


@pytest.mark.parametrize("target", ["root_boolean", "valid_boolean"])
def test_verifier_rejects_noncanonical_raw_enum_value_two(tmp_path, target: str) -> None:
    frames = [_frame(0.0), _frame(0.5)]
    path = tmp_path / f"enum-value-two-{target}.h5"
    _write_table(path, frames)
    with h5py.File(path, "r+") as handle:
        if target == "root_boolean":
            attr = handle.attrs.get_id("conversion_complete")
            attr.write(np.asarray(2, dtype="u1"), mtype=h5py.h5t.NATIVE_UINT8)
            assert bool(handle.attrs["conversion_complete"]) is True
        else:
            dataset = handle["valid"]
            file_space = dataset.id.get_space()
            file_space.select_hyperslab((0, 0), (1, 1))
            memory_space = h5py.h5s.create_simple((1,))
            dataset.id.write(memory_space, file_space, np.asarray([2], dtype="u1"),
                             mtype=h5py.h5t.NATIVE_UINT8)
            assert bool(dataset[0, 0]) is True
    with pytest.raises(NativeFluidTableError, match="raw enum value is not exactly TRUE=1|non-TRUE enum value"):
        _verify(path, frames)
