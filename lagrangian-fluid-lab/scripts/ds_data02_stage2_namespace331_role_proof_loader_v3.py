#!/usr/bin/env python3
"""V3 role-proof loader with one-pass content and stat binding.

V2 hashes an artifact and then reads it a second time.  This forward loader
reads each bounded artifact once, computes the digest over those exact bytes,
and compares pre/post ``st_dev``, ``st_ino``, size, mtime and ctime.  It also
rejects symlink replacement.  The generic role-proof schema requires a real
producer request and source-contract closure; caller supplied role/status
strings alone remain UNKNOWN.

Deferred typed/V16 results are still stat-only.  No H5, BI4, raw array, or
trajectory payload is opened by this module.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import stat as stat_module
from pathlib import Path
from typing import Any, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location(
    "namespace331_role_proof_loader_v2_for_v3",
    SCRIPT_DIR / "ds_data02_stage2_namespace331_role_proof_loader_v2.py",
)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover
    raise ImportError("namespace331 V2 role-proof loader is unavailable")
_V2 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_V2)


SCHEMA = "ds02.stage2.namespace331.role-proof-loader.v3"
REQUEST_SCHEMA = "ds02.stage2.namespace331.v16-typed-event-request.v3"
ROLE_PROOF_SCHEMA = _V2.ROLE_PROOF_SCHEMA
MAX_ARTIFACT_BYTES = _V2.MAX_ARTIFACT_BYTES
KNOWN_STATUSES = _V2.KNOWN_STATUSES
REQUIRED_ROLES = _V2.REQUIRED_ROLES
FIXTURE_PRODUCER_REQUEST_SCHEMA = "ds02.stage2.namespace331.fixture.producer-request.v1"
FIXTURE_SOURCE_CONTRACT_SCHEMA = "ds02.stage2.namespace331.fixture.source-contract.v1"


class RoleProofLoaderV3Error(ValueError):
    """Malformed, stale, or unclosed role evidence."""


def _sha(value: Any, name: str) -> str:
    try:
        return _V2._sha(value, name)
    except Exception as error:
        raise RoleProofLoaderV3Error(str(error)) from error


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def canonical_sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical({k: v for k, v in value.items()
                                     if k != "request_sha256"}).encode()).hexdigest()


def _sig(info: os.stat_result) -> dict[str, int]:
    return {
        "st_dev": int(info.st_dev),
        "st_ino": int(info.st_ino),
        "size": int(info.st_size),
        "mtime_ns": int(info.st_mtime_ns),
        "ctime_ns": int(info.st_ctime_ns),
    }


def _lstat_regular(path: Path, *, maximum: int = MAX_ARTIFACT_BYTES) -> os.stat_result:
    try:
        info = os.lstat(path)
    except OSError as error:
        raise RoleProofLoaderV3Error(f"cannot stat role artifact: {path}") from error
    if stat_module.S_ISLNK(info.st_mode):
        raise RoleProofLoaderV3Error(f"role artifact is a symlink: {path}")
    if not stat_module.S_ISREG(info.st_mode):
        raise RoleProofLoaderV3Error(f"role artifact is not a regular file: {path}")
    if info.st_size > maximum:
        raise RoleProofLoaderV3Error(f"role artifact exceeds bounded metadata limit: {path}")
    return info


def _read_once(path: Path, *, maximum: int = MAX_ARTIFACT_BYTES) -> tuple[bytes, str, dict[str, int], dict[str, int]]:
    """Read and hash exactly one bounded inode, with no symlink following."""
    target = path.expanduser()
    before_path = _lstat_regular(target, maximum=maximum)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(target, flags)
    except OSError as error:
        raise RoleProofLoaderV3Error(f"cannot open role artifact without following symlink: {target}") from error
    try:
        before_fd = os.fstat(fd)
        if _sig(before_fd) != _sig(before_path):
            raise RoleProofLoaderV3Error(f"role artifact changed before read: {target}")
        digest = hashlib.sha256()
        pieces: list[bytes] = []
        total = 0
        with os.fdopen(fd, "rb", closefd=True) as stream:
            fd = -1
            while True:
                block = stream.read(min(1024 * 1024, maximum - total + 1))
                if not block:
                    break
                total += len(block)
                if total > maximum:
                    raise RoleProofLoaderV3Error(f"role artifact grew beyond bound: {target}")
                digest.update(block)
                pieces.append(block)
            # fstat must be captured while the descriptor is still open.
            after_fd = os.fstat(stream.fileno())
        after_path = _lstat_regular(target, maximum=maximum)
    except Exception:
        if fd >= 0:
            os.close(fd)
        raise
    before = _sig(before_fd)
    after = _sig(after_fd)
    path_after = _sig(after_path)
    if before != after or after != path_after:
        raise RoleProofLoaderV3Error(f"role artifact changed during bounded read: {target}")
    return b"".join(pieces), digest.hexdigest(), before, after


def _decode(data: bytes, *, path: Path, digest: str, size: int) -> dict[str, Any]:
    if data.lstrip().startswith(b"<"):
        return _V2._xml_evidence(data, path=path, artifact_sha256=digest, artifact_bytes=size)
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RoleProofLoaderV3Error(f"artifact is neither bounded JSON nor XML: {path}") from error
    if not isinstance(value, Mapping):
        raise RoleProofLoaderV3Error("role proof JSON must be an object")
    return _V2._json_evidence(value, path=path, artifact_sha256=digest, artifact_bytes=size)


def _bound_closure(proof: Mapping[str, Any], *, family_id: str,
                   physical_case_id: str) -> tuple[bool, dict[str, Any], str | None]:
    """Validate an explicit producer request/source-contract fixture closure.

    No production producer schema is silently guessed here.  The only generic
    closure accepted by this forward loader is an explicitly named fixture
    schema, and its result is marked ``FIXTURE_ONLY``.  A future production
    producer gets its own schema adapter instead of inheriting caller strings.
    """
    closure = proof.get("producer_source_closure")
    if not isinstance(closure, Mapping):
        return False, {}, "generic_role_proof_missing_producer_source_closure"
    producer_id = closure.get("producer_id")
    if not isinstance(producer_id, str) or not producer_id:
        return False, {}, "producer_source_closure_missing_producer_id"
    details: dict[str, Any] = {"producer_id": producer_id, "artifacts": {},
                               "credit_boundary": "MANUFACTURED_FIXTURE_ONLY"}
    source_document: Mapping[str, Any] | None = None
    source_binding: Mapping[str, Any] | None = None
    request_document: Mapping[str, Any] | None = None
    for role in ("producer_request", "source_contract"):
        binding = closure.get(role)
        if not isinstance(binding, Mapping) or not isinstance(binding.get("path"), str):
            return False, details, f"producer_source_closure_missing_{role}"
        try:
            expected = _sha(binding.get("sha256"), f"producer_source_closure.{role}.sha256")
            path = Path(binding["path"]).expanduser()
            data, observed, before, after = _read_once(path)
        except RoleProofLoaderV3Error as error:
            return False, details, f"producer_source_closure_{role}_unreadable:{error}"
        if observed != expected:
            return False, details, f"producer_source_closure_{role}_sha_mismatch"
        try:
            document = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False, details, f"producer_source_closure_{role}_not_json"
        if not isinstance(document, Mapping):
            return False, details, f"producer_source_closure_{role}_not_object"
        family, physical = _V2._identity(document)
        if family is None or physical is None:
            return False, details, f"producer_source_closure_{role}_missing_exact_identity"
        if family != family_id:
            return False, details, f"producer_source_closure_{role}_family_mismatch"
        if physical != physical_case_id:
            return False, details, f"producer_source_closure_{role}_case_mismatch"
        status = _V2._status(document.get("status", document.get("proof_status")))
        if status not in KNOWN_STATUSES:
            return False, details, f"producer_source_closure_{role}_status_unsupported"
        if role == "producer_request":
            if document.get("schema") != FIXTURE_PRODUCER_REQUEST_SCHEMA:
                return False, details, "producer_source_closure_request_schema_unsupported"
            if document.get("producer_id") != producer_id:
                return False, details, "producer_source_closure_request_producer_mismatch"
            request_document = document
        else:
            if document.get("schema") != FIXTURE_SOURCE_CONTRACT_SCHEMA:
                return False, details, "producer_source_closure_source_schema_unsupported"
            source_document = document
            source_binding = binding
        details["artifacts"][role] = {
            "path": str(path), "sha256": observed, "bytes": len(data),
            "stat_pre": before, "stat_post": after, "status": status,
        }
    if request_document is None or source_document is None or source_binding is None:
        return False, details, "producer_source_closure_incomplete"
    # The request's input digest must point to the exact source-contract file
    # and SHA that were read above.  A free-standing source SHA is not enough.
    input_sha = request_document.get("input_sha256")
    if not isinstance(input_sha, Mapping):
        return False, details, "producer_source_closure_request_missing_input_sha256"
    source_input = input_sha.get("source_contract")
    if not isinstance(source_input, Mapping):
        return False, details, "producer_source_closure_request_missing_source_contract_input"
    if source_input.get("path") != source_binding.get("path") or source_input.get("sha256") != source_binding.get("sha256"):
        return False, details, "producer_source_closure_request_source_contract_binding_mismatch"
    semantic_role = _V2._role_from_text(proof.get("semantic_role", proof.get("role")))
    source_role = _V2._role_from_text(source_document.get("semantic_role", source_document.get("role")))
    if semantic_role is None or source_role != semantic_role:
        return False, details, "producer_source_closure_source_role_mismatch"
    for key in ("source_region", "target_region", "control_id"):
        if key in proof and proof.get(key) is not None and source_document.get(key) != proof.get(key):
            return False, details, f"producer_source_closure_{key}_mismatch"
    expected_source_sha = proof.get("source_sha256", proof.get("source_content_sha256"))
    source_content_sha = source_document.get("source_sha256", source_document.get("content_sha256"))
    if expected_source_sha is not None and source_content_sha != expected_source_sha:
        return False, details, "producer_source_closure_source_content_sha_mismatch"
    return True, details, None


def load_role_proof_artifact(
    path: Path | str, *, expected_sha256: str, expected_role: str,
    family_id: str, physical_case_id: str, expected_source_region: str | None = None,
    expected_target_region: str | None = None, expected_control_id: str | None = None,
    expected_current_sha256: str | None = None,
) -> dict[str, Any]:
    """Load one role artifact using one bounded read and exact stat binding."""
    if expected_role not in REQUIRED_ROLES:
        raise RoleProofLoaderV3Error(f"unsupported expected role: {expected_role}")
    expected_sha = _sha(expected_sha256, "expected_sha256")
    expected_current = (_sha(expected_current_sha256, "expected_current_sha256")
                       if expected_current_sha256 is not None else None)
    target = Path(path).expanduser()
    data, observed_sha, before, after = _read_once(target)
    if observed_sha != expected_sha:
        raise RoleProofLoaderV3Error(f"artifact SHA differs from expected: {target}")
    record = _decode(data, path=target, digest=observed_sha, size=len(data))
    record = dict(record)
    record["schema"] = SCHEMA
    record["artifact_stat_pre"] = before
    record["artifact_stat_post"] = after
    reasons = list(record.get("unknown_reasons", []))

    # Generic role proof status is not trusted unless the artifact carries
    # independently hash-bound producer request and source-contract files.
    role_proof = None
    try:
        value = json.loads(data.decode("utf-8")) if not data.lstrip().startswith(b"<") else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        value = None
    if isinstance(value, Mapping) and value.get("schema") == ROLE_PROOF_SCHEMA:
        role_proof = value.get("role_proof") if isinstance(value.get("role_proof"), Mapping) else None
    if role_proof is not None:
        valid, closure, reason = _bound_closure(role_proof, family_id=family_id,
                                                physical_case_id=physical_case_id)
        record["producer_source_closure"] = closure
        if not valid and reason:
            reasons.append(reason)

    actual_family = record.get("case_identity", {}).get("family_id")
    actual_case = record.get("case_identity", {}).get("physical_case_id")
    if record.get("derived_semantic_role") != expected_role:
        reasons.append("artifact_role_does_not_match_requested_role")
    if actual_family != family_id:
        reasons.append("artifact_family_identity_mismatch")
    if actual_case != physical_case_id:
        reasons.append("artifact_physical_case_identity_mismatch")
    proof_status = record.get("proof_status")
    if proof_status not in KNOWN_STATUSES:
        reasons.append("artifact_has_no_supported_verified_status")
    if expected_current_sha256 is not None and record.get("source_sha256") != expected_current:
        reasons.append("artifact_current_source_sha_mismatch")
    if expected_source_region is not None and record.get("source_region") != expected_source_region:
        reasons.append("artifact_source_region_missing_or_mismatch")
    if expected_target_region is not None and record.get("target_region") != expected_target_region:
        reasons.append("artifact_target_region_missing_or_mismatch")
    if expected_control_id is not None and record.get("control_id") != expected_control_id:
        reasons.append("artifact_control_id_missing_or_mismatch")
    if expected_role == "control" and not record.get("control_id"):
        reasons.append("control_artifact_has_no_control_id")
    if expected_role == "source" and not record.get("source_sha256"):
        reasons.append("source_artifact_has_no_current_source_sha")
    if expected_role == "region_owner" and not record.get("target_region"):
        reasons.append("owner_artifact_has_no_explicit_region")
    record["unknown_reasons"] = list(dict.fromkeys(reasons))
    record["status"] = "KNOWN" if not record["unknown_reasons"] else "UNKNOWN"
    record["requested_role"] = expected_role
    record["expected_case_identity"] = {"family_id": family_id,
                                         "physical_case_id": physical_case_id}
    if expected_source_region is not None:
        record["expected_source_region"] = expected_source_region
    if expected_target_region is not None:
        record["expected_target_region"] = expected_target_region
    if expected_control_id is not None:
        record["expected_control_id"] = expected_control_id
    return record


def _typed_stat(path: Path | str) -> dict[str, Any]:
    return _V2._typed_stat(path)


def build_typed_event_request_v3(
    typed_result_path: Path | str, *, typed_result_sha256: str,
    current_binding: Mapping[str, Any], role_artifacts: Sequence[Mapping[str, Any]],
    family_id: str, physical_case_id: str, source_region: str, target_region: str,
    control_id: str | None, output_event_stream: Path | str, max_wall_seconds: int = 900,
) -> dict[str, Any]:
    """Build a V3 request while loading role artifacts through V3."""
    typed_sha = _sha(typed_result_sha256, "typed_result_sha256")
    if not isinstance(current_binding, Mapping):
        raise RoleProofLoaderV3Error("current_binding is required")
    current_sha = _sha(current_binding.get("sha256", current_binding.get("file_sha256")),
                       "current_binding.sha256")
    if not family_id or not physical_case_id or not source_region or not target_region:
        raise RoleProofLoaderV3Error("family/case/source_region/target_region are required")
    if not isinstance(max_wall_seconds, int) or max_wall_seconds <= 0:
        raise RoleProofLoaderV3Error("max_wall_seconds must be positive")
    if not isinstance(role_artifacts, Sequence) or isinstance(role_artifacts, (str, bytes)):
        raise RoleProofLoaderV3Error("role_artifacts must be a sequence")
    by_role: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(role_artifacts):
        if not isinstance(item, Mapping):
            raise RoleProofLoaderV3Error(f"role_artifacts[{index}] must be an object")
        role = item.get("role")
        if not isinstance(role, str) or role not in REQUIRED_ROLES or role in by_role:
            raise RoleProofLoaderV3Error(f"invalid or duplicate role_artifacts[{index}]")
        by_role[role] = load_role_proof_artifact(
            item.get("path"), expected_sha256=item.get("sha256"), expected_role=role,
            family_id=family_id, physical_case_id=physical_case_id,
            expected_source_region=source_region if role == "source" else None,
            expected_target_region=target_region if role == "region_owner" else None,
            expected_control_id=control_id if role == "control" else None,
            expected_current_sha256=current_sha if role == "source" else None)
    missing = [role for role in REQUIRED_ROLES if role not in by_role]
    if missing:
        raise RoleProofLoaderV3Error(f"missing role artifacts: {', '.join(missing)}")
    known_roles = [role for role in REQUIRED_ROLES if by_role[role]["status"] == "KNOWN"]
    request = {
        "schema": REQUEST_SCHEMA,
        "status": "READY_FOR_PARENT_GUARD_ROLE_PROOFS" if len(known_roles) == 3
        else "ROLE_PROOF_METADATA_PARTIAL_UNKNOWN",
        "loader_schema": SCHEMA,
        "case_identity": {"family_id": family_id, "physical_case_id": physical_case_id,
                           "identity_status": "CANONICAL"},
        "typed_result": {"path": str(Path(typed_result_path).expanduser()), "sha256": typed_sha,
                         "stat": _typed_stat(typed_result_path),
                         "content_policy": "PARENT_GUARD_READ_AFTER_ATOMIC_RESERVATION"},
        "current_binding": {"path": current_binding.get("path"), "sha256": current_sha,
                             "content_policy": "SMALL_CURRENT_METADATA_AFTER_ATOMIC_RESERVATION"},
        "role_proof_artifacts": [by_role[role] for role in REQUIRED_ROLES],
        "role_status": {role: by_role[role]["status"] for role in REQUIRED_ROLES},
        "event_contract": {"source_region": source_region, "target_region": target_region,
                           "control_id": control_id, "identity_key": "(Zone,Idp)",
                           "unknown_role_policy": "all labels and metrics UNKNOWN when any required role is UNKNOWN"},
        "execution": {"entrypoint": "ds_data02_stage2_namespace331_v16_typed_event_adapter_v2.py",
                      "output_event_stream": str(Path(output_event_stream).expanduser()),
                      "max_wall_seconds": max_wall_seconds,
                      "source_read_phase": "after_atomic_parent_reservation",
                      "parent_supervision_required": True, "model_invoked": False,
                      "h5_bi4_raw_opened": False},
        "qualification_boundary": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "large_content_policy": {"typed_result_sha_only_at_build": True,
                                  "typed_result_content_read_by_builder": False,
                                  "role_artifacts_read_bounded": True, "old_path_fallback": False},
    }
    request["request_sha256"] = canonical_sha(request)
    return request


def _write_json(path: Path | str, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser()
    if target.exists() or target.is_symlink():
        raise RoleProofLoaderV3Error(f"refusing to overwrite: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                      encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("--artifact", type=Path, required=True)
    inspect.add_argument("--sha256", required=True)
    inspect.add_argument("--role", choices=REQUIRED_ROLES, required=True)
    inspect.add_argument("--family-id", required=True)
    inspect.add_argument("--physical-case-id", required=True)
    inspect.add_argument("--source-region")
    inspect.add_argument("--target-region")
    inspect.add_argument("--control-id")
    inspect.add_argument("--current-sha256")
    build = sub.add_parser("build-request")
    build.add_argument("--typed-result", type=Path, required=True)
    build.add_argument("--typed-sha256", required=True)
    build.add_argument("--current-path", required=True)
    build.add_argument("--current-sha256", required=True)
    build.add_argument("--role-artifact", action="append", nargs=3,
                       metavar=("ROLE", "PATH", "SHA256"), default=[])
    build.add_argument("--family-id", required=True)
    build.add_argument("--physical-case-id", required=True)
    build.add_argument("--source-region", required=True)
    build.add_argument("--target-region", required=True)
    build.add_argument("--control-id")
    build.add_argument("--output-event-stream", required=True)
    build.add_argument("--request", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            result = load_role_proof_artifact(
                args.artifact, expected_sha256=args.sha256, expected_role=args.role,
                family_id=args.family_id, physical_case_id=args.physical_case_id,
                expected_source_region=args.source_region,
                expected_target_region=args.target_region,
                expected_control_id=args.control_id,
                expected_current_sha256=args.current_sha256)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        artifacts = [{"role": role, "path": path, "sha256": sha}
                     for role, path, sha in args.role_artifact]
        request = build_typed_event_request_v3(
            args.typed_result, typed_result_sha256=args.typed_sha256,
            current_binding={"path": args.current_path, "sha256": args.current_sha256},
            role_artifacts=artifacts, family_id=args.family_id,
            physical_case_id=args.physical_case_id, source_region=args.source_region,
            target_region=args.target_region, control_id=args.control_id,
            output_event_stream=args.output_event_stream)
        _write_json(args.request, request)
        print(json.dumps({"request": str(args.request), "status": request["status"],
                          "request_sha256": request["request_sha256"],
                          "role_status": request["role_status"]}, sort_keys=True))
        return 0
    except (OSError, RoleProofLoaderV3Error) as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
