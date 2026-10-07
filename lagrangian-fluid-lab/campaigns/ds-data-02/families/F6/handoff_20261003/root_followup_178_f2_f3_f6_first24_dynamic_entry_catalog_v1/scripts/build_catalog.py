#!/usr/bin/env python3
"""Build the metadata-only first24 dynamic entry catalog.

This utility reads only JSON/XML/XMF and already published PNG artifacts.  It
does not open solver payloads (H5/BI4/CSV/DAT/VTK) and does not launch jobs.
The output deliberately preserves accepted semantic hashes and actual native
request scopes as separate roles.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys
from typing import Any


INTEGRATION = pathlib.Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics"
)
CAMPAIGN = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02"
HANDOFF = CAMPAIGN / "handoff_20261003"
DATA = pathlib.Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")

F2_MEMBERSHIP = HANDOFF / (
    "root_stage1_source165_F2_authoritative_first8_first24_subset_final48_and_actual24_"
    "visual_delivery_closed_checkpoint_1211/F2-first8-first24-final48-physical-membership-"
    "and-actual24-visual-delivery.json"
)
F3_MEMBERSHIP = HANDOFF / (
    "root_stage1_source157_F3_actual_frozen8_plus16_accepted_delivery_first24_semantic_"
    "native_roles_preserved_checkpoint_1252/MAIN_F3_ACTUAL_FIRST24_DELIVERED_SUBSET_CURRENT37_"
    "FINAL48.json"
)
F46_MEMBERSHIP = HANDOFF / (
    "root_stage1_source152169_F4_actual_frozen8_delivery24_subset48_F6_actual24_subset47_"
    "one_pending_checkpoint_1238/MAIN_ACTUAL_FIRST24_F4_F6_SUBSET_CURRENT_ACCEPTED.json"
)
CURRENT_INDEX = HANDOFF / (
    "root_stage1_source176_assignedF6_actualF2_RX061ROT075_actual1142_full401QI_personal26PNG_"
    "quantified39fluid_visual_acceptance_1268/full336-current285-actual-final48-delivery-"
    "progress-index.json"
)

FROZEN8 = HANDOFF / (
    "root_stage1_source178_F5_M095T080_actual984_full801_actual34contacts_ninekeys_"
    "first8_each_family_independent_visual_acceptance_1093/FIRST8_PER_FAMILY_STAGE1_"
    "SUBSET56.json"
)

ALLOWED_SUFFIXES = {".json", ".xml", ".xmf", ".png"}
FORBIDDEN_SUFFIXES = {
    ".h5",
    ".bi4",
    ".csv",
    ".dat",
    ".vtk",
    ".vtu",
    ".pvsm",
    ".gif",
}


def read_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_ref(raw: str, source: pathlib.Path) -> pathlib.Path:
    candidate = pathlib.Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate
    for root in (source.parent, INTEGRATION, pathlib.Path("/home/jade/Projects/DualSPHysics")):
        resolved = root / candidate
        if resolved.exists():
            return resolved
    return source.parent / candidate


def collect_refs(value: Any, source_key: str = "", output: list[tuple[str, str, str]] | None = None) -> list[tuple[str, str, str]]:
    """Collect path/hash pairs without following or opening the referenced files."""

    if output is None:
        output = []
    if isinstance(value, dict):
        if isinstance(value.get("path"), str) and isinstance(value.get("sha256"), str):
            output.append((value["path"], value["sha256"], source_key or "path_sha256"))
        for key, item in value.items():
            if key.endswith("_path") and isinstance(item, str):
                hash_key = key[:-5] + "_sha256"
                if isinstance(value.get(hash_key), str):
                    output.append((item, value[hash_key], source_key or key))
            # Producers also use direct names such as ``xdmf`` and
            # ``conversion_report`` beside their ``*_sha256`` field.
            if (
                isinstance(item, str)
                and not key.endswith("_sha256")
                and isinstance(value.get(key + "_sha256"), str)
            ):
                output.append((item, value[key + "_sha256"], source_key or key))
        for key, item in value.items():
            collect_refs(item, (source_key + "." + key).strip("."), output)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            collect_refs(item, f"{source_key}[{index}]", output)
    return output


def ref_kind(path: pathlib.Path) -> str:
    return path.suffix.lower().lstrip(".")


def ref_role(path: pathlib.Path, source_keys: set[str]) -> str:
    name = path.name.lower()
    keys = " ".join(source_keys).lower()
    suffix = path.suffix.lower()
    if suffix == ".png":
        if "all_frames" in name or "contact" in keys:
            return "contact_png"
        return "key_png"
    if "manifest" in name or "manifest" in keys:
        return "xmf_manifest"
    if suffix == ".xmf":
        return "xmf_xml"
    if (
        "paraview-full-animation-report" in name
        or "full-render-report" in name
        or "animation_integrity_report" in keys
        or "native_full_render_report" in keys
    ):
        return "render_report"
    if any(token in name or token in keys for token in ("gencase", "prepared-input", "generated_xml", "definition")):
        return "gencase_or_definition"
    if any(token in name or token in keys for token in ("initial_qa", "initial-qa", "frame0", "audit", "qa_report")):
        return "initial_qa_or_audit"
    if "typed" in name or "conversion" in name or "typed" in keys or "conversion" in keys:
        return "typed_receipt_or_report"
    if "native" in name or "native" in keys:
        return "native_receipt_or_report"
    if "owner" in name or "source" in name or "owner" in keys or "source" in keys:
        return "owner_or_source"
    if "render" in name or "render" in keys:
        return "render_receipt"
    return "metadata"


def filtered_ref_records(document: Any, source: pathlib.Path, cache: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Return immutable metadata/P​​NG refs; forbidden payload suffixes are never opened."""

    grouped: dict[str, dict[str, Any]] = {}
    for raw, declared, source_key in collect_refs(document):
        suffix = pathlib.Path(raw).suffix.lower()
        if suffix in FORBIDDEN_SUFFIXES or suffix not in ALLOWED_SUFFIXES:
            continue
        resolved = resolve_ref(raw, source)
        key = str(resolved)
        entry = grouped.setdefault(key, {"path": key, "raw_paths": set(), "declared": set(), "source_keys": set()})
        entry["raw_paths"].add(raw)
        entry["declared"].add(declared)
        entry["source_keys"].add(source_key)

    records: list[dict[str, Any]] = []
    for key in sorted(grouped):
        entry = grouped[key]
        path = pathlib.Path(key)
        if not path.exists() or not path.is_file():
            raise RuntimeError(f"missing allowed evidence path: {path}")
        if len(entry["declared"]) != 1:
            raise RuntimeError(f"conflicting declared hashes for {path}: {entry['declared']}")
        if key not in cache:
            # Only .json/.xml/.xmf/.png reaches this point.
            cache[key] = {"sha256": sha256_file(path), "bytes": path.stat().st_size}
        record = {
            "path": key,
            "kind": ref_kind(path),
            "role": ref_role(path, entry["source_keys"]),
            "declared_sha256": next(iter(entry["declared"])),
            "sha256": cache[key]["sha256"],
            "bytes": cache[key]["bytes"],
            "source_keys": sorted(entry["source_keys"]),
        }
        records.append(record)
    return records


