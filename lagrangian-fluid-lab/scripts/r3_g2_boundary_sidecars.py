#!/usr/bin/env python3
"""Generate and audit finite boundary-triangle sidecars for the W11 pilot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scripts.boundary_sidecars import audit_sidecar, read_binary_vtk_polydata, write_sidecar
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from boundary_sidecars import audit_sidecar, read_binary_vtk_polydata, write_sidecar


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
DEFAULT_MANIFEST = LAB / "release" / "v0.1-development" / "manifest.json"
DEFAULT_OUTPUT = CAMPAIGN / "sidecars" / "r3-g2-boundary"
DEFAULT_REPORT = CAMPAIGN / "r3-g2-boundary-sidecars.json"


def source_geometry(case: dict, lab: Path = LAB, campaign: Path = CAMPAIGN) -> Path:
    """Locate the exact generated MkCells file for a development case."""
    case_id = case["case_id"]
    family = case["family"]
    if family == "F2":
        return campaign / "artifacts" / "w06" / case_id / "generated" / f"{case_id}_MkCells.vtk"
    return lab / "cases" / family / case_id / "generated" / f"{case_id}_MkCells.vtk"


def build_report(manifest_path: Path = DEFAULT_MANIFEST, output_dir: Path = DEFAULT_OUTPUT,
                 report_path: Path = DEFAULT_REPORT, selected_ids: tuple[str, ...] | None = None) -> dict:
    manifest_path = Path(manifest_path).resolve()
    output_dir = Path(output_dir).resolve()
    manifest = json.loads(manifest_path.read_text())
    records = manifest["cases"]
    selected = [record for record in records if record["family"] in {"F1", "F2", "F3"}]
    if selected_ids is not None:
        wanted = set(selected_ids)
        selected = [record for record in selected if record["case_id"] in wanted]
        missing = sorted(wanted - {record["case_id"] for record in selected})
        if missing:
            raise ValueError(f"requested cases are unavailable in the manifest: {missing}")
    cases = {}
    for record in selected:
        case_id = record["case_id"]
        source = source_geometry(record)
        if not source.is_file():
            raise FileNotFoundError(source)
        h5_path = manifest_path.parent / record["hdf5"]
        parsed = read_binary_vtk_polydata(source)
        destination = output_dir / f"{case_id}.h5"
        summary = write_sidecar(
            destination,
            case_id,
            h5_path,
            parsed,
            source_vtk_label=str(source.relative_to(LAB)),
            source_hdf5_label=str(h5_path.relative_to(manifest_path.parent)),
        )
        summary.update({
            "case_id": case_id,
            "family": record["family"],
            "source_vtk_relative": str(source.relative_to(LAB)),
            "source_hdf5_relative": str(h5_path.relative_to(manifest_path.parent)),
            "sidecar_relative": str(destination.relative_to(CAMPAIGN)),
            "source_polygon_count": len(parsed["cells"]),
            "source_boundary_polygon_count": int(sum(int(kind) in (0, 1) for kind in parsed["type"])),
            "source_fluid_polygon_count": int(sum(int(kind) == 3 for kind in parsed["type"])),
        })
        cases[case_id] = summary
    report = {
        "schema_version": 1,
        "scope": "R3 G2 finite boundary-triangle sidecar generation and audit",
        "execution_status": "complete",
        "acceptance_status": "candidate_geometry_only",
        "non_claim": "sidecars provide geometry for wall-aware numerical tracing; they do not supply external physical validation or destination labels",
        "source_contract": {
            "format": "DualSPHysics binary VTK POLYDATA MkCells",
            "included_types": {"0": "fixed boundary", "1": "prescribed moving boundary"},
            "excluded_types": {"3": "fluid surface; never used as a wall"},
            "triangulation": "fan triangulation of each finite polygon",
            "output": "world-space triangles at every exported HDF5 time; moving Type 1 cells use /control/cup_world_from_body",
        },
        "case_count": len(cases),
        "cases": cases,
        "all_sidecars_valid": bool(cases) and all(
            item["all_frames_finite"] and item["all_frames_nondegenerate"]
            and item["coordinate_frame"] == "world"
            for item in cases.values()
        ),
        "open_blockers": [
            "sidecars are not yet linked into the W11 release manifest or material destination specifications",
            "wall-aware tracer convergence must be rerun using these sidecars before material targets can be accepted",
            "static polygon provenance must be checked against each final production solver definition after resolution changes",
        ],
    }
    report_path = Path(report_path).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--case", dest="cases", action="append", default=None)
    args = parser.parse_args()
    report = build_report(args.manifest, args.output_dir, args.report,
                          tuple(args.cases) if args.cases else None)
    print(json.dumps({
        "case_count": report["case_count"],
        "all_sidecars_valid": report["all_sidecars_valid"],
        "report": str(args.report.resolve()),
    }, indent=2))


if __name__ == "__main__":
    main()
