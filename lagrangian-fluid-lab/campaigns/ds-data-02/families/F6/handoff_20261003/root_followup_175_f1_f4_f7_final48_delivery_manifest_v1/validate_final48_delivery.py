#!/usr/bin/env python3
"""Read-only validator for the F6-owned F1/F4/F7 final-48 roster.

The validator reads only JSON/XML/XMF/PNG evidence named by the roster and
the four immutable membership authorities.  It never opens H5/BI4/CSV/DAT/
VTK payloads, writes a checkpoint, changes a registry, or launches work.

By default it verifies current metadata/PNG/XMF file existence, size and the
stored SHA-256 closure.  ``--rehash`` recomputes SHA-256 for every unique
allowed product reference (XMF and PNG are explicitly permitted evidence for
this handoff).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
ROSTER = HERE / "final48-delivery-roster.json"
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
HANDOFF = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003"
CHECKPOINT = HANDOFF / "ROOT_LIVE_RESUMPTION_CHECKPOINT_218.json"
ROOT1232 = HANDOFF / (
    "root_stage1_source150151_F1_F7_actual_frozen8_subset_visual24_final48_"
    "F4_three_missing_source24_preserved_checkpoint_1232/"
    "MAIN_ACTUAL_FIRST24_F1_F7_SUBSET48.json"
)
ROOT1238 = HANDOFF / (
    "root_stage1_source152169_F4_actual_frozen8_delivery24_subset48_"
    "F6_actual24_subset47_one_pending_checkpoint_1238/"
    "MAIN_ACTUAL_FIRST24_F4_F6_SUBSET_CURRENT_ACCEPTED.json"
)
ROOT1093 = HANDOFF / (
    "root_stage1_source178_F5_M095T080_actual984_full801_actual34contacts_"
    "ninekeys_first8_each_family_independent_visual_acceptance_1093/"
    "FIRST8_PER_FAMILY_STAGE1_SUBSET56.json"
)
ROOT1258 = HANDOFF / (
    "root_stage1_source198_F5_M094T095_actual1161_personal34contacts_ninekeys_"
    "full801QI_plan_roles_prefix17_visual_acceptance_1258/"
    "full336-current281-actual-wrapper-contract-role-aware-registration-"
    "progress-index.json"
)

ALLOWED = {".json", ".xml", ".xmf", ".png"}
FORBIDDEN = {".h5", ".bi4", ".csv", ".dat", ".vtk", ".vtu", ".out", ".gif", ".pvsm"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FAMILIES = ("F1", "F4", "F7")


class ValidationError(Exception):
    pass


def load(path: Path) -> Any:
    if not path.is_file():
        raise ValidationError(f"missing metadata file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check_sha(path: Path, expected: str, *, rehash: bool) -> None:
    if not path.is_file():
        raise ValidationError(f"missing referenced evidence: {path}")
    if path.suffix.lower() in FORBIDDEN or path.suffix.lower() not in ALLOWED:
        raise ValidationError(f"non-permitted evidence reference: {path}")
    if not isinstance(expected, str) or not SHA256_RE.fullmatch(expected):
        raise ValidationError(f"invalid SHA-256 in roster for {path}")
    actual_size = path.stat().st_size
    # ``bytes`` is checked by the caller because ref metadata carries it.
    if rehash and sha256(path) != expected:
        raise ValidationError(f"SHA-256 drift: {path}")


def decision_sha(path_text: str) -> str:
    path = Path(path_text)
    if path.suffix.lower() != ".json":
        raise ValidationError(f"decision is not JSON: {path}")
    if not path.is_file():
        raise ValidationError(f"missing decision: {path}")
    return sha256(path)


def ref_dicts(value: Any) -> list[dict[str, Any]]:
    """Yield nested roster references without interpreting payload strings."""
    out: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if isinstance(value.get("path"), str) and value["path"].startswith("/"):
            out.append(value)
        for child in value.values():
            out.extend(ref_dicts(child))
    elif isinstance(value, list):
        for child in value:
            out.extend(ref_dicts(child))
    return out


def refs_in_category(case: dict[str, Any], category: str) -> list[dict[str, Any]]:
    value = case["product_metadata"].get(category)
    return value if isinstance(value, list) else []


def expected_memberships() -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    d1232 = load(ROOT1232)
    d1238 = load(ROOT1238)
    d1093 = load(ROOT1093)
    first8: dict[str, list[dict[str, Any]]] = {}
    first24: dict[str, list[dict[str, Any]]] = {}
    for family in ("F1", "F7"):
        first8[family] = d1232["families"][family]["actual_first8"]
        first24[family] = d1232["families"][family]["actual_first24"]
    rows = d1238["families"]["F4"]["rows_actual_source_order"]
    frozen_ids = d1238["families"]["F4"]["frozen_actual_first8_physical_case_ids"]
    by_id = {row["physical_case_id"]: row for row in rows}
    first8["F4"] = [by_id[physical_id] for physical_id in frozen_ids]
    first24["F4"] = rows
    frozen8 = {
        family: d1093["cases_by_family"][family]
        for family in FAMILIES
    }
    return first8, first24, frozen8


def accepted_final48() -> dict[str, list[dict[str, Any]]]:
    checkpoint = load(CHECKPOINT)
    if checkpoint.get("checkpoint") != 218:
        raise ValidationError("checkpoint authority is not checkpoint 218")
    result = {family: [] for family in FAMILIES}
    for path_text in checkpoint.get("accepted_decisions", []):
        decision_path = Path(path_text)
        decision = load(decision_path)
        family = decision.get("family_id")
        if family in result:
            result[family].append({
                "path": str(decision_path),
                "sha256": sha256(decision_path),
                "family_id": family,
                "case_id": decision.get("case_id"),
                "physical_case_id": decision.get("physical_case_id"),
            })
    return result


def authority_checks(roster: dict[str, Any]) -> None:
    expected = {
        "checkpoint218": CHECKPOINT,
        "root1093_frozen8": ROOT1093,
        "root1232_f1_f7_first24": ROOT1232,
        "root1238_f4_first24": ROOT1238,
        "root1258_role_aware_native_index": ROOT1258,
    }
    authority = roster.get("authority")
    if not isinstance(authority, dict):
        raise ValidationError("roster authority block missing")
    for key, path in expected.items():
        ref = authority.get(key)
        if not isinstance(ref, dict) or Path(ref.get("path", "")) != path:
            raise ValidationError(f"authority path mismatch: {key}")
        if ref.get("bytes") != path.stat().st_size:
            raise ValidationError(f"authority byte count drift: {key}")
        if ref.get("sha256") != sha256(path):
            raise ValidationError(f"authority SHA drift: {key}")


def validate_product_ref(ref: dict[str, Any], *, rehash: bool) -> None:
    path_text = ref.get("path")
    if not isinstance(path_text, str) or not path_text.startswith("/"):
        raise ValidationError("product reference path is not absolute")
    path = Path(path_text)
    if path.suffix.lower() in FORBIDDEN or path.suffix.lower() not in ALLOWED:
        raise ValidationError(f"forbidden/non-metadata product path: {path}")
    if not path.is_file():
        raise ValidationError(f"product path missing: {path}")
    if not isinstance(ref.get("bytes"), int) or ref["bytes"] != path.stat().st_size:
        raise ValidationError(f"product byte count drift: {path}")
    check_sha(path, ref.get("sha256"), rehash=rehash)
    declared = ref.get("declared_sha256")
    if declared is not None and declared != ref.get("sha256"):
        raise ValidationError(f"declared SHA mismatch in roster: {path}")
    if declared is not None and ref.get("declared_sha256_matches_current") is not True:
        raise ValidationError(f"declared SHA was not verified: {path}")


def validate_role_ref(ref: dict[str, Any], *, rehash: bool) -> None:
    """Validate a Root1258 role-evidence pointer (which has no byte field)."""
    path_text = ref.get("path")
    if not isinstance(path_text, str) or not path_text.startswith("/"):
        raise ValidationError("Root1258 role evidence path is not absolute")
    path = Path(path_text)
    if path.suffix.lower() in FORBIDDEN or path.suffix.lower() not in ALLOWED:
        raise ValidationError(f"forbidden Root1258 role evidence: {path}")
    if not path.is_file():
        raise ValidationError(f"missing Root1258 role evidence: {path}")
    expected = ref.get("sha256")
    if expected is not None:
        check_sha(path, expected, rehash=rehash)


def validate_case(
    family: str,
    case: dict[str, Any],
    final_by_id: dict[str, dict[str, Any]],
    expected8: list[dict[str, Any]],
    expected24: list[dict[str, Any]],
    frozen8: list[dict[str, Any]],
    native_role_row: dict[str, Any],
    *,
    rehash: bool,
) -> None:
    physical_id = case.get("physical_case_id")
    if not isinstance(physical_id, str) or not physical_id:
        raise ValidationError(f"{family}: case has no physical_case_id")
    if case.get("family_id") != family or case.get("physical_family") != family:
        raise ValidationError(f"{family}/{physical_id}: physical family mismatch")
    if case.get("source_assignment_family") != "F6":
        raise ValidationError(f"{family}/{physical_id}: source assignment is not F6")

    role = case.get("role_aware_native_registration")
    if not isinstance(role, dict):
        raise ValidationError(f"{family}/{physical_id}: Root1258 native role missing")
    identity = role.get("source_index_row_identity", {})
    for key in ("family_id", "physical_case_id", "case_id"):
        if identity.get(key) != native_role_row.get(key):
            raise ValidationError(f"{family}/{physical_id}: Root1258 identity mismatch: {key}")
    if role.get("accepted_decision_top_condition_sha256") != native_role_row.get("accepted_decision_top_condition_sha256"):
        raise ValidationError(f"{family}/{physical_id}: accepted top condition role drift")
    if role.get("accepted_decision_top_hash_role") != native_role_row.get("accepted_decision_top_hash_role"):
        raise ValidationError(f"{family}/{physical_id}: accepted top hash role drift")
    expected_scope = native_role_row.get("native_request_scope")
    actual_scope = role.get("native_request_scope")
    if actual_scope != expected_scope:
        raise ValidationError(f"{family}/{physical_id}: actual native scope drift")
    if role.get("native_scope_sha256_is_missing") != (
        not isinstance(expected_scope, dict) or expected_scope.get("sha256") is None
    ):
        raise ValidationError(f"{family}/{physical_id}: missing native scope was filled or mislabelled")
    for ref in ref_dicts(actual_scope):
        validate_role_ref(ref, rehash=rehash)

    accepted = case.get("accepted_decision")
    if not isinstance(accepted, dict):
        raise ValidationError(f"{family}/{physical_id}: accepted decision missing")
    accepted_path = accepted.get("path")
    if not isinstance(accepted_path, str):
        raise ValidationError(f"{family}/{physical_id}: accepted decision path missing")
    expected = final_by_id.get(physical_id)
    if expected is None:
        raise ValidationError(f"{family}/{physical_id}: absent from checkpoint218 F48")
    if accepted_path != expected["path"] or accepted.get("sha256") != expected["sha256"]:
        raise ValidationError(f"{family}/{physical_id}: accepted decision is not checkpoint218 authority")
    if decision_sha(accepted_path) != accepted["sha256"]:
        raise ValidationError(f"{family}/{physical_id}: accepted decision SHA drift")
    decision = load(Path(accepted_path))
    for key in ("family_id", "case_id", "physical_case_id"):
        if decision.get(key) != case.get(key):
            raise ValidationError(f"{family}/{physical_id}: decision {key} mismatch")

    scope = case.get("physical_scope", {})
    if scope.get("scope_roles_are_distinct") is not True:
        raise ValidationError(f"{family}/{physical_id}: scope separation missing")
    status = case.get("delivery_status", {})
    required_status = {
        "numerical_precision_status": "not accepted",
        "q_n": False,
        "q_e": False,
        "case_credit": 0,
        "new_acceptance": False,
    }
    for key, value in required_status.items():
        if status.get(key) != value:
            raise ValidationError(f"{family}/{physical_id}: status {key} mismatch")
    pm = case.get("product_metadata", {})
    if pm.get("science_payload_refs_omitted") is not True:
        raise ValidationError(f"{family}/{physical_id}: scientific payload was not marked omitted")
    if not isinstance(pm.get("receipt_roles"), dict):
        raise ValidationError(f"{family}/{physical_id}: receipt role separation missing")
    for category in ("native", "typed", "xmf", "render"):
        refs = refs_in_category(case, category)
        if not refs:
            raise ValidationError(f"{family}/{physical_id}: empty product category {category}")
        for ref in refs:
            validate_product_ref(ref, rehash=rehash)
    xmf_paths = [Path(ref["path"]) for ref in refs_in_category(case, "xmf")]
    if not any(path.suffix.lower() == ".xmf" for path in xmf_paths):
        raise ValidationError(f"{family}/{physical_id}: case.xmf missing")
    if not any(path.name == "manifest.json" for path in xmf_paths):
        raise ValidationError(f"{family}/{physical_id}: XMF manifest missing")
    render_paths = [Path(ref["path"]).name for ref in refs_in_category(case, "render")]
    if not any("report" in name.lower() for name in render_paths):
        raise ValidationError(f"{family}/{physical_id}: render report missing")
    png = pm.get("png", {})
    contacts = png.get("contact_sheets", [])
    keys = png.get("key_frames", [])
    if not contacts or not keys:
        raise ValidationError(f"{family}/{physical_id}: PNG entry metadata incomplete")
    for ref in list(contacts) + list(keys) + list(png.get("other_png", [])):
        validate_product_ref(ref, rehash=rehash)
        if Path(ref["path"]).suffix.lower() != ".png":
            raise ValidationError(f"{family}/{physical_id}: non-PNG in PNG block")
    counts = png.get("counts", {})
    if counts.get("contact_sheets") != len(contacts) or counts.get("key_frames") != len(keys):
        raise ValidationError(f"{family}/{physical_id}: PNG count block mismatch")

    membership_role = case.get("membership_role")
    evidence = case.get("membership_evidence", {})
    row8 = next((row for row in expected8 if row.get("physical_case_id") == physical_id), None)
    row24 = next((row for row in expected24 if row.get("physical_case_id") == physical_id), None)
    if membership_role == "first8" and (row8 is None or row24 is None):
        raise ValidationError(f"{family}/{physical_id}: first8 case absent from authority rows")
    if membership_role == "first24" and row24 is None:
        raise ValidationError(f"{family}/{physical_id}: first24 case absent from authority rows")
    if membership_role == "final48_only" and row24 is not None:
        raise ValidationError(f"{family}/{physical_id}: final48_only is in first24")
    expected8_decision = row8.get("accepted_visual_decision") if row8 else None
    if family == "F4" and row8:
        expected8_decision = row8.get("actual_visual_decision")
    expected24_decision = None
    if row24:
        expected24_decision = row24.get("accepted_visual_decision") or row24.get("actual_visual_decision")
    for label, actual, expected_ref in (
        ("first8", evidence.get("first8_source_decision"), expected8_decision),
        ("first24", evidence.get("first24_source_decision"), expected24_decision),
    ):
        if expected_ref is None:
            if actual is not None:
                raise ValidationError(f"{family}/{physical_id}: unexpected {label} authority ref")
            continue
        if not isinstance(actual, dict) or actual.get("path") != expected_ref.get("path") or actual.get("sha256") != expected_ref.get("sha256"):
            raise ValidationError(f"{family}/{physical_id}: {label} authority ref mismatch")
    if membership_role == "first8":
        frozen_ref = frozen8[expected8.index(row8)] if row8 in expected8 else None
        if frozen_ref and evidence.get("first8_source_decision") != frozen_ref:
            raise ValidationError(f"{family}/{physical_id}: Root1093 first8 order/ref mismatch")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rehash", action="store_true", help="rehash all unique JSON/XML/XMF/PNG product refs")
    args = parser.parse_args()
    errors: list[str] = []
    try:
        roster = load(ROSTER)
        if roster.get("schema") != "ds02.f6.cross-family-final48-delivery-roster.v1":
            raise ValidationError("unexpected roster schema")
        scope = roster.get("package_scope", {})
        checks = {
            "source_assignment_family": "F6",
            "physical_families": list(FAMILIES),
            "case_credit": 0,
            "new_acceptance": False,
            "precision_status": "视觉检查通过、数值精度未验收",
            "q_n": False,
            "q_e": False,
            "scientific_payload_read": False,
            "scientific_payload_hashed": False,
            "png_visual_review_repeated": False,
            "gemini": False,
            "recursive_delegation": False,
            "checkpoint_not_modified": True,
        }
        for key, expected in checks.items():
            if scope.get(key) != expected:
                raise ValidationError(f"package scope mismatch: {key}")
        if "Root1258 role-aware index" not in scope.get("native_registration_role_source", ""):
            raise ValidationError("package scope does not identify Root1258 native role source")
        authority_checks(roster)
        first8, first24, frozen8 = expected_memberships()
        final = accepted_final48()
        root1258 = load(ROOT1258)
        native_role_rows = {
            (row.get("family_id"), row.get("physical_case_id")): row
            for row in root1258.get("cases", [])
            if isinstance(row, dict)
        }
        for family in FAMILIES:
            fam = roster.get("families", {}).get(family)
            if not isinstance(fam, dict):
                raise ValidationError(f"missing family {family}")
            cases = fam.get("cases", [])
            if len(cases) != 48:
                raise ValidationError(f"{family}: expected 48 cases, got {len(cases)}")
            final_ids = [row["physical_case_id"] for row in final[family]]
            if len(final_ids) != 48 or len(set(final_ids)) != 48:
                raise ValidationError(f"{family}: checkpoint final48 authority is not unique 48")
            case_ids = [case.get("physical_case_id") for case in cases]
            if case_ids != fam.get("final48_physical_case_ids") or case_ids != final_ids:
                raise ValidationError(f"{family}: final48 order/IDs do not match checkpoint authority")
            ids8 = list(fam.get("first8_physical_case_ids", []))
            ids24 = list(fam.get("first24_physical_case_ids", []))
            if len(ids8) != 8 or len(set(ids8)) != 8 or len(ids24) != 24 or len(set(ids24)) != 24:
                raise ValidationError(f"{family}: malformed first8/first24 membership")
            if not set(ids8) < set(ids24) < set(case_ids):
                raise ValidationError(f"{family}: strict subset relation failed")
            expected8_ids = [row["physical_case_id"] for row in first8[family]]
            expected24_ids = [row["physical_case_id"] for row in first24[family]]
            if ids8 != expected8_ids or ids24 != expected24_ids:
                raise ValidationError(f"{family}: first8/first24 authority order mismatch")
            expected_frozen_refs = frozen8[family]
            expected8_decisions = [
                (row.get("accepted_visual_decision") or row.get("actual_visual_decision"))
                for row in first8[family]
            ]
            if [(x.get("path"), x.get("sha256")) for x in expected_frozen_refs] != [
                (x.get("path"), x.get("sha256")) for x in expected8_decisions
            ]:
                raise ValidationError(f"{family}: Root1093 frozen8 does not match first8 authority")
            final_by_id = {row["physical_case_id"]: row for row in final[family]}
            for case in cases:
                native_role_row = native_role_rows.get((family, case.get("physical_case_id")))
                if native_role_row is None:
                    raise ValidationError(f"{family}/{case.get('physical_case_id')}: missing Root1258 row")
                validate_case(
                    family,
                    case,
                    final_by_id,
                    first8[family],
                    first24[family],
                    frozen8[family],
                    native_role_row,
                    rehash=args.rehash,
                )
        print(json.dumps({
            "status": "PASS",
            "schema": roster["schema"],
            "families": {family: 48 for family in FAMILIES},
            "strict_subset": "8 < 24 < 48 for F1/F4/F7",
            "checkpoint": 218,
            "rehash": bool(args.rehash),
            "scientific_payload_read_or_hashed": False,
            "case_credit": 0,
            "new_acceptance": False,
        }, ensure_ascii=False, sort_keys=True))
        return 0
    except (ValidationError, KeyError, TypeError, ValueError, OSError) as exc:
        errors.append(str(exc))
    print(json.dumps({"status": "FAIL", "errors": errors}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
