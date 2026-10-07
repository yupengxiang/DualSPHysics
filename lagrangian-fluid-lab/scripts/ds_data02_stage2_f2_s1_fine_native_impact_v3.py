#!/usr/bin/env python3
"""Audit the completed config-closed fine175 native decode without rerunning it.

The v1 sidecar and the v2 audit request are preserved.  C52 was a provenance
failure in the v2 *audit* wrapper: it passed a V2 decoder receipt into the v1
auditor, whose decoder identity gate quite correctly required the old V1 case
id.  This forward-only module keeps the exact V2 decoder identity and repeats
only the small CSV/RunPARTs join itself.  It never calls the consumed v1
``audit`` function, never runs PartVTKOut, and never opens trajectory/H5 data.

The sidecar reports the native observation lower bound.  Native exclusion is
not labelled as spill, domain loss, or a dynamical error; those remain
UNKNOWN.  A future expanded-domain pair is described as an explicit
time-aligned observation plan, not as a result of this audit.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve()
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PARTVTKOUT_DEFAULT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64")
STRACE_DEFAULT = Path("/usr/bin/strace")
RUNTIME_V4_DEFAULT = SCRIPT.parent / "ds_data02_runtime_v4.py"
RUNTIME_V2_DEFAULT = SCRIPT.parent / "ds_data02_runtime_v2.py"
DISPATCH_V4_DEFAULT = SCRIPT.parent / "ds_data02_stage2_dispatch_v4.py"
STRICT_V4_DEFAULT = SCRIPT.parent / "ds_data02_strict_dispatch_v4.py"
V1_SCRIPT_DEFAULT = SCRIPT.parent / "ds_data02_stage2_f2_s1_fine_native_impact_v1.py"

PHYSICAL_CASE_ID = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
FINE_CASE_ID = "F2_S1_FINE_FULL_REFERENCE_DP00855_T4_SAME_CFL_DENSE"
DECODER_CASE_ID = "F2_S1_FINE_NATIVE_IMPACT_AUDIT_V2"
DECODER_ATTEMPT_ID = "f2-s1-fine-partvtkout-v2-primary-002"
AUDIT_CASE_ID = "F2_S1_FINE_NATIVE_IMPACT_AUDIT_V3"
AUDIT_ATTEMPT_ID = "f2-s1-fine-native-impact-v3-audit-003"
OUTPUT_SCHEMA = "ds02.stage2.f2-s1-fine-native-impact-v3.v1"
MOTIVES = {1: "position", 2: "density", 3: "movement"}


class FineAuditError(RuntimeError):
    """Raised when a source identity or completed receipt is not exact."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise FineAuditError(f"{label} is missing: {path}")
    return path


