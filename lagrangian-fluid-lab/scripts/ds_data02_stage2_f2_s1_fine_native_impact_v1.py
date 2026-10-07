#!/usr/bin/env python3
"""Prepare and audit the bounded native impact ledger for the F2-S1 fine run.

The fine reference was already solved by the primary GPU guard.  This module
does not read trajectory HDF5 and never reruns a solver.  ``prepare`` emits a
new one-CPU official ``PartVTKOut`` request bound to that completed solver
receipt.  ``audit`` consumes the completed decoder receipt, the decoded CSV,
and the small ``RunPARTs``/``Run.out``/XML files.  It joins every native
``Idp`` to its actual saved ``Part`` and time and computes only a lower bound
on typed source mass whose observation ended.  Native exclusion is not
classified as physical spill and no dynamics, QN, or QE credit is emitted.

This is a new namespace.  It deliberately does not import or rewrite any of
the consumed Stage2 omission sidecars.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
PRIMARY_WORKTREE = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
LAB_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab")
PARTVTKOUT_DEFAULT = LAB_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64"
DISPATCH_V4_DEFAULT = PRIMARY_WORKTREE / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py"
STRICT_V4_DEFAULT = PRIMARY_WORKTREE / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v4.py"
RUNTIME_V4_DEFAULT = PRIMARY_WORKTREE / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v4.py"

FINE_CASE_ID = "F2_S1_FINE_FULL_REFERENCE_DP00855_T4_SAME_CFL_DENSE"
PHYSICAL_CASE_ID = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
MOTIVES = {1: "position", 2: "density", 3: "movement"}
RUNPART_FIELDS = ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov")
CASE_RE = re.compile(r'CaseName="([^"]+)"')
MAP_RE = re.compile(r"MapRealPos\((border|final)\)=\(([^)]*)\)-\(([^)]*)\)")


class EvidenceError(RuntimeError):
    """Raised for missing, changed, or ambiguous source evidence."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(path: str | Path, label: str) -> Path:
    value = Path(path).resolve()
    if not value.is_file():
        raise EvidenceError(f"{label} is missing: {value}")
    return value


def require_dir(path: str | Path, label: str) -> Path:
    value = Path(path).resolve()
    if not value.is_dir():
        raise EvidenceError(f"{label} is missing: {value}")
    return value


def read_json(path: str | Path, label: str) -> tuple[Path, dict[str, Any]]:
    value = require_file(path, label)
    try:
        data = json.loads(value.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - error text is evidence
        raise EvidenceError(f"{label} is invalid JSON: {value}: {exc}") from exc
    if not isinstance(data, dict):
        raise EvidenceError(f"{label} is not a JSON object: {value}")
    return value, data


def binding(path: str | Path, *, declared_sha256: str | None = None,
            label: str = "evidence") -> dict[str, Any]:
    value = require_file(path, label)
    actual = sha256(value)
    if declared_sha256 is not None and actual != declared_sha256:
        raise EvidenceError(f"{label} hash differs from binding: {value}")
    return {"path": str(value), "sha256": actual, "bytes": value.stat().st_size,
            "mtime_ns": value.stat().st_mtime_ns}


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
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


def command_value(command: list[str], flag: str) -> str:
    for index, value in enumerate(command[:-1]):
        if value == flag:
            return command[index + 1]
    raise EvidenceError(f"command is missing {flag}")


def expanded_command(request_command: list[str], output_root: Path) -> list[str]:
    return [str(value).replace("{attempt_root}", str(output_root))
            for value in request_command]


def _input_digest(receipt: dict[str, Any], path: Path, *, label: str,
                  rehash: bool = True) -> str:
    key = str(Path(path).resolve())
    request = receipt.get("request", {})
    declared = request.get("input_sha256", {}).get(key)
    launch = receipt.get("input_hashes_at_launch", {}).get(key)
    finish = receipt.get("input_hashes_after_run", {}).get(key)
    if not declared or declared != launch or declared != finish:
        raise EvidenceError(f"{label} input digest is not stable: {key}")
    if rehash and sha256(path) != declared:
        raise EvidenceError(f"{label} changed after its guarded execution: {key}")
    return str(declared)


def _descendants(root: ET.Element, tag: str):
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] == tag:
            yield node


