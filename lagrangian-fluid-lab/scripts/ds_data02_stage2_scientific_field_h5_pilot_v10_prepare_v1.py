#!/usr/bin/env python3
"""Prepare seven independent, source-bound V10 H5 pilot requests.

The existing seven-case index is useful for selecting one representative from
each family, but it is not an executable admission unit.  This builder splits
that index into seven immutable single-case requests.  It reads only bounded
JSON/source metadata and HDF5 ``stat`` records.  A trajectory HDF5 is never
opened or hashed here; its producer SHA is carried as a deferred parent guard
obligation.

The output is deliberately still ``SOURCE_PREPARED`` and carries no
scientific credit.  A parent must reserve the requested CPU and the split
Home/external storage budget before validating the deferred HDF5 content.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any


SCRIPT = Path(__file__).resolve()
REQUEST_SCHEMA = "ds02.request.v1"
MANIFEST_SCHEMA = "ds02.stage2.scientific-field-h5-pilot-manifest.v10"
INDEX_SCHEMA = "ds02.stage2.scientific-field-h5-pilot-request-index.v1"
REPORT_SCHEMA = "ds02.stage2.scientific-field-h5-pilot-source-report.v1"
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
MAX_JSON_BYTES = 10 * 1024 * 1024
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_STATIC_BYTES = 10 * 1024 * 1024
SCRATCH_BYTES = 512 * 1024 * 1024
LOG_BYTES = 8 * 1024 * 1024
HOME_HEADROOM_BYTES = 512 * 1024 * 1024
EXTERNAL_HEADROOM_BYTES = 20 * 1024**3
H5_SUFFIXES = {".h5", ".hdf5"}
PAYLOAD_SUFFIXES = H5_SUFFIXES | {
    ".bi4", ".obi4", ".ibi4", ".vtk", ".vtu", ".vtp", ".xmf",
    ".xdmf", ".csv", ".jsonl", ".npy", ".npz", ".raw", ".bin",
}
PILOT_FAMILIES = ("F1", "F2", "F3", "F4", "F5", "F6", "F7")


class PilotPrepareError(ValueError):
    """The source package cannot be admitted as a V10 pilot request."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise PilotPrepareError(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(char not in "0123456789abcdef" for char in value):
        raise PilotPrepareError(f"{label} is not hexadecimal")
    return value


def bounded_file(value: Any, label: str, *, max_bytes: int = MAX_JSON_BYTES) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not value:
        raise PilotPrepareError(f"{label} lacks a path")
    raw = Path(value).expanduser()
    if raw.is_symlink():
        raise PilotPrepareError(f"{label} must not be a symlink: {raw}")
    path = raw.resolve()
    if not path.is_file():
        raise PilotPrepareError(f"{label} is missing: {path}")
    if path.stat().st_size > max_bytes:
        raise PilotPrepareError(f"{label} exceeds the bounded {max_bytes}-byte limit: {path}")
    return path


def read_json(value: Any, label: str, *, max_bytes: int = MAX_JSON_BYTES) -> tuple[Path, dict[str, Any]]:
    path = bounded_file(value, label, max_bytes=max_bytes)
    before = file_stat(path, label)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PilotPrepareError(f"{label} is not bounded JSON") from exc
    after = file_stat(path, label)
    if before != after:
        raise PilotPrepareError(f"{label} changed while being read")
    if not isinstance(document, dict):
        raise PilotPrepareError(f"{label} must contain an object")
    return path, document


def file_stat(path: Path, label: str = "file") -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise PilotPrepareError(f"{label} is not a regular non-symlink file: {path}")
    value = path.stat()
    return {
        "path": str(path),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
    }


def static_ref(value: Any, role: str, *, expected_sha: str | None = None) -> dict[str, Any]:
    path = bounded_file(value, role, max_bytes=MAX_STATIC_BYTES)
    if path.suffix.lower() in PAYLOAD_SUFFIXES:
        raise PilotPrepareError(f"{role} is a payload, not a static source: {path}")
    before = file_stat(path, role)
    actual = sha256_file(path)
    after = file_stat(path, role)
    if before != after:
        raise PilotPrepareError(f"{role} changed while being hashed: {path}")
    if expected_sha is not None and actual != digest(expected_sha, f"{role} expected SHA"):
        raise PilotPrepareError(f"{role} content SHA differs: {path}")
    before.update({"role": role, "sha256": actual, "content_read_by_preparer": True})
    return before


