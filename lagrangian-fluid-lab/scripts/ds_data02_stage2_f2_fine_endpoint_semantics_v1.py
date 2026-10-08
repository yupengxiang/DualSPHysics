#!/usr/bin/env python3
"""Record endpoint counter semantics for the consumed F2 fine native audit.

The v4 native audit is already consumed and immutable.  This forward-only
sidecar re-reads its small JSON/CSV/log/source inputs and records the two
step counters without assigning a cause to their one-step difference:

* ``RunPARTs.csv`` ``Steps`` sums to 91714;
* ``Run.out`` ``Steps of simulation`` reports 91713.

The endpoint claim is limited to the final saved row's ``DtMax`` bracket.  It
does not identify the solver's final integration step, infer an unflushed
step, or reinterpret the old v4 receipt.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any


SCRIPT = Path(__file__).resolve()
WORKTREE_ROOT = SCRIPT.parents[2]
LAB_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
VENV = LAB_ROOT / ".venv/bin/python"
RUNTIME_V4 = SCRIPT.parent / "ds_data02_runtime_v4.py"
RUNTIME_V2 = SCRIPT.parent / "ds_data02_runtime_v2.py"
DISPATCH_V4 = SCRIPT.parent / "ds_data02_stage2_dispatch_v4.py"
STRICT_V4 = SCRIPT.parent / "ds_data02_strict_dispatch_v4.py"

V4_ATTEMPT = DATA_ROOT / (
    "families/F2/F2_S1_FINE_NATIVE_IMPACT_AUDIT_V4/"
    "f2-s1-fine-native-impact-v4-primary-001"
)
V4_OUTPUT = V4_ATTEMPT / "f2-s1-fine-native-impact-v4.json"
V4_RECEIPT = V4_ATTEMPT / "execution-receipt.json"
V4_STDOUT = V4_ATTEMPT / "stdout.log"
V4_REQUEST = WORKTREE_ROOT / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "f2-s1-fine-native-impact-v4/fine-native-impact-v4-request.json"
)
V4_SCRIPT = WORKTREE_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_f2_s1_fine_native_impact_v4.py"
V4_BASE_SCRIPT = WORKTREE_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_f2_s1_fine_native_impact_v1.py"
SOLVER_RECEIPT = DATA_ROOT / (
    "families/F2/F2_S1_FINE_FULL_REFERENCE_DP00855_T4_SAME_CFL_DENSE/"
    "f2-s1-fine-dp00855-same-cfl-full4s-primary-001/execution-receipt.json"
)
SOLVER_OUTPUT = SOLVER_RECEIPT.parent / "solver_output"
RUNPARTS = SOLVER_OUTPUT / "RunPARTs.csv"
RUN_OUT = SOLVER_OUTPUT / "Run.out"
MANIFEST_SCHEMA = "ds02.stage2.f2-s1-fine-endpoint-semantics-manifest.v1"
OUTPUT_SCHEMA = "ds02.stage2.f2-s1-fine-endpoint-semantics.v1"
REQUEST_CASE = "F2_S1_FINE_ENDPOINT_SEMANTICS_V1"
REQUEST_ATTEMPT = "f2-s1-fine-endpoint-semantics-v1-primary-001"
PHYSICAL_CASE = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
SOLVER_CASE = "F2_S1_FINE_FULL_REFERENCE_DP00855_T4_SAME_CFL_DENSE"

SOURCE_AUDIT_FILES = {
    "jsph": WORKTREE_ROOT / "src/source/JSph.cpp",
    "jsph_cpu_single": WORKTREE_ROOT / "src/source/JSphCpuSingle.cpp",
    "jsph_gpu_single": WORKTREE_ROOT / "src/source/JSphGpuSingle.cpp",
}


class EndpointSemanticsError(RuntimeError):
    """Raised when the frozen v4 source or endpoint contract is not closed."""


def sha256(value: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(value).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: Path | str, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise EndpointSemanticsError(f"{label} is missing: {path}")
    return path


def read_json(value: Path | str, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(value, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EndpointSemanticsError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise EndpointSemanticsError(f"{label} is not a JSON object: {path}")
    return path, payload


def record(value: Path | str, label: str) -> dict[str, Any]:
    path = require_file(value, label)
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}


def atomic_json(path: Path, payload: dict[str, Any], *, refuse_existing: bool = True) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if refuse_existing and path.exists():
        raise EndpointSemanticsError(f"refuse to overwrite existing evidence: {path}")
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=WORKTREE_ROOT,
        check=True, capture_output=True, text=True
    ).stdout.strip()


def stable_receipt_input(receipt: dict[str, Any], path: Path, label: str) -> str:
    key = str(path.resolve())
    request = receipt.get("request", {})
    declared = request.get("input_sha256", {}).get(key)
    launch = receipt.get("input_hashes_at_launch", {}).get(key)
    finish = receipt.get("input_hashes_after_run", {}).get(key)
    if not declared or declared != launch or declared != finish:
        raise EndpointSemanticsError(f"{label} lacks equal declared/launch/end hash: {path}")
    actual = sha256(path)
    if actual != declared:
        raise EndpointSemanticsError(f"{label} changed after consumed receipt: {path}")
    return actual


def parse_runparts(path: Path) -> dict[str, Any]:
    path = require_file(path, "RunPARTs.csv")
    lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    reader = csv.DictReader(lines, delimiter=";")
    required = {"Part", "TimeStep [s]", "Steps", "DtMin [s]", "DtMax [s]"}
    if reader.fieldnames is None or not required <= set(reader.fieldnames):
        raise EndpointSemanticsError("RunPARTs.csv header lacks endpoint fields")
    rows: list[dict[str, Any]] = []
    for raw in reader:
        try:
            row = {
                "part": int(raw["Part"].replace(",", "")),
                "time_s": float(raw["TimeStep [s]"]),
                "steps": int(raw["Steps"].replace(",", "")),
                "dt_min_s": float(raw["DtMin [s]"]),
                "dt_max_s": float(raw["DtMax [s]"]),
            }
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise EndpointSemanticsError("RunPARTs.csv has an invalid row") from exc
        if row["part"] != len(rows) or row["steps"] < 0:
            raise EndpointSemanticsError("RunPARTs.csv Part/Steps sequence is invalid")
        if rows and row["time_s"] <= rows[-1]["time_s"]:
            raise EndpointSemanticsError("RunPARTs.csv time is not increasing")
        rows.append(row)
    if not rows:
        raise EndpointSemanticsError("RunPARTs.csv is empty")
    return {
        "path": str(path), "sha256": sha256(path), "row_count": len(rows),
        "steps_sum": sum(row["steps"] for row in rows), "rows": rows,
    }


def parse_run_out(path: Path) -> dict[str, Any]:
    path = require_file(path, "Run.out")
    text = path.read_text(encoding="utf-8", errors="replace")
    summary = re.findall(r"Steps of simulation\.*:\s*([0-9,]+)", text)
    if len(summary) != 1:
        raise EndpointSemanticsError(f"Run.out needs exactly one simulation-step summary, got {len(summary)}")
    table_pattern = re.compile(
        r"^\s*(\d{5})\s+([0-9.]+)\s+([0-9,]+)\s+([0-9,]+)\s+"
    )
    table: list[dict[str, Any]] = []
    for line in text.splitlines():
        match = table_pattern.match(line)
        if match:
            table.append({
                "part": int(match.group(1)), "time_s_printed": float(match.group(2)),
                "total_steps": int(match.group(3).replace(",", "")),
                "steps": int(match.group(4).replace(",", "")),
            })
    if not table:
        raise EndpointSemanticsError("Run.out PART table is absent")
    return {
        "path": str(path), "sha256": sha256(path),
        "simulation_steps": int(summary[0].replace(",", "")),
        "part_row_count": len(table), "rows": table,
    }


def source_excerpt(path: Path, line_no: int) -> dict[str, Any]:
    path = require_file(path, f"source audit file {path.name}")
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if line_no < 1 or line_no > len(lines):
        raise EndpointSemanticsError(f"source audit line is outside file: {path}:{line_no}")
    return {"path": str(path), "sha256": sha256(path), "line": line_no, "text": lines[line_no - 1].strip()}


def source_semantics() -> dict[str, Any]:
    return {
        "runparts_steps_field": source_excerpt(SOURCE_AUDIT_FILES["jsph"], 3001),
        "runparts_steps_write": source_excerpt(SOURCE_AUDIT_FILES["jsph"], 3002),
        "runout_part_total_and_delta": source_excerpt(SOURCE_AUDIT_FILES["jsph"], 3242),
        "runout_summary_nstep": source_excerpt(SOURCE_AUDIT_FILES["jsph"], 3542),
        "gpu_initial_partnstep": source_excerpt(SOURCE_AUDIT_FILES["jsph_gpu_single"], 987),
        "gpu_nstep_increment": source_excerpt(SOURCE_AUDIT_FILES["jsph_gpu_single"], 1010),
        "gpu_partnstep_update": source_excerpt(SOURCE_AUDIT_FILES["jsph_gpu_single"], 1029),
        "cpu_initial_partnstep": source_excerpt(SOURCE_AUDIT_FILES["jsph_cpu_single"], 1176),
        "cpu_nstep_increment": source_excerpt(SOURCE_AUDIT_FILES["jsph_cpu_single"], 1199),
        "cpu_partnstep_update": source_excerpt(SOURCE_AUDIT_FILES["jsph_cpu_single"], 1218),
        "interpretation": {
            "RunPARTs_Steps": "producer computes Nstep-PartNstep for each saved PART",
            "Run_out_part_table": "producer prints Nstep and Nstep-PartNstep separately",
            "Run_out_summary": "producer prints final Nstep",
            "GPU_initialization_observation": "GPU source sets PartNstep=-1 after initial SaveData; this is a source-level candidate for a first-interval offset, not a runtime cause attribution",
            "CPU_initialization_observation": "CPU source sets PartNstep=0 after initial SaveData; backend-specific semantics must remain explicit",
            "runtime_cause_claim": "UNKNOWN; this sidecar does not infer why the observed counters differ by one",
        },
    }


def validate_v4_sources() -> dict[str, Any]:
    v4_receipt_path, receipt = read_json(V4_RECEIPT, "consumed fine v4 execution receipt")
    v4_output_path, output = read_json(V4_OUTPUT, "consumed fine v4 output")
    v4_request_path, request = read_json(V4_REQUEST, "consumed fine v4 request")
    solver_receipt_path, solver_receipt = read_json(SOLVER_RECEIPT, "fine solver receipt")
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise EndpointSemanticsError("consumed v4 receipt is not completed code 0")
    if Path(receipt.get("output_root", "")).resolve() != V4_ATTEMPT.resolve():
        raise EndpointSemanticsError("consumed v4 receipt output root differs")
    if request.get("schema") != "ds02.request.v1" or request.get("family_id") != "F2" or request.get("case_id") != "F2_S1_FINE_NATIVE_IMPACT_AUDIT_V4":
        raise EndpointSemanticsError("consumed v4 request identity differs")
    if request.get("physical_case_id") != PHYSICAL_CASE:
        raise EndpointSemanticsError("consumed v4 request physical identity differs")
    if output.get("schema") != "ds02.stage2.f2-s1-fine-native-impact-v4.v1" or output.get("status") != "NATIVE_IMPACT_RECONCILED":
        raise EndpointSemanticsError("consumed v4 sidecar schema/status differs")
    identity = output.get("audit_identity", {})
    if identity.get("audit_case_id") != "F2_S1_FINE_NATIVE_IMPACT_AUDIT_V4":
        raise EndpointSemanticsError("consumed v4 sidecar identity differs")
    if solver_receipt.get("schema") != "ds02.execution-receipt.v1" or solver_receipt.get("status") != "completed" or solver_receipt.get("returncode") != 0:
        raise EndpointSemanticsError("source fine solver receipt is not completed code 0")
    solver_request = solver_receipt.get("request", {})
    solver_case = solver_request.get("request_case_id", solver_request.get("case_id"))
    if solver_request.get("family_id") != "F2" or solver_case != SOLVER_CASE or solver_request.get("physical_case_id") != PHYSICAL_CASE:
        raise EndpointSemanticsError("source fine solver identity differs")
    endpoint = output.get("native_decode", {}).get("endpoint_contract", {})
    last_step = endpoint.get("last_integration_step", {})
    saved = endpoint.get("saved_endpoint", {})
    requested = endpoint.get("requested_endpoint", {})
    bracket = endpoint.get("saved_transition_bracket_s")
    if requested.get("requested_end_s") != 4.000007783879406 or saved.get("saved_time_s") != 4.000018446461944:
        raise EndpointSemanticsError("consumed v4 endpoint values differ")
    if not isinstance(bracket, list) or len(bracket) != 2 or not (bracket[0] <= requested["requested_end_s"] <= bracket[1]):
        raise EndpointSemanticsError("requested endpoint is not inside saved transition bracket")
    if last_step.get("requested_end_inside_bound") is not True or last_step.get("source") != "RunPARTs.csv final row DtMin [s]/DtMax [s]; bound is conservative, not an exact prior state":
        raise EndpointSemanticsError("consumed v4 last-row bound contract differs")
    canonical_request = receipt.get("request", {}).get("root_canonical_binding", {})
    canonical_request_path = require_file(canonical_request.get("source_request", ""), "consumed v4 canonical source request")
    canonical_request_sha = canonical_request.get("source_sha256")
    if canonical_request_sha != sha256(V4_REQUEST) or canonical_request_sha != sha256(canonical_request_path):
        raise EndpointSemanticsError("consumed v4 canonical request digest differs from the bound request bytes")
    for path, label in ((V4_SCRIPT, "v4 script"), (V4_BASE_SCRIPT, "v4 base script"),
                        (RUNTIME_V4, "runtime v4"), (RUNTIME_V2, "runtime v2"),
                        (DISPATCH_V4, "dispatch v4"), (STRICT_V4, "strict v4"),
                        (RUNPARTS, "RunPARTs.csv"), (RUN_OUT, "Run.out"),
                        (SOLVER_RECEIPT, "solver receipt")):
        stable_receipt_input(receipt, path, label)
    return {
        "v4_output_path": v4_output_path, "v4_output": output,
        "v4_receipt_path": v4_receipt_path, "v4_receipt": receipt,
        "v4_request_path": v4_request_path, "v4_request": request,
        "canonical_request_path": canonical_request_path,
        "canonical_request_sha256": canonical_request_sha,
        "solver_receipt_path": solver_receipt_path, "solver_receipt": solver_receipt,
        "endpoint": endpoint,
    }


def make_manifest(output_dir: Path) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    validate_v4_sources()
    files = [
        SCRIPT, V4_OUTPUT, V4_RECEIPT, V4_STDOUT, V4_REQUEST, V4_SCRIPT, V4_BASE_SCRIPT,
        SOLVER_RECEIPT, RUNPARTS, RUN_OUT, RUNTIME_V4, RUNTIME_V2, DISPATCH_V4, STRICT_V4,
        *SOURCE_AUDIT_FILES.values(),
    ]
    unique: list[Path] = []
    seen: set[str] = set()
    for value in files:
        path = require_file(value, f"endpoint semantics source {Path(value).name}")
        if path.suffix.lower() in {".h5", ".hdf5", ".bi4"} or path.name.startswith("Part_"):
            raise EndpointSemanticsError(f"forbidden H5/trajectory input: {path}")
        if str(path) not in seen:
            seen.add(str(path)); unique.append(path)
    input_hashes = {str(path): sha256(path) for path in unique}
    manifest_path = output_dir / "f2-s1-fine-endpoint-semantics-manifest.json"
    request_path = output_dir / "f2-s1-fine-endpoint-semantics-request.json"
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "PREPARED_CONSUMED_V4_ENDPOINT_SEMANTICS",
        "physical_case_id": PHYSICAL_CASE,
        "solver_case_id": SOLVER_CASE,
        "consumed_v4": {"output": record(V4_OUTPUT, "v4 output"), "receipt": record(V4_RECEIPT, "v4 receipt"), "request": record(V4_REQUEST, "v4 request")},
        "solver_inputs": {"receipt": record(SOLVER_RECEIPT, "solver receipt"), "runparts": record(RUNPARTS, "RunPARTs.csv"), "run_out": record(RUN_OUT, "Run.out")},
        "source_semantics": source_semantics(),
        "input_files": sorted(input_hashes),
        "input_sha256": dict(sorted(input_hashes.items())),
        "read_policy": {"h5_opened": False, "trajectory_opened": False, "solver_started": False, "partvtkout_started": False},
        "qualification": {"physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED"},
        "counter_policy": {
            "runparts_steps_sum": "recorded as emitted interval rows",
            "run_out_summary_steps": "recorded as emitted final Nstep",
            "difference": "reported without causal attribution",
            "last_integration_step_relation": "UNKNOWN",
        },
    }
    atomic_json(manifest_path, manifest)
    request_inputs = dict(input_hashes)
    request_inputs[str(manifest_path)] = sha256(manifest_path)
    request = {
        "schema": "ds02.request.v1", "family_id": "F2", "case_id": REQUEST_CASE,
        "physical_case_id": PHYSICAL_CASE, "attempt_id": REQUEST_ATTEMPT,
        "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1,
        "max_wall_seconds": 300, "estimated_storage_bytes": 32 * 1024 * 1024,
        "cwd": str(SCRIPT.parent), "worktree_root": str(WORKTREE_ROOT),
        "command": [str(VENV), str(SCRIPT), "run", "--manifest", str(manifest_path), "--output", "{attempt_root}/f2-s1-fine-endpoint-semantics-v1.json"],
        "input_files": sorted(request_inputs), "input_sha256": dict(sorted(request_inputs.items())),
        "runtime_binding": {"runtime_v4": record(RUNTIME_V4, "runtime v4"), "runtime_v2": record(RUNTIME_V2, "runtime v2"), "dispatch_v4": record(DISPATCH_V4, "dispatch v4"), "strict_v4": record(STRICT_V4, "strict v4")},
        "source_scope": {"consumed_v4_reused": True, "runparts_and_runout_only": True, "source_counter_audit": True, "h5_or_trajectory_inputs": [], "solver_or_decoder_started": False},
        "source_read_cost": {"h5_bytes_read": 0, "trajectory_bytes_read": 0, "runtime_pre_post_hash_bytes": sum(path.stat().st_size for path in unique) * 2, "estimated_output_bytes": 32 * 1024 * 1024},
        "launch_commit": git_head(), "canonical_ready": True, "launch_owner": "root", "primary_launch_owner": "root",
        "launch": True, "launch_allowed": True, "execution_allowed": True, "shared_lease_required": True, "foreign_process_protection_required": True,
        "solver_launch_forbidden": True, "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED",
        "request_note": "Forward semantics sidecar for consumed fine-impact-v4. It records RunPARTs Steps sum 91714 and Run.out simulation steps 91713 without explaining the difference; endpoint credit is only the final saved row DtMin/DtMax bound containing requested end. Final integration-step relation remains UNKNOWN.",
    }
    atomic_json(request_path, request)
    return {"status": "prepared", "manifest": str(manifest_path), "manifest_sha256": sha256(manifest_path), "request": str(request_path), "request_sha256": sha256(request_path), "source_input_count": len(unique), "guard_input_count": len(request_inputs)}


def run(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest_path, manifest = read_json(manifest_path, "endpoint semantics manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "PREPARED_CONSUMED_V4_ENDPOINT_SEMANTICS":
        raise EndpointSemanticsError("manifest schema/status differs")
    for path_text, expected in manifest.get("input_sha256", {}).items():
        path = require_file(path_text, "manifest source")
        if sha256(path) != expected:
            raise EndpointSemanticsError(f"manifest source changed: {path}")
    source = validate_v4_sources()
    runparts = parse_runparts(RUNPARTS)
    runout = parse_run_out(RUN_OUT)
    endpoint = source["endpoint"]
    saved = endpoint["saved_endpoint"]
    requested = endpoint["requested_endpoint"]
    last_step = endpoint["last_integration_step"]
    if runparts["row_count"] != int(source["v4_output"]["native_decode"]["runparts_row_count"]):
        raise EndpointSemanticsError("RunPARTs row count differs from consumed v4 output")
    if runparts["steps_sum"] != 91714 or runout["simulation_steps"] != 91713:
        raise EndpointSemanticsError("observed frozen counter values differ from expected audit facts")
    if runparts["rows"][-1]["part"] != saved["part"] or runparts["rows"][-1]["time_s"] != saved["saved_time_s"]:
        raise EndpointSemanticsError("RunPARTs final row differs from consumed endpoint")
    final_row = runparts["rows"][-1]
    if final_row["dt_min_s"] != last_step["dt_min_s"] or final_row["dt_max_s"] != last_step["dt_max_s"]:
        raise EndpointSemanticsError("RunPARTs final DtMin/DtMax differs from consumed endpoint")
    if runout["rows"][-1]["total_steps"] != runout["simulation_steps"] or runout["rows"][-1]["part"] != saved["part"]:
        raise EndpointSemanticsError("Run.out final table/summary mismatch")
    if not (endpoint["saved_transition_bracket_s"][0] <= requested["requested_end_s"] <= endpoint["saved_transition_bracket_s"][1]):
        raise EndpointSemanticsError("requested endpoint is outside the saved transition bracket")
    result = {
        "schema": OUTPUT_SCHEMA, "status": "CONSUMED_V4_ENDPOINT_SEMANTICS_RECORDED",
        "manifest": record(manifest_path, "endpoint semantics manifest"),
        "source": {"v4_output": record(V4_OUTPUT, "v4 output"), "v4_receipt": record(V4_RECEIPT, "v4 receipt"), "v4_request": record(V4_REQUEST, "v4 request"), "solver_receipt": record(SOLVER_RECEIPT, "solver receipt"), "runparts": record(RUNPARTS, "RunPARTs.csv"), "run_out": record(RUN_OUT, "Run.out")},
        "endpoint_semantics": {
            "requested_end_s": requested["requested_end_s"], "saved_end_s": saved["saved_time_s"], "saved_part": saved["part"],
            "previous_saved_time_s": saved["previous_saved_time_s"], "saved_transition_bracket_s": endpoint["saved_transition_bracket_s"],
            "saved_row_dt_min_s": final_row["dt_min_s"], "saved_row_dt_max_s": final_row["dt_max_s"],
            "conservative_last_saved_row_bound_s": last_step["conservative_time_bound_s"], "requested_end_inside_saved_row_bound": True,
            "last_integration_step_relation": "UNKNOWN",
            "policy": "last saved row DtMin/DtMax bound only; preserve requested/saved endpoints and all rows; no crop/tolerance or final-step attribution",
        },
        "step_counter_observation": {
            "runparts_row_count": runparts["row_count"], "runparts_steps_sum": runparts["steps_sum"],
            "run_out_part_row_count": runout["part_row_count"], "run_out_simulation_steps": runout["simulation_steps"],
            "difference_runparts_sum_minus_runout_summary": runparts["steps_sum"] - runout["simulation_steps"],
            "relation": "OBSERVED_COUNTER_DIFFERENCE_ONLY",
            "causal_explanation": "UNKNOWN",
            "unflushed_step_inference": False, "zero_based_inference": False,
        },
        "source_semantics": source_semantics(),
        "read_policy": {"h5_opened": False, "trajectory_opened": False, "solver_started": False, "partvtkout_started": False},
        "qualification": {"physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED"},
    }
    atomic_json(output_path.resolve(), result)
    return {"status": result["status"], "output": str(output_path.resolve()), "runparts_steps_sum": runparts["steps_sum"], "run_out_simulation_steps": runout["simulation_steps"], "difference": 1}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare"); prep.add_argument("--output-dir", type=Path, required=True)
    runner = sub.add_parser("run"); runner.add_argument("--manifest", type=Path, required=True); runner.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = make_manifest(args.output_dir) if args.action == "prepare" else run(args.manifest, args.output)
    except EndpointSemanticsError as exc:
        raise SystemExit(f"EndpointSemanticsError: {exc}")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
