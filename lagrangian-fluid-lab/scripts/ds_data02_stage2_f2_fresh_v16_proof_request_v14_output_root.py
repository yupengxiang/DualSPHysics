#!/usr/bin/env python3
"""ROOT200 forward of the V13 profile request with a bounded proof root.

ROOT197 reached V12 result validation but V8 rejected the proof output because
the parent supplied a new Home attempt directory that was absent from the
request's relocation roots.  V14 carries the same source-bound observer
profile and V12 sidecar, then adds exactly one explicit ROOT200 output root to
``relocation.output_root``.  The producer result/typed paths and forbidden
original roots remain unchanged.  This module only reads bounded request and
source metadata; it does not run V12, open the V16 result, or read H5/BI4.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V13_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_fresh_v16_proof_request_v13_profile_rebind.py"
V8_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v8.py"
V12_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v12.py"
REQUEST_SCHEMA = "ds02.stage2.f2-fresh-v16-proof-consumer-request.v8"
V12_FORWARD_SCHEMA = "ds02.stage2.f2-fresh-v16-proof-consumer-v12-forward.v1"
V14_SCHEMA = "ds02.stage2.f2-fresh-v16-profile-output-root-builder-v14.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


class OutputRootRebindError(RuntimeError):
    """Raised when the explicit ROOT200 proof output root is unsafe."""


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise OutputRootRebindError(f"cannot load bound module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V13 = _load(V13_SCRIPT, "ds02_bound_profile_v13_for_v14")
V8 = _load(V8_SCRIPT, "ds02_bound_v8_for_v14")
V12 = _load(V12_SCRIPT, "ds02_bound_v12_for_v14")


def _json(path: Path | str, role: str) -> tuple[Path, dict[str, Any]]:
    target = Path(path).expanduser().resolve()
    if target.is_symlink() or not target.is_file():
        raise OutputRootRebindError(f"{role} must be an existing regular file: {target}")
    if target.stat().st_size > 16 * 1024 * 1024:
        raise OutputRootRebindError(f"{role} exceeds bounded metadata size")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise OutputRootRebindError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise OutputRootRebindError(f"{role} must be a JSON object")
    return target, value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists() or target.is_symlink():
        raise OutputRootRebindError(f"refusing existing ROOT200 request output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    return target


def _root200(value: Any, role: str) -> str:
    if not isinstance(value, str) or not value.startswith("/"):
        raise OutputRootRebindError(f"{role} must be an absolute path")
    path = Path(value).expanduser().resolve(strict=False)
    if "ROOT200" not in str(path).upper():
        raise OutputRootRebindError(f"{role} must carry the fresh ROOT200 identity")
    if path in {Path("/"), Path("/tmp"), Path("/var/tmp"), Path("/home"), Path("/home/jade")}:
        raise OutputRootRebindError(f"{role} is too broad")
    return str(path)


def build_request(*, root194_request: Path, producer_worker_request: Path,
                  sidecar_output: Path, output: Path, case_id: str,
                  attempt_id: str, fresh_output_root: Path) -> dict[str, Any]:
    if "ROOT200" not in case_id.upper() or "ROOT200" not in attempt_id.upper():
        raise OutputRootRebindError("ROOT200 case and attempt identities are required")
    fresh_root = _root200(str(fresh_output_root), "fresh proof output root")
    # V13 remains the source/profile authority.  Use an ephemeral V13 request
    # only to avoid changing its ROOT197 identity; the final sidecar is the
    # requested immutable output and the intermediate request never becomes
    # an actionable source.
    with tempfile.TemporaryDirectory(prefix="ds02-root200-v14-") as temporary:
        temporary_path = Path(temporary)
        intermediate_request = temporary_path / "root197-intermediate.json"
        intermediate_root = temporary_path / "STAGE2_F2_ROOT197_INTERMEDIATE"
        V13.build_request(
            root194_request=root194_request, producer_worker_request=producer_worker_request,
            sidecar_output=sidecar_output, output=intermediate_request,
            case_id="STAGE2_F2_ROOT197_V13_INTERMEDIATE_20261009",
            attempt_id="f2-s1-root197-v13-intermediate-001",
            fresh_output_root=intermediate_root,
        )
        _intermediate_path, request = _json(intermediate_request, "V13 intermediate request")
    request["case_id"] = case_id
    request["attempt_id"] = attempt_id
    relocation = request.get("relocation")
    if not isinstance(relocation, dict):
        raise OutputRootRebindError("V13 request relocation contract is missing")
    old_output_root = relocation.get("output_root")
    relocation["output_root"] = fresh_root
    relocation["proof_output_root_binding"] = {
        "schema": V14_SCHEMA,
        "path": fresh_root,
        "role": "V12/V8 proof output only",
        "proof_output_only": True,
        "source_result_root_unchanged": True,
        "parent_reservation_required": True,
        "broad_home_fallback_forbidden": True,
        "replaced_v13_output_root": old_output_root,
    }
    namespace = request.get("fresh_proof_namespace")
    if not isinstance(namespace, dict):
        raise OutputRootRebindError("V13 fresh proof namespace is missing")
    namespace["root"] = fresh_root
    namespace["is_new"] = True
    namespace["output_root_rebound_v14"] = True
    provenance = request.get("profile_rebind_provenance")
    if not isinstance(provenance, dict):
        raise OutputRootRebindError("V13 profile provenance is missing")
    provenance["forward_version"] = V14_SCHEMA
    provenance["proof_output_root"] = fresh_root
    forward = request.get("v12_forward")
    if not isinstance(forward, dict) or forward.get("schema") != V12_FORWARD_SCHEMA:
        raise OutputRootRebindError("V13 V12 forward marker is missing")
    forward["output_root_rebind_v14"] = {
        "schema": V14_SCHEMA,
        "path": fresh_root,
        "proof_output_only": True,
        "old_v13_output_root": old_output_root,
    }
    request["status"] = "READY_FOR_PARENT_GUARD"
    request["output_root_rebind_provenance"] = {
        "schema": V14_SCHEMA,
        "from_v13_profile_request": True,
        "old_request_case": "STAGE2_F2_ROOT197_V13_PROFILE_REBIND_20261009",
        "old_request_attempt": "f2-s1-root197-v13-profile-rebind-001",
        "old_output_root": old_output_root,
        "new_output_root": fresh_root,
        "payload_read": False,
    }
    request["sha256"] = V13.canonical_sha(request)
    target = _write_new(output, request)
    return {
        "schema": V14_SCHEMA,
        "status": "ROOT200_PROFILE_OUTPUT_ROOT_METADATA_READY_FOR_PARENT",
        "request": str(target),
        "request_file_sha256": V13.sha256_file(target),
        "request_canonical_sha256": request["sha256"],
        "sidecar": str(sidecar_output.resolve()),
        "fresh_output_root": fresh_root,
        "replaced_v13_output_root": old_output_root,
        "payload_read": False,
        "hdf5_or_bi4_read": False,
        "quality": dict(UNKNOWN),
        "qualification": dict(UNKNOWN),
    }


def validate_request(path: Path | str) -> dict[str, Any]:
    request_path, request = _json(path, "ROOT200 V14 request")
    if request.get("schema") != REQUEST_SCHEMA or request.get("sha256") != V13.canonical_sha(request):
        raise OutputRootRebindError("ROOT200 V14 request is not canonical V8")
    if "ROOT200" not in str(request.get("case_id", "")).upper() or "ROOT200" not in str(request.get("attempt_id", "")).upper():
        raise OutputRootRebindError("ROOT200 V14 identity is missing")
    profile = request.get("observer_profile_source_binding")
    expected = request.get("expected", {}).get("time", {}) if isinstance(request.get("expected"), Mapping) else {}
    if not isinstance(profile, Mapping) or profile.get("profile_sha256") != expected.get("observer_profile_sha256") or profile.get("profile_sha256") != V13.EXPECTED_PROFILE_SHA:
        raise OutputRootRebindError("ROOT200 profile SHA differs")
    relocation = request.get("relocation")
    namespace = request.get("fresh_proof_namespace")
    binding = relocation.get("proof_output_root_binding") if isinstance(relocation, Mapping) else None
    if not isinstance(relocation, Mapping) or not isinstance(namespace, Mapping) or not isinstance(binding, Mapping):
        raise OutputRootRebindError("ROOT200 output-root binding is missing")
    output_root = _root200(relocation.get("output_root"), "ROOT200 relocation.output_root")
    if output_root != _root200(namespace.get("root"), "ROOT200 namespace root") or output_root != _root200(binding.get("path"), "ROOT200 binding path"):
        raise OutputRootRebindError("ROOT200 proof output roots differ")
    if binding.get("schema") != V14_SCHEMA or binding.get("proof_output_only") is not True:
        raise OutputRootRebindError("ROOT200 proof output-root contract is not strict")
    if relocation.get("target_root") == output_root:
        raise OutputRootRebindError("ROOT200 output root replaced producer input root")
    V8._validate_request(request, verify_result_stat=False)
    V12.preflight(request_path)
    return {
        "schema": V14_SCHEMA,
        "status": "ROOT200_PROFILE_OUTPUT_ROOT_METADATA_VALIDATED_READY_FOR_PARENT",
        "request": {"path": str(request_path), "file_sha256": V13.sha256_file(request_path), "canonical_sha256": request["sha256"]},
        "fresh_output_root": output_root,
        "profile_sha256": V13.EXPECTED_PROFILE_SHA,
        "payload_read": False,
        "hdf5_or_bi4_read": False,
        "quality": dict(UNKNOWN),
        "qualification": dict(UNKNOWN),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    for name in ("root194-request", "producer-worker-request", "sidecar-output", "output"):
        build.add_argument(f"--{name}", type=Path, required=True)
    build.add_argument("--case-id", required=True)
    build.add_argument("--attempt-id", required=True)
    build.add_argument("--fresh-output-root", type=Path, required=True)
    check = sub.add_parser("validate")
    check.add_argument("--request", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            value = build_request(root194_request=args.root194_request.absolute(), producer_worker_request=args.producer_worker_request.absolute(),
                                  sidecar_output=args.sidecar_output.absolute(), output=args.output.absolute(), case_id=args.case_id,
                                  attempt_id=args.attempt_id, fresh_output_root=args.fresh_output_root.absolute())
        else:
            value = validate_request(args.request.absolute())
    except (OutputRootRebindError, OSError, TypeError, ValueError, json.JSONDecodeError, V13.ProfileRebindError, V8.ProofConsumerError, V12.V12ProofConsumerError) as error:
        print(f"ROOT200 V14 profile/output-root bridge: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
