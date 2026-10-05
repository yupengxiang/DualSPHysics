#!/usr/bin/env python3
"""Build the F4 fresh095 source-only pre-solver GenCase QA handoff.

The builder reads only JSON/XML/source metadata and hashes only those small
metadata files plus code/decoder artifacts.  It never opens or hashes a BI4,
H5, VTK, or CSV payload.  The registered CPU worker receives the attested
GenCase BI4 only when Root explicitly enables a disabled request.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any

PACKAGE = Path(__file__).resolve().parent
F4_ROOT = PACKAGE.parents[3]
FAMILY_ROOT = F4_ROOT / "families" / "F4"
FRESH091 = FAMILY_ROOT / "handoff_20261003" / "root_followup_091_stage1_f4_first24_coverage_audit_v1"
FRESH092 = FAMILY_ROOT / "handoff_20261003" / "root_followup_092_stage1_f4_actual_gencase_root237_initial_qa_bind_v1"
ACTUAL_BINDING_PATH = FRESH092 / "metadata" / "fresh092-actual-gencase-binding.json"
ACTUAL_PLAN_PATH = FRESH092 / "metadata" / "fresh092-actual-gencase-plan.json"
PARTVTK_CONTRACT_PATH = FRESH092 / "metadata" / "partvtk-binary-contract.json"
ROOT237_CONTRACT_PATH = FRESH092 / "metadata" / "root237-interface-contract.json"
DECODER_PATH = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/scripts/f8_r008_safe_bi4_decoder_v1.py")
PARTVTK_PATH = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
RUNTIME_PATH = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py")
STRICT_PATH = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py")
RESOURCE_PATH = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json")
PYTHON = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
WORKTREE_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-f4/DualSPHysics/lagrangian-fluid-lab")
RAW_SUFFIXES = {".bi4", ".h5", ".vtk", ".vtu", ".vtp", ".csv"}
HEX = set("0123456789abcdef")
SCHEMA = "ds02.f4.fresh095.gencase-basic-source-package.v1"


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    if path.suffix.lower() in RAW_SUFFIXES:
        raise ValueError(f"source builder refuses scientific payload hash: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def valid_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value.lower()) <= HEX


def sha_ref(path: Path, *, supplied: str | None = None) -> dict[str, Any]:
    observed = sha(path)
    if supplied is not None and observed != supplied:
        raise ValueError(f"metadata SHA drift: {path}")
    return {"path": str(path), "sha256": observed}


def parse_xml(path: Path, expected: dict[str, Any]) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    particles = root.find(".//execution/particles")
    if particles is None:
        raise ValueError(f"generated XML lacks particles: {path}")
    total = int(particles.attrib["np"])
    fixed = int(particles.attrib["nb"])
    blocks = [
        {
            "mkfluid": int(node.attrib["mkfluid"]),
            "mk": int(node.attrib["mk"]),
            "begin": int(node.attrib["begin"]),
            "count": int(node.attrib["count"]),
        }
        for node in particles.findall("fluid")
    ]
    fluid = sum(row["count"] for row in blocks)
    if (total, fixed, fluid) != (
        int(expected["total_particles"]),
        int(expected["fixed_particles"]),
        int(expected["fluid_particles"]),
    ):
        raise ValueError(f"generated XML counts differ from actual GenCase row: {path}")
    if total != fixed + fluid:
        raise ValueError(f"generated XML particle partition does not close: {path}")
    data2d = root.find(".//execution/constants/data2d")
    if data2d is None:
        data2d = root.find(".//data2d")
    if data2d is None or str(data2d.attrib.get("value", "")).lower() != "false":
        raise ValueError(f"generated XML is not explicit 3-D: {path}")
    definition = root.find(".//geometry/definition")
    if definition is None or abs(float(definition.attrib["dp"]) - float(expected["dp_m"])) > 1e-12:
        raise ValueError(f"generated XML dp differs from actual plan: {path}")
    velocities = [
        {key: node.attrib[key] for key in ("mkfluid", "x", "y", "z") if key in node.attrib}
        for node in root.findall(".//initials/velocity")
    ]
    return {
        "counts": {"total": total, "fixed": fixed, "fluid": fluid},
        "fluid_blocks": blocks,
        "data2d": False,
        "velocities": velocities,
    }


def endpoint_owner(endpoint: dict[str, Any]) -> dict[str, Any]:
    owner_path = Path(endpoint["owner_path"])
    owner = load_json(owner_path)
    if owner.get("physical_case_id") != endpoint["physical_case_id"]:
        raise ValueError(f"owner physical case drift: {endpoint['endpoint_id']}")
    if owner.get("physical_condition_sha256") != endpoint["physical_condition_sha256"]:
        raise ValueError(f"owner condition drift: {endpoint['endpoint_id']}")
    return owner


def make_binding(endpoint: dict[str, Any], row: dict[str, Any], actual_binding: dict[str, Any]) -> dict[str, Any]:
    eid = str(endpoint["endpoint_id"])
    owner = endpoint_owner(endpoint)
    source_ref = owner["source_definition"]
    source_path = Path(source_ref["path"])
    source_sha = sha(source_path)
    if source_sha != source_ref["sha256"]:
        raise ValueError(f"source Definition SHA drift: {eid}")
    receipt_ref = row["gencase_receipt"]
    receipt_path = Path(receipt_ref["path"])
    receipt = load_json(receipt_path)
    receipt_sha = sha(receipt_path)
    if receipt_sha != receipt_ref["producer_sha256"]:
        raise ValueError(f"GenCase receipt SHA drift: {eid}")
    if receipt.get("status") not in {"completed", "completed/0"} or receipt.get("returncode") != 0:
        raise ValueError(f"GenCase receipt is not completed/0: {eid}")
    if receipt.get("solver_dimension_from_gencase") != 3:
        raise ValueError(f"GenCase receipt is not 3-D: {eid}")
    xml_ref = row["generated_xml"]
    xml_path = Path(xml_ref["path"])
    xml_sha = sha(xml_path)
    if xml_sha != xml_ref.get("observed_xml_sha256") or xml_sha != xml_ref.get("producer_sha256"):
        raise ValueError(f"generated XML SHA drift: {eid}")
    expected = {
        "dimension": 3,
        "total_particles": int(row["total_particles"]),
        "fixed_particles": int(row["fixed_particles"]),
        "fluid_particles": int(row["fluid_particles"]),
        "density_kg_m3": float(endpoint["density_kg_m3"]),
        "dp_m": float(endpoint["dp_m"]),
        "parameters": dict(endpoint["parameters"]),
        "tank": dict(owner["geometry"]["tank"]),
        "sources": {
            name: {
                "mkfluid": int(region["mkfluid"]),
                "low_m": list(region["low_m"]),
                "size_m": list(region["size_m"]),
            }
            for name, region in (
                ("drop", owner["geometry"]["drop"]),
                ("pool", owner["geometry"]["pool"]),
            )
        },
    }
    xml_info = parse_xml(xml_path, expected)
    for name, source in expected["sources"].items():
        block = next(
            row_block
            for row_block in xml_info["fluid_blocks"]
            if row_block["mkfluid"] == source["mkfluid"]
        )
        source["xml_uid_block"] = block
    prepared_ref = row["prepared_input_report"]
    prepared_path = Path(prepared_ref["path"])
    prepared_sha = sha(prepared_path)
    if prepared_sha != prepared_ref["sha256"]:
        raise ValueError(f"prepared report SHA drift: {eid}")
    prepared = load_json(prepared_path)
    if prepared.get("actual_total_particles") not in {None, expected["total_particles"]}:
        raise ValueError(f"prepared report total drift: {eid}")
    bi4_ref = row["generated_bi4"]
    if not valid_sha(bi4_ref.get("producer_sha256")):
        raise ValueError(f"GenCase BI4 producer attestation missing: {eid}")
    decoder_sha = sha(DECODER_PATH)
    partvtk_contract = load_json(PARTVTK_CONTRACT_PATH)
    if partvtk_contract.get("registered_sha256") != "b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e":
        raise ValueError("PartVTK contract SHA drift")
    if partvtk_contract.get("source_read_or_hashed") is not False:
        raise ValueError("PartVTK contract unexpectedly claims source payload access")
    return {
        "schema": "ds02.f4.fresh095.gencase-basic-input-binding.v1",
        "family_id": "F4",
        "scope_id": "F4_STAGE1_FIRST24_PRE_SOLVER_GENCASE_BASIC_INITIAL_QA_V1",
        "case_id": eid,
        "physical_case_id": endpoint["physical_case_id"],
        "physical_condition_sha256": endpoint["physical_condition_sha256"],
        "source_plan_condition_sha256": endpoint["source_plan_condition_sha256"],
        "actual_source_commit": actual_binding.get("actual_source_commit"),
        "producer_scope": "Root44424/Root445 individual completed/0 GenCase evidence as recorded by fresh092",
        "source_owner": sha_ref(Path(endpoint["owner_path"])),
        "source_definition": sha_ref(source_path, supplied=source_sha),
        "gencase_receipt": {
            **sha_ref(receipt_path, supplied=receipt_sha),
            "status": receipt.get("status"),
            "returncode": int(receipt.get("returncode")),
            "attempt_id": str(receipt.get("attempt_id") or receipt_path.parent.name),
        },
        "prepared_report": sha_ref(prepared_path, supplied=prepared_sha),
        "generated_xml": sha_ref(xml_path, supplied=xml_sha),
        "generated_bi4": {
            "path": str(bi4_ref["path"]),
            "producer_sha256": bi4_ref["producer_sha256"],
            "content_rehashed_by_source": False,
            "read_by_source": False,
        },
        "expected": expected,
        "initial_velocity_declaration": {
            "values": xml_info["velocities"],
            "claim": "generated XML declaration only; no native frame-0 velocity observation",
        },
        "reader": {
            "partvtk_binary": {
                "path": str(PARTVTK_PATH),
                "registered_sha256": partvtk_contract["registered_sha256"],
                "source_read_or_hashed": False,
            },
            "safe_decoder_source": {
                "path": str(DECODER_PATH),
                "registered_sha256": decoder_sha,
                "source_read_or_hashed": False,
            },
            "accessed_arrays_by_registered_job": ["Posd", "Idp"],
            "raw_marker_arrays": {"Mk": "not_required/not_observed", "Type": "not_required/not_observed"},
        },
        "mass_policy": {
            "native_vs_nominal_report": True,
            "mass_rescaled": False,
            "stage1_gate": False,
            "exact_continuum_lattice_gate": False,
        },
        "downstream": {
            "post_native_frame0_velocity_audit": "fresh094",
            "post_native_contract_path": str(
                FAMILY_ROOT / "handoff_20261003" /
                "root_followup_094_stage1_f4_basic_native_input_qa_v1"
            ),
            "fresh093_native_plan_must_be_rederived_after_fresh095_pass": True,
        },
        "source_only": True,
        "execution_allowed": False,
        "arrays_read_by_source": False,
        "future_hashes_null": True,
        "claim_boundary": (
            "Pre-solver GenCase basic initial QA only; no native solver receipt/frame0 "
            "dependency, no native frame velocity observation, no mass/continuum "
            "lattice/precision/Q-N/visual/production approval."
        ),
    }


def package_input_paths(binding: dict[str, Any]) -> tuple[list[Path], list[Path]]:
    small = [
        PACKAGE / "workers" / "run_f4_fresh095_gencase_basic_initial_qa.py",
        PACKAGE / "metadata" / "fresh095-gencase-plan.json",
        PACKAGE / "metadata" / "fresh095-partvtk-contract.json",
        PACKAGE / "metadata" / "fresh095-root44424-evidence.json",
        PACKAGE / "metadata" / "fresh095-stage1-contract.json",
        Path(binding["source_owner"]["path"]),
        Path(binding["source_definition"]["path"]),
        Path(binding["gencase_receipt"]["path"]),
        Path(binding["prepared_report"]["path"]),
        Path(binding["generated_xml"]["path"]),
        PARTVTK_CONTRACT_PATH,
        ROOT237_CONTRACT_PATH,
        RUNTIME_PATH,
        STRICT_PATH,
        RESOURCE_PATH,
        DECODER_PATH,
        Path(binding["reader"]["partvtk_binary"]["path"]),
    ]
    deferred = [Path(binding["generated_bi4"]["path"])]
    return small, deferred


def make_request(binding: dict[str, Any]) -> dict[str, Any]:
    eid = binding["case_id"]
    small, deferred = package_input_paths(binding)
    input_sha = {}
    for path in small:
        input_sha[str(path)] = sha(path)
    attempt = f"root-stage1-f4-{eid.lower()}-gencase-basic-initial-qa-095"
    return {
        "schema": "ds02.runner-request.v2",
        "scope_id": "F4_STAGE1_FIRST24_PRE_SOLVER_GENCASE_BASIC_INITIAL_QA_V1",
        "family_id": "F4",
        "case_id": eid,
        "attempt_id": attempt,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 4,
        "max_wall_seconds": 1800,
        "estimated_storage_bytes": 2147483648,
        "cwd": str(PACKAGE / "workers"),
        "worktree_root": str(WORKTREE_ROOT),
        "launch_owner": "root",
        "root_review_required": True,
        "command": [
            str(PYTHON),
            str(PACKAGE / "workers" / "run_f4_fresh095_gencase_basic_initial_qa.py"),
            "--binding",
            str(PACKAGE / "metadata" / "bindings" / f"{eid}.gencase-basic-input-binding.json"),
            "--output",
            "{attempt_root}/gencase-basic-initial-qa.json",
        ],
        "input_files": [str(path) for path in small],
        "input_sha256": input_sha,
        "deferred_input_files": [str(path) for path in deferred],
        "deferred_input_sha256": {str(path): None for path in deferred},
        "deferred_bi4_producer_sha256": {
            str(Path(binding["generated_bi4"]["path"])): binding["generated_bi4"]["producer_sha256"]
        },
        "depends_on_attempts": [binding["gencase_receipt"]["attempt_id"]],
        "gencase_receipt": binding["gencase_receipt"]["path"],
        "gencase_receipt_sha256": binding["gencase_receipt"]["sha256"],
        "generated_xml": {
            "path": binding["generated_xml"]["path"],
            "sha256": binding["generated_xml"]["sha256"],
        },
        "owner_binding": binding["source_owner"],
        "root_cpu_reader": binding["reader"],
        "native_upstream_request": None,
        "gencase_actual_evidence": {
            "receipt": binding["gencase_receipt"]["path"],
            "receipt_sha256": binding["gencase_receipt"]["sha256"],
            "generated_xml": binding["generated_xml"]["path"],
            "generated_xml_sha256": binding["generated_xml"]["sha256"],
            "prepared_report": binding["prepared_report"]["path"],
            "prepared_report_sha256": binding["prepared_report"]["sha256"],
            "generated_bi4": binding["generated_bi4"]["path"],
            "generated_bi4_producer_sha256": binding["generated_bi4"]["producer_sha256"],
            "solver_dimension_from_gencase": binding["expected"]["dimension"],
            "total_particles": binding["expected"]["total_particles"],
            "fixed_particles": binding["expected"]["fixed_particles"],
            "fluid_particles": binding["expected"]["fluid_particles"],
        },
        "disabled": True,
        "launch": False,
        "launch_allowed": False,
        "execution_allowed": False,
        "source_only": True,
        "status": "source_only_disabled",
        "disabled_reason": (
            "Root must explicitly enable this pre-solver CPU audit only after "
            "reviewing the individual Root44424/Root445 completed/0 GenCase "
            "receipt, prepared XML/Definition, and attested BI4. It requires "
            "no native solver receipt or frame-0. The worker reads GenCase BI4 "
            "read-only through the registered decoder; fresh094 remains the "
            "separate post-native gate."
        ),
        "expected_outputs": {
            "gencase_basic_initial_qa": "{attempt_root}/gencase-basic-initial-qa.json",
            "report_sha256": None,
            "native_receipt": None,
            "native_frame0": None,
            "all_future_sha256": None,
        },
        "stage1_qa_contract": {
            "path": str(PACKAGE / "metadata" / "fresh095-stage1-contract.json"),
            "pre_solver_gencase_basic": True,
            "requires_native_receipt": False,
            "requires_native_frame0": False,
            "native_frame0_velocity": "deferred to fresh094 after fullnative",
        },
        "claim_boundary": "Pre-solver GenCase basic initial QA only; native solver/frame0 not required.",
        "root_only": True,
        "initial_velocity_claim": "XML declaration only; native frame-0 velocity deferred to fresh094",
        "no_jobs_started_by_source": True,
        "no_shared_registry_write": True,
        "precision_status": "not_accepted",
        "q_n_status": "not_assessed",
        "production_approval": "none",
        "independent_case_count_increment": 0,
        "arrays_read_by_source": False,
        "bi4_read_by_source": False,
        "h5_read": False,
        "csv_read": False,
        "native_solver_dependency": None,
    }


def build() -> None:
    actual_binding = load_json(ACTUAL_BINDING_PATH)
    actual_plan = load_json(ACTUAL_PLAN_PATH)
    cases = actual_plan.get("cases")
    rows = actual_binding.get("per_case_actual_gencase_receipts")
    if not isinstance(cases, list) or len(cases) != 24:
        raise ValueError("fresh092 actual plan must contain 24 cases")
    if not isinstance(rows, list) or len(rows) != 24:
        raise ValueError("fresh092 actual binding must contain 24 rows")
    by_id = {str(row["endpoint_id"]): row for row in rows}
    bindings = []
    requests = []
    for endpoint in cases:
        eid = str(endpoint["endpoint_id"])
        if eid not in by_id:
            raise ValueError(f"fresh092 binding missing {eid}")
        binding = make_binding(endpoint, by_id[eid], actual_binding)
        binding_path = PACKAGE / "metadata" / "bindings" / f"{eid}.gencase-basic-input-binding.json"
        write_json(binding_path, binding)
        bindings.append(binding)
    plan = {
        "schema": "ds02.f4.fresh095.gencase-basic-plan.v1",
        "family_id": "F4",
        "scope_id": "F4_STAGE1_FIRST24_PRE_SOLVER_GENCASE_BASIC_INITIAL_QA_V1",
        "case_count": 24,
        "actual_source_commit": actual_plan.get("actual_source_commit"),
        "producer_scope": "Root44424/Root445 individual completed/0 GenCase evidence",
        "cases": [
            {
                "case_id": binding["case_id"],
                "binding": str(PACKAGE / "metadata" / "bindings" / f"{binding['case_id']}.gencase-basic-input-binding.json"),
                "binding_sha256": None,
                "gencase_attempt_id": binding["gencase_receipt"]["attempt_id"],
                "physical_condition_sha256": binding["physical_condition_sha256"],
                "expected_counts": binding["expected"],
                "native_solver_dependency": None,
            }
            for binding in bindings
        ],
        "source_only": True,
        "future_hashes_null": True,
        "claim_boundary": "Pre-solver GenCase basic input QA only.",
    }
    write_json(PACKAGE / "metadata" / "fresh095-gencase-plan.json", plan)
    for row in plan["cases"]:
        row["binding_sha256"] = sha(Path(row["binding"]))
    write_json(PACKAGE / "metadata" / "fresh095-gencase-plan.json", plan)
    # The plan hash is deliberately not used as a self-referential input.
    write_json(PACKAGE / "metadata" / "fresh095-root44424-evidence.json", {
        "schema": "ds02.f4.fresh095.root44424-evidence.v1",
        "source_binding": str(ACTUAL_BINDING_PATH),
        "source_binding_sha256": sha(ACTUAL_BINDING_PATH),
        "source_plan": str(ACTUAL_PLAN_PATH),
        "source_plan_sha256": sha(ACTUAL_PLAN_PATH),
        "actual_source_commit": actual_plan.get("actual_source_commit"),
        "case_count": 24,
        "all_individual_receipts_completed0": True,
        "aggregate_receipt_promotion": "none",
        "producer_bi4_sha": "attested per case; source package does not read or rehash BI4",
        "claim_boundary": "GenCase producer evidence only; no native/solver/visual/precision/Q-N/production claim.",
    })
    for binding in bindings:
        requests.append(make_request(binding))
    for request in requests:
        eid = request["case_id"]
        write_json(PACKAGE / "requests" / f"{eid}-gencase-basic-initial-qa-disabled.request.json", request)
    request_index_cases = []
    for row in plan["cases"]:
        row["request"] = str(
            PACKAGE / "requests" /
            f"{row['case_id']}-gencase-basic-initial-qa-disabled.request.json"
        )
        request_index_cases.append({**row, "request_sha256": sha(Path(row["request"]))})
    write_json(PACKAGE / "evidence" / "request-index.json", {
        "schema": "ds02.f4.fresh095.request-index.v1",
        "scope_id": plan["scope_id"],
        "case_count": 24,
        "all_disabled": True,
        "cases": request_index_cases,
        "future_native_receipts": None,
        "fresh094_post_native_only": True,
    })
    write_json(PACKAGE / "metadata" / "fresh095-root44424-evidence.json", {
        "schema": "ds02.f4.fresh095.root44424-evidence.v1",
        "source_binding": str(ACTUAL_BINDING_PATH),
        "source_binding_sha256": sha(ACTUAL_BINDING_PATH),
        "source_plan": str(ACTUAL_PLAN_PATH),
        "source_plan_sha256": sha(ACTUAL_PLAN_PATH),
        "actual_source_commit": actual_plan.get("actual_source_commit"),
        "case_count": 24,
        "all_individual_receipts_completed0": True,
        "aggregate_receipt_promotion": "none",
        "producer_bi4_sha": "attested per case; source package does not read or rehash BI4",
        "claim_boundary": "GenCase producer evidence only; no native/solver/visual/precision/Q-N/production claim.",
    })
    # Rebuild request input closure now that plan/evidence exist.
    for request in requests:
        eid = request["case_id"]
        binding = load_json(
            PACKAGE / "metadata" / "bindings" /
            f"{eid}.gencase-basic-input-binding.json"
        )
        small, deferred = package_input_paths(binding)
        request["input_sha256"] = {str(path): sha(path) for path in small}
        request["input_files"] = [str(path) for path in small]
        request["deferred_input_files"] = [str(path) for path in deferred]
        request["deferred_input_sha256"] = {str(path): None for path in deferred}
        write_json(PACKAGE / "requests" / f"{eid}-gencase-basic-initial-qa-disabled.request.json", request)
    # Binding hashes are part of the plan. Request hashes stay only in the
    # non-self-referential request index because requests hash the plan.
    static_paths = [
        PACKAGE / "workers" / "run_f4_fresh095_gencase_basic_initial_qa.py",
        PACKAGE / "metadata" / "fresh095-gencase-plan.json",
        PACKAGE / "metadata" / "fresh095-root44424-evidence.json",
        PACKAGE / "metadata" / "fresh095-partvtk-contract.json",
        PACKAGE / "evidence" / "request-index.json",
    ]
    closure = {}
    for path in static_paths:
        if path.is_file():
            closure[str(path)] = sha(path)
    for binding in bindings:
        bpath = PACKAGE / "metadata" / "bindings" / f"{binding['case_id']}.gencase-basic-input-binding.json"
        closure[str(bpath)] = sha(bpath)
    for request in requests:
        rpath = PACKAGE / "requests" / f"{request['case_id']}-gencase-basic-initial-qa-disabled.request.json"
        closure[str(rpath)] = sha(rpath)
    write_json(PACKAGE / "evidence" / "source-static-closure.json", {
        "schema": "ds02.f4.fresh095.source-static-closure.v1",
        "paths": closure,
        "scientific_payloads_opened_or_hashed_by_builder": False,
        "deferred_bi4_hashes": None,
        "fresh093_094_bytes_modified": False,
    })
    manifest = {
        "schema": "ds02.f4.fresh095.manifest.v1",
        "family_id": "F4",
        "scope_id": plan["scope_id"],
        "case_count": 24,
        "source_only": True,
        "all_requests_disabled": True,
        "pre_solver": True,
        "native_solver_dependency": None,
        "future_hashes_null": True,
        "upstream_actual_gencase": str(ACTUAL_BINDING_PATH),
        "downstream_post_native": str(
            FAMILY_ROOT / "handoff_20261003" /
            "root_followup_094_stage1_f4_basic_native_input_qa_v1"
        ),
        "preserved_negative": "Root470 strict diagnostic remains unchanged and is not used as this gate.",
        "claim_boundary": "Pre-solver GenCase basic initial QA only.",
    }
    write_json(PACKAGE / "F4_STAGE1_FRESH095_PRE_SOLVER_GENCASE_BASIC_INITIAL_QA_MANIFEST.json", manifest)


if __name__ == "__main__":
    build()
