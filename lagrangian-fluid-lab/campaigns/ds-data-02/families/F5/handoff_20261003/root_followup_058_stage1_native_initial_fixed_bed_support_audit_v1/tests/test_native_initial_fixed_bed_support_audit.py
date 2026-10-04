from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "native_initial_fixed_bed_support_audit.py"
SPEC = importlib.util.spec_from_file_location("f5_native_initial_fixed_bed_support", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_fixed_marker_metrics_separate_x_domain_segments_and_mid_y() -> None:
    positions = np.asarray(
        [
            [0.0, 0.00, 0.00],
            [2.5, 0.00, 0.14],
            [3.5, 0.02, 0.42],
            [4.9, 0.00, 0.00],
            [0.0, 0.16, 0.00],
            [1.0, 0.00, -0.10],
            [1.0, 0.00, 0.00],
        ],
        dtype=np.float64,
    )
    result = MODULE.frame_metrics(
        frame_index=400,
        time_s=8.0,
        positions=positions,
        valid=np.ones(7, dtype=np.uint8),
        particle_type=np.asarray([0, 0, 0, 0, 0, 0, 3], dtype=np.int8),
        markers=np.asarray([40, 40, 40, 40, 40, 0, 1], dtype=np.int16),
        masses=np.ones(7, dtype=np.float64),
        particle_ids=np.arange(100, 107, dtype=np.uint32),
    )
    assert result["fixed_type0_valid_count"] == 6
    assert result["bed_marker_valid_count"] == 5
    assert result["distance_evaluable_count"] == 4
    assert result["near_mid_y_strip"]["count"] == 3
    assert result["marker_histogram_fixed_type0_valid"]["40"]["count"] == 5
    assert sum(item["count"] for item in result["x_bins_dp"]) == 4
    assert sum(item["count"] for item in result["bed_segment_bins"]) == 4
    assert result["depth_bins"]["0.02m"]["count"] == 0
    assert result["relative_particle_layers"]


def test_static_gen050_provenance_contract_is_hash_and_mesh_bound(tmp_path: Path) -> None:
    xml = """<?xml version='1.0'?><case><geometry><commands><mainlist>
      <setshapemode>dp | actual | bound</setshapemode>
      <setdrawmode mode='full'/><setmkbound mk='40'/>
      <drawtriangles cmt='bed'><points><point x='0' y='0' z='0'/><point x='1' y='0' z='0'/><point x='0' y='1' z='0'/></points><triangles><triangle x='0' y='1' z='2'/></triangles></drawtriangles>
      <drawfilestl file='assets/f5_compact_continuous_bed_profile.stl'/><shapeout file='continuous_bed'/>
      <clipplane><point x='2' y='0' z='0'/><vector x='0.28' y='0' z='-1'/></clipplane>
      </mainlist></commands></geometry><particles>
      <fixed mkbound='40' mk='40' begin='0' count='2'/><fluid mkfluid='0' mk='1' begin='2' count='1'/>
      </particles></case>"""
    files = {}
    contents = {
        "selected_definition": xml,
        "generated_xml": xml,
        "generated_definition": xml,
        "prepared_input_report": None,
        "gencase_receipt": None,
        "gencase_stdout": "Triangles: 1\nParticle summary\n",
        "bed_stl": "solid bed\n facet normal 0 0 1\n  outer loop\n   vertex 0 0 0\n   vertex 1 0 0\n   vertex 0 1 0\n  endloop\n endfacet\nendsolid bed\n",
        "motion_asset": "0 0\n",
    }
    for role, content in contents.items():
        path = tmp_path / role
        if role.endswith("definition") or role == "generated_xml":
            path = path.with_suffix(".xml")
        elif role == "prepared_input_report" or role == "gencase_receipt":
            path = path.with_suffix(".json")
        elif role == "bed_stl":
            path = path.with_suffix(".stl")
        else:
            path = path.with_suffix(".dat" if role == "motion_asset" else ".log")
        if content is not None:
            path.write_text(content, encoding="utf-8")
        files[role] = path

    generated_sha = hashlib.sha256(files["generated_xml"].read_bytes()).hexdigest()
    files["prepared_input_report"].write_text(
        json.dumps(
            {
                "xml_sha256": generated_sha,
                "generated_xml_particle_counts": {"fixed": 2, "moving": 0, "floating": 0, "fluid": 1},
                "actual_total_particles": 3,
                "actual_generated_constants": {},
                "native_initial_typed_QA": "pending",
                "q_n": "not_granted",
                "production_approval": "none",
            }
        ),
        encoding="utf-8",
    )
    files["gencase_receipt"].write_text(
        json.dumps(
            {
                "status": "completed",
                "returncode": 0,
                "total_particles": 3,
                "fluid_particles": 1,
                "solver_dimension_from_gencase": 3,
                "output_root": "synthetic",
                "binary_sha256": "synthetic",
                "stdout_sha256": hashlib.sha256(files["gencase_stdout"].read_bytes()).hexdigest(),
                "finished_at_utc": "synthetic",
            }
        ),
        encoding="utf-8",
    )
    source_files = {
        role: {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "role": role}
        for role, path in files.items()
    }
    manifest = tmp_path / "provenance.json"
    manifest.write_text(
        json.dumps(
            {
                "source_files": source_files,
                "expectations": {
                    "bed_marker_mk": 40,
                    "bed_stl_relative_name": "assets/f5_compact_continuous_bed_profile.stl",
                    "minimum_triangle_count": 1,
                    "generated_fixed_count": 2,
                    "clipplane_vector": [0.28, 0.0, -1.0],
                },
            }
        ),
        encoding="utf-8",
    )
    result = MODULE.audit_source_provenance(manifest)
    assert result["consistency_checks"]["drawmode_full_in_all_xml"] is True
    assert result["consistency_checks"]["bed_stl_drawn_in_all_xml"] is True
    assert result["consistency_checks"]["triangle_mesh_declared_in_all_xml"] is True
    assert result["consistency_checks"]["generated_xml_bed_mk40_range_present"] is True
    assert result["particle_identity_ranges"]["bed_mk40_ranges"][0]["count"] == 2
    assert result["bed_stl_mesh_attributes"]["facet_count"] == 1
    assert result["interpretation_boundary"]["no_hollow_stl_claim"] is True
