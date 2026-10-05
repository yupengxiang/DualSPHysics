#!/usr/bin/env python3
"""Bind Root343 GenCase metadata for the F7 fresh075 native-QA worker.

This is deliberately a metadata adapter.  It reads JSON and generated XML,
hashes only JSON/XML/definition/source files, and checks the existence of BI4
and motion payloads.  It never opens or hashes BI4, CSV, H5, or motion-data
bytes.  Root runs it only after the GenCase receipts are completed/0.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


EXPECTED = {
    "total": 70179,
    "fixed": 27495,
    "moving": 1984,
    "floating": 0,
    "fluid": 40700,
    "dimension": 3,
}
RAW_SUFFIXES = {".bi4", ".csv", ".h5", ".hdf5", ".dat", ".ibi4"}


class BindingError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise BindingError(message)


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def sha_metadata(path: Path) -> str:
    require(path.suffix.lower() not in RAW_SUFFIXES,
            f"scientific payload hash forbidden in metadata adapter: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dump(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def actual_attempt(data_root: Path, case_id: str, suffix: str) -> Path:
    return (data_root / "families" / "F7" / case_id /
            f"root-stage1-f7-{case_id.lower()}-genuine-gencase-{suffix}")


def parse_xml(path: Path, endpoint: dict[str, Any]) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    constants = root.find("./execution/constants")
    particles = root.find("./execution/particles")
    definition = root.find("./casedef/geometry/definition")
    require(constants is not None and particles is not None and definition is not None,
            f"{path}: required XML sections missing")
    data2d = constants.find("data2d")
    require(data2d is not None and data2d.get("value") == "false",
            f"{path}: generated case is not 3D")
    require(definition.get("dp") == "0.02", f"{path}: dp changed")
    params = {
        node.get("key"): node.get("value")
        for node in root.findall("./execution/parameters/parameter")
    }
    require(params.get("TimeMax") == "12" and params.get("TimeOut") == "0.02",
            f"{path}: native time window changed")

    counts: dict[str, int] = {}
    blocks: list[dict[str, Any]] = []
    block_contract = {
        "fixed": (0, 10),
        "moving": (1, 12),
        "floating": (2, 11),
        "fluid": (3, 2),
    }
    for name, (particle_type, expected_mk) in block_contract.items():
        node = particles.find(name)
        if node is None:
            counts[name] = 0
            require(endpoint.get(f"expected_{name}", EXPECTED[name]) == 0,
                    f"{path}: missing nonzero {name} block")
            continue
        count = int(node.get("count", "-1"))
        begin = int(node.get("begin", "-1"))
        mk = int(node.get("mk", "-1"))
        counts[name] = count
        blocks.append({"name": name, "begin": begin, "count": count,
                       "type": particle_type, "mk": mk})
        require(mk == expected_mk, f"{path}: {name} Mk {mk} != {expected_mk}")
    expected_counts = {k: int(endpoint.get(f"expected_{k}", EXPECTED[k]))
                       for k in ("fixed", "moving", "floating", "fluid")}
    require(counts == expected_counts,
            f"{path}: XML counts {counts} do not match the source contract")
    total = int(particles.get("np", "-1"))
    require(total == EXPECTED["total"] and total == sum(counts.values()),
            f"{path}: XML total mismatch")
    return {
        "counts": counts,
        "total_particles": total,
        "solver_dimension": 3,
        "type_mk_blocks": blocks,
        "data2d": False,
        "dp_m": 0.02,
        "time_max_s": 12.0,
        "time_out_s": 0.02,
        "floating_node_present": particles.find("floating") is not None,
    }


def validate_motion(plan: dict[str, Any], receipt_path: Path,
                    report_path: Path) -> None:
    receipt = load(receipt_path)
    require(receipt.get("status") == "completed" and receipt.get("returncode") == 0,
            "motion preparation is not completed/0")
    report = load(report_path)
    require(report.get("schema") ==
            "ds02.f7.next24-target-angle-source-preparation.v1",
            "motion report schema mismatch")
    require(report.get("endpoint_count") == len(plan["endpoints"]) == 24,
            "motion report endpoint count mismatch")
    planned = {row["endpoint_id"]: row for row in plan["endpoints"]}
    observed = {row["endpoint_id"]: row for row in report.get("endpoints", [])}
    require(set(planned) == set(observed), "motion report endpoint set mismatch")
    for case_id, source in planned.items():
        require(float(observed[case_id]["amplitude_deg"]) ==
                float(source["amplitude_deg"]),
                f"motion amplitude mismatch: {case_id}")


def validate_group(group: dict[str, Any], plan: dict[str, Any],
                   group_path: Path) -> dict[str, dict[str, Any]]:
    require(group.get("schema") == "ds02.f7.next24.gencase-bindings.v1",
            "GenCase binding group schema mismatch")
    require(group.get("launch_allowed") is False and
            group.get("arrays_read_by_binder") is False,
            "GenCase binding group is not source-only")
    entries = group.get("bindings", [])
    require(len(entries) == 24, f"expected 24 GenCase bindings, got {len(entries)}")
    planned = {row["endpoint_id"]: row for row in plan["endpoints"]}
    result: dict[str, dict[str, Any]] = {}
    for entry in entries:
        entry_path = Path(entry["binding"])
        binding = load(entry_path)
        case_id = binding.get("case_id")
        require(case_id in planned, f"unexpected GenCase case: {case_id}")
        require(binding.get("launch_allowed") is False and
                binding.get("execution_allowed") is False,
                f"{case_id}: binding unexpectedly enabled")
        expected = planned[case_id]
        require(binding.get("physical_condition_sha256") ==
                expected["physical_condition_sha256"],
                f"{case_id}: source-plan condition hash drift")
        require(binding.get("canonical_physical_binding_sha256") ==
                expected["canonical_physical_binding_sha256"],
                f"{case_id}: canonical physical hash drift")
        require(binding.get("threads") == 2 and binding.get("dp_m") == 0.02,
                f"{case_id}: GenCase recipe fields missing")
        result[case_id] = {
            "binding": str(entry_path),
            "binding_sha256": sha_metadata(entry_path),
            "definition": binding.get("definition"),
            "definition_sha256": binding.get("definition_sha256"),
            "motion_report": binding.get("motion_report"),
            "motion_receipt": binding.get("motion_receipt"),
            "source_plan": binding.get("source_plan"),
            "source_plan_sha256": binding.get("source_plan_sha256"),
        }
    require(set(result) == set(planned), "GenCase binding set is incomplete")
    return result


def bind_case(case_id: str, endpoint: dict[str, Any], group_binding: dict[str, Any],
              data_root: Path, suffix: str, source_owner: Path) -> dict[str, Any]:
    attempt = actual_attempt(data_root, case_id, suffix)
    prepared = attempt / "prepared"
    receipt_path = attempt / "execution-receipt.json"
    report_path = prepared / "prepared-input-report.json"
    xml_path = prepared / f"{case_id}.xml"
    definition_path = prepared / f"{case_id}_Def.xml"
    bi4_path = prepared / f"{case_id}.bi4"
    motion_path = prepared / "motion_obstacle_quintic.dat"
    for path, label in ((receipt_path, "GenCase receipt"),
                        (report_path, "prepared-input-report"),
                        (xml_path, "generated XML"),
                        (definition_path, "generated Def XML")):
        require(path.is_file(), f"{case_id}: missing {label}: {path}")
    # Presence is sufficient for raw payloads.  Do not stat, open, or hash them.
    require(bi4_path.is_file(), f"{case_id}: missing generated BI4: {bi4_path}")
    require(motion_path.is_file(), f"{case_id}: missing copied motion asset: {motion_path}")

    receipt = load(receipt_path)
    require(receipt.get("status") == "completed" and receipt.get("returncode") == 0,
            f"{case_id}: GenCase receipt is not completed/0")
    # Root003's execution receipt records completed/0 and preserves the
    # request's expected runtime fields; the actual generated counts are
    # producer-attested by prepared-input-report plus generated XML.  Some
    # runner receipts also expose the three counts at top level, so validate
    # them when present without treating a missing convenience field as an
    # actual-particle claim.
    receipt_request = receipt.get("request", {})
    request_counts = receipt_request.get("expected_counts", {})
    require(request_counts.get("total") in (None, EXPECTED["total"]) and
            request_counts.get("fluid") in (None, EXPECTED["fluid"]) and
            request_counts.get("dimension") in (None, EXPECTED["dimension"]),
            f"{case_id}: receipt request count contract mismatch")
    top_counts = {
        "total": receipt.get("total_particles"),
        "fluid": receipt.get("fluid_particles"),
        "dimension": receipt.get("solver_dimension_from_gencase"),
    }
    for key, value in top_counts.items():
        if value is not None:
            require(value == EXPECTED[key],
                    f"{case_id}: receipt top-level {key} mismatch")
    report = load(report_path)
    require(report.get("schema") == "ds02.root.actual-native-source-preflight.v1",
            f"{case_id}: prepared report schema mismatch")
    xml_info = parse_xml(xml_path, endpoint)
    report_counts = report.get("generated_xml_particle_counts")
    require(report_counts == xml_info["counts"],
            f"{case_id}: prepared report/XML count mismatch")
    require(report.get("actual_total_particles") == xml_info["total_particles"],
            f"{case_id}: prepared report/XML total mismatch")
    require(report.get("xml_sha256") == sha_metadata(xml_path),
            f"{case_id}: producer XML digest mismatch")
    require(sha_metadata(definition_path) == group_binding["definition_sha256"],
            f"{case_id}: generated Def digest differs from bound source Def")
    owner = load(source_owner)
    require(owner.get("physical_condition_sha256") ==
            endpoint["physical_condition_sha256"],
            f"{case_id}: owner condition hash mismatch")
    require(owner.get("canonical_physical_binding_sha256") ==
            endpoint["canonical_physical_binding_sha256"],
            f"{case_id}: owner canonical hash mismatch")
    producer_bi4 = report.get("bi4_sha256")
    return {
        "case_id": case_id,
        "physical_case_id": case_id,
        "amplitude_deg": endpoint["amplitude_deg"],
        "physical_condition_sha256": endpoint["physical_condition_sha256"],
        "canonical_physical_binding_sha256": endpoint["canonical_physical_binding_sha256"],
        "owner_path": str(source_owner),
        "owner_sha256": sha_metadata(source_owner),
        "gencase_binding": group_binding["binding"],
        "gencase_binding_sha256": group_binding["binding_sha256"],
        "gencase_receipt": str(receipt_path),
        "gencase_receipt_sha256": sha_metadata(receipt_path),
        "prepared_input_report": str(report_path),
        "prepared_input_report_sha256": sha_metadata(report_path),
        "generated_xml": str(xml_path),
        "generated_xml_sha256": sha_metadata(xml_path),
        "generated_definition": str(definition_path),
        "generated_definition_sha256": sha_metadata(definition_path),
        "generated_bi4": str(bi4_path),
        "generated_bi4_sha256": None,
        "producer_attested_bi4_sha256": producer_bi4,
        "generated_motion": str(motion_path),
        "generated_motion_sha256": None,
        "actual_counts": {
            "total": xml_info["total_particles"],
            **xml_info["counts"],
            "dimension": xml_info["solver_dimension"],
        },
        "receipt_count_fields": {
            "top_level_present": any(value is not None for value in top_counts.values()),
            "request_expected_counts": request_counts,
        },
        "expected": {
            "total_particles": EXPECTED["total"],
            "fixed_particles": EXPECTED["fixed"],
            "moving_particles": EXPECTED["moving"],
            "floating_particles": EXPECTED["floating"],
            "fluid_particles": EXPECTED["fluid"],
            "solver_dimension": EXPECTED["dimension"],
            "dp_m": 0.02,
            "time_max_s": 12.0,
            "time_out_s": 0.02,
            "motion_rows": 12001,
            "type_mk_blocks": xml_info["type_mk_blocks"],
            "velocity_zero_tolerance_m_per_s": 1e-12,
            "native_fluid_mass_kg": 325.60001628,
            "continuum_envelope_mass_kg": 320.1984,
            "mass_tolerance_kg": 1e-8,
        },
    }


def write_runtime_evidence(case: dict[str, Any], output: Path) -> dict[str, Any]:
    """Create the bounded receipt shape required by the qualification runner.

    The Python GenCase wrapper's execution receipt records completed/0 but does
    not always expose the parsed particle counts at its top level.  The
    adapter derives those counts from the actual prepared report and XML and
    emits a small JSON evidence file.  It is provenance metadata, not a claim
    that the adapter ran GenCase or read BI4.
    """
    evidence = {
        "schema": "ds02.f7.fresh075.actual-gencase-runtime-evidence.v1",
        "status": "completed",
        "returncode": 0,
        "total_particles": int(case["actual_counts"]["total"]),
        "fluid_particles": int(case["actual_counts"]["fluid"]),
        "solver_dimension_from_gencase": int(case["actual_counts"]["dimension"]),
        "case_id": case["case_id"],
        "physical_case_id": case["physical_case_id"],
        "actual_counts": case["actual_counts"],
        "source_execution_receipt": case["gencase_receipt"],
        "source_execution_receipt_sha256": case["gencase_receipt_sha256"],
        "prepared_input_report": case["prepared_input_report"],
        "prepared_input_report_sha256": case["prepared_input_report_sha256"],
        "generated_xml": case["generated_xml"],
        "generated_xml_sha256": case["generated_xml_sha256"],
        "generated_definition": case["generated_definition"],
        "generated_definition_sha256": case["generated_definition_sha256"],
        "producer_attested_bi4_sha256": case["producer_attested_bi4_sha256"],
        "adapter_only": True,
        "arrays_read": False,
        "raw_payload_policy": "BI4 and motion payloads were presence-checked only; no payload bytes were opened or hashed by the adapter",
    }
    dump(output, evidence)
    return {"path": str(output), "sha256": sha_metadata(output), "schema": evidence["schema"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--owners-root", required=True, type=Path)
    parser.add_argument("--motion-receipt", required=True, type=Path)
    parser.add_argument("--motion-report", required=True, type=Path)
    parser.add_argument("--gencase-bindings", required=True, type=Path)
    parser.add_argument("--data-root", type=Path,
                        default=Path("/home/jade/Projects/DualSPHysics-data/ds-data-02"))
    parser.add_argument("--gencase-attempt-suffix", default="074")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    plan = load(args.plan)
    require(plan.get("scope_id") == "root_followup_074_stage1_next24_target_angles_v1",
            "unexpected source plan scope")
    validate_motion(plan, args.motion_receipt, args.motion_report)
    group = load(args.gencase_bindings)
    group_rows = validate_group(group, plan, args.gencase_bindings)
    cases = []
    evidence_dir = args.output.parent / "cases"
    for endpoint in plan["endpoints"]:
        case_id = endpoint["endpoint_id"]
        owner_path = args.owners_root / f"{case_id}.owner.json"
        require(owner_path.is_file(), f"{case_id}: owner missing: {owner_path}")
        case = bind_case(case_id, endpoint, group_rows[case_id],
                         args.data_root, args.gencase_attempt_suffix, owner_path)
        evidence_path = evidence_dir / f"{case_id}.gencase-runtime-evidence.json"
        case["runtime_evidence"] = write_runtime_evidence(case, evidence_path)
        cases.append(case)
    output = {
        "schema": "ds02.f7.fresh075.actual-gencase-native-qa-binding.v1",
        "scope_id": "root_followup_075_actual_gencase_native_metadata_adapter_v1",
        "source_scope_id": plan["scope_id"],
        "partvtk": "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64",
        "partvtk_sha256": "62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00",
        "source_plan": {"path": str(args.plan), "sha256": sha_metadata(args.plan)},
        "motion_provenance": {
            "receipt": str(args.motion_receipt),
            "receipt_sha256": sha_metadata(args.motion_receipt),
            "report": str(args.motion_report),
            "report_sha256": sha_metadata(args.motion_report),
        },
        "gencase_binding_group": {
            "path": str(args.gencase_bindings),
            "sha256": sha_metadata(args.gencase_bindings),
        },
        "runtime_evidence_directory": str(evidence_dir),
        "cases": cases,
        "launch_allowed": False,
        "execution_allowed": False,
        "arrays_read_by_binder": False,
        "raw_payload_policy": {
            "bi4": "presence checked only; no read/hash by adapter",
            "motion_dat": "presence checked only; no read/hash by adapter",
            "csv": "not read",
            "h5": "not read",
        },
        "claim_boundary": (
            "Root343 GenCase receipt/report/XML/Def metadata is bound. "
            "Official PartVTK initial UID/type/Mk/positive-field/zero-velocity/"
            "unique-coordinate/no-overlap/3D/mass QA remains a disabled Root CPU audit; "
            "no dynamics, visual, Q-N, precision, or production claim."
        ),
    }
    dump(args.output, output)
    print(json.dumps({"output": str(args.output), "case_count": len(cases),
                      "launch_allowed": False}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BindingError as exc:
        raise SystemExit(f"fresh075 metadata binding failed: {exc}") from exc
