#!/usr/bin/env python3
"""Verify a namespace330 V4 catalog against its bound lifecycle plan.

The first independent checker for the namespace product only checked the
catalog's own hashes and carried a stale, fixed coverage label.  This checker
joins every catalog row to the lifecycle plan and evidence registry named by
the catalog itself.  Coverage counts are calculated from those rows, and the
native proof is joined by exact ``physical_case_id`` with its per-case fields.

Only bounded JSON metadata is read.  No trajectory, H5, BI4, raw array, or
other scientific payload is opened.  Qualification remains unknown and the
historical alias remains an explicit unresolved identity.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location(
    "namespace330_scoped_v4_for_dynamic_verify",
    SCRIPT_DIR / "ds_data02_stage2_namespace330_scoped_v4.py",
)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover
    raise ImportError("namespace330 V4 source is unavailable")
_V4 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_V4)


SCHEMA = "ds02.stage2.namespace330.scoped-proof-catalog.v4.independent-verification.v2"
MAX_METADATA_BYTES = int(_V4.MAX_METADATA_BYTES)
UNKNOWN_QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


class Namespace330V4DynamicVerificationError(ValueError):
    """The product or its bound metadata evidence is stale or inconsistent."""


def _read_json(path: Path, role: str) -> dict[str, Any]:
    try:
        return _V4._read_json(path, role)
    except Exception as error:
        raise Namespace330V4DynamicVerificationError(str(error)) from error


def _sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise Namespace330V4DynamicVerificationError(f"metadata source is not a regular file: {path}")
    if path.stat().st_size > MAX_METADATA_BYTES:
        raise Namespace330V4DynamicVerificationError(
            f"metadata source exceeds bound ({MAX_METADATA_BYTES} bytes): {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fail(message: str) -> None:
    raise Namespace330V4DynamicVerificationError(message)


def _expect(label: str, observed: Any, expected: Any) -> None:
    if observed != expected:
        _fail(f"{label} differs: observed={observed!r}, expected={expected!r}")


def _source_refs(catalog: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    values = catalog.get("source_inputs")
    if not isinstance(values, list):
        _fail("catalog source_inputs is missing")
    refs: dict[str, Mapping[str, Any]] = {}
    for ref in values:
        if not isinstance(ref, Mapping) or not isinstance(ref.get("role"), str):
            _fail("malformed catalog source input")
        role = str(ref["role"])
        if role in refs:
            _fail(f"duplicate catalog source role: {role}")
        if not isinstance(ref.get("path"), str) or not isinstance(ref.get("file_sha256"), str):
            _fail(f"source role lacks path/SHA: {role}")
        refs[role] = ref
    return refs


def _bound_path(ref: Mapping[str, Any], override: Path | None, role: str) -> Path:
    path = Path(str(ref["path"])).expanduser()
    if override is not None and override.expanduser().resolve() != path.resolve():
        _fail(f"{role} override is not the path bound by the catalog")
    observed = _sha(path)
    _expect(f"{role} file SHA", observed, ref.get("file_sha256"))
    return path


def _alias_identity(plan_alias: Any) -> str:
    if plan_alias == "NONE":
        return "NONE"
    if plan_alias == "HISTORICAL_ALIAS_REVIEW_REQUIRED":
        return "UNKNOWN_IDENTITY"
    _fail(f"unsupported lifecycle alias state: {plan_alias!r}")
    return "UNKNOWN_IDENTITY"  # pragma: no cover


def _native_rows(value: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = value.get("newly_bound_cases")
    if not isinstance(rows, list):
        # The current native proof uses this explicit list.  Do not search
        # arbitrary nested metadata: that could attach aggregate rows.
        return []
    result: list[Mapping[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("physical_case_id"), str):
            _fail("native proof contains a malformed per-case row")
        result.append(row)
    return result


def _native_expected(row: Mapping[str, Any]) -> dict[str, Any]:
    categories = row.get("native_cause_categories")
    if categories is not None:
        if not isinstance(categories, list) or not all(
            isinstance(item, str) and item for item in categories
        ):
            _fail(f"native categories are malformed for {row.get('physical_case_id')}")
        categories_value: list[str] | None = sorted(set(categories))
    else:
        # A scalar native_cause is a real producer field.  It must remain in
        # native_exit_cause; it is not silently rewritten as a category list.
        categories_value = None
    cause = row.get("native_exit_cause", row.get("native_cause"))
    if cause is None:
        cause = "UNKNOWN"
    if not isinstance(cause, str) or not cause:
        _fail(f"native cause is malformed for {row.get('physical_case_id')}")
    join = row.get("saved_frame_join")
    if join is not None and not isinstance(join, Mapping):
        _fail(f"native saved_frame_join is malformed for {row.get('physical_case_id')}")
    saved_frames = row.get("saved_frame_matches")
    if saved_frames is None and isinstance(join, Mapping):
        saved_frames = join.get("saved_frame_matches")
    count = row.get("target_fluid_identity_count", row.get("fluid_identity_count"))
    exact_join = row.get("exact_join_rows")
    return {
        "status": "COMPLETED",
        "native_exit_cause": cause,
        "native_cause_categories": categories_value,
        "target_fluid_identity_count": count,
        "saved_frame_matches": saved_frames,
        "exact_join_rows": exact_join,
    }


def _native_observed(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": row.get("status"),
        "native_exit_cause": row.get("native_exit_cause"),
        "native_cause_categories": row.get("native_cause_categories"),
        "target_fluid_identity_count": row.get("target_fluid_identity_count"),
        "saved_frame_matches": row.get("saved_frame_matches"),
        "exact_join_rows": row.get("exact_join_rows"),
    }


def _check_case(plan_row: Mapping[str, Any], catalog_row: Mapping[str, Any]) -> dict[str, Any]:
    case_id = plan_row.get("physical_case_id")
    if not isinstance(case_id, str):
        _fail("plan contains a case without physical_case_id")
    _expect(f"case {case_id} current_index", catalog_row.get("current_index"), plan_row.get("current_index"))
    _expect(f"case {case_id} family_id", catalog_row.get("family_id"), plan_row.get("family_id"))
    _expect(f"case {case_id} canonical identity", catalog_row.get("canonical_case_id"), case_id)

    saved = catalog_row.get("saved_mask")
    if not isinstance(saved, Mapping):
        _fail(f"case {case_id} lacks saved_mask")
    _expect(f"case {case_id} saved coverage", saved.get("actual_saved_mask_coverage"),
            plan_row.get("actual_saved_mask_coverage"))
    _expect(f"case {case_id} lifecycle status", saved.get("lifecycle_status"), plan_row.get("status"))
    _expect(f"case {case_id} scientific credit", saved.get("scientific_credit"),
            plan_row.get("scientific_credit"))
    _expect(f"case {case_id} attempt lineage", saved.get("attempt_lineage"),
            plan_row.get("attempt_lineage"))
    expected_saved_status = "ACTUAL_COVERED" if plan_row.get("actual_saved_mask_coverage") else "NOT_OBSERVED"
    _expect(f"case {case_id} saved-mask status", saved.get("status"), expected_saved_status)

    identity = catalog_row.get("identity")
    if not isinstance(identity, Mapping):
        _fail(f"case {case_id} lacks identity evidence")
    _expect(f"case {case_id} alias identity", identity.get("historical_alias_status"),
            _alias_identity(plan_row.get("historical_alias")))
    _expect(f"case {case_id} canonical_not_replaced_by_alias",
            identity.get("canonical_not_replaced_by_alias"), True)

    access = catalog_row.get("source_access")
    if not isinstance(access, Mapping):
        _fail(f"case {case_id} lacks source access evidence")
    for key in ("audit_row_bound", "lifecycle_row_bound", "v26_row_bound",
                "historical_alias_is_not_source_fallback"):
        _expect(f"case {case_id} source evidence {key}", access.get(key), True)
    current_roles = access.get("current_roles")
    if not isinstance(current_roles, Mapping) or not isinstance(current_roles.get("trajectory"), Mapping):
        _fail(f"case {case_id} lacks trajectory source evidence")
    _expect(f"case {case_id} trajectory binding", current_roles["trajectory"].get("path"),
            plan_row.get("trajectory_path"))

    physical = catalog_row.get("physical")
    if not isinstance(physical, Mapping):
        _fail(f"case {case_id} lacks physical metadata")
    _expect(f"case {case_id} dynamical impact", physical.get("dynamics"),
            plan_row.get("dynamical_impact"))
    _expect(f"case {case_id} physical fate", physical.get("physical_fate"),
            plan_row.get("physical_fate"))
    _expect(f"case {case_id} qualification", catalog_row.get("qualification"), UNKNOWN_QUALIFICATION)
    _expect(f"case {case_id} qualification credit", catalog_row.get("qualification_credit"), "NONE")

    return {
        "canonical_case_id": case_id,
        "current_index": plan_row.get("current_index"),
        "family_id": plan_row.get("family_id"),
        "saved_mask_status": saved.get("lifecycle_status"),
        "actual_saved_mask_coverage": saved.get("actual_saved_mask_coverage"),
        "historical_alias_status": identity.get("historical_alias_status"),
        "source_evidence": "EXACT_CURRENT_AUDIT_LIFECYCLE_V26_JOIN",
        "qualification": dict(UNKNOWN_QUALIFICATION),
    }


def verify_namespace330_v4_dynamic(
    output_dir: Path | str,
    *,
    plan_path: Path | str | None = None,
    registry_path: Path | str | None = None,
) -> dict[str, Any]:
    """Verify one catalog using only its own bound plan/registry references."""
    output = Path(output_dir).expanduser()
    # This validates catalog/request canonical hashes and their artifact join,
    # while all plan/registry joins below are independently checked here.
    _V4.load_namespace330_scoped_v4(output)
    catalog = _read_json(output / "namespace330-scoped-v4-catalog.json", "V4 catalog")
    request = _read_json(output / "namespace330-scoped-v4-source-request.json", "V4 request")
    if request.get("source_inputs") != catalog.get("source_inputs"):
        _fail("request/catalog source_inputs differ")
    if request.get("input_summary") != catalog.get("input_summary"):
        _fail("request/catalog input_summary differ")
    if catalog.get("qualification") != UNKNOWN_QUALIFICATION or request.get("qualification") != UNKNOWN_QUALIFICATION:
        _fail("qualification was promoted")

    refs = _source_refs(catalog)
    plan_ref = refs.get("typed_lifecycle_registry")
    registry_ref = refs.get("lifecycle_evidence_registry")
    if plan_ref is None or registry_ref is None:
        _fail("catalog does not bind both lifecycle plan and evidence registry")
    bound_plan = _bound_path(plan_ref, Path(plan_path).expanduser() if plan_path else None,
                             "typed lifecycle plan")
    bound_registry = _bound_path(registry_ref, Path(registry_path).expanduser() if registry_path else None,
                                  "lifecycle evidence registry")
    plan = _read_json(bound_plan, "typed lifecycle plan")
    registry = _read_json(bound_registry, "lifecycle evidence registry")
    if plan.get("schema") != "ds02.stage2.typed-lifecycle-continuation-plan.v4":
        _fail("bound lifecycle plan schema is unsupported")
    if registry.get("schema") != "ds02.stage2.typed-lifecycle-evidence-registry.v4":
        _fail("bound lifecycle registry schema is unsupported")

    # Re-hash every declared bounded metadata input.  No path in a case row is
    # opened; the trajectory/raw/H5 paths stay provenance-only.
    checked_sources = []
    for role, ref in refs.items():
        path = Path(str(ref["path"])).expanduser()
        observed = _sha(path)
        _expect(f"source input {role} SHA", observed, ref.get("file_sha256"))
        checked_sources.append({"role": role, "path": str(path), "file_sha256": observed,
                                "bytes": path.stat().st_size})

    # The plan's own current and registry refs must agree with the catalog's
    # source graph.  This prevents a fresh count from being paired with an old
    # CURRENT/audit identity.
    current_ref = refs.get("CURRENT336")
    audit_ref = refs.get("scientific_audit_v23")
    if current_ref is None or audit_ref is None:
        _fail("catalog lacks CURRENT336/scientific audit source refs")
    _expect("plan current path", plan.get("current_catalog", {}).get("path"), current_ref.get("path"))
    _expect("plan current SHA", plan.get("current_catalog", {}).get("sha256"), current_ref.get("file_sha256"))
    _expect("plan registry path", plan.get("evidence_registry", {}).get("path"), registry_ref.get("path"))
    _expect("plan registry SHA", plan.get("evidence_registry", {}).get("sha256"), registry_ref.get("file_sha256"))
    _expect("registry current ref", registry.get("current"),
            {"path": current_ref.get("path"), "sha256": current_ref.get("file_sha256")})
    _expect("registry audit ref", registry.get("audit"),
            {"path": audit_ref.get("path"), "sha256": audit_ref.get("file_sha256")})
    if plan.get("inventory_scope", {}).get("source_content_opened") is not False:
        _fail("plan source content policy is not metadata-only")
    if plan.get("source_read_policy", {}).get("native_or_bi4_opened") is not False:
        _fail("plan records native/BI4 content access")

    catalog_rows = catalog.get("cases")
    plan_rows = plan.get("case_records")
    if not isinstance(catalog_rows, list) or not isinstance(plan_rows, list):
        _fail("catalog/plan case rows are missing")
    if len(catalog_rows) != len(plan_rows):
        _fail("catalog/plan case counts differ")
    catalog_by_id = {row.get("canonical_case_id"): row for row in catalog_rows if isinstance(row, Mapping)}
    plan_by_id = {row.get("physical_case_id"): row for row in plan_rows if isinstance(row, Mapping)}
    if len(catalog_by_id) != len(catalog_rows) or len(plan_by_id) != len(plan_rows):
        _fail("catalog/plan case identities are missing or duplicated")
    if set(catalog_by_id) != set(plan_by_id):
        _fail("catalog/plan case identity sets differ")
    case_checks = [_check_case(plan_by_id[case_id], catalog_by_id[case_id])
                   for case_id in (row.get("physical_case_id") for row in plan_rows)]

    # Calculate coverage from rows and require the declaration to agree.  No
    # historical count is embedded in this verifier.
    actual_ids = {case_id for case_id, row in plan_by_id.items()
                  if row.get("actual_saved_mask_coverage") is True}
    alias_ids = {case_id for case_id, row in plan_by_id.items()
                 if row.get("historical_alias") != "NONE"}
    unscheduled_ids = {case_id for case_id, row in plan_by_id.items()
                       if row.get("status") == "UNSCHEDULED_EXACT_CURRENT_AUDIT"}
    pending_ids = {case_id for case_id, row in plan_by_id.items()
                   if isinstance(row.get("status"), str) and row.get("status") in {
                       "PENDING_NO_CREDIT", "PENDING", "INCOMPLETE", "FAILED_REQUIRES_NEW_ATTEMPT"
                   }}
    exact_audit_ids = {case_id for case_id, row in plan_by_id.items()
                       if row.get("source_join_status") == "EXACT_CURRENT_AUDIT_METADATA_JOIN"}
    derived_coverage = {
        "actual_saved_mask_cases": len(actual_ids),
        "current_cases": len(plan_rows),
        "exact_current_audit_rows": len(exact_audit_ids),
        "failed_requires_new_attempt_cases": sum(
            row.get("status") == "FAILED_REQUIRES_NEW_ATTEMPT" for row in plan_rows
        ),
        "historical_alias_unresolved": len(alias_ids),
        "incomplete_or_mismatched": sum(
            row.get("source_join_status") not in {
                "EXACT_CURRENT_AUDIT_METADATA_JOIN", "SEPARATE_HISTORICAL_ALIAS_UNRESOLVED"
            } for row in plan_rows
        ),
        "pending_no_credit_cases": len(pending_ids),
        "physical_or_scientific_credit_cases": sum(
            row.get("scientific_credit") not in {"NONE", "NONE_PHYSICAL"} for row in plan_rows
        ),
        "remaining_exact_unscheduled_cases": len(unscheduled_ids),
    }
    _expect("plan declared coverage", plan.get("coverage"), derived_coverage)

    # The registry is the second independent source of saved-mask evidence.
    producers = registry.get("producers")
    if not isinstance(producers, list):
        _fail("registry producers are missing")
    registry_case_to_producer: dict[str, str] = {}
    producer_ids: set[str] = set()
    for producer in producers:
        if not isinstance(producer, Mapping) or not isinstance(producer.get("producer_id"), str):
            _fail("malformed registry producer")
        producer_id = str(producer["producer_id"])
        if producer_id in producer_ids:
            _fail(f"duplicate registry producer: {producer_id}")
        producer_ids.add(producer_id)
        if producer.get("status") != "COMPLETED":
            _fail(f"registry producer is not completed: {producer_id}")
        case_ids = producer.get("case_ids")
        if not isinstance(case_ids, list) or not case_ids or any(not isinstance(case_id, str) for case_id in case_ids):
            _fail(f"registry producer has malformed case_ids: {producer_id}")
        for case_id in case_ids:
            if case_id in registry_case_to_producer:
                _fail(f"registry case is attached to multiple producers: {case_id}")
            registry_case_to_producer[case_id] = producer_id
    if set(registry_case_to_producer) != actual_ids:
        _fail("registry saved-mask case union differs from lifecycle plan")
    for case_id in actual_ids:
        plan_row = plan_by_id[case_id]
        lineage = plan_row.get("attempt_lineage")
        if not isinstance(lineage, list) or not lineage:
            _fail(f"saved case lacks attempt lineage: {case_id}")
        for item in lineage:
            if not isinstance(item, Mapping):
                _fail(f"malformed attempt lineage: {case_id}")
            producer_id = item.get("producer_id")
            if registry_case_to_producer.get(case_id) != producer_id:
                _fail(f"registry producer mismatch: {case_id}")
            producer = next(p for p in producers if p.get("producer_id") == producer_id)
            # Registry v4 producers do not uniformly repeat the attempt id:
            # some batch entries carry it in the lifecycle plan only.  When
            # present, it is an additional exact join; absence is not a
            # license to attach another producer because case membership and
            # the plan lineage are still checked above.
            if "attempt_id" in producer:
                _expect(f"registry attempt for {case_id}", producer.get("attempt_id"), item.get("attempt_id"))

    # Exact native joins.  A row with a scalar native_cause keeps that scalar
    # in native_exit_cause; only an explicit producer category list populates
    # native_cause_categories.
    native_ref = refs.get("native_proof")
    native_rows: list[Mapping[str, Any]] = []
    native_path: Path | None = None
    if native_ref is not None:
        native_path = _bound_path(native_ref, None, "native proof")
        native_rows = _native_rows(_read_json(native_path, "native proof"))
    native_by_id: dict[str, Mapping[str, Any]] = {}
    for row in native_rows:
        case_id = str(row["physical_case_id"])
        if case_id in native_by_id:
            _fail(f"duplicate native proof row: {case_id}")
        native_by_id[case_id] = row
    if native_by_id.keys() - catalog_by_id.keys():
        _fail("native proof contains a case outside CURRENT")
    native_matches = 0
    for case_id, catalog_row in catalog_by_id.items():
        observed = catalog_row.get("native_proof_observation")
        if not isinstance(observed, Mapping):
            _fail(f"case {case_id} lacks native proof observation")
        if case_id in native_by_id:
            expected = _native_expected(native_by_id[case_id])
            native_matches += 1
            _expect(f"native {case_id} fields", _native_observed(observed), expected)
            _expect(f"native {case_id} source row count", observed.get("matching_case_row_count"), 1)
            sources = observed.get("source_file_sha256s")
            _expect(f"native {case_id} source SHA list", sources, [native_ref.get("file_sha256")] if native_ref else [])
            scopes = catalog_row.get("source_access", {}).get("native_proof_scopes")
            if not isinstance(scopes, list) or len(scopes) != 1:
                _fail(f"native {case_id} source scope is not exact")
            _expect(f"native {case_id} scope SHA", scopes[0].get("file_sha256"), native_ref.get("file_sha256"))
        else:
            _expect(f"native {case_id} status", observed.get("status"), "UNKNOWN_NO_EXACT_CASE_ROW")
            _expect(f"native {case_id} matching row count", observed.get("matching_case_row_count"), 0)
            _expect(f"native {case_id} source SHA list", observed.get("source_file_sha256s"), [])
            _expect(f"native {case_id} scopes", catalog_row.get("source_access", {}).get("native_proof_scopes"), [])
    if native_ref is None and native_matches:
        _fail("native observations exist without a native source binding")
    expected_native_summary = catalog.get("input_summary", {}).get("native")
    if not isinstance(expected_native_summary, Mapping):
        _fail("catalog native input summary is missing")
    _expect("native proof count", expected_native_summary.get("proof_count"), int(native_ref is not None))
    _expect("native matching count", expected_native_summary.get("matching_case_rows"), native_matches)
    _expect("native unmatched count", expected_native_summary.get("unmatched_case_rows"), 0)
    _expect("native unscoped count", expected_native_summary.get("unscoped_top_level_proofs"), 0)
    mass_refs = [role for role in refs if role.startswith("mass_proof")]
    mass_summary = catalog.get("input_summary", {}).get("mass")
    if not isinstance(mass_summary, Mapping):
        _fail("catalog mass input summary is missing")
    _expect("mass proof count", mass_summary.get("proof_count"), len(mass_refs))
    _expect("mass matching count", mass_summary.get("matching_case_rows"), 0)

    return {
        "schema": SCHEMA,
        "status": "VERIFIED_METADATA_ONLY_DYNAMIC_COVERAGE",
        "catalog_sha256": catalog.get("sha256"),
        "request_sha256": request.get("sha256"),
        "request_id": request.get("request_id"),
        "plan": {"path": str(bound_plan), "file_sha256": plan_ref.get("file_sha256"),
                 "schema": plan.get("schema"), "status": plan.get("status")},
        "registry": {"path": str(bound_registry), "file_sha256": registry_ref.get("file_sha256"),
                     "producer_count": len(producers), "completed_case_count": len(registry_case_to_producer)},
        "coverage": derived_coverage,
        "plan_declared_coverage": dict(plan.get("coverage", {})),
        "family_counts": dict(catalog.get("family_counts", {})),
        "case_count_checked": len(case_checks),
        "case_checks": case_checks,
        "native": {"proof_file_rows": len(native_rows), "catalog_matching_case_rows": native_matches,
                    "source_sha256": native_ref.get("file_sha256") if native_ref else None},
        "mass": {"proof_file_count": len(mass_refs), "catalog_matching_case_rows": 0},
        "qualification": dict(UNKNOWN_QUALIFICATION),
        "read_scope": {"small_metadata_only": True, "payload_opened": False,
                        "trajectory_h5_opened": False, "bi4_opened": False,
                        "raw_arrays_opened": False, "aggregate_fallback": False,
                        "qualification_credit": "NONE"},
        "source_inputs_checked": checked_sources,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--plan", type=Path,
                        help="optional path; it must equal the catalog's bound plan path")
    parser.add_argument("--registry", type=Path,
                        help="optional path; it must equal the catalog's bound registry path")
    parser.add_argument("--verification-output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = verify_namespace330_v4_dynamic(args.output, plan_path=args.plan,
                                                 registry_path=args.registry)
        if args.verification_output is not None:
            target = args.verification_output.expanduser()
            if target.exists() or target.is_symlink():
                raise Namespace330V4DynamicVerificationError(f"refusing to overwrite: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
                              encoding="utf-8")
        print(json.dumps(report, sort_keys=True))
    except (OSError, json.JSONDecodeError, Namespace330V4DynamicVerificationError,
            _V4.Namespace330ScopedV4Error) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
