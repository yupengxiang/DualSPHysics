#!/usr/bin/env python3
"""Materialize a root-reviewed H2 solver-canary runtime manifest.

The adapter consumes the fresh H2 Definition and its passed CPU/native
preflight, then writes a ``core.f2.static_full_cup.runtime_prepared.v1``
manifest understood by the existing read-only worker.  ``prepare`` and
``make-job`` never launch DualSPHysics, CUDA, the queue, or the ledger.  The
only runtime path is an explicit future scheduler job after the H2 runtime
root review has been inspected.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
import sys
from typing import Any

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts import core_cfd
from scripts import f2_static_full_cup_runtime as runtime
PREFLIGHT = LAB / "campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h2-cell0-v1/preflight.json"
WRITER = LAB / "campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h2-cell0-v1/input/writer-receipt.json"
ROOT_REVIEW = LAB / "campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h2-runtime-root-review-v1.json"
REPAIR_ID = "F2_static_full_cup_initial_support_clearance_h2_v1"
SCOPE_ID = "F2_static_full_cup_volume_hold_x_v1"
CASE_ID = "CORE_F2_static_full_cup_volume_supportclearance_h2_q0p00000000_dp0p010000000000_canary"
RUNTIME_SCHEMA = runtime.RUNTIME_SCHEMA
SOLVER_RELATIVE = Path("vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
DECODER_RELATIVE = Path("campaigns/l1-resume/artifacts/bi4_dump")
CLOSED_FACES = ["bottom", "left", "right", "front", "back"]


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    partial.replace(path)


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": digest(path), "bytes": path.stat().st_size, "role": role}


def _resolve(value: str | Path) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else LAB / path).resolve()


def _verify_root_review(path: Path = ROOT_REVIEW) -> dict[str, Any]:
    review = load(path)
    if review.get("schema") != "core.f2.static_full_cup.boundary_repair_h2.runtime_root_review.v1":
        raise ValueError("H2 runtime root review schema mismatch")
    if review.get("status") != "approved_for_one_solver_canary" or review.get("decision") != "approved_for_one_solver_canary":
        raise ValueError("H2 runtime root review does not authorize one solver canary")
    if review.get("authorized_cell_indices") != [0] or review.get("case_id") != CASE_ID:
        raise ValueError("H2 runtime root review canary identity mismatch")
    authorization = review.get("authorization", {})
    for key in ("solver_launch", "gpu_launch", "job_spec_creation", "queue_mutation", "ledger_mutation"):
        if authorization.get(key) is not True:
            raise ValueError(f"H2 runtime review does not authorize {key}")
    if authorization.get("registry_mutation") is not False or authorization.get("qualification_credit") != 0:
        raise ValueError("H2 runtime review opened registry or qualification state")
    controls = review.get("execution_controls", {})
    if controls.get("read_only_review") is not True:
        raise ValueError("H2 runtime review must record a read-only decision")
    if any(controls.get(key) is not False for key in ("solver_now", "gpu_launch_now", "job_spec_creation_now")):
        raise ValueError("H2 runtime review contains an immediate action")
    if any(controls.get(key) != 0 for key in ("queue_mutation_now", "ledger_mutation_now", "registry_mutation_now")):
        raise ValueError("H2 runtime review contains a central mutation")
    if review.get("execution_policy", {}).get("same_input_retry") is not False:
        raise ValueError("same-input retry is not closed")
    return review


def _input_inventory(paths: list[Path]) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in paths:
        path = Path(path).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        result[str(path)] = digest(path)
    return result


def _runtime_domain(definition: Path) -> dict[str, list[float]]:
    root = ET.parse(definition).getroot()
    node = root.find("./execution/parameters/simulationdomain")
    if node is None:
        raise ValueError("fresh H2 Definition has no simulation domain")
    result = {}
    for key in ("posmin", "posmax"):
        value = node.find(key)
        if value is None:
            raise ValueError(f"fresh H2 Definition has no {key}")
        result[key] = [float(value.get(axis)) for axis in "xyz"]
    return {"posmin_m": result["posmin"], "posmax_m": result["posmax"]}


def prepare(*, preflight_path: Path = PREFLIGHT, writer_path: Path = WRITER,
            root_review_path: Path = ROOT_REVIEW, output: Path) -> dict[str, Any]:
    preflight_path, writer_path, root_review_path, output = map(Path, (preflight_path, writer_path, root_review_path, output))
    preflight_path, writer_path, root_review_path, output = (p.resolve() for p in (preflight_path, writer_path, root_review_path, output))
    review = _verify_root_review(root_review_path)
    preflight = load(preflight_path)
    writer = load(writer_path)
    if preflight.get("status") != "cpu_native_preflight_pass" or preflight.get("preflight_pass") is not True:
        raise ValueError("H2 CPU/native input preflight is not passed")
    if preflight.get("qualified") is not False or preflight.get("T1_numerical") is not False or preflight.get("matrix_credit") != 0:
        raise ValueError("H2 preflight qualification boundary changed")
    if preflight.get("case_id") != CASE_ID or writer.get("case_id") != CASE_ID:
        raise ValueError("H2 prepared case identity mismatch")
    definition = _resolve(writer["definition"]["path"])
    motion = _resolve(writer["motion"]["path"])
    generated_xml = _resolve(preflight["gencase_generated_xml"]["path"])
    bi4 = _resolve(preflight["native_bi4"]["path"])
    solver = LAB / SOLVER_RELATIVE
    decoder = LAB / DECODER_RELATIVE
    for path in (definition, motion, generated_xml, bi4, solver, decoder):
        if not path.is_file():
            raise FileNotFoundError(path)
    generated_motion = bi4.parent / motion.name
    if generated_motion.exists() and digest(generated_motion) != digest(motion):
        raise ValueError("generated motion file conflicts with the fresh H2 motion")
    if not generated_motion.exists():
        # GenCase preserves the filename in the generated XML but does not
        # copy this zero-angle file for every invocation.  Materialize the
        # exact fresh file beside the generated prefix before any solver job;
        # this is still input preparation, not a solver retry or trajectory.
        shutil.copyfile(motion, generated_motion)
    fluid = writer["continuous_fluid"]
    sampling = writer["sampling"]
    continuous_low = [float(x) for x in fluid["low_m"]]
    continuous_size = [float(x) for x in fluid["size_m"]]
    continuous_mass = float(fluid["volume_m3"]) * 1000.0
    discrete_mass = float(sampling["native_mass_kg"])
    box = {
        "continuous_low_m": continuous_low,
        "continuous_size_m": continuous_size,
        "continuous_volume_m3": float(fluid["volume_m3"]),
        "continuous_mass_kg": continuous_mass,
        "discrete_mass_kg": discrete_mass,
        "first_center_m": [float(x) for x in sampling["first_center_m"]],
        "draw_size_m": [float(x) for x in sampling["draw_size_m"]],
        "counts": [int(x) for x in sampling["counts"]],
        "particle_count": int(sampling["particle_count"]),
        "mkfluid": 0,
        "native_cell_centre_sampling": True,
        "mass_policy": "native rho*dp^3; no mass rescaling",
    }
    sampling_contract = {
        "fluid_boxes": [box],
        "expected_fluid_particles": int(sampling["particle_count"]),
        "continuous_mass_kg": continuous_mass,
        "sampled_mass_kg": discrete_mass,
        "mass_policy": "native rho*dp^3; no mass rescaling",
    }
    cup_low = continuous_low[:]
    # The wall geometry is unchanged and occupies the full fixed cup, while
    # the source box itself is shifted by c on all three closed axes.
    cup_low = [0.0, -0.15, 0.65]
    cup_size = [0.425, 0.30, 0.45]
    runtime_domain = _runtime_domain(definition)
    config = {
        "schema": "core.cfd.v1", "family": "F2", "scope_id": SCOPE_ID,
        "revision_id": "F2_static_full_cup_support_clearance_h2_v1", "case_id": CASE_ID,
        "recipe_id": "F2_static_full_cup_volume_hold_mdbc_h2_v1", "recipe": "mdbc_native",
        "stage": "repair_canary", "split": "qualification_only", "qualification_only": True,
        "parameter": {"name": "initial_volume_q", "q": 0.0, "value_m3": float(fluid["volume_m3"])},
        "dp_m": float(writer["dp_m"]), "cfl": 0.2, "time_max_s": 0.60,
        "output_interval_s": 0.02, "registered_output_interval_s": 0.02,
        "source_definition": str(definition), "physical_case_id": CASE_ID,
        "lineage_group_id": f"{SCOPE_ID}/{REPAIR_ID}/{CASE_ID}",
        "source_label_semantics": "single initial numerical fluid source; not material truth",
        "control_semantics": "fixed cup at zero angle; H2 initial support-clearance repair only",
        "cup": {"low": cup_low, "size": cup_size, "mkbound": 0},
        "wall_bounds": {"xmin": cup_low[0], "xmax": cup_low[0] + cup_size[0],
                        "ymin": cup_low[1], "ymax": cup_low[1] + cup_size[1],
                        "zmin": cup_low[2], "zmax": cup_low[2] + cup_size[2]},
        "closed_faces": list(CLOSED_FACES), "open_faces": ["top"],
        "runtime_domain": runtime_domain,
        "initial_condition": {"q": 0.0, "initial_volume_m3": float(fluid["volume_m3"]),
                               "fluid_source_low_m": continuous_low,
                               "fluid_source_size_m": continuous_size,
                               "support_clearance_m": float(fluid["clearance_m"]),
                               "fill_height_m": continuous_size[2], "mass_rescaling": False},
        "repair_hypothesis": REPAIR_ID, "qualification_claim": "none; one H2 solver canary only", "qualified": False,
    }
    inputs = _input_inventory([
        preflight_path, writer_path, root_review_path, definition, motion,
        generated_xml, generated_motion, bi4, solver, decoder,
        LAB / "scripts/core_cfd.py", LAB / "scripts/f2_static_full_cup_runtime.py",
    ])
    mass_preflight = core_cfd.mass_quality(sampling_contract)
    prepared = {
        "schema": RUNTIME_SCHEMA, "created_at": stamp(), "family": "F2", "scope_id": SCOPE_ID,
        "cell_index": 0, "repair_id": REPAIR_ID, "source_preflight": ref(preflight_path, "H2 CPU/native input preflight"),
        "source_preflight_sha256": digest(preflight_path), "writer_receipt": ref(writer_path, "H2 fresh input receipt"),
        "root_review": ref(root_review_path, "H2 solver-canary root review"),
        "root_review_decision": review["decision"], "config": config, "sampling": sampling_contract,
        "mass_preflight": mass_preflight, "preflight_pass": bool(mass_preflight["mass_gate_pass"]),
        "generated_prefix": str(bi4.with_suffix("")), "source_template": str(definition),
        "source_template_sha256": digest(definition), "inputs": inputs,
        "solver_binary": str(solver), "solver_sha256": digest(solver), "decoder": str(decoder),
        "decoder_sha256": digest(decoder), "solver_arguments": ["-mdbc_noslip:1"],
        "solver_launch_authorized": True, "gpu_launch_authorized": True,
        "job_spec_creation_authorized": True, "queue_mutation_authorized": True,
        "ledger_mutation_authorized": True, "registry_mutation_authorized": False,
        "qualification_claim": "none; one H2 solver canary only", "qualified": False,
        "registry_mutation": 0, "matrix_expansion_authorized": False,
    }
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"runtime prepared output is not fresh: {output}")
    write_json(output / "prepared.json", prepared)
    return prepared


def make_job(*, prepared_path: Path, output: Path, job_id: str, host: str = "ada",
             timeout_seconds: int = 7200) -> dict[str, Any]:
    prepared_path, output = Path(prepared_path).resolve(), Path(output).resolve()
    prepared = load(prepared_path)
    if prepared.get("schema") != RUNTIME_SCHEMA or prepared.get("solver_launch_authorized") is not True:
        raise ValueError("H2 runtime manifest is not solver-authorized")
    if prepared.get("registry_mutation_authorized") is not False:
        raise ValueError("H2 runtime manifest opened registry mutation")
    spec = runtime.make_job(lab=LAB, prepared_path=prepared_path, output=output,
                            job_id=job_id, host=host, timeout_seconds=timeout_seconds,
                            category="static_hold_canary")
    spec.update({"registry_mutation_authorized": False,
                 "matrix_expansion_authorized": False,
                 "qualification_credit": 0,
                 "same_input_retry": False})
    write_json(output, spec)
    return spec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--preflight", type=Path, default=PREFLIGHT)
    p.add_argument("--writer", type=Path, default=WRITER)
    p.add_argument("--root-review", type=Path, default=ROOT_REVIEW)
    p = sub.add_parser("make-job")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--job-id", required=True)
    p.add_argument("--host", default="ada")
    p.add_argument("--timeout", type=int, default=7200)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        value = prepare(preflight_path=args.preflight, writer_path=args.writer,
                        root_review_path=args.root_review, output=args.output)
        print(json.dumps({"schema": value["schema"], "case_id": value["config"]["case_id"],
                          "preflight_pass": value["preflight_pass"], "qualification_claim": value["qualification_claim"]}, ensure_ascii=False))
    else:
        value = make_job(prepared_path=args.prepared, output=args.output, job_id=args.job_id,
                         host=args.host, timeout_seconds=args.timeout)
        print(json.dumps({"job_id": value["job_id"], "host": value["host"],
                          "qualification_claim": value["qualification_claim"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
