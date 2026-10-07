#!/usr/bin/env python3
"""Build a source-bound typed-mass impact screen for the historical 118 cases.

The stream is deliberately limited to completed scientific-scan JSON, native
cause sidecars, their completion receipts, and small referenced native
evidence.  It never opens trajectory H5, Part_*.bi4 trajectory frames, or
starts a solver.  The 0.003 threshold is a preregistered mass-visibility
screen only; both physical fate and dynamical impact stay UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

SCRIPT = Path(__file__).resolve()
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
CASE_COUNT = 118
MASS_GATE = 0.003
OUTPUT_SCHEMA = "ds02.stage2.omission-task-impact-stream.v1"
FAMILY_CASE_COUNTS = {"F2": 48, "F4": 22, "F6": 48}
EXPECTED_MOTIVES = {"F2": {"position": 1078}, "F4": {"density": 51}, "F6": {"position": 199}}
MOTIVE_CODES = {1: "position", 2: "density", 3: "movement"}


class StreamError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise StreamError(f"{label} is missing: {path}")
    return path


def read_json(value: str | Path, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(value, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StreamError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise StreamError(f"{label} is not an object: {path}")
    return path, payload


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path = path.resolve()
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


def file_binding(path: Path) -> dict[str, Any]:
    return {"path": str(path.resolve()), "sha256": sha256(path), "bytes": path.stat().st_size}


def _case_number(path: Path, family: str) -> str:
    match = re.search(rf"STAGE2_OMISSION_{family}_(\d+)$", path.name)
    return match.group(1) if match else "S1"


def _referenced_files(value: Any) -> set[Path]:
    """Collect explicit small-file path fields without following H5 paths."""
    found: set[Path] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "path" and isinstance(child, str):
                path = Path(child).expanduser()
                if path.suffix.lower() in {".h5", ".hdf5"}:
                    continue
                if path.is_file():
                    found.add(path.resolve())
            else:
                found.update(_referenced_files(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_referenced_files(child))
    return found


def _entry(case_key: str, family: str, forensic_path: Path, scan_path: Path, receipt_path: Path,
           forensic_kind: str, forensic: dict[str, Any], scan: dict[str, Any]) -> dict[str, Any]:
    files = {forensic_path.resolve(), scan_path.resolve(), receipt_path.resolve()}
    files.update(_referenced_files(forensic))
    files = {path for path in files if path.suffix.lower() not in {".h5", ".hdf5"}}
    if any(path.suffix.lower() in {".h5", ".hdf5"} for path in files):
        raise StreamError(f"H5 slipped into source input set: {case_key}")
    return {
        "case_key": case_key, "family_id": family, "physical_case_id": scan.get("physical_case_id"),
        "forensic_kind": forensic_kind, "forensic_path": str(forensic_path.resolve()),
        "forensic_sha256": sha256(forensic_path), "scan_path": str(scan_path.resolve()),
        "scan_sha256": sha256(scan_path), "scan_receipt_path": str(receipt_path.resolve()),
        "scan_receipt_sha256": sha256(receipt_path), "bound_files": [str(path) for path in sorted(files)],
    }


def make_manifest(output: Path, data_root: Path = DATA_ROOT) -> dict[str, Any]:
    data_root = data_root.resolve()
    entries: list[dict[str, Any]] = []
    # The F2-S1 legacy three-Idp ledger is a distinct completed scan outside
    # the numbered CURRENT336 batch and is the 48th historical F2 case.
    legacy_forensic = data_root / "families/F2/STAGE2_F2_S1_EXCLUSIONS/join-F2-S1-001/native-reconciliation.json"
    legacy_scan = data_root / "families/F2/STAGE2_F2_S1_SCIENCE/scan-F2-S1-001/scientific-scan.json"
    legacy_receipt = legacy_scan.parent / "execution-receipt.json"
    _, legacy = read_json(legacy_forensic, "F2-S1 native reconciliation")
    _, legacy_scan_data = read_json(legacy_scan, "F2-S1 scientific scan")
    entries.append(_entry("F2/scan-F2-S1-001", "F2", legacy_forensic, legacy_scan, legacy_receipt, "native-reconciliation.v1", legacy, legacy_scan_data))
    for family in ("F2", "F4", "F6"):
        for forensic_path in sorted((data_root / "families" / family).glob(f"STAGE2_OMISSION_{family}_*/**/omission-forensics.json")):
            _, forensic = read_json(forensic_path, f"{family} forensic sidecar")
            scan_path = require_file(forensic["scan"]["path"], f"{family} scan")
            receipt_path = require_file(forensic["scan_completion"]["receipt"]["path"], f"{family} scan receipt")
            _, scan = read_json(scan_path, f"{family} scan")
            key = f"{family}/scan-{family}-{_case_number(forensic_path.parent.parent, family)}-001"
            # A resumed F2-076 scan has attempt 002; the path in the forensic
            # sidecar is authoritative, so derive the actual scan directory.
            key = f"{family}/{scan_path.parent.name}"
            entries.append(_entry(key, family, forensic_path, scan_path, receipt_path, "omission-forensics.v2", forensic, scan))
    entries.sort(key=lambda item: item["case_key"])
    counts = Counter(item["family_id"] for item in entries)
    if len(entries) != CASE_COUNT or dict(counts) != FAMILY_CASE_COUNTS:
        raise StreamError(f"historical source membership is incomplete: {dict(counts)} / {len(entries)}")
    inputs: dict[str, str] = {}
    for entry in entries:
        for value in entry["bound_files"]:
            path = require_file(value, "bound evidence")
            if path.suffix.lower() in {".h5", ".hdf5"}:
                raise StreamError(f"H5 input is forbidden: {path}")
            inputs[str(path)] = sha256(path)
    manifest = {
        "schema": "ds02.stage2.omission-task-impact-stream-manifest.v1", "status": "IMMUTABLE_SOURCE_SET",
        "case_count": len(entries), "family_case_counts": dict(sorted(counts.items())),
        "families": ["F2", "F4", "F6"], "data_root": str(data_root), "entries": entries,
        "inputs": dict(sorted(inputs.items())),
        "read_policy": {"h5_opened": False, "trajectory_part_content_opened": False, "solver_started": False, "cfd_or_model_run": False},
        "native_cause_policy": "use actual native motive/cause from bound forensic decode; endpoint MapRealPos/Rhop predicates are not causes",
        "qualification_policy": "mass screen only; physical fate, dynamical impact, QN and QE remain UNKNOWN",
    }
    output = output.resolve()
    if output.exists():
        raise StreamError(f"preserve existing manifest: {output}")
    atomic_json(output, manifest)
    return {"status": manifest["status"], "manifest": str(output), "manifest_sha256": sha256(output), "case_count": len(entries), "input_count": len(inputs), "family_case_counts": dict(sorted(counts.items()))}


def _stable_receipt(scan_path: Path, receipt_path: Path, family: str, physical_case_id: str) -> dict[str, Any]:
    receipt = read_json(receipt_path, "scan execution receipt")[1]
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise StreamError(f"scan receipt is not completed code 0: {receipt_path}")
    if Path(receipt.get("output_root", "")).resolve() != scan_path.parent.resolve():
        raise StreamError(f"scan receipt output root mismatch: {receipt_path}")
    request = receipt.get("request", {})
    if request.get("family_id") != family:
        raise StreamError(f"scan receipt family mismatch: {receipt_path}")
    if not str(request.get("attempt_id", "")).startswith(scan_path.parent.name):
        raise StreamError(f"scan receipt attempt differs from scan directory: {receipt_path}")
    command = request.get("command", [])
    if not isinstance(command, list) or "--case-id" not in command:
        raise StreamError(f"scan receipt command lacks exact case id: {receipt_path}")
    case_index = command.index("--case-id")
    if case_index + 1 >= len(command) or command[case_index + 1] != physical_case_id:
        raise StreamError(f"scan receipt case identity differs: {receipt_path}")
    launch = receipt.get("input_hashes_at_launch", {})
    finish = receipt.get("input_hashes_after_run", {})
    declared = request.get("input_sha256", {})
    if not launch or launch != finish or any(declared.get(key) != value for key, value in launch.items()):
        raise StreamError(f"scan receipt inputs are not stable/declared: {receipt_path}")
    return receipt


def _same_mass(left: Any, right: Any) -> bool:
    try:
        return math.isclose(float(left), float(right), rel_tol=2e-12, abs_tol=2e-12)
    except (TypeError, ValueError):
        return False


def _native_rows(kind: str, forensic: dict[str, Any]) -> dict[tuple[int, int], dict[str, Any]]:
    if kind == "omission-forensics.v2":
        if forensic.get("schema") != "ds02.stage2.omission-forensics.v2" or forensic.get("status") != "CAUSES_RECONCILED":
            raise StreamError("forensic sidecar is not a completed v2 cause reconciliation")
        rows = forensic.get("excluded_particles", [])
    elif kind == "native-reconciliation.v1":
        if forensic.get("schema") != "ds02.stage2.native-exclusion-reconciliation.v1" or forensic.get("status") != "CAUSES_RECONCILED":
            raise StreamError("legacy F2-S1 reconciliation is not completed")
        rows = forensic.get("missing_fluid_ids", [])
    else:
        raise StreamError(f"unsupported forensic kind: {kind}")
    result: dict[tuple[int, int], dict[str, Any]] = {}
    for row in rows:
        key = (int(row["zone"]), int(row["idp"]))
        if key in result:
            raise StreamError(f"duplicate native Idp in forensic source: {key}")
        if kind == "native-reconciliation.v1":
            native = row.get("native_record", {})
            code = int(native.get("motive_code", 0))
            motive = native.get("motive")
        else:
            code = int(row.get("native_motive_code", 0))
            motive = row.get("native_motive")
        if code not in MOTIVE_CODES or motive != MOTIVE_CODES[code]:
            raise StreamError(f"native motive code/label mismatch for {key}")
        cause = row.get("native_exit_cause")
        expected_cause = f"NUMERICAL_{motive.upper()}_EXCLUSION"
        if cause != expected_cause:
            raise StreamError(f"native cause is absent or inconsistent for {key}: {cause}")
        result[key] = {
            "zone": key[0], "idp": key[1], "native_motive": motive, "native_motive_code": code,
            "native_exit_cause": cause, "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN",
        }
    return result


def analyze_case(entry: dict[str, Any], *, verify_bound_inputs: bool = True) -> dict[str, Any]:
    family = entry["family_id"]
    forensic_path, forensic = read_json(entry["forensic_path"], f"{entry['case_key']} forensic")
    scan_path, scan = read_json(entry["scan_path"], f"{entry['case_key']} scan")
    receipt_path = require_file(entry["scan_receipt_path"], f"{entry['case_key']} receipt")
    if verify_bound_inputs:
        for path_text in entry.get("bound_files", []):
            path = require_file(path_text, "bound source")
            if path.suffix.lower() in {".h5", ".hdf5"}:
                raise StreamError(f"H5 source is forbidden: {path}")
    if sha256(forensic_path) != entry["forensic_sha256"] or sha256(scan_path) != entry["scan_sha256"] or sha256(receipt_path) != entry["scan_receipt_sha256"]:
        raise StreamError(f"manifest primary digest mismatch: {entry['case_key']}")
    if scan.get("schema") != "ds02.stage2.scientific-scan.v1" or scan.get("scan_status") != "SCANNED" or scan.get("family_id") != family:
        raise StreamError(f"scan is not a completed exact source: {entry['case_key']}")
    if scan.get("physical_case_id") != entry.get("physical_case_id"):
        raise StreamError(f"scan physical identity differs: {entry['case_key']}")
    _stable_receipt(scan_path, receipt_path, family, str(scan["physical_case_id"]))
    fluid = scan.get("type_ledgers", {}).get("fluid", {})
    if int(fluid.get("type_code", -1)) != 3 or int(fluid.get("typed_initial_count", 0)) <= 0:
        raise StreamError(f"fluid typed ledger missing: {entry['case_key']}")
    scan_records = scan.get("missing_id_records", [])
    scan_by_id: dict[tuple[int, int], dict[str, Any]] = {}
    for row in scan_records:
        key = (int(row["zone"]), int(row["idp"]))
        if key in scan_by_id:
            raise StreamError(f"duplicate scan Idp: {entry['case_key']} {key}")
        if int(row.get("type_code", -1)) != 3:
            raise StreamError(f"non-fluid missing record: {entry['case_key']} {key}")
        scan_by_id[key] = row
    native_by_id = _native_rows(entry["forensic_kind"], forensic)
    typed_ids = forensic.get("typed_identity", {}).get("ids") if entry["forensic_kind"] == "omission-forensics.v2" else forensic.get("missing_fluid_ids")
    typed_by_id = {(int(row["zone"]), int(row["idp"])): row for row in (typed_ids or [])}
    if len(typed_by_id) != len(typed_ids or []):
        raise StreamError(f"duplicate typed Idp: {entry['case_key']}")
    if set(scan_by_id) != set(typed_by_id) or set(native_by_id) != set(typed_by_id):
        raise StreamError(f"scan/typed/native Idp sets differ: {entry['case_key']}")
    expected_count = int(forensic.get("typed_identity", {}).get("missing_fluid_count", len(typed_by_id))) if entry["forensic_kind"] == "omission-forensics.v2" else int(forensic.get("typed_unique_missing", len(typed_by_id)))
    if expected_count != len(typed_by_id) or int(fluid.get("cumulative_unique_missing", len(scan_by_id))) != len(scan_by_id):
        raise StreamError(f"missing count identity differs: {entry['case_key']}")
    missing_mass = 0.0
    first_times: list[float] = []
    joined: list[dict[str, Any]] = []
    for key in sorted(typed_by_id):
        typed = typed_by_id[key]
        scan_row = scan_by_id[key]
        native = native_by_id[key]
        if typed.get("initial_mass_kg") is not None and not _same_mass(typed.get("initial_mass_kg"), scan_row.get("initial_mass_kg")):
            raise StreamError(f"typed/scan mass differs: {entry['case_key']} {key}")
        if typed.get("first_missing_frame") is not None and int(typed["first_missing_frame"]) != int(scan_row.get("first_missing_frame", -1)):
            raise StreamError(f"typed/scan first-missing frame differs: {entry['case_key']} {key}")
        typed_bracket = typed.get("first_missing_bracket_s")
        scan_bracket = scan_row.get("first_missing_bracket_s")
        if typed_bracket is not None and scan_bracket is not None and (len(typed_bracket) != 2 or len(scan_bracket) != 2 or any(not _same_mass(left, right) for left, right in zip(typed_bracket, scan_bracket))):
            raise StreamError(f"typed/scan first-missing time differs: {entry['case_key']} {key}")
        mass = float(scan_row["initial_mass_kg"])
        missing_mass += mass
        bracket = scan_row.get("first_missing_bracket_s") or typed.get("first_missing_bracket_s")
        if not isinstance(bracket, list) or len(bracket) != 2:
            raise StreamError(f"missing time bracket absent: {entry['case_key']} {key}")
        first_times.extend(float(value) for value in bracket)
        joined.append({"zone": key[0], "idp": key[1], "type_code": 3, "initial_mass_kg": mass,
                       "first_missing_frame": int(scan_row["first_missing_frame"]), "first_missing_bracket_s": [float(bracket[0]), float(bracket[1])], **native})
    denominator = float(fluid["typed_initial_mass_kg"])
    missing_ledger = fluid.get("missing_initial_mass_kg", missing_mass)
    if isinstance(missing_ledger, list):
        missing_ledger = missing_ledger[-1] if missing_ledger else 0.0
    if denominator <= 0 or not _same_mass(missing_mass, float(missing_ledger)):
        raise StreamError(f"typed fluid mass ledger differs: {entry['case_key']}")
    fraction = missing_mass / denominator
    screen = "mass_screen_subset_below_gate" if fraction <= MASS_GATE else "mass_screen_subset_above_gate"
    if entry["forensic_kind"] == "omission-forensics.v2":
        typed_mass = float(forensic["typed_identity"]["missing_fluid_initial_mass_kg"])
        if not _same_mass(typed_mass, missing_mass):
            raise StreamError(f"forensic typed mass differs: {entry['case_key']}")
        native_decode = forensic.get("native_decode", {})
        totals = native_decode.get("runparts_totals", {})
        if int(totals.get("NpOut", len(native_by_id))) != len(native_by_id):
            raise StreamError(f"native RunPARTs count differs: {entry['case_key']}")
    sample_floating = scan.get("type_ledgers", {}).get("floating", {}).get("typed_initial_mass_kg")
    return {
        "case_key": entry["case_key"], "family_id": family, "physical_case_id": scan["physical_case_id"],
        "forensic_kind": entry["forensic_kind"], "typed_fluid_particle_count": int(fluid["typed_initial_count"]),
        "typed_initial_fluid_mass_kg": denominator, "missing_fluid_count": len(joined),
        "missing_mass_lower_bound_kg": missing_mass, "missing_mass_fraction_lower_bound": fraction,
        "mass_screen": screen, "screen_gate_fraction": MASS_GATE,
        "native_motive_counts": dict(sorted(Counter(row["native_motive"] for row in joined).items())),
        "native_exit_cause_counts": dict(sorted(Counter(row["native_exit_cause"] for row in joined).items())),
        "first_missing_window_s": [min(first_times), max(first_times)] if first_times else None,
        "particles": joined,
        "per_mk_denominator": {"status": "UNKNOWN_REQUIRES_BOUND_STATIC_MK_AUDIT", "reason": "scan/native identity records carry type_code and Zone/Idp, not an independently source-bound MK initial mass partition", "mass_fraction_not_split_by_mk": True},
        "f6_mass_semantics": ({"sample_floating_typed_initial_mass_kg": float(sample_floating), "rigid_body_mass": "separate XML/producer quantity; sample mass is not body mass"} if family == "F6" and sample_floating is not None else None),
        "observability": {"first_missing_window_known": True, "possible_unknowns": ["physical destination/fate", "fluid free-surface/pressure response", "rigid force/impulse and coupled dynamics"], "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED"},
    }


def audit(manifest_path: Path, output: Path) -> dict[str, Any]:
    manifest_path, manifest = read_json(manifest_path, "impact stream manifest")
    if manifest.get("schema") != "ds02.stage2.omission-task-impact-stream-manifest.v1" or manifest.get("status") != "IMMUTABLE_SOURCE_SET":
        raise StreamError("manifest is not an immutable stream source set")
    if int(manifest.get("case_count", -1)) != CASE_COUNT or manifest.get("family_case_counts") != FAMILY_CASE_COUNTS:
        raise StreamError("manifest case membership is not exact 48/22/48")
    if any(Path(path).suffix.lower() in {".h5", ".hdf5"} for path in manifest.get("inputs", {})):
        raise StreamError("manifest contains forbidden H5 input")
    for path_text, expected in manifest.get("inputs", {}).items():
        path = require_file(path_text, "manifest input")
        if sha256(path) != expected:
            raise StreamError(f"manifest input changed: {path}")
    cases = [analyze_case(entry) for entry in manifest.get("entries", [])]
    if len(cases) != CASE_COUNT:
        raise StreamError("manifest did not produce all cases")
    family_aggregates: dict[str, dict[str, Any]] = {}
    total_motives: dict[str, Counter[str]] = defaultdict(Counter)
    screen_below: list[str] = []
    screen_above: list[str] = []
    for family in ("F2", "F4", "F6"):
        subset = [case for case in cases if case["family_id"] == family]
        motive_counts = Counter()
        for case in subset:
            motive_counts.update(case["native_motive_counts"])
            (screen_below if case["mass_screen"] == "mass_screen_subset_below_gate" else screen_above).append(case["case_key"])
        total_missing = sum(case["missing_mass_lower_bound_kg"] for case in subset)
        total_denominator = sum(case["typed_initial_fluid_mass_kg"] for case in subset)
        family_aggregates[family] = {"case_count": len(subset), "native_id_count": sum(case["missing_fluid_count"] for case in subset), "native_motive_counts": dict(sorted(motive_counts.items())), "missing_mass_lower_bound_kg": total_missing, "typed_initial_fluid_mass_kg_sum": total_denominator, "weighted_missing_mass_fraction_lower_bound": total_missing / total_denominator if total_denominator else None, "screen_below_gate_case_count": sum(case["mass_screen"] == "mass_screen_subset_below_gate" for case in subset), "screen_above_gate_case_count": sum(case["mass_screen"] == "mass_screen_subset_above_gate" for case in subset), "per_mk_denominator": "UNKNOWN_REQUIRES_BOUND_STATIC_MK_AUDIT"}
        total_motives[family].update(motive_counts)
    observed_motives = {family: dict(sorted(counts.items())) for family, counts in sorted(total_motives.items())}
    if observed_motives != EXPECTED_MOTIVES:
        raise StreamError(f"actual native motive aggregate differs: {observed_motives}")
    output = output.resolve()
    if output.exists():
        raise StreamError(f"preserve existing stream sidecar: {output}")
    result = {
        "schema": OUTPUT_SCHEMA, "status": "TASK_IMPACT_STREAM_AUDITED_TYPED_MASS_SCREEN_DYNAMICS_UNKNOWN",
        "source_manifest": file_binding(manifest_path), "coverage": {"case_count": len(cases), "family_case_counts": FAMILY_CASE_COUNTS, "native_id_count": sum(case["missing_fluid_count"] for case in cases), "native_id_count_by_family": {family: family_aggregates[family]["native_id_count"] for family in ("F2", "F4", "F6")}},
        "cases": cases,
        "family_aggregates": family_aggregates, "native_motive_aggregate": observed_motives,
        "mass_screen": {"registered_gate_fraction": MASS_GATE, "below_gate_cases": sorted(screen_below), "above_gate_cases": sorted(screen_above), "interpretation": "screening lower bound on missing source-visible mass only; below gate is not safe dynamics and above gate is not a bounded error", "acceptance_granted": False},
        "per_mk_status": "UNKNOWN_REQUIRES_BOUND_STATIC_MK_AUDIT",
        "native_cause_scope": "actual PartVTKOut/RunPARTs native motive codes from source-bound forensic sidecars; endpoint MapRealPos/Rhop predicates are not additional causes",
        "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED",
        "read_policy": {"h5_opened": False, "trajectory_part_content_opened": False, "solver_started": False, "partvtkout_started": False, "cfd_or_model_run": False},
        "next_evidence": {"required_for_qualification": ["source-bound static initial mass partition by MK/type", "time-aligned calibrated fluid/rigid observer comparison", "physical destination/fate evidence"], "no_claim_from_mass_screen": True},
    }
    atomic_json(output, result)
    return {"status": result["status"], "output": str(output), "case_count": len(cases), "native_id_count": result["coverage"]["native_id_count"], "native_motive_aggregate": observed_motives}


def prepare_manifest_request(manifest_path: Path, output_request: Path) -> dict[str, Any]:
    manifest_path, manifest = read_json(manifest_path, "impact stream manifest")
    if manifest.get("schema") != "ds02.stage2.omission-task-impact-stream-manifest.v1" or int(manifest.get("case_count", -1)) != CASE_COUNT:
        raise StreamError("manifest is not the exact 118-case source set")
    runtime_dir = SCRIPT.parent
    files = [SCRIPT, manifest_path, runtime_dir / "ds_data02_runtime_v4.py", runtime_dir / "ds_data02_stage2_dispatch_v4.py", runtime_dir / "ds_data02_strict_dispatch_v4.py"]
    files += [Path(value) for value in manifest.get("inputs", {})]
    unique = list(dict.fromkeys(require_file(path, f"request input {Path(path).name}") for path in files))
    output_request = output_request.resolve()
    request = {
        "schema": "ds02.request.v1", "family_id": "infra", "case_id": "STAGE2_OMISSION_TASK_IMPACT_STREAM_118_V1", "physical_case_id": "F2_F4_F6_HISTORICAL_118", "attempt_id": "omission-task-impact-stream-v1-primary-001",
        "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 900, "estimated_storage_bytes": 256 * 1024 * 1024,
        "cwd": str(SCRIPT.parent), "worktree_root": str(SCRIPT.parents[2]), "command": [str(VENV), str(SCRIPT), "audit", "--manifest", str(manifest_path), "--output", "{attempt_root}/omission-task-impact-stream-v1.json"],
        "input_files": [str(path) for path in unique], "input_sha256": {str(path): sha256(path) for path in unique}, "source_manifest": str(manifest_path), "source_manifest_sha256": sha256(manifest_path),
        "source_case_membership": {"F2": 48, "F4": 22, "F6": 48, "native_ids": {"F2": 1078, "F4": 51, "F6": 199}},
        "no_h5_or_solver": True, "launch": True, "launch_allowed": True, "execution_allowed": True, "launch_owner": "root", "shared_lease_required": True, "foreign_process_protection_required": True,
        "mass_screen_gate_fraction": MASS_GATE, "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED",
        "request_note": "Source-bound 118-case typed impact stream audit. Reads only small JSON/native evidence and hashes; no H5, trajectory frames, PartVTKOut, solver, CFD, or model. The 0.003 gate is a mass screen, never dynamics credit.",
    }
    atomic_json(output_request, request)
    return {"status": "prepared", "request": str(output_request), "request_sha256": sha256(output_request), "input_count": len(unique), "manifest_sha256": sha256(manifest_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    make = sub.add_parser("make-manifest")
    make.add_argument("--output", type=Path, required=True)
    make.add_argument("--data-root", type=Path, default=DATA_ROOT)
    prep = sub.add_parser("prepare")
    prep.add_argument("--manifest", type=Path, required=True)
    prep.add_argument("--output-request", type=Path, required=True)
    aud = sub.add_parser("audit")
    aud.add_argument("--manifest", type=Path, required=True)
    aud.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "make-manifest":
            result = make_manifest(args.output, args.data_root)
        elif args.action == "prepare":
            result = prepare_manifest_request(args.manifest, args.output_request)
        else:
            result = audit(args.manifest, args.output)
    except StreamError as exc:
        raise SystemExit(f"StreamError: {exc}")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
