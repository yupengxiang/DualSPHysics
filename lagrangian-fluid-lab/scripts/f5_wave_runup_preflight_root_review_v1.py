#!/usr/bin/env python3
"""Review the fresh F5 input identity and authorize one CPU/native preflight."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any


LAB = Path(__file__).resolve().parents[1]
ROOT = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v1"
ROOT_REVIEW = LAB / "campaigns/core-v1/cfd/f5-wave-runup-root-review-v1.json"
CONTRACT = ROOT / "fresh-definition-contract-v1.json"
DEFINITION = ROOT / "F5_wave_runup_q0p50_dp0p0075_Def.xml"
MOTION = ROOT / "Mov_piston_q0p50_scaled.dat"
OUTPUT = ROOT / "preflight-root-review-v1.json"
IMPLEMENTATION = LAB / "scripts/f5_wave_runup_preflight_root_review_v1.py"
TEST = LAB / "tests/test_f5_wave_runup_preflight_root_review_v1.py"
PREFLIGHT_OUTPUT = ROOT / "preflight-v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(LAB))


def bind(path: Path, role: str) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": rel(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def build() -> dict[str, Any]:
    root_review = load(ROOT_REVIEW)
    contract = load(CONTRACT)
    assert root_review["schema"] == "core.f5.third_t1.root_review_receipt.v1"
    assert root_review["review_decision"]["authorized_solver"] is False
    assert root_review["review_decision"]["authorized_cpu_native_preflight"] is False
    assert contract["schema"] == "core.f5.third_t1.definition_materialization.v1"
    assert contract["status"] == "definition_written_preflight_pending"
    assert contract["qualification_claim"] == "none"
    assert contract["candidate"]["q"] == 0.5
    assert contract["candidate"]["dp_m"] == 0.0075
    assert contract["fixed_contract"]["denominator_rows"] == 15
    assert contract["fixed_contract"]["event_window_required"] is True
    assert contract["execution_controls"]["gencase_invoked"] is False
    assert not PREFLIGHT_OUTPUT.exists(), "preflight output must be new before authorization"

    xml = ET.parse(DEFINITION).getroot()
    definition = xml.find("./casedef/geometry/definition")
    assert definition is not None and definition.get("dp") == "0.0075"
    motion = xml.find("./casedef/motion/objreal/mvpredef/file")
    assert motion is not None and motion.get("name") == MOTION.name
    params = {node.get("key"): node.get("value") for node in xml.findall("./execution/parameters/parameter")}
    assert params.get("TimeMax") == "16"
    assert params.get("TimeOut") == "0.02"
    gauges = {node.get("name") for node in xml.findall("./execution/special/gauges/swl")}
    assert {"WG1", "WG2", "WG3", "WG4"} <= gauges
    rows = [line.split() for line in MOTION.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows and rows[0][0] == "0.0000000000" and float(rows[-1][0]) >= 15.0

    return {
        "schema": "core.f5.third_t1.preflight_root_review_receipt.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "record_id": "f5-wave-runup-third-t1-preflight-root-review-v1",
        "status": "authorized_one_fresh_cpu_native_preflight_only",
        "review_decision": {
            "candidate_scope_id": contract["candidate"]["scope_id"],
            "authorized_now": True,
            "authorized_action": "run_exactly_one_fresh_cpu_gencase_native_decode",
            "authorized_case": "F5_wave_runup_q0p50_dp0p0075",
            "authorized_solver": False,
            "authorized_gpu": False,
            "authorized_queue": False,
            "authorized_matrix": False,
            "reason": "fresh Definition, motion, official provenance and fixed hard gates are hash-closed",
            "failure_policy": "any hard gate failure stops and remains zero credit; no same-input retry",
        },
        "input_review": {
            "root_review": bind(ROOT_REVIEW, "F5 initial root review"),
            "definition_contract": bind(CONTRACT, "fresh Definition contract"),
            "definition": bind(DEFINITION, "fresh F5 Definition"),
            "motion": bind(MOTION, "fresh F5 piston motion"),
            "motion_row_count": len(rows),
            "motion_time_end_s": float(rows[-1][0]),
            "xml_dp_m": float(definition.get("dp")),
            "xml_time_max_s": float(params["TimeMax"]),
            "xml_output_interval_s": float(params["TimeOut"]),
            "external_gauges": sorted(gauges & {"WG1", "WG2", "WG3", "WG4"}),
            "preflight_output_absent": True,
            "old_generated_or_trajectory_reused": False,
        },
        "fixed_hard_gates": {
            "id_unique_and_xml_aligned": "pending",
            "finite_native_arrays": "pending",
            "mass_gate": "pending",
            "piston_slope_block_endpoint_violations": 0,
            "saved_chord_crossings": 0,
            "full_window_reached": "pending",
            "event_completion": "pending",
            "denominator_rows": 15,
            "qualification_credit": 0,
        },
        "execution_constraints": {
            "review_only": True,
            "gencase_invoked": False,
            "native_decode_invoked": False,
            "solver_invoked": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_mutation": 0,
            "qualification_credit": 0,
            "core_gate_changed": False,
        },
        "hash_bindings": {
            "implementation": bind(IMPLEMENTATION, "F5 preflight root-review implementation"),
            "test": bind(TEST, "F5 preflight root-review regression test"),
        },
    }


def verify(path: Path = OUTPUT) -> dict[str, Any]:
    value = load(path)
    assert value["schema"] == "core.f5.third_t1.preflight_root_review_receipt.v1"
    assert value["review_decision"]["authorized_action"] == "run_exactly_one_fresh_cpu_gencase_native_decode"
    assert value["review_decision"]["authorized_solver"] is False
    assert value["execution_constraints"]["qualification_credit"] == 0
    for item in value["hash_bindings"].values():
        path = LAB / item["path"]
        assert path.is_file() and path.stat().st_size == item["bytes"] and sha256(path) == item["sha256"]
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    review = build()
    args.output.write_text(json.dumps(review, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    verify(args.output)
    print(json.dumps({"status": review["status"], "output": rel(args.output), "sha256": sha256(args.output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
