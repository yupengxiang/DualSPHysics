#!/usr/bin/env python3
"""Build v5 canonical observer requests using the v2 source enforcer.

The v4 builder and all v4 requests are consumed history and remain untouched.
This additive builder reuses v4's identity and snapshot validation without
opening any BI4 file, then writes a new request identity whose command uses
``stage2_native_physical_observer_enforcer_v2.py``.  v2 verifies the complete
selected-file stat record across the child decode and rejects UNKNOWN child
artifacts even when the child exits zero.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any

import stage2_native_observer_canonical_request_v4 as base


SCHEMA = "ds02.stage2.native-observer-canonical-request.v5"
REQUEST_SCHEMA = base.REQUEST_SCHEMA
REPO = base.REPO
REQUEST_ROOT = base.REQUEST_ROOT
ENFORCER_WORKER_V2 = Path(__file__).with_name("stage2_native_physical_observer_enforcer_v2.py").resolve()
TEMPLATE_PATHS = base.TEMPLATE_PATHS


def atomic_json(path: Path, value: Any) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refuse to overwrite immutable request: {path}")
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def deep_forward(value: Any, temporary_manifest: str, final_manifest: str) -> Any:
    """Forward only v4 identity tokens and the temporary manifest path."""

    if isinstance(value, dict):
        return {
            (final_manifest if key == temporary_manifest else key): deep_forward(item, temporary_manifest, final_manifest)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [deep_forward(item, temporary_manifest, final_manifest) for item in value]
    if isinstance(value, str):
        return (value.replace(temporary_manifest, final_manifest)
                .replace("CANONICAL_SNAPSHOT_V4", "CANONICAL_SNAPSHOT_V5")
                .replace("canonical_snapshot_v4", "canonical_snapshot_v5")
                .replace("canonical-snapshot-v4", "canonical-snapshot-v5"))
    return value


def make_forward_request(template: dict[str, Any], snapshot_entry: dict[str, Any],
                         receipt_path: Path, result_path: Path, output_dir: Path) -> tuple[dict[str, Any], Path]:
    """Use the immutable v4 constructor in a private directory, then forward its bytes."""

    with tempfile.TemporaryDirectory(prefix="ds02-observer-v5-build-") as temp_text:
        temp_dir = Path(temp_text)
        old_enforcer = base.ENFORCER_WORKER
        old_data_root = base.DATA_ROOT
        base.ENFORCER_WORKER = ENFORCER_WORKER_V2
        # The v4 constructor only uses DATA_ROOT for an existence guard.  A
        # private root prevents a new builder from probing/claiming a v4 data
        # output path; no source data is touched.
        base.DATA_ROOT = temp_dir / "data-root"
        try:
            request, temp_request_path = base.make_request(
                template, snapshot_entry, receipt_path, result_path, Path(__file__).resolve(), temp_dir
            )
        finally:
            base.ENFORCER_WORKER = old_enforcer
            base.DATA_ROOT = old_data_root

        temp_manifest_path = Path(request["source_snapshot_binding"]["expected_source_manifest"]["path"]).resolve()
        manifest_value = json.loads(temp_manifest_path.read_text(encoding="utf-8"))
        final_manifest_path = output_dir / temp_manifest_path.name
        atomic_json(final_manifest_path, manifest_value)
        forwarded = deep_forward(request, str(temp_manifest_path), str(final_manifest_path))
        forwarded["source_snapshot_binding"]["expected_source_manifest"] = base.record(final_manifest_path)
        forwarded["deferred_hash_policy"]["source_mutation_during_decode"] = (
            "FAIL_IF_PRE_POST_CONTENT_OR_COMPLETE_STAT_DIFFERS"
        )
        forwarded["source_snapshot_binding"]["source_stat_validation"] = (
            "enforcer v2 requires pre.stat_after == post.stat_before and "
            "pre.stat_before == post.stat_after for every selected frame"
        )
        token = str(forwarded["case_id"]).replace("_CANONICAL_SNAPSHOT_V5", "")
        request_path = output_dir / f"{token.lower()}_canonical_snapshot_v5.json"
        atomic_json(request_path, forwarded)
        return forwarded, request_path


def build(snapshot_receipt_path: Path, snapshot_result_path: Path, output_dir: Path) -> dict[str, Any]:
    receipt_path = base.regular_file(snapshot_receipt_path, "snapshot terminal receipt")
    result_path = base.regular_file(snapshot_result_path, "snapshot terminal result")
    receipt = base.load_json(receipt_path, "snapshot terminal receipt")
    result = base.load_json(result_path, "snapshot terminal result")
    templates = [base.selected_template_metadata(path) for path in TEMPLATE_PATHS]
    entries = base.validate_snapshot_pair(receipt, result, receipt_path, result_path, templates)
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"refuse to populate non-empty canonical request directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    for template, entry in zip(templates, entries):
        _request, path = make_forward_request(template, entry, receipt_path, result_path, output_dir)
        paths.append(str(path.resolve()))
    manifest = {
        "schema": SCHEMA,
        "status": "PREPARED_CANONICAL_REQUESTS_SNAPSHOT_BOUND_ENFORCER_V2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "snapshot_receipt": base.record(receipt_path),
        "snapshot_result": base.record(result_path),
        "template_count": len(templates),
        "selected_native_file_count": 36,
        "builder_scope": {
            "bi4_read": False,
            "bi4_hash": False,
            "hdf5_read": False,
            "decoder_launch": False,
            "source_sha_consumed_from_snapshot_result": True,
            "parent_pre_decode_sha_and_complete_stat_check_required": True,
            "worker_post_decode_sha_and_complete_stat_check_required": True,
            "cross_decode_stat_boundary_check": "pre.stat_after == post.stat_before and pre.stat_before == post.stat_after",
            "unknown_child_status_is_failure": True,
        },
        "enforcer": {"path": str(ENFORCER_WORKER_V2), "schema": "ds02.stage2.native-physical-observer-enforcer.v2"},
        "request_paths": paths,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(output_dir / "canonical_observer_requests_v5_manifest.json", manifest)
    return manifest


def manufactured_self_test() -> dict[str, Any]:
    base_result = base.manufactured_self_test()
    assert base_result["status"] == "PASS"
    transformed = deep_forward(
        {"case_id": "X_CANONICAL_SNAPSHOT_V4", "path": "canonical_snapshot_v4.json"},
        "/tmp/old-manifest.json", "/tmp/new-manifest.json",
    )
    assert transformed["case_id"] == "X_CANONICAL_SNAPSHOT_V5"
    assert transformed["path"] == "canonical_snapshot_v5.json"
    assert ENFORCER_WORKER_V2.name.endswith("enforcer_v2.py")
    return {"status": "PASS", "base_snapshot_identity_checks": True,
            "v4_identity_forwarded_to_v5": True, "enforcer_v2_bound": True,
            "bi4_read": False, "hdf5_read": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-receipt", type=Path)
    parser.add_argument("--snapshot-result", type=Path)
    parser.add_argument("--output-dir", type=Path,
                        default=REQUEST_ROOT / "stage2-native-observer-canonical-v5-forward")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(manufactured_self_test(), indent=2))
        return 0
    if args.snapshot_receipt is None or args.snapshot_result is None:
        parser.error("--snapshot-receipt and --snapshot-result are required unless --self-test is used")
    manifest = build(args.snapshot_receipt, args.snapshot_result, args.output_dir)
    print(json.dumps({"status": manifest["status"], "requests": len(manifest["request_paths"]),
                      "selected_native_file_count": manifest["selected_native_file_count"], "bi4_read": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
