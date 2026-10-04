"""Source-only API checks; no ParaView, solver, or trajectory is launched."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "render.py"
SPEC = importlib.util.spec_from_file_location("f2_stage1_renderer", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
renderer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(renderer)


def base_manifest() -> dict:
    return {
        "schema": renderer.MANIFEST_SCHEMA,
        "xdmf": "/tmp/case.xmf",
        "xdmf_sha256": "a" * 64,
        "frames": 3,
        "particles": 4,
        "actual_time_s": [0.0, 0.1, 0.2],
        "fields": {
            "position": {},
            "time": {},
            "valid": {},
            "particle_id": {},
            "particle_zone": {},
            "type": {},
            "mass": {},
            "velocity": {},
            "density": {},
            "pressure": {},
        },
    }


def test_manifest_and_native_aliases_are_source_bound():
    manifest = base_manifest()
    manifest["type_aliases"] = {"fluid": 7, "moving": [4], "floating": 5, "fixed": 0}
    renderer.validate_manifest(manifest)
    assert renderer.resolve_type_codes(manifest) == {
        "fluid": (7,),
        "moving": (4,),
        "floating": (5,),
        "fixed": (0,),
    }


def test_camera_bounds_are_safe_and_cutaway_is_display_only():
    camera = renderer.camera_for_bounds([[-2, 3], [-4, 6], [0, 1]])
    assert camera["bounds"] == [[-2.0, 3.0], [-4.0, 6.0], [0.0, 1.0]]
    assert camera["parallel_scale"] > 10.0
    assert camera["cutaway_y"] == pytest.approx(1.0)
    assert [view["name"] for view in camera["views"]] == ["isometric", "transverse_side"]


def test_selection_rejects_duplicates_and_preserves_order():
    assert renderer.parse_frame_selection("4,1,9", 10) == [4, 1, 9]
    with pytest.raises(renderer.RendererError, match="duplicates"):
        renderer.parse_frame_selection("1,1", 3)
    with pytest.raises(renderer.RendererError, match="out-of-range"):
        renderer.parse_frame_selection("3", 3)


def test_template_is_explicitly_unlaunched():
    template = json.loads(SCRIPT.with_name("request.template.json").read_text())
    assert template["schema"] == renderer.REQUEST_SCHEMA
    assert template["status"] == "template_only_not_launched"
    assert template["launch_policy"]["root_only"] is True
    assert template["launch_policy"]["numerical_precision_status"] == "not accepted"
