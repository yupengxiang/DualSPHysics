#!/usr/bin/env python3
"""Adapt the ROOT139 snapshot wrapper to the enforcer's v1 source manifest.

ROOT139's ``native_selected_source_snapshot_v2.json`` is a producer wrapper:
it contains request metadata and an ``immutable_source_sha_list``.  The
consumed observer enforcer intentionally accepts the smaller
``native-observer-source-manifest.v1`` contract instead.  This forward-only
adapter reads only the ROOT139 JSON and emits that exact contract.  It never
opens, hashes, stats, or scans a ``Part_*.bi4`` payload.

The adapter is deliberately strict about the ROOT139 physical identity,
selected ten-frame axis, raw-root path, source SHA-list, and snapshot JSON
SHA.  It therefore cannot silently turn another snapshot or another sentinel
into the F3-S2 header audit.  Scientific fields remain UNKNOWN until the
enforcer and official decoder actually run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any


ADAPTER_SCHEMA = "ds02.stage2.f3-s2.native-source-manifest-adapter.v1"
MANIFEST_SCHEMA = "ds02.stage2.native-observer-source-manifest.v1"
SNAPSHOT_SCHEMA = "ds02.stage2.native-source-snapshot.v2"
SNAPSHOT_STATUS = "PASS_SELECTED_NATIVE_SOURCE_HASHED_STABLE"

SNAPSHOT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/"
    "F3_S2_COARSE_SELECTED_SOURCE_SNAPSHOT_ROOT_139/"
    "f3-s2-coarse-selected-source-snapshot-root-139-001-root-forward-030-001/"
    "native_selected_source_snapshot_v2.json"
)
SNAPSHOT_SHA256 = "0a479cf3c52c51b2fd57f4c68168bdc9077a8f06132866b864769e237b29e1df"
SNAPSHOT_REQUEST_SHA256 = "2041adc01baddeb7e90d20c4b5bb882ea107f61da995f67ca198120bab9bbfad"
SNAPSHOT_PROOF_SHA256 = "2c8cc5f2a11dca8d0d6052cf3c2ace870cacb792c50fd31dcf7c74e348bd9c35"
SNAPSHOT_PROOF = Path(
    "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/"
    "F3_TEN_SELECTED_SOURCE_SNAPSHOT_ACTUAL_SCOPE_ROOT_VERIFICATION_139.json"
)
EXPECTED_RAW_ROOT = Path(
    "/var/tmp/ds02-stage2/F3/"
    "F3_S2_OWNER_CENTERED_DP015_FULL_CFD_CANARY_ROOT_133/"
    "f3-s2-owner-centered-dp015-full-cfd-canary-v8-root-133-001/"
    "solver_output/data"
)
EXPECTED_FRAMES = [0, 199, 200, 399, 400, 599, 600, 799, 800, 835]
EXPECTED_FAMILY_ID = "F3"
EXPECTED_SENTINEL_ID = "F3-S2"
EXPECTED_PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
EXPECTED_CASE_ID = "F3_S2_COARSE_SELECTED_SOURCE_SNAPSHOT_ROOT_139"


class AdapterError(ValueError):
    """The producer snapshot cannot be adapted without changing its identity."""


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def require_json_file(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise AdapterError(f"{label} is missing or symlinked: {path}")
    return path


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise AdapterError(f"{label} is not a lowercase SHA-256")
    return value


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AdapterError(f"{label} is not a positive integer")
    return int(value)


def _source_record(value: Any, frame: int, raw_root: Path) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AdapterError(f"frame {frame} source record is not an object")
    path = value.get("path")
    expected_path = (raw_root / f"Part_{frame:04d}.bi4").resolve()
    if path != str(expected_path):
        raise AdapterError(f"frame {frame} path is not the ROOT133 raw-root contract: {path!r}")
    if value.get("frame") != frame:
        raise AdapterError(f"source record frame mismatch: expected {frame}, got {value.get('frame')!r}")
    return {
        "frame": frame,
        "path": str(expected_path),
        "bytes": _positive_int(value.get("bytes"), f"frame {frame} bytes"),
        "sha256": _sha(value.get("sha256"), f"frame {frame} sha256"),
    }


def load_root139_snapshot(
    path: Path,
    *,
    expected_snapshot_sha: str | None = SNAPSHOT_SHA256,
    strict_actual_identity: bool = True,
) -> dict[str, Any]:
    """Read and validate the small ROOT139 wrapper without touching BI4 files."""

    path = require_json_file(path, "ROOT139 snapshot")
    actual_sha, snapshot_bytes = sha256_file(path)
    if expected_snapshot_sha is not None and actual_sha != expected_snapshot_sha:
        raise AdapterError(
            f"ROOT139 snapshot SHA mismatch: expected {expected_snapshot_sha}, got {actual_sha}"
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AdapterError(f"cannot read ROOT139 snapshot JSON: {path}") from exc
    if not isinstance(value, dict):
        raise AdapterError("ROOT139 snapshot is not an object")
    if value.get("schema") != SNAPSHOT_SCHEMA or value.get("status") != SNAPSHOT_STATUS:
        raise AdapterError("ROOT139 snapshot does not have the successful v2 wrapper schema/status")

    scope = value.get("worker_scope")
    if not isinstance(scope, dict):
        raise AdapterError("ROOT139 snapshot has no worker_scope")
    if scope.get("selected_native_bi4_only") is not True:
        raise AdapterError("ROOT139 snapshot is not restricted to selected native BI4 files")
    if scope.get("bi4_decode") is not False or scope.get("hdf5_read") is not False or scope.get("solver_launch") is not False:
        raise AdapterError("ROOT139 snapshot scope claims an unsupported operation")
    if scope.get("full_raw_tree_scan") not in {False, "FORBIDDEN", "NOT_COMPUTED_BY_WORKER"}:
        raise AdapterError("ROOT139 snapshot is not an exact selected-frame snapshot")

    requests = value.get("requests")
    if not isinstance(requests, list) or len(requests) != 1 or not isinstance(requests[0], dict):
        raise AdapterError("ROOT139 snapshot must contain exactly one producer request")
    request = requests[0]
    observer_request = request.get("observer_request")
    if not isinstance(observer_request, dict):
        raise AdapterError("ROOT139 request identity is missing observer_request")
    if strict_actual_identity and observer_request.get("sha256") != SNAPSHOT_REQUEST_SHA256:
        raise AdapterError("ROOT139 observer request SHA does not match the actual request")
    if strict_actual_identity and request.get("case_id") != EXPECTED_CASE_ID:
        raise AdapterError(f"unexpected ROOT139 case_id: {request.get('case_id')!r}")
    if strict_actual_identity:
        for key, expected in (
            ("family_id", EXPECTED_FAMILY_ID),
            ("sentinel_id", EXPECTED_SENTINEL_ID),
            ("physical_case_id", EXPECTED_PHYSICAL_CASE_ID),
        ):
            if request.get(key) != expected:
                raise AdapterError(f"unexpected ROOT139 {key}: {request.get(key)!r}")
    raw_root = request.get("raw_root")
    if not isinstance(raw_root, str) or (strict_actual_identity and Path(raw_root).expanduser().resolve() != EXPECTED_RAW_ROOT.resolve()):
        raise AdapterError(f"ROOT139 raw_root does not match ROOT133: {raw_root!r}")
    frame_ids = request.get("selected_native_frame_ids")
    if frame_ids != EXPECTED_FRAMES:
        raise AdapterError(f"ROOT139 selected frame axis differs: {frame_ids!r}")

    request_files = request.get("selected_native_files")
    immutable_files = value.get("immutable_source_sha_list")
    if not isinstance(request_files, list) or not isinstance(immutable_files, list):
        raise AdapterError("ROOT139 selected source records are missing")
    if len(request_files) != len(EXPECTED_FRAMES) or len(immutable_files) != len(EXPECTED_FRAMES):
        raise AdapterError("ROOT139 does not contain exactly ten selected source files")
    root = Path(raw_root).expanduser().resolve()
    selected = [_source_record(item, frame, root) for item, frame in zip(request_files, EXPECTED_FRAMES)]
    immutable = [_source_record(item, frame, root) for item, frame in zip(immutable_files, EXPECTED_FRAMES)]
    if selected != immutable:
        raise AdapterError("ROOT139 request and immutable source SHA lists differ")
    request_selected_bytes = request.get("selected_native_total_bytes", request.get("selected_native_bytes"))
    if request_selected_bytes != sum(item["bytes"] for item in selected):
        raise AdapterError("ROOT139 selected byte total does not close")
    source_digest = _sha(request.get("selected_source_sha256"), "ROOT139 source SHA-list digest")
    if value.get("source_sha_list_digest") != source_digest:
        raise AdapterError("ROOT139 wrapper/source request SHA-list digest differs")
    if value.get("selected_native_total_bytes") != request_selected_bytes:
        raise AdapterError("ROOT139 wrapper/request byte totals differ")

    return {
        "snapshot_path": str(path),
        "snapshot_sha256": actual_sha,
        "snapshot_bytes": snapshot_bytes,
        "snapshot_schema": value["schema"],
        "snapshot_status": value["status"],
        "raw_root": str(root),
        "selected_native_files": selected,
        "selected_native_total_bytes": int(request_selected_bytes),
        "source_sha_list_digest": source_digest,
        "identity": {
            "family_id": EXPECTED_FAMILY_ID,
            "sentinel_id": EXPECTED_SENTINEL_ID,
            "physical_case_id": EXPECTED_PHYSICAL_CASE_ID,
            "case_id": EXPECTED_CASE_ID,
            "observer_request_path": observer_request.get("path"),
            "observer_request_sha256": observer_request["sha256"],
        },
        "selected_frame_ids": list(EXPECTED_FRAMES),
        "native_payload_read_by_adapter": False,
    }


def build_manifest(
    snapshot_path: Path,
    *,
    expected_snapshot_sha: str | None = SNAPSHOT_SHA256,
    strict_actual_identity: bool = True,
) -> dict[str, Any]:
    snapshot = load_root139_snapshot(
        snapshot_path,
        expected_snapshot_sha=expected_snapshot_sha,
        strict_actual_identity=strict_actual_identity,
    )
    return {
        "schema": MANIFEST_SCHEMA,
        "status": "PASS_ADAPTED_ROOT139_SOURCE_MANIFEST",
        "raw_root": snapshot["raw_root"],
        "selected_native_files": snapshot["selected_native_files"],
        "adapter": {
            "schema": ADAPTER_SCHEMA,
            "status": "PASS_ROOT139_WRAPPER_TO_ENFORCER_V1",
            "native_payload_read": False,
            "full_raw_tree_scan": False,
            "hdf5_read": False,
            "solver_launch": False,
        },
        "source_snapshot_binding": {
            "path": snapshot["snapshot_path"],
            "sha256": snapshot["snapshot_sha256"],
            "bytes": snapshot["snapshot_bytes"],
            "schema": snapshot["snapshot_schema"],
            "status": snapshot["snapshot_status"],
            "source_sha_list_digest": snapshot["source_sha_list_digest"],
            "selected_native_total_bytes": snapshot["selected_native_total_bytes"],
            "selected_frame_ids": snapshot["selected_frame_ids"],
            "identity": snapshot["identity"],
            "snapshot_proof_sha256": SNAPSHOT_PROOF_SHA256,
        },
        "compatibility": {
            "enforcer_manifest_schema": MANIFEST_SCHEMA,
            "enforcer_load_api": "load_manifest(path) -> (manifest, normalized_selected_native_files)",
            "root144_wrapper_schema_rejected": True,
            "root147_adapter_scope": "metadata-only; no BI4 payload read",
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def write_new(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse to overwrite immutable adapted manifest: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _manufactured_snapshot(raw_root: Path) -> dict[str, Any]:
    records = [
        {"frame": frame, "path": str(raw_root / f"Part_{frame:04d}.bi4"), "bytes": frame + 1, "sha256": f"{frame + 1:064x}"}
        for frame in EXPECTED_FRAMES
    ]
    return {
        "schema": SNAPSHOT_SCHEMA,
        "status": SNAPSHOT_STATUS,
        "worker_scope": {
            "selected_native_bi4_only": True,
            "bi4_decode": False,
            "hdf5_read": False,
            "solver_launch": False,
            "full_raw_tree_scan": False,
        },
        "requests": [{
            "observer_request": {"path": "/manufactured/root139-request.json", "sha256": SNAPSHOT_REQUEST_SHA256},
            "case_id": EXPECTED_CASE_ID,
            "family_id": EXPECTED_FAMILY_ID,
            "sentinel_id": EXPECTED_SENTINEL_ID,
            "physical_case_id": EXPECTED_PHYSICAL_CASE_ID,
            "raw_root": str(raw_root),
            "selected_native_frame_ids": EXPECTED_FRAMES,
            "selected_native_files": records,
            "selected_native_total_bytes": sum(item["bytes"] for item in records),
            "selected_source_sha256": "a" * 64,
        }],
        "immutable_source_sha_list": records,
        "selected_native_total_bytes": sum(item["bytes"] for item in records),
        "source_sha_list_digest": "a" * 64,
    }


def self_test() -> dict[str, Any]:
    """Exercise the adapter and both enforcer manifest-loading APIs only."""

    import stage2_native_physical_observer_enforcer_v1 as enforcer_v1
    import stage2_native_physical_observer_enforcer_v2 as enforcer_v2

    with tempfile.TemporaryDirectory(prefix="ds02-f3-root147-adapter-") as root_text:
        root = Path(root_text)
        snapshot_path = root / "root139-wrapper.json"
        snapshot_path.write_text(json.dumps(_manufactured_snapshot(root / "raw")), encoding="utf-8")
        value = build_manifest(snapshot_path, expected_snapshot_sha=None, strict_actual_identity=False)
        adapted = root / "native-observer-source-manifest-v1.json"
        write_new(adapted, value)
        for module in (enforcer_v1, enforcer_v2):
            loaded, records = module.load_manifest(adapted)
            assert loaded["schema"] == MANIFEST_SCHEMA
            assert loaded["status"] == "PASS_ADAPTED_ROOT139_SOURCE_MANIFEST"
            assert [item["frame"] for item in records] == EXPECTED_FRAMES
            assert loaded["source_snapshot_binding"]["identity"]["sentinel_id"] == EXPECTED_SENTINEL_ID
        try:
            enforcer_v1.load_manifest(snapshot_path)
        except enforcer_v1.SourceIntegrityError:
            wrapper_rejected = True
        else:
            wrapper_rejected = False
        assert wrapper_rejected
        bad = json.loads(snapshot_path.read_text(encoding="utf-8"))
        bad["requests"][0]["sentinel_id"] = "F3-S1"
        bad_path = root / "wrong-sentinel.json"
        bad_path.write_text(json.dumps(bad), encoding="utf-8")
        try:
            build_manifest(bad_path, expected_snapshot_sha=None)
        except AdapterError:
            identity_rejected = True
        else:
            identity_rejected = False
        assert identity_rejected
    return {
        "status": "PASS",
        "schema": ADAPTER_SCHEMA,
        "enforcer_manifest_schema": MANIFEST_SCHEMA,
        "enforcer_v1_load_api": True,
        "enforcer_v2_load_api": True,
        "root139_wrapper_rejected_by_enforcer": wrapper_rejected,
        "wrong_sentinel_rejected": identity_rejected,
        "selected_frame_count": len(EXPECTED_FRAMES),
        "native_payload_read": False,
        "solver_launch": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--snapshot", type=Path, default=SNAPSHOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-snapshot-sha", default=SNAPSHOT_SHA256)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    if args.output is None:
        parser.error("--output is required unless --self-test is used")
    value = build_manifest(args.snapshot, expected_snapshot_sha=args.expected_snapshot_sha)
    write_new(args.output, value)
    print(json.dumps({
        "status": value["status"],
        "manifest": str(args.output.expanduser().resolve()),
        "snapshot_sha256": value["source_snapshot_binding"]["sha256"],
        "selected_frame_count": len(value["selected_native_files"]),
        "native_payload_read": False,
        "solver_launch": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
