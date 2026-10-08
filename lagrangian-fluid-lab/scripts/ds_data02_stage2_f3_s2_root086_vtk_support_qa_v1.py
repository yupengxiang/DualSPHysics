#!/usr/bin/env python3
"""Audit the guarded ROOT086 F3-S2 GenCase support products.

The worker is deliberately narrower than a solver qualification.  It closes
the corrected S2 XML/control/physical-owner lineage to the completed official
GenCase receipt and reads the generated Fluid/Bound VTK point clouds.  The VTK
files are deferred inputs: the parent runner must hash/stat them before and
after the worker, while this process checks its own pre/post pair.  No BI4,
HDF5, solver, or GenCase execution is allowed.

The continuous owner box is the source physical contract
``[-.45,-.09,0] + [.9,.18,.09]`` (0.01458 m³, 14.58 kg at 1000 kg/m³).
The generated fluid drawbox is a discrete producer selector and is reported
separately.  In particular, the historical fine-grid count of 15,208 points
outside that selector is not an owner-box or physical-fate finding.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import sys
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np


SCHEMA = "ds02.stage2.f3.s2.root086.vtk-support-qa.v1"
OWNER_LOW_M = [-0.45, -0.09, 0.0]
OWNER_SIZE_M = [0.9, 0.18, 0.09]
OWNER_VOLUME_M3 = 0.01458
OWNER_DENSITY_KG_M3 = 1000.0
OWNER_MASS_KG = 14.58
EXPECTED_DP_M = 0.006
EXPECTED_FLUID_COUNT = 67500
EXPECTED_BOUND_COUNT = 111708
EXPECTED_TOTAL_COUNT = 179208
EXPECTED_MASSFLUID_KG = 0.000216
EXPECTED_CONTROL_SHA256 = "9a776c1c02aeeb779902964953cd51b2af1f8ab41905398bb5125a44b93e6989"
EXPECTED_SOURCE_XML_SHA256 = "1162322010c42b9a084d76db0e20de571111cb009eb3afb699f2ee4c17d37406"
EXPECTED_SOURCE_REPORT_SHA256 = "82c9234cdda3c687a04513755c7bd1d73faf7627fa3027026ff158385ac6dd41"
EXPECTED_PRIOR_SUPPORT_SHA256 = "3a882f545b4393f1d56863c54a6057871c31ba44e5db64a9a01cea7f343c64c0"
EXPECTED_FLUID_BEGIN = 111708


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
        raise AuditError(f"missing input file: {path}")
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
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


def canonical(node: ET.Element) -> tuple[Any, ...]:
    return (local(node), tuple(sorted(node.attrib.items())), (node.text or "").strip(),
            tuple(canonical(child) for child in list(node)))


def first(root: ET.Element, name: str, label: str) -> ET.Element:
    found = [node for node in root.iter() if local(node) == name]
    if not found:
        raise AuditError(f"{label} has no <{name}>")
    return found[0]


def number(value: str | None, label: str) -> float:
    if value is None:
        raise AuditError(f"{label} has no numeric value")
    try:
        result = float(value)
    except ValueError as exc:
        raise AuditError(f"{label} is not numeric: {value!r}") from exc
    if not math.isfinite(result):
        raise AuditError(f"{label} is not finite")
    return result


def vector(node: ET.Element, label: str) -> list[float]:
    return [number(node.get(axis), f"{label}.{axis}") for axis in "xyz"]


def parse_drawboxes(root: ET.Element) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    fluid: list[dict[str, Any]] = []
    bound: list[dict[str, Any]] = []
    for mainlist in (node for node in root.iter() if local(node) == "mainlist"):
        active_fluid: int | None = None
        active_bound: int | None = None
        for node in list(mainlist):
            kind = local(node)
            if kind == "setmkfluid":
                active_fluid, active_bound = int(node.get("mk", "0")), None
                continue
            elif kind == "setmkbound":
                active_fluid, active_bound = None, int(node.get("mk", "0"))
                continue
            elif kind != "drawbox":
                continue
            point = next((child for child in node if local(child) == "point"), None)
            size = next((child for child in node if local(child) == "size"), None)
            if point is None or size is None:
                raise AuditError("drawbox is missing point/size")
            low = vector(point, "drawbox.point")
            size_m = vector(size, "drawbox.size")
            if any(value <= 0 for value in size_m):
                raise AuditError("drawbox has non-positive size")
            item = {"low_m": low, "size_m": size_m,
                    "high_m": [low[i] + size_m[i] for i in range(3)],
                    "volume_m3": math.prod(size_m),
                    "mkfluid": active_fluid, "mkbound": active_bound,
                    "boxfill": next((child.text or "" for child in node if local(child) == "boxfill"), "").strip()}
            if active_fluid is not None:
                fluid.append(item)
            elif active_bound is not None:
                bound.append(item)
    return fluid, bound


def parse_xml(path: Path, label: str) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    case = first(root, "casedef", label)
    definition = first(case, "definition", label)
    particles = first(root, "particles", label)
    counts: dict[str, int] = {}
    for child in list(particles):
        if local(child) in {"fixed", "floating", "fluid", "moving"} and child.get("count") is not None:
            counts[local(child)] = counts.get(local(child), 0) + int(child.get("count"))
    massfluid = first(root, "massfluid", label)
    acc = [node for node in root.iter() if local(node) == "acctimesfile"]
    control_name = acc[0].get("value") if acc else None
    if control_name is None:
        raise AuditError(f"{label} has no acctimesfile")
    fluid_boxes, bound_boxes = parse_drawboxes(root)
    return {
        "casedef": canonical(case),
        "dp_m": number(definition.get("dp"), f"{label}.dp"),
        "counts": counts,
        "total_particles": sum(counts.values()),
        "massfluid_kg": number(massfluid.get("value"), f"{label}.massfluid"),
        "sample_fluid_mass_kg": counts.get("fluid", 0) * number(massfluid.get("value"), f"{label}.massfluid"),
        "control_name": control_name,
        "fluid_boxes": fluid_boxes,
        "bound_boxes": bound_boxes,
    }


def parse_source_xml(path: Path, label: str) -> dict[str, Any]:
    """Read only the source definition's casedef/control projection."""
    root = ET.parse(path).getroot()
    case = first(root, "casedef", label)
    acc = [node for node in root.iter() if local(node) == "acctimesfile"]
    return {"casedef": canonical(case), "control_name": acc[0].get("value") if acc else None}


