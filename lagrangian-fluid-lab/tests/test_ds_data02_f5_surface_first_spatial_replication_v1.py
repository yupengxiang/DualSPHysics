"""Targeted synthetic unit tests for F5 surface-first spatial replication.

Adheres strictly to Root Continuation 016:
- Synthetic small fixtures and syntax checks only.
- Does NOT execute solver, PartVTK, conversion, labels, or actual campaign H5/CSV data audit.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

import pytest

from scripts.ds_data02_f5_surface_first_spatial_replication_v1 import (
    CASE_SPECS,
    FLUID_HIGH,
    FLUID_LOW,
    FLUID_MASS_KG,
    FLUID_SIZE,
    FLUID_VOLUME_M3,
    MANIFEST_PATH,
    BINDINGS_PATH,
    SCHEMA_BINDINGS,
    SCHEMA_MANIFEST,
    SCHEMA_REQUEST,
    TARGET_SCOPE,
    prepare,
    projection,
    sha256_file,
)
from scripts.ds_data02_f5_surface_lineage_v3 import (
    SCHEMA_LINEAGE_V3,
    _vtk_points_payload,
)


def test_prepare_and_manifest():
    """Verify prepare() generates valid manifest, bindings, and all 16 runner requests."""
    res = prepare()
    assert res["status"] == "prepared"
    assert Path(res["manifest"]).is_file()
    assert Path(res["bindings"]).is_file()
    assert len(res["cases"]) == 4

    manifest = json.loads(Path(res["manifest"]).read_text(encoding="utf-8"))
    assert manifest["schema"] == SCHEMA_MANIFEST
    assert manifest["family_id"] == "F5"
    assert manifest["execution_rules"]["launch_allowed"] is False
    assert manifest["execution_rules"]["root_review_required"] is True
    assert manifest["execution_rules"]["no_gpu_until_actual_qa_passes"] is True

    bindings = json.loads(Path(res["bindings"]).read_text(encoding="utf-8"))
    assert bindings["schema"] == SCHEMA_BINDINGS
    assert len(bindings["cases"]) == 4

    for case_key in ["runup_dp050", "weir_dp050", "runup_dp025", "weir_dp025"]:
        assert case_key in bindings["cases"]
        cdata = bindings["cases"][case_key]
        assert Path(cdata["definition_xml"]).is_file()
        assert Path(cdata["bed_stl"]).is_file()
        assert Path(cdata["piston_dat"]).is_file()
        assert cdata["projection_invariant_proven"] is True

        reqs = cdata["requests"]
        for req_kind in ["gencase", "coverage", "lineage", "initial_mass_qa"]:
            req_path = Path(reqs[req_kind])
            assert req_path.is_file()
            robj = json.loads(req_path.read_text(encoding="utf-8"))
            assert robj["schema"] == SCHEMA_REQUEST
            assert robj["launch_allowed"] is False
            assert robj["root_review_required"] is True
            assert robj["cpu_threads"] == 4
            assert robj["max_wall_seconds"] in {1800, 3600}


def test_fluid_continuum_and_lattice_theoretical_values():
    """Verify exact theoretical fluid volume and particle counts across resolutions."""
    # Bounds: [-0.9, 3.3] x [-0.7, 0.7] x [0.02, 0.42]
    dx = FLUID_HIGH[0] - FLUID_LOW[0]
    dy = FLUID_HIGH[1] - FLUID_LOW[1]
    dz = FLUID_HIGH[2] - FLUID_LOW[2]
    assert abs(dx - 4.2) < 1e-9
    assert abs(dy - 1.4) < 1e-9
    assert abs(dz - 0.4) < 1e-9

    volume = dx * dy * dz
    assert abs(volume - 2.352) < 1e-9
    mass = volume * 1000.0
    assert abs(mass - 2352.0) < 1e-9

    # DP = 0.05
    nx_05 = int(round(dx / 0.05))
    ny_05 = int(round(dy / 0.05))
    nz_05 = int(round(dz / 0.05))
    assert (nx_05, ny_05, nz_05) == (84, 28, 8)
    n_fluid_05 = nx_05 * ny_05 * nz_05
    assert n_fluid_05 == 18816

    # DP = 0.025
    nx_025 = int(round(dx / 0.025))
    ny_025 = int(round(dy / 0.025))
    nz_025 = int(round(dz / 0.025))
    assert (nx_025, ny_025, nz_025) == (168, 56, 16)
    n_fluid_025 = nx_025 * ny_025 * nz_025
    assert n_fluid_025 == 150528

    # DP = 0.010
    nx_010 = int(round(dx / 0.010))
    ny_010 = int(round(dy / 0.010))
    nz_010 = int(round(dz / 0.010))
    assert (nx_010, ny_010, nz_010) == (420, 140, 40)
    n_fluid_010 = nx_010 * ny_010 * nz_010
    assert n_fluid_010 == 2352000


def test_xml_projection_invariance_after_stripping_support_nodes():
    """Verify that removing the 4 surface-first nodes yields byte/tree projection identical to mother XML."""
    for case_key, spec in CASE_SPECS.items():
        mother_xml = spec["mother_xml"]
        mother_tree = ET.parse(mother_xml)

        new_xml = TARGET_SCOPE / case_key / f"{spec['case_id']}.xml"
        assert new_xml.is_file()
        new_tree = ET.parse(new_xml)

        main = new_tree.find(".//geometry/commands/mainlist")
        assert main is not None

        # Verify the 4 nodes exist in the expected order
        support_nodes = [n for n in main if n.get("cmt", "").startswith("root_numeric_bed_surface_support")]
        assert len(support_nodes) == 4
        assert [n.tag for n in support_nodes] == ["setmkbound", "setdrawmode", "drawtriangles", "setdrawmode"]

        # Verify 60 triangles
        triangles_elem = support_nodes[2].find("triangles")
        assert triangles_elem is not None
        assert len(triangles_elem) == 60

        # Remove them and check projection equivalence
        for n in support_nodes:
            main.remove(n)

        assert projection(mother_tree.getroot()) == projection(new_tree.getroot())


def test_synthetic_vtk_points_payload():
    """Test _vtk_points_payload on a synthetic binary VTK snippet."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        vtk_file = Path(tmp_dir) / "test.vtk"
        header = b"# vtk DataFile Version 3.0\nGenerated\nBINARY\nDATASET POLYDATA\nPOINTS 3 float\n"
        # 3 points = 9 floats = 36 bytes
        coords = bytes(range(36))
        vtk_file.write_bytes(header + coords + b"\nVERTICES 1 4\n")

        count, payload = _vtk_points_payload(vtk_file)
        assert count == 3
        assert payload == coords
        assert len(payload) == 36
