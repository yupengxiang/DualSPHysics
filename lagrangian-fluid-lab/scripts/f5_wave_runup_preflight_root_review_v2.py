#!/usr/bin/env python3
"""Independent static review of the F5 v2 asset-closure repair."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any


LAB = Path(__file__).resolve().parents[1]
ROOT = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2"
CONTRACT = ROOT / "fresh-definition-contract-v2.json"
V1_PREFLIGHT = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v1/preflight-v1/preflight.json"
OUTPUT = ROOT / "preflight-root-review-v2.json"
IMPLEMENTATION = LAB / "scripts/f5_wave_runup_preflight_root_review_v2.py"
TEST = LAB / "tests/test_f5_wave_runup_preflight_root_review_v2.py"
RUNNER = LAB / "scripts/f5_wave_runup_preflight_v2.py"
PREFLIGHT_OUTPUT = ROOT / "preflight-v2"


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
    contract = load(CONTRACT)
    prior = load(V1_PREFLIGHT)
    assert contract["schema"] == "core.f5.third_t1.definition_materialization.v2"
    assert contract["status"] == "definition_written_preflight_pending"
    assert contract["repair_lineage"]["failure_class"] == "definition_relative_asset_not_adjacent"
    assert prior["status"] == "cpu_native_preflight_failed_hard_audit"
    assert prior["failure_reason"] == "GenCase returned nonzero"
    assert not PREFLIGHT_OUTPUT.exists()
    definition = ROOT / Path(contract["fresh_identity"]["definition"]["output"]["path"]).name
    motion = ROOT / Path(contract["fresh_identity"]["motion"]["output"]["path"]).name
    for path in (definition, motion, ROOT / "Slope.stl", ROOT / "Blocks_3D_scaled.stl"):
        assert path.is_file(), path
    xml = ET.parse(definition).getroot()
    motion_ref = xml.find("./casedef/motion/objreal/mvpredef/file")
    assert motion_ref is not None and (ROOT / motion_ref.get("name")).resolve() == motion.resolve()
    assert {name for name in ("Slope.stl", "Blocks_3D_scaled.stl") if (ROOT / name).is_file()} == {"Slope.stl", "Blocks_3D_scaled.stl"}
    params = {node.get("key"): node.get("value") for node in xml.findall("./execution/parameters/parameter")}
    assert params["TimeMax"] == "16"
    assert params["TimeOut"] == "0.02"
    return {
        "schema": "core.f5.third_t1.preflight_root_review_receipt.v2",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "record_id": "f5-wave-runup-third-t1-preflight-root-review-v2",
        "status": "authorized_one_fresh_cpu_native_preflight_only",
        "review_decision": {
            "candidate_scope_id": contract["candidate"]["scope_id"],
            "candidate_revision_id": contract["candidate"]["revision_id"],
            "authorized_now": True,
            "authorized_action": "run_exactly_one_fresh_v2_cpu_gencase_native_decode",
            "authorized_solver": False,
            "authorized_gpu": False,
            "authorized_queue": False,
            "authorized_matrix": False,
            "reason": "v1 failed before native decode due to a missing Definition-relative STL; v2 closes the asset identity in a new output stem",
            "failure_policy": "any hard gate failure stops and remains zero credit; v1 and v2 output stems cannot be retried",
        },
        "repair_review": {
            "prior_v1_failure": bind(V1_PREFLIGHT, "v1 GenCase failure evidence"),
            "prior_v1_reused": False,
            "new_definition": bind(definition, "fresh v2 Definition"),
            "new_motion": bind(motion, "fresh v2 motion"),
            "adjacent_slope": bind(ROOT / "Slope.stl", "Definition-relative slope asset"),
            "adjacent_blocks": bind(ROOT / "Blocks_3D_scaled.stl", "Definition-relative block asset"),
            "preflight_output_absent": True,
            "asset_closure_pass": True,
        },
        "fixed_hard_gates": {
            "id_unique_and_xml_aligned": "pending",
            "finite_native_arrays": "pending",
            "mass_gate": "pending",
            "geometry_static_integrity": "pending",
            "saved_chord_crossings": 0,
            "full_window_reached": "not_applicable_until_solver",
            "event_completion": "not_applicable_until_solver",
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
            "implementation": bind(IMPLEMENTATION, "F5 v2 preflight root-review implementation"),
            "test": bind(TEST, "F5 v2 preflight root-review regression test"),
            "definition_writer": bind(LAB / "scripts/f5_wave_runup_definition_writer_v2.py", "F5 v2 Definition writer"),
            "preflight_runner": bind(RUNNER, "F5 v2 CPU/native preflight runner"),
        },
    }


def verify(path: Path = OUTPUT) -> dict[str, Any]:
    value = load(path)
    assert value["schema"] == "core.f5.third_t1.preflight_root_review_receipt.v2"
    assert value["review_decision"]["authorized_action"] == "run_exactly_one_fresh_v2_cpu_gencase_native_decode"
    assert value["review_decision"]["authorized_solver"] is False
    for item in value["hash_bindings"].values():
        path = LAB / item["path"]
        assert path.is_file() and path.stat().st_size == item["bytes"] and sha256(path) == item["sha256"]
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    value = build()
    args.output.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    verify(args.output)
    print(json.dumps({"status": value["status"], "output": rel(args.output), "sha256": sha256(args.output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
