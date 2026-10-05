#!/usr/bin/env python3
"""Metadata-only validator for the F4 fresh082 initial-native QA binding.

The worker validates Root's genuine per-case GenCase receipts and XML metadata,
then validates a separately produced native frame-0 audit index.  It never
opens BI4/H5/CSV/VTK particle data and never rewrites the Root195 receipts.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any

SCHEMA = "ds02.f4.internal8.initial-native-qa-assembly.v1"
REQUIRED_CHECK_GROUPS = {
    "legal_domain": ("finite_tank_face_coverage", "legal_domain", "domain_legal", "finite_domain_bounds"),
    "initial_nonoverlap": ("drop_and_pool_bounds_are_separated", "initial_overlap_free", "no_initial_overlap", "drop_pool_nonoverlap"),
    "marker_partition": ("complete_type_partition", "mk_partition", "particle_type_partition"),
    "drop_pool_sources": ("positive_drop_and_pool_source_rows", "all_source_population_checks", "drop_pool_checks"),
    "uid_complete": ("finite_unique_complete_ids", "unique_complete_ids", "uid_complete"),
    "nonfinite_free": ("finite_unique_complete_ids", "finite_positions", "finite_values", "nonfinite_free"),
    "true_3d": ("true_3d",),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def as_path(value: Any, label: str) -> Path:
    if isinstance(value, dict):
        value = value.get("path")
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} lacks a path")
    return Path(value)


def reported_sha(value: Any, label: str) -> str:
    if not isinstance(value, dict) or not isinstance(value.get("sha256"), str):
        raise ValueError(f"{label} lacks producer sha256")
    return value["sha256"]


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "pass", "passed", "covered"}
    return bool(value)


def parameter(root: ET.Element, key: str) -> str | None:
    for element in root.iter("parameter"):
        if element.attrib.get("key") == key:
            return element.attrib.get("value")
    return None


def finite_point(point: Any) -> bool:
    return (
        isinstance(point, list)
        and len(point) == 3
        and all(isinstance(value, (int, float)) and math.isfinite(float(value)) for value in point)
    )


def parse_generated_xml(xml_path: Path, endpoint: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
    """Read only generated XML metadata; particle counts remain dynamic."""
    root = ET.parse(xml_path).getroot()
    definition = root.find(".//definition")
    if definition is None:
        raise ValueError(f"{endpoint['endpoint_id']}: generated XML lacks definition")
    dp = float(definition.attrib["dp"])
    if not math.isclose(dp, 0.01, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError(f"{endpoint['endpoint_id']}: generated dp={dp} is not 0.01")
    time_max = float(parameter(root, "TimeMax"))
    time_out = float(parameter(root, "TimeOut"))
    if not math.isclose(time_max, 1.2, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError(f"{endpoint['endpoint_id']}: TimeMax changed")
    if not math.isclose(time_out, 0.001, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError(f"{endpoint['endpoint_id']}: TimeOut changed")

    particles = root.find("execution/particles")
    if particles is None:
        particles = root.find(".//particles")
    if particles is None:
        raise ValueError(f"{endpoint['endpoint_id']}: generated XML lacks particles")
    try:
        total = int(particles.attrib["np"])
        fixed = int(particles.attrib["nb"])
    except (KeyError, ValueError) as error:
        raise ValueError(f"{endpoint['endpoint_id']}: invalid XML particle totals") from error
    fluid_blocks = []
    for element in particles.findall("fluid"):
        try:
            row = {
                "mkfluid": int(element.attrib["mkfluid"]),
                "mk": int(element.attrib["mk"]),
                "begin": int(element.attrib["begin"]),
                "count": int(element.attrib["count"]),
            }
        except (KeyError, ValueError) as error:
            raise ValueError(f"{endpoint['endpoint_id']}: invalid fluid block") from error
        if row["count"] <= 0:
            raise ValueError(f"{endpoint['endpoint_id']}: nonpositive fluid block")
        fluid_blocks.append(row)
    fluid = sum(row["count"] for row in fluid_blocks)
    if total <= 0 or fixed <= 0 or fluid <= 0 or total != fixed + fluid:
        raise ValueError(f"{endpoint['endpoint_id']}: dynamic particle partition does not close")
    if {row["mkfluid"] for row in fluid_blocks} != {0, 1}:
        raise ValueError(f"{endpoint['endpoint_id']}: expected pool/drop mkfluid partition is absent")

    data2d = root.find(".//data2d")
    if data2d is None:
        raise ValueError(f"{endpoint['endpoint_id']}: generated XML lacks data2d evidence")
    true_3d_from_xml = not boolish(data2d.attrib.get("value"))
    if not true_3d_from_xml:
        raise ValueError(f"{endpoint['endpoint_id']}: generated XML is 2D")

    for name, observed in (("total_particles", total), ("fixed_particles", fixed), ("fluid_particles", fluid)):
        if name in receipt and int(receipt[name]) != observed:
            raise ValueError(f"{endpoint['endpoint_id']}: {name} disagrees with XML")
    if int(receipt.get("solver_dimension_from_gencase", 0)) != 3:
        raise ValueError(f"{endpoint['endpoint_id']}: per-case GenCase receipt is not 3D")
    return {
        "xml_sha256": sha256(xml_path),
        "total_particles": total,
        "fixed_particles": fixed,
        "fluid_particles": fluid,
        "fluid_blocks": fluid_blocks,
        "dp_m": dp,
        "time_max_s": time_max,
        "time_out_s": time_out,
        "data2d": False,
        "solver_dimension_from_gencase": 3,
    }


def check_value(value: Any) -> bool:
    if isinstance(value, dict):
        if "covered" in value:
            return boolish(value["covered"])
        if "pass" in value:
            return boolish(value["pass"])
        if value and all(isinstance(v, dict) for v in value.values()):
            return all(check_value(v) for v in value.values())
    return boolish(value)


def native_checks(row: dict[str, Any], endpoint_id: str) -> dict[str, Any]:
    checks = row.get("checks")
    if not isinstance(checks, dict):
        raise ValueError(f"{endpoint_id}: native QA row lacks checks")
    selected: dict[str, Any] = {}
    for group, aliases in REQUIRED_CHECK_GROUPS.items():
        found = next((key for key in aliases if key in checks), None)
        if found is None or not check_value(checks[found]):
            raise ValueError(f"{endpoint_id}: required native check {group} is absent or false")
        selected[group] = {"field": found, "value": checks[found]}

    source_rows = row.get("source_rows")
    if not isinstance(source_rows, list):
        raise ValueError(f"{endpoint_id}: native QA row lacks drop/pool source rows")
    by_source = {str(item.get("source")): item for item in source_rows if isinstance(item, dict)}
    if set(by_source) != {"drop", "pool"}:
        raise ValueError(f"{endpoint_id}: native QA source rows are not exactly drop/pool")
    for source in ("drop", "pool"):
        item = by_source[source]
        if int(item.get("fluid_count", 0)) <= 0:
            raise ValueError(f"{endpoint_id}: {source} source has no positive population")
        bounds = item.get("bounds_m")
        if not isinstance(bounds, list) or len(bounds) != 2 or not all(finite_point(point) for point in bounds):
            raise ValueError(f"{endpoint_id}: {source} bounds are not finite 3D bounds")
        subchecks = item.get("checks")
        if not isinstance(subchecks, dict) or not subchecks or not all(check_value(v) for v in subchecks.values()):
            raise ValueError(f"{endpoint_id}: {source} source checks are incomplete")
    return {
        "required_checks": selected,
        "source_rows": by_source,
        "pass": True,
        "audit_returncode": row.get("native_audit_returncode", row.get("audit_returncode", row.get("returncode"))),
    }


def validate(
    *,
    plan_path: Path,
    source_receipt_path: Path,
    gencase_report_path: Path,
    gencase_execution_receipt_path: Path,
    gencase_root: Path,
    native_qa_index_path: Path,
    owner_root: Path,
    metadata_root: Path,
) -> dict[str, Any]:
    plan = load_json(plan_path)
    source_receipt = load_json(source_receipt_path)
    gencase_report = load_json(gencase_report_path)
    parent_receipt = load_json(gencase_execution_receipt_path)
    native_index = load_json(native_qa_index_path)

    if plan.get("family_id") != "F4" or plan.get("stage_contract", {}).get("launch_allowed") is not False:
        raise ValueError("source plan is not the frozen F4 source-only plan")
    endpoints = plan.get("endpoints")
    if not isinstance(endpoints, list) or len(endpoints) != 8:
        raise ValueError("F4 internal8 plan must contain exactly eight endpoints")
    if source_receipt.get("source_plan_sha256") != sha256(plan_path):
        raise ValueError("source-build receipt is not bound to the plan")

    # The wrapper-level failure is evidence, not a completion receipt.  The
    # per-case receipts and aggregate report are the independent actual source.
    if parent_receipt.get("status") != "failed" or parent_receipt.get("returncode") != 0:
        raise ValueError("Root195 aggregate wrapper failure/OS0 was not preserved")
    if parent_receipt.get("error") != "GenCase actual particle count missing":
        raise ValueError("Root195 aggregate wrapper failure reason changed")
    if gencase_report.get("status") != "completed" or int(gencase_report.get("gencase_returncode_failures", -1)) != 0:
        raise ValueError("Root195 aggregate member report is not completed0")
    if int(gencase_report.get("endpoint_count", -1)) != len(endpoints):
        raise ValueError("Root195 aggregate member count mismatch")
    if gencase_report.get("source_plan_sha256") != sha256(plan_path):
        raise ValueError("Root195 aggregate report is not bound to the source plan")

    report_commands = {str(row.get("endpoint_id")): row for row in gencase_report.get("commands", []) if isinstance(row, dict)}
    expected_ids = [str(endpoint["endpoint_id"]) for endpoint in endpoints]
    if set(report_commands) != set(expected_ids):
        raise ValueError("Root195 aggregate report endpoint IDs differ from source plan")

    owner_by_id = {}
    metadata_by_id = {}
    cases = []
    for endpoint in endpoints:
        endpoint_id = str(endpoint["endpoint_id"])
        owner_path = owner_root / f"{endpoint_id}.owner.json"
        metadata_path = metadata_root / f"{endpoint_id}.metadata.json"
        owner = load_json(owner_path)
        metadata = load_json(metadata_path)
        owner_binding = owner.get("physical_binding")
        if not isinstance(owner_binding, dict):
            raise ValueError(f"{endpoint_id}: owner lacks physical binding")
        canonical = hashlib.sha256(json.dumps(owner_binding, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        if canonical != owner.get("physical_binding_sha256") or canonical != endpoint.get("physical_condition_sha256"):
            raise ValueError(f"{endpoint_id}: canonical physical binding hash drift")
        if metadata.get("physical_binding_sha256") != canonical or metadata.get("case_id") != endpoint_id:
            raise ValueError(f"{endpoint_id}: metadata binding drift")
        owner_source = owner.get("source_definition", {})
        source_definition = Path(str(owner_source.get("path", "")))
        if not source_definition.is_file() or sha256(source_definition) != owner_source.get("sha256"):
            raise ValueError(f"{endpoint_id}: source Definition binding is not closed")
        row = report_commands[endpoint_id]
        if row.get("executed") is not True or row.get("returncode") != 0:
            raise ValueError(f"{endpoint_id}: aggregate command is not genuine OS0")
        if row.get("physical_condition_sha256") != canonical or row.get("source_definition_sha256") != owner_source.get("sha256"):
            raise ValueError(f"{endpoint_id}: aggregate command source binding drift")

        case_dir = gencase_root / endpoint_id
        case_receipt_path = case_dir / "gencase-receipt.json"
        case_receipt = load_json(case_receipt_path)
        if case_receipt.get("status") != "completed" or case_receipt.get("returncode") != 0:
            raise ValueError(f"{endpoint_id}: genuine per-case GenCase receipt is not completed0")
        if case_receipt.get("individual_GenCase_OS_returncode_recorded_from_subprocess") is not True:
            raise ValueError(f"{endpoint_id}: per-case OS returncode provenance is missing")
        if case_receipt.get("case_id") != endpoint_id or case_receipt.get("physical_condition_sha256") != canonical:
            raise ValueError(f"{endpoint_id}: per-case receipt identity drift")
        xml_path = as_path(case_receipt.get("generated_xml"), f"{endpoint_id} generated XML")
        bi4_path = as_path(case_receipt.get("generated_bi4"), f"{endpoint_id} generated BI4")
        expected_xml = case_dir / f"{endpoint_id}.xml"
        expected_bi4 = case_dir / f"{endpoint_id}.bi4"
        if xml_path.resolve() != expected_xml.resolve() or bi4_path.resolve() != expected_bi4.resolve():
            raise ValueError(f"{endpoint_id}: generated output path is outside Root195 contract")
        if not xml_path.is_file() or not bi4_path.is_file():
            raise FileNotFoundError(f"{endpoint_id}: generated XML/BI4 is missing")
        report_xml = as_path(row.get("generated_xml"), f"{endpoint_id} aggregate XML")
        report_bi4 = as_path(row.get("generated_bi4"), f"{endpoint_id} aggregate BI4")
        if report_xml.resolve() != xml_path.resolve() or report_bi4.resolve() != bi4_path.resolve():
            raise ValueError(f"{endpoint_id}: aggregate and per-case output paths differ")
        xml_sha = sha256(xml_path)
        if xml_sha != reported_sha(case_receipt.get("generated_xml"), f"{endpoint_id} XML"):
            raise ValueError(f"{endpoint_id}: generated XML producer hash mismatch")
        if xml_sha != reported_sha(row.get("generated_xml"), f"{endpoint_id} aggregate XML"):
            raise ValueError(f"{endpoint_id}: aggregate XML producer hash mismatch")
        # BI4 is intentionally not opened or rehashed here.  Its producer
        # hash is carried from the genuine Root195 receipt for the native job.
        bi4_sha = reported_sha(case_receipt.get("generated_bi4"), f"{endpoint_id} BI4")
        if bi4_sha != reported_sha(row.get("generated_bi4"), f"{endpoint_id} aggregate BI4"):
            raise ValueError(f"{endpoint_id}: aggregate/per-case BI4 producer hash mismatch")
        counts = parse_generated_xml(xml_path, endpoint, case_receipt)
        cases.append({
            "endpoint_id": endpoint_id,
            "physical_condition_sha256": canonical,
            "gencase_receipt": str(case_receipt_path),
            "gencase_receipt_sha256": sha256(case_receipt_path),
            "aggregate_command": row.get("command"),
            "generated_xml": {"path": str(xml_path), "sha256": xml_sha},
            "generated_bi4": {"path": str(bi4_path), "producer_sha256": bi4_sha, "content_rehashed_by_binder": False},
            "dynamic_xml_counts": counts,
            "source_definition_sha256": owner_source.get("sha256"),
            "genuine_per_case_os_returncode": 0,
        })
        owner_by_id[endpoint_id] = owner
        metadata_by_id[endpoint_id] = metadata

    rows = native_index.get("cases", native_index.get("endpoints"))
    if not isinstance(rows, list):
        raise ValueError("Root196 native QA index lacks cases/endpoints")
    qa_by_id = {str(row.get("endpoint_id", row.get("case_id"))): row for row in rows if isinstance(row, dict)}
    if set(qa_by_id) != set(expected_ids):
        raise ValueError("Root196 native QA index endpoint IDs differ from source plan")
    qa_cases = []
    for endpoint_id in expected_ids:
        row = qa_by_id[endpoint_id]
        if row.get("pass") is not True:
            raise ValueError(f"{endpoint_id}: native QA did not pass")
        returncode = row.get("native_audit_returncode", row.get("audit_returncode", row.get("returncode")))
        if returncode != 0:
            raise ValueError(f"{endpoint_id}: native QA OS returncode is not 0")
        checked = native_checks(row, endpoint_id)
        report_path = Path(str(row.get("path", row.get("audit_path", row.get("native_preflight_audit", "")))))
        report_hash = None
        if report_path and str(report_path) not in {"", "."} and report_path.is_file():
            report_hash = sha256(report_path)
        qa_cases.append({
            "endpoint_id": endpoint_id,
            "native_qa_path": str(report_path) if str(report_path) not in {"", "."} else None,
            "native_qa_sha256": report_hash,
            "native_audit_returncode": returncode,
            "checks": checked,
        })

    return {
        "schema": SCHEMA,
        "family_id": "F4",
        "scope_id": plan["scope_id"],
        "qa_attempt_id": "root-stage1-f4-internal8-native-initial-qa-196",
        "status": "pass",
        "gencase_parent_execution_receipt": {
            "path": str(gencase_execution_receipt_path),
            "sha256": sha256(gencase_execution_receipt_path),
            "status": parent_receipt.get("status"),
            "returncode": parent_receipt.get("returncode"),
            "error": parent_receipt.get("error"),
            "preserved_without_promotion": True,
        },
        "gencase_aggregate_report": {
            "path": str(gencase_report_path),
            "sha256": sha256(gencase_report_path),
            "status": gencase_report.get("status"),
            "gencase_returncode_failures": gencase_report.get("gencase_returncode_failures"),
            "execute_requested": gencase_report.get("execute_requested"),
        },
        "cases": cases,
        "native_qa": qa_cases,
        "required_native_checks": sorted(REQUIRED_CHECK_GROUPS),
        "dynamic_counts_from_generated_xml": True,
        "hardcoded_mother_particle_counts": False,
        "arrays_read_by_binder": False,
        "bi4_read_by_binder": False,
        "h5_read": False,
        "csv_read": False,
        "q_n_status": "not_assessed",
        "precision_status": "not_accepted",
        "visual_status": "pending",
        "production_approval": "none",
        "claim_boundary": "Initial native input QA only; Root195 aggregate failed receipt remains failed and no Q-N, precision, visual, or production status is granted.",
    }
