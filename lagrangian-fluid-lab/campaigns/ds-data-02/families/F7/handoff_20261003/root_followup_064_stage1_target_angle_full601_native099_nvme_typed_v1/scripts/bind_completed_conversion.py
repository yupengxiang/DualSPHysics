from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

HANDOFF = Path(__file__).resolve().parents[1]
OWNER_DIR = HANDOFF / "owners"
REQUEST_DIR = HANDOFF / "requests"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7")
EXPECTED_BLOCKS = [
    {"begin": 0, "count": 27495, "type": 0, "mk": 10},
    {"begin": 27495, "count": 1984, "type": 1, "mk": 12},
    {"begin": 29479, "count": 40700, "type": 3, "mk": 2},
]
EXPECTED = {
    "total": 70179,
    "fluid": 40700,
    "frames": 601,
    "dimension": 3,
    "time_first_s": 0.0,
    "time_last_s": 12.0,
}
ENDPOINTS = {
    "F7_OBSTACLE_QUINTIC_B08_A030": {
        "owner": OWNER_DIR / "F7_OBSTACLE_QUINTIC_B08_A030.owner.json",
        "request": REQUEST_DIR / "F7_OBSTACLE_QUINTIC_B08_A030.nvme-conversion-request.json",
        "typed_attempt": "root-stage1-f7-a030-full601-native-typed-nvme-064",
        "source_hash": "d23a491656bd152dd8dd0216abcd41b6df8a1f9e4478f9c9fd2f11b79f1f38e4",
    },
    "F7_OBSTACLE_QUINTIC_B08_A065": {
        "owner": OWNER_DIR / "F7_OBSTACLE_QUINTIC_B08_A065.owner.json",
        "request": REQUEST_DIR / "F7_OBSTACLE_QUINTIC_B08_A065.nvme-conversion-request.json",
        "typed_attempt": "root-stage1-f7-a065-full601-native-typed-nvme-064",
        "source_hash": "7694c57f286b25b288fd7813a0abbaa2eac82751a1540c623e3f3268d7eb8600",
    },
}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def completed_receipt(path: Path, label: str) -> dict[str, Any]:
    require(path.is_file(), f"{label} receipt missing: {path}")
    value = load(path)
    require(value.get("status") == "completed", f"{label} is not completed")
    require(value.get("returncode") == 0, f"{label} returncode is not zero")
    return value


def owner_and_request(endpoint_id: str) -> tuple[dict[str, Any], dict[str, Any], Path, Path]:
    require(endpoint_id in ENDPOINTS, f"unknown endpoint: {endpoint_id}")
    meta = ENDPOINTS[endpoint_id]
    owner_path = meta["owner"]
    request_path = meta["request"]
    owner = load(owner_path)
    request = load(request_path)
    require(owner.get("schema") == "ds02.f7.full601-native099-owner.v1", "owner schema mismatch")
    require(owner.get("case_id") == endpoint_id, "owner case mismatch")
    require(request.get("schema") == "ds02.runner-request.v2", "request schema mismatch")
    require(request.get("case_id") == endpoint_id, "request case mismatch")
    require(request.get("launch_allowed") is False, "source request must remain disabled")
    expected_attempt = "a030" if endpoint_id.endswith("A030") else "a065"
    require(request.get("attempt_id") == f"root-stage1-f7-{expected_attempt}-full601-native-typed-nvme-064", "typed attempt mismatch")
    binding = owner.get("physical_binding")
    require(isinstance(binding, dict), "owner has no explicit physical_binding")
    actual_canonical = canonical_hash(binding)
    require(actual_canonical == owner.get("canonical_physical_binding_sha256"), "owner canonical binding hash is stale")
    require(owner.get("physical_condition_sha256") == meta["source_hash"], "declared source condition hash mismatch")
    require(request.get("canonical_physical_binding_sha256") == actual_canonical, "request canonical binding hash mismatch")
    require(request.get("physical_condition_sha256") == meta["source_hash"], "request source condition hash mismatch")
    return owner, request, owner_path, request_path


def validate_owner_file_hashes(owner: dict[str, Any]) -> None:
    source = owner["source062_binding"]
    require(sha(Path(source["endpoint_plan"])) == source["endpoint_plan_sha256"], "source endpoint-plan hash mismatch")
    require(sha(Path(source["source_definition"])) == source["source_definition_sha256"], "source Definition hash mismatch")
    gencase = owner["gencase_provenance"]
    for key in ("receipt", "generated_xml", "generated_bi4", "generated_definition", "generated_motion"):
        hash_key = key + "_sha256"
        require(sha(Path(gencase[key])) == gencase[hash_key], f"GenCase {key} hash mismatch")
    qa = owner["initial_qa_provenance"]
    require(sha(Path(qa["receipt"])) == qa["receipt_sha256"], "QA receipt hash mismatch")
    require(sha(Path(qa["report"])) == qa["report_sha256"], "QA report hash mismatch")
    solver = owner["native_solver_provenance"]
    require(sha(Path(solver["receipt"])) == solver["receipt_sha256"], "native solver receipt hash mismatch")
    require(sha(Path(solver["solver_log"])) == solver["solver_log_sha256"], "native solver log hash mismatch")



