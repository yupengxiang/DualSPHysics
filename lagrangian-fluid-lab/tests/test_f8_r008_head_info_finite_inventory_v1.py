from __future__ import annotations

import hashlib
import math
import os
import struct
import tempfile

import pytest

from scripts import f8_r008_head_info_finite_inventory_v1 as inventory


_PACK = {
    2: "<i", 3: "<b", 4: "<B", 5: "<h", 6: "<H", 7: "<i", 8: "<I",
    9: "<q", 10: "<Q", 11: "<f", 12: "<d", 20: "<iii", 21: "<III",
    22: "<fff", 23: "<ddd",
}


def _string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return struct.pack("<I", len(encoded)) + encoded


def _encode_value(name: str, type_code: int, value) -> bytes:
    data = _string(name) + struct.pack("<i", type_code)
    if type_code == 1:
        return data + _string(value)
    if type_code == 2:
        value = int(value)
    values = value if type_code in (20, 21, 22, 23) else (value,)
    return data + struct.pack(_PACK[type_code], *values)


def _encode_item(
    name: str,
    values: list[tuple[str, int, object]],
    *,
    children: tuple[bytes, ...] = (),
    arrays: int = 0,
) -> bytes:
    values_data = _string("\nVALUES") + struct.pack("<I", len(values))
    values_data += b"".join(_encode_value(*entry) for entry in values)
    definition = (
        _string("\nITEM\n") + _string(name) + struct.pack("<ii", 0, 0)
        + _string("%.7E") + _string("%.15E")
        + struct.pack("<III", arrays, len(children), len(values_data))
    )
    return struct.pack("<I", len(definition)) + definition + values_data + b"".join(children)


def _file(filecode: str, *items: bytes) -> bytes:
    header = filecode.encode("ascii").ljust(58, b" ") + b"\n\0" + b"\0" * 4
    assert len(header) == inventory.HEADER_BYTES
    return header + b"".join(items)


def _default_value(type_code: int):
    if type_code == 1:
        return "synthetic"
    if type_code == 2:
        return False
    if type_code in (22, 23):
        return (1.25, 2.5, 3.75)
    if type_code in (20, 21):
        return (1, 2, 3)
    if type_code in (11, 12):
        return 1.25
    return 1


def _values(schema: dict[str, int]) -> list[tuple[str, int, object]]:
    return [(name, type_code, _default_value(type_code))
            for name, type_code in schema.items()]


def _head_blob(
    *,
    overrides: dict[str, object] | None = None,
    extra: tuple[str, int, object] | None = None,
    duplicate: str | None = None,
    wrong_type: tuple[str, int, object] | None = None,
    arrays: int = 0,
    blocks: tuple[tuple[str, int, int, int], ...] = (
        ("Fixed", 10, 0, 4), ("Floating", 20, 0, 2), ("Fluid", 30, 0, 8),
    ),
    declared_blocks: int | None = None,
) -> bytes:
    root_values = _values(inventory.HEAD_TYPES)
    values_by_name = {name: index for index, (name, _type, _value) in enumerate(root_values)}
    root_values[values_by_name["FmtVersion"]] = ("FmtVersion", 8, 180324)
    counts = {"Fixed": 0, "Moving": 0, "Floating": 0, "Fluid": 0}
    for kind, _mk, _mktype, count in blocks:
        counts[kind] += count
    root_overrides = {
        "Npiece": 1,
        "CaseNp": sum(counts.values()),
        "CaseNfixed": counts["Fixed"],
        "CaseNmoving": counts["Moving"],
        "CaseNfloat": counts["Floating"],
        "CaseNfluid": counts["Fluid"],
    }
    root_overrides.update(overrides or {})
    for name, value in root_overrides.items():
        index = values_by_name[name]
        root_values[index] = (name, root_values[index][1], value)
    if extra:
        root_values.append(extra)
    if duplicate:
        root_values.append(root_values[values_by_name[duplicate]])
    if wrong_type:
        index = values_by_name[wrong_type[0]]
        root_values[index] = wrong_type

    block_items = []
    for index, (kind, mk, mktype, count) in enumerate(blocks):
        block_values = [
            ("Type", 1, kind), ("Mk", 8, mk), ("MkType", 8, mktype), ("Count", 8, count),
        ]
        block_items.append(_encode_item(f"MkBlock_{index:03d}", block_values))
    child_count = len(block_items) if declared_blocks is None else declared_blocks
    mkblocks = _encode_item("MkBlocks", [("Count", 8, child_count)], children=tuple(block_items))
    return _file(inventory.FILECODE_HEAD,
                 _encode_item("JPartDataHead", root_values, children=(mkblocks,), arrays=arrays))


