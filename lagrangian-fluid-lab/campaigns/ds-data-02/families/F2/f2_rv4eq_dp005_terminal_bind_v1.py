#!/usr/bin/env python3
"""Bind terminal RV4EQ DP005 solver bytes to additive conversion requests.

The v2 conversion templates were intentionally deferred until the two
root-owned solvers terminated.  This additive binder reads those templates,
the terminal semantics report, and immutable native output bytes, then writes
v3 owner metadata and conversion requests.  It never launches conversion or
PartVTKOut and never edits the v2 templates or solver output.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


FAMILY_ROOT = Path(__file__).resolve().parent
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
F2_DATA_ROOT = DATA_ROOT / "families/F2"
V2_ROOT = FAMILY_ROOT / "rv4_equivalent_dp005/postprocess_handoff_v2"
TERMINAL_REPORT = F2_DATA_ROOT / "F2_RV4EQ_DP005_TERMINAL_SEMANTICS_20261002/terminal-semantics.json"
OUTPUT_ROOT = FAMILY_ROOT / "rv4_equivalent_dp005/postprocess_handoff_v3_terminal_bound"
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
CONVERTER = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_direct_convert.py")
RUNTIME = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py")
PYTHON = Path("/home/jade/.codex/worktrees/ds-data-02-f2/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
SCHEMA = "ds-data-02.f2.rv4eq-dp005.postprocess-handoff.v3-terminal-bound"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    return path


def load(path: Path) -> dict[str, Any]:
    value = json.loads(require(path, "JSON input").read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def binding(path: Path) -> dict[str, Any]:
    path = require(path, "bound input")
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}


def case_paths(case_id: str, background: str) -> dict[str, Path]:
    case_root = F2_DATA_ROOT / case_id
    attempts = sorted(case_root.glob("*/solver_output/RunPARTs.csv"))
    if len(attempts) != 1:
        raise ValueError(f"expected one terminal solver output for {case_id}, found {len(attempts)}")
    runparts = attempts[0]
    solver_output = runparts.parent
    attempt_root = solver_output.parent
    data_root = solver_output / "data"
    return {
        "solver_attempt": attempt_root,
        "receipt": attempt_root / "execution-receipt.json",
        "run_out": solver_output / "Run.out",
        "run_csv": solver_output / "Run.csv",
        "runparts": runparts,
        "part_first": data_root / "Part_0000.bi4",
        "part_middle": data_root / "Part_0200.bi4",
        "part_last": data_root / "Part_0400.bi4",
        "data_root": data_root,
    }


def bind_case(background: str, terminal_case: dict[str, Any], output_root: Path) -> tuple[Path, Path]:
    case_id = str(terminal_case["case_id"])
    v2_path = V2_ROOT / "conversion_requests" / f"{case_id}_conversion_request_v2.json"
    v2 = load(v2_path)
    paths = case_paths(case_id, background)
    terminal_files = [paths[key] for key in ("receipt", "run_out", "run_csv", "runparts", "part_first", "part_middle", "part_last")]
    terminal_hashes = {str(path): sha256(require(path, "terminal native input")) for path in terminal_files}
    owner_v2_path = Path(str(v2["owner_metadata"]["path"]))
    owner_v2 = load(owner_v2_path)
    owner = dict(owner_v2)
    owner["schema"] = "ds-data-02.f2.rv4eq-dp005-owner.v3-terminal-bound"
    owner["lineage"] = {
        "previous_owner_metadata": binding(owner_v2_path),
        "terminal_semantics_report": binding(TERMINAL_REPORT),
        "terminal_solver_receipt": binding(paths["receipt"]),
        "terminal_native_output_is_read_only": True,
    }
    owner["terminal_native_semantics"] = {
        "status": "completed_code0_full_window",
        "report": binding(TERMINAL_REPORT),
        "receipt": binding(paths["receipt"]),
        "runparts": binding(paths["runparts"]),
        "NpOut_sum": int(terminal_case["native_exclusion_accounting"]["NpOut_sum"]),
        "NpOutPos_sum": int(terminal_case["native_exclusion_accounting"]["NpOutPos_sum"]),
        "NpOutRho_sum": int(terminal_case["native_exclusion_accounting"]["NpOutRho_sum"]),
        "NpOutMov_sum": int(terminal_case["native_exclusion_accounting"]["NpOutMov_sum"]),
        "initial_fluid_particles": int(terminal_case["native_exclusion_accounting"]["initial_fluid_particles"]),
        "final_fluid_particles": int(terminal_case["native_exclusion_accounting"]["final_fluid_particles"]),
        "motive_status": "pending_official_partvtkout",
        "fate_status": "numerical_unknown_until_typed_position_motive_pose_closure",
    }
    owner_path = output_root / "owner_metadata" / f"{case_id}.owner.v3.json"
    dump(owner_path, owner)

    request = json.loads(json.dumps(v2))
    request["schema"] = "ds-data-02.runner.request.v1"
    request["attempt_id"] = f"conversion-{case_id.lower()}-fullstate-v3-terminal-bound-001"
    request["status"] = "ready_deferred_conversion_slot"
    request["conversion_launch"] = {
        "allowed": False,
        "reason": "F4 conversion slots are occupied; root must schedule this immutable request after slot review",
    }
    request["deferred_binding_policy"] = "terminal solver is code0 and all listed native hashes are bound; root still controls launch and conversion slot"
    request["solver_launch_forbidden"] = True
    request["owner_metadata"] = {"path": str(owner_path), "sha256": sha256(owner_path)}
    request["command"] = [
        str(PYTHON),
        str(CONVERTER),
        "--data-root", str(paths["data_root"]),
        "--generated-xml", str(request["generated_xml"]["path"]),
        "--output", "{attempt_root}/trajectory.h5",
        "--report", "{attempt_root}/conversion-report.json",
        "--solver-log", str(paths["run_out"]),
        "--solver-receipt", str(paths["receipt"]),
        "--gencase-receipt", str(request["gencase_receipt"]),
        "--owner-metadata", str(owner_path),
        "--decoder", request["command"][request["command"].index("--decoder") + 1],
        "--partvtk", str(PARTVTK),
        "--validation-dir", "{attempt_root}/partvtk-validation",
        "--keep-validation-csv",
    ]
    request["input_files"] = list(dict.fromkeys([*request["input_files"], str(FAMILY_ROOT / "f2_rv4eq_dp005_terminal_bind_v1.py"), str(FAMILY_ROOT / "f2_rv4eq_dp005_terminal_semantics_v1.py"), str(TERMINAL_REPORT), str(PARTVTK), str(CONVERTER), str(RUNTIME), *[str(path) for path in terminal_files]]))
    input_sha = dict(request.get("input_sha256", {}))
    for path in request["input_files"]:
        input_sha[str(Path(path).resolve())] = sha256(require(Path(path), "request input"))
    request["input_sha256"] = dict(sorted(input_sha.items()))
    request["deferred_input_files"] = []
    request["terminal_source_bindings"] = {str(path): binding(path) for path in terminal_files}
    request["terminal_semantics_report"] = binding(TERMINAL_REPORT)
    request["native_exclusion_gate"] = {
        "status": "terminal_runparts_bound_typed_partvtkout_pending",
        "semantics": "RunPARTs full-window sums are bound; PartVTKOut Idp/PartOut/Motive/position and moving-pose closure remain separate",
        "NpOut_sum": int(terminal_case["native_exclusion_accounting"]["NpOut_sum"]),
        "NpOutPos_sum": int(terminal_case["native_exclusion_accounting"]["NpOutPos_sum"]),
        "NpOutRho_sum": int(terminal_case["native_exclusion_accounting"]["NpOutRho_sum"]),
        "NpOutMov_sum": int(terminal_case["native_exclusion_accounting"]["NpOutMov_sum"]),
        "motive_status": "pending_official_partvtkout",
        "unknown_fate_kept": True,
        "physical_spill_inference": False,
    }
    request["actual_source"] = {
        **request["actual_source"],
        "terminal_semantics_report": binding(TERMINAL_REPORT),
        "solver_receipt": binding(paths["receipt"]),
        "run_out": binding(paths["run_out"]),
        "run_csv": binding(paths["run_csv"]),
        "runparts": binding(paths["runparts"]),
        "full_window_native_part_files": {"count": 401, "first": binding(paths["part_first"]), "middle": binding(paths["part_middle"]), "last": binding(paths["part_last"])},
        "terminal_status": "completed_code0",
        "physical_fate": "unknown_until_typed_partvtkout_and_pose_boundary_closure",
    }
    request["quality_thresholds"]["event_timing_qualification"] = False
    request["request_note"] = "Terminal-bound immutable owner/fullstate request. It is ready for root scheduling but launch remains disabled while F4 owns both conversion slots. PartVTK_linux64 is the full-frame validator; PartVTKOut Motive closure is separate and does not grant Q-I/Q-N."
    out_path = output_root / "conversion_requests" / f"{case_id}_conversion_request_v3_terminal_bound.json"
    dump(out_path, request)
    return owner_path, out_path


def build(output_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    output_root = output_root.expanduser().resolve()
    report = load(TERMINAL_REPORT)
    cases = {str(case["background"]): case for case in report.get("cases", [])}
    if set(cases) != {"CENTER", "OFFSET"}:
        raise ValueError("terminal semantics report must contain CENTER and OFFSET")
    owners: list[Path] = []
    requests: list[Path] = []
    for background in ("CENTER", "OFFSET"):
        owner, request = bind_case(background, cases[background], output_root)
        owners.append(owner)
        requests.append(request)
    manifest = {
        "schema": SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "scope_id": "F2_SCOPE_RV4_EQUIVALENT_DP005_PRECHECK_20261002",
        "terminal_semantics_report": binding(TERMINAL_REPORT),
        "requests": [binding(path) for path in requests],
        "owner_metadata": [binding(path) for path in owners],
        "partvtk": {"path": str(PARTVTK), "sha256": sha256(require(PARTVTK, "PartVTK_linux64")), "role": "full-frame conversion validation"},
        "partvtkout": {"path": "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64", "role": "separate typed native exclusion closure; not invoked"},
        "solver_launch": False,
        "conversion_launch": False,
        "qualification_claim": "none",
        "production_claim": "none",
    }
    manifest_path = output_root / "postprocess_handoff_manifest_v3_terminal_bound.json"
    dump(manifest_path, manifest)
    manifest["manifest"] = binding(manifest_path)
    dump(manifest_path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    result = build(args.output_root)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