def validate_provenance(owner: dict[str, Any], endpoint_id: str) -> dict[str, Any]:
    gencase_meta = owner["gencase_provenance"]
    solver_meta = owner["native_solver_provenance"]
    qa_meta = owner["initial_qa_provenance"]
    gencase_receipt = Path(gencase_meta["receipt"])
    solver_receipt = Path(solver_meta["receipt"])
    qa_receipt = Path(qa_meta["receipt"])
    gencase = completed_receipt(gencase_receipt, "actual GenCase085")
    solver = completed_receipt(solver_receipt, "actual native099 solver")
    qa = completed_receipt(qa_receipt, "actual QA096")
    require(Path(str(gencase.get("output_root", ""))).name.endswith("genuine-gencase-085"), "GenCase receipt is not actual085")
    require(Path(str(solver.get("output_root", ""))).name.endswith("full601-native-099"), "solver receipt is not actual099")
    require(Path(str(qa.get("output_root", ""))).name.endswith("actual-native-initial-qa-096"), "QA receipt is not actual096")
    require(gencase_meta["expected_counts"] == {"total": 70179, "fixed": 27495, "moving": 1984, "fluid": 40700}, "owner GenCase counts changed")
    require(solver_meta["full_window"] == {"time_max_s": 12.0, "save_interval_s": 0.02, "frames": 601}, "owner native window changed")
    qa_report = load(Path(qa_meta["report"]))
    require(qa_report.get("all_cases_passed") is True, "QA096 report does not pass both endpoints")
    case_rows = {row.get("case_id"): row for row in qa_report.get("cases", []) if isinstance(row, dict)}
    row = case_rows.get(endpoint_id)
    require(row is not None and row.get("passed") is True, f"QA096 endpoint did not pass: {endpoint_id}")
    require(row.get("native_particles") == 70179, "QA096 native particle count changed")
    require(row.get("checks", {}).get("actual_3d") is True, "QA096 is not 3-D")
    require(row.get("checks", {}).get("no_initial_overlap") is True, "QA096 no-overlap check failed")
    return {"gencase": gencase, "solver": solver, "qa": qa, "qa_report": qa_report}


def validate_static(endpoint_id: str) -> dict[str, Any]:
    owner, request, owner_path, request_path = owner_and_request(endpoint_id)
    validate_owner_file_hashes(owner)
    provenance = validate_provenance(owner, endpoint_id)
    input_hashes = request.get("input_sha256", {})
    require(isinstance(input_hashes, dict), "request input_sha256 is not an object")
    stale = []
    for raw_path in request.get("input_files", []):
        path = Path(raw_path)
        require(path.is_file(), f"request input missing: {path}")
        expected = input_hashes.get(str(path))
        if expected != sha(path):
            stale.append(str(path))
    require(not stale, f"request input hashes are stale: {stale}")
    return {
        "endpoint_id": endpoint_id,
        "owner": str(owner_path),
        "request": str(request_path),
        "canonical_physical_binding_sha256": owner["canonical_physical_binding_sha256"],
        "declared_source_condition_sha256": owner["physical_condition_sha256"],
        "source_request_disabled": request["launch_allowed"] is False,
        "provenance_completed": True,
        "qa_all_cases_passed": provenance["qa_report"].get("all_cases_passed") is True,
    }


