#!/usr/bin/env python3
"""Prepare and run one guarded F2-S1 GenCase initial-native QA.

The target is the completed F2-S1 ``dp=.00855`` mass-compatible GenCase
candidate.  The worker decodes exactly its ``generated.bi4`` frame zero with
the source-grounded GenCase ``PeriMode=96`` exception, checks XML begin/count
ranges and finite native fields, and records pre/post SHA plus complete file
stat boundaries.  It never reads HDF5/VTK or starts a solver.

The particle sum is reported against the frozen F2 discrete source-sample
target (21.114 kg).  It is explicitly not a continuum mass or rigid-body
mass, so this QA does not turn the F2 continuum-owner mismatch into a pass.
Request generation hashes only small metadata and records the deferred BI4
stat; the BI4 payload is opened only by a parent-guarded ``--run``.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any


SCHEMA = "ds02.stage2.f2-s1.gencase-initial-native-qa.v1"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
DECODER_SOURCE = REPO / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp"
ADAPTER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f1_s1_generated_initial_observer_v1.py"
BASE_OBSERVER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_native_physical_observer_v2.py"
PERIODIC_HEADER = Path("/home/jade/Projects/DualSPHysics/src/source/JPeriodicDef.h")
PERIODIC_BI4_HEADER = Path("/home/jade/Projects/DualSPHysics/src/source/JPartDataBi4.h")
PERIODIC_BI4_SOURCE = Path("/home/jade/Projects/DualSPHysics/src/source/JPartDataBi4.cpp")
RUNNER = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
RUNTIME_V6 = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py"
RUNTIME_V2 = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
CASE_ROOT = DATA_ROOT / (
    "families/F2/F2_S1_MASSFIT_V4_NEAR_DP0p008550/"
    "f2_s1_massfit_v4_near_dp0p008550-001"
)
SOURCE_DEF = REPO / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
    "stage2_f2_mass_fit_probe_inputs_v4/F2_S1/near_dp0085/0p008550/"
    "F2_S1_MASSFIT_V4_NEAR_DP0p008550_Def.xml"
)
MOTION = CASE_ROOT / "F2_S1_COARSE_PHASE_PROBE_DP01258_motion.dat"
GENERATED_XML = CASE_ROOT / "generated.xml"
GENERATED_BI4 = CASE_ROOT / "generated.bi4"
GENCASE_RECEIPT = CASE_ROOT / "execution-receipt.json"
CASE_ID = "F2_S1_MASSFIT_V4_NEAR_DP0p008550"
ATTEMPT_ID = "f2-s1-gencase-initial-native-qa-v1-root-forward-001"
REQUEST_PATH = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f2-s1-gencase-initial-native-qa-v1/f2_s1_gencase_initial_native_qa_v1.json"
OUTPUT_ROOT = DATA_ROOT / "families/F2/STAGE2_F2_S1_MASSFIT_INITIAL_NATIVE_QA_V1" / ATTEMPT_ID
DISCRETE_SOURCE_SAMPLE_MASS_KG = 21.114
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stat_record(path: Path, label: str) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(f"{label} is not a regular file: {path}")
    value = path.stat()
    return {"path": str(path), "bytes": int(value.st_size), "device": int(value.st_dev),
            "inode": int(value.st_ino), "mode": int(value.st_mode),
            "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns),
            "nlink": int(value.st_nlink)}


def hash_stable(path: Path, label: str) -> dict[str, Any]:
    before = stat_record(path, label)
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    after = stat_record(path, label)
    if before != after or size != before["bytes"]:
        raise RuntimeError(f"{label} changed while hashing")
    return {**after, "sha256": digest.hexdigest(), "stat_before": before, "stat_after": after}


def record(path: Path, label: str) -> dict[str, Any]:
    value = stat_record(path, label)
    value["sha256"] = sha256_file(path)
    return value


def atomic_json(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object: {path}")
    return value


def load_adapter() -> Any:
    name = "ds02_f2_gencase_initial_adapter_v1"
    spec = importlib.util.spec_from_file_location(name, ADAPTER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import GenCase observer adapter: {ADAPTER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _receipt() -> dict[str, Any]:
    receipt = load_json(GENCASE_RECEIPT, "GenCase receipt")
    request = receipt.get("request", {})
    checks = {
        "completed": receipt.get("status") == "completed",
        "returncode_zero": receipt.get("returncode") == 0,
        "gencase_kind": request.get("cpu_task_kind") == "gencase",
        "case_id": request.get("case_id") == CASE_ID,
        "output_root": Path(str(receipt.get("output_root", ""))).resolve() == CASE_ROOT.resolve(),
    }
    if not all(checks.values()):
        raise ValueError(f"GenCase receipt identity/status mismatch: {checks}")
    return {"record": record(GENCASE_RECEIPT, "GenCase receipt"), "checks": checks,
            "request_case_id": request.get("case_id"), "request_attempt_id": request.get("attempt_id"),
            "request_sha256": receipt.get("request_sha256"), "charged_bytes": receipt.get("bytes")}


def _case() -> dict[str, Any]:
    adapter = load_adapter()
    source = adapter.parse_source_xml(GENERATED_XML)
    fluid_count = sum(int(row["count"]) for row in source["blocks"] if row["kind"] == "fluid")
    particle_count = sum(int(row["count"]) for row in source["blocks"])
    return {"case_id": CASE_ID, "attempt_id": ATTEMPT_ID, "dp_m": 0.00855,
            "root": CASE_ROOT, "source_def": SOURCE_DEF, "fluid_count": fluid_count,
            "particle_count": particle_count, "source": source}


def _mass_gate(sample_mass: float) -> dict[str, Any]:
    delta = sample_mass - DISCRETE_SOURCE_SAMPLE_MASS_KG
    fraction = delta / DISCRETE_SOURCE_SAMPLE_MASS_KG
    return {
        "sample_mass_kg": sample_mass,
        "discrete_source_sample_target_kg": DISCRETE_SOURCE_SAMPLE_MASS_KG,
        "relative_to_discrete_source_sample_fraction": fraction,
        "relative_to_discrete_source_sample_percent": 100.0 * fraction,
        "gate": "PASS_DISCRETE_SAMPLE_DIAGNOSTIC_WITHIN_1PCT" if abs(fraction) <= 0.01 else (
            "MARGINAL_DISCRETE_SAMPLE_DIAGNOSTIC_WITHIN_2PCT" if abs(fraction) <= 0.02 else "HARD_FAIL_DISCRETE_SAMPLE_DIAGNOSTIC"),
        "continuum_mass_status": "UNKNOWN_NOT_INFERRED_FROM_PARTICLE_SUM",
        "rigid_body_mass_status": "UNKNOWN_NOT_INFERRED_FROM_PARTICLE_SUM",
        "mass_rescale": False,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    output = args.output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite output: {output}")
    adapter = load_adapter()
    case = _case()
    receipt = _receipt()
    decoder_contract = adapter.decoder_source_contract(DECODER_SOURCE)
    if decoder_contract.get("status") != "PASS_SOURCE_ARGC3_OUTPUT_PREFIX_CONTRACT":
        raise RuntimeError("official decoder source contract is not proven")
    semantic_tests = adapter.manufactured_generated_semantic_selftests()
    if semantic_tests.get("status") != "PASS":
        raise RuntimeError("GenCase semantic self-tests failed")
    source = case["source"]
    periodic = adapter.gencase_periodic_contract(GENERATED_XML, load_json(GENCASE_RECEIPT, "GenCase receipt"))
    native_pre = hash_stable(GENERATED_BI4, "F2 generated BI4 pre-decode")
    scratch = args.scratch_root.expanduser().resolve()
    decoded = adapter.decode_generated_frame(GENERATED_BI4, DECODER, scratch, 0, periodic)
    native_post = hash_stable(GENERATED_BI4, "F2 generated BI4 post-decode")
    if native_pre["sha256"] != native_post["sha256"] or native_pre["bytes"] != native_post["bytes"]:
        raise RuntimeError("F2 generated BI4 content changed across decode")
    if native_pre["stat_after"] != native_post["stat_before"] or native_pre["stat_before"] != native_post["stat_after"]:
        raise RuntimeError("F2 generated BI4 stat changed across decode")
    if decoded["saved_file"]["sha256"] != native_pre["sha256"] or decoded["saved_file"]["bytes"] != native_pre["bytes"]:
        raise RuntimeError("decoder-reported F2 generated BI4 differs from guarded source")
    ids = decoded["ids"]
    if int(ids.size) != int(case["particle_count"]):
        raise RuntimeError(f"decoded particle count {ids.size} != XML count {case['particle_count']}")
    expected_ids = adapter.np.arange(case["particle_count"], dtype=ids.dtype)
    if not adapter.np.array_equal(ids, expected_ids):
        raise RuntimeError("F2 generated Idp axis is not the XML begin/count sequence")
    kind, mkfluid, mk_absolute = adapter.assign_particle_ranges(ids, source["blocks"])
    fluid = kind == "fluid"
    if int(fluid.sum()) != int(case["fluid_count"]):
        raise RuntimeError("F2 decoded fluid count differs from generated XML")
    if not (adapter.np.isfinite(decoded["position"]).all() and adapter.np.isfinite(decoded["velocity"]).all() and adapter.np.isfinite(decoded["density"]).all()):
        raise RuntimeError("F2 generated native fields contain NaN/Inf")
    observations = adapter.frame_observables(decoded, source, expected_time_s=0.0)
    massfluid = source["constants"].get("massfluid_kg")
    if massfluid is None:
        raise RuntimeError("F2 generated XML lacks massfluid")
    mass = float(fluid.sum()) * float(massfluid)
    return {
        "schema": SCHEMA,
        "status": "PASS_INITIAL_NATIVE_FIELDS_AND_DISCRETE_SAMPLE_MASS",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "identity": {"family_id": "F2", "sentinel_id": "F2-S1",
                     "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090",
                     "candidate_case_id": CASE_ID, "candidate_attempt_id": case["attempt_id"]},
        "scope": {"native_initial_frame_only": True, "hdf5_read": False, "vtk_read": False,
                  "solver_launch": False, "full_time_scan": False, "full_native_tree_scanned": False},
        "source": {"source_def": record(SOURCE_DEF, "F2 source Def"),
                   "generated_xml": record(GENERATED_XML, "F2 generated XML"),
                   "motion": record(MOTION, "F2 motion source"), "gencase_receipt": receipt["record"],
                   "decoder": record(DECODER, "official BI4 decoder"),
                   "decoder_source": record(DECODER_SOURCE, "official decoder source"),
                   "periodic_contract": periodic, "decoder_contract": decoder_contract},
        "native_source_integrity": {"status": "PASS_PRE_POST_SHA_AND_COMPLETE_STAT",
                                    "pre_decode": native_pre, "post_decode": native_post,
                                    "sha_equal": True, "cross_decode_stat_equal": True},
        "decoded_identity": {"particle_count": int(ids.size), "id_unique": bool(adapter.np.unique(ids).size == ids.size),
                             "id_min": int(ids.min()), "id_max": int(ids.max()),
                             "xml_particle_count": int(case["particle_count"]), "xml_fluid_count": int(case["fluid_count"]),
                             "fluid_count": int(fluid.sum()), "status": "PASS_XML_BEGIN_COUNT_EXACT_ID_COVERAGE",
                             "mkfluid_relative_values": sorted(set(int(value) for value in mkfluid[fluid].tolist())),
                             "mk_absolute_values": sorted(set(int(value) for value in mk_absolute[fluid].tolist()))},
        "decoded_frame": {"time_s": decoded["decoded_time_s"], "field_digest_sha256": decoded["field_digest_sha256"],
                          "decoder_xml_sha256": decoded["decoder_xml_sha256"], "position_dtype": decoded["position_dtype"],
                          "dynamic_semantics": decoded["dynamic_semantics"]},
        "observations": observations,
        "sample_mass_audit": _mass_gate(mass),
        "scientific_qualification": UNKNOWN,
    }


def _request_record(path: Path) -> dict[str, Any]:
    value = record(path, "request input")
    return {key: value[key] for key in ("path", "bytes", "mtime_ns", "sha256")}


def build_request() -> dict[str, Any]:
    if REQUEST_PATH.exists():
        raise FileExistsError(f"refusing to overwrite request: {REQUEST_PATH}")
    case = _case()
    receipt = _receipt()
    # Parsing generated XML is small and only determines the expected range;
    # it does not open the deferred native BI4.
    small_paths = [Path(__file__), ADAPTER, BASE_OBSERVER, PYTHON, DECODER, DECODER_SOURCE,
                   PERIODIC_HEADER, PERIODIC_BI4_HEADER, PERIODIC_BI4_SOURCE,
                   RUNNER, STRICT, RUNTIME, RUNTIME_V6, RUNTIME_V2,
                   SOURCE_DEF, GENERATED_XML, MOTION, GENCASE_RECEIPT]
    records: dict[str, dict[str, Any]] = {}
    for path in small_paths:
        item = _request_record(path)
        records[item["path"]] = item
    deferred_stat = stat_record(GENERATED_BI4, "deferred F2 generated BI4")
    request = {
        "schema": REQUEST_SCHEMA, "kind": "cpu", "cpu_task_kind": "audit",
        "family_id": "F2", "sentinel_id": "F2-S1",
        "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090",
        "case_id": "F2_S1_Gencase_INITIAL_NATIVE_QA_V1", "attempt_id": ATTEMPT_ID,
        "launch_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True,
                                         capture_output=True, text=True).stdout.strip(),
        "command": [str(PYTHON), str(Path(__file__).resolve()), "--run",
                     "--output", "{attempt_root}/f2-s1-gencase-initial-native-qa.json",
                     "--scratch-root", "{attempt_root}/scratch"],
        "cwd": str(REPO), "worktree_root": str(REPO),
        "input_files": list(records), "input_hashes": {key: value["sha256"] for key, value in records.items()},
        "input_records": records,
        "deferred_input_files": [str(GENERATED_BI4.resolve())],
        "deferred_input_stats": {str(GENERATED_BI4.resolve()): {**deferred_stat,
            "sha256": "PARENT_GUARD_COMPUTED", "hash_scope": "pre/decode/post worker boundary"}},
        "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 1800,
        "estimated_native_read_bytes": int(deferred_stat["bytes"]),
        "estimated_input_read_bytes": int(deferred_stat["bytes"]) + sum(int(item["bytes"]) for item in records.values()),
        "estimated_storage_bytes": 512 * 1024**2, "estimated_peak_memory_bytes": 1024**3,
        "estimated_cpu_core_hours": 0.5,
        # This artifact is a parent-reviewable request.  The builder must not
        # turn a request-generation step into a native read; root may enable a
        # guarded attempt only after reviewing the deferred BI4 reservation.
        "execution_allowed": False, "launch_disabled": True, "solver_started": False,
        "gencase_launch": False, "solver_launch": False, "hdf5_read": False, "bi4_read": True,
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(RUNNER),
                           "strict_guard": str(STRICT), "runtime": str(RUNTIME),
                           "cpu_parent_binding": "required", "gpu": "none", "gpu_uuid_lease": "none",
                           "solver_launch": "forbidden", "hdf5_read": "forbidden",
                           "source_output_protection": "completed GenCase source immutable; new QA output only"},
        "output_root": str(OUTPUT_ROOT), "output": {"atomic": True, "refuse_overwrite": True},
        "source_binding": {"candidate_generated_xml": str(GENERATED_XML.resolve()),
                            "candidate_generated_bi4": str(GENERATED_BI4.resolve()),
                            "candidate_gencase_receipt": str(GENCASE_RECEIPT.resolve()),
                            "candidate_source_def": str(SOURCE_DEF.resolve()),
                            "deferred_bi4_scope": "exactly generated.bi4 frame zero; no Part_* tree, H5, or VTK",
                            "sample_mass_target_kg": DISCRETE_SOURCE_SAMPLE_MASS_KG,
                            "sample_mass_role": "discrete CURRENT source diagnostic only; not continuum/rigid mass",
                            "no_mass_rescale": True, "qualification": UNKNOWN},
        "qualification_stage": "stage2_f2_s1_gencase_initial_native_qa_pending_parent_cpu_guard",
        "qualification": UNKNOWN,
    }
    atomic_json(REQUEST_PATH, request)
    return request


def self_test() -> dict[str, Any]:
    adapter = load_adapter()
    result = adapter.manufactured_generated_semantic_selftests()
    if result.get("status") != "PASS":
        raise AssertionError("GenCase adapter manufactured semantic tests failed")
    with tempfile.TemporaryDirectory(prefix="ds02-f2-initial-qa-") as temporary:
        path = Path(temporary) / "source.bi4"
        path.write_bytes(b"f2-initial-qa")
        before = stat_record(path, "self-test")
        os.utime(path, ns=(before["mtime_ns"] + 1_000_000, before["mtime_ns"] + 1_000_000))
        after = stat_record(path, "self-test touched")
        if before == after:
            raise AssertionError("stat mutation was not observable")
    return {"status": "PASS", "checks": ["GenCase PeriMode narrow contract", "manufactured wrong-mode rejection",
                                             "source stat mutation detection"], "native_payload_read": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--request", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--scratch-root", type=Path)
    args = parser.parse_args()
    if sum((args.self_test, args.request, args.run)) != 1:
        parser.error("choose exactly one of --self-test, --request, or --run")
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False))
        return 0
    if args.request:
        value = build_request()
        print(json.dumps({"status": "READY_PARENT_CPU_GUARD", "request": str(REQUEST_PATH.resolve()),
                          "deferred_bytes": value["deferred_input_stats"][str(GENERATED_BI4.resolve())]["bytes"]}, ensure_ascii=False))
        return 0
    if args.output is None or args.scratch_root is None:
        parser.error("--run requires --output and --scratch-root")
    try:
        value = run(args)
    except Exception as error:
        # A source mutation or unsupported decoder semantics must not become a
        # successful artifact.  Parent can inspect the nonzero receipt.
        print(json.dumps({"status": "FAIL_INITIAL_NATIVE_QA", "error": f"{type(error).__name__}: {error}"}, ensure_ascii=False), file=sys.stderr)
        return 2
    atomic_json(args.output, value)
    print(json.dumps({"status": value["status"], "output": str(args.output.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
