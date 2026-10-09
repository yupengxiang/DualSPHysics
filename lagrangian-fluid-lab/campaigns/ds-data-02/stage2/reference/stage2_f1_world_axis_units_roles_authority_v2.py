#!/usr/bin/env python3
"""Build a bounded, source-only F1 authority sidecar.

This helper reads only the small F1 generated/Def XML files, official BI4
storage source, the existing observer/contract source, and the immutable
fourteen-sentinel registry metadata.  It refuses production BI4/H5/VTK
payloads and never launches a solver.  The resulting report distinguishes
source-closed component/typed-role facts from the still-unknown producer
world-axis orientation and numerical qualification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat
import tempfile
import xml.etree.ElementTree as ET
from typing import Any


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1")
REGISTRY = HERE / "stage2_fourteen_evidence_status_v4.json"
CONTRACT = HERE / "stage2_f1_world_axis_units_roles_authority_contract_v2.json"
OBSERVER = HERE / "stage2_f1_native_selected_observer_v1.py"
ROOT202_CONTRACT = HERE / "stage2_f1_com_observer_calibration_contract_v1.json"
SOURCE_FILES = {
    "jpartdata_bi4_cpp": ROOT / "src/source/JPartDataBi4.cpp",
    "jpartdata_bi4_header": ROOT / "src/source/JPartDataBi4.h",
    "typesdef_header": ROOT / "src/source/TypesDef.h",
    "bi4_dump_cpp": ROOT / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp",
    "observer": OBSERVER,
    "root202_contract": ROOT202_CONTRACT,
    "contract": CONTRACT,
}
S1_XML = DATA / "F1_FALLBACK_ECC_COARSE/root-fallback-ecc-coarse-actual-gencase-027/prepared/F1_FALLBACK_ECC_COARSE.xml"
S1_DEF = DATA / "F1_FALLBACK_ECC_COARSE/root-fallback-ecc-coarse-actual-gencase-027/prepared/F1_FALLBACK_ECC_COARSE_Def.xml"
S2_COARSE_XML = DATA / "F1_S2_SPATIAL_COARSE_DP0p022500/f1-s2-spatial-coarse-dp0p022500-v5-primary-001/generated.xml"
S2_MEDIUM_XML = DATA / "F1_STAGE1_DUAL_H340_DP020/root-stage1-dual-h340-actual-gencase-027/prepared/F1_STAGE1_DUAL_H340_DP020.xml"
S2_MEDIUM_DEF = DATA / "F1_STAGE1_DUAL_H340_DP020/root-stage1-dual-h340-actual-gencase-027/prepared/F1_STAGE1_DUAL_H340_DP020_Def.xml"
S2_FINE_XML = DATA / "F1_S2_SPATIAL_INTERVAL_DP0p017000/f1-s2-spatial-interval-dp0p017000-v2-primary-001/generated.xml"
XML_FILES = {
    "f1_s1_generated": S1_XML,
    "f1_s1_definition": S1_DEF,
    "f1_s2_coarse_generated": S2_COARSE_XML,
    "f1_s2_medium_generated": S2_MEDIUM_XML,
    "f1_s2_medium_definition": S2_MEDIUM_DEF,
    "f1_s2_fine_generated": S2_FINE_XML,
}
FORBIDDEN = {".bi4", ".h5", ".hdf5", ".vtk", ".vtu"}
MAX_BYTES = 16 * 1024 * 1024
SCHEMA = "ds02.stage2.f1.world-axis-units-roles-authority.v2"

EXPECTED = {
    "f1_s1_generated": {"family": "F1-S1", "fluid": 40200, "fixed": 101436, "time_max": "1.6"},
    "f1_s2_coarse_generated": {"family": "F1-S2", "fluid": 29700, "fixed": 68664, "time_max": "4.0"},
    "f1_s2_medium_generated": {"family": "F1-S2", "fluid": 42500, "fixed": 87816, "time_max": "4.0"},
    "f1_s2_fine_generated": {"family": "F1-S2", "fluid": 69620, "fixed": 149362, "time_max": "4.0"},
}
REQUIRED_PARAMETERS = {
    "Boundary": "1",
    "SavePosDouble": "1",
    "StepAlgorithm": "1",
    "VerletSteps": "40",
    "Kernel": "1",
    "ViscoTreatment": "1",
    "Shifting": "0",
    "RigidAlgorithm": "1",
    "CoefDtMin": "0.05",
    "TimeOut": "0.01",
    "RhopOutMin": "700",
    "RhopOutMax": "1300",
}


class AuditFailure(RuntimeError):
    pass


def _path(value: str | Path) -> Path:
    return Path(value).expanduser().absolute()


def _record(path: Path, label: str) -> dict[str, Any]:
    path = _path(path)
    if path.suffix.lower() in FORBIDDEN:
        raise AuditFailure(f"forbidden production payload in source-only audit: {path}")
    if path.is_symlink() or not path.is_file():
        raise AuditFailure(f"{label} is not a regular non-symlink file: {path}")
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
        raise AuditFailure(f"{label} is unsafe or exceeds the bounded source size: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns
    ):
        raise AuditFailure(f"{label} changed while being read: {path}")
    return {
        "path": str(path),
        "label": label,
        "bytes": int(after.st_size),
        "sha256": digest.hexdigest(),
        "device": int(after.st_dev),
        "inode": int(after.st_ino),
        "mtime_ns": int(after.st_mtime_ns),
        "ctime_ns": int(after.st_ctime_ns),
        "regular_file": True,
        "symlink": False,
        "link_count": int(after.st_nlink),
    }


def _float(value: str, label: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise AuditFailure(f"{label} is not numeric: {value!r}") from exc


def _unit_node(root: ET.Element, tag: str, unit: str) -> ET.Element:
    nodes = [node for node in root.iter(tag) if node.get("units_comment") == unit]
    if len(nodes) != 1:
        raise AuditFailure(f"expected exactly one {tag} node with units {unit!r}, got {len(nodes)}")
    return nodes[0]


def _generated_case(label: str, path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    gravity = _unit_node(root, "gravity", "m/s^2")
    if [float(gravity.get(axis, "nan")) for axis in ("x", "y", "z")] != [0.0, 0.0, -9.81]:
        raise AuditFailure(f"{label} gravity differs from the frozen source vector")
    _unit_node(root, "rhop0", "kg/m^3")
    _unit_node(root, "massbound", "kg")
    _unit_node(root, "massfluid", "kg")
    parameters = {node.get("key"): node.get("value") for node in root.findall(".//parameter")}
    for key, expected in REQUIRED_PARAMETERS.items():
        if parameters.get(key) != expected:
            raise AuditFailure(f"{label} parameter {key} differs: {parameters.get(key)!r} != {expected!r}")
    expected = EXPECTED[label]
    if parameters.get("TimeMax") != expected["time_max"]:
        raise AuditFailure(f"{label} TimeMax differs")
    particles = root.find(".//particles")
    if particles is None:
        raise AuditFailure(f"{label} has no particles block")
    if particles.get("mkboundfirst") != "10" or particles.get("mkfluidfirst") != "1":
        raise AuditFailure(f"{label} typed first-MK values are not 10/1")
    fixed_summary = next((node for node in root.findall(".//fixed") if "begin" not in node.attrib), None)
    fluid_summary = next((node for node in root.findall(".//fluid") if "begin" not in node.attrib), None)
    if fixed_summary is None or fluid_summary is None:
        raise AuditFailure(f"{label} lacks fixed/fluid summary blocks")
    fixed_count = int(fixed_summary.get("count", "-1"))
    fluid_count = int(fluid_summary.get("count", "-1"))
    if (fixed_count, fluid_count) != (expected["fixed"], expected["fluid"]):
        raise AuditFailure(f"{label} role counts differ: fixed={fixed_count} fluid={fluid_count}")
    fixed_groups = [node for node in root.findall(".//fixed") if "begin" in node.attrib]
    fluid_groups = [node for node in root.findall(".//fluid") if "begin" in node.attrib]
    if len(fixed_groups) != 2 or any(node.get("mk") not in {"10", "11"} for node in fixed_groups):
        raise AuditFailure(f"{label} fixed groups do not use absolute MK 10/11")
    if len(fluid_groups) != 1 or fluid_groups[0].get("mkfluid") != "0" or fluid_groups[0].get("mk") != "1":
        raise AuditFailure(f"{label} fluid group does not map relative MK0 to absolute MK1")
    if sum(int(node.get("count", "-1")) for node in fixed_groups) != fixed_count:
        raise AuditFailure(f"{label} fixed MK groups do not conserve fixed count")
    if int(fluid_groups[0].get("count", "-1")) != fluid_count:
        raise AuditFailure(f"{label} fluid MK group count differs from summary")
    motion_tags = [node.tag for node in root.iter() if node.tag.lower() in {"motion", "moving", "floating"}]
    return {
        "label": label,
        "source_record": _record(path, f"{label} generated XML"),
        "gravity": {axis: float(gravity.get(axis)) for axis in ("x", "y", "z")},
        "parameters": {key: parameters[key] for key in {*REQUIRED_PARAMETERS, "TimeMax"}},
        "particles": {
            "np": int(particles.get("np", "-1")),
            "fixed_count": fixed_count,
            "fluid_count": fluid_count,
            "mkboundfirst": 10,
            "mkfluidfirst": 1,
            "fixed_absolute_mk": [10, 11],
            "fluid_relative_mk": 0,
            "fluid_absolute_mk": 1,
        },
        "motion_tags": motion_tags,
        "typed_role_status": "PASS_SOURCE_XML_RANGES",
    }


def _definition(label: str, path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    node = root.find(".//geometry/definition")
    pointref = root.find(".//geometry/definition/pointref")
    if node is None or pointref is None or node.get("units_comment") != "metres (m)":
        raise AuditFailure(f"{label} lacks the source geometry metre contract")
    shape_modes = [node.text.strip() for node in root.iter("setshapemode") if node.text and node.text.strip()]
    draw_modes = [node.get("mode") for node in root.iter("setdrawmode")]
    fluid_commands = [node.get("mk") for node in root.iter("setmkfluid")]
    if shape_modes != ["dp | actual | bound"] or draw_modes != ["full"] or fluid_commands != ["0"]:
        raise AuditFailure(f"{label} source geometry selector/control semantics changed")
    return {
        "label": label,
        "source_record": _record(path, f"{label} source Def XML"),
        "dp": float(node.get("dp")),
        "units_comment": node.get("units_comment"),
        "pointref_m": {axis: float(pointref.get(axis)) for axis in ("x", "y", "z")},
        "setshapemode": shape_modes,
        "setdrawmode": draw_modes,
        "setmkfluid": fluid_commands,
    }


def _registry_summary() -> dict[str, Any]:
    record = _record(REGISTRY, "immutable fourteen-sentinel registry")
    value = json.loads(REGISTRY.read_text(encoding="utf-8"))
    sentinels = value.get("sentinels")
    if value.get("schema") != "ds02.stage2.fourteen-sentinel-evidence-status.v4" or not isinstance(sentinels, list) or len(sentinels) != 14:
        raise AuditFailure("immutable v4 registry identity snapshot is not the expected 14-sentinel file")
    ids = [item.get("sentinel_id") for item in sentinels]
    if any(not isinstance(item, str) for item in ids) or len(set(ids)) != 14:
        raise AuditFailure("immutable v4 registry has non-unique sentinel identities")
    return {"record": record, "sentinel_count": 14, "sentinel_ids": ids, "identity_bytes_rewritten": False}


def build(output: Path) -> dict[str, Any]:
    source_records = {name: _record(path, name) for name, path in SOURCE_FILES.items()}
    source_records.update({name: _record(path, name) for name, path in XML_FILES.items()})
    definitions = [_definition("F1-S1 source Def", S1_DEF), _definition("F1-S2 medium source Def", S2_MEDIUM_DEF)]
    generated = [_generated_case(label, path) for label, path in EXPECTED_XML.items()]
    registry = _registry_summary()
    report = {
        "schema": SCHEMA,
        "status": "SOURCE_ONLY_AUTHORITY_AUDIT_COMPLETE_NO_SCIENTIFIC_Q",
        "scope": {
            "production_native_payload_read": False,
            "production_h5_vtk_read": False,
            "large_report_read": False,
            "solver_started": False,
            "gpu": False,
            "ledger_mutation": False,
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "source_records": source_records,
        "definitions": definitions,
        "generated_cases": generated,
        "authority": json.loads(CONTRACT.read_text(encoding="utf-8")),
        "registry_identity_closure": registry,
        "root207_proof_ref": {
            "root_id": "ROOT207",
            "proof_sha256": "c2016d5a36922230eafc57c49baadaeff3a2bc920bb953b5fef215eb9fda30ab",
            "payload_read_by_this_helper": False,
            "scope": "selected native header/role/mass/weighted observations only; axis UNKNOWN",
        },
        "next_minimum_gate": "Bind an actual producer writer/case source record for solver-to-world x/y/z orientation. If absent, retain component-space/typed-role/header diagnostics only; do not infer orientation from gravity or identity rotation.",
    }
    output = _path(output)
    if output.exists() or output.is_symlink():
        raise AuditFailure(f"refusing to overwrite output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


# Ordered mapping kept separate so the generated report preserves the actual
# five ROOT207 condition classes while deduplicating their source XML records.
EXPECTED_XML = {
    "f1_s1_generated": S1_XML,
    "f1_s2_coarse_generated": S2_COARSE_XML,
    "f1_s2_medium_generated": S2_MEDIUM_XML,
    "f1_s2_fine_generated": S2_FINE_XML,
}


def _self_test() -> dict[str, Any]:
    # Tiny fixture only: no production paths are opened in self-test mode.
    with tempfile.TemporaryDirectory(prefix="f1-authority-v2-") as tmp_name:
        tiny = Path(tmp_name) / "tiny.xml"
        tiny.write_text("<case><gravity x='0' y='0' z='-9.81'/></case>\n", encoding="utf-8")
        record = _record(tiny, "tiny fixture")
        assert record["bytes"] > 0 and len(record["sha256"]) == 64
    return {
        "schema": SCHEMA,
        "status": "PASS",
        "production_payload_read": False,
        "solver_started": False,
        "qualification_credit": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        print(json.dumps(_self_test(), sort_keys=True))
        return 0
    if args.output is None:
        parser.error("--output is required with --build")
    try:
        report = build(args.output)
    except Exception as exc:
        print(json.dumps({"schema": SCHEMA, "status": "BLOCKED", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"schema": report["schema"], "status": report["status"], "output": str(_path(args.output))}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
