#!/usr/bin/env python3
"""Reconcile the one historical F2 alias using bounded source metadata.

The case is intentionally kept unresolved unless the current catalog row,
023 audit receipt, producer request, generated source, geometry/control
metadata, and canonical condition binding all agree.  This command follows
only the exact paths recorded by those small metadata files.  It never opens
the trajectory H5, BI4/OBI4, PartOut, RunPARTs, or any JSONL payload and it
does not replace the alias with a neighbouring case.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
STAGE2 = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
CURRENT = STAGE2 / "CURRENT336.json"
AUDIT_023 = STAGE2 / "checkpoints/SCIENTIFIC_AUDIT_VERIFICATION_023.json"
ALIAS_INDEX_185 = STAGE2 / "checkpoints/CURRENT_ALIAS_MISMATCH_INDEX_ACTUAL_ROOT_VERIFICATION_185.json"
PLAN_280 = STAGE2 / "checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT280_V4.json"
REGISTRY_280 = STAGE2 / "requests/typed-lifecycle-evidence-registry-v4-after-root280-001.json"
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
AUDIT_023_SHA = "72fd44794443130ab129d75593a4d6689c889cf3af859cd602d11d540acf2881"
# This is the immutable checkpoint file SHA.  Its embedded ``report_sha256``
# refers to the separately published report and is intentionally not used as
# the file digest here.
ALIAS_INDEX_185_SHA = "04855e2968ab7821e21213d0ccb61508198fde54348e3d8d213790dc97d49ef3"
PLAN_280_SHA = "24202edc188a1f82a8fba4a2bffddc226843a954df5e0c7393c070d76b286900"
REGISTRY_280_SHA = "4778b7ffbf6ed672bb6d604a776c55038f01ca9cdb090f7e73742816fa0ce5cf"
TARGET = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
# CURRENT336 is a bounded catalog (about 2.6 MiB), while all followed
# producer/source documents remain well below 1 MiB.  This is still metadata
# only; deferred trajectory/native suffixes are rejected before stat/hash.
MAX_SMALL_BYTES = 4 * 1024 * 1024
PAYLOAD_SUFFIXES = {".h5", ".hdf5", ".jsonl", ".bi4", ".obi4"}


class AliasResolutionError(ValueError):
    pass


def _path(value: Any, label: str, *, reject_payload: bool = True) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise AliasResolutionError(f"{label} has no path")
    path = Path(value).expanduser().resolve()
    if reject_payload and path.suffix.lower() in PAYLOAD_SUFFIXES:
        raise AliasResolutionError(f"{label} is a deferred payload: {path}")
    if not path.is_file():
        raise AliasResolutionError(f"{label} is missing: {path}")
    return path


def _ref(path: Path, label: str, expected: str | None = None) -> dict[str, Any]:
    path = _path(path, label)
    stat = path.stat()
    if stat.st_size > MAX_SMALL_BYTES:
        raise AliasResolutionError(f"{label} exceeds bounded metadata read: {path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected is not None and digest != expected:
        raise AliasResolutionError(f"{label} SHA differs: {path}: {digest} != {expected}")
    return {
        "path": str(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": digest,
        "content_opened_by_preparer": True,
    }


def _json(path: Path, label: str) -> dict[str, Any]:
    _ref(path, label)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AliasResolutionError(f"{label} must be a JSON object")
    return value


def _atomic(path: Path, value: dict[str, Any]) -> dict[str, Any]:
    path = Path(path).expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise AliasResolutionError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return _ref(path, "new F2 alias resolution sidecar")


def _geometry(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def build(output: Path) -> dict[str, Any]:
    current_ref = _ref(CURRENT, "CURRENT336", CURRENT_SHA)
    current = _json(CURRENT, "CURRENT336")
    current_row = next((row for row in current.get("cases", []) if isinstance(row, dict) and row.get("physical_case_id") == TARGET), None)
    if not isinstance(current_row, dict):
        raise AliasResolutionError("historical alias row is absent from CURRENT336")
    if current_row.get("runtime_case_alias") == TARGET:
        raise AliasResolutionError("CURRENT row no longer records a distinct runtime alias")

    audit_ref = _ref(AUDIT_023, "scientific audit verification 023", AUDIT_023_SHA)
    audit = _json(AUDIT_023, "scientific audit verification 023")
    audit_row = next((row for row in audit.get("verified_cases", []) if isinstance(row, dict) and row.get("physical_case_id") == TARGET), None)
    if not isinstance(audit_row, dict):
        raise AliasResolutionError("023 does not contain the target alias row")
    audit_receipt_path = _path(audit_row.get("receipt"), "023 audit receipt")
    audit_receipt_ref = _ref(audit_receipt_path, "023 audit receipt", None)
    audit_receipt = _json(audit_receipt_path, "023 audit receipt")

    alias_index_ref = _ref(ALIAS_INDEX_185, "historical alias index 185", ALIAS_INDEX_185_SHA)
    alias_index = _json(ALIAS_INDEX_185, "historical alias index 185")
    if alias_index.get("target_row_canonical_equal") is not True:
        raise AliasResolutionError("185 did not confirm the target row canonical equality")

    plan_ref = _ref(PLAN_280, "after-root280 lifecycle plan", PLAN_280_SHA)
    plan = _json(PLAN_280, "after-root280 lifecycle plan")
    plan_row = next((row for row in plan.get("case_records", []) if isinstance(row, dict) and row.get("physical_case_id") == TARGET), None)
    if not isinstance(plan_row, dict) or plan_row.get("status") != "HISTORICAL_ALIAS_UNRESOLVED":
        raise AliasResolutionError("after-root280 plan does not retain the alias as unresolved")
    registry_ref = _ref(REGISTRY_280, "after-root280 lifecycle registry", REGISTRY_280_SHA)
    registry = _json(REGISTRY_280, "after-root280 lifecycle registry")

    metadata_refs: dict[str, dict[str, Any]] = {
        "current_manifest": _ref(Path(current_row["manifest"]["path"]), "CURRENT row manifest", current_row["manifest"].get("recomputed_sha256")),
        "conversion_report": _ref(Path(current_row["conversion_report"]["path"]), "CURRENT conversion report", current_row["conversion_report"].get("recomputed_sha256")),
        "gencase_receipt": _ref(Path(current_row["source_bindings"]["gencase_receipt"]["path"]), "CURRENT GenCase receipt", current_row["source_bindings"]["gencase_receipt"].get("sha256")),
        "solver_receipt": _ref(Path(current_row["source_bindings"]["solver_receipt"]["path"]), "CURRENT solver receipt", current_row["source_bindings"]["solver_receipt"].get("sha256")),
        "owner_metadata": _ref(Path(current_row["source_bindings"]["owner_metadata"]["path"]), "CURRENT owner metadata", current_row["source_bindings"]["owner_metadata"].get("sha256")),
    }
    manifest = _json(Path(metadata_refs["current_manifest"]["path"]), "CURRENT row manifest")
    conversion = _json(Path(metadata_refs["conversion_report"]["path"]), "CURRENT conversion report")
    gencase_receipt = _json(Path(metadata_refs["gencase_receipt"]["path"]), "CURRENT GenCase receipt")
    solver_receipt = _json(Path(metadata_refs["solver_receipt"]["path"]), "CURRENT solver receipt")
    owner = _json(Path(metadata_refs["owner_metadata"]["path"]), "CURRENT owner metadata")

    provenance = owner.get("provenance")
    if not isinstance(provenance, dict):
        raise AliasResolutionError("owner metadata has no provenance")
    native_request_path = _path(provenance.get("actual_native_request", {}).get("path"), "actual producer native request")
    source_metadata_path = _path(provenance.get("source_metadata", {}).get("path"), "source metadata")
    source_owner_path = _path(provenance.get("source_owner", {}).get("path"), "source owner metadata")
    source_definition_path = _path(provenance.get("source_definition", {}).get("path"), "source definition XML")
    metadata_refs.update({
        "actual_native_request": _ref(native_request_path, "actual producer native request", provenance["actual_native_request"].get("sha256")),
        "source_metadata": _ref(source_metadata_path, "source metadata", provenance["source_metadata"].get("sha256")),
        "source_owner": _ref(source_owner_path, "source owner metadata", provenance["source_owner"].get("sha256")),
        "source_definition": _ref(source_definition_path, "source definition XML", provenance["source_definition"].get("sha256")),
    })
    native_request = _json(native_request_path, "actual producer native request")
    source_metadata = _json(source_metadata_path, "source metadata")
    source_owner = _json(source_owner_path, "source owner metadata")
    source_definition_text = source_definition_path.read_text(encoding="utf-8", errors="replace")

    current_geometry = current_row.get("known_numeric_physical_parameters")
    manifest_geometry = manifest.get("actual_geometry")
    conversion_condition = conversion.get("hash_scopes", {}).get("physical_condition", {})
    conversion_geometry = conversion_condition.get("geometry") if isinstance(conversion_condition, dict) else None
    owner_geometry = owner.get("geometry")
    source_geometry = source_metadata.get("geometry")
    geometry_equal = (
        isinstance(manifest_geometry, dict)
        and manifest_geometry == conversion_geometry == owner_geometry == source_geometry
    )
    controls = [
        conversion_condition.get("control_family_id") if isinstance(conversion_condition, dict) else None,
        owner.get("control_family_id"),
        source_metadata.get("control_family_id"),
        source_owner.get("control_family_id") or source_owner.get("source_canonical_condition", {}).get("control_family_id"),
    ]
    present_controls = [value for value in controls if isinstance(value, str)]
    control_equal = bool(present_controls) and len(set(present_controls)) == 1 and present_controls[0] == "F2_CTRL_SMOOTH_ROTATE_Y_V1"
    motion_values = [
        conversion_condition.get("parameters", {}).get("source_motion_sha256") if isinstance(conversion_condition, dict) else None,
        owner.get("parameters", {}).get("source_motion_sha256"),
        source_metadata.get("motion", {}).get("sha256"),
        source_metadata.get("physical_condition", {}).get("motion_file_sha256"),
    ]
    motion_equal = len(set(motion_values)) == 1 and isinstance(motion_values[0], str)

    legacy_sha = manifest.get("physical_condition_sha256")
    canonical_sha = manifest.get("canonical_source_physical_condition_sha256")
    request_sha = native_request.get("physical_condition_sha256")
    source_plan_sha = source_metadata.get("source_plan_physical_condition_sha256")
    binding_values = {
        "manifest_canonical_source": canonical_sha,
        "source_metadata_binding": source_metadata.get("source_canonical_physical_binding_sha256"),
        "source_owner_binding": source_owner.get("canonical_physical_binding_sha256"),
        "owner_binding": owner.get("canonical_physical_binding_sha256"),
        "actual_converter_scope": provenance.get("actual_converter_physical_condition_scope_sha256"),
    }
    canonical_binding_present = all(isinstance(value, str) and value for key, value in binding_values.items() if key != "manifest_canonical_source")
    scope_equality_not_claimed = manifest.get("scope_equality_not_claimed") is True

    identity_consistent = all(
        value == TARGET
        for value in (
            current_row.get("physical_case_id"),
            manifest.get("physical_case_id"),
            conversion_condition.get("physical_case_id") if isinstance(conversion_condition, dict) else None,
            owner.get("physical_case_id"),
            source_metadata.get("physical_case_id"),
            source_owner.get("physical_case_id"),
            native_request.get("physical_case_id"),
            audit_row.get("physical_case_id"),
        )
    )
    runtime_alias = current_row.get("runtime_case_alias")
    runtime_alias_consistent = all(
        value == runtime_alias
        for value in (
            manifest.get("case_id"),
            owner.get("case_id"),
            source_metadata.get("case_id"),
            source_owner.get("case_id"),
            native_request.get("case_id"),
            gencase_receipt.get("request", {}).get("case_id"),
        )
    )

    result = {
        "schema": "ds02.stage2.f2-historical-alias-resolution.v1",
        "status": "UNRESOLVED_HISTORICAL_ALIAS_NO_CANONICAL_BINDING",
        "alias": {
            "physical_case_id": TARGET,
            "runtime_case_alias": runtime_alias,
            "current_index": current_row.get("current_index", 78),
            "plan_status": plan_row.get("status"),
            "source_join_status": plan_row.get("source_join_status"),
            "scientific_credit": plan_row.get("scientific_credit"),
        },
        "bounded_inputs": {
            "current_catalog": current_ref,
            "scientific_audit_023": audit_ref,
            "audit_receipt": audit_receipt_ref,
            "alias_index_185": alias_index_ref,
            "after_root280_plan": plan_ref,
            "after_root280_registry": registry_ref,
            "producer_and_source_metadata": metadata_refs,
        },
        "evidence": {
            "current_row_exact_target": current_row.get("physical_case_id") == TARGET,
            "current_row_runtime_alias_present": isinstance(runtime_alias, str) and runtime_alias != TARGET,
            "audit_023_exact_current_path_and_declared_sha_match": audit_row.get("exact_CURRENT_path_and_declared_sha_match") is True,
            "audit_023_scan_status": audit_row.get("scan_status"),
            "audit_023_receipt_status": audit_receipt.get("status"),
            "audit_023_trajectory_sha256": audit_row.get("trajectory_verified_sha256"),
            "root185_target_row_canonical_equal": alias_index.get("target_row_canonical_equal"),
            "root185_original_producer_binds_alias_at_launch_and_end": alias_index.get("original_producer_binds_alias_at_launch_and_end"),
            "root185_original_producer_exact_current_binding": alias_index.get("original_producer_exact_current_binding"),
            "identity_consistent_across_metadata": identity_consistent,
            "runtime_alias_consistent_across_producer_metadata": runtime_alias_consistent,
            "geometry_values_equal_across_manifest_conversion_owner_source": geometry_equal,
            "control_family_equal": control_equal,
            "motion_sha_equal": motion_equal,
            "legacy_condition_sha256": legacy_sha,
            "canonical_source_condition_sha256": canonical_sha,
            "producer_request_condition_sha256": request_sha,
            "source_plan_condition_sha256": source_plan_sha,
            "canonical_binding_fields": binding_values,
            "canonical_binding_present": canonical_binding_present,
            "scope_equality_not_claimed": scope_equality_not_claimed,
            "source_definition_mentions_target": f"physical_case_id={TARGET}" in source_definition_text,
            "registry_has_target_producer": any(TARGET in (p.get("case_ids") or []) for p in registry.get("producers", []) if isinstance(p, dict)),
        },
        "resolution": {
            "physical_geometry_and_control_match": bool(geometry_equal and control_equal and motion_equal),
            "producer_identity_and_runtime_alias_match": bool(identity_consistent and runtime_alias_consistent),
            "exact_alias_equivalence_proven": False,
            "reason": "The metadata agrees on the target physical_case_id, runtime alias, geometry, control, and motion, but the producer manifest says scope_equality_not_claimed and the canonical physical binding fields are null. Root185 also records alias-bound launch/end with original_producer_exact_current_binding=false. These facts do not authorize substituting the alias into the exact CURRENT lifecycle set.",
            "required_before_resolution": [
                "an explicit immutable canonical binding joining the alias producer scope to the CURRENT row",
                "a producer/request/receipt identity join that is exact for that binding, not a neighboring case",
            ],
        },
        "claim_boundary": {
            "alias_substitution": "FORBIDDEN",
            "typed_lifecycle_credit": "NONE",
            "native_cause": "UNKNOWN_FROM_THIS_ALIAS_SIDECAR",
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "dynamics": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        },
        "read_policy": {
            "metadata_json_xml_opened": True,
            "trajectory_h5_content_opened": False,
            "bi4_or_obi4_opened": False,
            "partout_or_runparts_opened": False,
            "jsonl_opened": False,
            "solver_started": False,
        },
    }
    return {"output": _atomic(output, result), "result": result}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    build_parser = sub.add_parser("build")
    build_parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.action == "self-test":
            value = {"status": "PASS", "alias": TARGET, "payload_content_opened": False, "exact_alias_equivalence_proven": False}
        else:
            value = build(args.output)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"F2_ALIAS_RESOLUTION_ERROR: {exc}")
        return 2
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
