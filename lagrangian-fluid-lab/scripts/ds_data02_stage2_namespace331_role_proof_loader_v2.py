#!/usr/bin/env python3
"""Load hash-bound role proof artifacts for the namespace331 V16 adapter.

The V1 adapter accepts a caller supplied ``semantic_role`` and a small
attestation object.  That is useful as a transport format, but it is not an
identity proof: a caller can manufacture both strings.  This V2 loader makes
the artifact the authority.  It reads only bounded JSON/XML proof artifacts,
derives the role and case identity from their contents, and reports UNKNOWN
when the artifact has no exact region/control/source evidence.

Large typed/V16 results are never opened by this module.  The request builder
records their expected SHA and stat for the parent guard; the parent must do
the content read after reservation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat as stat_module
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA = "ds02.stage2.namespace331.role-proof-loader.v2"
REQUEST_SCHEMA = "ds02.stage2.namespace331.v16-typed-event-request.v2"
ROLE_PROOF_SCHEMA = "ds02.stage2.namespace331.role-proof.v2"
MAX_ARTIFACT_BYTES = 10 * 1024 * 1024
KNOWN_STATUSES = {"VERIFIED", "PASS", "COMPLETED", "SOURCE_BOUND"}
REQUIRED_ROLES = ("source", "region_owner", "control")
_HEX = frozenset("0123456789abcdef")


class RoleProofLoaderError(ValueError):
    """Malformed, stale, or semantically unusable role evidence."""


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c.lower() not in _HEX for c in value):
        raise RoleProofLoaderError(f"{name} must be a SHA-256")
    return value.lower()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def canonical_sha(value: Mapping[str, Any]) -> str:
    """Hash a request without its self-referential request_sha256 field."""
    return hashlib.sha256(_canonical({k: v for k, v in value.items()
                                     if k != "request_sha256"}).encode()).hexdigest()


def _regular_file(path: Path, *, maximum: int | None = None) -> os.stat_result:
    if path.is_symlink() or not path.is_file():
        raise RoleProofLoaderError(f"artifact is not a regular non-symlink file: {path}")
    info = path.stat()
    if maximum is not None and info.st_size > maximum:
        raise RoleProofLoaderError(f"artifact exceeds bounded metadata limit: {path}")
    return info


def _file_sha_and_bytes(path: Path, *, maximum: int = MAX_ARTIFACT_BYTES) -> tuple[str, int]:
    info = _regular_file(path, maximum=maximum)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest(), int(info.st_size)


def _stat(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser()
    if target.is_symlink() or not target.exists():
        return {"exists": False}
    info = target.stat()
    kind = "file" if stat_module.S_ISREG(info.st_mode) else (
        "directory" if stat_module.S_ISDIR(info.st_mode) else "other")
    return {
        "exists": True,
        "kind": kind,
        "bytes": int(info.st_size) if kind == "file" else None,
        "mode_bits": int(info.st_mode & 0o7777),
        "mtime_ns": int(info.st_mtime_ns),
        "ctime_ns": int(info.st_ctime_ns),
        "st_dev": int(info.st_dev),
        "st_ino": int(info.st_ino),
    }


def _read_bounded(path: Path) -> tuple[bytes, str, int]:
    digest, size = _file_sha_and_bytes(path)
    # Hashing and reading are both intentionally bounded by the same limit.
    data = path.read_bytes()
    if len(data) != size:
        raise RoleProofLoaderError(f"artifact changed during bounded read: {path}")
    return data, digest, size


def _identity(value: Mapping[str, Any]) -> tuple[str | None, str | None]:
    nested = value.get("case_identity")
    if not isinstance(nested, Mapping):
        nested = value
    family = nested.get("family_id")
    physical = nested.get("physical_case_id", nested.get("case_id"))
    return (family if isinstance(family, str) and family else None,
            physical if isinstance(physical, str) and physical else None)


def _role_from_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "source": "source", "source_binding": "source",
        "source_proof": "source", "region_owner": "region_owner",
        "owner": "region_owner", "owner_metadata": "region_owner",
        "control": "control", "control_proof": "control",
    }
    return aliases.get(normalized)


def _status(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    upper = value.strip().upper()
    if upper in KNOWN_STATUSES:
        return upper
    if upper.startswith("VERIFIED_") or upper.startswith("COMPLETED_"):
        return "VERIFIED"
    return None


def _base_record(*, path: Path, artifact_sha256: str, artifact_bytes: int,
                 artifact_schema: str | None, derived_role: str | None,
                 family: str | None, physical: str | None) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "artifact_path": str(path),
        "artifact_sha256": artifact_sha256,
        "artifact_bytes": artifact_bytes,
        "artifact_schema": artifact_schema,
        "derived_semantic_role": derived_role,
        "case_identity": {"family_id": family, "physical_case_id": physical},
        "source_region": None,
        "target_region": None,
        "control_id": None,
        "source_sha256": None,
        "proof_status": None,
        "status": "UNKNOWN",
        "unknown_reasons": [],
        "evidence": {},
    }


def _json_evidence(doc: Mapping[str, Any], *, path: Path, artifact_sha256: str,
                   artifact_bytes: int) -> dict[str, Any]:
    schema = doc.get("schema") if isinstance(doc.get("schema"), str) else None
    family, physical = _identity(doc)
    derived: str | None = None
    source_region = None
    target_region = None
    control_id = None
    source_sha = None
    proof_status: str | None = None
    evidence: dict[str, Any] = {}

    # Explicit V2 role proof is the only generic schema accepted from a new
    # producer.  The role is read from the artifact, never from a caller field.
    if schema == ROLE_PROOF_SCHEMA and isinstance(doc.get("role_proof"), Mapping):
        proof = doc["role_proof"]
        derived = _role_from_text(proof.get("semantic_role", proof.get("role")))
        proof_status = _status(proof.get("proof_status", proof.get("status")))
        family, physical = _identity(proof) if _identity(proof) != (None, None) else (family, physical)
        source_region = proof.get("source_region", proof.get("region"))
        target_region = proof.get("target_region", proof.get("region"))
        control_id = proof.get("control_id", proof.get("control_family_id"))
        source_sha = proof.get("source_sha256", proof.get("source_content_sha256"))
        if source_sha is not None:
            source_sha = _sha(source_sha, "role_proof.source_sha256")
        evidence = {"producer": "explicit_role_proof_v2"}

    # ROOT200 is a real small actual verification artifact.  Its source_binding
    # has an exact CURRENT identity and exact case identity, so it can prove the
    # source role without opening the large typed result named inside it.
    elif schema == "ds02.stage2.root-actual-verification.v1":
        binding = doc.get("source_binding")
        if isinstance(binding, Mapping) and isinstance(doc.get("case_identity"), Mapping):
            derived = "source"
            proof_status = _status(doc.get("status"))
            source_sha = binding.get("current_catalog_sha256")
            if source_sha is not None:
                source_sha = _sha(source_sha, "source_binding.current_catalog_sha256")
            evidence = {
                "binding_status": binding.get("binding_status"),
                "current_catalog_sha256": source_sha,
                "fresh_result_file_sha256": doc.get("fresh_proof_file_sha256"),
            }
            source_region = doc.get("source_region")
            if source_region is None and isinstance(doc.get("report"), Mapping):
                source_region = doc["report"].get("source_region")
            target_region = doc.get("target_region")

    # The actual owner artifact has an exact case/control condition and an
    # explicit source condition.  It is source-bound metadata, but it does not
    # claim a physical owner region, so region_owner remains unavailable.
    elif schema in {"ds02.f2.stage1.actual812-typed157-provenance-owner.v1",
                    "ds02.root.lower-head-fallback-owner.v1",
                    "ds02.f5.stage1.next34.source-owner.v1"}:
        if isinstance(doc.get("control_family_id"), str):
            derived = "control"
            proof_status = "SOURCE_BOUND"
            control_id = doc.get("control_family_id")
            condition = doc.get("source_canonical_condition")
            if isinstance(condition, Mapping):
                source_region = condition.get("source_region")
                target_region = condition.get("target_region")
                evidence = {"control_condition_keys": sorted(str(k) for k in condition)}
            else:
                evidence = {"control_condition_keys": []}

    # V26 case artifacts identify the exact case and effective condition role,
    # but intentionally mark owner semantics unknown.  The loader surfaces that
    # fact rather than upgrading a group/owner SHA into a physical region proof.
    elif schema == "ds02.stage2.effective-condition-case.v26":
        derived = "region_owner"
        evidence = {"group_status": doc.get("effective_condition", {}).get("group_status")
                    if isinstance(doc.get("effective_condition"), Mapping) else None,
                    "owner_sha256_used_as_identity": False}
        effective = doc.get("effective_condition")
        if isinstance(effective, Mapping):
            axes = effective.get("axes")
            if isinstance(axes, Mapping):
                region = axes.get("region", axes.get("target_region"))
                if isinstance(region, str):
                    target_region = region

    record = _base_record(path=path, artifact_sha256=artifact_sha256,
                          artifact_bytes=artifact_bytes, artifact_schema=schema,
                          derived_role=derived, family=family, physical=physical)
    record.update({"source_region": source_region if isinstance(source_region, str) else None,
                   "target_region": target_region if isinstance(target_region, str) else None,
                   "control_id": control_id if isinstance(control_id, str) else None,
                   "source_sha256": source_sha,
                   "proof_status": proof_status,
                   "evidence": evidence})
    return record


def _xml_evidence(data: bytes, *, path: Path, artifact_sha256: str,
                  artifact_bytes: int) -> dict[str, Any]:
    # ElementTree does not fetch external entities, and explicit DOCTYPE/
    # ENTITY declarations are rejected before parsing for a fail-closed path.
    upper = data.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise RoleProofLoaderError("XML proof contains an external entity declaration")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise RoleProofLoaderError(f"invalid XML role proof: {error}") from error
    tags = {element.tag.rsplit("}", 1)[-1] for element in root.iter()}
    attrs = {str(k): str(v) for element in root.iter() for k, v in element.attrib.items()}
    # A plain GenCase XML has useful control/geometry values but no exact case
    # identity or signed role.  It is therefore parsed and returned UNKNOWN.
    control_id = attrs.get("control_id") or attrs.get("control_family_id")
    return {
        **_base_record(path=path, artifact_sha256=artifact_sha256,
                       artifact_bytes=artifact_bytes,
                       artifact_schema=f"xml:{root.tag.rsplit('}', 1)[-1]}",
                       derived_role=_role_from_text(attrs.get("semantic_role"))),
        "control_id": control_id,
        "evidence": {"xml_root": root.tag.rsplit("}", 1)[-1],
                      "tag_count": len(tags), "has_geometry": "geometry" in tags,
                      "has_control_constants": bool({"gravity", "rhop0", "gamma"} & tags)},
        "unknown_reasons": ["XML artifact lacks hash-bound case identity/role proof"],
    }


def load_role_proof_artifact(
    path: Path | str, *, expected_sha256: str, expected_role: str,
    family_id: str, physical_case_id: str, expected_source_region: str | None = None,
    expected_target_region: str | None = None, expected_control_id: str | None = None,
    expected_current_sha256: str | None = None,
) -> dict[str, Any]:
    """Load one small artifact and derive a role-bound evidence record.

    A semantic mismatch is represented as UNKNOWN (with reasons), allowing a
    source-only catalog to preserve uncertainty.  A stale hash, unsafe file,
    malformed JSON/XML, or invalid caller contract raises and cannot be used to
    build a request.
    """
    if expected_role not in REQUIRED_ROLES:
        raise RoleProofLoaderError(f"unsupported expected role: {expected_role}")
    expected_sha = _sha(expected_sha256, "expected_sha256")
    expected_current = (_sha(expected_current_sha256, "expected_current_sha256")
                       if expected_current_sha256 is not None else None)
    target = Path(path).expanduser()
    data, observed_sha, size = _read_bounded(target)
    if observed_sha != expected_sha:
        raise RoleProofLoaderError(f"artifact SHA differs from expected: {target}")
    if data.lstrip().startswith(b"<"):
        record = _xml_evidence(data, path=target, artifact_sha256=observed_sha,
                               artifact_bytes=size)
    else:
        try:
            value = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RoleProofLoaderError(f"artifact is neither bounded JSON nor XML: {target}") from error
        if not isinstance(value, Mapping):
            raise RoleProofLoaderError("role proof JSON must be an object")
        record = _json_evidence(value, path=target, artifact_sha256=observed_sha,
                                artifact_bytes=size)

    reasons = list(record.get("unknown_reasons", []))
    if record.get("derived_semantic_role") != expected_role:
        reasons.append("artifact_role_does_not_match_requested_role")
    actual_family = record.get("case_identity", {}).get("family_id")
    actual_case = record.get("case_identity", {}).get("physical_case_id")
    if actual_family != family_id:
        reasons.append("artifact_family_identity_mismatch")
    if actual_case != physical_case_id:
        reasons.append("artifact_physical_case_identity_mismatch")
    proof_status = record.get("proof_status")
    if proof_status not in KNOWN_STATUSES:
        reasons.append("artifact_has_no_supported_verified_status")
    if expected_current_sha256 is not None:
        bound_current = record.get("source_sha256")
        if bound_current != expected_current:
            reasons.append("artifact_current_source_sha_mismatch")
    if expected_source_region is not None and record.get("source_region") != expected_source_region:
        reasons.append("artifact_source_region_missing_or_mismatch")
    if expected_target_region is not None and record.get("target_region") != expected_target_region:
        reasons.append("artifact_target_region_missing_or_mismatch")
    if expected_control_id is not None and record.get("control_id") != expected_control_id:
        reasons.append("artifact_control_id_missing_or_mismatch")
    # A control proof needs a control id, a source proof needs a bound source
    # digest, and an owner proof needs an explicit region.  These are distinct
    # requirements so a valid control artifact cannot masquerade as an owner.
    if expected_role == "control" and not record.get("control_id"):
        reasons.append("control_artifact_has_no_control_id")
    if expected_role == "source" and not record.get("source_sha256"):
        reasons.append("source_artifact_has_no_current_source_sha")
    if expected_role == "region_owner" and not record.get("target_region"):
        reasons.append("owner_artifact_has_no_explicit_region")
    # Keep deterministic output while retaining the first occurrence of each
    # reason for audit readability.
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
    # Stat is intentionally the only operation performed on the deferred
    # typed result.  The parent worker owns the later bounded content read.
    return _stat(path)


def build_typed_event_request_v2(
    typed_result_path: Path | str, *, typed_result_sha256: str,
    current_binding: Mapping[str, Any], role_artifacts: Sequence[Mapping[str, Any]],
    family_id: str, physical_case_id: str, source_region: str, target_region: str,
    control_id: str | None, output_event_stream: Path | str,
    max_wall_seconds: int = 900,
) -> dict[str, Any]:
    """Build a source-only V2 request from actual small role artifacts."""
    typed_sha = _sha(typed_result_sha256, "typed_result_sha256")
    if not isinstance(current_binding, Mapping):
        raise RoleProofLoaderError("current_binding is required")
    current_sha = _sha(current_binding.get("sha256", current_binding.get("file_sha256")),
                       "current_binding.sha256")
    if not family_id or not physical_case_id or not source_region or not target_region:
        raise RoleProofLoaderError("family/case/source_region/target_region are required")
    if not isinstance(max_wall_seconds, int) or max_wall_seconds <= 0:
        raise RoleProofLoaderError("max_wall_seconds must be positive")
    if not isinstance(role_artifacts, Sequence) or isinstance(role_artifacts, (str, bytes)):
        raise RoleProofLoaderError("role_artifacts must be a sequence")
    by_role: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(role_artifacts):
        if not isinstance(item, Mapping):
            raise RoleProofLoaderError(f"role_artifacts[{index}] must be an object")
        role = item.get("role")
        if not isinstance(role, str) or role not in REQUIRED_ROLES or role in by_role:
            raise RoleProofLoaderError(f"invalid or duplicate role_artifacts[{index}]")
        evidence = load_role_proof_artifact(
            item.get("path"), expected_sha256=item.get("sha256"), expected_role=role,
            family_id=family_id, physical_case_id=physical_case_id,
            expected_source_region=source_region if role == "source" else None,
            expected_target_region=target_region if role == "region_owner" else None,
            expected_control_id=control_id if role == "control" else None,
            expected_current_sha256=current_sha if role == "source" else None,
        )
        by_role[role] = evidence
    missing = [role for role in REQUIRED_ROLES if role not in by_role]
    if missing:
        raise RoleProofLoaderError(f"missing role artifacts: {', '.join(missing)}")
    known_roles = [role for role in REQUIRED_ROLES if by_role[role]["status"] == "KNOWN"]
    request = {
        "schema": REQUEST_SCHEMA,
        "status": "READY_FOR_PARENT_GUARD_ROLE_PROOFS" if len(known_roles) == 3
        else "ROLE_PROOF_METADATA_PARTIAL_UNKNOWN",
        "loader_schema": SCHEMA,
        "case_identity": {"family_id": family_id, "physical_case_id": physical_case_id,
                           "identity_status": "CANONICAL"},
        "typed_result": {"path": str(Path(typed_result_path).expanduser()),
                         "sha256": typed_sha,
                         "stat": _typed_stat(typed_result_path),
                         "content_policy": "PARENT_GUARD_READ_AFTER_ATOMIC_RESERVATION"},
        "current_binding": {"path": current_binding.get("path"), "sha256": current_sha,
                             "content_policy": "SMALL_CURRENT_METADATA_AFTER_ATOMIC_RESERVATION"},
        "role_proof_artifacts": [by_role[role] for role in REQUIRED_ROLES],
        "role_status": {role: by_role[role]["status"] for role in REQUIRED_ROLES},
        "event_contract": {
            "source_region": source_region, "target_region": target_region,
            "control_id": control_id, "identity_key": "(Zone,Idp)",
            "unknown_role_policy": "all labels and metrics UNKNOWN when any required role is UNKNOWN",
        },
        "execution": {
            "entrypoint": "ds_data02_stage2_namespace331_v16_typed_event_adapter_v1.py",
            "output_event_stream": str(Path(output_event_stream).expanduser()),
            "max_wall_seconds": max_wall_seconds,
            "source_read_phase": "after_atomic_parent_reservation",
            "parent_supervision_required": True, "model_invoked": False,
            "h5_bi4_raw_opened": False,
        },
        "qualification_boundary": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "large_content_policy": {
            "typed_result_sha_only_at_build": True,
            "typed_result_content_read_by_builder": False,
            "role_artifacts_read_bounded": True,
            "old_path_fallback": False,
        },
    }
    request["request_sha256"] = canonical_sha(request)
    return request


def _write_json(path: Path | str, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser()
    if target.exists() or target.is_symlink():
        raise RoleProofLoaderError(f"refusing to overwrite: {target}")
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
            value = load_role_proof_artifact(
                args.artifact, expected_sha256=args.sha256, expected_role=args.role,
                family_id=args.family_id, physical_case_id=args.physical_case_id,
                expected_source_region=args.source_region,
                expected_target_region=args.target_region,
                expected_control_id=args.control_id,
                expected_current_sha256=args.current_sha256)
            print(json.dumps(value, indent=2, sort_keys=True))
            return 0
        artifacts = [{"role": role, "path": path, "sha256": sha}
                     for role, path, sha in args.role_artifact]
        request = build_typed_event_request_v2(
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
    except (OSError, RoleProofLoaderError) as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
