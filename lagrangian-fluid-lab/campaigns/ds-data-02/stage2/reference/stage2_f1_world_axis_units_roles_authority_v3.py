#!/usr/bin/env python3
"""Build the additive F1 axis/units/role scope sidecar.

The v2 sidecar remains immutable.  This version records the source evidence
that closes solver-component time/velocity units and narrows the
producer-to-world orientation gate to world-frame claims.  It reads only
small XML/source/registry metadata; it never opens a production BI4/H5/VTK
payload and never starts a solver.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
# HERE is ``.../stage2/reference``; parents[4] is the DualSPHysics checkout.
PROJECT = HERE.parents[4]
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1")
CONTRACT = HERE / "stage2_f1_world_axis_units_roles_authority_contract_v3.json"
OLD_CONTRACT = HERE / "stage2_f1_world_axis_units_roles_authority_contract_v2.json"
OLD_HELPER = HERE / "stage2_f1_world_axis_units_roles_authority_v2.py"
REGISTRY = HERE / "stage2_fourteen_evidence_status_v4.json"
ROOT202 = HERE / "stage2_f1_com_observer_calibration_contract_v1.json"
ROOT207_PROOF = PROJECT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F1_NATIVE_SELECTED_OBSERVER_V5_ACTUAL_ROOT_VERIFICATION_207.json"

XMLS = {
    "f1_s1_generated": DATA / "F1_FALLBACK_ECC_COARSE/root-fallback-ecc-coarse-actual-gencase-027/prepared/F1_FALLBACK_ECC_COARSE.xml",
    "f1_s1_definition": DATA / "F1_FALLBACK_ECC_COARSE/root-fallback-ecc-coarse-actual-gencase-027/prepared/F1_FALLBACK_ECC_COARSE_Def.xml",
    "f1_s2_coarse_generated": DATA / "F1_S2_SPATIAL_COARSE_DP0p022500/f1-s2-spatial-coarse-dp0p022500-v5-primary-001/generated.xml",
    "f1_s2_medium_generated": DATA / "F1_STAGE1_DUAL_H340_DP020/root-stage1-dual-h340-actual-gencase-027/prepared/F1_STAGE1_DUAL_H340_DP020.xml",
    "f1_s2_medium_definition": DATA / "F1_STAGE1_DUAL_H340_DP020/root-stage1-dual-h340-actual-gencase-027/prepared/F1_STAGE1_DUAL_H340_DP020_Def.xml",
    "f1_s2_fine_generated": DATA / "F1_S2_SPATIAL_INTERVAL_DP0p017000/f1-s2-spatial-interval-dp0p017000-v2-primary-001/generated.xml",
}

SOURCES = {
    "jpartdata_bi4_cpp": (PROJECT / "src/source/JPartDataBi4.cpp", ["CreateArray(\"Idp\"", "CreateArray(\"Posd\"", "CreateArray(\"Vel\"", "CreateArray(\"Rhop\""]),
    "jpartdata_bi4_header": (PROJECT / "src/source/JPartDataBi4.h", ["Get_Posd", "Get_Vel", "Get_Rhop"]),
    "typesdef_header": (PROJECT / "src/source/TypesDef.h", ["float x,y,z;", "double x,y,z;"]),
    "bi4_dump_cpp": (PROJECT / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp", ["JBinaryData", "LoadFile"]),
    "jsph_header": (PROJECT / "src/source/JSph.h", ["Gravity;", "[m/s^2]"]),
    "jsph_cpp": (PROJECT / "src/source/JSph.cpp", ["time [s]", "TimeStep [s]", "TimeMax=eparms.GetValueDouble", "TimePart=eparms.GetValueDouble"]),
    "jsph_cpu_single_cpp": (PROJECT / "src/source/JSphCpuSingle.cpp", ["const double dx=dt*double(vr.x)", "TimeStep+=stepdt", "LastDt=stepdt"]),
    "jsph_gpu_simple_kernel": (PROJECT / "src/source/JSphGpuSimple_ker.cu", ["double dx=double(rvel1.x)*dt", "double dy=double(rvel1.y)*dt", "double dz=double(rvel1.z)*dt", "double dx=double(rvelrhopre.x)*dtm"]),
    "root202_contract": (ROOT202, ["velocity_unit", "time_unit", "producer_axis_orientation_metadata_required"]),
    "old_contract": (OLD_CONTRACT, ["producer_world_axis_orientation", "minimum_next_gate"]),
    "old_helper": (OLD_HELPER, ["production_payload_read", "root207_proof_ref"]),
    "registry": (REGISTRY, ["fourteen-sentinel-evidence-status.v4"]),
}

FORBIDDEN = {".bi4", ".h5", ".hdf5", ".vtk", ".vtu"}
MAX_FILE_BYTES = 16 * 1024 * 1024
SCHEMA = "ds02.stage2.f1.world-axis-units-roles-authority.v3"


class AuditFailure(RuntimeError):
    pass


def _abs(path: str | Path) -> Path:
    return Path(path).expanduser().absolute()


def _record(path: str | Path, label: str) -> dict[str, Any]:
    path = _abs(path)
    if path.suffix.lower() in FORBIDDEN:
        raise AuditFailure(f"forbidden payload suffix in source-only audit: {path}")
    if path.is_symlink() or not path.is_file():
        raise AuditFailure(f"{label} is not a regular non-symlink file: {path}")
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
        raise AuditFailure(f"{label} is missing, non-regular, or too large: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = path.stat()
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if tuple(getattr(before, f) for f in fields) != tuple(getattr(after, f) for f in fields):
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
        "link_count": int(after.st_nlink),
        "symlink": False,
    }


def _text(path: Path) -> str:
    record = _record(path, "source assertion")
    if record["bytes"] > MAX_FILE_BYTES:
        raise AuditFailure(f"source assertion unexpectedly exceeds limit: {path}")
    return path.read_text(encoding="utf-8", errors="strict")


def _assert_source(name: str, path: Path, snippets: list[str]) -> dict[str, Any]:
    text = _text(path)
    missing = [snippet for snippet in snippets if snippet not in text]
    if missing:
        raise AuditFailure(f"{name} missing source evidence: {missing}")
    record = _record(path, name)
    return {"record": record, "required_snippets": snippets, "status": "PASS_SOURCE_TEXT_BOUND"}


def _xml_summary(name: str, path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    is_definition = name.endswith("_definition")
    gravity_all = list(root.iter("gravity"))
    gravity = ([node for node in gravity_all if node.get("units_comment") == "m/s^2"]
               if not is_definition else gravity_all)
    if len(gravity) != 1 or [float(gravity[0].get(axis, "nan")) for axis in ("x", "y", "z")] != [0.0, 0.0, -9.81]:
        raise AuditFailure(f"{name} lacks the frozen F1 gravity source contract")
    if not is_definition:
        for tag, unit in (("rhop0", "kg/m^3"), ("massfluid", "kg"), ("massbound", "kg")):
            if len([node for node in root.iter(tag) if node.get("units_comment") == unit]) != 1:
                raise AuditFailure(f"{name} lacks exactly one {tag} {unit} node")
    params = {node.get("key"): node.get("value") for node in root.findall(".//parameter")}
    return {
        "record": _record(path, name),
        "gravity": {axis: float(gravity[0].get(axis)) for axis in ("x", "y", "z")},
        "units": {
            "position": "m",
            "gravity": "m/s^2",
            "density": "kg/m^3" if not is_definition else "source constants value; generated XML unit-bound",
            "mass": "kg" if not is_definition else "generated XML unit-bound",
        },
        "control": {key: params.get(key) for key in ("Boundary", "SavePosDouble", "StepAlgorithm", "VerletSteps", "Kernel", "ViscoTreatment", "Shifting", "RigidAlgorithm", "CoefDtMin", "TimeOut", "TimeMax")},
        "motion_tags": [node.tag for node in root.iter() if node.tag.lower() in {"motion", "moving", "floating"}],
        "status": "PASS_XML_UNIT_CONTROL_BINDING",
    }


def build(output: Path) -> dict[str, Any]:
    source = {name: _assert_source(name, path, snippets) for name, (path, snippets) in SOURCES.items()}
    xml = {name: _xml_summary(name, path) for name, path in XMLS.items()}
    proof_sha = "c2016d5a36922230eafc57c49baadaeff3a2bc920bb953b5fef215eb9fda30ab"
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    if registry.get("schema") != "ds02.stage2.fourteen-sentinel-evidence-status.v4" or len(registry.get("sentinels", [])) != 14:
        raise AuditFailure("fourteen-sentinel registry schema/count mismatch")
    result = {
        "schema": SCHEMA,
        "status": "SOURCE_ONLY_SCOPE_CORRECTION_COMPLETE_NO_SCIENTIFIC_Q",
        "scope": {
            "production_native_payload_read": False,
            "production_h5_vtk_read": False,
            "large_report_read": False,
            "solver_started": False,
            "ledger_mutation": False,
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "source_records": source,
        "xml_cases": xml,
        "authority": json.loads(CONTRACT.read_text(encoding="utf-8")),
        "registry_identity": {"record": source["registry"]["record"], "sentinel_count": 14, "identity_rewritten": False},
        "root207": {
            "proof_path": str(ROOT207_PROOF),
            "proof_sha256": proof_sha,
            "record_status": "FROZEN_EXTERNAL_PROOF_REFERENCE_NOT_READ_BY_THIS_SOURCE_ONLY_HELPER",
            "payload_read_by_this_helper": False,
            "scope": "native header/role/mass/selected weighted observations inherited from ROOT207; producer world-axis remains UNKNOWN",
        },
        "minimum_next_gate": {
            "component_space": "No producer-to-world record is required for a bounded component-space native diagnostic. The next F1-S2 gate is exact XML/control/role/native-proof/time joining with no interpolation.",
            "world_frame": "Require a producer writer/case source record declaring solver-to-world x/y/z orientation, with exact source SHA/stat and binary request/receipt join. Gravity alone is insufficient.",
            "velocity_time": "The SI m/s convention is source-closed for the solver component update: time [s] and dt [s] are labeled in JSph output, TimeStep advances by stepdt, and the GPU kernels update displacement as velocity times dt. The absence of an XML velocity-unit attribute is not a permanent UNKNOWN.",
        },
        "f1_s2_task": {
            "cases": ["coarse", "medium", "fine"],
            "operation": "At actual saved times, compare only native mass-weighted fluid component-space COM/velocity/KE with fixed and moving roles excluded; report asynchronous lower/upper frame IDs and times separately.",
            "no_interpolation": True,
            "no_neighbor_truth": True,
            "continuum_owner_mass": "UNKNOWN",
            "native_sample_mass_kg": {"coarse": 338.3015496656, "medium": 340.0000161491, "fine": 342.0430547278},
            "world_frame_status": "UNKNOWN_PENDING_ORIENTATION_SOURCE",
            "frozen_tolerances_unchanged": True,
            "expected_result_scope": "diagnostic metadata/field integrity only; QI/QN/QE remain UNKNOWN until the original task contract's separate gates are met",
        },
    }
    output = _abs(output)
    if output.exists() or output.is_symlink():
        raise AuditFailure(f"refusing to overwrite output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _self_test() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="f1-axis-v3-") as tmp:
        tiny = Path(tmp) / "tiny.txt"
        tiny.write_text("component x y z; time [s]; velocity*dt\n", encoding="utf-8")
        record = _record(tiny, "manufactured source fixture")
        assert record["bytes"] > 0 and len(record["sha256"]) == 64
        assert "time [s]" in tiny.read_text(encoding="utf-8")
    return {"schema": SCHEMA, "status": "PASS", "production_payload_read": False, "solver_started": False, "qualification_credit": 0}


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
        result = build(args.output)
    except Exception as exc:
        print(json.dumps({"schema": SCHEMA, "status": "BLOCKED", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"schema": result["schema"], "status": result["status"], "output": str(_abs(args.output))}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
