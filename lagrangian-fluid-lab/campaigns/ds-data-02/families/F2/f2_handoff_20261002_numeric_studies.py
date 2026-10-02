#!/usr/bin/env python3
"""Freeze F2 medium internal-step and save-cadence comparison requests.

This is a request materializer only.  It reads the completed center and
offset medium RunPARTs logs, chooses one common fixed step equal to half the
smallest positive baseline ``DtMin [s]`` seen in either run, and writes two
numerical views per background:

* ``half_dt`` uses that explicit ``DtFixed`` and the baseline 0.01 s save;
* ``half_save`` retains adaptive integration and changes only ``TimeOut`` to
  0.005 s.

The generated XMLs and copied BI4 geometry live in the data product area and
are independent inputs.  No solver, GenCase, or GPU process is launched by
this module.  Every request retains the physical binding, source hashes, and
the complete 4 s window, while leaving qualification and production claims
unassigned.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any, Iterable


FAMILY = "F2"
SCOPE = "F2_SCOPE_GEM_COMMENSURATE_CELLCENTER_20261002_V2"
LAB_ROOT = Path(__file__).resolve().parents[4]
FAMILY_ROOT = LAB_ROOT / "campaigns/ds-data-02/families/F2"
HANDOFF = FAMILY_ROOT / "handoff_20261002"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
DATA_FAMILY_ROOT = DATA_ROOT / "families/F2"
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
QUALITY = FAMILY_ROOT / "quality_contract.json"
EVENTS = FAMILY_ROOT / "event_definitions.json"
SAVE_PLAN = FAMILY_ROOT / "integration_save_plan.json"


class StudyError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def require(path: Path, label: str) -> Path:
    path = path.resolve()
    if not path.is_file():
        raise StudyError(f"{label} is missing: {path}")
    return path


def load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(require(path, label).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StudyError(f"{label} is not valid JSON: {path}") from error
    if not isinstance(value, dict):
        raise StudyError(f"{label} must be an object: {path}")
    return value


def bindings(paths: Iterable[Path]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for path in paths:
        path = require(Path(path), "study input")
        result[str(path)] = {"path": str(path), "sha256": sha256(path)}
    return result


def positive_baseline_dtmins(runparts: Path) -> list[float]:
    values: list[float] = []
    with require(runparts, "RunPARTs.csv").open(encoding="utf-8", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            try:
                value = float(str(row["DtMin [s]"]).strip().replace(",", ""))
            except (KeyError, TypeError, ValueError):
                continue
            if value > 0:
                values.append(value)
    if not values:
        raise StudyError(f"RunPARTs.csv has no positive DtMin [s] values: {runparts}")
    return values


def solver_artifacts(solver_receipt: Path) -> tuple[dict[str, Any], Path, Path, Path, Path, Path]:
    receipt = load(solver_receipt, "solver receipt")
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise StudyError("solver receipt must be terminal completed with returncode=0")
    request = receipt.get("request", {})
    prefix = Path(str(request.get("gencase_input_prefix", ""))).resolve()
    xml = require(prefix.with_suffix(".xml"), "baseline generated XML")
    bi4 = require(prefix.with_suffix(".bi4"), "baseline generated BI4")
    root = (Path(str(receipt.get("output_root", ""))) / "solver_output").resolve()
    if not root.is_dir():
        raise StudyError(f"solver output is missing: {root}")
    runparts = require(root / "RunPARTs.csv", "baseline RunPARTs.csv")
    motion_name = f"{prefix.name}_motion.dat"
    motion = require(prefix.parent / motion_name, "baseline copied motion")
    return receipt, xml, bi4, motion, runparts, root


def replace_parameter(xml_text: str, key: str, value: str) -> str:
    pattern = rf'(<parameter\s+key="{re.escape(key)}"\s+value=")[^"]*("\s*/>)'
    updated, count = re.subn(pattern, rf"\g<1>{value}\g<2>", xml_text)
    if count != 1:
        raise StudyError(f"expected one XML parameter {key}, found {count}")
    return updated


def make_xml(source: Path, destination: Path, *, study: str, dt_fixed: float, time_out: float) -> None:
    text = require(source, "baseline generated XML").read_text(encoding="utf-8")
    text = replace_parameter(text, "DtFixed", f"{dt_fixed:.17g}")
    text = replace_parameter(text, "TimeOut", f"{time_out:.17g}")
    marker = f"<!-- F2 numerical study={study}; physical geometry and motion unchanged; full window=4 s; -->\n"
    if marker not in text:
        text = text.replace("?>\n", "?>\n" + marker, 1)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")


def make_request(*, case_id: str, background: str, study: str, prefix: Path, xml: Path, bi4: Path,
                 motion: Path, solver_receipt: Path, owner: Path, baseline_runparts: Path,
                 baseline_min_dt: float, common_min_dt: float, output: Path) -> dict[str, Any]:
    numerical = {
        "study": study,
        "physical_condition_hash": load(owner, "owner metadata").get("physical_condition_hash_declared", ""),
        "baseline_positive_dtmin_min_s": baseline_min_dt,
        "common_baseline_positive_dtmin_min_s": common_min_dt,
        "dt_fixed_s": float(f"{common_min_dt / 2:.17g}") if study == "half_dt" else 0.0,
        "time_out_s": 0.01 if study == "half_dt" else 0.005,
        "time_max_s": 4.0,
        "integration_control": "explicit DtFixed halves the common observed baseline minimum; half_save leaves DtFixed=0 and halves only TimeOut",
    }
    numerical_hash = canonical_hash(numerical)
    input_files = [Path(__file__), SOLVER, xml, bi4, motion, solver_receipt, owner, baseline_runparts, QUALITY, EVENTS, SAVE_PLAN]
    request = {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": FAMILY,
        "scope_id": SCOPE,
        "kind": "qualification",
        "attempt_id": f"qualification-{case_id.lower()}-{study}-4s-v1",
        "case_id": case_id,
        "background": background,
        "command": [str(SOLVER), str(prefix), "{attempt_root}/solver_output"],
        "cwd": str(prefix.parent),
        "input_prefix": str(prefix),
        "input_files": [str(Path(path).resolve()) for path in input_files],
        "source_bindings": bindings(input_files),
        "gencase_artifacts": {
            "xml": {"path": str(xml), "sha256": sha256(xml)},
            "bi4": {"path": str(bi4), "sha256": sha256(bi4)},
            "copied_motion": {"path": str(motion), "sha256": sha256(motion)},
            "solver_receipt": {"path": str(solver_receipt.resolve()), "sha256": sha256(solver_receipt)},
        },
        "physical_condition_hash": str(numerical["physical_condition_hash"]),
        "numerical_recipe_hash": numerical_hash,
        "numerical_study": numerical,
        "event_window_s": 4.0,
        "control_family_id": "F2_CTRL_SMOOTH_ROTATE_Y_GEM_V2",
        "geometry_family_id": f"F2_GEOM_GEM_CUP_RECEIVER_{background.upper()}_V2",
        "cpu_threads": 4,
        "max_wall_seconds": 600,
        "estimated_peak_gpu_mib": 4096,
        "estimated_storage_bytes": 4 * 1024**3,
        "gpu_launch": {"family_owner_launch": False, "requested_by": "root_primary_process"},
        "raw_output_root": str(DATA_FAMILY_ROOT),
        "worktree_root": str(LAB_ROOT.parent),
        "request_note": "Prepared-only independent F2 numeric comparison; copied geometry BI4 and motion are hash-bound, complete 4 s window retained, no Q-I/Q-N/production claim.",
        "qualification_claim": "none",
        "expected_outputs": {"receipt": str(output / "execution-receipt.json"), "solver_output": str(output / "solver_output")},
    }
    return request


def prepare_pair(*, center_solver_receipt: Path, offset_solver_receipt: Path,
                 center_owner: Path, offset_owner: Path, output_root: Path) -> dict[str, Any]:
    cases = [("center_catch", center_solver_receipt, center_owner), ("offset_spill", offset_solver_receipt, offset_owner)]
    records: list[dict[str, Any]] = []
    parsed: list[tuple[str, dict[str, Any], Path, Path, Path, Path, Path, list[float]]] = []
    for background, receipt_path, owner_path in cases:
        receipt, xml, bi4, motion, runparts, solver_output = solver_artifacts(receipt_path)
        owner = load(owner_path, "owner metadata")
        case_id = str(owner["case_id"])
        if str(receipt.get("request", {}).get("case_id", case_id)) != case_id:
            raise StudyError(f"solver receipt case_id differs from owner metadata: {case_id}")
        mins = positive_baseline_dtmins(runparts)
        parsed.append((background, receipt, xml, bi4, motion, runparts, solver_output, mins))
    common_min = min(min(mins) for *_, mins in parsed)
    common_half = common_min / 2.0
    for background, receipt, baseline_xml, baseline_bi4, baseline_motion, runparts, solver_output, mins in parsed:
        case_id = str(load(center_owner if background == "center_catch" else offset_owner, "owner metadata")["case_id"])
        owner_path = center_owner if background == "center_catch" else offset_owner
        case_root = DATA_FAMILY_ROOT / case_id / "numerical-studies-20261002"
        for study in ("half_dt", "half_save"):
            study_root = case_root / study
            prefix = study_root / case_id
            xml = prefix.with_suffix(".xml")
            bi4 = prefix.with_suffix(".bi4")
            motion = prefix.parent / f"{case_id}_motion.dat"
            make_xml(baseline_xml, xml, study=study, dt_fixed=common_half if study == "half_dt" else 0.0,
                     time_out=0.01 if study == "half_dt" else 0.005)
            shutil.copy2(baseline_bi4, bi4)
            shutil.copy2(baseline_motion, motion)
            request_output = case_root / f"{study}-qualification-4s-v1"
            request = make_request(case_id=case_id, background=background, study=study, prefix=prefix,
                                   xml=xml, bi4=bi4, motion=motion, solver_receipt=receipt_path,
                                   owner=owner_path, baseline_runparts=runparts,
                                   baseline_min_dt=min(mins), common_min_dt=common_min, output=request_output)
            request_path = output_root / "requests" / f"{case_id}_{study}_qualification_request.json"
            request_path.parent.mkdir(parents=True, exist_ok=True)
            request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            records.append({"case_id": case_id, "background": background, "study": study,
                            "request": str(request_path.resolve()), "request_sha256": sha256(request_path),
                            "xml": {"path": str(xml), "sha256": sha256(xml)},
                            "bi4": {"path": str(bi4), "sha256": sha256(bi4)},
                            "motion": {"path": str(motion), "sha256": sha256(motion)},
                            "baseline_min_positive_dtmin_s": min(mins),
                            "common_min_positive_dtmin_s": common_min,
                            "dt_fixed_s": common_half if study == "half_dt" else 0.0,
                            "time_out_s": 0.01 if study == "half_dt" else 0.005})
    manifest = {
        "schema": "ds-data-02.f2.numeric-study-plan.v1",
        "scope_id": SCOPE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "physical_geometry_unchanged": True,
        "event_window_s": 4.0,
        "mass_rescaling": False,
        "qualification_claim": "none",
        "baseline_dtmin_statistic": "minimum positive DtMin [s] over all RunPARTs save rows in the two completed medium baselines",
        "common_min_positive_dtmin_s": common_min,
        "common_half_dt_fixed_s": common_half,
        "studies": records,
        "q_n": "not assessed until root runs both integration and save comparisons and evaluates frozen event/physical error budgets",
    }
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / "numeric-study-plan.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest["manifest"] = {"path": str(manifest_path.resolve()), "sha256": sha256(manifest_path)}
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--center-solver-receipt", type=Path, required=True)
    parser.add_argument("--offset-solver-receipt", type=Path, required=True)
    parser.add_argument("--center-owner", type=Path, required=True)
    parser.add_argument("--offset-owner", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=HANDOFF / "numerical_studies")
    args = parser.parse_args(argv)
    try:
        result = prepare_pair(center_solver_receipt=args.center_solver_receipt, offset_solver_receipt=args.offset_solver_receipt,
                              center_owner=args.center_owner, offset_owner=args.offset_owner, output_root=args.output_root)
    except (StudyError, OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"f2_handoff_20261002_numeric_studies: {type(error).__name__}: {error}")
        return 2
    print(json.dumps({"status": "prepared_only", "manifest": result["manifest"], "study_count": len(result["studies"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
