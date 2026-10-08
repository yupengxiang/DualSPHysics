#!/usr/bin/env python3
"""Audit F6 fluid-owner authority without opening native payloads.

The XML ``drawbox`` used to generate fluid particles is reported as a
discrete producer selector.  It is not promoted to a continuous fluid-owner
contract unless the source itself carries an explicit owner declaration.  The
six existing S1/S2 XML/receipt pairs are therefore useful for body-contract
and sample-mass diagnostics while the continuum fluid-owner status remains
explicitly UNKNOWN in the current source.  A prose drawbox comment is never
treated as an owner contract; only a separately linked, hash-bound authority
record could establish one.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any
import xml.etree.ElementTree as ET


SCHEMA = "ds02.stage2.f6.fluid-owner-authority-audit.v2"
BODY_MASS_KG = 128.0
BODY_CENTER_M = [2.4, 1.2, 1.08]
BODY_INERTIA_KG_M2 = [8.53333333333, 8.53333333333, 13.6533333333]
ORIGINAL_FLUID_SAMPLE_MASS_KG = 5120.0
GENCASE_SHA256 = "a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226"


class AuditError(ValueError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise AuditError(f"missing input: {path}")
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
            "ctime_ns": stat.st_ctime_ns, "st_dev": stat.st_dev, "st_ino": stat.st_ino,
            "sha256": sha256(path)}


def require_file(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise AuditError(f"{label} is not a regular file: {path}")
    return path


def write_new(path: Path, value: Any) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def local(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1]


def first(root: ET.Element, name: str, label: str) -> ET.Element:
    for node in root.iter():
        if local(node) == name:
            return node
    raise AuditError(f"{label} has no <{name}>")


def num(value: str | None, label: str) -> float:
    if value is None:
        raise AuditError(f"{label} has no number")
    try:
        result = float(value)
    except ValueError as exc:
        raise AuditError(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise AuditError(f"{label} is not finite")
    return result


def vec(node: ET.Element, label: str) -> list[float]:
    return [num(node.get(axis), f"{label}.{axis}") for axis in "xyz"]


def canonical(node: ET.Element) -> tuple[Any, ...]:
    return (local(node), tuple(sorted(node.attrib.items())), (node.text or "").strip(),
            tuple(canonical(child) for child in list(node)))


def drawboxes(root: ET.Element) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for mainlist in (node for node in root.iter() if local(node) == "mainlist"):
        active_fluid: int | None = None
        active_bound: int | None = None
        for node in list(mainlist):
            kind = local(node)
            if kind == "setmkfluid":
                active_fluid, active_bound = int(node.get("mk", "0")), None
                continue
            if kind == "setmkbound":
                active_fluid, active_bound = None, int(node.get("mk", "0"))
                continue
            if kind != "drawbox":
                continue
            point = next((child for child in node if local(child) == "point"), None)
            size = next((child for child in node if local(child) == "size"), None)
            if point is None or size is None:
                raise AuditError("drawbox is missing point/size")
            if active_fluid is None:
                continue
            low = vec(point, "fluid.drawbox.point")
            size_m = vec(size, "fluid.drawbox.size")
            result.append({
                "mkfluid": active_fluid, "boxfill": next((child.text or "" for child in node if local(child) == "boxfill"), "").strip(),
                "comment": node.get("cmt") or node.get("comment"), "low_m": low, "size_m": size_m,
                "volume_m3": math.prod(size_m),
            })
    return result


def xml_summary(path: Path, label: str) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    case = first(root, "casedef", label)
    definition = first(case, "definition", label)
    particles = first(root, "particles", label)
    massfluid = first(root, "massfluid", label)
    massbody = first(case, "massbody", label)
    center = first(case, "center", label)
    inertia = first(case, "inertia", label)
    counts: dict[str, int] = {}
    for child in list(particles):
        if local(child) in {"fixed", "floating", "fluid", "moving"} and child.get("count") is not None:
            counts[local(child)] = counts.get(local(child), 0) + int(child.get("count"))
    return {
        "casedef": canonical(case), "dp_m": num(definition.get("dp"), f"{label}.dp"),
        "counts": counts, "massfluid_kg": num(massfluid.get("value"), f"{label}.massfluid"),
        "fluid_sample_mass_kg": counts.get("fluid", 0) * num(massfluid.get("value"), f"{label}.massfluid"),
        "body_mass_kg": num(massbody.get("value"), f"{label}.massbody"),
        "body_center_m": vec(center, f"{label}.center"), "body_inertia_kg_m2": vec(inertia, f"{label}.inertia"),
        "fluid_drawboxes": drawboxes(root),
    }


def classify_sample(sample: float, target: float) -> dict[str, Any]:
    error = sample / target - 1.0
    if abs(error) <= 0.01:
        gate = "PASS_TARGET_ONE_PERCENT_DIAGNOSTIC"
    elif abs(error) <= 0.02:
        gate = "MARGINAL_TARGET_ONE_TO_TWO_PERCENT_DIAGNOSTIC"
    else:
        gate = "HARDFAIL_TARGET_OVER_TWO_PERCENT"
    return {"target_sample_mass_kg": target, "candidate_sample_mass_kg": sample,
            "error_fraction": error, "error_percent": error * 100.0, "gate": gate,
            "basis": "frozen original-grid discrete fluid sample mass; not continuum owner"}


def audit(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest_path = require_file(manifest_path, "manifest")
    manifest_pre = record(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "ds02.stage2.f6.fluid-owner-authority-audit.manifest.v2":
        raise AuditError("unexpected F6 source manifest schema")
    rows = manifest.get("rows")
    if not isinstance(rows, list) or len(rows) != 6:
        raise AuditError("F6 source manifest must contain six rows")
    source_manifest = require_file(manifest["source_manifest"]["path"], "source three-grid manifest")
    paths: dict[str, Path] = {"manifest": manifest_path, "source_manifest": source_manifest}
    for i, row in enumerate(rows):
        for role, label in (("source_definition", "source XML"), ("generated_xml", "generated XML"), ("receipt", "GenCase receipt")):
            paths[f"row{i}.{role}"] = require_file(row[role]["path"], f"{row['sentinel_id']}/{row['grid_id']} {label}")
    pre = {key: record(path) for key, path in paths.items()}
    if pre["manifest"] != manifest_pre:
        raise AuditError("manifest changed before XML audit")
    if pre["source_manifest"]["sha256"] != manifest["source_manifest"]["sha256"]:
        raise AuditError("source three-grid manifest digest changed")
    official = require_file(manifest["gencase_binary"]["path"], "official GenCase binary")
    official_record = record(official)
    if official_record["sha256"] != GENCASE_SHA256:
        raise AuditError("official GenCase digest mismatch")
    records: list[dict[str, Any]] = []
    drawbox_shapes: list[tuple[Any, ...]] = []
    targets: dict[str, float] = {}
    parsed: list[tuple[int, dict[str, Any], dict[str, Any], dict[str, Any], Path, Path, Path]] = []
    for i, row in enumerate(rows):
        source = paths[f"row{i}.source_definition"]
        generated = paths[f"row{i}.generated_xml"]
        receipt_path = paths[f"row{i}.receipt"]
        if pre[f"row{i}.source_definition"]["sha256"] != row["source_definition"]["sha256"]:
            raise AuditError(f"{row['sentinel_id']}/{row['grid_id']} source XML changed")
        if pre[f"row{i}.generated_xml"]["sha256"] != row["generated_xml"]["sha256"]:
            raise AuditError(f"{row['sentinel_id']}/{row['grid_id']} generated XML changed")
        if pre[f"row{i}.receipt"]["sha256"] != row["receipt"]["sha256"]:
            raise AuditError(f"{row['sentinel_id']}/{row['grid_id']} receipt changed")
        source_summary = xml_summary(source, f"{row['sentinel_id']}/{row['grid_id']} source")
        generated_summary = xml_summary(generated, f"{row['sentinel_id']}/{row['grid_id']} generated")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
            raise AuditError(f"{row['sentinel_id']}/{row['grid_id']} receipt is not completed")
        if source_summary["casedef"] != generated_summary["casedef"]:
            raise AuditError(f"{row['sentinel_id']}/{row['grid_id']} source/generated casedef differs")
        for actual, expected, label in ((generated_summary["body_mass_kg"], BODY_MASS_KG, "body mass"),):
            if abs(actual - expected) > 1e-12:
                raise AuditError(f"{row['sentinel_id']}/{row['grid_id']} {label} differs")
        if generated_summary["body_center_m"] != BODY_CENTER_M or any(abs(a - b) > 1e-12 for a, b in zip(generated_summary["body_inertia_kg_m2"], BODY_INERTIA_KG_M2)):
            raise AuditError(f"{row['sentinel_id']}/{row['grid_id']} body contract differs")
        if not generated_summary["fluid_drawboxes"]:
            raise AuditError(f"{row['sentinel_id']}/{row['grid_id']} has no fluid drawbox")
        shape = tuple((tuple(x["low_m"]), tuple(x["size_m"]), x["boxfill"], x["comment"]) for x in generated_summary["fluid_drawboxes"])
        drawbox_shapes.append(shape)
        parsed.append((i, row, source_summary, generated_summary, source, generated, receipt_path))
        if row["grid_id"] == "original":
            targets[row["sentinel_id"]] = generated_summary["fluid_sample_mass_kg"]
    if len(set(drawbox_shapes)) != 1:
        raise AuditError("fluid drawbox producer geometry is not common across six grids")
    for i, row, source_summary, generated_summary, source, generated, receipt_path in parsed:
        target = targets[row["sentinel_id"]]
        comments = [x["comment"] for x in generated_summary["fluid_drawboxes"] if x["comment"]]
        records.append({
            "sentinel_id": row["sentinel_id"], "grid_id": row["grid_id"], "physical_case_id": row["physical_case_id"],
            "dp_m": generated_summary["dp_m"], "source_definition": pre[f"row{i}.source_definition"],
            "generated_xml": pre[f"row{i}.generated_xml"], "receipt": pre[f"row{i}.receipt"],
            "fluid_drawbox_producer_selector": generated_summary["fluid_drawboxes"],
            "continuous_fluid_owner_authority": "UNKNOWN_NO_LINKED_CONTINUOUS_OWNER_CONTRACT",
            "owner_authority_evidence": {
                "linked_contract": None,
                "source_drawbox_comments": comments,
                "comments_are_not_authority": True,
            },
            "drawbox_volume_mass_is_not_owner": True,
            "fluid_sample": classify_sample(generated_summary["fluid_sample_mass_kg"], target),
            "body_contract": {"massbody_kg": generated_summary["body_mass_kg"], "center_m": generated_summary["body_center_m"], "inertia_kg_m2": generated_summary["body_inertia_kg_m2"]},
        })
    post = {key: record(path) for key, path in paths.items()}
    if pre != post:
        raise AuditError("F6 XML/JSON input changed during audit")
    report = {
        "schema": SCHEMA, "status": "COMPLETED_F6_FLUID_OWNER_AUTHORITY_XML_SOURCE_AUDIT",
        "manifest": pre["manifest"], "official_gencase": official_record,
        "rows": records,
        "owner_authority": {
            "continuous_fluid_owner": "UNKNOWN_NO_LINKED_CONTINUOUS_OWNER_CONTRACT",
            "reason": "XML fluid drawbox is a discrete producer selector; prose comments are not authority and no separately linked continuous-owner contract is bound.",
            "body_mass_is_separate": True,
            "physical_body_mass_kg": BODY_MASS_KG,
            "drawbox_volume_or_rho_volume_must_not_be_promoted": True,
        },
        "input_stability": {"pre": pre, "post": post, "all_equal": pre == post},
        "scientific_status": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN"},
        "scope": {"xml_json_only": True, "vtk_opened": False, "bi4_opened": False, "hdf5_opened": False, "solver_started": False, "gencase_started": False, "old_products_modified": False},
    }
    write_new(output_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        report = audit(Path(args.manifest), Path(args.output))
    except Exception as exc:
        print(f"F6 fluid owner authority audit failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"schema": report["schema"], "status": report["status"], "rows": len(report["rows"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
