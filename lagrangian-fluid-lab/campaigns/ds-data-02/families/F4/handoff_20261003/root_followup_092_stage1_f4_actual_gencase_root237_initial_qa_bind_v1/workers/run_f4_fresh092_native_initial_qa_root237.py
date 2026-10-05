#!/usr/bin/env python3
"""Root-owned fresh092 native initial-QA producer.

The request is disabled source metadata. When Root enables it after the 24
individual Root445 GenCase receipts are reviewed, this worker reads the
producer XML/JSON metadata, creates read-only aliases for the registered XML,
BI4 and receipt, and invokes the pinned Root237 F4 audit interface. It never
runs GenCase or a solver, and the source-side ``sha`` helper refuses BI4/H5/
VTK/CSV scientific payload hashes.
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

SCHEMA = "ds02.f4.fresh092.root237-native-initial-qa.v1"
ARRAY_SUFFIXES = {".bi4", ".h5", ".vtk", ".csv"}
HEX = set("0123456789abcdef")


def sha(path: Path) -> str:
    if path.suffix.lower() in ARRAY_SUFFIXES:
        raise ValueError(f"source worker refuses scientific-array hash: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def valid_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value.lower()) <= HEX


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
    if not source.is_file() or source.suffix.lower() not in {".xml", ".bi4", ".json"}:
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    os.symlink(source, destination)


def plan_cases(plan: dict[str, Any]) -> list[dict[str, Any]]:
    cases = plan.get("cases")
    if not isinstance(cases, list) or len(cases) != 24:
        raise ValueError("fresh092 plan must contain exactly 24 cases")
    ids = [str(row.get("endpoint_id")) for row in cases]
    if len(set(ids)) != 24 or any(not value or value == "None" for value in ids):
        raise ValueError("fresh092 plan case identities are not unique")
    return cases


def rows_from_binding(binding: dict[str, Any], cases: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    parent = binding.get("aggregate_execution_receipt")
    if isinstance(parent, dict) and parent.get("status") == "failed" and parent.get("preserved_without_promotion") is not True:
        raise ValueError("preserved aggregate failure must not be promoted")
    rows = binding.get("per_case_actual_gencase_receipts")
    if not isinstance(rows, list) or len(rows) < len(cases):
        raise ValueError("per-case GenCase binding rows are fewer than the selected fresh092 cases")
    wanted = {str(case["endpoint_id"]) for case in cases}
    result: dict[str, dict[str, Any]] = {}
    for item in rows:
        eid = str(item.get("endpoint_id"))
        if eid not in wanted or eid in result:
            raise ValueError(f"unexpected or duplicate endpoint: {eid}")
        receipt_ref = item.get("gencase_receipt")
        xml_ref = item.get("generated_xml")
        bi4_ref = item.get("generated_bi4")
        if not all(isinstance(row, dict) for row in (receipt_ref, xml_ref, bi4_ref)):
            raise ValueError(f"{eid}: incomplete actual producer binding")
        receipt_path = Path(str(receipt_ref["path"]))
        xml_path = Path(str(xml_ref["path"]))
        bi4_path = Path(str(bi4_ref["path"]))
        receipt = load(require(receipt_path))
        if receipt.get("status") not in {"completed", "completed/0"} or receipt.get("returncode") != 0:
            raise ValueError(f"{eid}: GenCase receipt is not completed/0")
        if item.get("solver_dimension_from_gencase") != 3 or receipt.get("solver_dimension_from_gencase") != 3:
            raise ValueError(f"{eid}: GenCase is not actual 3D")
        total = int(receipt.get("total_particles", item.get("total_particles", 0)))
        fluid = int(receipt.get("fluid_particles", item.get("fluid_particles", 0)))
        if total <= 0 or fluid <= 0 or fluid >= total:
            raise ValueError(f"{eid}: invalid actual GenCase counts")
        require(xml_path)
        # Existence is enough for BI4 here. Its digest is the registered
        # producer value and is never recomputed by this worker.
        require(bi4_path, array=True)
        observed_xml = sha(xml_path)
        if observed_xml != xml_ref.get("producer_sha256"):
            raise ValueError(f"{eid}: generated XML producer digest drift")
        bi4_sha = bi4_ref.get("producer_sha256")
        if not valid_sha(bi4_sha) or bi4_ref.get("content_rehashed_by_source") is not False:
            raise ValueError(f"{eid}: BI4 producer attestation is incomplete")
        result[eid] = {
            "row": item, "receipt": receipt, "receipt_path": receipt_path,
            "xml_path": xml_path, "bi4_path": bi4_path, "total": total,
            "fluid": fluid, "xml_sha256": observed_xml, "bi4_sha256": bi4_sha,
        }
    if set(result) != wanted:
        raise ValueError("actual GenCase endpoint set differs from fresh092 plan")
    return result


def physical_binding(endpoint: dict[str, Any], owner: dict[str, Any]) -> dict[str, Any]:
    geometry = owner.get("geometry")
    if not isinstance(geometry, dict) or not isinstance(geometry.get("tank"), dict):
        raise ValueError(f"{endpoint['endpoint_id']}: owner lacks tank geometry")
    regions = {name: box for name, box in geometry.items() if isinstance(box, dict) and "mkfluid" in box}
    if set(regions) != {"drop", "pool"}:
        raise ValueError(f"{endpoint['endpoint_id']}: expected drop/pool source regions")
    state = dict(owner.get("initial_state", {}))
    state["source_regions"] = regions
    state.setdefault("initial_mass_by_source_kg", None)
    state.setdefault("initial_mass_total_kg", None)
    state.setdefault("initial_native_mass_status", "pending actual generated native weights; no rescale")
    state.setdefault("mass_policy", "native_rho_dp_cubed_no_rescaling")
    density = float(endpoint["density_kg_m3"])
    return {
        "schema": owner.get("schema", "ds-data-02.physical-binding.v1"),
        "family_id": "F4", "physical_case_id": owner["physical_case_id"],
        "physical_condition_sha256": owner["physical_condition_sha256"],
        "geometry": geometry, "geometry_family_id": owner.get("geometry_family_id"),
        "initial_state": state, "density_kg_m3": density,
        "parameters": owner.get("parameters", {}), "controls": owner.get("controls", {}),
        "solver_recipe": owner.get("solver_recipe", {}),
        "mechanism_id": owner.get("mechanism_id"), "lineage_group_id": owner.get("lineage_group_id"),
        "open_inlet": False, "periodic_boundary": False,
    }


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
    blocks = [{"mkfluid": int(row.attrib["mkfluid"]), "mk": int(row.attrib["mk"]), "begin": int(row.attrib["begin"]), "count": int(row.attrib["count"])} for row in fluids]
    fluid_count = sum(row["count"] for row in blocks)
    if total <= 0 or fixed_count <= 0 or fluid_count <= 0 or total != fixed_count + fluid_count:
        raise ValueError(f"XML particle partition does not close: {path}")
    by_mkfluid = {row["mkfluid"]: row for row in blocks}
    source_rows = []
    for source, region in sorted(regions.items()):
        mkfluid = int(region["mkfluid"])
        if mkfluid not in by_mkfluid:
            raise ValueError(f"XML lacks mkfluid={mkfluid}: {path}")
        block = by_mkfluid[mkfluid]
        source_rows.append({"source": source, "mkfluid": mkfluid, "derived_native_mk": block["mk"], "uid_begin": block["begin"], "uid_count": block["count"], "uid_end_exclusive": block["begin"] + block["count"], "count_source": "generated XML execution/particles fluid block"})
    if sum(row["uid_count"] for row in source_rows) != fluid_count:
        raise ValueError("XML source partition does not close")
    return {"xml_path": str(path), "xml_sha256": sha(path), "total_particles": total, "fixed_particles": fixed_count, "fluid_particles": fluid_count, "fluid_blocks": blocks, "source_rows": source_rows, "marker_semantics": {"raw_native_mk_observed": False, "raw_native_type_observed": False, "derived_partition": "generated XML mkfluid/mk/begin/count plus native Idp UID ranges"}}


def metadata(*, endpoint: dict[str, Any], owner: dict[str, Any], physical: dict[str, Any], source_definition: Path, receipt_path: Path, xml: dict[str, Any], output: Path) -> None:
    regions = physical["initial_state"]["source_regions"]
    continuous = {source: float(region["size_m"][0] * region["size_m"][1] * region["size_m"][2] * physical["density_kg_m3"]) for source, region in regions.items()}
    value = {
        "schema": "ds02.f4.fresh092.xml-uid-root237-native-qa-metadata.v1",
        "case_id": endpoint["endpoint_id"], "physical_case_id": physical["physical_case_id"],
        "physical_condition_sha256": owner["physical_condition_sha256"], "physical_binding": physical,
        "physical_binding_sha256": None, "dp_m": float(endpoint["dp_m"]),
        "source_regions": regions, "expected_counts_by_source": {str(row["source"]): int(row["uid_count"]) for row in xml["source_rows"]},
        "continuous_mass_by_source_kg": continuous, "native_mass_by_source_kg": None,
        "definition_sha256": sha(source_definition), "original_definition": str(source_definition),
        "original_source_sha256": {str(source_definition): sha(source_definition), str(xml["xml_path"]): xml["xml_sha256"], str(receipt_path): sha(receipt_path)},
        "generated_xml_partition": xml, "raw_native_marker_arrays": {"Mk": "not required/not observed", "Type": "not required/not observed"},
        "arrays_read_by_source": False, "source_only": True,
        "claim_boundary": "XML/UID-derived initial native input QA only; native mass remains pending independent audit output; no solver, visual, precision, Q-N, or production approval.",
    }
    dump(output, value)
    alias(source_definition, output.parent / f"{endpoint['endpoint_id']}_Def.xml")


def metadata_preflight(plan_path: Path, owner_root: Path, output_root: Path) -> int:
    plan = load(require(plan_path))
    cases = plan_cases(plan)
    rows = []
    for endpoint in cases:
        eid = str(endpoint["endpoint_id"])
        owner = load(require(owner_root / f"{eid}.owner.json"))
        source = Path(owner["source_definition"]["path"])
        require(source)
        physical = physical_binding(endpoint, owner)
        rows.append({"endpoint_id": eid, "physical_case_id": physical["physical_case_id"], "physical_condition_sha256": owner["physical_condition_sha256"], "definition": str(source), "definition_sha256": sha(source), "geometry_tank_present": True, "native_counts": None, "native_mass": None, "arrays_read": False})
    output_root.mkdir(parents=True, exist_ok=True)
    dump(output_root / "metadata-preflight.json", {"schema": "ds02.f4.fresh092.metadata-preflight.v1", "status": "completed", "scope_id": plan["scope_id"], "case_count": len(rows), "cases": rows, "scientific_arrays_opened": False, "future_gencase_hashes": None, "claim_boundary": "Source owner/metadata/Definition contract only; no GenCase, BI4, native QA, solver, visual, precision, Q-N, or production claim."})
    return 0


def run(args: argparse.Namespace) -> int:
    plan = load(require(args.plan))
    all_cases = plan_cases(plan)
    if args.case_id is None:
        cases = all_cases
    else:
        cases = [row for row in all_cases if str(row["endpoint_id"]) == args.case_id]
        if len(cases) != 1:
            raise ValueError(f"--case-id is not a fresh092 case: {args.case_id}")
    binding = load(require(args.gencase_binding))
    rows = rows_from_binding(binding, cases)
    output_root = Path(args.output_root)
    owner_root = Path(args.owner_root)
    reports = []
    all_pass = True
    for endpoint in cases:
        eid = str(endpoint["endpoint_id"])
        row = rows[eid]
        owner = load(require(owner_root / f"{eid}.owner.json"))
        if owner["physical_condition_sha256"] != endpoint["physical_condition_sha256"]:
            raise ValueError(f"{eid}: physical condition drift")
        physical = physical_binding(endpoint, owner)
        xml = xml_partition(row["xml_path"], physical["initial_state"]["source_regions"])
        if row["total"] != xml["total_particles"] or row["fluid"] != xml["fluid_particles"]:
            raise ValueError(f"{eid}: XML and receipt counts differ")
        metadata_path = output_root / "metadata" / f"{eid}.metadata.json"
        source_definition = Path(owner["source_definition"]["path"])
        metadata(endpoint=endpoint, owner=owner, physical=physical, source_definition=source_definition, receipt_path=row["receipt_path"], xml=xml, output=metadata_path)
        adapter_case = output_root / "xml-uid-audit-adapters" / eid
        prefix = adapter_case / eid
        alias(row["xml_path"], prefix.with_suffix(".xml"))
        alias(row["bi4_path"], prefix.with_suffix(".bi4"))
        alias(row["receipt_path"], prefix.parent / "execution-receipt.json")
        raw = output_root / "native-audit" / "cases" / eid / "native-preflight-audit.raw.json"
        command = [str(args.python), str(args.audit_script), "audit", "--metadata", str(metadata_path), "--prefix", str(prefix), "--output", str(raw)]
        completed = subprocess.run(command, cwd=str(args.audit_script.parents[1]), check=False, capture_output=True, text=True)
        if not raw.is_file():
            raise RuntimeError(f"Root237 audit produced no report for {eid}: {completed.stderr[-2000:]}")
        report = load(raw)
        checks = dict(report.get("checks", {}))
        checks["xml_uid_partition_matches_actual_generated_xml"] = int(report.get("total_particles", -1)) == xml["total_particles"] and int(report.get("fluid_particles", -1)) == xml["fluid_particles"]
        checks["raw_mk_type_arrays_not_required"] = True
        report.update({"schema": "ds02.f4.fresh092.root237-native-preflight-audit.v1", "endpoint_id": eid, "physical_case_id": physical["physical_case_id"], "physical_condition_sha256": owner["physical_condition_sha256"], "generated_xml_partition": xml, "checks": checks, "pass": bool(report.get("pass")) and completed.returncode == 0 and all(checks.values()), "native_audit_returncode": int(completed.returncode), "audit_command": command, "source_gencase_receipt": str(row["receipt_path"]), "source_gencase_receipt_sha256": sha(row["receipt_path"]), "source_generated_xml": str(row["xml_path"]), "source_generated_xml_sha256": xml["xml_sha256"], "source_generated_bi4": str(row["bi4_path"]), "source_generated_bi4_producer_sha256": row["bi4_sha256"], "raw_native_arrays_observed": ["Posd", "Idp"], "raw_native_marker_arrays_observed": [], "arrays_read_by_source": False, "claim_boundary": "Initial native input QA only; XML/UID-derived marker partition and official read-only Posd/Idp audit. Native mass, solver, visual, precision, Q-N, and production remain Root-gated."})
        report_path = output_root / "native-audit" / "cases" / eid / "native-preflight-audit.json"
        dump(report_path, report)
        row_out = {"endpoint_id": eid, "case_id": eid, "path": str(report_path), "report_sha256": sha(report_path), "pass": bool(report["pass"]), "checks": checks, "total_particles": xml["total_particles"], "fluid_particles": xml["fluid_particles"], "generated_xml_sha256": xml["xml_sha256"], "generated_bi4_producer_sha256": row["bi4_sha256"], "raw_native_arrays_observed": ["Posd", "Idp"], "raw_native_marker_arrays_observed": []}
        reports.append(row_out)
        all_pass = all_pass and bool(report["pass"])
    attempt_id = str(plan["qa_attempt_id"]) if args.case_id is None else f"{plan['qa_attempt_id']}-{args.case_id.lower()}"
    index_path = output_root / "initial-native-qa-index.json"
    index = {"schema": "ds02.f4.fresh092.root237-native-initial-qa-index.v1", "family_id": "F4", "scope_id": plan["scope_id"], "qa_attempt_id": attempt_id, "status": "completed" if all_pass else "failed", "pass": all_pass, "case_count": len(reports), "cases": reports, "root_gencase_parent_preserved": True, "raw_native_arrays_observed": ["Posd", "Idp"], "raw_native_marker_arrays_observed": [], "arrays_read_by_job": True, "arrays_copied": False, "q_n_status": "not_assessed", "precision_status": "not_accepted", "production_approval": "none", "claim_boundary": "Initial native input QA only; no solver, visual, precision, Q-N, or production approval."}
    dump(index_path, index)
    binding_path = output_root / "initial-native-qa-binding.json"
    dump(binding_path, {"schema": "ds02.f4.fresh092.root237-native-initial-qa-binding.v1", "family_id": "F4", "scope_id": plan["scope_id"], "qa_attempt_id": attempt_id, "status": index["status"], "pass": all_pass, "index": str(index_path), "index_sha256": sha(index_path), "cases": reports, "root_gencase_parent_preserved": True, "independent_case_count_increment": 0, "raw_native_arrays_observed": ["Posd", "Idp"], "raw_native_marker_arrays_observed": [], "production_approval": "none", "q_n_status": "not_assessed", "precision_status": "not_accepted"})
    dump(output_root / "producer-summary.json", {"schema": "ds02.f4.fresh092.root237-native-initial-qa-summary.v1", "status": index["status"], "index": str(index_path), "index_sha256": sha(index_path), "binding": str(binding_path), "binding_sha256": sha(binding_path), "case_count": len(reports), "arrays_read_by_source": False, "arrays_read_by_job": True, "bi4_copied": False, "parent_receipt_preserved": True})
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
    parser.add_argument("--case-id")
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
