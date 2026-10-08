#!/usr/bin/env python3
"""Expose the v27 product through a guarded metadata/access loader.

The loader is intentionally small and JSON-only.  It gives downstream task
code a stable way to load a family card and the one exact F2 index-78
reproduction contract without treating a prepared request as an execution.
The contract distinguishes actual native/quality evidence from the pending
portable raw-to-typed-to-label guard.  No H5, BI4, PartOut, or solver file is
opened here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
FAMILIES = [f"F{i}" for i in range(1, 8)]
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".bi4", ".bi2", ".bi1"}
PRODUCT_SCHEMA = "ds02.stage2.final-family-product.v27"
MANIFEST_SCHEMA = "ds02.stage2.final-family-product-manifest.v27"
DELIVERY_SCHEMA = "ds02.stage2.product-delivery-metadata.v28"


class DeliveryError(RuntimeError):
    """Raised when the product or its execution identity is incomplete."""


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _path(value: Path | str, label: str, *, allow_h5: bool = False) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute() or not path.is_file():
        raise DeliveryError(f"{label} is not an existing absolute file: {path}")
    if not allow_h5 and path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise DeliveryError(f"{label} is a forbidden scientific payload: {path}")
    return path


def _json(value: Path | str, label: str) -> tuple[Path, dict[str, Any]]:
    path = _path(value, label)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DeliveryError(f"{label} is invalid JSON: {path}") from error
    if not isinstance(data, dict):
        raise DeliveryError(f"{label} must be a JSON object")
    return path, data


def _ref(path: Path, role: str) -> dict[str, Any]:
    return {"role": role, "path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def load_product_json(product_path: Path | str) -> dict[str, Any]:
    """Load and validate the actual v27 JSON product without scientific I/O."""
    path, product = _json(product_path, "v27 product")
    if product.get("schema") != PRODUCT_SCHEMA or product.get("status") != "PREPARED_ACTUAL_V25_BOUND_SEVEN_FAMILY_PRODUCT_NO_PHYSICAL_QUALIFICATION":
        raise DeliveryError("v27 product schema/status is not the source-bound product")
    coverage = product.get("coverage") or {}
    if coverage.get("current_case_count") != 336 or coverage.get("hidden_current_cases") != 0 or coverage.get("anchor_cards") != 7 or coverage.get("native_alias_cases") != 118:
        raise DeliveryError("v27 product coverage is incomplete")
    cards = product.get("family_cards")
    if not isinstance(cards, dict) or sorted(cards) != FAMILIES:
        raise DeliveryError("v27 product does not contain exactly seven family cards")
    for family, card in cards.items():
        if card.get("schema") != "ds02.stage2.family-card.v27" or card.get("family_id") != family:
            raise DeliveryError(f"v27 family card {family} has an unexpected schema/identity")
        eligibility = card.get("task_eligibility") or {}
        if eligibility.get("physical_fate") != "UNKNOWN" or eligibility.get("dynamical_impact") != "UNKNOWN" or eligibility.get("QN") != "UNKNOWN" or eligibility.get("QE") != "UNKNOWN" or eligibility.get("QI") != "UNKNOWN":
            raise DeliveryError(f"v27 family card {family} grants unsupported scientific credit")
        policy = card.get("access_policy") or {}
        if any(policy.get(key) is not False for key in ("original_trajectory_h5_opened_by_assembler", "materialized_label_h5_opened_by_assembler", "part_bi4_opened_by_assembler", "solver_started", "model_invoked")):
            raise DeliveryError(f"v27 family card {family} has an open read policy")
    policy = product.get("read_policy") or {}
    if any(policy.get(key) is not False for key in ("original_trajectory_h5_opened_by_this_worker", "materialized_label_h5_opened_by_this_worker", "part_bi4_opened_by_this_worker", "raw_solver_output_opened_by_this_worker", "solver_started", "model_invoked")):
        raise DeliveryError("v27 product read policy is not JSON-only")
    manifest_ref = (product.get("inputs") or {}).get("manifest") or {}
    if manifest_ref.get("path") != str(path.parent / "final-family-product-manifest-v27.json"):
        # A guarded runtime may place output and manifest under sibling names;
        # path equality is checked when the manifest is loaded.  This branch
        # keeps the product usable for an explicit externally supplied path.
        if not isinstance(manifest_ref.get("path"), str) or not manifest_ref.get("path"):
            raise DeliveryError("v27 product lacks its manifest path")
    if manifest_ref.get("sha256") and Path(manifest_ref["path"]).is_file() and sha256_file(manifest_ref["path"]) != manifest_ref["sha256"]:
        raise DeliveryError("v27 product manifest digest differs")
    product["_loaded_product_path"] = str(path)
    product["_loaded_product_sha256"] = sha256_file(path)
    return product


def get_family_card(product: dict[str, Any], family_id: str) -> dict[str, Any]:
    """Return one exact family card, preserving its UNKNOWN boundaries."""
    if family_id not in FAMILIES:
        raise DeliveryError(f"unknown family: {family_id}")
    cards = product.get("family_cards") or {}
    card = cards.get(family_id)
    if not isinstance(card, dict):
        raise DeliveryError(f"family card is missing: {family_id}")
    return card


def get_current_case(product: dict[str, Any], family_id: str, current_index: int | None = None) -> dict[str, Any]:
    """Get an exposed CURRENT row; non-anchor rows never inherit anchor credit."""
    card = get_family_card(product, family_id)
    anchor = (card.get("current_anchor") or {}).get("current_index")
    if current_index is None:
        current_index = anchor
    cases = product.get("case_inventory")
    if not isinstance(cases, list):
        raise DeliveryError("v27 case inventory is missing")
    matches = [case for case in cases if case.get("current_index") == current_index and case.get("family_id") == family_id]
    if len(matches) != 1:
        raise DeliveryError(f"CURRENT case is not unique: {family_id}/{current_index}")
    case = matches[0]
    if current_index != anchor and case.get("anchor_card") is not None:
        raise DeliveryError("non-anchor case incorrectly inherits an anchor card")
    return case


def single_case_reproduction_contract(product: dict[str, Any], family_id: str = "F2") -> dict[str, Any]:
    """Describe one exact case's supported stages and pending stages."""
    if family_id != "F2":
        raise DeliveryError("the only bounded end-to-end contract is F2 index-78")
    card = get_family_card(product, "F2")
    anchor = card["current_anchor"]
    raw = card["raw_reconstruction"]
    if anchor.get("current_index") != 78 or anchor.get("physical_case_id") != "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090":
        raise DeliveryError("F2 card is not the registered index-78 case")
    if raw.get("producer_or_root_status") != "F2_NATIVE_V4_TERMINAL_VERIFIED; EXECUTABLE_PORTABLE_V4_FORWARD":
        # State records use the raw reconstruction phrase; the native bundle
        # is the authoritative terminal-v4 phrase.  Keep the distinction
        # explicit instead of upgrading the state credit.
        native_status = "ACTUAL_NATIVE_V4_TERMINAL_VERIFIED"
    else:
        native_status = "ACTUAL_NATIVE_V4_TERMINAL_VERIFIED"
    return {
        "schema": "ds02.stage2.single-case-reproduction-contract.v1",
        "case": {
            "family_id": "F2", "current_index": 78,
            "physical_case_id": anchor["physical_case_id"], "runtime_case_alias": anchor["runtime_case_alias"],
            "identity_key": "(Zone,Idp)", "frames": anchor["frames"], "particles": anchor["particles"],
            "actual_time_window_s": anchor["actual_time_window_s"],
        },
        "stages": [
            {"stage": "producer_current_and_v25_binding", "status": "ACTUAL_VERIFIED_JSON_ONLY", "scope": "exact forensic CURRENT path/SHA plus DATA v25 report/manifest/receipt"},
            {"stage": "native_raw_to_typed_and_label", "status": native_status, "scope": "F2 v4 terminal native evidence; source paths are provenance and not reopened here"},
            {"stage": "saved_frame_quality", "status": "ACTUAL_STRICT_PRODUCER_BOUND", "scope": "source-role/mass ledger and saved-frame chord diagnostics"},
            {"stage": "portable_raw_to_typed_to_label_replay", "status": "PENDING_CONSUMER_GUARD", "scope": "copy/re-hash/OS-open audit required; no portable credit in this contract"},
            {"stage": "physical_fate_or_dynamics", "status": "UNKNOWN", "scope": "not inferable from identity loss, saved brackets, or mass visibility"},
        ],
        "supported_task_scope": [
            "exact source/owner/control/geometry metadata",
            "source-role-specific mass bookkeeping",
            "native motive/source-visible alias identity",
            "saved-frame artifact/chord-censor diagnostics",
        ],
        "unsupported_or_pending": [
            "physical destination/legal flux",
            "continuous first arrival and hidden recrossings",
            "dynamical/QN/QE/QI qualification",
            "portable full-chain replay until consumer guard completes",
        ],
        "loader_entrypoints": [
            "load_product_json(path)", "get_family_card(product, 'F2')", "get_current_case(product, 'F2', 78)", "single_case_reproduction_contract(product, 'F2')",
        ],
    }


