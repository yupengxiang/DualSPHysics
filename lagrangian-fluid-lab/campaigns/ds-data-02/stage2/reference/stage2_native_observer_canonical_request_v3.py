#!/usr/bin/env python3
"""Build v6 observer requests bound to a completed native source snapshot.

The source snapshot is the provenance boundary.  This forward builder accepts
the original v1 selected-file result and the v2 result that also proves
pre/post ``stat`` stability while hashing.  For v2 every selected record must
carry identical size, mtime, ctime, inode, and device values before and after
the stream; a missing or changed record is rejected.  The builder verifies the
four template identities and 36 recorded BI4 SHA entries, then creates four
new CPU requests for the existing native observer v2.  It never opens, stats,
or hashes a BI4 file.  Selected BI4 paths remain deferred runtime inputs; the
observer's actual selected-frame output can be checked against the snapshot
SHA list after the parent guard dispatches the request.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any


SCHEMA = "ds02.stage2.native-observer-canonical-request.v3"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
REQUEST_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
OBSERVER_WORKER = REFERENCE / "stage2_native_physical_observer_v2.py"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
DECODER_SOURCE = REPO / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp"
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
V6_RUNNER = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v6.py"
V6_STRICT = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v6.py"
V6_RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py"
V2_RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
SNAPSHOT_RESULT_DEFAULT = Path("native_selected_source_snapshot_v1.json")
PART_RE = re.compile(r"^Part_(\d+)\.bi4$")

TEMPLATE_PATHS = (
    REQUEST_ROOT / "stage2-f1-s1-observer-v1/f1_s1_dp010_same_cfl_selected_native_observer_v1.json",
    REQUEST_ROOT / "stage2-f1-s1-observer-v1/f1_s1_dp010_half_cfl_selected_native_observer_v1.json",
    REQUEST_ROOT / "stage2-f1-s2-coarse-observer-v3/f1_s2_coarse_dp0225_selected_native_observer_v3.json",
    REQUEST_ROOT / "stage2-f1-s2-fine-observer-v2/f1_s2_fine_dp017_selected_native_observer_v2.json",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular_file(path: Path, label: str) -> Path:
    path = path.expanduser()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular non-symlink file: {path}")
    return path.resolve()


def record(path: Path) -> dict[str, Any]:
    path = regular_file(path, "static input")
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256(path)}


def atomic_json(path: Path, value: Any) -> None:
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


def load_json(path: Path, label: str) -> dict[str, Any]:
    path = regular_file(path, label)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object: {path}")
    return value


def selected_template_metadata(path: Path) -> dict[str, Any]:
    value = load_json(path, "observer template")
    if value.get("schema") != REQUEST_SCHEMA:
        raise ValueError(f"observer template has wrong request schema: {path}")
    source = value.get("source_binding")
    if not isinstance(source, dict):
        raise ValueError(f"observer template lacks source_binding: {path}")
    frames = value.get("selected_native_frame_ids")
    if not isinstance(frames, list) or not frames or len(set(frames)) != len(frames):
        raise ValueError(f"observer template has invalid selected frame list: {path}")
    for frame in frames:
        if not isinstance(frame, int) or frame < 0:
            raise ValueError(f"observer template has invalid frame: {path}")
    raw_root = source.get("raw_root")
    if not isinstance(raw_root, str) or not raw_root:
        raise ValueError(f"observer template lacks raw-root: {path}")
    raw_root_path = Path(raw_root).expanduser().resolve()
    runparts = source.get("runparts", {}).get("path")
    generated_xml = source.get("generated_xml", {}).get("path")
    if not isinstance(runparts, str) or not isinstance(generated_xml, str):
        raise ValueError(f"observer template lacks RunPARTs/generated XML binding: {path}")
    query_times = value.get("query_times_s")
    if not isinstance(query_times, list) or not query_times:
        query_times = [float(key) for key in source.get("query_brackets", {})]
    if not query_times or any(not isinstance(time_s, (int, float)) for time_s in query_times):
        raise ValueError(f"observer template lacks finite query times: {path}")
    deferred = value.get("deferred_input_files")
    if not isinstance(deferred, list):
        raise ValueError(f"observer template lacks deferred selected inputs: {path}")
    selected_paths: dict[int, str] = {}
    for item in deferred:
        if not isinstance(item, str):
            raise ValueError(f"observer template deferred inputs must be strings: {path}")
        candidate = Path(item).expanduser().resolve()
        match = PART_RE.fullmatch(candidate.name)
        if match is None:
            continue
        frame = int(match.group(1))
        if candidate.parent != raw_root_path:
            raise ValueError(f"observer template selected BI4 is outside raw root: {path}")
        if frame in selected_paths:
            raise ValueError(f"observer template repeats selected frame: {path} frame {frame}")
        selected_paths[frame] = str(candidate)
    if set(selected_paths) != set(frames):
        raise ValueError(f"observer template deferred frames differ from selected frame list: {path}")
    return {
        "template_path": str(path.resolve()),
        "template": value,
        "frames": [int(frame) for frame in frames],
        "selected_paths": [selected_paths[int(frame)] for frame in frames],
        "raw_root": str(raw_root_path),
        "runparts": str(Path(runparts).expanduser().resolve()),
        "generated_xml": str(Path(generated_xml).expanduser().resolve()),
        "query_times_s": [float(time_s) for time_s in query_times],
        "source": source,
    }


def validate_snapshot_pair(receipt: dict[str, Any], result: dict[str, Any],
                           receipt_path: Path, result_path: Path,
                           templates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if receipt.get("schema") != "ds02.execution-receipt.v1":
        raise ValueError("snapshot terminal receipt has wrong schema")
    if receipt.get("status") != "completed" or receipt.get("returncode", 0) != 0:
        raise ValueError(f"snapshot receipt is not a completed successful terminal: {receipt_path}")
    snapshot_schema = result.get("schema")
    if snapshot_schema == "ds02.stage2.native-source-snapshot.v1":
        if result.get("status") != "PASS_SELECTED_NATIVE_SOURCE_HASHED":
            raise ValueError("snapshot v1 result is not a successful selected-source hash result")
        stable_stat_guard = False
    elif snapshot_schema == "ds02.stage2.native-source-snapshot.v2":
        if result.get("status") != "PASS_SELECTED_NATIVE_SOURCE_HASHED_STABLE":
            raise ValueError("snapshot v2 result is not a successful stable selected-source hash result")
        scope = result.get("worker_scope", {})
        if scope.get("pre_post_stat_consistency") is not True or scope.get("mutation_during_hash") != "REJECTED":
            raise ValueError("snapshot v2 lacks its pre/post stat mutation guard")
        stable_stat_guard = True
    else:
        raise ValueError("snapshot result has wrong schema")
    scope = result.get("worker_scope", {})
    if scope.get("selected_file_count") != 36 or scope.get("full_raw_tree_hash") != "NOT_COMPUTED_BY_WORKER":
        raise ValueError("snapshot result does not prove the exact 36-file bounded scope")
    entries = result.get("requests")
    if not isinstance(entries, list) or len(entries) != len(templates):
        raise ValueError("snapshot result must contain one entry for each observer template")
    by_template = {str(Path(str(entry.get("observer_request", {}).get("path", ""))).resolve()): entry for entry in entries}
    if len(by_template) != len(entries):
        raise ValueError("snapshot result repeats an observer request")
    all_files: list[dict[str, Any]] = []
    output_root = Path(str(receipt.get("output_root", result_path.parent))).resolve()
    try:
        result_path.resolve().relative_to(output_root)
    except ValueError as exc:
        raise ValueError("snapshot result is outside terminal receipt output root") from exc
    for template in templates:
        entry = by_template.get(template["template_path"])
        if entry is None:
            raise ValueError(f"snapshot result has no entry for template: {template['template_path']}")
        selected = entry.get("selected_native_files")
        if not isinstance(selected, list) or len(selected) != len(template["frames"]):
            raise ValueError(f"snapshot entry has wrong selected frame count: {template['template_path']}")
        ordered = sorted(selected, key=lambda item: int(item.get("frame", -1)))
        frames = [int(item.get("frame", -1)) for item in ordered]
        if frames != sorted(template["frames"]):
            raise ValueError(f"snapshot frames differ from template: {template['template_path']}")
        if str(entry.get("raw_root")) != template["raw_root"]:
            raise ValueError(f"snapshot raw-root differs from template: {template['template_path']}")
        for item in selected:
            path = str(Path(str(item.get("path"))).resolve())
            if path not in template["selected_paths"] or PART_RE.fullmatch(Path(path).name) is None:
                raise ValueError(f"snapshot selected path differs from template: {path}")
            digest = item.get("sha256")
            if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise ValueError("snapshot selected file has no valid content SHA")
            if not isinstance(item.get("bytes"), int) or item["bytes"] <= 0:
                raise ValueError("snapshot selected file has invalid byte count")
            normalized = {"frame": int(item["frame"]), "path": path,
                          "bytes": item["bytes"], "sha256": digest}
            if stable_stat_guard:
                before = item.get("stat_before")
                after = item.get("stat_after")
                if not isinstance(before, dict) or not isinstance(after, dict) or before != after:
                    raise ValueError(f"snapshot v2 selected file lacks identical pre/post stat: {path}")
                required_stat_keys = {"bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"}
                if set(before) != required_stat_keys or any(not isinstance(before[key], int) for key in required_stat_keys):
                    raise ValueError(f"snapshot v2 selected file has incomplete stat record: {path}")
                if before["bytes"] != item["bytes"]:
                    raise ValueError(f"snapshot v2 stat byte count differs from hash byte count: {path}")
                normalized["stat_before"] = before
                normalized["stat_after"] = after
                normalized["stat_consistency"] = "PASS_PRE_POST_IDENTICAL"
            all_files.append(normalized)
        if not isinstance(entry.get("selected_source_sha256"), str):
            raise ValueError("snapshot entry lacks selected_source_sha256")
    if len({item["path"] for item in all_files}) != 36:
        raise ValueError("snapshot selected native file list is not globally unique")
    for entry in entries:
        entry["_snapshot_schema"] = snapshot_schema
        entry["_stable_stat_guard"] = stable_stat_guard
    return entries


def source_dependency_paths(template: dict[str, Any]) -> list[Path]:
    source = template["source"]
    paths = [Path(template["template_path"]), OBSERVER_WORKER, DECODER, DECODER_SOURCE,
             Path(template["runparts"]), Path(template["generated_xml"])]
    for key in ("source_gencase_receipt", "solver_receipt", "solver_attempt", "terminal_audit"):
        value = source.get(key)
        if isinstance(value, dict) and isinstance(value.get("path"), str):
            paths.append(Path(value["path"]))
    return paths


def make_request(template: dict[str, Any], snapshot_entry: dict[str, Any],
                 receipt_path: Path, result_path: Path, builder_path: Path,
                 request_dir: Path) -> tuple[dict[str, Any], Path]:
    template_value = template["template"]
    source = template["source"]
    sentinel = str(template_value.get("sentinel_id", source.get("sentinel_id", "UNKNOWN")))
    family = str(template_value.get("family_id", source.get("family_id", "UNKNOWN")))
    original_case = str(template_value.get("case_id", "OBSERVER"))
    token = re.sub(r"[^A-Za-z0-9]+", "_", original_case).strip("_")
    case_id = f"{token}_CANONICAL_SNAPSHOT_V3"
    attempt_id = f"{token.lower()}-canonical-snapshot-v3-parent-001"
    filename = f"{token.lower()}_canonical_snapshot_v3.json"
    request_path = request_dir / filename
    if request_path.exists():
        raise FileExistsError(request_path)
    snapshot_files = [item for item in snapshot_entry["selected_native_files"]]
    expected_by_path = {str(Path(str(item["path"])).resolve()): item for item in snapshot_files}
    selected_records = []
    for frame, path in zip(template["frames"], template["selected_paths"]):
        source_record = expected_by_path[path]
        selected_record = {"frame": int(frame), "path": path, "bytes": source_record["bytes"],
                           "sha256": source_record["sha256"]}
        if snapshot_entry.get("_stable_stat_guard"):
            selected_record.update({"stat_before": source_record["stat_before"],
                                    "stat_after": source_record["stat_after"],
                                    "stat_consistency": "PASS_PRE_POST_IDENTICAL"})
        selected_records.append(selected_record)
    static_paths = [builder_path.resolve(), receipt_path.resolve(), result_path.resolve(),
                    OBSERVER_WORKER.resolve(), DECODER.resolve(), DECODER_SOURCE.resolve(),
                    V6_RUNNER.resolve(), V6_STRICT.resolve(), V6_RUNTIME.resolve(), V2_RUNTIME.resolve(),
                    PYTHON.resolve(), Path(template["runparts"]).resolve(), Path(template["generated_xml"]).resolve()]
    static_paths.extend(path.resolve() for path in source_dependency_paths(template))
    input_files: list[Path] = []
    seen: set[str] = set()
    for path in static_paths:
        if str(path) in seen:
            continue
        if not path.is_file():
            raise FileNotFoundError(f"canonical observer static dependency missing: {path}")
        seen.add(str(path)); input_files.append(path)
    command = [str(PYTHON), str(OBSERVER_WORKER),
               "--raw-root", template["raw_root"], "--runparts", template["runparts"],
               "--generated-xml", template["generated_xml"], "--decoder", str(DECODER),
               "--decoder-source", str(DECODER_SOURCE),
               "--output", f"{{attempt_root}}/observer/{filename}",
               "--scratch-root", "{attempt_root}/scratch/bi4_decode",
               "--expected-frame-count", str(source["frame_count"]),
               "--expected-final-time-s", str(source["last_saved_time_s"]),
               "--final-time-tolerance-s", "1e-12", "--frames", *[str(frame) for frame in template["frames"]],
               "--query-times", *[str(time_s) for time_s in template["query_times_s"]]]
    output_root = DATA_ROOT / "families" / family / case_id / attempt_id
    if output_root.exists():
        raise FileExistsError(output_root)
    selected_bytes = sum(item["bytes"] for item in selected_records)
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": family,
        "sentinel_id": sentinel,
        "physical_case_id": template_value.get("physical_case_id", source.get("physical_case_id", "UNKNOWN")),
        "case_id": case_id,
        "attempt_id": attempt_id,
        "command": command,
        "cwd": str(REPO),
        "worktree_root": str(REPO),
        "input_files": [str(path) for path in input_files],
        "input_hashes": {str(path): sha256(path) for path in input_files},
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1800,
        "estimated_native_read_bytes": selected_bytes,
        "estimated_storage_bytes": 1024 * 1024 * 1024,
        "estimated_peak_memory_bytes": 1024 * 1024 * 1024,
        "output": {"atomic": True, "refuse_overwrite": True, "path": f"{{attempt_root}}/observer/{filename}",
                   "scratch_cleanup": "worker-owned temporary decoder tree"},
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "hdf5_read": False,
        "deferred_input_files": [template["raw_root"], *template["selected_paths"]],
        "deferred_input_file_count": len(template["selected_paths"]),
        "deferred_hash_policy": {
            "snapshot_terminal_sha_source": "selected native SHA records below",
            "snapshot_pre_post_stat_guard": bool(snapshot_entry.get("_stable_stat_guard")),
            "snapshot_mutation_during_hash": "REJECTED" if snapshot_entry.get("_stable_stat_guard") else "NOT_AVAILABLE_IN_V1",
            "builder_bi4_read": False,
            "builder_bi4_hash": False,
            "full_raw_tree_hash": "NOT_COMPUTED_BY_BUILDER",
            "observer_runtime_scope": "selected frames only; actual output source records must match snapshot SHA list",
            "hdf5_read": False,
            "particle_field_interpolation": "NOT_PERFORMED",
        },
        "source_snapshot_binding": {
            "snapshot_schema": snapshot_entry.get("_snapshot_schema", "ds02.stage2.native-source-snapshot.v1"),
            "pre_post_stat_guard": bool(snapshot_entry.get("_stable_stat_guard")),
            "snapshot_receipt": record(receipt_path),
            "snapshot_result": record(result_path),
            "snapshot_result_entry": {
                "observer_request": snapshot_entry["observer_request"],
                "selected_source_sha256": snapshot_entry["selected_source_sha256"],
                "selected_native_bytes": snapshot_entry["selected_native_bytes"],
                "selected_native_files": selected_records,
            },
            "source_sha_validation": "post-observer output source.selected_part_records must equal these records; builder did not reread BI4",
        },
        "source_binding": {
            "template_request": record(Path(template["template_path"])),
            "raw_root": template["raw_root"],
            "runparts": record(Path(template["runparts"])),
            "generated_xml": record(Path(template["generated_xml"])),
            "selected_native_frame_ids": template["frames"],
            "query_times_s": template["query_times_s"],
            "last_saved_time_s": source["last_saved_time_s"],
            "physical_case_id": template_value.get("physical_case_id", source.get("physical_case_id", "UNKNOWN")),
            "source_control": "inherited exact template source; no geometry/control mutation",
        },
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(V6_RUNNER),
            "strict_guard": str(V6_STRICT),
            "runtime": str(V6_RUNTIME),
            "cpu_parent_binding": "required",
            "gpu": "none",
            "solver_launch": "forbidden",
            "hdf5_read": "forbidden",
            "launch_disabled": False,
            "parent_v6_review_required": True,
        },
        "qualification_stage": "stage2_canonical_selected_native_observer_v3_pending_parent_v6_dispatch",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(request_path, request)
    return request, request_path


def build(snapshot_receipt_path: Path, snapshot_result_path: Path, output_dir: Path) -> dict[str, Any]:
    receipt_path = regular_file(snapshot_receipt_path, "snapshot terminal receipt")
    result_path = regular_file(snapshot_result_path, "snapshot terminal result")
    receipt = load_json(receipt_path, "snapshot terminal receipt")
    result = load_json(result_path, "snapshot terminal result")
    templates = [selected_template_metadata(path) for path in TEMPLATE_PATHS]
    entries = validate_snapshot_pair(receipt, result, receipt_path, result_path, templates)
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"refuse to populate non-empty canonical request directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    requests: list[dict[str, Any]] = []
    paths: list[str] = []
    for template, entry in zip(templates, entries):
        request, path = make_request(template, entry, receipt_path, result_path, Path(__file__).resolve(), output_dir)
        requests.append(request); paths.append(str(path.resolve()))
    manifest = {
        "schema": SCHEMA,
        "status": "PREPARED_CANONICAL_REQUESTS_SNAPSHOT_BOUND",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "snapshot_receipt": record(receipt_path),
        "snapshot_result": record(result_path),
        "template_count": len(templates),
        "selected_native_file_count": 36,
        "builder_scope": {"bi4_read": False, "bi4_hash": False, "hdf5_read": False,
                           "decoder_launch": False, "source_sha_consumed_from_snapshot_result": True,
                           "pre_post_stat_guard_consumed": any(entry.get("_stable_stat_guard") for entry in entries)},
        "request_paths": paths,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(output_dir / "canonical_observer_requests_v2_manifest.json", manifest)
    return manifest


def manufactured_self_test() -> dict[str, Any]:
    templates: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    for index in range(4):
        template_path = f"/template/{index}.json"
        raw_root = f"/raw/{index}"
        frames = list(range(9))
        paths = [f"{raw_root}/Part_{frame:04d}.bi4" for frame in frames]
        template = {"template_path": template_path, "frames": frames, "selected_paths": paths,
                    "raw_root": raw_root, "runparts": "/meta/RunPARTs.csv",
                    "generated_xml": "/meta/case.xml", "query_times_s": [0.0],
                    "source": {"frame_count": 2, "last_saved_time_s": 1.0},
                    "template": {"case_id": f"CASE{index}", "family_id": "F1", "sentinel_id": f"F1-S{index}",
                                 "physical_case_id": "SELF"}}
        templates.append(template)
        entries.append({"observer_request": {"path": template_path}, "raw_root": raw_root,
                        "selected_native_files": [{"frame": frame, "path": path, "bytes": 4, "sha256": f"{index * 9 + frame:064x}"}
                                                   for frame, path in zip(frames, paths)],
                        "selected_source_sha256": f"{index + 10:064x}", "selected_native_bytes": 36})
    receipt = {"schema": "ds02.execution-receipt.v1", "status": "completed", "returncode": 0,
               "output_root": "/snapshot/out"}
    result = {"schema": "ds02.stage2.native-source-snapshot.v1", "status": "PASS_SELECTED_NATIVE_SOURCE_HASHED",
              "worker_scope": {"selected_file_count": 36, "full_raw_tree_hash": "NOT_COMPUTED_BY_WORKER"},
              "requests": entries}
    checked = validate_snapshot_pair(receipt, result, Path("/snapshot/receipt.json"), Path("/snapshot/out/result.json"), templates)
    assert len(checked) == 4
    stable_result = json.loads(json.dumps(result))
    stable_result["schema"] = "ds02.stage2.native-source-snapshot.v2"
    stable_result["status"] = "PASS_SELECTED_NATIVE_SOURCE_HASHED_STABLE"
    stable_result["worker_scope"]["pre_post_stat_consistency"] = True
    stable_result["worker_scope"]["mutation_during_hash"] = "REJECTED"
    stable_stat = {"bytes": 4, "mtime_ns": 1, "ctime_ns": 2, "st_dev": 3, "st_ino": 4}
    for entry in stable_result["requests"]:
        for item in entry["selected_native_files"]:
            item["stat_before"] = dict(stable_stat)
            item["stat_after"] = dict(stable_stat)
            item["stat_consistency"] = "PASS_PRE_POST_IDENTICAL"
    stable_checked = validate_snapshot_pair(receipt, stable_result, Path("/snapshot/receipt.json"), Path("/snapshot/out/stable-result.json"), templates)
    assert len(stable_checked) == 4 and all(entry["_stable_stat_guard"] for entry in stable_checked)
    changed_result = json.loads(json.dumps(stable_result))
    changed_result["requests"][0]["selected_native_files"][0]["stat_after"]["bytes"] = 5
    try:
        validate_snapshot_pair(receipt, changed_result, Path("/snapshot/receipt.json"), Path("/snapshot/out/changed-result.json"), templates)
    except ValueError:
        changed_stat_rejected = True
    else:
        changed_stat_rejected = False
    assert changed_stat_rejected
    duplicate = json.loads(json.dumps(result)); duplicate["requests"][1]["selected_native_files"][0]["path"] = entries[0]["selected_native_files"][0]["path"]
    try:
        validate_snapshot_pair(receipt, duplicate, Path("/snapshot/receipt.json"), Path("/snapshot/out/result.json"), templates)
    except ValueError:
        duplicate_rejected = True
    else:
        duplicate_rejected = False
    assert duplicate_rejected
    return {"status": "PASS", "four_template_entries_checked": len(checked), "stable_v2_checked": len(stable_checked),
            "changed_stat_rejected": changed_stat_rejected, "duplicate_rejected": True,
            "bi4_read": False, "bi4_hash": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-receipt", type=Path)
    parser.add_argument("--snapshot-result", type=Path)
    parser.add_argument("--output-dir", type=Path, default=REQUEST_ROOT / "stage2-native-observer-canonical-v2")
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
