#!/usr/bin/env python3
"""Bounded material/event/censoring consumer for a typed event stream.

This additive entry point composes the strict tuple-identity and
mass-weighted event validator from ``namespace331_mass_weighted_labels_v2``
with a small CURRENT binding gate.  It is intentionally a development
consumer: producer handoffs for ROOT313/276/345 are accepted only as explicit
metadata references after their real terminal receipts exist, and no event
or qualification credit is granted by this module.  Missing source, owner,
region, control, or producer closure returns labels/metrics as UNKNOWN rather
than treating a status/index row as a physical label.

The guarded ``run`` path reads only bounded JSON metadata.  It never opens
H5, BI4, native arrays, trajectory content, or a model.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import stat
from pathlib import Path
from typing import Any, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location(
    "namespace331_mass_weighted_labels_v2_for_material_event_v1",
    SCRIPT_DIR / "ds_data02_stage2_namespace331_mass_weighted_labels_v2.py",
)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover
    raise ImportError("namespace331 mass/event v2 is unavailable")
_EVENT = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_EVENT)


SCHEMA = "ds02.stage2.namespace331.material-event-consumer.v1"
REQUEST_SCHEMA = "ds02.stage2.namespace331.material-event-consumer-request.v1"
RESULT_SCHEMA = "ds02.stage2.namespace331.material-event-consumer-result.v1"
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
MAX_METADATA_BYTES = 10 * 1024 * 1024
UNKNOWN_QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HISTORICAL_ALIAS_STATUS = "HISTORICAL_ALIAS_UNRESOLVED"


class MaterialEventConsumerError(ValueError):
    """Malformed, stale, or unclosed material/event input."""


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise MaterialEventConsumerError(f"{role} must be a SHA-256")
    try:
        int(value, 16)
    except ValueError as error:
        raise MaterialEventConsumerError(f"{role} is not hexadecimal") from error
    return value


def _lstat(path: Path, role: str) -> os.stat_result:
    try:
        info = os.lstat(path)
    except OSError as error:
        raise MaterialEventConsumerError(f"{role} cannot be stat'ed: {path}") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise MaterialEventConsumerError(f"{role} must be a regular non-symlink file")
    if info.st_size > MAX_METADATA_BYTES:
        raise MaterialEventConsumerError(f"{role} exceeds {MAX_METADATA_BYTES} byte metadata bound")
    return info


def _read_json(path: Path | str, role: str) -> tuple[dict[str, Any], dict[str, int], dict[str, int], str]:
    target = Path(path).expanduser()
    before = _lstat(target, role)
    data = target.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    after = _lstat(target, role)
    before_sig = {"st_dev": int(before.st_dev), "st_ino": int(before.st_ino),
                  "size": int(before.st_size), "mtime_ns": int(before.st_mtime_ns),
                  "ctime_ns": int(before.st_ctime_ns)}
    after_sig = {"st_dev": int(after.st_dev), "st_ino": int(after.st_ino),
                 "size": int(after.st_size), "mtime_ns": int(after.st_mtime_ns),
                 "ctime_ns": int(after.st_ctime_ns)}
    if before_sig != after_sig:
        raise MaterialEventConsumerError(f"{role} changed during bounded read")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MaterialEventConsumerError(f"{role} is not bounded JSON") from error
    if not isinstance(value, dict):
        raise MaterialEventConsumerError(f"{role} must be a JSON object")
    return value, before_sig, after_sig, digest


def _metadata_ref(value: Any, role: str, *, required: bool = True) -> dict[str, Any] | None:
    if value is None and not required:
        return None
    if not isinstance(value, Mapping):
        raise MaterialEventConsumerError(f"{role} reference is missing")
    path = value.get("path")
    declared = value.get("sha256", value.get("file_sha256"))
    if not isinstance(path, str):
        raise MaterialEventConsumerError(f"{role}.path is missing")
    observed = _lstat(Path(path).expanduser(), role)
    expected = _sha(declared, f"{role}.sha256")
    # Content is bounded metadata only; a producer handoff must be hash-bound
    # before it can be used as a source role, but missing handoffs remain a
    # valid pending request rather than a fabricated status.
    data, before, after, actual = _read_json(Path(path), role)
    if actual != expected:
        raise MaterialEventConsumerError(f"{role} SHA differs")
    return {"path": str(Path(path).expanduser().resolve()), "sha256": actual,
            "bytes": int(observed.st_size), "schema": data.get("schema"),
            "stat_pre": before, "stat_post": after}


def _current_binding(value: Any, *, allow_fixture: bool = False) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MaterialEventConsumerError("current_binding is required")
    path = value.get("path")
    expected = _sha(value.get("sha256", value.get("file_sha256")), "current_binding.sha256")
    current, before, after, actual = _read_json(Path(path), "CURRENT336")
    if actual != expected:
        raise MaterialEventConsumerError("CURRENT binding SHA differs")
    if current.get("schema") == CURRENT_SCHEMA:
        if actual != CURRENT_SHA256:
            raise MaterialEventConsumerError("CURRENT336 is not the pinned current catalog")
        rows = current.get("cases")
    elif allow_fixture and current.get("schema") == "ds02.stage2.fixture.current336.v1":
        rows = current.get("cases")
    else:
        raise MaterialEventConsumerError("unsupported CURRENT binding schema")
    if not isinstance(rows, list):
        raise MaterialEventConsumerError("CURRENT binding cases are missing")
    case_id = value.get("physical_case_id")
    index = value.get("case_index")
    if isinstance(index, bool) or not isinstance(index, int) or index < 0 or index >= len(rows):
        raise MaterialEventConsumerError("current_binding.case_index is invalid")
    row = rows[index]
    if not isinstance(row, Mapping) or row.get("physical_case_id") != case_id:
        raise MaterialEventConsumerError("CURRENT binding case row differs")
    if row.get("physical_case_id") == "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090":
        raise MaterialEventConsumerError("historical F2 alias cannot enter material/event consumer")
    return {"path": str(Path(path).expanduser().resolve()), "sha256": actual,
            "schema": current.get("schema"), "case_index": index,
            "physical_case_id": case_id, "stat_pre": before, "stat_post": after}


def _producer_handoffs(value: Any) -> dict[str, Any]:
    """Read optional ROOT handoff refs without treating status as evidence."""
    if value is None:
        return {"status": "PENDING_ROOT_TERMINAL_HANDOFF", "roles": {},
                "production_eligible": False}
    if not isinstance(value, Mapping):
        raise MaterialEventConsumerError("producer_handoffs must be an object")
    roles: dict[str, Any] = {}
    for role, ref in value.items():
        if role not in {"ROOT313_mass", "ROOT276_f6", "ROOT345_event", "material_source"}:
            raise MaterialEventConsumerError(f"unsupported producer handoff role: {role}")
        roles[role] = _metadata_ref(ref, role, required=True)
    return {"status": "METADATA_BOUND_PENDING_CONSUMER_SCOPE", "roles": roles,
            "production_eligible": False}


def build_request(event_stream_path: Path | str, output_path: Path | str, *,
                  current_binding: Mapping[str, Any], source_bindings: Sequence[Mapping[str, Any]],
                  producer_handoffs: Mapping[str, Any] | None = None,
                  max_wall_seconds: int = 900, allow_fixture: bool = False) -> dict[str, Any]:
    stream, _, _, stream_sha = _read_json(Path(event_stream_path), "event_stream")
    if stream.get("schema") != _EVENT.EVENT_SCHEMA:
        raise MaterialEventConsumerError("event stream is not namespace331 v2")
    identity = stream.get("case_identity")
    if not isinstance(identity, Mapping) or identity.get("identity_status") != "CANONICAL":
        raise MaterialEventConsumerError("event request requires canonical case identity")
    current = _current_binding(current_binding, allow_fixture=allow_fixture)
    if current["physical_case_id"] != identity.get("physical_case_id"):
        raise MaterialEventConsumerError("CURRENT and event stream case identities differ")
    refs: list[dict[str, Any]] = []
    for index, ref in enumerate(source_bindings):
        if not isinstance(ref, Mapping):
            raise MaterialEventConsumerError(f"source_bindings[{index}] is malformed")
        role = ref.get("role")
        if not isinstance(role, str) or not role:
            raise MaterialEventConsumerError(f"source_bindings[{index}].role is missing")
        _sha(ref.get("sha256", ref.get("file_sha256")), f"source_bindings[{index}].sha256")
        refs.append({**dict(ref), "content_policy": ref.get("content_policy", "PARENT_GUARD_DEFERRED")})
    if not isinstance(max_wall_seconds, int) or max_wall_seconds <= 0:
        raise MaterialEventConsumerError("max_wall_seconds must be positive")
    request = {
        "schema": REQUEST_SCHEMA, "status": "READY_FOR_PARENT_GUARD_METADATA_ONLY",
        "case_identity": dict(identity), "current_binding": current,
        "event_stream": {"path": str(Path(event_stream_path).expanduser().resolve()),
                          "sha256": stream_sha, "content_policy": "BOUNDED_JSON_AFTER_RESERVATION"},
        "source_bindings": refs,
        "producer_handoffs": _producer_handoffs(producer_handoffs),
        "execution": {"entrypoint": str(Path(__file__).resolve()),
                       "argv_template": ["run", "--request", "<bound-request>"],
                       "max_wall_seconds": max_wall_seconds,
                       "source_read_phase": "after_atomic_parent_reservation",
                       "parent_supervision_required": True, "model_invoked": False},
        "output": {"path": str(Path(output_path).expanduser().resolve()),
                   "content_policy": "SMALL_RESULT_AND_VALIDATION_JSON"},
        "development_fixture": bool(allow_fixture), "production_eligible": False,
        "qualification": dict(UNKNOWN_QUALIFICATION), "no_original_path_fallback": True,
    }
    request["request_sha256"] = _EVENT.canonical_sha(request)
    return request


def _unknown_metrics() -> dict[str, None]:
    return {key: None for key in (
        "first_arrival_mass_weighted_time_s", "first_arrival_mass_kg", "first_arrival_count",
        "right_censored_mass_kg", "excluded_mass_kg", "no_arrival_observed_mass_kg",
        "crossing_count", "gross_crossing_mass_kg", "net_flux_mass_kg",
        "net_flux_rate_kg_s", "mass_weighted_residence_time_s", "residence_mass_time_kg_s")}


def run_request(request_path: Path | str, *, allow_fixture: bool = False) -> dict[str, Any]:
    request, _, _, request_sha = _read_json(Path(request_path), "material/event request")
    if request.get("schema") != REQUEST_SCHEMA:
        raise MaterialEventConsumerError("unsupported material/event request schema")
    if request.get("request_sha256") != _EVENT.canonical_sha(request):
        raise MaterialEventConsumerError("material/event request canonical SHA differs")
    current = _current_binding(request.get("current_binding"), allow_fixture=allow_fixture)
    event_ref = request.get("event_stream")
    if not isinstance(event_ref, Mapping):
        raise MaterialEventConsumerError("event_stream binding is missing")
    stream, _, _, stream_sha = _read_json(Path(event_ref["path"]), "event_stream")
    if stream_sha != event_ref.get("sha256"):
        raise MaterialEventConsumerError("event stream SHA differs from request")
    identity = stream.get("case_identity")
    if identity.get("physical_case_id") != current["physical_case_id"]:
        raise MaterialEventConsumerError("event/CURRENT identity differs")
    normalized = _EVENT.validate_event_stream_v2(stream, verify_sources=False)
    result = _EVENT.produce_labels_v2(stream, verify_sources=False)
    # The V2 result is the validated event/censoring arithmetic.  Material
    # role closure is separately reported; no role/status index can promote
    # it to physical truth.
    binding_status = result.get("binding_status", {})
    known_roles = all(binding_status.get(key) == _EVENT.STATUS_KNOWN
                      for key in ("source_status", "region_owner_status", "control_status"))
    output = {
        "schema": RESULT_SCHEMA, "request_sha256": request_sha,
        "event_result_schema": result.get("schema"),
        "case_identity": {"family_id": normalized["family_id"],
                           "physical_case_id": normalized["physical_case_id"],
                           "identity_status": normalized["identity_status"]},
        "current_binding": current,
        "derived_status": result.get("derived_status", "UNKNOWN"),
        "labels": result.get("labels", []),
        "censoring": {"status": "VALIDATED_METADATA_ONLY" if known_roles else "UNKNOWN_ROLE_CLOSURE",
                       "metrics": result.get("metrics") if known_roles else _unknown_metrics(),
                       "observation_statuses": sorted({p.get("observation_status")
                                                       for p in normalized["particles"]})},
        "material": {"status": "UNKNOWN_NO_PRODUCTION_MATERIAL_ROLE_CREDIT",
                      "source_status": binding_status.get("source_status"),
                      "region_owner_status": binding_status.get("region_owner_status"),
                      "control_status": binding_status.get("control_status"),
                      "mass_semantics": "mass-weighted only after validated (Zone,Idp) and role closure"},
        "producer_handoffs": request.get("producer_handoffs"),
        "qualification": dict(UNKNOWN_QUALIFICATION), "production_eligible": False,
        "model_invoked": False, "cfd_invoked": False,
        "claim_boundary": "tiny/interface or parent-guarded development metadata; no physical/event qualification credit",
    }
    return output


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise MaterialEventConsumerError(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--event-stream", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--request", type=Path, required=True)
    build.add_argument("--current-path", type=Path, required=True)
    build.add_argument("--current-sha256", required=True)
    build.add_argument("--case-index", type=int, required=True)
    build.add_argument("--physical-case-id", required=True)
    build.add_argument("--source-binding", action="append", nargs=4,
                       metavar=("ROLE", "PATH", "SHA256", "SEMANTIC_ROLE"), default=[])
    build.add_argument("--allow-fixture", action="store_true")
    run = sub.add_parser("run")
    run.add_argument("--request", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--allow-fixture", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            current_ref = {"path": str(args.current_path), "sha256": args.current_sha256,
                           "case_index": args.case_index, "physical_case_id": args.physical_case_id}
            refs = [{"role": role, "path": path, "sha256": sha, "semantic_role": semantic}
                    for role, path, sha, semantic in args.source_binding]
            request = build_request(args.event_stream, args.output, current_binding=current_ref,
                                    source_bindings=refs, allow_fixture=args.allow_fixture)
            _write_new(args.request, request)
            print(json.dumps({"schema": REQUEST_SCHEMA, "request": str(args.request),
                              "request_sha256": request["request_sha256"]}, sort_keys=True))
        else:
            result = run_request(args.request, allow_fixture=args.allow_fixture)
            _write_new(args.output, result)
            print(json.dumps({"schema": RESULT_SCHEMA, "output": str(args.output),
                              "derived_status": result["derived_status"]}, sort_keys=True))
        return 0
    except (OSError, MaterialEventConsumerError) as error:
        print(f"MATERIAL_EVENT_CONSUMER_ERROR: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

