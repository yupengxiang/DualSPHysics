#!/usr/bin/env python3
"""Forward V4 F2-S1 GenCase requests after the consumed V3 argv failure.

V3 inputs and requests remain immutable.  This builder reuses the already
prepared source-centred Def/motion bytes, passes the GenCase input prefix with
the final ``.xml`` removed (so the official binary resolves ``*_Def.xml``),
adds explicit ``-threads:1 -ompthreads:1``, and binds the actual adjacent
``DsphConfig.xml``/GenCase binary.  It only writes new request identities and
QA templates; it does not run GenCase or read BI4/VTK/HDF5.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any


REPO = Path(__file__).resolve().parents[5]
V3_PATH = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f2_s1_source_centered_v3_gencase_requests_v1.py"
spec = importlib.util.spec_from_file_location("ds02_f2_source_centered_v3_builder", V3_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot import V3 builder: {V3_PATH}")
v3 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v3
spec.loader.exec_module(v3)


SCHEMA = "ds02.stage2.f2-s1.source-centered-v4-gencase.v1"
REQUEST_SCHEMA = "ds02.request.v1"
STAGE2 = v3.STAGE2
REFERENCE = v3.REFERENCE
MAIN = v3.MAIN
DATA_ROOT = v3.DATA_ROOT
GENCASE = v3.GENCASE
GENCASE_CONFIG = GENCASE.parent / "DsphConfig.xml"
DISPATCH = v3.DISPATCH
STRICT = v3.STRICT
RUNTIME = v3.RUNTIME
PYTHON = v3.PYTHON
SOURCE_DEF = v3.SOURCE_DEF
SOURCE_MOTION = v3.SOURCE_MOTION
QA_WORKER = v3.QA_WORKER
ADAPTER = REFERENCE / "stage2_f1_s1_generated_initial_observer_v1.py"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
DECODER_SOURCE = REPO / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp"
REQUEST_DIR = STAGE2 / "requests/stage2-f2-s1-source-centered-v4-gencase-v1"
MANIFEST_PATH = REFERENCE / "stage2_f2_s1_source_centered_v4_manifest_v1.json"
REPORT_PATH = REFERENCE / "stage2_f2_s1_source_centered_v4_requests_v1.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    return path


def record(path: Path) -> dict[str, Any]:
    path = regular(path)
    value = path.stat()
    return {"path": str(path), "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns), "sha256": sha256(path)}


def atomic_json(path: Path, value: Any) -> None:
    encoded = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    path = path.expanduser().resolve()
    if path.exists():
        if path.read_bytes() == encoded:
            return
        raise FileExistsError(f"refuse to overwrite immutable artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(encoded); handle.flush(); os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def build(launch_commit: str) -> dict[str, Any]:
    if not v3.MANIFEST_PATH.is_file():
        raise FileNotFoundError(f"prepare immutable V3 inputs first: {v3.MANIFEST_PATH}")
    v3_manifest = json.loads(v3.MANIFEST_PATH.read_text(encoding="utf-8"))
    REQUEST_DIR.mkdir(parents=True, exist_ok=True)
    manifest_rungs: list[dict[str, Any]] = []
    requests: list[dict[str, Any]] = []
    for rung in v3_manifest["rungs"]:
        token = str(rung["token"])
        case_id = f"F2_S1_SOURCE_CENTERED_V4_{token.upper()}"
        attempt_id = f"f2-s1-source-centered-v4-{token}-gencase-root-forward-001"
        candidate = Path(rung["candidate_def"]["path"]).resolve()
        motion = Path(rung["motion"]["path"]).resolve()
        if candidate.name.endswith("_Def.xml"):
            input_prefix = candidate.with_suffix("")
        else:
            raise ValueError(f"candidate must end _Def.xml: {candidate}")
        output_root = DATA_ROOT / "families/F2" / case_id / attempt_id
        source_paths = [Path(__file__), V3_PATH, candidate, motion, SOURCE_DEF, SOURCE_MOTION,
                        GENCASE, GENCASE_CONFIG, DISPATCH, STRICT, RUNTIME]
        source_paths = list(dict.fromkeys(regular(path) for path in source_paths))
        records = {str(path): record(path) for path in source_paths}
        request_path = REQUEST_DIR / f"{case_id.lower()}.json"
        if request_path.exists():
            raise FileExistsError(request_path)
        request = {
            "schema": REQUEST_SCHEMA, "kind": "cpu", "cpu_task_kind": "gencase", "family_id": "F2", "sentinel_id": "F2-S1",
            "physical_case_id": v3.PHYSICAL_CASE_ID, "case_id": case_id, "attempt_id": attempt_id, "launch_commit": launch_commit,
            "command": [str(GENCASE), str(input_prefix), "{attempt_root}/generated", "-save:all", "-threads:1", "-ompthreads:1"],
            "cwd": str(candidate.parent), "worktree_root": str(REPO), "input_files": list(records),
            "input_hashes": {path: item["sha256"] for path, item in records.items()}, "input_records": records,
            "deferred_input_files": [], "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": int(rung["wall_seconds"]),
            "estimated_input_read_bytes": sum(int(item["bytes"]) for item in records.values()), "estimated_storage_bytes": int(rung["storage_bytes"]), "estimated_peak_memory_bytes": int(rung["memory_bytes"]),
            "estimated_native_read_bytes": 0, "estimated_bi4_read_bytes": 0, "estimated_hdf5_read_bytes": 0,
            "execution_allowed": True, "launch_disabled": False, "solver_started": False, "gencase_launch": True, "solver_launch": False,
            "hdf5_read": False, "bi4_read": False, "output_root": str(output_root), "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/generated"},
            "source_binding": {
                "schema": "ds02.stage2.f2-s1.source-centered-v4-binding.v1", "v3_request_not_reused": True,
                "source_def": records[str(SOURCE_DEF)], "source_motion": records[str(SOURCE_MOTION)], "candidate_def": records[str(candidate)], "candidate_motion": records[str(motion)],
                "gencase_binary": records[str(GENCASE)], "gencase_config": records[str(GENCASE_CONFIG)],
                "input_prefix": str(input_prefix), "input_prefix_rule": "candidate *_Def.xml with final .xml removed; official GenCase resolves *_Def.xml",
                "representation": {"dp_m": rung["dp_m"], "pointref_m": rung["pointref"], "only_intentional_edits": ["definition@dp", "definition/pointref"]},
                "continuous_owner": v3_manifest["continuous_owner"], "controls_and_drawboxes_frozen": True, "mass_audit_preregistration": rung["lattice"],
                "omp_policy": "-threads:1 -ompthreads:1; parent must record actual OMP/thread report",
                "post_gencase_required": ["generated.xml", "generated.bi4", "execution-receipt.json", "GenCase.out/VTK if present"],
                "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
            },
            "qa_followup": {"worker": str(QA_WORKER.resolve()), "required_after_terminal": True, "native_frame": 0, "no_hdf5_or_full_tree_scan": True,
                            "expected_fluid_count_predicted": rung["fluid_count"], "expected_mass_predicted_kg": rung["lattice"]["predicted_continuum_sample_mass_kg"], "qualification_until_qa": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}},
            "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(DISPATCH), "strict_guard": str(STRICT), "runtime": str(RUNTIME), "launch_commit": launch_commit, "cpu_parent_binding": "required", "gpu": "none", "solver_launch": "forbidden", "hdf5_read": "forbidden", "output_tree_charge": "required; no outside attempt side effects"},
            "qualification_stage": "stage2_f2_s1_source_centered_v4_gencase_preflight_pending_initial_native_qa", "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        }
        atomic_json(request_path, request)
        manifest_rungs.append({"token": token, "request": record(request_path), "input_prefix": str(input_prefix), "rung": rung})
        qa_case_id = f"{case_id}_INITIAL_NATIVE_QA"
        qa_attempt = f"f2-s1-source-centered-v4-{token}-initial-native-qa-root-forward-001"
        generated_root = output_root / "generated"
        qa_output_root = DATA_ROOT / "families/F2" / qa_case_id / qa_attempt
        qa_path = REQUEST_DIR / f"{case_id.lower()}_initial_native_qa.json"
        qa_static = [Path(__file__), V3_PATH, QA_WORKER, ADAPTER, candidate, motion, SOURCE_DEF, SOURCE_MOTION, PYTHON, GENCASE, GENCASE_CONFIG, DECODER, DECODER_SOURCE, DISPATCH, STRICT, RUNTIME, Path("/home/jade/Projects/DualSPHysics/src/source/JPeriodicDef.h"), Path("/home/jade/Projects/DualSPHysics/src/source/JPartDataBi4.h"), Path("/home/jade/Projects/DualSPHysics/src/source/JPartDataBi4.cpp")]
        qa_static = list(dict.fromkeys(regular(path) for path in qa_static))
        qa_records = {str(path): record(path) for path in qa_static}
        qa = {
            "schema": REQUEST_SCHEMA, "kind": "cpu", "cpu_task_kind": "audit", "family_id": "F2", "sentinel_id": "F2-S1", "physical_case_id": v3.PHYSICAL_CASE_ID,
            "case_id": qa_case_id, "attempt_id": qa_attempt, "launch_commit": launch_commit,
            "command": [str(PYTHON), str(QA_WORKER.resolve()), "--generated-xml", str(generated_root / "generated.xml"), "--generated-bi4", str(generated_root / "generated.bi4"), "--gencase-receipt", str(output_root / "execution-receipt.json"), "--candidate-def", str(candidate), "--source-def", str(SOURCE_DEF), "--source-motion", str(SOURCE_MOTION), "--decoder", str(DECODER), "--decoder-source", str(DECODER_SOURCE), "--output", "{attempt_root}/f2_initial_native_qa.json", "--scratch-root", "{attempt_root}/scratch", "--physical-case-id", v3.PHYSICAL_CASE_ID, "--case-id", case_id, "--attempt-id", attempt_id, "--rung-token", token, "--expected-dp", str(rung["dp_m"]), "--expected-fluid-count", str(rung["fluid_count"])],
            "cwd": str(REPO), "worktree_root": str(REPO), "input_files": list(qa_records), "input_hashes": {path: item["sha256"] for path, item in qa_records.items()},
            "deferred_input_files": [str(generated_root / "generated.xml"), str(generated_root / "generated.bi4"), str(output_root / "execution-receipt.json")], "deferred_input_stats": {str(generated_root / "generated.xml"): {"sha256": "PARENT_GUARD_COMPUTED"}, str(generated_root / "generated.bi4"): {"sha256": "PARENT_GUARD_COMPUTED"}, str(output_root / "execution-receipt.json"): {"sha256": "PARENT_GUARD_COMPUTED"}},
            "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 3600, "estimated_native_read_bytes": "PARENT_GUARD_MEASURE_GENERATED_BI4", "estimated_storage_bytes": 2 * 1024**3, "estimated_peak_memory_bytes": 2 * 1024**3,
            "execution_allowed": False, "launch_disabled": True, "solver_started": False, "gencase_launch": False, "solver_launch": False, "hdf5_read": False, "bi4_read": True,
            "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(DISPATCH), "strict_guard": str(STRICT), "runtime": str(RUNTIME), "parent_guard_required": True, "solver_launch": "forbidden", "hdf5_read": "forbidden"},
            "source_binding": {"candidate_def": records[str(candidate)], "source_def": records[str(SOURCE_DEF)], "source_motion": records[str(SOURCE_MOTION)], "gencase_request": record(request_path), "generated_outputs": "deferred until corresponding V4 GenCase receipt", "mass_gate": "whole initial fluid mass against 18.876kg; per-MK audit; no rescale", "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}},
            "output_root": str(qa_output_root), "output": {"atomic": True, "refuse_overwrite": True},
        }
        qa["source_binding"]["expected_total_count_from_terminal_xml"] = True
        atomic_json(qa_path, qa)
        manifest_rungs[-1]["qa_template"] = record(qa_path)
        requests.append({"gencase": str(request_path), "qa_template": str(qa_path), "token": token})
    manifest = {"schema": SCHEMA, "status": "PREPARED_V4_CORRECT_GENCASE_PREFIX_AND_OMP_BINDING", "launch_commit": launch_commit, "v3_manifest": record(v3.MANIFEST_PATH), "rungs": manifest_rungs, "requests": requests, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}
    atomic_json(MANIFEST_PATH, manifest)
    atomic_json(REPORT_PATH, manifest)
    return manifest


def self_test() -> dict[str, Any]:
    assert str(Path("/tmp/F2_Def.xml").with_suffix("")) == "/tmp/F2_Def"
    assert "-ompthreads:1" in ["-threads:1", "-ompthreads:1"]
    return {"status": "PASS", "input_prefix_rule": "remove final .xml from *_Def.xml", "explicit_ompthreads": 1, "gencase_started": False, "native_payload_read": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--build-requests", action="store_true")
    parser.add_argument("--launch-commit")
    args = parser.parse_args()
    if sum((args.self_test, args.build_requests)) != 1:
        parser.error("choose exactly one mode")
    if args.self_test:
        value = self_test()
    else:
        if not args.launch_commit:
            parser.error("--build-requests requires --launch-commit")
        value = build(args.launch_commit)
    print(json.dumps(value if args.self_test else {"status": value["status"], "request_count": len(value["requests"]), "manifest": str(MANIFEST_PATH)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
