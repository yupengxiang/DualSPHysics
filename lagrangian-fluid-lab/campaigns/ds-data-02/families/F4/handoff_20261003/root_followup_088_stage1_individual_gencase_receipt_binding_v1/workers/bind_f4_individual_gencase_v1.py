#!/usr/bin/env python3
"""Bind six independently executed F4 GenCase outputs for the fresh087 QA worker.

This worker is intended for a Root-owned CPU audit after the six individual
GenCase requests finish.  It reads runtime JSON receipts and generated XML,
checks the XML particle partition, and only stats the BI4 files.  BI4/H5/VTK/
CSV bytes are never opened or hashed here.  A registered producer binding must
provide the BI4 digest and the XML/receipt producer digests; null or invented
digests are rejected.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any

SCHEMA = "ds02.f4.lattice-aligned-fallback6.individual-gencase-binding.v1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ARRAY_SUFFIXES = {".bi4", ".h5", ".vtk", ".csv"}


def sha256(path: Path) -> str:
    if path.suffix.lower() in ARRAY_SUFFIXES:
        raise ValueError(f"source binder refuses scientific-array hash: {path}")
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
    temporary = path.with_name(path.name + f".{__import__('os').getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def require_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return load(path)


def require_small(path: Path) -> Path:
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix.lower() in ARRAY_SUFFIXES:
        raise ValueError(f"scientific array cannot be read by source binder: {path}")
    return path


def require_bi4(path: Path) -> Path:
    if not path.is_file():
        raise FileNotFoundError(path)
    size = path.stat().st_size
    if size <= 0:
        raise ValueError(f"generated BI4 is empty: {path}")
    return path


def digest_field(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise ValueError(f"{label} must be a registered lowercase SHA-256 digest")
    return value


def endpoint_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    endpoints = plan.get("endpoints")
    if not isinstance(endpoints, list) or len(endpoints) != 6:
        raise ValueError("fresh087 plan must contain exactly six endpoints")
    result: dict[str, dict[str, Any]] = {}
    for endpoint in endpoints:
        endpoint_id = str(endpoint["endpoint_id"])
        if endpoint_id in result:
            raise ValueError(f"duplicate endpoint in plan: {endpoint_id}")
        result[endpoint_id] = endpoint
    return result


def actual_attempt_root(data_root: Path, request: dict[str, Any]) -> Path:
    return data_root / "families" / str(request["family_id"]) / str(request["case_id"]) / str(request["attempt_id"])


def request_outputs(data_root: Path, request: dict[str, Any]) -> tuple[Path, Path, Path]:
    root = actual_attempt_root(data_root, request)
    command = request.get("command")
    if not isinstance(command, list) or len(command) < 3 or not isinstance(command[2], str):
        raise ValueError(f"{request['case_id']}: GenCase command has no output prefix")
    if "{attempt_root}" not in command[2]:
        raise ValueError(f"{request['case_id']}: output prefix is not bound to runtime attempt_root")
    prefix = Path(command[2].replace("{attempt_root}", str(root)))
    return root / "execution-receipt.json", Path(str(prefix) + ".xml"), Path(str(prefix) + ".bi4")


def xml_partition(xml_path: Path, source_regions: dict[str, Any]) -> dict[str, Any]:
    root = ET.parse(xml_path).getroot()
    particles = root.find("./execution/particles")
    if particles is None:
        raise ValueError(f"generated XML lacks execution/particles: {xml_path}")
    fixed_nodes = particles.findall("fixed")
    fluid_nodes = particles.findall("fluid")
    if len(fixed_nodes) != 1 or not fluid_nodes:
        raise ValueError(f"generated XML lacks a unique fixed block and fluid blocks: {xml_path}")
    total = int(particles.attrib["np"])
    fixed = int(particles.attrib.get("nb", fixed_nodes[0].attrib["count"]))
    fixed_from_block = int(fixed_nodes[0].attrib["count"])
    if fixed != fixed_from_block:
        raise ValueError(f"generated XML fixed count disagreement: {xml_path}")
    blocks = []
    for fluid in fluid_nodes:
        blocks.append({
            "mkfluid": int(fluid.attrib["mkfluid"]),
            "mk": int(fluid.attrib["mk"]),
            "begin": int(fluid.attrib["begin"]),
            "count": int(fluid.attrib["count"]),
        })
    fluid_count = sum(block["count"] for block in blocks)
    if total <= 0 or fixed <= 0 or fluid_count <= 0 or total != fixed + fluid_count:
        raise ValueError(f"generated XML particle partition does not close: {xml_path}")
    by_mkfluid = {block["mkfluid"]: block for block in blocks}
    source_rows = []
    for source, region in sorted(source_regions.items()):
        mkfluid = int(region["mkfluid"])
        if mkfluid not in by_mkfluid:
            raise ValueError(f"generated XML lacks mkfluid={mkfluid} for source={source}")
        block = by_mkfluid[mkfluid]
        source_rows.append({
            "source": source,
            "mkfluid": mkfluid,
            "derived_native_mk": block["mk"],
            "uid_begin": block["begin"],
            "uid_count": block["count"],
            "uid_end_exclusive": block["begin"] + block["count"],
            "count_source": "generated XML execution/particles fluid block",
        })
    if sum(row["uid_count"] for row in source_rows) != fluid_count:
        raise ValueError(f"generated XML source partition does not close: {xml_path}")
    return {
        "xml_path": str(xml_path),
        "xml_sha256": sha256(xml_path),
        "total_particles": total,
        "fixed_particles": fixed,
        "fluid_particles": fluid_count,
        "fluid_blocks": blocks,
        "source_rows": source_rows,
        "raw_native_marker_arrays_observed": [],
        "marker_semantics": {
            "raw_native_mk_observed": False,
            "raw_native_type_observed": False,
            "derived_partition": "generated XML mkfluid/mk/begin/count; BI4 remains unread",
        },
    }


def registered_cases(binding: dict[str, Any], endpoints: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if binding.get("schema") != "ds02.f4.registered-gencase-producer-binding.v1":
        raise ValueError("producer binding is not the registered fresh088 schema")
    cases = binding.get("cases")
    if not isinstance(cases, list) or len(cases) != len(endpoints):
        raise ValueError("registered producer binding must contain one row per endpoint")
    result: dict[str, dict[str, Any]] = {}
    for row in cases:
        endpoint_id = str(row.get("endpoint_id"))
        if endpoint_id not in endpoints or endpoint_id in result:
            raise ValueError(f"unexpected or duplicate registered endpoint: {endpoint_id}")
        for key in ("gencase_receipt", "generated_xml", "generated_bi4"):
            if not isinstance(row.get(key), dict):
                raise ValueError(f"{endpoint_id}: missing registered {key} object")
        receipt = row["gencase_receipt"]
        xml = row["generated_xml"]
        bi4 = row["generated_bi4"]
        digest_field(receipt.get("producer_sha256"), label=f"{endpoint_id}.gencase_receipt.producer_sha256")
        digest_field(xml.get("producer_sha256"), label=f"{endpoint_id}.generated_xml.producer_sha256")
        digest_field(bi4.get("producer_sha256"), label=f"{endpoint_id}.generated_bi4.producer_sha256")
        if row.get("solver_dimension_from_gencase") != 3:
            raise ValueError(f"{endpoint_id}: registered GenCase dimension is not 3")
        if row.get("per_case_os_returncode") != 0:
            raise ValueError(f"{endpoint_id}: registered GenCase OS returncode is not 0")
        result[endpoint_id] = row
    if set(result) != set(endpoints):
        raise ValueError("registered producer endpoint set differs from fresh087 plan")
    return result


def bind_registered_root_index(args: argparse.Namespace) -> dict[str, Any]:
    """Bind Root227's registered per-case prepared reports.

    Root227 intentionally used a distinct prepared-input path below each
    original fresh087 attempt.  The index is the authority for those paths;
    this function does not reconstruct or guess them from a future aggregate
    directory.  The prepared report is the producer-registered source for the
    XML and BI4 digests.  Only XML is re-read here; BI4 is checked by stat.
    """
    plan = require_json(args.plan)
    endpoints = endpoint_map(plan)
    index = require_json(args.registered_index)
    if index.get("independent_case_increment") != 0:
        raise ValueError("registered Root index must not grant independent-case credit")
    if index.get("prior216eight_scientific_failures_preserved") is not True:
        raise ValueError("registered Root index does not preserve Root216 negative evidence")
    index_rows = index.get("rows")
    if not isinstance(index_rows, list) or len(index_rows) != len(endpoints):
        raise ValueError("registered Root index must contain six rows")
    rows_by_id: dict[str, dict[str, Any]] = {}
    for row in index_rows:
        endpoint_id = str(row.get("case_id"))
        if endpoint_id not in endpoints or endpoint_id in rows_by_id:
            raise ValueError(f"unexpected or duplicate Root index endpoint: {endpoint_id}")
        if row.get("only_drop_point_z_changed") is not True:
            raise ValueError(f"{endpoint_id}: Root index lacks independent mother-diff assertion")
        rows_by_id[endpoint_id] = row
    if set(rows_by_id) != set(endpoints):
        raise ValueError("registered Root index endpoint set differs from fresh087 plan")
    result_rows = []
    for endpoint_id, endpoint in endpoints.items():
        row = rows_by_id[endpoint_id]
        prefix = Path(str(row["actual_output_prefix"]))
        prepared = prefix.parent
        report_path = prepared / "prepared-input-report.json"
        receipt_path = prepared.parent / "execution-receipt.json"
        xml_path = Path(str(prefix) + ".xml")
        bi4_path = Path(str(prefix) + ".bi4")
        report = require_json(report_path)
        if report.get("schema") != "ds02.root.actual-native-source-preflight.v1":
            raise ValueError(f"{endpoint_id}: unexpected registered prepared report schema")
        if report.get("case_id") != endpoint_id or Path(str(report.get("prefix"))).resolve() != prefix.resolve():
            raise ValueError(f"{endpoint_id}: registered prepared report identity/prefix mismatch")
        owner = require_json(args.owner_root / f"{endpoint_id}.owner.json")
        definition = owner["source_definition"]
        if report.get("source_definition") != definition["path"]:
            raise ValueError(f"{endpoint_id}: prepared report source Definition path drift")
        if report.get("definition_sha256") != definition["sha256"]:
            raise ValueError(f"{endpoint_id}: prepared report Definition digest drift")
        receipt = require_json(require_small(receipt_path))
        if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
            raise ValueError(f"{endpoint_id}: registered runtime receipt is not completed with OS returncode 0")
        receipt_request = receipt.get("request")
        if isinstance(receipt_request, dict) and receipt_request.get("case_id") != endpoint_id:
            raise ValueError(f"{endpoint_id}: runtime receipt request identity drift")
        xml_path = require_small(xml_path)
        bi4_path = require_bi4(bi4_path)
        xml = xml_partition(xml_path, owner["physical_binding"]["initial_state"]["source_regions"])
        registered_xml_sha = digest_field(report.get("xml_sha256"), label=f"{endpoint_id}.prepared_report.xml_sha256")
        registered_bi4_sha = digest_field(report.get("bi4_sha256"), label=f"{endpoint_id}.prepared_report.bi4_sha256")
        if xml["xml_sha256"] != registered_xml_sha:
            raise ValueError(f"{endpoint_id}: generated XML differs from registered producer digest")
        counts = report.get("generated_xml_particle_counts")
        if not isinstance(counts, dict):
            raise ValueError(f"{endpoint_id}: prepared report lacks generated XML counts")
        expected_counts = {
            "fixed_particles": int(counts["fixed"]),
            "fluid_particles": int(counts["fluid"]),
            "total_particles": int(report["actual_total_particles"]),
        }
        if any(xml[key] != value for key, value in expected_counts.items()):
            raise ValueError(f"{endpoint_id}: XML counts differ from registered prepared report")
        if report.get("actual_generated_constants", {}).get("data2d", {}).get("value") != "false":
            raise ValueError(f"{endpoint_id}: registered prepared report is not genuine 3-D")
        if receipt.get("solver_dimension_from_gencase") not in (None, 3):
            raise ValueError(f"{endpoint_id}: runtime receipt dimension is not 3")
        # The report's native QA field is intentionally still pending.  This
        # binder does not turn a GenCase result into a native QA pass.
        if report.get("native_initial_typed_QA") != "pending actual arrays":
            raise ValueError(f"{endpoint_id}: prepared report has unexpected native-QA status")
        receipt_sha = sha256(receipt_path)
        request_path = require_small(Path(str(row["request"])))
        request_sha = sha256(request_path)
        if receipt.get("request_sha256") not in (None, request_sha):
            raise ValueError(f"{endpoint_id}: runtime receipt does not bind the registered Root request")
        result_rows.append({
            "endpoint_id": endpoint_id,
            "physical_condition_sha256": endpoint["physical_condition_sha256"],
            "gencase_receipt": {
                "path": str(receipt_path),
                "producer_sha256": receipt_sha,
                "observed_sha256": receipt_sha,
                "status": "completed",
                "returncode": 0,
            },
            "generated_xml": {
                "path": str(xml_path),
                "producer_sha256": registered_xml_sha,
                "observed_xml_sha256": xml["xml_sha256"],
            },
            "generated_bi4": {
                "path": str(bi4_path),
                "producer_sha256": registered_bi4_sha,
                "size_bytes_from_stat": bi4_path.stat().st_size,
                "content_rehashed_by_source": False,
            },
            "individual_GenCase_OS_returncode_recorded_from_subprocess": True,
            "per_case_os_returncode": 0,
            "solver_dimension_from_gencase": 3,
            "total_particles": xml["total_particles"],
            "fixed_particles": xml["fixed_particles"],
            "fluid_particles": xml["fluid_particles"],
            "generated_xml_partition": xml,
            "prepared_input_report": str(report_path),
            "prepared_input_report_sha256": sha256(report_path),
            "registered_root_request": str(request_path),
            "registered_root_request_sha256": request_sha,
        })
    return {
        "schema": SCHEMA,
        "family_id": "F4",
        "scope_id": plan["scope_id"],
        "source_plan": str(args.plan),
        "source_plan_sha256": sha256(args.plan),
        "registered_root_index": str(args.registered_index),
        "registered_root_index_sha256": sha256(args.registered_index),
        "registered_root_source_commit": index.get("source_commit"),
        "aggregate_execution_receipt": {
            "status": "individual_receipts",
            "returncode": None,
            "preserved_without_promotion": True,
            "reason": "Root227 used six independent GenCase wrapper attempts; no aggregate parent receipt is promoted",
        },
        "root216_failure_evidence": plan.get("root216_failure_evidence"),
        "root216_promoted": False,
        "per_case_actual_gencase_receipts": result_rows,
        "case_count": len(result_rows),
        "independent_case_count_increment": 0,
        "arrays_read_by_source": False,
        "bi4_bytes_read_by_source": False,
        "bi4_hashes_computed_by_source": False,
        "claim_boundary": "Registered individual GenCase receipt, generated XML count/partition, and producer-registered BI4 digest/path only; native QA, mass, solver, visual, precision, Q-N, and production remain Root-gated.",
    }


def bind(args: argparse.Namespace) -> dict[str, Any]:
    plan = require_json(args.plan)
    endpoints = endpoint_map(plan)
    request_dir = args.request_dir
    owners = args.owner_root
    producer = registered_cases(require_json(args.producer_binding), endpoints)
    rows = []
    for endpoint_id, endpoint in endpoints.items():
        request_path = request_dir / f"{endpoint_id}-gencase.request.json"
        request = require_json(request_path)
        if request.get("case_id") != endpoint_id or request.get("family_id") != "F4":
            raise ValueError(f"{endpoint_id}: request identity differs from fresh087 endpoint")
        if request.get("kind") != "cpu" or request.get("cpu_task_kind") != "gencase":
            raise ValueError(f"{endpoint_id}: request is not an individual CPU GenCase request")
        request_sha = sha256(request_path)
        receipt_path, xml_path, bi4_path = request_outputs(args.data_root, request)
        registered = producer[endpoint_id]
        receipt_ref = registered["gencase_receipt"]
        xml_ref = registered["generated_xml"]
        bi4_ref = registered["generated_bi4"]
        if Path(str(receipt_ref["path"])).resolve() != receipt_path.resolve():
            raise ValueError(f"{endpoint_id}: registered receipt path is not the individual runtime output")
        if Path(str(xml_ref["path"])).resolve() != xml_path.resolve():
            raise ValueError(f"{endpoint_id}: registered XML path does not match the request output prefix")
        if Path(str(bi4_ref["path"])).resolve() != bi4_path.resolve():
            raise ValueError(f"{endpoint_id}: registered BI4 path does not match the request output prefix")
        receipt_path = require_small(receipt_path)
        xml_path = require_small(xml_path)
        bi4_path = require_bi4(bi4_path)
        receipt = require_json(receipt_path)
        if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
            raise ValueError(f"{endpoint_id}: individual runtime receipt is not completed with OS returncode 0")
        if receipt.get("request_sha256") not in (None, request_sha):
            raise ValueError(f"{endpoint_id}: runtime receipt request hash differs from source request")
        actual_receipt_sha = sha256(receipt_path)
        if actual_receipt_sha != receipt_ref["producer_sha256"]:
            raise ValueError(f"{endpoint_id}: runtime receipt producer hash drift")
        xml = xml_partition(xml_path, require_json(owners / f"{endpoint_id}.owner.json")["physical_binding"]["initial_state"]["source_regions"])
        if xml["xml_sha256"] != xml_ref["producer_sha256"]:
            raise ValueError(f"{endpoint_id}: generated XML producer hash drift")
        receipt_total = receipt.get("total_particles")
        receipt_fluid = receipt.get("fluid_particles")
        if receipt_total is not None and int(receipt_total) != xml["total_particles"]:
            raise ValueError(f"{endpoint_id}: receipt and generated XML total counts differ")
        if receipt_fluid is not None and int(receipt_fluid) != xml["fluid_particles"]:
            raise ValueError(f"{endpoint_id}: receipt and generated XML fluid counts differ")
        rows.append({
            "endpoint_id": endpoint_id,
            "physical_condition_sha256": endpoint["physical_condition_sha256"],
            "gencase_receipt": {
                "path": str(receipt_path),
                "producer_sha256": receipt_ref["producer_sha256"],
                "observed_sha256": actual_receipt_sha,
                "status": "completed",
                "returncode": 0,
            },
            "generated_xml": {
                "path": str(xml_path),
                "producer_sha256": xml_ref["producer_sha256"],
                "observed_xml_sha256": xml["xml_sha256"],
            },
            "generated_bi4": {
                "path": str(bi4_path),
                "producer_sha256": bi4_ref["producer_sha256"],
                "size_bytes_from_stat": bi4_path.stat().st_size,
                "content_rehashed_by_source": False,
            },
            "individual_GenCase_OS_returncode_recorded_from_subprocess": True,
            "per_case_os_returncode": 0,
            "solver_dimension_from_gencase": 3,
            "total_particles": xml["total_particles"],
            "fixed_particles": xml["fixed_particles"],
            "fluid_particles": xml["fluid_particles"],
            "generated_xml_partition": xml,
            "request_path": str(request_path),
            "request_sha256": request_sha,
        })
    return {
        "schema": SCHEMA,
        "family_id": "F4",
        "scope_id": plan["scope_id"],
        "source_plan": str(args.plan),
        "source_plan_sha256": sha256(args.plan),
        "aggregate_execution_receipt": {
            "status": "individual_receipts",
            "returncode": None,
            "preserved_without_promotion": True,
            "reason": "six independent GenCase runtime receipts; no aggregate GenCase subprocess was executed",
        },
        "root216_failure_evidence": plan.get("root216_failure_evidence"),
        "root216_promoted": False,
        "per_case_actual_gencase_receipts": rows,
        "case_count": len(rows),
        "independent_case_count_increment": 0,
        "arrays_read_by_source": False,
        "bi4_bytes_read_by_source": False,
        "bi4_hashes_computed_by_source": False,
        "claim_boundary": "Actual individual GenCase receipt/XML/BI4 path binding only; native QA, solver, visual, precision, Q-N, and production remain Root-gated.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--request-dir", type=Path)
    parser.add_argument("--owner-root", required=True, type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--producer-binding", type=Path)
    parser.add_argument("--registered-index", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.registered_index is not None:
            result = bind_registered_root_index(args)
        else:
            if args.request_dir is None or args.data_root is None or args.producer_binding is None:
                parser.error("direct mode requires --request-dir, --data-root, and --producer-binding")
            result = bind(args)
        dump(args.output, result)
        print(json.dumps({"schema": SCHEMA, "status": "completed", "cases": result["case_count"], "arrays_read_by_source": False}, sort_keys=True))
        return 0
    except Exception as error:
        print(json.dumps({"schema": SCHEMA, "status": "failed", "error_type": type(error).__name__, "error": str(error), "arrays_read_by_source": False}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
