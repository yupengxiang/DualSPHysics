#!/usr/bin/env python3
"""Prepare a source-bound canonical F2 raw replay anchor.

This is an additive metadata planner.  It selects CURRENT336 row 65, the
saved-mask canonical F2 case, and refuses the historical unresolved alias at
row 78.  It records the exact raw tree and source roles for a later parent
guard, but never opens BI4, HDF5, initial CSV, or other scientific payload.
The emitted worker request is deliberately ``PARENT_GUARD_REQUIRED`` until a
reserved parent computes the raw/source content hashes.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


SCHEMA = "ds02.stage2.f2-canonical-raw-anchor-plan.v2"
REQUEST_SCHEMA = "ds02.stage2.f2-native-raw-to-typed-to-label-request.v2"
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
CURRENT_CATALOG_SCHEMA = "ds02.stage2.current336.v1"
CATALOG_SCHEMA = "ds02.stage2.namespace330.scoped-proof-catalog.v6"
PHYSICAL_INDEX_SCHEMA = "ds02.stage2.all336-effective-condition-source-index.v27"
PROOF_SCHEMA = "ds02.stage2.root-actual-verification.v1"
CANONICAL_ID = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX047_RY014_FILL080_ROT075"
HISTORICAL_ALIAS_ID = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
PENDING = "PENDING_PARENT_GUARD_CONTENT_SHA256"
UNKNOWN_QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
SMALL_HASH_LIMIT = 8 * 1024 * 1024


class AnchorError(ValueError):
    """The requested source-bound anchor is not safe to expose."""


def _load(path: Path, role: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AnchorError(f"cannot read {role}: {path}: {error}") from error
    if not isinstance(value, dict):
        raise AnchorError(f"{role} must be a JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                      ensure_ascii=True).encode()).hexdigest()


def _path(value: Any, role: str) -> Path:
    if not isinstance(value, str) or not value:
        raise AnchorError(f"{role}.path is missing")
    return Path(value).expanduser()


def _stat_ref(path: Path, role: str, declared_sha: str | None = None) -> dict[str, Any]:
    if not path.is_file():
        raise AnchorError(f"{role} is missing: {path}")
    stat = path.stat()
    digest: str | None = None
    content_status = "PARENT_GUARD_REQUIRED"
    if stat.st_size <= SMALL_HASH_LIMIT:
        digest = _sha256(path)
        content_status = "CONTENT_SHA_OBSERVED"
        if declared_sha and declared_sha != digest:
            raise AnchorError(f"{role} declared SHA differs from current bytes")
    elif declared_sha:
        digest = declared_sha
        content_status = "PRODUCER_DECLARED_PARENT_RECHECK"
    return {
        "role": role,
        "path": str(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "mode_bits": int(stat.st_mode & 0o777),
        "sha256": digest,
        "content_sha_status": content_status,
        "content_read_by_planner": content_status == "CONTENT_SHA_OBSERVED",
    }


def _source_ref(value: Any, role: str, *, allow_missing: bool = False) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not isinstance(value.get("path"), str):
        if allow_missing:
            return {"role": role, "path": None, "status": "PENDING_PARENT_SOURCE_BINDING"}
        raise AnchorError(f"{role} source binding is missing")
    path = Path(str(value["path"])).expanduser()
    declared = value.get("sha256", value.get("recomputed_sha256"))
    return _stat_ref(path, role, declared if isinstance(declared, str) else None)


def _row(current: Mapping[str, Any], index: int) -> Mapping[str, Any]:
    if current.get("schema") != CURRENT_CATALOG_SCHEMA:
        raise AnchorError("CURRENT catalog schema is not current336.v1")
    if not isinstance(current.get("cases"), list) or len(current["cases"]) != 336:
        raise AnchorError("CURRENT catalog must contain 336 cases")
    if index < 0 or index >= len(current["cases"]):
        raise AnchorError("requested CURRENT index is out of range")
    value = current["cases"][index]
    if not isinstance(value, Mapping):
        raise AnchorError("CURRENT selected row is malformed")
    return value


def select_canonical(current: Mapping[str, Any], *, index: int = 65) -> Mapping[str, Any]:
    """Select the exact canonical row and reject known alias identities."""
    row = _row(current, index)
    identity = row.get("physical_case_id")
    if identity == HISTORICAL_ALIAS_ID or index == 78:
        raise AnchorError("historical unresolved F2 alias cannot be a canonical raw anchor")
    if index != 65 or identity != CANONICAL_ID:
        raise AnchorError("canonical F2 anchor must be CURRENT row 65 RX047/ROT075")
    if row.get("family_id") != "F2":
        raise AnchorError("selected anchor is not family F2")
    return row


def _catalog_row(catalog: Mapping[str, Any], index: int, case_id: str) -> Mapping[str, Any]:
    if catalog.get("schema") != CATALOG_SCHEMA:
        raise AnchorError("scoped catalog schema is not v6")
    rows = catalog.get("cases")
    if not isinstance(rows, list) or len(rows) != 336:
        raise AnchorError("scoped catalog must contain 336 cases")
    row = rows[index]
    if not isinstance(row, Mapping) or row.get("physical_case_id") != case_id:
        raise AnchorError("scoped catalog row does not bind the selected CURRENT case")
    identity = row.get("identity")
    lifecycle = row.get("lifecycle")
    if not isinstance(identity, Mapping) or identity.get("canonical_case_id") != case_id:
        raise AnchorError("selected catalog row is not canonical")
    if identity.get("identity_credit") is not True or identity.get("status") != "CANONICAL_CURRENT_SAVED_MASK":
        raise AnchorError("selected catalog row has no canonical saved-mask identity")
    if not isinstance(lifecycle, Mapping) or lifecycle.get("historical_alias") != "NONE":
        raise AnchorError("selected catalog row is an alias")
    if lifecycle.get("status") != "ACTUAL_SAVED_MASK_COMPLETED":
        raise AnchorError("selected catalog row is not completed saved-mask metadata")
    return row


def _physical_row(index_doc: Mapping[str, Any], index: int, case_id: str) -> Mapping[str, Any]:
    if index_doc.get("schema") != PHYSICAL_INDEX_SCHEMA:
        raise AnchorError("physical source index schema is not v27")
    rows = index_doc.get("cases")
    if not isinstance(rows, list) or len(rows) != 336:
        raise AnchorError("physical source index must contain 336 cases")
    row = rows[index]
    if not isinstance(row, Mapping) or row.get("physical_case_id") != case_id:
        raise AnchorError("v27 physical row does not bind selected case")
    if row.get("physical_union_status") != "UNKNOWN_PHYSICAL_UNASSIGNED":
        raise AnchorError("unexpected physical status; planner only accepts unknown/unassigned")
    return row


def _proof_row(proof: Mapping[str, Any], case_id: str) -> Mapping[str, Any]:
    if proof.get("schema") != PROOF_SCHEMA:
        raise AnchorError("actual proof schema is not root-actual-verification.v1")
    rows = [row for row in proof.get("case_verifications", [])
            if isinstance(row, Mapping) and row.get("physical_case_id") == case_id]
    if len(rows) != 1:
        raise AnchorError("actual proof does not contain exactly one selected case row")
    row = rows[0]
    if row.get("status") != "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY":
        raise AnchorError("selected proof row is not saved-mask diagnostic-only")
    return row


def _find_initial_csv(raw_root: Path) -> Path | None:
    # Restrict the name-only walk to the one case root; no file content is
    # opened.  Avoid a recursive DATA scan and stop after the first match.
    case_root = raw_root.parents[2] if len(raw_root.parents) >= 3 else raw_root.parent
    for directory, dirnames, filenames in __import__("os").walk(case_root):
        dirnames[:] = sorted(dirnames)[:64]
        if "initial.csv" in filenames:
            return Path(directory) / "initial.csv"
    return None


def _module_ref(repo_root: Path, role: str, filename: str) -> dict[str, Any]:
    path = repo_root / "lagrangian-fluid-lab" / "scripts" / filename
    if not path.is_file():
        raise AnchorError(f"required runtime module is missing: {path}")
    return {"role": role, "path": str(path), "sha256": _sha256(path)}


def _source_files(repo_root: Path, current_path: Path, row: Mapping[str, Any],
                  raw_root: Path) -> list[dict[str, Any]]:
    bindings = row.get("source_bindings")
    if not isinstance(bindings, Mapping):
        raise AnchorError("CURRENT source_bindings are missing")
    values: list[dict[str, Any]] = []
    values.append(_stat_ref(current_path, "current_catalog", CURRENT_SHA))
    values.append(_source_ref(row.get("manifest"), "manifest"))
    values.append(_source_ref(row.get("xmf"), "xmf"))
    values.append(_source_ref(bindings.get("generated_xml"), "generated_xml"))
    generated = Path(str(bindings["generated_xml"]["path"])).expanduser()
    motion = generated.with_name(generated.stem + "_motion.dat")
    if not motion.is_file():
        # Existing GenCase output sometimes uses the motion file beside the
        # XML with the case-name suffix.  A missing role stays deferred rather
        # than silently falling back to the alias template.
        motion = generated.parent / (generated.stem + ".dat")
    if motion.is_file():
        values.append(_stat_ref(motion, "motion_dat"))
    else:
        values.append({"role": "motion_dat", "path": None, "status": "PARENT_SOURCE_BINDING_REQUIRED"})
    for role in ("gencase_receipt", "solver_receipt", "owner_metadata"):
        values.append(_source_ref(bindings.get(role), role))
    conversion = row.get("conversion_report")
    values.append(_source_ref(conversion, "conversion_report"))
    initial = _find_initial_csv(raw_root)
    if initial is None:
        values.append({"role": "initial_csv", "path": None, "status": "PARENT_SOURCE_BINDING_REQUIRED"})
    else:
        values.append(_stat_ref(initial, "initial_csv"))
    solver_root = raw_root.parent
    values.append(_stat_ref(raw_root / "PartOut_000.obi4", "native_partout"))
    values.append(_stat_ref(solver_root / "RunPARTs.csv", "native_runparts"))
    return values


def _raw_binding(row: Mapping[str, Any]) -> tuple[dict[str, Any], Path]:
    raw_value = row.get("raw_root")
    if not isinstance(raw_value, Mapping) or not isinstance(raw_value.get("path"), str):
        raise AnchorError("CURRENT raw_root is missing")
    raw_root = Path(raw_value["path"]).expanduser()
    if not raw_root.is_dir():
        raise AnchorError(f"raw root is missing: {raw_root}")
    frames = sorted(raw_root.glob("Part_[0-9][0-9][0-9][0-9].bi4"))
    if len(frames) != int(row.get("frames", -1)):
        raise AnchorError("raw frame count does not match CURRENT")
    records = []
    for index, path in enumerate(frames):
        if path.name != f"Part_{index:04d}.bi4":
            raise AnchorError("raw frame names are not contiguous top-level Part paths")
        stat = path.stat()
        records.append({"frame": index, "path": str(path), "bytes": int(stat.st_size),
                        "mtime_ns": int(stat.st_mtime_ns), "sha256": PENDING,
                        "content_sha_status": "PARENT_GUARD_REQUIRED"})
    observed_names = sorted(path.name for path in raw_root.iterdir())
    required_aux = [name for name in ("PartInfo.ibi4", "PartOut_000.obi4", "PartMotionRef.ibi4")
                    if name in observed_names]
    return {
        "data_root": str(raw_root), "frame_count": len(records), "expected_file_count": len(observed_names),
        "frame_pattern": "Part_%04d.bi4", "frames": records,
        "expected_raw_tree_sha256": PENDING,
        "source_tree_hash_basis": "all observed top-level names/stat plus content; parent hashes after reservation",
        "auxiliary_entries_stat_only": required_aux,
        "content_hash_status": "PARENT_GUARD_REQUIRED",
    }, raw_root


def _request_source_records(source_bindings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert plan refs to the worker's source-file shape without guessing."""
    records: list[dict[str, Any]] = []
    for item in source_bindings:
        record = {key: item[key] for key in ("role", "path", "sha256", "bytes", "mtime_ns")
                  if key in item}
        if record.get("path") is None:
            # Keep the unresolved role visible to the parent builder, but do
            # not silently substitute a path from the historical alias.
            record["status"] = item.get("status", "PARENT_SOURCE_BINDING_REQUIRED")
        records.append(record)
    return records