def validate_conversion(endpoint_id: str, report_path: Path, h5_path: Path) -> dict[str, Any]:
    owner, request, owner_path, request_path = owner_and_request(endpoint_id)
    validate_owner_file_hashes(owner)
    provenance = validate_provenance(owner, endpoint_id)
    require(report_path.is_file(), f"conversion report missing: {report_path}")
    require(h5_path.is_file(), f"trajectory H5 missing: {h5_path}")
    report = load(report_path)
    require(report.get("schema") == "ds-data-02.bi4-direct-conversion.v1", "conversion schema mismatch")
    require(report.get("conversion_status") == "completed", "conversion is not completed")
    require(Path(str(report.get("output_hdf5", ""))).resolve() == h5_path.resolve(), "report H5 path mismatch")
    require(report.get("frames") == EXPECTED["frames"], "conversion frame count is not 601")
    require(report.get("particles") == EXPECTED["total"], "conversion particle count is not 70179")
    dimension = report.get("solver_dimension", {})
    require(dimension.get("solver_dimension") == EXPECTED["dimension"], "conversion is not 3-D")
    require(report.get("time_evidence", {}).get("first_s") == EXPECTED["time_first_s"], "conversion first time is not 0")
    require(report.get("time_evidence", {}).get("last_s") == EXPECTED["time_last_s"], "conversion last time is not 12")
    require(report.get("time_evidence", {}).get("strictly_increasing") is True, "conversion time axis is not increasing")
    typed = report.get("typed_identity", {})
    require(typed.get("observed_types") == [0, 1, 3], "conversion observed types changed")
    require(typed.get("observed_mks") == [2, 10, 12], "conversion observed Mk values changed")
    observed_blocks = [
        {key: block.get(key) for key in ("begin", "count", "type", "mk")}
        for block in typed.get("blocks", [])
        if isinstance(block, dict)
    ]
    require(observed_blocks == EXPECTED_BLOCKS, "conversion typed blocks do not match actual QA096")
    partvtk = report.get("partvtk_validation", {})
    require(partvtk.get("all_passed") is True, "official PartVTK validation did not pass")
    hash_scopes = report.get("hash_scopes", {})
    observed_canonical = hash_scopes.get("physical_condition_sha256")
    require(observed_canonical == owner["canonical_physical_binding_sha256"], "converter physical hash differs from owner canonical hash")
    h5_sha = sha(h5_path)
    require(report.get("output_sha256") == h5_sha, "conversion output hash mismatch")
    source_hash = owner["physical_condition_sha256"]
    return {
        "endpoint_id": endpoint_id,
        "owner": str(owner_path),
        "request": str(request_path),
        "conversion_report": str(report_path.resolve()),
        "conversion_report_sha256": sha(report_path),
        "trajectory_h5": str(h5_path.resolve()),
        "trajectory_h5_sha256": h5_sha,
        "frames": report["frames"],
        "particles": report["particles"],
        "fluid_particles": EXPECTED["fluid"],
        "solver_dimension": dimension,
        "observed_converter_physical_condition_sha256": observed_canonical,
        "declared_source_condition_sha256": source_hash,
        "source_vs_converter_hash_equal": observed_canonical == source_hash,
        "native_fluid_mass_kg": owner["native_recipe"]["native_fluid_mass_kg"],
        "continuum_fluid_mass_kg": owner["native_recipe"]["continuum_envelope_mass_kg"],
        "mass_difference_kg": owner["native_recipe"]["native_minus_continuum_mass_kg"],
        "mass_rescaled": False,
        "gencase_status": provenance["gencase"].get("status"),
        "initial_qa_all_cases_passed": provenance["qa_report"].get("all_cases_passed") is True,
        "native_solver_status": provenance["solver"].get("status"),
        "partvtk_all_passed": True,
        "q_n": "not_granted",
        "production_approval": "none",
        "array_policy": "H5 bytes hashed only; helper does not open H5 datasets or decode native arrays",
    }


def bind(endpoint_id: str, report_path: Path, h5_path: Path, output_path: Path, force: bool) -> dict[str, Any]:
    value = validate_conversion(endpoint_id, report_path, h5_path)
    value.update({
        "schema": "ds02.f7.full601-native099-nvme-typed-binding.v1",
        "bound_status": "root-bound-after-actual-nvme-conversion",
        "bound_by": str(Path(__file__).resolve()),
        "binding_semantics": "converter hash is canonical physical_binding.v1; source062 condition hash is retained as a separate declared provenance hash",
        "launch_allowed": False,
        "full_native_window": True,
        "native_motion_reader": "piecewise_linear_absolute_angle_increment",
        "native_sampled_regular": "not C2",
    })
    if output_path.exists() and not force:
        raise FileExistsError(f"refusing to overwrite binding: {output_path}; use --force")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\\n", encoding="utf-8")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Bind actual F7 native099 NVMe typed conversion metadata without opening H5 datasets.")
    parser.add_argument("--endpoint", choices=sorted(ENDPOINTS), required=True)
    parser.add_argument("--mode", choices=("static", "bind"), default="static")
    parser.add_argument("--conversion-report", type=Path)
    parser.add_argument("--trajectory-h5", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    static = validate_static(args.endpoint)
    if args.mode == "static":
        print(json.dumps(static, sort_keys=True))
        return 0
    require(args.conversion_report is not None, "--conversion-report is required for bind mode")
    require(args.trajectory_h5 is not None, "--trajectory-h5 is required for bind mode")
    output = args.output
    if output is None:
        meta = ENDPOINTS[args.endpoint]
        output = DATA_ROOT / args.endpoint / meta["typed_attempt"] / "typed-binding.json"
    result = bind(args.endpoint, args.conversion_report.resolve(), args.trajectory_h5.resolve(), output.resolve(), args.force)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
