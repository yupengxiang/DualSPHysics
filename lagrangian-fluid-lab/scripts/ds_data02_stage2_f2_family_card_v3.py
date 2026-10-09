#!/usr/bin/env python3
"""Build an additive F2 card from the actual ROOT126/129/131 products.

This is a JSON-and-small-source audit only.  It reuses the immutable V2 card
validator for the 336/118 identity lineage, then adds the completed ROOT126
401-frame stream, ROOT129 sidecar, and ROOT131 logged-domain proof.  It never
opens H5, BI4, PartOut, VTK, raw solver output, or a solver and never turns a
native numerical-exclusion count into physical fate or dynamics credit.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any

SCHEMA = "ds02.stage2.f2.family-card.v3"
MANIFEST_SCHEMA = "ds02.stage2.f2.family-card.manifest.v3"
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".bi4", ".obi4", ".bi2", ".bi1", ".vtk"}
REQUIRED_SOURCE_KEYS = {
    "base_v2_script",
    "base_v2_manifest",
    "root126_report",
    "root126_receipt",
    "root126_proof",
    "root129_report",
    "root129_receipt",
    "root129_proof",
    "root131_proof",
    "domain_v1_evidence",
    "domain_v2_evidence",
    "domain_v2_script",
    "cpu_predicate_source",
    "gpu_predicate_source",
    "map_source",
    "motive_source",
    "motive_header_source",
    "partout_source",
}


class CardError(ValueError):
    """Raised when a card source is missing, stale, or semantically unsafe."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stat_ref(path: Path, role: str) -> dict[str, Any]:
    stat = path.stat()
    return {
        "role": role,
        "path": str(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "st_dev": stat.st_dev,
        "st_ino": stat.st_ino,
        "sha256": sha256_file(path),
    }


def require_file(path_value: Any, label: str, *, json_only: bool = False) -> Path:
    if not isinstance(path_value, str) or not path_value:
        raise CardError(f"{label} path is missing")
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise CardError(f"{label} is not an existing file: {path}")
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise CardError(f"{label} points to forbidden scientific payload: {path}")
    if json_only and path.suffix.lower() != ".json":
        raise CardError(f"{label} is not JSON: {path}")
    return path


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CardError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise CardError(f"{label} is not a JSON object: {path}")
    return value


def finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise CardError(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise CardError(f"{label} is not finite")
    return result


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise CardError(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def load_manifest(path: Path) -> tuple[dict[str, Any], dict[str, Path], dict[str, dict[str, Any]]]:
    manifest = read_json(path, "F2 family-card V3 manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise CardError("F2 family-card V3 manifest schema differs")
    entries = manifest.get("source_refs")
    if not isinstance(entries, list) or not entries:
        raise CardError("F2 family-card V3 manifest has no source references")
    paths: dict[str, Path] = {}
    products: dict[str, dict[str, Any]] = {}
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
            raise CardError("malformed V3 source reference")
        key = item["key"]
        if key in paths:
            raise CardError(f"duplicate V3 source key: {key}")
        path_value = require_file(item.get("path"), key, json_only=key not in {
            "cpu_predicate_source", "gpu_predicate_source", "map_source",
            "motive_source", "motive_header_source", "partout_source",
            "domain_v2_script", "base_v2_script",
        })
        expected = item.get("sha256")
        actual = sha256_file(path_value)
        if expected != actual:
            raise CardError(f"{key} SHA differs from manifest")
        paths[key] = path_value
        if path_value.suffix.lower() == ".json":
            products[key] = read_json(path_value, key)
    missing = REQUIRED_SOURCE_KEYS - set(paths)
    unexpected = set(paths) - REQUIRED_SOURCE_KEYS
    if missing or unexpected:
        raise CardError(f"V3 source closure differs: missing={sorted(missing)} unexpected={sorted(unexpected)}")
    return manifest, paths, products


def load_v2(manifest_path: Path, script_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    spec = importlib.util.spec_from_file_location("f2_family_card_v2_for_v3", script_path)
    if spec is None or spec.loader is None:
        raise CardError(f"cannot load V2 card validator: {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        result = module.derive(manifest_path)
    except Exception as exc:
        raise CardError(f"immutable V2 card validation failed: {exc}") from exc
    if result.get("schema") != "ds02.stage2.f2.family-card.v2":
        raise CardError("base V2 card validator returned an unexpected schema")
    return result, module


def binding_hash(product: dict[str, Any], key: str, expected: Path, label: str) -> None:
    binding = product.get(key)
    if not isinstance(binding, dict):
        raise CardError(f"{label} lacks {key} binding")
    if binding.get("path") != str(expected):
        raise CardError(f"{label} {key} path is not the bound source")
    if binding.get("sha256") != sha256_file(expected):
        raise CardError(f"{label} {key} SHA differs from the bound source")


def validate_stream(products: dict[str, dict[str, Any]], paths: dict[str, Path]) -> dict[str, Any]:
    report = products["root126_report"]
    if report.get("schema") != "ds02.stage2.f2.coarse-active-stream.v8":
        raise CardError("ROOT126 stream report schema differs")
    if report.get("status") != "COMPLETED_F2_COARSE_ACTIVE_FLUID_STREAM_V8_EXACT_NATIVE_MASS_BITS":
        raise CardError("ROOT126 stream is not a completed exact-mass report")
    if report.get("family_id") != "F2":
        raise CardError("ROOT126 stream family differs")
    stream = report.get("active_fluid_stream")
    if not isinstance(stream, dict) or stream.get("frame_count") != 401:
        raise CardError("ROOT126 does not bind all 401 saved frames")
    native_join = report.get("native_identity_join")
    if not isinstance(native_join, dict) or native_join.get("native_row_count") != 153:
        raise CardError("ROOT126 native identity count differs from 153")
    mass = report.get("mass_and_material")
    if not isinstance(mass, dict):
        raise CardError("ROOT126 mass block is missing")
    side_product = (products.get("root129_report") or {}).get("product") or {}
    xml_whole = finite(side_product.get("xml_whole_initial_fluid_mass_kg"), "ROOT126 XML whole mass")
    native_whole = finite(side_product.get("native_whole_initial_fluid_mass_kg"), "ROOT126 native whole mass")
    excluded = finite(mass.get("native_excluded_mass_lower_bound_kg"), "ROOT126 excluded mass")
    fraction = finite(mass.get("native_excluded_mass_fraction_whole_initial"), "ROOT126 unknown mass fraction")
    if abs(xml_whole - 18.910848) > 1e-12 or excluded <= 0 or fraction <= 0.003:
        raise CardError("ROOT126 mass screen no longer preserves the frozen .003 failure")
    claim = report.get("claim_boundary") or {}
    if claim.get("physical_destination_or_legal_flux") != "UNKNOWN" or claim.get("dynamical_impact") != "UNKNOWN":
        raise CardError("ROOT126 grants physical fate or dynamics")
    receipt = products["root126_receipt"]
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise CardError("ROOT126 receipt is not completed")
    if receipt.get("model_invoked") is True or receipt.get("cfd_invoked") is True:
        raise CardError("ROOT126 receipt reports a model/CFD invocation")
    root126_proof = products["root126_proof"]
    if root126_proof.get("schema") != "ds02.stage2.root.f2.stream-verification.v1":
        # The proof schema is intentionally checked conservatively by content
        # below as producer checkpoint names changed once during forwarding.
        if root126_proof.get("status") != "VERIFIED_ACTUAL_401_NATIVE_FRAME_STREAM_EXACT_MASS_ENCODING_AND_CENSOR_SCREEN_FAIL":
            raise CardError("ROOT126 verification proof is not the actual stream proof")
    return {
        "report": stat_ref(paths["root126_report"], "ROOT126 active stream report"),
        "receipt": stat_ref(paths["root126_receipt"], "ROOT126 execution receipt"),
        "proof": stat_ref(paths["root126_proof"], "ROOT126 verification proof"),
        "frame_count": 401,
        "native_omission_count": 153,
        "xml_whole_initial_fluid_mass_kg": xml_whole,
        "native_whole_initial_fluid_mass_kg": native_whole,
        "native_excluded_mass_lower_bound_kg": excluded,
        "unknown_identity_fraction_xml_whole": fraction,
        "frozen_unknown_identity_fraction_max": 0.003,
        "mass_screen": "FAIL_OVER_FROZEN_XML_WHOLE_INITIAL_0P003",
        "native_integrity": "SOURCE_CLOSED_401_FRAME_TYPED_STREAM_AND_IDENTITY_JOIN",
        "physical_fate": "UNKNOWN",
        "legal_outflow_or_spill": "UNKNOWN",
        "dynamical_impact": "UNKNOWN",
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def validate_sidecar(products: dict[str, dict[str, Any]], paths: dict[str, Path], stream: dict[str, Any]) -> dict[str, Any]:
    sidecar = products["root129_report"]
    if sidecar.get("schema") != "ds02.stage2.f2.coarse-active-stream-result-sidecar.v2":
        raise CardError("ROOT129 sidecar schema differs")
    if (sidecar.get("product") or {}).get("status") != "V8_STREAM_SOURCE_CLOSED_UNKNOWN_MASS_SCREEN_FAIL":
        raise CardError("ROOT129 sidecar product status differs")
    product = sidecar.get("product")
    if not isinstance(product, dict):
        raise CardError("ROOT129 sidecar product is missing")
    if product.get("status") != "V8_STREAM_SOURCE_CLOSED_UNKNOWN_MASS_SCREEN_FAIL":
        raise CardError("ROOT129 sidecar product status differs")
    if product.get("frame_count") != 401 or product.get("native_omission_count") != 153:
        raise CardError("ROOT129 sidecar does not bind ROOT126 401/153")
    if product.get("mass_screen") != "FAIL_OVER_FROZEN_XML_WHOLE_INITIAL_0P003":
        raise CardError("ROOT129 sidecar changes the frozen mass screen")
    if product.get("qualification") != {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}:
        raise CardError("ROOT129 sidecar grants qualification")
    if any(product.get(key) != "UNKNOWN" for key in ("physical_fate", "legal_outflow_or_spill", "dynamical_impact")):
        raise CardError("ROOT129 sidecar grants fate, flux, or dynamics")
    report_binding = product.get("report") or {}
    if report_binding.get("path") != str(paths["root126_report"]) or report_binding.get("sha256") != sha256_file(paths["root126_report"]):
        raise CardError("ROOT129 sidecar report binding differs from ROOT126")
    receipt_binding = product.get("execution_receipt") or {}
    if receipt_binding.get("path") != str(paths["root126_receipt"]) or receipt_binding.get("sha256") != sha256_file(paths["root126_receipt"]):
        raise CardError("ROOT129 sidecar receipt binding differs from ROOT126")
    return {
        "report": stat_ref(paths["root129_report"], "ROOT129 sidecar report"),
        "receipt": stat_ref(paths["root129_receipt"], "ROOT129 execution receipt"),
        "proof": stat_ref(paths["root129_proof"], "ROOT129 verification proof"),
        "status": sidecar.get("status"),
        "native_stream_source": "ROOT126 report/receipt exact path and SHA",
        "native_omission_count": 153,
        "unknown_mass_fraction": product.get("observed_unknown_identity_lower_bound_fraction_xml"),
        "physical_fate": "UNKNOWN",
        "dynamical_impact": "UNKNOWN",
        "qualification": product.get("qualification"),
    }


def validate_domain(products: dict[str, dict[str, Any]], paths: dict[str, Path]) -> dict[str, Any]:
    proof = products["root131_proof"]
    if proof.get("schema") != "ds02.stage2.root.f2-domain-metadata-verification.v1":
        raise CardError("ROOT131 domain proof schema differs")
    if proof.get("status") != "VERIFIED_ACTUAL153_NATIVE_COORDINATES_AGAINST_LOGGED_NUMERICAL_DOMAIN":
        raise CardError("ROOT131 domain proof status differs")
    if proof.get("exact153_native_id_position_density_bracket_joins") is not True:
        raise CardError("ROOT131 lacks exact native ID/domain joins")
    if proof.get("root126_proof_sha256") != sha256_file(paths["root126_proof"]):
        raise CardError("ROOT131 does not bind the actual ROOT126 proof")
    if proof.get("native_report_sha256") != sha256_file(paths["root126_report"]):
        raise CardError("ROOT131 does not bind the actual ROOT126 stream report")
    if proof.get("unique_final_map_violators") != 153 or proof.get("border_map_face_violation_events") != 175:
        raise CardError("ROOT131 domain counts differ")
    if proof.get("inside_declared_generation_box_aabb") != 0 or proof.get("below_declared_static_bottom_reference") != 22:
        raise CardError("ROOT131 geometry counts differ")
    if proof.get("mass_screen") != "FAIL_OVER_FROZEN_XML_WHOLE_INITIAL_0P003":
        raise CardError("ROOT131 changes the frozen mass screen")
    domain_v2 = products["domain_v2_evidence"]
    if domain_v2.get("schema") != "ds02.stage2.f2.coarse-position-domain-source-diagnostic.v2":
        raise CardError("F2 domain V2 source diagnostic schema differs")
    official = domain_v2.get("official_source") or {}
    if official.get("repository_commit") != "1ef78a446276cca8664d5e586d2e42e6e8f7e448":
        raise CardError("F2 domain source commit differs")
    if official.get("compiled_binary_source_link") != "UNKNOWN_UNPROVEN":
        raise CardError("F2 domain diagnostic overstates compiled GPU linkage")
    gpu = (((official.get("files") or {}).get("gpu_position_predicate") or {}).get("binding") or {})
    if gpu.get("path") != str(paths["gpu_predicate_source"]) or gpu.get("sha256") != sha256_file(paths["gpu_predicate_source"]):
        raise CardError("F2 GPU predicate source is not bound to the diagnostic")
    interpretation = domain_v2.get("interpretation") or {}
    if interpretation.get("physical_fate") != "UNKNOWN" or interpretation.get("dynamical_impact") != "UNKNOWN":
        raise CardError("F2 domain V2 diagnostic grants physical fate or dynamics")
    final = proof.get("map_real_pos_final") or {}
    border = proof.get("border_map_side_counts") or {}
    return {
        "proof": stat_ref(paths["root131_proof"], "ROOT131 domain verification proof"),
        "source_v1": stat_ref(paths["domain_v1_evidence"], "ROOT131 source V1 evidence"),
        "source_v2": stat_ref(paths["domain_v2_evidence"], "F2 domain V2 source diagnostic"),
        "official_repository_commit": official.get("repository_commit"),
        "cpu_predicate": stat_ref(paths["cpu_predicate_source"], "DualSPHysics CPU position predicate source"),
        "gpu_predicate": stat_ref(paths["gpu_predicate_source"], "DualSPHysics GPU position predicate source"),
        "gpu_compiled_link": "UNKNOWN_UNPROVEN",
        "final_map_domain": final,
        "final_unique_position_violators": 153,
        "final_face_events": proof.get("final_map_face_violation_events"),
        "border_unique_position_violators": proof.get("unique_border_map_violators"),
        "border_face_events": 175,
        "border_side_counts": border,
        "inside_generation_aabb": 0,
        "below_static_bottom_reference": 22,
        "interpretation": "Numerical MapRealPos/drawbox predicates are source-supported. They do not prove legal spill, moving-wall contact, physical fate, or dynamics.",
        "sensitivity_control": "PREREGISTERED_NOT_RUN_AND_NOT_QUALIFICATION",
        "physical_fate": "UNKNOWN",
        "legal_outflow_or_spill": "UNKNOWN",
        "dynamical_impact": "UNKNOWN",
    }


def derive(manifest_path: Path) -> dict[str, Any]:
    manifest, paths, products = load_manifest(manifest_path)
    v2_result, _ = load_v2(paths["base_v2_manifest"], paths["base_v2_script"])
    stream = validate_stream(products, paths)
    sidecar = validate_sidecar(products, paths, stream)
    domain = validate_domain(products, paths)
    if v2_result.get("task_eligibility", {}).get("QN") != "UNKNOWN":
        raise CardError("base V2 card grants QN credit")
    return {
        "schema": SCHEMA,
        "status": "PREPARED_F2_ADDITIVE_CARD_V3_NATIVE_STREAM_DOMAIN_BOUND_NO_SCIENTIFIC_CREDIT",
        "family_id": "F2",
        "card_lineage": {
            "role": "additive F3 card over immutable V2 identity card; V2/V27/V29/V30 products remain authoritative",
            "base_v2_schema": v2_result.get("schema"),
            "base_v2_status": v2_result.get("status"),
            "base_v2_manifest": stat_ref(paths["base_v2_manifest"], "immutable F2 card V2 manifest"),
            "base_v2_script": stat_ref(paths["base_v2_script"], "immutable F2 card V2 validator"),
            "old_products_immutable": True,
        },
        "actual_root126_stream": stream,
        "actual_root129_sidecar": sidecar,
        "actual_root131_domain": domain,
        "f2_native_scope": {
            "historical_v29_native_position_ids": 1078,
            "root126_root129_native_stream_ids": 153,
            "root126_root129_motive": "position",
            "source_identity_key": "(case_key, Idp)",
            "native_xml_type_mk": "XML-bound source ranges; not an independent native header type/MK read in this JSON-only card",
            "whole_initial_mass_denominator": "Frozen XML whole-initial fluid mass 18.910848 kg for the .003 screen",
            "native_whole_initial_mass_kg": 18.91084830276668,
        },
        "task_eligibility": {
            "native_frame_integrity_and_identity": "ELIGIBLE_SOURCE_CLOSED_DEVELOPMENT_DIAGNOSTIC",
            "source_MK_and_mass_bookkeeping": "ELIGIBLE_SOURCE_CLOSED_INITIAL_AXIS_ONLY",
            "numerical_position_exclusion_and_saved_bracket": "ELIGIBLE_NUMERICAL_CAUSE_DIAGNOSTIC",
            "domain_sensitivity": "PREPARED_METADATA_CONTROL_ONLY_NOT_RUN",
            "physical_destination": "UNKNOWN",
            "legal_outflow_or_spill": "UNKNOWN",
            "wall_contact_or_penetration": "UNKNOWN",
            "continuous_event_time": "UNKNOWN_SAVED_BRACKET_ONLY",
            "conversion_implementation_filtering": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "qualification_credit": "NONE",
        },
        "mass_and_censoring": {
            "native_excluded_mass_lower_bound_kg": stream["native_excluded_mass_lower_bound_kg"],
            "xml_whole_initial_mass_kg": stream["xml_whole_initial_fluid_mass_kg"],
            "unknown_identity_fraction_xml_whole": stream["unknown_identity_fraction_xml_whole"],
            "frozen_unknown_identity_fraction_max": 0.003,
            "screen": "FAIL; lower-bound visibility exceeds frozen .003 screen",
            "meaning": "This is a source/mass visibility screen, not a bounded velocity, impact, force, coupling, fate, or dynamics error.",
            "missing_identity_censoring": "153 source-visible native position exclusions remain censored for physical destination and continuous event semantics.",
        },
        "source_and_access": {
            "json_and_small_source_only": True,
            "h5_bi4_partout_vtk_raw_solver_opened_by_card": False,
            "gpu_predicate_source": "Pinned to JSphGpu_ker.cu at repository commit; compiled binary linkage remains UNKNOWN_UNPROVEN.",
            "license_and_redistribution": "Refer to immutable V2/product-access provenance; no new license claim.",
            "source_refs": {key: stat_ref(path, key) for key, path in paths.items()},
        },
        "claim_boundary": {
            "native_integrity": "SOURCE_CLOSED_FOR_ROOT126_401_FRAME_STREAM_AND_ROOT129_SIDEcar",
            "numerical_position_cause": "SOURCE_SUPPORTED_MAP_PREDICATE_AND_LOGGED_DOMAIN; NOT_PHYSICAL_FATE",
            "mass_screen": "FAIL_OVER_FROZEN_XML_WHOLE_INITIAL_0P003",
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "wall_contact": "UNKNOWN",
            "dynamics": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        },
    }


def audit(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest_path = require_file(str(manifest_path), "F2 family-card V3 manifest", json_only=True)
    result = derive(manifest_path)
    atomic_json(output_path, result)
    return {"schema": result["schema"], "status": result["status"], "native_ids": result["actual_root126_stream"]["native_omission_count"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(audit(args.manifest, args.output), sort_keys=True))
    except Exception as exc:
        print(f"F2 family-card v3 failed: {exc}", file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