def deferred_h5(value: Any, case_id: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PilotPrepareError(f"{case_id}: trajectory_h5 metadata is missing")
    raw = value.get("path")
    if not isinstance(raw, (str, os.PathLike)) or not raw:
        raise PilotPrepareError(f"{case_id}: trajectory_h5 path is missing")
    path = Path(raw).expanduser()
    if path.is_symlink():
        raise PilotPrepareError(f"{case_id}: trajectory_h5 is a symlink")
    path = path.resolve()
    if path.suffix.lower() not in H5_SUFFIXES:
        raise PilotPrepareError(f"{case_id}: trajectory_h5 is not HDF5")
    # stat(2) is the only operation allowed on deferred scientific payloads.
    observed = file_stat(path, f"{case_id} trajectory_h5")
    for key in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        if key in value and int(value[key]) != int(observed[key]):
            raise PilotPrepareError(f"{case_id}: HDF5 stat changed at {key}")
    known = digest(value.get("known_sha256") or value.get("sha256"), f"{case_id} deferred HDF5 known SHA")
    observed.update({
        "known_sha256": known,
        "deferred_after_parent_reservation": True,
        "content_read_by_preparer": False,
        "known_sha_source": value.get("known_sha_source", "frozen producer evidence"),
    })
    return observed


def atomic_json(path: Path, value: dict[str, Any], *, max_bytes: int = MAX_JSON_BYTES) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise PilotPrepareError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > max_bytes:
            raise PilotPrepareError(f"output exceeds bounded JSON limit: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _path_from_ref(ref: Any, label: str) -> Path:
    if not isinstance(ref, dict):
        raise PilotPrepareError(f"{label} is not a source reference")
    return bounded_file(ref.get("path"), label, max_bytes=MAX_STATIC_BYTES)


def _ref_key(ref: dict[str, Any]) -> str:
    return str(Path(ref["path"]).expanduser().resolve())


def _dedupe_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for ref in refs:
        path = _ref_key(ref)
        sha = digest(ref.get("sha256"), f"source ref {path} SHA")
        old = merged.get(path)
        if old is not None and old["sha256"] != sha:
            raise PilotPrepareError(f"conflicting SHA for source ref {path}")
        merged[path] = {**ref, "path": path, "sha256": sha}
    return [merged[path] for path in sorted(merged)]


def _rebind_path(value: Any, args: argparse.Namespace) -> tuple[Any, str | None]:
    """Apply only an explicitly supplied old-checkout prefix replacement."""
    if not isinstance(value, (str, os.PathLike)) or not value:
        return value, None
    raw = str(Path(value).expanduser())
    old = str(Path(args.source_rebind_from).expanduser()).rstrip("/") if args.source_rebind_from else None
    new = str(Path(args.source_rebind_to).expanduser()).rstrip("/") if args.source_rebind_to else None
    if not old or not new or not (raw == old or raw.startswith(old + "/")):
        return value, None
    return new + raw[len(old):], raw


def _source_refs_from_pilot(pilot: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    refs = pilot.get("static_source_refs")
    if not isinstance(refs, list) or not refs:
        raise PilotPrepareError("pilot index lacks static_source_refs")
    checked: list[dict[str, Any]] = []
    for item in refs:
        if not isinstance(item, dict):
            raise PilotPrepareError("pilot static source ref is not an object")
        role = str(item.get("role") or "pilot static source")
        rebound, provenance = _rebind_path(item.get("path"), args)
        checked_ref = static_ref(rebound, role, expected_sha=None if provenance else item.get("sha256"))
        if provenance is not None:
            checked_ref["provenance_path"] = provenance
            checked_ref["rebound_from_explicit_prefix"] = True
        checked.append(checked_ref)
    return checked


def _current_binding(path: Path, document: dict[str, Any]) -> dict[str, Any]:
    if document.get("schema") != CURRENT_SCHEMA or not isinstance(document.get("cases"), list) or len(document["cases"]) != 336:
        raise PilotPrepareError("CURRENT is not the frozen 336-case catalog")
    current_sha = sha256_file(path)
    if current_sha != CURRENT_SHA256:
        raise PilotPrepareError("CURRENT SHA differs from frozen CURRENT336")
    return {**file_stat(path, "CURRENT336"), "role": "current336", "sha256": current_sha, "content_read_by_preparer": True, "cases": 336, "alias_excluded": True}


def _find_current_row(current: dict[str, Any], case_id: str) -> dict[str, Any]:
    rows = [row for row in current.get("cases", []) if isinstance(row, dict) and row.get("physical_case_id") == case_id]
    if len(rows) != 1:
        raise PilotPrepareError(f"CURRENT has no unique row for {case_id}")
    return rows[0]


def _core_refs(args: argparse.Namespace) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for path, role in (
        (SCRIPT, "pilot_v10_request_builder"),
        (args.worker, "scientific_field_h5_worker_v3"),
        (args.verifier, "scientific_field_h5_verifier_v5"),
        (args.runtime_v10, "runtime_v10_git_bound"),
        (args.dispatch, "dispatch_v9"),
        (args.strict_dispatch, "strict_dispatch_v9"),
        (args.config, "official_runtime_config"),
    ):
        refs.append(static_ref(path, role))
    literal = Path(args.python).expanduser()
    # The pinned environment entrypoint is intentionally a symlink on this
    # host.  Preserve that literal argv[0], while hashing/stat'ing only its
    # resolved interpreter target as provenance; resolving argv[0] itself
    # would silently switch the runtime ABI to a system Python.
    if not literal.exists() or not literal.resolve().is_file():
        raise PilotPrepareError(f"literal Python is unavailable: {literal}")
    python_ref = static_ref(literal.resolve(), "literal_python")
    python_ref["literal_path"] = str(literal)
    # argv[0] intentionally retains the literal environment path.  This is
    # separate from the resolved/stat provenance path and prevents an ABI
    # symlink from silently becoming /usr/bin/python.
    python_ref["resolved_path"] = str(Path(python_ref["path"]))
    refs.append(python_ref)
    return refs


def _case_from_pilot(case: dict[str, Any], current: dict[str, Any], case_id: str, args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if case.get("physical_case_id") != case_id:
        raise PilotPrepareError("pilot case identity differs from its selection")
    current_row = _find_current_row(current, case_id)
    family = case.get("family_id")
    if not isinstance(family, str) or current_row.get("family_id") != family:
        raise PilotPrepareError(f"{case_id}: family differs from CURRENT")
    trajectory = deferred_h5(case.get("trajectory_h5"), case_id)
    refs: list[dict[str, Any]] = []
    missing_manifest = case.get("case_manifest") is None
    for field in ("producer_terminal_proof", "producer_receipt", "typed_summary"):
        ref = case.get(field)
        if not isinstance(ref, dict):
            raise PilotPrepareError(f"{case_id}: missing {field}")
        rebound, provenance = _rebind_path(ref.get("path"), args)
        checked_ref = static_ref(rebound, f"{case_id} {field}", expected_sha=None if provenance else ref.get("sha256"))
        if provenance is not None:
            checked_ref["provenance_path"] = provenance
            checked_ref["rebound_from_explicit_prefix"] = True
        refs.append(checked_ref)
    manifest_ref = None
    if not missing_manifest:
        ref = case["case_manifest"]
        rebound, provenance = _rebind_path(ref.get("path"), args)
        manifest_ref = static_ref(rebound, f"{case_id} case_manifest", expected_sha=None if provenance else ref.get("sha256"))
        if provenance is not None:
            manifest_ref["provenance_path"] = provenance
            manifest_ref["rebound_from_explicit_prefix"] = True
        refs.append(manifest_ref)
    elif case.get("case_manifest_status") not in (None, "UNKNOWN_MISSING_MANIFEST", "NOT_EXPOSED_BY_PRODUCER"):
        raise PilotPrepareError(f"{case_id}: unsupported missing case manifest status")
    selected = {
        **case,
        "trajectory_h5": trajectory,
        "case_manifest": manifest_ref,
        "case_manifest_status": "UNKNOWN_MISSING_MANIFEST" if missing_manifest else "BOUND",
        "source_content_read_by_preparer": False,
        "scientific_credit": 0,
        "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
        "current_index": current_row.get("current_index"),
        "pilot_current_row": {"family_id": current_row.get("family_id"), "frames": current_row.get("frames"), "particles": current_row.get("particles")},
    }
    return selected, refs


def _cost(case: dict[str, Any], static_refs: list[dict[str, Any]], *, max_memory: int) -> dict[str, Any]:
    h5_bytes = int(case["trajectory_h5"]["bytes"])
    minimum_passes = 3
    h5_read = h5_bytes * minimum_passes
    static_bytes = sum(int(item["bytes"]) for item in static_refs)
    external = h5_read + SCRATCH_BYTES + EXTERNAL_HEADROOM_BYTES
    home = MAX_OUTPUT_BYTES + LOG_BYTES + HOME_HEADROOM_BYTES
    total = external + home
    return {
        "deferred_h5_bytes": h5_bytes,
        "minimum_h5_passes": minimum_passes,
        "estimated_h5_read_bytes": h5_read,
        "static_source_bytes": static_bytes,
        "scratch_bytes": SCRATCH_BYTES,
        "log_bytes": LOG_BYTES,
        "output_cap_bytes": MAX_OUTPUT_BYTES,
        "home_storage_bytes": home,
        "external_storage_bytes": external,
        "estimated_storage_bytes": total,
        "estimated_memory_bytes": max_memory,
        "conservative_headroom": {"home_bytes": HOME_HEADROOM_BYTES, "external_bytes": EXTERNAL_HEADROOM_BYTES},
        "h5_content_read_by_preparer": False,
    }


def _request_for_case(
    args: argparse.Namespace,
    output_dir: Path,
    family: str,
    selected: dict[str, Any],
    static_refs: list[dict[str, Any]],
    manifest_ref: dict[str, Any],
    cost: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    case_id = str(selected["physical_case_id"])
    case_dir = output_dir / f"{family}-{case_id}"
    manifest_path = case_dir / "scientific-field-h5-pilot-manifest.json"
    request_path = case_dir / "scientific-field-h5-pilot-request.json"
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "READY_FOR_GUARDED_SINGLE_CASE_RAW_H5_FIELD_AUDIT",
        "pilot_scope": {"family_id": family, "physical_case_id": case_id, "one_case_only": True, "historical_alias_excluded": True},
        "current_catalog": args.current_binding,
        "source_contract": {
            "source_manifest": args.source_manifest_ref,
            "pilot_index": args.pilot_index_ref,
            "plan": args.plan_ref,
            "registry": args.registry_ref,
        },
        "static_source_refs": static_refs,
        "cases": [selected],
        "worker_contract": {
            "worker_version": "v3_vectorized_postread_guard",
            "runtime_version": "v10_git_bound",
            "sequential_cases": True,
            "bounded_memory": True,
            "required_static_datasets": ["time", "particle_id", "particle_zone", "initial_type", "initial_mass"],
            "required_frame_datasets": ["position", "velocity", "density", "mass", "pressure", "valid", "type"],
            "post_guard": "final HDF5 stat/hash after all deferred datasets are read",
        },
        "read_policy": {
            "prepare_json_and_stat_only": True,
            "trajectory_h5_opened_by_preparer": False,
            "trajectory_h5_hashed_by_preparer": False,
            "trajectory_h5_opened_after_parent_reservation": True,
            "raw_bi4_opened": False,
            "solver_started": False,
        },
        "claim_boundary": {
            "scientific_credit": 0, "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
            "units": "DECLARED_ONLY_UNVERIFIED", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN",
        },
        "source_read_cost": cost,
    }
    atomic_json(manifest_path, manifest)
    manifest_ref = static_ref(manifest_path, "single-case V10 manifest")
    all_refs = _dedupe_refs([*static_refs, manifest_ref])
    input_files = [item["path"] for item in all_refs]
    input_sha = {item["path"]: item["sha256"] for item in all_refs}
    literal_python = str(Path(args.python).expanduser())
    request = {
        "schema": REQUEST_SCHEMA,
        "request_id": f"scientific-field-h5-pilot-v10-{family}-{case_id}",
        "attempt_id": f"scientific-field-h5-pilot-v10-{family}-{case_id}",
        "family_id": family,
        "case_id": case_id,
        "physical_case_ids": [case_id],
        "kind": "cpu", "cpu_task_kind": "scientific_field_h5_audit",
        "cpu_threads": 1, "omp_threads": 1,
        "max_wall_seconds": int(args.max_wall_seconds), "max_memory_bytes": int(args.max_memory_bytes),
        "cwd": str(args.lab_root), "worktree_root": str(args.worktree_root),
        "command": [literal_python, "-B", str(Path(args.worker).expanduser().resolve()), "audit", "--manifest", str(manifest_path.resolve()), "--output", "{attempt_root}/scientific-field-h5-audit.json", "--chunk", str(args.chunk)],
        "input_files": input_files, "input_sha256": input_sha,
        "deferred_input_files": [selected["trajectory_h5"]["path"]],
        "deferred_input_records": [selected["trajectory_h5"]],
        "output_files": ["{attempt_root}/scientific-field-h5-audit.json"],
        "manifest_contract": {"path": str(manifest_path.resolve()), "sha256": manifest_ref["sha256"]},
        "interpreter_binding": {"literal_path": literal_python, "resolved_path": str(Path(literal_python).resolve()), "sha256": next(item["sha256"] for item in all_refs if item.get("path") == str(Path(literal_python).resolve()))},
        "runtime_binding": {
            "runtime_v10_git_bound": next(item for item in all_refs if item.get("role") == "runtime_v10_git_bound"),
            "dispatch_v9": next(item for item in all_refs if item.get("role") == "dispatch_v9"),
            "strict_dispatch_v9": next(item for item in all_refs if item.get("role") == "strict_dispatch_v9"),
            "official_config": next(item for item in all_refs if item.get("role") == "official_runtime_config"),
        },
        "storage_scope": {
            "schema": "ds02.storage-scope.v1",
            "home_storage_bytes": cost["home_storage_bytes"],
            "external_storage_bytes": cost["external_storage_bytes"],
            "estimated_storage_bytes": cost["estimated_storage_bytes"],
            "home_headroom_bytes": HOME_HEADROOM_BYTES,
            "external_headroom_bytes": EXTERNAL_HEADROOM_BYTES,
            "legacy_scope_defaulted": False,
        },
        "source_read_cost": {**cost, "family": family, "case_count": 1},
        "read_policy": manifest["read_policy"], "claim_boundary": manifest["claim_boundary"],
        "launch_allowed": True, "execution_allowed": True, "launch_owner": "root", "shared_lease_required": True,
        "status": "SOURCE_PREPARED_SINGLE_CASE_V10_NOT_RUN",
        "scientific_credit": 0,
        "request_note": "Single-case source closure only. Parent reservation, deferred HDF5 content hash, post-read stat/hash, and independent V5 verification are mandatory; no qualification is claimed.",
    }
    atomic_json(request_path, request)
    return request_path, request


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    pilot_index_path, pilot = read_json(args.pilot_index, "seven-family pilot index")
    if pilot.get("schema") != "ds02.stage2.scientific-field-h5-audit-manifest.v2":
        raise PilotPrepareError("pilot index schema is not the frozen seven-family audit manifest")
    cases = pilot.get("cases")
    if not isinstance(cases, list) or len(cases) != 7:
        raise PilotPrepareError("pilot index must contain exactly seven cases")
    by_family: dict[str, dict[str, Any]] = {}
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("family_id"), str):
            raise PilotPrepareError("pilot case is invalid")
        family = str(case["family_id"])
        if family in by_family:
            raise PilotPrepareError(f"duplicate family in pilot index: {family}")
        by_family[family] = case
    if set(by_family) != set(PILOT_FAMILIES):
        raise PilotPrepareError("pilot index does not cover F1..F7 exactly")
    current_path, current = read_json(args.current, "CURRENT336")
    current_binding = _current_binding(current_path, current)
    source_manifest_path, source_manifest = read_json(args.source_manifest, "335 source manifest")
    if source_manifest.get("schema") != "ds02.stage2.scientific-field-h5-batch-source.v1" or len(source_manifest.get("cases", [])) != 335:
        raise PilotPrepareError("source manifest is not the canonical 335-case index")
    plan_path, plan = read_json(args.plan, "typed lifecycle plan")
    registry_path, registry = read_json(args.registry, "typed lifecycle registry")
    if not isinstance(plan.get("schema"), str) or not isinstance(registry.get("schema"), str):
        raise PilotPrepareError("plan/registry metadata schema is missing")
    args.current_binding = current_binding
    args.pilot_index_ref = static_ref(pilot_index_path, "seven-family pilot index")
    args.source_manifest_ref = static_ref(source_manifest_path, "335 source manifest")
    args.plan_ref = static_ref(plan_path, "typed lifecycle plan")
    args.registry_ref = static_ref(registry_path, "typed lifecycle registry")
    args.primary_pilot_refs = _source_refs_from_pilot(pilot, args)
    common = _dedupe_refs([args.current_binding, args.pilot_index_ref, args.source_manifest_ref, args.plan_ref, args.registry_ref, *args.primary_pilot_refs, *_core_refs(args)])
    output_dir = Path(args.output_dir).expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise PilotPrepareError(f"refusing non-empty fresh output namespace: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=False)
    rows: list[dict[str, Any]] = []
    for family in PILOT_FAMILIES:
        selected, case_refs = _case_from_pilot(by_family[family], current, str(by_family[family]["physical_case_id"]), args)
        refs = _dedupe_refs([*common, *case_refs])
        cost = _cost(selected, refs, max_memory=int(args.max_memory_bytes))
        # The manifest itself is created inside _request_for_case, so all
        # pre-manifest refs are also independently present in the request.
        request_path, request = _request_for_case(args, output_dir, family, selected, refs, {}, cost)
        # _request_for_case returns the final manifest contract; record it by
        # reading only the small generated request, not any scientific file.
        rows.append({
            "family_id": family, "physical_case_id": selected["physical_case_id"],
            "case_manifest_status": selected["case_manifest_status"],
            "request": {"path": str(request_path), "sha256": sha256_file(request_path)},
            "manifest": request.get("manifest_contract"),
            "deferred_h5": {"path": selected["trajectory_h5"]["path"], "bytes": selected["trajectory_h5"]["bytes"], "known_sha256": selected["trajectory_h5"]["known_sha256"], "content_read_by_preparer": False},
            "source_read_cost": cost,
            "scientific_credit": 0,
            "production_eligible": False,
        })
    index = {
        "schema": INDEX_SCHEMA,
        "status": "SOURCE_PREPARED_SEVEN_SINGLE_CASE_V10_NOT_RUN",
        "pilot_count": 7, "families": list(PILOT_FAMILIES), "requests": rows,
        "current_binding": current_binding,
        "source_contract": {"pilot_index": args.pilot_index_ref, "source_manifest": args.source_manifest_ref, "plan": args.plan_ref, "registry": args.registry_ref},
        "runtime_contract": {"runtime_version": "v10_git_bound", "literal_python": str(Path(args.python).expanduser()), "source_fallback": False},
        "read_policy": {"metadata_only": True, "trajectory_h5_opened": False, "trajectory_h5_hashed": False, "bi4_opened": False, "solver_started": False, "launch_performed": False},
        "qualification_boundary": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0},
        "source_read_cost": {"cases": 7, "estimated_h5_read_bytes": sum(row["source_read_cost"]["estimated_h5_read_bytes"] for row in rows), "estimated_storage_bytes": sum(row["source_read_cost"]["estimated_storage_bytes"] for row in rows), "one_case_at_a_time": True, "f2_missing_manifest_isolated_unknown": any(row["family_id"] == "F2" and row["case_manifest_status"] == "UNKNOWN_MISSING_MANIFEST" for row in rows)},
    }
    index_path = output_dir / "scientific-field-h5-pilot-v10-request-index.json"
    atomic_json(index_path, index)
    report = {"schema": REPORT_SCHEMA, "status": index["status"], "index": {"path": str(index_path), "sha256": sha256_file(index_path)}, "request_count": 7, "case_count": 7, "production_eligible": False, "scientific_credit": 0, "read_policy": index["read_policy"], "claim_boundary": index["qualification_boundary"]}
    report_path = output_dir / "scientific-field-h5-pilot-v10-source-report.json"
    atomic_json(report_path, report)
    return {"status": index["status"], "index": str(index_path), "index_sha256": sha256_file(index_path), "report": str(report_path), "report_sha256": sha256_file(report_path), "requests": 7, "estimated_h5_read_bytes": index["source_read_cost"]["estimated_h5_read_bytes"], "scientific_credit": 0}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    root_default = SCRIPT.parents[2]
    stage2_default = root_default / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
    parser.add_argument("--pilot-index", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--verifier", type=Path, required=True)
    parser.add_argument("--runtime-v10", type=Path, required=True)
    parser.add_argument("--dispatch", type=Path, required=True)
    parser.add_argument("--strict-dispatch", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--lab-root", type=Path, default=root_default / "lagrangian-fluid-lab")
    parser.add_argument("--worktree-root", type=Path, default=root_default)
    parser.add_argument("--source-rebind-from", type=Path, help="old prepared checkout prefix for explicit source rebinding")
    parser.add_argument("--source-rebind-to", type=Path, help="new primary checkout prefix paired with --source-rebind-from")
    parser.add_argument("--chunk", type=int, default=65536)
    parser.add_argument("--max-wall-seconds", type=int, default=900)
    parser.add_argument("--max-memory-bytes", type=int, default=4 * 1024**3)
    args = parser.parse_args(argv)
    if args.max_wall_seconds <= 0 or args.max_memory_bytes <= 0 or args.chunk <= 0:
        parser.error("chunk, max-wall-seconds and max-memory-bytes must be positive")
    try:
        result = prepare(args)
    except (PilotPrepareError, OSError) as exc:
        print(f"scientific-field-h5-pilot-v10-prepare: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
