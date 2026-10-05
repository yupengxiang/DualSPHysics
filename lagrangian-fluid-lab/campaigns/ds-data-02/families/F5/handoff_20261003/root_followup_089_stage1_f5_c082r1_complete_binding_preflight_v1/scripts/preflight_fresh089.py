#!/usr/bin/env python3
"""Metadata-only fresh089 preflight.

This checks every binding path reached by the three workers, the registered
Root265/Root234 producer identities, and disabled request wiring. It reads
JSON metadata and source text only; it never opens CSV/BI4/H5/array payloads,
launches a worker, or changes a scientific predicate.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path

B = Path(__file__).resolve().parents[1]
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082R1"
GEN = "root-stage1-f5-c082r1-official-void-fill-genuine-gencase-265"
OLDGEN = "root-stage1-f5-c082r1-inward-analytic-bed-genuine-gencase-234"
QA = "root-stage1-f5-c082r1-voidfill-actual-native-initial-qa-286"
COV = "root-stage1-f5-c082r1-voidfill-bed-footprint-audit-287"
DIAG = "root-stage1-f5-c082r1-actual-cohort-yindex-diagnostic-288"
CANDIDATE = {"total_particles": 194427, "fixed_particles": 162005, "moving_particles": 4480, "floating_particles": 0, "fluid_particles": 27942}
OLD = {"total_particles": 194427, "fixed_particles": 158559, "moving_particles": 4210, "floating_particles": 0, "fluid_particles": 31658}

def fail(message: str) -> None:
    raise ValueError(message)

def require(value, message: str) -> None:
    if not value:
        fail(message)

def load_json(path: Path, label: str) -> dict:
    require(path.is_file(), f"{label} missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"{label} is not JSON metadata: {path}: {exc}")
    require(isinstance(value, dict), f"{label} must be a JSON object")
    return value

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            h.update(block)
    return h.hexdigest()

def get_path(obj: dict, dotted: str):
    value = obj
    for key in dotted.split("."):
        require(isinstance(value, dict) and key in value, f"missing binding field {dotted}")
        value = value[key]
    return value

def check_file_ref(ref: dict, path: str, *, sha_required: bool = False) -> None:
    require(isinstance(ref, dict), f"{path} must be an object")
    require(isinstance(ref.get("path"), str) and ref["path"], f"{path}.path missing")
    if sha_required:
        require(isinstance(ref.get("sha256"), str) and len(ref["sha256"]) == 64, f"{path}.sha256 missing")

def check_counts(counts: dict, expected: dict, label: str) -> None:
    actual = {key: counts.get(key) for key in expected}
    require(actual == expected, f"{label} counts mismatch: {actual} != {expected}")

def check_worker_contract(contract: dict, filename: str, binding: dict) -> None:
    spec = contract["workers"][filename]
    for dotted in spec["required_binding_paths"]:
        get_path(binding, dotted)
    require(spec["binding_file"], f"{filename} binding file missing in contract")

def check_request(req: dict, filename: str, expected_attempt: str, binding_name: str, worker_name: str) -> None:
    require(req.get("schema") == "ds02.runner-request.v2", f"{filename} runner schema mismatch")
    require(req.get("attempt_id") == expected_attempt, f"{filename} attempt mismatch")
    require(req.get("execution_allowed") is False and req.get("launch_allowed") is False, f"{filename} is enabled")
    require(req.get("arrays_allowed") is False and req.get("solver_allowed") is False, f"{filename} permits arrays/solver")
    require(req.get("full16_authorized") is False and req.get("full801_authorized") is False, f"{filename} grants long run")
    command = req.get("command")
    require(isinstance(command, list) and len(command) >= 4, f"{filename} command contract missing")
    require("--binding" in command, f"{filename} command binding flag mismatch")
    binding_index = command.index("--binding")
    require(binding_index + 1 < len(command) and command[binding_index + 1].endswith(binding_name), f"{filename} command binding mismatch")
    require(any(str(item).endswith(worker_name) for item in command), f"{filename} command worker mismatch")
    for raw in req.get("input_files", []):
        path = Path(raw)
        if path.resolve().is_relative_to(B) and path.is_file():
            digest = req.get("input_sha256", {}).get(raw)
            require(digest == sha(path), f"{filename} local input SHA mismatch: {path}")

def main() -> None:
    contract = load_json(B / "worker-binding-contract.json", "worker-binding-contract")
    qa = load_json(B / "initial-qa-binding.json", "initial QA binding")
    cov = load_json(B / "central-bed-coverage-binding.json", "coverage binding")
    diag = load_json(B / "fluid-lattice-cohort-diagnostic-binding.json", "diagnostic binding")

    # Every static path the worker reaches is checked before any CSV/array stage.
    check_worker_contract(contract, "initial_qa_worker.py", qa)
    check_worker_contract(contract, "direct_partvtk_initial_mk50_coverage.py", cov)
    check_worker_contract(contract, "diagnose_r1_fluid_lattice_text_rounding.py", diag)

    require(qa.get("schema") == "ds02.f5.c082r1.void-fill.actual-initial-qa-binding.fresh089.v1", "QA binding schema mismatch")
    require("attempt_id" not in qa, "QA binding contains ambiguous top-level attempt_id")
    require(qa.get("qa_attempt_id") == QA and qa.get("gencase_attempt_id") == GEN, "QA/GenCase identities are not separated")
    check_counts(qa["actual_counts"], CANDIDATE, "Root265 candidate")
    require(qa["files"]["gencase_output_root"]["path"].endswith("/" + GEN), "QA output-root field does not bind Root265")
    require(qa["future_output"]["all_future_sha256"] is None, "future QA artifact SHA is prefilled")

    # JSON metadata checks bind the genuine producer receipt/report, but never open
    # its BI4/XML/CSV payloads here.
    candidate_binding_path = Path(qa["files"]["actual_gencase_binding"]["path"])
    candidate_binding = load_json(candidate_binding_path, "Root265 actual binding")
    require(candidate_binding.get("attempt_id") == GEN, "Root265 sidecar attempt mismatch")
    check_counts(candidate_binding["actual_counts"], CANDIDATE, "Root265 sidecar")
    receipt = load_json(Path(qa["files"]["gencase_receipt"]["path"]), "Root265 receipt metadata")
    require(receipt.get("status") == "completed" and receipt.get("returncode") == 0, "Root265 receipt is not completed/zero")
    require(receipt.get("request", {}).get("case_id") == CASE, "Root265 receipt case mismatch")
    require(receipt.get("request", {}).get("attempt_id") == GEN, "Root265 receipt attempt mismatch")
    require(receipt.get("output_root") == qa["files"]["gencase_output_root"]["path"], "Root265 output-root mismatch")
    require(receipt.get("total_particles") == CANDIDATE["total_particles"] and receipt.get("fluid_particles") == CANDIDATE["fluid_particles"], "Root265 receipt counts mismatch")
    report = load_json(Path(qa["files"]["prepared_input_report"]["path"]), "Root265 prepared report metadata")
    require(report.get("actual_total_particles") == CANDIDATE["total_particles"], "Root265 prepared total mismatch")
    check_counts(report.get("generated_xml_particle_counts", {}), {"fixed": CANDIDATE["fixed_particles"], "moving": CANDIDATE["moving_particles"], "floating": CANDIDATE["floating_particles"], "fluid": CANDIDATE["fluid_particles"]}, "Root265 prepared report")

    require(cov.get("schema") == "ds02.f5.c082r1.void-fill.initial-mk50-coverage-binding.fresh089.v1", "coverage binding schema mismatch")
    require(cov.get("attempt_id") == COV and cov.get("gencase_attempt_id") == GEN and cov.get("depends_on_initial_qa_attempt") == QA, "coverage identity/dependency mismatch")
    check_counts(cov["actual_counts"], CANDIDATE, "coverage candidate")
    require(cov["files"]["qa_provenance"]["path"].find("-qa-286/") >= 0, "coverage still points to stale QA266/281 output")
    require(cov["files"]["qa_receipt"]["path"].find("-qa-286/") >= 0, "coverage QA receipt path is stale")

    require(diag.get("schema") == "ds02.f5.c082r1.fluid-lattice-text-rounding-binding.fresh089.v1", "diagnostic binding schema mismatch")
    require(diag.get("diagnostic_attempt_id") == DIAG, "diagnostic attempt mismatch")
    require(diag.get("actual_gencase_attempt_id") == OLDGEN, "diagnostic producer is not old234")
    check_counts(diag["actual_gencase"]["actual_counts"], OLD, "old234 CSV producer")
    check_counts(diag["actual_candidate_gencase"]["actual_counts"], CANDIDATE, "candidate265 sidecar")
    root256 = diag["actual_root256"]
    require(root256["actual_csv_mass_kg"] == 253.26401266320002, "registered Root256 mass value missing/mutated")
    mass_source = root256["actual_csv_mass_source"]
    require(mass_source["report"] == root256["report"] and mass_source["report_sha256"] == root256["report_sha256"], "Root256 mass source report mismatch")
    require(mass_source["field"] == "mass_metadata.actual_csv_mass_kg_from_root246", "Root256 mass source field mismatch")
    root256_report = load_json(Path(root256["report"]), "Root256 diagnostic metadata")
    registered_mass = root256_report.get("mass_metadata", {}).get("actual_csv_mass_kg_from_root246")
    require(registered_mass == root256["actual_csv_mass_kg"], "Root256 mass was not taken from registered metadata")

    requests = [
        ("initial-qa-request.json", QA, "initial-qa-binding.json", "initial_qa_worker.py"),
        ("central-bed-coverage-request.json", COV, "central-bed-coverage-binding.json", "direct_partvtk_initial_mk50_coverage.py"),
        ("fluid-lattice-cohort-diagnostic-request.json", DIAG, "fluid-lattice-cohort-diagnostic-binding.json", "diagnose_r1_fluid_lattice_text_rounding.py"),
    ]
    for name, attempt, binding_name, worker_name in requests:
        check_request(load_json(B / name, name), name, attempt, binding_name, worker_name)

    # Synthetic serialization checks exercise all binding paths without invoking
    # scientific workers. A deliberate count swap must be rejected by this contract.
    for name, binding in (("QA", qa), ("coverage", cov), ("diagnostic", diag)):
        roundtrip = json.loads(json.dumps(binding, sort_keys=True))
        check_worker_contract(contract, {"QA":"initial_qa_worker.py", "coverage":"direct_partvtk_initial_mk50_coverage.py", "diagnostic":"diagnose_r1_fluid_lattice_text_rounding.py"}[name], roundtrip)
    swapped = json.loads(json.dumps(diag))
    swapped["actual_gencase"] = swapped["actual_candidate_gencase"]
    try:
        check_counts(swapped["actual_gencase"]["actual_counts"], OLD, "intentional count-mix negative")
    except ValueError:
        pass
    else:
        fail("synthetic count-mix negative was accepted")

    for worker in ("initial_qa_worker.py", "direct_partvtk_initial_mk50_coverage.py", "diagnose_r1_fluid_lattice_text_rounding.py"):
        worker_source = (B / "workers" / worker).read_text(encoding="utf-8")
        require("fresh089" in worker_source and "validate_binding_contract" in worker_source, f"{worker} lacks fresh089 contract guard")
    report = {
        "schema": "ds02.f5.c082r1.fresh089.binding-contract-preflight-report.v1",
        "status": "metadata_preflight_passed",
        "case_id": CASE,
        "attempts": {"gencase": GEN, "initial_qa": QA, "bed_coverage": COV, "cohort_diagnostic": DIAG},
        "candidate_counts": CANDIDATE,
        "old_csv_producer_counts": OLD,
        "registered_root256_mass_kg": root256["actual_csv_mass_kg"],
        "registered_root256_mass_source_field": mass_source["field"],
        "worker_binding_paths_checked": sum(len(spec["required_binding_paths"]) for spec in contract["workers"].values()),
        "request_contracts_checked": len(requests),
        "synthetic_roundtrip_checked": True,
        "synthetic_count_mix_rejected": True,
        "arrays_opened_by_preflight": False,
        "workers_started_by_preflight": False,
        "scientific_thresholds_changed": False,
        "future_output_sha256": None,
    }
    (B / "binding-contract-preflight-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))

if __name__ == "__main__":
    main()