def parse_generated_xml(path: Path) -> dict[str, Any]:
    path = require_file(path, "generated XML")
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise EvidenceError(f"generated XML is invalid: {path}") from exc
    fluid = next((item for item in _descendants(root, "fluid")
                  if "count" in item.attrib), None)
    mass = next((item for item in _descendants(root, "massfluid")
                 if "value" in item.attrib), None)
    if fluid is None or mass is None:
        raise EvidenceError("generated XML lacks fluid count or MassFluid")
    try:
        fluid_count = int(fluid.attrib["count"])
        massfluid = float(mass.attrib["value"])
    except (KeyError, TypeError, ValueError) as exc:
        raise EvidenceError("generated XML fluid mass metadata is invalid") from exc
    if fluid_count <= 0 or not math.isfinite(massfluid) or massfluid <= 0:
        raise EvidenceError("generated XML fluid mass metadata is nonpositive")
    parameters = next(_descendants(root, "parameters"), None)
    if parameters is None:
        raise EvidenceError("generated XML parameters are missing")
    controls: dict[str, float] = {}
    for item in _descendants(parameters, "parameter"):
        key = item.attrib.get("key")
        if key in {"Boundary", "TimeMax", "TimeOut", "RhopOutMin", "RhopOutMax"}:
            try:
                controls[key] = float(item.attrib["value"])
            except (KeyError, TypeError, ValueError) as exc:
                raise EvidenceError(f"generated XML control {key} is invalid") from exc
    domain = next(_descendants(parameters, "simulationdomain"), None)
    if domain is None:
        raise EvidenceError("generated XML simulationdomain is missing")
    bounds: dict[str, list[float]] = {}
    for name in ("posmin", "posmax"):
        node = next((item for item in domain if item.tag.rsplit("}", 1)[-1] == name), None)
        if node is None:
            raise EvidenceError(f"generated XML simulationdomain/{name} is missing")
        try:
            values = [float(node.attrib[axis]) for axis in "xyz"]
        except (KeyError, TypeError, ValueError) as exc:
            raise EvidenceError(f"generated XML simulationdomain/{name} is invalid") from exc
        if not all(math.isfinite(value) for value in values):
            raise EvidenceError(f"generated XML simulationdomain/{name} is nonfinite")
        bounds[name] = values
    return {
        "path": str(path),
        "sha256": sha256(path),
        "fluid_count": fluid_count,
        "massfluid_kg": massfluid,
        "initial_fluid_mass_kg": fluid_count * massfluid,
        "controls": controls,
        "simulationdomain": bounds,
    }


def parse_run_out(path: Path) -> dict[str, Any]:
    path = require_file(path, "Run.out")
    text = path.read_text(encoding="utf-8", errors="replace")
    cases = CASE_RE.findall(text)
    if len(cases) != 1:
        raise EvidenceError("Run.out CaseName is missing or ambiguous")
    maps: dict[str, list[list[float]]] = {}
    for match in MAP_RE.finditer(text):
        if match.group(1) in maps:
            raise EvidenceError(f"Run.out repeats MapRealPos({match.group(1)})")
        try:
            low = [float(value) for value in match.group(2).split(",")]
            high = [float(value) for value in match.group(3).split(",")]
        except ValueError as exc:
            raise EvidenceError("Run.out MapRealPos is invalid") from exc
        if len(low) != 3 or len(high) != 3 or any(a >= b for a, b in zip(low, high)):
            raise EvidenceError("Run.out MapRealPos bounds are invalid")
        maps[match.group(1)] = [low, high]
    if set(maps) != {"border", "final"}:
        raise EvidenceError("Run.out lacks exactly border and final MapRealPos")
    return {"path": str(path), "sha256": sha256(path), "case_name": cases[0],
            "map_real_pos": maps}