def _request_skeleton(template_path: Path | None, *, row: Mapping[str, Any], current_path: Path,
                      modules: Mapping[str, Any], raw: Mapping[str, Any],
                      sources: list[dict[str, Any]], plan_id: str) -> dict[str, Any]:
    if template_path is not None:
        request = _load(template_path, "historical worker request template")
    else:
        request = {}
    request = copy.deepcopy(request)
    case_id = str(row["physical_case_id"])
    request.update({
        "schema": REQUEST_SCHEMA,
        "request_id": f"f2-s1-canonical-raw-to-typed-label-v2-{plan_id}",
        "role": "DEVELOPMENT",
        "status": "PENDING_PARENT_GUARD",
        "case_identity": {
            "current_case_index": 65, "family_id": "F2",
            "manifest_case_id": row.get("runtime_case_alias"),
            "manifest_physical_case_id": case_id,
            "physical_case_id": case_id,
            "runtime_case_alias": row.get("runtime_case_alias"),
        },
        "current_binding": {
            "binding_status": "EXACT_CURRENT_ROW",
            "case_index": 65, "path": str(current_path), "sha256": CURRENT_SHA,
            "frames": row.get("frames"), "particles": row.get("particles"),
            "actual_time_window_s": row.get("actual_time_window_s"),
            "identity_key": "(Zone,Idp)",
        },
        "modules": dict(modules),
        "source_files": _request_source_records(sources),
        "raw_binding": dict(raw),
        "source_hashes_preverified_by_parent": True,
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": dict(UNKNOWN_QUALIFICATION),
        "evidence_scope": {
            "status": "PARENT_GUARD_REQUIRED",
            "raw_tree_sha256": "PENDING_PARENT_GUARD_CONTENT_SHA256",
            "scientific_payload_read_by_planner": False,
            "historical_alias_fallback": False,
        },
        "execution": {
            "python": "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
            "requires_parent_stage2guard": True,
            "no_h5_copy_by_worker": False,
            "no_model_or_cfd": True,
            "command_template": [
                "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
                "-B", "-I", "<bound_worker_path>", "run", "--request", "<bound_request_path>",
                "--output-dir", "<fresh_attempt_root>", "--io-slot-approved",
            ],
        },
    })
    # Nested old v15 requests often contain actionable alias paths.  Preserve
    # only their provenance, never an executable path that could fall back to
    # row 78 or an old consumer worktree.
    request["v15_request"] = {
        "status": "PARENT_GUARD_SOURCE_REBIND_REQUIRED",
        "historical_template_path": str(template_path) if template_path else None,
        "source_fallback_forbidden": True,
        "canonical_case_id": case_id,
    }
    return request


