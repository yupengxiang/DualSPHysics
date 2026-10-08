#!/usr/bin/env python3
"""Build an additive, JSON-only F2 family-card reconciliation sidecar.

The seven-family product remains the catalog authority.  This sidecar binds
the existing F2 card to the already-produced 336/118 ledgers and the ROOT105
coarse canary so a consumer can distinguish CURRENT evidence from the new
non-CURRENT canary.  It never opens H5, BI4, PartOut, raw solver output, or a
solver.  The ROOT111 active-frame stream is recorded as pending metadata and
receives no execution or scientific credit before its guarded receipt exists.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f2.family-card.v1"
MANIFEST_SCHEMA = "ds02.stage2.f2.family-card.manifest.v1"
CASE_KEY = "F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_T4_COARSE_CANARY_ROOT_095"
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".bi4", ".obi4", ".bi2", ".bi1"}


class CardError(ValueError):
    """Raised when one of the source-bound JSON products is not closed."""


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


def require_json(path_value: Any, label: str) -> Path:
    if not isinstance(path_value, str) or not path_value:
        raise CardError(f"{label} path is missing")
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise CardError(f"{label} is not an existing file: {path}")
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise CardError(f"{label} points to forbidden scientific payload: {path}")
    if path.suffix.lower() != ".json":
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
    manifest = read_json(path, "F2 family-card manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise CardError("family-card manifest schema differs")
    source_entries = manifest.get("source_refs")
    if not isinstance(source_entries, list) or not source_entries:
        raise CardError("family-card manifest has no source references")
    paths: dict[str, Path] = {}
    products: dict[str, dict[str, Any]] = {}
    for item in source_entries:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
            raise CardError("malformed family-card source reference")
        key = item["key"]
        source = require_json(item.get("path"), key)
        expected = item.get("sha256")
        actual = sha256_file(source)
        if expected != actual:
            raise CardError(f"{key} SHA differs from manifest")
        paths[key] = source
        products[key] = read_json(source, key)
    return manifest, paths, products


def _f2_rows(product: dict[str, Any], label: str) -> list[dict[str, Any]]:
    rows = product.get("cases")
    if not isinstance(rows, list):
        raise CardError(f"{label} has no case list")
    selected = [row for row in rows if isinstance(row, dict) and str(row.get("case_key", "")).startswith("F2/")]
    if len(selected) != 48:
        raise CardError(f"{label} has {len(selected)} F2 rows, expected 48")
    return selected


def derive(manifest_path: Path) -> dict[str, Any]:
    manifest, paths, products = load_manifest(manifest_path)
    base = products["v27_product"]
    if base.get("schema") != "ds02.stage2.final-family-product.v27" or base.get("status") != "PREPARED_ACTUAL_V25_BOUND_SEVEN_FAMILY_PRODUCT_NO_PHYSICAL_QUALIFICATION":
        raise CardError("base seven-family product is not the actual v27 product")
    coverage = base.get("coverage") or {}
    if coverage.get("current_case_count") != 336 or coverage.get("native_alias_cases") != 118:
        raise CardError("base product coverage is not 336 CURRENT / 118 native aliases")
    cards = base.get("family_cards") or {}
    base_card = cards.get("F2")
    if not isinstance(base_card, dict) or base_card.get("schema") != "ds02.stage2.family-card.v27" or base_card.get("family_id") != "F2":
        raise CardError("base product lacks the source-bound F2 card")
    if (base_card.get("task_eligibility") or {}).get("QN") != "UNKNOWN":
        raise CardError("base F2 card grants QN credit")

    v29 = products["v29_catalog"]
    if v29.get("schema") != "ds02.stage2.final-qualification-catalog.v29" or v29.get("status") != "ACTUAL_336_CASE_AUDIT_AND_118_NATIVE_IMPACT_BOUND_NO_SCIENTIFIC_QUALIFICATION":
        raise CardError("v29 catalog is not the actual 336/118 catalog")
    v29_rows = _f2_rows(v29, "v29 catalog")
    native_rows = [row for row in v29_rows if isinstance(row.get("native_omission"), dict)]
    old_count = sum(int(row["native_omission"].get("native_count", 0)) for row in native_rows)
    old_causes = Counter()
    old_screen = Counter()
    source_closure = Counter()
    conversion_scope = Counter()
    for row in native_rows:
        omission = row["native_omission"]
        old_causes.update(omission.get("native_exit_cause_counts") or {})
        source_mass = omission.get("source_visible_mass") or {}
        old_screen[str(source_mass.get("screen", "UNKNOWN"))] += 1
        source_closure[str((omission.get("source_closure") or {}).get("status", "UNKNOWN"))] += 1
        conversion_scope[str(omission.get("conversion_omission", "UNKNOWN"))] += 1
    if old_count != 1078 or old_causes != Counter({"NUMERICAL_POSITION_EXCLUSION": 1078}):
        raise CardError(f"v29 F2 native cause total differs: {old_count}/{dict(old_causes)}")

    v30 = products["v30_catalog"]
    if v30.get("schema") != "ds02.stage2.task-scope-catalog.v30" or v30.get("status") != "ACTUAL_V29_TASK_SCOPE_INDEX_WITH_QN_QE_QI_UNKNOWN":
        raise CardError("v30 task-scope catalog is not the actual product")
    v30_rows = _f2_rows(v30, "v30 task-scope catalog")
    if any((row.get("error_qualification") or {}).get("QN") != "UNKNOWN" for row in v30_rows):
        raise CardError("v30 F2 rows grant QN credit")

    identity = products["native_identity_audit"]
    if identity.get("schema") != "ds02.stage2.native-identity-audit.v2" or identity.get("native_id_count") != 1328:
        raise CardError("native identity audit is not the 1328-ID product")
    identity_f2 = (identity.get("family_counts") or {}).get("F2")
    if not isinstance(identity_f2, dict) or identity_f2.get("cases") != 48:
        raise CardError("native identity audit lacks all 48 F2 cases")

    impact = products["impact_ledger"]
    impact_coverage = impact.get("coverage") or {}
    if impact.get("schema") != "ds02.stage2.omission-impact-ledger.v2" or impact.get("status") != "IMPACT_LEDGER_SOURCE_CLOSED_WITH_FATE_AND_DYNAMICS_UNKNOWN":
        raise CardError("impact ledger status is not the source-closed UNKNOWN product")
    if impact_coverage.get("case_count") != 118 or (impact_coverage.get("family_counts") or {}).get("F2") != 48:
        raise CardError("impact ledger does not cover all 48 F2 native cases")

    coarse = products["root105_report"]
    if coarse.get("schema") != "ds02.stage2.f2.coarse-canary-native-qa.v1" or coarse.get("status") != "COMPLETED_F2_COARSE_CANARY_NATIVE_IDENTITY_MOTIVE_QA":
        raise CardError("ROOT105 coarse report is not completed native QA")
    generated = coarse.get("generated_particles") or {}
    if generated.get("fluid_count") != 27750 or abs(finite(generated.get("massfluid_kg"), "ROOT105 MassFluid") - 0.000681472) > 1e-15:
        raise CardError("ROOT105 source-owner initial fluid axis differs")
    fluid_blocks = generated.get("fluid_blocks")
    if not isinstance(fluid_blocks, list) or len(fluid_blocks) != 3 or any(int(block.get("count", -1)) != 9250 for block in fluid_blocks):
        raise CardError("ROOT105 does not expose the expected three source-MK blocks")
    native_identity = coarse.get("native_identity") or {}
    coarse_rows = native_identity.get("rows")
    if not isinstance(coarse_rows, list) or len(coarse_rows) != 153:
        raise CardError("ROOT105 native identity count differs from 153")
    coarse_motives = Counter(str(row.get("motive")) for row in coarse_rows)
    coarse_mk = Counter(str(row.get("mk")) for row in coarse_rows)
    if coarse_motives != Counter({"position": 153}):
        raise CardError(f"ROOT105 motive counts are not all position: {dict(coarse_motives)}")
    initial_mass = finite(generated["massfluid_kg"], "ROOT105 MassFluid") * int(generated["fluid_count"])
    lower_mass = sum(finite(row.get("initial_mass_kg"), "ROOT105 native initial mass") for row in coarse_rows)
    lower_fraction = lower_mass / initial_mass
    if abs(initial_mass - 18.910848) > 1e-12 or abs(lower_fraction - 0.005513513513513513) > 1e-12:
        raise CardError("ROOT105 whole-initial mass screen differs")

    access = products["access_provenance"]
    if access.get("schema") != "ds02.stage2.product-access-provenance.v1" or access.get("status") != "ACTUAL_V28_V30_METADATA_PROVENANCE_NO_REDISTRIBUTION_DETERMINATION":
        raise CardError("product-access provenance is not the actual UNKNOWN-bound product")
    boundary = access.get("access_boundary") or {}
    if boundary.get("redistribution") != "UNKNOWN_NOT_ESTABLISHED; legal review and artifact policy are outside this sidecar":
        raise CardError("access provenance no longer keeps redistribution UNKNOWN")

    pending = manifest.get("pending_root111")
    if not isinstance(pending, dict) or pending.get("status") != "PENDING_GUARDED_EXECUTION" or pending.get("scientific_credit") != "NONE_UNTIL_COMPLETED_RECEIPT":
        raise CardError("ROOT111 pending status is not conservative")
    return {
        "schema": SCHEMA,
        "status": "PREPARED_F2_ADDITIVE_CARD_ROOT111_PENDING",
        "family_id": "F2",
        "card_lineage": {
            "role": "additive F2 reconciliation sidecar; existing seven-family product remains authoritative",
            "base_product_schema": base.get("schema"),
            "base_f2_card_schema": base_card.get("schema"),
            "base_product": stat_ref(paths["v27_product"], "v27 seven-family product"),
            "base_manifest": stat_ref(paths["v27_manifest"], "v27 product manifest"),
            "base_receipt": stat_ref(paths["v27_receipt"], "v27 product receipt"),
        },
        "current336_and_118": {
            "current_case_count": 336,
            "f2_current_case_count": 48,
            "native_alias_case_count": 118,
            "native_alias_id_count": 1328,
            "f2_historical_native_id_count": old_count,
            "f2_historical_native_causes": dict(old_causes),
            "f2_historical_mass_screen_case_counts": dict(old_screen),
            "f2_source_closure_statuses": dict(source_closure),
            "f2_conversion_source_scope": dict(conversion_scope),
            "all_qi_qn_qe": "UNKNOWN",
            "native_identity_source": "existing v29/v30/impact JSON only; no new native decode",
        },
        "f2_source_owner_initial_axis": {
            "status": "SOURCE_CLOSED_INITIAL_AXIS_ONLY",
            "initial_fluid_count": 27750,
            "massfluid_kg": 0.000681472,
            "whole_initial_mass_kg": initial_mass,
            "three_source_mk_blocks": fluid_blocks,
            "native153_lower_bound_mass_kg": lower_mass,
            "native153_lower_bound_fraction_whole_initial": lower_fraction,
            "native153_motive_counts": dict(coarse_motives),
            "native153_count_by_mk": dict(coarse_mk),
            "physical_owner_continuity": "UNKNOWN",
            "physical_fate_or_legal_flux": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "screen_gate_fraction": 0.003,
            "screen_result": "ABOVE_FROZEN_UNKNOWN_MASS_SCREEN",
        },
        "root111_stream": {
            "status": "PENDING_GUARDED_EXECUTION",
            "planned_case_key": CASE_KEY,
            "planned_frames": 401,
            "planned_native_read": True,
            "execution_credit": "NONE_UNTIL_COMPLETED_RECEIPT",
            "decoder_import_fix": "V4 registered direct-converter module before dataclass execution",
            "active_frame_stream_result": "UNKNOWN_PENDING_ROOT111",
            "physical_fate": "UNKNOWN",
            "dynamics": "UNKNOWN",
        },
        "task_eligibility": {
            "source_role_mass_bookkeeping": "ELIGIBLE_SOURCE_CLOSED_METADATA",
            "native_motive_identity": "ELIGIBLE_SOURCE_VISIBLE_118_CASE_SCOPE",
            "finite_field_and_saved_bracket_diagnostics": "ELIGIBLE_WHERE_EXISTING_ROW_IS_SOURCE_CLOSED",
            "ROOT105_coarse_saved_active_observer": "PENDING_ROOT111",
            "physical_destination": "UNKNOWN",
            "legal_outflow_or_spill": "UNKNOWN",
            "continuous_event_time": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "qualification_credit": "NONE",
        },
        "failure_and_censoring": {
            "historical_f2_native_source_closure": "47_FULL_PROBE_SOURCE_CLOSED; 1_FULL_NATIVE_SOURCE_CLOSED",
            "native153_identity": "position-only source-visible exclusion; fate remains UNKNOWN",
            "missing_mass_lower_bound_is_dynamical_error_bound": False,
            "saved_brackets_are_continuous_event_times": False,
            "hidden_recrossings": "UNKNOWN",
            "conversion_implementation_filtering": "UNKNOWN_FOR_47; UNKNOWN_NOT_BOUND_BY_CONVERTER_IMPLEMENTATION_FOR_ONE",
            "ROOT111_failure_or_pending_scope": "V4 request pending; no stream credit",
        },
        "access_and_permissions": {
            "metadata_json_read": "OBSERVED_READ_ONLY",
            "H5_BI4_PartOut_raw_solver": "FORBIDDEN_TO_THIS_WORKER",
            "internal_workspace_access": boundary.get("internal_workspace_access", "UNKNOWN"),
            "external_access": boundary.get("external_access", "UNKNOWN"),
            "redistribution": boundary.get("redistribution", "UNKNOWN"),
            "license_determination": "UNKNOWN_NOT_ESTABLISHED_BY_THIS_CARD",
            "dependency_versions": "REFER_TO_BOUND_PRODUCT_ACCESS_PROVENANCE",
        },
        "source": {key: stat_ref(path, key) for key, path in paths.items()},
        "claim_boundary": {
            "product_completion": "NOT_CLAIMED",
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "dynamics": "UNKNOWN",
        },
    }


def audit(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest_path = require_json(str(manifest_path), "F2 family-card manifest")
    result = derive(manifest_path)
    atomic_json(output_path, result)
    return {"schema": result["schema"], "status": result["status"], "f2_current_cases": result["current336_and_118"]["f2_current_case_count"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(audit(args.manifest, args.output), sort_keys=True))
    except Exception as exc:
        print(f"F2 family-card v1 failed: {exc}", file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

