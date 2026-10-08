#!/usr/bin/env python3
"""Audit the existing F6 S1/S2 three-grid GenCase products.

This is a small, forward-only source audit.  It reads only the six generated
XML files, their completed GenCase receipts, the six source-definition XML
files, and the two already-consumed frame-0 JSON reports.  It never opens a
BI4/H5/VTK payload and never launches GenCase or the solver.

The report keeps the physical floating body mass (128 kg) separate from the
SPH particle sample mass.  The latter is a grid-dependent consequence of the
generated ``massfluid`` and floating-particle count, so it must not be used as
the body's physical mass.  The original-grid frame-0 reports are reused only
as bounded provenance; they do not upgrade the coarse/fine rows to a full
native identity check or grant QI/QN/QE.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from typing import Any, Iterable


SCHEMA = "ds02.stage2.f6.three-grid-initial-body-control.v1"
GENCASE_SHA256 = "a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226"
BODY_MASS_KG = 128.0
ORIGINAL_PARTICLE_MASS_KG = 0.015625
ORIGINAL_FLOATING_COUNT = 16384
ORIGINAL_SAMPLE_MASS_KG = ORIGINAL_PARTICLE_MASS_KG * ORIGINAL_FLOATING_COUNT
EXPECTED_CENTER_M = [2.4, 1.2, 1.08]
EXPECTED_INERTIA_KG_M2 = [8.53333333333, 8.53333333333, 13.6533333333]
EXPECTED_GRAVITY_M_S2 = [0.0, 0.0, -9.81]
EXPECTED_CFL = 0.2


class AuditError(ValueError):
    """Raised for a source, receipt, or semantic binding mismatch."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise AuditError(f"{label} is not a regular file: {path}")
    return path


def local_tag(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1]


def children_with_tag(node: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in node.iter() if local_tag(child) == name]


def one(node: ET.Element, name: str, *, label: str) -> ET.Element:
    found = children_with_tag(node, name)
    if not found:
        raise AuditError(f"{label} is missing <{name}>")
    return found[0]


def number(value: str | None, label: str) -> float:
    if value is None:
        raise AuditError(f"{label} has no numeric value")
    try:
        return float(value)
    except ValueError as exc:
        raise AuditError(f"{label} is not numeric: {value!r}") from exc


def vector(node: ET.Element, axes: str, label: str) -> list[float]:
    return [number(node.get(axis), f"{label}.{axis}") for axis in axes]


def canonical(node: ET.Element, *, ignore: set[tuple[str, str]] | None = None) -> tuple[Any, ...]:
    ignored = ignore or set()
    attrs = tuple(sorted(
        (key, value)
        for key, value in node.attrib.items()
        if (local_tag(node), key) not in ignored
    ))
    return (
        local_tag(node),
        attrs,
        (node.text or "").strip(),
        tuple(canonical(child, ignore=ignored) for child in list(node)),
    )


def casedef(root: ET.Element, label: str) -> ET.Element:
    found = children_with_tag(root, "casedef")
    if not found:
        raise AuditError(f"{label} has no casedef")
    return found[0]


def contract_from_casedef(node: ET.Element, label: str) -> dict[str, Any]:
    definition = one(node, "definition", label=label)
    body = one(node, "massbody", label=label)
    center = one(node, "center", label=label)
    inertia = one(node, "inertia", label=label)
    angular = one(node, "angularvelini", label=label)
    gravity = one(node, "gravity", label=label)
    cfl = one(node, "cflnumber", label=label)
    floating = one(node, "floating", label=label)
    return {
        "dp_m": number(definition.get("dp"), f"{label}.definition.dp"),
        "body_mass_kg": number(body.get("value"), f"{label}.massbody"),
        "center_m": vector(center, "xyz", f"{label}.center"),
        "inertia_kg_m2": vector(inertia, "xyz", f"{label}.inertia"),
        "angular_velocity_rad_s": vector(angular, "xyz", f"{label}.angularvelini"),
        "gravity_m_s2": vector(gravity, "xyz", f"{label}.gravity"),
        "cfl": number(cfl.get("value"), f"{label}.cflnumber"),
        "floating_mkbound": floating.get("mkbound"),
    }


