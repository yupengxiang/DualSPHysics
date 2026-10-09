#!/usr/bin/env python3
"""Tiny production-shape fixtures for the generic worker-output adapter."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parent / "ds_data02_stage2_verify_generic_native_join_v2.py"
spec = importlib.util.spec_from_file_location("stage2_generic_join_verifier_v2", SCRIPT)
assert spec is not None and spec.loader is not None
MODULE = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = MODULE
spec.loader.exec_module(MODULE)


RUNPARTS_COLUMNS = (
    "Part", "TimeStep [s]", "Steps", "DTsMin", "PartRuntime [s]", "NpSave", "NpSim", "NpNew", "NpOut", "NctSim",
    "NpAlloc [X]", "NctAlloc [X]", "SimRuntime [s]", "NpbSim", "NpfSim", "NpNormal", "NpOutPos", "NpOutRho",
    "NpOutMov", "DtMin [s]", "DtMax [s]", "MemCPU [MiB]", "MemGPU [MiB]", "MemGPU_Cells [MiB]", "NpAlloc", "NctAlloc",
)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def ref(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "st_dev": stat.st_dev,
        "st_ino": stat.st_ino,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def make_fixture(directory: Path) -> dict[str, Path]:
    proof_path = directory / "proof.json"
    proof = {
        "schema": MODULE.PROOF_SCHEMA,
        "status": "VERIFIED_ACTUAL_F2_TYPED_LIFECYCLE_BATCH_SAVED_MASK_DIAGNOSTICS_NO_PHYSICAL_CREDIT",
        "counts": {"cases_requested": 2, "completed": 2, "failed": 0},
        "case_verifications": [
            {"physical_case_id": "case-a", "family_id": "F2", "status": "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY"},
            {"physical_case_id": "case-b", "family_id": "F2", "status": "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY"},
        ],
    }
    write_json(proof_path, proof)
    proof_ref = ref(proof_path)

    scope = {
        "schema": "ds02.stage2.generic-native-typed-native-join.v1-manifest",
        "case_scope": {
            "original_case_count": 3,
            "existing_exact_join_count": 1,
            "cause_not_located_count": 0,
            "cause_bound_missing_join_count": 2,
            "selected_canonical_count": 2,
            "selected_case_ids": ["case-a", "case-b"],
            "existing_join_case_ids": ["old-case"],
            "unresolved_alias_case_ids": ["alias-case"],
        },
        "producer_case_index": {"case-a": "ROOT193", "case-b": "ROOT193"},
        "producer_proof_bundles": [{
            "producer_id": "ROOT193",
            "full_case_ids": ["case-a", "case-b"],
            "selected_case_ids": ["case-a", "case-b"],
            "proof": proof_ref,
        }],
        "actual_join_proofs": [proof_ref],
    }
    scope_path = directory / "scope.json"
    write_json(scope_path, scope)

    records_path = directory / "typed.jsonl"
    records_path.write_text('{"record_fields":"one row per static (Zone, Idp); saved-frame lifecycle only"}\n', encoding="utf-8")
    summary_path = directory / "typed-summary.json"
    write_json(summary_path, {"schema": "ds02.stage2.typed-lifecycle-v4-summary.v1", "physical_case_id": "case-a"})

    contract_path = directory / "case-a-contract.json"
    contract = {
        "schema": "ds02.stage2.generic-native-extract-contract.v1",
        "status": "READY_PARENT_GUARDED_NATIVE_EXTRACT",
        "physical_case_id": "case-a",
        "family_id": "F2",
        "typed_deferred": {
            "summary": ref(summary_path),
            "records": {**ref(records_path), "sha256": "PARENT_GUARD_COMPUTED", "rows": 2},
        },
    }
    write_json(contract_path, contract)
    contract_b_path = directory / "case-b-contract.json"
    contract_b = {**contract, "physical_case_id": "case-b"}
    write_json(contract_b_path, contract_b)

    manifest_path = directory / "generic-native-manifest.json"
    manifest = {
        "schema": MODULE.WORKER_MANIFEST_SCHEMA,
        "status": "READY_PARENT_GUARDED_NATIVE_EXTRACT",
        "family_id": "F2",
        "physical_case_ids": ["case-a", "case-b"],
        "contracts": [{**ref(contract_path), "physical_case_id": "case-a"}, {**ref(contract_b_path), "physical_case_id": "case-b"}],
        "typed_proof_bundles": [{
            "producer_id": "ROOT193",
            "full_case_ids": ["case-a", "case-b"],
            "selected_case_ids": ["case-a", "case-b"],
            "proof": proof_ref,
            "synthetic_merged_proof": False,
        }],
        "terminal_proof": proof_ref,
        "claim_boundary": {"physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "native_cause": "exact official PartOut Motive only"},
    }
    write_json(manifest_path, manifest)

    worker_path = directory / "worker.py"
    worker_path.write_text("# tiny source-only worker fixture\n", encoding="utf-8")
    static_paths = [manifest_path, contract_path, contract_b_path, worker_path]
    request_path = directory / "generic-native-request.json"
    request = {
        "schema": MODULE.REQUEST_SCHEMA,
        "family_id": "F2",
        "physical_case_ids": ["case-a", "case-b"],
        "manifest_contract": {"path": str(manifest_path), "sha256": ref(manifest_path)["sha256"]},
        "command": [sys.executable, str(worker_path), "audit", "--manifest", str(manifest_path), "--output", "{attempt_root}/generic-native-extract.json"],
        "input_files": [str(path) for path in static_paths],
        "input_sha256": {str(path): ref(path)["sha256"] for path in static_paths},
        "deferred_input_files": [str(records_path)],
    }
    write_json(request_path, request)

    native_path = directory / "PartOut.csv"
    native_path.write_text(
        "Pos.x [m],Pos.y [m],Pos.z [m],PartOut,Motive,Idp,Vel.x [m/s],Vel.y [m/s],Vel.z [m/s],Rhop [kg/m^3]\n"
        "0,0,0,1,1,1,0,0,0,1000\n",
        encoding="utf-8",
    )
    runparts_path = directory / "RunPARTs.csv"
    header = ";".join(RUNPARTS_COLUMNS)
    row0 = ["0", "0.2", "1", "0.01", "0", "1", "1", "0", "0", "1", "1.0", "1.0", "0", "1", "1", "1", "0", "0", "0", "0.01", "0.02", "1", "0", "0", "1", "1"]
    row1 = ["1", "0.3", "2", "0.01", "0", "1", "1", "0", "1", "1", "1.0", "1.0", "0", "1", "1", "1", "1", "0", "0", "0.01", "0.02", "1", "0", "0", "1", "1"]
    runparts_path.write_text(header + "\n" + ";".join(row0) + "\n" + ";".join(row1) + "\n# footer\n", encoding="utf-8")
    native_ref = ref(native_path)
    runparts_ref = ref(runparts_path)
    records_stat = ref(records_path)
    typed_evidence = {"pre_stat": records_stat, "post_stat": records_stat, "sha256": hashlib.sha256(records_path.read_bytes()).hexdigest(), "rows": 1, "target_count": 1}
    case_report_path = directory / "case-a-report.json"
    case_report = {
        "schema": MODULE.WORKER_CASE_SCHEMA,
        "status": "COMPLETED_GENERIC_NATIVE_TYPED_SAVED_BRACKET_DIAGNOSTIC_ONLY",
        "physical_case_id": "case-a",
        "family_id": "F2",
        "typed": typed_evidence,
        "native": {
            "partout_csv": {"pre_stat": native_ref, "post_stat": native_ref, "sha256": native_ref["sha256"], "rows": 1},
            "runparts": {"pre_stat": runparts_ref, "post_stat": runparts_ref, "sha256": runparts_ref["sha256"], "saved_times_s": [0.2, 0.3]},
        },
        "counts": {"typed_targets": 1, "native_rows": 1, "joined": 1},
        "rows": [{"identity_key": [0, 1], "zone": 0, "idp": 1, "first_missing_frame": 3, "first_missing_time_s": 0.3, "bracket_s": [0.2, 0.3], "motive_code": 1, "part_out": 1, "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN"}],
        "claim_boundary": {"physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "native_cause": "exact official PartOut Motive only"},
    }
    write_json(case_report_path, case_report)
    report_path = directory / "generic-native-report.json"
    report = {
        "schema": MODULE.WORKER_REPORT_SCHEMA,
        "status": "COMPLETED_WITH_CASE_FAILURES",
        "family_id": "F2",
        "case_results": [
            {"physical_case_id": "case-a", "status": "COMPLETED", "output": str(case_report_path), "joined": 1},
            {"physical_case_id": "case-b", "status": "FAILED", "error_type": "GenericExtractError", "error_message": "fixture failure", "saved_mask_credit": False},
        ],
        "counts": {"requested": 2, "completed": 1, "failed": 1},
        "claim_boundary": {"native_cause": "exact official PartOut Motive only", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
    }
    write_json(report_path, report)
    return {"scope": scope_path, "manifest": manifest_path, "request": request_path, "report": report_path, "case_report": case_report_path, "native": native_path}


class GenericNativeJoinV2Tests(unittest.TestCase):
    def test_real_worker_report_shape_accepts_partial_failure_and_dynamic_counts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            paths = make_fixture(Path(td))
            output = Path(td) / "verified.json"
            result = subprocess.run([
                sys.executable, str(SCRIPT), "verify", "--scope", str(paths["scope"]), "--manifest", str(paths["manifest"]),
                "--request", str(paths["request"]), "--report", str(paths["report"]), "--output", str(output),
            ], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            verified = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(verified["counts"]["worker_completed_cases"], 1)
            self.assertEqual(verified["counts"]["worker_failed_cases"], 1)
            self.assertEqual(verified["counts"]["new_typed_native_join_physical_cases"], 1)
            self.assertEqual(verified["counts"]["new_native_cause_credit"], 0)
            self.assertEqual(verified["counts"]["scope_existing_exact_join_count"], 1)
            self.assertTrue(verified["read_policy"]["jsonl_content_opened"] is False)

    def test_rejects_already_joined_worker_case_and_stale_request_sha(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            paths = make_fixture(directory)
            scope = json.loads(paths["scope"].read_text(encoding="utf-8"))
            scope["case_scope"]["selected_case_ids"] = ["old-case", "case-b"]
            scope["producer_case_index"] = {"old-case": "ROOT193", "case-b": "ROOT193"}
            bad_scope = directory / "bad-scope.json"
            write_json(bad_scope, scope)
            with self.assertRaises(MODULE.GenericJoinV2Error):
                MODULE.verify(bad_scope, paths["manifest"], paths["request"], paths["report"])

            request = json.loads(paths["request"].read_text(encoding="utf-8"))
            request["input_sha256"][str(paths["manifest"])] = "0" * 64
            bad_request = directory / "bad-request.json"
            write_json(bad_request, request)
            with self.assertRaises(MODULE.GenericJoinV2Error):
                MODULE.verify(paths["scope"], paths["manifest"], bad_request, paths["report"])

    def test_rejects_duplicate_case_output_row(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            paths = make_fixture(directory)
            case = json.loads(paths["case_report"].read_text(encoding="utf-8"))
            case["rows"].append(dict(case["rows"][0]))
            case["counts"]["typed_targets"] = 2
            case["counts"]["native_rows"] = 2
            case["counts"]["joined"] = 2
            write_json(paths["case_report"], case)
            with self.assertRaises(MODULE.GenericJoinV2Error):
                MODULE.verify(paths["scope"], paths["manifest"], paths["request"], paths["report"])


if __name__ == "__main__":
    unittest.main()
