"""Exercise production native ``_audit_one`` through a real tiny worker.

The older V5 fixture writes a case report itself and replaces the rolling
scope loader.  This test deliberately does neither.  It creates a tiny
parent-reserved contract, executes the test-only worker subprocess, and lets
the reviewed V1 implementation (also used by V3 and ROOT312 V4) create the
case report.  V5 then consumes the resulting production-shaped batch report
against the real V10/CURRENT336/lifecycle-plan scope.

The opaque OBI4 is a fixture payload only.  The decoder is a tiny executable
that writes the exact PartOut/RunPARTs files consumed by the production
intake parser; no production native payload is opened.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import ds_data02_stage2_verify_generic_native_join_v5 as verifier


CASE_ID = "F4_DROP_gap0p20000_xoffm0p08000_yoff0p04000_uz0p40000"
ROOT = SCRIPT_DIR.parents[0]
STAGE2 = ROOT / "campaigns/ds-data-02/stage2"
OVERLAY = STAGE2 / "checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT268_ACTUAL_OVERLAY_V10.json"
PLAN = STAGE2 / "checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT269_V4.json"
CURRENT = STAGE2 / "CURRENT336.json"
WORKER = SCRIPT_DIR / "ds_data02_stage2_tiny_production_native_worker.py"
PRODUCTION_BACKENDS = ("generic-v3", "root312-v4")


RUNPARTS_COLUMNS = (
    "Part", "TimeStep [s]", "Steps", "DTsMin", "PartRuntime [s]", "NpSave", "NpSim", "NpNew", "NpOut", "NctSim",
    "NpAlloc [X]", "NctAlloc [X]", "SimRuntime [s]", "NpbSim", "NpfSim", "NpNormal", "NpOutPos", "NpOutRho",
    "NpOutMov", "DtMin [s]", "DtMax [s]", "MemCPU [MiB]", "MemGPU [MiB]", "MemGPU_Cells [MiB]", "NpAlloc", "NctAlloc",
)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ref(path: Path, *, rows: int | None = None) -> dict[str, object]:
    stat = path.stat()
    value: dict[str, object] = {
        "path": str(path.resolve()),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": _sha(path),
    }
    if rows is not None:
        value["rows"] = rows
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _make_fixture(root: Path, backend: str) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    typed = root / "typed-records.jsonl"
    typed.write_text(
        '{"record_fields":"one row per static (Zone, Idp); saved-frame lifecycle only"}\n'
        '{"zone":0,"idp":1,"initial_role":"fluid","initial_type_code":3,"initial_mass_kg":0.125,'
        '"first_disappeared_frame":1,"first_disappeared_time_s":0.3,"first_disappeared_bracket_s":[0.2,0.3]}\n',
        encoding="utf-8",
    )
    summary = root / "typed-summary.json"
    _write_json(summary, {
        "schema": "ds02.stage2.typed-lifecycle-sidecar.v4",
        "physical_case_id": CASE_ID,
        "timeline": {"time_s": [0.2, 0.3]},
        "role_ledgers": {"fluid": {"first_disappearance_count": 1}},
    })

    native_dir = root / "native-data"
    native_dir.mkdir()
    obi4 = native_dir / "PartOut_000.obi4"
    obi4.write_bytes(b"tiny opaque OBI4 fixture; never interpreted\n")

    decoder = root / "tiny-partvtkout.sh"
    decoder.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "data=''\n"
        "csv=''\n"
        "resume=''\n"
        "while [ \"$#\" -gt 0 ]; do\n"
        "  case \"$1\" in\n"
        "    -dirdata) data=$2; shift 2 ;;\n"
        "    -savecsv) csv=$2; shift 2 ;;\n"
        "    -saveresume) resume=$2; shift 2 ;;\n"
        "    *) shift ;;\n"
        "  esac\n"
        "done\n"
        "[ -d \"$data\" ]\n"
        "mkdir -p \"$(dirname \"$csv\")\" \"$(dirname \"$resume\")\"\n"
        "cat > \"$csv\" <<'CSV'\n"
        "Pos.x [m],Pos.y [m],Pos.z [m],PartOut,Motive,Idp,Zone,Rhop [kg/m^3]\n"
        "0.1,0.2,0.3,1,1,1,0,1000.0\n"
        "CSV\n"
        "cat > \"$resume\" <<'RESUME'\n"
        "tiny decoder resume\n"
        "RESUME\n",
        encoding="utf-8",
    )
    decoder.chmod(0o755)

    row0 = ["0", "0.2", "1", "0.01", "0", "1", "1", "0", "0", "1", "1.0", "1.0", "0", "1", "1", "1", "0", "0", "0", "0.01", "0.02", "1", "0", "0", "1", "1"]
    row1 = ["1", "0.3", "2", "0.01", "0", "1", "1", "0", "1", "1", "1.0", "1.0", "0", "1", "1", "1", "1", "0", "0", "0.01", "0.02", "1", "0", "0", "1", "1"]
    runparts = root / "RunPARTs.csv"
    runparts.write_text(";".join(RUNPARTS_COLUMNS) + "\n" + ";".join(row0) + "\n" + ";".join(row1) + "\n", encoding="utf-8")

    case_manifest = root / "case-manifest.json"
    _write_json(case_manifest, {"physical_case_id": CASE_ID, "status": "COMPLETED"})
    receipt = root / "case-receipt.json"
    _write_json(receipt, {"status": "COMPLETED", "returncode": 0})

    typed_ref = {**_ref(typed, rows=1), "deferred": True, "content_opened_by_preparer": False, "read_after_parent_reservation": True}
    summary_ref = _ref(summary)
    obi4_ref = {**_ref(obi4), "deferred": True, "content_opened_by_preparer": False, "read_after_parent_reservation": True}
    runparts_ref = {**_ref(runparts), "deferred": True, "content_opened_by_preparer": False, "read_after_parent_reservation": True}
    decoder_ref = _ref(decoder)
    dir_stat = native_dir.stat()
    data_dir_ref = {
        "path": str(native_dir.resolve()),
        "bytes": int(dir_stat.st_size),
        "mtime_ns": int(dir_stat.st_mtime_ns),
        "ctime_ns": int(dir_stat.st_ctime_ns),
        "st_dev": int(dir_stat.st_dev),
        "st_ino": int(dir_stat.st_ino),
    }

    contract = {
        "schema": "ds02.stage2.generic-native-extract-contract.v1",
        "status": "READY_PARENT_GUARDED_NATIVE_EXTRACT",
        "physical_case_id": CASE_ID,
        "family_id": "F4",
        "historical_118_membership": True,
        "typed_deferred": {"summary": summary_ref, "records": typed_ref},
        "native_deferred": {"data_dir": data_dir_ref, "partout_obi4": obi4_ref, "runparts_csv": runparts_ref},
        "claim_boundary": {"physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    contract_path = root / "case-contract.json"
    _write_json(contract_path, contract)
    contract_ref = _ref(contract_path)

    # This is a producer-proof-shaped tiny source edge.  The worker output is
    # generated later by production _audit_one; no case report is written here.
    proof_row = {
        "physical_case_id": CASE_ID,
        "family_id": "F4",
        "status": "COMPLETED_TYPED_LIFECYCLE_NO_PHYSICAL_CREDIT",
        "summary": str(summary.resolve()),
        "summary_sha256": summary_ref["sha256"],
        "records_stat_only": typed_ref,
        "case_manifest": str(case_manifest.resolve()),
        "case_manifest_sha256": _sha(case_manifest),
        "receipt": str(receipt.resolve()),
        "receipt_sha256": _sha(receipt),
        "source_H5_prepost_known_SHA_and_current_stat_equal": True,
        "native_cause_fate_legal_flux_dynamics": "UNKNOWN",
    }
    proof = {
        "schema": verifier.PROOF_SCHEMA,
        "status": "VERIFIED_ACTUAL_TINY_WORKER_SOURCE_FIXTURE_NO_PHYSICAL_CREDIT",
        "counts": {"cases_requested": 1, "completed": 1, "failed": 0},
        "case_verifications": [proof_row],
    }
    proof_path = root / "producer-proof.json"
    _write_json(proof_path, proof)

    manifest = {
        "schema": verifier.ROOT312_MANIFEST_SCHEMA,
        "status": "READY_PARENT_GUARDED_ROOT312_F4_NATIVE_EXTRACT",
        "family_id": "F4",
        "physical_case_ids": [CASE_ID],
        "contracts": [{"physical_case_id": CASE_ID, **contract_ref}],
        "proof_bundles": [{
            "bundle_id": "TINY_ROOT312_PRODUCER",
            "producer_proof": _ref(proof_path),
            "full_case_count": 1,
            "full_case_ids": [CASE_ID],
            "selected_case_ids": [CASE_ID],
            "producer_proof_preserved": True,
        }],
        "official_sources": {"partvtkout": decoder_ref},
        "claim_boundary": {"physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    manifest_path = root / f"manifest-{backend}.json"
    _write_json(manifest_path, manifest)
    manifest_ref = _ref(manifest_path)

    static_paths = [manifest_path, contract_path, proof_path, summary, case_manifest, receipt, decoder, WORKER]
    request = {
        "schema": verifier.REQUEST_SCHEMA,
        "family_id": "F4",
        "physical_case_ids": [CASE_ID],
        "manifest_contract": {"path": str(manifest_path.resolve()), "sha256": manifest_ref["sha256"]},
        "command": [sys.executable, str(WORKER.resolve()), "audit", "--manifest", str(manifest_path.resolve()), "--backend", backend, "--output", "{attempt_root}/worker-report.json"],
        "input_files": [str(path.resolve()) for path in static_paths],
        "input_sha256": {str(path.resolve()): _sha(path) for path in static_paths},
        "deferred_input_files": [str(typed.resolve()), str(obi4.resolve()), str(runparts.resolve())],
        "official_sources": {"partvtkout": decoder_ref},
    }
    request_path = root / f"request-{backend}.json"
    _write_json(request_path, request)
    return {"manifest": manifest_path, "request": request_path, "proof": proof_path, "contract": contract_path, "typed": typed, "summary": summary}


def _load_root312_worker():
    path = SCRIPT_DIR / "ds_data02_stage2_build_root312_f4_native_extract_v4.py"
    spec = importlib.util.spec_from_file_location("tiny_direct_root312_v4", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _make_direct_root312_fixture(root: Path) -> tuple[Path, Path]:
    """Make the real V4 audit's required 3+4/8+8 manifest shape."""
    base = _make_fixture(root / "base", "root312-v4")
    selected = [
        "F4_DROP_gap0p20000_xoffm0p08000_yoff0p04000_uz0p40000",
        "F4_DROP_gap0p20000_xoff0p08000_yoffm0p04000_uz0p40000",
        "F4_DROP_gap0p25000_xoff0p08000_yoff0p04000_uz0p40000",
        "F4_DROP_gap0p26000_xoff0p08000_yoff0p04000_uz0p40000",
        "F4_DROP_gap0p26000_xoff0p08000_yoffm0p04000_uz0p40000",
        "F4_DROP_gap0p26000_xoff0p08000_yoffm0p04000_uz0p60000",
        "F4_DROP_gap0p26000_xoffm0p08000_yoffm0p04000_uz0p60000",
    ]
    contracts = []
    for case_id in selected:
        value = json.loads(base["contract"].read_text(encoding="utf-8"))
        value["physical_case_id"] = case_id
        contract = root / "contracts" / f"{case_id}.json"
        contract.parent.mkdir(parents=True, exist_ok=True)
        _write_json(contract, value)
        contracts.append({"physical_case_id": case_id, **_ref(contract)})

    def proof(path: Path, full_ids: list[str]) -> Path:
        summary_ref = _ref(base["summary"])
        records_ref = {**_ref(base["typed"], rows=1), "deferred": True, "content_opened_by_preparer": False, "read_after_parent_reservation": True}
        rows = []
        for case_id in full_ids:
            rows.append({
                "physical_case_id": case_id,
                "family_id": "F4",
                "status": "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY",
                "summary": str(base["summary"].resolve()),
                "summary_sha256": summary_ref["sha256"],
                "records_stat_only": records_ref,
                "case_manifest": str((root / "base/case-manifest.json").resolve()),
                "case_manifest_sha256": _sha(root / "base/case-manifest.json"),
                "receipt": str((root / "base/case-receipt.json").resolve()),
                "receipt_sha256": _sha(root / "base/case-receipt.json"),
                "source_H5_prepost_known_SHA_and_current_stat_equal": True,
                "native_cause_fate_legal_flux_dynamics": "UNKNOWN",
            })
        _write_json(path, {"schema": verifier.PROOF_SCHEMA, "status": "VERIFIED_ACTUAL_TINY_ROOT312_PRODUCER", "counts": {"cases_requested": 8, "completed": 8, "failed": 0}, "case_verifications": rows})
        return path

    proof296 = proof(root / "proof296.json", selected[:3] + [f"F4_TINY_ROOT312_DIAGNOSTIC_296_{i}" for i in range(5)])
    proof297 = proof(root / "proof297.json", selected[3:] + [f"F4_TINY_ROOT312_DIAGNOSTIC_297_{i}" for i in range(4)])
    decoder_ref = _ref(root / "base/tiny-partvtkout.sh")
    manifest = {
        "schema": verifier.ROOT312_MANIFEST_SCHEMA,
        "status": "READY_PARENT_GUARDED_ROOT312_F4_NATIVE_EXTRACT",
        "family_id": "F4",
        "physical_case_ids": selected,
        "contracts": contracts,
        "proof_bundles": [
            {"bundle_id": "ROOT296", "producer_proof": _ref(proof296), "full_case_count": 8, "full_case_ids": json.loads(proof296.read_text())["case_verifications"] and [r["physical_case_id"] for r in json.loads(proof296.read_text())["case_verifications"]], "selected_case_ids": selected[:3], "producer_proof_preserved": True},
            {"bundle_id": "ROOT297", "producer_proof": _ref(proof297), "full_case_count": 8, "full_case_ids": [r["physical_case_id"] for r in json.loads(proof297.read_text())["case_verifications"]], "selected_case_ids": selected[3:], "producer_proof_preserved": True},
        ],
        "producer_proof_merge": {"created": False},
        "official_sources": {"partvtkout": decoder_ref},
        "claim_boundary": {"physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    manifest_path = root / "direct-root312-manifest.json"
    _write_json(manifest_path, manifest)
    return manifest_path, root / "direct-root312-report.json"


class TinyProductionWorkerV5Tests(unittest.TestCase):
    def _run(self, root: Path, backend: str) -> tuple[dict[str, Path], Path]:
        paths = _make_fixture(root, backend)
        report = root / f"worker-report-{backend}.json"
        command = [sys.executable, str(WORKER), "audit", "--manifest", str(paths["manifest"]), "--backend", backend, "--output", str(report)]
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertTrue(report.is_file(), completed.stdout)
        # The test-only worker must have created the case report through the
        # imported production _audit_one; no fixture case-report file exists.
        result = json.loads(report.read_text(encoding="utf-8"))
        case_output = Path(result["case_results"][0]["output"])
        self.assertTrue(case_output.is_file())
        self.assertEqual(json.loads(case_output.read_text(encoding="utf-8"))["counts"]["joined"], 1)
        return paths, report

    def test_generic_v3_worker_and_v5_real_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths, report = self._run(Path(directory), "generic-v3")
            output = verifier.verify(OVERLAY, paths["manifest"], paths["request"], report, PLAN, CURRENT)
            self.assertEqual(output["status"], "VERIFIED_GENERIC_OR_ROOT312_WORKER_OUTPUT_ALL_CASES")
            self.assertEqual(output["counts"]["worker_completed"], 1)

    def test_generic_v1_worker_and_v5_real_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths, report = self._run(Path(directory), "generic-v1")
            output = verifier.verify(OVERLAY, paths["manifest"], paths["request"], report, PLAN, CURRENT)
            self.assertEqual(output["status"], "VERIFIED_GENERIC_OR_ROOT312_WORKER_OUTPUT_ALL_CASES")
            self.assertEqual(output["counts"]["worker_completed"], 1)

    def test_root312_v4_worker_and_v5_real_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths, report = self._run(Path(directory), "root312-v4")
            output = verifier.verify(OVERLAY, paths["manifest"], paths["request"], report, PLAN, CURRENT)
            self.assertEqual(output["status"], "VERIFIED_GENERIC_OR_ROOT312_WORKER_OUTPUT_ALL_CASES")
            self.assertEqual(output["counts"]["worker_completed"], 1)

    def test_root312_v4_audit_itself_constructs_batch_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, report = _make_direct_root312_fixture(Path(directory))
            worker = _load_root312_worker()
            value = worker.audit(argparse.Namespace(manifest=manifest, output=report))
            self.assertEqual(value["status"], "COMPLETED_SELECTED_ORIGINAL118_NATIVE_DIAGNOSTIC_ONLY")
            batch = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(batch["schema"], "ds02.stage2.root312-f4-native-extract-report.v2")
            self.assertEqual(batch["counts"], {"requested": 7, "completed": 7, "failed": 0})

    def test_production_worker_does_not_accept_decoder_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = _make_fixture(Path(directory), "generic-v3")
            decoder = Path(json.loads(paths["manifest"].read_text())["official_sources"]["partvtkout"]["path"])
            decoder.write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
            decoder.chmod(0o755)
            command = [sys.executable, str(WORKER), "audit", "--manifest", str(paths["manifest"]), "--backend", "generic-v3", "--output", str(Path(directory) / "failed.json")]
            completed = subprocess.run(command, check=False, capture_output=True, text=True)
            self.assertNotEqual(completed.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