def parse_source(path: Path, label: str) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    case = casedef(root, label)
    return {
        "contract": contract_from_casedef(case, label),
        "casedef": canonical(case),
        # dp and angular velocity are intentionally omitted from this key for
        # the cross-grid physical-contract comparison.
        "physical_canonical": canonical(case, ignore={
            ("definition", "dp"),
            ("angularvelini", "x"),
            ("angularvelini", "y"),
            ("angularvelini", "z"),
            ("angularvelini", "units_comment"),
        }),
    }


def parse_generated(path: Path, label: str) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    case = casedef(root, label)
    contract = contract_from_casedef(case, label)
    particles = one(root, "particles", label=label)
    counts: dict[str, int] = {}
    for child in list(particles):
        name = local_tag(child)
        if name in {"fixed", "floating", "fluid", "moving"} and child.get("count") is not None:
            counts[name] = counts.get(name, 0) + int(child.get("count"))
    if not {"fixed", "floating", "fluid"}.issubset(counts):
        raise AuditError(f"{label} particles do not contain fixed/floating/fluid counts")
    masspart = one(root, "masspart", label=label)
    massfluid = one(root, "massfluid", label=label)
    return {
        "contract": contract,
        "casedef": canonical(case),
        "physical_canonical": canonical(case, ignore={
            ("definition", "dp"),
            ("angularvelini", "x"),
            ("angularvelini", "y"),
            ("angularvelini", "z"),
            ("angularvelini", "units_comment"),
        }),
        "counts": counts,
        "total_particles": sum(counts.values()),
        "masspart_kg": number(masspart.get("value"), f"{label}.masspart"),
        "massfluid_kg": number(massfluid.get("value"), f"{label}.massfluid"),
        "sample_floating_mass_kg": counts["floating"] * number(massfluid.get("value"), f"{label}.massfluid"),
    }


def _path_from_command(command_value: Any, label: str) -> Path:
    if not isinstance(command_value, str):
        raise AuditError(f"{label} command element is not a string")
    return Path(command_value).expanduser().resolve()


def validate_receipt(row: dict[str, Any], source: Path, generated: Path, receipt_path: Path) -> dict[str, Any]:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise AuditError(f"{row['sentinel_id']}/{row['grid_id']} GenCase receipt is not completed")
    command = receipt.get("command")
    if not isinstance(command, list) or len(command) < 4:
        raise AuditError(f"{row['sentinel_id']}/{row['grid_id']} receipt has no complete GenCase command")
    gencase = Path(row["gencase_binary"]).expanduser().resolve()
    if _path_from_command(command[0], "GenCase") != gencase:
        raise AuditError(f"{row['sentinel_id']}/{row['grid_id']} receipt invokes a different GenCase binary")
    if receipt.get("binary_sha256") != row["gencase_sha256"]:
        raise AuditError(f"{row['sentinel_id']}/{row['grid_id']} GenCase binary digest mismatch")
    source_stem = source.with_suffix("").resolve()
    if _path_from_command(command[1], "GenCase source") != source_stem:
        raise AuditError(f"{row['sentinel_id']}/{row['grid_id']} receipt source definition mismatch")
    generated_prefix = generated.with_suffix("").resolve()
    if _path_from_command(command[2], "GenCase output") != generated_prefix:
        raise AuditError(f"{row['sentinel_id']}/{row['grid_id']} receipt generated output mismatch")
    if "-save:all" not in command[3:]:
        raise AuditError(f"{row['sentinel_id']}/{row['grid_id']} receipt omitted -save:all")
    launch_hashes = receipt.get("input_hashes_at_launch") or {}
    if launch_hashes.get(str(source)) != row["source_definition"]["sha256"]:
        raise AuditError(f"{row['sentinel_id']}/{row['grid_id']} receipt did not bind source definition digest")
    if launch_hashes.get(str(gencase)) != row["gencase_sha256"]:
        raise AuditError(f"{row['sentinel_id']}/{row['grid_id']} receipt did not bind GenCase digest")
    return {
        "path": str(receipt_path),
        "sha256": sha256(receipt_path),
        "status": receipt["status"],
        "returncode": receipt["returncode"],
        "command": command,
        "binary_sha256": receipt["binary_sha256"],
        "total_particles": receipt.get("total_particles"),
        "fluid_particles": receipt.get("fluid_particles"),
    }


