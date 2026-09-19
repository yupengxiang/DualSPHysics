#!/usr/bin/env python3
"""Execute one guarded L2-R F5 runtime-domain confirmation.

This is the execution companion to :mod:`l2_f5r_confirmation`.  It owns one
fresh case/attempt, rechecks one idle local GPU, keeps the solver in a single
CUDA namespace, converts the resulting fluid frames, exports native PartOut,
and invokes the read-only F5R identity audit.  It deliberately does not touch
the shared resume controller or emit a qualification receipt.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess

try:
    from scripts import l2_c1_canary as c1
    from scripts import l2_f5r_confirmation as f5
    from scripts.campaign_runner import execute_attempt, query_gpus, require_idle_allowed_gpu
    from scripts.l2_campaign import atomic_json, sha256_file, utc_now
    from scripts.trajectory_io import convert_streaming
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import l2_c1_canary as c1
    import l2_f5r_confirmation as f5
    from campaign_runner import execute_attempt, query_gpus, require_idle_allowed_gpu
    from l2_campaign import atomic_json, sha256_file, utc_now
    from trajectory_io import convert_streaming


LAB = f5.LAB
CAMPAIGN = f5.CAMPAIGN
ROOT = f5.DEFAULT_ROOT
CASE_ID = f5.FRESH_CASE_ID
DEFINITION = f5.DEFAULT_XML
GENERATED_ROOT = ROOT / "artifacts" / CASE_ID / "generated"
GENERATED_PREFIX = GENERATED_ROOT / CASE_ID
GENERATED_XML = GENERATED_PREFIX.with_suffix(".xml")
RUN_ROOT = CAMPAIGN / "runs"
DATA_ROOT = ROOT / "data"
HDF5 = DATA_ROOT / f"{CASE_ID}.h5"
AUDIT_REPORT = f5.DEFAULT_AUDIT
PREFLIGHT_REPORT = f5.DEFAULT_PREFLIGHT
BIN = LAB / "vendor" / "official" / "DualSPHysics_v5.4" / "bin" / "linux"
GENCASE = BIN / "GenCase_linux64"
SOLVER = BIN / "DualSPHysics5.4_linux64"
PARTVTKOUT = BIN / "PartVTKOut_linux64"


def environment() -> dict[str, str]:
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{BIN}:{env.get('LD_LIBRARY_PATH', '')}"
    return env


def live_idle_gpu(gpu: int) -> dict:
    records = query_gpus()
    selected = next((row for row in records if row["index"] == gpu), None)
    if selected is None:
        raise RuntimeError(f"physical GPU {gpu} is not visible")
    # The historical inventory only covered a subset of this now-local
    # machine.  The live UUID set is the source of truth for this explicit
    # local run; GPU occupancy is still checked immediately before launch.
    allowed = [row["uuid"] for row in records if 0 <= row["index"] <= 7]
    return require_idle_allowed_gpu(gpu, allowed)


def generate_case() -> dict:
    if not DEFINITION.is_file():
        f5.build_preflight(
            source_xml=f5.LEGACY_DEFINITION,
            configured_xml=DEFINITION,
            output_report=PREFLIGHT_REPORT,
            runtime_domain=f5.F5R_RUNTIME_DOMAIN,
        )
    if not DEFINITION.is_file():
        raise FileNotFoundError(DEFINITION)
    GENERATED_ROOT.mkdir(parents=True, exist_ok=True)
    process = subprocess.run(
        [str(GENCASE), str(DEFINITION.with_suffix("")), str(GENERATED_PREFIX), "-save:all"],
        cwd=DEFINITION.parent,
        env=environment(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    (GENERATED_ROOT / "gencase.stdout.log").write_text(process.stdout or "")
    if process.returncode != 0 or not GENERATED_XML.is_file():
        raise RuntimeError(f"GenCase failed with return code {process.returncode}")
    return {
        "returncode": process.returncode,
        "definition": str(DEFINITION),
        "definition_sha256": sha256_file(DEFINITION)[0],
        "generated_xml": str(GENERATED_XML),
        "generated_xml_sha256": sha256_file(GENERATED_XML)[0],
        "gencase_sha256": sha256_file(GENCASE)[0],
    }


def run_solver(gpu: int) -> tuple[dict, dict]:
    gpu_record = live_idle_gpu(gpu)
    env = environment()
    env["CUDA_VISIBLE_DEVICES"] = str(gpu)
    attempt = execute_attempt(
        CASE_ID,
        [str(SOLVER), "-gpu:0", str(GENERATED_PREFIX), "{output}"],
        RUN_ROOT,
        cwd=LAB,
        env=env,
        evidence_glob="data/Part_*.bi4",
        required_text="Finished execution (code=0)",
        timeout_seconds=3600,
        resource_category="qualification",
    )
    attempt["gpu_isolation"] = {
        "physical_gpu": gpu,
        "uuid": gpu_record["uuid"],
        "cuda_visible_devices": str(gpu),
        "solver_gpu_argument": 0,
        "live_record": gpu_record,
        "solver_sha256": sha256_file(SOLVER)[0],
    }
    return attempt, gpu_record


def materialize_evidence(attempt: dict) -> dict:
    if attempt.get("status") != "completed":
        raise RuntimeError("cannot materialize evidence from an incomplete solver attempt")
    attempt_dir = Path(attempt["attempt_directory"])
    csv_dir = attempt_dir / "csv"
    csv_paths = c1.partvtk_csv(attempt_dir / "data", csv_dir, "-all,+fluid")
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    record = {"id": CASE_ID, "family": "F5", "mechanism": "runtime-domain-confirmation", "shifting": 0}
    convert_streaming(record, csv_paths, HDF5)
    config = {
        "recipe_id": f5.FRESH_RECIPE_ID,
        "physical_case_id": "physical_L2R_F5_runtime_domain_confirmation_v1",
        "lineage_group_id": f5.FRESH_LINEAGE_ID,
        "paired_background_id": f5.FRESH_BACKGROUND_ID,
        "view_id": "world_fluid_particle_v1",
        "control_semantics": "known gravity and low-weir initial release; no future fluid state",
        "family": "F5",
    }
    semantics = c1.add_semantics(HDF5, config, attempt)
    partout_csv = attempt_dir / "PartOut_F5R.csv"
    partout_resume = attempt_dir / "PartOut_F5R-resume.csv"
    process = subprocess.run(
        [
            str(PARTVTKOUT),
            "-dirdata",
            str(attempt_dir / "data"),
            "-savecsv",
            str(partout_csv),
            "-saveresume",
            str(partout_resume),
            "-createdirs:1",
            "-csvsep:1",
        ],
        cwd=attempt_dir,
        env=environment(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    (attempt_dir / "partvtkout.stdout.log").write_text(process.stdout or "")
    if process.returncode != 0 or not partout_csv.is_file():
        raise RuntimeError(f"PartVTKOut failed with return code {process.returncode}")
    return {
        "attempt_directory": str(attempt_dir),
        "hdf5": str(HDF5),
        "hdf5_sha256": sha256_file(HDF5)[0],
        "fluid_csv_frame_count": len(csv_paths),
        "partout_csv": str(partout_csv),
        "partout_csv_sha256": sha256_file(partout_csv)[0],
        "partout_resume": str(partout_resume),
        "partvtkout_returncode": process.returncode,
        "semantics": semantics,
    }


def run(gpu: int) -> dict:
    prepared = generate_case()
    attempt, gpu_record = run_solver(gpu)
    materialized = materialize_evidence(attempt)
    audit = f5.build_audit(
        attempt_dir=Path(attempt["attempt_directory"]),
        hdf5_path=HDF5,
        runparts_path=Path(attempt["attempt_directory"]) / "RunPARTs.csv",
        partout_csv=Path(materialized["partout_csv"]),
        run_log=Path(attempt["attempt_directory"]) / "Run.out",
        generated_xml=GENERATED_XML,
        preflight_report=PREFLIGHT_REPORT,
        output_report=AUDIT_REPORT,
    )
    report = {
        "schema": "l2r.f5r.runner.v1",
        "created_at_utc": utc_now(),
        "case_id": CASE_ID,
        "physical_gpu": gpu,
        "gpu_record": gpu_record,
        "prepared": prepared,
        "attempt": attempt,
        "materialized": materialized,
        "audit_report": str(AUDIT_REPORT),
        "audit_status": audit.get("status"),
        "audit_decision": audit.get("decision"),
        "qualification_claim": "none; bounded F5R confirmation only",
        "receipt_emitted": False,
        "shared_resume_state_updated": False,
    }
    atomic_json(ROOT / "f5r-runner-record.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--gpu", type=int, required=True)
    args = parser.parse_args()
    if args.command == "run":
        report = run(args.gpu)
        print(json.dumps({
            "attempt_status": report["attempt"].get("status"),
            "audit_status": report["audit_status"],
            "audit_decision": report["audit_decision"],
            "audit_report": report["audit_report"],
            "record": str(ROOT / "f5r-runner-record.json"),
        }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
