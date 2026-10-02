#!/usr/bin/env python3
"""Materialise the evidence-bound F2 RV4 numerical recipe.

RV4 keeps the commensurate 24.576 kg physical mother, copied BI4 population,
and copied rotation control byte-for-byte.  It changes only the numerical
solver recipe and one explicitly registered computational-domain repair:

* ``domain_repair01`` pads the open numerical map by 0.20 m on every face;
* ``baseline_save001`` uses ``TimeOut=0.001`` s;
* ``half_save0005`` uses ``TimeOut=0.0005`` s;
* ``half_native_dt`` uses the same 0.001 s save cadence and fixes DtFixed to
  one half of the smallest observed adaptive baseline step for that DP.

Only the six ``baseline_save001`` request files are marked ready for primary
GPU scheduling.  The temporal variants are registered candidate inputs and
must not be launched by this module.  The script copies consumed BI4/motion
bytes into a fresh data-root staging directory, never mutates the consumed
GenCase tree, and never launches GenCase or DualSPHysics.
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
import xml.etree.ElementTree as ET

import numpy as np


SCHEMA = "ds-data-02.f2.numerical-recipe.v4"
FAMILY = "F2"
SCOPE = "F2_SCOPE_GEM_COMMENSURATE_CELLCENTER_20261002_V2"
RECIPE_ID = "F2_GEM_COMMENSURATE_CELLCENTER_V4_DOMAIN_REPAIR01"
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
FAMILY_ROOT = Path(__file__).resolve().parent
WORKTREE_ROOT = FAMILY_ROOT.parents[4]
OLD_REQUEST_ROOT = FAMILY_ROOT / "handoff_20261002" / "qualification_requests"
OLD_DEFINITION_ROOT = FAMILY_ROOT / "handoff_20261002" / "gridphase_v2" / "definitions"
DOMAIN_LOW = [-1.60, -1.40, -0.70]
DOMAIN_HIGH = [3.20, 1.40, 2.40]
OLD_DOMAIN_LOW = [-1.40, -1.20, -0.50]
OLD_DOMAIN_HIGH = [3.00, 1.20, 2.20]
VARIANTS = {
    "baseline_save001": {"save_s": 0.001, "dt_fixed_mode": "adaptive_baseline", "gpu_ready": True},
    "half_save0005": {"save_s": 0.0005, "dt_fixed_mode": "adaptive_baseline", "gpu_ready": False},
    "half_native_dt": {"save_s": 0.001, "dt_fixed_mode": "half_observed_baseline_min", "gpu_ready": False},
}
RESOLUTIONS = ("COARSE", "MEDIUM", "FINE")
BACKGROUNDS = ("CENTER", "OFFSET")
GPU_MIB = {"COARSE": 2048, "MEDIUM": 4096, "FINE": 8192}
STORAGE_BYTES = {"COARSE": 2 * 1024**3, "MEDIUM": 4 * 1024**3, "FINE": 8 * 1024**3}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_hash(value: object) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def require(path: Path, label: str) -> Path:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} is missing: {path}")
    return path


def old_request(case_id: str) -> dict:
    path = OLD_REQUEST_ROOT / f"{case_id}_qualification_request.json"
    return json.loads(require(path, "old qualification request").read_text())


def old_case_paths(case_id: str) -> dict[str, Path]:
    base = DATA_ROOT / "families" / "F2" / case_id
    old = old_request(case_id)
    prefix = Path(old["gencase_input_prefix"])
    return {
        "request": OLD_REQUEST_ROOT / f"{case_id}_qualification_request.json",
        "prefix": prefix,
        "xml": require(Path(str(prefix) + ".xml"), "consumed generated XML"),
        "bi4": require(Path(str(prefix) + ".bi4"), "consumed generated BI4"),
        "motion": require(Path(old["gencase_artifacts"]["copied_motion"]["path"]), "consumed copied motion"),
        "gencase_receipt": require(Path(old["gencase_receipt"]), "consumed GenCase receipt"),
        "runparts": require(next((base.glob("qualification-*/solver_output/RunPARTs.csv")), ""), "consumed RunPARTs.csv"),
    }


def observed_min_dt(runparts: Path) -> tuple[float, dict]:
    values = []
    with runparts.open(newline="") as stream:
        rows = csv.DictReader(stream, delimiter=";")
        for row in rows:
            raw = (row.get("DtMin [s]") or "").strip()
            try:
                value = float(raw)
            except ValueError:
                continue
            if value > 0:
                values.append(value)
    if not values:
        raise ValueError(f"no positive DtMin values in {runparts}")
    return min(values), {
        "min_observed_dt_s": min(values),
        "max_observed_dt_s": max(values),
        "positive_rows": len(values),
        "source": str(runparts),
        "source_sha256": sha256(runparts),
        "semantics": "adaptive baseline RunPARTs DtMin field; half-native recipe uses one half of the minimum",
    }


def replace_parameter(text: str, key: str, value: str) -> str:
    pattern = rf'(<parameter\s+key="{re.escape(key)}"\s+value=")[^"]+("\s*/>)'
    rewritten, count = re.subn(pattern, rf"\g<1>{value}\g<2>", text, count=1)
    if count != 1:
        raise ValueError(f"generated XML does not contain exactly one parameter {key}")
    return rewritten


def replace_domain(text: str) -> str:
    pattern = (r'(<simulationdomain[^>]*>\s*<posmin\s+x=")[^"]+("\s+y=")[^"]+("\s+z=")[^"]+("[^>]*/>\s*'
               r'<posmax\s+x=")[^"]+("\s+y=")[^"]+("\s+z=")[^"]+("\s*/>\s*</simulationdomain>)')
    values = [*(f"{x:.17g}" for x in DOMAIN_LOW), *(f"{x:.17g}" for x in DOMAIN_HIGH)]
    replacement = r"\g<1>" + values[0] + r"\g<2>" + values[1] + r"\g<3>" + values[2] + r"\g<4>" + values[3] + r"\g<5>" + values[4] + r"\g<6>" + values[5] + r"\g<7>"
    rewritten, count = re.subn(pattern, replacement, text, count=1)
    if count != 1:
        raise ValueError("generated XML does not contain one runtime simulationdomain")
    return rewritten


def numeric_fields(xml: Path) -> dict:
    root = ET.parse(xml).getroot()
    params = {node.get("key"): node.get("value") for node in root.findall(".//execution/parameters/parameter") if node.get("key")}
    domain = root.find(".//execution/parameters/simulationdomain")
    if domain is None:
        raise ValueError(f"{xml}: runtime simulationdomain missing")
    low = [float(domain.find("posmin").get(axis)) for axis in "xyz"]
    high = [float(domain.find("posmax").get(axis)) for axis in "xyz"]
    return {"TimeOut": params.get("TimeOut"), "DtFixed": params.get("DtFixed"), "DtIni": params.get("DtIni"), "DtMin": params.get("DtMin"), "TimeMax": params.get("TimeMax"), "domain_low_m": low, "domain_high_m": high}


def physical_equality(old_xml: Path, new_xml: Path) -> dict:
    old = numeric_fields(old_xml)
    new = numeric_fields(new_xml)
    allowed = {"TimeOut", "DtFixed", "domain_low_m", "domain_high_m"}
    differences = {key: {"old": old[key], "new": new[key]} for key in old if old.get(key) != new.get(key)}
    unexpected = sorted(set(differences) - allowed)
    if unexpected:
        raise ValueError(f"new XML changed non-numeric physical/control fields: {unexpected}")
    return {"old_numeric_fields": old, "new_numeric_fields": new, "differences": differences, "unexpected_differences": unexpected, "physical_geometry_control_unchanged": not unexpected}


def source_paths() -> list[Path]:
    family = FAMILY_ROOT
    integration = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
    paths = [
        Path(__file__),
        family / "quality_contract.json", family / "event_definitions.json", family / "integration_save_plan.json",
        family / "case_registry.jsonl", family / "definitions" / "reference_matrix.json",
        family / "handoff_20261002" / "README.md", family / "handoff_20261002" / "gridphase_v2" / "manifest.json",
        family / "f2_handoff_20261002_event_audit.py",
        family / "f2_handoff_20261002_geometry_pose_audit.py",
        family / "f2_handoff_20261002_recipe_v4_preflight.py",
        integration / "scripts/ds_data02_runtime_v2.py",
        SOLVER,
    ]
    for path in paths:
        if path.is_file():
            yield path.resolve()


def input_binding(paths: list[Path]) -> dict[str, str]:
    return {str(path.resolve()): sha256(path) for path in paths}


def build_case_variant(output_root: Path, case_id: str, variant: str, half_dt: float | None) -> dict:
    old = old_case_paths(case_id)
    old_request_data = old_request(case_id)
    case_stage = output_root / "staged_inputs" / case_id / variant
    case_stage.mkdir(parents=True, exist_ok=False)
    new_id = f"{case_id}_RV4D1_{variant.upper()}"
    xml_path = output_root / "definitions" / new_id / f"{new_id}.xml"
    xml_path.parent.mkdir(parents=True, exist_ok=False)
    text = old["xml"].read_text()
    text = replace_domain(text)
    text = replace_parameter(text, "TimeOut", f"{VARIANTS[variant]['save_s']:.17g}")
    dt_fixed = 0.0
    if variant == "half_native_dt":
        if half_dt is None or half_dt <= 0:
            raise ValueError(f"{case_id}: half-native dt is unavailable")
        dt_fixed = half_dt
        text = replace_parameter(text, "DtFixed", f"{half_dt:.17g}")
    xml_path.write_text(text)
    # Keep the generated prefix new-named while preserving exact GenCase BI4
    # and copied motion bytes.  The XML intentionally retains the original
    # motion basename so the only physical control input is a byte-identical
    # copy resolved from the new staging cwd.
    prefix = case_stage / new_id
    bi4_path = Path(str(prefix) + ".bi4")
    motion_path = case_stage / old["motion"].name
    shutil.copyfile(old["bi4"], bi4_path)
    shutil.copyfile(old["motion"], motion_path)
    if sha256(bi4_path) != sha256(old["bi4"]):
        raise ValueError(f"{case_id}: BI4 copy hash differs")
    if sha256(motion_path) != sha256(old["motion"]):
        raise ValueError(f"{case_id}: motion copy hash differs")
    equality = physical_equality(old["xml"], xml_path)
    old_phys = str(old_request_data["physical_condition_hash"])
    numerical_fields_payload = {
        "recipe_id": RECIPE_ID, "variant": variant, "case_id": case_id,
        "resolution": case_id.rsplit("_", 1)[-1].lower(), "dp_m": float(old_request_data["numerical_recipe_fields"]["dp_m"]),
        "save_interval_s": VARIANTS[variant]["save_s"], "DtFixed_s": dt_fixed,
        "domain_repair_id": "F2_NUM_DOMAIN_REPAIR01_PAD_0P20M",
        "time_max_s": 4.0, "parts_out_max": 1,
    }
    numerical_hash = canonical_hash(numerical_fields_payload)
    return {
        "case_id": case_id, "new_case_id": new_id, "variant": variant,
        "old_request": str(old["request"].resolve()), "old_request_sha256": sha256(old["request"]),
        "generated_xml": {"path": str(xml_path.resolve()), "sha256": sha256(xml_path)},
        "staged_prefix": str(prefix.resolve()), "staged_bi4": {"path": str(bi4_path.resolve()), "sha256": sha256(bi4_path)},
        "staged_motion": {"path": str(motion_path.resolve()), "sha256": sha256(motion_path)},
        "consumed_inputs": {key: {"path": str(path.resolve()), "sha256": sha256(path)} for key, path in old.items() if key not in {"request", "prefix"}},
        "physical_condition_hash": old_phys, "physical_equality_proof": equality,
        "numerical_fields": numerical_fields_payload, "numerical_recipe_hash": numerical_hash,
        "dt_fixed_guard": {"DtIni_s": 0.0, "DtMin_s": 0.0, "fixed_step_does_not_exceed_observed_baseline": variant != "half_native_dt" or (half_dt is not None and half_dt > 0)},
    }


def make_request(output_root: Path, record: dict, all_input_paths: list[Path]) -> dict:
    case_id = record["case_id"]
    variant = record["variant"]
    old = old_case_paths(case_id)
    old_request_data = old_request(case_id)
    new_id = record["new_case_id"]
    attempt = f"qualification-{new_id.lower()}-native-fullstate-v1"
    resolution = case_id.rsplit("_", 1)[-1]
    bg = "center_catch" if "CENTER" in case_id else "offset_spill"
    xml = Path(record["generated_xml"]["path"])
    stage = Path(record["staged_prefix"]).parent
    request = {
        "schema": "ds-data-02.runner.request.v1", "kind": "qualification", "family_id": FAMILY,
        "case_id": new_id, "attempt_id": attempt,
        "command": [str(SOLVER.resolve()), str(Path(record["staged_prefix"]).resolve()), "{attempt_root}/solver_output"],
        "cwd": str(stage.resolve()), "max_wall_seconds": 300, "cpu_threads": 4,
        "worktree_root": str(WORKTREE_ROOT.resolve()),
        "estimated_peak_gpu_mib": GPU_MIB[resolution], "estimated_storage_bytes": STORAGE_BYTES[resolution],
        "event_window_s": 4.0, "physical_case_id": case_id,
        "physical_condition_hash": record["physical_condition_hash"], "physical_geometry_control_hash": record["physical_condition_hash"],
        "numerical_recipe_hash": record["numerical_recipe_hash"], "recipe_id": RECIPE_ID,
        "scope_id": SCOPE, "mechanism_id": bg, "resolution": resolution.lower(),
        "gencase_receipt": str(old["gencase_receipt"].resolve()), "gencase_receipt_sha256": sha256(old["gencase_receipt"]),
        "gencase_prefix": str(Path(record["staged_prefix"]).resolve()),
        "gencase_artifacts": {
            "new_xml": record["generated_xml"], "copied_bi4": record["staged_bi4"], "copied_motion": record["staged_motion"],
            "consumed_gencase_receipt": {"path": str(old["gencase_receipt"].resolve()), "sha256": sha256(old["gencase_receipt"])},
        },
        "source_binding": {
            "staging_cwd": str(stage.resolve()), "control_relative_path": old["motion"].name,
            "control_sha256": record["staged_motion"]["sha256"], "bi4_sha256": record["staged_bi4"]["sha256"],
            "new_xml_sha256": record["generated_xml"]["sha256"], "old_xml_sha256": sha256(old["xml"]),
            "old_physical_case_id": case_id,
        },
        "numerical_recipe_fields": record["numerical_fields"],
        "domain_repair": {
            "id": "F2_NUM_DOMAIN_REPAIR01_PAD_0P20M", "candidate_only_until_actual_solver_evidence": True,
            "old_low_m": OLD_DOMAIN_LOW, "old_high_m": OLD_DOMAIN_HIGH,
            "new_low_m": DOMAIN_LOW, "new_high_m": DOMAIN_HIGH,
            "finite_physical_geometry_unchanged": True,
        },
        "thresholds_apply_before_results": True,
        "quality_thresholds": {
            "continuous_initial_mass_kg": 24.576, "native_mass_relative_budget_fraction": 1e-12,
            "event_time_absolute_budget_s": 0.0036681953999691376,
            "save_half_width_budget_s": 0.0007336390799938275,
            "macro_relative_error_threshold": 0.05, "unknown_mass_remains_in_initial_denominator": True,
            "initial_typed_3d_fluid_required": True,
        },
        "input_files": [str(path.resolve()) for path in all_input_paths],
        "input_sha256": input_binding(all_input_paths),
        "gpu_launch": {"family_owner_launch": False, "requested_by": "primary_process"},
        "qualification_launch_authority": "shared_ds_data_02_runner_only_primary_process",
        "status": "ready_for_primary_gpu_scheduling" if variant == "baseline_save001" else "registered_temporal_candidate_no_gpu",
        "request_note": "New F2 RV4 domain-repair numerical recipe; copied exact BI4/motion and unchanged physical mother. This is a solver request only; no Q-I/Q-N/production approval. Temporal candidates must not be launched by this file.",
    }
    return request


def build(output_root: Path) -> dict:
    output_root = output_root.resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise ValueError(f"recipe output must be fresh: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    audit_report = DATA_ROOT / "families/F2/F2H10V2_INITIAL_AUDIT/geometry-pose-domain-audit-v4/f2-geometry-pose-domain-audit.json"
    if not audit_report.is_file():
        raise FileNotFoundError(f"run geometry/pose audit first: {audit_report}")
    cases = []
    dt_audits = {}
    for background in BACKGROUNDS:
        for resolution in RESOLUTIONS:
            case_id = f"F2H10V2_{background}_V1_{resolution}"
            old = old_case_paths(case_id)
            minimum, evidence = observed_min_dt(old["runparts"])
            dt_audits[case_id] = evidence
            for variant in VARIANTS:
                half_dt = 0.5 * minimum if variant == "half_native_dt" else None
                cases.append(build_case_variant(output_root, case_id, variant, half_dt))
    common = list(source_paths())
    common.extend([audit_report.resolve(), require(Path("/home/jade/.codex/worktrees/ds-data-02-f2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/GOAL_ZH.md"), "campaign goal")])
    requests_dir = output_root / "requests"
    requests_dir.mkdir()
    request_records = []
    for record in cases:
        input_paths = list(common)
        old = old_case_paths(record["case_id"])
        input_paths.extend([Path(record["generated_xml"]["path"]), Path(record["staged_bi4"]["path"]), Path(record["staged_motion"]["path"]), old["xml"], old["bi4"], old["motion"], old["gencase_receipt"], old["runparts"]])
        request = make_request(output_root, record, input_paths)
        path = requests_dir / f"{record['new_case_id']}_request.json"
        path.write_text(json.dumps(request, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
        record["request"] = {"path": str(path.resolve()), "sha256": sha256(path), "status": request["status"]}
        request_records.append(request)
    manifest = {
        "schema": SCHEMA, "created_at_utc": stamp(), "recipe_id": RECIPE_ID, "scope_id": SCOPE,
        "qualification_claim": "none; requests are ready/candidate solver inputs only",
        "physical_mother": {
            "continuous_volume_m3": 0.024576, "continuous_mass_kg": 24.576,
            "geometry_control_unchanged": True, "native_mass_authority": "generated BI4 MassFluid double × CaseNfluid",
            "display_csv_mass_not_authority": True,
        },
        "domain_repair": {
            "id": "F2_NUM_DOMAIN_REPAIR01_PAD_0P20M", "basis_report": {"path": str(audit_report.resolve()), "sha256": sha256(audit_report)},
            "old_low_m": OLD_DOMAIN_LOW, "old_high_m": OLD_DOMAIN_HIGH, "new_low_m": DOMAIN_LOW, "new_high_m": DOMAIN_HIGH,
            "padding_m": 0.20, "changed_solver_field": "execution/parameters/simulationdomain only",
            "finite_geometry_and_motion_unchanged": True, "physical_spill_not_inferred": True,
            "repair_budget": "first of at most two evidence-based numerical-domain repairs; no second repair registered",
        },
        "frozen_thresholds": {
            "event_time_absolute_budget_s": 0.0036681953999691376, "save_half_width_budget_s": 0.0007336390799938275,
            "baseline_save_interval_s": 0.001, "half_save_interval_s": 0.0005,
            "integration_study_required_separately": True, "macro_relative_error_threshold": 0.05,
            "continuous_initial_mass_kg": 24.576, "native_mass_relative_budget_fraction": 1e-12,
            "unknown_mass_separate_from_spill": True,
        },
        "dt_evidence_by_case": dt_audits,
        "variants": [{"variant": key, **value, "launch": "six baseline only" if value["gpu_ready"] else "do not launch; registered candidate"} for key, value in VARIANTS.items()],
        "cases": cases,
        "requests": [{"case_id": r["case_id"], "status": r["status"], "request_path": next(x["request"]["path"] for x in cases if x["new_case_id"] == r["case_id"])} for r in request_records],
    }
    manifest_path = output_root / "recipe_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    manifest = build(args.output_root)
    print(json.dumps({"manifest": str(args.output_root.resolve() / "recipe_manifest.json"), "requests": len(manifest["requests"]), "ready": sum(x["status"] == "ready_for_primary_gpu_scheduling" for x in manifest["requests"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
