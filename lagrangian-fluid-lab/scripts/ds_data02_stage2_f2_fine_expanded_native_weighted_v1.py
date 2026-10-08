#!/usr/bin/env python3
"""Source-bound expanded-F2 PartVTKOut and weighted native comparison.

This forward-only worker uses the completed original175 and expanded111
solver outputs.  It runs the official PartVTKOut exactly once for the
expanded raw ``PartOut_000.obi4`` and compares that fresh CSV with the
already completed original175 CSV.  The worker reads only the native
PartOut containers and small RunPARTs/Run.out/XML evidence; H5 and
trajectory ``Part_*.bi4`` content are excluded.  A reduced native count is
reported as a visibility lower bound and never as physical fate or dynamics.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
import os
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import json
from collections import Counter, defaultdict
from typing import Any


SCRIPT = Path(__file__).resolve()
WORKTREE_ROOT = SCRIPT.parents[2]
LAB_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
VENV = LAB_ROOT / ".venv/bin/python"
TOOL = LAB_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64"
CONFIG = LAB_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux/DsphConfig.xml"
STRACE = Path("/usr/bin/strace")
RUNTIME_V4 = SCRIPT.parent / "ds_data02_runtime_v4.py"
RUNTIME_V2 = SCRIPT.parent / "ds_data02_runtime_v2.py"
DISPATCH_V4 = SCRIPT.parent / "ds_data02_stage2_dispatch_v4.py"
STRICT_V4 = SCRIPT.parent / "ds_data02_strict_dispatch_v4.py"

ORIGINAL_SOLVER_RECEIPT = DATA_ROOT / (
    "families/F2/F2_S1_FINE_FULL_REFERENCE_DP00855_T4_SAME_CFL_DENSE/"
    "f2-s1-fine-dp00855-same-cfl-full4s-primary-001/execution-receipt.json"
)
EXPANDED_SOLVER_RECEIPT = DATA_ROOT / (
    "families/F2/F2_S1_FINE_DOMAIN_EXPANDED_DP00855_XYZ_V1/"
    "f2-s1-fine-domain-expanded-xyz-v2-primary-001/execution-receipt.json"
)
EXPANDED_REQUEST = WORKTREE_ROOT / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "f2-s1-fine-domain-expanded-xyz-v2/fine-domain-expanded-request.json"
)
EXPANDED_PREPARED = WORKTREE_ROOT / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "f2-s1-fine-domain-expanded-xyz-v2/prepared/prepared.json"
)
EXPANDED_CLASSIFICATION = WORKTREE_ROOT / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "f2-s1-fine-domain-expanded-xyz-v2/fine-domain-boundary-classification.json"
)
ORIGINAL_DECODER_RECEIPT = DATA_ROOT / (
    "families/F2/F2_S1_FINE_NATIVE_IMPACT_AUDIT_V2/"
    "f2-s1-fine-partvtkout-v2-primary-002/execution-receipt.json"
)
ORIGINAL_DECODER_CSV = ORIGINAL_DECODER_RECEIPT.parent / "PartOut.csv"
REQUEST_CASE = "F2_S1_FINE_EXPANDED_NATIVE_WEIGHTED_V1"
REQUEST_ATTEMPT = "f2-s1-fine-expanded-native-weighted-v1-primary-001"
PHYSICAL_CASE = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
ORIGINAL_CASE = "F2_S1_FINE_FULL_REFERENCE_DP00855_T4_SAME_CFL_DENSE"
EXPANDED_CASE = "F2_S1_FINE_DOMAIN_EXPANDED_DP00855_XYZ_V1"
OUTPUT_SCHEMA = "ds02.stage2.f2-s1-fine-expanded-native-weighted.v1"
MANIFEST_SCHEMA = "ds02.stage2.f2-s1-fine-expanded-native-weighted-manifest.v1"
CSV_FIELDS = ("Idp", "PartOut", "Motive", "Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Rhop [kg/m^3]")
MOTIVES = {1: "position", 2: "density", 3: "movement"}
UNKNOWN_MASS_GATE = 0.003


class WeightedAuditError(RuntimeError):
    """Raised when source identity, native rows, or decoder closure is open."""


def sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: Path | str, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise WeightedAuditError(f"{label} is missing: {path}")
    return path


def require_dir(value: Path | str, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise WeightedAuditError(f"{label} is missing: {path}")
    return path


def read_json(value: Path | str, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(value, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WeightedAuditError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise WeightedAuditError(f"{label} is not a JSON object: {path}")
    return path, payload


def atomic_json(path: Path, payload: dict[str, Any], *, refuse_existing: bool = True) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if refuse_existing and path.exists():
        raise WeightedAuditError(f"refuse to overwrite existing file: {path}")
    encoded = (json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
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
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=WORKTREE_ROOT,
                          check=True, capture_output=True, text=True).stdout.strip()


def record(path: Path | str, label: str) -> dict[str, Any]:
    path = require_file(path, label)
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}


def no_trajectory(path: Path, label: str) -> None:
    if path.name == "trajectory.h5" or (path.name.startswith("Part_") and path.name.endswith(".bi4")):
        raise WeightedAuditError(f"{label} includes forbidden trajectory content: {path}")


def stable_declared(receipt: dict[str, Any], path: Path, label: str) -> str:
    key = str(path.resolve())
    request = receipt.get("request", {})
    declared = request.get("input_sha256", {}).get(key)
    launch = receipt.get("input_hashes_at_launch", {}).get(key)
    finish = receipt.get("input_hashes_after_run", {}).get(key)
    if not declared or declared != launch or declared != finish:
        raise WeightedAuditError(f"{label} is not stable in receipt launch/end hashes: {path}")
    if sha256(path) != declared:
        raise WeightedAuditError(f"{label} digest changed after receipt: {path}")
    return str(declared)


def solver_source(receipt_path: Path, receipt: dict[str, Any], expected_case: str) -> dict[str, Any]:
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise WeightedAuditError(f"solver receipt is not completed: {receipt_path}")
    request = receipt.get("request", {})
    request_case = request.get("request_case_id", request.get("case_id"))
    if request.get("family_id") != "F2" or request_case != expected_case:
        raise WeightedAuditError(f"solver request identity differs for {expected_case}")
    if request.get("physical_case_id") != PHYSICAL_CASE:
        raise WeightedAuditError("solver physical case identity differs")
    output_root = require_dir(receipt.get("output_root", ""), f"{expected_case} solver output root")
    raw_root = require_dir(output_root / "solver_output/data", f"{expected_case} raw solver root")
    paths = {
        "solver_receipt": receipt_path,
        "runparts": output_root / "solver_output/RunPARTs.csv",
        "run_out": output_root / "solver_output/Run.out",
        "raw_partout": raw_root / "PartOut_000.obi4",
    }
    refs = {key: record(path, f"{expected_case} {key}") for key, path in paths.items()}
    # Output files are intentionally checked against their current bytes and
    # then bound as inputs to the new guarded attempt; old solver receipts are
    # never retroactively edited.
    trajectory = sorted(raw_root.glob("Part_*.bi4"))
    if not trajectory:
        raise WeightedAuditError(f"{expected_case} raw output has no Part_*.bi4 inventory")
    inventory = {"glob": "Part_*.bi4", "file_count": len(trajectory),
                 "total_bytes": sum(path.stat().st_size for path in trajectory),
                 "content_hash_performed": False}
    return {"case_id": expected_case, "receipt": receipt, "receipt_path": receipt_path,
            "output_root": output_root, "raw_root": raw_root, "refs": refs, "trajectory_inventory": inventory}


def extract_command_prefix(receipt: dict[str, Any]) -> Path:
    command = receipt.get("request", {}).get("command", [])
    if not isinstance(command, list) or len(command) < 2:
        raise WeightedAuditError("solver receipt command is incomplete")
    return Path(str(command[1])).expanduser().resolve()


def xml_metadata(path: Path, label: str) -> dict[str, Any]:
    path = require_file(path, label)
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise WeightedAuditError(f"{label} is invalid XML: {path}") from exc
    particles = root.find(".//particles")
    if particles is None:
        raise WeightedAuditError(f"{label} lacks particles metadata")
    aggregate = next((node for node in root.iter("fluid") if "mkfluid" not in node.attrib), None)
    mass_node = root.find(".//massfluid")
    if aggregate is None or mass_node is None:
        raise WeightedAuditError(f"{label} lacks aggregate fluid/mass metadata")
    try:
        fluid_count = int(aggregate.attrib["count"])
        mkfluidfirst = int(particles.attrib["mkfluidfirst"])
        massfluid = float(mass_node.attrib["value"])
    except (KeyError, TypeError, ValueError) as exc:
        raise WeightedAuditError(f"{label} has invalid fluid metadata") from exc
    ranges = []
    for node in particles.findall("fluid"):
        if "mkfluid" not in node.attrib:
            continue
        begin = int(node.attrib["begin"])
        count = int(node.attrib["count"])
        mkfluid = int(node.attrib["mkfluid"])
        ranges.append({"mkfluid": mkfluid, "mk_absolute": mkfluidfirst + mkfluid,
                       "begin": begin, "count": count, "end": begin + count})
    if not ranges or sum(item["count"] for item in ranges) != fluid_count:
        raise WeightedAuditError(f"{label} fluid ranges do not sum to aggregate count")
    return {"path": str(path), "sha256": sha256(path), "fluid_count": fluid_count,
            "mkfluidfirst": mkfluidfirst, "massfluid_kg": massfluid,
            "initial_mass_kg": fluid_count * massfluid, "ranges": ranges}


def normalized_xml(path: Path) -> bytes:
    root = ET.parse(path).getroot()
    domain = root.find(".//simulationdomain")
    if domain is not None:
        parent = next((node for node in root.iter() if domain in list(node)), None)
        if parent is not None:
            parent.remove(domain)
    return ET.tostring(root, encoding="utf-8")


def validate_pair_xml(original: Path, expanded: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    original_meta = xml_metadata(original, "original generated XML")
    expanded_meta = xml_metadata(expanded, "expanded prepared XML")
    if normalized_xml(original) != normalized_xml(expanded):
        raise WeightedAuditError("original/expanded XML differs outside simulationdomain")
    if original_meta["fluid_count"] != expanded_meta["fluid_count"] or original_meta["massfluid_kg"] != expanded_meta["massfluid_kg"]:
        raise WeightedAuditError("paired XML initial fluid mass metadata differs")
    return original_meta, expanded_meta


def parse_runparts(path: Path, label: str) -> dict[str, Any]:
    path = require_file(path, label)
    lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    reader = csv.DictReader(lines, delimiter=";")
    required = {"Part", "TimeStep [s]", "NpOut", "NpOutPos", "NpOutRho", "NpOutMov"}
    if reader.fieldnames is None or not required <= set(reader.fieldnames):
        raise WeightedAuditError(f"{label} has incomplete RunPARTs header")
    rows = []
    totals = Counter()
    for raw in reader:
        try:
            part = int(raw["Part"].replace(",", "")); time_s = float(raw["TimeStep [s]"])
            counts = {key: int(raw[key].replace(",", "")) for key in ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov")}
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise WeightedAuditError(f"{label} has invalid RunPARTs row") from exc
        if part != len(rows) or not math.isfinite(time_s) or any(value < 0 for value in counts.values()):
            raise WeightedAuditError(f"{label} RunPARTs part/time/count sequence is invalid")
        if rows and time_s <= rows[-1]["time_s"]:
            raise WeightedAuditError(f"{label} RunPARTs time is not increasing")
        if counts["NpOut"] != counts["NpOutPos"] + counts["NpOutRho"] + counts["NpOutMov"]:
            raise WeightedAuditError(f"{label} RunPARTs motive counts do not sum")
        rows.append({"part": part, "time_s": time_s, **counts})
        totals.update(counts)
    if not rows:
        raise WeightedAuditError(f"{label} RunPARTs is empty")
    return {"path": str(path), "sha256": sha256(path), "rows": rows, "totals": dict(totals)}


def parse_native_csv(path: Path, label: str) -> list[dict[str, Any]]:
    path = require_file(path, label)
    with path.open(newline="", encoding="utf-8", errors="replace") as stream:
        reader = csv.DictReader(stream)
        names = {str(name).strip() for name in (reader.fieldnames or [])}
        if not set(CSV_FIELDS) <= names:
            raise WeightedAuditError(f"{label} lacks required native CSV columns")
        rows = []
        seen: set[int] = set()
        for raw in reader:
            item = {str(key).strip(): (value or "").strip() for key, value in raw.items() if key is not None}
            try:
                row = {"idp": int(item["Idp"]), "part": int(item["PartOut"]),
                       "motive": int(item["Motive"]),
                       "position": [float(item[f"Pos.{axis} [m]"]) for axis in "xyz"],
                       "rhop": float(item["Rhop [kg/m^3]"])}
            except (KeyError, TypeError, ValueError) as exc:
                raise WeightedAuditError(f"{label} native CSV row is invalid") from exc
            if row["idp"] in seen or row["idp"] < 0 or row["part"] < 1 or row["motive"] not in MOTIVES:
                raise WeightedAuditError(f"{label} has ambiguous Idp or invalid motive/frame")
            if not all(math.isfinite(value) for value in (*row["position"], row["rhop"])):
                raise WeightedAuditError(f"{label} has nonfinite native values")
            seen.add(row["idp"]); rows.append(row)
    if not rows:
        raise WeightedAuditError(f"{label} has no native rows")
    return rows


def mk_for_id(idp: int, metadata: dict[str, Any]) -> dict[str, Any]:
    for item in metadata["ranges"]:
        if item["begin"] <= idp < item["end"]:
            return {"mkfluid": item["mkfluid"], "mk_absolute": item["mk_absolute"]}
    raise WeightedAuditError(f"Idp {idp} is outside XML fluid ranges")


def weighted_case(case: str, rows: list[dict[str, Any]], runparts: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    if len(rows) != runparts["totals"]["NpOut"]:
        raise WeightedAuditError(f"{case} native CSV count differs from RunPARTs NpOut")
    by_part = {row["part"]: row for row in runparts["rows"]}
    per_mk: dict[int, Counter[str]] = defaultdict(Counter)
    enriched = []
    for row in rows:
        if row["part"] not in by_part:
            raise WeightedAuditError(f"{case} native row PartOut is outside RunPARTs")
        mk = mk_for_id(row["idp"], metadata)
        motive = MOTIVES[row["motive"]]
        per_mk[mk["mk_absolute"]][motive] += 1
        enriched.append({**row, **mk, "motive_name": motive,
                         "time_s": by_part[row["part"]]["time_s"]})
    counts = Counter(row["motive_name"] for row in enriched)
    return {
        "case_id": case,
        "native_count": len(enriched),
        "motive_counts": dict(sorted(counts.items())),
        "per_mk_motive_counts": {str(key): dict(sorted(value.items())) for key, value in sorted(per_mk.items())},
        "first_native_time_s": min(row["time_s"] for row in enriched),
        "last_native_time_s": max(row["time_s"] for row in enriched),
        "runparts_final_time_s": runparts["rows"][-1]["time_s"],
        "initial_mass_denominator_kg": metadata["initial_mass_kg"],
        "particle_mass_kg": metadata["massfluid_kg"],
        "native_mass_lower_bound_kg": len(enriched) * metadata["massfluid_kg"],
        "native_mass_fraction_lower_bound": len(enriched) * metadata["massfluid_kg"] / metadata["initial_mass_kg"],
        "records": enriched,
    }


def paired_weighted_impact(original_rows: list[dict[str, Any]], expanded_rows: list[dict[str, Any]],
                           original_runparts: dict[str, Any], expanded_runparts: dict[str, Any],
                           metadata: dict[str, Any]) -> dict[str, Any]:
    original = weighted_case(ORIGINAL_CASE, original_rows, original_runparts, metadata)
    expanded = weighted_case(EXPANDED_CASE, expanded_rows, expanded_runparts, metadata)
    original_ids = {row["idp"] for row in original_rows}
    expanded_ids = {row["idp"] for row in expanded_rows}
    reduction = original["native_count"] - expanded["native_count"]
    reduction_fraction = reduction * metadata["massfluid_kg"] / metadata["initial_mass_kg"]
    return {
        "schema": "ds02.stage2.f2-s1-fine-native-weighted-impact.v1",
        "comparison": "same frozen whole initial mass denominator and same physical CURRENT case; native visibility only",
        "initial_mass_basis": {
            "denominator_kg": metadata["initial_mass_kg"],
            "massfluid_kg": metadata["massfluid_kg"],
            "fluid_count": metadata["fluid_count"],
            "source": "paired generated XML fluid count × massfluid; diagnostic mass basis",
        },
        "original": original,
        "expanded": expanded,
        "native_id_set_comparison": {
            "original_only_count": len(original_ids - expanded_ids),
            "expanded_only_count": len(expanded_ids - original_ids),
            "shared_count": len(original_ids & expanded_ids),
        },
        "native_visibility_difference": {
            "original_minus_expanded_count": reduction,
            "mass_lower_bound_difference_kg": reduction * metadata["massfluid_kg"],
            "mass_fraction_lower_bound_difference": reduction_fraction,
            "expanded_unknown_mass_gate_0p003": expanded["native_mass_fraction_lower_bound"] <= UNKNOWN_MASS_GATE,
            "interpretation": "difference in native exclusion visibility only; physical destination, spill, velocity, impulse, coupling, and dynamics UNKNOWN",
        },
        "physical_fate": "UNKNOWN",
        "dynamical_impact": "UNKNOWN",
    }


def trace_opened(trace: Path, needle: str) -> bool:
    text = trace.read_text(encoding="utf-8", errors="replace")
    return any(needle in line and "openat(" in line and "= -1" not in line for line in text.splitlines())


def official_decode(raw_root: Path, output_root: Path) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    csv_path = output_root / "PartOut.csv"
    resume_path = output_root / "resume.csv"
    trace_path = output_root / "native-openat.trace"
    command = [str(STRACE), "-f", "-qq", "-e", "trace=openat,open,statx", "-o", str(trace_path),
               str(TOOL), "-dirdata", str(raw_root), "-savecsv", str(csv_path),
               "-saveresume", str(resume_path), "-createdirs:1", "-csvsep:1"]
    completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=900)
    if completed.returncode != 0:
        raise WeightedAuditError(f"official expanded PartVTKOut failed: {completed.stdout[-2000:]} {completed.stderr[-2000:]}")
    require_file(csv_path, "expanded PartOut.csv")
    require_file(resume_path, "expanded decoder resume")
    require_file(trace_path, "expanded decoder trace")
    config = TOOL.parent / "DsphConfig.xml"
    if config.resolve() != CONFIG.resolve() or not trace_opened(trace_path, "DsphConfig.xml") or not trace_opened(trace_path, "PartOut_000.obi4"):
        raise WeightedAuditError("expanded decoder trace lacks exact DsphConfig.xml/PartOut_000.obi4 opens")
    trace_text = trace_path.read_text(encoding="utf-8", errors="replace")
    if any("Part_" in line and ".bi4" in line and "PartOut_" not in line for line in trace_text.splitlines()):
        raise WeightedAuditError("expanded decoder unexpectedly opened trajectory Part_*.bi4")
    decoder = {"schema": "ds02.stage2.f2-expanded-partvtkout-receipt.v1", "status": "completed", "returncode": 0,
               "command": command, "raw_root": str(raw_root), "output_root": str(output_root),
               "csv": record(csv_path, "expanded decoded CSV"), "resume": record(resume_path, "expanded decoder resume"),
               "trace": record(trace_path, "expanded decoder trace"),
               "tool": record(TOOL, "official PartVTKOut"), "config": record(CONFIG, "official DsphConfig.xml"),
               "strace": record(STRACE, "strace"), "stdout": completed.stdout, "stderr": completed.stderr,
               "h5_opened": False, "trajectory_opened": False}
    atomic_json(output_root / "expanded-partvtkout-receipt.json", decoder)
    decoder["receipt"] = record(output_root / "expanded-partvtkout-receipt.json", "expanded decoder receipt")
    return decoder


def prepare(output_dir: Path) -> dict[str, Any]:
    original_receipt_path, original_receipt = read_json(ORIGINAL_SOLVER_RECEIPT, "original solver receipt")
    expanded_receipt_path, expanded_receipt = read_json(EXPANDED_SOLVER_RECEIPT, "expanded solver receipt")
    original = solver_source(original_receipt_path, original_receipt, ORIGINAL_CASE)
    expanded = solver_source(expanded_receipt_path, expanded_receipt, EXPANDED_CASE)
    _, expanded_request = read_json(EXPANDED_REQUEST, "expanded source request")
    _, prepared = read_json(EXPANDED_PREPARED, "expanded prepared metadata")
    _, classification = read_json(EXPANDED_CLASSIFICATION, "expanded boundary classification")
    original_prefix = extract_command_prefix(original_receipt)
    original_xml = original_prefix.with_suffix(".xml")
    expanded_xml = Path(str(expanded_request["command"][1])).with_suffix(".xml")
    original_xml = require_file(original_xml, "original generated XML")
    expanded_xml = require_file(expanded_xml, "expanded prepared XML")
    if expanded_request.get("physical_case_id") != PHYSICAL_CASE or expanded_request.get("case_id") != EXPANDED_CASE:
        raise WeightedAuditError("expanded source request identity differs")
    expanded_request_key = str(expanded_xml)
    if expanded_request.get("input_sha256", {}).get(expanded_request_key) != sha256(expanded_xml):
        raise WeightedAuditError("expanded prepared XML is not bound by source request")
    original_meta, expanded_meta = validate_pair_xml(original_xml, expanded_xml)
    if original_meta["initial_mass_kg"] != 21.060888732 or expanded_meta["initial_mass_kg"] != 21.060888732:
        raise WeightedAuditError("paired whole initial mass does not equal frozen 21.060888732 kg")
    original_decoder_path, original_decoder = read_json(ORIGINAL_DECODER_RECEIPT, "original completed decoder receipt")
    if original_decoder.get("status") != "completed" or original_decoder.get("returncode") != 0:
        raise WeightedAuditError("original decoder is not completed")
    if original_decoder.get("request", {}).get("physical_case_id") != PHYSICAL_CASE:
        raise WeightedAuditError("original decoder physical identity differs")
    if original_decoder.get("request", {}).get("source_solver_receipt") != str(original_receipt_path):
        raise WeightedAuditError("original decoder does not bind original solver receipt")
    original_csv = require_file(ORIGINAL_DECODER_CSV, "original completed decoder CSV")
    if original_decoder.get("request", {}).get("source_partout_csv_sha256") not in (None, sha256(original_csv)):
        raise WeightedAuditError("original decoder CSV digest differs")
    motion_candidates = [Path(value) for value in expanded_request.get("input_files", []) if str(value).endswith(".dat")]
    if len(motion_candidates) < 1:
        raise WeightedAuditError("expanded request lacks motion source")
    motion_hashes = {sha256(require_file(path, "motion source")) for path in motion_candidates}
    if len(motion_hashes) != 1:
        raise WeightedAuditError("expanded request motion aliases differ")
    motion_path = motion_candidates[0]
    generated_bi4 = require_file(prepared["source_generated_bi4"]["path"], "shared generated BI4") if isinstance(prepared.get("source_generated_bi4"), dict) else require_file(expanded_request.get("source_generated_bi4", ""), "shared generated BI4")
    original_bi4 = require_file(original_prefix.with_suffix(".bi4"), "original generated BI4")
    if sha256(generated_bi4) != sha256(original_bi4):
        raise WeightedAuditError("original and expanded paired generated BI4 differ")
    files = [SCRIPT, RUNTIME_V4, RUNTIME_V2, DISPATCH_V4, STRICT_V4, TOOL, CONFIG, STRACE,
             original_receipt_path, expanded_receipt_path, EXPANDED_REQUEST, EXPANDED_PREPARED,
             EXPANDED_CLASSIFICATION, original_decoder_path, original_csv, original_xml, expanded_xml,
             generated_bi4, original_bi4, *motion_candidates, original["refs"]["runparts"]["path"], original["refs"]["run_out"]["path"],
             original["refs"]["raw_partout"]["path"], expanded["refs"]["runparts"]["path"], expanded["refs"]["run_out"]["path"],
             expanded["refs"]["raw_partout"]["path"]]
    unique: list[Path] = []
    seen: set[str] = set()
    for value in files:
        path = require_file(value, f"source input {Path(value).name}")
        no_trajectory(path, "source input")
        if str(path) not in seen:
            seen.add(str(path)); unique.append(path)
    input_hashes = {str(path): sha256(path) for path in unique}
    output_dir = output_dir.resolve(); output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "f2-s1-fine-expanded-native-weighted-manifest.json"
    request_path = output_dir / "f2-s1-fine-expanded-native-weighted-request.json"
    manifest = {
        "schema": MANIFEST_SCHEMA, "status": "PREPARED_CONFIG_CLOSED_EXPANDED_NATIVE_WEIGHTED",
        "physical_case_id": PHYSICAL_CASE, "original_case_id": ORIGINAL_CASE, "expanded_case_id": EXPANDED_CASE,
        "source_cases": {
            "original": {"solver_receipt": record(original_receipt_path, "original solver receipt"),
                          "raw_root": str(original["raw_root"]), "raw_partout": original["refs"]["raw_partout"],
                          "runparts": original["refs"]["runparts"], "run_out": original["refs"]["run_out"],
                          "xml": record(original_xml, "original XML"), "decoder_receipt": record(original_decoder_path, "original decoder receipt"),
                          "decoder_csv": record(original_csv, "original decoder CSV"), "trajectory_inventory": original["trajectory_inventory"]},
            "expanded": {"solver_receipt": record(expanded_receipt_path, "expanded solver receipt"),
                          "raw_root": str(expanded["raw_root"]), "raw_partout": expanded["refs"]["raw_partout"],
                          "runparts": expanded["refs"]["runparts"], "run_out": expanded["refs"]["run_out"],
                          "xml": record(expanded_xml, "expanded XML"), "trajectory_inventory": expanded["trajectory_inventory"]},
        },
        "paired_control": {"same_physical_case": True, "same_initial_mass_denominator_kg": 21.060888732,
                            "same_generated_bi4": record(generated_bi4, "shared generated BI4"),
                            "same_motion": record(motion_path, "shared motion"),
                            "non_domain_xml_equal": True, "expanded_domain_change_only": True,
                            "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
        "official_runtime": {"tool": record(TOOL, "official PartVTKOut"), "config": record(CONFIG, "official DsphConfig.xml"),
                              "strace": record(STRACE, "strace"), "runtime_v4": record(RUNTIME_V4, "runtime v4"),
                              "runtime_v2": record(RUNTIME_V2, "runtime v2"), "dispatch_v4": record(DISPATCH_V4, "dispatch v4"),
                              "strict_v4": record(STRICT_V4, "strict dispatch v4")},
        "guard_input_files": sorted(input_hashes), "input_sha256": dict(sorted(input_hashes.items())),
        "read_policy": {"h5_opened": False, "trajectory_content_opened": False, "solver_started": False,
                         "partvtkout_expanded_only": True, "old_original_decoder_reused": True,
                         "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
        "classification_source": record(EXPANDED_CLASSIFICATION, "expanded classification"),
        "classification_status": classification.get("status"),
    }
    # The manifest is the container for the source hash set, so it cannot
    # contain a self-hash without creating an impossible fixed point.  Keep
    # it out of its own input map; bind its final bytes in the dispatch
    # request below, where the manifest is an ordinary declared input.
    atomic_json(manifest_path, manifest)
    request_input_hashes = dict(input_hashes)
    request_input_hashes[str(manifest_path)] = sha256(manifest_path)
    request = {
        "schema": "ds02.request.v1", "family_id": "F2", "case_id": REQUEST_CASE, "physical_case_id": PHYSICAL_CASE,
        "attempt_id": REQUEST_ATTEMPT, "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1,
        "max_wall_seconds": 1800, "estimated_storage_bytes": 512 * 1024 * 1024,
        "cwd": str(SCRIPT.parent), "worktree_root": str(WORKTREE_ROOT),
        "command": [str(VENV), str(SCRIPT), "run", "--manifest", str(manifest_path), "--output", "{attempt_root}/f2-s1-fine-expanded-native-weighted.json"],
        "input_files": sorted(request_input_hashes), "input_sha256": dict(sorted(request_input_hashes.items())),
        "runtime_binding": manifest["official_runtime"]["runtime_v4"],
        "official_decoder_argv": [str(TOOL), "-dirdata", "<expanded raw solver_output/data>", "-savecsv", "<attempt>/expanded-decoder/PartOut.csv", "-saveresume", "<attempt>/expanded-decoder/resume.csv", "-createdirs:1", "-csvsep:1"],
        "source_scope": {"expanded_decoder_raw_partout_only": True, "original_decoder_csv_reused": True, "h5_or_trajectory_inputs": [], "config_closed": True},
        "source_read_cost": {"runtime_pre_post_hash_bytes": sum(path.stat().st_size for path in unique) * 2,
                              "raw_partout_bytes": original["refs"]["raw_partout"]["bytes"] + expanded["refs"]["raw_partout"]["bytes"],
                              "trajectory_bytes_read": 0, "h5_bytes_read": 0, "estimated_output_bytes": 512 * 1024 * 1024},
        "launch_commit": git_head(), "canonical_ready": True, "launch_owner": "root", "primary_launch_owner": "root",
        "launch": True, "launch_allowed": True, "execution_allowed": True, "foreign_process_protection_required": True,
        "shared_lease_required": True, "solver_launch_forbidden": True, "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN",
        "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED",
        "request_note": "One guarded CPU worker runs official PartVTKOut only on completed expanded111 raw PartOut_000.obi4, reuses completed original175 CSV, and emits paired native weighted mass visibility. No H5, trajectory Part_*.bi4, solver, CFD, or physical-fate claim.",
    }
    atomic_json(request_path, request)
    return {"status": "prepared", "manifest": str(manifest_path), "manifest_sha256": sha256(manifest_path),
            "request": str(request_path), "request_sha256": sha256(request_path), "input_count": len(input_hashes),
            "guard_input_count": len(request_input_hashes),
            "original_native_expected": 175, "expanded_native_expected": 111,
            "runtime_pre_post_hash_bytes": request["source_read_cost"]["runtime_pre_post_hash_bytes"]}


def run(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest_path, manifest = read_json(manifest_path, "expanded native weighted manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "PREPARED_CONFIG_CLOSED_EXPANDED_NATIVE_WEIGHTED":
        raise WeightedAuditError("manifest schema/status is not prepared")
    for path_text, digest in manifest.get("input_sha256", {}).items():
        path = require_file(path_text, "guarded source input")
        no_trajectory(path, "guarded source input")
        if sha256(path) != digest:
            raise WeightedAuditError(f"guarded source input changed: {path}")
    original = manifest["source_cases"]["original"]
    expanded = manifest["source_cases"]["expanded"]
    original_rows = parse_native_csv(Path(original["decoder_csv"]["path"]), "original completed CSV")
    original_runparts = parse_runparts(Path(original["runparts"]["path"]), "original RunPARTs")
    expanded_runparts = parse_runparts(Path(expanded["runparts"]["path"]), "expanded RunPARTs")
    # Re-run the pair contract at execution time.  The manifest hashes protect
    # the bytes, while this semantic check protects against a prepared pair
    # whose only permitted change is the numerical simulation domain.
    metadata, expanded_xml_meta = validate_pair_xml(
        Path(original["xml"]["path"]), Path(expanded["xml"]["path"])
    )
    if metadata["initial_mass_kg"] != 21.060888732 or expanded_xml_meta["initial_mass_kg"] != 21.060888732:
        raise WeightedAuditError("worker paired XML mass denominator is not the frozen 21.060888732 kg")
    decoder = official_decode(Path(expanded["raw_root"]), output_path.resolve().parent / "expanded-decoder")
    expanded_rows = parse_native_csv(Path(decoder["csv"]["path"]), "expanded decoded CSV")
    paired = paired_weighted_impact(original_rows, expanded_rows, original_runparts, expanded_runparts, metadata)
    result = {
        "schema": OUTPUT_SCHEMA, "status": "EXPANDED_NATIVE_WEIGHTED_RECONCILED",
        "manifest": record(manifest_path, "weighted manifest"), "physical_case_id": PHYSICAL_CASE,
        "official_expanded_decoder": decoder, "paired_weighted_impact": paired,
        "source_policy": {"h5_opened": False, "trajectory_content_opened": False, "expanded_partvtkout_started": True,
                           "original_partvtkout_rerun": False, "solver_reexecuted": False,
                           "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
        "qualification": {"physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED"},
    }
    atomic_json(output_path, result)
    return {"status": result["status"], "output": str(output_path), "expanded_native_count": len(expanded_rows),
            "original_native_count": len(original_rows),
            "expanded_mass_fraction_lower_bound": paired["expanded"]["native_mass_fraction_lower_bound"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare"); prep.add_argument("--output-dir", type=Path, required=True)
    runner = sub.add_parser("run"); runner.add_argument("--manifest", type=Path, required=True); runner.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.output_dir) if args.action == "prepare" else run(args.manifest, args.output)
    except WeightedAuditError as exc:
        raise SystemExit(f"WeightedAuditError: {exc}")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
