#!/usr/bin/env python3
"""Build and validate a bounded, diagnostic-only A8 full-temporal receipt.

This bridge is intentionally independent from the existing A8 bridges and
readers.  It consumes exactly three JSON objects:

* the recorded ``core.verification.v1`` full-temporal receipt;
* ``bundle.json`` from the A8 reader package; and
* that package's ``dataset.json``.

The package metadata is used only for identity binding.  Paths named by the
metadata (including HDF5, NPZ, checkpoint, code, and worker assets) are never
opened, hashed, executed, or used to infer a scientific qualification.  A
blocked bridge is still diagnostic-only and has zero credit.  The CLI returns
non-zero whenever the input or the generated bridge is blocked.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

if __name__ == "__main__":
    sys.dont_write_bytecode = True


LAB_ROOT = Path(__file__).resolve().parents[1]
VERIFICATION_FILENAME = "A8-FULL-REPRODUCE-V2-FULL-TEMPORAL-VERIFY-2026-09-28.json"
DEFAULT_PACKAGE_RELATIVE = "campaigns/core-v1/reproduction/a8-full-reproduce-v2"
DEFAULT_BRIDGE_FILENAME = "A8-FULL-TEMPORAL-VERIFY-RECEIPT-BRIDGE-V1-2026-09-28.json"
DEFAULT_ZH_FILENAME = "A8-FULL-TEMPORAL-VERIFY-RECEIPT-BRIDGE-V1-2026-09-28.zh-CN.md"

BRIDGE_SCHEMA = "core.a8.full_temporal_verify_receipt_bridge.v1"
VERIFICATION_SCHEMA = "core.verification.v1"
BUNDLE_SCHEMA = "core.reader_bundle.v2"
DATASET_SCHEMA = "core.dataset.v2"

EXPECTED_CASE_COUNT = 32
EXPECTED_TRANSITIONS = 835
MAX_VERIFICATION_JSON_BYTES = 16 * 1024 * 1024
MAX_PACKAGE_JSON_BYTES = 256 * 1024
MAX_BRIDGE_JSON_BYTES = 2 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CASE_ID_RE = re.compile(r"^[A-Za-z0-9_.+-]+$")

ZERO_CREDIT_CLAIMS = {
    "formal_training": False,
    "T1_numerical": False,
    "T2_macro": False,
    "T2_path": False,
    "qualification": False,
    "credit": 0,
}
ZERO_MUTATIONS = {
    "registry": 0,
    "ledger": 0,
    "denominator": 0,
    "gate": 0,
    "completion": 0,
    "plan": 0,
}


class BridgeContractError(ValueError):
    """Raised when a bounded bridge input cannot be safely bound."""


def _strict_bool(value: object, *, label: str) -> bool:
    if type(value) is not bool:
        raise BridgeContractError(f"{label} must be a boolean")
    return bool(value)


def _strict_int(value: object, *, label: str, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise BridgeContractError(f"{label} must be an integer")
    if minimum is not None and value < minimum:
        raise BridgeContractError(f"{label} must be >= {minimum}")
    return int(value)


def _sha256(value: object, *, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise BridgeContractError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _absolute(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return Path(os.path.abspath(candidate))


def _assert_no_symlink_components(path: Path, *, require_final: bool) -> None:
    """Reject symlinks in the whole path without resolving the leaf first."""
    path = _absolute(path)
    current = Path(path.root)
    parts = path.parts[1:] if path.is_absolute() else path.parts
    for index, part in enumerate(parts):
        current = current / part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            if require_final or index != len(parts) - 1:
                raise BridgeContractError(f"path component is missing: {current}") from None
            return
        except OSError as error:
            raise BridgeContractError(f"cannot inspect path component {current}: {error}") from error
        if stat.S_ISLNK(info.st_mode):
            raise BridgeContractError(f"symlink path component is forbidden: {current}")


def _regular_directory(path: str | Path, *, label: str) -> Path:
    candidate = _absolute(path)
    _assert_no_symlink_components(candidate, require_final=True)
    try:
        info = os.lstat(candidate)
    except OSError as error:
        raise BridgeContractError(f"{label} cannot be inspected: {error}") from error
    if not stat.S_ISDIR(info.st_mode):
        raise BridgeContractError(f"{label} must be a regular directory")
    return candidate


def _relative(path: Path, root: Path, *, label: str, allow_root: bool = False) -> str:
    path = _absolute(path)
    root = _absolute(root)
    try:
        value = path.relative_to(root)
    except ValueError as error:
        raise BridgeContractError(f"{label} must be inside the selected root") from error
    if value == Path("."):
        if allow_root:
            return "."
        raise BridgeContractError(f"{label} cannot be the selected root")
    if value.is_absolute() or ".." in value.parts:
        raise BridgeContractError(f"{label} is not a portable relative path")
    rendered = value.as_posix()
    if not rendered or rendered.startswith("/") or rendered == ".":
        raise BridgeContractError(f"{label} is not a portable relative path")
    return rendered


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_constant(token: str) -> None:
    raise ValueError(f"non-finite JSON constant is forbidden: {token}")


def _parse_json(raw: bytes, *, label: str, max_bytes: int) -> dict[str, object]:
    if type(raw) is not bytes or len(raw) > max_bytes:
        raise BridgeContractError(f"{label} exceeds its bounded byte limit")
    try:
        text = raw.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            strict=True,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
            parse_float=lambda token: _finite_float(token, label=label),
            parse_int=lambda token: _bounded_int(token, label=label),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, OverflowError, RecursionError, ValueError) as error:
        if isinstance(error, BridgeContractError):
            raise
        raise BridgeContractError(f"{label} is not strict JSON: {error}") from error
    if type(value) is not dict:
        raise BridgeContractError(f"{label} top level must be an object")
    return value


def _finite_float(token: str, *, label: str) -> float:
    value = float(token)
    if not (value == value and value not in (float("inf"), float("-inf"))):
        raise ValueError(f"{label} contains a non-finite number")
    return value


def _bounded_int(token: str, *, label: str) -> int:
    digits = token[1:] if token.startswith("-") else token
    if len(digits) > 128:
        raise ValueError(f"{label} contains an overlong integer")
    return int(token)


def _read_raw(path: str | Path, *, label: str, max_bytes: int) -> tuple[bytes, Path]:
    candidate = _absolute(path)
    if candidate.suffix != ".json":
        raise BridgeContractError(f"{label} must have a .json suffix")
    _assert_no_symlink_components(candidate, require_final=True)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise BridgeContractError(f"{label} cannot enforce no-follow open on this platform")
    flags = os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(candidate, flags)
    except OSError as error:
        raise BridgeContractError(f"{label} cannot be opened: {error}") from error
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise BridgeContractError(f"{label} must be a regular file")
        if before.st_size > max_bytes:
            raise BridgeContractError(f"{label} exceeds {max_bytes} bytes")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(fd)
    except BridgeContractError:
        raise
    except OSError as error:
        raise BridgeContractError(f"{label} cannot be read: {error}") from error
    finally:
        os.close(fd)
    before_id = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    after_id = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    if len(raw) > max_bytes:
        raise BridgeContractError(f"{label} exceeds {max_bytes} bytes")
    if len(raw) != before.st_size or before_id != after_id:
        raise BridgeContractError(f"{label} changed during bounded read")
    return raw, candidate


def _read_json_ref(
    path: str | Path,
    *,
    root: Path,
    label: str,
    max_bytes: int,
    expected_name: str | None = None,
    expected_parent: str | None = None,
) -> tuple[dict[str, object], dict[str, object], Path]:
    raw, safe_path = _read_raw(path, label=label, max_bytes=max_bytes)
    if expected_name is not None and safe_path.name != expected_name:
        raise BridgeContractError(f"{label} must be named {expected_name}")
    if expected_parent is not None and safe_path.parent.name != expected_parent:
        raise BridgeContractError(f"{label} must be under a {expected_parent} directory")
    reference = {
        "path": _relative(safe_path, root, label=label),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "schema": None,
        "opened": True,
        "read_policy": "strict_bounded_json_no_follow",
    }
    payload = _parse_json(raw, label=label, max_bytes=max_bytes)
    reference["schema"] = payload.get("schema")
    return reference, payload, safe_path


def _valid_case_id(value: object, *, label: str) -> str:
    if not isinstance(value, str) or CASE_ID_RE.fullmatch(value) is None:
        raise BridgeContractError(f"{label} must be a portable case identifier")
    return value


def _valid_relative_metadata_path(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise BridgeContractError(f"{label} must be a relative path")
    path = Path(value)
    if path.as_posix() != value or ".." in path.parts:
        raise BridgeContractError(f"{label} must be a normalized relative path")
    return value


def _validate_package(
    *,
    package_root: Path,
    bundle: Mapping[str, object],
    dataset: Mapping[str, object],
    bundle_ref: Mapping[str, object],
    dataset_ref: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object], list[str]]:
    blockers: list[str] = []
    if bundle.get("schema") != BUNDLE_SCHEMA:
        blockers.append(f"bundle_schema_drift:{bundle.get('schema')!r}")
    if dataset.get("schema") != DATASET_SCHEMA:
        blockers.append(f"dataset_schema_drift:{dataset.get('schema')!r}")
    for key, expected in (("case_count", EXPECTED_CASE_COUNT), ("checkpoint_count", 0)):
        try:
            value = _strict_int(bundle.get(key), label=f"bundle.{key}")
            if value != expected:
                blockers.append(f"bundle_{key}_drift:{value}!={expected}")
        except BridgeContractError as error:
            blockers.append(str(error))
    for key, expected in (("full_core_release", False), ("model_reproduction_supported", False)):
        try:
            if _strict_bool(bundle.get(key), label=f"bundle.{key}") is not expected:
                blockers.append(f"bundle_{key}_must_be_{expected}")
        except BridgeContractError as error:
            blockers.append(str(error))
    try:
        if _strict_bool(dataset.get("formal_release"), label="dataset.formal_release"):
            blockers.append("dataset_formal_release_must_be_false")
    except BridgeContractError as error:
        blockers.append(str(error))

    bundle_files = bundle.get("files")
    file_entries: dict[str, Mapping[str, object]] = {}
    if not isinstance(bundle_files, list):
        blockers.append("bundle_files_missing_or_not_a_list")
    else:
        for index, entry in enumerate(bundle_files):
            if not isinstance(entry, Mapping):
                blockers.append(f"bundle_file_{index}_not_an_object")
                continue
            try:
                file_path = _valid_relative_metadata_path(entry.get("path"), label=f"bundle.files[{index}].path")
                if file_path in file_entries:
                    blockers.append(f"bundle_file_duplicate:{file_path}")
                file_entries[file_path] = entry
                _strict_int(entry.get("bytes"), label=f"bundle.files[{index}].bytes", minimum=0)
                _sha256(entry.get("sha256"), label=f"bundle.files[{index}].sha256")
            except BridgeContractError as error:
                blockers.append(str(error))
    if "dataset.json" not in file_entries:
        blockers.append("bundle_files_missing_dataset_json")
    else:
        entry = file_entries["dataset.json"]
        if entry.get("bytes") != dataset_ref.get("bytes"):
            blockers.append("bundle_dataset_bytes_drift")
        if entry.get("sha256") != dataset_ref.get("sha256"):
            blockers.append("bundle_dataset_sha256_drift")

    try:
        dataset_case_count = _strict_int(dataset.get("case_count"), label="dataset.case_count")
        if dataset_case_count != EXPECTED_CASE_COUNT:
            blockers.append(f"dataset_case_count_drift:{dataset_case_count}!={EXPECTED_CASE_COUNT}")
    except BridgeContractError as error:
        dataset_case_count = None
        blockers.append(str(error))
    dataset_cases = dataset.get("cases")
    dataset_by_id: dict[str, Mapping[str, object]] = {}
    if not isinstance(dataset_cases, list):
        blockers.append("dataset_cases_missing_or_not_a_list")
    else:
        if len(dataset_cases) != EXPECTED_CASE_COUNT:
            blockers.append(f"dataset_cases_length_drift:{len(dataset_cases)}!={EXPECTED_CASE_COUNT}")
        for index, row in enumerate(dataset_cases):
            if not isinstance(row, Mapping):
                blockers.append(f"dataset_case_{index}_not_an_object")
                continue
            try:
                case_id = _valid_case_id(row.get("case_id"), label=f"dataset.cases[{index}].case_id")
                if case_id in dataset_by_id:
                    blockers.append(f"dataset_case_duplicate:{case_id}")
                dataset_by_id[case_id] = row
                _sha256(row.get("sha256"), label=f"dataset.cases[{index}].sha256")
            except BridgeContractError as error:
                blockers.append(str(error))

    package_projection = {
        "package_root": {
            "path": _relative(package_root, package_root.parent, label="package_root"),
            "name": package_root.name,
            "directory": True,
            "symlink": False,
        },
        "bundle": dict(bundle_ref),
        "dataset": dict(dataset_ref),
        "bundle_schema": bundle.get("schema"),
        "dataset_schema": dataset.get("schema"),
        "bundle_case_count": bundle.get("case_count"),
        "dataset_case_count": dataset.get("case_count"),
        "bundle_file_count": len(file_entries),
        "checkpoint_count": bundle.get("checkpoint_count"),
        "non_json_assets_opened": False,
        "package_metadata_only": True,
    }
    return package_projection, dataset_by_id, _dedupe(blockers)


def _validate_verification(
    *,
    payload: Mapping[str, object],
    report_ref: Mapping[str, object],
    dataset_ref: Mapping[str, object],
    dataset_by_id: Mapping[str, Mapping[str, object]],
) -> tuple[dict[str, object], list[str]]:
    blockers: list[str] = []
    for key, expected in (("schema", VERIFICATION_SCHEMA), ("case_count", EXPECTED_CASE_COUNT)):
        if key == "schema":
            if payload.get(key) != expected:
                blockers.append(f"verification_schema_drift:{payload.get(key)!r}")
        else:
            try:
                value = _strict_int(payload.get(key), label="verification.case_count")
                if value != expected:
                    blockers.append(f"verification_case_count_drift:{value}!={expected}")
            except BridgeContractError as error:
                blockers.append(str(error))
    for key in ("passed", "full_temporal_scan"):
        try:
            if _strict_bool(payload.get(key), label=f"verification.{key}") is not True:
                blockers.append(f"verification_{key}_must_be_true")
        except BridgeContractError as error:
            blockers.append(str(error))
    try:
        if _strict_bool(payload.get("qualification_inferred"), label="verification.qualification_inferred"):
            blockers.append("verification_qualification_inferred_must_be_false")
    except BridgeContractError as error:
        blockers.append(str(error))
    try:
        manifest_sha = _sha256(payload.get("manifest_sha256"), label="verification.manifest_sha256")
        if manifest_sha != dataset_ref.get("sha256"):
            blockers.append("verification_manifest_sha256_does_not_bind_dataset_json")
    except BridgeContractError as error:
        manifest_sha = None
        blockers.append(str(error))

    cases = payload.get("cases")
    observed_by_id: dict[str, Mapping[str, object]] = {}
    if not isinstance(cases, list):
        blockers.append("verification_cases_missing_or_not_a_list")
    else:
        if len(cases) != EXPECTED_CASE_COUNT:
            blockers.append(f"verification_cases_length_drift:{len(cases)}!={EXPECTED_CASE_COUNT}")
        for index, row in enumerate(cases):
            if not isinstance(row, Mapping):
                blockers.append(f"verification_case_{index}_not_an_object")
                continue
            label = f"verification.cases[{index}]"
            try:
                case_id = _valid_case_id(row.get("case_id"), label=f"{label}.case_id")
                if case_id in observed_by_id:
                    blockers.append(f"verification_case_duplicate:{case_id}")
                observed_by_id[case_id] = row
                if case_id not in dataset_by_id:
                    blockers.append(f"verification_case_not_in_dataset:{case_id}")
                else:
                    if row.get("sha256") != dataset_by_id[case_id].get("sha256"):
                        blockers.append(f"verification_case_sha256_drift:{case_id}")
                if _strict_bool(row.get("passed"), label=f"{label}.passed") is not True:
                    blockers.append(f"verification_case_not_passed:{case_id}")
                if _strict_int(row.get("transition_count"), label=f"{label}.transition_count") != EXPECTED_TRANSITIONS:
                    blockers.append(f"verification_case_transition_count_drift:{case_id}")
                if "full_temporal_scan" in row and _strict_bool(
                    row.get("full_temporal_scan"), label=f"{label}.full_temporal_scan"
                ) is not True:
                    blockers.append(f"verification_case_full_temporal_scan_false:{case_id}")
                oracles = row.get("oracles")
                if not isinstance(oracles, list) or len(oracles) != EXPECTED_TRANSITIONS:
                    blockers.append(f"verification_case_oracle_count_drift:{case_id}")
                else:
                    for oracle_index, oracle in enumerate(oracles):
                        if not isinstance(oracle, Mapping):
                            blockers.append(f"verification_oracle_not_object:{case_id}:{oracle_index}")
                            continue
                        if oracle.get("schema") != "core.updater_oracle.v1":
                            blockers.append(f"verification_oracle_schema_drift:{case_id}:{oracle_index}")
                        if oracle.get("learned_model_qualified") is not False:
                            blockers.append(f"verification_oracle_qualification_drift:{case_id}:{oracle_index}")
            except BridgeContractError as error:
                blockers.append(str(error))

    expected_ids = set(dataset_by_id)
    observed_ids = set(observed_by_id)
    for case_id in sorted(expected_ids - observed_ids):
        blockers.append(f"verification_case_missing:{case_id}")
    for case_id in sorted(observed_ids - expected_ids):
        blockers.append(f"verification_case_unexpected:{case_id}")

    verification_projection = {
        "source": dict(report_ref),
        "schema": payload.get("schema"),
        "passed": payload.get("passed"),
        "full_temporal_scan": payload.get("full_temporal_scan"),
        "qualification_inferred": payload.get("qualification_inferred"),
        "case_count": payload.get("case_count"),
        "observed_case_count": len(observed_by_id),
        "passed_case_count": sum(1 for row in observed_by_id.values() if row.get("passed") is True),
        "full_temporal_case_count": sum(
            1
            for row in observed_by_id.values()
            if row.get("passed") is True
            and row.get("transition_count") == EXPECTED_TRANSITIONS
            and ("full_temporal_scan" not in row or row.get("full_temporal_scan") is True)
            and isinstance(row.get("oracles"), list)
            and len(row.get("oracles")) == EXPECTED_TRANSITIONS
        ),
        "transition_count": EXPECTED_TRANSITIONS,
        "manifest_sha256": payload.get("manifest_sha256"),
        "case_ids": sorted(observed_by_id),
        "source_payload_embedded": False,
    }
    return verification_projection, _dedupe(blockers)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _base_report(
    *,
    blockers: list[str],
    package: Mapping[str, object] | None,
    verification: Mapping[str, object] | None,
    read_boundary: Mapping[str, object],
) -> dict[str, object]:
    blockers = _dedupe(list(blockers))
    passed = not blockers
    report: dict[str, object] = {
        "schema": BRIDGE_SCHEMA,
        "version": 1,
        "status": "passed" if passed else "blocked",
        "passed": passed,
        "blocked": not passed,
        "diagnostic_only": True,
        "qualification_inferred": False,
        "qualification_credit": 0,
        "claims": dict(ZERO_CREDIT_CLAIMS),
        "mutations": dict(ZERO_MUTATIONS),
        "package": dict(package) if package is not None else None,
        "verification": dict(verification) if verification is not None else None,
        "blockers": blockers,
        "read_boundary": dict(read_boundary),
    }
    return report


def _read_boundary() -> dict[str, object]:
    return {
        "verification_json_opened": False,
        "bundle_json_opened": False,
        "dataset_json_opened": False,
        "strict_duplicate_keys_rejected": True,
        "strict_nonfinite_numbers_rejected": True,
        "bounded_json_reads": True,
        "hdf5_opened": False,
        "npz_opened": False,
        "checkpoint_opened": False,
        "training_started": False,
        "solver_started": False,
        "worker_or_queue_started": False,
        "gpu_started": False,
    }


def build_bridge_report(
    *,
    verification_report: str | Path,
    package_root: str | Path,
    lab_root: str | Path = LAB_ROOT,
    output: str | Path | None = None,
    zh_output: str | Path | None = None,
) -> dict[str, object]:
    """Build the bounded bridge, optionally writing JSON and Chinese Markdown."""
    boundary = _read_boundary()
    blockers: list[str] = []
    package_projection: dict[str, object] | None = None
    verification_projection: dict[str, object] | None = None
    try:
        root = _regular_directory(lab_root, label="lab_root")
    except BridgeContractError as error:
        report = _base_report(
            blockers=[f"lab_root_invalid:{error}"],
            package=None,
            verification=None,
            read_boundary=boundary,
        )
        _write_requested_outputs(report, output=output, zh_output=zh_output, lab_root=None)
        return report

    try:
        package = _regular_directory(package_root, label="package_root")
        package_relative = _relative(package, root, label="package_root")
        if package_relative == ".":
            raise BridgeContractError("package_root must be below lab_root")
    except BridgeContractError as error:
        report = _base_report(
            blockers=[f"package_root_invalid:{error}"],
            package=None,
            verification=None,
            read_boundary=boundary,
        )
        _write_requested_outputs(
            report,
            output=output,
            zh_output=zh_output,
            lab_root=root,
            protected_paths=(_absolute(verification_report),),
        )
        return report

    try:
        verification_ref, verification_payload, verification_path = _read_json_ref(
            verification_report,
            root=root,
            label="verification report",
            max_bytes=MAX_VERIFICATION_JSON_BYTES,
            expected_name=VERIFICATION_FILENAME,
            expected_parent="reports",
        )
        boundary["verification_json_opened"] = True
    except BridgeContractError as error:
        blockers.append(f"verification_json_unreadable:{error}")
        verification_ref = None
        verification_payload = None
        verification_path = None

    try:
        bundle_ref, bundle_payload, bundle_path = _read_json_ref(
            package / "bundle.json",
            root=package,
            label="package bundle.json",
            max_bytes=MAX_PACKAGE_JSON_BYTES,
            expected_name="bundle.json",
        )
        boundary["bundle_json_opened"] = True
    except BridgeContractError as error:
        blockers.append(f"bundle_json_unreadable:{error}")
        bundle_ref = None
        bundle_payload = None
        bundle_path = None

    try:
        dataset_ref, dataset_payload, dataset_path = _read_json_ref(
            package / "dataset.json",
            root=package,
            label="package dataset.json",
            max_bytes=MAX_PACKAGE_JSON_BYTES,
            expected_name="dataset.json",
        )
        boundary["dataset_json_opened"] = True
    except BridgeContractError as error:
        blockers.append(f"dataset_json_unreadable:{error}")
        dataset_ref = None
        dataset_payload = None
        dataset_path = None

    if bundle_ref is not None and dataset_ref is not None:
        if bundle_path is None or dataset_path is None or bundle_path.parent != dataset_path.parent:
            blockers.append("package_root_identity_drift")
        if bundle_ref.get("path") != "bundle.json" or dataset_ref.get("path") != "dataset.json":
            blockers.append("package_metadata_paths_drift")
    if bundle_payload is not None and dataset_payload is not None and bundle_ref and dataset_ref:
        package_projection, dataset_by_id, package_blockers = _validate_package(
            package_root=package,
            bundle=bundle_payload,
            dataset=dataset_payload,
            bundle_ref=bundle_ref,
            dataset_ref=dataset_ref,
        )
        # The projection is relative to the selected lab root, not to the
        # package parent.  Keep this identity portable and explicit.
        package_projection["package_root"] = {
            "path": _relative(package, root, label="package_root"),
            "name": package.name,
            "directory": True,
            "symlink": False,
        }
        blockers.extend(package_blockers)
    else:
        dataset_by_id = {}

    if verification_payload is not None and verification_ref is not None and dataset_ref is not None:
        verification_projection, verification_blockers = _validate_verification(
            payload=verification_payload,
            report_ref=verification_ref,
            dataset_ref=dataset_ref,
            dataset_by_id=dataset_by_id,
        )
        blockers.extend(verification_blockers)
    else:
        blockers.append("verification_package_binding_incomplete")

    report = _base_report(
        blockers=blockers,
        package=package_projection,
        verification=verification_projection,
        read_boundary=boundary,
    )
    _write_requested_outputs(
        report,
        output=output,
        zh_output=zh_output,
        lab_root=root,
        protected_paths=(
            _absolute(verification_report),
            package / "bundle.json",
            package / "dataset.json",
        ),
    )
    return report


def _output_path(path: str | Path, *, lab_root: Path, label: str, suffix: str) -> Path:
    candidate = _absolute(path)
    if candidate.suffix != suffix:
        raise BridgeContractError(f"{label} must have suffix {suffix}")
    # The final output directory may be created by the controlled writer; all
    # existing parent components must still be real, non-symlink directories.
    _assert_no_symlink_components(candidate.parent, require_final=False)
    if candidate.exists() and candidate.is_symlink():
        raise BridgeContractError(f"{label} symlink is forbidden")
    _relative(candidate, lab_root, label=label)
    return candidate


def _atomic_write(path: Path, raw: bytes, *, max_bytes: int, label: str) -> None:
    if len(raw) > max_bytes:
        raise BridgeContractError(f"{label} exceeds output byte limit")
    path.parent.mkdir(parents=False, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _write_requested_outputs(
    report: Mapping[str, object],
    *,
    output: str | Path | None,
    zh_output: str | Path | None,
    lab_root: Path | None,
    protected_paths: tuple[Path, ...] = (),
) -> None:
    if output is None and zh_output is None:
        return
    if lab_root is None:
        raise BridgeContractError("cannot write outputs without a valid lab_root")
    protected = {_absolute(path) for path in protected_paths}
    if output is not None:
        output_path = _output_path(output, lab_root=lab_root, label="bridge output", suffix=".json")
        if output_path in protected:
            raise BridgeContractError("bridge output must not overwrite a bounded input JSON")
        _atomic_write(
            output_path,
            (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8"),
            max_bytes=MAX_BRIDGE_JSON_BYTES,
            label="bridge JSON output",
        )
    if zh_output is not None:
        zh_path = _output_path(zh_output, lab_root=lab_root, label="Chinese bridge output", suffix=".md")
        _atomic_write(
            zh_path,
            render_zh(report).encode("utf-8"),
            max_bytes=MAX_BRIDGE_JSON_BYTES,
            label="Chinese bridge output",
        )


def render_zh(report: Mapping[str, object]) -> str:
    """Render a compact Chinese diagnostic receipt without source payloads."""
    package = report.get("package") if isinstance(report.get("package"), Mapping) else {}
    verification = report.get("verification") if isinstance(report.get("verification"), Mapping) else {}
    blockers = report.get("blockers") if isinstance(report.get("blockers"), list) else []
    package_root = package.get("package_root") if isinstance(package.get("package_root"), Mapping) else {}
    lines = [
        "# A8 full-temporal verification receipt bridge v1",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- diagnostic-only：`{report.get('diagnostic_only')}`",
        f"- qualification_inferred：`{report.get('qualification_inferred')}`",
        f"- qualification credit：`{report.get('qualification_credit')}`",
        f"- package root：`{package_root.get('path', '<unbound>')}`",
        f"- verification：`{verification.get('passed')}`，full-temporal cases `{verification.get('full_temporal_case_count', 0)}/{EXPECTED_CASE_COUNT}`",
        f"- transitions per case：`{EXPECTED_TRANSITIONS}`",
        "",
        "## 读取边界",
        "",
        "仅打开 verification/bundle/dataset 三个 bounded JSON；没有打开 HDF5、NPZ、checkpoint，没有启动训练、solver、worker、queue 或 GPU。",
        "",
        "## Blockers",
        "",
    ]
    if blockers:
        lines.extend(f"- `{item}`" for item in blockers)
    else:
        lines.append("- 无；该 bridge 仍只提供 diagnostic-only、zero-credit 证据。")
    lines.append("")
    return "\n".join(lines)


def _validate_local_shape(report: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    if report.get("schema") != BRIDGE_SCHEMA:
        errors.append("bridge.schema drift")
    if report.get("version") != 1:
        errors.append("bridge.version drift")
    if report.get("diagnostic_only") is not True:
        errors.append("bridge.diagnostic_only must be true")
    if report.get("qualification_inferred") is not False:
        errors.append("bridge.qualification_inferred must be false")
    if report.get("qualification_credit") != 0:
        errors.append("bridge.qualification_credit drift")
    if report.get("claims") != ZERO_CREDIT_CLAIMS:
        errors.append("bridge.claims drift")
    if report.get("mutations") != ZERO_MUTATIONS:
        errors.append("bridge.mutations drift")
    blockers = report.get("blockers")
    if not isinstance(blockers, list) or any(not isinstance(item, str) for item in blockers):
        errors.append("bridge.blockers malformed")
        blockers = []
    passed = report.get("passed")
    blocked = report.get("blocked")
    if type(passed) is not bool or type(blocked) is not bool or blocked is not (not passed):
        errors.append("bridge passed/blocked relation drift")
    expected_status = "passed" if passed is True else "blocked"
    if report.get("status") != expected_status:
        errors.append("bridge.status drift")
    if passed is True and blockers:
        errors.append("passed bridge contains blockers")
    if passed is not True:
        errors.append("bridge is blocked")
    if not isinstance(report.get("read_boundary"), Mapping):
        errors.append("bridge.read_boundary missing")
    else:
        boundary = report["read_boundary"]
        for key in (
            "hdf5_opened", "npz_opened", "checkpoint_opened", "training_started",
            "solver_started", "worker_or_queue_started", "gpu_started",
        ):
            if boundary.get(key) is not False:
                errors.append(f"bridge.read_boundary.{key} must be false")
    return errors


def validate_report(
    report: Mapping[str, object],
    *,
    verification_report: str | Path | None = None,
    package_root: str | Path | None = None,
    lab_root: str | Path = LAB_ROOT,
) -> list[str]:
    """Validate a bridge locally and, when paths are supplied, against inputs."""
    if not isinstance(report, Mapping):
        return ["bridge report must be an object"]
    errors = _validate_local_shape(report)
    if verification_report is None or package_root is None:
        return errors
    expected = build_bridge_report(
        verification_report=verification_report,
        package_root=package_root,
        lab_root=lab_root,
    )
    if dict(report) != expected:
        errors.append("bridge report does not match the current bounded inputs")
    return _dedupe(errors)


def validate_report_file(
    *,
    bridge_path: str | Path,
    verification_report: str | Path,
    package_root: str | Path,
    lab_root: str | Path = LAB_ROOT,
) -> list[str]:
    root = _regular_directory(lab_root, label="lab_root")
    ref, payload, _ = _read_json_ref(
        bridge_path,
        root=root,
        label="bridge report",
        max_bytes=MAX_BRIDGE_JSON_BYTES,
        expected_name=None,
    )
    del ref
    return validate_report(
        payload,
        verification_report=verification_report,
        package_root=package_root,
        lab_root=root,
    )


def _default_paths() -> tuple[Path, Path, Path, Path]:
    verification = LAB_ROOT / "reports" / VERIFICATION_FILENAME
    package = LAB_ROOT / DEFAULT_PACKAGE_RELATIVE
    output = LAB_ROOT / "reports" / DEFAULT_BRIDGE_FILENAME
    zh_output = LAB_ROOT / "reports" / DEFAULT_ZH_FILENAME
    return verification, package, output, zh_output


def main(argv: list[str] | None = None) -> int:
    verification_default, package_default, output_default, zh_default = _default_paths()
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="build the diagnostic-only bridge")
    build_parser.add_argument("--lab-root", default=str(LAB_ROOT))
    build_parser.add_argument("--verification", default=str(verification_default))
    build_parser.add_argument("--package-root", default=str(package_default))
    build_parser.add_argument("--output", default=str(output_default))
    build_parser.add_argument("--zh-output", default=str(zh_default))

    validate_parser = subparsers.add_parser("validate", help="validate an existing bridge")
    validate_parser.add_argument("--lab-root", default=str(LAB_ROOT))
    validate_parser.add_argument("--bridge", default=str(output_default))
    validate_parser.add_argument("--verification", default=str(verification_default))
    validate_parser.add_argument("--package-root", default=str(package_default))

    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            report = build_bridge_report(
                verification_report=args.verification,
                package_root=args.package_root,
                lab_root=args.lab_root,
                output=args.output,
                zh_output=args.zh_output,
            )
            print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
            return 0 if report.get("passed") is True else 2
        errors = validate_report_file(
            bridge_path=args.bridge,
            verification_report=args.verification,
            package_root=args.package_root,
            lab_root=args.lab_root,
        )
    except (BridgeContractError, OSError, TypeError, ValueError) as error:
        print(json.dumps({"status": "blocked", "errors": [str(error)]}, ensure_ascii=False), file=sys.stderr)
        return 2
    if errors:
        print(json.dumps({"status": "blocked", "errors": errors}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"status": "passed", "errors": []}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