def validate_frame0(row: dict[str, Any], generated: dict[str, Any]) -> dict[str, Any] | None:
    binding = row.get("initial_frame_check")
    if binding is None:
        return None
    path = require_file(binding["path"], f"{row['sentinel_id']} initial-frame report")
    if sha256(path) != binding["sha256"]:
        raise AuditError(f"{row['sentinel_id']} initial-frame report digest mismatch")
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("status") != "PASS":
        raise AuditError(f"{row['sentinel_id']} initial-frame report is not PASS")
    scope = report.get("scope") or {}
    if scope.get("frame_index") != 0 or scope.get("full_time_scan") is not False:
        raise AuditError(f"{row['sentinel_id']} initial-frame scope is broader or not frame zero")
    generated_input = (report.get("inputs") or {}).get("generated_xml") or {}
    reference_binding = binding.get("reference_generated_xml")
    if not isinstance(reference_binding, dict):
        raise AuditError(f"{row['sentinel_id']} initial-frame reference XML binding is missing")
    reference_xml = require_file(reference_binding["path"], f"{row['sentinel_id']} initial-frame reference XML")
    if sha256(reference_xml) != reference_binding["sha256"]:
        raise AuditError(f"{row['sentinel_id']} initial-frame reference XML digest mismatch")
    if Path(str(generated_input.get("path", ""))).expanduser().resolve() != reference_xml:
        raise AuditError(f"{row['sentinel_id']} initial-frame report binds another generated XML path")
    if generated_input.get("sha256") != reference_binding["sha256"]:
        raise AuditError(f"{row['sentinel_id']} initial-frame report binds another generated XML digest")
    typed_blocks = (report.get("typed") or {}).get("blocks_from_generated_xml") or []
    counts = {str(item.get("tag")): int(item["count"]) for item in typed_blocks if item.get("tag")}
    expected = row["expected_counts"]
    if counts and any(counts.get(key) != expected[key] for key in ("fixed", "floating", "fluid")):
        raise AuditError(f"{row['sentinel_id']} initial-frame typed blocks disagree with grid counts")
    return {
        "path": str(path),
        "sha256": sha256(path),
        "status": report["status"],
        "scope": {
            "frame_index": scope.get("frame_index"),
            "raw_read": scope.get("raw_read"),
            "typed_read": scope.get("typed_read"),
            "full_time_scan": scope.get("full_time_scan"),
            "full_hdf5_rehash": scope.get("full_hdf5_rehash"),
        },
        "reference_generated_xml": {
            "path": str(reference_xml),
            "sha256": reference_binding["sha256"],
            "scope": "consumed original-sentinel GenCase XML; separate from this three-grid row's XML",
        },
        "native_identity_scope": "ORIGINAL_GRID_FRAME0_ONLY",
    }


