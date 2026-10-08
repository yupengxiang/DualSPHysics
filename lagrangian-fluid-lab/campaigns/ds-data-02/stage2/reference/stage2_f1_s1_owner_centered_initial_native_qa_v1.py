#!/usr/bin/env python3
"""Bounded native initial-state QA for the matched F1-S1 owner rungs.

This worker is deliberately narrower than a solver or a time-series observer.
It decodes exactly the two completed GenCase ``generated.bi4`` files for the
owner-centred ``dp=.005`` and ``dp=.0025`` representations.  The generated
XML, receipt, and source Def are hashed as ordinary small inputs.  Each BI4
is a deferred parent-guard input: the worker records a pre-hash/stat, decodes
one file with the official ``bi4_dump`` binary, and records a post-hash/stat.
Any source change across the decode is a hard source-integrity failure.

The report compares decoded ID/type ranges, finite position/velocity/density,
XML particle counts, and native sample mass.  A summed native sample mass is
kept separate from the frozen continuous owner mass and from any rigid-body
mass.  The worker never reads HDF5, launches a solver, reads VTK geometry, or
grants QI/QN/QE scientific qualification.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any


SCHEMA = "ds02.stage2.f1-s1.owner-centred-initial-native-qa.v1"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
DECODER_SOURCE = REPO / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp"
OBSERVER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_native_physical_observer_v2.py"
RUNNER = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
RUNTIME_V6 = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py"
RUNTIME_V2 = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
OWNER = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/"
    "handoff_20261003/root_actual_fallback_canonical_bindings_and_typed_034/ecc_coarse/owner.json"
)
OWNER_BINDING = OWNER.parent.parent / "ecc-physical-binding.json"
DP005_PROOF = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F1_OWNER_DP005_V2_SUPPORT_CONTROL_ACTUAL_INDEPENDENT_VERIFICATION_001.json"
DP0025_PROOF = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F1_OWNER_DP0025_V3_GENCASE_ACTUAL_INDEPENDENT_VERIFICATION_001.json"
READ_SCOPE_SIDECAR = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F1_OWNER_SUPPORT_ROOT_READ_SCOPE_SEMANTIC_SIDECAR_030.json"

QA_CASE_ID = "F1_S1_OWNER_CENTERED_INITIAL_NATIVE_QA_V1"
QA_ATTEMPT_ID = "f1-s1-owner-centered-initial-native-qa-v1-root-forward-031-001"
QA_REQUEST_DIR = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f1-s1-owner-centered-initial-native-qa-v1"
QA_REQUEST = QA_REQUEST_DIR / "f1_s1_owner_centered_initial_native_qa_v1.json"
QA_OUTPUT_ROOT = DATA_ROOT / "families/F1" / QA_CASE_ID / QA_ATTEMPT_ID

OWNER_MASS_KG = 40.2
MASS_TARGET_FRACTION = 0.01
MASS_MARGINAL_FRACTION = 0.02

CASES: dict[str, dict[str, Any]] = {
    "dp005": {
        "case_id": "F1_S1_OWNER_CENTERED_DP0p005000_V2",
        "dp_m": 0.005,
        "expected_fluid_count": 321600,
        "source_def": REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f1_s1_owner_centered_support_inputs_v2/F1_S1_OWNER_CENTERED_DP0p005000_V2_Def.xml",
        "root": DATA_ROOT / "families/F1/F1_S1_OWNER_CENTERED_DP0p005000_V2/f1-s1-owner-centered-dp0p005000-v2-root-001-root-forward-030-001",
    },
    "dp0025": {
        "case_id": "F1_S1_OWNER_CENTERED_DP0p002500_V3",
        "dp_m": 0.0025,
        "expected_fluid_count": 2572800,
        "source_def": REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f1_s1_owner_centered_support_inputs_v3/F1_S1_OWNER_CENTERED_DP0p002500_V3_Def.xml",
        "root": DATA_ROOT / "families/F1/F1_S1_OWNER_CENTERED_DP0p002500_V3/f1-s1-owner-centered-dp0p002500-v3-root-001-root-forward-030-001",
    },
}


class SourceIntegrityError(RuntimeError):
    """Raised when a deferred BI4 changes across the bounded decode."""


def load_observer_module() -> Any:
    module_name = "ds02_stage2_native_physical_observer_v2_for_initial_qa"
    spec = importlib.util.spec_from_file_location(module_name, OBSERVER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import observer worker: {OBSERVER}")
    module = importlib.util.module_from_spec(spec)
    # Dataclasses and typing helpers in the observer resolve their module from
    # sys.modules while exec_module runs.  Register the exact module first.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    return path


def directory(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_dir() or path.is_symlink():
        raise FileNotFoundError(f"{label} must be a regular directory: {path}")
    return path


def stat_record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    info = path.stat()
    return {
        "path": str(path),
        "bytes": int(info.st_size),
        "device": int(info.st_dev),
        "inode": int(info.st_ino),
        "mtime_ns": int(info.st_mtime_ns),
        "ctime_ns": int(info.st_ctime_ns),
    }


def hash_with_stable_stat(path: Path, label: str) -> dict[str, Any]:
    before = stat_record(path, label)
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    after = stat_record(path, label)
    if before != after:
        raise SourceIntegrityError(f"{label} changed while hashing: before={before} after={after}")
    if size != before["bytes"]:
        raise SourceIntegrityError(f"{label} size changed during read: {size} != {before['bytes']}")
    return {**after, "sha256": digest.hexdigest(), "stat_before": before, "stat_after": after}


def file_record(path: Path, label: str) -> dict[str, Any]:
    return hash_with_stable_stat(path, label)


def atomic_json(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refuse overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def parse_receipt(case: dict[str, Any], label: str) -> dict[str, Any]:
    root = directory(case["root"], f"{label} output root")
    receipt_path = root / "execution-receipt.json"
    receipt = load_json(receipt_path, f"{label} execution receipt")
    request = receipt.get("request", {})
    expected_case_id = case["case_id"]
    checks = {
        "schema": receipt.get("schema") == "ds02.execution-receipt.v1",
        "status": receipt.get("status") == "completed",
        "returncode": receipt.get("returncode") == 0,
        "request_case_id": request.get("case_id") == expected_case_id,
        "receipt_output_root": Path(str(receipt.get("output_root", ""))).resolve() == root,
    }
    if not all(checks.values()):
        raise ValueError(f"{label} receipt identity/status checks failed: {checks}")
    launch = receipt.get("input_hashes_at_launch")
    finish = receipt.get("input_hashes_after_run")
    if launch is not None and finish is not None and launch != finish:
        raise SourceIntegrityError(f"{label} GenCase inputs changed across its receipt")
    return {
        "file": file_record(receipt_path, f"{label} receipt"),
        "request_case_id": request.get("case_id"),
        "request_attempt_id": request.get("attempt_id"),
        "physical_case_id": request.get("physical_case_id"),
        "request_sha256": receipt.get("request_sha256"),
        "output_root": str(root),
        "charged_bytes": receipt.get("bytes"),
        "cpu_core_seconds": receipt.get("cpu_core_seconds"),
        "input_hashes_stable": launch == finish if launch is not None and finish is not None else "UNKNOWN_RECEIPT_FIELDS",
        "checks": checks,
    }


def mass_gate(error_fraction: float) -> str:
    if abs(error_fraction) <= MASS_TARGET_FRACTION:
        return "PREFERRED_WITHIN_1_PERCENT"
    if abs(error_fraction) <= MASS_MARGINAL_FRACTION:
        return "MARGINAL_WITHIN_2_PERCENT"
    return "HARD_FAIL_ABOVE_2_PERCENT"


def run_case(label: str, case: dict[str, Any], observer: Any, scratch_root: Path) -> dict[str, Any]:
    root = directory(case["root"], f"{label} output root")
    generated_xml = root / "generated.xml"
    native = root / "generated.bi4"
    receipt = parse_receipt(case, label)
    source_xml_record = file_record(generated_xml, f"{label} generated XML")
    source_def_record = file_record(case["source_def"], f"{label} source Def")
    source = observer.parse_source_xml(generated_xml)
    native_pre = hash_with_stable_stat(native, f"{label} generated BI4 pre-decode")
    decoded = observer.decode_frame(native, DECODER, scratch_root, 0)
    native_post = hash_with_stable_stat(native, f"{label} generated BI4 post-decode")
    if native_pre["stat_after"] != native_post["stat_before"] or native_pre["stat_before"] != native_post["stat_after"]:
        raise SourceIntegrityError(f"{label} generated BI4 stat changed across decode")
    if decoded["saved_file"]["sha256"] != native_pre["sha256"] or decoded["saved_file"]["bytes"] != native_pre["bytes"]:
        raise SourceIntegrityError(f"{label} decoder-reported BI4 identity differs from guarded pre-hash")

    ids = decoded["ids"]
    blocks = source["blocks"]
    xml_particle_count = sum(int(item["count"]) for item in blocks)
    fluid_blocks = [item for item in blocks if item["kind"] == "fluid"]
    xml_fluid_count = sum(int(item["count"]) for item in fluid_blocks)
    if xml_fluid_count != int(case["expected_fluid_count"]):
        raise ValueError(f"{label} expected fluid count does not match generated XML: {xml_fluid_count}")
    if int(ids.size) != xml_particle_count:
        raise ValueError(f"{label} decoded particle count {ids.size} != XML count {xml_particle_count}")
    expected_ids = observer.np.arange(xml_particle_count, dtype=ids.dtype)
    if not observer.np.array_equal(ids, expected_ids):
        raise ValueError(f"{label} decoded Idp axis is not the exact XML begin/count sequence")
    kind, mkfluid_relative, mk_absolute = observer.assign_particle_ranges(ids, blocks)
    fluid_mask = kind == "fluid"
    if int(fluid_mask.sum()) != xml_fluid_count:
        raise ValueError(f"{label} decoded fluid range count differs from XML")
    if not (observer.np.isfinite(decoded["position"]).all() and observer.np.isfinite(decoded["velocity"]).all() and observer.np.isfinite(decoded["density"]).all()):
        raise ValueError(f"{label} decoded native fields contain non-finite values")
    observations = observer.frame_observables(decoded, source, expected_time_s=0.0)
    massfluid = source["constants"].get("massfluid_kg")
    if massfluid is None:
        raise ValueError(f"{label} generated XML has no massfluid constant")
    sample_mass = float(xml_fluid_count) * float(massfluid)
    mass_error = (sample_mass - OWNER_MASS_KG) / OWNER_MASS_KG
    decoded_fluid_group = observations.get("groups", {}).get("fluid", {})
    decoded_mass = decoded_fluid_group.get("sample_mass_kg")
    if not isinstance(decoded_mass, (int, float)) or abs(float(decoded_mass) - sample_mass) > 1.0e-12:
        raise ValueError(f"{label} observer sample mass disagrees with XML count/massfluid")
    status = "PASS_INITIAL_NATIVE_FIELDS_AND_SAMPLE_MASS"
    return {
        "status": status,
        "case_id": case["case_id"],
        "dp_m": case["dp_m"],
        "source_def": source_def_record,
        "generated_xml": source_xml_record,
        "receipt": receipt,
        "source_particle_ranges": source,
        "native_source_integrity": {
            "status": "PASS_PRE_POST_HASH_AND_COMPLETE_STAT",
            "pre_decode": native_pre,
            "post_decode": native_post,
            "cross_decode_stat_equal": True,
            "full_native_tree_scanned": False,
        },
        "decoded_identity": {
            "particle_count": int(ids.size),
            "id_unique": bool(observer.np.unique(ids).size == ids.size),
            "id_min": int(ids.min()),
            "id_max": int(ids.max()),
            "xml_particle_count": xml_particle_count,
            "xml_fluid_count": xml_fluid_count,
            "fluid_count": int(fluid_mask.sum()),
            "status": "PASS_XML_BEGIN_COUNT_EXACT_ID_COVERAGE",
        },
        "decoded_frame": {
            "decoded_time_s": decoded["decoded_time_s"],
            "time_reference": "generated BI4 metadata; no RunPARTs query; initial-state only",
            "field_digest_sha256": decoded["field_digest_sha256"],
            "decoder_xml_sha256": decoded["decoder_xml_sha256"],
            "position_dtype": decoded["position_dtype"],
            "dynamic_semantics": decoded["dynamic_semantics"],
        },
        "observations": observations,
        "sample_mass_audit": {
            "massfluid_kg_per_particle": float(massfluid),
            "decoded_fluid_sample_mass_kg": sample_mass,
            "continuous_owner_mass_kg": OWNER_MASS_KG,
            "relative_error_vs_continuous_owner": mass_error,
            "gate": mass_gate(mass_error),
            "interpretation": "native particle sample diagnostic; not continuum or rigid-body mass",
            "mass_rescale": False,
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def failure_artifact(output: Path, status: str, reason: str, *, label: str | None = None) -> dict[str, Any]:
    value = {
        "schema": SCHEMA,
        "status": status,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "failure_reason": reason,
        "case": label,
        "scope": {
            "native_initial_only": True,
            "hdf5_read": False,
            "solver_launch": False,
            "full_time_scan": False,
            "typed_conversion": False,
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(output, value)
    return value


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.output.exists():
        raise FileExistsError(f"refuse overwrite immutable output: {args.output}")
    observer = load_observer_module()
    decoder_contract = observer.decoder_source_contract(DECODER_SOURCE)
    if decoder_contract.get("status") != "PASS_SOURCE_ARGC3_OUTPUT_PREFIX_CONTRACT":
        raise RuntimeError("official decoder source contract is not proven")
    semantic_tests = observer.manufactured_semantic_selftests()
    if semantic_tests.get("status") != "PASS":
        raise RuntimeError("observer manufactured semantic tests failed")
    scratch_root = args.scratch_root.expanduser().resolve()
    scratch_root.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {}
    for label, case in CASES.items():
        results[label] = run_case(label, case, observer, scratch_root)
    statuses = [item.get("status") for item in results.values()]
    aggregate_status = "PASS_INITIAL_NATIVE_FIELDS_AND_SAMPLE_MASS" if all(
        item == "PASS_INITIAL_NATIVE_FIELDS_AND_SAMPLE_MASS" for item in statuses
    ) else "UNKNOWN_OR_PARTIAL_INITIAL_NATIVE_QA"
    payload = {
        "schema": SCHEMA,
        "status": aggregate_status,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "family_id": "F1",
        "sentinel_id": "F1-S1",
        "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        "scope": {
            "cases": list(CASES),
            "native_initial_frame_only": True,
            "native_input_files": "exactly generated.bi4 for dp005 and dp0025",
            "full_time_scan": False,
            "hdf5_read": False,
            "vtk_read": False,
            "solver_launch": False,
            "typed_conversion": False,
            "full_native_tree_scanned": False,
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "source": {
            "decoder": decoder_contract,
            "observer_worker": file_record(OBSERVER, "observer worker"),
            "decoder_binary": file_record(DECODER, "official BI4 decoder"),
            "decoder_source": file_record(DECODER_SOURCE, "official BI4 decoder source"),
            "continuous_owner": {
                "mass_kg": OWNER_MASS_KG,
                "authority": "CURRENT owner/physical-binding; not inferred from particle sums",
                "owner_file": file_record(OWNER, "continuous owner file"),
                "physical_binding": file_record(OWNER_BINDING, "continuous physical binding"),
            },
            "independent_proofs": [
                file_record(DP005_PROOF, "dp005 actual support proof"),
                file_record(DP0025_PROOF, "dp0025 actual GenCase proof"),
                file_record(READ_SCOPE_SIDECAR, "read-scope semantic sidecar"),
            ],
        },
        "cases": results,
        "manufactured_semantic_selftests": semantic_tests,
        "conclusion": {
            "initial_native_identity_and_finite_fields": "PASS" if aggregate_status.startswith("PASS") else "UNKNOWN",
            "sample_mass_gate": "RECORDED_PER_CASE",
            "continuum_geometry_equivalence": "UNKNOWN_NOT_PROVED_BY_PARTICLE_DECODE",
            "rigid_body_mass_or_inertia": "UNKNOWN_NOT_INFERRED",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        },
    }
    atomic_json(args.output, payload)
    return payload


def record_for_request(path: Path, label: str) -> dict[str, Any]:
    result = file_record(path, label)
    # Request input_records need the common compact shape; the worker output
    # retains the complete stat boundaries for deferred BI4s.
    return {key: result[key] for key in ("path", "bytes", "mtime_ns", "sha256")}


def build_request() -> dict[str, Any]:
    if QA_REQUEST.exists():
        raise FileExistsError(f"refuse overwrite immutable request: {QA_REQUEST}")
    records_paths = [
        Path(__file__), OBSERVER, PYTHON, DECODER, DECODER_SOURCE, RUNNER, STRICT, RUNTIME, RUNTIME_V6, RUNTIME_V2,
        OWNER, OWNER_BINDING, DP005_PROOF, DP0025_PROOF, READ_SCOPE_SIDECAR,
    ]
    deferred: list[Path] = []
    for label, case in CASES.items():
        records_paths.extend([case["source_def"], case["root"] / "generated.xml", case["root"] / "execution-receipt.json"])
        deferred.append(case["root"] / "generated.bi4")
    records: dict[str, dict[str, Any]] = {}
    for path in records_paths:
        item = record_for_request(path, "initial native QA request input")
        records[item["path"]] = item
    deferred_stats: dict[str, dict[str, Any]] = {}
    deferred_bytes = 0
    for path in deferred:
        stat = stat_record(path, "deferred generated BI4")
        deferred_stats[str(path.resolve())] = {
            **stat,
            "sha256": "PARENT_GUARD_COMPUTED",
            "hash_scope": "parent pre/decode/post; worker emits exact SHA and stat boundaries",
        }
        deferred_bytes += int(stat["bytes"])
    estimated_small = sum(int(item["bytes"]) for item in records.values())
    # Deferred native inputs are guarded and hashed by the parent around the
    # decode; strict v8 therefore requires them in deferred_input_files only,
    # never in the digest-bound input_files list.
    input_files = list(records)
    request = {
        "schema": REQUEST_SCHEMA,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": "F1",
        "sentinel_id": "F1-S1",
        "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        "case_id": QA_CASE_ID,
        "attempt_id": QA_ATTEMPT_ID,
        "launch_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip(),
        "command": [str(PYTHON), str(Path(__file__).resolve()), "--run", "--output", "{attempt_root}/initial-native-qa.json", "--scratch-root", "{attempt_root}/scratch"],
        "cwd": str(REPO),
        "worktree_root": str(REPO),
        "input_files": input_files,
        "input_hashes": {path: item["sha256"] for path, item in records.items()},
        "input_records": records,
        "deferred_input_files": [str(path.resolve()) for path in deferred],
        "deferred_input_file_count": len(deferred),
        "deferred_input_stats": deferred_stats,
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1800,
        "estimated_input_read_bytes": estimated_small + 4 * deferred_bytes,
        "estimated_native_read_bytes": 4 * deferred_bytes,
        "estimated_bi4_read_bytes": 4 * deferred_bytes,
        "estimated_hdf5_read_bytes": 0,
        "estimated_storage_bytes": 2 * 1024 * 1024 * 1024,
        "estimated_peak_memory_bytes": 1024 * 1024 * 1024,
        "estimated_cpu_core_hours": 0.5,
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "gencase_launch": False,
        "solver_launch": False,
        "hdf5_read": False,
        "bi4_read": True,
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(RUNNER),
            "strict_guard": str(STRICT),
            "runtime": str(RUNTIME),
            "launch_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip(),
            "cpu_parent_binding": "required",
            "cpu_threads": 1,
            "gpu": "none",
            "gpu_uuid_lease": "none",
            "solver_launch": "forbidden",
            "hdf5_read": "forbidden",
            "source_output_protection": "all completed GenCase outputs immutable; new QA output only",
            "deferred_native_scope": "exactly two generated.bi4 files; no Part_* tree and no VTK",
        },
        "output_root": str(QA_OUTPUT_ROOT),
        "output": {"atomic": True, "refuse_overwrite": True},
        "source_binding": {
            "schema": SCHEMA,
            "source_cases": {label: {"case_id": case["case_id"], "dp_m": case["dp_m"], "expected_fluid_count": case["expected_fluid_count"], "generated_xml": str(case["root"] / "generated.xml"), "generated_bi4": str(case["root"] / "generated.bi4")} for label, case in CASES.items()},
            "continuous_owner_mass_kg": OWNER_MASS_KG,
            "sample_mass_basis": "decoded fluid particle count × generated XML massfluid; diagnostic only",
            "rigid_body_mass_and_inertia": "UNKNOWN; not inferred from fluid sample sum",
            "no_mass_rescale": True,
            "pre_post_stat": "required for each deferred BI4; mutation rejects source",
            "decoded_fields": ["Idp", "Pos-or-Posd", "Vel", "Rhop"],
            "not_decoded": ["HDF5", "VTK", "pressure/EOS pressure"],
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "qualification_stage": "stage2_f1_s1_owner_centered_initial_native_qa_v1_pending_parent_guard",
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(QA_REQUEST, request)
    return request


def self_test() -> dict[str, Any]:
    observer = load_observer_module()
    manufactured = observer.manufactured_semantic_selftests()
    if manufactured.get("status") != "PASS":
        raise AssertionError("observer manufactured semantic self-tests failed")
    with tempfile.TemporaryDirectory(prefix="ds02-f1-initial-qa-") as temporary:
        path = Path(temporary) / "source.bi4"
        path.write_bytes(b"initial-qa-source")
        before = hash_with_stable_stat(path, "self-test source")
        os.utime(path, ns=(before["mtime_ns"] + 1_000_000, before["mtime_ns"] + 1_000_000))
        after = stat_record(path, "self-test source touched")
        assert before["stat_after"] != after
    return {
        "status": "PASS",
        "checks": [
            "official observer module import registered in sys.modules",
            "manufactured relative/absolute MK, mass, and time semantics",
            "complete pre/post stat mutation detection",
            "no native payload read",
        ],
        "bi4_read": False,
        "hdf5_read": False,
        "solver_launch": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--request", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--scratch-root", type=Path)
    args = parser.parse_args()
    selected = [args.self_test, args.request, args.run]
    if sum(selected) != 1:
        parser.error("choose exactly one operation")
    if args.self_test:
        result = self_test()
    elif args.request:
        result = build_request()
    else:
        if args.output is None or args.scratch_root is None:
            parser.error("--run requires --output and --scratch-root")
        try:
            result = run(args)
        except SourceIntegrityError as exc:
            result = failure_artifact(args.output.resolve(), "FAIL_SOURCE_INTEGRITY", str(exc))
        except observer_exception() as exc:  # type: ignore[misc]
            result = failure_artifact(args.output.resolve(), "UNKNOWN_UNSUPPORTED_SEMANTICS", str(exc))
    print(json.dumps({"status": result.get("status"), "output": str(args.output.resolve()) if args.output else None}, ensure_ascii=False))
    return 0


def observer_exception() -> type[BaseException]:
    """Return the observer's unsupported exception without importing it twice."""
    module = load_observer_module()
    return module.UnsupportedSemantics


if __name__ == "__main__":
    raise SystemExit(main())