def parse_control(path: Path, label: str) -> dict[str, Any]:
    times: list[float] = []
    row_count = 0
    header: list[str] | None = None
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream, delimiter=";")
        for row in reader:
            if not row or all(not cell.strip() for cell in row):
                continue
            if header is None:
                header = [cell.strip().lstrip("#") for cell in row]
                continue
            if len(row) != len(header):
                raise AuditError(f"{label} control row width mismatch")
            values = [number(cell.strip(), f"{label} control") for cell in row]
            times.append(values[0]); row_count += 1
    if header is None or not row_count or header[0].lower() != "time":
        raise AuditError(f"{label} control has no Time header/rows")
    if any(later < earlier for earlier, later in zip(times, times[1:])):
        raise AuditError(f"{label} control time is not monotonic")
    return {"header": header, "row_count": row_count, "time_first_s": times[0],
            "time_last_s": times[-1], "time_monotonic_non_decreasing": True}


def read_vtk_points(path: Path) -> tuple[np.ndarray, dict[str, Any]]:
    data = path.read_bytes()
    match = re.search(rb"(?m)^POINTS\s+(\d+)\s+float\r?\n", data)
    if match is None:
        raise AuditError(f"{path} has no binary float POINTS section")
    count = int(match.group(1)); offset = match.end(); size = count * 3 * 4
    if offset + size > len(data):
        raise AuditError(f"{path} POINTS payload is truncated")
    points = np.frombuffer(data, dtype=">f4", count=count * 3, offset=offset).reshape((-1, 3)).copy()
    if not np.isfinite(points).all():
        raise AuditError(f"{path} contains non-finite points")
    return points, {"point_count": count, "points_offset": offset, "points_bytes": size}


def read_fluid_vtk(path: Path, expected_count: int, begin: int, count: int) -> tuple[np.ndarray, dict[str, Any]]:
    points, meta = read_vtk_points(path)
    if points.shape[0] != expected_count:
        raise AuditError(f"Fluid VTK count {points.shape[0]} != XML count {expected_count}")
    data = path.read_bytes()
    pdata_re = re.compile(rb"(?m)^POINT_DATA\s+(\d+)\r?\n")
    pdata = pdata_re.search(data, meta["points_offset"] + meta["points_bytes"])
    if pdata is None or int(pdata.group(1)) != expected_count:
        raise AuditError("Fluid VTK has no matching POINT_DATA")
    scalar_re = re.compile(rb"(?m)^SCALARS\s+Idp\s+unsigned_int(?:\s+1)?\r?\n")
    scalar = scalar_re.search(data, pdata.end())
    if scalar is None:
        raise AuditError("Fluid VTK has no unsigned-int Idp scalar")
    lookup = re.match(rb"LOOKUP_TABLE\s+default\r?\n", data[scalar.end():])
    if lookup is None:
        raise AuditError("Fluid Idp scalar has no default lookup table")
    offset = scalar.end() + lookup.end(); size = expected_count * 4
    if offset + size > len(data):
        raise AuditError("Fluid Idp payload is truncated")
    ids = np.frombuffer(data, dtype=">u4", count=expected_count, offset=offset).copy()
    global_ids = np.arange(begin, begin + count, dtype=np.uint32)
    local_ids = np.arange(count, dtype=np.uint32)
    if np.array_equal(np.sort(ids), np.sort(global_ids)):
        mapping = "GLOBAL_XML_PARTICLE_IDS"
    elif np.array_equal(np.sort(ids), local_ids):
        mapping = "LOCAL_FLUID_ORDER_TO_XML_IDS"
    else:
        raise AuditError("Fluid VTK Idp values do not match XML fluid range")
    return points, {**meta, "idp_mapping": mapping, "idp_count": int(ids.size), "idp_scalar": "unsigned_int"}


