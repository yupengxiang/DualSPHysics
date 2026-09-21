#!/usr/bin/env python3
"""Authorize one fresh v2 CPU/native preflight after static root review.

The receipt binds the new literal Definition, its contract, and the explicit
receiver/destination observer.  It closes solver, GPU, queue, registry,
ledger, and qualification paths.  Writing this receipt is not a preflight and
does not add a T1 row or credit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts import f2_receiver_ballistic_catch_release010_v2_definition as definition
from scripts import f2_receiver_ballistic_catch_release010_v2_observer as observer


BASE = definition.BASE
CANDIDATE = LAB / "campaigns/core-v1/cfd/f2-pour-catch-candidate-card-v2.json"
ROUTE_AUDIT = LAB / "campaigns/core-v1/cfd/f2-pour-catch-route-audit-v1.json"
ROOT_REVIEW_DIR = BASE / "root-review"
ROOT_RECEIPT = ROOT_REVIEW_DIR / "admission-receipt-v2.json"
SCHEMA = "core.f2.receiver_ballistic_catch.root_review_admission.v2"
IMPLEMENTATION = Path(__file__).resolve()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def _assert_ref(item: dict[str, Any], label: str) -> Path:
    path = Path(item["path"])
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    if item.get("sha256") != sha256(path) or item.get("bytes") != path.stat().st_size:
        raise ValueError(f"{label}: stale hash/size")
    return path


def _static_checks() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    candidate = load(CANDIDATE)
    route = load(ROUTE_AUDIT)
    if candidate.get("candidate_id") != "F2_receiver_ballistic_catch_release_speed010_v2":
        raise ValueError("candidate identity is not the selected v2 route")
    if candidate.get("scope_id") != definition.SCOPE_ID or candidate.get("revision_id") != definition.REVISION_ID:
        raise ValueError("candidate scope/revision does not match the fresh Definition")
    if candidate.get("matrix_credit") != 0 or candidate.get("qualification_claim") != "none":
        raise ValueError("candidate card opened qualification credit")
    if route.get("selected_route", {}).get("same_input_retry") is not False:
        raise ValueError("route audit permits same-input retry")
    if route.get("selected_route", {}).get("old_failed_input_reused") is not False:
        raise ValueError("route audit reuses old input")
    if route.get("core_gate", {}).get("registry_mutation") != 0 or route.get("core_gate", {}).get("ledger_mutation") != 0:
        raise ValueError("route audit opened central mutation")

    definition_audit = definition.inspect_definition(definition.DEFAULT_DEFINITION)
    if definition_audit["initial_velocity_m_s"] != [0.0, 0.0, -0.1]:
        raise ValueError("v2 release speed is not the declared fresh hypothesis")
    contract = load(definition.DEFAULT_CONTRACT)
    if contract.get("schema") != "core.f2.receiver_ballistic_catch.definition_contract.v2":
        raise ValueError("Definition contract schema mismatch")
    if contract.get("definition_sha256") != definition_audit["sha256"]:
        raise ValueError("Definition contract does not bind literal XML")
    if contract.get("fresh_input", {}).get("same_input_retry") is not False:
        raise ValueError("Definition contract permits same-input retry")
    observer_contract = load(observer.OUTPUT)
    observer.verify_contract(observer.OUTPUT)

    old_token = "f2-static-receiver-ballistic-catch-v1"
    for path in (definition.DEFAULT_DEFINITION, definition.DEFAULT_CONTRACT, observer.OUTPUT):
        if old_token in str(path):
            raise ValueError(f"v1 namespace entered v2 closure: {path}")
    if BASE.exists():
        old_entries = [path for path in BASE.rglob("*") if old_token in str(path)]
        if old_entries:
            raise ValueError(f"v1 namespace entered v2 directory: {old_entries[0]}")
        generated = list((BASE / "preflight-v2").glob("**/*")) if (BASE / "preflight-v2").exists() else []
        if generated:
            raise FileExistsError("v2 preflight namespace is already materialized; one-shot admission cannot repeat")
    return candidate, route, contract, observer_contract


def build_receipt(output: Path = ROOT_RECEIPT) -> dict[str, Any]:
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(f"admission receipt already exists: {output}")
    candidate, route, contract, observer_contract = _static_checks()
    if not definition.DEFAULT_DEFINITION.is_file() or not definition.DEFAULT_CONTRACT.is_file() or not observer.OUTPUT.is_file():
        raise FileNotFoundError("v2 Definition, Definition contract, and observer contract are required")

    receipt = {
        "schema": SCHEMA,
        "status": "authorized_one_fresh_cpu_native_preflight_only",
        "qualification_claim": "none",
        "matrix_credit": 0,
        "review_decision": {
            "family": "F2",
            "scope_id": definition.SCOPE_ID,
            "revision_id": definition.REVISION_ID,
            "candidate_id": candidate["candidate_id"],
            "anchor_case_id": definition.CASE_ID,
            "authorized_now": True,
            "authorized_action": "run exactly one fresh CPU GenCase and native initial-frame decode in the v2 namespace",
            "authorized_solver": False,
            "authorized_gpu": False,
            "authorized_queue": False,
            "authorized_ledger": False,
            "authorized_registry": False,
            "authorized_matrix": False,
            "reason": "the release-speed v2 is a falsifiable new Definition and output identity with explicit contact, retained/spill, and q-endpoint observer ownership",
            "next_review_required": "review the zero-credit CPU/native receipt before any protected solver decision; no solver is authorized by this receipt",
        },
        "fresh_identity": {
            "new_literal_definition": True,
            "new_definition_path": str(definition.DEFAULT_DEFINITION.resolve()),
            "new_output_directory": str((BASE / "preflight-v2").resolve()),
            "old_v1_definition_reused": False,
            "old_v1_generated_xml_reused": False,
            "old_v1_native_bi4_reused": False,
            "old_v1_trajectory_reused": False,
            "old_v1_output_stem_reused": False,
            "same_input_retry": False,
            "submerged_slot_assets_reused": False,
        },
        "observer_admission": {
            "receiver_contact_contract_reviewed": True,
            "retained_vs_spill_contract_reviewed": True,
            "q_endpoint_contract_reviewed": True,
            "missing_ids_are_hard_failure": True,
            "open_top_is_not_closed_wall_violation": True,
            "event_observation_is_not_qualification": True,
        },
        "fixed_hard_gates": {
            "ids_unique_and_xml_aligned": True,
            "fluid_ids_match_generated_xml": True,
            "all_decoded_arrays_finite": True,
            "closed_outer_wall_endpoint_count_max": 0,
            "closed_receiver_endpoint_count_max": 0,
            "runtime_domain_outside_count_max": 0,
            "source_mass_relative_error_max": 0.025,
            "threshold_relaxation": False,
            "survivor_renormalization": False,
        },
        "denominator": {
            "planned_rows": 15,
            "executed_rows": 0,
            "passed_rows": 0,
            "failed_rows": 0,
            "event_censored_rows": 0,
            "unattempted_rows": 15,
            "qualification_credit": 0,
            "parent_denominator_changed": False,
        },
        "execution_constraints": {
            "definition_writer_invoked": True,
            "gencase_invoked": False,
            "native_decoder_invoked": False,
            "solver_invoked": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_mutation": 0,
            "T1_denominator_mutation": 0,
            "T2_denominator_mutation": 0,
            "qualification_credit": 0,
        },
        "retained_failure_denominator": {
            "v1_loader_returncode": 127,
            "v1_repair_excluded_particles": 64,
            "v1_repair_excluded_particles_density": 44,
            "v1_hard_integrity_pass": False,
            "v1_matrix_credit": 0,
            "v1_same_input_retry": False,
            "v1_rows_removed": 0,
        },
        "hash_bindings": {
            "candidate_card": ref(CANDIDATE, "selected conditional candidate card"),
            "route_audit": ref(ROUTE_AUDIT, "read-only route decision"),
            "definition": ref(definition.DEFAULT_DEFINITION, "fresh literal v2 Definition"),
            "definition_contract": ref(definition.DEFAULT_CONTRACT, "fresh v2 Definition hash closure"),
            "observer_contract": ref(observer.OUTPUT, "fresh receiver/destination/q observer contract"),
            "definition_implementation": ref(Path(definition.__file__), "v2 literal Definition implementation"),
            "observer_implementation": ref(Path(observer.__file__), "v2 observer implementation"),
            "review_implementation": ref(IMPLEMENTATION, "v2 root-review/admission implementation"),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return receipt


def verify_receipt(path: Path = ROOT_RECEIPT) -> dict[str, Any]:
    value = load(Path(path))
    if value.get("schema") != SCHEMA or value.get("status") != "authorized_one_fresh_cpu_native_preflight_only":
        raise ValueError("admission schema/status mismatch")
    if value.get("qualification_claim") != "none" or value.get("matrix_credit") != 0:
        raise ValueError("admission credit is open")
    if value.get("review_decision", {}).get("authorized_now") is not True:
        raise ValueError("admission is not explicit")
    for key in ("authorized_solver", "authorized_gpu", "authorized_queue", "authorized_ledger", "authorized_registry", "authorized_matrix"):
        if value["review_decision"].get(key) is not False:
            raise ValueError(f"admission opened {key}")
    for key in ("candidate_card", "route_audit", "definition", "definition_contract", "observer_contract", "definition_implementation", "observer_implementation", "review_implementation"):
        _assert_ref(value["hash_bindings"][key], key)
    if value["hash_bindings"]["review_implementation"]["path"] != str(IMPLEMENTATION):
        raise ValueError("root review implementation path changed")
    if value["fresh_identity"]["same_input_retry"] is not False:
        raise ValueError("same-input retry was enabled")
    for key in ("old_v1_definition_reused", "old_v1_generated_xml_reused", "old_v1_native_bi4_reused", "old_v1_trajectory_reused", "old_v1_output_stem_reused", "submerged_slot_assets_reused"):
        if value["fresh_identity"][key] is not False:
            raise ValueError(f"fresh identity reused old asset: {key}")
    controls = value["execution_constraints"]
    for key in ("gencase_invoked", "native_decoder_invoked", "solver_invoked", "gpu_started"):
        if controls[key] is not False:
            raise ValueError(f"admission execution already opened: {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation", "matrix_mutation", "T1_denominator_mutation", "T2_denominator_mutation", "qualification_credit"):
        if controls[key] != 0:
            raise ValueError(f"admission mutation opened: {key}")
    return {"status": "ok", "candidate_id": value["review_decision"]["candidate_id"], "authorized_preflights": 1, "matrix_credit": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("authorize")
    p.add_argument("--output", type=Path, default=ROOT_RECEIPT)
    p = sub.add_parser("verify")
    p.add_argument("--receipt", type=Path, default=ROOT_RECEIPT)
    args = parser.parse_args()
    result = build_receipt(args.output) if args.command == "authorize" else verify_receipt(args.receipt)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
