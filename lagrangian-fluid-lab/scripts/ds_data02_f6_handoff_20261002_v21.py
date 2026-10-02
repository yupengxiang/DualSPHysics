#!/usr/bin/env python3
"""F6 PartVTKOut lifecycle requests and native exclusion reconciliation."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
V20 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v20.py")
V20_SPEC = importlib.util.spec_from_file_location("f6_handoff_v20_for_partvtkout", V20)
if V20_SPEC is None or V20_SPEC.loader is None:
    raise RuntimeError(f"cannot load v20: {V20}")
V20_MODULE = importlib.util.module_from_spec(V20_SPEC)
V20_SPEC.loader.exec_module(V20_MODULE)

V19_MODULE = V20_MODULE.V19_MODULE
V16_MODULE = V19_MODULE.V16_MODULE
FAMILY_ROOT = V20_MODULE.FAMILY_ROOT
RAW_ROOT = V20_MODULE.RAW_ROOT
INTEGRATION_LAB = V20_MODULE.INTEGRATION_LAB
VENV_PYTHON = V20_MODULE.VENV_PYTHON
PARTVTKOUT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64")
NATIVE_LABELS = V16_MODULE.NATIVE_LABELS
SIMPLE_LABEL_CONFIG = V16_MODULE.SIMPLE_LABEL_CONFIG
WAVE_LABEL_CONFIG = V16_MODULE.WAVE_LABEL_CONFIG
POST_ROOT = FAMILY_ROOT / "postprocessing_006"
REQUEST_ROOT = POST_ROOT / "execution_requests"

CASES = [
    ("simple_free_response", "coarse", "F6_HANDOFF_20261002_SIMPLE_FREE_RESPONSE_RIGID003_DOMAIN_XY_REPAIR_02_COARSE"),
    ("simple_free_response", "medium", "F6_HANDOFF_20261002_SIMPLE_FREE_RESPONSE_RIGID003_DOMAIN_X_REPAIR_01_MEDIUM"),
    ("simple_free_response", "fine", "F6_HANDOFF_20261002_SIMPLE_FREE_RESPONSE_RIGID003_DOMAIN_XY_REPAIR_02_FINE"),
    ("wave_no_contact", "coarse", "F6_HANDOFF_20261002_WAVE_NO_CONTACT_RIGID003_DOMAIN_XY_REPAIR_02_COARSE"),
    ("wave_no_contact", "medium", "F6_HANDOFF_20261002_WAVE_NO_CONTACT_RIGID003_DOMAIN_X_REPAIR_01_MEDIUM"),
    ("wave_no_contact", "fine", "F6_HANDOFF_20261002_WAVE_NO_CONTACT_RIGID003_DOMAIN_XY_REPAIR_02_FINE"),
]


def sha256(path: Path) -> str:
    return V20_MODULE.sha256(path)


def read_json(path: Path) -> dict[str, Any]:
    return V20_MODULE.read_json(path)


def write_json(path: Path, value: Any) -> None:
    V20_MODULE.write_json(path, value)


def _case_paths(case_id: str) -> dict[str, Path]:
    case_root = RAW_ROOT / case_id
    solver_attempt = case_root / f"{case_id}_SOLVER_QUAL_001"
    solver_root = solver_attempt / "solver_output"
    gencase = case_root / f"{case_id}_GENCASE_001"
    return {
        "case_root": case_root,
        "solver_attempt": solver_attempt,
        "solver_root": solver_root,
        "data": solver_root / "data",
        "runparts": solver_root / "RunPARTs.csv",
        "runout": solver_root / "Run.out",
        "solver_receipt": solver_attempt / "execution-receipt.json",
        "xml": gencase / f"{case_id}.xml",
        "gencase_bi4": gencase / f"{case_id}.bi4",
        "gencase_receipt": gencase / "execution-receipt.json",
    }


def _input_files(paths: dict[str, Path], mechanism: str, resolution: str) -> list[Path]:
    files = [SCRIPT, V20, V19_MODULE.SCRIPT, PARTVTKOUT, paths["runparts"], paths["runout"], paths["solver_receipt"], paths["xml"], paths["gencase_bi4"], paths["gencase_receipt"]]
    files.extend(sorted(paths["data"].glob("PartOut_*.obi4")))
    # Bind the actual solver request/receipt and the immutable repair audit;
    # the PartVTKOut command itself reads only the data directory.
    files.append(V16_MODULE.AUDIT_PATH)
    if resolution == "medium":
        files.append(V16_MODULE.MEDIUM_AUDIT_PATH)
    result: list[Path] = []
    seen: set[str] = set()
    for value in files:
        path = Path(value)
        key = str(path.resolve())
        if key not in seen:
            seen.add(key)
            result.append(path)
    missing = [str(path) for path in result if not path.is_file()]
    if missing:
        raise FileNotFoundError("PartVTKOut input missing: " + ", ".join(missing))
    return result


def prepare() -> dict[str, Any]:
    REQUEST_ROOT.mkdir(parents=True, exist_ok=True)
    requests: list[dict[str, Any]] = []
    for mechanism, resolution, case_id in CASES:
        paths = _case_paths(case_id)
        inputs = _input_files(paths, mechanism, resolution)
        strings = [str(path.resolve()) for path in inputs]
        attempt = f"{case_id}_PARTVTKOUT_001"
        output_root = RAW_ROOT / case_id / attempt
        csv_out = output_root / "excluded.csv"
        resume_out = output_root / "excluded-resume.csv"
        request = {
            "schema": "ds02.runner.request.v1",
            "family_id": "F6",
            "case_id": case_id,
            "mechanism_id": mechanism,
            "resolution_id": resolution,
            "attempt_id": attempt,
            "kind": "cpu",
            "cpu_task_kind": "audit",
            "cpu_threads": 4,
            "max_wall_seconds": 600,
            "estimated_storage_bytes": 268435456,
            "worktree_root": str(V16_MODULE.MODULE.REPO_ROOT.resolve()),
            "cwd": str(paths["solver_root"].resolve()),
            "command": [str(PARTVTKOUT), "-dirdata", str(paths["data"].resolve()), "-savecsv", "{attempt_root}/excluded.csv", "-saveresume", "{attempt_root}/excluded-resume.csv", "-createdirs:1", "-csvsep:1"],
            "input_files": strings,
            "input_hashes_at_request": {key: sha256(Path(key)) for key in strings},
            "source_solver_attempt": str(paths["solver_attempt"].resolve()),
            "source_solver_receipt_sha256": sha256(paths["solver_receipt"]),
            "source_partout_files": [str(path.resolve()) for path in sorted(paths["data"].glob("PartOut_*.obi4"))],
            "output_contract": {"csv": str(csv_out), "resume": str(resume_out), "official_binary": str(PARTVTKOUT), "join_key": "PartOut/Idp", "native_reason_source": "RunPARTs.csv"},
            "purpose": "official PartVTKOut decode of every native exclusion file; preserve unknown physical destination until RunPARTs join",
            "gpu_launch": False,
            "q_n_status": "pending_native_exclusion_reconciliation",
        }
        path = REQUEST_ROOT / f"{case_id}_partvtkout_001.json"
        write_json(path, request)
        requests.append({"path": str(path.resolve()), "sha256": sha256(path), "kind": "partvtkout", "case_id": case_id})

    # Enriched H5 labels are only prepared after both medium H5_004 receipts
    # exist.  Their requests are emitted by prepare-labels, preserving this
    # six-case PartVTKOut request manifest as an immutable dispatch card.
    result = {"schema": "ds-data-02.f6.rigid003.postprocessing_006.requests_001.v1", "family_id": "F6", "status": "prepared_pending_shared_cpu_audit", "requests": requests, "gpu_launch": False, "q_n_status": "pending PartVTKOut and enriched H5 labels"}
    write_json(POST_ROOT / "request_manifest.json", result)
    return result


def prepare_labels() -> dict[str, Any]:
    REQUEST_ROOT.mkdir(parents=True, exist_ok=True)
    requests: list[dict[str, Any]] = []
    for mechanism in ("simple_free_response", "wave_no_contact"):
        case = V16_MODULE._old_medium_case(mechanism)
        cid = str(case["case_id"])
        h5 = RAW_ROOT / cid / f"{cid}_NATIVE_H5_004/trajectory.h5"
        report = h5.with_name("conversion-report.json")
        if not h5.is_file() or not report.is_file():
            raise FileNotFoundError(f"enriched H5 is pending: {h5}")
        config = SIMPLE_LABEL_CONFIG if mechanism == "simple_free_response" else WAVE_LABEL_CONFIG
        attempt = f"{cid}_LABELS_004"
        inputs = [SCRIPT, V20, V19_MODULE.SCRIPT, NATIVE_LABELS, config, h5, report]
        strings = [str(Path(path).resolve()) for path in inputs]
        output = RAW_ROOT / cid / attempt / "native-labels.h5"
        request = {
            "schema": "ds02.runner.request.v1",
            "family_id": "F6",
            "case_id": cid,
            "mechanism_id": mechanism,
            "resolution_id": "medium",
            "attempt_id": attempt,
            "kind": "cpu",
            "cpu_task_kind": "labels",
            "cpu_threads": 2,
            "max_wall_seconds": 900,
            "estimated_storage_bytes": 536870912,
            "worktree_root": str(V16_MODULE.MODULE.REPO_ROOT.resolve()),
            "cwd": str(INTEGRATION_LAB.resolve()),
            "command": [str(VENV_PYTHON), str(SCRIPT), "run-labels", "--source", str(h5.resolve()), "--config", str(config.resolve()), "--output", "{attempt_root}/native-labels.h5"],
            "input_files": strings,
            "input_hashes_at_request": {key: sha256(Path(key)) for key in strings},
            "source_trajectory": str(h5.resolve()),
            "source_trajectory_sha256": sha256(h5),
            "source_conversion_report_sha256": sha256(report),
            "output_contract": {"labels": str(output), "source_rigid_metadata": "enriched H5_004", "fluid_type3_only": True},
            "purpose": "materialize event labels from enriched sparse H5; no model and no Q-N claim",
            "gpu_launch": False,
            "q_n_status": "pending_native_exclusion_reconciliation",
        }
        path = REQUEST_ROOT / f"{cid}_labels_004.json"
        write_json(path, request)
        requests.append({"path": str(path.resolve()), "sha256": sha256(path), "kind": "labels", "case_id": cid})
    sidecar = {"schema": "ds-data-02.f6.rigid003.postprocessing_006.labels_004.v1", "family_id": "F6", "source_enriched_attempt": "NATIVE_H5_004", "old_sparse_h5_003_preserved": True, "gpu_launch": False, "q_n_status": "pending_native_exclusion_reconciliation", "requests": requests}
    write_json(POST_ROOT / "labels_004_evidence.json", sidecar)
    return sidecar


def _clean_key(value: Any) -> str:
    return str(value or "").strip().lstrip("\ufeff").rstrip(",").strip()


def _number(value: Any) -> float | None:
    try:
        return float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    number = _number(value)
    return None if number is None else int(number)


def _row_value(row: dict[str, Any], *names: str) -> Any:
    lower = {_clean_key(key).lower(): value for key, value in row.items() if key is not None}
    for name in names:
        if name.lower() in lower:
            return lower[name.lower()]
    for key, value in lower.items():
        if any(name.lower() in key for name in names):
            return value
    return None


def _runparts(path: Path) -> dict[str, Any]:
    lines = path.read_text(errors="replace").splitlines()
    header = next((i for i, line in enumerate(lines) if line.strip().startswith("Part;")), None)
    if header is None:
        return {"status": "missing_header", "rows": [], "totals": {}}
    rows: list[dict[str, Any]] = []
    for raw in csv.DictReader(lines[header:], delimiter=";"):
        part = _int(_row_value(raw, "Part"))
        t = _number(_row_value(raw, "TimeStep [s]"))
        if part is None or t is None:
            continue
        values = {name: _int(_row_value(raw, label)) or 0 for name, label in (("np_out", "NpOut"), ("np_out_pos", "NpOutPos"), ("np_out_rho", "NpOutRho"), ("np_out_mov", "NpOutMov"))}
        rows.append({"part": part, "time_s": t, **values})
    totals = {name: sum(row[name] for row in rows) for name in ("np_out", "np_out_pos", "np_out_rho", "np_out_mov")}
    first_nonzero = {name: next((row for row in rows if row[name] > 0), None) for name in ("np_out", "np_out_pos", "np_out_rho", "np_out_mov")}
    return {"status": "available", "rows": rows, "totals": totals, "first_nonzero": first_nonzero}


def _xml_roles(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    groups = []
    particles = root.find(".//execution/particles")
    if particles is not None:
        for role in ("fixed", "moving", "floating", "fluid"):
            for node in particles.findall(role):
                if node.get("begin") is not None and node.get("count") is not None:
                    groups.append((int(node.get("begin")), int(node.get("count")), role))
    def role_for(pid: int) -> str:
        for begin, count, role in groups:
            if begin <= pid < begin + count:
                return role
        return "unknown"
    return {"groups": [{"begin": begin, "count": count, "role": role} for begin, count, role in groups], "role_for": role_for}


def _partvtkout_csv(path: Path, runparts: dict[str, Any], roles: dict[str, Any]) -> dict[str, Any]:
    text = path.read_text(errors="replace")
    first = next((line for line in text.splitlines() if line.strip()), "")
    delimiter = ";" if first.count(";") > first.count(",") else ","
    native_by_part = {row["part"]: row for row in runparts["rows"]}
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for raw in csv.DictReader(text.splitlines(), delimiter=delimiter):
        pid = _int(_row_value(raw, "Idp", "IDp", "Id"))
        part = _int(_row_value(raw, "PartOut", "Part Out"))
        if pid is None or part is None:
            errors.append("malformed_row")
            continue
        native = native_by_part.get(part)
        counters = {"position": int(native["np_out_pos"]) if native else 0, "density": int(native["np_out_rho"]) if native else 0, "movement": int(native["np_out_mov"]) if native else 0}
        active = [name for name, value in counters.items() if value]
        reason = active[0] if len(active) == 1 else ("multiple" if len(active) > 1 else "unknown")
        rows.append({"particle_id": pid, "part_out": part, "time_s": native["time_s"] if native else None, "motive": _int(_row_value(raw, "Motive")), "role": roles["role_for"](pid), "native_reason": reason, "native_reason_counters": counters, "position_m": [_number(_row_value(raw, f"Pos.{axis} [m]")) for axis in "xyz"], "density_kg_m3": _number(_row_value(raw, "Rhop [kg/m^3]"))})
    return {"status": "available" if not errors else "available_with_findings", "delimiter": delimiter, "rows": rows, "errors": errors, "reason_counts": dict(Counter(row["native_reason"] for row in rows)), "role_counts": dict(Counter(row["role"] for row in rows))}


def summarize() -> dict[str, Any]:
    manifest = read_json(POST_ROOT / "request_manifest.json")
    outputs: list[dict[str, Any]] = []
    for entry in manifest["requests"]:
        request = read_json(Path(entry["path"]))
        case_id = request["case_id"]
        attempt = RAW_ROOT / case_id / request["attempt_id"]
        csv_path = attempt / "excluded.csv"
        receipt = attempt / "execution-receipt.json"
        paths = _case_paths(case_id)
        runparts = _runparts(paths["runparts"])
        roles = _xml_roles(paths["xml"])
        decoded = _partvtkout_csv(csv_path, runparts, roles) if csv_path.is_file() else {"status": "missing", "rows": []}
        first_missing = None
        h5_report = RAW_ROOT / case_id / f"{case_id}_NATIVE_H5_004/conversion-report.json"
        if h5_report.is_file():
            first_missing = read_json(h5_report).get("first_missing")
        outputs.append({"case_id": case_id, "mechanism_id": request["mechanism_id"], "resolution_id": request["resolution_id"], "receipt": {"path": str(receipt.resolve()), "sha256": sha256(receipt) if receipt.is_file() else None, "status": read_json(receipt).get("status") if receipt.is_file() else "missing", "returncode": read_json(receipt).get("returncode") if receipt.is_file() else None}, "runparts": {"totals": runparts["totals"], "first_nonzero": runparts["first_nonzero"]}, "partvtkout": {"csv": str(csv_path.resolve()), "csv_sha256": sha256(csv_path) if csv_path.is_file() else None, "decoded": decoded}, "first_missing_initial_cohort": first_missing, "unknown_physical_destination_preserved": True, "q_n_status": "pending_native_exclusion_reconciliation"})
    result = {"schema": "ds-data-02.f6.rigid003.partvtkout-reconciliation.v1", "family_id": "F6", "status": "review_only", "cases": outputs, "qualification_claim": "none", "production_claim": "none", "unknown_policy": "A PartVTKOut row without a unique RunPARTs reason remains unknown; no physical destination is inferred."}
    write_json(POST_ROOT / "partvtkout_reconciliation_001.json", result)
    return result


def _run_labels(args: argparse.Namespace) -> int:
    return V19_MODULE._run_labels(args)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "prepare-labels", "summarize", "run-labels"])
    parser.add_argument("--source", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        print(json.dumps(prepare(), ensure_ascii=False, indent=2))
        return 0
    if args.action == "prepare-labels":
        print(json.dumps(prepare_labels(), ensure_ascii=False, indent=2))
        return 0
    if args.action == "summarize":
        print(json.dumps(summarize(), ensure_ascii=False, indent=2))
        return 0
    for name in ("source", "config", "output"):
        if getattr(args, name) is None:
            parser.error(f"run-labels requires --{name}")
    return _run_labels(args)


if __name__ == "__main__":
    raise SystemExit(main())
