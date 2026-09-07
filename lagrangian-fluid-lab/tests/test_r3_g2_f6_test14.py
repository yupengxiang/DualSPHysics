import numpy as np

from scripts.r3_g2_f6_test14 import (
    FILE_SHA256,
    OFFSETS,
    RESOLUTIONS,
    definition_text,
    dominant_period,
    records,
    write_world_stl,
)


def test_matrix_has_two_data_supported_offsets_by_three_resolutions():
    matrix = records()
    assert len(matrix) == 6
    assert {item["offset_m"] for item in matrix} == {-0.074, 0.076}
    assert {item["dp"] for item in matrix} == set(RESOLUTIONS.values())
    assert {item["experiment"] for item in matrix} == {
        "Fl1-0p074.txt", "Fl1+0p76.txt"
    }
    assert len({item["case_id"] for item in matrix}) == 6
    assert set(FILE_SHA256) >= {"Float1.STL", "Fl1-0p074.txt", "Fl1+0p76.txt"}


def test_definition_is_heave_only_and_keeps_time_axes_separate():
    record = records()[0]
    xml = definition_text(record)
    assert '<translationDOF x="0" y="0" z="1"' in xml
    assert '<rotationDOF x="0" y="0" z="0"' in xml
    assert f'<parameter key="TimeOut" value="{record["tout"]}"' in xml
    assert '<parameter key="DtFixed"' not in xml
    assert '<dampingcylinder active="true">' in xml


def test_offset_changes_cog_and_uses_per_case_transformed_stl():
    neg = definition_text(next(item for item in records() if item["offset_name"] == "neg074"))
    pos = definition_text(next(item for item in records() if item["offset_name"] == "pos076"))
    assert 'z="0.629000"' in neg
    assert 'z="0.779000"' in pos
    assert "neg074_coarse/generated/Float1_world.stl" in neg
    assert "pos076_coarse/generated/Float1_world.stl" in pos


def test_dominant_period_recovers_synthetic_signal():
    time = np.arange(0, 4.5 + 0.005, 0.005)
    period = 0.9
    signal = np.cos(2 * np.pi * time / period)
    assert abs(dominant_period(time, signal) - period) < 0.06


def test_every_offset_maps_to_one_trace():
    assert all(item["experiment"].endswith(".txt") for item in OFFSETS.values())


def test_world_stl_transform_is_explicit_and_metric(tmp_path):
    import struct

    source = tmp_path / "one.stl"
    header = b"test".ljust(80, b"\0")
    triangle = struct.pack(
        "<I12fH", 1,
        0, 1, 0,
        0, 0, 0,
        300, 0, 0,
        150, 290, 300,
        0,
    )
    source.write_bytes(header + triangle)
    target = tmp_path / "world.stl"
    audit = write_world_stl(source, target, 0.613)
    assert audit["source_triangles"] == 1
    assert audit["source_connected_components"] == 1
    assert audit["selected_outer_triangles"] == 1
    assert np.allclose(audit["transformed_stl_bbox_min_m"], [-0.15, -0.15, 0.613])
    assert np.allclose(audit["transformed_stl_bbox_max_m"], [0.15, 0.15, 0.903])
