#!/usr/bin/env python3
"""Build the F6-owned, metadata-only final-48 roster for F1/F4/F7.

This reader intentionally admits only JSON/XML/XMF/PNG as hashable evidence.
H5/BI4/CSV/DAT/VTK and other scientific payloads are excluded before any read.
It does not modify the integration checkpoint or launch work.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

INTEGRATION = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics"
)
HANDOFF = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003"
F6_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics")
OUT = F6_ROOT / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/"
    "root_followup_175_f1_f4_f7_final48_delivery_manifest_v1"
)

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

ALLOWED_SUFFIXES = {".json", ".xml", ".xmf", ".png"}
FORBIDDEN_SUFFIXES = {
    ".h5", ".bi4", ".csv", ".dat", ".vtk", ".vtu", ".out", ".gif", ".pvsm"
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_bytes(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def authority_ref(path: Path, role: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError(f"authority is not metadata-only: {path}")
    return {
        "path": str(path),
        "role": role,
        "kind": "metadata",
        "bytes": path.stat().st_size,
        "sha256": sha256_bytes(path),
    }


def walk_path_nodes(value: Any, key_path: tuple[str, ...] = ()) -> Iterable[dict[str, Any]]:
    path_key_hints = {
        "path", "execution_receipt", "receipt", "report", "manifest", "case_xmf",
        "xdmf", "xmf", "generated_xml", "generated_definition_xml", "generated_def_xml",
        "prepared_input_report", "conversion_report", "typed_report", "render_report",
        "publish_receipt", "native_receipt", "typed_receipt", "normal_xmf", "normal_manifest",
        "dynamic_manifest", "dynamic_xdmf", "dynamic_xdmf_manifest", "native", "full_native",
        "render", "request", "owner_metadata", "canonical_owner", "source_owner", "gencase",
        "initial_native_qa", "native_initial_qa", "initial_qa_report", "typed_full601",
        "native_full601", "xmf_full601", "render_full601", "paraview_full_animation_report",
        "png_hash_manifest", "evidence_chain", "evidence_manifest",
    }
    if isinstance(value, str) and value.startswith("/"):
        key = key_path[-1].lower() if key_path else ""
        if key in path_key_hints or key.endswith("_path"):
            yield {
                "path": value,
                "key_path": ".".join(key_path),
                "declared_sha256": None,
            }
        return
    if isinstance(value, dict):
        raw_path = value.get("path")
        if isinstance(raw_path, str) and raw_path.startswith("/"):
            yield {
                "path": raw_path,
                "key_path": ".".join(key_path + ("path",)),
                "declared_sha256": value.get("sha256")
                if isinstance(value.get("sha256"), str)
                else None,
            }
        for key, child in value.items():
            yield from walk_path_nodes(child, key_path + (str(key),))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_path_nodes(child, key_path + (str(index),))


def suffix(path: str) -> str:
    return Path(path).suffix.lower()


def path_basename(path: str) -> str:
    return Path(path).name.lower()


def is_forbidden(path: str) -> bool:
    return suffix(path) in FORBIDDEN_SUFFIXES


def classify_node(node: dict[str, Any]) -> str | None:
    path = node["path"]
    ext = suffix(path)
    if ext == ".png":
        return "png"
    if ext not in ALLOWED_SUFFIXES:
        return None
    key_path = node["key_path"].lower()
    base = path_basename(path)
    last_keys = [part for part in key_path.split(".") if not part.isdigit()]
    last = last_keys[-2] if last_keys and last_keys[-1] == "path" and len(last_keys) > 1 else ""

    # Explicit decision fields have priority over filename heuristics.
    if last in {
        "native_receipt", "native", "native_solver", "native_full601", "full_native",
        "native_execution_receipt",
    }:
        return "native"
    if last in {
        "typed_receipt", "typed", "conversion_report", "typed_full601",
        "typed_conversion", "typed_report",
    }:
        return "typed"
    if last in {
        "dynamic_xdmf_manifest", "dynamic_manifest", "normal_manifest", "manifest",
        "dynamic_xdmf", "normal_xdmf", "xdmf", "normal",
    } or ext == ".xmf":
        return "xmf"
    if last in {
        "animation_receipt", "animation_integrity_report", "native_full_render_report",
        "render", "render_report", "paraview_full_animation_report", "render_full601",
    }:
        return "render"
    if last in {"initial_native_qa", "native_initial_qa", "native_frame0_qa", "native_qa"}:
        return "qa"
    if last in {
        "generated_xml", "generated_xml", "generated_def_xml", "gencase", "prepared",
        "actual_motion_clone_receipt",
    }:
        return "gencase"
    if last in {"owner_metadata", "canonical_owner", "source_owner", "owner"}:
        return "owner"

    # The six-stage receipt list has only a path field, so use its immutable
    # attempt name as the stage discriminator.
    if "actual_completed_receipts" in key_path or "actual_completed_metadata_evidence" in key_path:
        low = path.lower()
        # A typed attempt can own the XMF handoff directory (for example
        # ``...actual-typed255.../xdmf/manifest.json``).  Directory/filename
        # provenance is stronger than the parent evidence key here; keep the
        # manifest with the XMF product rather than mislabelling it as typed.
        if "/xdmf/" in low or "/xmf/" in low or (
            base in {"case.xmf", "manifest.json"} and "xmf" in low
        ):
            return "xmf"
        if "gencase" in low:
            return "gencase"
        if "initial-qa" in low or "initial_qa" in low or "frame0" in low:
            return "qa"
        if "typed" in low or "conversion" in low:
            return "typed"
        if "paraview" in low or "render" in low or "animation" in low:
            return "render"
        if "xdmf" in low or "xmf" in low:
            return "xmf"
        if "native" in low:
            return "native"

    # Some older F1 decisions stored stage paths under generic source_N keys;
    # some delegated F4/F7 decisions use actual_completed_metadata_evidence.
    # Their attempt names remain the only unambiguous stage marker.
    if "bindings" in key_path or "actual_completed_metadata_evidence" in key_path:
        low = path.lower()
        if "gencase" in low:
            return "gencase"
        if "initial-qa" in low or "initial_qa" in low or "frame0" in low:
            return "qa"
        if "typed" in low or "conversion" in low:
            return "typed"
        if "paraview" in low or "render" in low or "animation" in low:
            return "render"
        if "xdmf" in low or "xmf" in low or "normal-dynamic" in low:
            return "xmf"
        if "native" in low:
            return "native"

    # Newer evidence blocks use descriptive names rather than the old binding
    # keys. Keep these as stage references where their names are unambiguous.
    if "initial_native_qa" in key_path or "native_initial_qa" in key_path:
        return "qa"
    if "conversion_report" in key_path or "typed" in key_path:
        return "typed"
    if "dynamic_entry" in key_path and ("manifest" in key_path or "xdmf" in key_path):
        return "xmf"
    if "render_report" in key_path or "paraview" in key_path or "animation" in key_path:
        return "render"
    if base == "manifest.json" or base.endswith(".xmf"):
        return "xmf"
    return "other"


def png_role(node: dict[str, Any]) -> str:
    key_path = node["key_path"].lower()
    base = path_basename(node["path"])
    if "contact" in key_path or base.startswith("all_frames_"):
        return "contact_sheet"
    if (
        "key" in key_path
        or "full_size" in key_path
        or "/frames/frame_" in node["path"].lower()
    ):
        return "key_frame"
    return "other_png"


def metadata_ref(node: dict[str, Any], role: str, category: str) -> dict[str, Any]:
    path = Path(node["path"])
    if not path.is_file():
        raise FileNotFoundError(path)
    if suffix(str(path)) not in ALLOWED_SUFFIXES:
        raise ValueError(f"scientific/non-target payload reached metadata_ref: {path}")
    actual = sha256_bytes(path)
    result: dict[str, Any] = {
        "path": str(path),
        "role": role,
        "category": category,
        "kind": "metadata",
        "format": suffix(str(path))[1:],
        "bytes": path.stat().st_size,
        "sha256": actual,
        "source_key": node["key_path"],
    }
    declared = node.get("declared_sha256")
    if declared:
        result["declared_sha256"] = declared
        result["declared_sha256_matches_current"] = declared == actual
    return result


def dedupe_refs(nodes: Iterable[dict[str, Any]], category: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in nodes:
        path = node["path"]
        if path in seen:
            continue
        seen.add(path)
        # A few immutable decisions preserve an obsolete source pointer while
        # also recording the actual replacement. Keep the obsolete pointer in
        # the case audit below, but never present it as a live product input.
        if not Path(path).is_file():
            continue
        result.append(metadata_ref(node, node["key_path"], category))
    return result


def derived_node(path: Path, key_path: str) -> dict[str, Any]:
    """Represent a concrete sibling metadata file of a producer receipt."""
    return {"path": str(path), "key_path": key_path, "declared_sha256": None}


def derive_stage_siblings(product: dict[str, Any], category: str, names: tuple[str, ...]) -> None:
    """Add manifest/report siblings next to an already-bound stage receipt.

    Delegated decision records sometimes retain only the producer execution
    receipt. The sibling filenames below are the frozen producer layout used by
    the recorded receipt itself; this is path closure, not a directory search.
    """
    existing = {ref["path"] for ref in product[category]}
    additions: list[dict[str, Any]] = []
    for receipt in product[category]:
        path = Path(receipt["path"])
        if path.name != "execution-receipt.json":
            continue
        parents = [path.parent]
        # XMF and render workers commonly put their payload metadata in a
        # child xdmf/render directory while keeping the receipt at attempt root.
        parents.extend([path.parent / "xdmf", path.parent / "xmf", path.parent / "render"])
        for parent in parents:
            for name in names:
                candidate = parent / name
                if candidate.is_file() and str(candidate) not in existing:
                    additions.append(derived_node(candidate, f"derived_from_{category}_receipt_directory"))
                    existing.add(str(candidate))
    product[category].extend(
        metadata_ref(node, f"derived_from_{category}_receipt_directory", category)
        for node in additions
    )


def execution_status(path: str) -> dict[str, Any]:
    result: dict[str, Any] = {"path": path, "status_read": False}
    try:
        data = load_json(Path(path))
    except Exception as exc:  # receipt may be a producer-owned opaque JSON variant
        result["status_error"] = type(exc).__name__
        return result
    result["status_read"] = True
    for key in ("status", "completed", "returncode", "return_code", "exit_code", "terminal"):
        if key in data:
            result[key] = data[key]
    completed = data.get("completed")
    status = data.get("status")
    rc = data.get("returncode", data.get("return_code", data.get("exit_code")))
    result["terminal_success_observed"] = (
        (status == "completed" or completed is True)
        and (rc in (None, 0))
    )
    return result


def safe_metadata_view(value: Any) -> Any:
    """Remove full saved-frame inventories before reading review metadata."""
    if isinstance(value, dict):
        return {
            key: safe_metadata_view(child)
            for key, child in value.items()
            if key not in {
                "visual_scope", "all_601_saved_frame_pngs", "all_saved_frame_pngs",
                "trajectory", "trajectory_h5", "trajectory_binding",
            }
        }
    if isinstance(value, list):
        return [safe_metadata_view(child) for child in value]
    return value


def related_metadata_nodes(decision: dict[str, Any], direct_nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Read only case-level review JSON needed to close stale decision pointers.

    Several delegated F4/F7 decisions intentionally keep the actual chain in a
    separate visual-review/chain-closure JSON. Those are metadata files. We
    select the matching case and omit the full saved-frame inventory, then load
    only its explicitly named evidence manifests.
    """
    result: list[dict[str, Any]] = []
    loaded: set[Path] = set()
    queue: list[Path] = []
    for node in direct_nodes:
        key = node["key_path"].lower()
        if suffix(node["path"]) == ".json" and any(
            token in key for token in ("source_review", "source_visual_review", "review_index", "review_closure")
        ):
            queue.append(Path(node["path"]))
    while queue and len(loaded) < 8:
        path = queue.pop(0)
        if path in loaded or not path.is_file() or suffix(str(path)) != ".json":
            continue
        loaded.add(path)
        try:
            data = safe_metadata_view(load_json(path))
        except Exception:
            continue
        selected: Any = data
        if isinstance(data, dict) and isinstance(data.get("cases"), (list, dict)):
            raw_cases = data["cases"]
            rows = list(raw_cases.values()) if isinstance(raw_cases, dict) else raw_cases
            matches = [
                row for row in rows
                if isinstance(row, dict)
                and row.get("physical_case_id") == decision.get("physical_case_id")
            ]
            if not matches and isinstance(raw_cases, dict):
                keyed = raw_cases.get(decision.get("physical_case_id"))
                if isinstance(keyed, dict):
                    matches = [keyed]
            if not matches:
                matches = [
                    row for row in rows
                    if isinstance(row, dict) and row.get("case_id") == decision.get("case_id")
                ]
            selected = matches[0] if matches else {}
        for node in walk_path_nodes(selected, (f"related:{path.name}",)):
            if is_forbidden(node["path"]):
                continue
            result.append(node)

        # Review packages use relative names for the PNG/evidence manifests.
        # Resolve only those named metadata links; never walk arbitrary strings.
        def find_related(value: Any, key_path: tuple[str, ...] = ()) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    low = str(key).lower()
                    if isinstance(child, str) and low in {
                        "png_hash_manifest", "png_index_ref", "png_artifacts",
                        "evidence_chain", "evidence_manifest", "evidence_files",
                    }:
                        candidate = Path(child)
                        if not candidate.is_absolute():
                            local_candidate = path.parent / candidate
                            # Review JSON commonly stores the package-relative
                            # string "metadata/png-hashes.json" from inside
                            # metadata/, so try package root as well.
                            candidate = (
                                local_candidate
                                if local_candidate.is_file()
                                else path.parent.parent / candidate
                            )
                        # Older delegated review packages use png_index_ref as
                        # a case key (rather than a pathname).  The sibling
                        # png-hashes.json is the immutable metadata index for
                        # that key; resolve it without treating the case key
                        # as a filesystem path.
                        if not candidate.is_file() and low == "png_index_ref":
                            for index_name in (
                                "png-hashes.json",
                                "png-hash-manifest.json",
                                "png_hashes.json",
                            ):
                                sibling = path.parent / index_name
                                if sibling.is_file():
                                    candidate = sibling
                                    break
                        if candidate.is_file() and candidate not in loaded:
                            queue.append(candidate)
                    find_related(child, key_path + (str(key),))
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    find_related(child, key_path + (str(index),))
        find_related(selected)
        # Some early delegated review JSONs keep the PNG index only as a
        # sibling file and expose no per-case link.  Once the matching case
        # has been selected, the sibling index is still the correct immutable
        # metadata source; it is safe to enqueue it and select by physical ID.
        for index_name in (
            "png-hashes.json",
            "png-hash-manifest.json",
            "png_hashes.json",
        ):
            sibling = path.parent / index_name
            if sibling.is_file() and sibling not in loaded:
                queue.append(sibling)
                break
    return result


