#!/usr/bin/env python3
"""Build an additive, JSON-only F2 family-card identity-closure reconciliation sidecar.

The seven-family product remains the catalog authority.  This sidecar binds
the existing F2 card to the already-produced 336/118 ledgers and the ROOT105
coarse canary and the historical/supplemented native identity products so a consumer can distinguish CURRENT evidence from the new
non-CURRENT canary.  It never opens H5, BI4, PartOut, raw solver output, or a
solver.  The ROOT111 active-frame stream is recorded as pending metadata and
receives no execution or scientific credit before its guarded receipt exists.
The ROOT056 1325-row audit remains historical; ROOT070 is validated as the
separate 1328-row source-closed supplement, with a strict 3-row transition.
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


SCHEMA = "ds02.stage2.f2.family-card.v2"
MANIFEST_SCHEMA = "ds02.stage2.f2.family-card.manifest.v2"
CASE_KEY = "F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_T4_COARSE_CANARY_ROOT_095"
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".bi4", ".obi4", ".bi2", ".bi1"}
REQUIRED_SOURCE_KEYS = {
    "v27_product",
    "v27_manifest",
    "v27_receipt",
    "v29_catalog",
    "v30_catalog",
    "v30_manifest",
    "historical_identity_audit",
    "historical_identity_receipt",
    "supplemented_identity_rows",
    "supplemented_identity_receipt",
    "supplemented_closure_report",
    "supplemented_closure_receipt",
    "impact_ledger",
    "root105_report",
    "access_provenance",
}


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
    missing = REQUIRED_SOURCE_KEYS - set(paths)
    unexpected = set(paths) - REQUIRED_SOURCE_KEYS
    if missing or unexpected:
        raise CardError(
            "family-card manifest source closure differs: "
            f"missing={sorted(missing)} unexpected={sorted(unexpected)}"
        )
    return manifest, paths, products


def _f2_rows(product: dict[str, Any], label: str) -> list[dict[str, Any]]:
    rows = product.get("cases")
    if not isinstance(rows, list):
        raise CardError(f"{label} has no case list")
    selected = [row for row in rows if isinstance(row, dict) and str(row.get("case_key", "")).startswith("F2/")]
    if len(selected) != 48:
        raise CardError(f"{label} has {len(selected)} F2 rows, expected 48")
    return selected


def _completed_receipt(receipt: dict[str, Any], label: str) -> None:
    """Require a completed, source-guarded JSON producer receipt.

    The receipts are evidence of the producer execution only.  They do not
    elevate the resulting numerical exclusions to physical fate or dynamics.
    """
    if receipt.get("schema") != "ds02.execution-receipt.v1":
        raise CardError(f"{label} receipt schema differs")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise CardError(f"{label} receipt is not completed successfully")
    if receipt.get("model_invoked") is True or receipt.get("cfd_invoked") is True:
        raise CardError(f"{label} receipt reports a model/CFD invocation")
    preflight = receipt.get("source_preflight") or {}
    if preflight.get("status") != "PASS_AFTER_RESERVATION":
        raise CardError(f"{label} receipt lacks post-reservation source preflight")


def _stat_binding(product: dict[str, Any], key: str, paths: dict[str, Path], source_key: str) -> None:
    bindings = product.get("source_bindings")
    binding = bindings.get(key) if isinstance(bindings, dict) else None
    if not isinstance(binding, dict):
        raise CardError(f"supplemented identity report lacks {key} binding")
    expected_path = str(paths[source_key])
    if binding.get("path") != expected_path:
        raise CardError(f"supplemented identity {key} path is not the manifest-bound source")
    expected_sha = sha256_file(paths[source_key])
    if binding.get("sha256") != expected_sha:
        raise CardError(f"supplemented identity {key} SHA is not the manifest-bound source")


def _identity_rows(product: dict[str, Any], label: str) -> list[dict[str, Any]]:
    rows = product.get("native_identity_records")
    if not isinstance(rows, list) or len(rows) != 1328:
        raise CardError(f"{label} does not contain exactly 1328 identity rows")
    required = {
        "case_key",
        "family_id",
        "first_missing_bracket_s",
        "first_missing_frame",
        "idp",
        "initial_mass_kg",
        "mk",
        "native_motive",
        "native_motive_code",
        "numerical_cause",
        "partvtk_density_kg_m3",
        "partvtk_position_m",
        "physical_case_id",
        "row_index",
        "type",
        "typed_tag",
        "zone",
    }
    keys: set[tuple[str, int]] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not required.issubset(row):
            raise CardError(f"{label} row {index} lacks the native identity fields")
        if row.get("row_index") != index:
            raise CardError(f"{label} row_index is not contiguous at row {index}")
        case_key = row.get("case_key")
        family = row.get("family_id")
        idp = row.get("idp")
        if not isinstance(case_key, str) or family not in {"F2", "F4", "F6"}:
            raise CardError(f"{label} row {index} has an invalid case/family identity")
        if not isinstance(idp, int) or isinstance(idp, bool):
            raise CardError(f"{label} row {index} has a non-integer Idp")
        if not case_key.startswith(f"{family}/"):
            raise CardError(f"{label} row {index} family/case prefix differs")
        identity_key = (case_key, idp)
        if identity_key in keys:
            raise CardError(f"{label} contains a duplicate case-qualified Idp")
        keys.add(identity_key)
        bracket = row.get("first_missing_bracket_s")
        if not isinstance(bracket, list) or len(bracket) != 2:
            raise CardError(f"{label} row {index} lacks a saved first-missing bracket")
        lo, hi = finite(bracket[0], f"{label} row {index} bracket lower"), finite(bracket[1], f"{label} row {index} bracket upper")
        if lo > hi:
            raise CardError(f"{label} row {index} has an inverted first-missing bracket")
        if finite(row.get("initial_mass_kg"), f"{label} row {index} initial mass") <= 0:
            raise CardError(f"{label} row {index} has non-positive initial mass")
    return rows


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

    historical_identity = products["historical_identity_audit"]
    if historical_identity.get("schema") != "ds02.stage2.native-identity-audit.v2":
        raise CardError("historical native identity audit schema differs")
    if historical_identity.get("status") != "COMPLETED_WITH_CASE_SCOPED_SOURCE_GAPS":
        raise CardError("historical native identity audit status differs")
    if historical_identity.get("native_id_count") != 1325:
        raise CardError("historical native identity audit is not the immutable 1325-ID product")
    historical_f2 = (historical_identity.get("family_counts") or {}).get("F2")
    if not isinstance(historical_f2, dict) or historical_f2.get("cases") != 48 or historical_f2.get("closed") != 47 or historical_f2.get("source_incomplete") != 1:
        raise CardError("historical native identity audit does not preserve the F2 47+1 source gap")
    _completed_receipt(products["historical_identity_receipt"], "historical native identity")

    supplemented = products["supplemented_identity_rows"]
    if supplemented.get("schema") != "ds02.stage2.native-source-identity-development-subset.v2":
        raise CardError("supplemented native identity rows schema differs")
    if supplemented.get("status") != "PASS_FORWARD_STATS_CORRECTION_ORIGINAL_V1_PRESERVED":
        raise CardError("supplemented native identity rows status differs")
    supplemented_summary = supplemented.get("native_source_closed_subset") or {}
    if supplemented_summary.get("case_count") != 118 or supplemented_summary.get("row_count") != 1328:
        raise CardError("supplemented native identity rows are not the 118-case/1328-row product")
    if supplemented_summary.get("family_case_counts") != {"F2": 48, "F4": 22, "F6": 48}:
        raise CardError("supplemented family case counts differ")
    if supplemented_summary.get("family_motive_id_counts") != {"F2:position": 1078, "F4:density": 51, "F6:position": 199}:
        raise CardError("supplemented family motive counts differ")
    if supplemented_summary.get("global_idp_uniqueness") is not False or supplemented_summary.get("identity_key") != "(case_key, Idp); Idp is not globally unique across physical cases":
        raise CardError("supplemented identity key contract differs")
    supplemented_rows = _identity_rows(supplemented, "supplemented native identity")
    supplemented_keys = {(row["case_key"], row["idp"]) for row in supplemented_rows}
    historical_rows = historical_identity.get("cases")
    if not isinstance(historical_rows, list):
        raise CardError("historical native identity audit has no case rows")
    historical_keys: set[tuple[str, int]] = set()
    for case in historical_rows:
        if not isinstance(case, dict):
            raise CardError("historical native identity audit contains a malformed case row")
        native_identity = case.get("native_identity") or {}
        ids = native_identity.get("ids")
        if isinstance(ids, list):
            for item in ids:
                if isinstance(item, dict) and isinstance(item.get("idp"), int):
                    historical_keys.add((str(case.get("case_key")), int(item["idp"])))
    if len(historical_keys) != 1325:
        raise CardError("historical native identity row expansion is not 1325 unique case-qualified IDs")
    supplement_keys = supplemented_keys - historical_keys
    if len(supplement_keys) != 3 or supplement_keys != {
        ("F2/scan-F2-S1-001", 397194),
        ("F2/scan-F2-S1-001", 403829),
        ("F2/scan-F2-S1-001", 404024),
    }:
        raise CardError("supplemented identity does not add the exact three F2-S1 IDs")
    if historical_keys - supplemented_keys:
        raise CardError("supplemented identity dropped a historical case-qualified ID")
    _completed_receipt(products["supplemented_identity_receipt"], "supplemented native identity")

    closure = products["supplemented_closure_report"]
    if closure.get("schema") != "ds02.stage2.f2-s1-native-source-closure-118.v2" or closure.get("status") != "PASS_ACTUAL_118_CASE_SOURCE_CLOSED_WITH_PRIOR_GAP_SPECTRUM_PRESERVED":
        raise CardError("supplemented source-closure report is not the actual source-closed product")
    if closure.get("native_id_count") != 1328 or not isinstance(closure.get("cases"), list) or len(closure["cases"]) != 118:
        raise CardError("supplemented source-closure report does not cover 118 cases/1328 IDs")
    singleton_cases = [case for case in closure["cases"] if isinstance(case, dict) and case.get("case_key") == "F2/scan-F2-S1-001"]
    if len(singleton_cases) != 1:
        raise CardError("supplemented source-closure report lacks the F2-S1 singleton")
    singleton_identity = singleton_cases[0].get("native_identity") or {}
    singleton_ids = singleton_identity.get("ids")
    if singleton_identity.get("id_count") != 3 or not isinstance(singleton_ids, list) or {int(item.get("idp")) for item in singleton_ids if isinstance(item, dict)} != {397194, 403829, 404024}:
        raise CardError("supplemented source-closure report does not bind the exact three F2-S1 IDs")
    closure_boundary = closure.get("claim_boundary") or {}
    physical_fate = closure_boundary.get("physical_fate")
    dynamical_impact = closure_boundary.get("dynamical_impact")
    if not isinstance(physical_fate, str) or not physical_fate.startswith("UNKNOWN") or not isinstance(dynamical_impact, str) or not dynamical_impact.startswith("UNKNOWN"):
        raise CardError("supplemented source-closure report grants physical fate or dynamics")
    _completed_receipt(products["supplemented_closure_receipt"], "supplemented source closure")
    _stat_binding(supplemented, "root064_closure_report", paths, "supplemented_closure_report")
    _stat_binding(supplemented, "root064_closure_receipt", paths, "supplemented_closure_receipt")

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
    if not isinstance(pending, dict) or pending.get("status") not in {"PENDING_GUARDED_EXECUTION", "FAILED_NO_SCIENTIFIC_CREDIT"} or pending.get("scientific_credit") != "NONE_UNTIL_COMPLETED_RECEIPT":
        raise CardError("ROOT111 pending/failed status is not conservative")
    return {
        "schema": SCHEMA,
        "status": "PREPARED_F2_ADDITIVE_CARD_V2_IDENTITY_CLOSED_NO_STREAM_CREDIT",
        "family_id": "F2",
        "card_lineage": {
            "role": "additive F2 reconciliation sidecar; existing seven-family product remains authoritative",
            "base_product_schema": base.get("schema"),
            "base_f2_card_schema": base_card.get("schema"),
            "base_product": stat_ref(paths["v27_product"], "v27 seven-family product"),
            "base_manifest": stat_ref(paths["v27_manifest"], "v27 product manifest"),
            "base_receipt": stat_ref(paths["v27_receipt"], "v27 product receipt"),
            "v1_card_status": "PRESERVED; ROOT112 failure is not rewritten",
            "v1_failure_scope": "ROOT056 was a valid historical 1325-row audit with one F2 source-incomplete case; it was not mutated to appear as 1328",
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
            "native_identity_source": "existing v29/v30/impact JSON plus the source-closed ROOT070 identity supplement; no new native decode",
        },
        "native_identity_closure": {
            "historical_root056": {
                "status": historical_identity.get("status"),
                "native_id_count": historical_identity.get("native_id_count"),
                "f2_cases": historical_f2.get("cases"),
                "f2_closed": historical_f2.get("closed"),
                "f2_source_incomplete": historical_f2.get("source_incomplete"),
                "report": stat_ref(paths["historical_identity_audit"], "historical ROOT056 identity audit"),
                "receipt": stat_ref(paths["historical_identity_receipt"], "historical ROOT056 execution receipt"),
            },
            "supplemented_root070": {
                "status": supplemented.get("status"),
                "native_id_count": supplemented_summary.get("row_count"),
                "case_count": supplemented_summary.get("case_count"),
                "family_case_counts": supplemented_summary.get("family_case_counts"),
                "family_motive_id_counts": supplemented_summary.get("family_motive_id_counts"),
                "report": stat_ref(paths["supplemented_identity_rows"], "supplemented ROOT070 identity rows"),
                "receipt": stat_ref(paths["supplemented_identity_receipt"], "supplemented ROOT070 execution receipt"),
            },
            "f2_s1_supplement": {
                "historical_id_count": len(historical_keys),
                "supplemented_id_count": len(supplemented_keys),
                "added_id_count": len(supplement_keys),
                "case_key": "F2/scan-F2-S1-001",
                "added_idp": sorted(idp for case_key, idp in supplement_keys if case_key == "F2/scan-F2-S1-001"),
                "source_closure_report": stat_ref(paths["supplemented_closure_report"], "supplemented ROOT064 source-closure report"),
                "source_closure_receipt": stat_ref(paths["supplemented_closure_receipt"], "supplemented ROOT064 execution receipt"),
                "native_identity_status": "SOURCE_CLOSED_SINGLETON_ADAPTER_V3",
                "physical_fate": "UNKNOWN_NOT_PROVEN",
                "dynamical_impact": "UNKNOWN; mass visibility is not a dynamics bound",
            },
            "transition": {
                "historical_root056_rows": 1325,
                "supplemented_root070_rows": 1328,
                "supplement_rows": 3,
                "transition_is_set_difference": True,
                "source_closure_is_not_physical_fate": True,
                "converter_initial_filter": "UNKNOWN outside explicit selected producer metadata",
            },
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
            "status": pending.get("status"),
            "planned_case_key": CASE_KEY,
            "planned_frames": 401,
            "planned_native_read": True,
            "execution_credit": "NONE_UNTIL_COMPLETED_RECEIPT",
            "decoder_import_fix": "V4 registered direct-converter module before dataclass execution",
            "active_frame_stream_result": "UNKNOWN_PENDING_ROOT111" if pending.get("status") == "PENDING_GUARDED_EXECUTION" else "FAILED_NO_SCIENTIFIC_CREDIT_ROOT111",
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
            "historical_f2_native_source_closure": "ROOT056 preserved 47 closed + 1 source-incomplete; ROOT070/ROOT064 closes the one case for native identity only",
            "f2_s1_supplement_provenance": "ROOT064 source-closure report and ROOT063 singleton producer/receipt are bound through ROOT070 source_bindings",
            "native153_identity": "position-only source-visible exclusion; fate remains UNKNOWN",
            "missing_mass_lower_bound_is_dynamical_error_bound": False,
            "saved_brackets_are_continuous_event_times": False,
            "hidden_recrossings": "UNKNOWN",
            "conversion_implementation_filtering": "UNKNOWN_FOR_47; UNKNOWN_NOT_BOUND_BY_CONVERTER_IMPLEMENTATION_FOR_ONE",
            "ROOT111_failure_or_pending_scope": "V4 request pending/failed bytes remain separate; no stream credit",
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
        print(f"F2 family-card v2 failed: {exc}", file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