def parse_runparts(path: Path) -> dict[str, Any]:
    path = require_file(path, "RunPARTs.csv")
    lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    reader = csv.DictReader(lines, delimiter=";")
    required = {"Part", "TimeStep [s]", *RUNPART_FIELDS}
    if reader.fieldnames is None or not required <= set(reader.fieldnames):
        raise EvidenceError("RunPARTs header is incomplete")
    rows: list[dict[str, Any]] = []
    totals = {field: 0 for field in RUNPART_FIELDS}
    for raw in reader:
        try:
            part = int(raw["Part"].replace(",", ""))
            time_s = float(raw["TimeStep [s]"])
            counts = {field: int(raw[field].replace(",", "")) for field in RUNPART_FIELDS}
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise EvidenceError("RunPARTs row is invalid") from exc
        if part != len(rows) or not math.isfinite(time_s):
            raise EvidenceError("RunPARTs Part sequence/time is invalid")
        if rows and time_s <= rows[-1]["time_s"]:
            raise EvidenceError("RunPARTs time is not strictly increasing")
        if any(value < 0 for value in counts.values()):
            raise EvidenceError("RunPARTs has a negative exclusion count")
        if counts["NpOut"] != sum(counts[field] for field in RUNPART_FIELDS[1:]):
            raise EvidenceError("RunPARTs NpOut does not equal motive counts")
        row = {"part": part, "time_s": time_s, **counts}
        rows.append(row)
        for field, value in counts.items():
            totals[field] += value
    if not rows:
        raise EvidenceError("RunPARTs has no rows")
    return {"path": str(path), "sha256": sha256(path), "rows": rows,
            "totals": totals}


def parse_partout(path: Path) -> list[dict[str, Any]]:
    path = require_file(path, "decoded PartOut.csv")
    with path.open(newline="", encoding="utf-8", errors="replace") as stream:
        reader = csv.DictReader(stream)
        names = {name.strip() for name in (reader.fieldnames or [])}
        required = {"Idp", "PartOut", "Motive", "Pos.x [m]", "Pos.y [m]",
                    "Pos.z [m]", "Rhop [kg/m^3]"}
        if not required <= names:
            raise EvidenceError("decoded PartOut header is incomplete")
        rows: list[dict[str, Any]] = []
        for raw in reader:
            item = {key.strip(): (value or "").strip()
                    for key, value in raw.items() if key and value is not None}
            try:
                row = {
                    "idp": int(item["Idp"]),
                    "part_out": int(item["PartOut"]),
                    "motive_code": int(item["Motive"]),
                    "position_m": [float(item[f"Pos.{axis} [m]"]) for axis in "xyz"],
                    "density_kg_m3": float(item["Rhop [kg/m^3]"]),
                }
            except (KeyError, TypeError, ValueError) as exc:
                raise EvidenceError("decoded PartOut row is invalid") from exc
            if row["idp"] < 0 or row["part_out"] < 1 or row["motive_code"] not in MOTIVES:
                raise EvidenceError("decoded PartOut identity or motive is invalid")
            if not all(math.isfinite(value) for value in (*row["position_m"], row["density_kg_m3"])):
                raise EvidenceError("decoded PartOut state is nonfinite")
            rows.append(row)
    if not rows:
        raise EvidenceError("decoded PartOut has no records")
    if len({row["idp"] for row in rows}) != len(rows):
        raise EvidenceError("decoded PartOut has duplicate Idp records")
    return rows