def _info_root_values(*, piece: int = 0, npiece: int = 1) -> list[tuple[str, int, object]]:
    values = _values(inventory.INFO_ROOT_TYPES)
    index = {name: at for at, (name, _type, _value) in enumerate(values)}
    values[index["Piece"]] = ("Piece", 8, piece)
    values[index["Npiece"]] = ("Npiece", 8, npiece)
    return values


def _info_part_values(
    cpart: int,
    *,
    optional_writer_fields: bool = False,
    bad: tuple[str, int, object] | None = None,
    duplicate: str | None = None,
    arrays: int = 0,
) -> list[tuple[str, int, object]]:
    schema = {**inventory.PART_REQUIRED_TYPES, **inventory.PART_INFO_REQUIRED_TYPES}
    values = _values(schema)
    positions = {name: index for index, (name, _type, _value) in enumerate(values)}
    values[positions["Cpart"]] = ("Cpart", 8, cpart)
    values[positions["Step"]] = ("Step", 8, 100 + cpart)
    if optional_writer_fields:
        values.extend([
            ("NpTotal", 10, 1000), ("IdMax", 10, 999),
            ("SymplecticDtPre", 12, 0.01), ("DemDtForce", 12, 0.02),
            ("dterror", 12, 0.0), ("nctalloc", 9, 4), ("nctused", 9, 3),
            ("npalloc", 9, 1200), ("npused", 9, 1000),
            ("subdomain_count", 8, 2),
            ("subdomainmin_00", 23, (0.0, 0.0, 0.0)),
            ("subdomainmax_00", 23, (1.0, 1.0, 1.0)),
            ("subdomainmin_01", 23, (1.0, 0.0, 0.0)),
            ("subdomainmax_01", 23, (2.0, 1.0, 1.0)),
        ])
    if bad:
        bad_position = next((index for index, entry in enumerate(values)
                             if entry[0] == bad[0]), None)
        if bad_position is not None:
            values[bad_position] = bad
        else:
            values.append(bad)
    if duplicate:
        values.append(values[positions[duplicate]])
    return values


def _info_blob(
    *,
    filename: str = "PartInfo.ibi4",
    piece: int = 0,
    npiece: int = 1,
    cparts: tuple[int, ...] = (1, 2),
    optional_writer_fields: bool = False,
    part_bad: tuple[str, int, object] | None = None,
    duplicate_part_field: str | None = None,
    root_extra: tuple[str, int, object] | None = None,
    root_duplicate: str | None = None,
    part_arrays: int = 0,
    root_arrays: int = 0,
) -> bytes:
    root_values = _info_root_values(piece=piece, npiece=npiece)
    if root_extra:
        root_values.append(root_extra)
    if root_duplicate:
        at = next(i for i, (name, _type, _value) in enumerate(root_values)
                  if name == root_duplicate)
        root_values.append(root_values[at])
    root = _encode_item("JPartDataBi4", root_values, arrays=root_arrays)
    rows = tuple(
        _encode_item(
            f"PART_{cpart:04d}",
            _info_part_values(
                cpart,
                optional_writer_fields=optional_writer_fields,
                bad=part_bad if index == 0 else None,
                duplicate=duplicate_part_field if index == 0 else None,
            ),
            arrays=part_arrays if index == 0 else 0,
        )
        for index, cpart in enumerate(cparts)
    )
    assert filename == "PartInfo.ibi4" or filename == f"PartInfo_p{piece:02d}.ibi4"
    return _file(inventory.FILECODE_INFO, root, *rows)


def _summarize(blob: bytes, filename: str = "Part_Head.ibi4", *, digest: str | None = None):
    with tempfile.NamedTemporaryFile() as stream:
        stream.write(blob)
        stream.flush()
        return inventory.summarize_head_info_fd(
            stream.fileno(), filename, digest or hashlib.sha256(blob).hexdigest(),
        )


def test_part_head_finite_inventory_scans_all_native_float_and_double_fields():
    result = _summarize(_head_blob())

    assert result["schema"] == inventory.SCHEMA
    assert result["status"] == inventory.STATUS_FINITE
    assert result["kind"] == "Part_Head"
    assert result["native_structure"]["mk_block_count"] == 3
    assert result["native_structure"]["particle_counts_by_type"] == {
        "Fixed": 4, "Moving": 0, "Floating": 2, "Fluid": 8,
    }
    assert result["floating_value_inventory"]["total_component_count"] == 34
    assert result["floating_value_inventory"]["all_components_finite"] is True
    assert result["arrays_present"] == 0
    assert result["qualification_credit"] == 0
    assert result["authority"] == {
        "granted": False, "native_integrity": False, "t1": False, "readiness": False,
    }


