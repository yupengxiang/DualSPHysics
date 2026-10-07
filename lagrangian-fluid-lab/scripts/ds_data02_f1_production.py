#!/usr/bin/env python3
"""Assign F1 split plan and materialize Stage 8 production definitions and GenCase requests."""

from __future__ import annotations

import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from ds_data02_f1 import (
    FAMILY_DIR,
    FAMILY_ID,
    make_case,
    write_case,
    preflight_definition,
    sha256_file,
)
BIN_ROOT = REPO / "vendor/official/DualSPHysics_v5.4/bin/linux"

SPLIT_MAP = {
    1: "train", 2: "validation", 3: "test", 4: "train",
    5: "validation", 6: "test", 7: "train", 8: "validation",
    9: "test", 10: "train", 11: "validation", 12: "test",
    13: "train", 14: "validation", 15: "test", 16: "train",
    17: "validation", 18: "test", 19: "train", 20: "validation",
    21: "test", 22: "train", 23: "validation", 24: "test",
}


def stage_for_pair(pair: int) -> str:
    if 1 <= pair <= 4:
        return "stage8"
    if 5 <= pair <= 12:
        return "stage24"
    if 13 <= pair <= 24:
        return "stage48"
    raise ValueError(f"unknown pair {pair}")


def apply_f1_splits(family_dir: Path = FAMILY_DIR) -> dict[str, Any]:
    family_dir = Path(family_dir).resolve()
    registry_path = family_dir / "case_registry.jsonl"
    split_plan_path = family_dir / "split_plan.json"

    # 1. Write split_plan.json
    split_plan = {
        "schema": "ds-data-02.f1.split-plan.v1",
        "family_id": FAMILY_ID,
        "assigned": True,
        "status": "assigned_stages_8_24_48",
        "grouping_key": "physical_case_id/lineage_group_id",
        "leakage_rule": (
            "resolution views, restarts, windows, and format copies stay in the same physical group; "
            "paired eccentric and dual channel cases retain identical split to eliminate cross-mechanism leakage"
        ),
        "production_case_count": 48,
        "production_cases_per_mechanism": 24,
        "reference_case_count": 6,
        "split_counts": {
            "train": 16,
            "validation": 16,
            "test": 16,
        },
        "split_counts_per_mechanism": {
            "eccentric_obstacle": {"train": 8, "validation": 8, "test": 8},
            "asymmetric_dual_channel": {"train": 8, "validation": 8, "test": 8},
        },
        "stages": {
            "stage8": {
                "cumulative_case_count": 8,
                "incremental_case_count": 8,
                "selection": "physical parent pairs 1..4 (4 eccentric + 4 dual)",
                "split_counts": {"train": 4, "validation": 2, "test": 2},
            },
            "stage24": {
                "cumulative_case_count": 24,
                "incremental_case_count": 16,
                "selection": "physical parent pairs 5..12 (cumulative pairs 1..12)",
                "split_counts": {"train": 8, "validation": 8, "test": 8},
            },
            "stage48": {
                "cumulative_case_count": 48,
                "incremental_case_count": 24,
                "selection": "physical parent pairs 13..24 (cumulative pairs 1..24)",
                "split_counts": {"train": 16, "validation": 16, "test": 16},
            },
        },
    }
    split_plan_path.write_text(json.dumps(split_plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # 2. Update case_registry.jsonl
    cases = []
    for line in registry_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        pair_str = row["paired_background_id"]
        pair_num = int(pair_str.split("_")[-1])
        split = SPLIT_MAP[pair_num]
        stage = stage_for_pair(pair_num)
        row["split"] = split
        row["stage"] = stage
        row["production"] = True
        row["production_resolution"] = "fine"
        cases.append(row)

    registry_path.write_text("\n".join(json.dumps(c, sort_keys=True) for c in cases) + "\n", encoding="utf-8")

    return {
        "status": "splits_applied",
        "split_plan_path": str(split_plan_path),
        "registry_path": str(registry_path),
        "total_cases": len(cases),
    }


def materialize_stage8(family_dir: Path = FAMILY_DIR) -> list[dict[str, Any]]:
    family_dir = Path(family_dir).resolve()
    registry_path = family_dir / "case_registry.jsonl"
    prod_defs_dir = family_dir / "production/definitions"
    requests_dir = family_dir / "requests"
    prod_defs_dir.mkdir(parents=True, exist_ok=True)
    requests_dir.mkdir(parents=True, exist_ok=True)

    gencase_bin = REPO / "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"

    cases = [json.loads(line) for line in registry_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    stage8_cases = [c for c in cases if c.get("stage") == "stage8"]

    materialized = []
    for c in stage8_cases:
        cid = f"{c['case_id']}_FINE"
        case_dict = make_case(
            c["mechanism_id"],
            "fine",
            case_id=cid,
            physical_case_id=c["physical_case_id"],
            paired_background_id=c["paired_background_id"],
            values=c["parameter_values"],
            strict_source=False,
        )
        write_result = write_case(case_dict, prod_defs_dir)
        preflight_result = preflight_definition(write_result["definition_path"], write_result["metadata_path"], require_source_evidence=False)
        assert preflight_result["status"] == "pass", f"preflight failed for {cid}"

        # Emit GenCase request
        def_xml = Path(write_result["definition_path"]).resolve()
        gencase_req = {
            "schema": "ds02.cpu-request.v2",
            "family_id": FAMILY_ID,
            "case_id": cid,
            "attempt_id": f"{cid}_GENCASE_01",
            "kind": "cpu",
            "cpu_task_kind": "gencase",
            "command": [
                str(gencase_bin),
                str(def_xml.with_suffix("")),
                "{attempt_root}/" + cid,
                "-save:all",
            ],
            "cwd": str(prod_defs_dir),
            "max_wall_seconds": 300,
            "cpu_threads": 4,
            "estimated_storage_bytes": 256 * 1024 * 1024,
            "input_files": [
                str(gencase_bin),
                str(def_xml),
                str(Path(write_result["metadata_path"]).resolve()),
            ],
            "worktree_root": str(REPO.parent),
            "purpose": "bounded native GenCase preflight only; no solver/GPU/model",
            "physical_parent_id": c["physical_case_id"],
            "registry_kind": "production",
            "expected_checks": {
                "mechanism": c["mechanism_id"],
                "registry_kind": "production",
                "physical_parent_id": c["physical_case_id"],
                "resolution": "fine",
                "expected_dimension": 3,
                "positive_fluid_required": True,
            },
        }
        req_path = requests_dir / f"{cid}-gencase.json"
        req_path.write_text(json.dumps(gencase_req, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        materialized.append({
            "case_id": cid,
            "definition": str(def_xml),
            "gencase_request": str(req_path),
        })

    return materialized


def emit_stage8_solver_requests(family_dir: Path = FAMILY_DIR, attempt_number: int = 1) -> list[Path]:
    family_dir = Path(family_dir).resolve()
    requests_dir = family_dir / "requests"
    prod_defs_dir = family_dir / "production/definitions"
    data_f1_dir = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1")
    solver_bin = REPO / "vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"

    cases = [
        ("F1_ECC_P01_FINE", "eccentric_obstacle", 1.6, 0.01),
        ("F1_ECC_P02_FINE", "eccentric_obstacle", 1.6, 0.01),
        ("F1_ECC_P03_FINE", "eccentric_obstacle", 1.6, 0.01),
        ("F1_ECC_P04_FINE", "eccentric_obstacle", 1.6, 0.01),
        ("F1_DUAL_P01_FINE", "asymmetric_dual_channel", 6.0, 0.01),
        ("F1_DUAL_P02_FINE", "asymmetric_dual_channel", 6.0, 0.01),
        ("F1_DUAL_P03_FINE", "asymmetric_dual_channel", 6.0, 0.01),
        ("F1_DUAL_P04_FINE", "asymmetric_dual_channel", 6.0, 0.01),
    ]

    solver_requests = []
    for cid, mech, tmax, tout in cases:
        gencase_receipts = sorted((data_f1_dir / cid).glob(f"{cid}_GENCASE_*/execution-receipt.json"))
        valid_receipt = None
        for r_path in reversed(gencase_receipts):
            r_data = json.loads(r_path.read_text())
            if r_data.get("status") == "completed" and r_data.get("returncode") == 0 and r_data.get("fluid_particles", 0) > 0:
                valid_receipt = r_path
                receipt_data = r_data
                break
        if not valid_receipt:
            raise RuntimeError(f"no valid completed GenCase receipt found for {cid}")

        gencase_dir = valid_receipt.parent
        prefix = gencase_dir / cid
        bi4 = prefix.with_suffix(".bi4")
        xml = prefix.with_suffix(".xml")
        def_xml = prod_defs_dir / f"{cid}_Def.xml"
        meta_json = prod_defs_dir / f"{cid}.metadata.json"

        for p in (bi4, xml, def_xml, meta_json):
            if not p.is_file():
                raise FileNotFoundError(f"missing required file {p}")

        input_files = [
            str(valid_receipt),
            str(bi4),
            str(xml),
            str(def_xml),
            str(meta_json),
        ]
        input_hashes = {p: sha256_file(Path(p)) for p in input_files}

        total_parts = receipt_data["total_particles"]
        is_dual = mech == "asymmetric_dual_channel"

        # Check existing qualification attempts
        qual_dirs = sorted((data_f1_dir / cid).glob(f"{cid}_QUALIFICATION_*"))
        completed_qual = False
        latest_attempt_idx = 0
        for qd in qual_dirs:
            rec_file = qd / "execution-receipt.json"
            if rec_file.is_file():
                try:
                    qrec = json.loads(rec_file.read_text())
                    num = int(qd.name.split("_")[-1])
                    latest_attempt_idx = max(latest_attempt_idx, num)
                    if qrec.get("status") == "completed" and qrec.get("returncode") == 0:
                        completed_qual = True
                except Exception:
                    pass

        if completed_qual:
            current_attempt = 1
        else:
            current_attempt = max(latest_attempt_idx + 1, attempt_number)

        req = {
            "schema": "ds02.runner-request.v2",
            "family_id": "F1",
            "case_id": cid,
            "attempt_id": f"{cid}_QUALIFICATION_{current_attempt:03d}",
            "physical_case_id": cid.replace("_FINE", ""),
            "physical_parent_id": cid.replace("_FINE", ""),
            "registry_kind": "production",
            "kind": "qualification",
            "command": [
                str(solver_bin),
                str(prefix),
                "{attempt_root}/solver",
                f"-tmax:{tmax}",
                f"-tout:{tout}",
            ],
            "cwd": str(gencase_dir),
            "worktree_root": str(REPO.parent),
            "max_wall_seconds": 2400 if is_dual else 600,
            "cpu_threads": 2,
            "estimated_storage_bytes": 40 * 1024**3 if is_dual else 2 * 1024**3,
            "estimated_peak_gpu_mib": 16384 if is_dual else 2048,
            "gencase_receipt": str(valid_receipt),
            "gencase_receipt_sha256": sha256_file(valid_receipt),
            "gencase_prefix": str(prefix),
            "gencase_bi4": str(bi4),
            "gencase_xml": str(xml),
            "input_files": input_files,
            "input_hashes": input_hashes,
        }

        req_path = requests_dir / f"{cid}-solver.json"
        req_path.write_text(json.dumps(req, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        solver_requests.append(req_path)

    return solver_requests


if __name__ == "__main__":
    split_res = apply_f1_splits()
    print(json.dumps(split_res, indent=2))
    stage8_res = materialize_stage8()
    print(f"Materialized {len(stage8_res)} Stage 8 cases for F1.")
    solvers = emit_stage8_solver_requests()
    print(f"Emitted {len(solvers)} Stage 8 solver requests for F1.")