def require_dir(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise FineAuditError(f"{label} is missing: {path}")
    return path


def read_json(value: str | Path, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(value, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FineAuditError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise FineAuditError(f"{label} is not an object: {path}")
    return path, payload


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def load_v1(path: Path):
    spec = importlib.util.spec_from_file_location("ds02_f2_fine_native_impact_v1", path)
    if spec is None or spec.loader is None:
        raise FineAuditError(f"cannot load preserved v1 parser: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def expanded(command: list[Any], output_root: Path) -> list[str]:
    return [str(value).replace("{attempt_root}", str(output_root)) for value in command]


def flag_value(command: list[Any], flag: str, label: str) -> str:
    for index, value in enumerate(command[:-1]):
        if str(value) == flag:
            return str(command[index + 1])
    raise FineAuditError(f"{label} command lacks {flag}")


def stable_input(receipt: dict[str, Any], path: Path, *, label: str) -> str:
    key = str(path.resolve())
    request = receipt.get("request", {})
    declared = request.get("input_sha256", {}).get(key)
    launch = receipt.get("input_hashes_at_launch", {}).get(key)
    finish = receipt.get("input_hashes_after_run", {}).get(key)
    if not declared or declared != launch or declared != finish:
        raise FineAuditError(f"{label} is not stable across decoder launch/end: {key}")
    if sha256(path) != declared:
        raise FineAuditError(f"{label} changed after decoder completion: {key}")
    return str(declared)


def fixed_native_argv(tool: Path, raw_dir: Path, output_root: Path) -> list[str]:
    return [
        str(tool.resolve()), "-dirdata", str(raw_dir.resolve()),
        "-savecsv", str((output_root / "PartOut.csv").resolve()),
        "-saveresume", str((output_root / "resume.csv").resolve()),
        "-createdirs:1", "-csvsep:1",
    ]


def trace_opened(trace_path: Path, needle: str) -> bool:
    text = trace_path.read_text(encoding="utf-8", errors="replace")
    return any(
        needle in line and "openat(" in line and "= " in line and "= -1" not in line
        for line in text.splitlines()
    )


def _source_hash(source: dict[str, Any], field: str) -> str:
    path = Path(source[field]).resolve()
    return sha256(path)


def validate_decoder(decoder_path: Path, source: dict[str, Any]) -> tuple[dict[str, Any], Path, Path, dict[str, Any]]:
    """Validate the exact completed primary002 decoder, including config closure."""
    decoder_path, decoder = read_json(decoder_path, "PartVTKOut primary002 receipt")
    if (decoder.get("schema") != "ds02.execution-receipt.v1" or
            decoder.get("status") != "completed" or decoder.get("returncode") != 0):
        raise FineAuditError("primary002 decoder receipt is not completed code 0")
    output_root = require_dir(decoder.get("output_root", ""), "decoder output root")
    if output_root != decoder_path.parent:
        raise FineAuditError("decoder output_root is inconsistent with receipt path")
    request = decoder.get("request", {})
    if request.get("family_id") != "F2" or request.get("case_id") != DECODER_CASE_ID:
        raise FineAuditError("decoder request case identity differs from exact V2 primary002")
    if request.get("attempt_id") != DECODER_ATTEMPT_ID:
        raise FineAuditError("decoder attempt is not the completed primary002 attempt")
    if request.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise FineAuditError("decoder physical identity differs")
    source_receipt = str(source["solver_receipt_path"])
    if request.get("source_solver_receipt") != source_receipt:
        raise FineAuditError("decoder source solver receipt is not exact")
    source_fields = {
        "source_raw_partout": source["raw_partout"],
        "source_runparts": source["runparts"],
        "source_run_out": source["run_out"],
        "source_generated_xml": source["generated_xml"],
        "source_gencase_receipt": source["gencase_receipt"],
    }
    for field, path in source_fields.items():
        if request.get(field) != str(path):
            raise FineAuditError(f"decoder {field} is not exact")
        declared_key = f"{field}_sha256"
        declared_hash = request.get(declared_key)
        if declared_hash != sha256(Path(path)):
            raise FineAuditError(f"decoder {declared_key} is not the current source digest")
    request_command = request.get("command", [])
    command = [str(value) for value in decoder.get("command", [])]
    if not isinstance(request_command, list) or not isinstance(command, list):
        raise FineAuditError("decoder command is not argv")
    if expanded(request_command, output_root) != command:
        raise FineAuditError("decoder receipt command differs from expanded request")
    trace_prefix = [
        str(STRACE_DEFAULT), "-f", "-qq", "-e", "trace=openat,open,statx",
        "-o", str((output_root / "native-openat.trace").resolve()),
    ]
    if command[:7] != trace_prefix:
        raise FineAuditError("decoder does not use the exact registered strace prefix")
    if len(command) < 8:
        raise FineAuditError("decoder command has no tool argv")
    tool = require_file(command[7], "official PartVTKOut tool in decoder command")
    if tool != PARTVTKOUT_DEFAULT.resolve():
        raise FineAuditError("decoder official tool path differs")
    raw_dir = Path(flag_value(command[8:], "-dirdata", "decoder")).resolve()
    if raw_dir != Path(source["raw_partout"]).parent.resolve():
        raise FineAuditError("decoder -dirdata is not source solver raw root")
    if command[7:] != fixed_native_argv(tool, raw_dir, output_root):
        raise FineAuditError("decoder tool argv is not the exact registered native command")
    if any(str(value).startswith("-threads") for value in command):
        raise FineAuditError("decoder carries unsupported threads flag")
    trace_path = Path(flag_value(command[:7], "-o", "strace")).resolve()
    if trace_path != (output_root / "native-openat.trace").resolve() or not trace_path.is_file():
        raise FineAuditError("decoder trace path is not the guarded output trace")
    if not trace_opened(trace_path, "DsphConfig.xml") or not trace_opened(trace_path, "PartOut_000.obi4"):
        raise FineAuditError("decoder trace lacks successful DsphConfig.xml and PartOut_000.obi4 opens")
    config = tool.parent / "DsphConfig.xml"
    if not config.is_file():
        raise FineAuditError("official DsphConfig.xml is missing")
    if decoder.get("binary_sha256") != sha256(STRACE_DEFAULT):
        raise FineAuditError("receipt binary_sha256 is not the bound strace digest")
    declared = request.get("input_sha256", {})
    files = {str(Path(value).resolve()) for value in request.get("input_files", [])}
    if set(declared) != files or not files:
        raise FineAuditError("decoder input digest map is incomplete")
    for value in sorted(files):
        stable_input(decoder, Path(value), label=Path(value).name)
    for key in (str(tool), str(STRACE_DEFAULT.resolve()), str(config.resolve())):
        if key not in files:
            raise FineAuditError(f"decoder request does not bind runtime source: {key}")
    if any(Path(value).name.startswith("Part_") and Path(value).suffix == ".bi4" for value in files):
        raise FineAuditError("decoder request unexpectedly binds trajectory Part_*.bi4")
    partout_csv = require_file(flag_value(command, "-savecsv", "decoder"), "decoded PartOut.csv")
    resume = require_file(flag_value(command, "-saveresume", "decoder"), "decoder resume CSV")
    if partout_csv.parent != output_root or resume.parent != output_root:
        raise FineAuditError("decoder outputs are outside guarded output root")
    return decoder, partout_csv, resume, {
        "official_tool": {"path": str(tool), "sha256": sha256(tool), "bytes": tool.stat().st_size},
        "strace": {"path": str(STRACE_DEFAULT), "sha256": sha256(STRACE_DEFAULT), "bytes": STRACE_DEFAULT.stat().st_size},
        "config": {"path": str(config), "sha256": sha256(config), "bytes": config.stat().st_size},
        "trace": {"path": str(trace_path), "sha256": sha256(trace_path), "bytes": trace_path.stat().st_size,
                  "opened_DsphConfig_xml": True, "opened_PartOut_000_obi4": True},
        "command": command,
        "tool_argv": command[7:],
    }


def _binding(path: Path) -> dict[str, Any]:
    return {"path": str(path.resolve()), "sha256": sha256(path), "bytes": path.stat().st_size}


def _native_rows(v1: Any, runparts: dict[str, Any], partout: list[dict[str, Any]],
                 solver_receipt: dict[str, Any], source: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    run_out = v1.parse_run_out(source["run_out"])
    command = source["solver_command"]
    expected_case_name = Path(command[1]).name
    if run_out["case_name"] != expected_case_name:
        raise FineAuditError("Run.out CaseName does not match solver generated prefix")
    timeline = runparts["rows"]
    if len(timeline) < 2:
        raise FineAuditError("native timeline is too short for first-gap brackets")
    max_tmax = float(solver_receipt.get("request", {}).get("physical_window_s", [0, timeline[-1]["time_s"]])[1])
    if timeline[0]["time_s"] != 0.0 or timeline[-1]["time_s"] > max_tmax + 1e-6:
        raise FineAuditError("RunPARTs timeline is outside the exact solver window")
    if runparts["totals"]["NpOut"] != len(partout):
        raise FineAuditError("PartOut row count differs from RunPARTs NpOut total")
    rows_by_part: dict[int, Counter[str]] = defaultdict(Counter)
    for row in partout:
        rows_by_part[row["part_out"]][MOTIVES[row["motive_code"]]] += 1
    for native in timeline:
        expected = Counter({"position": native["NpOutPos"], "density": native["NpOutRho"],
                            "movement": native["NpOutMov"]})
        if rows_by_part.get(native["part"], Counter()) != +expected:
            raise FineAuditError(f"PartOut/RunPARTs motive count differs at Part {native['part']}")
    if len({row["idp"] for row in partout}) != len(partout):
        raise FineAuditError("PartOut Idp identity is ambiguous")
    mass = float(source["xml"]["massfluid_kg"])
    denominator = float(source["xml"]["initial_fluid_mass_kg"])
    records: list[dict[str, Any]] = []
    for row in sorted(partout, key=lambda item: (item["part_out"], item["idp"])):
        part = int(row["part_out"])
        if part >= len(timeline) or part < 1:
            raise FineAuditError(f"PartOut frame {part} is outside RunPARTs timeline")
        current = timeline[part]
        previous = timeline[part - 1]
        records.append({
            "idp": row["idp"], "zone": 0,
            "type_semantics": "native PartOut Idp; fluid type is not re-inferred without typed H5",
            "native_motive": MOTIVES[row["motive_code"]], "native_motive_code": row["motive_code"],
            "part_out": part, "first_native_exclusion_frame": part,
            "first_native_exclusion_time_s": current["time_s"],
            "previous_native_frame": previous["part"], "previous_native_time_s": previous["time_s"],
            "first_native_exclusion_bracket_s": [previous["time_s"], current["time_s"]],
            "time_gap_s": current["time_s"] - previous["time_s"],
            "position_m": row["position_m"], "density_kg_m3": row["density_kg_m3"],
            "initial_mass_kg": mass, "mass_fraction_lower_bound": mass / denominator,
            "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN",
        })
    first = min(item["first_native_exclusion_time_s"] for item in records)
    last = max(item["first_native_exclusion_time_s"] for item in records)
    plan = {
        "status": "PLANNED_AFTER_EXPANDED_DOMAIN_PAIR",
        "comparison": "same BI4, motion, physics, geometry, and DP00855/CFL; numerical xyz domain is the sole intended change",
        "alignment": "actual RunPARTs TimeStep [s] values and completed solver receipts; never frame-number alignment",
        "intervals_s": [
            {"name": "pre_first_native_exclusion", "closed_left_open_right": [0.0, first],
             "meaning": "baseline has no observed native exclusion before this time"},
            {"name": "native_exclusion_transition", "closed": [first, last],
             "meaning": "compare cumulative native motive counts and per-ID first-gap brackets"},
            {"name": "post_last_native_exclusion", "open_left_closed_right": [last, timeline[-1]["time_s"]],
             "meaning": "compare retained observer signals only over the common completed time interval"},
        ],
        "required_pair_observables": [
            "RunPARTs cumulative NpOut/NpOutPos/NpOutRho/NpOutMov versus actual time",
            "per-ID PartOut motive, position, and first-gap time bracket",
            "solver Run.csv/registered observer channels for fluid mass/COM/force or impulse when present",
            "rigid-body pose/omega/force channels when present, with their own source receipt and units",
        ],
        "decision_rule": "report observed interval differences and unresolved channels; no mass rescaling and no dynamics/QN/QE credit from native counts",
        "current_source_first_exclusion_time_s": first,
        "current_source_last_exclusion_time_s": last,
        "current_source_final_time_s": timeline[-1]["time_s"],
    }
    return records, {"run_out": run_out, "dynamic_impact_plan": plan}


def audit(solver_receipt_path: Path, decoder_receipt_path: Path, v1_script_path: Path, output: Path) -> dict[str, Any]:
    v1 = load_v1(require_file(v1_script_path, "preserved fine v1 parser"))
    solver_path, solver_receipt = read_json(solver_receipt_path, "fine solver receipt")
    source = v1._solver_sources(solver_path, solver_receipt)
    decoder, partout_csv, resume, closure = validate_decoder(decoder_receipt_path, source)
    runparts = v1.parse_runparts(source["runparts"])
    partout = v1.parse_partout(partout_csv)
    records, derived = _native_rows(v1, runparts, partout, solver_receipt, source)
    mass = float(source["xml"]["massfluid_kg"])
    denominator = float(source["xml"]["initial_fluid_mass_kg"])
    motive_counts = Counter(item["native_motive"] for item in records)
    total_mass = mass * len(records)
    result: dict[str, Any] = {
        "schema": OUTPUT_SCHEMA,
        "status": "NATIVE_IMPACT_RECONCILED",
        "family_id": "F2", "request_case_id": FINE_CASE_ID,
        "physical_case_id": PHYSICAL_CASE_ID,
        "audit_identity": {
            "audit_case_id": AUDIT_CASE_ID,
            "audit_attempt_id": AUDIT_ATTEMPT_ID,
            "decoder_case_id": decoder["request"]["case_id"],
            "decoder_attempt_id": decoder["request"]["attempt_id"],
            "decoder_identity_rule": "exact F2 primary002 V2 decoder receipt; V1 decoder receipt and primary001 are rejected",
        },
        "source": {
            "solver_receipt": _binding(source["solver_receipt_path"]),
            "solver_receipt_request_sha256": solver_receipt.get("request_sha256"),
            "solver_command": source["solver_command"],
            "generated_xml": _binding(source["generated_xml"]),
            "generated_bi4": {"path": str(source["generated_bi4"]),
                              "sha256_from_solver_receipt": source["generated_bi4_sha256"],
                              "hash_policy": "reused completed solver input digest; no duplicate large-file read"},
            "gencase_receipt": _binding(source["gencase_receipt"]),
            "run_out": _binding(source["run_out"]), "runparts": _binding(source["runparts"]),
            "raw_partout": _binding(source["raw_partout"]),
            "decoder_receipt": _binding(decoder_receipt_path),
            "decoded_partout_csv": _binding(partout_csv), "decoder_resume_csv": _binding(resume),
            "decoder_output_scope": {
                "output_root": str(Path(decoder["output_root"]).resolve()),
                "receipt_reported_bytes": decoder.get("bytes"),
                "csv_and_resume_are_direct_children": True,
                "csv_hash_is_bound_here": True,
            },
        },
        "decoder_provenance_v3": {
            "decoder_receipt_sha256": sha256(decoder_receipt_path),
            **closure,
            "source_request_sha256": decoder.get("request_sha256"),
            "source_solver_receipt": str(source["solver_receipt_path"]),
            "source_solver_receipt_sha256": sha256(source["solver_receipt_path"]),
            "source_raw_partout": str(source["raw_partout"]),
            "source_raw_partout_sha256": sha256(source["raw_partout"]),
        },
        "native_decode": {
            "tool": "official PartVTKOut",
            "command": decoder.get("command"),
            "runparts_row_count": len(runparts["rows"]),
            "actual_time_window_s": [runparts["rows"][0]["time_s"], runparts["rows"][-1]["time_s"]],
            "runparts_totals": runparts["totals"], "partout_rows": len(records),
            "motive_counts": dict(sorted(motive_counts.items())), "run_out": derived["run_out"],
        },
        "typed_mass_visibility": {
            "basis": "generated XML MassFluid times generated XML fluid count; diagnostic source-bound proxy",
            "initial_fluid_particle_count": source["xml"]["fluid_count"],
            "initial_mass_per_fluid_particle_kg": mass,
            "initial_fluid_mass_denominator_kg": denominator,
            "native_exclusion_count": len(records),
            "native_excluded_mass_lower_bound_kg": total_mass,
            "native_excluded_mass_fraction_lower_bound": total_mass / denominator,
            "unknown_mass_fraction_gate_0p003": (total_mass / denominator) <= 0.003,
            "interpretation": "mass/source visibility lower bound only; not a bound on physical spill, velocity, impulse, coupling, or dynamics",
        },
        "records": records,
        "observation_impact": {
            "first_native_gap_times_are_known": True,
            "particle_identity_source": "official PartVTKOut Idp joined to the exact completed fine solver receipt and RunPARTs Part",
            "observables_unknown": ["physical destination/fate", "fluid free-surface and pressure response", "rigid/body force and coupled impulse response"],
            "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN",
        },
        "dynamic_impact_plan": derived["dynamic_impact_plan"],
        "source_policy": {
            "h5_opened": False, "trajectory_part_content_opened": False,
            "decoder_raw_partout_source": "official completed primary002 PartOut_000.obi4 decode",
            "dsph_config_bound": True, "official_tool_bound": True,
            "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN",
        },
        "qualification": {"physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED",
                           "trajectory_h5_read": False, "solver_reexecuted": False},
    }
    output = Path(output).resolve()
    if output.exists():
        raise FineAuditError(f"preserve existing impact sidecar: {output}")
    atomic_json(output, result)
    return {"status": result["status"], "output": str(output), "native_exclusion_count": len(records),
            "motive_counts": dict(motive_counts), "mass_fraction_lower_bound": total_mass / denominator}


def prepare(decoder_receipt_path: Path, solver_receipt_path: Path, v1_script_path: Path,
            output_request: Path, partvtkout: Path, strace: Path,
            runtime_v4: Path, runtime_v2: Path, dispatch_v4: Path, strict_v4: Path) -> dict[str, Any]:
    """Prepare only the CPU audit request; PartVTKOut was already completed."""
    v1 = load_v1(require_file(v1_script_path, "preserved fine v1 parser"))
    solver_path, solver = read_json(solver_receipt_path, "fine solver receipt")
    source = v1._solver_sources(solver_path, solver)
    decoder_path, decoder = read_json(decoder_receipt_path, "primary002 decoder receipt")
    if decoder.get("request", {}).get("case_id") != DECODER_CASE_ID or decoder.get("request", {}).get("attempt_id") != DECODER_ATTEMPT_ID:
        raise FineAuditError("decoder is not the exact completed primary002 case/attempt")
    decoder, partout_csv, resume, closure = validate_decoder(decoder_path, source)
    files: list[Path] = [
        SCRIPT, v1_script_path, decoder_path, partout_csv, resume,
        Path(closure["trace"]["path"]), Path(closure["official_tool"]["path"]),
        Path(closure["strace"]["path"]), Path(closure["config"]["path"]),
        runtime_v4, runtime_v2, dispatch_v4, strict_v4,
        source["solver_receipt_path"], source["generated_xml"], source["generated_bi4"],
        source["runparts"], source["run_out"], source["raw_partout"], source["gencase_receipt"],
    ]
    files.extend(Path(value) for value in decoder["request"].get("input_files", []))
    unique = list(dict.fromkeys(Path(value).resolve() for value in files))
    for path in unique:
        require_file(path, f"audit input {path.name}")
    digests = {str(path): sha256(path) for path in unique}
    timeline = v1.parse_runparts(source["runparts"])
    request = {
        "schema": "ds02.request.v1", "family_id": "F2", "case_id": AUDIT_CASE_ID,
        "physical_case_id": PHYSICAL_CASE_ID, "attempt_id": AUDIT_ATTEMPT_ID,
        "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1,
        "max_wall_seconds": 300, "estimated_storage_bytes": 128 * 1024 * 1024,
        "cwd": str(SCRIPT.parent), "worktree_root": str(SCRIPT.parents[2]),
        "command": [str(VENV), str(SCRIPT), "audit", "--solver-receipt", str(source["solver_receipt_path"]),
                    "--decoder-receipt", str(decoder_path), "--v1-script", str(v1_script_path),
                    "--output", "{attempt_root}/f2-s1-fine-native-impact-v3.json"],
        "input_files": [str(path) for path in unique], "input_sha256": digests,
        "source_solver_receipt": str(source["solver_receipt_path"]),
        "source_solver_receipt_sha256": sha256(source["solver_receipt_path"]),
        "source_decoder_receipt": str(decoder_path), "source_decoder_receipt_sha256": sha256(decoder_path),
        "source_decoder_request_sha256": decoder.get("request_sha256"),
        "source_decoder_case_id": DECODER_CASE_ID, "source_decoder_attempt_id": DECODER_ATTEMPT_ID,
        "source_partout_csv": str(partout_csv), "source_partout_csv_sha256": sha256(partout_csv),
        "source_resume_csv": str(resume), "source_resume_csv_sha256": sha256(resume),
        "native_runtime_closure": closure,
        "native_identity_contract": {
            "solver_case_id": FINE_CASE_ID, "physical_case_id": PHYSICAL_CASE_ID,
            "decoder_case_id": DECODER_CASE_ID, "decoder_attempt_id": DECODER_ATTEMPT_ID,
            "raw_parent": str(Path(source["raw_partout"]).parent),
            "source_fields": {field: {"path": str(path), "sha256": sha256(Path(path))}
                              for field, path in {"raw_partout": source["raw_partout"], "runparts": source["runparts"],
                                                   "run_out": source["run_out"], "generated_xml": source["generated_xml"],
                                                   "gencase_receipt": source["gencase_receipt"]}.items()},
            "identity_rule": "exact primary002 receipt/CSV/config/tool; primary001 and V1 decoder identities rejected",
        },
        "expected_native_timeline": {"runparts_rows": len(timeline["rows"]), "runparts_totals": timeline["totals"],
                                      "time_window_s": [timeline["rows"][0]["time_s"], timeline["rows"][-1]["time_s"]]},
        "dynamic_impact_plan": {
            "status": "PLANNED_ONLY_UNTIL_EXPANDED_DOMAIN_PAIR_COMPLETES",
            "pair_control": "same generated BI4/motion, all physical XML settings, and DP00855/CFL; numerical xyz bounds only",
            "alignment": "actual RunPARTs TimeStep [s] and source observer timestamps, no frame-number or mass-rescaled alignment",
            "windows": ["pre_first_native_exclusion", "native_exclusion_transition", "post_last_native_exclusion"],
            "required_observables": ["cumulative native motive counts", "fluid mass/COM/force or impulse observer channels if registered", "rigid pose/omega/force channels if registered"],
            "interpretation": "observed interval differences only; fate, dynamics, QN, and QE remain UNKNOWN",
        },
        "canonical_ready": True, "launch": True, "launch_allowed": True, "execution_allowed": True,
        "foreign_process_protection_required": True, "shared_lease_required": True,
        "solver_launch_forbidden": True, "trajectory_h5_read": False,
        "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED",
        "request_note": "Forward v3 CPU-only audit fixes C52 by exact V2 primary002 decoder identity mapping; it consumes the completed 175-row CSV and does not rerun PartVTKOut, solver, H5, or trajectory data.",
    }
    atomic_json(output_request, request)
    return {"status": "prepared", "request": str(output_request.resolve()), "request_sha256": sha256(output_request),
            "input_count": len(unique), "partout_csv": str(partout_csv), "decoder_receipt": str(decoder_path),
            "config": closure["config"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--decoder-receipt", type=Path, required=True)
    prep.add_argument("--solver-receipt", type=Path, required=True)
    prep.add_argument("--v1-script", type=Path, default=V1_SCRIPT_DEFAULT)
    prep.add_argument("--output-request", type=Path, required=True)
    prep.add_argument("--partvtkout", type=Path, default=PARTVTKOUT_DEFAULT)
    prep.add_argument("--strace", type=Path, default=STRACE_DEFAULT)
    prep.add_argument("--runtime-v4", type=Path, default=RUNTIME_V4_DEFAULT)
    prep.add_argument("--runtime-v2", type=Path, default=RUNTIME_V2_DEFAULT)
    prep.add_argument("--dispatch-v4", type=Path, default=DISPATCH_V4_DEFAULT)
    prep.add_argument("--strict-v4", type=Path, default=STRICT_V4_DEFAULT)
    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--solver-receipt", type=Path, required=True)
    audit_parser.add_argument("--decoder-receipt", type=Path, required=True)
    audit_parser.add_argument("--v1-script", type=Path, default=V1_SCRIPT_DEFAULT)
    audit_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            result = prepare(args.decoder_receipt, args.solver_receipt, args.v1_script, args.output_request,
                             args.partvtkout, args.strace, args.runtime_v4, args.runtime_v2,
                             args.dispatch_v4, args.strict_v4)
        else:
            result = audit(args.solver_receipt, args.decoder_receipt, args.v1_script, args.output)
    except FineAuditError as exc:
        raise SystemExit(f"FineAuditError: {exc}")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
