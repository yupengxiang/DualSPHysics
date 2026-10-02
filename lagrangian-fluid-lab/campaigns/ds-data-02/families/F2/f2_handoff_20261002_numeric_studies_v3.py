#!/usr/bin/env python3
"""Freeze corrected F2 medium internal-step and save-cadence requests.

This is a request materializer only.  It reads the completed center and
offset medium RunPARTs logs, chooses one common fixed step equal to half the
smallest positive baseline ``DtMin [s]`` seen in either run, and writes two
numerical views per background:

* ``half_dt`` uses that explicit ``DtFixed`` and the baseline 0.01 s save;
* ``half_save`` retains adaptive integration and changes only ``TimeOut`` to
  0.005 s.

The v3 materializer keeps the solver receipt with its own background (the v1
materializer accidentally reused the final loop receipt for both views),
proves that the study XML differs from its baseline only in ``DtFixed`` and
``TimeOut``, and binds equal BI4/motion hashes.  It also records the baseline
first positive step as a post-run guard for the explicit fixed-step view.
No solver, GenCase, or GPU process is launched by this module.  Every request
retains the physical binding, source hashes, and the complete 4 s window,
while leaving qualification and production claims unassigned.
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
from typing import Any, Iterable, Mapping


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


def xml_parameters(path: Path) -> dict[str, str]:
    text = require(path, "study XML").read_text(encoding="utf-8")
    return {key: value for key, value in re.findall(r'<parameter\s+key="([^"]+)"\s+value="([^"]*)"', text)}


def normalized_xml(path: Path) -> str:
    """Remove the study marker and normalize only the two allowed controls."""
    text = require(path, "study XML").read_text(encoding="utf-8")
    text = re.sub(r"<!-- F2 numerical study=.*?-->\n", "", text)
    for key in ("DtFixed", "TimeOut"):
        text, count = re.subn(
            rf'(<parameter\s+key="{re.escape(key)}"\s+value=")[^"]*("\s*/>)',
            rf"\g<1>__CONTROL_{key}__\g<2>", text,
        )
        if count != 1:
            raise StudyError(f"expected one XML parameter {key} while comparing {path}, found {count}")
    return text


def first_positive_dt(runparts: Path) -> dict[str, float]:
    with require(runparts, "RunPARTs.csv").open(encoding="utf-8", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            try:
                dtmin = float(str(row["DtMin [s]"]).strip().replace(",", ""))
                dtmax = float(str(row["DtMax [s]"]).strip().replace(",", ""))
            except (KeyError, TypeError, ValueError):
                continue
            if dtmin > 0:
                return {"dtmin_s": dtmin, "dtmax_s": dtmax}
    raise StudyError(f"RunPARTs.csv has no first positive DtMin [s] row: {runparts}")


def make_request(*, case_id: str, background: str, study: str, prefix: Path, xml: Path, bi4: Path,
                 motion: Path, solver_receipt: Path, owner: Path, baseline_runparts: Path,
                 baseline_min_dt: float, common_min_dt: float, baseline_first_dt: Mapping[str, float],
                 physical_equality: Mapping[str, Any], baseline_parameters: Mapping[str, str], output: Path) -> dict[str, Any]:
    numerical = {
        "study": study,
        "physical_condition_hash": load(owner, "owner metadata").get("physical_condition_hash_declared", ""),
        "baseline_positive_dtmin_min_s": baseline_min_dt,
        "baseline_first_positive_dtmin_s": float(baseline_first_dt["dtmin_s"]),
        "baseline_first_positive_dtmax_s": float(baseline_first_dt["dtmax_s"]),
        "common_baseline_positive_dtmin_min_s": common_min_dt,
        "dt_fixed_s": float(f"{common_min_dt / 2:.17g}") if study == "half_dt" else 0.0,
        "time_out_s": 0.01 if study == "half_dt" else 0.005,
        "xml_dtini": str(baseline_parameters.get("DtIni", "")),
        "xml_dtmin": str(baseline_parameters.get("DtMin", "")),
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
        "physical_input_equality": dict(physical_equality),
        "post_run_checks": {
            "first_step_guard": {
                "criterion": "half_dt RunPARTs first positive DtMax must be <= the bound recorded from this same background baseline",
                "bound_s": float(baseline_first_dt["dtmax_s"]),
                "must_be_evaluated_after_run": True,
            },
            "dtini_dtmin_semantics": "DtIni and DtMin remain exactly the baseline XML values; only DtFixed is changed for half_dt, and actual RunPARTs DtMin/DtMax must be reported before any numerical conclusion",
        },
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
    parsed: list[tuple[str, Path, dict[str, Any], Path, Path, Path, Path, Path, list[float], dict[str, float]]] = []
    for background, receipt_path, owner_path in cases:
        receipt, xml, bi4, motion, runparts, solver_output = solver_artifacts(receipt_path)
        owner = load(owner_path, "owner metadata")
        case_id = str(owner["case_id"])
        if str(receipt.get("request", {}).get("case_id", case_id)) != case_id:
            raise StudyError(f"solver receipt case_id differs from owner metadata: {case_id}")
        mins = positive_baseline_dtmins(runparts)
        parsed.append((background, receipt_path.resolve(), receipt, xml, bi4, motion, runparts, solver_output, mins, first_positive_dt(runparts)))
    common_min = min(min(mins) for _, _, _, _, _, _, _, _, mins, _ in parsed)
    common_half = common_min / 2.0
    for background, solver_receipt_path, receipt, baseline_xml, baseline_bi4, baseline_motion, runparts, solver_output, mins, first_dt in parsed:
        case_id = str(load(center_owner if background == "center_catch" else offset_owner, "owner metadata")["case_id"])
        owner_path = center_owner if background == "center_catch" else offset_owner
        case_root = DATA_FAMILY_ROOT / case_id / "numerical-studies-20261002-v3"
        baseline_params = xml_parameters(baseline_xml)
        if baseline_params.get("DtIni") != "0" or baseline_params.get("DtMin") != "0":
            raise StudyError(f"baseline {case_id} has unexpected DtIni/DtMin: {baseline_params.get('DtIni')}, {baseline_params.get('DtMin')}")
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
            study_params = xml_parameters(xml)
            if study_params.get("DtIni") != baseline_params.get("DtIni") or study_params.get("DtMin") != baseline_params.get("DtMin"):
                raise StudyError(f"{case_id} {study} changed DtIni/DtMin")
            if normalized_xml(baseline_xml) != normalized_xml(xml):
                raise StudyError(f"{case_id} {study} XML changed fields beyond DtFixed/TimeOut")
            physical_equality = {
                "xml_allowed_control_changes": ["DtFixed", "TimeOut"],
                "xml_normalized_equal": True,
                "baseline_xml_sha256": sha256(baseline_xml),
                "study_xml_sha256": sha256(xml),
                "baseline_xml_normalized_sha256": hashlib.sha256(normalized_xml(baseline_xml).encode()).hexdigest(),
                "study_xml_normalized_sha256": hashlib.sha256(normalized_xml(xml).encode()).hexdigest(),
                "bi4_hash_equal": sha256(baseline_bi4) == sha256(bi4),
                "baseline_bi4_sha256": sha256(baseline_bi4),
                "study_bi4_sha256": sha256(bi4),
                "motion_hash_equal": sha256(baseline_motion) == sha256(motion),
                "baseline_motion_sha256": sha256(baseline_motion),
                "study_motion_sha256": sha256(motion),
            }
            if not physical_equality["bi4_hash_equal"] or not physical_equality["motion_hash_equal"]:
                raise StudyError(f"{case_id} {study} copied physical input hash mismatch")
            request_output = case_root / f"{study}-qualification-4s-v1"
            request = make_request(case_id=case_id, background=background, study=study, prefix=prefix,
                                   xml=xml, bi4=bi4, motion=motion, solver_receipt=solver_receipt_path,
                                   owner=owner_path, baseline_runparts=runparts,
                                   baseline_min_dt=min(mins), common_min_dt=common_min, baseline_first_dt=first_dt,
                                   physical_equality=physical_equality, baseline_parameters=baseline_params, output=request_output)
            request_path = output_root / "requests" / f"{case_id}_{study}_qualification_request_v3.json"
            request_path.parent.mkdir(parents=True, exist_ok=True)
            request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            records.append({"case_id": case_id, "background": background, "study": study,
                            "request": str(request_path.resolve()), "request_sha256": sha256(request_path),
                            "xml": {"path": str(xml), "sha256": sha256(xml)},
                            "bi4": {"path": str(bi4), "sha256": sha256(bi4)},
                            "motion": {"path": str(motion), "sha256": sha256(motion)},
                            "baseline_min_positive_dtmin_s": min(mins),
                            "baseline_first_positive_dt": first_dt,
                            "common_min_positive_dtmin_s": common_min,
                            "dt_fixed_s": common_half if study == "half_dt" else 0.0,
                            "time_out_s": 0.01 if study == "half_dt" else 0.005,
                            "solver_receipt": {"path": str(solver_receipt_path), "sha256": sha256(solver_receipt_path)},
                            "physical_input_equality": physical_equality})
    manifest = {
        "schema": "ds-data-02.f2.numeric-study-plan.v3",
        "scope_id": SCOPE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "physical_geometry_unchanged": True,
        "event_window_s": 4.0,
        "mass_rescaling": False,
        "qualification_claim": "none",
        "baseline_dtmin_statistic": "minimum positive DtMin [s] over all RunPARTs save rows in the two completed medium baselines",
        "common_min_positive_dtmin_s": common_min,
        "common_half_dt_fixed_s": common_half,
        "study_version": "v3_correct_background_receipts_and_physical_equality",
        "studies": records,
        "q_n": "not assessed until root runs both integration and save comparisons and evaluates frozen event/physical error budgets",
    }
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / "numeric-study-plan-v3.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest["manifest"] = {"path": str(manifest_path.resolve()), "sha256": sha256(manifest_path)}
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--center-solver-receipt", type=Path, required=True)
    parser.add_argument("--offset-solver-receipt", type=Path, required=True)
    parser.add_argument("--center-owner", type=Path, required=True)
    parser.add_argument("--offset-owner", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=HANDOFF / "numerical_studies_v3")
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