@pytest.mark.parametrize("field,value", [
    ("Data2dPosY", float("nan")),
    ("CasePosMin", (0.0, float("inf"), 1.0)),
    ("ViscoValue", float("-inf")),
    ("Gravity", (0.0, float("nan"), 1.0)),
])
def test_part_head_reports_nonfinite_scalar_and_vector_components(field, value):
    result = _summarize(_head_blob(overrides={field: value}))
    report = result["floating_value_inventory"]
    assert result["status"] == inventory.STATUS_NONFINITE
    assert report["nonfinite_component_count"] >= 1
    assert report["all_components_finite"] is False
    assert result["qualification_credit"] == 0
    assert result["authority"]["granted"] is False


def test_part_head_rejects_unknown_wrong_typed_duplicate_and_population_mismatch():
    with pytest.raises(inventory.HeadInfoFiniteInventoryError, match="unknown"):
        _summarize(_head_blob(extra=("Unreviewed", 12, 1.0)))
    with pytest.raises(inventory.HeadInfoFiniteInventoryError, match="native type"):
        _summarize(_head_blob(wrong_type=("ViscoValue", 12, 1.0)))
    with pytest.raises(inventory.HeadInfoFiniteInventoryError, match="duplicate"):
        _summarize(_head_blob(duplicate="Dp"))
    with pytest.raises(inventory.HeadInfoFiniteInventoryError, match="population sums"):
        _summarize(_head_blob(overrides={"CaseNfluid": 999}))


def test_part_head_mkblocks_shape_and_bounds_are_strict(monkeypatch):
    with pytest.raises(inventory.HeadInfoFiniteInventoryError, match="Count differs"):
        _summarize(_head_blob(declared_blocks=2))
    monkeypatch.setattr(inventory, "MAX_HEAD_BLOCKS", 1)
    with pytest.raises(inventory.HeadInfoFiniteInventoryError, match="frozen bound"):
        _summarize(_head_blob())


def test_part_head_rejects_unexpected_arrays_and_wrong_filecode_or_filename():
    with pytest.raises(inventory.HeadInfoFiniteInventoryError, match="arrays"):
        _summarize(_head_blob(arrays=1))
    wrong_code = _file("#FileJBD WrongCode", _encode_item("JPartDataHead", []))
    with pytest.raises(inventory.HeadInfoFiniteInventoryError, match="filecode"):
        _summarize(wrong_code)
    with pytest.raises(inventory.HeadInfoFiniteInventoryError, match="filename"):
        _summarize(_head_blob(), "../Part_Head.ibi4")


def test_partinfo_accepts_writer_list_append_records_and_piece_filename_binding():
    single = _summarize(_info_blob(), "PartInfo.ibi4")
    assert single["kind"] == "PartInfo"
    assert single["native_structure"]["record_count"] == 2
    assert single["native_structure"]["cpart_values"] == [1, 2]
    assert single["floating_value_inventory"]["all_components_finite"] is True
    assert single["arrays_present"] == 0

    piece_name = "PartInfo_p01.ibi4"
    piece = _summarize(
        _info_blob(filename=piece_name, piece=1, npiece=3, cparts=(20,)), piece_name,
    )
    assert piece["native_structure"]["piece"] == 1
    assert piece["native_structure"]["piece_count"] == 3
    with pytest.raises(inventory.HeadInfoFiniteInventoryError, match="filename"):
        _summarize(_info_blob(piece=1, npiece=3, cparts=(1,)), "PartInfo.ibi4")


def test_partinfo_reports_nonfinite_and_accepts_only_source_proven_optional_fields():
    result = _summarize(
        _info_blob(optional_writer_fields=True, part_bad=("dterror", 12, float("nan"))),
        "PartInfo.ibi4",
    )
    report = result["floating_value_inventory"]
    assert result["status"] == inventory.STATUS_NONFINITE
    assert report["nonfinite_component_count"] == 1
    assert any(record["metadata_name"] == "subdomainmin_00" for record in report["records"])
    assert any(record["metadata_name"] == "SymplecticDtPre" for record in report["records"])


