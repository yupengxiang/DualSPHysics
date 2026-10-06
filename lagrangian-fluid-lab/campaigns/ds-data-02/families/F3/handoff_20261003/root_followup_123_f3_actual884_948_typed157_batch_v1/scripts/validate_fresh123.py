#!/usr/bin/env python3
"""Validate fresh123 request closure without scientific-payload I/O."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

FORBIDDEN = {".bi4", ".ibi4", ".obi4", ".h5", ".hdf5", ".csv", ".dat", ".vtk", ".vtu", ".npy", ".npz", ".raw"}
ROOT157_NAME = "nvme_convert_home_capped_v2.py"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def option(command: list[str], name: str) -> str:
    try:
        return command[command.index(name) + 1]
    except (ValueError, IndexError) as exc:
        raise RuntimeError(f"missing command option {name}") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    package = args.package.resolve()
    index = read_json(package / "metadata" / "candidate-index.json")
    rows = index["selected_cases"]
    request_paths = sorted((package / "requests").glob("*.json"))
    require(len(request_paths) == len(rows), "request/index count mismatch")
    row_by_case = {row["case_id"]: row for row in rows}
    results = []
    for request_path in request_paths:
        req = read_json(request_path)
        case = req.get("case_id")
        require(case in row_by_case, f"unexpected case {case}")
        row = row_by_case[case]
        require(req.get("schema") == "ds02.runner-request.v2", f"{case}: schema")
        require(req.get("fresh_id") == "fresh123", f"{case}: fresh id")
        require(req.get("family_id") == "F3", f"{case}: family")
        require(req.get("disabled") is True and req.get("source_only") is True, f"{case}: not disabled source-only")
        require(req.get("execution_allowed") is False and req.get("launch_allowed") is False and req.get("launch") is False, f"{case}: launch gate")
        require(req.get("case_credit") == 0 and req.get("q_n_granted") is False, f"{case}: credit gate")
        require(req.get("physical_case_id") == row["physical_case_id"], f"{case}: physical id")
        binding = Path(req["binding"]).resolve()
        require(binding.is_absolute() and binding.is_file(), f"{case}: binding missing")
        require(str(binding) == row["owner_path"], f"{case}: binding is not selected owner")
        require(sha256(binding) == req["binding_sha256"] == row["owner_sha256"], f"{case}: binding sha")
        owner = read_json(binding)
        physical_binding = owner.get("physical_binding")
        require(isinstance(physical_binding, dict) and physical_binding.get("schema") == "ds-data-02.physical-binding.v1", f"{case}: physical binding schema")
        require(req.get("actual_converter_scope_sha256") == row["physical_condition_sha256"], f"{case}: scope sha")
        require(req.get("canonical_physical_condition_sha256") == row["physical_condition_sha256"], f"{case}: canonical scope sha")
        require(req.get("actual_converter_scope_preflight", {}).get("status") == "pass_metadata_only_explicit_physical_binding_v1", f"{case}: preflight status")
        require(req.get("expected_dimension") == 3 and req.get("expected_particles") == 179208 and req.get("expected_frames") == 836, f"{case}: recipe counts")
        require(req.get("actual_counts", {}).get("dimension") == 3 and req.get("actual_counts", {}).get("total") == 179208, f"{case}: actual counts")
        require(req.get("actual_counts", {}).get("fixed") == 111708 and req.get("actual_counts", {}).get("fluid") == 67500, f"{case}: actual partition")
        native = req.get("actual_native_dependency", {})
        require(native.get("status") == "completed" and native.get("returncode") == 0, f"{case}: native status")
        require(native.get("native_saved_frame_file_count") == 836 and native.get("part_filename_count_stat_only") == 836, f"{case}: native frame/file count")
        receipt = Path(native["receipt"]).resolve()
        require(receipt.is_file() and sha256(receipt) == native["receipt_sha256"], f"{case}: native receipt sha")
        receipt_meta = read_json(receipt)
        require(receipt_meta.get("status") == "completed" and receipt_meta.get("returncode") == 0, f"{case}: receipt terminal status")
        evidence = read_json(Path(row["native_evidence_path"]))
        require(evidence["receipt"]["sha256"] == native["receipt_sha256"], f"{case}: evidence receipt link")
        native_request = Path(req["native_request"]["path"]).resolve()
        require(native_request.is_file() and sha256(native_request) == req["native_request"]["sha256"], f"{case}: native request sha")
        require(req["depends_on_attempt"] == native_request.name.removesuffix("-native-request.json"), f"{case}: stale active dependency")
        require(req["depends_on_attempts"] == [req["depends_on_attempt"]], f"{case}: dependency list")
        require(req.get("historical_root839_negative") is None and req.get("root_distinct_successor_of_unlaunched_request") is None, f"{case}: stale historical active field")
        require("root_followup_118" not in json.dumps(req, sort_keys=True), f"{case}: fresh118 leaked into request")
        command = req.get("command")
        require(isinstance(command, list) and len(command) > 4, f"{case}: command")
        require(Path(command[1]).name == ROOT157_NAME and sha256(Path(command[1])) == req["source157_worker"]["sha256"], f"{case}: Root157 worker")
        require("--" in command, f"{case}: command separator")
        tail = command[command.index("--") + 1:]
        require(not any("ds_data02_direct_convert.py" in item or "ds_data02_nvme_convert_v1.py" in item for item in tail), f"{case}: redundant converter after separator")
        require(Path(option(command, "--owner-metadata")).resolve() == binding, f"{case}: owner command binding")
        require(option(command, "--current-attempt-id").startswith(f"F3/{case}/"), f"{case}: current attempt id")
        require(int(req.get("cpu_threads", -1)) == 2 and int(req.get("estimated_storage_bytes", -1)) == 4294967296, f"{case}: resource request")
        policy = req.get("storage_policy", {})
        require(policy.get("global_conversion_cap") == 2 and policy.get("home_free_floor_bytes") == 536870912000 and policy.get("home_publish_cap_bytes") == 4294967296 and policy.get("private_nvme_staging_limit_bytes") == 25769803776 and policy.get("private_nvme_free_reserve_bytes") == 107374182400, f"{case}: storage policy")
        current_inputs = req.get("input_files", [])
        require(all(Path(x).is_absolute() for x in current_inputs), f"{case}: non-absolute current input")
        require(not any(Path(x).suffix.lower() in FORBIDDEN for x in current_inputs), f"{case}: scientific suffix in current input")
        require(not any("root_followup_118" in x or "root_followup_121" in x for x in current_inputs), f"{case}: stale historical input")
        for value in current_inputs:
            path = Path(value)
            require(path.is_file(), f"{case}: missing current input {path}")
            require(req["input_sha256"].get(value) == sha256(path), f"{case}: input sha {path}")
        require(str(binding) in current_inputs, f"{case}: binding not in current input map")
        # This deliberately keys by the request's actual absolute binding path,
        # rather than rebuilding a path from __file__. That is the relocation-
        # safe contract used by Root's handoff adapter.
        require(req["input_sha256"].get(str(binding)) == sha256(binding), f"{case}: binding map closure")
        future_hashes = req.get("future_input_sha256", {})
        require(req.get("future_input_hashes_null") is True and future_hashes and all(v is None for v in future_hashes.values()), f"{case}: future hash policy")
        future_outputs = req.get("future_outputs", {})
        require(all(value is None or value == 0 or (isinstance(value, str) and "{attempt_root}" in value) for value in future_outputs.values()), f"{case}: future output prefill")
        results.append({
            "case_id": case,
            "request_path": str(request_path.resolve()),
            "request_sha256": sha256(request_path),
            "native_status": "completed0",
            "native_receipt_sha256": native["receipt_sha256"],
            "owner_sha256": req["binding_sha256"],
            "current_input_count": len(current_inputs),
            "current_input_sha256_closed": True,
            "stale_fresh118_inputs": False,
            "relocation_safe_binding_check": True,
            "typed_status": "disabled_wait_root_launch",
        })
    output = args.output or package / "metadata" / "fresh123-validator-report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        "schema": "ds02.stage1.f3.fresh123.validator-report.v1",
        "package": str(package),
        "selected_count": len(results),
        "results": results,
        "science_payload_opened_or_hashed": False,
        "shared_state_modified": False,
        "jobs_started": 0,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "pass", "selected_count": len(results), "report": str(output.resolve())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
