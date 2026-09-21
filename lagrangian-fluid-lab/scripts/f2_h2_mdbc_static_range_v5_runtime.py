#!/usr/bin/env python3
"""Hash-bound runtime adapter for the independent F2 H2-v5 candidate.

The v5 materializer deliberately has a CPU/native-preparation schema rather
than the ``core.cfd.v1`` worker schema.  This adapter creates a fresh runtime
view for one explicitly approved cell.  It never edits a prepared cell and
never mutates the campaign registry or ledger.  ``prepare-runtime`` and
``make-job`` are side-effect limited to their requested output files; only
``run`` may invoke the solver through the existing core CFD worker.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import core_cfd

RUNTIME_SCHEMA = "core.f2.h2_mdbc.static_range_v5.runtime_prepared.v1"
JOB_SCHEMA = "core.cfd.job.v1"
ROOT_REVIEW_SCHEMA = "core.root_review.v1"
ADMISSION_SCHEMA = "core.f2.h2_mdbc.static_range_v5.runtime_admission.v1"
CELL_SCHEMA = "core.f2.h2_mdbc.static_range_v5.cell_prepared.v1"
MATRIX_SCHEMA = "core.f2.h2_mdbc.static_range_v5_preparation.v1"
CORE_CFD_SCHEMA = "core.cfd.v1"
FAMILY = "F2"
SCOPE_ID = "F2_H2_mdbc_static_range_qualification_v5"
REVISION_ID = "F2_H2_mdbc_static_range_mdbc_v5_top_layer_lateral_lattice"
TIME_MAX_S = 0.60
OUTPUT_INTERVAL_S = 0.02
DEFAULT_MATRIX = LAB_ROOT / (
    "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5/"
    "prepared-20260920-v5-all/matrix-preparation.json"
)
DEFAULT_CANDIDATE = LAB_ROOT / "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-candidate-v5.json"
DEFAULT_ANCHOR = LAB_ROOT / "campaigns/core-v1/cfd/prepared/F2_H2_mdbc_boundary_repair_canary_v2/prepared.json"
DEFAULT_SOLVER = LAB_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
DEFAULT_DECODER = LAB_ROOT / "campaigns/l1-resume/artifacts/bi4_dump"


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


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


def _resolve(root: Path, value: str | Path) -> Path:
    value = Path(value)
    return (value if value.is_absolute() else root / value).resolve()


def _source_cell(path: Path, index: int) -> tuple[dict[str, Any], Path]:
    path = Path(path).resolve()
    cell = load(path)
    if cell.get("schema") != CELL_SCHEMA:
        raise ValueError("source cell schema is not the v5 CPU preparation schema")
    if int(cell.get("index", -1)) != int(index):
        raise ValueError("source cell index does not match the requested runtime index")
    if cell.get("candidate_id") != "F2_H2_mdbc_static_range_qualification_v5":
        raise ValueError("source cell candidate identity mismatch")
    if cell.get("scope_id") != SCOPE_ID or cell.get("preflight_pass") is not True:
        raise ValueError("source cell is not a passed CPU/native preflight")
    if float(cell.get("time_max_s", -1.0)) != TIME_MAX_S:
        raise ValueError("source cell time window is not the registered 0.60 s canary window")
    if float(cell.get("output_interval_s", -1.0)) != OUTPUT_INTERVAL_S:
        raise ValueError("source cell output cadence is not the registered 0.02 s cadence")
    for key in ("solver_invoked", "gpu_invoked", "queue_mutated", "ledger_mutated", "registry_mutated"):
        if cell.get(key) is not False:
            raise ValueError(f"source cell control closure is not false for {key}")
    if cell.get("sampling", {}).get("mass_policy") != "native rho*dp^3; no mass rescaling":
        raise ValueError("source cell mass policy is not native rho*dp^3 without rescaling")
    if cell.get("mdbc_normal_gate", {}).get("zero_boundary_normals") != 0:
        raise ValueError("source cell has zero mDBC boundary normals")
    return cell, path


def _candidate(candidate_path: Path) -> dict[str, Any]:
    candidate = load(candidate_path)
    if candidate.get("scope_id") != SCOPE_ID or candidate.get("revision_id") != REVISION_ID:
        raise ValueError("candidate scope or revision mismatch")
    if candidate.get("qualification_only") is not True or candidate.get("qualified") is not False:
        raise ValueError("candidate must remain qualification-only and unqualified")
    if candidate.get("T1_numerical") is not False or candidate.get("qualification_claim", "").startswith("none") is False:
        raise ValueError("candidate qualification controls are not closed")
    for key in ("central_ledger_mutation", "registry_mutation", "gpu_launch_by_subagent"):
        if candidate.get(key) not in (0, False):
            raise ValueError(f"candidate has an unauthorized {key}")
    if candidate.get("physical_contract", {}).get("boundary_method") != 2:
        raise ValueError("candidate does not bind mDBC Boundary=2")
    normal = candidate.get("physical_contract", {}).get("mdbc_normals", {})
    if normal.get("normal_construction_layers_vdp") != -0.5 or normal.get("normal_search_distance_h") != 3.0 or normal.get("svshapes") is not True:
        raise ValueError("candidate mDBC normal contract mismatch")
    if candidate.get("physical_contract", {}).get("runtime_window", {}).get("time_max_s") != TIME_MAX_S:
        raise ValueError("candidate runtime window mismatch")
    return candidate


def _root_review(path: Path, index: int) -> tuple[dict[str, Any], Path]:
    path = Path(path).resolve()
    review = load(path)
    if review.get("schema") != ROOT_REVIEW_SCHEMA:
        raise ValueError("root review schema mismatch")
    if review.get("scope_id") != SCOPE_ID:
        raise ValueError("root review scope mismatch")
    if review.get("decision") not in {"approved_for_runtime_smoke", "approved_for_8_cell_canary"}:
        raise ValueError("root review does not authorize runtime execution")
    if int(index) not in {int(x) for x in review.get("authorized_cell_indices", [])}:
        raise ValueError("requested cell is not root-authorized")
    auth = review.get("authorization", {})
    for key in ("solver_launch", "gpu_launch", "job_spec_creation", "queue_mutation"):
        if auth.get(key) is not True:
            raise ValueError(f"root review does not authorize {key}")
    for key in ("ledger_mutation", "registry_mutation", "material_training", "model_training"):
        if auth.get(key) is not False:
            raise ValueError(f"root review does not prohibit {key}")
    if review.get("qualification_claim") != "none":
        raise ValueError("runtime review must carry qualification_claim=none")
    return review, path


def _admission(path: Path, *, source: Path, candidate: Path, matrix: Path, index: int) -> dict[str, Any]:
    admission = load(path)
    if admission.get("schema") != ADMISSION_SCHEMA or admission.get("scope_id") != SCOPE_ID:
        raise ValueError("v5 runtime admission schema/scope mismatch")
    if admission.get("decision") != "root_review_required_for_one_canary":
        raise ValueError("unexpected v5 admission decision")
    if int(index) not in {int(x) for x in admission.get("authorized_cell_indices", [])}:
        raise ValueError("admission does not authorize requested cell")
    for key, actual in (("source_preparation", source), ("candidate_card", candidate), ("matrix_report", matrix)):
        item = admission.get(key)
        if not isinstance(item, dict) or Path(item.get("path", "")).resolve() != actual.resolve() or item.get("sha256") != digest(actual):
            raise ValueError(f"admission {key} is not bound to the requested input")
    if admission.get("qualification_claim") != "none" or admission.get("registry_mutation") != 0:
        raise ValueError("admission qualification or registry controls are open")
    return admission


def _fluid_boxes(source: dict[str, Any]) -> list[dict[str, Any]]:
    boxes = []
    for box in source["sampling"]["fluid_boxes"]:
        boxes.append({
            "low": list(box["continuous_low_m"]),
            "size": list(box["continuous_size_m"]),
            "mkfluid": int(box["mkfluid"]),
            "continuous_low_m": list(box["continuous_low_m"]),
            "continuous_size_m": list(box["continuous_size_m"]),
            "first_center_m": list(box["first_center_m"]),
            "draw_size_m": list(box["draw_size_m"]),
            "counts": list(box["counts"]),
            "particle_count": int(box["particle_count"]),
            "continuous_mass_kg": float(box["continuous_mass_kg"]),
            "discrete_mass_kg": float(box["discrete_mass_kg"]),
            "native_cell_centre_sampling": True,
        })
    return boxes


def _sampling(source: dict[str, Any]) -> dict[str, Any]:
    raw = source["sampling"]
    return {
        "fluid_boxes": _fluid_boxes(source),
        "expected_fluid_particles": int(raw["expected_fluid_particles"]),
        "continuous_mass_kg": float(raw["continuous_mass_kg"]),
        "sampled_mass_kg": float(raw["sampled_mass_kg"]),
        "mass_policy": "native rho*dp^3, no mass rescaling",
    }


def _input_inventory(paths: list[Path]) -> dict[str, str]:
    inventory: dict[str, str] = {}
    for path in paths:
        path = Path(path).resolve()
        if path.is_file():
            inventory[str(path)] = digest(path)
    return dict(sorted(inventory.items()))


def materialize_runtime_prepared(*, lab: Path, source_prepared: Path, candidate: Path,
                                 matrix: Path, admission: Path, root_review: Path,
                                 anchor: Path, output: Path, cell_index: int) -> dict[str, Any]:
    lab = Path(lab).resolve()
    source, source_path = _source_cell(source_prepared, cell_index)
    candidate_payload = _candidate(candidate)
    matrix_payload = load(matrix)
    if matrix_payload.get("schema") != MATRIX_SCHEMA or matrix_payload.get("candidate_id") != candidate_payload.get("candidate_id"):
        raise ValueError("v5 matrix report schema/candidate mismatch")
    matrix_rows = matrix_payload.get("cells", [])
    row = next((item for item in matrix_rows if int(item.get("index", -1)) == int(cell_index)), None)
    if not isinstance(row, dict) or row.get("preflight_pass") is not True or row.get("qualification_credit") is not False:
        raise ValueError("requested matrix row is not a passed, zero-credit v5 row")
    _admission(admission, source=source_path, candidate=candidate, matrix=matrix, index=cell_index)
    review, review_path = _root_review(root_review, cell_index)
    anchor = Path(anchor).resolve()
    anchor_payload = load(anchor)
    if anchor_payload.get("schema") != CORE_CFD_SCHEMA or anchor_payload.get("config", {}).get("family") != FAMILY:
        raise ValueError("anchor is not a core F2 CFD prepared input")
    for key in ("solver_binary", "decoder", "solver_sha256", "decoder_sha256"):
        if key not in anchor_payload:
            raise ValueError(f"anchor missing {key}")
    solver = Path(anchor_payload["solver_binary"]).resolve()
    decoder = Path(anchor_payload["decoder"]).resolve()
    if not solver.is_file() or not decoder.is_file():
        raise FileNotFoundError("pinned solver or decoder missing")
    if digest(solver) != anchor_payload["solver_sha256"] or digest(decoder) != anchor_payload["decoder_sha256"]:
        raise ValueError("anchor native tool hash mismatch")
    config = deepcopy(anchor_payload["config"])
    config.update({
        "schema": CORE_CFD_SCHEMA,
        "family": FAMILY,
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "case_id": str(source["case_id"]),
        "recipe_id": "F2_H2_mdbc_static_range_v5_runtime_v1",
        "recipe": "mdbc_native",
        "stage": "qualification",
        "parameter": {"name": "initial_liquid_volume_q", "q": float(source["q"]),
                       "value_m3": float(source["sampling"]["continuous_volume_m3"])},
        "dp_m": float(source["dp_m"]),
        "time_max_s": TIME_MAX_S,
        "output_interval_s": OUTPUT_INTERVAL_S,
        "registered_output_interval_s": OUTPUT_INTERVAL_S,
        "source_definition": str(source["definition_audit"]["definition"]),
        "physical_case_id": str(source["case_id"]),
        "lineage_group_id": f"{SCOPE_ID}/{source['case_id']}",
        "fluid_boxes": _fluid_boxes(source),
        "qualification_claim": "none; root-approved solver canary only",
        "qualified": False,
        "boundary_method": 2,
        "physical_geometry_changed": False,
    })
    config["cup"] = deepcopy(candidate_payload["physical_contract"]["cup"])
    config["receiver"] = deepcopy(candidate_payload["physical_contract"]["receiver"])
    config["tray"] = deepcopy(candidate_payload["physical_contract"]["tray"])
    config["runtime_domain"] = deepcopy(candidate_payload["physical_contract"]["runtime_domain"])
    sampling = _sampling(source)
    mass = core_cfd.mass_quality(sampling)
    if not mass["mass_gate_pass"]:
        raise ValueError("v5 runtime sampling mass gate failed")
    generated_prefix = Path(source["generated_prefix"]).resolve()
    if not generated_prefix.with_suffix(".xml").is_file() or not generated_prefix.with_suffix(".bi4").is_file():
        raise FileNotFoundError("v5 native generated prefix is incomplete")
    input_paths = [Path(__file__), source_path, candidate, matrix, admission, anchor,
                   review_path, generated_prefix.with_suffix(".xml"), generated_prefix.with_suffix(".bi4"),
                   generated_prefix.with_suffix(".out"), Path(source["definition_audit"]["definition"]),
                   solver, decoder]
    for item in source.get("hash_closure", []):
        if isinstance(item, dict) and isinstance(item.get("path"), str):
            input_paths.append(Path(item["path"]))
    prepared = {
        "schema": RUNTIME_SCHEMA,
        "created_at": stamp(),
        "family": FAMILY,
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "cell_index": int(cell_index),
        "case_id": str(source["case_id"]),
        "source_prepared": ref(source_path, "v5 CPU/native prepared cell"),
        "candidate_card": ref(candidate, "v5 candidate card"),
        "matrix_report": ref(matrix, "v5 fixed-denominator matrix report"),
        "admission": ref(admission, "v5 runtime admission"),
        "root_review": ref(review_path, "root runtime canary review"),
        "anchor_prepared": ref(anchor, "H2 mDBC anchor prepared input"),
        "config": config,
        "sampling": sampling,
        "mass_preflight": mass,
        "preflight_pass": True,
        "generated_prefix": str(generated_prefix),
        "source_template": str(source["definition_audit"]["source_definition"]),
        "source_template_sha256": source["definition_audit"]["source_definition_sha256"],
        "solver_binary": str(solver),
        "solver_sha256": digest(solver),
        "decoder": str(decoder),
        "decoder_sha256": digest(decoder),
        "solver_arguments": list(anchor_payload.get("solver_arguments", ["-mdbc_noslip:1"])),
        "inputs": _input_inventory(input_paths),
        "solver_launch_authorized": True,
        "gpu_launch_authorized": True,
        "job_spec_creation_authorized": True,
        "queue_mutation_authorized": True,
        "ledger_mutation_authorized": False,
        "registry_mutation_authorized": False,
        "qualification_claim": "none; root-approved solver canary only",
        "qualified": False,
    }
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"runtime output is not fresh: {output}")
    write_json(output / "prepared.json", prepared)
    return prepared


def make_job(*, lab: Path, prepared_path: Path, output: Path, job_id: str,
             host: str = "ada", timeout_seconds: int = 3600) -> dict[str, Any]:
    lab, prepared_path, output = Path(lab).resolve(), Path(prepared_path).resolve(), Path(output).resolve()
    prepared = load(prepared_path)
    if prepared.get("schema") != RUNTIME_SCHEMA or prepared.get("preflight_pass") is not True:
        raise ValueError("runtime prepared schema or preflight mismatch")
    for key in ("solver_launch_authorized", "gpu_launch_authorized", "job_spec_creation_authorized", "queue_mutation_authorized"):
        if prepared.get(key) is not True:
            raise ValueError(f"runtime prepared input does not authorize {key}")
    if prepared.get("registry_mutation_authorized") is not False:
        raise ValueError("runtime prepared input permits registry mutation")
    script = (lab / "scripts/f2_h2_mdbc_static_range_v5_runtime.py").resolve()
    cfd_script = (lab / "scripts/core_cfd.py").resolve()
    input_files = [{"path": str(prepared_path), "sha256": digest(prepared_path)}]
    for path, sha in sorted(prepared.get("inputs", {}).items()):
        if not any(item["path"] == path for item in input_files):
            input_files.append({"path": path, "sha256": sha})
    for path in (script, cfd_script):
        item = {"path": str(path), "sha256": digest(path)}
        if not any(existing["path"] == item["path"] for existing in input_files):
            input_files.append(item)
    spec = {
        "schema": JOB_SCHEMA,
        "job_id": job_id,
        "logical_id": job_id,
        "attempt_role": "root_approved_f2_h2_v5_solver_canary",
        "category": "qualification_canary",
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
        "prepared_case_id": prepared["case_id"],
        "prepared_sha256": digest(prepared_path),
        "root_review_sha256": prepared["root_review"]["sha256"],
        "registered_window_s": TIME_MAX_S,
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
    if prepared.get("ledger_mutation_authorized") is not False or prepared.get("registry_mutation_authorized") is not False:
        raise ValueError("runtime worker cannot run with ledger or registry mutation enabled")
    result = core_cfd.run(prepared_path, lab, output)
    result.update({"family": FAMILY, "scope_id": SCOPE_ID, "cell_index": int(prepared["cell_index"]),
                   "runtime_prepared_sha256": digest(prepared_path),
                   "qualification_claim": "none; solver execution receipt only", "qualified": False,
                   "registry_mutation": 0})
    write_json(output / "result.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare-runtime")
    p.add_argument("--source-prepared", type=Path, required=True)
    p.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    p.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    p.add_argument("--admission", type=Path, required=True)
    p.add_argument("--root-review", type=Path, required=True)
    p.add_argument("--anchor", type=Path, default=DEFAULT_ANCHOR)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--cell-index", type=int, required=True)
    p = sub.add_parser("make-job")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--job-id", required=True)
    p.add_argument("--host", default="ada")
    p.add_argument("--timeout", type=int, default=3600)
    p = sub.add_parser("run")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "prepare-runtime":
        value = materialize_runtime_prepared(lab=args.lab_root, source_prepared=args.source_prepared,
                                             candidate=args.candidate, matrix=args.matrix, admission=args.admission,
                                             root_review=args.root_review, anchor=args.anchor, output=args.output,
                                             cell_index=args.cell_index)
        print(json.dumps({"schema": value["schema"], "case_id": value["case_id"],
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