def first8_and_first24_memberships() -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    d1232 = load_json(ROOT1232)
    d1238 = load_json(ROOT1238)
    result8: dict[str, list[dict[str, Any]]] = {}
    result24: dict[str, list[dict[str, Any]]] = {}
    for family in ("F1", "F7"):
        result8[family] = d1232["families"][family]["actual_first8"]
        result24[family] = d1232["families"][family]["actual_first24"]
    f4_rows = d1238["families"]["F4"]["rows_actual_source_order"]
    frozen_ids = d1238["families"]["F4"]["frozen_actual_first8_physical_case_ids"]
    by_id = {row["physical_case_id"]: row for row in f4_rows}
    result8["F4"] = [by_id[physical_id] for physical_id in frozen_ids]
    result24["F4"] = f4_rows
    return result8, result24


def row_decision(row: dict[str, Any], family: str) -> dict[str, Any]:
    if family == "F4":
        return row["actual_visual_decision"]
    return row["accepted_visual_decision"]


def row_physical_id(row: dict[str, Any]) -> str:
    return row["physical_case_id"]


def make_membership_evidence(
    family: str,
    first8: list[dict[str, Any]],
    first24: list[dict[str, Any]],
    final_decisions: list[tuple[Path, dict[str, Any]]],
) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    first8_by_id = {row_physical_id(row): row for row in first8}
    first24_by_id = {row_physical_id(row): row for row in first24}
    result: dict[str, dict[str, Any]] = {}
    for path, decision in final_decisions:
        physical_id = decision["physical_case_id"]
        role = "first8" if physical_id in first8_by_id else (
            "first24" if physical_id in first24_by_id else "final48_only"
        )
        result[physical_id] = {
            "membership_role": role,
            "physical_family": family,
            "accepted_decision_path": str(path),
            "first8_source_decision": (
                row_decision(first8_by_id[physical_id], family)
                if physical_id in first8_by_id else None
            ),
            "first24_source_decision": (
                row_decision(first24_by_id[physical_id], family)
                if physical_id in first24_by_id else None
            ),
        }
    return result, {
        "first8_physical_case_ids": [row_physical_id(row) for row in first8],
        "first24_physical_case_ids": [row_physical_id(row) for row in first24],
        "final48_physical_case_ids": [d["physical_case_id"] for _, d in final_decisions],
    }


