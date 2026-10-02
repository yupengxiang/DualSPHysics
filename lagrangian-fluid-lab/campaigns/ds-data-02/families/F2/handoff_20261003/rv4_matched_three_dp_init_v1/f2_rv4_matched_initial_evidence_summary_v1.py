#!/usr/bin/env python3
"""Summarise terminal matched-mother GenCase and frame-zero evidence.

The summary reads only compact GenCase receipts, v3 PartVTK reports and their
requests.  It does not read or rewrite the large BI4/CSV payloads.  Every
entry is checked against the report's source bindings and the terminal
request/receipt before it is written.  The result is evidence for a root-owned
solver review; it cannot grant Q-I, Q-N or production eligibility.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


FAMILY_ID = "F2"
SCOPE_ID = "F2_SCOPE_RV4_MATCHED_THREE_DP_INIT_20261003"
SCHEMA = "ds-data-02.f2.rv4-matched-initial-evidence-summary.v1"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
FAMILY_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = Path(__file__).resolve().parent / "artifacts"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path, label: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def require_hash(path: Path, expected: str, label: str) -> str:
    actual = sha256(path)
    if actual != expected:
        raise ValueError(f"{label} hash mismatch: {path}: {actual} != {expected}")
    return actual


def request_for_case(case_id: str) -> Path:
    paths = sorted((ARTIFACT_ROOT / "requests").glob(f"{case_id}_initial_partvtk_audit_request_v3.json"))
    if len(paths) != 1:
        raise FileNotFoundError(f"expected one v3 PartVTK request for {case_id}, got {paths}")
    return paths[0]


def report_for_case(case_id: str, data_root: Path) -> Path:
    paths = sorted((data_root / "families" / "F2" / case_id).glob("partvtk-*-003/initial-partvtk-audit.json"))
    if len(paths) != 1:
        raise FileNotFoundError(f"expected one v3 PartVTK report for {case_id}, got {paths}")
    return paths[0]


def compact_faces(report: dict[str, Any]) -> dict[str, Any]:
    coverage = report["finite_face_coverage"]
    return {
        "all_finite_faces_covered": bool(coverage["all_finite_faces_covered"]),
        "native_mk_row_counts": {
            item["native_mk"]: item["row_count"]
            for item in coverage["boxes"].values()
        },
        "face_pass": {
            item["native_mk"]: bool(item["pass"])
            for item in coverage["boxes"].values()
        },
    }


def case_entry(case_id: str, data_root: Path) -> dict[str, Any]:
    request_path = request_for_case(case_id)
    request = read_json(request_path, "PartVTK request")
    report_path = report_for_case(case_id, data_root)
    report = read_json(report_path, "PartVTK report")
    if report.get("status") != "initial_native_partvtk_audit_complete" or not report.get("all_checks_pass"):
        raise ValueError(f"initial audit did not pass for {case_id}")
    if report.get("q_n_status") != "not_assessed" or report.get("qualification_claim") != "none":
        raise ValueError(f"qualification boundary changed for {case_id}")

    binding = report["source_binding"]
    receipt_path = Path(binding["gencase_receipt"]["path"]).resolve()
    receipt = read_json(receipt_path, "GenCase receipt")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError(f"GenCase receipt is not terminal-successful for {case_id}")
    if request.get("gencase_terminal_binding", {}).get("receipt_path") != str(receipt_path):
        raise ValueError(f"request/GenCase receipt mismatch for {case_id}")
    if request.get("gencase_terminal_binding", {}).get("receipt_sha256") != sha256(receipt_path):
        raise ValueError(f"request/GenCase receipt hash mismatch for {case_id}")
    if request.get("case_id") != case_id or request.get("solver_launch_forbidden") is not True:
        raise ValueError(f"invalid CPU-only request binding for {case_id}")
    if request.get("q_n_status") != "not_assessed":
        raise ValueError(f"request Q-N boundary changed for {case_id}")

    for key in ("metadata", "gencase_receipt", "generated_xml", "generated_bi4"):
        bound = binding[key]
        require_hash(Path(bound["path"]), bound["sha256"], f"report {key}")
    request_sha = sha256(request_path)
    metadata = read_json(Path(binding["metadata"]["path"]), "case metadata")
    source = report["source_fluid"]
    generated = report["generated_xml"]
    return {
        "case_id": case_id,
        "background": metadata["background"],
        "mechanism_id": metadata["mechanism_id"],
        "resolution": metadata["resolution"],
        "dp_m": generated["dp_m"],
        "physical_case_id": metadata["physical_case_id"],
        "physical_condition_hash": binding["physical_condition_hash"],
        "numerical_recipe_hash": binding["numerical_recipe_hash"],
        "q_n_status": report["q_n_status"],
        "qualification_claim": report["qualification_claim"],
        "geometry_family_id": metadata["rv4_binding"]["geometry_family_id"],
        "control_family_id": metadata["rv4_binding"]["control_family_id"],
        "continuum_mass_kg": source["continuous_mass_kg"],
        "native_xml_mass_kg": source["native_xml_mass_total_kg"],
        "csv_mass_kg": source["csv_mass_total_kg"],
        "native_mass_relative_error": source["mass_relative_error_native_to_continuum"],
        "csv_mass_relative_error": source["mass_relative_error_csv_to_continuum"],
        "fluid_count": source["fluid_row_count"],
        "fluid_mk_counts": source["fluid_type_mk_counts"],
        "unique_fluid_ids": source["unique_id_count"],
        "source_band_positions_pass": all(item["pass"] for item in source["source_band_positions"].values()),
        "initial_overlap": source["initial_overlap"],
        "finite_faces": compact_faces(report),
        "gencase": {
            "receipt": str(receipt_path),
            "receipt_sha256": sha256(receipt_path),
            "status": receipt["status"],
            "returncode": receipt["returncode"],
            "elapsed_seconds": receipt.get("elapsed_seconds"),
            "solver_dimension_from_gencase": receipt.get("solver_dimension_from_gencase"),
            "output_root": receipt.get("output_root"),
        },
        "partvtk": {
            "report": str(report_path),
            "report_sha256": sha256(report_path),
            "receipt": str(report_path.parent / "execution-receipt.json"),
            "request": str(request_path),
            "request_sha256": request_sha,
            "csv": report["partvtk"]["csv"],
            "binary": report["partvtk"]["binary"],
            "returncode": report["partvtk"]["returncode"],
        },
        "metadata_sha256": binding["metadata"]["sha256"],
        "generated_xml_sha256": binding["generated_xml"]["sha256"],
        "generated_bi4_sha256": binding["generated_bi4"]["sha256"],
        "motion_sha256": metadata["motion_and_control"]["source_motion_sha256"],
        "physical_projection_equality": metadata["rv4_binding"]["physical_projection_equality"],
    }


def build_summary(data_root: Path = DATA_ROOT) -> dict[str, Any]:
    manifest_path = ARTIFACT_ROOT / "rv4-matched-three-dp-init-manifest.json"
    manifest = read_json(manifest_path, "matched-mother manifest")
    if manifest.get("scope_id") != SCOPE_ID or manifest.get("status") != "same_mother_cpu_gencase_requests_registered_not_run":
        raise ValueError("manifest scope/status changed")
    case_ids = [item["case_id"] for item in manifest["cases"]]
    if len(case_ids) != 4 or len(set(case_ids)) != 4:
        raise ValueError(f"expected four distinct matched cases, got {case_ids}")
    cases = [case_entry(case_id, data_root) for case_id in sorted(case_ids)]
    physical_by_background: dict[str, set[str]] = {}
    for item in cases:
        physical_by_background.setdefault(item["background"], set()).add(item["physical_condition_hash"])
    if any(len(values) != 1 for values in physical_by_background.values()) or set(physical_by_background) != {"CENTER", "OFFSET"}:
        raise ValueError(f"same-background physical hashes are not stable: {physical_by_background}")
    return {
        "schema": SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "family_id": FAMILY_ID,
        "scope_id": SCOPE_ID,
        "status": "actual_initial_gencase_partvtk_evidence_complete",
        "qualification_claim": "none",
        "q_i_status": "initial geometry/population/finite-face evidence only; full lifecycle and solver trajectory not audited",
        "q_n_status": "not_assessed",
        "production_status": "not_evaluated",
        "source_manifest": {"path": str(manifest_path.resolve()), "sha256": sha256(manifest_path)},
        "physical_mother": manifest["physical_mother"],
        "candidate_resolution_plan": manifest["candidate_resolution_plan"],
        "cases": cases,
        "checks": {
            "case_count_is_four": len(cases) == 4,
            "center_and_offset_have_two_resolutions": all(sum(item["background"] == background for item in cases) == 2 for background in ("CENTER", "OFFSET")),
            "same_background_physical_hash_stable": all(len(values) == 1 for values in physical_by_background.values()),
            "all_initial_reports_pass": all(item["finite_faces"]["all_finite_faces_covered"] and item["source_band_positions_pass"] for item in cases),
            "all_native_mass_matches_continuum": all(item["native_mass_relative_error"] == 0.0 for item in cases),
            "all_cases_remain_qn_pending": all(item["q_n_status"] == "not_assessed" and item["qualification_claim"] == "none" for item in cases),
        },
        "claim_boundary": "This sidecar binds actual initial-state evidence only. It does not infer physical spill from initial occupancy, close lifecycle Q-I, compare solver trajectories, or grant Q-N/production eligibility.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    parser.add_argument("--output", type=Path, default=ARTIFACT_ROOT / "rv4-matched-initial-evidence-summary-v1.json")
    args = parser.parse_args()
    result = build_summary(args.data_root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve()), "sha256": sha256(args.output), "case_count": len(result["cases"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
