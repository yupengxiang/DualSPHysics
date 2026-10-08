#!/usr/bin/env python3
"""Bind four F1 observer requests to completed selected-file snapshots.

The terminal solver runs and the four standalone v3 pre-snapshot bundles are
already immutable.  This forward builder is the second half of that chain:
it consumes one completed ``native-source-snapshot.v2`` result and receipt,
copies the selected SHA/stat records into a new expected-source manifest, and
emits one enforcer-v2 observer request.  It never opens, stats, or hashes a
BI4 file.  Consequently a 105 GB dp=.0025 tree is represented by the nine
selected files only; the full tree is never copied or scanned.

The builder deliberately accepts one snapshot at a time.  Four independent
invocations keep each raw-root identity and terminal receipt explicit and
avoid a combined request accidentally pairing frames from different CFL
runs.  The saved-time metadata requests remain the standalone v3 requests;
this script only closes the snapshot -> SHA-bound observer leg.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
STANDALONE = HERE / "stage2_f1_owner_postsolver_requests_standalone_v3.py"
OBSERVER_WORKER = HERE / "stage2_native_physical_observer_v2.py"
ENFORCER_V2 = HERE / "stage2_native_physical_observer_enforcer_v2.py"
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
V8_RUNNER = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
V8_STRICT = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
V8_RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
V2_RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
SCHEMA = "ds02.stage2.f1.owner-snapshot-bound-observer-builder.v1"
SNAPSHOT_SCHEMA = "ds02.stage2.native-source-snapshot.v2"
SNAPSHOT_STATUS = "PASS_SELECTED_NATIVE_SOURCE_HASHED_STABLE"
PART_RE = re.compile(r"^Part_(\d+)\.bi4$")


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load source module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def base_module() -> Any:
    # Kept as a small compatibility hook for callers that imported the first
    # draft.  The final builder below is standalone and does not load the
    # consumed v1/v3 request constructors.
    return None


def f1_template(path: Path) -> dict[str, Any]:
    """Normalize the standalone-v3 F1 request to the canonical template shape.

    The standalone builder calls the solver input ``solver_input_xml`` because
    it distinguishes that copied XML from the original GenCase XML.  The
    canonical constructor uses the neutral ``generated_xml`` key.  Keep the
    original request path and source records unchanged while providing that
    narrow adapter in memory.
    """
    value = load_json(path, "F1 pre-snapshot observer request")
    source = value.get("source_binding")
    if not isinstance(source, dict):
        raise ValueError("F1 observer request lacks source_binding")
    frames = value.get("selected_native_frame_ids")
    raw_root = source.get("raw_root")
    runparts = source.get("runparts", {}).get("path") if isinstance(source.get("runparts"), dict) else None
    generated_xml = source.get("solver_input_xml", {}).get("path") if isinstance(source.get("solver_input_xml"), dict) else None
    deferred = value.get("deferred_input_files")
    if not isinstance(frames, list) or not frames or not isinstance(raw_root, str) or not isinstance(runparts, str) or not isinstance(generated_xml, str) or not isinstance(deferred, list):
        raise ValueError("F1 observer request lacks standalone source bindings")
    raw_root_path = Path(raw_root).expanduser().resolve()
    selected: dict[int, str] = {}
    for item in deferred:
        if not isinstance(item, str):
            continue
        candidate = Path(item).expanduser().resolve()
        match = PART_RE.fullmatch(candidate.name)
        if match is None:
            continue
        frame = int(match.group(1))
        if candidate.parent != raw_root_path or frame in selected:
            raise ValueError("F1 deferred selected frame path is invalid or duplicated")
        selected[frame] = str(candidate)
    if set(selected) != {int(frame) for frame in frames}:
        raise ValueError("F1 deferred selected frame set differs from request")
    return {
        "template_path": str(path.resolve()),
        "template": value,
        "frames": [int(frame) for frame in frames],
        "selected_paths": [selected[int(frame)] for frame in frames],
        "raw_root": str(raw_root_path),
        "runparts": str(Path(runparts).expanduser().resolve()),
        "generated_xml": str(Path(generated_xml).expanduser().resolve()),
        "query_times_s": [float(value) for value in value.get("query_times_s", [])],
        "source": source,
    }


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular non-symlink file: {path}")
    return path


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def sha256(path: Path) -> str:
    digest = __import__("hashlib").sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = regular(path, "static source")
    stat = path.stat()
    return {"path": str(path), "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "sha256": sha256(path)}


def source_dependency_paths(template: dict[str, Any]) -> list[Path]:
    """Collect only the text/source closure named by the pre-observer request."""
    paths = [Path(template["template_path"]), OBSERVER_WORKER, ENFORCER_V2,
             Path(template["runparts"]), Path(template["generated_xml"]),
             V8_RUNNER, V8_STRICT, V8_RUNTIME, V2_RUNTIME, PYTHON]
    source = template["source"]
    for key in (
        "source_gencase_receipt", "solver_receipt", "parent_solver_request",
        "materialization_receipt", "source_generated_xml", "solver_input_xml",
        "runparts", "run_out", "run_csv", "dtall_info", "dt_info",
        "owner_contract", "owner", "physical_binding", "quality_label_split",
        "initial_qa_proof", "support_control_proof", "fine_half_solver_proof",
    ):
        value = source.get(key)
        if isinstance(value, dict) and isinstance(value.get("path"), str):
            paths.append(Path(value["path"]))
    # The source request's decoder closure is explicit in its command/input
    # records; include the current fixed decoder and source below.
    for candidate in (
        Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump"),
        HERE / "../../../../scripts/native/bi4_dump.cpp",
    ):
        paths.append(candidate)
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        path = path.expanduser().resolve()
        if str(path) not in seen:
            seen.add(str(path)); result.append(path)
    return result


def stat_shape(value: Any, label: str) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a stat object")
    required = ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino")
    if set(value) != set(required) or any(not isinstance(value[key], int) for key in required):
        raise ValueError(f"{label} has incomplete stat fields")
    return {key: int(value[key]) for key in required}


def validate_snapshot(pre_request_path: Path, receipt_path: Path, result_path: Path, template: dict[str, Any], base: Any) -> dict[str, Any]:
    receipt = load_json(receipt_path, "snapshot terminal receipt")
    result = load_json(result_path, "snapshot result")
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError("snapshot receipt is not a completed successful v8 CPU receipt")
    output_root = Path(str(receipt.get("output_root", ""))).expanduser().resolve()
    try:
        result_path.resolve().relative_to(output_root)
    except ValueError as exc:
        raise ValueError("snapshot result is outside its terminal receipt output root") from exc
    if result.get("schema") != SNAPSHOT_SCHEMA or result.get("status") != SNAPSHOT_STATUS:
        raise ValueError("snapshot result is not stable native-source snapshot v2")
    scope = result.get("worker_scope", {})
    if scope.get("full_raw_tree_hash") != "NOT_COMPUTED_BY_WORKER" or scope.get("pre_post_stat_consistency") is not True or scope.get("mutation_during_hash") != "REJECTED":
        raise ValueError("snapshot result lacks the v2 pre/post mutation guard")
    entries = result.get("requests")
    if not isinstance(entries, list) or len(entries) != 1:
        raise ValueError("F1 snapshot binder requires exactly one observer entry")
    entry = entries[0]
    observer_record = entry.get("observer_request")
    if not isinstance(observer_record, dict) or str(Path(str(observer_record.get("path", ""))).expanduser().resolve()) != str(pre_request_path.resolve()):
        raise ValueError("snapshot was not produced from the supplied F1 observer request")
    identity = template["template"]
    for key in ("family_id", "sentinel_id", "physical_case_id"):
        expected = identity.get(key, template["source"].get(key))
        if expected is not None and entry.get(key) != expected:
            raise ValueError(f"snapshot identity mismatch for {key}: {entry.get(key)!r} != {expected!r}")
    frames = template["frames"]
    if entry.get("selected_native_frame_ids") != frames:
        raise ValueError("snapshot selected frame IDs differ from the pre-snapshot request")
    raw_root = str(Path(str(entry.get("raw_root", ""))).expanduser().resolve())
    if raw_root != template["raw_root"]:
        raise ValueError("snapshot raw-root differs from the pre-snapshot request")
    selected = entry.get("selected_native_files")
    if not isinstance(selected, list) or len(selected) != len(frames):
        raise ValueError("snapshot does not carry one record for every selected frame")
    by_frame: dict[int, dict[str, Any]] = {}
    for item in selected:
        if not isinstance(item, dict):
            raise ValueError("snapshot selected file record is not an object")
        frame = item.get("frame")
        if not isinstance(frame, int) or frame in by_frame or frame not in frames:
            raise ValueError("snapshot selected frame record is invalid or duplicated")
        path = Path(str(item.get("path", ""))).expanduser().resolve()
        match = PART_RE.fullmatch(path.name)
        if match is None or int(match.group(1)) != frame or str(path.parent) != raw_root:
            raise ValueError(f"snapshot selected path is outside the bound raw root: {path}")
        digest = item.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"snapshot frame {frame} has no content SHA")
        if not isinstance(item.get("bytes"), int) or item["bytes"] <= 0:
            raise ValueError(f"snapshot frame {frame} has invalid byte count")
        before = stat_shape(item.get("stat_before"), f"snapshot frame {frame}.stat_before")
        after = stat_shape(item.get("stat_after"), f"snapshot frame {frame}.stat_after")
        if before != after or before["bytes"] != item["bytes"]:
            raise ValueError(f"snapshot frame {frame} lacks identical pre/post stat")
        by_frame[frame] = {
            "frame": frame,
            "path": str(path),
            "bytes": int(item["bytes"]),
            "sha256": digest,
            "stat_before": before,
            "stat_after": after,
            "stat_consistency": "PASS_PRE_POST_IDENTICAL",
        }
    if sorted(by_frame) != sorted(frames):
        raise ValueError("snapshot frame set is incomplete")
    if not isinstance(entry.get("selected_source_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", entry["selected_source_sha256"]):
        raise ValueError("snapshot lacks selected_source_sha256")
    checked = dict(entry)
    checked["selected_native_files"] = [by_frame[frame] for frame in frames]
    checked["selected_native_bytes"] = sum(item["bytes"] for item in checked["selected_native_files"])
    checked["_snapshot_schema"] = SNAPSHOT_SCHEMA
    checked["_stable_stat_guard"] = True
    checked["_snapshot_receipt_path"] = str(receipt_path.resolve())
    checked["_snapshot_result_path"] = str(result_path.resolve())
    return checked


def deep_forward(value: Any, old_root: str, new_root: str) -> Any:
    if isinstance(value, dict):
        return {key: deep_forward(item, old_root, new_root) for key, item in value.items()}
    if isinstance(value, list):
        return [deep_forward(item, old_root, new_root) for item in value]
    if isinstance(value, str):
        return value.replace(old_root, new_root).replace("CANONICAL_SNAPSHOT_V3", "SNAPSHOT_BOUND_V4").replace("canonical_snapshot_v3", "snapshot-bound-v4")
    return value


def atomic_json(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refuse to overwrite immutable artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build(pre_request_path: Path, snapshot_receipt_path: Path, snapshot_result_path: Path, output_dir: Path) -> dict[str, Any]:
    pre_request_path = regular(pre_request_path, "F1 pre-snapshot observer request")
    template = f1_template(pre_request_path)
    checked = validate_snapshot(pre_request_path, snapshot_receipt_path, snapshot_result_path, template, None)
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"refuse to populate non-empty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    source = template["source"]
    identity = template["template"]
    family = str(identity.get("family_id", source.get("family_id", "F1")))
    sentinel = str(identity.get("sentinel_id", source.get("sentinel_id", "F1-S1")))
    physical_case = str(identity.get("physical_case_id", source.get("physical_case_id", "UNKNOWN")))
    original_case = re.sub(r"[^A-Za-z0-9]+", "_", str(identity.get("case_id", "F1_OWNER"))).strip("_")
    token = f"{original_case}_SNAPSHOT_BOUND_V4"
    attempt_id = f"{token.lower()}-root-forward-001"
    filename = f"{token.lower()}.json"
    request_path = output_dir / filename
    manifest_path = output_dir / f"{token.lower()}_expected_source_manifest_v1.json"
    selected_records = checked["selected_native_files"]
    manifest = {
        "schema": "ds02.stage2.native-observer-source-manifest.v1",
        "snapshot_schema": SNAPSHOT_SCHEMA,
        "observer_request": {"path": str(pre_request_path.resolve()), "bytes": pre_request_path.stat().st_size, "mtime_ns": pre_request_path.stat().st_mtime_ns, "sha256": sha256(pre_request_path)},
        "case_id": identity.get("case_id", "UNKNOWN"), "family_id": family, "sentinel_id": sentinel,
        "physical_case_id": physical_case, "raw_root": template["raw_root"],
        "selected_native_frame_ids": template["frames"],
        "selected_native_files": selected_records,
        "selected_source_sha256": checked["selected_source_sha256"],
        "source_sha_policy": "snapshot v2 SHA; enforcer v2 pre/post complete-stat and SHA check around child decode",
    }
    atomic_json(manifest_path, manifest)

    decoder = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump").resolve()
    decoder_source = (HERE / "../../../../scripts/native/bi4_dump.cpp").resolve()
    static_paths = source_dependency_paths(template) + [
        pre_request_path.resolve(), snapshot_receipt_path.resolve(), snapshot_result_path.resolve(),
        manifest_path.resolve(), Path(__file__).resolve(), STANDALONE.resolve(), decoder, decoder_source,
    ]
    input_files: list[Path] = []
    seen: set[str] = set()
    for path in static_paths:
        path = path.expanduser().resolve()
        if str(path) in seen:
            continue
        regular(path, "F1 snapshot-bound static input")
        seen.add(str(path)); input_files.append(path)
    command = [
        str(PYTHON), str(ENFORCER_V2.resolve()), "--observer-worker", str(OBSERVER_WORKER.resolve()),
        "--expected-source-manifest", str(manifest_path.resolve()), "--raw-root", template["raw_root"],
        "--runparts", template["runparts"], "--generated-xml", template["generated_xml"],
        "--decoder", str(decoder), "--decoder-source", str(decoder_source),
        "--output", f"{{attempt_root}}/observer/{filename}", "--scratch-root", "{attempt_root}/scratch/bi4_decode",
        "--cwd", str(Path(__file__).resolve().parents[5]), "--expected-frame-count", str(source["frame_count"]),
        "--expected-final-time-s", str(source["last_saved_time_s"]), "--final-time-tolerance-s", "1e-12",
        "--frames", *[str(frame) for frame in template["frames"]], "--query-times", *[str(time_s) for time_s in template["query_times_s"]],
    ]
    selected_bytes = sum(int(item["bytes"]) for item in selected_records)
    output_root = DATA_ROOT / "families" / family / token / attempt_id
    if output_root.exists():
        raise FileExistsError(f"observer output root already exists: {output_root}")
    request: dict[str, Any] = {
        "schema": "ds02.request.v1", "kind": "cpu", "cpu_task_kind": "native_observer",
        "family_id": family, "sentinel_id": sentinel, "physical_case_id": physical_case,
        "case_id": token, "attempt_id": attempt_id, "command": command,
        "cwd": str(Path(__file__).resolve().parents[5]), "worktree_root": str(Path(__file__).resolve().parents[5]),
        "input_files": [str(path) for path in input_files],
        "input_hashes": {str(path): sha256(path) for path in input_files},
        "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 1800,
        "estimated_native_read_bytes": selected_bytes, "estimated_storage_bytes": max(1 << 30, 2 * selected_bytes + (256 << 20)),
        "estimated_peak_memory_bytes": 1 << 30,
        "output": {"path": f"{{attempt_root}}/observer/{filename}", "atomic": True, "refuse_overwrite": True, "scratch_cleanup": "worker-owned temporary decoder tree"},
        "execution_allowed": True, "launch_disabled": False, "solver_started": False, "hdf5_read": False, "bi4_decode": False,
        "deferred_input_files": [template["raw_root"], *template["selected_paths"]],
        "deferred_input_file_count": len(template["selected_paths"]),
        "deferred_hash_policy": {
            "snapshot_schema": SNAPSHOT_SCHEMA, "snapshot_pre_post_stat_guard": True,
            "snapshot_mutation_during_hash": "REJECTED", "snapshot_terminal_sha_source": "selected SHA records below",
            "builder_bi4_read": False, "builder_bi4_hash": False, "full_raw_tree_hash": "NOT_COMPUTED_BY_BUILDER",
            "observer_runtime_scope": "selected frames only; no full-tree scan", "parent_guard_pre_decode_sha_and_stat": "REQUIRED",
            "worker_post_decode_sha_and_stat": "REQUIRED", "source_mutation_during_decode": "FAIL_IF_PRE_POST_DIFFERS",
        },
        "source_snapshot_binding": {
            "snapshot_schema": SNAPSHOT_SCHEMA, "snapshot_receipt": record(snapshot_receipt_path),
            "snapshot_result": record(snapshot_result_path), "expected_source_manifest": record(manifest_path),
            "snapshot_result_entry": {"observer_request": checked["observer_request"], "selected_source_sha256": checked["selected_source_sha256"], "selected_native_bytes": checked["selected_native_bytes"], "selected_native_files": selected_records},
            "source_sha_policy": "selected SHA/stat records consumed from completed snapshot v2; enforcer v2 rechecks pre/post around child decode",
        },
        "source_binding": {
            "pre_snapshot_observer_request": record(pre_request_path), "raw_root": template["raw_root"],
            "runparts": record(Path(template["runparts"])), "generated_xml": record(Path(template["generated_xml"])),
            "selected_native_frame_ids": template["frames"], "query_times_s": template["query_times_s"],
            "last_saved_time_s": source["last_saved_time_s"], "physical_case_id": physical_case,
            "source_control": "terminal F1 solver input unchanged; selected native payload deferred",
            "continuous_owner_mass_kg": 40.2, "particle_sample_mass_is_separate_diagnostic": True,
        },
        "builder_closure": {
            "schema": SCHEMA, "standalone_pre_snapshot_builder": str(STANDALONE.resolve()),
            "enforcer": {"path": str(ENFORCER_V2.resolve()), "schema": "ds02.stage2.native-physical-observer-enforcer.v2"},
            "native_sha_source": "completed native-source-snapshot.v2 result only", "full_tree_copy_or_scan": False,
            "selected_frame_count": len(template["frames"]),
        },
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(V8_RUNNER.resolve()), "strict_guard": str(V8_STRICT.resolve()), "runtime": str(V8_RUNTIME.resolve()), "cpu_parent_binding": "required", "gpu": "none", "solver_launch": "forbidden", "hdf5_read": "forbidden", "parent_v8_review_required": True},
        "qualification_stage": "stage2_f1_owner_selected_native_snapshot_bound_enforcer_v2_pending_parent_v8_cpu_guard",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    atomic_json(request_path, request)
    return {"status": "PASS_SNAPSHOT_BOUND_OBSERVER_REQUEST", "request": str(request_path), "manifest": str(manifest_path), "selected_frames": template["frames"], "selected_source_sha256": checked["selected_source_sha256"], "selected_native_bytes": selected_bytes, "bi4_read": False}


def manufactured_self_test() -> dict[str, Any]:
    # Exercise the complete snapshot identity/frame/stat contract with tiny
    # metadata fixtures; no native path is opened.
    stat = {"bytes": 4, "mtime_ns": 1, "ctime_ns": 2, "st_dev": 3, "st_ino": 4}
    with tempfile.TemporaryDirectory(prefix="ds02-f1-snapshot-bind-selftest-") as root_text:
        root = Path(root_text); output_root = root / "snapshot-output"; output_root.mkdir()
        pre_path = root / "observer.json"
        pre = {"schema": "ds02.request.v1", "case_id": "SELF_CASE", "family_id": "F1", "sentinel_id": "F1-S1", "physical_case_id": "SELF", "selected_native_frame_ids": [0, 1], "query_times_s": [0.0], "deferred_input_files": ["/raw", "/raw/Part_0000.bi4", "/raw/Part_0001.bi4"], "source_binding": {"raw_root": "/raw", "runparts": {"path": "/meta/RunPARTs.csv"}, "solver_input_xml": {"path": "/meta/case.xml"}}}
        pre_path.write_text(json.dumps(pre))
        entries = [{"observer_request": {"path": str(pre_path)}, "family_id": "F1", "sentinel_id": "F1-S1", "physical_case_id": "SELF", "selected_native_frame_ids": [0, 1], "raw_root": "/raw", "selected_source_sha256": "a" * 64, "selected_native_bytes": 8, "selected_native_files": [{"frame": i, "path": f"/raw/Part_{i:04d}.bi4", "bytes": 4, "sha256": f"{i + 1:064x}", "stat_before": stat, "stat_after": stat} for i in range(2)]}]
        result_path = output_root / "native_selected_source_snapshot_v2.json"
        result_path.write_text(json.dumps({"schema": SNAPSHOT_SCHEMA, "status": SNAPSHOT_STATUS, "worker_scope": {"full_raw_tree_hash": "NOT_COMPUTED_BY_WORKER", "pre_post_stat_consistency": True, "mutation_during_hash": "REJECTED"}, "requests": entries}))
        receipt_path = output_root / "execution-receipt.json"
        receipt_path.write_text(json.dumps({"schema": "ds02.execution-receipt.v1", "status": "completed", "returncode": 0, "output_root": str(output_root)}))
        template = f1_template(pre_path)
        checked = validate_snapshot(pre_path, receipt_path, result_path, template, None)
        assert checked["selected_source_sha256"] == "a" * 64 and len(checked["selected_native_files"]) == 2
        broken = json.loads(result_path.read_text()); broken["requests"][0]["selected_native_files"].pop()
        result_path.write_text(json.dumps(broken))
        try:
            validate_snapshot(pre_path, receipt_path, result_path, template, None)
        except ValueError:
            missing_rejected = True
        else:
            missing_rejected = False
        assert missing_rejected
    return {"status": "PASS", "snapshot_v2_identity_and_stat_checked": True, "missing_selected_record_rejected": True, "bi4_read": False, "solver_launch": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pre-observer-request", type=Path)
    parser.add_argument("--snapshot-receipt", type=Path)
    parser.add_argument("--snapshot-result", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(manufactured_self_test(), indent=2))
        return 0
    if any(value is None for value in (args.pre_observer_request, args.snapshot_receipt, args.snapshot_result, args.output_dir)):
        parser.error("--pre-observer-request, --snapshot-receipt, --snapshot-result, and --output-dir are required")
    assert args.pre_observer_request and args.snapshot_receipt and args.snapshot_result and args.output_dir
    result = build(args.pre_observer_request, args.snapshot_receipt, args.snapshot_result, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