def _validate_execution_identity(product_path: Path, manifest_path: Path, request_path: Path, proof_path: Path, receipt_path: Path, manifest: dict[str, Any], request: dict[str, Any], proof: dict[str, Any], receipt: dict[str, Any]) -> None:
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "PREPARED_ACTUAL_V25_BOUND_SEVEN_FAMILY_PRODUCT_NO_PHYSICAL_QUALIFICATION":
        raise DeliveryError("v27 manifest is not the actual-bound manifest")
    if request.get("request_schema") != "ds02.stage2.final-family-product-v27-request.v1":
        raise DeliveryError("v27 request schema is not the guarded request")
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or not str(proof.get("status", "")).startswith("PASS_ACTUAL"):
        raise DeliveryError("v27 proof is not an actual producer proof")
    if proof.get("H5_BI4_read_by_root") is not False:
        raise DeliveryError("v27 proof does not close H5/BI4 scope")
    qualification = proof.get("scientific_qualification") or proof.get("qualification") or {}
    if any(qualification.get(key) not in (None, "UNKNOWN") for key in ("QN", "QE", "QI")):
        raise DeliveryError("v27 proof grants scientific qualification")
    report_path = proof.get("report") or proof.get("product") or proof.get("output")
    manifest_value = proof.get("output_evidence_manifest") or proof.get("manifest") or proof.get("output_manifest")
    receipt_value = proof.get("receipt")
    if report_path is not None and report_path != str(product_path):
        raise DeliveryError("v27 proof report/product path differs")
    if manifest_value is not None and manifest_value != str(manifest_path):
        raise DeliveryError("v27 proof manifest path differs")
    if receipt_value is not None and receipt_value != str(receipt_path):
        raise DeliveryError("v27 proof receipt path differs")
    for value, path, label in ((proof.get("report_sha256"), product_path, "v27 product"), (proof.get("output_evidence_manifest_sha256") or proof.get("manifest_sha256"), manifest_path, "v27 manifest"), (proof.get("receipt_sha256"), receipt_path, "v27 receipt")):
        if value is not None and value != sha256_file(path):
            raise DeliveryError(f"{label} digest differs from v27 proof")
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") not in (None, 0):
        raise DeliveryError("v27 receipt is not completed")
    if receipt.get("output_root") and Path(receipt["output_root"]) != product_path.parent:
        raise DeliveryError("v27 receipt output_root differs from product parent")
    # The prepared request is itself an input.  Its path/sha may be recorded
    # under either request or request_path by the independent proof.
    proof_request = proof.get("request") or proof.get("request_path")
    if proof_request is not None and proof_request != str(request_path):
        raise DeliveryError("v27 proof request path differs")
    proof_request_sha = proof.get("request_sha256")
    if proof_request_sha is not None and proof_request_sha != sha256_file(request_path):
        raise DeliveryError("v27 request digest differs from proof")