def test_partinfo_rejects_unknown_wrong_type_duplicate_and_bad_appended_item():
    with pytest.raises(inventory.HeadInfoFiniteInventoryError, match="unknown"):
        _summarize(_info_blob(part_bad=("mystery", 12, 1.0)), "PartInfo.ibi4")
    with pytest.raises(inventory.HeadInfoFiniteInventoryError, match="native type"):
        _summarize(_info_blob(part_bad=("TimeStep", 11, 1.0)), "PartInfo.ibi4")
    with pytest.raises(inventory.HeadInfoFiniteInventoryError, match="duplicate"):
        _summarize(_info_blob(duplicate_part_field="TimeStep"), "PartInfo.ibi4")
    duplicate_rows = _info_blob(cparts=(3, 3))
    with pytest.raises(inventory.HeadInfoFiniteInventoryError, match="duplicated"):
        _summarize(duplicate_rows, "PartInfo.ibi4")
    with pytest.raises(inventory.HeadInfoFiniteInventoryError, match="PART_NNNN"):
        _summarize(
            _file(inventory.FILECODE_INFO,
                  _encode_item("JPartDataBi4", _info_root_values()),
                  _encode_item("BROKEN", _info_part_values(1))),
            "PartInfo.ibi4",
        )


def test_partinfo_requires_list_records_and_rejects_arrays_or_wrong_filecode():
    root_only = _file(inventory.FILECODE_INFO, _encode_item("JPartDataBi4", _info_root_values()))
    with pytest.raises(inventory.HeadInfoFiniteInventoryError, match="no PART records"):
        _summarize(root_only, "PartInfo.ibi4")
    with pytest.raises(inventory.HeadInfoFiniteInventoryError, match="arrays"):
        _summarize(_info_blob(root_arrays=1), "PartInfo.ibi4")
    with pytest.raises(inventory.HeadInfoFiniteInventoryError, match="arrays"):
        _summarize(_info_blob(part_arrays=1), "PartInfo.ibi4")
    wrong_code = _file("#FileJBD JPartDataBi4", _encode_item("JPartDataBi4", _info_root_values()))
    with pytest.raises(inventory.HeadInfoFiniteInventoryError, match="filecode"):
        _summarize(wrong_code, "PartInfo.ibi4")


def test_partinfo_bounds_optional_groups_and_unexpected_subdomains(monkeypatch):
    monkeypatch.setattr(inventory, "MAX_PARTINFO_RECORDS", 1)
    with pytest.raises(inventory.HeadInfoFiniteInventoryError, match="item count"):
        _summarize(_info_blob(cparts=(1, 2)), "PartInfo.ibi4")

    monkeypatch.setattr(inventory, "MAX_PARTINFO_RECORDS", 50_000)
    partial_gpu = _info_blob(part_bad=("nctalloc", 9, 3))
    with pytest.raises(inventory.HeadInfoFiniteInventoryError, match="GPU memory"):
        _summarize(partial_gpu, "PartInfo.ibi4")
    bad_subdomain = _info_blob(part_bad=("subdomainmin_09", 23, (0.0, 0.0, 0.0)))
    with pytest.raises(inventory.HeadInfoFiniteInventoryError, match="unknown"):
        _summarize(bad_subdomain, "PartInfo.ibi4")


def test_manifest_sha_and_file_byte_bounds_are_enforced(monkeypatch):
    blob = _head_blob()
    wrong_digest = hashlib.sha256(b"different synthetic bytes").hexdigest()
    with pytest.raises(inventory.HeadInfoFiniteInventoryError, match="SHA-256"):
        _summarize(blob, digest=wrong_digest)
    monkeypatch.setattr(inventory, "MAX_INPUT_BYTES", len(blob) - 1)
    with pytest.raises(inventory.HeadInfoFiniteInventoryError, match="byte length"):
        _summarize(blob)


def test_held_fd_mutation_during_schema_parse_fails_post_parse_binding(monkeypatch):
    blob = _head_blob()
    digest = hashlib.sha256(blob).hexdigest()
    original_parse = inventory._parse_native
    with tempfile.NamedTemporaryFile() as stream:
        stream.write(blob)
        stream.flush()

        def parse_then_mutate(data, kind, filename):
            result = original_parse(data, kind, filename)
            old = struct.unpack("<B", os.pread(stream.fileno(), 1, 70))[0]
            os.pwrite(stream.fileno(), bytes((old ^ 1,)), 70)
            return result

        monkeypatch.setattr(inventory, "_parse_native", parse_then_mutate)
        with pytest.raises(inventory.HeadInfoFiniteInventoryError, match="identity changed"):
            inventory.summarize_head_info_fd(stream.fileno(), "Part_Head.ibi4", digest)


@pytest.mark.parametrize("blob_builder", [
    lambda: b"x" * 64,
    lambda: _head_blob()[:-1],
])
def test_malformed_or_truncated_bi4_fails_closed(blob_builder):
    blob = blob_builder()
    with pytest.raises(inventory.HeadInfoFiniteInventoryError):
        _summarize(blob)
