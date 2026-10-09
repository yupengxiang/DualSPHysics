#!/usr/bin/env python3
"""Strict source-bound namespace331 event labels (v2).

The consumed v1 consumer was intentionally small, but its free-form particle
ids and status strings were insufficient to establish physical identity.  It
also aggregated every crossing/residence row after validation.  This additive
version requires a ``(Zone, Idp)`` identity, rejects out-of-target and
overlapping intervals, and requires hash-bound source/owner/control roles
before producing numerical labels.  An UNKNOWN case identity produces an
all-UNKNOWN result, preserving the distinction between missing identity and
an observed event stream.

Only bounded event/proof JSON is accepted.  No scientific payload is opened
and qualification remains UNKNOWN.
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
    "namespace331_v1_for_v2",
    SCRIPT_DIR / "ds_data02_stage2_namespace331_mass_weighted_labels.py",
)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover
    raise ImportError("namespace331 v1 source is unavailable")
_V1 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_V1)


EVENT_SCHEMA = "ds02.stage2.namespace331.mass-weighted-event-stream.v2"
RESULT_SCHEMA = "ds02.stage2.namespace331.mass-weighted-label-result.v2"
REQUEST_SCHEMA = "ds02.stage2.namespace331.mass-weighted-label-request.v2"
VALIDATOR_SCHEMA = "ds02.stage2.namespace331.mass-weighted-label-validation.v2"
STATUS_KNOWN = _V1.STATUS_KNOWN
STATUS_UNKNOWN = _V1.STATUS_UNKNOWN
QUALIFICATION_UNKNOWN = dict(_V1.QUALIFICATION_UNKNOWN)
MAX_METADATA_BYTES = _V1.MAX_METADATA_BYTES
PARTICLE_STATUSES = set(_V1.PARTICLE_STATUSES)
EVENT_TYPES = set(_V1.EVENT_TYPES)
DIRECTIONS = set(_V1.DIRECTIONS)


class Namespace331V2Error(ValueError):
    """A malformed or unbound v2 event stream."""


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def canonical_sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical({k: v for k, v in value.items()
                                     if k not in {"sha256", "request_sha256"}}).encode()).hexdigest()


def _read_json(path: Path | str, role: str) -> dict[str, Any]:
    try:
        return _V1._read_json(path, role=role)
    except Exception as error:
        raise Namespace331V2Error(str(error)) from error


def _stat(path: Path | str) -> dict[str, Any]:
    return _V1._stat(path)


def _sha_file(path: Path | str) -> str:
    try:
        return _V1._sha256_file(path)
    except Exception as error:
        raise Namespace331V2Error(str(error)) from error


def _finite(value: Any, name: str) -> float:
    try:
        return _V1._finite(value, name)
    except Exception as error:
        raise Namespace331V2Error(str(error)) from error


def _sha(value: Any, name: str) -> str:
    try:
        return _V1._sha(value, name)
    except Exception as error:
        raise Namespace331V2Error(str(error)) from error


def _status(value: Any, name: str) -> str:
    try:
        return _V1._status(value, name)
    except Exception as error:
        raise Namespace331V2Error(str(error)) from error


def _canonical_particle_identity(raw: Mapping[str, Any], index: int) -> tuple[dict[str, int], str]:
    identity = raw.get("particle_identity")
    particle_id = raw.get("particle_id")
    if isinstance(particle_id, Mapping):
        identity = particle_id
        particle_id = None
    if not isinstance(identity, Mapping):
        identity = raw
    zone = identity.get("Zone", identity.get("zone"))
    idp = identity.get("Idp", identity.get("idp"))
    if isinstance(zone, bool) or not isinstance(zone, int) or isinstance(idp, bool) or not isinstance(idp, int):
        raise Namespace331V2Error(f"particles[{index}] requires integer (Zone, Idp) identity")
    canonical = f"Zone={zone};Idp={idp}"
    if particle_id is not None and particle_id != canonical:
        raise Namespace331V2Error(f"particles[{index}].particle_id is not canonical for (Zone, Idp)")
    return {"Zone": zone, "Idp": idp}, canonical


def _role_ref_map(document: Mapping[str, Any], *, verify_sources: bool) -> dict[str, dict[str, Any]]:
    raw_bindings = document.get("source_bindings")
    if not isinstance(raw_bindings, list) or not raw_bindings:
        raise Namespace331V2Error("source_bindings must be a nonempty list")
    # Let the consumed validator retain its bounded path/SHA checks, then
    # apply the new semantic-role contract to the original objects.
    try:
        normalized = _V1._validate_source_bindings(raw_bindings, verify_content=verify_sources)
    except Exception as error:
        raise Namespace331V2Error(str(error)) from error
    by_role = {item["role"]: item for item in normalized}
    originals = {item.get("role"): item for item in raw_bindings
                 if isinstance(item, Mapping) and isinstance(item.get("role"), str)}
    contract = document.get("observation_contract")
    if not isinstance(contract, Mapping):
        raise Namespace331V2Error("observation_contract is required")
    role_names = contract.get("role_bindings")
    if not isinstance(role_names, Mapping):
        role_names = contract.get("source_role_bindings")
    if not isinstance(role_names, Mapping):
        role_names = {}
    aliases = {
        "source": ("source", "source_role", "source_binding"),
        "region_owner": ("region_owner", "owner", "region_owner_role", "owner_role"),
        "control": ("control", "control_role", "control_binding"),
    }
    statuses = {
        "source": contract.get("source_status"),
        "region_owner": contract.get("region_owner_status"),
        "control": contract.get("control_status"),
    }
    result: dict[str, dict[str, Any]] = {}
    for semantic, names in aliases.items():
        name = next((role_names.get(key) for key in names
                     if isinstance(role_names.get(key), str) and role_names.get(key)), None)
        if statuses[semantic] == STATUS_KNOWN:
            if name is None or name not in by_role:
                raise Namespace331V2Error(f"KNOWN {semantic} role is not declared in source_bindings")
            original = originals.get(name, {})
            role_kind = original.get("semantic_role", original.get("role_kind"))
            if role_kind != semantic:
                raise Namespace331V2Error(f"source binding {name} is not semantic role {semantic}")
            path = str(original.get("path", ""))
            # A source/owner/control role cannot be satisfied by an arbitrary
            # Python file merely because its bytes have a hash.
            if path.lower().endswith(".py"):
                raise Namespace331V2Error(f"KNOWN {semantic} role cannot be an arbitrary Python file")
            declared = _sha(original.get("sha256", original.get("file_sha256")),
                             f"source binding {name}.sha256")
            observed = original.get("observed_sha256")
            if observed is not None:
                observed = _sha(observed, f"source binding {name}.observed_sha256")
            verified = original.get("content_verified") is True
            after_reservation = original.get("hash_verified_after_reservation") is True
            if verify_sources:
                verified = by_role[name].get("content_verified") is True
                observed = by_role[name].get("observed_stat") and declared
            elif observed != declared and not after_reservation:
                raise Namespace331V2Error(f"KNOWN {semantic} role lacks hash-bound observed SHA")
            if not verified and not after_reservation and observed != declared:
                raise Namespace331V2Error(f"KNOWN {semantic} role is not content verified")
            result[semantic] = {
                "role": name, "semantic_role": semantic, "sha256": declared,
                "path": path, "content_verified": bool(verified or after_reservation),
                "hash_verified_after_reservation": bool(after_reservation),
            }
        else:
            result[semantic] = {"role": name, "semantic_role": semantic,
                                "content_verified": False}
    return result


def _validate_contract_v2(document: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    try:
        contract = _V1._validate_contract(document)
    except Exception as error:
        raise Namespace331V2Error(str(error)) from error
    roles = _role_ref_map(document, verify_sources=False)
    contract["role_bindings"] = roles
    return contract, roles


def _validate_particles_v2(document: Mapping[str, Any], contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    particles = document.get("particles")
    if not isinstance(particles, list) or not particles:
        raise Namespace331V2Error("particles must be a nonempty list")
    start, end = contract["observation_window_s"]
    identities: set[tuple[int, int]] = set()
    particle_ids: set[str] = set()
    event_ids: set[str] = set()
    normalized: list[dict[str, Any]] = []
    denominator = 0.0
    for index, raw in enumerate(particles):
        if not isinstance(raw, Mapping):
            raise Namespace331V2Error(f"particles[{index}] must be an object")
        identity, particle_id = _canonical_particle_identity(raw, index)
        key = (identity["Zone"], identity["Idp"])
        if key in identities or particle_id in particle_ids:
            raise Namespace331V2Error(f"duplicate particle identity (Zone, Idp): {key}")
        identities.add(key)
        particle_ids.add(particle_id)
        mass = _finite(raw.get("mass_kg"), f"particles[{index}].mass_kg")
        if mass <= 0:
            raise Namespace331V2Error(f"particles[{index}].mass_kg must be positive")
        status = raw.get("observation_status")
        if status not in PARTICLE_STATUSES:
            raise Namespace331V2Error(f"particles[{index}].observation_status is invalid")
        initial_region = raw.get("initial_region")
        if not isinstance(initial_region, str) or not initial_region:
            raise Namespace331V2Error(f"particles[{index}].initial_region is required")
        raw_events = raw.get("events", [])
        if not isinstance(raw_events, list):
            raise Namespace331V2Error(f"particles[{index}].events must be a list")
        events: list[dict[str, Any]] = []
        previous_time = -math.inf
        residence: list[tuple[float, float, str]] = []
        for event_index, event in enumerate(raw_events):
            if not isinstance(event, Mapping):
                raise Namespace331V2Error(f"particle {particle_id} event is not an object")
            event_id = event.get("event_id")
            if not isinstance(event_id, str) or not event_id or event_id in event_ids:
                raise Namespace331V2Error(f"event_id missing or duplicated: {event_id!r}")
            event_ids.add(event_id)
            event_type = event.get("event_type")
            if event_type not in EVENT_TYPES:
                raise Namespace331V2Error(f"event {event_id} has unsupported event_type")
            region = event.get("region")
            if region != contract["target_region"]:
                raise Namespace331V2Error(f"event {event_id} is outside target_region")
            if event_type == "RESIDENCE_INTERVAL":
                event_start = _finite(event.get("start_time_s"), f"{event_id}.start_time_s")
                event_end = _finite(event.get("end_time_s"), f"{event_id}.end_time_s")
                if event_start < start or event_end > end or event_end <= event_start:
                    raise Namespace331V2Error(f"event {event_id} has an invalid residence interval")
                event_time = event_start
                residence.append((event_start, event_end, event_id))
            else:
                event_time = _finite(event.get("time_s"), f"{event_id}.time_s")
                if event_time < start or event_time > end:
                    raise Namespace331V2Error(f"event {event_id} lies outside observation window")
                if event_type == "CROSSING" and event.get("direction") not in DIRECTIONS:
                    raise Namespace331V2Error(f"event {event_id} crossing direction is invalid")
            if event_time < previous_time:
                raise Namespace331V2Error(f"events for particle {particle_id} are not time ordered")
            previous_time = event_time
            events.append(dict(event))
        residence.sort()
        for prior, current in zip(residence, residence[1:]):
            if current[0] < prior[1]:
                raise Namespace331V2Error(f"overlapping residence intervals for {particle_id}")
        if status == "EXCLUDED" and events:
            raise Namespace331V2Error(f"excluded particle {particle_id} cannot carry observation events")
        if status != "EXCLUDED":
            denominator += mass
        normalized.append({"particle_id": particle_id, "particle_identity": identity,
                           "mass_kg": mass, "observation_status": status,
                           "initial_region": initial_region, "events": events})
    if not math.isclose(denominator, contract["eligible_initial_mass_kg"],
                        rel_tol=0.0, abs_tol=1e-12 * max(1.0, denominator)):
        raise Namespace331V2Error("eligible initial mass does not equal observed+censored particle mass")
    return normalized


def validate_event_stream_v2(document: Mapping[str, Any], *, verify_sources: bool = False) -> dict[str, Any]:
    if not isinstance(document, Mapping) or document.get("schema") != EVENT_SCHEMA:
        raise Namespace331V2Error(f"event stream schema must be {EVENT_SCHEMA}")
    identity = document.get("case_identity")
    if not isinstance(identity, Mapping):
        raise Namespace331V2Error("case_identity is required")
    family = identity.get("family_id")
    case_id = identity.get("physical_case_id")
    if not isinstance(family, str) or not family.startswith("F") or not isinstance(case_id, str) or not case_id:
        raise Namespace331V2Error("case_identity must contain family_id and physical_case_id")
    identity_status = identity.get("identity_status")
    if identity_status not in {"CANONICAL", "UNKNOWN"}:
        raise Namespace331V2Error("historical aliases cannot replace the canonical case identity")
    contract, roles = _validate_contract_v2(document)
    # Re-run role validation with content when explicitly requested.  The
    # first pass is intentionally metadata-only for a parent preflight.
    if verify_sources:
        roles = _role_ref_map(document, verify_sources=True)
        contract["role_bindings"] = roles
    particles = _validate_particles_v2(document, contract)
    return {"family_id": family, "physical_case_id": case_id,
            "identity_status": identity_status, "contract": contract,
            "source_bindings": roles, "particles": particles}


def _unknown_result(normalized: Mapping[str, Any], reason: str) -> dict[str, Any]:
    return {
        "schema": RESULT_SCHEMA,
        "family_id": normalized["family_id"],
        "physical_case_id": normalized["physical_case_id"],
        "identity_status": normalized["identity_status"],
        "derived_status": "UNKNOWN",
        "unknown_reason": reason,
        "binding_status": {k: normalized["contract"][k]
                           for k in ("source_status", "region_owner_status", "control_status")},
        "labels": [{"particle_id": p["particle_id"],
                    "particle_identity": dict(p["particle_identity"]),
                    "label_status": "UNKNOWN_MISSING_CASE_IDENTITY_OR_BINDING"}
                   for p in normalized["particles"]],
        "metrics": {key: None for key in (
            "first_arrival_mass_weighted_time_s", "first_arrival_mass_kg", "first_arrival_count",
            "right_censored_mass_kg", "excluded_mass_kg", "no_arrival_observed_mass_kg",
            "crossing_count", "gross_crossing_mass_kg", "net_flux_mass_kg",
            "net_flux_rate_kg_s", "mass_weighted_residence_time_s", "residence_mass_time_kg_s")},
        "accounting_status": "UNKNOWN", "quality": dict(QUALIFICATION_UNKNOWN),
        "qualification": dict(QUALIFICATION_UNKNOWN), "model_invoked": False,
        "source_bindings": normalized["source_bindings"],
    }


def produce_labels_v2(document: Mapping[str, Any], *, verify_sources: bool = False) -> dict[str, Any]:
    normalized = validate_event_stream_v2(document, verify_sources=verify_sources)
    if normalized["identity_status"] == "UNKNOWN":
        return _unknown_result(normalized, "canonical case identity is UNKNOWN")
    contract = normalized["contract"]
    if any(contract[k] != STATUS_KNOWN for k in ("source_status", "region_owner_status", "control_status")):
        missing = [k for k in ("source_status", "region_owner_status", "control_status")
                   if contract[k] != STATUS_KNOWN]
        return _unknown_result(normalized, "missing binding(s): " + ", ".join(missing))
    # V1 computes only after its validator has accepted the event stream.  V2
    # has already performed the stricter tuple identity, target-region and
    # interval checks above, so its arithmetic is safe to reuse.
    legacy_document = copy.deepcopy(dict(document))
    legacy_document["schema"] = _V1.EVENT_SCHEMA
    result = _V1.produce_labels(legacy_document, verify_sources=verify_sources)
    result["schema"] = RESULT_SCHEMA
    result["identity_status"] = normalized["identity_status"]
    result["source_bindings"] = normalized["source_bindings"]
    by_id = {p["particle_id"]: p for p in normalized["particles"]}
    for label in result["labels"]:
        label["particle_identity"] = dict(by_id[label["particle_id"]]["particle_identity"])
    result["binding_status"] = {k: contract[k]
                                 for k in ("source_status", "region_owner_status", "control_status")}
    result["qualification"] = dict(QUALIFICATION_UNKNOWN)
    result["quality"] = dict(QUALIFICATION_UNKNOWN)
    return result


def validate_result_v2(result: Mapping[str, Any], document: Mapping[str, Any], *, verify_sources: bool = False) -> dict[str, Any]:
    if not isinstance(result, Mapping) or result.get("schema") != RESULT_SCHEMA:
        raise Namespace331V2Error(f"result schema must be {RESULT_SCHEMA}")
    expected = produce_labels_v2(document, verify_sources=verify_sources)
    for field in ("family_id", "physical_case_id", "identity_status", "derived_status",
                  "binding_status", "labels", "metrics", "source_bindings"):
        if result.get(field) != expected.get(field):
            raise Namespace331V2Error(f"result field {field} does not match independent recomputation")
    if result.get("qualification") != QUALIFICATION_UNKNOWN or result.get("quality") != QUALIFICATION_UNKNOWN:
        raise Namespace331V2Error("qualification must remain UNKNOWN")
    if result.get("model_invoked") is not False:
        raise Namespace331V2Error("model invocation is forbidden")
    return {"schema": VALIDATOR_SCHEMA, "status": "PASS_SOURCE_BOUND_DEVELOPMENT_UNKNOWN",
            "case_id": expected["physical_case_id"], "result_schema": RESULT_SCHEMA,
            "recomputed": True, "qualification": dict(QUALIFICATION_UNKNOWN)}


def build_request_v2(event_stream_path: Path | str, output_path: Path | str,
                     *, source_bindings: Sequence[Mapping[str, Any]], family_id: str,
                     physical_case_id: str, max_wall_seconds: int = 900) -> dict[str, Any]:
    input_path = Path(event_stream_path).expanduser()
    stream = _read_json(input_path, "event_stream")
    normalized = validate_event_stream_v2(stream, verify_sources=False)
    if normalized["family_id"] != family_id or normalized["physical_case_id"] != physical_case_id:
        raise Namespace331V2Error("request case identity differs from event stream")
    if not isinstance(max_wall_seconds, int) or max_wall_seconds <= 0:
        raise Namespace331V2Error("max_wall_seconds must be positive")
    refs: list[dict[str, Any]] = []
    for index, item in enumerate(source_bindings):
        if not isinstance(item, Mapping):
            raise Namespace331V2Error(f"source_bindings[{index}] must be an object")
        ref = dict(item)
        ref.setdefault("content_policy", "PARENT_GUARD_DEFERRED")
        # Validate declaration now; content is intentionally deferred.
        _sha(ref.get("sha256", ref.get("file_sha256")), f"source_bindings[{index}].sha256")
        refs.append(ref)
    request = {
        "schema": REQUEST_SCHEMA, "namespace": 331,
        "status": "READY_FOR_PARENT_GUARD_METADATA_ONLY",
        "case_identity": {"family_id": family_id, "physical_case_id": physical_case_id,
                           "identity_status": normalized["identity_status"]},
        "event_stream": {"path": str(input_path), "file_sha256": _sha_file(input_path),
                          "stat": _stat(input_path),
                          "content_policy": "SMALL_EVENT_STREAM_AFTER_RESERVATION"},
        "source_bindings": refs,
        "binding_requirements": {
            "role_bindings": normalized["contract"].get("role_bindings"),
            "known_requires_observed_sha256": True,
            "owner_sha_is_provenance_not_physical_identity": True,
            "unknown_case_identity_produces_all_unknown": True,
        },
        "execution": {
            "entrypoint": "ds_data02_stage2_namespace331_mass_weighted_labels_v2.py",
            "argv_template": ["--input", str(input_path), "--output", str(output_path)],
            "max_wall_seconds": max_wall_seconds,
            "source_read_phase": "after_atomic_parent_reservation",
            "parent_supervision_required": True, "model_invoked": False,
        },
        "output": {"path": str(Path(output_path).expanduser()),
                   "content_policy": "SMALL_LABEL_RESULT_AND_VALIDATION_JSON"},
        "qualification_boundary": dict(QUALIFICATION_UNKNOWN),
    }
    request["request_sha256"] = canonical_sha(request)
    return request


def _write_json(path: Path | str, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                      encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    produce = sub.add_parser("produce")
    produce.add_argument("--input", type=Path, required=True)
    produce.add_argument("--output", type=Path, required=True)
    produce.add_argument("--verify-sources", action="store_true")
    request = sub.add_parser("build-request")
    request.add_argument("--input", type=Path, required=True)
    request.add_argument("--output", type=Path, required=True)
    request.add_argument("--request", type=Path, required=True)
    request.add_argument("--family-id", required=True)
    request.add_argument("--physical-case-id", required=True)
    request.add_argument("--source-binding", action="append", nargs=5,
                         metavar=("ROLE", "SEMANTIC_ROLE", "PATH", "SHA256", "OBSERVED_SHA256"), default=[])
    args = parser.parse_args(argv)
    try:
        if args.command == "produce":
            stream = _read_json(args.input, "event_stream")
            result = produce_labels_v2(stream, verify_sources=args.verify_sources)
            _write_json(args.output, result)
            print(json.dumps({"output": str(args.output), "schema": result["schema"],
                              "derived_status": result["derived_status"]}, sort_keys=True))
        else:
            bindings = [{"role": role, "semantic_role": semantic, "path": path,
                         "sha256": digest, "observed_sha256": observed,
                         "content_verified": False, "hash_verified_after_reservation": True,
                         "content_policy": "PARENT_GUARD_DEFERRED"}
                        for role, semantic, path, digest, observed in args.source_binding]
            request_value = build_request_v2(
                args.input, args.output, source_bindings=bindings,
                family_id=args.family_id, physical_case_id=args.physical_case_id)
            _write_json(args.request, request_value)
            print(json.dumps({"request": str(args.request),
                              "request_sha256": request_value["request_sha256"]}, sort_keys=True))
    except (OSError, Namespace331V2Error) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
