#!/usr/bin/env python3
"""Prepare one source-bound F5-S1 GenCase mass-support canary.

The F5-S1 source is the transformed ``M095_T090`` motion case.  The source
solver actually ran with ``-tmax:16`` and ``-tout:0.02`` although the XML
keeps ``TimeMax=26``.  This module prepares one forward fine-grid candidate
(``dp=0.0155478404873736``) from the already reviewed mass-fit bracket.  It
only requests GenCase and a generated-XML mass audit; it never starts a
solver, reads BI4/H5 payloads, or grants QI/QN/QE.

The old v1/v2 mass-fit requests remain immutable.  This forward request uses
the official ``-threads:1`` spelling and the shared v4 CPU guard.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any
from xml.etree import ElementTree as ET


REPO = Path(__file__).resolve().parents[5]
PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
STAGE2 = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
CURRENT = DATA_ROOT / "families/infra/STAGE2_CURRENT336_CATALOG/catalog-003/CURRENT336.json"
REVIEW = STAGE2 / "review-source/families/F5.md"
QUALITY = STAGE2 / "reference/stage2_reference_quality_cost_v2.json"
V1_RESULTS = STAGE2 / "reference/stage2_mass_fit_probe_results_v1.json"
V1_REQUEST = STAGE2 / "requests/stage2-mass-fit-probe-v1/f5_s1_massfit_v1_fine_dp0p015635.json"
V1_RECEIPT = DATA_ROOT / "families/F5/F5_S1_MASSFIT_V1_FINE_DP0p015635/f5_s1_massfit_v1_fine_dp0p015635-001/execution-receipt.json"
V2_REQUEST = STAGE2 / "requests/stage2-mass-fit-probe-v2/f5_s1_massfit_v2_fine_dp0p015548.json"
SOURCE_XML = DATA_ROOT / (
    "families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1/"
    "root-stage1-f5-c082s1-m095_t090-genuine-gencase-118-root640/prepared/"
    "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1.xml"
)
SOURCE_GCASE_RECEIPT = SOURCE_XML.parents[1] / "execution-receipt.json"
SOURCE_SOLVER_ROOT = DATA_ROOT / (
    "families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1/"
    "root-stage1-f5-c082s1-m095_t090-full801-native-release-131-root808"
)
SOURCE_SOLVER_RECEIPT = SOURCE_SOLVER_ROOT / "execution-receipt.json"
SOURCE_RUNPARTS = SOURCE_SOLVER_ROOT / "solver_output/RunPARTs.csv"
SOURCE_DEF = Path(
    "/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/"
    "handoff_20261003/root_followup_118_stage1_f5_c082s1_first24_cpu_contract_disabled_v1/"
    "candidates/M095_T090/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M095_T090_Def.xml"
)
MOTION = DATA_ROOT / (
    "families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1/"
    "root-stage1-f5-c082s1-m095_t090-motion-transform-117-root630/prepared/assets/"
    "f5_c082s1_motion_m095_t090.dat"
)
CANDIDATE_DEF = STAGE2 / "reference/stage2_mass_fit_probe_inputs_v2/F5_S1/fine/fine_Def.xml"
CANDIDATE_MOTION = CANDIDATE_DEF.parent / "assets/f5_c082s1_motion_m095_t090.dat"
EFFECTIVE_CONTROL = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F5_EFFECTIVE_CONTROL_INDEPENDENT_VERIFICATION_001.json"
FULL801_ANCHOR = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F5_FULL801_RAW_RECONSTRUCTION_ACTUAL_INDEPENDENT_VERIFICATION_001.json"
LABELS = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F5_ANCHOR_FAMILY_LABELS_ACTUAL_INDEPENDENT_VERIFICATION_001.json"
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
REQUEST = STAGE2 / "requests/f5-s1-mass-support-canary-v1-root-forward-001.json"
BUDGET = STAGE2 / "reference/stage2_f5_s1_mass_support_canary_v1.json"
MiB = 1024 * 1024


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def record(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    st = path.stat()
    return {"path": str(path.resolve()), "bytes": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": sha256(path)}


def write_new(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as f:
            fd = -1
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def normalized_def(path: Path) -> str:
    data = path.read_bytes()
    data, n = re.subn(rb'(<definition\b[^>]*\bdp=")[^"]+("[^>]*>)', rb"\1<DP>\2", data, count=1)
    if n != 1:
        raise ValueError(f"missing unique definition@dp: {path}")
    return hashlib.sha256(data).hexdigest()


def definition_dp(path: Path) -> float:
    root = ET.parse(path).getroot()
    node = root.find(".//definition")
    if node is None or "dp" not in node.attrib:
        raise ValueError(f"missing definition dp: {path}")
    return float(node.attrib["dp"])


def source_controls() -> dict[str, Any]:
    root = ET.parse(SOURCE_XML).getroot()
    params = {n.attrib.get("key"): n.attrib.get("value") for n in root.findall(".//parameter")}
    cfl = [n.attrib.get("value") for n in root.findall(".//cflnumber")]
    motion_names = [n.attrib.get("name") for n in root.findall(".//motion//file")]
    if params.get("TimeMax") != "26" or params.get("TimeOut") != "0.02":
        raise ValueError("unexpected source XML time controls")
    if cfl != ["0.2", "0.2"]:
        raise ValueError(f"unexpected source CFL values: {cfl}")
    if motion_names != ["assets/f5_c082s1_motion_m095_t090.dat", "assets/f5_c082s1_motion_m095_t090.dat"]:
        raise ValueError(f"unexpected source motion refs: {motion_names}")
    return {
        "xml_TimeMax_s": 26.0,
        "xml_TimeOut_s": 0.02,
        "source_effective_cli_tmax_s": 16.0,
        "source_effective_cli_tout_s": 0.02,
        "source_cfl": 0.2,
        "motion_table_asset": "assets/f5_c082s1_motion_m095_t090.dat",
        "motion_is_transformed_source": True,
        "xml_time_vs_cli_note": "XML TimeMax=26 is retained source metadata; historical solver argv -tmax:16 is authoritative for the 16 s window.",
    }


def load_lineage() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    results = json.loads(V1_RESULTS.read_text(encoding="utf-8"))
    previous = next(x for x in results["results"] if x["sentinel_id"] == "F5-S1" and x["label"] == "fine")
    effective = json.loads(EFFECTIVE_CONTROL.read_text(encoding="utf-8"))
    anchor = json.loads(FULL801_ANCHOR.read_text(encoding="utf-8"))
    return previous, effective, anchor


def validate() -> dict[str, Any]:
    required = [
        CURRENT, REVIEW, QUALITY, V1_RESULTS, V1_REQUEST, V1_RECEIPT, V2_REQUEST,
        SOURCE_XML, SOURCE_GCASE_RECEIPT, SOURCE_SOLVER_RECEIPT, SOURCE_RUNPARTS,
        SOURCE_DEF, MOTION, CANDIDATE_DEF, CANDIDATE_MOTION, EFFECTIVE_CONTROL,
        FULL801_ANCHOR, LABELS, GENCASE,
    ]
    for path in required:
        record(path)
    if sha256(MOTION) != sha256(CANDIDATE_MOTION):
        raise ValueError("candidate motion is not byte-identical to transformed source motion")
    if normalized_def(SOURCE_DEF) != normalized_def(CANDIDATE_DEF):
        raise ValueError("candidate changes normalized continuous Def geometry/control")
    if abs(definition_dp(SOURCE_DEF) - 0.02) > 1e-12:
        raise ValueError("unexpected source dp")
    if abs(definition_dp(CANDIDATE_DEF) - 0.0155478404873736) > 1e-12:
        raise ValueError("unexpected candidate dp")
    controls = source_controls()
    previous, effective, anchor = load_lineage()
    if effective.get("status") != "PASS_SCOPED_SOURCE_CONTROL_AND_SAVED_TIME":
        raise ValueError("effective-control proof is not scoped PASS")
    if anchor.get("native_frame_count") != 801 or anchor.get("scientific_qualification", {}).get("QI") != "UNKNOWN":
        raise ValueError("full801 anchor scope changed or was upgraded")
    if previous["mass_gate"]["gate"] != "MARGINAL_1_TO_2PCT":
        raise ValueError("expected prior fine bracket to remain marginal")
    return {"controls": controls, "previous": previous, "effective": effective, "anchor": anchor}


def build() -> tuple[dict[str, Any], dict[str, Any]]:
    facts = validate()
    source_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()
    file_paths = [
        PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py",
        PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v4.py",
        PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v4.py",
        GENCASE,
        Path(__file__), CURRENT, REVIEW, QUALITY, V1_RESULTS, V1_REQUEST, V1_RECEIPT, V2_REQUEST,
        SOURCE_XML, SOURCE_GCASE_RECEIPT, SOURCE_SOLVER_RECEIPT, SOURCE_RUNPARTS, SOURCE_DEF, MOTION,
        CANDIDATE_DEF, CANDIDATE_MOTION, EFFECTIVE_CONTROL, FULL801_ANCHOR, LABELS,
    ]
    unique: list[Path] = []
    seen: set[str] = set()
    for path in file_paths:
        path = path.resolve()
        if str(path) not in seen:
            unique.append(path)
            seen.add(str(path))
    inputs = {str(path): sha256(path) for path in unique}
    source_binding = {
        "schema": "ds02.stage2.f5-s1-mass-support-source-binding.v1",
        "sentinel_id": "F5-S1",
        "family_id": "F5",
        "physical_case_id": "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090",
        "source_xml": record(SOURCE_XML),
        "source_definition": record(SOURCE_DEF),
        "transformed_motion": record(MOTION),
        "source_gencase_receipt": record(SOURCE_GCASE_RECEIPT),
        "source_solver_receipt": record(SOURCE_SOLVER_RECEIPT),
        "source_runparts": record(SOURCE_RUNPARTS),
        "effective_control_proof": record(EFFECTIVE_CONTROL),
        "full801_anchor_proof": record(FULL801_ANCHOR),
        "anchor_label_proof": record(LABELS),
        "candidate_definition": record(CANDIDATE_DEF),
        "candidate_motion_copy": record(CANDIDATE_MOTION),
        "normalized_continuous_definition_equal": True,
        "motion_copy_byte_identical": True,
    }
    candidate = {
        "dp_m": definition_dp(CANDIDATE_DEF),
        "h_m": 0.0155478404873736 * (3.0 ** 0.5),
        "source_dp_m": 0.02,
        "prior_actual_dp_m": facts["previous"]["prediction"]["predicted_dp_m"],
        "prior_actual_sample_mass_kg": facts["previous"]["mass_gate"]["actual_generated_xml_sample_mass_kg"],
        "source_sample_mass_kg": facts["previous"]["mass_gate"]["source_sample_mass_kg"],
        "prior_actual_deviation_pct": facts["previous"]["mass_gate"]["deviation_pct_vs_source"],
        "mass_gate": "UNKNOWN_UNTIL_GUARDED_GENERATED_XML",
        "mass_rescaling": False,
        "continuous_geometry_or_control_change": False,
    }
    budget = {
        "schema": "ds02.stage2.f5-s1-mass-support-canary.v1",
        "status": "READY_FOR_PARENT_CPU_GUARD_REVIEW",
        "sentinel_id": "F5-S1",
        "family_id": "F5",
        "physical_case_id": "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090",
        "candidate": candidate,
        "source_and_control": facts["controls"],
        "source_binding": source_binding,
        "three_grid_context": {
            "original_dp0p020000": {"initial_sample_mass_kg": 253.264, "mass_gate": "PASS_TARGET_1PCT_DIAGNOSTIC", "source_role": "actual F5-S1 source; no new GenCase"},
            "coarse_dp0p0247861835694456": {"initial_sample_mass_kg": 254.923798949948, "deviation_pct_vs_original": 0.6553631585807687, "mass_gate": "PASS_TARGET_1PCT_DIAGNOSTIC", "source_role": "completed v1 GenCase audit; no rerun"},
            "fine_dp0p0155478404873736": {"initial_sample_mass_kg": "UNKNOWN_UNTIL_GUARDED_GENERATED_XML", "source_role": "this forward CPU GenCase canary"},
            "interpretation": "All mass values are initial SPH sample-mass diagnostics. They do not establish continuous-bed truth or QI/QN/QE.",
        },
        "budget": {
            "task": "GenCase plus generated-XML mass/control audit only",
            "cpu_threads": 1,
            "max_wall_seconds": 900,
            "estimated_cpu_core_hours": 0.25,
            "estimated_storage_bytes": 134217728,
            "gpu": "none",
            "h5_or_full_native_read": "forbidden",
            "solver_launch": "forbidden",
            "output": "new attempt_root only; never overwrite source or prior receipts",
        },
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_status": "not granted by GenCase"},
        "source_producer_vs_current_head": source_head,
    }
    request = {
        "schema": "ds02.request.v1",
        "family_id": "F5",
        "sentinel_id": "F5-S1",
        "case_id": "F5_S1_MASS_SUPPORT_CANARY_DP0p015548",
        "physical_case_id": "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090",
        "attempt_id": "f5-s1-mass-support-canary-dp0p015548-root-forward-001",
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 900,
        "estimated_storage_bytes": 134217728,
        "worktree_root": str(REPO),
        "cwd": str(CANDIDATE_DEF.parent.resolve()),
        "command": [str(GENCASE), str(CANDIDATE_DEF.with_suffix("")), "{attempt_root}/generated", "-save:all", "-threads:1"],
        "input_files": [str(path) for path in unique],
        "input_hashes": inputs,
        "input_sha256": inputs,
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py"),
            "strict_guard": str(PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v4.py"),
            "runtime": str(PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v4.py"),
            "launch_commit": source_head,
            "cpu_parent_binding": "required",
            "gpu": "none",
            "solver_launch": "forbidden",
            "estimated_cpu_core_hours": 0.25,
            "estimated_new_storage_bytes": 134217728,
            "source_pre_post_hash_required": True,
        },
        "source_binding": source_binding,
        "mass_support": candidate,
        "scope": {
            "gencase_only": True,
            "solver_started": False,
            "full_time_hdf5_read": False,
            "full_native_read": False,
            "mass_gate": "UNKNOWN_UNTIL_GUARDED_GENERATED_XML",
            "scientific_qualification": "UNKNOWN",
        },
        "budget_report": str(BUDGET.resolve()),
        "status": "READY_FOR_PARENT_CPU_GUARD_REVIEW",
    }
    return budget, request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--emit", action="store_true")
    args = parser.parse_args()
    if not (args.check or args.emit):
        parser.error("choose --check or --emit")
    budget, request = build()
    if args.emit:
        write_new(BUDGET, budget)
        write_new(REQUEST, request)
    print(json.dumps({"status": "PASS", "check": True, "emitted": bool(args.emit), "budget": str(BUDGET), "request": str(REQUEST)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
