#!/usr/bin/env python3
"""Bounded V16/typed-result to namespace331 event-stream adapter.

The adapter consumes an already guarded, bounded JSON result mapping.  It does
not open H5/BI4/raw data and it never invents particle identities, masses,
regions, times, or source ownership.  A caller that only has the large V16
path can build a deferred request with :func:`build_typed_event_request_v1`;
the parent guard must provide the content mapping after reservation.

The resulting document is namespace331-v2 compatible and keeps the V16
source/current/owner/control evidence as explicit hash-bound bindings.  Missing
identity, mass, time, or role evidence remains UNKNOWN or fails closed rather
than becoming a fabricated KNOWN label.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location(
    "namespace331_labels_v2_for_v16_adapter",
    SCRIPT_DIR / "ds_data02_stage2_namespace331_mass_weighted_labels_v2.py",
)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover
    raise ImportError("namespace331 v2 source is unavailable")
_N331 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_N331)


ADAPTER_SCHEMA = "ds02.stage2.namespace331.v16-typed-event-adapter.v1"
REQUEST_SCHEMA = "ds02.stage2.namespace331.v16-typed-event-request.v1"
EVENT_SCHEMA = _N331.EVENT_SCHEMA
QUALIFICATION_UNKNOWN = dict(_N331.QUALIFICATION_UNKNOWN)
MAX_METADATA_BYTES = _N331.MAX_METADATA_BYTES
STATUS_KNOWN = _N331.STATUS_KNOWN
STATUS_UNKNOWN = _N331.STATUS_UNKNOWN
_HEX = set("0123456789abcdef")


class TypedEventAdapterError(ValueError):
    """Missing, stale, or ambiguous V16/typed event evidence."""


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def canonical_sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical({k: v for k, v in value.items()
                                     if k not in {"sha256", "request_sha256"}}).encode()).hexdigest()


def _finite(value: Any, name: str, *, allow_none: bool = True) -> float | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypedEventAdapterError(f"{name} must be finite numeric metadata")
    result = float(value)
    if not math.isfinite(result):
        raise TypedEventAdapterError(f"{name} must be finite numeric metadata")
    return result


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch.lower() not in _HEX for ch in value):
        raise TypedEventAdapterError(f"{name} must be a SHA-256")
    return value.lower()


def _stat(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser()
    if target.is_symlink() or not target.exists():
        return {"exists": False}
    value = target.stat()
    return {"exists": True, "kind": "file" if target.is_file() else "directory",
            "bytes": int(value.st_size) if target.is_file() else None,
            "mode_bits": int(value.st_mode & 0o7777), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns), "st_dev": int(value.st_dev),
            "st_ino": int(value.st_ino)}


def _sha_file(path: Path | str, *, maximum: int | None = None) -> str:
    target = Path(path).expanduser()
    if target.is_symlink() or not target.is_file():
        raise TypedEventAdapterError(f"typed result must be a regular non-symlink file: {target}")
    if maximum is not None and target.stat().st_size > maximum:
        raise TypedEventAdapterError(f"metadata file exceeds bounded read limit: {target}")
    digest = hashlib.sha256()
    with target.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _case_identity(result: Mapping[str, Any]) -> tuple[str, str, str]:
    value = result.get("case_identity")
    if not isinstance(value, Mapping):
        raise TypedEventAdapterError("typed result lacks case_identity")
    family = value.get("family_id")
    case_id = value.get("physical_case_id")
    if not isinstance(family, str) or not family or not isinstance(case_id, str) or not case_id:
        raise TypedEventAdapterError("typed result case_identity lacks family/case")
    status = value.get("identity_status", "CANONICAL")
    if status not in {"CANONICAL", "UNKNOWN"}:
        status = "UNKNOWN"
    return family, case_id, status


def _current_digest(result: Mapping[str, Any]) -> str | None:
    binding = result.get("source_binding")
    if isinstance(binding, Mapping):
        for key in ("current_catalog_sha256", "current_manifest_sha256", "current_sha256"):
            if binding.get(key) is not None:
                return _sha(binding[key], f"source_binding.{key}")
    binding = result.get("current_binding")
    if isinstance(binding, Mapping) and binding.get("sha256") is not None:
        return _sha(binding["sha256"], "current_binding.sha256")
    return None


def _role_bindings(source_bindings: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str], bool]:
    if not isinstance(source_bindings, Sequence) or isinstance(source_bindings, (str, bytes)):
        raise TypedEventAdapterError("source_bindings must be a sequence")
    role_map: dict[str, str] = {}
    refs: list[dict[str, Any]] = []
    verified = True
    required = {"source", "region_owner", "control"}
    for index, raw in enumerate(source_bindings):
        if not isinstance(raw, Mapping):
            raise TypedEventAdapterError(f"source_bindings[{index}] must be an object")
        role = raw.get("role")
        semantic = raw.get("semantic_role", raw.get("role_kind"))
        path = raw.get("path")
        if not isinstance(role, str) or not role or not isinstance(semantic, str) or semantic not in required:
            raise TypedEventAdapterError(f"source_bindings[{index}] needs a source/owner/control semantic role")
        if role in role_map.values() or semantic in role_map:
            raise TypedEventAdapterError(f"duplicate source binding role: {role}/{semantic}")
        digest = _sha(raw.get("sha256", raw.get("file_sha256")), f"source_bindings[{index}].sha256")
        observed = raw.get("observed_sha256")
        if observed is not None:
            observed = _sha(observed, f"source_bindings[{index}].observed_sha256")
        attestation = raw.get("role_attestation", raw.get("binding_evidence"))
        attestation_ok = False
        if isinstance(attestation, Mapping):
            attestation_digest = attestation.get("content_sha256",
                                                attestation.get("source_content_sha256",
                                                                attestation.get("sha256")))
            attestation_status = attestation.get("proof_status", attestation.get("status"))
            attestation_ok = (
                attestation.get("semantic_role") == semantic and
                isinstance(attestation.get("content_schema"), str) and
                attestation.get("content_schema") and
                isinstance(attestation_status, str) and
                attestation_status.upper() in {"VERIFIED", "PASS", "COMPLETED", "SOURCE_BOUND"} and
                isinstance(attestation_digest, str) and attestation_digest.lower() == digest
            )
        # A path SHA and a caller-supplied semantic_role are only provenance.
        # The small role attestation must bind the source content's semantic
        # schema and digest before a role can become KNOWN.
        bound = attestation_ok and (raw.get("content_verified") is True or
                                    raw.get("hash_verified_after_reservation") is True or
                                    observed == digest)
        verified = verified and bound
        role_map[semantic] = role
        refs.append({"role": role, "semantic_role": semantic, "path": path,
                     "sha256": digest, "observed_sha256": observed,
                     "content_verified": bool(raw.get("content_verified") is True),
                     "hash_verified_after_reservation": bool(raw.get("hash_verified_after_reservation") is True),
                     "role_attestation": copy.deepcopy(dict(attestation))
                     if isinstance(attestation, Mapping) else None,
                     "content_policy": raw.get("content_policy", "PARENT_GUARD_DEFERRED")})
    missing = required - set(role_map)
    if missing:
        verified = False
    return refs, role_map, verified


def _window(result: Mapping[str, Any], explicit: Sequence[float] | None) -> list[float]:
    if explicit is not None:
        if len(explicit) != 2:
            raise TypedEventAdapterError("observation_window_s must contain [start,end]")
        start, end = (_finite(explicit[0], "observation_window_s[0]", allow_none=False),
                      _finite(explicit[1], "observation_window_s[1]", allow_none=False))
    else:
        value = result.get("window")
        if not isinstance(value, Mapping):
            raise TypedEventAdapterError("typed result needs an explicit observation window")
        start = _finite(value.get("time_start_s", value.get("first_s")), "window.start_s")
        end = _finite(value.get("time_stop_s", value.get("last_s")), "window.end_s")
    if start is None or end is None or start < 0 or end <= start:
        raise TypedEventAdapterError("observation window must be finite, nonnegative, and increasing")
    return [start, end]


def _particle_identity(row: Mapping[str, Any], index: int) -> tuple[dict[str, int], str]:
    zone = row.get("zone", row.get("Zone"))
    idp = row.get("idp", row.get("Idp"))
    if isinstance(row.get("particle_identity"), Mapping):
        identity = row["particle_identity"]
        zone = identity.get("Zone", identity.get("zone"))
        idp = identity.get("Idp", identity.get("idp"))
    if isinstance(zone, bool) or not isinstance(zone, int) or isinstance(idp, bool) or not isinstance(idp, int):
        raise TypedEventAdapterError(f"typed row {index} lacks integer Zone/Idp")
    return {"Zone": zone, "Idp": idp}, f"Zone={zone};Idp={idp}"


def _label_status(row: Mapping[str, Any]) -> str:
    value = row.get("observation_status", row.get("status"))
    if not isinstance(value, str):
        return "CENSORED"
    upper = value.upper()
    if "EXCLUD" in upper:
        return "EXCLUDED"
    if "CENSOR" in upper or "UNKNOWN" in upper or "MISSING" in upper:
        return "CENSORED"
    return "OBSERVED"


def _event_rows(label: Mapping[str, Any], *, target_region: str, particle_id: str,
                index: int) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    arrival = label.get("event_time_s")
    if arrival is None:
        arrival = label.get("first_arrival_time_s")
    arrival_value = _finite(arrival, f"labels[{index}].event_time_s")
    if arrival_value is not None:
        events.append({"event_id": f"{particle_id}-arrival", "event_type": "ARRIVAL",
                       "time_s": arrival_value, "region": target_region})
    crossings = label.get("crossing_events")
    if crossings is None:
        crossings = label.get("crossings")
    if crossings is not None:
        if not isinstance(crossings, list):
            raise TypedEventAdapterError(f"labels[{index}].crossing_events must be a list")
        for cindex, crossing in enumerate(crossings):
            if not isinstance(crossing, Mapping):
                raise TypedEventAdapterError(f"labels[{index}] crossing {cindex} is not an object")
            time_value = _finite(crossing.get("time_s"), f"crossing[{cindex}].time_s", allow_none=False)
            direction = crossing.get("direction")
            region = crossing.get("region", target_region)
            if direction not in _N331.DIRECTIONS:
                raise TypedEventAdapterError(f"crossing[{cindex}] direction is not explicit")
            events.append({"event_id": f"{particle_id}-crossing-{cindex}",
                           "event_type": "CROSSING", "time_s": time_value,
                           "direction": direction, "region": region})
    residence = label.get("residence_intervals", label.get("residence"))
    if residence is not None:
        if not isinstance(residence, list):
            raise TypedEventAdapterError(f"labels[{index}].residence_intervals must be a list")
        for rindex, interval in enumerate(residence):
            if not isinstance(interval, Mapping):
                raise TypedEventAdapterError(f"residence[{rindex}] is not an object")
            events.append({"event_id": f"{particle_id}-residence-{rindex}",
                           "event_type": "RESIDENCE_INTERVAL",
                           "start_time_s": _finite(interval.get("start_time_s"),
                                                    f"residence[{rindex}].start_time_s", allow_none=False),
                           "end_time_s": _finite(interval.get("end_time_s"),
                                                  f"residence[{rindex}].end_time_s", allow_none=False),
                           "region": interval.get("region", target_region)})
    # Sort by the event's start/time so namespace331's monotonic event guard
    # sees the same order independent of V16 producer list order.
    events.sort(key=lambda item: item.get("start_time_s", item.get("time_s")))
    return events


def build_event_stream_from_v16(
    typed_result: Mapping[str, Any], *, current_binding: Mapping[str, Any],
    source_bindings: Sequence[Mapping[str, Any]], target_region: str,
    source_region: str, observation_window_s: Sequence[float] | None = None,
) -> dict[str, Any]:
    """Convert a bounded typed/V16 result mapping into a strict event stream."""
    if not isinstance(typed_result, Mapping):
        raise TypedEventAdapterError("typed_result must be a JSON object")
    schema = typed_result.get("schema")
    if not isinstance(schema, str) or not (schema.endswith(".v16") or "typed" in schema.lower()):
        raise TypedEventAdapterError("typed_result schema is not a supported V16/typed result")
    if not isinstance(current_binding, Mapping):
        raise TypedEventAdapterError("current_binding is required")
    current_sha = _sha(current_binding.get("sha256", current_binding.get("file_sha256")),
                       "current_binding.sha256")
    result_current_sha = _current_digest(typed_result)
    current_match = result_current_sha is not None and result_current_sha == current_sha
    family, case_id, identity_status = _case_identity(typed_result)
    refs, role_map, roles_bound = _role_bindings(source_bindings)
    target_region = target_region if isinstance(target_region, str) and target_region else None
    source_region = source_region if isinstance(source_region, str) and source_region else None
    if target_region is None or source_region is None:
        raise TypedEventAdapterError("source_region and target_region are required; they are not inferred")
    window = _window(typed_result, observation_window_s)
    labels = typed_result.get("labels")
    if not isinstance(labels, list) or not labels:
        raise TypedEventAdapterError("typed result labels with Zone/Idp rows are required")
    particles: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    denominator = None
    denom = typed_result.get("initial_mass_denominator")
    if isinstance(denom, Mapping):
        denominator = _finite(denom.get("denominator_kg", denom.get("initial_fluid_mass_kg")),
                              "initial_mass_denominator.denominator_kg")
    if denominator is None:
        denominator = _finite(typed_result.get("selected_initial_mass_kg"),
                              "selected_initial_mass_kg")
    if denominator is None or denominator <= 0:
        raise TypedEventAdapterError("typed result lacks an explicit positive initial mass denominator")
    for index, label in enumerate(labels):
        if not isinstance(label, Mapping):
            raise TypedEventAdapterError(f"labels[{index}] must be an object")
        identity, particle_id = _particle_identity(label, index)
        key = (identity["Zone"], identity["Idp"])
        if key in seen:
            raise TypedEventAdapterError(f"duplicate typed Zone/Idp identity: {key}")
        seen.add(key)
        mass = _finite(label.get("initial_mass_kg"), f"labels[{index}].initial_mass_kg")
        if mass is None or mass <= 0:
            raise TypedEventAdapterError(f"labels[{index}] lacks positive initial_mass_kg")
        status = _label_status(label)
        events = _event_rows(label, target_region=target_region, particle_id=particle_id, index=index)
        particles.append({"particle_identity": identity, "particle_id": particle_id,
                          "mass_kg": mass, "initial_region": source_region,
                          "observation_status": status, "events": events})
    observed_sum = sum(item["mass_kg"] for item in particles if item["observation_status"] != "EXCLUDED")
    if not math.isclose(observed_sum, denominator, rel_tol=0.0,
                        abs_tol=1e-12 * max(1.0, abs(observed_sum), abs(denominator))):
        raise TypedEventAdapterError("typed label mass sum differs from explicit denominator")
    status_known = current_match and roles_bound and identity_status == "CANONICAL"
    document = {
        "schema": EVENT_SCHEMA,
        "adapter": {"schema": ADAPTER_SCHEMA, "source_result_schema": schema,
                     "source_current_sha256": result_current_sha,
                     "current_binding_sha256": current_sha,
                     "current_binding_match": current_match,
                     "typed_content_policy": "PARENT_GUARD_BOUND_JSON_ONLY",
                     "h5_bi4_raw_opened": False},
        "case_identity": {"family_id": family, "physical_case_id": case_id,
                           "identity_status": identity_status if identity_status == "CANONICAL" else "UNKNOWN"},
        "source_bindings": refs,
        "observation_contract": {
            "source_status": STATUS_KNOWN if status_known else STATUS_UNKNOWN,
            "region_owner_status": STATUS_KNOWN if status_known else STATUS_UNKNOWN,
            "control_status": STATUS_KNOWN if status_known else STATUS_UNKNOWN,
            "role_bindings": role_map,
            "source_region": source_region, "target_region": target_region,
            "observation_window_s": window, "eligible_initial_mass_kg": denominator,
        },
        "particles": particles,
        "qualification": dict(QUALIFICATION_UNKNOWN),
        "model_invoked": False,
        "cfd_invoked": False,
    }
    document["adapter"]["status"] = "BOUND" if status_known else "UNKNOWN_UNBOUND_EVIDENCE"
    document["adapter"]["unknown_reasons"] = [reason for reason, ok in (
        ("current_binding_mismatch", current_match),
        ("source_owner_control_roles_not_hash_bound", roles_bound),
        ("canonical_case_identity_missing", identity_status == "CANONICAL"),
    ) if not ok]
    return document


def build_typed_event_request_v1(
    typed_result_path: Path | str, *, typed_result_sha256: str,
    current_binding: Mapping[str, Any], source_bindings: Sequence[Mapping[str, Any]],
    output_event_stream: Path | str, family_id: str, physical_case_id: str,
    target_region: str, source_region: str, max_wall_seconds: int = 900,
) -> dict[str, Any]:
    """Build a deferred parent request without opening the typed result."""
    typed_path = Path(typed_result_path).expanduser()
    digest = _sha(typed_result_sha256, "typed_result_sha256")
    current_sha = _sha(current_binding.get("sha256", current_binding.get("file_sha256")),
                       "current_binding.sha256")
    refs, role_map, roles_bound = _role_bindings(source_bindings)
    if not isinstance(family_id, str) or not family_id or not isinstance(physical_case_id, str) or not physical_case_id:
        raise TypedEventAdapterError("family_id and physical_case_id are required")
    if not isinstance(target_region, str) or not target_region or not isinstance(source_region, str) or not source_region:
        raise TypedEventAdapterError("source_region and target_region are required")
    if not isinstance(max_wall_seconds, int) or max_wall_seconds <= 0:
        raise TypedEventAdapterError("max_wall_seconds must be positive")
    request = {
        "schema": REQUEST_SCHEMA, "status": "READY_FOR_PARENT_GUARD_TYPED_JSON",
        "adapter": ADAPTER_SCHEMA, "case_identity": {"family_id": family_id,
                                                       "physical_case_id": physical_case_id},
        "typed_result": {"path": str(typed_path), "sha256": digest,
                          "stat": _stat(typed_path),
                          "content_policy": "READ_AFTER_ATOMIC_RESERVATION"},
        "current_binding": {"path": current_binding.get("path"), "sha256": current_sha,
                             "content_policy": "SMALL_CURRENT_METADATA_AFTER_RESERVATION"},
        "source_bindings": refs,
        "role_bindings": role_map,
        "role_bindings_hash_bound_at_build": roles_bound,
        "event_contract": {"source_region": source_region, "target_region": target_region,
                            "observation_window": "from typed result window or explicit request",
                            "identity_key": "(Zone,Idp)",
                            "unknown_identity_or_binding": "all labels and metrics UNKNOWN"},
        "execution": {"entrypoint": "ds_data02_stage2_namespace331_v16_typed_event_adapter_v1.py",
                       "output_event_stream": str(Path(output_event_stream).expanduser()),
                       "max_wall_seconds": max_wall_seconds,
                       "source_read_phase": "after_atomic_parent_reservation",
                       "parent_supervision_required": True, "model_invoked": False,
                       "h5_bi4_raw_opened": False},
        "qualification_boundary": dict(QUALIFICATION_UNKNOWN),
    }
    request["request_sha256"] = canonical_sha(request)
    return request


def _read_bounded_json(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser()
    if target.is_symlink() or not target.is_file() or target.stat().st_size > MAX_METADATA_BYTES:
        raise TypedEventAdapterError("typed JSON must be a bounded regular file")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TypedEventAdapterError(str(error)) from error
    if not isinstance(value, Mapping):
        raise TypedEventAdapterError("typed JSON must be an object")
    return dict(value)


def _write_json(path: Path | str, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                      encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    req = sub.add_parser("build-request")
    req.add_argument("--typed-result", type=Path, required=True)
    req.add_argument("--typed-sha256", required=True)
    req.add_argument("--current-sha256", required=True)
    req.add_argument("--current-path", required=True)
    req.add_argument("--source-binding", action="append", nargs=5,
                     metavar=("ROLE", "SEMANTIC_ROLE", "PATH", "SHA256", "OBSERVED_SHA256"), default=[])
    req.add_argument("--output-event-stream", required=True)
    req.add_argument("--request", type=Path, required=True)
    req.add_argument("--family-id", required=True)
    req.add_argument("--physical-case-id", required=True)
    req.add_argument("--source-region", required=True)
    req.add_argument("--target-region", required=True)
    convert = sub.add_parser("convert")
    convert.add_argument("--typed-result", type=Path, required=True)
    convert.add_argument("--current-sha256", required=True)
    convert.add_argument("--current-path", required=True)
    convert.add_argument("--source-binding", action="append", nargs=5,
                         metavar=("ROLE", "SEMANTIC_ROLE", "PATH", "SHA256", "OBSERVED_SHA256"), default=[])
    convert.add_argument("--source-region", required=True)
    convert.add_argument("--target-region", required=True)
    convert.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        bindings = [{"role": role, "semantic_role": semantic, "path": path,
                     "sha256": digest, "observed_sha256": observed,
                     "content_verified": bool(observed),
                     "content_policy": "PARENT_GUARD_DEFERRED"}
                    for role, semantic, path, digest, observed in args.source_binding]
        if args.command == "build-request":
            request = build_typed_event_request_v1(
                args.typed_result, typed_result_sha256=args.typed_sha256,
                current_binding={"path": args.current_path, "sha256": args.current_sha256},
                source_bindings=bindings, output_event_stream=args.output_event_stream,
                family_id=args.family_id, physical_case_id=args.physical_case_id,
                source_region=args.source_region, target_region=args.target_region)
            _write_json(args.request, request)
            print(json.dumps({"request": str(args.request),
                              "request_sha256": request["request_sha256"]}, sort_keys=True))
        else:
            typed = _read_bounded_json(args.typed_result)
            document = build_event_stream_from_v16(
                typed, current_binding={"path": args.current_path, "sha256": args.current_sha256},
                source_bindings=bindings, source_region=args.source_region,
                target_region=args.target_region)
            _write_json(args.output, document)
            print(json.dumps({"output": str(args.output), "schema": document["schema"],
                              "status": document["adapter"]["status"]}, sort_keys=True))
    except (OSError, TypedEventAdapterError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
