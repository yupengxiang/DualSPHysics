#!/usr/bin/env python3
"""Build the metadata-only F2 final48 primary-delivery handoff.

This builder reads JSON metadata only.  It never opens a science payload and
never hashes H5/BI4/CSV/DAT/VTK files.  PNG hashes and byte counts are copied
only when already attested by an upstream JSON decision.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


INTEGRATION = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003"
)
PACKAGE = Path(__file__).resolve().parents[1]
META = PACKAGE / "metadata"

ROOT320 = INTEGRATION / "ROOT_LIVE_RESUMPTION_CHECKPOINT_320.json"
ROOT1330_DIR = INTEGRATION / (
    "root_stage1_source173_F2_final48_actual42_primary_401frames_"
    "baseline421566_four_request_receipt_role_corrections_P03_unknown_"
    "typed_recovery_six_pending_1330"
)
ROOT1330 = ROOT1330_DIR / "F2-FINAL48-ACTUAL42ACCEPTED-SIXPENDING-CORRECTED-PRIMARY-DELIVERY.json"
ROOT1432_DIR = INTEGRATION / (
    "root_stage1_source223_actualF2_RX061ROT090_original1119_full401QI_"
    "personal26PNG_open_rim_dispersion_one_UID_omission_truthful_visual_"
    "acceptance_1432"
)
ROOT1432_INDEX = ROOT1432_DIR / "full336-current330-actual-final48-delivery-progress-index.json"
LAST1063 = INTEGRATION / (
    "root_stage1_current328_lastF2_original1063_full401_two_fluid_omissions_"
    "realQA_native_XMF_plan_roles_live1189_durableQI1430_1429"
    "/last-F2-original1063-full401-two-omissions-realQA-live-runtime-and-"
    "durableQI-readiness.json"
)

NEW_CASES = {
    "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX063_RY014_FILL080_ROT105": INTEGRATION / (
        "root_stage1_source175_F2_RX063ROT105_original1155_full401QI_"
        "personal26PNG_three_fluid_omissions_genuine_initialQA_receipt_"
        "role_correction_visual_acceptance_1352"
    ),
    "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX063_RY014_FILL080_ROT090": INTEGRATION / (
        "root_stage1_source193_F2_RX063ROT090_original1143_full401QI_"
        "personal26PNG_fifteen_fluid_omissions_genuine_initialQA_visual_"
        "acceptance_1375"
    ),
    "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090": INTEGRATION / (
        "root_stage1_source216_actualF2_RX056ROT090_original1097_full401QI_"
        "personal26PNG_three_fluid_omissions_genuineQA_native_XMF_roles_"
        "visual_acceptance_1394"
    ),
    "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX049_RY014_FILL080_ROT075": INTEGRATION / (
        "root_stage1_source183_actualF2_RX049ROT075_original1009_full401QI_"
        "personal26PNG_thirtyfive_fluid_omissions_genuineQA_native_XMF_"
        "roles_visual_acceptance_1402"
    ),
    "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX061_RY014_FILL080_ROT090": ROOT1432_DIR,
}


def load(path: Path):
    """Load a JSON metadata file; the allowlist prevents payload IO."""
    if path.suffix.lower() != ".json":
        raise ValueError(f"metadata builder refuses non-JSON input: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def sha256(path: Path) -> str:
    if path.suffix.lower() not in {".json", ".xml", ".xmf", ".py", ".md"}:
        raise ValueError(f"builder refuses to hash science/payload suffix: {path}")
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ref(path: Path, declared: str | None = None) -> dict:
    """Return a metadata reference without reading payload-like paths."""
    return {"path": str(path), "sha256": declared or sha256(path)}


def find_one(directory: Path, suffix: str) -> Path:
    matches = sorted(directory.glob(f"*{suffix}"))
    if len(matches) != 1:
        raise RuntimeError(f"expected one {suffix} in {directory}, got {matches}")
    return matches[0]


def adoption(directory: Path) -> tuple[dict, dict, dict, dict, Path, dict]:
    adoption_file = find_one(directory, "-personal-visual-adoption.json")
    adopted = load(adoption_file)
    decision = load(directory / Path(adopted["new_visual_decision"]["path"]).name)
    # The path in an adoption JSON is absolute and may point outside the source
    # directory.  Prefer it, while keeping an explicit source-directory check.
    decision_path = Path(adopted["new_visual_decision"]["path"])
    if decision_path.exists():
        decision = load(decision_path)
    validation_path = Path(adopted["source_validation"]["path"])
    validation = load(validation_path) if validation_path.exists() else {}
    qi_path = Path(adopted["independent_QI"]["path"])
    qi = load(qi_path) if qi_path.exists() else {}
    return adopted, decision, validation, qi, adoption_file, {
        "decision_path": decision_path,
        "validation_path": validation_path,
        "qi_path": qi_path,
    }


def ref_from_obj(obj):
    if isinstance(obj, dict) and "path" in obj and "sha256" in obj:
        return {"path": obj["path"], "sha256": obj["sha256"]}
    return obj


def primary_refs(decision: dict) -> dict:
    evidence = decision.get("actual_completed_metadata_evidence", {})
    # Keep every actual producer metadata reference, including genuine QA and
    # GenCase.  No payload itself is copied or opened.
    return {k: ref_from_obj(v) for k, v in evidence.items()}


def visual_evidence(decision: dict) -> dict:
    contacts = copy.deepcopy(decision.get("contact_sheets", []))
    keys = copy.deepcopy(decision.get("keyframes", []))
    return {
        "personal_visual_role": {
            "agent_personally_viewed_all_contacts_and_keys": decision.get(
                "agent_personally_viewed_all_contacts_and_keys"
            ),
            "contact_count": decision.get("personal_reviewed_contacts", len(contacts)),
            "keyframe_count": decision.get("personal_reviewed_keyframes", len(keys)),
            "contact_sheets": contacts,
            "keyframes": keys,
            "content_read_by_this_builder": False,
        },
        "published_navigation_role": {
            "contact_count": len(contacts),
            "keyframe_count": len(keys),
            "keyframe_indices": [
                item.get("frame", item.get("frame_index"))
                for item in keys
            ],
            "unique_contact_paths": len({item.get("path", item.get("absolute_path")) for item in contacts}),
            "unique_keyframe_paths": len({item.get("path", item.get("absolute_path")) for item in keys}),
            "producer_png_sha_and_bytes_are_attestation_only": True,
            "personal_images_and_navigation_are_separate_roles": True,
        },
    }


def new_product(physical_id: str, order: int, membership: dict) -> dict:
    directory = NEW_CASES[physical_id]
    adopted, decision, validation, qi, adoption_file, paths = adoption(directory)
    primary = primary_refs(decision)
    # The task requires a real initial QA/GenCase claim only where an explicit
    # producer reference exists.  This is intentionally presence based.
    qa_receipt = primary.get("initial_qa_receipt")
    qa_report = primary.get("initial_qa_report")
    gencase_receipt = primary.get("typed_source_gencase_receipt", primary.get("gencase_receipt"))
    generated_xml = primary.get("typed_source_generated_xml", primary.get("generated_xml"))
    explicit_qa = bool(
        decision.get("genuine_initial_QA_receipt_completed0_and_report_pass")
        or decision.get("source_initial_qa_stage_role_correction", {}).get(
            "actual_initial_qa_completed0_and_report_pass", False
        )
        or (qa_receipt is not None and qa_report is not None)
    )
    omission = decision.get("lifecycle_omissions")
    if omission is None:
        omission = decision.get("actual_quantified_missing_fluid")
    row = {
        "delivery_order": order,
        "family_id": decision.get("family_id", "F2"),
        "case_id": decision["case_id"],
        "physical_case_id": decision["physical_case_id"],
        "membership": membership,
        "delivery_status": "accepted_visual_decision_current_root320_followup",
        "case_credit_delta": 0,
        "case_credit": 0,
        "Q_N": 0,
        "Q_E": 0,
        "physical_condition_sha256": decision.get("physical_condition_sha256"),
        "actual_converter_scope_sha256": decision.get("actual_converter_scope_sha256"),
        "physical_scope_roles": {
            "actual_native_XMF_plan_namespaces": copy.deepcopy(
                decision.get("actual_native_XMF_plan_namespaces")
            ),
            "scope_clarification": ref_from_obj(decision.get("source_scope_clarification")),
            "plan_field_absence_is_preserved": True,
            "canonical_native_and_typed_XMF_legacy_are_not_conflated": True,
        },
        "primary_product_metadata": primary,
        "proofs": {
            "accepted_visual_decision": ref_from_obj(adopted.get("new_visual_decision")),
            "own_full401_QI": ref_from_obj(adopted.get("independent_QI")),
            "source_validator": ref_from_obj(adopted.get("source_validation")),
            "source_adoption": ref(adoption_file),
            "source_personal_visual_review": ref_from_obj(decision.get("source_personal_visual_review")),
            "actual_initial_QA_explicit": explicit_qa,
            "actual_initial_QA_receipt": ref_from_obj(qa_receipt),
            "actual_initial_QA_report": ref_from_obj(qa_report),
            "actual_GenCase_receipt": ref_from_obj(gencase_receipt),
            "actual_GenCase_generated_XML": ref_from_obj(generated_xml),
            "QI_is_not_runner_receipt": True,
        },
        "counts_and_time": {
            "full_native_frames": decision.get("full_native_frames"),
            "particle_count": decision.get("particle_count"),
            "initial_fluid_particles": decision.get("initial_fluid_particles"),
            "actual_initial_type_counts": copy.deepcopy(decision.get("actual_initial_type_counts")),
            "actual_terminal_type_counts": copy.deepcopy(decision.get("actual_terminal_type_counts")),
            "actual_type_counts": copy.deepcopy(decision.get("actual_type_counts")),
            "actual_physical_window_s": copy.deepcopy(decision.get("actual_physical_window_s")),
        },
        "fluid_omissions": copy.deepcopy(omission),
        "visual": visual_evidence(decision),
        "limits": {
            "strict_container": "unknown_or_not_claimed",
            "subDP_positive_depth": "not_quantified",
            "numerical_precision": "not_accepted; historical negative evidence retained",
            "bed_zero_bins": "diagnostic only where present",
            "weak_or_local_response": "disclosed; no large runup claim",
        },
        "source_metadata_model": validation.get("source_model", "gpt-5.6-luna/max"),
        "main_scientific_payload_IO": False,
    }
    return row


def main() -> None:
    root = load(ROOT1330)
    membership = root["membership"]
    registered = membership["registered_final48_physical_case_ids"]
    frozen = set(membership["frozen_first8_physical_case_ids"])
    actual24 = set(membership["actual_first24_physical_case_ids"])
    final48 = set(registered)
    corrected = root["main_corrected_actual_primary_and_published_navigation_sidecars"]
    corrected_by_id = {row["physical_case_id"]: copy.deepcopy(row) for row in corrected}
    pending_id = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX053_RY014_FILL080_ROT090"
    new_by_id = set(NEW_CASES)
    if pending_id in corrected_by_id or pending_id in new_by_id:
        raise AssertionError("pending case must not be a product")
    if set(corrected_by_id) & new_by_id:
        raise AssertionError("new product duplicates inherited product")
    if not new_by_id <= final48:
        raise AssertionError("all five new products must be members of Root1330 final48")
    if pending_id not in final48:
        raise AssertionError("RX053/ROT090 must remain in final48 pending boundary")

    products = []
    for order, physical_id in enumerate(registered, start=1):
        if physical_id == pending_id:
            continue
        member = {
            "frozen_first8_member": physical_id in frozen,
            "actual_first24_member": physical_id in actual24,
            "registered_final48_member": True,
            "membership_source": "Root1276 arrays inherited through Root1330; no lexical selection",
        }
        if physical_id in corrected_by_id:
            row = corrected_by_id[physical_id]
            row["delivery_order"] = order
            row["case_credit_delta"] = 0
            row["case_credit"] = 0
            row["Q_N"] = 0
            row["Q_E"] = 0
            row["membership"] = member
            row["inherited_from_root1330_primary_sidecar"] = True
            row["scientific_payload_IO"] = False
            products.append(row)
        elif physical_id in new_by_id:
            products.append(new_product(physical_id, order, member))
        else:
            raise AssertionError(f"no actual accepted product for {physical_id}")

    if len(products) != 47:
        raise AssertionError(f"expected 47 accepted products, got {len(products)}")
    if len({p["physical_case_id"] for p in products}) != 47:
        raise AssertionError("product physical IDs are not unique")

    def source_ref(path: Path):
        return {"path": str(path), "sha256": sha256(path)}

    source_provenance = {
        "schema": "ds02.f5.fresh224.source-provenance.v1",
        "source_only": True,
        "authoritative_sources": {
            "root320_checkpoint": source_ref(ROOT320),
            "root1330_delivery": source_ref(ROOT1330),
            "root1432_progress_index": source_ref(ROOT1432_INDEX),
            "root1063_pending_durable_metadata": source_ref(LAST1063),
        },
        "root1330_original_exact_package": copy.deepcopy(root.get("source_original_exact_package")),
        "root1330_membership": {
            "frozen_first8_physical_case_ids": membership["frozen_first8_physical_case_ids"],
            "actual_first24_physical_case_ids": membership["actual_first24_physical_case_ids"],
            "registered_final48_physical_case_ids": registered,
            "frozen8_subset_actual24_subset_final48": membership[
                "frozen8_subset_actual24_subset_registered48"
            ],
        },
        "baseline_policy": {
            "baseline421566_preserved_where_inherited_sidecar_declares": True,
            "new_actual_f2_products_particle_axis": 418104,
            "do_not_normalize_421566_to_418104": True,
            "baseline_condition_field_presence_and_absence_are_case_local": True,
        },
        "roles": {
            "native_canonical": "actual native producer field only",
            "typed_xmf_legacy": "actual conversion/typed producer scope only",
            "source_plan_and_SourceDef": "case-local declared roles; missing fields remain absent/null",
            "personal_visual": "upstream personal-review metadata and published PNG attestations",
            "navigation": "published contact/key references; separate role from personal review",
        },
        "payload_boundary": {
            "scientific_payload_IO": False,
            "science_payload_hashing": False,
            "PNG_handling": "producer-attested metadata only; no PNG read/hash by this package builder",
            "jobs_started": 0,
            "shared_state_mutation": False,
        },
    }

    pending_source = load(LAST1063)
    active = {
        "schema": "ds02.f2.final48.pending-primary-product.v1",
        "status": "pending_running_not_completed",
        "case_credit": 0,
        "family_id": "F2",
        "case_id": pending_source["case_id"],
        "physical_case_id": pending_source["physical_case_id"],
        "membership": {
            "frozen_first8_member": pending_source["physical_case_id"] in frozen,
            "actual_first24_member": pending_source["physical_case_id"] in actual24,
            "registered_final48_member": pending_source["physical_case_id"] in final48,
        },
        "actual_product": {
            "completed": False,
            "atomic_published": False,
            "personal_visual_review": None,
            "own_QI": {
                "path": pending_source["durable_entry"]["path"],
                "sha256": pending_source["durable_entry"]["sha256"],
                "status": "unexecuted",
                "output_sha256": None,
            },
        },
        "upstream_metadata": {
            "refs": copy.deepcopy(pending_source["upstream_full401_metadata_refs"]),
            "prior_previsual_review": copy.deepcopy(pending_source["prior_previsual_review"]),
            "canonical_native_sha256": pending_source["canonical_native_sha256"],
            "typed_XMF_legacy_sha256": pending_source["typed_XMF_legacy_sha256"],
            "actual_native_XMF_plan_field_namespaces": copy.deepcopy(
                pending_source["actual_native_XMF_plan_field_namespaces"]
            ),
            "actual_time_window_s": pending_source["actual_time_window_s"],
            "genuine_initial_QA_and_GenCase_completed0": pending_source[
                "genuine_initial_QA_and_GenCase_completed0"
            ],
            "fluid_omissions": copy.deepcopy(pending_source["fluid_omissions"]),
        },
        "live_observation": {
            "actual_registered_worker_pid": 772469,
            "actual_registered_worker_start_ticks": "215275078",
            "outer_launcher_pid": 772344,
            "outer_reservation_id": (
                "F2/F2_STAGE1_FIRST48_EXPANSION_RX053_RY014_FILL080_ROT090_"
                "DP010_SPATIAL_REFERENCE_SAVE010/root-stage1-f2-rx053-rot090-"
                "actual1048-full401-116-023-nvme-hard2gib-root1063"
            ),
            "same_handle_running": True,
            "running_is_not_completed0": True,
            "receipt_observation_is_mutable_until_terminal": True,
        },
        "no_restart": True,
        "scientific_payload_IO": False,
    }

    products_doc = {
        "schema": "ds02.f2.final48.primary-delivery-products.v1",
        "package": "fresh224",
        "family_id": "F2",
        "status": "47_actual_primary_products_1_pending",
        "case_credit": 0,
        "Q_N": 0,
        "Q_E": 0,
        "registered_final48_count": 48,
        "accepted_actual_product_count": 47,
        "pending_primary_count": 1,
        "membership": copy.deepcopy(source_provenance["root1330_membership"]),
        "products": products,
        "pending_case_id": pending_id,
        "pending_file": "pending-rx053-rot090.json",
        "scientific_payload_IO": False,
        "new_jobs": 0,
    }
    META.mkdir(parents=True, exist_ok=True)
    (META / "f2-final48-products.json").write_text(
        json.dumps(products_doc, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (META / "pending-rx053-rot090.json").write_text(
        json.dumps(pending_source, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (META / "pending-rx053-rot090-package-view.json").write_text(
        json.dumps(active, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (META / "source-provenance.json").write_text(
        json.dumps(source_provenance, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"built {len(products)} products + 1 pending in {PACKAGE}")


if __name__ == "__main__":
    main()