def axis_summary(points: np.ndarray) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for axis, index in zip("xyz", range(3)):
        values = np.unique(points[:, index]); diffs = np.diff(values)
        result[axis] = {"unique_count": int(values.size), "min_m": float(values[0]), "max_m": float(values[-1]),
                        "spacing_min_m": float(diffs.min()) if diffs.size else 0.0,
                        "spacing_max_m": float(diffs.max()) if diffs.size else 0.0}
    return result


def owner_relation(points: np.ndarray, dp_m: float) -> dict[str, Any]:
    low = np.asarray(OWNER_LOW_M, dtype=np.float64)
    high = low + np.asarray(OWNER_SIZE_M, dtype=np.float64)
    tolerance = max(1e-8, dp_m * 1e-5)
    inside = np.all((points >= low - tolerance) & (points <= high + tolerance), axis=1)
    return {"owner_low_m": OWNER_LOW_M, "owner_high_m": high.tolist(), "tolerance_m": tolerance,
            "inside_owner_closed_count": int(inside.sum()), "outside_owner_closed_count": int((~inside).sum()),
            "interpretation": "discrete generated points relative to source owner box; no physical-fate claim"}


def receipt_control_paths(receipt: dict[str, Any], expected_path: Path, expected_sha: str) -> list[str]:
    candidates: list[str] = []
    for container in [receipt.get("request", {}), receipt.get("input_hashes_at_launch", {}), receipt.get("input_hashes_after_run", {})]:
        mapping = container.get("input_sha256") if isinstance(container, dict) and isinstance(container.get("input_sha256"), dict) else container
        if not isinstance(mapping, dict):
            continue
        for path, digest in mapping.items():
            if Path(path).name == expected_path.name and digest == expected_sha:
                candidates.append(str(Path(path).expanduser().resolve()))
    if not candidates:
        raise AuditError("ROOT086 execution receipt did not bind the source control digest")
    return sorted(set(candidates))


