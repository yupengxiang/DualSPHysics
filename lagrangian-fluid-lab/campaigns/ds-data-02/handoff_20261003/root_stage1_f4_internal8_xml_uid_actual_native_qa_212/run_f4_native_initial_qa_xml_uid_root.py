#!/usr/bin/env python3
"""Root212 F4 native initial QA using the successful XML/UID audit contract.

This is disabled source-only code.  The source side reads only small JSON/XML
metadata and never opens a BI4.  A Root-owned CPU audit may invoke the consumed
F4 centered-reference audit, which observes read-only native ``Posd`` and
``Idp`` through the pinned decoder.  The fluid/fixed/Mk partition is derived
from the generated XML execution particle blocks and Idp ranges; raw native
``Mk`` and ``Type`` arrays are not required or claimed as observed.

The worker creates symlinks in its fresh attempt directory instead of copying
or rewriting Root195 BI4/XML bytes.  It preserves Root195's failed aggregate
receipt and writes per-case reports, an index, and a binding only in the fresh
attempt output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
import xml.etree.ElementTree as ET


SCHEMA = "ds02.f4.internal8.native-initial-qa-xml-uid.v1"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")


def sha256(path: Path) -> str:
    """Hash only the small metadata/XML/report artifacts owned by this worker."""

    if path.suffix.lower() in {".bi4", ".h5", ".vtk", ".csv"}:
        raise ValueError(f"source metadata worker refuses scientific array hash: {path}")
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


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def require_file(path: Path, *, hashable: bool = True) -> Path:
    if not path.is_file():
        raise FileNotFoundError(path)
    if hashable:
        sha256(path)
    return path


def symlink_once(source: Path, destination: Path) -> None:
    if not source.is_file() or source.suffix.lower() not in {".xml", ".bi4"}:
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    os.symlink(source, destination)


def xml_partition(xml_path: Path, source_regions: dict[str, Any]) -> dict[str, Any]:
    """Read actual generated XML counts and derive source/UID partition rows."""

    root = ET.parse(xml_path).getroot()
    particles = root.find("execution/particles")
    if particles is None:
        raise ValueError(f"generated XML lacks execution/particles: {xml_path}")
    fixed = particles.find("fixed")
    fluids = particles.findall("fluid")
    if fixed is None or not fluids:
        raise ValueError(f"generated XML lacks fixed/fluid blocks: {xml_path}")
    total = int(particles.attrib["np"])
    fixed_count = int(particles.attrib["nb"])
    blocks = []
    for fluid in fluids:
        blocks.append({
            "mkfluid": int(fluid.attrib["mkfluid"]),
            "mk": int(fluid.attrib["mk"]),
            "begin": int(fluid.attrib["begin"]),
            "count": int(fluid.attrib["count"]),
        })
    fluid_count = sum(int(row["count"]) for row in blocks)
    if total != fixed_count + fluid_count or total <= 0 or fixed_count <= 0 or fluid_count <= 0:
        raise ValueError(f"generated XML particle partition does not close: {xml_path}")
    by_mkfluid = {int(row["mkfluid"]): row for row in blocks}
    source_rows = []
    for source, region in sorted(source_regions.items()):
        mkfluid = int(region["mkfluid"])
        if mkfluid not in by_mkfluid:
            raise ValueError(f"generated XML lacks mkfluid={mkfluid} for source={source}")
        block = by_mkfluid[mkfluid]
        source_rows.append({
            "source": source,
            "mkfluid": mkfluid,
            "derived_native_mk": int(block["mk"]),
            "uid_begin": int(block["begin"]),
            "uid_count": int(block["count"]),
            "uid_end_exclusive": int(block["begin"]) + int(block["count"]),
            "count_source": "generated XML execution/particles fluid block",
        })
    if sum(int(row["uid_count"]) for row in source_rows) != fluid_count:
        raise ValueError("XML source partition does not close over fluid count")
    return {
        "xml_path": str(xml_path),
        "xml_sha256": sha256(xml_path),
        "total_particles": total,
        "fixed_particles": fixed_count,
        "fluid_particles": fluid_count,
        "fluid_blocks": blocks,
        "source_rows": source_rows,
        "marker_semantics": {
            "raw_native_mk_observed": False,
            "raw_native_type_observed": False,
            "derived_partition": "generated XML mkfluid/mk/begin/count plus read-only native Idp UID ranges",
            "claim_boundary": "derived marker partition; no raw Mk/Type observation",
        },
    }


def root195_rows(binding: dict[str, Any]) -> dict[str, dict[str, Any]]:
    parent = binding["aggregate_execution_receipt"]
    if parent.get("status") != "failed" or parent.get("returncode") != 0 or parent.get("error") != "GenCase actual particle count missing":
        raise ValueError("Root195 aggregate failure evidence changed")
    if parent.get("preserved_without_promotion") is not True:
        raise ValueError("Root195 aggregate receipt is not explicitly preserved")
    rows = binding.get("per_case_actual_gencase_receipts")
    if not isinstance(rows, list) or len(rows) != 8:
        raise ValueError("Root195 binding must contain eight per-case rows")
    result = {}
    for row in rows:
        eid = str(row["endpoint_id"])
        receipt_path = Path(str(row["gencase_receipt"]["path"]))
        receipt = load_json(require_file(receipt_path))
        if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
            raise ValueError(f"{eid}: per-case GenCase receipt is not completed0")
        if receipt.get("individual_GenCase_OS_returncode_recorded_from_subprocess") is not True:
            raise ValueError(f"{eid}: missing individual GenCase subprocess OS0 proof")
        if row.get("solver_dimension_from_gencase") != 3:
            raise ValueError(f"{eid}: actual GenCase is not 3-D")
        xml_path = Path(str(row["generated_xml"]["path"]))
        bi4_path = Path(str(row["generated_bi4"]["path"]))
        require_file(xml_path)
        require_file(bi4_path, hashable=False)
        if sha256(xml_path) != row["generated_xml"]["producer_sha256"]:
            raise ValueError(f"{eid}: generated XML producer hash drift")
        if row["generated_bi4"].get("content_rehashed_by_source") is not False:
            raise ValueError(f"{eid}: source must not claim BI4 rehash")
        result[eid] = {"row": row, "receipt": receipt, "receipt_path": receipt_path, "xml_path": xml_path, "bi4_path": bi4_path}
    return result


def adapter_metadata(*, endpoint: dict[str, Any], owner: dict[str, Any], source_definition: Path, receipt_path: Path, xml: dict[str, Any], output_metadata: Path) -> None:
    physical = owner["physical_binding"]
    regions = physical["initial_state"]["source_regions"]
    expected = {row["source"]: int(row["uid_count"]) for row in xml["source_rows"]}
    continuous = {
        source: float(region["size_m"][0] * region["size_m"][1] * region["size_m"][2] * physical["density_kg_m3"])
        for source, region in regions.items()
    }
    value = {
        "schema": "ds02.f4.internal8.xml-uid-native-qa-metadata.v1",
        "case_id": endpoint["endpoint_id"],
        "physical_case_id": physical["physical_case_id"],
        "physical_condition_sha256": owner["physical_condition_sha256"],
        # The canonical recipe is owned alongside the physical binding.  Do
        # not infer dp from generated counts or from the failed aggregate.
        "dp_m": float(owner.get("source_recipe", {}).get("dp_m", 0.01)),
        "physical_binding": physical,
        "source_regions": regions,
        "expected_counts_by_source": expected,
        "continuous_mass_by_source_kg": continuous,
        "definition_sha256": sha256(source_definition),
        "original_definition": str(source_definition),
        "original_source_sha256": {
            str(source_definition): sha256(source_definition),
            str(xml["xml_path"]): xml["xml_sha256"],
            str(receipt_path): sha256(receipt_path),
        },
        "generated_xml_partition": xml,
        "raw_native_marker_arrays": {"Mk": "not required/not observed", "Type": "not required/not observed"},
        "claim_boundary": "XML/UID-derived initial native input QA only; native solver, visual, precision, Q-N, and production remain Root-gated.",
        "arrays_read_by_source": False,
        "source_only": True,
    }
    write_json(output_metadata, value)
    # The consumed audit locates this exact basename beside metadata.
    definition_link = output_metadata.parent / f"{endpoint['endpoint_id']}_Def.xml"
    symlink_once(source_definition, definition_link)


def run(args: argparse.Namespace) -> int:
    plan = load_json(require_file(args.plan))
    binding = load_json(require_file(args.root195_binding))
    endpoints = plan.get("endpoints")
    if not isinstance(endpoints, list) or len(endpoints) != 8:
        raise ValueError("source plan must contain exactly eight endpoints")
    rows = root195_rows(binding)
    if set(rows) != {str(row["endpoint_id"]) for row in endpoints}:
        raise ValueError("Root195 endpoint IDs do not match source plan")
    output_root = Path(args.output_root)
    # The strict runtime creates the unique attempt root before spawning the
    # worker.  It is empty by construction; the runtime's collision guard,
    # rather than this worker, owns attempt-root uniqueness.
    output_root.mkdir(parents=True, exist_ok=True)
    adapter_root = output_root / "xml-uid-audit-adapters"
    metadata_root = output_root / "metadata"
    reports_root = output_root / "native-audit/cases"
    case_rows = []
    all_pass = True
    for endpoint in endpoints:
        eid = str(endpoint["endpoint_id"])
        row = rows[eid]
        owner_path = Path(args.owner_root) / f"{eid}.owner.json"
        owner = load_json(require_file(owner_path))
        if owner.get("physical_condition_sha256") != endpoint.get("physical_condition_sha256"):
            raise ValueError(f"{eid}: physical condition drift")
        xml = xml_partition(row["xml_path"], owner["physical_binding"]["initial_state"]["source_regions"])
        if xml["total_particles"] != row["receipt"].get("total_particles") or xml["fluid_particles"] != row["receipt"].get("fluid_particles"):
            raise ValueError(f"{eid}: XML counts differ from actual per-case receipt")
        source_definition = Path(owner["source_definition"]["path"])
        metadata_path = metadata_root / f"{eid}.metadata.json"
        adapter_metadata(endpoint=endpoint, owner=owner, source_definition=source_definition, receipt_path=row["receipt_path"], xml=xml, output_metadata=metadata_path)
        adapter_case = adapter_root / eid
        prefix = adapter_case / eid
        symlink_once(row["xml_path"], prefix.with_suffix(".xml"))
        symlink_once(row["bi4_path"], prefix.with_suffix(".bi4"))
        write_json(adapter_case / "execution-receipt.json", {
            "schema": "ds02.f4.xml-uid-derived-audit-receipt.v1",
            "status": "completed", "returncode": 0,
            "source_gencase_receipt": str(row["receipt_path"]),
            "source_gencase_receipt_sha256": sha256(row["receipt_path"]),
            "generated_xml": str(row["xml_path"]),
            "generated_xml_sha256": xml["xml_sha256"],
            "generated_bi4": str(row["bi4_path"]),
            "generated_bi4_producer_sha256": row["generated_bi4"]["producer_sha256"],
            "derived_marker_partition": xml["source_rows"],
            "raw_mk_type_observed": False,
            "claim_boundary": "Local alias only; Root195 receipt and BI4/XML remain immutable.",
        })
        raw_report = reports_root / eid / "native-preflight-audit.raw.json"
        report_path = reports_root / eid / "native-preflight-audit.json"
        raw_report.parent.mkdir(parents=True, exist_ok=True)
        command = [str(args.python), str(args.audit_script), "audit", "--metadata", str(metadata_path), "--prefix", str(prefix), "--output", str(raw_report)]
        completed = subprocess.run(command, cwd=str(args.audit_script.parents[1]), check=False, capture_output=True, text=True)
        if not raw_report.is_file():
            raise RuntimeError(f"official F4 audit produced no report for {eid}: {completed.stderr[-2000:]}")
        report = load_json(raw_report)
        checks = dict(report.get("checks", {}))
        source_rows = report.get("source_rows", [])
        by_source = {str(item.get("source")): item for item in source_rows if isinstance(item, dict)}
        drop = by_source.get("drop", {}).get("bounds_m")
        pool = by_source.get("pool", {}).get("bounds_m")
        nonoverlap = False
        if isinstance(drop, list) and isinstance(pool, list) and len(drop) == 2 and len(pool) == 2:
            nonoverlap = any(drop[1][axis] <= pool[0][axis] or pool[1][axis] <= drop[0][axis] for axis in range(3))
        checks["drop_pool_nonoverlap_3d"] = bool(nonoverlap)
        observed_source_counts = {
            str(item.get("source")): int(item.get("fluid_count"))
            for item in source_rows
            if isinstance(item, dict) and item.get("source") is not None and item.get("fluid_count") is not None
        }
        expected_source_counts = {
            str(item["source"]): int(item["uid_count"]) for item in xml["source_rows"]
        }
        checks["xml_uid_partition_matches_actual_generated_xml"] = (
            observed_source_counts == expected_source_counts
            and int(report.get("total_particles", -1)) == xml["total_particles"]
            and int(report.get("fluid_particles", -1)) == xml["fluid_particles"]
        )
        checks["raw_mk_type_arrays_not_required"] = True
        report.update({
            "schema": "ds02.f4.internal8.native-preflight-audit.xml-uid.v1",
            "endpoint_id": eid,
            "physical_case_id": owner["physical_binding"]["physical_case_id"],
            "physical_condition_sha256": owner["physical_condition_sha256"],
            "generated_xml_partition": xml,
            "derived_marker_partition": xml["source_rows"],
            "raw_native_marker_semantics": {"Mk": "not observed", "Type": "not observed", "partition_source": "generated XML + read-only Idp UID ranges"},
            "checks": checks,
            "pass": bool(report.get("pass")) and completed.returncode == 0 and all(checks.values()),
            "native_audit_returncode": int(completed.returncode),
            "audit_command": command,
            "source_gencase_receipt": str(row["receipt_path"]),
            "source_gencase_receipt_sha256": sha256(row["receipt_path"]),
            "source_generated_xml": str(row["xml_path"]),
            "source_generated_xml_sha256": xml["xml_sha256"],
            "source_generated_bi4": str(row["bi4_path"]),
            "source_generated_bi4_producer_sha256": row["generated_bi4"]["producer_sha256"],
            "read_policy": {"native_bi4": "official F4 audit, read-only", "native_arrays_observed": ["Posd", "Idp"], "native_arrays_not_required": ["Mk", "Type"], "h5": False, "csv": False, "vtk": False, "solver": False, "conversion": False, "rendering": False},
            "arrays_read_by_source": False,
            "claim_boundary": "Initial native input QA only; Mk/Type partition is XML/UID-derived and no solver, visual, precision, Q-N, or production approval is granted.",
        })
        write_json(report_path, report)
        case_rows.append({"endpoint_id": eid, "case_id": eid, "path": str(report_path), "report_sha256": sha256(report_path), "pass": bool(report["pass"]), "checks": checks, "total_particles": xml["total_particles"], "fluid_particles": xml["fluid_particles"], "generated_xml_sha256": xml["xml_sha256"], "generated_bi4_producer_sha256": row["generated_bi4"]["producer_sha256"], "raw_native_arrays_observed": ["Posd", "Idp"], "raw_native_marker_arrays_observed": []})
        all_pass = all_pass and bool(report["pass"])
    parent_path = Path(args.gencase_execution_receipt)
    aggregate = load_json(require_file(parent_path))
    index = {
        "schema": "ds02.f4.internal8.native-initial-qa-index.xml-uid.v1",
        "family_id": "F4", "scope_id": plan["scope_id"], "qa_attempt_id": "root-stage1-f4-internal8-native-initial-qa-212",
        "status": "completed" if all_pass else "failed", "pass": all_pass, "native_audit_returncode": 0 if all_pass else 1,
        "case_count": len(case_rows), "cases": case_rows,
        "root195_parent_execution_receipt": {"path": str(parent_path), "sha256": sha256(parent_path), "status": aggregate.get("status"), "returncode": aggregate.get("returncode"), "error": aggregate.get("error"), "preserved_without_promotion": True},
        "arrays_read_by_job": True, "arrays_copied": False,
        "native_marker_semantics": "raw Posd/Idp observed; Mk/Type partition derived from generated XML and UID ranges",
        "q_n_status": "not_assessed", "precision_status": "not_accepted", "production_approval": "none",
        "claim_boundary": "Initial native input QA only; no solver, visual, precision, Q-N, or production approval.",
    }
    index_path = output_root / "initial-native-qa-index.json"
    write_json(index_path, index)
    binding = {
        "schema": "ds02.f4.internal8.native-initial-qa-binding.xml-uid.v1",
        "family_id": "F4", "scope_id": plan["scope_id"], "qa_attempt_id": index["qa_attempt_id"],
        "status": "pass" if all_pass else "failed", "pass": all_pass, "cases": case_rows,
        "index": str(index_path), "index_sha256": sha256(index_path),
        "root195_parent_preserved_failed": True,
        "raw_native_arrays_observed": ["Posd", "Idp"], "raw_native_marker_arrays_observed": [],
        "derived_marker_partition": "generated XML execution/particles + native Idp UID ranges",
        "independent_case_count_increment": 0, "precision_status": "not_accepted", "q_n_status": "not_assessed", "production_approval": "none",
    }
    binding_path = output_root / "initial-native-qa-binding.json"
    write_json(binding_path, binding)
    summary = {"schema": "ds02.f4.internal8.native-initial-qa-xml-uid-summary.v1", "status": "completed" if all_pass else "failed", "index": str(index_path), "index_sha256": sha256(index_path), "binding": str(binding_path), "binding_sha256": sha256(binding_path), "case_count": 8, "arrays_read_by_job": True, "arrays_read_by_source": False, "bi4_copied": False, "parent_receipt_preserved": True}
    write_json(output_root / "producer-summary.json", summary)
    return 0 if all_pass else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--root195-binding", required=True, type=Path)
    parser.add_argument("--gencase-execution-receipt", required=True, type=Path)
    parser.add_argument("--gencase-root", required=True, type=Path)
    parser.add_argument("--owner-root", required=True, type=Path)
    parser.add_argument("--audit-script", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--python", required=True, type=Path)
    args = parser.parse_args()
    try:
        return run(args)
    except Exception as error:
        print(json.dumps({"schema": SCHEMA, "status": "failed", "error_type": type(error).__name__, "error": str(error), "parent_receipt_preserved": True, "arrays_read_by_source": False}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