def direct_source_ref(source: Any) -> dict[str, Any] | None:
    if not isinstance(source, dict):
        return None
    path = source.get("path")
    if not isinstance(path, str) or not path.startswith("/"):
        return None
    if suffix(path) not in ALLOWED_SUFFIXES:
        return None
    return {
        "path": path,
        "key_path": "authority_row.accepted_visual_decision.path",
        "declared_sha256": source.get("sha256") if isinstance(source.get("sha256"), str) else None,
    }


def native_registration_metadata(
    family: str,
    physical_id: str,
    role_rows: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    """Preserve Root1258's native role without inferring missing scope.

    The accepted decision's top-level physical hash is a semantic declaration
    and is carried separately from ``native_request_scope``.  A null native
    scope remains null; this package never fills it from either declaration.
    """
    row = role_rows.get((family, physical_id))
    if row is None:
        raise AssertionError(f"{family}/{physical_id}: missing Root1258 role-aware row")
    scope = row.get("native_request_scope")
    return {
        "role_source": "Root1258 full336 role-aware registration metadata; metadata-only reference",
        "source_index_row_identity": {
            "family_id": row.get("family_id"),
            "physical_case_id": row.get("physical_case_id"),
            "case_id": row.get("case_id"),
            "status": row.get("status"),
        },
        "accepted_decision_top_condition_sha256": row.get(
            "accepted_decision_top_condition_sha256"
        ),
        "accepted_decision_top_hash_role": row.get(
            "accepted_decision_top_hash_role"
        ),
        "declared_source_plan_condition_sha256": row.get(
            "declared_source_plan_condition_sha256"
        ),
        "declared_actual_converter_scope_sha256": row.get(
            "declared_actual_converter_scope_sha256"
        ),
        "native_request_scope": scope,
        "top_or_render_declared_condition_equals_actual_native_request": row.get(
            "top_or_render_declared_condition_equals_actual_native_request"
        ),
        "native_scope_sha256_is_missing": not isinstance(scope, dict)
        or scope.get("sha256") is None,
        "original_receipt_and_recovery_roles_preserved": True,
    }


def build_product_refs(decision: dict[str, Any]) -> dict[str, Any]:
    nodes = list(walk_path_nodes(decision))
    nodes.extend(related_metadata_nodes(decision, nodes))
    missing_source_pointers = [
        {"path": node["path"], "source_key": node["key_path"], "status": "preserved_but_missing"}
        for node in nodes
        if not Path(node["path"]).is_file() and not is_forbidden(node["path"])
    ]
    by_category: dict[str, list[dict[str, Any]]] = {key: [] for key in (
        "native", "typed", "xmf", "render", "qa", "gencase", "owner", "other"
    )}
    png_nodes: list[dict[str, Any]] = []
    for node in nodes:
        if is_forbidden(node["path"]):
            continue
        category = classify_node(node)
        if category == "png":
            png_nodes.append(node)
        elif category in by_category:
            by_category[category].append(node)

    # Stable first-seen ordering follows the immutable accepted decision, not
    # a directory walk. Keep only the requested product and provenance classes.
    product: dict[str, Any] = {}
    for category in ("native", "typed", "xmf", "render"):
        product[category] = dedupe_refs(by_category[category], category)
    derive_stage_siblings(product, "typed", ("conversion-report.json",))
    derive_stage_siblings(product, "xmf", ("manifest.json", "case.xmf"))
    derive_stage_siblings(product, "render", ("paraview-full-animation-report.json", "render-publish-receipt.json"))
    product["qa"] = dedupe_refs(by_category["qa"], "initial_native_qa")
    product["gencase"] = dedupe_refs(by_category["gencase"], "gencase_or_generated_xml")
    product["owner"] = dedupe_refs(by_category["owner"], "owner_or_scope_metadata")

    contact: list[dict[str, Any]] = []
    key: list[dict[str, Any]] = []
    other_png: list[dict[str, Any]] = []
    seen_png: set[str] = set()
    for node in png_nodes:
        if node["path"] in seen_png:
            continue
        seen_png.add(node["path"])
        if not Path(node["path"]).is_file():
            continue
        role = png_role(node)
        ref = metadata_ref(node, role, "png")
        if role == "contact_sheet":
            contact.append(ref)
        elif role == "key_frame":
            key.append(ref)
        else:
            other_png.append(ref)
    product["png"] = {
        "contact_sheets": contact,
        "key_frames": key,
        "other_png": other_png,
        "counts": {
            "contact_sheets": len(contact),
            "key_frames": len(key),
            "other_png": len(other_png),
        },
    }

    # Preserve original binding receipts and separate producer/recovery
    # evidence. This does not reinterpret a nonterminal original as success.
    direct_receipts: list[dict[str, Any]] = []
    actual_evidence: list[dict[str, Any]] = []
    seen_receipts: set[str] = set()
    for node in nodes:
        path = node["path"]
        if Path(path).name != "execution-receipt.json":
            continue
        if path in seen_receipts:
            continue
        seen_receipts.add(path)
        ref = metadata_ref(node, node["key_path"], "execution_receipt")
        ref["observed"] = execution_status(path)
        if "actual_completed_receipts" in node["key_path"]:
            actual_evidence.append(ref)
        else:
            direct_receipts.append(ref)
    product["receipt_roles"] = {
        "original_or_direct_binding_receipts": direct_receipts,
        "actual_completed_or_recovery_evidence_receipts": actual_evidence,
        "nonterminal_or_nonzero_preserved": [
            ref for ref in direct_receipts + actual_evidence
            if not ref["observed"].get("terminal_success_observed", False)
        ],
    }
    product["science_payload_refs_omitted"] = True
    product["missing_source_pointers_preserved"] = missing_source_pointers
    return product


def main() -> None:
    cp = load_json(CHECKPOINT)
    root1093 = load_json(ROOT1093)
    root1258 = load_json(ROOT1258)
    role_rows = {
        (row.get("family_id"), row.get("physical_case_id")): row
        for row in root1258["cases"]
        if isinstance(row, dict)
    }
    first8, first24 = first8_and_first24_memberships()
    accepted: dict[str, list[tuple[Path, dict[str, Any]]]] = {f: [] for f in ("F1", "F4", "F7")}
    for raw_path in cp["accepted_decisions"]:
        path = Path(raw_path)
        decision = load_json(path)
        if decision.get("family_id") in accepted:
            accepted[decision["family_id"]].append((path, decision))

    authorities = {
        "checkpoint218": authority_ref(CHECKPOINT, "stable predecessor; not rewritten by this package"),
        "root1093_frozen8": authority_ref(ROOT1093, "frozen first8 membership authority"),
        "root1232_f1_f7_first24": authority_ref(ROOT1232, "actual first24 membership authority for F1/F7"),
        "root1238_f4_first24": authority_ref(ROOT1238, "actual first24 membership authority for F4"),
        "root1258_role_aware_native_index": authority_ref(
            ROOT1258,
            "current role-aware native registration metadata; accepted top hash and actual native scope remain separate",
        ),
    }

    families: dict[str, Any] = {}
    for family in ("F1", "F4", "F7"):
        final_rows = accepted[family]
        if len(final_rows) != 48:
            raise AssertionError(f"{family}: checkpoint final accepted count {len(final_rows)} != 48")
        membership_evidence, ids = make_membership_evidence(
            family, first8[family], first24[family], final_rows
        )
        final_set = set(ids["final48_physical_case_ids"])
        first8_set = set(ids["first8_physical_case_ids"])
        first24_set = set(ids["first24_physical_case_ids"])
        if len(final_set) != 48 or len(first8_set) != 8 or len(first24_set) != 24:
            raise AssertionError(f"{family}: duplicate physical IDs in membership")
        if not first8_set < first24_set or not first24_set < final_set:
            raise AssertionError(f"{family}: strict 8 < 24 < 48 subset relation failed")

        # Verify Root1093 frozen8 path set against the actual first8 source.
        frozen_paths = [entry["path"] for entry in root1093["cases_by_family"][family]]
        actual_first8_paths = [
            row_decision(row, family)["path"] for row in first8[family]
        ]
        if set(frozen_paths) != set(actual_first8_paths):
            raise AssertionError(f"{family}: Root1093 frozen8 does not match actual first8")

        cases: list[dict[str, Any]] = []
        for path, decision in final_rows:
            physical_id = decision["physical_case_id"]
            case = {
                "family_id": family,
                "physical_family": family,
                "source_assignment_family": "F6",
                "case_id": decision.get("case_id"),
                "physical_case_id": physical_id,
                "source_role": "cross-family final48 metadata roster; F6 owns this handoff only",
                "role_aware_native_registration": native_registration_metadata(
                    family, physical_id, role_rows
                ),
                "membership_role": membership_evidence[physical_id]["membership_role"],
                "accepted_decision": {
                    "path": str(path),
                    "sha256": sha256_bytes(path),
                    "kind": "immutable accepted visual decision metadata",
                    "status": decision.get("status"),
                    "visual_review_status": "visual-approved",
                },
                "membership_evidence": membership_evidence[physical_id],
                "physical_scope": {
                    "physical_condition_sha256": decision.get("physical_condition_sha256"),
                    "source_plan_condition_sha256": decision.get(
                        "source_plan_physical_condition_sha256",
                        decision.get("source_plan_condition_sha256"),
                    ),
                    "source_canonical_physical_binding_sha256": decision.get(
                        "source_canonical_physical_binding_sha256"
                    ),
                    "scope_roles_are_distinct": True,
                },
                "delivery_status": {
                    "visual_status": "visual checks passed in immutable accepted decision",
                    "numerical_precision_status": "not accepted",
                    "q_n": False,
                    "q_e": False,
                    "case_credit": 0,
                    "new_acceptance": False,
                },
                "product_metadata": build_product_refs(decision),
                "decision_provenance": {
                    "decision_family": decision.get("family_id"),
                    "decision_schema": decision.get("schema"),
                    "accepted_at_utc": decision.get("at_utc"),
                    "frames": decision.get("frames"),
                    "physical_window_s": decision.get("physical_window_s"),
                    "actual_last_time_s": decision.get("actual_last_time_s"),
                },
            }
            cases.append(case)

        families[family] = {
            "family_id": family,
            "source_assignment_family": "F6",
            "physical_family": family,
            "counts": {"first8": 8, "first24": 24, "final48": 48},
            "subset_proof": {
                "strict_first8_subset_first24": True,
                "strict_first24_subset_final48": True,
                "first8_order_source": "Root1093 frozen8 order cross-checked with Root1232/1238",
                "first24_order_source": "Root1232/Root1238 actual source order",
                "final48_order_source": "checkpoint218 accepted_decisions order filtered by family",
                "physical_ids_unique_at_each_level": True,
            },
            "first8_physical_case_ids": ids["first8_physical_case_ids"],
            "first24_physical_case_ids": ids["first24_physical_case_ids"],
            "final48_physical_case_ids": ids["final48_physical_case_ids"],
            "cases": cases,
        }

    manifest = {
        "schema": "ds02.f6.cross-family-final48-delivery-roster.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "package_scope": {
            "source_assignment_family": "F6",
            "physical_families": ["F1", "F4", "F7"],
            "purpose": "metadata-only final48 delivery checklist; no new acceptance or computation",
            "case_credit": 0,
            "new_acceptance": False,
            "precision_status": "视觉检查通过、数值精度未验收",
            "q_n": False,
            "q_e": False,
            "scientific_payload_read": False,
            "scientific_payload_hashed": False,
            "png_visual_review_repeated": False,
            "model": "GPT-5.6-Luna/max",
            "gemini": False,
            "recursive_delegation": False,
            "checkpoint_not_modified": True,
            "native_registration_role_source": "Root1258 role-aware index is a separate metadata role; no accepted-top/native-scope substitution",
        },
        "authority": authorities,
        "families": families,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "final48-delivery-roster.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {OUT / 'final48-delivery-roster.json'}")
    print({family: len(data["cases"]) for family, data in families.items()})


if __name__ == "__main__":
    main()
