#!/usr/bin/env python3
"""Root-owned native initial-QA producer for the six fallback endpoints.

The source package only supplies this disabled worker and its contract.  When
Root enables it after genuine per-case GenCase receipts exist, the worker
reads small XML/JSON metadata, creates read-only aliases, and invokes the
pinned official F4 native frame-0 audit.  It never hashes or copies BI4/H5,
and it never runs GenCase or a solver.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
from typing import Any

SCHEMA = "ds02.f4.lattice-aligned-fallback6.native-initial-qa.v1"


def sha(path: Path) -> str:
    if path.suffix.lower() in {".bi4", ".h5", ".vtk", ".csv"}:
        raise ValueError(f"source worker refuses scientific-array hash: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def require(path: Path, *, array: bool = False) -> Path:
    if not path.is_file():
        raise FileNotFoundError(path)
    if not array:
        sha(path)
    return path


def alias(source: Path, destination: Path) -> None:
    if not source.is_file() or source.suffix.lower() not in {".xml", ".bi4"}:
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    os.symlink(source, destination)


def xml_partition(path: Path, regions: dict[str, Any]) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    particles = root.find("execution/particles")
    if particles is None:
        raise ValueError(f"generated XML lacks execution/particles: {path}")
    fixed = particles.find("fixed")
    fluids = particles.findall("fluid")
    if fixed is None or not fluids:
        raise ValueError(f"generated XML lacks fixed/fluid blocks: {path}")
    total = int(particles.attrib["np"])
    fixed_count = int(particles.attrib["nb"])
    blocks = [{"mkfluid": int(f.attrib["mkfluid"]), "mk": int(f.attrib["mk"]), "begin": int(f.attrib["begin"]), "count": int(f.attrib["count"])} for f in fluids]
    fluid_count = sum(item["count"] for item in blocks)
    if total <= 0 or fixed_count <= 0 or fluid_count <= 0 or total != fixed_count + fluid_count:
        raise ValueError(f"XML particle partition does not close: {path}")
    by_mkfluid = {item["mkfluid"]: item for item in blocks}
    source_rows = []
    for source, region in sorted(regions.items()):
        mkfluid = int(region["mkfluid"])
        if mkfluid not in by_mkfluid:
            raise ValueError(f"XML lacks mkfluid={mkfluid} for source={source}")
        block = by_mkfluid[mkfluid]
        source_rows.append({"source": source, "mkfluid": mkfluid, "derived_native_mk": block["mk"], "uid_begin": block["begin"], "uid_count": block["count"], "uid_end_exclusive": block["begin"] + block["count"], "count_source": "generated XML execution/particles fluid block"})
    if sum(item["uid_count"] for item in source_rows) != fluid_count:
        raise ValueError("XML source partition does not close")
    return {"xml_path": str(path), "xml_sha256": sha(path), "total_particles": total, "fixed_particles": fixed_count, "fluid_particles": fluid_count, "fluid_blocks": blocks, "source_rows": source_rows, "marker_semantics": {"raw_native_mk_observed": False, "raw_native_type_observed": False, "derived_partition": "generated XML mkfluid/mk/begin/count plus native Idp UID ranges"}}


def rows_from_binding(binding: dict[str, Any], endpoints: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    parent = binding.get("aggregate_execution_receipt")
    if not isinstance(parent, dict):
        raise ValueError("missing aggregate_execution_receipt provenance")
    if parent.get("status") == "failed" and parent.get("preserved_without_promotion") is not True:
        raise ValueError("failed aggregate must be explicitly preserved without promotion")
    rows = binding.get("per_case_actual_gencase_receipts")
    if not isinstance(rows, list) or len(rows) != len(endpoints):
        raise ValueError("per-case GenCase binding count does not match fallback plan")
    wanted = {str(ep["endpoint_id"]) for ep in endpoints}
    result: dict[str, dict[str, Any]] = {}
    for item in rows:
        eid = str(item["endpoint_id"])
        if eid not in wanted or eid in result:
            raise ValueError(f"unexpected or duplicate endpoint: {eid}")
        receipt_ref = item["gencase_receipt"]
        xml_ref = item["generated_xml"]
        bi4_ref = item["generated_bi4"]
        receipt_path = Path(str(receipt_ref["path"]))
        xml_path = Path(str(xml_ref["path"]))
        bi4_path = Path(str(bi4_ref["path"]))
        receipt = load(require(receipt_path))
        if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
            raise ValueError(f"{eid}: per-case GenCase receipt is not completed0")
        if item.get("solver_dimension_from_gencase") != 3:
            raise ValueError(f"{eid}: GenCase is not 3-D")
        require(xml_path)
        require(bi4_path, array=True)
        observed_xml = sha(xml_path)
        if observed_xml != xml_ref.get("producer_sha256") or observed_xml != xml_ref.get("observed_xml_sha256", observed_xml):
            raise ValueError(f"{eid}: generated XML producer hash drift")
        if bi4_ref.get("content_rehashed_by_source") is not False:
            raise ValueError(f"{eid}: source must not rehash BI4")
        result[eid] = {"row": item, "receipt": receipt, "receipt_path": receipt_path, "xml_path": xml_path, "bi4_path": bi4_path}
    if set(result) != wanted:
        raise ValueError("fallback binding endpoint set differs from plan")
    return result


def metadata(*, endpoint: dict[str, Any], owner: dict[str, Any], source_definition: Path, receipt_path: Path, xml: dict[str, Any], output: Path) -> None:
    physical = owner["physical_binding"]
    regions = physical["initial_state"]["source_regions"]
    continuous = {source: float(region["size_m"][0] * region["size_m"][1] * region["size_m"][2] * physical["density_kg_m3"]) for source, region in regions.items()}
    value = {
        "schema": "ds02.f4.lattice-aligned-fallback6.xml-uid-native-qa-metadata.v1",
        "case_id": endpoint["endpoint_id"],
        "physical_case_id": physical["physical_case_id"],
        "physical_condition_sha256": owner["physical_condition_sha256"],
        "physical_binding": physical,
        "physical_binding_sha256": owner["physical_binding_sha256"],
        "dp_m": float(owner["source_recipe"]["dp_m"]),
        "source_regions": regions,
        "expected_counts_by_source": {str(item["source"]): int(item["uid_count"]) for item in xml["source_rows"]},
        "continuous_mass_by_source_kg": continuous,
        "native_mass_by_source_kg": None,
        "definition_sha256": sha(source_definition),
        "original_definition": str(source_definition),
        "original_source_sha256": {str(source_definition): sha(source_definition), str(xml["xml_path"]): xml["xml_sha256"], str(receipt_path): sha(receipt_path)},
        "generated_xml_partition": xml,
        "raw_native_marker_arrays": {"Mk": "not required/not observed", "Type": "not required/not observed"},
        "arrays_read_by_source": False,
        "source_only": True,
        "claim_boundary": "XML/UID-derived initial native input QA only; native mass remains pending independent audit output; no solver, visual, precision, Q-N, or production approval.",
    }
    dump(output, value)
    alias(source_definition, output.parent / f"{endpoint['endpoint_id']}_Def.xml")


def metadata_preflight(plan_path: Path, owner_root: Path, output_root: Path) -> int:
    """Validate all six source metadata bindings without future GenCase data."""
    plan = load(require(plan_path))
    endpoints = plan.get("endpoints")
    if not isinstance(endpoints, list) or len(endpoints) != 6:
        raise ValueError("fallback plan must contain six endpoints")
    cases = []
    for endpoint in endpoints:
        eid = str(endpoint["endpoint_id"])
        owner = load(require(owner_root / f"{eid}.owner.json"))
        source = Path(owner["source_definition"]["path"])
        require(source)
        if owner["physical_condition_sha256"] != endpoint["physical_condition_sha256"]:
            raise ValueError(f"{eid}: physical condition drift")
        if owner["physical_binding"]["geometry"].get("tank") is None:
            raise ValueError(f"{eid}: physical binding lacks tank geometry")
        if owner["physical_binding"]["initial_state"]["initial_mass_by_source_kg"] is not None:
            raise ValueError(f"{eid}: source metadata contains fabricated native mass")
        if owner["source_recipe"].get("source_particle_counts") is not None:
            raise ValueError(f"{eid}: source metadata contains fabricated native counts")
        cases.append({
            "endpoint_id": eid,
            "physical_case_id": owner["physical_binding"]["physical_case_id"],
            "physical_condition_sha256": owner["physical_condition_sha256"],
            "definition": str(source),
            "definition_sha256": sha(source),
            "geometry_tank_present": True,
            "native_counts": None,
            "native_mass": None,
            "arrays_read": False,
        })
    output_root.mkdir(parents=True, exist_ok=True)
    dump(output_root / "metadata-preflight.json", {
        "schema": "ds02.f4.lattice-aligned-fallback6.metadata-preflight.v1",
        "status": "completed",
        "scope_id": plan["scope_id"],
        "case_count": len(cases),
        "cases": cases,
        "scientific_arrays_opened": False,
        "future_gencase_hashes": None,
        "claim_boundary": "Source owner/metadata/Definition contract only; no GenCase, BI4, native QA, solver, visual, precision, Q-N, or production claim.",
    })
    return 0


def run(args: argparse.Namespace) -> int:
    plan = load(require(args.plan))
    binding = load(require(args.gencase_binding))
    endpoints = plan.get("endpoints")
    if not isinstance(endpoints, list) or len(endpoints) != 6:
        raise ValueError("fallback plan must contain six endpoints")
    rows = rows_from_binding(binding, endpoints)
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    owner_root = Path(args.owner_root)
    reports = []
    all_pass = True
    for endpoint in endpoints:
        eid = str(endpoint["endpoint_id"])
        row = rows[eid]
        owner = load(require(owner_root / f"{eid}.owner.json"))
        if owner["physical_condition_sha256"] != endpoint["physical_condition_sha256"]:
            raise ValueError(f"{eid}: physical condition drift")
        xml = xml_partition(row["xml_path"], owner["physical_binding"]["initial_state"]["source_regions"])
        actual_counts = row["receipt"].get("counts") or row["receipt"].get("particle_counts")
        if isinstance(actual_counts, dict):
            if int(actual_counts.get("total", xml["total_particles"])) != xml["total_particles"] or int(actual_counts.get("fluid", xml["fluid_particles"])) != xml["fluid_particles"]:
                raise ValueError(f"{eid}: XML and receipt counts differ")
        metadata_path = output_root / "metadata" / f"{eid}.metadata.json"
        source_definition = Path(owner["source_definition"]["path"])
        metadata(endpoint=endpoint, owner=owner, source_definition=source_definition, receipt_path=row["receipt_path"], xml=xml, output=metadata_path)
        adapter_case = output_root / "xml-uid-audit-adapters" / eid
        prefix = adapter_case / eid
        alias(row["xml_path"], prefix.with_suffix(".xml"))
        alias(row["bi4_path"], prefix.with_suffix(".bi4"))
        alias(row["receipt_path"], prefix.parent / "execution-receipt.json")
        raw = output_root / "native-audit" / "cases" / eid / "native-preflight-audit.raw.json"
        raw.parent.mkdir(parents=True, exist_ok=True)
        command = [str(args.python), str(args.audit_script), "audit", "--metadata", str(metadata_path), "--prefix", str(prefix), "--output", str(raw)]
        completed = subprocess.run(command, cwd=str(args.audit_script.parents[1]), check=False, capture_output=True, text=True)
        if not raw.is_file():
            raise RuntimeError(f"official F4 audit produced no report for {eid}: {completed.stderr[-2000:]}")
        report = load(raw)
        checks = dict(report.get("checks", {}))
        checks["xml_uid_partition_matches_actual_generated_xml"] = int(report.get("total_particles", -1)) == xml["total_particles"] and int(report.get("fluid_particles", -1)) == xml["fluid_particles"]
        checks["raw_mk_type_arrays_not_required"] = True
        report.update({"schema": "ds02.f4.lattice-aligned-fallback6.native-preflight-audit.v1", "endpoint_id": eid, "physical_case_id": owner["physical_binding"]["physical_case_id"], "physical_condition_sha256": owner["physical_condition_sha256"], "generated_xml_partition": xml, "checks": checks, "pass": bool(report.get("pass")) and completed.returncode == 0 and all(checks.values()), "native_audit_returncode": int(completed.returncode), "audit_command": command, "source_gencase_receipt": str(row["receipt_path"]), "source_gencase_receipt_sha256": sha(row["receipt_path"]), "source_generated_xml": str(row["xml_path"]), "source_generated_xml_sha256": xml["xml_sha256"], "source_generated_bi4": str(row["bi4_path"]), "source_generated_bi4_producer_sha256": row["row"]["generated_bi4"]["producer_sha256"], "raw_native_arrays_observed": ["Posd", "Idp"], "raw_native_marker_arrays_observed": [], "arrays_read_by_source": False, "claim_boundary": "Initial native input QA only; XML/UID-derived marker partition and official read-only Posd/Idp audit. Native mass, solver, visual, precision, Q-N, and production remain Root-gated."})
        report_path = output_root / "native-audit" / "cases" / eid / "native-preflight-audit.json"
        dump(report_path, report)
        row_out = {"endpoint_id": eid, "case_id": eid, "path": str(report_path), "report_sha256": sha(report_path), "pass": bool(report["pass"]), "checks": checks, "total_particles": xml["total_particles"], "fluid_particles": xml["fluid_particles"], "generated_xml_sha256": xml["xml_sha256"], "generated_bi4_producer_sha256": row["row"]["generated_bi4"]["producer_sha256"], "raw_native_arrays_observed": ["Posd", "Idp"], "raw_native_marker_arrays_observed": []}
        reports.append(row_out)
        all_pass = all_pass and bool(report["pass"])
    index = {"schema": "ds02.f4.lattice-aligned-fallback6.native-initial-qa-index.v1", "family_id": "F4", "scope_id": plan["scope_id"], "qa_attempt_id": "root-stage1-f4-fallback6-native-initial-qa-087", "status": "completed" if all_pass else "failed", "pass": all_pass, "case_count": len(reports), "cases": reports, "root_gencase_parent_preserved": True, "raw_native_arrays_observed": ["Posd", "Idp"], "raw_native_marker_arrays_observed": [], "arrays_read_by_job": True, "arrays_copied": False, "q_n_status": "not_assessed", "precision_status": "not_accepted", "production_approval": "none", "claim_boundary": "Initial native input QA only; no solver, visual, precision, Q-N, or production approval."}
    index_path = output_root / "initial-native-qa-index.json"
    dump(index_path, index)
    binding_out = {"schema": "ds02.f4.lattice-aligned-fallback6.native-initial-qa-binding.v1", "family_id": "F4", "scope_id": plan["scope_id"], "qa_attempt_id": index["qa_attempt_id"], "status": index["status"], "pass": all_pass, "index": str(index_path), "index_sha256": sha(index_path), "cases": reports, "root_gencase_parent_preserved": True, "independent_case_count_increment": 0, "raw_native_arrays_observed": ["Posd", "Idp"], "raw_native_marker_arrays_observed": [], "production_approval": "none", "q_n_status": "not_assessed", "precision_status": "not_accepted"}
    binding_path = output_root / "initial-native-qa-binding.json"
    dump(binding_path, binding_out)
    dump(output_root / "producer-summary.json", {"schema": "ds02.f4.lattice-aligned-fallback6.native-initial-qa-summary.v1", "status": index["status"], "index": str(index_path), "index_sha256": sha(index_path), "binding": str(binding_path), "binding_sha256": sha(binding_path), "case_count": len(reports), "arrays_read_by_source": False, "arrays_read_by_job": True, "bi4_copied": False, "parent_receipt_preserved": True})
    return 0 if all_pass else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata-preflight", action="store_true")
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--gencase-binding", required=True, type=Path)
    parser.add_argument("--owner-root", required=True, type=Path)
    parser.add_argument("--audit-script", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--python", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.metadata_preflight:
            return metadata_preflight(args.plan, args.owner_root, Path(args.output_root))
        return run(args)
    except Exception as error:
        print(json.dumps({"schema": SCHEMA, "status": "failed", "error_type": type(error).__name__, "error": str(error), "arrays_read_by_source": False, "parent_receipt_preserved": True}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
