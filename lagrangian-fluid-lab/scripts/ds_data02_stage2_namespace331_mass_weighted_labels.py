#!/usr/bin/env python3
"""Source-bound mass-weighted event labels for namespace331.

This is a small, model-free consumer for an already materialized event
stream.  It does not open trajectory/H5/BI4/raw data and it never infers a
physical owner, source cohort, or control from a path or an owner hash.  A
parent guard may provide such a stream after it has verified the scientific
sources.  Until all three bindings are explicitly ``KNOWN`` the numerical
labels remain ``UNKNOWN``.

The event contract deliberately separates two kinds of missing observation:

* ``CENSORED`` is an eligible particle whose observation ended without a
  complete arrival/exit history; its mass remains in the eligible denominator
  and is reported as a censoring bucket.
* ``EXCLUDED`` is outside the declared analysis cohort.  Its mass is reported
  separately and is never silently treated as censored or as an observed
  particle.

The implementation is intentionally independent of the large scientific
products.  The CLI accepts only bounded JSON metadata/event streams and is
therefore suitable for a later parent-supervised execution request.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence


EVENT_SCHEMA = "ds02.stage2.namespace331.mass-weighted-event-stream.v1"
RESULT_SCHEMA = "ds02.stage2.namespace331.mass-weighted-label-result.v1"
REQUEST_SCHEMA = "ds02.stage2.namespace331.mass-weighted-label-request.v1"
VALIDATOR_SCHEMA = "ds02.stage2.namespace331.mass-weighted-label-validation.v1"
STATUS_KNOWN = "KNOWN"
STATUS_UNKNOWN = "UNKNOWN"
PARTICLE_STATUSES = {"OBSERVED", "CENSORED", "EXCLUDED"}
EVENT_TYPES = {"ARRIVAL", "CROSSING", "RESIDENCE_INTERVAL"}
DIRECTIONS = {"IN", "OUT"}
QUALIFICATION_UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
MAX_METADATA_BYTES = 8 * 1024 * 1024
_HEX64 = set("0123456789abcdef")


class Namespace331Error(ValueError):
    """A malformed, unbound, or scientifically ambiguous event contract."""


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def canonical_sha(value: Mapping[str, Any]) -> str:
    """Return the canonical hash of an object without its self hash."""
    return hashlib.sha256(_canonical({k: v for k, v in value.items()
                                      if k not in {"sha256", "request_sha256"}}).encode()).hexdigest()


def _sha256_file(path: Path | str, *, maximum: int = MAX_METADATA_BYTES) -> str:
    target = Path(path).expanduser()
    if target.is_symlink() or not target.is_file():
        raise Namespace331Error(f"expected regular non-symlink file: {target}")
    if target.stat().st_size > maximum:
        raise Namespace331Error(f"metadata size bound exceeded: {target}")
    digest = hashlib.sha256()
    with target.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stat(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser()
    if target.is_symlink() or not target.exists():
        return {"exists": False}
    value = target.stat()
    return {
        "exists": True,
        "kind": "file" if target.is_file() else "directory",
        "bytes": int(value.st_size) if target.is_file() else None,
        "mode_bits": int(value.st_mode & 0o7777),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
    }


def _read_json(path: Path | str, *, role: str) -> dict[str, Any]:
    target = Path(path).expanduser()
    if target.is_symlink() or not target.is_file():
        raise Namespace331Error(f"{role} must be a regular non-symlink JSON file: {target}")
    if target.stat().st_size > MAX_METADATA_BYTES:
        raise Namespace331Error(f"{role} exceeds the bounded JSON input limit: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise Namespace331Error(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise Namespace331Error(f"{role} must be a JSON object")
    return value


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Namespace331Error(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise Namespace331Error(f"{name} must be finite")
    return result


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in _HEX64 for c in value.lower()):
        raise Namespace331Error(f"{name} must be a lowercase/uppercase SHA-256")
    return value.lower()


def _status(value: Any, name: str) -> str:
    if value not in {STATUS_KNOWN, STATUS_UNKNOWN}:
        raise Namespace331Error(f"{name} must be KNOWN or UNKNOWN")
    return str(value)


def _source_ref(value: Any, index: int, *, verify_content: bool = False) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise Namespace331Error(f"source_bindings[{index}] must be an object")
    role = value.get("role")
    path = value.get("path")
    if not isinstance(role, str) or not role or not isinstance(path, str) or not path:
        raise Namespace331Error(f"source_bindings[{index}] needs role and path")
    expected = _sha(value.get("sha256", value.get("file_sha256")),
                    f"source_bindings[{index}].sha256")
    policy = value.get("content_policy")
    if not isinstance(policy, str) or not policy:
        raise Namespace331Error(f"source_bindings[{index}].content_policy is required")
    result = {
        "role": role,
        "path": path,
        "sha256": expected,
        "content_policy": policy,
        "declared_bytes": value.get("bytes", value.get("declared_bytes")),
        "historical_stat": dict(value.get("historical_stat", {}))
        if isinstance(value.get("historical_stat"), Mapping) else None,
    }
    target = Path(path).expanduser()
    if verify_content:
        observed = _sha256_file(target)
        if observed != expected:
            raise Namespace331Error(f"source binding SHA mismatch for {role}")
        result["observed_stat"] = _stat(target)
        result["content_verified"] = True
    else:
        # A missing path is a deferred parent-guard source, never a fallback.
        result["observed_stat"] = _stat(target)
        result["content_verified"] = False
        result["content_verification"] = "DEFERRED_PARENT_GUARD_NO_FALLBACK"
    return result


def _validate_source_bindings(value: Any, *, verify_content: bool = False) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise Namespace331Error("source_bindings must be a nonempty list")
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        ref = _source_ref(item, index, verify_content=verify_content)
        if ref["role"] in seen:
            raise Namespace331Error(f"duplicate source binding role: {ref['role']}")
        seen.add(ref["role"])
        result.append(ref)
    return result


def _validate_contract(document: Mapping[str, Any]) -> dict[str, Any]:
    contract = document.get("observation_contract")
    if not isinstance(contract, Mapping):
        raise Namespace331Error("observation_contract is required")
    source_status = _status(contract.get("source_status"), "source_status")
    owner_status = _status(contract.get("region_owner_status"), "region_owner_status")
    control_status = _status(contract.get("control_status"), "control_status")
    window = contract.get("observation_window_s")
    if not isinstance(window, list) or len(window) != 2:
        raise Namespace331Error("observation_window_s must contain [start, end]")
    start, end = (_finite(window[0], "observation_window_s[0]"),
                  _finite(window[1], "observation_window_s[1]"))
    if start < 0 or end <= start:
        raise Namespace331Error("observation window must be finite, nonnegative, and increasing")
    source_region = contract.get("source_region")
    target_region = contract.get("target_region")
    if not isinstance(source_region, str) or not source_region:
        raise Namespace331Error("source_region is required")
    if not isinstance(target_region, str) or not target_region:
        raise Namespace331Error("target_region is required")
    denominator = _finite(contract.get("eligible_initial_mass_kg"),
                          "eligible_initial_mass_kg")
    if denominator <= 0:
        raise Namespace331Error("eligible_initial_mass_kg must be positive")
    return {
        "source_status": source_status,
        "region_owner_status": owner_status,
        "control_status": control_status,
        "observation_window_s": [start, end],
        "source_region": source_region,
        "target_region": target_region,
        "eligible_initial_mass_kg": denominator,
    }


def _validate_particles(document: Mapping[str, Any], contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    particles = document.get("particles")
    if not isinstance(particles, list) or not particles:
        raise Namespace331Error("particles must be a nonempty list")
    start, end = contract["observation_window_s"]
    ids: set[str] = set()
    event_ids: set[str] = set()
    normalized: list[dict[str, Any]] = []
    denominator = 0.0
    excluded_mass = 0.0
    for index, raw in enumerate(particles):
        if not isinstance(raw, Mapping):
            raise Namespace331Error(f"particles[{index}] must be an object")
        particle_id = raw.get("particle_id")
        if not isinstance(particle_id, str) or not particle_id or particle_id in ids:
            raise Namespace331Error(f"particle_id missing or duplicated: {particle_id!r}")
        ids.add(particle_id)
        mass = _finite(raw.get("mass_kg"), f"particles[{index}].mass_kg")
        if mass <= 0:
            raise Namespace331Error(f"particles[{index}].mass_kg must be positive")
        status = raw.get("observation_status")
        if status not in PARTICLE_STATUSES:
            raise Namespace331Error(f"particles[{index}].observation_status is invalid")
        initial_region = raw.get("initial_region")
        if not isinstance(initial_region, str) or not initial_region:
            raise Namespace331Error(f"particles[{index}].initial_region is required")
        raw_events = raw.get("events", [])
        if not isinstance(raw_events, list):
            raise Namespace331Error(f"particles[{index}].events must be a list")
        events: list[dict[str, Any]] = []
        previous_time = -math.inf
        for event_index, event in enumerate(raw_events):
            if not isinstance(event, Mapping):
                raise Namespace331Error(f"particle {particle_id} event is not an object")
            event_id = event.get("event_id")
            if not isinstance(event_id, str) or not event_id or event_id in event_ids:
                raise Namespace331Error(f"event_id missing or duplicated: {event_id!r}")
            event_ids.add(event_id)
            event_type = event.get("event_type")
            if event_type not in EVENT_TYPES:
                raise Namespace331Error(f"event {event_id} has unsupported event_type")
            if event_type == "RESIDENCE_INTERVAL":
                event_start = _finite(event.get("start_time_s"), f"{event_id}.start_time_s")
                event_end = _finite(event.get("end_time_s"), f"{event_id}.end_time_s")
                if event_start < start or event_end > end or event_end <= event_start:
                    raise Namespace331Error(f"event {event_id} has an invalid residence interval")
                event_time = event_start
                if event.get("region") != contract["target_region"]:
                    raise Namespace331Error(f"event {event_id} residence region is not target_region")
            else:
                event_time = _finite(event.get("time_s"), f"{event_id}.time_s")
                if event_time < start or event_time > end:
                    raise Namespace331Error(f"event {event_id} lies outside observation window")
                if event_type == "ARRIVAL" and event.get("region") != contract["target_region"]:
                    raise Namespace331Error(f"event {event_id} arrival region is not target_region")
                if event_type == "CROSSING":
                    if event.get("direction") not in DIRECTIONS:
                        raise Namespace331Error(f"event {event_id} crossing direction is invalid")
                    if event.get("region") != contract["target_region"]:
                        raise Namespace331Error(f"event {event_id} crossing region is not target_region")
            if event_time < previous_time:
                raise Namespace331Error(f"events for particle {particle_id} are not time ordered")
            previous_time = event_time
            events.append(dict(event))
        if status == "EXCLUDED" and events:
            raise Namespace331Error(f"excluded particle {particle_id} cannot carry observation events")
        if status == "EXCLUDED":
            excluded_mass += mass
        else:
            denominator += mass
        normalized.append({"particle_id": particle_id, "mass_kg": mass,
                           "observation_status": status, "initial_region": initial_region,
                           "events": events})
    if not math.isclose(denominator, contract["eligible_initial_mass_kg"],
                        rel_tol=0.0, abs_tol=1e-12 * max(1.0, denominator)):
        raise Namespace331Error("eligible initial mass does not equal observed+censored particle mass")
    return normalized


def validate_event_stream(document: Mapping[str, Any], *, verify_sources: bool = False) -> dict[str, Any]:
    """Validate a bounded event stream and return normalized metadata."""
    if not isinstance(document, Mapping) or document.get("schema") != EVENT_SCHEMA:
        raise Namespace331Error(f"event stream schema must be {EVENT_SCHEMA}")
    identity = document.get("case_identity")
    if not isinstance(identity, Mapping):
        raise Namespace331Error("case_identity is required")
    family = identity.get("family_id")
    case_id = identity.get("physical_case_id")
    if not isinstance(family, str) or not family.startswith("F") or not isinstance(case_id, str) or not case_id:
        raise Namespace331Error("case_identity must contain family_id and physical_case_id")
    if identity.get("identity_status") not in {"CANONICAL", "UNKNOWN"}:
        raise Namespace331Error("historical aliases cannot replace the canonical case identity")
    contract = _validate_contract(document)
    source_bindings = _validate_source_bindings(document.get("source_bindings"),
                                                verify_content=verify_sources)
    particles = _validate_particles(document, contract)
    return {"family_id": family, "physical_case_id": case_id,
            "identity_status": identity.get("identity_status"),
            "contract": contract, "source_bindings": source_bindings,
            "particles": particles}


def _unknown_result(normalized: Mapping[str, Any], reason: str) -> dict[str, Any]:
    particles = normalized["particles"]
    return {
        "schema": RESULT_SCHEMA,
        "family_id": normalized["family_id"],
        "physical_case_id": normalized["physical_case_id"],
        "identity_status": normalized["identity_status"],
        "derived_status": "UNKNOWN",
        "unknown_reason": reason,
        "binding_status": {
            key: normalized["contract"][key]
            for key in ("source_status", "region_owner_status", "control_status")
        },
        "observation_window_s": list(normalized["contract"]["observation_window_s"]),
        "source_region": normalized["contract"]["source_region"],
        "target_region": normalized["contract"]["target_region"],
        "labels": [{"particle_id": item["particle_id"],
                    "label_status": "UNKNOWN_MISSING_SOURCE_OWNER_OR_CONTROL"}
                   for item in particles],
        "metrics": {
            "first_arrival_mass_weighted_time_s": None,
            "first_arrival_mass_kg": None,
            "first_arrival_count": None,
            "right_censored_mass_kg": None,
            "excluded_mass_kg": None,
            "no_arrival_observed_mass_kg": None,
            "crossing_count": None,
            "gross_crossing_mass_kg": None,
            "net_flux_mass_kg": None,
            "net_flux_rate_kg_s": None,
            "mass_weighted_residence_time_s": None,
            "residence_mass_time_kg_s": None,
        },
        "accounting_status": "UNKNOWN",
        "quality": dict(QUALIFICATION_UNKNOWN),
        "qualification": dict(QUALIFICATION_UNKNOWN),
        "model_invoked": False,
        "censoring_and_exclusion_policy": {
            "censored_is_eligible_right_censoring": True,
            "excluded_is_outside_denominator": True,
        },
        "source_bindings": normalized["source_bindings"],
    }


def produce_labels(document: Mapping[str, Any], *, verify_sources: bool = False) -> dict[str, Any]:
    """Produce mass-weighted first-arrival/crossing/residence labels."""
    normalized = validate_event_stream(document, verify_sources=verify_sources)
    contract = normalized["contract"]
    if any(contract[key] != STATUS_KNOWN for key in
           ("source_status", "region_owner_status", "control_status")):
        missing = [key for key in ("source_status", "region_owner_status", "control_status")
                   if contract[key] != STATUS_KNOWN]
        return _unknown_result(normalized, "missing binding(s): " + ", ".join(missing))
    start, end = contract["observation_window_s"]
    window = end - start
    target = contract["target_region"]
    source = contract["source_region"]
    labels: list[dict[str, Any]] = []
    arrival_mass = 0.0
    arrival_time_mass = 0.0
    censored_mass = 0.0
    excluded_mass = 0.0
    no_arrival_mass = 0.0
    crossing_count = 0
    gross_crossing_mass = 0.0
    net_flux_mass = 0.0
    residence_mass_time = 0.0
    for particle in normalized["particles"]:
        mass = particle["mass_kg"]
        status = particle["observation_status"]
        if status == "EXCLUDED":
            excluded_mass += mass
            labels.append({"particle_id": particle["particle_id"], "label_status": "EXCLUDED",
                           "first_arrival_time_s": None, "crossing_count": 0,
                           "residence_time_s": 0.0})
            continue
        arrival_times = [float(event["time_s"]) for event in particle["events"]
                         if event["event_type"] == "ARRIVAL" and event.get("region") == target]
        first_arrival = min(arrival_times) if arrival_times else None
        if first_arrival is not None:
            arrival_mass += mass
            arrival_time_mass += mass * first_arrival
            label_status = "OBSERVED_FIRST_ARRIVAL"
        elif status == "CENSORED":
            censored_mass += mass
            label_status = "RIGHT_CENSORED_NO_ARRIVAL"
        else:
            no_arrival_mass += mass
            label_status = "NO_ARRIVAL_IN_OBSERVED_WINDOW"
        crossings = [event for event in particle["events"] if event["event_type"] == "CROSSING"]
        particle_net = 0.0
        for event in crossings:
            crossing_count += 1
            gross_crossing_mass += mass
            sign = 1.0 if event["direction"] == "IN" else -1.0
            particle_net += sign * mass
        net_flux_mass += particle_net
        intervals = [event for event in particle["events"] if event["event_type"] == "RESIDENCE_INTERVAL"]
        residence_time = sum(float(event["end_time_s"]) - float(event["start_time_s"])
                             for event in intervals)
        residence_mass_time += mass * residence_time
        labels.append({"particle_id": particle["particle_id"], "label_status": label_status,
                       "first_arrival_time_s": first_arrival, "crossing_count": len(crossings),
                       "residence_time_s": residence_time})
    metrics = {
        "first_arrival_mass_weighted_time_s": (arrival_time_mass / arrival_mass
                                                if arrival_mass > 0 else None),
        "first_arrival_mass_kg": arrival_mass,
        "first_arrival_count": sum(1 for row in labels if row["label_status"] == "OBSERVED_FIRST_ARRIVAL"),
        "right_censored_mass_kg": censored_mass,
        "excluded_mass_kg": excluded_mass,
        "no_arrival_observed_mass_kg": no_arrival_mass,
        "crossing_count": crossing_count,
        "gross_crossing_mass_kg": gross_crossing_mass,
        "net_flux_mass_kg": net_flux_mass,
        "net_flux_rate_kg_s": net_flux_mass / window,
        "mass_weighted_residence_time_s": (residence_mass_time / contract["eligible_initial_mass_kg"]),
        "residence_mass_time_kg_s": residence_mass_time,
    }
    return {
        "schema": RESULT_SCHEMA,
        "family_id": normalized["family_id"],
        "physical_case_id": normalized["physical_case_id"],
        "identity_status": normalized["identity_status"],
        "derived_status": "OBSERVED_METADATA_ONLY_DEVELOPMENT_UNKNOWN",
        "binding_status": dict((key, contract[key]) for key in
                                ("source_status", "region_owner_status", "control_status")),
        "observation_window_s": [start, end],
        "source_region": source,
        "target_region": target,
        "labels": labels,
        "metrics": metrics,
        "mass_accounting": {
            "eligible_initial_mass_kg": contract["eligible_initial_mass_kg"],
            "observed_particle_mass_kg": contract["eligible_initial_mass_kg"] - censored_mass,
            "right_censored_mass_kg": censored_mass,
            "excluded_mass_kg": excluded_mass,
            "denominator_excludes_excluded": True,
            "denominator_conserved": math.isclose(
                contract["eligible_initial_mass_kg"],
                (contract["eligible_initial_mass_kg"] - censored_mass) + censored_mass,
                rel_tol=0.0, abs_tol=1e-12),
        },
        "censoring_and_exclusion_policy": {
            "censored_is_eligible_right_censoring": True,
            "excluded_is_outside_denominator": True,
            "unobserved_endpoint_is_not_reclassified_as_excluded": True,
        },
        "source_bindings": normalized["source_bindings"],
        "quality": dict(QUALIFICATION_UNKNOWN),
        "qualification": dict(QUALIFICATION_UNKNOWN),
        "model_invoked": False,
    }


def validate_result(result: Mapping[str, Any], document: Mapping[str, Any], *,
                    verify_sources: bool = False) -> dict[str, Any]:
    """Independently validate result identity, status, and recomputed labels."""
    if not isinstance(result, Mapping) or result.get("schema") != RESULT_SCHEMA:
        raise Namespace331Error(f"result schema must be {RESULT_SCHEMA}")
    expected = produce_labels(document, verify_sources=verify_sources)
    for field in ("family_id", "physical_case_id", "identity_status", "derived_status",
                  "binding_status", "observation_window_s", "source_region", "target_region",
                  "labels", "metrics", "source_bindings"):
        if result.get(field) != expected.get(field):
            raise Namespace331Error(f"result field {field} does not match independent recomputation")
    if result.get("quality") != QUALIFICATION_UNKNOWN or result.get("qualification") != QUALIFICATION_UNKNOWN:
        raise Namespace331Error("qualification must remain UNKNOWN")
    if result.get("model_invoked") is not False:
        raise Namespace331Error("model invocation is forbidden")
    return {"schema": VALIDATOR_SCHEMA, "status": "PASS_SOURCE_BOUND_DEVELOPMENT_UNKNOWN",
            "case_id": expected["physical_case_id"], "result_schema": RESULT_SCHEMA,
            "recomputed": True, "qualification": dict(QUALIFICATION_UNKNOWN)}


def build_request(event_stream_path: Path | str, output_path: Path | str,
                  *, source_bindings: Sequence[Mapping[str, Any]], family_id: str,
                  physical_case_id: str, source_status: str = STATUS_UNKNOWN,
                  region_owner_status: str = STATUS_UNKNOWN,
                  control_status: str = STATUS_UNKNOWN,
                  max_wall_seconds: int = 900) -> dict[str, Any]:
    """Build a bounded parent request without reading scientific payloads."""
    input_path = Path(event_stream_path).expanduser()
    stream = _read_json(input_path, role="event_stream")
    normalized = validate_event_stream(stream, verify_sources=False)
    if normalized["family_id"] != family_id or normalized["physical_case_id"] != physical_case_id:
        raise Namespace331Error("request case identity differs from event stream")
    if not source_bindings:
        raise Namespace331Error("at least one external source binding is required")
    for name, value in (("source_status", source_status),
                        ("region_owner_status", region_owner_status),
                        ("control_status", control_status)):
        _status(value, name)
    if not isinstance(max_wall_seconds, int) or max_wall_seconds <= 0:
        raise Namespace331Error("max_wall_seconds must be a positive integer")
    input_stat = _stat(input_path)
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "namespace": 331,
        "status": "READY_FOR_PARENT_GUARD_METADATA_ONLY",
        "case_identity": {"family_id": family_id, "physical_case_id": physical_case_id,
                           "identity_status": normalized["identity_status"]},
        "event_stream": {
            "path": str(input_path), "file_sha256": _sha256_file(input_path),
            "stat": input_stat, "content_policy": "SMALL_EVENT_STREAM_AFTER_RESERVATION",
        },
        "source_bindings": [_source_ref(item, index, verify_content=False)
                            for index, item in enumerate(source_bindings)],
        "binding_requirements": {
            "source_status": source_status,
            "region_owner_status": region_owner_status,
            "control_status": control_status,
            "missing_any_binding_keeps_all_numeric_labels_unknown": True,
            "owner_sha_is_provenance_not_physical_identity": True,
        },
        "execution": {
            "entrypoint": "ds_data02_stage2_namespace331_mass_weighted_labels.py",
            "argv_template": ["--input", str(input_path), "--output", str(output_path)],
            "max_wall_seconds": max_wall_seconds,
            "source_read_phase": "after_atomic_parent_reservation",
            "parent_supervision_required": True,
            "model_invoked": False,
        },
        "output": {"path": str(Path(output_path).expanduser()),
                   "content_policy": "SMALL_LABEL_RESULT_AND_VALIDATION_JSON"},
        "qualification_boundary": dict(QUALIFICATION_UNKNOWN),
        "scientific_scope": {
            "first_arrival": "observed event stream only",
            "repeated_crossing": "explicit saved/event rows only; hidden crossings UNKNOWN",
            "residence": "explicit intervals only",
            "net_flux": "signed explicit crossings only",
            "censoring": "eligible mass retained in denominator",
            "exclusion": "outside denominator and separately reported",
        },
    }
    request["request_sha256"] = canonical_sha(request)
    return request


def _write_json(path: Path | str, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                      encoding="utf-8")


def main() -> int:
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
    request.add_argument("--source-binding", action="append", nargs=3,
                         metavar=("ROLE", "PATH", "SHA256"), default=[])
    args = parser.parse_args()
    try:
        if args.command == "produce":
            stream = _read_json(args.input, role="event_stream")
            result = produce_labels(stream, verify_sources=args.verify_sources)
            _write_json(args.output, result)
            print(json.dumps({"output": str(args.output), "schema": result["schema"],
                              "derived_status": result["derived_status"]}, sort_keys=True))
        else:
            refs = [{"role": role, "path": path, "sha256": digest,
                     "content_policy": "PARENT_GUARD_DEFERRED"}
                    for role, path, digest in args.source_binding]
            request_value = build_request(
                args.input, args.output, source_bindings=refs,
                family_id=args.family_id, physical_case_id=args.physical_case_id)
            _write_json(args.request, request_value)
            print(json.dumps({"request": str(args.request),
                              "request_sha256": request_value["request_sha256"]}, sort_keys=True))
    except (OSError, Namespace331Error) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
