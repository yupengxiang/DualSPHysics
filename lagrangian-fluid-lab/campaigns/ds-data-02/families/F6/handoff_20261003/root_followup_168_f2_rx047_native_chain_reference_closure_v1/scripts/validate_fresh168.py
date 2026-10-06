#!/usr/bin/env python3
"""Build and validate the fresh168 metadata-only RX047 native-chain closure.

This script reads JSON/XML/Python metadata references only.  It deliberately
filters scientific payload references from the render request input lists and
never opens or hashes those payloads.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


PKG = Path(__file__).resolve().parents[1]
INTEGRATION = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics"
)
CAMPAIGN = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02"
HANDOFF = CAMPAIGN / "handoff_20261003"
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")

ROOT1205 = HANDOFF / (
    "root_stage1_source146147_F3_membership_native_request_roles_full336_"
    "registration_successor_checkpoint_1205/full336-role-aware-physical-"
    "registration-progress-index.json"
)
FRESH167 = PKG.parent / "root_followup_167_f2_native_actual_json_closure_v1" / (
    "metadata/f2-native-actual-json-closure.json"
)
FRESH167_ROLE_AUDIT = HANDOFF / (
    "root_stage1_source166167_F2_actual_native_receipt_nine_conditions_"
    "four_semantic_role_differences_absences_preserved_checkpoint_1216/"
    "actual167-own-native-JSON-field-and-semantic-alias-closure.json"
)
NATIVE_REVIEW = HANDOFF / (
    "root_stage1_F2_actual804809_full401_native_correct_known_solver_literal_"
    "prelaunch_repair1_812/actual-24-native-enablement-review.json"
)

FORBIDDEN_SUFFIXES = (
    ".h5",
    ".bi4",
    ".csv",
    ".dat",
    ".vtk",
    ".vtu",
    ".pvd",
    ".pvtu",
)
METADATA_SUFFIXES = (".json", ".xml", ".xmf", ".py", ".sh")

CASES = {
    "ROT075": {
        "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX047_RY014_FILL080_ROT075",
        "decision": HANDOFF / (
            "root_stage1_delegated133_F2_ROT075_full401_actual951_"
            "independent_QI_lifecycle_visual_integration_973/"
            "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX047_RY014_FILL080_ROT075-"
            "delegated-visual-decision.json"
        ),
        "adoption": HANDOFF / (
            "root_stage1_delegated133_F2_ROT075_full401_actual951_"
            "independent_QI_lifecycle_visual_integration_973/"
            "adoption-and-independent-review.json"
        ),
        "visual": CAMPAIGN / (
            "families/F6/handoff_20261003/"
            "root_followup_133_f2_rx047_ry014_fill080_rot075_root951_"
            "delegated_visual_acceptance_v1/metadata/visual-review.json"
        ),
        "chain": CAMPAIGN / (
            "families/F6/handoff_20261003/"
            "root_followup_133_f2_rx047_ry014_fill080_rot075_root951_"
            "delegated_visual_acceptance_v1/metadata/chain-closure.json"
        ),
        "render_request": HANDOFF / (
            "root_stage1_grounded116_manifest_path_repair1_full37_first_then_"
            "shared2_951/requests/"
            "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX047_RY014_FILL080_ROT075-"
            "render-request.json"
        ),
        "render_wrapper": HANDOFF / (
            "root_stage1_grounded116_manifest_path_repair1_full37_first_then_"
            "shared2_951/wrapper-requests/"
            "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX047_RY014_FILL080_ROT075-"
            "enabled-wrapper.json"
        ),
    },
    "ROT090": {
        "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX047_RY014_FILL080_ROT090",
        "decision": HANDOFF / (
            "root_stage1_delegated136_F4full1201_F6full241_F2full401_"
            "actual951_independent_QI_visual_integration_986/"
            "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX047_RY014_FILL080_ROT090-"
            "delegated-visual-decision.json"
        ),
        "adoption": HANDOFF / (
            "root_stage1_delegated136_F4full1201_F6full241_F2full401_"
            "actual951_independent_QI_visual_integration_986/"
            "adoption-and-three-case-independent-review.json"
        ),
        "visual": CAMPAIGN / (
            "families/F6/handoff_20261003/"
            "root_followup_136_f4_f6_f2_delegated_visual_acceptance_v1/"
            "metadata/visual-review.json"
        ),
        "chain": CAMPAIGN / (
            "families/F6/handoff_20261003/"
            "root_followup_136_f4_f6_f2_delegated_visual_acceptance_v1/"
            "metadata/chain-closure.json"
        ),
        "render_request": HANDOFF / (
            "root_stage1_grounded116_manifest_path_repair1_full37_first_then_"
            "shared2_951/requests/"
            "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX047_RY014_FILL080_ROT090-render-request.json"
        ),
        "render_wrapper": HANDOFF / (
            "root_stage1_grounded116_manifest_path_repair1_full37_first_then_"
            "shared2_951/wrapper-requests/"
            "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX047_RY014_FILL080_ROT090-enabled-wrapper.json"
        ),
    },
    "ROT105": {
        "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX047_RY014_FILL080_ROT105",
        "decision": HANDOFF / (
            "root_stage1_delegated134_F2_ROT105_full401_actual951_"
            "independent_QI_lifecycle_visual_integration_976/"
            "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX047_RY014_FILL080_ROT105-"
            "delegated-visual-decision.json"
        ),
        "adoption": HANDOFF / (
            "root_stage1_delegated134_F2_ROT105_full401_actual951_"
            "independent_QI_lifecycle_visual_integration_976/"
            "adoption-and-independent-review.json"
        ),
        "visual": CAMPAIGN / (
            "families/F6/handoff_20261003/"
            "root_followup_134_f2_rx047_ry014_fill080_rot105_root951_"
            "delegated_visual_acceptance_v1/metadata/visual-review.json"
        ),
        "chain": CAMPAIGN / (
            "families/F6/handoff_20261003/"
            "root_followup_134_f2_rx047_ry014_fill080_rot105_root951_"
            "delegated_visual_acceptance_v1/metadata/chain-closure.json"
        ),
        "render_request": HANDOFF / (
            "root_stage1_grounded116_manifest_path_repair1_full37_first_then_"
            "shared2_951/requests/"
            "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX047_RY014_FILL080_ROT105-"
            "render-request.json"
        ),
        "render_wrapper": HANDOFF / (
            "root_stage1_grounded116_manifest_path_repair1_full37_first_then_"
            "shared2_951/wrapper-requests/"
            "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX047_RY014_FILL080_ROT105-enabled-wrapper.json"
        ),
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text())


def ref(path: Path, declared: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"path": str(path), "exists": path.exists()}
    if path.exists():
        out["actual_sha256"] = sha256(path)
    if declared is not None:
        out["declared_sha256"] = declared
        out["declared_matches_actual"] = path.exists() and out["actual_sha256"] == declared
    return out


def forbidden_path(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    low = value.lower()
    return any(low.endswith(s) or f"{s}/" in low for s in FORBIDDEN_SUFFIXES) or "/trajectory" in low


def metadata_input_ref(path: str) -> bool:
    low = path.lower()
    return (not forbidden_path(path)) and low.endswith(METADATA_SUFFIXES)


def safe_request_inputs(request: dict[str, Any]) -> dict[str, Any]:
    files = request.get("input_files", [])
    hashes = request.get("input_sha256", {})
    safe = []
    omitted = 0
    for item in files:
        if not isinstance(item, str):
            continue
        if forbidden_path(item):
            omitted += 1
            continue
        if metadata_input_ref(item):
            safe.append({"path": item, "declared_sha256": hashes.get(item)})
        else:
            omitted += 1
    return {
        "metadata_refs": safe,
        "metadata_ref_count": len(safe),
        "omitted_nonmetadata_or_science_ref_count": omitted,
        "science_payload_refs_copied": False,
    }


def find_case_ref(obj: Any, target_path: str, target_physical: str) -> bool:
    if isinstance(obj, dict):
        if obj.get("path") == target_path:
            return True
        if obj.get("physical_case_id") == target_physical:
            text = json.dumps(obj, ensure_ascii=False)
            if target_path in text:
                return True
        return any(find_case_ref(v, target_path, target_physical) for v in obj.values())
    if isinstance(obj, list):
        return any(find_case_ref(v, target_path, target_physical) for v in obj)
    return False


def extract_physical_row(index: dict[str, Any], physical_case_id: str) -> dict[str, Any]:
    rows = index.get("cases", [])
    for row in rows:
        if row.get("physical_case_id") == physical_case_id:
            native = row.get("native_request_scope") or {}
            return {
                "accepted_decision": row.get("accepted_decision"),
                "status": row.get("status"),
                "case_credit_already_in_authoritative_checkpoint": row.get(
                    "case_credit_already_in_authoritative_checkpoint"
                ),
                "historical_native_scope_sha256": native.get("sha256"),
                "historical_native_scope_role": native.get("role"),
                "historical_native_candidate_receipt_count": len(
                    native.get("candidate_receipts", [])
                ),
                "old_roster_condition_field": row.get("old_roster_condition_field"),
            }
    raise KeyError(physical_case_id)


def find_fresh167_row(physical_case_id: str) -> dict[str, Any]:
    data = load(FRESH167_ROLE_AUDIT)
    for row in data.get("rows", []):
        if row.get("physical_case_id") == physical_case_id:
            return row
    raise KeyError(physical_case_id)


def safe_identity(receipt: dict[str, Any]) -> dict[str, Any]:
    request = receipt.get("request") or {}
    keys = (
        "schema",
        "family_id",
        "case_id",
        "physical_case_id",
        "physical_condition_sha256",
        "source_plan_physical_condition_sha256",
        "actual_converter_scope_sha256",
        "attempt_id",
        "expected_native_frames",
        "expected_dimension",
        "physical_window_s",
        "save_interval_s",
        "production_approval",
        "q_n",
        "precision_status",
    )
    return {
        "status": receipt.get("status"),
        "returncode": receipt.get("returncode"),
        "request": {k: request.get(k) for k in keys if k in request},
        "physical_binding_present": "physical_binding" in request,
    }


def report_metadata(path: Path) -> dict[str, Any]:
    data = load(path)
    dim = data.get("solver_dimension")
    if isinstance(dim, dict):
        dim = dim.get("solver_dimension")
    scopes = data.get("hash_scopes") or {}
    provenance = data.get("source_provenance") or {}
    solver = provenance.get("solver_receipt") or {}
    owner = provenance.get("owner_metadata") or {}
    return {
        "report": ref(path),
        "schema": data.get("schema"),
        "conversion_status": data.get("conversion_status"),
        "solver_dimension": dim,
        "frames": data.get("frames"),
        "particles": data.get("particles"),
        "actual_converter_scope_sha256": scopes.get("physical_condition_sha256"),
        "source_provenance_solver_receipt": {
            "path": solver.get("path"),
            "declared_sha256": solver.get("sha256"),
        },
        "owner_metadata": (
            {"path": owner.get("path"), "declared_sha256": owner.get("sha256")}
            if owner
            else None
        ),
    }


def render_metadata(
    request_path: Path,
    wrapper_path: Path,
    chain: dict[str, Any],
    decision_evidence: dict[str, Any],
) -> dict[str, Any]:
    request = load(request_path)
    wrapper = load(wrapper_path)
    chain_render = (chain.get("producer_chain") or {}).get("render") or {}
    if not chain_render:
        chain_render = decision_evidence.get("render") or {}
    report_path = Path(chain_render["report"])
    publish_path = Path(chain_render["publish_receipt"])
    receipt_path = Path(chain_render["receipt"])
    receipt_data = load(receipt_path)
    publish_data = load(publish_path)
    report_data = load(report_path)
    return {
        "request": ref(request_path),
        "wrapper": ref(wrapper_path),
        "request_identity": {
            k: request.get(k)
            for k in (
                "schema",
                "family_id",
                "case_id",
                "physical_case_id",
                "physical_condition_sha256",
                "actual_converter_scope_sha256",
                "attempt_id",
                "expected_frames",
                "expected_particles",
                "expected_contact_sheets",
                "disabled",
                "source_only",
                "launch",
                "launch_allowed",
                "execution_allowed",
            )
        },
        "wrapper_identity": {
            k: wrapper.get(k)
            for k in (
                "schema",
                "case_id",
                "physical_case_id",
                "actual_converter_scope_sha256",
                "attempt_id",
                "expected_frames",
                "expected_particles",
                "expected_contact_sheets",
                "disabled",
                "source_only",
                "launch",
                "launch_allowed",
                "execution_allowed",
            )
        },
        "declared_request_metadata_inputs": safe_request_inputs(request),
        "declared_wrapper_metadata_inputs": safe_request_inputs(wrapper),
        "actual_render": {
            "status": chain_render.get("status"),
            "receipt_status": receipt_data.get("status"),
            "receipt_returncode": receipt_data.get("returncode"),
            "publish_status": publish_data.get("status") or publish_data.get("published_status"),
            "receipt": ref(receipt_path),
            "report": ref(report_path),
            "publish_receipt": ref(publish_path),
            "frames": chain_render.get("frames") or report_data.get("frames"),
            "contact_sheets": chain_render.get("contact_sheets"),
            "key_frames": chain_render.get("key_frames"),
            "camera_bounds_source": chain_render.get("camera_bounds_source"),
        },
    }


def build() -> dict[str, Any]:
    root_index = load(ROOT1205)
    fresh167 = load(FRESH167)
    native_review = load(NATIVE_REVIEW)
    rows: list[dict[str, Any]] = []
    for tag, cfg in CASES.items():
        decision = load(cfg["decision"])
        visual = load(cfg["visual"])
        chain = load(cfg["chain"])
        adoption = load(cfg["adoption"])
        request = load(cfg["render_request"])
        wrapper = load(cfg["render_wrapper"])
        physical = cfg["physical_case_id"]
        decision_evidence = decision.get("actual_completed_metadata_evidence") or {}
        native_evidence = decision_evidence.get("native") or decision_evidence.get("native_full") or {}
        native_chain = (chain.get("producer_chain") or {}).get("native") or {}
        chain_native_ref_present = bool(native_chain.get("receipt") and native_chain.get("request"))
        # The aggregate fresh136 chain audit keeps the F2 row but does not
        # repeat its producer_chain.  Resolve that one case through the
        # immutable Root812 request roster and the accepted decision receipt.
        if not native_chain.get("receipt"):
            native_receipt_path = Path(
                native_evidence.get("execution_receipt")
                or native_evidence.get("receipt")
            )
            review_requests = native_review.get("requests", [])
            request_value = next(
                value
                for value in review_requests
                if isinstance(value, str) and decision.get("case_id", "") in value
            )
            native_request_path = Path(request_value)
            native_chain = {
                "status": native_evidence.get("status", "completed/0"),
                "receipt": str(native_receipt_path),
                "request": str(native_request_path),
                "saved_frame_count": native_evidence.get("saved_frame_count", 401),
            }
        else:
            native_receipt_path = Path(native_chain["receipt"])
            native_request_path = Path(native_chain["request"])
        native_receipt = load(native_receipt_path)
        conversion_report_path = Path(
            ((decision_evidence.get("typed") or {}).get("report"))
            or ((decision_evidence.get("typed") or {}).get("conversion_report"))
        )
        conversion = report_metadata(conversion_report_path)
        solver = conversion["source_provenance_solver_receipt"]
        solver_path = Path(solver["path"])
        scope = decision.get("scope_separation") or {}
        visual_scope = visual.get("scope_separation") or {}
        chain_scope = chain.get("scope_separation") or {}
        decision_path = cfg["decision"]
        adoption_matches = find_case_ref(adoption, str(decision_path), physical)
        row167 = find_fresh167_row(physical)
        role_row = extract_physical_row(root_index, physical)
        native_request_sha = sha256(native_request_path)
        native_receipt_sha = sha256(native_receipt_path)
        solver_actual_sha = sha256(solver_path)
        decision_evidence_request_path = native_evidence.get("request") or str(native_request_path)
        decision_evidence_receipt_path = (
            native_evidence.get("receipt")
            or native_evidence.get("execution_receipt")
            or str(native_receipt_path)
        )
        direct_native = {
            "request": ref(native_request_path),
            "receipt": ref(native_receipt_path),
            "receipt_identity": safe_identity(native_receipt),
            "decision_evidence_request": ref(Path(decision_evidence_request_path)),
            "decision_evidence_receipt": ref(Path(decision_evidence_receipt_path)),
            "chain_producer_request": ref(native_request_path),
            "chain_producer_receipt": ref(native_receipt_path),
            "decision_and_chain_request_same": decision_evidence_request_path == str(native_request_path),
            "decision_and_chain_receipt_same": decision_evidence_receipt_path == str(native_receipt_path),
            "direct_ref_resolved": native_receipt_path.exists() and native_request_path.exists(),
            "chain_native_ref_present_in_source_chain_json": chain_native_ref_present,
            "native_request_resolution_source": (
                "accepted_decision_chain.producer_chain.native"
                if chain_native_ref_present
                else "Root812 actual-24-native-enablement-review.requests plus accepted decision native receipt"
            ),
        }
        source_solver = {
            "path": solver["path"],
            "declared_sha256": solver["declared_sha256"],
            "actual_sha256": solver_actual_sha,
            "declared_matches_actual": solver.get("declared_sha256") == solver_actual_sha,
            "same_file_as_native_receipt": solver_path == native_receipt_path,
        }
        row = {
            "tag": tag,
            "family_id": decision.get("family_id"),
            "case_id": decision.get("case_id"),
            "physical_case_id": physical,
            "accepted_decision": {
                **ref(decision_path),
                "status": decision.get("status"),
                "semantic_condition_sha256": decision.get("physical_condition_sha256"),
                "source_canonical_physical_condition_sha256": decision.get(
                    "source_canonical_physical_condition_sha256"
                ),
                "actual_converter_scope_sha256": decision.get("actual_converter_scope_sha256"),
                "precision_status": decision.get("precision_status"),
            },
            "main_adoption_proof": {
                **ref(cfg["adoption"]),
                "accepted_decision_reference_found": adoption_matches,
            },
            "source_visual_decision": ref(cfg["visual"]),
            "source_chain_audit": ref(cfg["chain"]),
            "role_aware_root1205_row": {
                **ref(ROOT1205),
                **role_row,
                "historical_native_scope_is_not_replaced": True,
            },
            "fresh167_pending_marker": {
                **ref(FRESH167_ROLE_AUDIT),
                "actual_native_ref_missing_in_direct_accepted_chain": row167.get(
                    "actual_native_ref_missing_in_direct_accepted_chain"
                ),
                "no_invented_native_SHA_in_fresh167": row167.get("no_invented_native_SHA"),
                "fresh168_resolution": "resolved from accepted decision evidence, source chain closure, actual native receipt, and conversion source_provenance.solver_receipt",
            },
            "native_actual_role": direct_native,
            "typed_conversion": {
                **conversion,
                "source_provenance_solver_receipt": source_solver,
            },
            "xmf_actual_role": {
                "request": ref(Path((decision_evidence.get("xmf") or {}).get("request"))) if (decision_evidence.get("xmf") or {}).get("request") else None,
                "manifest": ref(Path((decision_evidence.get("xmf") or {}).get("manifest"))) if (decision_evidence.get("xmf") or {}).get("manifest") else None,
                "case_xmf": ref(Path((decision_evidence.get("xmf") or {}).get("case_xmf"))) if (decision_evidence.get("xmf") or {}).get("case_xmf") else None,
                "receipt": ref(Path((decision_evidence.get("xmf") or {}).get("receipt"))) if (decision_evidence.get("xmf") or {}).get("receipt") else None,
                "status": (decision_evidence.get("xmf") or {}).get("status"),
                "frames": (decision_evidence.get("xmf") or {}).get("frames"),
                "particles": (decision_evidence.get("xmf") or {}).get("particles"),
                "dimension": (decision_evidence.get("xmf") or {}).get("dimension"),
            },
            "render_declared_inputs_and_actual": render_metadata(
                cfg["render_request"], cfg["render_wrapper"], chain, decision_evidence
            ),
            "scope_roles": {
                "accepted_semantic_condition_sha256": decision.get("physical_condition_sha256"),
                "native_request_physical_condition_sha256": (native_receipt.get("request") or {}).get("physical_condition_sha256"),
                "native_request_source_plan_sha256": (native_receipt.get("request") or {}).get("source_plan_physical_condition_sha256"),
                "actual_converter_scope_sha256": conversion.get("actual_converter_scope_sha256"),
                "render_declared_physical_scope_sha256": request.get("physical_condition_sha256"),
                "source_plan_scope_sha256": scope.get("source_plan_scope_sha256") or visual_scope.get("source_plan_scope_sha256") or chain_scope.get("source_plan_scope_sha256"),
                "source_definition_sha256": scope.get("source_definition_sha256") or visual_scope.get("source_definition_sha256") or chain_scope.get("source_definition_sha256"),
                "equality_claim": "none; semantic, native request, actual converter, render declaration, source plan, and source definition remain role-separated",
            },
            "resolution": {
                "status": "resolved",
                "historical_root1205_native_scope_was_null": role_row.get("historical_native_scope_sha256") is None,
                "direct_native_refs_are_actual_metadata_only": True,
                "source_provenance_solver_receipt_verified": source_solver["declared_matches_actual"],
                "no_science_payload_read_or_hashed_by_fresh168": True,
            },
        }
        rows.append(row)

    # Keep the previously established true absence explicit and untouched.
    coarse = next(r for r in fresh167.get("rows", []) if r.get("physical_case_id") == "F2H10V2_OFFSET_V1")
    coarse_native = (coarse.get("native_receipt_declarations") or [{}])[0]
    output = {
        "schema": "ds02.f6.fresh168.rx047-native-chain-closure.v1",
        "fresh_id": "fresh168",
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_only": True,
        "family_scope": "F6 handoff only; referenced cases remain F2 historical evidence",
        "scientific_payload_read_or_hashed_by_fresh168": False,
        "root1205_authoritative_reference": ref(ROOT1205),
        "fresh167_authoritative_reference": ref(FRESH167),
        "fresh167_role_audit_reference": ref(FRESH167_ROLE_AUDIT),
        "native_review_reference": ref(NATIVE_REVIEW),
        "cases": rows,
        "untouched_true_absence_guard": {
            "physical_case_id": coarse.get("physical_case_id"),
            "case_id": coarse.get("case_id"),
            "fresh167_reference": ref(FRESH167),
            "accepted_semantic_condition_sha256": (coarse.get("accepted_decision") or {}).get("top_physical_condition_sha256"),
            "direct_native_condition_sha256": None,
            "native_receipt": ref(Path(coarse_native["path"]), coarse_native.get("declared_sha256")),
            "native_receipt_request_physical_condition_field_present": (coarse_native.get("request_identity") or {}).get("physical_condition_sha256", {}).get("present"),
            "action": "preserved true absence; no canonical/top hash substitution",
        },
        "new_case_credit": 0,
        "global_state_modified": False,
        "jobs_started": False,
    }
    return output


def package_json_paths() -> Iterable[Path]:
    return PKG.rglob("*.json")


def validate(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("schema") != "ds02.f6.fresh168.rx047-native-chain-closure.v1":
        errors.append("schema")
    if data.get("source_only") is not True or data.get("scientific_payload_read_or_hashed_by_fresh168") is not False:
        errors.append("source boundary")
    expected = {
        "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX047_RY014_FILL080_ROT075",
        "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX047_RY014_FILL080_ROT090",
        "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX047_RY014_FILL080_ROT105",
    }
    got = {row.get("physical_case_id") for row in data.get("cases", [])}
    if got != expected or len(data.get("cases", [])) != 3:
        errors.append("exact RX047 three-case set")
    for top_ref_name in (
        "root1205_authoritative_reference",
        "fresh167_authoritative_reference",
        "fresh167_role_audit_reference",
        "native_review_reference",
    ):
        item = data.get(top_ref_name) or {}
        p = Path(item.get("path", ""))
        if not p.exists() or item.get("actual_sha256") != sha256(p):
            errors.append(f"top reference:{top_ref_name}")
    for row in data.get("cases", []):
        tag = row.get("tag", "?")
        for field in ("accepted_decision", "main_adoption_proof", "source_visual_decision", "source_chain_audit", "role_aware_root1205_row", "fresh167_pending_marker"):
            item = row.get(field) or {}
            p = Path(item.get("path", ""))
            if not p.exists() or item.get("actual_sha256") != sha256(p):
                errors.append(f"{tag}:{field} ref")
        accepted = row.get("accepted_decision") or {}
        if accepted.get("status") != "visual-approved-by-delegated-agent":
            errors.append(f"{tag}:accepted status")
        if (row.get("main_adoption_proof") or {}).get("accepted_decision_reference_found") is not True:
            errors.append(f"{tag}:adoption proof reference")
        native = row.get("native_actual_role") or {}
        receipt = native.get("receipt") or {}
        request = native.get("request") or {}
        if not native.get("direct_ref_resolved"):
            errors.append(f"{tag}:native unresolved")
        for item, name in ((request, "native request"), (receipt, "native receipt")):
            p = Path(item.get("path", ""))
            if not p.exists() or item.get("actual_sha256") != sha256(p):
                errors.append(f"{tag}:{name} hash")
        ident = native.get("receipt_identity") or {}
        if ident.get("status") != "completed" or ident.get("returncode") != 0:
            errors.append(f"{tag}:native terminal")
        if native.get("decision_and_chain_request_same") is not True or native.get("decision_and_chain_receipt_same") is not True:
            errors.append(f"{tag}:decision-chain native mismatch")
        typed = row.get("typed_conversion") or {}
        report = typed.get("report") or {}
        if not report.get("exists") or report.get("actual_sha256") != sha256(Path(report["path"])):
            errors.append(f"{tag}:conversion report")
        if typed.get("conversion_status") != "completed" or typed.get("solver_dimension") != 3 or typed.get("frames") != 401:
            errors.append(f"{tag}:conversion metadata")
        solver = typed.get("source_provenance_solver_receipt") or {}
        sp = Path(solver.get("path", ""))
        if not sp.exists() or solver.get("actual_sha256") != sha256(sp) or not solver.get("declared_matches_actual"):
            errors.append(f"{tag}:solver receipt provenance")
        if not solver.get("same_file_as_native_receipt"):
            errors.append(f"{tag}:solver/native identity")
        render = row.get("render_declared_inputs_and_actual") or {}
        for key in ("request", "wrapper"):
            item = render.get(key) or {}
            p = Path(item.get("path", ""))
            if not p.exists() or item.get("actual_sha256") != sha256(p):
                errors.append(f"{tag}:render {key}")
        ident = render.get("request_identity") or {}
        if ident.get("expected_frames") != 401 or ident.get("expected_particles") != 418104 or ident.get("expected_contact_sheets") != 17:
            errors.append(f"{tag}:render expected metadata")
        actual = (render.get("actual_render") or {})
        if actual.get("status") not in ("completed/0", "completed") or actual.get("receipt_status") != "completed" or actual.get("receipt_returncode") != 0 or actual.get("frames") != 401:
            errors.append(f"{tag}:render terminal")
        for field in ("receipt", "report", "publish_receipt"):
            item = actual.get(field) or {}
            p = Path(item.get("path", ""))
            if not p.exists() or item.get("actual_sha256") != sha256(p):
                errors.append(f"{tag}:render {field} ref")
        roles = row.get("scope_roles") or {}
        if roles.get("equality_claim") != "none; semantic, native request, actual converter, render declaration, source plan, and source definition remain role-separated":
            errors.append(f"{tag}:scope role claim")
        if row.get("resolution", {}).get("historical_root1205_native_scope_was_null") is not True:
            errors.append(f"{tag}:historical null not preserved")
    guard = data.get("untouched_true_absence_guard") or {}
    if guard.get("direct_native_condition_sha256") is not None or guard.get("native_receipt_request_physical_condition_field_present") is not False:
        errors.append("true absence guard")
    # No forbidden scientific payload paths are copied into package JSON.  A
    # schema label such as ``bi4-direct-conversion`` is metadata, not a path.
    def package_has_forbidden_path(obj: Any) -> bool:
        if isinstance(obj, str):
            return ("/" in obj or obj.startswith("~")) and forbidden_path(obj)
        if isinstance(obj, dict):
            return any(package_has_forbidden_path(v) for v in obj.values())
        if isinstance(obj, list):
            return any(package_has_forbidden_path(v) for v in obj)
        return False

    # No forbidden scientific payload paths are copied into package JSON.
    for p in package_json_paths():
        try: text = p.read_text().lower()
        except OSError: continue
        try: parsed = json.loads(text)
        except json.JSONDecodeError: continue
        if package_has_forbidden_path(parsed):
            errors.append(f"forbidden scientific reference in {p.name}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    metadata_path = PKG / "metadata/rx047-native-chain-closure.json"
    if args.write:
        metadata_path.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n")
    data = load(metadata_path)
    errors = validate(data)
    print(json.dumps({"schema": data.get("schema"), "cases": len(data.get("cases", [])), "errors": errors, "status": "PASS" if not errors else "FAIL"}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
