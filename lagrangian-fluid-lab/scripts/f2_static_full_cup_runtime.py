#!/usr/bin/env python3
"""Runtime adapter for the F2 static full-cup qualification candidate.

The v4 matrix preparation is intentionally CPU-only and has a different
schema from :mod:`scripts.core_cfd`.  This module creates a separate,
hash-bound runtime view for an explicitly root-approved cell and then delegates
the actual solver/conversion/audit implementation to ``core_cfd.run``.  The
source preparation is never edited in place.  Preparation and job creation do
not invoke a solver, CUDA, queue or ledger; only the ``run`` subcommand does.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import core_cfd


RUNTIME_SCHEMA = "core.f2.static_full_cup.runtime_prepared.v1"
JOB_SCHEMA = "core.cfd.job.v1"
ROOT_REVIEW_SCHEMA = "core.root_review.v1"
PREPARATION_SCHEMA = "core.f2.static_full_cup.matrix_cell_prepared.v1"
ADMISSION_SCHEMA = "core.f2.static_full_cup.qualification_admission.v1"
FAMILY = "F2"
SCOPE_ID = "F2_static_full_cup_volume_hold_x_v1"
TIME_MAX_S = 0.60
REGISTERED_OUTPUT_INTERVAL_S = 0.02
DEFAULT_SOLVER_RELATIVE = "vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
DEFAULT_DECODER_RELATIVE = "campaigns/l1-resume/artifacts/bi4_dump"
CLOSED_FACES = ["bottom", "left", "right", "front", "back"]


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    partial.replace(path)


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": digest(path), "bytes": path.stat().st_size, "role": role}


def verify_ref(item: dict[str, Any], label: str) -> Path:
    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
        raise ValueError(f"{label} has no path")
    path = Path(item["path"]).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    if item.get("sha256") != digest(path):
        raise ValueError(f"{label} hash mismatch: {path}")
    if item.get("bytes") is not None and int(item["bytes"]) != path.stat().st_size:
        raise ValueError(f"{label} byte count mismatch: {path}")
    return path


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _path(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else root / path).resolve()


def _root_review(review_path: Path, *, index: int) -> tuple[dict[str, Any], Path]:
    review_path = Path(review_path).resolve()
    review = load(review_path)
    if review.get("schema") != ROOT_REVIEW_SCHEMA:
        raise ValueError("root review schema mismatch")
    if review.get("decision") not in {"approved_for_runtime_smoke", "approved_for_8_cell_canary"}:
        raise ValueError("root review does not authorize a runtime smoke/canary")
    if review.get("scope_id") != SCOPE_ID:
        raise ValueError("root review scope mismatch")
    authorized = {int(value) for value in review.get("authorized_cell_indices", [])}
    if index not in authorized:
        raise ValueError(f"cell {index} is not authorized by root review")
    controls = review.get("authorization", {})
    for key in ("solver_launch", "gpu_launch", "job_spec_creation", "queue_mutation", "ledger_mutation"):
        if controls.get(key) is not True:
            raise ValueError(f"root review does not authorize {key}")
    if controls.get("registry_mutation") is not False:
        raise ValueError("runtime review must prohibit registry mutation")
    if review.get("qualification_claim") != "none":
        raise ValueError("runtime review must carry qualification_claim=none")
    return review, review_path


def _source_cell(path: Path, *, index: int) -> tuple[dict[str, Any], Path]:
    path = Path(path).resolve()
    prepared = load(path)
    if prepared.get("schema") != PREPARATION_SCHEMA:
        raise ValueError("source cell is not the v4 CPU preparation schema")
    if int(prepared.get("index", -1)) != int(index):
        raise ValueError("source cell index mismatch")
    if prepared.get("scope_id") != SCOPE_ID or prepared.get("preflight_pass") is not True:
        raise ValueError("source cell is not an approved v4 preflight")
    for key in ("solver_invoked", "gpu_invoked", "queue_mutated", "ledger_mutated", "registry_mutated", "mass_rescaling"):
        if prepared.get(key) is not False:
            raise ValueError(f"source cell execution control is not closed: {key}")
    return prepared, path


def _cup(source: dict[str, Any], candidate: dict[str, Any]) -> tuple[list[float], list[float]]:
    physical = candidate.get("physical_contract", {})
    cup = physical.get("cup", {})
    low = [float(x) for x in cup.get("low_m", [])]
    size = [float(x) for x in cup.get("size_m", [])]
    if len(low) != 3 or len(size) != 3 or any(x <= 0 for x in size):
        raise ValueError("candidate cup geometry is invalid")
    expected = float(source["initial_fill_height_m"])
    if expected <= 0 or expected > size[2]:
        raise ValueError("source fill height is outside cup")
    return low, size


def _sampling(source: dict[str, Any], low: list[float], size: list[float]) -> dict[str, Any]:
    native = source.get("sampling", {})
    continuous_volume = float(source["initial_volume_m3"])
    discrete_mass = float(native["discrete_mass_kg"])
    box = {
        "continuous_low_m": [low[0], low[1], low[2]],
        "continuous_size_m": [size[0], size[1], float(source["initial_fill_height_m"])],
        "first_center_m": list(native["first_center_m"]),
        "draw_size_m": list(native["draw_size_m"]),
        "counts": list(native["counts"]),
        "particle_count": int(native["particle_count"]),
        "continuous_mass_kg": continuous_volume * 1000.0,
        "discrete_mass_kg": discrete_mass,
        "mkfluid": 0,
        "native_cell_centre_sampling": True,
    }
    return {
        "fluid_boxes": [box],
        "expected_fluid_particles": int(native["particle_count"]),
        "continuous_mass_kg": continuous_volume * 1000.0,
        "sampled_mass_kg": discrete_mass,
        "mass_policy": "native rho*dp^3; no mass rescaling",
    }


def _input_inventory(source_path: Path, source: dict[str, Any], lab: Path,
                     solver: Path, decoder: Path, *bound_files: Path) -> dict[str, str]:
    paths: set[Path] = {source_path, solver, decoder, *(Path(item).resolve() for item in bound_files)}
    closure = source.get("hash_closure", [])
    for item in closure:
        if isinstance(item, dict) and isinstance(item.get("path"), str):
            paths.add(Path(item["path"]).resolve())
    # Keep the full generated closure available to a remote worker.  This is
    # an input copy only; no source file is rewritten by the adapter.
    for item in source_path.parent.rglob("*"):
        if item.is_file() and item.name != "prepared.json":
            paths.add(item.resolve())
    result: dict[str, str] = {}
    for path in sorted(paths):
        if not path.is_file():
            raise FileNotFoundError(path)
        result[str(path)] = digest(path)
    return result


def materialize_runtime_prepared(*, lab: Path, source_prepared: Path, candidate_card: Path,
                                 admission: Path, root_review: Path, output: Path,
                                 cell_index: int) -> dict[str, Any]:
    """Create one independent runtime view after a root-approved review."""
    lab, source_prepared, candidate_card, admission, output = map(
        Path, (lab, source_prepared, candidate_card, admission, output))
    source, source_path = _source_cell(source_prepared, index=cell_index)
    review, review_path = _root_review(root_review, index=cell_index)
    admission_payload = load(admission)
    if admission_payload.get("schema") != ADMISSION_SCHEMA:
        raise ValueError("admission contract schema mismatch")
    if admission_payload.get("scope_id") != SCOPE_ID:
        raise ValueError("admission contract scope mismatch")
    candidate = load(candidate_card)
    if candidate.get("scope_id") != SCOPE_ID or candidate.get("qualification_only") is not True:
        raise ValueError("candidate card is not qualification-only")
    source_ref = admission_payload.get("source_preparation", {})
    if source_ref.get("sha256") != digest(Path(source_ref["path"])):
        raise ValueError("admission source preparation hash mismatch")
    preparation_report = source_path.parents[2] / "matrix-preparation.json"
    if Path(source_ref["path"]).resolve() != preparation_report.resolve():
        raise ValueError("source cell is not under the admitted v4 preparation")
    low, size = _cup(source, candidate)
    solver = _path(lab, DEFAULT_SOLVER_RELATIVE)
    decoder = _path(lab, DEFAULT_DECODER_RELATIVE)
    if not solver.is_file() or not decoder.is_file():
        raise FileNotFoundError("pinned solver or decoder missing")
    sampling = _sampling(source, low, size)
    wall_low = low
    wall_high = [low[i] + size[i] for i in range(3)]
    runtime_domain = candidate["physical_contract"]["runtime_domain"]
    q = float(source["q"])
    case_id = str(source["case_id"])
    config = {
        "schema": "core.cfd.v1",
        "family": FAMILY,
        "scope_id": SCOPE_ID,
        "revision_id": "F2_static_full_cup_volume_hold_runtime_v1",
        "case_id": case_id,
        "recipe_id": "F2_static_full_cup_volume_hold_dbc_v1",
        "recipe": "native_dbc",
        "stage": "qualification",
        "split": "qualification_only",
        "qualification_only": True,
        "parameter": {"name": "initial_volume_q", "q": q, "value_m3": float(source["initial_volume_m3"])},
        "dp_m": float(source["dp_m"]),
        "cfl": 0.2,
        "time_max_s": float(source["time_max_s"]),
        "output_interval_s": float(source["output_interval_s"]),
        "registered_output_interval_s": float(source.get("registered_output_interval_s", REGISTERED_OUTPUT_INTERVAL_S)),
        "source_definition": str(source.get("definition_audit", {}).get("source_definition", "")),
        "physical_case_id": case_id,
        "lineage_group_id": f"{SCOPE_ID}/{case_id}",
        "source_label_semantics": "single initial numerical fluid source; not material truth",
        "control_semantics": "fixed cup at zero angle; static hold only",
        "cup": {"low": low, "size": size, "mkbound": 0},
        "wall_bounds": {"xmin": wall_low[0], "xmax": wall_high[0], "ymin": wall_low[1],
                        "ymax": wall_high[1], "zmin": wall_low[2], "zmax": wall_high[2]},
        "closed_faces": list(CLOSED_FACES),
        "open_faces": ["top"],
        "runtime_domain": runtime_domain,
        "initial_condition": {"q": q, "initial_volume_m3": float(source["initial_volume_m3"]),
                               "fill_height_m": float(source["initial_fill_height_m"]),
                               "mass_rescaling": False},
        "qualification_claim": "none; root-approved solver canary only",
        "qualified": False,
    }
    inputs = _input_inventory(source_path, source, lab, solver, decoder,
                              candidate_card, admission, review_path)
    prepared = {
        "schema": RUNTIME_SCHEMA,
        "created_at": stamp(),
        "family": FAMILY,
        "scope_id": SCOPE_ID,
        "cell_index": int(cell_index),
        "source_prepared": ref(source_path, "v4 CPU cell preparation"),
        "source_prepared_sha256": digest(source_path),
        "source_preparation_report": str(preparation_report.resolve()),
        "candidate_card": ref(candidate_card, "15-cell candidate card"),
        "admission_contract": ref(admission, "F2 candidate admission contract"),
        "root_review": ref(review_path, "root solver-canary review"),
        "root_review_decision": review["decision"],
        "config": config,
        "sampling": sampling,
        "mass_preflight": core_cfd.mass_quality(sampling),
        "preflight_pass": bool(core_cfd.mass_quality(sampling)["mass_gate_pass"]),
        "generated_prefix": str(source["generated_prefix"]),
        "source_template": str(source.get("definition_audit", {}).get("source_definition", "")),
        "source_template_sha256": source.get("definition_audit", {}).get("source_definition_sha256"),
        "inputs": inputs,
        "solver_binary": str(solver),
        "solver_sha256": digest(solver),
        "decoder": str(decoder),
        "decoder_sha256": digest(decoder),
        "solver_arguments": [],
        "solver_launch_authorized": True,
        "gpu_launch_authorized": True,
        "job_spec_creation_authorized": True,
        "queue_mutation_authorized": True,
        "ledger_mutation_authorized": True,
        "registry_mutation_authorized": False,
        "qualification_claim": "none; root-approved solver canary only",
        "qualified": False,
    }
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"runtime output is not fresh: {output}")
    write_json(output / "prepared.json", prepared)
    return prepared


def make_job(*, lab: Path, prepared_path: Path, output: Path, job_id: str,
             category: str = "f2_static_full_cup_static_hold_canary",
             timeout_seconds: int = 7200, host: str = "ada") -> dict[str, Any]:
    prepared_path, lab, output = Path(prepared_path).resolve(), Path(lab).resolve(), Path(output).resolve()
    prepared = load(prepared_path)
    if prepared.get("schema") != RUNTIME_SCHEMA or prepared.get("solver_launch_authorized") is not True:
        raise ValueError("runtime prepared input is not root-authorized")
    if prepared.get("job_spec_creation_authorized") is not True or prepared.get("registry_mutation_authorized") is not False:
        raise ValueError("runtime prepared job controls are not closed")
    solver = Path(prepared["solver_binary"]).resolve()
    decoder = Path(prepared["decoder"]).resolve()
    script = (lab / "scripts/f2_static_full_cup_runtime.py").resolve()
    cfd = (lab / "scripts/core_cfd.py").resolve()
    input_files = [{"path": str(prepared_path), "sha256": digest(prepared_path)}]
    for path, sha in sorted(prepared.get("inputs", {}).items()):
        if not any(item["path"] == path for item in input_files):
            input_files.append({"path": path, "sha256": sha})
    for path in (solver, decoder, script, cfd):
        item = {"path": str(path), "sha256": digest(path)}
        if not any(existing["path"] == item["path"] for existing in input_files):
            input_files.append(item)
    spec = {
        "schema": JOB_SCHEMA,
        "job_id": job_id,
        "logical_id": job_id,
        "attempt_role": "root_approved_f2_static_full_cup_solver_canary",
        "category": category,
        "host": host,
        "source_lab": str(lab),
        "cwd": str(lab),
        "argv": [str(lab / ".venv/bin/python"), str(script), "--lab-root", str(lab),
                 "run", "--prepared", str(prepared_path), "--output", "{attempt_dir}/product"],
        "required_outputs": ["product/result.json", "product/trajectory.h5", "product/audit.json",
                              "product/prepared.json", "product/worker-status.json"],
        "resources": {"cpu_cores": 2, "ram_mib": 20480, "gpu_peak_mib": 8192, "io_weight": 1},
        "timeout_seconds": int(timeout_seconds),
        "depends_on": [],
        "qualification_claim": "none",
        "qualification_only": True,
        "family": FAMILY,
        "scope_id": SCOPE_ID,
        "cell_index": int(prepared["cell_index"]),
        "prepared_case_id": prepared["config"]["case_id"],
        "prepared_sha256": digest(prepared_path),
        "root_review_sha256": prepared["root_review"]["sha256"],
        "registered_window_s": float(prepared["config"]["time_max_s"]),
        "worker_contract": "core_runtime worker; scheduler supplies one CUDA UUID and solver uses -gpu:0; output is attempt_dir/product",
        "input_files": input_files,
    }
    write_json(output, spec)
    return spec


def run(*, lab: Path, prepared_path: Path, output: Path) -> dict[str, Any]:
    prepared_path, lab, output = Path(prepared_path).resolve(), Path(lab).resolve(), Path(output).resolve()
    prepared = load(prepared_path)
    if prepared.get("schema") != RUNTIME_SCHEMA or prepared.get("solver_launch_authorized") is not True:
        raise ValueError("runtime solver launch is not authorized")
    result = core_cfd.run(prepared_path, lab, output)
    source_prepared_sha256 = prepared.get("source_prepared_sha256", prepared.get("source_preflight_sha256"))
    if not source_prepared_sha256:
        raise ValueError("runtime manifest has no source preparation/preflight hash")
    result.update({
        "family": FAMILY,
        "scope_id": SCOPE_ID,
        "cell_index": int(prepared["cell_index"]),
        "source_prepared_sha256": source_prepared_sha256,
        "runtime_prepared_sha256": digest(prepared_path),
        "root_review_sha256": prepared["root_review"]["sha256"],
        "qualification_claim": "none; solver execution receipt only",
        "qualified": False,
        "registry_mutation": 0,
    })
    write_json(output / "result.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare-runtime")
    p.add_argument("--source-prepared", type=Path, required=True)
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--admission", type=Path, required=True)
    p.add_argument("--root-review", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--cell-index", type=int, required=True)
    p = sub.add_parser("make-job")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--job-id", required=True)
    p.add_argument("--host", default="ada")
    p.add_argument("--timeout", type=int, default=7200)
    p = sub.add_parser("run")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "prepare-runtime":
        value = materialize_runtime_prepared(lab=args.lab_root, source_prepared=args.source_prepared,
                                             candidate_card=args.candidate, admission=args.admission,
                                             root_review=args.root_review, output=args.output,
                                             cell_index=args.cell_index)
        print(json.dumps({"schema": value["schema"], "cell_index": value["cell_index"],
                          "preflight_pass": value["preflight_pass"], "qualification_claim": value["qualification_claim"]}, indent=2))
    elif args.command == "make-job":
        value = make_job(lab=args.lab_root, prepared_path=args.prepared, output=args.output,
                         job_id=args.job_id, host=args.host, timeout_seconds=args.timeout)
        print(json.dumps({"job_id": value["job_id"], "cell_index": value["cell_index"],
                          "host": value["host"], "input_count": len(value["input_files"])}, indent=2))
    else:
        value = run(lab=args.lab_root, prepared_path=args.prepared, output=args.output)
        print(json.dumps({"execution_status": value.get("execution_status"),
                          "hard_integrity_pass": value.get("hard_integrity_pass"),
                          "qualified": value.get("qualified"),
                          "qualification_claim": value.get("qualification_claim")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
