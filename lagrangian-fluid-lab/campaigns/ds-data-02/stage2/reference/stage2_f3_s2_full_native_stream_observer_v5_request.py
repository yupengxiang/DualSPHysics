#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build a forward full-native request with separated byte accounting.

The consumed v4 request used the complete external output-tree size as the
native Part read estimate.  ROOT162 shows that this conflates 6,593,641,516
bytes of actual Part files with 34,050,529 bytes of RunPARTs/log/other tree
content.  This additive builder keeps the v4 worker and source closure, but
requires separate Part and tree estimates and records BI4, forcing, and small
source bytes as independent guard costs.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
V4_REQUEST_PATH = HERE / "stage2_f3_s2_full_native_stream_observer_v4_request.py"
SCHEMA = "ds02.request.v1"
VARIANT = "ds02.stage2.f3-s2.full-native-stream-observer-request.v5"
NATIVE_PASSES = 4
ROOT162_PART_BYTES = 6_593_641_516
ROOT162_TREE_BYTES = 6_627_692_045


def _load_v4_request():
    spec = importlib.util.spec_from_file_location("stage2_f3_s2_full_native_stream_observer_v4_request_dependency", V4_REQUEST_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(V4_REQUEST_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V4_REQUEST = _load_v4_request()


def _canonical(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False, default=str).encode()).hexdigest()


def _scope_is_deferred_source(record: dict[str, Any]) -> bool:
    scope = str(record.get("content_scope", ""))
    return "after-reservation" in scope or "after_reservation" in scope


def _byte_classes(value: dict[str, Any]) -> dict[str, int]:
    records = value.get("input_records")
    if not isinstance(records, dict):
        raise ValueError("v4 request lacks input_records")
    total = 0
    source_payload = 0
    bi4 = 0
    forcing = 0
    for record in records.values():
        if not isinstance(record, dict):
            continue
        amount = int(record.get("bytes", 0) or 0)
        total += amount
        if not _scope_is_deferred_source(record):
            continue
        source_payload += amount
        label = str(record.get("label", "")).lower()
        if "bi4" in label:
            bi4 += amount
        elif "forcing" in label or "csv" in label:
            forcing += amount
    return {
        "static_small_input_bytes": total - source_payload,
        "deferred_source_bytes": source_payload,
        "bi4_source_bytes": bi4,
        "forcing_source_bytes": forcing,
        "input_record_total_bytes": total,
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    part_bytes = int(args.estimated_part_bytes)
    tree_bytes = int(args.estimated_native_tree_bytes)
    if part_bytes <= 0 or tree_bytes <= 0:
        raise ValueError("Part and native-tree byte estimates must be positive")
    if part_bytes > tree_bytes:
        raise ValueError("Part byte estimate cannot exceed complete native output-tree estimate")

    # V4's base builder needs a field named estimated_native_bytes.  Give it
    # the corrected Part-only value and replace all derived accounting below.
    base_args = argparse.Namespace(**vars(args))
    base_args.estimated_native_bytes = part_bytes
    base = V4_REQUEST.build(base_args)
    classes = _byte_classes(base)
    native_tree_nonpart = tree_bytes - part_bytes
    observer_process_read = part_bytes * NATIVE_PASSES + classes["static_small_input_bytes"]
    guarded_source_binding = classes["deferred_source_bytes"]
    guarded_input = observer_process_read + guarded_source_binding

    deferred = dict(base.get("deferred_input_records", {}))
    raw = dict(deferred.get("raw_root", {}))
    raw.update({
        "estimated_bytes": part_bytes,
        "estimated_part_bytes": part_bytes,
        "estimated_tree_bytes": tree_bytes,
        "estimated_non_part_tree_bytes": native_tree_nonpart,
        "estimated_passes": NATIVE_PASSES,
        "pass_semantics": [
            "v2 pre-decode checked_hash per Part",
            "decoder internal sha256_file per Part",
            "official decoder input read per Part",
            "v2 post-decode checked_hash per Part",
        ],
        "tree_size_is_not_part_read": True,
    })
    deferred["raw_root"] = raw

    value: dict[str, Any] = dict(base)
    value.update({
        "schema": SCHEMA,
        "variant_schema": VARIANT,
        "status": "READY_FOR_PARENT_V8_F3_FULL_NATIVE_STREAM_V5",
        "deferred_input_records": deferred,
        "estimated_native_part_bytes": part_bytes,
        "estimated_native_tree_bytes": tree_bytes,
        "estimated_native_tree_nonpart_bytes": native_tree_nonpart,
        "estimated_native_read_passes": NATIVE_PASSES,
        "estimated_native_read_bytes": part_bytes * NATIVE_PASSES,
        "estimated_static_small_input_bytes": classes["static_small_input_bytes"],
        "estimated_deferred_source_bytes": classes["deferred_source_bytes"],
        "estimated_bi4_source_bytes": classes["bi4_source_bytes"],
        "estimated_forcing_source_bytes": classes["forcing_source_bytes"],
        "estimated_observer_process_read_bytes": observer_process_read,
        "estimated_parent_source_binding_bytes": guarded_source_binding,
        "estimated_guarded_input_read_bytes": guarded_input,
        "estimated_input_read_bytes": guarded_input,
        "native_read_accounting": {
            "part_bytes": part_bytes,
            "complete_native_output_tree_bytes": tree_bytes,
            "non_part_tree_bytes": native_tree_nonpart,
            "raw_part_passes": NATIVE_PASSES,
            "raw_part_read_bytes": part_bytes * NATIVE_PASSES,
            "bi4_source_bytes": classes["bi4_source_bytes"],
            "forcing_source_bytes": classes["forcing_source_bytes"],
            "static_small_input_bytes": classes["static_small_input_bytes"],
            "observer_process_read_bytes": observer_process_read,
            "parent_source_binding_bytes": guarded_source_binding,
            "guarded_input_read_bytes": guarded_input,
            "tree_extra_is_not_multiplied_as_native_part_read": True,
            "estimate_status": "PLANNING_FROM_PARENT_SUPPLIED_STAT_SUMS",
            "guarded_input_semantics": "observer Part/static reads plus separately charged parent BI4/forcing source binding; not a claim that the observer reopens BI4/forcing",
        },
        "source_binding": dict(base.get("source_binding", {})),
        "qualification_stage": "stage2_f3_s2_full_native_stream_v5_pending_parent_guard",
    })
    value["source_binding"].update({
        "native_read_passes": NATIVE_PASSES,
        "native_read_estimate": "four passes over actual native Part files only; complete output-tree non-Part bytes and BI4/forcing/static inputs are separate",
        "part_bytes_are_parent_supplied_stat_sum": True,
        "complete_tree_bytes_are_context_only": True,
        "bi4_forcing_static_bytes_separately_accounted": True,
    })
    value["resource_estimate"] = dict(base.get("resource_estimate", {}))
    value["resource_estimate"].update({
        "estimated_native_part_bytes": part_bytes,
        "estimated_native_tree_bytes": tree_bytes,
        "estimated_native_tree_nonpart_bytes": native_tree_nonpart,
        "estimated_native_read_bytes": part_bytes * NATIVE_PASSES,
        "estimated_observer_process_read_bytes": observer_process_read,
        "estimated_parent_source_binding_bytes": guarded_source_binding,
        "estimated_guarded_input_read_bytes": guarded_input,
    })
    value["sha256"] = _canonical(value)
    return value


def self_test() -> dict[str, Any]:
    if ROOT162_TREE_BYTES - ROOT162_PART_BYTES != 34_050_529:
        raise AssertionError("ROOT162 tree/Part separation reference changed")
    if ROOT162_PART_BYTES * NATIVE_PASSES != 26_374_566_064:
        raise AssertionError("ROOT162 four-pass Part estimate changed")
    base = V4_REQUEST.self_test()
    if base.get("status") != "PASS":
        raise AssertionError(base)
    return {
        "status": "PASS",
        "schema": SCHEMA,
        "variant_schema": VARIANT,
        "native_read_passes": NATIVE_PASSES,
        "root162_part_bytes": ROOT162_PART_BYTES,
        "root162_tree_bytes": ROOT162_TREE_BYTES,
        "root162_nonpart_tree_bytes": ROOT162_TREE_BYTES - ROOT162_PART_BYTES,
        "root162_four_pass_part_bytes": ROOT162_PART_BYTES * NATIVE_PASSES,
        "payload_read": False,
        "solver_started": False,
    }


def _write_once(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    # Keep the V4 provenance/contract arguments, with the corrected native
    # accounting names replacing --estimated-native-bytes.  The V4 parser is
    # intentionally not executed here; explicit arguments avoid argv drift.
    parser.add_argument("--solver-request", type=Path)
    parser.add_argument("--terminal-receipt", type=Path)
    parser.add_argument("--terminal-proof", type=Path)
    parser.add_argument("--source-snapshot-proof", type=Path)
    parser.add_argument("--source-snapshot-report", type=Path)
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument("--runparts", type=Path)
    parser.add_argument("--generated-xml", type=Path)
    parser.add_argument("--calibration-contract", type=Path, default=V4_REQUEST.V3_REQUEST.CALIBRATION)
    parser.add_argument("--expected-frame-count", type=int)
    parser.add_argument("--expected-final-time-s", type=float)
    parser.add_argument("--expected-dp-m", type=float)
    parser.add_argument("--expected-initial-fluid-count", type=int)
    parser.add_argument("--final-time-tolerance-s", type=float, default=1.0e-9)
    parser.add_argument("--estimated-part-bytes", type=int)
    parser.add_argument("--estimated-native-tree-bytes", type=int)
    parser.add_argument("--estimated-output-records", type=int)
    parser.add_argument("--estimated-storage-bytes", type=int)
    parser.add_argument("--launch-commit")
    parser.add_argument("--case-id", default="F3_S2_FULL_NATIVE_STREAM_ROOT177_OR_ROOT178_V5")
    parser.add_argument("--attempt-id", default="f3-s2-full-native-stream-root177-or-root178-v5-001")
    parser.add_argument("--output", type=Path, default=HERE.parents[5] / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-full-native-stream-observer-v5-root177-or-root178-001.json")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    required = (
        args.solver_request, args.terminal_receipt, args.terminal_proof, args.source_snapshot_proof,
        args.source_snapshot_report, args.raw_root, args.runparts, args.generated_xml,
        args.expected_frame_count, args.expected_final_time_s, args.expected_dp_m,
        args.expected_initial_fluid_count, args.estimated_part_bytes, args.estimated_native_tree_bytes,
        args.estimated_storage_bytes, args.launch_commit,
    )
    if any(item is None for item in required):
        parser.error("--build-request requires terminal/source paths, frame contract, Part/tree byte estimates, and launch commit")
    try:
        value = build(args)
        _write_once(args.output, value)
    except BaseException as exc:
        print(json.dumps({"status": "FAILED_F3_FULL_NATIVE_STREAM_V5_REQUEST_BUILD", "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": value["status"], "output": str(args.output.expanduser().resolve()), "native_part_read_bytes": value["estimated_native_read_bytes"], "native_read_passes": NATIVE_PASSES, "payload_read": "parent_after_reservation", "solver_started": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
