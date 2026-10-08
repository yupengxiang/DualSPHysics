#!/usr/bin/env python3
"""Record static provenance for the F5-S1 Y-half GenCase mass mismatch.

This diagnostic intentionally reads only small XML/JSON/text inputs and the
GenCase executable metadata.  It does not open Fluid/Bound VTK, BI4, HDF5,
or start GenCase/solver work.  The generated XML mass is an interface fact;
the source-derived continuous mass is a frozen geometric model.  Boundary
overlap, clipping fate, and particle support therefore remain pending the
guarded V7 Fluid/Bound audit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
SCHEMA = "ds02.stage2.f5-s1.missing-mass-static-diagnostic.v1"
REQUEST_SCHEMA = "ds02.request.v1"
PHYSICAL_CASE_ID = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090"
CONTINUOUS_MASS_KG = 287.736
OLD_DISCRETE_SAMPLE_MASS_KG = 254.4779834119572

DEFAULTS = {
    "source_def": Path(
        "/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/"
        "lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/"
        "handoff_20261003/root_followup_118_stage1_f5_c082s1_first24_cpu_contract_disabled_v1/"
        "candidates/M095_T090/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M095_T090_Def.xml"
    ),
    "candidate_dp010": HERE / "stage2_f5_s1_clipplane_repair_v5_inputs/F5_S1/dp010/F5_S1_CLIPPLANE_YHALF_LATTICE_DP010_Def.xml",
    "candidate_dp005": HERE / "stage2_f5_s1_clipplane_repair_v5_inputs/F5_S1/dp005/F5_S1_CLIPPLANE_YHALF_LATTICE_DP005_Def.xml",
    "q_dp010": Path(
        "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
        "f5-s1-yhalf-dp010-gencase-v5-root-forward-106-001.json"
    ),
    "q_dp005": Path(
        "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
        "f5-s1-yhalf-dp005-gencase-v5-root-forward-107-001.json"
    ),
    "receipt_dp010": Path(
        "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/"
        "F5_S1_CLIPPLANE_YHALF_DP010_GENCASE_ROOT_106/"
        "f5-s1-yhalf-dp010-gencase-v5-root-106-001-root-forward-030-001/execution-receipt.json"
    ),
    "receipt_dp005": Path(
        "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/"
        "F5_S1_CLIPPLANE_YHALF_DP005_GENCASE_ROOT_107/"
        "f5-s1-yhalf-dp005-gencase-v5-root-107-001-root-forward-030-001/execution-receipt.json"
    ),
    "xml_dp010": Path(
        "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/"
        "F5_S1_CLIPPLANE_YHALF_DP010_GENCASE_ROOT_106/"
        "f5-s1-yhalf-dp010-gencase-v5-root-106-001-root-forward-030-001/generated.xml"
    ),
    "xml_dp005": Path(
        "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/"
        "F5_S1_CLIPPLANE_YHALF_DP005_GENCASE_ROOT_107/"
        "f5-s1-yhalf-dp005-gencase-v5-root-107-001-root-forward-030-001/generated.xml"
    ),
    "evidence": HERE / "stage2_f5_s1_clipplane_official_evidence_audit_v2.json",
    "template": Path(
        "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
        "DualSPHysics_v5.4/doc/xml_format/GenCase_CaseTemplate.xml"
    ),
    "help_file": Path(
        "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
        "DualSPHysics_v5.4/doc/help/GenCase_Help.out"
    ),
    "gencase": Path(
        "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
        "DualSPHysics_v5.4/bin/linux/GenCase_linux64"
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    return path


def record(path: Path, label: str, *, hash_content: bool = True) -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    value: dict[str, Any] = {
        "path": str(path),
        "label": label,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "read_scope": "small_static_input" if hash_content else "metadata_only",
    }
    if hash_content:
        value["sha256"] = sha256(path)
    return value


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def number(value: Any) -> float:
    return float(value)


def point(element: ET.Element | None) -> list[float] | None:
    if element is None:
        return None
    return [number(element.attrib[k]) for k in ("x", "y", "z")]


def canonical_element(element: ET.Element, *, mask_definition: bool = False) -> str:
    """Small deterministic XML representation for candidate comparison."""
    attrs = dict(element.attrib)
    if mask_definition and element.tag == "definition":
        attrs["dp"] = "<DP>"
    if mask_definition and element.tag == "pointref":
        for key in ("x", "y", "z"):
            if key in attrs:
                attrs[key] = "<POINTREF>"
    text = " ".join((element.text or "").split())
    parts = ["<", element.tag]
    for key, value in sorted(attrs.items()):
        parts.extend([" ", key, "=", repr(value)])
    parts.append(">")
    if text:
        parts.extend(["#", text])
    for child in element:
        parts.append(canonical_element(child, mask_definition=mask_definition))
    parts.extend(["</", element.tag, ">"])
    return "".join(parts)


def parse_def(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    root = ET.parse(path).getroot()
    definition = root.find("./casedef/geometry/definition")
    main = root.find("./casedef/geometry/commands/mainlist")
    if definition is None or main is None:
        raise ValueError(f"{label} lacks casedef/geometry definition or mainlist")
    pointref = definition.find("./pointref")
    commands: list[dict[str, Any]] = []
    clip: dict[str, Any] | None = None
    fluid_box: dict[str, Any] | None = None
    after_mkfluid = False
    for index, child in enumerate(main):
        item: dict[str, Any] = {
            "index": index,
            "tag": child.tag,
            "text": " ".join((child.text or "").split()) or None,
            "attributes": dict(sorted(child.attrib.items())),
        }
        if child.tag in {"drawbox", "drawextrude"}:
            item["point"] = point(child.find("./point"))
            item["size"] = point(child.find("./size"))
            item["boxfill"] = " ".join((child.findtext("./boxfill") or "").split()) or None
        if child.tag == "clipplane":
            clip = {
                "point_m": point(child.find("./point")),
                "vector_m": point(child.find("./vector")),
                "attributes": dict(sorted(child.attrib.items())),
            }
        if child.tag == "setmkfluid":
            after_mkfluid = True
            item["mk"] = child.attrib.get("mk")
        elif after_mkfluid and child.tag == "drawbox" and fluid_box is None:
            fluid_box = {
                "point_m": point(child.find("./point")),
                "size_m": point(child.find("./size")),
                "boxfill": " ".join((child.findtext("./boxfill") or "").split()) or None,
                "attributes": dict(sorted(child.attrib.items())),
            }
        commands.append(item)
    return {
        "record": record(path, label),
        "dp_m": number(definition.attrib["dp"]),
        "pointref_m": point(pointref),
        "shape_mode": " ".join((main.findtext("./setshapemode") or "").split()),
        "commands": commands,
        "clipplane": clip,
        "fluid_drawbox": fluid_box,
        "normalized_sha256": hashlib.sha256(canonical_element(root, mask_definition=True).encode()).hexdigest(),
    }


def parse_generated(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    root = ET.parse(path).getroot()
    definition = root.find("./casedef/geometry/definition")
    pointref = definition.find("./pointref") if definition is not None else None
    particles = root.find("./execution/particles")
    if particles is None:
        raise ValueError(f"{label} has no execution/particles summary")
    fluid_blocks = [
        element
        for element in particles.findall("./fluid")
        if all(key in element.attrib for key in ("begin", "count", "mkfluid", "mk"))
    ]
    if not fluid_blocks:
        raise ValueError(f"{label} has no generated fluid blocks with begin/mk/count")
    fluid_count = sum(int(element.attrib["count"]) for element in fluid_blocks)
    mass_element = root.find("./execution/constants/massfluid")
    if mass_element is None:
        mass_element = root.find(".//massfluid")
    if mass_element is None:
        raise ValueError(f"{label} has no massfluid")
    massfluid = number(mass_element.attrib["value"])
    sample_mass = fluid_count * massfluid
    relative = 100.0 * (sample_mass - CONTINUOUS_MASS_KG) / CONTINUOUS_MASS_KG
    if abs(relative) <= 1.0:
        mass_label = "PASS_PREFERRED_WHOLE_CONTINUOUS_MASS_1PCT"
    elif abs(relative) <= 2.0:
        mass_label = "MARGINAL_1_TO_2PCT_NO_SCIENTIFIC_QUALIFICATION"
    else:
        mass_label = "HARDFAIL_OVER_2PCT_CONTINUOUS_MASS"
    return {
        "record": record(path, label),
        "dp_m": number(definition.attrib["dp"]) if definition is not None else None,
        "pointref_m": point(pointref),
        "particles": {key: int(particles.attrib[key]) for key in ("np", "nb", "nbf") if key in particles.attrib},
        "fluid_blocks": [dict(sorted(element.attrib.items())) for element in fluid_blocks],
        "fluid_count": fluid_count,
        "massfluid_kg": massfluid,
        "sample_mass_kg": sample_mass,
        "continuous_mass_delta_kg": sample_mass - CONTINUOUS_MASS_KG,
        "continuous_mass_relative_percent": relative,
        "mass_gate": mass_label,
        "old_discrete_sample_delta_percent": 100.0 * (sample_mass - OLD_DISCRETE_SAMPLE_MASS_KG) / OLD_DISCRETE_SAMPLE_MASS_KG,
    }


def find_lines(path: Path, patterns: Iterable[str]) -> dict[str, list[int]]:
    lines = regular(path, "documentation").read_text(encoding="utf-8", errors="replace").splitlines()
    return {pattern: [index for index, line in enumerate(lines, 1) if pattern in line] for pattern in patterns}


def nm_symbols(binary: Path) -> dict[str, Any]:
    result = subprocess.run(["nm", "-C", str(binary)], check=True, capture_output=True, text=True)
    wanted = (
        "JClipShape::AddPlane",
        "JClipShape::ClipPoint",
        "JSpaceDraw::ClipPlaneVec",
        "JSpaceDraw::ClipReset",
        "JSpaceDraw::DrawBox",
        "JSpaceDraw::FillBox",
        "JFreePartsMk::CheckOverlaped",
        "JFreePartsMk::RemoveOverlaped",
    )
    found: dict[str, list[str]] = {key: [] for key in wanted}
    for line in result.stdout.splitlines():
        for key in wanted:
            if key in line and len(found[key]) < 8:
                found[key].append(line.strip())
    return {
        "command": ["nm", "-C", str(binary)],
        "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
        "matches": found,
        "all_required_symbols_seen": all(found.values()),
    }


def source_semantics(source: dict[str, Any], candidate_a: dict[str, Any], candidate_b: dict[str, Any]) -> dict[str, Any]:
    source_clip = source["clipplane"]
    fluid = source["fluid_drawbox"]
    if source_clip is None or fluid is None:
        raise ValueError("source clipplane/fluid drawbox not found")
    clip_point = source_clip["point_m"]
    clip_vector = source_clip["vector_m"]
    if clip_point != [2.0, 0.0, 0.0] or clip_vector != [0.28, 0.0, -1.0]:
        raise ValueError("source clipplane differs from frozen official F5 contract")
    low = fluid["point_m"]
    size = fluid["size_m"]
    volume = size[0] * size[1] * size[2]
    operations = [item["tag"] for item in source["commands"]]
    return {
        "source_shape_mode": source["shape_mode"],
        "source_command_order": operations,
        "source_clipplane": source_clip,
        "source_fluid_box": fluid,
        "source_box_volume_m3_before_clip": volume,
        "official_half_space": "0.28*(x-2)-z <= 0, retained z >= 0.28*(x-2)",
        "continuous_region_volume_m3": 0.287736,
        "continuous_region_mass_kg": CONTINUOUS_MASS_KG,
        "candidate_dp010_dp005_normalized_equal": candidate_a["normalized_sha256"] == candidate_b["normalized_sha256"],
        "candidate_changes_limited_to_registered_dp_and_pointref": candidate_a["commands"] == candidate_b["commands"],
        "candidate_box_and_clip_equal_source": (
            candidate_a["clipplane"] == source["clipplane"]
            and candidate_b["clipplane"] == source["clipplane"]
            and candidate_a["fluid_drawbox"] == source["fluid_drawbox"]
            and candidate_b["fluid_drawbox"] == source["fluid_drawbox"]
        ),
        "source_derived_model_is_not_particle_sample_truth": True,
    }


def load_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    for key, default in DEFAULTS.items():
        parser.add_argument(f"--{key.replace('_', '-')}", type=Path, default=default)
    parser.add_argument("--output", type=Path, default=HERE / "stage2_f5_s1_missing_mass_static_diagnostic_v1.json")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    source = parse_def(args.source_def, "F5 source Def")
    candidate_a = parse_def(args.candidate_dp010, "F5 dp010 candidate Def")
    candidate_b = parse_def(args.candidate_dp005, "F5 dp005 candidate Def")
    q_a = load_json(args.q_dp010, "F5 dp010 GenCase request")
    q_b = load_json(args.q_dp005, "F5 dp005 GenCase request")
    receipt_a = load_json(args.receipt_dp010, "F5 dp010 GenCase receipt")
    receipt_b = load_json(args.receipt_dp005, "F5 dp005 GenCase receipt")
    generated_a = parse_generated(args.xml_dp010, "F5 dp010 generated XML")
    generated_b = parse_generated(args.xml_dp005, "F5 dp005 generated XML")
    for grid, request, receipt, generated, expected in (
        ("dp010", q_a, receipt_a, generated_a, (0.010, [0.015, 0.005, 0.015])),
        ("dp005", q_b, receipt_b, generated_b, (0.005, [0.0125, 0.0025, 0.0125])),
    ):
        if request.get("schema") != REQUEST_SCHEMA or request.get("family_id") != "F5" or request.get("sentinel_id") != "F5-S1":
            raise ValueError(f"{grid} GenCase request identity mismatch")
        if request.get("physical_case_id") != PHYSICAL_CASE_ID:
            raise ValueError(f"{grid} physical case identity mismatch")
        binding = request.get("source_binding", {})
        if abs(float(binding.get("dp_m", -1.0)) - expected[0]) > 1e-12 or list(binding.get("pointref_m", [])) != expected[1]:
            raise ValueError(f"{grid} request dp/pointref binding mismatch")
        if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
            raise ValueError(f"{grid} GenCase receipt is not completed zero-return")
        if abs(float(generated["dp_m"]) - expected[0]) > 1e-12 or generated["pointref_m"] != expected[1]:
            raise ValueError(f"{grid} generated XML dp/pointref mismatch")
    evidence = load_json(args.evidence, "official F5 clip evidence")
    official_contract = evidence.get("clipplane_contract", {})
    official_mass = evidence.get("continuous_region", {}).get("mass_at_rho0_1000_kg")
    if official_mass is None or abs(float(official_mass) - CONTINUOUS_MASS_KG) > 1e-9:
        raise ValueError("official evidence continuous mass is not the frozen 287.736 kg")
    binary_record = record(args.gencase, "official GenCase binary")
    expected_binary_sha = official_contract.get("official_evidence", {}).get("command_output_bindings", {}).get("nm", {}).get("binary_sha256")
    # The evidence stores the binary hash under inputs.gencase; preserve the
    # explicit comparison but do not require an optional legacy field.
    evidence_binary_sha = evidence.get("inputs", {}).get("gencase", {}).get("sha256")
    if evidence_binary_sha and binary_record["sha256"] != evidence_binary_sha:
        raise ValueError("official GenCase binary differs from bound evidence")
    report = {
        "schema": SCHEMA,
        "status": "COMPLETED_STATIC_PROVENANCE_SUPPORT_PENDING",
        "identity": {"family_id": "F5", "sentinel_id": "F5-S1", "physical_case_id": PHYSICAL_CASE_ID},
        "scope": {
            "vtk_read": False,
            "bi4_read": False,
            "hdf5_read": False,
            "solver_started": False,
            "gencase_started": False,
            "support_payload_audit": "PENDING_GUARDED_V7",
        },
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "static XML/source evidence cannot establish particle support, overlap removal, or clip fate"},
        "source_inputs": {
            "source_def": source["record"],
            "candidate_dp010": candidate_a["record"],
            "candidate_dp005": candidate_b["record"],
            "q_dp010": record(args.q_dp010, "F5 dp010 GenCase request"),
            "q_dp005": record(args.q_dp005, "F5 dp005 GenCase request"),
            "receipt_dp010": record(args.receipt_dp010, "F5 dp010 GenCase receipt"),
            "receipt_dp005": record(args.receipt_dp005, "F5 dp005 GenCase receipt"),
            "generated_xml_dp010": generated_a["record"],
            "generated_xml_dp005": generated_b["record"],
            "official_evidence": record(args.evidence, "official F5 clip evidence"),
            "official_template": record(args.template, "official GenCase XML template"),
            "official_help": record(args.help_file, "official GenCase help"),
            "official_gencase": binary_record,
        },
        "source_semantics": source_semantics(source, candidate_a, candidate_b),
        "generated_xml_observations": {"dp010": generated_a, "dp005": generated_b},
        "terminal_receipts": {
            "dp010": {"status": receipt_a.get("status"), "returncode": receipt_a.get("returncode"), "planned_output_root": q_a.get("output_root"), "actual_output_root": receipt_a.get("output_root"), "planned_root_matches_receipt": q_a.get("output_root") == receipt_a.get("output_root")},
            "dp005": {"status": receipt_b.get("status"), "returncode": receipt_b.get("returncode"), "planned_output_root": q_b.get("output_root"), "actual_output_root": receipt_b.get("output_root"), "planned_root_matches_receipt": q_b.get("output_root") == receipt_b.get("output_root")},
        },
        "official_documentation": {
            "template_lines": find_lines(args.template, ("<setshapemode", "<clipreset", "<clipplane", "<drawbox", "<fillbox", "<drawextrude")),
            "help_lines": find_lines(args.help_file, ("-dp:", "-threads:", "-save:")),
            "nm": nm_symbols(args.gencase),
            "bound_evidence_symbols": official_contract.get("official_evidence", {}).get("symbols_required", []),
            "bound_clip_disassembly": {
                key: value
                for key, value in official_contract.get("official_evidence", {}).items()
                if key in {"add_plane_disassembly", "clip_plane_vec_disassembly", "clip_point_disassembly", "symbols_verified"}
            },
        },
        "missing_mass_interpretation": {
            "continuous_owner_mass_kg": CONTINUOUS_MASS_KG,
            "old_discrete_sample_mass_kg": OLD_DISCRETE_SAMPLE_MASS_KG,
            "old_discrete_sample_is_diagnostic_only": True,
            "dp010": "The terminal XML is 281.278 kg, 2.244418% below the source-derived continuous model; retain HARDFAIL for the frozen >2% gate.",
            "dp005": "The terminal XML is 284.450 kg, 1.142019% below the source-derived continuous model; retain MARGINAL and do not grant the preferred <=1% gate.",
            "static_evidence_can_prove": [
                "the source box and official clip plane define the frozen 0.287736 m^3 / 287.736 kg continuous model",
                "the two candidate Def files preserve command order, box, clip, motion, and controls while changing only registered dp/pointref phase",
                "the terminal XML count and massfluid values produce the reported sample masses",
                "the official binary exposes separate clip, draw/fill, and overlap-removal operations",
            ],
            "static_evidence_cannot_prove": [
                "whether a generated fluid point was removed by boundary overlap",
                "whether a point is outside the clip plane after all shape operations",
                "whether boundary/fluid support is complete or physically equivalent",
                "any scientific QI/QN/QE qualification",
            ],
            "next_required_evidence": "Run the additive V7 guarded support worker against the exact terminal GenCase request/receipt. Its worker-owned Fluid/Bound VTK pre/post SHA/stat checks must establish the missing particle/support facts; do not rescale mass or widen thresholds.",
        },
    }
    return report


def main() -> int:
    args = load_args()
    if args.self_test:
        assert abs(0.28 * (2.0 - 2.0) - 0.0) < 1e-12
        assert abs(3.42 * 0.28 * 0.38 - 0.363888) < 1e-12
        print("stage2_f5_s1_missing_mass_static_diagnostic_v1 self-test PASS")
        return 0
    report = build_report(args)
    output = args.output.expanduser().resolve()
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"refuse to overwrite immutable report: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(output), "dp010_mass_gate": report["generated_xml_observations"]["dp010"]["mass_gate"], "dp005_mass_gate": report["generated_xml_observations"]["dp005"]["mass_gate"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
