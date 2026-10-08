#!/usr/bin/env python3
"""Build additive F3/F6 family-card reconciliation metadata.

This worker consumes only already-produced JSON reports.  It binds the
source-closed F3 initial owner/support audits (ROOT102/ROOT104) and the F6
generated-semantics/owner audit (ROOT103) to the existing v27 family product.
It deliberately keeps the 336 CURRENT identities, native omission ledger,
license/access boundary, and all scientific qualification fields unchanged.
No H5, BI4, PartOut, VTK, raw solver tree, or solver is opened by this worker.
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


SCHEMA = "ds02.stage2.f3-f6.family-card.v1"
MANIFEST_SCHEMA = "ds02.stage2.f3-f6.family-card.manifest.v1"
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".bi4", ".obi4", ".bi2", ".bi1"}


class CardError(ValueError):
    """Raised when a source-bound JSON product is not closed."""


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


def equal_float(value: Any, expected: float, label: str, *, tolerance: float = 1e-12) -> float:
    actual = finite(value, label)
    if abs(actual - expected) > tolerance:
        raise CardError(f"{label} differs: {actual!r} != {expected!r}")
    return actual


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
    manifest = read_json(path, "F3/F6 family-card manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise CardError("F3/F6 family-card manifest schema differs")
    source_entries = manifest.get("source_refs")
    if not isinstance(source_entries, list) or not source_entries:
        raise CardError("F3/F6 family-card manifest has no source references")
    paths: dict[str, Path] = {}
    products: dict[str, dict[str, Any]] = {}
    for item in source_entries:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
            raise CardError("malformed F3/F6 family-card source reference")
        key = item["key"]
        if key in paths:
            raise CardError(f"duplicate source key: {key}")
        source = require_json(item.get("path"), key)
        expected = item.get("sha256")
        actual = sha256_file(source)
        if expected != actual:
            raise CardError(f"{key} SHA differs from manifest")
        paths[key] = source
        products[key] = read_json(source, key)
    return manifest, paths, products


def _family_rows(catalog: dict[str, Any], family: str) -> list[dict[str, Any]]:
    rows = catalog.get("cases")
    if not isinstance(rows, list):
        raise CardError("v29 catalog has no case list")
    selected = [row for row in rows if isinstance(row, dict) and (row.get("current") or {}).get("family_id") == family]
    if len(selected) != 48:
        raise CardError(f"v29 catalog has {len(selected)} {family} rows, expected 48")
    return selected


def _native_accounting(catalog: dict[str, Any], family: str) -> dict[str, Any]:
    rows = _family_rows(catalog, family)
    native_rows = [row for row in rows if row.get("native_omission") is not None]
    causes: Counter[str] = Counter()
    motives: Counter[str] = Counter()
    native_ids = 0
    case_keys: list[str] = []
    for row in native_rows:
        omission = row["native_omission"]
        if not isinstance(omission, dict):
            raise CardError(f"{family} native omission is malformed")
        native_count = int(omission.get("native_count", -1))
        if native_count < 0:
            raise CardError(f"{family} native count is invalid")
        native_ids += native_count
        causes.update({str(k): int(v) for k, v in (omission.get("native_exit_cause_counts") or {}).items()})
        motives[str(omission.get("native_motive", "UNKNOWN"))] += native_count
        case_keys.append(str(row.get("case_key")))
        dimensions = row.get("qualification_dimensions") or {}
        q = dimensions.get("error_qualification") or {}
        if any(q.get(name) != "UNKNOWN" for name in ("QI", "QN", "QE")):
            raise CardError(f"{family} v29 row grants qualification credit")
    return {
        "current_case_count": len(rows),
        "native_case_count": len(native_rows),
        "native_id_count": native_ids,
        "native_exit_cause_counts": dict(causes),
        "native_motive_counts": dict(motives),
        "native_case_keys": case_keys,
        "physical_fate": "UNKNOWN",
        "legal_flux": "UNKNOWN",
        "dynamics": "UNKNOWN",
    }


def _validate_base(products: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    base = products["v27_product"]
    if base.get("schema") != "ds02.stage2.final-family-product.v27" or base.get("status") != "PREPARED_ACTUAL_V25_BOUND_SEVEN_FAMILY_PRODUCT_NO_PHYSICAL_QUALIFICATION":
        raise CardError("base seven-family product is not actual v27")
    coverage = base.get("coverage") or {}
    if coverage.get("current_case_count") != 336 or coverage.get("native_alias_cases") != 118 or coverage.get("native_alias_ids") != 1328:
        raise CardError("base v27 coverage is not 336 CURRENT / 118 aliases / 1328 IDs")
    family_counts = coverage.get("family_counts") or {}
    if family_counts != {f"F{i}": 48 for i in range(1, 8)}:
        raise CardError("base v27 family counts are not seven groups of 48")
    cards = base.get("family_cards") or {}
    for family in ("F3", "F6"):
        card = cards.get(family)
        if not isinstance(card, dict) or card.get("schema") != "ds02.stage2.family-card.v27" or card.get("family_id") != family:
            raise CardError(f"base v27 lacks source card for {family}")
        eligibility = card.get("task_eligibility") or {}
        if any(eligibility.get(name) != "UNKNOWN" for name in ("QI", "QN", "QE", "physical_fate", "dynamical_impact")):
            raise CardError(f"base {family} card grants scientific qualification")
    return base, cards


def _validate_catalogs(products: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    catalog = products["v29_catalog"]
    if catalog.get("schema") != "ds02.stage2.final-qualification-catalog.v29" or catalog.get("status") != "ACTUAL_336_CASE_AUDIT_AND_118_NATIVE_IMPACT_BOUND_NO_SCIENTIFIC_QUALIFICATION":
        raise CardError("v29 catalog is not the actual source-closed catalog")
    coverage = catalog.get("coverage") or {}
    if coverage.get("current_cases") != 336 or coverage.get("audit_native_intersection") != 118:
        raise CardError("v29 coverage is not 336/118")
    if not coverage.get("all_qn_qe_qi_unknown"):
        raise CardError("v29 coverage no longer keeps QI/QN/QE UNKNOWN")
    impact = products["impact_ledger"]
    if impact.get("schema") != "ds02.stage2.omission-impact-ledger.v2" or impact.get("status") != "IMPACT_LEDGER_SOURCE_CLOSED_WITH_FATE_AND_DYNAMICS_UNKNOWN":
        raise CardError("impact ledger is not source-closed UNKNOWN")
    impact_coverage = impact.get("coverage") or {}
    if impact_coverage.get("case_count") != 118 or impact_coverage.get("full_source_case_count") != 118:
        raise CardError("impact ledger does not cover all 118 cases")
    if impact_coverage.get("family_counts") != {"F2": 48, "F4": 22, "F6": 48}:
        raise CardError("impact ledger family coverage differs")
    if impact_coverage.get("native_cause_counts") != {
        "NUMERICAL_DENSITY_EXCLUSION": 51,
        "NUMERICAL_POSITION_EXCLUSION": 1277,
    }:
        raise CardError("impact ledger native cause accounting differs from the 1328-ID closure")
    return catalog, impact


def _f3_card(products: dict[str, dict[str, Any]], paths: dict[str, Path], base_card: dict[str, Any]) -> dict[str, Any]:
    gencase = products["f3_gencase_report"]
    support = products["f3_support_report"]
    if gencase.get("schema") != "ds02.stage2.f3.s2.commensurate-dp003-gencase.v1" or gencase.get("status") != "COMPLETED_F3_S2_COMMENSURATE_DP003_GENCASE":
        raise CardError("ROOT102 is not the completed F3 commensurate GenCase report")
    if support.get("schema") != "ds02.stage2.f3.s2.dp003.initial-support-qa.v1" or support.get("status") != "COMPLETED_F3_S2_DP003_INITIAL_SUPPORT_SOURCE_CLOSED":
        raise CardError("ROOT104 is not the completed F3 initial support report")
    physical_case = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
    if gencase.get("physical_case_id") != physical_case or support.get("physical_case_id") != physical_case:
        raise CardError("F3 ROOT102/104 physical case identities differ")
    owner = (support.get("source") or {}).get("continuous_owner") or {}
    if owner.get("low_m") != [-0.45, -0.09, 0.0] or owner.get("size_m") != [0.9, 0.18, 0.09] or owner.get("tank_size_m") != [0.9, 0.18, 0.51]:
        raise CardError("F3 source owner dimensions differ")
    equal_float(owner.get("mass_kg"), 14.58, "F3 continuous owner mass")
    candidate = support.get("candidate") or {}
    if candidate.get("actual_counts_authoritative") is not True or candidate.get("preflight_estimate_is_not_count_evidence") is not True:
        raise CardError("F3 ROOT104 does not mark actual XML counts authoritative")
    actual = candidate.get("generated_xml_summary_actual") or {}
    counts = actual.get("counts") or {}
    if int(counts.get("fluid", -1)) != 540000:
        raise CardError("F3 actual XML fluid count differs")
    equal_float(actual.get("sample_fluid_mass_kg"), 14.58, "F3 actual XML sample mass")
    if abs(finite(actual.get("massfluid_kg"), "F3 actual XML MassFluid") - 0.000027) > 1e-15:
        raise CardError("F3 actual XML MassFluid differs")
    vtk_fluid = ((support.get("vtk_support") or {}).get("fluid") or {})
    axes = vtk_fluid.get("axis_summary") or {}
    axis_counts = {axis: int((axes.get(axis) or {}).get("unique_count", -1)) for axis in ("x", "y", "z")}
    if axis_counts != {"x": 300, "y": 60, "z": 30}:
        raise CardError(f"F3 actual support axis counts differ: {axis_counts}")
    if int(vtk_fluid.get("point_count", -1)) != 540000 or int(vtk_fluid.get("idp_count", -1)) != 540000:
        raise CardError("F3 VTK support identity count differs")
    owner_relation = vtk_fluid.get("owner_relation") or {}
    if int(owner_relation.get("outside_closed_count", -1)) != 0:
        raise CardError("F3 support has outside owner points")
    gencase_scope = gencase.get("scope") or {}
    support_scope = support.get("scope") or {}
    if gencase_scope.get("solver_started") is not False or support_scope.get("solver_started") is not False:
        raise CardError("F3 ROOT102/104 unexpectedly started a solver")
    status = support.get("scientific_status") or {}
    if any(status.get(name) != "UNKNOWN" for name in ("QI", "QN", "QE", "physical_fate", "dynamics")):
        raise CardError("F3 support report grants scientific credit")
    prior = (gencase.get("prior_support_summary") or {}).get("historical_dp0048_hardfail_preserved")
    if prior is not True:
        raise CardError("F3 ROOT102 does not preserve historical dp0048 failure")
    return {
        "family_id": "F3",
        "base_card_schema": base_card.get("schema"),
        "physical_case_id": physical_case,
        "source_closed_initial_owner": {
            "low_m": owner["low_m"],
            "size_m": owner["size_m"],
            "tank_size_m": owner["tank_size_m"],
            "density_kg_m3": 1000.0,
            "mass_kg": 14.58,
            "semantic_role": "initial continuous owner contract only; not a trajectory or dynamics claim",
        },
        "root102_gencase": {
            "status": gencase["status"],
            "actual_generated_sample_mass_kg": finite(actual.get("sample_fluid_mass_kg"), "F3 sample mass"),
            "actual_fluid_count": int(counts["fluid"]),
            "historical_dp0048_hardfail_preserved": True,
            "solver_started": False,
            "trajectory_h5_read": bool(gencase_scope.get("trajectory_h5_read")),
            "source_binding": stat_ref(paths["f3_gencase_report"], "ROOT102 report"),
            "receipt": stat_ref(paths["f3_gencase_receipt"], "ROOT102 receipt"),
        },
        "root104_initial_support": {
            "status": support["status"],
            "dp_m": finite(actual.get("dp_m"), "F3 actual dp"),
            "actual_support_axis_counts": axis_counts,
            "actual_fluid_count": int(vtk_fluid["point_count"]),
            "idp_count": int(vtk_fluid["idp_count"]),
            "owner_outside_closed_count": int(owner_relation["outside_closed_count"]),
            "actual_counts_authoritative": True,
            "scope": "initial generated support and owner-envelope audit only",
            "source_binding": stat_ref(paths["f3_support_report"], "ROOT104 report"),
            "receipt": stat_ref(paths["f3_support_receipt"], "ROOT104 receipt"),
        },
        "task_eligibility": {
            "owner_control_geometry_metadata": "ELIGIBLE_SOURCE_CLOSED_INITIAL_AUDIT",
            "saved_frame_artifact": (base_card.get("task_eligibility") or {}).get("saved_frame_artifact", "ELIGIBLE_LIMITED_SAVED_FRAME_DIAGNOSTICS"),
            "source_role_mass_bookkeeping": "ELIGIBLE_SOURCE_ROLE_BOOKKEEPING_ONLY",
            "material_region_event_transport": "EXCLUDED_UNSUPPORTED",
            "continuous_owner_dynamics_transfer": "UNKNOWN",
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "dynamics": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "qualification_credit": "NONE",
        },
        "failure_and_scope": {
            "historical_fine_grid_failure": "PRESERVED_FROM_ROOT102_PRIOR_SUPPORT; no rescaling or reclassification",
            "full_trajectory_or_solver_qualification": "UNKNOWN_NOT_MEASURED_HERE",
            "initial_support_is_dynamics": False,
        },
    }


def _f6_card(products: dict[str, dict[str, Any]], paths: dict[str, Path], base_card: dict[str, Any]) -> dict[str, Any]:
    owner = products["f6_owner_report"]
    semantics = products["f6_mass_semantics"]
    if owner.get("schema") != "ds02.stage2.f6.fluid-owner-authority-audit.v3" or owner.get("status") != "COMPLETED_F6_FLUID_OWNER_AUTHORITY_XML_SOURCE_PROJECTION_AUDIT":
        raise CardError("ROOT103 is not the completed F6 owner/semantics report")
    authority = owner.get("owner_authority") or {}
    if authority.get("continuous_fluid_owner") != "UNKNOWN_NO_LINKED_CONTINUOUS_OWNER_CONTRACT":
        raise CardError("ROOT103 unexpectedly promotes a continuous fluid owner")
    equal_float(authority.get("physical_body_mass_kg"), 128.0, "F6 ROOT103 body mass")
    if authority.get("body_mass_is_separate") is not True or authority.get("drawbox_volume_or_rho_volume_must_not_be_promoted") is not True:
        raise CardError("F6 ROOT103 mass separation guard is missing")
    rows = owner.get("rows")
    if not isinstance(rows, list) or len(rows) != 6:
        raise CardError("ROOT103 must contain six F6-1/F6-2 grid rows")
    row_summaries: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("continuous_fluid_owner_authority") != "UNKNOWN_NO_LINKED_CONTINUOUS_OWNER_CONTRACT":
            raise CardError("F6 row owner authority is not conservatively UNKNOWN")
        if row.get("drawbox_volume_mass_is_not_owner") is not True:
            raise CardError("F6 row drawbox selector was promoted to owner")
        generated = row.get("generated_particle_summary") or {}
        counts = generated.get("counts") or {}
        body = row.get("body_contract") or {}
        equal_float(body.get("massbody_kg"), 128.0, "F6 row physical body mass")
        row_summaries.append({
            "sentinel_id": row.get("sentinel_id"),
            "grid_id": row.get("grid_id"),
            "physical_case_id": row.get("physical_case_id"),
            "dp_m": finite(row.get("dp_m"), "F6 row dp"),
            "generated_counts": {str(k): int(v) for k, v in counts.items()},
            "massfluid_kg_per_particle": finite(generated.get("massfluid_kg"), "F6 generated MassFluid"),
            "generated_fluid_sample_mass_kg": finite(generated.get("fluid_sample_mass_kg"), "F6 generated fluid sample mass"),
            "body_mass_kg": 128.0,
            "sample_mass_gate": (row.get("fluid_sample") or {}).get("gate"),
            "sample_mass_basis": (row.get("fluid_sample") or {}).get("basis"),
            "owner_authority": "UNKNOWN_NO_LINKED_CONTINUOUS_OWNER_CONTRACT",
        })
    if semantics.get("schema") != "ds02.stage2.sentinel.initial-frame-equivalence.v2.3" or semantics.get("status") != "PASS":
        raise CardError("F6 mass-semantics source is not the completed frame-zero audit")
    mass_semantics = semantics.get("mass_semantics") or {}
    sample_by_type = ((mass_semantics.get("sample_mass") or {}).get("by_type") or {})
    floating = sample_by_type.get("2") or {}
    fluid = sample_by_type.get("3") or {}
    equal_float(floating.get("sample_mass_total_kg"), 256.0, "F6 floating sample mass")
    equal_float(fluid.get("sample_mass_total_kg"), 5120.0, "F6 fluid sample mass")
    bodies = ((mass_semantics.get("physical_rigid_body") or {}).get("bodies") or [])
    if not bodies or any(abs(finite(body.get("massbody_kg"), "F6 physical body mass") - 128.0) > 1e-12 for body in bodies):
        raise CardError("F6 physical body mass semantics differ")
    interpretation = str(mass_semantics.get("interpretation", ""))
    if "separate quantities" not in interpretation or "floating-particle sum" not in interpretation:
        raise CardError("F6 mass-semantics source does not preserve mass separation")
    scope = semantics.get("scope") or {}
    if scope.get("solver_started") is not False:
        raise CardError("F6 mass-semantics audit unexpectedly started solver")
    return {
        "family_id": "F6",
        "base_card_schema": base_card.get("schema"),
        "generated_owner_semantics": {
            "continuous_fluid_owner": "UNKNOWN_NO_LINKED_CONTINUOUS_OWNER_CONTRACT",
            "reason": authority.get("reason"),
            "drawbox_is_discrete_selector_only": True,
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "dynamics": "UNKNOWN",
        },
        "root103_generated_rows": {
            "status": owner["status"],
            "scope": "six XML source-projection/generated-summary rows; not a continuous-owner or dynamics proof",
            "rows": row_summaries,
            "source_binding": stat_ref(paths["f6_owner_report"], "ROOT103 report"),
            "receipt": stat_ref(paths["f6_owner_receipt"], "ROOT103 receipt"),
        },
        "mass_semantics": {
            "floating_sample_mass_total_kg": 256.0,
            "physical_rigid_body_mass_kg": 128.0,
            "fluid_sample_mass_total_kg": 5120.0,
            "interpretation": "native sample weights and XML physical rigid-body mass are separate quantities; never substitute one for the other",
            "source_binding": stat_ref(paths["f6_mass_semantics"], "F6 frame-zero mass semantics"),
            "qualification": "frame-zero mass/identity semantics only; QI/QN/QE UNKNOWN",
        },
        "task_eligibility": {
            "owner_control_geometry_metadata": "ELIGIBLE_SOURCE_CLOSED_METADATA_REFERENCE_ONLY",
            "native_cause_alias_join": (base_card.get("task_eligibility") or {}).get("native_cause_alias_join", "ELIGIBLE_EXACT_118_ALIAS_CASES"),
            "saved_frame_artifact": (base_card.get("task_eligibility") or {}).get("saved_frame_artifact", "ELIGIBLE_LIMITED_SAVED_FRAME_DIAGNOSTICS"),
            "source_role_mass_bookkeeping": "ELIGIBLE_SOURCE_ROLE_BOOKKEEPING_ONLY",
            "continuous_fluid_owner": "UNKNOWN",
            "material_region_event_transport": "EXCLUDED_UNSUPPORTED",
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "dynamics": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "qualification_credit": "NONE",
        },
        "failure_and_scope": {
            "sample_mass_grid_comparisons": "diagnostic only; no continuous-owner or QN claim",
            "rigid_body_vs_floating_sample": "kept separate explicitly",
            "continuous_owner_source_authority": "UNKNOWN_NO_LINKED_CONTINUOUS_OWNER_CONTRACT",
        },
    }


def derive(manifest_path: Path) -> dict[str, Any]:
    manifest, paths, products = load_manifest(manifest_path)
    required = {
        "v27_product", "v27_manifest", "v27_receipt", "v29_catalog", "impact_ledger", "access_provenance",
        "f3_gencase_report", "f3_gencase_receipt", "f3_support_report", "f3_support_receipt",
        "f6_owner_report", "f6_owner_receipt", "f6_mass_semantics",
    }
    missing = sorted(required - set(products))
    if missing:
        raise CardError(f"manifest lacks required source keys: {', '.join(missing)}")
    base, cards = _validate_base(products)
    catalog, impact = _validate_catalogs(products)
    f3_accounting = _native_accounting(catalog, "F3")
    f6_accounting = _native_accounting(catalog, "F6")
    if f3_accounting["native_id_count"] != 0 or f6_accounting["native_id_count"] != 199:
        raise CardError("F3/F6 native exclusion accounting differs from v29")
    access = products["access_provenance"]
    if access.get("schema") != "ds02.stage2.product-access-provenance.v1" or access.get("status") != "ACTUAL_V28_V30_METADATA_PROVENANCE_NO_REDISTRIBUTION_DETERMINATION":
        raise CardError("access provenance is not the actual UNKNOWN-bound product")
    boundary = access.get("access_boundary") or {}
    if not str(boundary.get("redistribution", "")).startswith("UNKNOWN_NOT_ESTABLISHED"):
        raise CardError("redistribution boundary is no longer UNKNOWN")
    f3 = _f3_card(products, paths, cards["F3"])
    f6 = _f6_card(products, paths, cards["F6"])
    return {
        "schema": SCHEMA,
        "status": "PREPARED_F3_F6_ADDITIVE_CARD_METADATA_ONLY",
        "families": ["F3", "F6"],
        "lineage": {
            "role": "additive reconciliation sidecar; v27 seven-family product remains authoritative",
            "base_product_schema": base.get("schema"),
            "base_product": stat_ref(paths["v27_product"], "v27 seven-family product"),
            "base_manifest": stat_ref(paths["v27_manifest"], "v27 product manifest"),
            "base_receipt": stat_ref(paths["v27_receipt"], "v27 product receipt"),
            "old_products_modified": False,
        },
        "current336_identity_preservation": {
            "current_case_count": 336,
            "family_counts": {f"F{i}": 48 for i in range(1, 8)},
            "native_alias_case_count": 118,
            "native_alias_id_count": 1328,
            "identity_source": "v27 product exact CURRENT inventory; no identities added, removed, or rewritten",
            "native_accounting_source": stat_ref(paths["v29_catalog"], "v29 native accounting catalog"),
            "impact_source": stat_ref(paths["impact_ledger"], "118-case impact ledger"),
            "all_qi_qn_qe": "UNKNOWN",
        },
        "native_exclusion_accounting": {
            "F3": f3_accounting,
            "F6": f6_accounting,
            "all118_ledger_coverage": (impact.get("coverage") or {}),
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "dynamics": "UNKNOWN",
            "mass_lower_bounds_are_not_dynamical_error_bounds": True,
        },
        "family_cards": {"F3": f3, "F6": f6},
        "access_and_permissions": {
            "metadata_json_read": "OBSERVED_READ_ONLY",
            "H5_BI4_PartOut_VTK_raw_solver": "FORBIDDEN_TO_THIS_WORKER",
            "internal_workspace_access": boundary.get("internal_workspace_access", "UNKNOWN"),
            "external_access": boundary.get("external_access", "UNKNOWN"),
            "redistribution": boundary.get("redistribution", "UNKNOWN"),
            "license_determination": "UNKNOWN_NOT_ESTABLISHED_BY_THIS_SIDECAR",
            "dependency_versions": "REFER_TO_BOUND_PRODUCT_ACCESS_PROVENANCE",
        },
        "read_policy": {
            "json_sources_only": True,
            "hdf5_read": False,
            "bi4_read": False,
            "partout_read": False,
            "vtk_read": False,
            "raw_solver_opened": False,
            "solver_started": False,
            "model_invoked": False,
            "old_products_modified": False,
        },
        "claim_boundary": {
            "product_completion": "NOT_CLAIMED",
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "dynamics": "UNKNOWN",
            "F3_initial_owner_or_300x60x30_support": "initial/source-support evidence only; not dynamics or solver qualification",
            "F6_body128_vs_floating_sample256": "separate mass semantics; not a physical transfer or dynamics claim",
        },
        "source": {key: stat_ref(path, key) for key, path in paths.items()},
    }


def audit(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest_path = require_json(str(manifest_path), "F3/F6 family-card manifest")
    result = derive(manifest_path)
    atomic_json(output_path, result)
    return {"schema": result["schema"], "status": result["status"], "families": result["families"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(audit(args.manifest, args.output), sort_keys=True))
    except Exception as exc:
        print(f"F3/F6 family-card v1 failed: {exc}", file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
