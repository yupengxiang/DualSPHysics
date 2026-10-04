#!/usr/bin/env python3
"""Root-only fresh070 adapter for the unchanged strict F6 initial-native QA.

The adapter keeps the QA066 official PartVTK worker and its typed checks.  It
changes only the binding contract: five internal omega endpoints, direct
GenCase069 roots, actual completed GenCase receipts, and canonical owners
materialized by Root before enablement.  This source file itself never starts
PartVTK; Root runs it only through the disabled request.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping

BASE_WORKER = Path(
    "/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/"
    "handoff_20261003/root_followup_066_stage1_omega_initial_native_qa_contract_fix_v1/"
    "workers/run_f6_initial_native_qa_v1.py"
)
RESULT_SCHEMA = "ds02.f6.stage1-omega-initial-native-qa-result.v3"
BINDING_SCHEMA = "ds02.f6.stage1-omega-initial-native-qa-binding.v3"
CANONICAL_SCHEMA = "ds02.root.f6.prospective-endpoint-canonical-owner.v1"
EXPECTED_COUNTS = {"dimension": 3, "fixed": 73441, "moving": 0, "floating": 16384, "fluid": 327680, "total": 417505}
CENTER = [2.4, 1.2, 1.08]
TANK_SIZE = [4.8, 2.4, 2.4]

_spec = importlib.util.spec_from_file_location("f6_qa066_base", BASE_WORKER)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"cannot load QA066 worker: {BASE_WORKER}")
_base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_base)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(path: Path, label: str) -> Path:
    if not path.is_file():
        raise _base.QAError(f"{label} is missing: {path}")
    return path


def load(path: Path, label: str) -> dict[str, Any]:
    require(path, label)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise _base.QAError(f"{label} is not a JSON object: {path}")
    return value


def close(left: list[float], right: list[float], tolerance: float = 1e-12) -> bool:
    return len(left) == len(right) and all(abs(float(a) - float(b)) <= tolerance for a, b in zip(left, right))


def vector(node: ET.Element | None, label: str) -> list[float]:
    if node is None:
        raise _base.QAError(f"missing XML node: {label}")
    values = []
    for axis in "xyz":
        raw = node.get(axis)
        if raw is None:
            raise _base.QAError(f"missing XML {label}.{axis}")
        value = float(raw)
        if not math.isfinite(value):
            raise _base.QAError(f"nonfinite XML {label}.{axis}")
        values.append(value)
    return values


def geometry_fingerprint(root: ET.Element) -> list[tuple[str, tuple[tuple[str, str], ...]]]:
    keep = {
        "definition", "pointref", "pointmin", "pointmax", "setdrawmode",
        "setmkfluid", "setmkbound", "drawbox", "boxfill", "point", "size",
        "shapeout", "commands", "mainlist",
    }
    return [
        (node.tag, tuple(sorted(node.attrib.items())))
        for node in root.findall(".//geometry//*")
        if node.tag in keep
    ]


def verify_owner(endpoint: Mapping[str, Any]) -> dict[str, Any]:
    owner_path = Path(str(endpoint["canonical_owner"]))
    owner = load(owner_path, f"canonical owner {endpoint['case_id']}")
    expected_hash = endpoint.get("canonical_owner_sha256")
    observed_hash = sha256(owner_path)
    if expected_hash and observed_hash != str(expected_hash):
        raise _base.QAError(
            f"canonical owner hash mismatch for {endpoint['case_id']}: "
            f"{observed_hash} != {expected_hash}"
        )
    case_id = str(endpoint["case_id"])
    if owner.get("schema") != CANONICAL_SCHEMA:
        raise _base.QAError(f"canonical owner schema drift: {case_id}")
    if owner.get("family_id") != "F6" or owner.get("case_id") != case_id or owner.get("physical_case_id") != case_id:
        raise _base.QAError(f"canonical owner case identity drift: {case_id}")
    condition = owner.get("physical_condition_sha256")
    if not isinstance(condition, str) or len(condition) != 64:
        raise _base.QAError(f"canonical physical condition hash is not bound: {case_id}")
    binding = owner.get("physical_binding")
    if not isinstance(binding, dict) or binding.get("physical_case_id") != case_id:
        raise _base.QAError(f"canonical physical binding is missing: {case_id}")
    params = binding.get("parameters")
    if not isinstance(params, dict):
        raise _base.QAError(f"canonical parameters are missing: {case_id}")
    if not close([float(x) for x in params.get("body_center_m", [])], list(CENTER)):
        raise _base.QAError(f"canonical center drift: {case_id}")
    if abs(float(params.get("body_mass_kg", float("nan"))) - 128.0) > 1e-12:
        raise _base.QAError(f"canonical physical mass drift: {case_id}")
    expected_omega = [float(x) for x in endpoint["omega_rad_s"]]
    actual_omega = [float(x) for x in params.get("initial_angular_velocity_rad_s", [])]
    if not close(actual_omega, expected_omega):
        raise _base.QAError(f"canonical omega drift: {case_id}")
    if params.get("translation_dof") != [1, 1, 1] or params.get("rotation_dof") != [1, 1, 1]:
        raise _base.QAError(f"canonical free-6DOF drift: {case_id}")
    controls = binding.get("controls", {})
    if controls.get("dp_m") is not None and abs(float(controls["dp_m"]) - 0.025) > 1e-12:
        raise _base.QAError(f"canonical dp drift: {case_id}")
    if controls.get("forcing") not in (None, "none"):
        raise _base.QAError(f"canonical forcing drift: {case_id}")
    return {
        "path": str(owner_path),
        "sha256": observed_hash,
        "physical_condition_sha256": condition,
        "case_id": case_id,
        "omega_rad_s": actual_omega,
    }


def verify_xml_geometry(endpoint: Mapping[str, Any]) -> None:
    source = ET.parse(require(Path(str(endpoint["source_definition"])), "source XML")).getroot()
    generated_path = require(Path(str(endpoint["generated_xml"])), "generated XML")
    generated = ET.parse(generated_path).getroot()
    if geometry_fingerprint(source) != geometry_fingerprint(generated):
        raise _base.QAError(f"source/generated geometry fingerprint differs: {endpoint['case_id']}")
    definition = generated.find(".//geometry/definition")
    if definition is None or abs(float(definition.get("dp", "nan")) - 0.025) > 1e-12:
        raise _base.QAError(f"generated geometry dp drift: {endpoint['case_id']}")
    sizes = [
        [float(node.get(axis, "nan")) for axis in "xyz"]
        for node in generated.findall(".//geometry/size")
    ]
    if not any(close(size, TANK_SIZE) for size in sizes):
        raise _base.QAError(f"generated tank geometry missing: {endpoint['case_id']}")


def verify_direct_gencase(endpoint: Mapping[str, Any]) -> None:
    case_id = str(endpoint["case_id"])
    generated = require(Path(str(endpoint["generated_xml"])), f"generated XML {case_id}")
    bi4 = require(Path(str(endpoint["generated_bi4"])), f"generated BI4 {case_id}")
    receipt_path = require(Path(str(endpoint["execution_receipt"])), f"GenCase receipt {case_id}")
    if generated.parent != Path(str(endpoint["gencase_attempt_root"])):
        raise _base.QAError(f"generated XML is not in direct GenCase root: {case_id}")
    if bi4.parent != generated.parent or "/prepared/" in str(generated):
        raise _base.QAError(f"prepared-prefix or split GenCase input: {case_id}")
    if sha256(generated) != str(endpoint["generated_xml_sha256"]):
        raise _base.QAError(f"generated XML hash mismatch: {case_id}")
    if sha256(bi4) != str(endpoint["generated_bi4_sha256"]):
        raise _base.QAError(f"generated BI4 hash mismatch: {case_id}")
    if sha256(receipt_path) != str(endpoint["execution_receipt_sha256"]):
        raise _base.QAError(f"GenCase receipt hash mismatch: {case_id}")
    receipt = load(receipt_path, f"GenCase receipt {case_id}")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise _base.QAError(f"GenCase is not completed/0: {case_id}")
    if int(receipt.get("total_particles", -1)) != EXPECTED_COUNTS["total"]:
        raise _base.QAError(f"GenCase total count drift: {case_id}")
    if int(receipt.get("fluid_particles", -1)) != EXPECTED_COUNTS["fluid"]:
        raise _base.QAError(f"GenCase fluid count drift: {case_id}")
    if int(receipt.get("solver_dimension_from_gencase", -1)) != EXPECTED_COUNTS["dimension"]:
        raise _base.QAError(f"GenCase dimension drift: {case_id}")
    verify_xml_geometry(endpoint)


def validate_binding(
    binding_path: Path,
    binding: Mapping[str, Any],
    partvtk: Path,
    expected_partvtk_sha256: str,
) -> None:
    if binding.get("schema") != BINDING_SCHEMA or binding.get("status") != "source_only_disabled":
        raise _base.QAError("fresh070 QA binding schema/status is not source-only disabled")
    if binding.get("launch_allowed") is not False or binding.get("root_only") is not True:
        raise _base.QAError("fresh070 QA binding is launchable or not Root-only")
    _base.verify_hash(partvtk, expected_partvtk_sha256, "official PartVTK")
    historical = binding.get("historical_evidence")
    if not isinstance(historical, list) or len(historical) != 2:
        raise _base.QAError("historical QA/semantic evidence must contain exactly two immutable records")
    for item in historical:
        if not isinstance(item, dict):
            raise _base.QAError("malformed historical evidence record")
        _base.verify_hash(Path(str(item["path"])), str(item["sha256"]), str(item.get("id", "historical evidence")))
    endpoints = binding.get("endpoints")
    if not isinstance(endpoints, list) or len(endpoints) != 5:
        raise _base.QAError("fresh070 must bind exactly five internal GenCase endpoints")
    seen: set[str] = set()
    for endpoint in endpoints:
        if not isinstance(endpoint, dict):
            raise _base.QAError("malformed endpoint binding")
        case_id = str(endpoint.get("case_id", ""))
        if not case_id or case_id in seen or str(endpoint.get("endpoint_id")) != case_id:
            raise _base.QAError(f"endpoint identity drift: {case_id}")
        seen.add(case_id)
        if endpoint.get("source_plan_condition_sha256") is not None:
            raise _base.QAError(f"new internal endpoint must keep source-plan condition null: {case_id}")
        expected_counts = {str(k): int(v) for k, v in endpoint.get("expected_counts", {}).items()}
        if expected_counts != EXPECTED_COUNTS:
            raise _base.QAError(f"native count contract drift: {case_id}")
        source = Path(str(endpoint["source_definition"]))
        _base.verify_hash(source, str(endpoint["source_definition_sha256"]), f"source definition {case_id}")
        verify_direct_gencase(endpoint)
        verify_owner(endpoint)

    if seen != {str(x["case_id"]) for x in endpoints}:
        raise _base.QAError("endpoint set is not closed")


def run(
    binding_path: Path,
    output_root: Path,
    partvtk_path: Path,
    expected_partvtk_sha256: str,
    threads: int,
) -> int:
    _base.SCHEMA = RESULT_SCHEMA
    _base.BINDING_SCHEMA = BINDING_SCHEMA
    _base.validate_binding = validate_binding
    return _base.run(binding_path, output_root, partvtk_path, expected_partvtk_sha256, threads)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--partvtk-exe", type=Path, default=Path(_base.DEFAULT_PARTVTK))
    parser.add_argument("--expected-partvtk-sha256", default=_base.DEFAULT_PARTVTK_SHA256)
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args()
    return run(args.binding, args.output_root, args.partvtk_exe, args.expected_partvtk_sha256, args.threads)


if __name__ == "__main__":
    raise SystemExit(main())