def audit(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest_path = require_file(manifest_path, "manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "ds02.stage2.f6.three-grid-initial-body-control.manifest.v1":
        raise AuditError("unexpected F6 three-grid manifest schema")
    if manifest.get("read_policy", {}).get("h5_bi4_vtk_opened") is not False:
        raise AuditError("manifest must explicitly prohibit H5/BI4/VTK reads")
    gencase = require_file(manifest["gencase_binary"]["path"], "official GenCase binary")
    if sha256(gencase) != manifest["gencase_binary"]["sha256"]:
        raise AuditError("official GenCase binary digest changed")
    if manifest["gencase_binary"]["sha256"] != GENCASE_SHA256:
        raise AuditError("manifest is bound to an unexpected official GenCase binary")
    rows = manifest.get("rows")
    if not isinstance(rows, list) or len(rows) != 6:
        raise AuditError("manifest must contain exactly six S1/S2 grid rows")
    source_physical_keys: list[tuple[Any, ...]] = []
    records: list[dict[str, Any]] = []
    for row in rows:
        for forbidden in (".h5", ".bi4", ".obi4", ".vtk"):
            if forbidden in json.dumps(row).lower():
                raise AuditError(f"row {row.get('sentinel_id')}/{row.get('grid_id')} contains forbidden payload path")
        source_binding = row["source_definition"]
        source = require_file(source_binding["path"], "source definition")
        generated_binding = row["generated_xml"]
        generated = require_file(generated_binding["path"], "generated XML")
        receipt_binding = row["receipt"]
        receipt = require_file(receipt_binding["path"], "GenCase receipt")
        if sha256(source) != source_binding["sha256"]:
            raise AuditError(f"{row['sentinel_id']}/{row['grid_id']} source definition digest changed")
        if sha256(generated) != generated_binding["sha256"]:
            raise AuditError(f"{row['sentinel_id']}/{row['grid_id']} generated XML digest changed")
        if sha256(receipt) != receipt_binding["sha256"]:
            raise AuditError(f"{row['sentinel_id']}/{row['grid_id']} receipt digest changed")
        source_summary = parse_source(source, f"{row['sentinel_id']}/{row['grid_id']} source")
        generated_summary = parse_generated(generated, f"{row['sentinel_id']}/{row['grid_id']} generated")
        contract = generated_summary["contract"]
        if source_summary["casedef"] != generated_summary["casedef"]:
            raise AuditError(f"{row['sentinel_id']}/{row['grid_id']} generated casedef is not source casedef")
        if generated_summary["physical_canonical"] != source_summary["physical_canonical"]:
            raise AuditError(f"{row['sentinel_id']}/{row['grid_id']} generated physical contract differs from source")
        if abs(contract["dp_m"] - float(row["dp_m"])) > 0.0:
            raise AuditError(f"{row['sentinel_id']}/{row['grid_id']} dp mismatch")
        for actual, expected, label in (
            (contract["angular_velocity_rad_s"], row["angular_velocity_rad_s"], "angular velocity"),
            (contract["center_m"], EXPECTED_CENTER_M, "center"),
            (contract["inertia_kg_m2"], EXPECTED_INERTIA_KG_M2, "inertia"),
            (contract["gravity_m_s2"], EXPECTED_GRAVITY_M_S2, "gravity"),
        ):
            if any(abs(float(a) - float(e)) > 1e-12 for a, e in zip(actual, expected)):
                raise AuditError(f"{row['sentinel_id']}/{row['grid_id']} {label} mismatch")
        if abs(contract["body_mass_kg"] - BODY_MASS_KG) > 1e-12:
            raise AuditError(f"{row['sentinel_id']}/{row['grid_id']} body mass is not 128 kg")
        if abs(contract["cfl"] - EXPECTED_CFL) > 1e-12:
            raise AuditError(f"{row['sentinel_id']}/{row['grid_id']} CFL mismatch")
        if generated_summary["counts"] != {k: int(v) for k, v in row["expected_counts"].items()}:
            raise AuditError(f"{row['sentinel_id']}/{row['grid_id']} particle counts mismatch")
        if int(json.loads(receipt.read_text(encoding="utf-8")).get("total_particles", -1)) != generated_summary["total_particles"]:
            raise AuditError(f"{row['sentinel_id']}/{row['grid_id']} receipt total count mismatch")
        if int(json.loads(receipt.read_text(encoding="utf-8")).get("fluid_particles", -1)) != generated_summary["counts"]["fluid"]:
            raise AuditError(f"{row['sentinel_id']}/{row['grid_id']} receipt fluid count mismatch")
        receipt_summary = validate_receipt(row, source, generated, receipt)
        frame0 = validate_frame0(row, generated_summary)
        source_physical_keys.append(source_summary["physical_canonical"])
        records.append({
            "sentinel_id": row["sentinel_id"],
            "physical_case_id": row["physical_case_id"],
            "grid_id": row["grid_id"],
            "dp_m": contract["dp_m"],
            "source_definition": {"path": str(source), "sha256": source_binding["sha256"]},
            "generated_xml": {"path": str(generated), "sha256": generated_binding["sha256"]},
            "gencase_receipt": receipt_summary,
            "angular_velocity_rad_s": contract["angular_velocity_rad_s"],
            "counts": generated_summary["counts"],
            "masspart_kg": generated_summary["masspart_kg"],
            "massfluid_kg": generated_summary["massfluid_kg"],
            "sample_floating_mass_kg": generated_summary["sample_floating_mass_kg"],
            "physical_body_mass_kg": BODY_MASS_KG,
            "frame0_provenance": frame0,
        })
    if len(set(source_physical_keys)) != 1:
        raise AuditError("S1/S2 source geometry/control contract is not common after excluding dp and angular release")
    by_sentinel: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_sentinel.setdefault(record["sentinel_id"], []).append(record)
    for sentinel, group in by_sentinel.items():
        if len(group) != 3:
            raise AuditError(f"{sentinel} does not have coarse/original/fine rows")
        velocities = {tuple(row["angular_velocity_rad_s"]) for row in group}
        if len(velocities) != 1:
            raise AuditError(f"{sentinel} angular control is not common across its three grids")
    report = {
        "schema": SCHEMA,
        "status": "completed_source_xml_receipt_audit",
        "manifest": {"path": str(manifest_path), "sha256": sha256(manifest_path)},
        "rows": records,
        "comparability": {
            "sentinels": sorted(by_sentinel),
            "grid_count": len(records),
            "source_xml_geometry_and_control_excluding_dp_and_omega": "PASS",
            "official_gencase_receipt_source_output_bindings": "PASS",
            "three_grid_particle_count_and_dp_bindings": "PASS",
            "native_identity": "UNKNOWN_EXCEPT_REUSED_ORIGINAL_FRAME0_SCOPE",
            "original_frame0_scope": "two original-grid JSON reports only; not a full grid/time identity audit",
        },
        "mass_semantics": {
            "physical_floating_body_mass_kg": BODY_MASS_KG,
            "original_grid_particle_mass_kg": ORIGINAL_PARTICLE_MASS_KG,
            "original_grid_floating_particle_count": ORIGINAL_FLOATING_COUNT,
            "original_grid_sample_floating_mass_kg": ORIGINAL_SAMPLE_MASS_KG,
            "sample_mass_definition": "generated floating particle count multiplied by generated massfluid; grid-dependent",
            "body_and_sample_are_not_interchangeable": True,
        },
        "scientific_status": {
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "physical_fate": "UNKNOWN",
            "dynamics": "UNKNOWN",
            "note": "This source/receipt audit supplies comparability evidence only; it is not a solver or trajectory qualification.",
        },
        "read_policy": {
            "xml_json_only": True,
            "h5_opened": False,
            "bi4_opened": False,
            "vtk_opened": False,
            "gencase_launched": False,
            "solver_launched": False,
            "old_products_modified": False,
        },
    }
    output_path = Path(output_path).expanduser().resolve()
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite output: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return report


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main() -> int:
    try:
        args = parser().parse_args()
        report = audit(Path(args.manifest), Path(args.output))
    except Exception as exc:
        print(f"F6 three-grid source audit failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "schema": report["schema"],
        "status": report["status"],
        "rows": len(report["rows"]),
        "native_identity": report["comparability"]["native_identity"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
