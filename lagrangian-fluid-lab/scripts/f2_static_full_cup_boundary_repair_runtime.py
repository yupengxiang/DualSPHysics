#!/usr/bin/env python3
"""Create a runtime view for the independently prepared F2 H1 repair.

The worker itself is the common ``f2_static_full_cup_runtime.py`` adapter;
this module only binds the H1 CPU/native preparation to a new root review.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import f2_static_full_cup_runtime as runtime


H1_SCHEMA = "core.f2.static_full_cup.boundary_repair_prepared.v1"
RUNTIME_SCHEMA = runtime.RUNTIME_SCHEMA
SCOPE_ID = runtime.SCOPE_ID


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def materialize(*, lab: Path, repair_prepared: Path, candidate: Path,
                admission: Path, root_review: Path, output: Path) -> dict[str, Any]:
    lab, repair_prepared, candidate, admission, output = map(Path, (lab, repair_prepared, candidate, admission, output))
    lab, repair_prepared, candidate, admission, output = (p.resolve() for p in (lab, repair_prepared, candidate, admission, output))
    repair = _load(repair_prepared)
    if repair.get("schema") != H1_SCHEMA or repair.get("repair_id") != "F2_static_full_cup_boundary_mdbc_h1_v1":
        raise ValueError("not the pinned H1 repair preparation")
    if repair.get("preflight_pass") is not True or repair.get("qualified") is not False:
        raise ValueError("H1 repair preflight is not passed/unqualified")
    for key in ("solver_invoked", "gpu_invoked", "queue_mutated", "ledger_mutated", "registry_mutated"):
        if repair.get(key) is not False:
            raise ValueError(f"H1 execution control is open: {key}")
    review, review_path = runtime._root_review(root_review, index=0)
    if review.get("repair_id") != repair["repair_id"] or review.get("hypothesis_class") != "H1_boundary_formulation_only":
        raise ValueError("root review does not bind H1")
    base_path = Path(repair["source_prepared"]["path"]).resolve()
    base, base_path = runtime._source_cell(base_path, index=0)
    candidate_payload = _load(candidate)
    admission_payload = _load(admission)
    if candidate_payload.get("scope_id") != SCOPE_ID or admission_payload.get("scope_id") != SCOPE_ID:
        raise ValueError("candidate/admission scope mismatch")
    low, size = runtime._cup(base, candidate_payload)
    sampling = runtime._sampling(base, low, size)
    solver = Path(repair["solver_binary"]).resolve()
    decoder = Path(repair["decoder"]).resolve()
    if not solver.is_file() or not decoder.is_file():
        raise FileNotFoundError("H1 solver/decoder missing")
    q = float(base["q"])
    case_id = str(base["case_id"])
    wall_high = [low[i] + size[i] for i in range(3)]
    config = {
        "schema": "core.cfd.v1", "family": "F2", "scope_id": SCOPE_ID,
        "revision_id": repair["repair_id"], "case_id": case_id,
        "recipe_id": "F2_static_full_cup_volume_hold_mdbc_h1_v1", "recipe": "mdbc_native",
        "stage": "repair_canary", "split": "qualification_only", "qualification_only": True,
        "parameter": {"name": "initial_volume_q", "q": q, "value_m3": float(base["initial_volume_m3"])},
        "dp_m": float(base["dp_m"]), "cfl": 0.2, "time_max_s": float(base["time_max_s"]),
        "output_interval_s": float(base["output_interval_s"]),
        "registered_output_interval_s": float(base.get("registered_output_interval_s", runtime.REGISTERED_OUTPUT_INTERVAL_S)),
        "source_definition": repair["definition_audit"]["definition"], "physical_case_id": case_id,
        "lineage_group_id": f"{SCOPE_ID}/{repair['repair_id']}/{case_id}",
        "source_label_semantics": "single initial numerical fluid source; not material truth",
        "control_semantics": "fixed cup at zero angle; H1 mDBC boundary repair only",
        "cup": {"low": low, "size": size, "mkbound": 0},
        "wall_bounds": {"xmin": low[0], "xmax": wall_high[0], "ymin": low[1], "ymax": wall_high[1],
                        "zmin": low[2], "zmax": wall_high[2]},
        "closed_faces": list(runtime.CLOSED_FACES), "open_faces": ["top"],
        "runtime_domain": candidate_payload["physical_contract"]["runtime_domain"],
        "initial_condition": {"q": q, "initial_volume_m3": float(base["initial_volume_m3"]),
                               "fill_height_m": float(base["initial_fill_height_m"]), "mass_rescaling": False},
        "repair_hypothesis": repair["repair_id"], "qualification_claim": "none; H1 solver canary only", "qualified": False,
    }
    inputs = runtime._input_inventory(repair_prepared, repair, lab, solver, decoder,
                                      candidate, admission, review_path, base_path)
    prepared = {
        "schema": RUNTIME_SCHEMA, "created_at": runtime.stamp(), "family": "F2", "scope_id": SCOPE_ID,
        "cell_index": 0, "repair_id": repair["repair_id"], "source_prepared": runtime.ref(repair_prepared, "H1 CPU/native repair preparation"),
        "source_prepared_sha256": runtime.digest(repair_prepared), "base_source_prepared": runtime.ref(base_path, "v4 DBC source cell"),
        "candidate_card": runtime.ref(candidate, "15-cell candidate card"), "admission_contract": runtime.ref(admission, "F2 candidate admission contract"),
        "root_review": runtime.ref(review_path, "H1 solver-canary root review"), "root_review_decision": review["decision"],
        "config": config, "sampling": sampling, "mass_preflight": runtime.core_cfd.mass_quality(sampling),
        "preflight_pass": bool(runtime.core_cfd.mass_quality(sampling)["mass_gate_pass"]),
        "generated_prefix": repair["generated_prefix"], "source_template": repair["definition_audit"]["definition"],
        "source_template_sha256": repair["definition_audit"]["definition_sha256"], "inputs": inputs,
        "solver_binary": str(solver), "solver_sha256": runtime.digest(solver), "decoder": str(decoder),
        "decoder_sha256": runtime.digest(decoder), "solver_arguments": ["-mdbc_noslip:1"],
        "solver_launch_authorized": True, "gpu_launch_authorized": True, "job_spec_creation_authorized": True,
        "queue_mutation_authorized": True, "ledger_mutation_authorized": True, "registry_mutation_authorized": False,
        "qualification_claim": "none; H1 solver canary only", "qualified": False,
    }
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"runtime output is not fresh: {output}")
    runtime.write_json(output / "prepared.json", prepared)
    return prepared


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, required=True)
    parser.add_argument("--repair-prepared", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--admission", type=Path, required=True)
    parser.add_argument("--root-review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    value = materialize(lab=args.lab_root, repair_prepared=args.repair_prepared, candidate=args.candidate,
                        admission=args.admission, root_review=args.root_review, output=args.output)
    print(json.dumps({"schema": value["schema"], "repair_id": value["repair_id"],
                      "preflight_pass": value["preflight_pass"], "qualification_claim": value["qualification_claim"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
