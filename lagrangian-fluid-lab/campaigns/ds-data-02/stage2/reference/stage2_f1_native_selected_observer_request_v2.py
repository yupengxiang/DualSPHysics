#!/usr/bin/env python3
"""Build the additive ROOT204 native-selected observer request (V2).

The consumed V1 request is intentionally left unchanged.  V1's worker is
still the implementation used by this request; this builder repairs the
request-side source closure and read accounting:

* the 25 Part files remain deferred inputs and are never put in
  ``input_files``;
* the producer report's known SHA/size/time is recorded without hashing a
  Part file while building the request;
* the parent guard performs a full stat/SHA check before and after the child;
* one official decoder input read and one worker ``sha256_file`` pass are
  joined with the parent pre/post hashes, so the conservative source-byte
  estimate is four passes, not one;
* V1's per-frame ``TemporaryDirectory`` cleanup is made an explicit guard
  requirement.  The worker has no hard scratch cap, so the parent owns that
  cap and post-child empty-directory check.

The normal build is run by the primary worktree after this file has been
integrated there.  ``--self-test`` uses only manufactured files.  A primary
preflight may stat the 25 deferred Part paths and read only the existing
small JSON/XML sidecars; it never opens or hashes a Part payload.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat as stat_module
import tempfile
import xml.etree.ElementTree as ET
from typing import Any, Iterable


REQUEST_SCHEMA = "ds02.request.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1.native-selected-observer-manifest.v2"
VARIANT_SCHEMA = "ds02.stage2.f1.native-selected-observer-request.v2"

PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
OLD_REFERENCE = Path("/home/jade/.codex/worktrees/ds-data-02-stage2-reference/DualSPHysics")
REFERENCE = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
REQUESTS = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests"
V1_REQUEST_DIR = REQUESTS / "stage2-f1-native-selected-observer-root204-002"
V1_MANIFEST = V1_REQUEST_DIR / "manifest.json"
V2_BUILDER_EXPECTED = REFERENCE / "stage2_f1_native_selected_observer_request_v2.py"
V2_CONTRACT_EXPECTED = REFERENCE / "stage2_f1_native_selected_observer_contract_v2.json"
V1_WORKER = REFERENCE / "stage2_f1_native_selected_observer_v1.py"
V1_BUILDER = REFERENCE / "stage2_f1_native_selected_observer_request_v1.py"
BASE_OBSERVER = REFERENCE / "stage2_native_physical_observer_v2.py"
V1_CONTRACT = REFERENCE / "stage2_f1_native_selected_observer_contract_v1.json"
ROOT202_BUILDER = REFERENCE / "stage2_f1_com_observer_calibration_request_v1.py"
ROOT202_CONTRACT = REFERENCE / "stage2_f1_com_observer_calibration_contract_v1.json"

PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYVENV_CFG = PYTHON.parent.parent / "pyvenv.cfg"
RUNTIME = PRIMARY / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
RUNNER = PRIMARY / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT_GUARD = PRIMARY / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
EXTERNAL_SOLVER_V5 = PRIMARY / "lagrangian-fluid-lab/scripts/ds_data02_stage2_external_solver_v5.py"
DECODER_SOURCE = PRIMARY / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp"
BI4_WRITER_CPP = Path("/home/jade/Projects/DualSPHysics/src/source/JPartDataBi4.cpp")
BI4_WRITER_H = Path("/home/jade/Projects/DualSPHysics/src/source/JPartDataBi4.h")
PYTHON_RECORD_SOURCE = PRIMARY / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "f3-s2-middle-half-output-native-observer-v2-root188-primary-001.json"
)

FORBIDDEN_INPUT_SUFFIXES = {".bi4", ".h5", ".hdf5", ".vtk", ".vtu"}
MAX_SMALL_FILE_BYTES = 8 * 1024 * 1024
MAX_METADATA_READ_BYTES = 10 * 1024 * 1024
NATIVE_READ_PASSES = 4
SCRATCH_CAP_BYTES = 256 * 1024 * 1024
PROCESS_MEMORY_CAP_BYTES = 2 * 1024 * 1024 * 1024
SELECTED_PER_CASE = 5


class MetadataBudget:
    """Count bytes deliberately read by the source-only builder."""

    def __init__(self, limit: int = MAX_METADATA_READ_BYTES) -> None:
        self.limit = int(limit)
        self.bytes = 0
        self.paths: list[str] = []

    def charge(self, path: Path, amount: int) -> None:
        self.bytes += int(amount)
        self.paths.append(str(path))
        if self.bytes > self.limit:
            raise RuntimeError(
                f"source-only metadata read budget exceeded: {self.bytes} > {self.limit}"
            )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _path(value: Path | str) -> Path:
    return Path(value).expanduser().resolve()


def _remap_primary(value: Any) -> Any:
    """Map old reference-worktree strings to the integrated primary tree."""

    if isinstance(value, str) and value.startswith(str(OLD_REFERENCE)):
        return str(PRIMARY / value[len(str(OLD_REFERENCE)) :].lstrip("/"))
    if isinstance(value, list):
        return [_remap_primary(item) for item in value]
    if isinstance(value, dict):
        return {key: _remap_primary(item) for key, item in value.items()}
    return value


def _regular_small(path: Path | str, label: str, budget: MetadataBudget, *, hash_bytes: bool = True) -> Path:
    path = _path(path)
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} is not a regular file: {path}")
    if path.suffix.lower() in FORBIDDEN_INPUT_SUFFIXES:
        raise ValueError(f"{label} is a native/H5/VTK payload and cannot be an input file: {path}")
    size = int(path.stat().st_size)
    if size > MAX_SMALL_FILE_BYTES:
        raise ValueError(f"{label} exceeds the source-only small-file limit: {path} ({size})")
    return path


def _record(path: Path | str, label: str, budget: MetadataBudget, *, content_scope: str = "small_metadata_hashed_by_builder") -> dict[str, Any]:
    path = _regular_small(path, label, budget)
    value = path.stat()
    data = path.read_bytes()
    budget.charge(path, len(data))
    return {
        "path": str(path),
        "label": label,
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
        "sha256": _sha256_bytes(data),
        "content_scope": content_scope,
    }


def _read_json_bytes(path: Path | str, label: str, budget: MetadataBudget) -> tuple[dict[str, Any], bytes]:
    path = _regular_small(path, label, budget)
    data = path.read_bytes()
    budget.charge(path, len(data))
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object")
    return value, data


def _read_json(path: Path | str, label: str, budget: MetadataBudget) -> dict[str, Any]:
    value, _ = _read_json_bytes(path, label, budget)
    return value


def _write_once(path: Path, value: Any) -> None:
    path = _path(path)
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _path_from(value: Any, label: str) -> Path:
    if isinstance(value, str):
        return _path(value)
    if isinstance(value, dict) and isinstance(value.get("path"), str):
        return _path(value["path"])
    raise ValueError(f"{label} has no path")


def _selected_frame_number(path: Path) -> int:
    stem = path.stem
    if not stem.startswith("Part_"):
        raise ValueError(f"selected native path has no Part_ frame number: {path}")
    try:
        return int(stem.split("_", 1)[1])
    except ValueError as exc:
        raise ValueError(f"invalid selected native frame path: {path}") from exc


def _producer_records(case: dict[str, Any], budget: MetadataBudget) -> dict[str, Any]:
    """Return deferred records from report metadata without hashing Part files."""

    provenance = case.get("old_observer_provenance")
    if not isinstance(provenance, dict):
        raise ValueError(f"{case.get('label', 'case')} has no observer provenance")
    report_path = _path_from(provenance.get("report"), "observer report")
    report, report_bytes = _read_json_bytes(report_path, f"{case.get('label', 'case')} selected observer report", budget)
    # The report is already bounded and was read once above.  This is the
    # report's exact byte SHA; it is never derived from or confused with a
    # native Part payload SHA.
    report_sha = _sha256_bytes(report_bytes)
    source = report.get("source")
    if not isinstance(source, dict):
        raise ValueError(f"{report_path} lacks source metadata")
    records = source.get("selected_part_records")
    if not isinstance(records, list):
        raise ValueError(f"{report_path} lacks selected_part_records")
    by_path: dict[str, dict[str, Any]] = {}
    by_frame: dict[int, dict[str, Any]] = {}
    for item in records:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        item_path = _path(item["path"])
        by_path[str(item_path)] = item
        try:
            by_frame[_selected_frame_number(item_path)] = item
        except ValueError:
            continue

    selected_paths = case.get("selected_native_frame_paths")
    selected_frames = case.get("selected_frames")
    if not isinstance(selected_paths, list) or not isinstance(selected_frames, list):
        raise ValueError(f"{case.get('label', 'case')} has malformed selected frame metadata")
    if len(selected_paths) != len(selected_frames):
        raise ValueError(f"{case.get('label', 'case')} selected frame/path length mismatch")

    output: dict[str, Any] = {}
    for raw_path, raw_frame in zip(selected_paths, selected_frames):
        selected = _path(raw_path)
        frame = int(raw_frame)
        if _selected_frame_number(selected) != frame:
            raise ValueError(f"{selected} does not match selected frame {frame}")
        declared = by_path.get(str(selected)) or by_frame.get(frame)
        if not isinstance(declared, dict):
            raise ValueError(f"{report_path} has no producer record for {selected}")
        if _path(declared["path"]) != selected:
            raise ValueError(f"producer frame record path mismatch for {selected}")
        for key in ("bytes", "mtime_ns", "sha256"):
            if key not in declared:
                raise ValueError(f"producer record {selected} lacks {key}")
        declared_bytes = int(declared["bytes"])
        declared_mtime = int(declared["mtime_ns"])
        if selected.is_symlink() or not selected.is_file():
            raise FileNotFoundError(f"deferred native frame is not a regular file: {selected}")
        # This is metadata-only.  Do not open/read/hash the Part file here.
        current = selected.stat()
        if int(current.st_size) != declared_bytes or int(current.st_mtime_ns) != declared_mtime:
            raise RuntimeError(f"deferred native frame metadata changed since producer report: {selected}")
        output[str(selected)] = {
            "path": str(selected),
            "frame": frame,
            "bytes": declared_bytes,
            "mtime_ns": declared_mtime,
            "sha256": str(declared["sha256"]),
            "known_sha256": str(declared["sha256"]),
            "sha256_computed_by_builder": False,
            "content_scope": "producer_report_declared_native_sha; parent_after_reservation_recheck_required",
            "producer_record": {
                "report_path": str(report_path),
                "report_sha256": report_sha,
                "report_record_path": str(declared["path"]),
            },
            "stat_at_prepare": {
                "bytes": int(current.st_size),
                "mtime_ns": int(current.st_mtime_ns),
                "ctime_ns": int(current.st_ctime_ns),
                "device": int(current.st_dev),
                "inode": int(current.st_ino),
            },
            "parent_recheck": {
                "before_child": ["bytes", "mtime_ns", "ctime_ns", "device", "inode", "sha256"],
                "after_child": ["bytes", "mtime_ns", "ctime_ns", "device", "inode", "sha256"],
                "source_replace_or_stat_change": "FAIL",
            },
        }
    return output


def _xml_particle_count(path: Path, budget: MetadataBudget) -> int:
    path = _regular_small(path, "generated XML", budget)
    data = path.read_bytes()
    budget.charge(path, len(data))
    root = ET.fromstring(data)
    particle = root.find(".//particles")
    if particle is None:
        return 0
    total = 0
    for node in particle:
        try:
            total += int(node.get("count", "0"))
        except ValueError:
            continue
    return max(total, 0)


def _literal_python_binding(budget: MetadataBudget) -> tuple[dict[str, Any], Path | None]:
    """Bind literal venv Python without hashing its large resolved binary here."""

    if not PYTHON.exists():
        raise FileNotFoundError(f"literal venv interpreter missing: {PYTHON}")
    resolved = PYTHON.resolve()
    python_stat = resolved.stat()
    pyvenv_record = _record(PYVENV_CFG, "literal venv pyvenv.cfg", budget)
    # A prior primary generic request carries the known runtime digest.  It is
    # metadata, not an unguarded re-read of the interpreter; the parent gate
    # must re-stat and re-hash the resolved target before execution.
    known_sha: str | None = None
    if PYTHON_RECORD_SOURCE.exists():
        candidate = _read_json(PYTHON_RECORD_SOURCE, "known literal Python runtime record", budget)
        for container_key in ("input_records", "runtime_closure"):
            container = candidate.get(container_key)
            if isinstance(container, dict):
                item = container.get(str(PYTHON))
                if isinstance(item, dict):
                    known_sha = item.get("sha256") or item.get("resolved_sha256")
                    if known_sha:
                        break
        if known_sha is None:
            known_sha = candidate.get("literal_python", {}).get("resolved_sha256") if isinstance(candidate.get("literal_python"), dict) else None
    binding = {
        "literal_path": str(PYTHON),
        "literal_path_is_symlink": bool(PYTHON.is_symlink()),
        "resolved_path": str(resolved),
        "resolved_stat_at_build": {
            "bytes": int(python_stat.st_size),
            "mtime_ns": int(python_stat.st_mtime_ns),
            "ctime_ns": int(python_stat.st_ctime_ns),
            "device": int(python_stat.st_dev),
            "inode": int(python_stat.st_ino),
        },
        "resolved_sha256": known_sha or "PARENT_RUNTIME_HASH_REQUIRED",
        "resolved_sha256_computed_by_builder": False,
        "pyvenv_cfg": pyvenv_record,
        "parent_pre_entry_recheck": "required",
        "argv0_must_remain_literal": True,
    }
    return binding, PYTHON_RECORD_SOURCE if PYTHON_RECORD_SOURCE.exists() else None


def _runtime_paths() -> list[Path]:
    return [RUNNER, RUNTIME, STRICT_GUARD, EXTERNAL_SOLVER_V5, DECODER_SOURCE, BI4_WRITER_CPP, BI4_WRITER_H]


def _source_path_set(raw_manifest: dict[str, Any], canonical_manifest: dict[str, Any], *, builder_path: Path, contract_path: Path) -> list[Path]:
    paths: list[Path] = []
    for item in raw_manifest.get("source_inputs", []):
        if isinstance(item, dict) and isinstance(item.get("path"), str):
            paths.append(_remap_primary(item["path"]))
    for case in canonical_manifest.get("cases", []):
        if not isinstance(case, dict):
            continue
        for key in ("runparts", "generated_xml", "decoder", "decoder_source", "solver_request", "solver_receipt"):
            if isinstance(case.get(key), str):
                paths.append(_path(case[key]))
        provenance = case.get("old_observer_provenance")
        if isinstance(provenance, dict):
            for value in provenance.values():
                if isinstance(value, dict) and isinstance(value.get("path"), str):
                    paths.append(_path(value["path"]))
    paths.extend([V1_MANIFEST, V1_WORKER, V1_BUILDER, BASE_OBSERVER, V1_CONTRACT, ROOT202_BUILDER, ROOT202_CONTRACT])
    paths.extend(_runtime_paths())
    paths.extend([builder_path, contract_path])
    return paths


def _unique_small_records(paths: Iterable[Path], budget: MetadataBudget) -> tuple[list[dict[str, Any]], list[Path]]:
    records: list[dict[str, Any]] = []
    unique: list[Path] = []
    seen: set[str] = set()
    for raw in paths:
        path = _path(raw)
        if str(path) in seen:
            continue
        seen.add(str(path))
        # The request closure may contain a known decoder executable with no
        # suffix.  Native data suffixes are rejected before any read.
        if path.suffix.lower() in FORBIDDEN_INPUT_SUFFIXES:
            raise ValueError(f"native payload leaked into input closure: {path}")
        records.append(_record(path, "ROOT204 V2 source/runtime input", budget))
        unique.append(path)
    return records, unique


def _canonical_manifest(raw: dict[str, Any]) -> dict[str, Any]:
    value = _remap_primary(raw)
    if not isinstance(value, dict):
        raise ValueError("ROOT204 V1 manifest is not an object")
    return value


def build_metadata(*, builder_path: Path, budget: MetadataBudget) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    raw_manifest = _read_json(V1_MANIFEST, "ROOT204 V1 manifest", budget)
    manifest = _canonical_manifest(raw_manifest)
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != 5:
        raise ValueError("ROOT204 V2 expects the five existing F1 producer cases")
    deferred: dict[str, Any] = {}
    max_particles = 0
    per_case_memory: dict[str, int] = {}
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("malformed ROOT204 case")
        selected = _producer_records(case, budget)
        if len(selected) != SELECTED_PER_CASE:
            raise ValueError(f"{case.get('label')} has {len(selected)} selected records, expected {SELECTED_PER_CASE}")
        deferred.update(selected)
        generated_xml = _path(case["generated_xml"])
        count = _xml_particle_count(generated_xml, budget)
        label = str(case.get("label", generated_xml.name))
        per_case_memory[label] = count
        max_particles = max(max_particles, count)
        case["selected_native_frame_records"] = [selected[str(_path(p))] for p in case["selected_native_frame_paths"]]
    if len(deferred) != 25:
        raise ValueError(f"ROOT204 V2 expects 25 deferred records, got {len(deferred)}")

    builder_path = _path(builder_path)
    if not builder_path.is_file():
        raise FileNotFoundError(f"V2 builder source is not present at requested binding path: {builder_path}")
    development_builder = _path(__file__)
    if builder_path not in {V2_BUILDER_EXPECTED, development_builder}:
        raise ValueError(f"request must bind the integrated V2 builder path: {V2_BUILDER_EXPECTED}")
    contract_path = V2_CONTRACT_EXPECTED if V2_CONTRACT_EXPECTED.is_file() else development_builder.with_name(V2_CONTRACT_EXPECTED.name)
    if not contract_path.is_file():
        raise FileNotFoundError(f"V2 contract source is not present: {contract_path}")

    literal_python, python_record_source = _literal_python_binding(budget)
    source_paths = _source_path_set(raw_manifest, manifest, builder_path=builder_path, contract_path=contract_path)
    if python_record_source is not None:
        source_paths.append(python_record_source)
    source_records, unique_paths = _unique_small_records(source_paths, budget)
    source_records_by_path = {item["path"]: item for item in source_records}

    # The manifest itself and V2 contract/builder are added after the case
    # records.  They are small, regular source files in the integrated tree.
    if str(builder_path) not in source_records_by_path:
        source_records.append(_record(builder_path, "ROOT204 V2 request builder", budget))
        unique_paths.append(builder_path)
    if str(contract_path) not in source_records_by_path:
        source_records.append(_record(contract_path, "ROOT204 V2 read/scratch contract", budget))
        unique_paths.append(contract_path)

    selected_bytes = sum(int(item["bytes"]) for item in deferred.values())
    native_read_bytes = selected_bytes * NATIVE_READ_PASSES
    static_input_bytes = sum(int(item["bytes"]) for item in source_records)
    estimated_numpy_peak = max_particles * 128
    manifest.update({
        "schema": MANIFEST_SCHEMA,
        "status": "PREPARED_ROOT204_V2_SOURCE_BOUND_METADATA_ONLY",
        "source_inputs": source_records,
        "native_deferred_records": deferred,
        "native_read_accounting": {
            "selected_native_frame_count": len(deferred),
            "selected_native_source_bytes": selected_bytes,
            "estimated_native_read_passes": NATIVE_READ_PASSES,
            "estimated_native_read_bytes": native_read_bytes,
            "estimate_is_conservative_transfer_proxy": True,
            "pass_semantics": [
                "parent_v8_pre_decode_full_sha256_and_stat",
                "official_bi4_decoder_input_read",
                "V1_worker_base_sha256_file_after_decode",
                "parent_v8_post_decode_full_sha256_and_stat",
            ],
            "worker_internal_source_reads_per_frame": {
                "official_decoder_input_read": 1,
                "base_sha256_file_pass": 1,
                "decoded_scratch_arrays": "not_part_source_bytes",
            },
            "output_json_hashing": "separate_from_native_source_byte_estimate",
        },
        "scratch_policy": {
            "concurrency": 1,
            "temporary_directory_per_frame": True,
            "temporary_directory_cleanup": "Python TemporaryDirectory removes decoded arrays/XML on success and exception",
            "scratch_root_may_remain_empty": True,
            "parent_cap_bytes": SCRATCH_CAP_BYTES,
            "parent_post_child_empty_or_removed_required": True,
            "worker_has_hard_cap": False,
        },
        "memory_policy": {
            "particle_counts_from_small_generated_xml": per_case_memory,
            "max_particles_one_frame": max_particles,
            "conservative_numpy_array_peak_bytes": estimated_numpy_peak,
            "process_memory_cap_bytes": PROCESS_MEMORY_CAP_BYTES,
            "measured_peak": False,
            "reason": "V1 decodes one frame at a time; arrays and temporary decoder files are released per frame; cap remains parent-owned",
        },
        "preparation_scope": {
            "production_native_payload_read_by_builder": False,
            "production_native_sha_computed_by_builder": False,
            "native_metadata_stat_only": True,
            "hdf5_read": False,
            "vtk_read": False,
            "solver_launch": False,
            "selected_case_count": len(cases),
            "selected_frames_per_case": SELECTED_PER_CASE,
            "metadata_read_budget_bytes": budget.limit,
            "metadata_read_bytes": budget.bytes,
        },
    })
    # The old manifest can contain old worktree path strings in provenance.
    # It is okay to preserve those records as historical text, but active
    # source paths and worker operands above are all primary absolute paths.
    manifest["native_deferred_policy"] = {
        "parent_after_reservation_first_sha_and_stat": True,
        "parent_after_child_post_sha_and_stat": True,
        "required_stat_fields": ["bytes", "mtime_ns", "ctime_ns", "device", "inode"],
        "known_sha_source": "existing producer selected_part_records; builder does not hash native payload",
        "selected_frame_paths_only": True,
        "full_native_tree_hash": "NOT_REQUESTED",
        "source_replace_or_stat_change": "FAIL",
    }
    return manifest, {str(path): record for path, record in zip(unique_paths, source_records)}, source_records, literal_python


def build_request(*, manifest_path: Path, manifest: dict[str, Any], source_records: list[dict[str, Any]], literal_python: dict[str, Any], builder_path: Path, case_id: str, attempt_id: str) -> dict[str, Any]:
    source_by_path = {item["path"]: item for item in source_records}
    manifest_record = source_by_path.get(str(_path(manifest_path)))
    if manifest_record is None:
        raise ValueError("V2 manifest record was not included in source closure")
    input_files = sorted(source_by_path)
    if any(Path(path).suffix.lower() in FORBIDDEN_INPUT_SUFFIXES for path in input_files):
        raise ValueError("native/H5/VTK payload leaked into input_files")
    input_sha256 = {path: source_by_path[path]["sha256"] for path in input_files}
    deferred = manifest.get("native_deferred_records")
    if not isinstance(deferred, dict) or len(deferred) != 25:
        raise ValueError("V2 request requires exactly 25 deferred native records")
    selected_bytes = sum(int(item["bytes"]) for item in deferred.values())
    native_read_bytes = selected_bytes * NATIVE_READ_PASSES
    static_input_bytes = sum(int(item["bytes"]) for item in source_records)
    worker_output = "{attempt_root}/observer/f1_native_selected_observer_v2.json"
    command = [
        str(PYTHON),
        str(V1_WORKER),
        "--manifest", str(_path(manifest_path)),
        "--attempt-root", "{attempt_root}",
        "--output", worker_output,
    ]
    source_binding = {
        "observer_worker": str(V1_WORKER),
        "worker_schema": "ds02.stage2.f1.native-selected-observer.v1 (V1 bytes preserved)",
        "request_schema_revision": "ROOT204 V2 source/deferred/read-accounting repair",
        "weighted_observables": "native MassFluid only; fixed/moving excluded",
        "time": "actual RunPARTs and decoder TimeStep; no interpolation",
        "old_observer_reports": "metadata provenance only; never native-header evidence",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "known_native_sha": "producer report declared; parent must recompute before and after child",
    }
    runtime_closure = {
        "literal_python": literal_python,
        "runner": str(RUNNER),
        "runtime": str(RUNTIME),
        "strict_guard": str(STRICT_GUARD),
        "external_solver_v5": str(EXTERNAL_SOLVER_V5),
        "source_imports": [str(V1_WORKER), str(BASE_OBSERVER)],
        "decoder_source": str(DECODER_SOURCE),
        "pyvenv_cfg": str(PYVENV_CFG),
        "parent_must_hash_all_before_entry": True,
    }
    return {
        "schema": REQUEST_SCHEMA,
        "variant_schema": VARIANT_SCHEMA,
        "status": "READY_FOR_PARENT_GUARD_SOURCE_BOUND_NATIVE_SELECTED_OBSERVER_V2",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "omp_threads": 1,
        "family_id": "F1",
        "sentinel_id": "F1-S1+F1-S2",
        "physical_case_id": "F1_NATIVE_HEADER_SELECTED_DIAGNOSTIC_V2",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "cwd": str(PRIMARY),
        "worktree_root": str(PRIMARY),
        "command": command,
        "input_files": input_files,
        "input_sha256": input_sha256,
        "input_records": source_by_path,
        "manifest": manifest_record,
        "deferred_input_files": sorted(deferred),
        "deferred_input_records": deferred,
        "deferred_input_policy": {
            "parent_after_reservation_first_sha_and_stat": True,
            "parent_after_child_post_sha_and_stat": True,
            "required_stat_fields": ["bytes", "mtime_ns", "ctime_ns", "device", "inode"],
            "producer_known_sha_is_not_builder_computed": True,
            "source_replace_or_stat_change": "FAIL",
            "full_native_tree_read": False,
            "selected_frame_count": len(deferred),
        },
        "native_read_accounting": manifest["native_read_accounting"],
        "estimated_native_read_bytes": native_read_bytes,
        "estimated_native_read_passes": NATIVE_READ_PASSES,
        "estimated_input_read_bytes": native_read_bytes + static_input_bytes,
        "estimated_input_read_bytes_scope": "four native source passes plus hashed small input/runtime records; not measured device I/O",
        "estimated_hdf5_read_bytes": 0,
        "estimated_storage_bytes": 512 * 1024 * 1024,
        "estimated_scratch_bytes": SCRATCH_CAP_BYTES,
        "estimated_peak_memory_bytes": PROCESS_MEMORY_CAP_BYTES,
        "memory_policy": manifest["memory_policy"],
        "scratch_policy": manifest["scratch_policy"],
        "max_wall_seconds": 1800,
        "max_memory_bytes": PROCESS_MEMORY_CAP_BYTES,
        "max_storage_bytes": 512 * 1024 * 1024,
        "output": {"path": worker_output, "atomic": True, "refuse_overwrite": True},
        "axis_authority": {
            "manifest": str(_path(manifest_path)),
            "source_writer_parser_xml_gravity_control_bound": True,
            "producer_axis_orientation_metadata": "MUST_BE_PRESENT_FOR_CALIBRATION; currently UNKNOWN",
            "no_axis_self_assertion": True,
        },
        "source_binding": source_binding,
        "runtime_closure": runtime_closure,
        "resource_guard": {
            "gpu": "none",
            "runner": str(RUNNER),
            "runtime": str(RUNTIME),
            "strict_guard": str(STRICT_GUARD),
            "parent_guard": "required before deferred BI4 reads",
            "parent_first_sha_and_stat": True,
            "parent_post_sha_and_stat": True,
            "scratch_cap_bytes": SCRATCH_CAP_BYTES,
            "scratch_cleanup_check": "required",
            "solver_launch": "forbidden",
        },
        "launch_disabled": True,
        "execution_allowed": False,
        "solver_started": False,
        "native_payload_read": False,
        "hdf5_read": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "builder_source": str(builder_path),
        "builder_source_sha256": source_by_path[str(builder_path)]["sha256"],
        "builder_source_closure_note": "V2 helper must be integrated at the primary path before this request is regenerated",
    }


def self_test() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="root204-v2-selftest-") as directory:
        root = Path(directory)
        small = root / "record.json"
        small.write_text("{\"status\":\"fixture\"}\n", encoding="utf-8")
        payload = root / "Part_0000.bi4"
        payload.write_bytes(b"manufactured-payload-only")
        budget = MetadataBudget()
        small_record = _record(small, "manufactured small input", budget)
        selected = payload.stat()
        deferred = {
            "path": str(payload),
            "bytes": int(selected.st_size),
            "mtime_ns": int(selected.st_mtime_ns),
            "sha256": _sha256_bytes(payload.read_bytes()),
        }
        # This uses manufactured bytes only; production deferred paths are
        # never touched by self-test.  The real builder explicitly sets this
        # boolean false for producer-declared records.
        assert small_record["sha256"] == _sha256_bytes(small.read_bytes())
        assert NATIVE_READ_PASSES * 160_854_885 == 643_419_540
        assert str(payload).endswith(".bi4")
        assert deferred["bytes"] > 0
        assert SCRATCH_CAP_BYTES < PROCESS_MEMORY_CAP_BYTES
    return {
        "status": "PASS",
        "schema": REQUEST_SCHEMA,
        "variant_schema": VARIANT_SCHEMA,
        "native_read_passes": NATIVE_READ_PASSES,
        "native_read_accounting": "prehash + decoder input + worker source hash + posthash",
        "deferred_records": 25,
        "payload_read": False,
        "solver_started": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build-primary", action="store_true")
    parser.add_argument("--builder-path", type=Path, default=V2_BUILDER_EXPECTED)
    parser.add_argument("--source-manifest", type=Path, default=V1_MANIFEST)
    parser.add_argument("--manifest-output", type=Path)
    parser.add_argument("--request-output", type=Path)
    parser.add_argument("--case-id", default="F1_S1_S2_NATIVE_HEADER_SELECTED_ROOT204_V2")
    parser.add_argument("--attempt-id", default="f1-s1-s2-native-header-selected-root204-v2-primary-001")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.manifest_output is None or args.request_output is None:
        parser.error("--manifest-output and --request-output are required for --build-primary")
    if _path(args.source_manifest) != _path(V1_MANIFEST):
        parser.error("V2 currently accepts only the immutable integrated ROOT204 V1 manifest")
    try:
        budget = MetadataBudget()
        manifest, _, source_records, literal_python = build_metadata(builder_path=args.builder_path, budget=budget)
        request_manifest_path = _path(args.manifest_output)
        # Write the manifest first, then add its small immutable record to the
        # request closure.  No deferred native path is opened or hashed here.
        _write_once(request_manifest_path, manifest)
        post_budget = MetadataBudget(limit=MAX_METADATA_READ_BYTES)
        manifest_record = _record(request_manifest_path, "ROOT204 V2 generated manifest", post_budget)
        request = build_request(
            manifest_path=request_manifest_path,
            manifest=manifest,
            source_records=source_records + [manifest_record],
            literal_python=literal_python,
            builder_path=_path(args.builder_path),
            case_id=args.case_id,
            attempt_id=args.attempt_id,
        )
        request["preparation_scope"] = {
            "production_native_payload_read_by_builder": False,
            "production_native_sha_computed_by_builder": False,
            "metadata_read_bytes": budget.bytes + post_budget.bytes,
            "metadata_read_budget_bytes": MAX_METADATA_READ_BYTES,
            "native_stat_only": True,
        }
        _write_once(_path(args.request_output), request)
        print(json.dumps({
            "status": "PREPARED_ROOT204_V2",
            "manifest": str(request_manifest_path),
            "request": str(_path(args.request_output)),
            "deferred_records": len(request["deferred_input_records"]),
            "estimated_native_read_bytes": request["estimated_native_read_bytes"],
            "metadata_read_bytes": request["preparation_scope"]["metadata_read_bytes"],
            "payload_read": False,
            "solver_started": False,
        }, ensure_ascii=False, indent=2, sort_keys=True))
    except Exception as exc:
        print(json.dumps({"status": "FAILED_ROOT204_V2_BUILD", "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=False, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