def audit(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest_path = require_file(manifest_path, "manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "ds02.stage2.f3.s2.root086.vtk-support-qa.manifest.v1":
        raise AuditError("unexpected ROOT086 manifest schema")
    source = manifest["source"]
    product = manifest["product"]
    owner = manifest["continuous_owner"]
    source_xml = require_file(source["xml"]["path"], "source XML")
    source_control = require_file(source["control"]["path"], "source control")
    prepared_report = require_file(source["prepared_report"]["path"], "prepared source report")
    prior_support = require_file(source["prior_support_report"]["path"], "prior support report")
    report_path = require_file(product["source_clone_report"]["path"], "ROOT086 source-clone report")
    execution_receipt_path = require_file(product["execution_receipt"]["path"], "ROOT086 execution receipt")
    generated_xml = require_file(product["generated_xml"]["path"], "ROOT086 generated XML")
    generated_control = require_file(product["generated_control"]["path"], "ROOT086 generated control")
    fluid_vtk = require_file(product["fluid_vtk"]["path"], "ROOT086 Fluid VTK")
    bound_vtk = require_file(product["bound_vtk"]["path"], "ROOT086 Bound VTK")
    for path, expected, label in [
        (source_xml, source["xml"]["sha256"], "source XML"),
        (source_control, source["control"]["sha256"], "source control"),
        (prepared_report, source["prepared_report"]["sha256"], "prepared report"),
        (prior_support, source["prior_support_report"]["sha256"], "prior support report"),
        (report_path, product["source_clone_report"]["sha256"], "ROOT086 report"),
        (execution_receipt_path, product["execution_receipt"]["sha256"], "ROOT086 receipt"),
        (generated_xml, product["generated_xml"]["sha256"], "generated XML"),
        (generated_control, product["generated_control"]["sha256"], "generated control"),
    ]:
        if sha256(path) != expected:
            raise AuditError(f"{label} digest changed")
    if source["xml"]["sha256"] != EXPECTED_SOURCE_XML_SHA256 or source["control"]["sha256"] != EXPECTED_CONTROL_SHA256:
        raise AuditError("manifest is not bound to the corrected S2 source XML/control")
    if source["prepared_report"]["sha256"] != EXPECTED_SOURCE_REPORT_SHA256 or source["prior_support_report"]["sha256"] != EXPECTED_PRIOR_SUPPORT_SHA256:
        raise AuditError("manifest source provenance is not the reviewed S2 source closure")
    root_report = json.loads(report_path.read_text(encoding="utf-8"))
    receipt = json.loads(execution_receipt_path.read_text(encoding="utf-8"))
    if root_report.get("status") != "completed_source_clone_gencase" or root_report.get("physical_case_id") != manifest["physical_case_id"]:
        raise AuditError("ROOT086 report status/physical case mismatch")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise AuditError("ROOT086 execution receipt is not completed")
    if Path(str(receipt.get("output_root", ""))).resolve() != Path(product["output_root"]).resolve():
        raise AuditError("ROOT086 receipt output root mismatch")
    binding = root_report.get("source_binding") or {}
    if binding.get("xml", {}).get("sha256") != source["xml"]["sha256"] or binding.get("control", {}).get("sha256") != source["control"]["sha256"]:
        raise AuditError("ROOT086 report source XML/control binding mismatch")
    owner_report = root_report.get("continuous_owner") or {}
    if owner_report.get("low_m") != OWNER_LOW_M or owner_report.get("size_m") != OWNER_SIZE_M:
        raise AuditError("ROOT086 continuous owner geometry mismatch")
    if abs(float(owner_report.get("volume_m3", -1)) - OWNER_VOLUME_M3) > 1e-12 or abs(float(owner_report.get("mass_kg", -1)) - OWNER_MASS_KG) > 1e-12:
        raise AuditError("ROOT086 continuous owner volume/mass mismatch")
    receipt_control = receipt_control_paths(receipt, source_control, source["control"]["sha256"])
    if sha256(generated_control) != sha256(source_control):
        raise AuditError("ROOT086 generated control copy differs from source control")
    control = parse_control(source_control, "S2 source control")
    source_meta = parse_source_xml(source_xml, "S2 source XML")
    generated_meta = parse_xml(generated_xml, "ROOT086 generated XML")
    if source_meta["casedef"] != generated_meta["casedef"]:
        raise AuditError("ROOT086 generated casedef differs from source XML")
    if generated_meta["dp_m"] != EXPECTED_DP_M or generated_meta["counts"] != {"fixed": EXPECTED_BOUND_COUNT, "fluid": EXPECTED_FLUID_COUNT}:
        raise AuditError("ROOT086 generated XML dp/counts mismatch")
    if generated_meta["total_particles"] != EXPECTED_TOTAL_COUNT or abs(generated_meta["massfluid_kg"] - EXPECTED_MASSFLUID_KG) > 1e-15:
        raise AuditError("ROOT086 generated XML total/massfluid mismatch")
    if generated_meta["control_name"] != source_control.name:
        raise AuditError("ROOT086 generated XML control basename mismatch")
    points, fluid_vtk_meta = read_fluid_vtk(fluid_vtk, EXPECTED_FLUID_COUNT, EXPECTED_FLUID_BEGIN, EXPECTED_FLUID_COUNT)
    bound_points, bound_vtk_meta = read_vtk_points(bound_vtk)
    if bound_vtk_meta["point_count"] != EXPECTED_BOUND_COUNT:
        raise AuditError("ROOT086 Bound VTK count mismatch")
    fluid_pre = record(fluid_vtk); bound_pre = record(bound_vtk)
    fluid_relation = owner_relation(points, EXPECTED_DP_M)
    fine = json.loads(prior_support.read_text(encoding="utf-8"))["cases"]["fine_dp0048"]
    fine_relation = fine["vtk_support"]["fluid_box_relation"]
    fine_axis = fine["vtk_support"]["fluid_axis_summary"]
    owner_high = [OWNER_LOW_M[i] + OWNER_SIZE_M[i] for i in range(3)]
    fine_owner_extrema_inside = all(
        float(fine_axis[axis]["min_m"]) >= OWNER_LOW_M[i] - 1e-8 and
        float(fine_axis[axis]["max_m"]) <= owner_high[i] + 1e-8
        for i, axis in enumerate("xyz")
    )
    if record(fluid_vtk) != fluid_pre or record(bound_vtk) != bound_pre:
        raise RuntimeError("VTK file changed during audit")
    report = {
        "schema": SCHEMA,
        "status": "COMPLETED_ROOT086_VTK_SUPPORT_SOURCE_CLOSED",
        "physical_case_id": manifest["physical_case_id"],
        "source": {"xml": record(source_xml), "control": record(source_control),
                   "prepared_report": record(prepared_report), "prior_support_report": record(prior_support),
                   "receipt_control_paths": receipt_control, "control_summary": control},
        "product": {"source_clone_report": record(report_path), "execution_receipt": record(execution_receipt_path),
                    "generated_xml": record(generated_xml), "generated_control": record(generated_control),
                    "generated_xml_summary": generated_meta, "receipt_status": receipt.get("status"),
                    "receipt_returncode": receipt.get("returncode")},
        "continuous_owner": {"low_m": OWNER_LOW_M, "size_m": OWNER_SIZE_M,
                             "high_m": owner_high, "volume_m3": OWNER_VOLUME_M3,
                             "density_kg_m3": OWNER_DENSITY_KG_M3, "mass_kg": OWNER_MASS_KG,
                             "semantics": "source physical owner contract; not the generated inner selector/drawbox"},
        "vtk_support": {"fluid": {**fluid_vtk_meta, "axis_summary": axis_summary(points), "owner_relation": fluid_relation},
                        "bound": {**bound_vtk_meta, "axis_summary": axis_summary(bound_points)},
                        "pre_post_sha_stat_equal": True},
        "fine_selector_vs_owner": {
            "prior_report_case": "fine_dp0048",
            "selector_relation": fine_relation,
            "selector_outside_closed_count": fine_relation.get("outside_closed_count"),
            "selector_box_is_not_continuous_owner": True,
            "continuous_owner_extrema_bounds": {"low_m": OWNER_LOW_M, "high_m": owner_high},
            "fine_axis_extrema_from_prior_report": fine_axis,
            "fine_owner_extrema_inside_status": "BOUNDED_INSIDE_BY_PRIOR_AXIS_EXTREMA" if fine_owner_extrema_inside else "OUTSIDE_OR_UNRESOLVED",
            "interpretation": "15208 points outside the fine inner selector do not establish continuous-owner escape, legal spill, fate, or dynamics.",
            "fine_discrete_mass_hardfail_preserved": fine.get("mass_audit", {}).get("discrete_sample_gate") == "HARDFAIL_DISCRETE_SAMPLE_OVER_TWO_PERCENT",
        },
        "scope": {"gencase_rerun": False, "solver_started": False, "bi4_opened": False, "hdf5_opened": False,
                  "fluid_vtk_read": True, "bound_vtk_read": True, "old_products_modified": False},
        "scientific_status": {"source_owner_and_vtk_support": "CLOSED_FOR_THIS_AUDIT",
                               "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
                               "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN"},
    }
    write_new(output_path, report)
    return report


def self_test() -> dict[str, Any]:
    payload = b"# vtk DataFile Version 3.0\nsmall\nBINARY\nDATASET POLYDATA\nPOINTS 1 float\n" + struct.pack(">fff", 0.1, 0.2, 0.3) + b"\nPOINT_DATA 1\nSCALARS Idp unsigned_int 1\nLOOKUP_TABLE default\n" + struct.pack(">I", 0) + b"\n"
    import tempfile
    with tempfile.TemporaryDirectory(prefix="f3-root086-vtk-") as directory:
        path = Path(directory) / "tiny.vtk"; path.write_bytes(payload)
        points, meta = read_fluid_vtk(path, 1, 0, 1)
        if meta["idp_mapping"] != "GLOBAL_XML_PARTICLE_IDS" or not np.isfinite(points).all():
            raise AssertionError("positive VTK fixture failed")
        bad = Path(directory) / "bad.vtk"; bad.write_bytes(payload.replace(b"unsigned_int", b"float"))
        try:
            read_fluid_vtk(bad, 1, 0, 1)
        except AuditError:
            pass
        else:
            raise AssertionError("wrong Idp type accepted")
    return {"status": "PASS", "bi4_opened": False, "hdf5_opened": False, "solver_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest")
    parser.add_argument("--output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            result = self_test()
        else:
            if not args.manifest or not args.output:
                parser.error("--manifest and --output are required")
            result = audit(Path(args.manifest), Path(args.output))
    except Exception as exc:
        print(f"F3 ROOT086 VTK support QA failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"schema": result["schema"] if "schema" in result else "self-test", "status": result["status"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