def ref_from_pair(pair: dict[str, Any], source: pathlib.Path, cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
    path = resolve_ref(pair["path"], source)
    if path.suffix.lower() in FORBIDDEN_SUFFIXES or path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise RuntimeError(f"forbidden authority/decision evidence path: {path}")
    if not path.exists():
        raise RuntimeError(f"missing authority/decision evidence: {path}")
    key = str(path)
    if key not in cache:
        cache[key] = {"sha256": sha256_file(path), "bytes": path.stat().st_size}
    actual = cache[key]
    if actual["sha256"] != pair["sha256"]:
        raise RuntimeError(f"declared SHA mismatch for {path}: {pair['sha256']} != {actual['sha256']}")
    return {"path": key, "sha256": actual["sha256"], "bytes": actual["bytes"], "role": "authority_or_decision"}


def render_summary(records: list[dict[str, Any]], expected_frames: int) -> tuple[dict[str, Any], dict[str, Any]]:
    candidates = [r for r in records if r["role"] == "render_report" and r["kind"] == "json"]
    if not candidates:
        raise RuntimeError("no full render report in accepted decision refs")
    chosen = None
    report = None
    for candidate in candidates:
        report = read_json(pathlib.Path(candidate["path"]))
        if report.get("frames") == expected_frames:
            chosen = candidate
            break
    if chosen is None or report is None:
        raise RuntimeError(f"no render report with {expected_frames} frames")
    fields = {}
    for key in (
        "schema",
        "frames",
        "source_frames",
        "all_frames_rendered",
        "actual_times_preserved_exactly",
        "native_identity_axis_preserved",
        "nonfinite_active_states",
        "diagnostic_only",
        "numerical_precision_status",
        "independent_case_increment",
    ):
        if key in report and not isinstance(report[key], (list, dict)):
            fields[key] = report[key]
    return chosen, fields


def safe_native_snapshot(index_row: dict[str, Any], source: pathlib.Path, cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
    scope = index_row.get("native_request_scope")
    snapshot: dict[str, Any] = {
        "present": isinstance(scope, dict),
        "sha256": scope.get("sha256") if isinstance(scope, dict) else None,
        "role": scope.get("role") if isinstance(scope, dict) else None,
        "condition_is_not_inferred_from_accepted_top_or_source_plan": (
            scope.get("condition_is_not_inferred_from_accepted_top_or_source_plan")
            if isinstance(scope, dict)
            else None
        ),
        "accepted_top_condition_sha256": index_row.get("accepted_decision_top_condition_sha256"),
        "declared_source_plan_condition_sha256": index_row.get("declared_source_plan_condition_sha256"),
        "declared_source_definition_sha256": index_row.get("declared_source_definition_sha256"),
        "declared_actual_converter_scope_sha256": index_row.get("declared_actual_converter_scope_sha256"),
        "top_or_render_declared_condition_equals_actual_native_request": index_row.get(
            "top_or_render_declared_condition_equals_actual_native_request"
        ),
        "actual_native_condition_field_true_absence": index_row.get("actual_native_condition_field_true_absence"),
    }
    # Preserve only allowed evidence references from the native-role snapshot.
    if isinstance(scope, dict):
        snapshot["allowed_evidence_refs"] = filtered_ref_records(scope, source, cache)
    else:
        snapshot["allowed_evidence_refs"] = []
    return snapshot


def make_row(family: str, physical_id: str, membership_row: dict[str, Any], decision_pair: dict[str, Any],
             first8: bool, index_row: dict[str, Any], cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
    decision_path = resolve_ref(decision_pair["path"], F2_MEMBERSHIP if family == "F2" else F3_MEMBERSHIP if family == "F3" else F46_MEMBERSHIP)
    decision = read_json(decision_path)
    expected_frames = {"F2": 401, "F3": 836, "F6": 241}[family]
    refs = filtered_ref_records(decision, decision_path, cache)
    # Accepted decisions sometimes carry the manifest as the only XMF entry
    # point.  Read that JSON metadata (never its scientific payload) to bind
    # the producer's own XMF path and SHA as a separate immutable ref.
    manifest_records: list[dict[str, Any]] = []
    for manifest in [r for r in refs if r["role"] == "xmf_manifest"]:
        manifest_records.extend(
            filtered_ref_records(read_json(pathlib.Path(manifest["path"])), pathlib.Path(manifest["path"]), cache)
        )
    by_path: dict[str, dict[str, Any]] = {}
    for record in refs + manifest_records:
        existing = by_path.get(record["path"])
        if existing is None:
            by_path[record["path"]] = record
        else:
            existing["source_keys"] = sorted(set(existing.get("source_keys", [])) | set(record.get("source_keys", [])))
            if existing["sha256"] != record["sha256"] or existing["declared_sha256"] != record["declared_sha256"]:
                raise RuntimeError(f"conflicting producer metadata for {record['path']}")
    refs = [by_path[key] for key in sorted(by_path)]
    render_ref, render_fields = render_summary(refs, expected_frames)
    manifests = [r for r in refs if r["role"] == "xmf_manifest"]
    xmf = [r for r in refs if r["role"] == "xmf_xml"]
    contacts = [r for r in refs if r["role"] == "contact_png"]
    keys = [r for r in refs if r["role"] == "key_png"]
    if not manifests or not xmf or not contacts or not keys:
        raise RuntimeError(f"incomplete published visual refs for {family}/{physical_id}")
    return {
        "family_id": family,
        "case_id": membership_row.get("case_id") or index_row.get("case_id"),
        "physical_case_id": physical_id,
        "first8_member": bool(first8),
        "first24_member": True,
        "final48_membership_source": "authoritative_family_membership_json; this catalog does not select or infer final48 rows",
        "accepted_decision": {
            **ref_from_pair(decision_pair, decision_path, cache),
            "role": "immutable_accepted_visual_decision",
            "top_condition_sha256": membership_row.get("accepted_decision_top_condition_sha256")
            or index_row.get("accepted_decision_top_condition_sha256"),
            "top_condition_role": "accepted semantic declaration; never overrides actual native request scope",
        },
        "source_declared_roles": {
            "accepted_decision_top_condition_sha256": membership_row.get("accepted_decision_top_condition_sha256")
            or index_row.get("accepted_decision_top_condition_sha256"),
            "declared_source_plan_condition_sha256": index_row.get("declared_source_plan_condition_sha256"),
            "declared_source_definition_sha256": index_row.get("declared_source_definition_sha256"),
            "declared_actual_converter_scope_sha256": index_row.get("declared_actual_converter_scope_sha256"),
            "actual_native_condition_field_true_absence": index_row.get("actual_native_condition_field_true_absence"),
            "roles_are_separate": True,
        },
        "native_request_role_snapshot": safe_native_snapshot(index_row, decision_path, cache),
        "actual_render_report": {"ref": render_ref, "metadata": render_fields},
        "actual_xmf_manifest": manifests[0],
        "actual_xmf_xml": xmf[0],
        "gencase_or_definition_refs": [r for r in refs if r["role"] == "gencase_or_definition"],
        "initial_qa_or_audit_refs": [r for r in refs if r["role"] == "initial_qa_or_audit"],
        "native_refs": [r for r in refs if r["role"] == "native_receipt_or_report"],
        "typed_refs": [r for r in refs if r["role"] == "typed_receipt_or_report"],
        "owner_or_source_refs": [r for r in refs if r["role"] == "owner_or_source"],
        "render_receipt_refs": [r for r in refs if r["role"] == "render_receipt"],
        "contact_png_refs": contacts,
        "key_png_refs": keys,
        "all_allowed_refs": refs,
        "evidence_scope": {
            "metadata_only": True,
            "published_png_refs_inherited": True,
            "new_visual_review": False,
            "scientific_payload_read_or_hashed": False,
            "case_credit": 0,
            "q_n": False,
            "q_e": False,
            "precision_status": "visual acceptance inherited; numerical precision not accepted",
        },
    }


def main() -> int:
    out_dir = pathlib.Path(__file__).resolve().parents[1]
    metadata_dir = out_dir / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    f2 = read_json(F2_MEMBERSHIP)
    f3 = read_json(F3_MEMBERSHIP)
    f46 = read_json(F46_MEMBERSHIP)
    current = read_json(CURRENT_INDEX)
    index_by_physical = {row["physical_case_id"]: row for row in current["cases"]}
    cache: dict[str, dict[str, Any]] = {}

    rows: list[dict[str, Any]] = []
    f2_ids = [row["physical_case_id"] for row in f2["case_refs"]]
    f3_ids = list(f3["actual_first24_physical_case_ids"])
    f6_rows = list(f46["families"]["F6"]["rows_actual_source_order"])
    if len(f2_ids) != 24 or len(f3_ids) != 24 or len(f6_rows) != 24:
        raise RuntimeError("authoritative first24 inputs are not 24 rows each")
    f2_by = {row["physical_case_id"]: row for row in f2["case_refs"]}
    f3_decisions = {physical: decision for physical, decision in zip(f3_ids, f3["actual_visual_decisions"])}
    f6_by = {row["physical_case_id"]: row for row in f6_rows}
    f2_first8 = {row["physical_case_id"] for row in f2["case_refs"] if row.get("first8_member") is True}
    f3_first8 = set(f3["actual_first8_physical_case_ids"])
    f6_first8 = set(f46["families"]["F6"]["frozen_actual_first8_physical_case_ids"])

    for physical in f2_ids:
        if physical not in index_by_physical:
            raise RuntimeError(f"F2 physical ID missing from current index: {physical}")
        rows.append(make_row("F2", physical, f2_by[physical], f2_by[physical]["accepted_decision"], physical in f2_first8, index_by_physical[physical], cache))
    for physical in f3_ids:
        if physical not in index_by_physical:
            raise RuntimeError(f"F3 physical ID missing from current index: {physical}")
        rows.append(make_row("F3", physical, {"accepted_decision_top_condition_sha256": index_by_physical[physical].get("accepted_decision_top_condition_sha256")}, f3_decisions[physical], physical in f3_first8, index_by_physical[physical], cache))
    for physical in [row["physical_case_id"] for row in f6_rows]:
        if physical not in index_by_physical:
            raise RuntimeError(f"F6 physical ID missing from current index: {physical}")
        rows.append(make_row("F6", physical, f6_by[physical], f6_by[physical]["actual_visual_decision"], physical in f6_first8, index_by_physical[physical], cache))

    authorities = []
    authority_pairs = [
        ("F2 first8/first24/final48 membership", F2_MEMBERSHIP, {"path": str(F2_MEMBERSHIP), "sha256": sha256_file(F2_MEMBERSHIP)}),
        ("F3 first8/first24/final48 membership", F3_MEMBERSHIP, {"path": str(F3_MEMBERSHIP), "sha256": sha256_file(F3_MEMBERSHIP)}),
        ("F6 first8/first24/final48 membership", F46_MEMBERSHIP, {"path": str(F46_MEMBERSHIP), "sha256": sha256_file(F46_MEMBERSHIP)}),
        ("Root1268 current role-aware delivery index", CURRENT_INDEX, {"path": str(CURRENT_INDEX), "sha256": sha256_file(CURRENT_INDEX)}),
        ("Root1093 frozen first8 authority", FROZEN8, {"path": str(FROZEN8), "sha256": sha256_file(FROZEN8)}),
    ]
    for label, source, pair in authority_pairs:
        authorities.append({"label": label, "ref": ref_from_pair(pair, source, cache)})

    f3_anchor = f3["anchor_accepted_semantic49_and_actual_native86562_roles_preserved"]
    catalog = {
        "schema": "ds02.f6.fresh178.first24-dynamic-entry-catalog.v1",
        "generated_by": "F6 delegated source-only metadata builder; no new visual review",
        "at_utc": "2026-10-07",
        "purpose": "Entry metadata for the authoritative first24 subsets of F2, F3, and F6; all 72 rows are inherited accepted deliveries.",
        "authorities": authorities,
        "membership": {
            "F2": {
                "first8_count": f2["first8_count"], "first24_count": f2["first24_count"], "final48_count": f2["final48_count"],
                "first8_subset_first24_subset_final48": f2["first8_subset_first24_subset_final48"],
                "actual_accepted_current": f2["actual_accepted_current_F2"],
            },
            "F3": {
                "first8_count": len(f3["actual_first8_physical_case_ids"]), "first24_count": len(f3["actual_first24_physical_case_ids"]), "final48_count": 48,
                "first8_subset_actual24_subset_current37_subset_final48": f3["first8_subset_actual24_subset_current37_subset_final48"],
                "actual_first24_delivered": f3["actual_first24_delivered"], "current_accepted": f3["current_F3_accepted"],
                "final48_delivered": f3["final48_delivered"],
                "anchor_semantic_vs_actual_native_roles": f3_anchor,
            },
            "F6": {
                "first8_count": len(f46["families"]["F6"]["frozen_actual_first8_physical_case_ids"]), "first24_count": f46["families"]["F6"]["actual_first24_count"], "final48_count": 48,
                "first8_subset_actual_delivery24": f46["families"]["F6"]["frozen_actual_first8_subset_actual_delivery24"],
                "current_accepted": f46["families"]["F6"]["current_accepted_independent_case_count"],
                "final48_complete": f46["families"]["F6"]["current_final48_complete"],
            },
        },
        "roles": {
            "accepted_top_condition": "accepted semantic/source declaration",
            "native_request_scope": "actual native request/receipt role when present in Root1268; absent fields remain absent",
            "source_plan_and_converter_scope": "separate provenance fields; no equality is inferred",
            "F3_anchor": "semantic SHA 49e319... and actual native SHA 86562... are role-separated; no physical parameter is inferred from either prefix",
            "F6_mass_and_omega": "no new physical or mass claim is made by this catalog",
        },
        "rows": rows,
        "policy": {
            "first8_is_subset_of_first24": True,
            "final48_is_not_replaced_by_planned24": True,
            "no_new_visual_review": True,
            "scientific_payload_read_or_hashed": False,
            "new_case_credit": 0,
            "q_n": False,
            "q_e": False,
            "numerical_precision_accepted": False,
            "forbidden_payload_suffixes": sorted(FORBIDDEN_SUFFIXES),
        },
    }
    out = metadata_dir / "dynamic-entry-catalog.json"
    out.write_text(json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(out), "rows": len(rows), "cached_allowed_files": len(cache)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
