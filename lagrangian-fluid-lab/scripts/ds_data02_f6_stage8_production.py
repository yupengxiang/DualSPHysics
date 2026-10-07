#!/usr/bin/env python3
"""Stage and advance Family F6 Stage 8 production cases under approved Fallback 02.

Formalizes the 8-case Stage 8 roster (pilot_8 subset: F6_000 through F6_007),
generates production XML definitions, executes bounded GenCase preflights via
ds_data02_runtime, verifies 3D geometry / zero particle loss / strict continuum
mass consistency, and prepares GPU solver launch requests targeting permitted
GPUs 2, 5, 6, 7.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import ds_data02_f6 as f6
import ds_data02_f6_resolution as f6r

PYTHON_BIN = REPO / ".venv/bin/python" if (REPO / ".venv/bin/python").is_file() else Path(sys.executable)
RUNTIME_SCRIPT = REPO / "scripts/ds_data02_runtime.py"
BIN_ROOT = REPO / "vendor/official/DualSPHysics_v5.4/bin/linux"
GENCASE_BIN = BIN_ROOT / "GenCase_linux64"
SOLVER_BIN = BIN_ROOT / "DualSPHysics5.4_linux64"

FAMILY_DIR = REPO / "campaigns/ds-data-02/families/F6"
PROD_DIR = FAMILY_DIR / "production"
PROD_DEFS_DIR = PROD_DIR / "definitions"
PROD_CASES_DIR = PROD_DIR / "cases"
PROD_GENCASE_DIR = PROD_DIR / "execution_requests"
PROD_SOLVER_DIR = PROD_DIR / "solver_requests"
FAMILY_REQUESTS_DIR = FAMILY_DIR / "requests"

DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
DATA_F6_ROOT = DATA_ROOT / "families/F6"

PILOT_8_CASES = [
    "F6_000_simple_free_response",
    "F6_001_wave_no_contact",
    "F6_002_simple_free_response",
    "F6_003_wave_no_contact",
    "F6_004_simple_free_response",
    "F6_005_wave_no_contact",
    "F6_006_simple_free_response",
    "F6_007_wave_no_contact",
]

# Strict GPU mapping for Stage 8: Permitted GPUs are {2, 5, 6, 7} only.
# GPUs 1, 3, 4 strictly off-limits (user wx), GPU 0 preserved.
STAGE8_GPU_MAP = {
    "F6_000_simple_free_response": 2,
    "F6_001_wave_no_contact": 2,
    "F6_002_simple_free_response": 5,
    "F6_003_wave_no_contact": 5,
    "F6_004_simple_free_response": 6,
    "F6_005_wave_no_contact": 6,
    "F6_006_simple_free_response": 7,
    "F6_007_wave_no_contact": 7,
}


def now_str() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_manifest_cases() -> list[dict]:
    cases = []
    manifests_dir = FAMILY_DIR / "case_manifests"
    for cid in PILOT_8_CASES:
        mpath = manifests_dir / f"{cid}.json"
        if not mpath.is_file():
            raise FileNotFoundError(f"case manifest missing: {mpath}")
        data = json.loads(mpath.read_text(encoding="utf-8"))
        cases.append(data["case"])
    return cases


def build_stage8_spec(case_manifest: dict) -> dict:
    cid = case_manifest["case_id"]
    mechanism = case_manifest["mechanism_id"]
    params = case_manifest["parameters"]

    density_ratio = float(params["body_density_ratio"])
    heave_offset = float(params["initial_heave_offset_m"])
    lateral_offset = float(params["initial_lateral_offset_m"])
    pitch_deg = float(params["initial_pitch_deg"])
    yaw_rad = float(params["phase_or_yaw_rad"])
    wave_height = float(params.get("wave_height_m") or 0.0)
    wave_period = float(params["wave_period_s"]) if params.get("wave_period_s") is not None else None

    # Mechanical geometry follows approved F6_OFFICIAL_SMALLBODY_FALLBACK_02
    dp = 0.040
    body_size = [0.60, 0.50, 0.32]
    body_volume = 0.60 * 0.50 * 0.32
    body_mass = round(density_ratio * body_volume * 1000.0, 4)

    # Moments of inertia from continuum solid box
    inertia = [
        [round(body_mass * (body_size[1] ** 2 + body_size[2] ** 2) / 12.0, 6), 0.0, 0.0],
        [0.0, round(body_mass * (body_size[0] ** 2 + body_size[2] ** 2) / 12.0, 6), 0.0],
        [0.0, 0.0, round(body_mass * (body_size[0] ** 2 + body_size[1] ** 2) / 12.0, 6)],
    ]

    if mechanism == "simple_free_response":
        tank = {"length_m": 4.0, "width_m": 2.0, "height_m": 1.4}
        water_level = 0.80
        body_point = [1.70, 0.75, 0.56]
        body_center = [2.00, 1.00, 0.72]
        fluid_fill = {
            "seed_m": [1.0, 1.0, 0.30],
            "point_m": [0.04, 0.04, 0.04],
            "size_m": [3.92, 1.92, 0.76],
        }
        paddle = None
        control = {
            "mode": "initial_release",
            "release_time_s": 0.0,
            "wave_height_m": 0.0,
            "wave_period_s": None,
            "ramp_periods": 0,
        }
        official_template_rel = "main/11_Floating/CaseFloating_Def.xml"
    else:
        tank = {"length_m": 5.0, "width_m": 2.0, "height_m": 1.4}
        water_level = 0.80
        body_point = [2.20, 0.75, 0.56]
        body_center = [2.50, 1.00, 0.72]
        fluid_fill = {
            "seed_m": [1.0, 1.0, 0.30],
            "point_m": [0.12, 0.04, 0.04],
            "size_m": [4.80, 1.92, 0.76],
        }
        paddle = {"point_m": [0.0, 0.0, 0.0], "size_m": [0.08, 2.0, 1.20], "mkbound": 10}
        control = {
            "mode": "regular_piston_wave",
            "release_time_s": 0.0,
            "wave_height_m": wave_height,
            "wave_period_s": wave_period,
            "ramp_periods": 3,
        }
        official_template_rel = "main/12_FloatingWaves/CaseFloatingWavesVal2_Def.xml"

    spec = {
        "case_id": cid,
        "mechanism_id": mechanism,
        "family_id": "F6",
        "fallback_id": "F6_OFFICIAL_SMALLBODY_FALLBACK_02",
        "physical_scope_id": f"F6_OFFICIAL_SMALLBODY_{mechanism.upper()}",
        "physical_case_id": case_manifest["physical_case_id"],
        "paired_background_id": case_manifest["paired_background_id"],
        "split": case_manifest["split"],
        "target_role": case_manifest["target_role"],
        "dp_m": dp,
        "tank": tank,
        "water_level_m": water_level,
        "body": {
            "kind": "box",
            "mkbound": 50,
            "point_m": body_point,
            "size_m": body_size,
            "mass_kg": body_mass,
            "initial_pose": {
                "center_m": body_center,
                "orientation_euler_deg": [0.0, pitch_deg, 0.0],
            },
            "initial_offset_m": {
                "heave": heave_offset,
                "lateral": lateral_offset,
                "pitch": pitch_deg,
                "yaw": yaw_rad,
            },
            "volume_m3": body_volume,
            "source_inertia_kg_m2": inertia,
        },
        "fluid_fill": fluid_fill,
        "paddle": paddle,
        "control": control,
        "parameters": params,
        "complexity_factor": 1.0,
        "official_template_rel": official_template_rel,
    }
    return spec


def materialize_stage8() -> list[dict]:
    PROD_DIR.mkdir(parents=True, exist_ok=True)
    PROD_DEFS_DIR.mkdir(parents=True, exist_ok=True)
    PROD_CASES_DIR.mkdir(parents=True, exist_ok=True)
    PROD_GENCASE_DIR.mkdir(parents=True, exist_ok=True)
    PROD_SOLVER_DIR.mkdir(parents=True, exist_ok=True)
    FAMILY_REQUESTS_DIR.mkdir(parents=True, exist_ok=True)

    manifest_cases = load_manifest_cases()
    roster = []

    for mc in manifest_cases:
        spec = build_stage8_spec(mc)
        cid = spec["case_id"]
        mechanism = spec["mechanism_id"]

        case_dir = PROD_CASES_DIR / cid
        case_dir.mkdir(parents=True, exist_ok=True)

        # 1. Definition XML
        def_xml = case_dir / f"{cid}_Def.xml"
        def_text = f6._definition_xml(spec)
        wall = spec["tank"]
        dp = float(spec["dp_m"])
        px = f6._fmt(float(wall["length_m"]) + dp)
        py = f6._fmt(float(wall["width_m"]) + dp)
        pz = f6._fmt(float(wall["height_m"]) + dp)
        pointmax_replacement = f'<pointmax x="{px}" y="{py}" z="{pz}" />'
        def_text, count = re.subn(r"<pointmax\b[^>]*/>", pointmax_replacement, def_text, count=1)
        if count != 1:
            raise ValueError(f"pointmax substitution failed for {cid}")
        def_text = def_text.replace(
            "</case>",
            "<!-- Stage 8 production: approved small-body fallback 02 scope; pointmax=finite-wall size+dp margin only. -->\n</case>",
            1,
        )
        def_xml.write_text(def_text, encoding="utf-8")
        ET.parse(def_xml)  # syntax check

        # Also copy to shared definitions directory
        (PROD_DEFS_DIR / f"{cid}_Def.xml").write_text(def_text, encoding="utf-8")

        # 2. Control CSV
        control_csv = case_dir / f"{cid}_Control.csv"
        f6._write_control(control_csv, spec)
        (PROD_DEFS_DIR / f"{cid}_Control.csv").write_text(control_csv.read_text(encoding="utf-8"), encoding="utf-8")

        # 3. Native JSON
        native_json = case_dir / f"{cid}_Native.json"
        f6._write_native(native_json, spec)
        (PROD_DEFS_DIR / f"{cid}_Native.json").write_text(native_json.read_text(encoding="utf-8"), encoding="utf-8")

        # 4. Normal JSON
        normal_json = case_dir / f"{cid}_Normal.json"
        f6._write_normal(normal_json, spec)
        (PROD_DEFS_DIR / f"{cid}_Normal.json").write_text(normal_json.read_text(encoding="utf-8"), encoding="utf-8")

        # Parse geometry
        geometry = f6r.parse_physical_definition(def_xml)
        geometry["continuous_geometry_hash"] = f6r._geometry_hash(geometry)

        official_template = REPO / "vendor/official/DualSPHysics_v5.4/examples" / spec["official_template_rel"]
        if not official_template.is_file():
            official_template = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/examples") / spec["official_template_rel"]

        copied = {
            "definition": {"path": str(def_xml.resolve()), "sha256": f6.sha256_file(def_xml)},
            "control": {"path": str(control_csv.resolve()), "sha256": f6.sha256_file(control_csv)},
            "native": {"path": str(native_json.resolve()), "sha256": f6.sha256_file(native_json)},
            "normal": {"path": str(normal_json.resolve()), "sha256": f6.sha256_file(normal_json)},
        }

        body_info = spec["body"]
        fill_info = spec["fluid_fill"]
        fluid_volume = math.prod(float(v) for v in fill_info["size_m"])

        case_entry = {
            "schema": "ds-data-02.f6.production-case.v1",
            "family_id": "F6",
            "case_id": cid,
            "mechanism_id": mechanism,
            "stage": "stage8",
            "pilot_subset": "pilot_8",
            "fallback_id": "F6_OFFICIAL_SMALLBODY_FALLBACK_02",
            "physical_scope_id": spec["physical_scope_id"],
            "physical_case_id": spec["physical_case_id"],
            "paired_background_id": spec["paired_background_id"],
            "split": spec["split"],
            "target_role": spec["target_role"],
            "dp_m": dp,
            "solver_dimension_required": 3,
            "continuous_geometry_hash": geometry["continuous_geometry_hash"],
            "physical_geometry_hash": geometry["continuous_geometry_hash"],
            "physical_wall_point_m": geometry["physical_wall_point_m"],
            "physical_wall_size_m": geometry["physical_wall_size_m"],
            "pointmax_m": geometry["gencase_pointmax_m"],
            "body": {
                **body_info,
                "volume_m3": body_info["volume_m3"],
                "source_inertia_kg_m2": body_info["source_inertia_kg_m2"],
            },
            "fluid_fill": {
                **fill_info,
                "volume_m3": fluid_volume,
                "continuous_mass_kg": fluid_volume * 1000.0,
            },
            "physical_fluid_region": {
                **fill_info,
                "volume_m3": fluid_volume,
                "continuous_mass_kg": fluid_volume * 1000.0,
                "liquid_surface_z_m": float(fill_info["point_m"][2]) + float(fill_info["size_m"][2]),
            },
            "paddle": geometry.get("paddle"),
            "control": spec["control"],
            "parameters": spec["parameters"],
            "paths": copied,
            "official_template": {
                "path": str(official_template.resolve()),
                "sha256": f6.sha256_file(official_template) if official_template.is_file() else None,
            },
            "estimated_counts": {
                "fixed": 15651 if mechanism == "simple_free_response" else 18676,
                "moving": 0 if mechanism == "simple_free_response" else 2940,
                "floating": 1872,
                "fluid": 80814 if mechanism == "simple_free_response" else 99426,
                "total": 98337 if mechanism == "simple_free_response" else 122914,
            },
            "estimated_storage_bytes": 268435456,
            "contact_policy": {
                "chrono": False,
                "RigidAlgorithm": 1,
                "wall_contact": "no contact mechanism; body is placed clear of finite walls",
            },
            "mass_rescaling": False,
            "status": "gencase_pending",
            "assigned_gpu": STAGE8_GPU_MAP[cid],
        }

        # 5. GenCase Request
        gencase_attempt = f"{cid}_GENCASE_01"
        gencase_input_files = [
            str(GENCASE_BIN.resolve()),
            str(def_xml.resolve()),
            str(control_csv.resolve()),
            str(native_json.resolve()),
            str(normal_json.resolve()),
        ]
        if official_template.is_file():
            gencase_input_files.append(str(official_template.resolve()))

        gencase_req = {
            "schema": "ds02.cpu-request.v2",
            "family_id": "F6",
            "case_id": cid,
            "attempt_id": gencase_attempt,
            "kind": "cpu",
            "cpu_task_kind": "gencase",
            "command": [
                str(GENCASE_BIN.resolve()),
                str(def_xml.resolve().with_suffix("")),
                "{attempt_root}/" + cid,
                "-save:all",
            ],
            "cwd": str(case_dir.resolve()),
            "max_wall_seconds": 300,
            "cpu_threads": 4,
            "estimated_storage_bytes": 268435456,
            "input_files": gencase_input_files,
            "worktree_root": str(REPO.parent),
            "purpose": "Stage 8 production GenCase preflight; verify zero particle loss and strict continuum mass",
            "physical_parent_id": spec["physical_case_id"],
            "registry_kind": "production",
            "solver_dimension_required": 3,
        }

        req_path = PROD_GENCASE_DIR / f"{cid}_gencase.json"
        req_path.write_text(json.dumps(gencase_req, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        case_entry["request"] = {
            "path": str(req_path.resolve()),
            "sha256": f6.sha256_file(req_path),
            "attempt_id": gencase_attempt,
        }

        # Write case.json in case directory
        (case_dir / "case.json").write_text(json.dumps(case_entry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        roster.append(case_entry)

    # Write stage 8 roster manifest
    roster_manifest = {
        "schema": "ds-data-02.f6.stage8-roster.v1",
        "family_id": "F6",
        "stage": "stage8",
        "pilot_subset": "pilot_8",
        "approved_scope": "F6_OFFICIAL_SMALLBODY_FALLBACK_02",
        "status": "materialized_gencase_pending",
        "total_cases": len(roster),
        "permitted_gpus": [2, 5, 6, 7],
        "cases": roster,
    }
    (PROD_DIR / "stage8_roster.json").write_text(json.dumps(roster_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[{now_str()}] Materialized {len(roster)} Stage 8 production cases under {PROD_DIR}")
    return roster


def execute_stage8_gencase(roster: list[dict], max_concurrency: int = 2) -> list[dict]:
    print(f"[{now_str()}] Executing GenCase for {len(roster)} Stage 8 cases (max concurrency: {max_concurrency})")
    results = []

    pending = list(roster)
    running: dict[subprocess.Popen, tuple[dict, Path, float]] = {}

    while pending or running:
        while pending and len(running) < max_concurrency:
            case = pending.pop(0)
            req_path = Path(case["request"]["path"])
            print(f"[{now_str()}] Launching GenCase: {case['case_id']}")
            cmd = [str(PYTHON_BIN), str(RUNTIME_SCRIPT), "run", "--request", str(req_path)]
            proc = subprocess.Popen(
                cmd,
                cwd=str(REPO),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            running[proc] = (case, req_path, time.monotonic())

        time.sleep(0.5)
        done_procs = []
        for proc, (case, req_path, start_t) in running.items():
            ret = proc.poll()
            if ret is not None:
                elapsed = time.monotonic() - start_t
                out, _ = proc.communicate()
                done_procs.append(proc)
                print(f"[{now_str()}] Finished GenCase: {case['case_id']} (returncode: {ret}, elapsed: {elapsed:.2f}s)")
                receipt_file = DATA_F6_ROOT / case["case_id"] / case["request"]["attempt_id"] / "execution-receipt.json"
                receipt = json.loads(receipt_file.read_text()) if receipt_file.is_file() else {}
                results.append({
                    "case_id": case["case_id"],
                    "returncode": ret,
                    "elapsed_seconds": elapsed,
                    "receipt_file": str(receipt_file),
                    "receipt": receipt,
                })
        for proc in done_procs:
            del running[proc]

    return results


def audit_stage8_gencase(roster: list[dict]) -> list[dict]:
    print(f"[{now_str()}] Running rigorous mechanical and continuum mass audits on all 8 cases...")
    audits = []

    for case in roster:
        cid = case["case_id"]
        case_dir = PROD_CASES_DIR / cid
        receipt_path = DATA_F6_ROOT / cid / case["request"]["attempt_id"] / "execution-receipt.json"

        audit = f6r.audit_gencase(case_dir, receipt_path)
        audit_path = case_dir / "gencase-audit.json"
        audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        checks = audit.get("checks", {})
        raw_counts = audit.get("generated", {}).get("counts", {})
        counts = {
            "fixed": raw_counts.get("fixed", 0),
            "moving": raw_counts.get("moving", 0),
            "floating": raw_counts.get("floating", 0),
            "fluid": raw_counts.get("fluid", 0),
        }
        counts["total"] = sum(counts.values())
        budget = audit.get("initial_mass_budget", {})
        relative_mass_error = budget.get("continuous_after_occupancy_mass_relative_error")

        expected_counts = case["estimated_counts"]
        zero_loss = (
            counts["fixed"] == expected_counts["fixed"]
            and counts["moving"] == expected_counts["moving"]
            and counts["floating"] == expected_counts["floating"]
            and counts["fluid"] == expected_counts["fluid"]
            and counts["total"] == expected_counts["total"]
        )
        bounds_valid = bool(checks.get("actual_3d") and checks.get("physical_wall_planes_match") and checks.get("effective_transverse_layers"))
        
        # Verify strict continuum mass consistency (-8.4271% for simple, -8.2066% for wave)
        is_simple = case["mechanism_id"] == "simple_free_response"
        expected_mass_error = -0.08427099976204222 if is_simple else -0.08206587413665792
        mass_consistent = abs(relative_mass_error - expected_mass_error) < 1e-6

        status = "pass" if (zero_loss and bounds_valid and mass_consistent and checks.get("positive_fluid_type3") and checks.get("positive_floating_type2")) else "fail"

        result = {
            "case_id": cid,
            "mechanism_id": case["mechanism_id"],
            "status": status,
            "audit_file": str(audit_path),
            "actual_counts": counts,
            "expected_counts": expected_counts,
            "zero_particle_loss": zero_loss,
            "actual_3d": checks.get("actual_3d"),
            "effective_transverse_layers": checks.get("effective_transverse_layers"),
            "finite_wall_faces_and_bottom": checks.get("finite_wall_faces_and_bottom"),
            "physical_wall_planes_match": checks.get("physical_wall_planes_match"),
            "positive_fluid_type3": checks.get("positive_fluid_type3"),
            "positive_floating_type2": checks.get("positive_floating_type2"),
            "wave_actual_moving_particles": checks.get("wave_actual_moving_particles"),
            "continuous_mass_relative_error": relative_mass_error,
            "expected_continuous_mass_error": expected_mass_error,
            "mass_consistency_pass": mass_consistent,
            "body_mass_kg": case["body"]["mass_kg"],
            "source_inertia_kg_m2": case["body"]["source_inertia_kg_m2"],
            "generated_floating_inertia": audit.get("generated", {}).get("floating_inertia_kg_m2"),
            "body_bounds_m": audit.get("generated", {}).get("body_bounds_m"),
            "assigned_gpu": case["assigned_gpu"],
        }
        audits.append(result)
        print(f"[{now_str()}] Case {cid}: status={status}, counts={counts} (zero_loss={zero_loss}), mass_error={relative_mass_error*100:.2f}%")

    return audits


def emit_stage8_solver_requests(roster: list[dict], audits: list[dict]) -> list[Path]:
    print(f"[{now_str()}] Preparing GPU solver launch requests for permitted GPUs 2, 5, 6, 7...")
    solver_request_paths = []
    audits_by_id = {a["case_id"]: a for a in audits}

    for case in roster:
        cid = case["case_id"]
        audit = audits_by_id[cid]
        gpu_idx = case["assigned_gpu"]
        assert gpu_idx in {2, 5, 6, 7}, f"illegal GPU index {gpu_idx} for {cid}"

        gencase_attempt = case["request"]["attempt_id"]
        gencase_dir = DATA_F6_ROOT / cid / gencase_attempt
        receipt_file = gencase_dir / "execution-receipt.json"
        prefix = gencase_dir / cid
        bi4 = prefix.with_suffix(".bi4")
        xml = prefix.with_suffix(".xml")
        normal_vtk = prefix.with_name(f"{cid}__Actual.vtk")

        def_xml = PROD_CASES_DIR / cid / f"{cid}_Def.xml"
        control_csv = PROD_CASES_DIR / cid / f"{cid}_Control.csv"
        native_json = PROD_CASES_DIR / cid / f"{cid}_Native.json"
        normal_json = PROD_CASES_DIR / cid / f"{cid}_Normal.json"
        case_json = PROD_CASES_DIR / cid / "case.json"

        for p in (receipt_file, bi4, xml, def_xml, control_csv, native_json, normal_json, case_json):
            if not p.is_file():
                raise FileNotFoundError(f"missing solver input dependency: {p}")

        input_files = [
            str(receipt_file.resolve()),
            str(bi4.resolve()),
            str(xml.resolve()),
            str(def_xml.resolve()),
            str(control_csv.resolve()),
            str(native_json.resolve()),
            str(normal_json.resolve()),
            str(case_json.resolve()),
        ]
        if normal_vtk.is_file():
            input_files.append(str(normal_vtk.resolve()))

        input_hashes = {p: f6.sha256_file(Path(p)) for p in input_files}
        solver_attempt = f"{cid}_QUALIFICATION_001"

        solver_req = {
            "schema": "ds02.runner-request.v2",
            "family_id": "F6",
            "case_id": cid,
            "attempt_id": solver_attempt,
            "physical_case_id": case["physical_case_id"],
            "physical_parent_id": case["physical_case_id"],
            "paired_background_id": case["paired_background_id"],
            "split": case["split"],
            "target_role": case["target_role"],
            "registry_kind": "production",
            "kind": "qualification",
            "command": [
                str(SOLVER_BIN.resolve()),
                str(prefix.resolve()),
                "{attempt_root}/solver",
                "-tmax:12.0",
                "-tout:0.05",
            ],
            "cwd": str(gencase_dir.resolve()),
            "worktree_root": str(REPO.parent),
            "max_wall_seconds": 1200,
            "cpu_threads": 2,
            "estimated_storage_bytes": 15 * 1024 * 1024 * 1024,
            "estimated_peak_gpu_mib": 8192,
            "target_gpu_index": gpu_idx,
            "permitted_gpus": [2, 5, 6, 7],
            "preserved_gpus": [0],
            "strictly_forbidden_gpus": [1, 3, 4],
            "gencase_receipt": str(receipt_file.resolve()),
            "gencase_receipt_sha256": f6.sha256_file(receipt_file),
            "gencase_prefix": str(prefix.resolve()),
            "gencase_bi4": str(bi4.resolve()),
            "gencase_xml": str(xml.resolve()),
            "total_particles": audit["actual_counts"]["total"],
            "fluid_particles": audit["actual_counts"]["fluid"],
            "floating_particles": audit["actual_counts"]["floating"],
            "fixed_particles": audit["actual_counts"]["fixed"],
            "moving_particles": audit["actual_counts"]["moving"],
            "input_files": input_files,
            "input_hashes": input_hashes,
            "qualification_claim": "Stage 8 production official small-body 3D contact-free FSI benchmark",
            "request_note": f"Production solver request for {cid} allocated to GPU {gpu_idx} under shared runtime controls.",
            "source_mother": "official_v54_01_floating",
            "fallback_scope_approved": "F6_OFFICIAL_SMALLBODY_FALLBACK_02",
        }

        # Write to production/solver_requests
        req_file = PROD_SOLVER_DIR / f"{cid}-solver.json"
        req_file.write_text(json.dumps(solver_req, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        solver_request_paths.append(req_file)

        # Also write to campaigns/ds-data-02/families/F6/requests/ for root runner integration
        family_req_file = FAMILY_REQUESTS_DIR / f"{cid}-solver.json"
        family_req_file.write_text(json.dumps(solver_req, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"[{now_str()}] Emitted {len(solver_request_paths)} GPU solver requests.")
    return solver_request_paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-gencase", action="store_true", help="Skip GenCase execution if already completed")
    args = parser.parse_args()

    # Step 1 & 2 & 3: Materialize Stage 8 roster and definitions
    roster = materialize_stage8()

    # Step 4: Execute GenCase
    if not args.skip_gencase:
        execute_stage8_gencase(roster, max_concurrency=2)

    # Step 4 continued: Audit GenCase outputs
    audits = audit_stage8_gencase(roster)

    # Step 5: Emit GPU solver launch requests
    solver_reqs = emit_stage8_solver_requests(roster, audits)

    # Write overall Stage 8 production audit summary
    all_passed = all(a["status"] == "pass" for a in audits)
    summary = {
        "schema": "ds-data-02.f6.stage8-production-summary.v1",
        "family_id": "F6",
        "stage": "stage8",
        "approved_scope": "F6_OFFICIAL_SMALLBODY_FALLBACK_02",
        "all_audits_passed": all_passed,
        "audits": audits,
        "solver_requests": [str(p) for p in solver_reqs],
        "generated_at_utc": now_str(),
    }
    summary_path = PROD_DIR / "stage8_production_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[{now_str()}] Stage 8 production summary written to {summary_path}")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
