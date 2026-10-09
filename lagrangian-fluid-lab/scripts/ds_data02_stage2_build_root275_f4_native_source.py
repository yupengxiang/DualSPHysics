#!/usr/bin/env python3
"""Build the source-only ROOT275 F4 native-extraction contract.

ROOT296 and ROOT297 contain immutable eight-case F4 lifecycle source groups.
The original-118 cases still classified as ``CAUSE_NOT_LOCATED`` after the
ROOT280 source preparation are seven cases split across those two groups.
This builder creates an exact seven-case lifecycle subset and passes it to the
generic native extractor in ``WAITING_FOR_LIFECYCLE_TERMINAL_PROOF`` mode.

The command only opens bounded JSON/source files and records statistics for
deferred payloads.  It does not open H5, JSONL, BI4/OBI4, PartOut, or
RunPARTs content, and it never submits a parent job.  ROOT must rebind the
request to the latest actual lifecycle registry and provide a completed typed
proof before native extraction is allowed.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
ORIGINAL_PRIMARY = Path("/home/jade/Projects/DualSPHysics")
STAGE2 = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
QUEUE = STAGE2 / "requests/root282-root307-lifecycle-source-queue-001"
CURRENT = STAGE2 / "CURRENT336.json"
INVENTORY = STAGE2 / "checkpoints/HISTORICAL118_NATIVE_TYPED_SOURCE_INVENTORY_AFTER_ROOT193_V1.json"
OVERLAY = STAGE2 / "checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT268_ACTUAL_OVERLAY_V10.json"
ROOT280_REQUEST = STAGE2 / "requests/root280-f4-lifecycle-prepared-001/root280-request.json"
ROOT280_SELECTION = STAGE2 / "requests/root280-f4-lifecycle-prepared-001/root280-selection-manifest.json"
TYPED_WORKER = PRIMARY / "lagrangian-fluid-lab/scripts/ds_data02_stage2_typed_lifecycle_batch_worker_v1.py"
RUNTIME_V8 = PRIMARY / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
DISPATCH_V8 = PRIMARY / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT_V8 = PRIMARY / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
VENV = ORIGINAL_PRIMARY / "lagrangian-fluid-lab/.venv/bin/python"
CONFIG = ORIGINAL_PRIMARY / "lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DsphConfig.xml"

ROOTS = {
    "ROOT296": QUEUE / "root296-f4-lifecycle-prepared-001",
    "ROOT297": QUEUE / "root297-f4-lifecycle-prepared-001",
}

TARGET_CASES = (
    "F4_DROP_gap0p20000_xoffm0p08000_yoff0p04000_uz0p40000",
    "F4_DROP_gap0p20000_xoffm0p08000_yoffm0p04000_uz0p40000",
    "F4_DROP_gap0p25000_xoff0p08000_yoff0p04000_uz0p40000",
    "F4_DROP_gap0p26000_xoff0p08000_yoff0p04000_uz0p40000",
    "F4_DROP_gap0p26000_xoff0p08000_yoffm0p04000_uz0p40000",
    "F4_DROP_gap0p26000_xoff0p08000_yoffm0p04000_uz0p60000",
    "F4_DROP_gap0p26000_xoffm0p08000_yoffm0p04000_uz0p60000",
)

ROOT280_CASES = (
    "F4_DROP_gap0p20000_xoff0p08000_yoff0p04000_uz0p60000",
    "F4_DROP_gap0p20000_xoff0p08000_yoffm0p04000_uz0p40000",
    "F4_DROP_gap0p22000_xoffm0p08000_yoffm0p04000_uz0p60000",
    "F4_DROP_gap0p24000_xoffm0p08000_yoff0p04000_uz0p60000",
)

CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
INVENTORY_SHA = "3d274db71d01f680b9997cc364298f9974a2cb09978acfb81f9a152622e75a00"
OVERLAY_SHA = "72683cdf4b96c334b6f6d6f2df668c9c15f30323b39fcf3473d230c5475e1224"
REQUEST_SCHEMA = "ds02.request.v1"
BATCH_SCHEMA = "ds02.stage2.typed-lifecycle-batch.v1"
SUBSET_SCHEMA = "ds02.stage2.typed-lifecycle-root275-subset.v1"
MAX_SMALL_BYTES = 10 * 1024 * 1024
PAYLOAD_SUFFIXES = {".h5", ".hdf5", ".bi4", ".obi4", ".jsonl"}


class Root275Error(ValueError):
    """Raised for stale identity or an unsafe subset contract."""


def _path(value: Any, label: str, *, directory: bool = False) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise Root275Error(f"{label} has no path")
    path = Path(value).expanduser().resolve()
    if directory and not path.is_dir():
        raise Root275Error(f"{label} directory is missing: {path}")
    if not directory and not path.is_file():
        raise Root275Error(f"{label} file is missing: {path}")
    return path


def _sha(path: Path, label: str, *, max_bytes: int = MAX_SMALL_BYTES) -> str:
    path = _path(path, label)
    size = path.stat().st_size
    if size > max_bytes:
        raise Root275Error(f"{label} exceeds bounded source read: {path} ({size} bytes)")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ref(path: Path, role: str, *, expected: str | None = None) -> dict[str, Any]:
    path = _path(path, role)
    stat = path.stat()
    if stat.st_size > MAX_SMALL_BYTES:
        raise Root275Error(f"{role} exceeds bounded source read: {path}")
    actual = _sha(path, role)
    if expected is not None and actual != expected:
        raise Root275Error(f"{role} SHA differs: {path}")
    return {
        "path": str(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": actual,
        "content_opened_by_preparer": True,
    }


def _json(path: Path, role: str) -> dict[str, Any]:
    path = _path(path, role)
    if path.stat().st_size > MAX_SMALL_BYTES:
        raise Root275Error(f"{role} exceeds bounded JSON read: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Root275Error(f"{role} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise Root275Error(f"{role} must be a JSON object: {path}")
    return value


def _atomic(path: Path, value: dict[str, Any], *, max_bytes: int = MAX_SMALL_BYTES) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise Root275Error(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > max_bytes:
            raise Root275Error(f"output exceeds bounded size: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return _ref(path, "new ROOT275 output")


def _load_parent(root: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    folder = ROOTS[root]
    root_request_path = folder / f"{root.lower()}-request.json"
    root_selection_path = folder / f"{root.lower()}-selection-manifest.json"
    delegated_request_path = folder / "delegated/typed-lifecycle-batch-v1-request.json"
    delegated_manifest_path = folder / "delegated/typed-lifecycle-batch-v1-manifest.json"
    root_request = _json(root_request_path, f"{root} selection request")
    root_selection = _json(root_selection_path, f"{root} selection manifest")
    delegated_request = _json(delegated_request_path, f"{root} delegated lifecycle request")
    delegated_manifest = _json(delegated_manifest_path, f"{root} delegated lifecycle manifest")
    if root_request.get("schema") != REQUEST_SCHEMA or root_request.get("family_id") != "F4":
        raise Root275Error(f"{root} selection request schema/family differs")
    if delegated_request.get("schema") != REQUEST_SCHEMA or delegated_request.get("family_id") != "F4":
        raise Root275Error(f"{root} delegated request schema/family differs")
    if delegated_manifest.get("schema") != BATCH_SCHEMA or delegated_manifest.get("status") != "READY_FOR_GUARDED_BATCH":
        raise Root275Error(f"{root} delegated manifest is not a guarded source manifest")
    ids = delegated_request.get("physical_case_ids")
    if not isinstance(ids, list) or len(ids) != 8 or len(ids) != len(set(ids)):
        raise Root275Error(f"{root} delegated request does not contain eight unique cases")
    cases = delegated_manifest.get("cases")
    if not isinstance(cases, list) or {row.get("physical_case_id") for row in cases if isinstance(row, dict)} != set(ids):
        raise Root275Error(f"{root} delegated manifest/request identity differs")
    by_id = {row["physical_case_id"]: row for row in cases}
    selected: dict[str, dict[str, Any]] = {}
    for case_id in TARGET_CASES:
        if case_id in by_id:
            selected[case_id] = by_id[case_id]
    return (
        {
            "root_request_path": root_request_path,
            "root_selection_path": root_selection_path,
            "delegated_request_path": delegated_request_path,
            "delegated_manifest_path": delegated_manifest_path,
        },
        root_request,
        root_selection,
        delegated_manifest,
        selected,
    )


def _collect_parent_refs(root: str, parent_paths: dict[str, Path], selected: dict[str, dict[str, Any]], refs: dict[str, dict[str, Any]], case_rows: dict[str, dict[str, Any]]) -> None:
    for key, path in parent_paths.items():
        _add_ref(refs, _ref(path, f"{root} {key}"), f"{root} {key}")
    parent_request = _json(parent_paths["delegated_request_path"], f"{root} delegated request")
    command = parent_request.get("command")
    if isinstance(command, list):
        for index, value in enumerate(command):
            if isinstance(value, str) and Path(value).is_file() and Path(value).suffix.lower() not in PAYLOAD_SUFFIXES:
                _add_ref(refs, _ref(Path(value), f"{root} command[{index}]"), f"{root} command[{index}]")
    for case_id, row in selected.items():
        case_manifest_path = _path(row.get("case_manifest"), f"{case_id} case manifest")
        case_request_path = _path(row.get("case_request"), f"{case_id} case request")
        case_manifest = _json(case_manifest_path, f"{case_id} case manifest")
        case_request = _json(case_request_path, f"{case_id} case request")
        if case_manifest.get("physical_case_id") != case_id or case_manifest.get("family_id") != "F4":
            raise Root275Error(f"{case_id} case manifest identity differs")
        if case_request.get("physical_case_id") != case_id or case_request.get("family_id") != "F4":
            raise Root275Error(f"{case_id} case request identity differs")
        _add_ref(refs, _ref(case_manifest_path, f"{case_id} case manifest"), f"{case_id} case manifest")
        _add_ref(refs, _ref(case_request_path, f"{case_id} case request"), f"{case_id} case request")
        for item in case_manifest.get("source_refs", []):
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                continue
            source_path = Path(item["path"])
            if source_path.suffix.lower() in PAYLOAD_SUFFIXES:
                continue
            _add_ref(refs, _ref(source_path, f"{case_id} {item.get('role', 'source')}", expected=item.get("sha256")), f"{case_id} {item.get('role', 'source')}")
        trajectory = case_manifest.get("trajectory_h5")
        if not isinstance(trajectory, dict) or not isinstance(trajectory.get("path"), str) or not isinstance(trajectory.get("sha256"), str):
            raise Root275Error(f"{case_id} deferred trajectory edge is missing")
        if Path(trajectory["path"]).suffix.lower() not in PAYLOAD_SUFFIXES:
            raise Root275Error(f"{case_id} trajectory suffix is not deferred payload")
        case_rows[case_id] = {
            "physical_case_id": case_id,
            "family_id": "F4",
            "case_manifest": str(case_manifest_path),
            "case_manifest_sha256": _sha(case_manifest_path, f"{case_id} case manifest"),
            "case_request": str(case_request_path),
            "case_request_sha256": _sha(case_request_path, f"{case_id} case request"),
            "current_index": row.get("current_index"),
            "source_join_status": "EXACT_CURRENT_AUDIT_METADATA_JOIN",
            "trajectory_h5": {
                "path": trajectory["path"],
                "bytes": int(trajectory["bytes"]),
                "sha256": trajectory["sha256"],
                "read_after_reservation": True,
                "content_opened_by_preparer": False,
                "declared_from": f"{root} per-case manifest",
            },
            "frames": int(case_manifest.get("frames", 0)),
            "particles": int(case_manifest.get("particles", 0)),
            "historical_alias": case_manifest.get("case_scope", "NONE"),
        }


def _add_ref(refs: dict[str, dict[str, Any]], ref: dict[str, Any], label: str) -> None:
    path = ref["path"]
    if Path(path).suffix.lower() in PAYLOAD_SUFFIXES:
        raise Root275Error(f"{label} payload entered static closure: {path}")
    previous = refs.get(path)
    if previous is not None and previous["sha256"] != ref["sha256"]:
        raise Root275Error(f"{label} has conflicting SHA: {path}")
    refs[path] = ref


def _load_base() -> Any:
    base_path = PRIMARY / "lagrangian-fluid-lab/scripts/ds_data02_stage2_build_generic_native_extract_v1.py"
    spec = importlib.util.spec_from_file_location("root275_generic_native_v1", base_path)
    if spec is None or spec.loader is None:
        raise Root275Error(f"cannot load generic extractor: {base_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    if args.namespace != "ROOT275":
        raise Root275Error("this builder only creates immutable ROOT275")
    if args.target_cases != list(TARGET_CASES):
        raise Root275Error("ROOT275 target case order differs from the reviewed seven-case subset")
    refs: dict[str, dict[str, Any]] = {}
    case_rows: dict[str, dict[str, Any]] = {}
    parent_manifests: dict[str, dict[str, Any]] = {}
    for root in ("ROOT296", "ROOT297"):
        paths, root_request, root_selection, delegated_manifest, selected = _load_parent(root)
        parent_manifests[root] = {
            "paths": paths,
            "request": root_request,
            "selection": root_selection,
            "manifest": delegated_manifest,
            "selected": sorted(selected),
        }
        _collect_parent_refs(root, paths, selected, refs, case_rows)
    if set(case_rows) != set(TARGET_CASES):
        raise Root275Error(f"parent groups do not exactly cover ROOT275: {sorted(set(TARGET_CASES) - set(case_rows))}")
    if set(case_rows) & set(ROOT280_CASES):
        raise Root275Error("ROOT275 overlaps ROOT280 source preparation")

    for path, role, expected in (
        (CURRENT, "CURRENT336", CURRENT_SHA),
        (INVENTORY, "historical 118 inventory", INVENTORY_SHA),
        (OVERLAY, "native-cause overlay V10", OVERLAY_SHA),
        (ROOT280_REQUEST, "ROOT280 request", None),
        (ROOT280_SELECTION, "ROOT280 selection", None),
        (TYPED_WORKER, "typed lifecycle batch worker", None),
        (RUNTIME_V8, "runtime v8", None),
        (DISPATCH_V8, "dispatch v8", None),
        (STRICT_V8, "strict v8", None),
        (VENV, "literal Python interpreter", None),
        (CONFIG, "official DsphConfig.xml", None),
    ):
        _add_ref(refs, _ref(path, role, expected=expected), role)

    target_records = [case_rows[case_id]["trajectory_h5"] for case_id in TARGET_CASES]
    selected_case_rows = [case_rows[case_id] for case_id in TARGET_CASES]
    output_root = args.output_root.expanduser().resolve()
    if output_root.exists():
        raise Root275Error(f"refusing to reuse output root: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    subset_manifest_path = output_root / "delegated/typed-lifecycle-batch-v1-manifest.json"
    subset_manifest = {
        "schema": BATCH_SCHEMA,
        "status": "READY_FOR_GUARDED_BATCH",
        "family_id": "F4",
        "case_count": len(TARGET_CASES),
        "cases": selected_case_rows,
        "current_catalog": {"path": str(CURRENT), "sha256": CURRENT_SHA},
        "deferred_trajectory_h5": target_records,
        "input_refs": sorted(refs.values(), key=lambda item: item["path"]),
        "group_policy": {"max_cases": 8, "max_source_bytes": 20 * 1024**3, "one_case_at_a_time": True, "historical_alias_excluded": True, "selected_source_bytes": sum(item["bytes"] for item in target_records)},
        "source_join_counts": {"current_cases": 336, "exact_current_audit_metadata_joins": len(TARGET_CASES), "historical_alias_rows": 1, "incomplete_or_mismatched": 0},
        "qualification_boundary": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "native_exit_cause": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
        "source_read_policy": {"json_and_stat_only_at_prepare": True, "trajectory_content_opened_at_prepare": False, "native_or_bi4_opened": False, "solver_started": False, "terminal_typed_proof_required_before_native_extract": True},
        "source_lineage": {"ROOT296": parent_manifests["ROOT296"]["selected"], "ROOT297": parent_manifests["ROOT297"]["selected"], "root280_excluded_case_ids": list(ROOT280_CASES), "overlay": {"path": str(OVERLAY), "sha256": OVERLAY_SHA}},
    }
    subset_ref = _atomic(subset_manifest_path, subset_manifest)
    _add_ref(refs, subset_ref, "ROOT275 subset manifest")

    request_path = args.request_output.expanduser().resolve()
    static_paths = sorted(refs)
    deferred_paths = [item["path"] for item in target_records]
    subset_request = {
        "schema": REQUEST_SCHEMA,
        "status": "READY_SOURCE_ONLY_WAITING_FOR_TERMINAL_PROOF",
        "shared_runtime_version": "v8",
        "family_id": "F4",
        "case_id": "STAGE2_TYPED_LIFECYCLE_BATCH_F4_ROOT275_SUBSET",
        "attempt_id": "typed-lifecycle-batch-v1-root275-subset-001-root-forward",
        "physical_case_ids": list(TARGET_CASES),
        "continuation_group": {"group_id": "F4-ROOT275-native-subset", "case_ids": list(TARGET_CASES), "source_parent_groups": ["F4-typed-lifecycle-continuation-001", "F4-typed-lifecycle-continuation-002"]},
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 3600,
        "max_memory_bytes": 4 * 1024**3,
        "estimated_storage_bytes": 4314890240,
        "estimated_deferred_read_bytes": sum(item["bytes"] for item in target_records),
        "estimated_deferred_read_passes": 1,
        "cwd": str(PRIMARY / "lagrangian-fluid-lab"),
        "worktree_root": str(PRIMARY),
        "command": [str(VENV), str(TYPED_WORKER), "run", "--manifest", str(subset_manifest_path), "--output-root", "{attempt_root}/typed-lifecycle-batch"],
        "input_files": static_paths,
        "input_sha256": {path: refs[path]["sha256"] for path in static_paths},
        "deferred_input_files": deferred_paths,
        "deferred_input_records": target_records,
        "manifest_contract": {"path": str(subset_manifest_path), "sha256": subset_ref["sha256"]},
        "launch_allowed": False,
        "execution_allowed": False,
        "launch_owner": "root",
        "request_note": "ROOT275 source-only F4 seven-case subset. This request is not a terminal typed producer proof; root must rebind the latest lifecycle registry and a completed typed proof before any native decoder request.",
        "claim_boundary": {"native_cause": "UNKNOWN until exact official PartOut Motive and (Zone,Idp) join", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_event_time": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "read_policy": {"prepare_opened_h5": False, "prepare_opened_jsonl": False, "prepare_opened_bi4": False, "prepare_opened_obi4": False, "prepare_opened_partout": False, "prepare_opened_runparts": False, "parent_reservation_required": True},
    }
    request_ref = _atomic(request_path, subset_request)

    # Use the reviewed generic extractor in source-only mode.  This creates
    # ROOT275 native contracts with launch_allowed=false and no typed proof.
    base = _load_base()
    ns = argparse.Namespace(
        namespace="ROOT275",
        lifecycle_request=request_path,
        current=CURRENT,
        inventory=INVENTORY,
        terminal_proof=None,
        consumed_report=[
            STAGE2 / "checkpoints/F4_NATIVE_TYPED_CAUSE_BATCH_V1_ACTUAL_ROOT_VERIFICATION_235.json",
            STAGE2 / "checkpoints/F4_UNLOCATED_NATIVE_EVIDENCE_V4_ACTUAL_ROOT_VERIFICATION_250.json",
            STAGE2 / "checkpoints/GENERIC_NATIVE_EXTRACT_F4_V2_ACTUAL_ROOT_VERIFICATION_264.json",
        ],
        exclude_case=list(ROOT280_CASES),
        output_root=output_root / "generic-native-extract",
        request_output=output_root / "generic-native-extract-v1-root-forward-275-source-only.json",
    )
    native_result = base.prepare(ns)
    return {
        "status": "ROOT275_SOURCE_ONLY_READY_WAITING_FOR_TYPED_TERMINAL_PROOF",
        "subset_request": {"path": str(request_path), "sha256": request_ref["sha256"], "bytes": request_ref["bytes"]},
        "subset_manifest": {"path": str(subset_manifest_path), "sha256": subset_ref["sha256"], "bytes": subset_ref["bytes"]},
        "native_source_request": native_result,
        "case_ids": list(TARGET_CASES),
        "root280_excluded_case_ids": list(ROOT280_CASES),
        "declared_deferred_source_bytes": sum(item["bytes"] for item in target_records),
        "prepare_opened_payload_content": False,
        "launch_allowed": False,
    }


def _self_test() -> dict[str, Any]:
    if len(TARGET_CASES) != 7 or len(set(TARGET_CASES)) != 7:
        raise Root275Error("ROOT275 target list is not seven unique cases")
    if set(TARGET_CASES) & set(ROOT280_CASES):
        raise Root275Error("ROOT275 overlaps ROOT280")
    return {"status": "PASS", "target_cases": len(TARGET_CASES), "root280_excluded": len(ROOT280_CASES), "payload_opened": False, "launch_allowed": False}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    prep = sub.add_parser("prepare")
    prep.add_argument("--namespace", default="ROOT275")
    prep.add_argument("--target-cases", nargs="*", default=list(TARGET_CASES))
    prep.add_argument("--output-root", type=Path, required=True)
    prep.add_argument("--request-output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = _self_test() if args.action == "self-test" else prepare(args)
    except (Root275Error, OSError, ValueError) as exc:
        print(f"ROOT275_SOURCE_ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
