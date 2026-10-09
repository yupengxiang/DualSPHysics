from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parent / "ds_data02_stage2_verify_generic_native_join_v3.py"
spec = importlib.util.spec_from_file_location("stage2_generic_join_verifier_v3", SCRIPT)
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def ref(path: Path, *, sha: str | None = None) -> dict[str, object]:
    raw = path.read_bytes()
    st = path.stat()
    return {"path": str(path.resolve()), "bytes": st.st_size, "mtime_ns": st.st_mtime_ns, "ctime_ns": st.st_ctime_ns, "st_dev": st.st_dev, "st_ino": st.st_ino, "sha256": hashlib.sha256(raw).hexdigest() if sha is None else sha}


def make_fixture(directory: Path) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    # Legacy single-case proof shape: no case_verifications list.
    old_proof = directory / "old-single-proof.json"
    write_json(old_proof, {"schema": MODULE.PROOF_SCHEMA, "status": "VERIFIED_ACTUAL_OLD_SINGLE_CASE_NO_PHYSICAL_CREDIT", "physical_case_id": "old-case"})
    old_ref = ref(old_proof)

    typed_records = directory / "case-a.jsonl"
    typed_records.write_text('{"record_fields":"one row per static (Zone, Idp); saved-frame lifecycle only"}\n', encoding="utf-8")
    records_ref = {**ref(typed_records), "rows": 1, "deferred": True, "read_after_parent_reservation": True}
    summary = directory / "case-a-summary.json"
    write_json(summary, {
        "schema": "ds02.stage2.typed-lifecycle-sidecar.v4",
        "physical_case_id": "case-a", "family_id": "F4",
        "timeline": {"frames": 2, "particles": 1, "time_s": [0.2, 0.3]},
        "role_ledgers": {"fluid": {"first_disappearance_count": 1}},
        "first_missing_records": [{"identity_key": [0, 1], "first_missing_frame": 1, "first_missing_time_s": 0.3, "bracket_s": [0.2, 0.3]}],
    })
    summary_ref = ref(summary)

    obi4 = directory / "PartOut_000.obi4"
    obi4.write_bytes(b"tiny-obi4-payload")
    obi4_ref = ref(obi4)
    partout = directory / "PartOut.csv"
    partout.write_text("Pos.x [m],Pos.y [m],Pos.z [m],PartOut,Motive,Idp,Vel.x [m/s],Vel.y [m/s],Vel.z [m/s],Rhop [kg/m^3]\n0,0,0,1,1,1,0,0,0,1000\n", encoding="utf-8")
    partout_ref = ref(partout)
    runparts = directory / "RunPARTs.csv"
    header = ";".join(RUNPARTS_COLUMNS)
    row0 = ["0", "0.2", "1", "0.01", "0", "1", "1", "0", "0", "1", "1.0", "1.0", "0", "1", "1", "1", "0", "0", "0", "0.01", "0.02", "1", "0", "0", "1", "1"]
    row1 = ["1", "0.3", "2", "0.01", "0", "1", "1", "0", "1", "1", "1.0", "1.0", "0", "1", "1", "1", "1", "0", "0", "0.01", "0.02", "1", "0", "0", "1", "1"]
    runparts.write_text(header + "\n" + ";".join(row0) + "\n" + ";".join(row1) + "\n# footer\n", encoding="utf-8")
    runparts_ref = ref(runparts)
    case_contract = directory / "case-a-contract.json"
    contract = {
        "schema": "ds02.stage2.generic-native-extract-contract.v1", "status": "READY_PARENT_GUARDED_NATIVE_EXTRACT",
        "physical_case_id": "case-a", "family_id": "F4",
        "typed_deferred": {"summary": summary_ref, "records": records_ref},
        "native_deferred": {"partout_obi4": {**obi4_ref, "deferred": True, "read_after_parent_reservation": True}, "runparts_csv": runparts_ref},
    }
    write_json(case_contract, contract)
    contract_ref = ref(case_contract)

    case_report = directory / "case-a-report.json"
    case_report_value = {
        "schema": MODULE.WORKER_CASE_SCHEMA, "status": "COMPLETED_GENERIC_NATIVE_TYPED_SAVED_BRACKET_DIAGNOSTIC_ONLY",
        "physical_case_id": "case-a", "family_id": "F4",
        "typed": {"pre_stat": {k: records_ref[k] for k in ("path", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino")}, "post_stat": {k: records_ref[k] for k in ("path", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino")}},
        "native": {
            "partout_obi4": {"pre_stat": obi4_ref, "post_stat": obi4_ref, "pre_sha256": obi4_ref["sha256"], "post_sha256": obi4_ref["sha256"]},
            "partout_csv": {"pre_stat": partout_ref, "post_stat": partout_ref, "sha256": partout_ref["sha256"], "rows": 1},
            "runparts": {"pre_stat": runparts_ref, "post_stat": runparts_ref, "sha256": runparts_ref["sha256"], "saved_times_s": [0.2, 0.3]},
        },
        "counts": {"typed_targets": 1, "native_rows": 1, "joined": 1},
        "rows": [{"identity_key": [0, 1], "zone": 0, "idp": 1, "first_missing_frame": 1, "first_missing_time_s": 0.3, "bracket_s": [0.2, 0.3], "motive_code": 1, "part_out": 1}],
        "claim_boundary": {"physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    write_json(case_report, case_report_value)

    proof = directory / "worker-proof.json"
    write_json(proof, {"schema": MODULE.PROOF_SCHEMA, "status": "VERIFIED_ACTUAL_F4_TYPED_BATCH_NO_PHYSICAL_CREDIT", "case_verifications": [{"physical_case_id": "case-a", "family_id": "F4"}]})
    proof_ref = ref(proof)

    manifest = directory / "root312-manifest.json"
    manifest_value = {
        "schema": MODULE.ROOT312_MANIFEST_SCHEMA, "status": "READY_PARENT_GUARDED_ROOT312_F4_NATIVE_EXTRACT", "family_id": "F4", "physical_case_ids": ["case-a"],
        "contracts": [{"physical_case_id": "case-a", **contract_ref}],
        "proof_bundles": [{"bundle_id": "ROOT296", "producer_proof": proof_ref, "full_case_count": 1, "full_case_ids": ["case-a"], "selected_case_ids": ["case-a"], "producer_proof_preserved": True}],
        "claim_boundary": {"physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    write_json(manifest, manifest_value)
    manifest_ref = ref(manifest)
    worker = directory / "worker.py"
    worker.write_text("# immutable source fixture\n", encoding="utf-8")
    request = directory / "request.json"
    static = [manifest, case_contract, worker]
    write_json(request, {"schema": MODULE.REQUEST_SCHEMA, "family_id": "F4", "physical_case_ids": ["case-a"], "manifest_contract": {"path": str(manifest.resolve()), "sha256": manifest_ref["sha256"]}, "command": [sys.executable, str(worker), "audit", "--manifest", str(manifest.resolve()), "--output", "{attempt_root}/report.json"], "input_files": [str(p.resolve()) for p in static], "input_sha256": {str(p.resolve()): ref(p)["sha256"] for p in static}, "deferred_input_files": [str(typed_records.resolve()), str(obi4.resolve())]})

    batch = directory / "batch-report.json"
    write_json(batch, {"schema": MODULE.WORKER_REPORT_SCHEMA, "status": "COMPLETED_ALL_CASES", "family_id": "F4", "case_results": [{"physical_case_id": "case-a", "status": "COMPLETED", "output": str(case_report.resolve()), "joined": 1}], "counts": {"requested": 1, "completed": 1, "failed": 0}, "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"})
    scope = directory / "overlay.json"
    write_json(scope, {"schema": MODULE.OVERLAY_SCHEMA, "status": "VERIFIED_METADATA_JOIN_TO_ACTUAL_PER_ID_PROOFS", "physical_case_count": 2, "actual_typed_native_saved_frame_join_physical_cases": ["old-case"], "remaining_cause_not_located_case_ids": ["case-a"], "actual_join_proofs": [old_ref], "qualification_boundary": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN"}})
    return {"scope": scope, "manifest": manifest, "request": request, "report": batch, "case_report": case_report, "proof": proof}


class GenericNativeJoinV3Tests(unittest.TestCase):
    def test_root312_keeps_two_complete_eight_case_proofs_separate_from_selected_subsets(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proof = root / "root296-proof.json"
            full_ids = [f"full-{index}" for index in range(8)]
            write_json(proof, {"schema": MODULE.PROOF_SCHEMA, "status": "VERIFIED_ACTUAL_ROOT296_EIGHT_CASES", "case_verifications": [{"physical_case_id": case_id} for case_id in full_ids]})
            proof_ref = ref(proof)
            old_proof = root / "existing-proof.json"
            write_json(old_proof, {"schema": MODULE.PROOF_SCHEMA, "status": "VERIFIED_ACTUAL_EXISTING", "physical_case_id": "old-case"})
            old_proof_ref = ref(old_proof)
            scope = root / "scope.json"
            write_json(scope, {"schema": MODULE.OVERLAY_SCHEMA, "status": "VERIFIED_METADATA_JOIN_TO_ACTUAL_PER_ID_PROOFS", "physical_case_count": 4, "actual_typed_native_saved_frame_join_physical_cases": ["old-case"], "remaining_cause_not_located_case_ids": full_ids[:3], "actual_join_proofs": [old_proof_ref], "qualification_boundary": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN"}})
            contract = root / "selected-contract.json"
            write_json(contract, {"schema": "ds02.stage2.generic-native-extract-contract.v1", "status": "READY_PARENT_GUARDED_NATIVE_EXTRACT", "physical_case_id": "full-0", "family_id": "F4", "typed_deferred": {}, "native_deferred": {}})
            manifest = root / "root312.json"
            write_json(manifest, {"schema": MODULE.ROOT312_MANIFEST_SCHEMA, "status": "READY_PARENT_GUARDED_ROOT312_F4_NATIVE_EXTRACT", "family_id": "F4", "physical_case_ids": ["full-0"], "contracts": [{"physical_case_id": "full-0", **ref(contract)}], "proof_bundles": [{"bundle_id": "ROOT296", "producer_proof": proof_ref, "full_case_count": 8, "full_case_ids": full_ids, "selected_case_ids": ["full-0"], "producer_proof_preserved": True}], "claim_boundary": {"physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}})
            loaded_scope, _ = MODULE._load_scope_v3(scope)
            loaded_manifest, _, by_case = MODULE._load_worker_manifest_v3(manifest, loaded_scope)
            self.assertEqual(loaded_manifest["_v3_normalized_bundles"][0]["proof_ids"], full_ids)
            self.assertEqual(loaded_manifest["_v3_normalized_bundles"][0]["selected_case_ids"], ["full-0"])
            self.assertEqual(set(by_case), {"full-0"})

    def test_root312_shape_summary_and_obi4_stat_are_strictly_verified(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            paths = make_fixture(Path(td))
            output = Path(td) / "verified.json"
            value = MODULE.verify(paths["scope"], paths["manifest"], paths["request"], paths["report"])
            self.assertEqual(value["counts"]["worker_completed_cases"], 1)
            self.assertTrue(value["claim_boundary"]["native_obi4_pre_post_checked"])
            MODULE._atomic(output, value)
            self.assertTrue(output.exists())

    def test_report_frame_tamper_is_rejected_against_summary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            paths = make_fixture(Path(td))
            value = json.loads(paths["case_report"].read_text(encoding="utf-8"))
            value["rows"][0]["first_missing_frame"] = 2
            write_json(paths["case_report"], value)
            with self.assertRaises(MODULE.GenericJoinV3Error):
                MODULE.verify(paths["scope"], paths["manifest"], paths["request"], paths["report"])

    def test_scope_proof_ids_must_match_existing_set(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            paths = make_fixture(Path(td))
            value = json.loads(paths["proof"].read_text(encoding="utf-8"))
            value["physical_case_id"] = "wrong-proof-case"
            write_json(paths["proof"], value)
            scope = json.loads(paths["scope"].read_text(encoding="utf-8"))
            scope["actual_join_proofs"][0] = ref(paths["proof"])
            write_json(paths["scope"], scope)
            with self.assertRaises(MODULE.GenericJoinV3Error, msg="scope proof IDs must be independently derived"):
                MODULE.verify(paths["scope"], paths["manifest"], paths["request"], paths["report"])

    def test_manifest_full_case_ids_must_match_proof_rows(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            paths = make_fixture(Path(td))
            value = json.loads(paths["manifest"].read_text(encoding="utf-8"))
            value["proof_bundles"][0]["full_case_ids"] = ["invented"]
            write_json(paths["manifest"], value)
            with self.assertRaises(MODULE.GenericJoinV3Error):
                MODULE.verify(paths["scope"], paths["manifest"], paths["request"], paths["report"])

    def test_obi4_sha_tamper_is_rejected_without_content_hashing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            paths = make_fixture(Path(td))
            value = json.loads(paths["case_report"].read_text(encoding="utf-8"))
            value["native"]["partout_obi4"]["post_sha256"] = "0" * 64
            write_json(paths["case_report"], value)
            with self.assertRaises(MODULE.GenericJoinV3Error):
                MODULE.verify(paths["scope"], paths["manifest"], paths["request"], paths["report"])


if __name__ == "__main__":
    unittest.main()