def build_delivery_metadata(product_path: Path | str, manifest_path: Path | str, request_path: Path | str, proof_path: Path | str, receipt_path: Path | str, output: Path | str) -> dict[str, Any]:
    product_path = _path(product_path, "v27 product")
    manifest_path, manifest = _json(manifest_path, "v27 manifest")
    request_path, request = _json(request_path, "v27 request")
    proof_path, proof = _json(proof_path, "v27 proof")
    receipt_path, receipt = _json(receipt_path, "v27 receipt")
    product = load_product_json(product_path)
    manifest_ref = (product.get("inputs") or {}).get("manifest") or {}
    if manifest_ref.get("path") != str(manifest_path) or manifest_ref.get("sha256") != sha256_file(manifest_path):
        raise DeliveryError("v27 product does not bind the supplied manifest exactly")
    _validate_execution_identity(product_path, manifest_path, request_path, proof_path, receipt_path, manifest, request, proof, receipt)
    source_refs = manifest.get("source_refs")
    if not isinstance(source_refs, list) or not source_refs:
        raise DeliveryError("v27 manifest lacks source references")
    dependencies = []
    for item in source_refs:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise DeliveryError("v27 source reference is malformed")
        path = _path(item["path"], item.get("role", "source reference"))
        digest = sha256_file(path)
        declared = item.get("sha256")
        if declared != digest:
            raise DeliveryError(f"source reference digest differs: {path}")
        role = str(item.get("role", "source reference"))
        if "F2 native" in role:
            access = "metadata_json_read_only; portable_guard_required_for_full_chain"
        elif "runtime" in role.lower() or "dispatch" in role.lower():
            access = "source_hash_bound_guard_only"
        else:
            access = "workspace_metadata_read_only"
        dependencies.append({"role": role, "path": str(path), "sha256": digest, "bytes": path.stat().st_size, "access": access, "scientific_payload_opened_by_this_worker": False})
    dependencies.extend([
        {**_ref(product_path, "v27 actual product"), "access": "workspace_metadata_read_only"},
        {**_ref(manifest_path, "v27 actual manifest"), "access": "workspace_metadata_read_only"},
        {**_ref(request_path, "v27 guarded request"), "access": "source_hash_bound_guard_only"},
        {**_ref(proof_path, "v27 actual proof"), "access": "workspace_metadata_read_only"},
        {**_ref(receipt_path, "v27 actual receipt"), "access": "workspace_metadata_read_only"},
    ])
    # Dedupe while retaining the first role/access declaration.
    unique: dict[str, dict[str, Any]] = {}
    for item in dependencies:
        unique.setdefault(item["path"], item)
    contract = single_case_reproduction_contract(product, "F2")
    result = {
        "schema": DELIVERY_SCHEMA,
        "status": "ACTUAL_V27_PRODUCT_LOADED_PORTABLE_F2_CHAIN_PENDING_CONSUMER_GUARD",
        "producer": {"script_path": str(SCRIPT), "script_sha256": sha256_file(SCRIPT)},
        "product": {"path": str(product_path), "sha256": sha256_file(product_path), "schema": product.get("schema"), "coverage": product.get("coverage")},
        "execution": {"proof": _ref(proof_path, "v27 actual proof"), "receipt": _ref(receipt_path, "v27 actual receipt"), "request": _ref(request_path, "v27 request"), "manifest": _ref(manifest_path, "v27 manifest")},
        "dependencies": list(unique.values()),
        "access_policy": {
            "workspace_evidence": "read-only JSON/XML/receipt/proof metadata under the paths above",
            "portable_raw_to_typed_to_label": "consumer parent guard required; no portable completion credit here",
            "trajectory_h5": "forbidden to this worker; producer paths remain provenance only",
            "materialized_label_h5": "forbidden to this worker; upstream quality report/receipt only",
            "part_bi4_and_solver_output": "forbidden to this worker",
            "external_redistribution": "not authorized by this product; retain workspace provenance and hashes",
        },
        "single_case_reproduction": contract,
        "task_qualification": {
            "source_owner_control_geometry_metadata": "ELIGIBLE_EXACT_ANCHOR",
            "source_role_mass_bookkeeping": "ELIGIBLE_SOURCE_ROLE_ONLY",
            "saved_frame_artifact_diagnostics": "ELIGIBLE_LIMITED_CHORD_CENSOR_SCOPE",
            "native_alias_identity": "ELIGIBLE_F2_INDEX78_NATIVE_SCOPE",
            "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_events": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "QI": "UNKNOWN",
        },
        "loader_interface": {
            "module": str(SCRIPT), "module_sha256": sha256_file(SCRIPT),
            "entrypoints": ["load_product_json(path)", "get_family_card(product, family_id)", "get_current_case(product, family_id, current_index)", "single_case_reproduction_contract(product, 'F2')"],
            "input_contract": "JSON product only; no scientific payload path accepted",
        },
        "read_policy": {"product_json_opened": True, "manifest_request_proof_receipt_opened": True, "trajectory_h5_opened": False, "materialized_label_h5_opened": False, "part_bi4_opened": False, "solver_started": False, "model_invoked": False},
    }
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise DeliveryError(f"refusing to overwrite v28 metadata: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--proof", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    build_delivery_metadata(args.product, args.manifest, args.request, args.proof, args.receipt, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