def build_plan(*, current_path: Path, catalog_path: Path, physical_index_path: Path,
               proof_path: Path, repo_root: Path, output_dir: Path, template_path: Path | None = None,
               index: int = 65) -> dict[str, Any]:
    current = _load(current_path, "CURRENT336")
    if _sha256(current_path) != CURRENT_SHA:
        raise AnchorError("CURRENT336 SHA is not the pinned current source")
    row = select_canonical(current, index=index)
    case_id = str(row["physical_case_id"])
    catalog = _load(catalog_path, "scoped catalog")
    catalog_row = _catalog_row(catalog, index, case_id)
    physical_index = _load(physical_index_path, "v27 physical index")
    physical_row = _physical_row(physical_index, index, case_id)
    proof = _load(proof_path, "ROOT206 actual proof")
    proof_row = _proof_row(proof, case_id)
    raw, raw_root = _raw_binding(row)
    sources = _source_files(repo_root, current_path, row, raw_root)
    modules = {
        "raw_converter": _module_ref(repo_root, "raw_converter", "ds_data02_f5_bi4.py"),
        "v14_operator": _module_ref(repo_root, "v14_operator", "ds_data02_stage2_f2_replay_v14.py"),
        "v15_operator": _module_ref(repo_root, "v15_operator", "ds_data02_stage2_f2_replay_v15.py"),
        "v16_operator": _module_ref(repo_root, "v16_operator", "ds_data02_stage2_f2_flux_v16.py"),
        "worker": _module_ref(repo_root, "worker", "ds_data02_stage2_f2_native_raw_to_typed_label_v2.py"),
    }
    plan_id = "f2-s1-canonical-raw-anchor-v2-root-forward-pending"
    request = _request_skeleton(template_path, row=row, current_path=current_path,
                                modules=modules, raw=raw, sources=sources, plan_id=plan_id)
    plan = {
        "schema": SCHEMA,
        "plan_id": plan_id,
        "status": "DEVELOPMENT_SOURCE_BOUND_PLAN; PARENT_GUARD_REQUIRED",
        "selection": {"family_id": "F2", "current_index": index, "physical_case_id": case_id,
                      "runtime_case_alias": row.get("runtime_case_alias"),
                      "historical_alias_rejected": HISTORICAL_ALIAS_ID,
                      "selection_rule": "exact CURRENT336 row 65; no latest/glob/alias fallback"},
        "current_binding": {"path": str(current_path), "sha256": CURRENT_SHA,
                            "schema": CURRENT_CATALOG_SCHEMA, "case_count": 336,
                            "row": {"frames": row.get("frames"), "particles": row.get("particles"),
                                    "time_window_s": row.get("actual_time_window_s"),
                                    "known_numeric_physical_parameters": row.get("known_numeric_physical_parameters", {})}},
        "catalog_binding": {"path": str(catalog_path), "sha256": _sha256(catalog_path),
                             "schema": CATALOG_SCHEMA,
                             "identity_status": catalog_row.get("identity", {}).get("status"),
                             "source_join_status": catalog_row.get("source_join_status")},
        "physical_policy_binding": {"path": str(physical_index_path), "sha256": _sha256(physical_index_path),
                                     "schema": PHYSICAL_INDEX_SCHEMA,
                                     "physical_union_group_id": physical_row.get("physical_union_group_id_v27"),
                                     "physical_union_status": physical_row.get("physical_union_status"),
                                     "split_safe": False},
        "actual_lifecycle_binding": {"path": str(proof_path), "sha256": _sha256(proof_path),
                                      "schema": PROOF_SCHEMA,
                                      "proof_row_status": proof_row.get("status"),
                                      "scientific_credit": "NONE_SAVED_MASK_DIAGNOSTIC_ONLY"},
        "source_bindings": sources,
        "modules": modules,
        "raw_binding": raw,
        "request_overlay": {
            "schema": REQUEST_SCHEMA,
            "template_path": str(template_path) if template_path else None,
            "status": "PENDING_PARENT_GUARD_CONTENT_AND_SOURCE_SHA",
            "validation": "not_worker_ready_until_parent fills raw tree/frame/large source hashes",
            "no_original_path_fallback": True,
            "request": request,
        },
        "typed_contract": {"identity_key": "(Zone,Idp)",
                           "fields": ["position", "velocity", "density", "mass", "pressure", "valid", "type", "mk"],
                           "all_fluid_initial_identity": "source-bound initial.csv; content deferred to parent guard",
                           "comparison": "exact identity/structural and finite numeric field checks; no fabricated errors"},
        "label_contract": {"v15_v16": "source-bound only after typed raw comparison", "model_invoked": False,
                           "cfd_invoked": False, "qualification": UNKNOWN_QUALIFICATION},
        "resource_contract": {"raw_tree_hash_passes": 2, "frame_content_hashes": 401,
                              "scratch": "attempt-owned; parent must account peak bytes", "max_wall_seconds": 3600,
                              "storage": "parent computes from stat and actual outputs; no lowball estimate"},
        "unknowns": ["raw content/tree hash pending parent guard", "typed arrays and labels not read",
                     "physical owner/geometry/fate/dynamics unknown", "split safety false", "QI/QN/QE UNKNOWN"],
        "model_invoked": False, "cfd_invoked": False, "qualification": UNKNOWN_QUALIFICATION,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_path = output_dir / "f2-s1-canonical-raw-anchor-plan-v2.json"
    if plan_path.exists():
        raise AnchorError(f"refusing to overwrite {plan_path}")
    plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    request_path = output_dir / "f2-s1-canonical-raw-anchor-request-v2.json"
    if request_path.exists():
        raise AnchorError(f"refusing to overwrite {request_path}")
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    plan["request_overlay"]["path"] = str(request_path)
    # Update the already-written plan with the request path; this is a new
    # output pair, never an in-place mutation of an older request.
    plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return plan


def validate_plan(path: Path, *, expected_current_sha: str = CURRENT_SHA) -> dict[str, Any]:
    plan = _load(path, "canonical anchor plan")
    if plan.get("schema") != SCHEMA:
        raise AnchorError("unexpected anchor plan schema")
    selection = plan.get("selection")
    if not isinstance(selection, Mapping) or selection.get("current_index") != 65:
        raise AnchorError("plan does not select canonical CURRENT row 65")
    if selection.get("physical_case_id") != CANONICAL_ID:
        raise AnchorError("plan identity is not canonical F2")
    if selection.get("historical_alias_rejected") != HISTORICAL_ALIAS_ID:
        raise AnchorError("plan does not record historical alias rejection")
    if plan.get("current_binding", {}).get("sha256") != expected_current_sha:
        raise AnchorError("plan CURRENT binding differs")
    if plan.get("raw_binding", {}).get("expected_raw_tree_sha256") != PENDING:
        raise AnchorError("source-only plan must defer raw tree hash")
    if plan.get("request_overlay", {}).get("status") != "PENDING_PARENT_GUARD_CONTENT_AND_SOURCE_SHA":
        raise AnchorError("plan cannot claim worker-ready content")
    if plan.get("qualification") != UNKNOWN_QUALIFICATION:
        raise AnchorError("plan qualification must remain UNKNOWN")
    return {"schema": SCHEMA, "status": plan.get("status"), "canonical": True,
            "current_index": 65, "raw_content_hash_status": "PARENT_GUARD_REQUIRED",
            "qualification": UNKNOWN_QUALIFICATION}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    build = sub.add_parser("build")
    build.add_argument("--current", type=Path, required=True)
    build.add_argument("--catalog", type=Path, required=True)
    build.add_argument("--physical-index", type=Path, required=True)
    build.add_argument("--proof", type=Path, required=True)
    build.add_argument("--repo-root", type=Path, required=True)
    build.add_argument("--output-dir", type=Path, required=True)
    build.add_argument("--template", type=Path)
    build.add_argument("--index", type=int, default=65)
    validate = sub.add_parser("validate")
    validate.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "validate":
            result = validate_plan(args.plan)
        else:
            result = build_plan(current_path=args.current, catalog_path=args.catalog,
                                physical_index_path=args.physical_index, proof_path=args.proof,
                                repo_root=args.repo_root, output_dir=args.output_dir,
                                template_path=args.template, index=args.index)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    except AnchorError as error:
        print(f"canonical F2 raw anchor: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