def _solver_sources(receipt_path: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    if receipt.get("schema") != "ds02.execution-receipt.v1":
        raise EvidenceError("unsupported solver receipt schema")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise EvidenceError("fine reference solver receipt is not completed")
    request = receipt.get("request", {})
    if request.get("family_id") != "F2" or request.get("case_id") != FINE_CASE_ID:
        raise EvidenceError("fine reference solver request case identity differs")
    if request.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise EvidenceError("fine reference solver request physical identity differs")
    solver_root = require_dir(receipt.get("output_root", ""), "solver output root")
    if solver_root != receipt_path.parent:
        raise EvidenceError("solver receipt output_root is inconsistent")
    command = request.get("command", [])
    if not isinstance(command, list) or len(command) < 3:
        raise EvidenceError("solver command is incomplete")
    prefix = require_file(str(command[1]) + ".xml", "solver generated XML")
    generated_bi4 = require_file(str(command[1]) + ".bi4", "solver generated BI4")
    run_out = require_file(solver_root / "solver_output" / "Run.out", "solver Run.out")
    runparts = require_file(solver_root / "solver_output" / "RunPARTs.csv", "solver RunPARTs")
    raw_partout = require_file(solver_root / "solver_output" / "data" / "PartOut_000.obi4",
                               "solver raw PartOut")
    gencase_receipt = request.get("gencase_receipt")
    if not gencase_receipt:
        raise EvidenceError("solver request lacks candidate GenCase receipt")
    gencase_receipt_path = require_file(gencase_receipt, "candidate GenCase receipt")
    xml = parse_generated_xml(prefix)
    return {
        "solver_receipt_path": receipt_path,
        "solver_receipt": receipt,
        "solver_root": solver_root,
        "solver_command": command,
        "generated_xml": prefix,
        "generated_bi4": generated_bi4,
        "run_out": run_out,
        "runparts": runparts,
        "raw_partout": raw_partout,
        "gencase_receipt": gencase_receipt_path,
        "xml": xml,
    }


def prepare_request(*, solver_receipt_path: Path, output: Path,
                    partvtkout: Path = PARTVTKOUT_DEFAULT,
                    dispatch_v4: Path = DISPATCH_V4_DEFAULT,
                    strict_v4: Path = STRICT_V4_DEFAULT,
                    runtime_v4: Path = RUNTIME_V4_DEFAULT,
                    worktree_root: Path = PRIMARY_WORKTREE) -> dict[str, Any]:
    solver_receipt_path, receipt = read_json(solver_receipt_path, "fine solver receipt")
    source = _solver_sources(solver_receipt_path, receipt)
    partvtkout = require_file(partvtkout, "official PartVTKOut")
    dispatch_v4 = require_file(dispatch_v4, "Stage2 v4 dispatch")
    strict_v4 = require_file(strict_v4, "Stage2 strict v4 dispatch")
    runtime_v4 = require_file(runtime_v4, "Stage2 v4 runtime")
    worktree_root = Path(worktree_root).resolve()
    files = [SCRIPT, dispatch_v4, strict_v4, runtime_v4, partvtkout,
             source["raw_partout"], source["runparts"], source["run_out"],
             solver_receipt_path, source["generated_xml"], source["gencase_receipt"]]
    unique: list[Path] = []
    seen: set[str] = set()
    for path in files:
        path = Path(path).resolve()
        if str(path) not in seen:
            seen.add(str(path))
            unique.append(path)
    output = Path(output).resolve()
    request = {
        "schema": "ds02.request.v1",
        "family_id": "F2",
        "case_id": "F2_S1_FINE_NATIVE_IMPACT_AUDIT_V1",
        "physical_case_id": PHYSICAL_CASE_ID,
        "attempt_id": "f2-s1-fine-native-impact-v1",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 300,
        "estimated_storage_bytes": 128 * 2**20,
        "command": [
            str(partvtkout.resolve()),
            "-dirdata", str(source["raw_partout"].parent.resolve()),
            "-savecsv", "{attempt_root}/PartOut.csv",
            "-saveresume", "{attempt_root}/resume.csv",
            "-createdirs:1", "-csvsep:1",
        ],
        "cwd": str(worktree_root),
        "worktree_root": str(worktree_root),
        "input_files": [str(path) for path in unique],
        "input_sha256": {str(path): sha256(path) for path in unique},
        "source_solver_receipt": str(solver_receipt_path),
        "source_solver_receipt_sha256": sha256(solver_receipt_path),
        "source_generated_xml": str(source["generated_xml"]),
        "source_generated_xml_sha256": source["xml"]["sha256"],
        "source_raw_partout": str(source["raw_partout"]),
        "source_raw_partout_sha256": sha256(source["raw_partout"]),
        "source_runparts": str(source["runparts"]),
        "source_runparts_sha256": sha256(source["runparts"]),
        "source_run_out": str(source["run_out"]),
        "source_run_out_sha256": sha256(source["run_out"]),
        "source_gencase_receipt": str(source["gencase_receipt"]),
        "source_gencase_receipt_sha256": sha256(source["gencase_receipt"]),
        "source_identity": {
            "family_id": "F2",
            "request_case_id": FINE_CASE_ID,
            "physical_case_id": PHYSICAL_CASE_ID,
            "generated_xml_sha256": source["xml"]["sha256"],
            "fluid_particle_count": source["xml"]["fluid_count"],
            "massfluid_kg": source["xml"]["massfluid_kg"],
            "initial_fluid_mass_kg": source["xml"]["initial_fluid_mass_kg"],
            "native_timeline_expected_from_solver_receipt": receipt.get("request", {}).get("expected_native_frames"),
            "native_timeline_actual_at_request": {
                "runparts_rows": None,
                "note": "filled by audit from the completed solver's RunPARTs; no frame count is inferred from request cadence",
            },
        },
        "native_contract": {
            "official_tool": "PartVTKOut",
            "threads_flag": "forbidden; shared runner sets OMP_NUM_THREADS=1",
            "expected_runparts_totals_at_prepare": parse_runparts(source["runparts"])["totals"],
            "expected_partout_rows_at_prepare": parse_runparts(source["runparts"])["totals"]["NpOut"],
            "time_source": "RunPARTs.csv Part/TimeStep [s] bound to same solver output_root",
            "particle_identity": "decoded PartOut Idp, exact source solver receipt and raw PartOut digest",
        },
        "output_plan": {
            "csv": "{attempt_root}/PartOut.csv",
            "resume": "{attempt_root}/resume.csv",
            "impact_sidecar": "created by audit only after completed decoder receipt",
        },
        "trajectory_h5_read": False,
        "solver_launch_forbidden": True,
        "gpu_launch": False,
        "physical_fate": "UNKNOWN",
        "dynamical_impact": "UNKNOWN",
        "QN": "NOT_ASSESSED",
        "QE": "NOT_ASSESSED",
        "qualification_claim": "none; native accounting and typed mass visibility lower bound only",
    }
    if output.exists():
        old = json.loads(output.read_text(encoding="utf-8"))
        if old != request:
            raise EvidenceError(f"refusing to overwrite existing request: {output}")
    else:
        atomic_json(output, request)
    return {"status": "prepared", "request": str(output),
            "request_sha256": sha256(output),
            "expected_totals": request["native_contract"]["expected_runparts_totals_at_prepare"]}


def _validate_decoder(*, decoder_path: Path, source: dict[str, Any]) -> tuple[dict[str, Any], Path, Path]:
    decoder_path, decoder = read_json(decoder_path, "PartVTKOut receipt")
    if decoder.get("schema") != "ds02.execution-receipt.v1":
        raise EvidenceError("unsupported PartVTKOut receipt schema")
    if decoder.get("status") != "completed" or decoder.get("returncode") != 0:
        raise EvidenceError("PartVTKOut receipt is not completed")
    output_root = require_dir(decoder.get("output_root", ""), "PartVTKOut output root")
    request = decoder.get("request", {})
    request_command = request.get("command", [])
    command = decoder.get("command", [])
    if expanded_command(request_command, output_root) != command:
        raise EvidenceError("PartVTKOut command differs from its request")
    if not command or Path(command[0]).name != "PartVTKOut_linux64":
        raise EvidenceError("decoder is not official PartVTKOut_linux64")
    if decoder.get("binary_sha256") != sha256(Path(command[0])):
        raise EvidenceError("PartVTKOut binary digest changed")
    if "-threads:1" in command or any(value.startswith("-threads:") for value in command):
        raise EvidenceError("PartVTKOut request must not carry an unsupported threads flag")
    raw_dir = source["raw_partout"].parent
    if Path(command_value(command, "-dirdata")).resolve() != raw_dir.resolve():
        raise EvidenceError("PartVTKOut -dirdata is not the solver raw data root")
    partout_csv = require_file(command_value(command, "-savecsv"), "decoded PartOut.csv")
    resume = require_file(command_value(command, "-saveresume"), "PartVTKOut resume CSV")
    if partout_csv.parent != output_root or resume.parent != output_root:
        raise EvidenceError("decoder outputs are outside the guarded output root")
    files = [Path(value).resolve() for value in request.get("input_files", [])]
    declared = request.get("input_sha256", {})
    if not files or set(declared) != {str(path) for path in files}:
        raise EvidenceError("decoder input digest map is incomplete")
    required = [source["raw_partout"], source["runparts"], source["run_out"],
                source["solver_receipt_path"], source["generated_xml"], source["gencase_receipt"]]
    for path in required:
        path = Path(path).resolve()
        if path not in files:
            raise EvidenceError(f"decoder request does not bind source: {path}")
        _input_digest(decoder, path, label=path.name)
    raw_declared = declared.get(str(source["raw_partout"]))
    if raw_declared != sha256(source["raw_partout"]):
        raise EvidenceError("raw PartOut digest changed")
    if decoder.get("request", {}).get("source_solver_receipt") != str(source["solver_receipt_path"]):
        raise EvidenceError("decoder source solver receipt path is not exact")
    return decoder, partout_csv, resume


def audit(*, solver_receipt_path: Path, decoder_receipt_path: Path,
          output: Path) -> dict[str, Any]:
    solver_receipt_path, solver_receipt = read_json(solver_receipt_path, "fine solver receipt")
    source = _solver_sources(solver_receipt_path, solver_receipt)
    decoder, partout_csv, resume = _validate_decoder(decoder_path=decoder_receipt_path, source=source)
    run_out = parse_run_out(source["run_out"])
    runparts = parse_runparts(source["runparts"])
    partout = parse_partout(partout_csv)
    command = source["solver_command"]
    expected_case_name = Path(command[1]).name
    if run_out["case_name"] != expected_case_name:
        raise EvidenceError("Run.out CaseName does not match the solver generated prefix")
    if len(runparts["rows"]) < 2:
        raise EvidenceError("native timeline is too short for first-gap brackets")
    max_tmax = float(solver_receipt["request"].get("physical_window_s", [0, runparts["rows"][-1]["time_s"]])[1])
    if runparts["rows"][0]["time_s"] != 0.0 or runparts["rows"][-1]["time_s"] > max_tmax + 1e-6:
        raise EvidenceError("RunPARTs timeline is outside the exact solver window")
    expected_totals = {field: int(value) for field, value in runparts["totals"].items()}
    if expected_totals["NpOut"] != len(partout):
        raise EvidenceError("PartOut row count differs from RunPARTs NpOut total")
    rows_by_part: dict[int, Counter[str]] = defaultdict(Counter)
    for row in partout:
        rows_by_part[row["part_out"]][MOTIVES[row["motive_code"]]] += 1
    for native in runparts["rows"]:
        observed = rows_by_part.get(native["part"], Counter())
        expected = Counter({"position": native["NpOutPos"],
                            "density": native["NpOutRho"],
                            "movement": native["NpOutMov"]})
        if observed != +expected:
            raise EvidenceError(f"PartOut/RunPARTs motive count differs at Part {native['part']}")
    if len({row["idp"] for row in partout}) != len(partout):
        raise EvidenceError("PartOut Idp identity is ambiguous")
    timeline = runparts["rows"]
    mass = float(source["xml"]["massfluid_kg"])
    denominator = float(source["xml"]["initial_fluid_mass_kg"])
    records: list[dict[str, Any]] = []
    for row in sorted(partout, key=lambda item: (item["part_out"], item["idp"])):
        part = int(row["part_out"])
        if part >= len(timeline):
            raise EvidenceError(f"PartOut frame {part} is outside RunPARTs timeline")
        current = timeline[part]
        previous = timeline[part - 1]
        records.append({
            "idp": row["idp"],
            "zone": 0,
            "type_semantics": "native PartOut Idp; fluid type is not re-inferred without typed H5",
            "native_motive": MOTIVES[row["motive_code"]],
            "native_motive_code": row["motive_code"],
            "part_out": part,
            "first_native_exclusion_frame": part,
            "first_native_exclusion_time_s": current["time_s"],
            "previous_native_frame": previous["part"],
            "previous_native_time_s": previous["time_s"],
            "first_native_exclusion_bracket_s": [previous["time_s"], current["time_s"]],
            "time_gap_s": current["time_s"] - previous["time_s"],
            "position_m": row["position_m"],
            "density_kg_m3": row["density_kg_m3"],
            "initial_mass_kg": mass,
            "mass_fraction_lower_bound": mass / denominator,
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
        })
    total_mass = mass * len(records)
    motive_counts = Counter(item["native_motive"] for item in records)
    result = {
        "schema": "ds02.stage2.f2-s1-fine-native-impact.v1",
        "status": "NATIVE_IMPACT_RECONCILED",
        "family_id": "F2",
        "request_case_id": FINE_CASE_ID,
        "physical_case_id": PHYSICAL_CASE_ID,
        "source": {
            "solver_receipt": binding(source["solver_receipt_path"]),
            "solver_receipt_request_sha256": solver_receipt.get("request_sha256"),
            "solver_command": source["solver_command"],
            "generated_xml": binding(source["generated_xml"]),
            "generated_bi4": {
                "path": str(source["generated_bi4"]),
                "sha256_from_solver_receipt": solver_receipt.get("request", {}).get("input_sha256", {}).get(str(source["generated_bi4"])),
                "hash_policy": "reused completed solver input digest; no duplicate large-file read in this audit",
            },
            "gencase_receipt": binding(source["gencase_receipt"]),
            "run_out": binding(source["run_out"]),
            "runparts": binding(source["runparts"]),
            "raw_partout": binding(source["raw_partout"]),
            "decoder_receipt": binding(decoder_receipt_path),
            "decoded_partout_csv": binding(partout_csv),
            "decoder_resume_csv": binding(resume),
        },
        "native_decode": {
            "tool": "official PartVTKOut",
            "command": decoder.get("command"),
            "runparts_row_count": len(timeline),
            "actual_time_window_s": [timeline[0]["time_s"], timeline[-1]["time_s"]],
            "runparts_totals": runparts["totals"],
            "partout_rows": len(records),
            "motive_counts": dict(sorted(motive_counts.items())),
            "run_out": run_out,
        },
        "typed_mass_visibility": {
            "basis": "generated XML MassFluid times generated XML fluid count; source-bound typed-mass lower-bound proxy",
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
            "particle_identity_source": "official PartVTKOut Idp joined to the same completed solver receipt and RunPARTs Part",
            "observables_unknown": ["physical destination/fate", "fluid free-surface and pressure response", "rigid/body force and coupled impulse response"],
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
        },
        "qualification": {"QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED", "trajectory_h5_read": False, "solver_reexecuted": False},
    }
    output = Path(output).resolve()
    if output.exists():
        raise EvidenceError(f"preserve existing impact sidecar: {output}")
    atomic_json(output, result)
    return {"status": result["status"], "output": str(output),
            "native_exclusion_count": len(records), "motive_counts": dict(motive_counts),
            "mass_fraction_lower_bound": total_mass / denominator}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--solver-receipt", type=Path, required=True)
    prep.add_argument("--output", type=Path, required=True)
    prep.add_argument("--partvtkout", type=Path, default=PARTVTKOUT_DEFAULT)
    prep.add_argument("--dispatch-v4", type=Path, default=DISPATCH_V4_DEFAULT)
    prep.add_argument("--strict-v4", type=Path, default=STRICT_V4_DEFAULT)
    prep.add_argument("--runtime-v4", type=Path, default=RUNTIME_V4_DEFAULT)
    prep.add_argument("--worktree-root", type=Path, default=PRIMARY_WORKTREE)
    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--solver-receipt", type=Path, required=True)
    audit_parser.add_argument("--decoder-receipt", type=Path, required=True)
    audit_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "prepare":
        print(json.dumps(prepare_request(solver_receipt_path=args.solver_receipt,
                                          output=args.output,
                                          partvtkout=args.partvtkout,
                                          dispatch_v4=args.dispatch_v4,
                                          strict_v4=args.strict_v4,
                                          runtime_v4=args.runtime_v4,
                                          worktree_root=args.worktree_root), sort_keys=True))
    else:
        print(json.dumps(audit(solver_receipt_path=args.solver_receipt,
                               decoder_receipt_path=args.decoder_receipt,
                               output=args.output), sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except EvidenceError as exc:
        raise SystemExit(f"EvidenceError: {exc}")
