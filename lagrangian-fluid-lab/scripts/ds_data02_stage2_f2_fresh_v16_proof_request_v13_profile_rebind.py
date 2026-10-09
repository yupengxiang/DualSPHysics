#!/usr/bin/env python3
"""Rebind the failed ROOT194 proof request to the actual producer profile.

ROOT194 reached the V8 result validator, but its frozen request carried the
old observer-profile digest ``4863...`` while the source-bound V66 worker
request actually carries canonical profile ``de4f...``.  This forward bridge
reads only the ROOT194 request, the small copied-worker request, and the V12
semantic sidecar.  It writes a new ROOT197 V8 request and a V13/V68 profile
sidecar.  It never opens the typed HDF5, the V16 JSON, BI4, or native frames.

The existing V12 consumer intentionally remains the execution interface.  Its
sidecar schema is retained for compatibility; the additive ``profile_rebind``
extension records the exact producer request and the replaced ROOT194 digest.
The old ROOT194 request stays immutable provenance and is never a payload
fallback.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
ROOT191_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_root191_typed_only_no_model_evaluator_v1.py"
V12_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v12.py"
V8_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v8.py"

ROOT194_V8_SCHEMA = "ds02.stage2.f2-fresh-v16-proof-consumer-request.v8"
V12_FORWARD_SCHEMA = "ds02.stage2.f2-fresh-v16-proof-consumer-v12-forward.v1"
V12_SIDECAR_SCHEMA = "ds02.stage2.f2-fresh-v16-missing-scope-sidecar.v1"
WORKER_SCHEMA = "ds02.stage2.f2-native-raw-to-typed-to-label-request.v2"
BRIDGE_SCHEMA = "ds02.stage2.f2-fresh-v16-profile-rebind-builder-v13.v1"
PROFILE_BINDING_SCHEMA = "ds02.stage2.f2-observer-profile-source-binding-v68.v1"
REQUEST_SCHEMA = "ds02.stage2.f2-root197-fresh-v16-proof-request-v13.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
MAX_METADATA_BYTES = 4 * 1024 * 1024

CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
COHORT_IDENTITY_SHA = "bc7c25286faeb5c9bbc9f27c176671c027bbc0650b9051f9d08241b4f3397d70"
EXPECTED_PROFILE_SHA = "de4f7ed699149424506216b30a2784750d54d6cc359fbfe9b9da3d299d7e5507"
EXPECTED_COUNT = 21114
EXPECTED_MASS = 21.114001002861187
EXPECTED_LATER_MISSING = 0.003000000142492354


class ProfileRebindError(RuntimeError):
    """Raised when the actual producer profile cannot safely replace ROOT194."""


def _load_root191() -> Any:
    spec = importlib.util.spec_from_file_location("ds02_bound_root191_for_profile_v13", ROOT191_SCRIPT)
    if spec is None or spec.loader is None:
        raise ProfileRebindError(f"cannot load ROOT191 metadata bridge: {ROOT191_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R191 = _load_root191()


def canonical_sha(value: Mapping[str, Any]) -> str:
    return R191.canonical_sha(value)


def sha256_file(path: Path | str, *, max_bytes: int | None = None) -> str:
    target = Path(path).expanduser()
    digest = hashlib.sha256()
    total = 0
    try:
        with target.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                total += len(block)
                if max_bytes is not None and total > max_bytes:
                    raise ProfileRebindError(f"metadata file exceeds bound: {target}")
                digest.update(block)
    except OSError as error:
        raise ProfileRebindError(f"cannot hash metadata file {target}: {error}") from error
    return digest.hexdigest()


def _file(value: Any, role: str, *, max_bytes: int = MAX_METADATA_BYTES) -> Path:
    if isinstance(value, Path):
        value = str(value)
    if not isinstance(value, str) or not value.startswith("/"):
        raise ProfileRebindError(f"{role} must be an absolute path")
    path = Path(value).expanduser()
    if path.is_symlink() or not path.is_file():
        raise ProfileRebindError(f"{role} must be a regular non-symlink file: {path}")
    if path.stat().st_size > max_bytes:
        raise ProfileRebindError(f"{role} exceeds the bounded JSON/source limit: {path}")
    return path.resolve()


def _json(value: Any, role: str, *, max_bytes: int = MAX_METADATA_BYTES) -> tuple[Path, dict[str, Any]]:
    path = _file(value, role, max_bytes=max_bytes)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProfileRebindError(f"cannot read {role}: {error}") from error
    if not isinstance(data, dict):
        raise ProfileRebindError(f"{role} must be a JSON object")
    return path, data


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in HEX64 for ch in value):
        raise ProfileRebindError(f"{role} must be a lowercase SHA-256")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists() or target.is_symlink():
        raise ProfileRebindError(f"refusing existing profile-rebind output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    return target


def _finite(value: Any, role: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ProfileRebindError(f"{role} must be finite numeric metadata")
    return float(value)


def _validate_profile(worker_path: Path, worker: Mapping[str, Any], v8: Mapping[str, Any],
                      *, require_replacement: bool = True) -> dict[str, Any]:
    if worker.get("schema") != WORKER_SCHEMA:
        raise ProfileRebindError("producer worker request is not the pinned V2 request schema")
    if worker.get("status") != "READY_FOR_PARENT_GUARD":
        raise ProfileRebindError("producer worker request is not a source-bound ready request")
    current = worker.get("current_binding")
    if not isinstance(current, Mapping) or current.get("sha256") != CURRENT_SHA:
        raise ProfileRebindError("producer worker CURRENT binding is not df7e")
    v15 = worker.get("v15_request")
    if not isinstance(v15, Mapping):
        raise ProfileRebindError("producer worker does not expose its bound V15 request")
    profile = v15.get("observer_profile")
    if not isinstance(profile, Mapping):
        raise ProfileRebindError("producer V15 observer_profile is missing")
    profile_sha = _sha(profile.get("sha256"), "producer observer_profile.sha256")
    if profile_sha != canonical_sha(profile):
        raise ProfileRebindError("producer observer_profile canonical SHA differs")
    if profile_sha != EXPECTED_PROFILE_SHA:
        raise ProfileRebindError(f"producer observer_profile is unexpected: {profile_sha}")
    if profile.get("current_binding_sha256") != CURRENT_SHA:
        raise ProfileRebindError("producer observer_profile current binding is not df7e")
    if profile.get("case_identity") != v8.get("expected", {}).get("case_identity"):
        raise ProfileRebindError("producer observer_profile case identity differs from ROOT194")
    if profile.get("query_times_s") != sorted(profile.get("query_times_s", [])):
        raise ProfileRebindError("producer observer_profile query times are not ordered")
    if not profile.get("query_times_s"):
        raise ProfileRebindError("producer observer_profile has no query times")
    time = v8.get("expected", {}).get("time")
    window = current.get("actual_time_window_s")
    if not isinstance(time, Mapping) or not isinstance(window, list) or len(window) != 2:
        raise ProfileRebindError("ROOT194 time/current window metadata is incomplete")
    if _finite(time.get("first_s"), "ROOT194 first_s") != _finite(window[0], "producer first_s"):
        raise ProfileRebindError("producer and ROOT194 first time differ")
    if _finite(time.get("last_s"), "ROOT194 last_s") != _finite(window[1], "producer last_s"):
        raise ProfileRebindError("producer and ROOT194 last time differ")
    if int(v15.get("cohort", {}).get("expected_initial_fluid_count", -1)) != EXPECTED_COUNT:
        raise ProfileRebindError("producer cohort count is not 21114")
    mass = v15.get("initial_mass_denominator")
    if not isinstance(mass, Mapping) or _finite(mass.get("denominator_kg"), "producer denominator") != EXPECTED_MASS:
        raise ProfileRebindError("producer mass denominator differs")
    if _finite(mass.get("later_missing_mass_kg"), "producer later missing mass") != EXPECTED_LATER_MISSING:
        raise ProfileRebindError("producer later missing mass differs")
    old_sha = _sha(time.get("observer_profile_sha256"), "ROOT194 observer_profile_sha256")
    if require_replacement and old_sha == profile_sha:
        raise ProfileRebindError("ROOT194 is already bound to this producer profile; no forward correction needed")
    return {
        "producer_worker_request": {"path": str(worker_path), "file_sha256": sha256_file(worker_path)},
        "profile_sha256": profile_sha,
        "profile_canonical_sha256": profile_sha,
        "previous_expected_sha256": old_sha,
        "profile_id": profile.get("profile_id"),
        "query_times_s": list(profile["query_times_s"]),
        "current_catalog_sha256": CURRENT_SHA,
        "trajectory_producer_sha256": profile.get("trajectory_producer_sha256"),
        "motion_control_end_angle_deg": profile.get("motion_control_end_angle_deg"),
    }


def build_request(*, root194_request: Path | str, producer_worker_request: Path | str,
                  sidecar_output: Path | str, output: Path | str,
                  case_id: str, attempt_id: str, fresh_output_root: Path | str) -> dict[str, Any]:
    outer_path, outer, v8_path, v8, root_info = R191._load_root194_request(Path(root194_request).expanduser().resolve())
    if not isinstance(case_id, str) or "ROOT197" not in case_id.upper():
        raise ProfileRebindError("new case_id must identify ROOT197")
    if not isinstance(attempt_id, str) or "ROOT197" not in attempt_id.upper():
        raise ProfileRebindError("new attempt_id must identify ROOT197")
    fresh_root = Path(fresh_output_root).expanduser().resolve()
    if fresh_root.exists() or "ROOT197" not in str(fresh_root).upper():
        raise ProfileRebindError("ROOT197 fresh proof namespace must be new")
    worker_path, worker = _json(producer_worker_request, "actual source-bound producer worker request")
    profile = _validate_profile(worker_path, worker, v8)
    old_sidecar_path, old_sidecar = _json(root_info["sidecar"]["path"], "ROOT194 semantic sidecar")
    if old_sidecar.get("schema") != V12_SIDECAR_SCHEMA or old_sidecar.get("sha256") != canonical_sha(old_sidecar):
        raise ProfileRebindError("ROOT194 semantic sidecar is not canonical V12 metadata")
    original_sidecar_sha = sha256_file(old_sidecar_path)
    sidecar = copy.deepcopy(old_sidecar)
    sidecar["historical_provenance"] = {
        "root194_sidecar": {"path": str(old_sidecar_path), "file_sha256": original_sidecar_sha,
                             "canonical_sha256": old_sidecar["sha256"]},
        "root194_request": {"path": str(v8_path), "file_sha256": root_info["v8_file_sha256"],
                             "canonical_sha256": root_info["v8_canonical_sha256"]},
    }
    # Keep the V12 schema and its source-request semantics, but explicitly
    # state that this source request is failed ROOT194 provenance only.
    producer_v66 = sidecar.get("producer_v66_request")
    if not isinstance(producer_v66, Mapping):
        raise ProfileRebindError("ROOT194 sidecar producer_v66_request is missing")
    sidecar["producer_v66_request"] = {
        "path": str(v8_path), "file_sha256": root_info["v8_file_sha256"],
        "canonical_sha256": root_info["v8_canonical_sha256"],
        "producer_case_id": producer_v66.get("producer_case_id"),
        "producer_attempt_id": producer_v66.get("producer_attempt_id"),
        "role": "ROOT194_FAILED_PROFILE_SOURCE_PROVENANCE_ONLY",
    }
    sidecar["profile_rebind_v13"] = {
        "schema": PROFILE_BINDING_SCHEMA,
        "producer_worker_request": profile["producer_worker_request"],
        "actual_profile_sha256": profile["profile_sha256"],
        "actual_profile_canonical_sha256": profile["profile_canonical_sha256"],
        "replaced_root194_expected_sha256": profile["previous_expected_sha256"],
        "current_catalog_sha256": CURRENT_SHA,
        "profile_id": profile["profile_id"],
        "query_times_s": profile["query_times_s"],
        "source_profile_is_actionable": True,
        "old_root194_request_is_not_an_execution_fallback": True,
    }
    sidecar["sha256"] = canonical_sha(sidecar)
    sidecar_path = _write_new(sidecar_output, sidecar)

    fresh = copy.deepcopy(v8)
    fresh["case_id"] = case_id
    fresh["attempt_id"] = attempt_id
    fresh["fresh_proof_namespace"] = {
        **dict(fresh.get("fresh_proof_namespace", {})), "root": str(fresh_root), "is_new": True,
        "rebound_from_root194": {"path": str(v8_path), "file_sha256": root_info["v8_file_sha256"]},
    }
    expected = fresh.get("expected")
    if not isinstance(expected, dict) or not isinstance(expected.get("time"), dict):
        raise ProfileRebindError("ROOT194 expected time contract is missing")
    expected["time"]["observer_profile_sha256"] = profile["profile_sha256"]
    expected["time"]["profile_binding_source"] = PROFILE_BINDING_SCHEMA
    fresh["observer_profile_source_binding"] = profile
    fresh["profile_rebind_provenance"] = {
        "schema": BRIDGE_SCHEMA,
        "replaces_request": {"path": str(v8_path), "file_sha256": root_info["v8_file_sha256"],
                              "canonical_sha256": root_info["v8_canonical_sha256"]},
        "producer_worker_request": profile["producer_worker_request"],
        "old_profile_sha256": profile["previous_expected_sha256"],
        "new_profile_sha256": profile["profile_sha256"],
        "payload_read": False,
    }
    marker = dict(fresh.get("v12_forward", {}))
    marker["semantic_sidecar"] = {"path": str(sidecar_path), "schema": V12_SIDECAR_SCHEMA,
                                   "sha256": sha256_file(sidecar_path)}
    marker["source_request"] = {
        "path": str(v8_path), "schema": ROOT194_V8_SCHEMA,
        "sha256": root_info["v8_canonical_sha256"],
        "file_sha256": root_info["v8_file_sha256"],
        "role": "ROOT194_FAILED_PROFILE_SOURCE_PROVENANCE_ONLY",
    }
    fresh["v12_forward"] = marker
    # Keep the original failed V66 request edge for audit, but make the new
    # request's actionable profile source the actual copied worker request.
    fresh["source_metadata_provenance"] = fresh.get("source_metadata")
    fresh["source_metadata"] = profile["producer_worker_request"]
    fresh["source_metadata"]["schema"] = WORKER_SCHEMA
    fresh["source_metadata"]["role"] = "ACTUAL_PROFILE_SOURCE_AFTER_ROOT194_FAILURE"
    fresh["status"] = "READY_FOR_PARENT_GUARD"
    fresh["sha256"] = canonical_sha(fresh)
    request_path = _write_new(output, fresh)
    return {
        "schema": BRIDGE_SCHEMA, "status": "READY_FOR_ROOT197_PARENT_GUARD",
        "request": str(request_path), "request_file_sha256": sha256_file(request_path),
        "request_canonical_sha256": fresh["sha256"],
        "sidecar": str(sidecar_path), "sidecar_file_sha256": sha256_file(sidecar_path),
        "root194_request": str(v8_path), "root194_failed_profile_sha256": profile["previous_expected_sha256"],
        "actual_profile_sha256": profile["profile_sha256"], "payload_read": False,
        "hdf5_or_bi4_read": False, "quality": dict(UNKNOWN), "qualification": dict(UNKNOWN),
    }


def validate_request(path: Path | str, sidecar: Path | str | None = None) -> dict[str, Any]:
    request_path, request = _json(path, "ROOT197 V13 proof request")
    if request.get("schema") != ROOT194_V8_SCHEMA or request.get("sha256") != canonical_sha(request):
        raise ProfileRebindError("ROOT197 request is not canonical V8")
    if "ROOT197" not in str(request.get("case_id", "")).upper() or "ROOT197" not in str(request.get("attempt_id", "")).upper():
        raise ProfileRebindError("ROOT197 request identity is missing")
    profile = request.get("observer_profile_source_binding")
    expected = request.get("expected", {}).get("time", {}) if isinstance(request.get("expected"), Mapping) else {}
    if not isinstance(profile, Mapping) or profile.get("profile_sha256") != expected.get("observer_profile_sha256"):
        raise ProfileRebindError("ROOT197 observer profile binding does not equal expected time SHA")
    if profile.get("profile_sha256") != EXPECTED_PROFILE_SHA or profile.get("current_catalog_sha256") != CURRENT_SHA:
        raise ProfileRebindError("ROOT197 observer profile is not the actual df7e-bound producer profile")
    marker = request.get("v12_forward")
    if not isinstance(marker, Mapping) or marker.get("source_request", {}).get("role") != "ROOT194_FAILED_PROFILE_SOURCE_PROVENANCE_ONLY":
        raise ProfileRebindError("ROOT197 failed-request provenance boundary is missing")
    sidecar_path, sidecar_value = _json(sidecar or marker.get("semantic_sidecar", {}).get("path"), "ROOT197 profile sidecar")
    if sidecar_value.get("schema") != V12_SIDECAR_SCHEMA or sidecar_value.get("sha256") != canonical_sha(sidecar_value):
        raise ProfileRebindError("ROOT197 V12 sidecar is not canonical")
    extension = sidecar_value.get("profile_rebind_v13")
    if not isinstance(extension, Mapping) or extension.get("schema") != PROFILE_BINDING_SCHEMA or extension.get("actual_profile_sha256") != EXPECTED_PROFILE_SHA:
        raise ProfileRebindError("ROOT197 V13/V68 profile sidecar extension is missing")
    sidecar_binding = marker.get("semantic_sidecar")
    if not isinstance(sidecar_binding, Mapping) or Path(str(sidecar_binding.get("path"))).expanduser().resolve() != sidecar_path.resolve():
        raise ProfileRebindError("ROOT197 V12 sidecar path differs")
    if sidecar_binding.get("sha256") != sha256_file(sidecar_path):
        raise ProfileRebindError("ROOT197 V12 sidecar file SHA differs")
    worker_binding = profile.get("producer_worker_request")
    if not isinstance(worker_binding, Mapping):
        raise ProfileRebindError("ROOT197 producer profile worker binding is missing")
    worker_path = _file(worker_binding.get("path"), "ROOT197 producer worker request")
    if worker_binding.get("file_sha256") != sha256_file(worker_path):
        raise ProfileRebindError("ROOT197 producer worker request SHA differs")
    _, worker = _json(worker_path, "ROOT197 producer worker request")
    actual = _validate_profile(worker_path, worker, request, require_replacement=False)
    if actual.get("profile_sha256") != profile.get("profile_sha256"):
        raise ProfileRebindError("ROOT197 request profile differs from the producer worker")
    return {"schema": BRIDGE_SCHEMA, "status": "ROOT197_PROFILE_METADATA_VALIDATED_READY_FOR_PARENT",
            "request": {"path": str(request_path), "file_sha256": sha256_file(request_path), "canonical_sha256": request["sha256"]},
            "sidecar": {"path": str(sidecar_path), "file_sha256": sha256_file(sidecar_path), "canonical_sha256": sidecar_value["sha256"]},
            "actual_profile_sha256": EXPECTED_PROFILE_SHA, "payload_read": False,
            "hdf5_or_bi4_read": False, "quality": dict(UNKNOWN), "qualification": dict(UNKNOWN)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--root194-request", type=Path, required=True)
    build.add_argument("--producer-worker-request", type=Path, required=True)
    build.add_argument("--sidecar-output", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--case-id", required=True)
    build.add_argument("--attempt-id", required=True)
    build.add_argument("--fresh-output-root", type=Path, required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--request", type=Path, required=True)
    validate.add_argument("--sidecar", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            value = build_request(root194_request=args.root194_request.absolute(),
                                  producer_worker_request=args.producer_worker_request.absolute(),
                                  sidecar_output=args.sidecar_output.absolute(), output=args.output.absolute(),
                                  case_id=args.case_id, attempt_id=args.attempt_id,
                                  fresh_output_root=args.fresh_output_root.absolute())
        else:
            value = validate_request(args.request.absolute(), args.sidecar.absolute() if args.sidecar else None)
    except (ProfileRebindError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"ROOT197 V13/V68 profile rebind: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
