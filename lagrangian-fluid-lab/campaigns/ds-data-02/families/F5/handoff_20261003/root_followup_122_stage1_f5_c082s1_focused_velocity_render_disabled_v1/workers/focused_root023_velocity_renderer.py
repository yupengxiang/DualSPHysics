#!/usr/bin/env python3
"""Run the unchanged Root023 temporal renderer with a display-only focus.

Root owns the actual pvpython invocation. This adapter reads only the Root598
JSON/XMF metadata before creating a derived manifest. It keeps the XDMF/H5
reader, all 801 saved times, all native fields and the full particle axis. The
only runtime display override is POINTS velocity magnitude coloring on a fixed
display scale and a local water/shoreline camera window. No source array is
edited, resampled, clipped or filtered.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any


SCIENCE_SUFFIXES = {".h5", ".dat", ".bi4", ".csv", ".vtk"}
EXPECTED_RENDERER_SHA = "5e78f7b92ad7c6f1d15902e3ccacc9099affb04b1b992a42f540eb88241bde66"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def sha_static(path: Path) -> str:
    """Hash source/metadata only; never pass a science payload here."""
    require(path.suffix.lower() not in SCIENCE_SUFFIXES, f"science payload hash forbidden: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def import_renderer(path: Path):
    require(path.is_file(), f"Root023 renderer missing: {path}")
    require(sha_static(path) == EXPECTED_RENDERER_SHA, "Root023 renderer bytes changed")
    spec = importlib.util.spec_from_file_location("ds02_root023_renderer", path)
    require(spec is not None and spec.loader is not None, "cannot load Root023 renderer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_focused_manifest(binding: dict[str, Any], source: dict[str, Any], output_dir: Path) -> Path:
    require(source.get("schema") == "ds02.stage1.paraview-temporal-product.v1", "Root598 XMF manifest schema")
    require(source.get("xdmf") == binding["xdmf"], "XDMF path differs from binding")
    require(source.get("xdmf_sha256") == binding["xdmf_sha256"], "XDMF producer SHA differs from binding")
    require(source.get("trajectory_h5") == binding["trajectory_h5"], "H5 path differs from binding")
    require(source.get("trajectory_h5_sha256") == binding["trajectory_h5_sha256"], "H5 producer SHA differs from binding")
    require(int(source.get("frames", -1)) == 801 and int(source.get("particles", -1)) == 194427, "Root598 shape")
    require(len(source.get("actual_time_s", [])) == 801, "Root598 actual time axis")
    fields = source.get("fields", {})
    require({"valid", "particle_id", "particle_zone", "type", "velocity"} <= set(fields), "Root598 velocity/native fields")

    derived = dict(source)
    derived["camera_bounds"] = binding["focus_camera_bounds_m"]
    derived["camera_bounds_policy"] = binding["camera_bounds_policy"]
    derived["focused_display_only"] = True
    derived["source_reader_unclipped"] = True
    derived["particle_clipping"] = False
    derived["fluid_color_mode"] = "POINTS velocity Magnitude"
    derived["velocity_color_scale_mps"] = binding["velocity_color"]["scale_mps"]
    derived["focus_frames"] = binding["focus_frames"]
    derived["root_visual_acceptance"] = False
    derived["full801_authorized"] = False
    derived["derived_from_manifest"] = binding["xmf_manifest"]
    derived["derived_from_manifest_sha256"] = binding["xmf_manifest_sha256"]

    output = output_dir / "focused-root598-display-manifest.json"
    output.write_text(json.dumps(derived, indent=2) + "\n", encoding="utf-8")
    return output


def patch_velocity_display(renderer: Any, binding: dict[str, Any]) -> None:
    base_builder = renderer._build_display_pipeline
    scale = binding["velocity_color"]["scale_mps"]
    require(isinstance(scale, list) and len(scale) == 2 and float(scale[1]) > float(scale[0]), "velocity display scale")

    def focused_builder(reader: Any, manifest: dict[str, Any], camera: dict[str, Any]) -> dict[str, Any]:
        pipeline = base_builder(reader, manifest, camera)
        from paraview.simple import ColorBy, GetColorTransferFunction, GetDisplayProperties, GetScalarBar

        lookup = GetColorTransferFunction("velocity")
        lookup.RescaleTransferFunction(float(scale[0]), float(scale[1]))
        for view in pipeline["views"]:
            display = GetDisplayProperties(pipeline["fluid"], view)
            require(display is not None, "fluid display proxy missing")
            ColorBy(display, ("POINTS", "velocity", "Magnitude"))
            display.LookupTable = lookup
            if hasattr(display, "MapScalars"):
                display.MapScalars = 1
            scalar_bar = GetScalarBar(lookup, view)
            scalar_bar.Title = "fluid velocity magnitude"
            scalar_bar.ComponentTitle = "m/s"
            scalar_bar.Visibility = 1
        return pipeline

    renderer._build_display_pipeline = focused_builder


def run(binding_path: Path, output_dir: Path) -> dict[str, Any]:
    binding = load_json(binding_path)
    require(binding.get("schema") == "ds02.f5.c082s1.focused-velocity-render-binding.fresh122.v1", "binding schema")
    require(binding.get("source_only") is True and binding.get("derived_view_only") is True, "source gate")
    require(binding.get("native_fields_preserved") is True, "native field contract")
    require(binding.get("no_particle_clipping_or_reader_filtering") is True, "reader filtering contract")
    require(binding.get("no_resampling") is True and binding.get("no_array_edit") is True, "display-only contract")
    require(not output_dir.exists(), f"refusing to reuse output directory: {output_dir}")
    output_dir.mkdir(parents=True)

    manifest_path = Path(binding["xmf_manifest"])
    source_manifest = load_json(manifest_path)
    require(sha_static(manifest_path) == binding["xmf_manifest_sha256"], "Root598 manifest changed")
    renderer_path = Path(binding["root023_renderer"])
    renderer = import_renderer(renderer_path)
    derived_manifest = make_focused_manifest(binding, source_manifest, output_dir)
    patch_velocity_display(renderer, binding)

    report = renderer.render_case(derived_manifest, output_dir, diagnostic_frames=None)
    report_path = output_dir / "paraview-full-animation-report.json"
    report = load_json(report_path)
    report.update({
        "focused_display": {
            "camera_bounds_m": binding["focus_camera_bounds_m"],
            "camera_bounds_policy": binding["camera_bounds_policy"],
            "source_reader_unclipped": True,
            "fluid_color": {
                "association": "POINTS",
                "array": "velocity",
                "component": "Magnitude",
                "scale_mps": binding["velocity_color"]["scale_mps"],
            },
            "focus_frames": binding["focus_frames"],
            "all_801_frames_requested": True,
            "actual_time_axis_preserved": True,
            "native_particle_axis_preserved": True,
            "array_edit": False,
            "resampling": False,
            "case_increment": 0,
            "visual_acceptance": False,
        },
        "root598_input_manifest": binding["xmf_manifest"],
        "root598_input_manifest_sha256": binding["xmf_manifest_sha256"],
        "trajectory_h5_producer_attestation": binding["trajectory_h5_sha256"],
        "trajectory_h5_opened_or_rehashed_by_adapter": False,
        "visual_review": "pending root inspection; focused display does not establish wave/runup mechanism acceptance",
        "numerical_precision_status": "not accepted",
        "independent_case_increment": 0,
    })
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.binding, args.output_dir)
    print(json.dumps({
        "status": "completed_render_adapter",
        "frames": report.get("frames"),
        "all_frames_rendered": report.get("all_frames_rendered"),
        "focus_frames": report["focused_display"]["focus_frames"],
        "velocity_color_scale_mps": report["focused_display"]["fluid_color"]["scale_mps"],
        "visual_acceptance": report["focused_display"]["visual_acceptance"],
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
