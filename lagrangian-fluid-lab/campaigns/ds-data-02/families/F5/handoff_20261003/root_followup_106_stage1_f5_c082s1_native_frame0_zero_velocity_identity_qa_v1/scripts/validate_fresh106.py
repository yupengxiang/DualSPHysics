#!/usr/bin/env python3
"""Static metadata and disabled-request validator for F5 fresh106.

This validator opens only package source files and JSON/XML/text metadata plus
the already completed producer receipts/reports.  It refuses to hash or read
BI4, CSV, H5, VTK or motion DAT payloads and never submits a task.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


PKG = Path(__file__).resolve().parents[1]
DATA_CASE = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1")
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
SCIENCE_SUFFIXES = {".bi4", ".csv", ".h5", ".hdf5", ".vtk", ".vtu", ".npy", ".npz", ".dat"}
HASHABLE_SUFFIXES = {".json", ".py", ".xml", ".md", ".txt", ".log"}
CANDIDATES = ("A080", "A120")
COUNTS = {"dimension": 3, "fixed": 158559, "floating": 0, "fluid": 31658, "moving": 4210, "total": 194427}


def require(value: Any, message: str) -> None:
    if not value:
        raise ValueError(message)


def load_json(path: Path) -> dict[str, Any]:
    require(path.suffix.lower() == ".json", f"JSON required: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def sha(path: Path) -> str:
    require(path.suffix.lower() in HASHABLE_SUFFIXES, f"validator cannot hash science payload: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check_worker_source() -> dict[str, Any]:
    worker = PKG / "workers/native_frame0_zero_velocity_identity_audit.py"
    tree = ast.parse(worker.read_text(encoding="utf-8"), filename=str(worker))
    source = worker.read_text(encoding="utf-8")
    require("Part_0000.bi4" in source, "worker does not bind Part_0000.bi4")
    require("PartVTK" in source and "subprocess.run" in source, "worker does not use official PartVTK")
    require("gencase_csv_velocity_not_substituted" in source, "worker velocity provenance guard missing")
    require("source_defined_initial_velocity" in source, "source-defined velocity guard missing")
    require("np.arange(expected_total)" in source, "consecutive native Idp guard missing")
    require("native_bed_mk" in source and "Mk" in source, "native Type/Mk identity guard missing")
    require("solver" not in {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
                             and node.id in {"launch_solver", "run_solver"}},
            "worker contains an unexpected solver launcher")
    return {
        "worker_path": str(worker),
        "worker_sha256": sha(worker),
        "ast_parse": True,
        "official_partvtk_bound": True,
        "native_frame0_bi4_bound": True,
        "gencase_velocity_not_used": True,
        "science_payloads_read_or_hashed_by_source_validator": False,
    }


def check_xml(path: Path, expected_sha: str) -> None:
    require(path.is_file(), f"generated XML missing: {path}")
    require(sha(path) == expected_sha, f"generated XML SHA mismatch: {path}")
    root = ET.parse(path).getroot()
    require(root.tag == "case", f"generated XML root mismatch: {path}")
    data2d = root.find("./execution/constants/data2d")
    require(data2d is not None and str(data2d.get("value", "")).lower() == "false",
            f"generated XML is not 3-D: {path}")


def check_candidate(candidate: str, worker_info: dict[str, Any]) -> dict[str, Any]:
    req_path = PKG / "requests" / f"{candidate}-native-frame0-zero-velocity-qa-request.json"
    binding_path = PKG / "bindings" / f"{candidate}-native-frame0-binding.json"
    req = load_json(req_path)
    binding = load_json(binding_path)
    require(req.get("schema") == "ds02.runner-request.v2", f"{candidate}: request schema")
    require(req.get("kind") == "cpu" and req.get("cpu_task_kind") == "audit", f"{candidate}: CPU audit kind")
    for key in ("disabled", "launch", "launch_allowed", "execution_allowed", "solver_allowed",
                "conversion_allowed", "source_only", "arrays_allowed", "array_edit_allowed"):
        expected = key in {"disabled", "source_only"}
        require(req.get(key) is expected, f"{candidate}: request flag {key}")
    require(req.get("launch_owner") == "root", f"{candidate}: launch owner")
    require(req.get("full801_authorized") is False and req.get("q_n_granted") is False,
            f"{candidate}: qualification/production gate")
    require(req.get("independent_case_count_increment") == 0, f"{candidate}: case count")
    require(req.get("future_output_hashes") and all(value is None for value in req["future_output_hashes"].values()),
            f"{candidate}: future hash is not null")
    require(req.get("future_product_paths") and all(value is None for value in req["future_product_paths"].values()),
            f"{candidate}: future product path is not null")
    require(req.get("actual_counts") == COUNTS, f"{candidate}: request actual counts")
    require(req.get("expected_frames") == 51 and req.get("expected_frame_index") == 0,
            f"{candidate}: frame contract")
    require(req.get("expected_dimension") == 3 and req.get("expected_particles") == COUNTS["total"],
            f"{candidate}: dimension/axis")
    require(req.get("source_defined_initial_velocity_m_per_s") == [0.0, 0.0, 0.0],
            f"{candidate}: source initial velocity")
    require(req.get("native_velocity_must_be_measured_from_part_0000_bi4") is True,
            f"{candidate}: native velocity source")
    require(req.get("gencase_csv_velocity_must_not_be_used_as_native_proof") is True,
            f"{candidate}: GenCase velocity substitution guard")
    require(req.get("root_inventory_policy_source_sha256") == "c9103e306f87bb5af871c5de28d9939aa05f0c95c72e1630778f4bcf50e91ab5",
            f"{candidate}: Root230 policy")
    corrected = req.get("root_corrected_source_inventory_policy_sha256")
    require(isinstance(corrected, dict)
            and corrected.get("actual_native230") == req["root_inventory_policy_source_sha256"]
            and corrected.get("source_declared") == "2649eedbcf4816f8d2fa7b2182828ea8b3ce107ef47f25c56780d29c5138def5",
            f"{candidate}: policy provenance")
    command = req.get("command")
    require(isinstance(command, list) and "--binding" in command and "--output-dir" in command,
            f"{candidate}: command shape")
    require(command[0].endswith("/.venv/bin/python") and command[1].endswith("native_frame0_zero_velocity_identity_audit.py"),
            f"{candidate}: command producer")
    require(req.get("input_sha256_provenance", "").startswith("source/JSON/XML metadata only"),
            f"{candidate}: input provenance")
    for path_text, digest in req.get("input_sha256", {}).items():
        if path_text.startswith("<root-bind:"):
            require(digest is None, f"{candidate}: unresolved placeholder has a digest")
            continue
        suffix = Path(path_text).suffix.lower()
        if suffix in SCIENCE_SUFFIXES:
            require(digest is None, f"{candidate}: source request hashed science payload {path_text}")
        elif suffix in HASHABLE_SUFFIXES:
            require(Path(path_text).is_file(), f"{candidate}: closure metadata missing {path_text}")
            require(digest == sha(Path(path_text)), f"{candidate}: closure SHA mismatch {path_text}")
    require(binding.get("schema") == "ds02.f5.c082s1.native-frame0-zero-velocity-identity-binding.fresh106.v1",
            f"{candidate}: binding schema")
    require(binding.get("source_only") is True and binding.get("execution_allowed") is False,
            f"{candidate}: binding is not source-only disabled")
    require(binding.get("actual_particle_counts") == COUNTS, f"{candidate}: binding counts")
    require(binding.get("dimension") == 3 and binding.get("fluid_type_code") == 3,
            f"{candidate}: binding dimension/type")
    require(binding.get("historical_exact_dp_lattice", {}).get("accepted_as_stage1_gate") is False,
            f"{candidate}: exact-DP negative was relabelled")
    require(req.get("binding_sha256") == sha(binding_path), f"{candidate}: binding SHA")
    require(req.get("worker_sha256") == worker_info["worker_sha256"], f"{candidate}: worker SHA")
    files = binding["files"]
    receipt_path = Path(files["native_receipt"]["path"])
    receipt = load_json(receipt_path)
    require(receipt.get("status") == "completed" and int(receipt.get("returncode", -1)) == 0,
            f"{candidate}: Root455 receipt")
    nested = receipt.get("request")
    require(isinstance(nested, dict)
            and nested.get("attempt_id") == binding["native_attempt_id"]
            and nested.get("case_id") == CASE,
            f"{candidate}: Root455 receipt identity")
    require(receipt.get("output_root") == files["native_output_root"]["path"],
            f"{candidate}: output root binding")
    require(sha(receipt_path) == files["native_receipt"]["sha256"], f"{candidate}: receipt SHA")
    require(nested.get("actual_counts") == COUNTS, f"{candidate}: receipt counts")
    check_xml(Path(files["generated_xml"]["path"]), files["generated_xml"]["sha256"])
    prepared = load_json(Path(files["prepared_input_report"]["path"]))
    require(prepared.get("actual_total_particles") == COUNTS["total"], f"{candidate}: prepared total")
    require(prepared.get("generated_xml_particle_counts") == {
        "fixed": COUNTS["fixed"], "moving": COUNTS["moving"],
        "floating": COUNTS["floating"], "fluid": COUNTS["fluid"],
    }, f"{candidate}: prepared counts")
    gencase_receipt = load_json(Path(files["gencase_receipt"]["path"]))
    require(gencase_receipt.get("status") == "completed"
            and int(gencase_receipt.get("returncode", -1)) == 0,
            f"{candidate}: GenCase receipt")
    require(load_json(Path(files["actual_initial_qa_receipt"]["path"])).get("status") == "completed",
            f"{candidate}: initial QA receipt")
    return {
        "candidate": candidate,
        "request_path": str(req_path),
        "request_sha256": sha(req_path),
        "binding_path": str(binding_path),
        "binding_sha256": sha(binding_path),
        "native_attempt_id": binding["native_attempt_id"],
        "native_receipt_sha256": files["native_receipt"]["sha256"],
        "actual_particle_counts": COUNTS,
        "actual_root455_receipt_completed_zero": True,
        "generated_xml_3d": True,
        "native_frame0_partvtk": "registered worker pending",
        "typed_enablement": "blocked until Root reviews native frame-0 QA",
        "full801_authorized": False,
        "q_n_granted": False,
        "independent_case_count_increment": 0,
    }


def refresh_manifest() -> str:
    files: dict[str, str] = {}
    for path in sorted(PKG.rglob("*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        require(path.suffix.lower() in HASHABLE_SUFFIXES,
                f"package contains nonmetadata file: {path}")
        files[str(path.relative_to(PKG))] = sha(path)
    manifest = {
        "schema": "ds02.f5.c082s1.native-frame0-zero-velocity-identity-package-manifest.fresh106.v1",
        "source_only": True,
        "science_payloads_in_package": False,
        "science_payloads_read_or_hashed_by_source_validator": False,
        "files": files,
        "future_output_hashes": {
            "frame0_qa_report_sha256": None,
            "frame0_qa_receipt_sha256": None,
            "partvtk_csv_sha256": None,
        },
        "full801_authorized": False,
        "q_n_granted": False,
        "independent_case_count_increment": 0,
    }
    path = PKG / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return sha(path)


def main() -> int:
    worker_info = check_worker_source()
    results = [check_candidate(candidate, worker_info) for candidate in CANDIDATES]
    report = {
        "schema": "ds02.f5.c082s1.native-frame0-zero-velocity-identity-validator-report.fresh106.v1",
        "status": "passed_metadata_and_disabled_frame0_contract",
        "candidates": results,
        "worker": worker_info,
        "historical_exact_dp_lattice": {
            "threshold": 1.0e-6,
            "diagnostic_only": True,
            "accepted_as_stage1_gate": False,
            "status": "negative retained",
        },
        "science_payloads_read_or_hashed_by_source_validator": False,
        "jobs_started": False,
        "shared_state_modified": False,
        "full801_authorized": False,
        "q_n_granted": False,
        "independent_case_count_increment": 0,
    }
    output = PKG / "metadata" / "fresh106-validator-report.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    refresh_manifest()
    print(json.dumps({
        "status": report["status"],
        "candidates": list(CANDIDATES),
        "science_payloads_read_or_hashed_by_validator": False,
        "jobs_started": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
