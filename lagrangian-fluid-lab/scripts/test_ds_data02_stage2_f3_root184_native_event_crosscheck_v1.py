from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_f3_root184_native_event_crosscheck_v1 as subject


def _write(path: Path, value: object) -> str:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sources(root: Path) -> tuple[Path, Path, Path, Path, Path, Path]:
    rows = [
        {"idp": 1000 + index, "motive": "position", "motive_code": 1, "part_out": 1 + index, "saved_record_bracket_s": [float(index), float(index + 1)]}
        for index in range(512)
    ]
    root182_report = root / "root182-report.json"
    root182_receipt = root / "root182-receipt.json"
    root182_report_sha = _write(root182_report, {
        "schema": subject.ROOT182_REPORT_SCHEMA,
        "status": "PASS",
        "case": {"case_id": subject.ROOT182_CASE, "physical_case_id": subject.ROOT182_PHYSICAL},
        "native_identity": {"rows": rows},
    })
    root182_receipt_sha = _write(root182_receipt, {"status": "completed", "returncode": 0})
    root182_proof = root / "root182-proof.json"
    _write(root182_proof, {"status": "ACTUAL_ROOT182", "report": str(root182_report), "report_sha256": root182_report_sha, "receipt": str(root182_receipt), "receipt_sha256": root182_receipt_sha})

    root178_report = root / "root178-report.json"
    root178_report_sha = _write(root178_report, {
        "schema": subject.ROOT178_REPORT_SCHEMA,
        "status": "PASS",
        "observations": [
            {"frame": 0, "runparts_time_s": 0.0, "identity_lifecycle": {"appeared_idp": [1000], "disappeared_idp": []}},
            {"frame": 1, "runparts_time_s": 1.0, "identity_lifecycle": {"appeared_idp": [], "disappeared_idp": [1000]}},
        ],
    })
    root178_receipt = root / "root178-receipt.json"
    root178_receipt_sha = _write(root178_receipt, {"status": "completed", "returncode": 0, "request": {"physical_case_id": subject.ROOT182_PHYSICAL}})
    root178_proof = root / "root178-proof.json"
    _write(root178_proof, {"status": "ACTUAL_ROOT178", "report": str(root178_report), "report_sha256": root178_report_sha, "receipt": str(root178_receipt), "receipt_sha256": root178_receipt_sha})
    return root182_proof, root182_report, root182_receipt, root178_proof, root178_report, root178_receipt


class Root184Tests(unittest.TestCase):
    def test_self_test_contract(self) -> None:
        self.assertEqual(subject.self_test()["status"], "PASS")

    def test_first_missing_comes_from_frame_event(self) -> None:
        value = {
            "observations": [
                {"frame": 7, "runparts_time_s": 0.7, "identity_lifecycle": {"appeared_idp": [], "disappeared_idp": [12]}},
            ],
            "id_lifecycle": {"records": [{"idp": 12, "first_missing_frame": 999}]},
        }
        events, _scope = subject._event_index(value)
        self.assertEqual(events[12]["event_frame"], 7)
        self.assertNotEqual(events[12]["event_frame"], value["id_lifecycle"]["records"][0]["first_missing_frame"])

    def test_payload_paths_are_rejected(self) -> None:
        with self.assertRaises(subject.Root184Error):
            subject._path("/tmp/PartOut_000.obi4", "raw")

    def test_prepare_does_not_open_future_root178_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root182_proof, root182_report, root182_receipt, _p, _r, _q = _sources(root)
            output = root / "prepared-manifest.json"
            args = SimpleNamespace(
                root182_proof=root182_proof,
                root182_report=root182_report,
                root182_receipt=root182_receipt,
                root178_proof=str(root / "future-proof.json"),
                root178_report=str(root / "future-report.json"),
                root178_receipt=str(root / "future-receipt.json"),
                output=output,
            )
            subject.prepare_manifest(args)
            value = json.loads(output.read_text())
            self.assertEqual(value["status"], "WAITING_ROOT178_TERMINAL")
            deferred = [ref for ref in value["source_refs"] if ref["role"].startswith("root178")]
            self.assertEqual(len(deferred), 3)
            self.assertTrue(all(ref["sha256"] == subject.DEFERRED for ref in deferred))

    def test_actual_crosscheck_is_bounded_and_classified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            r182p, r182r, r182q, r178p, r178r, r178q = _sources(root)
            output = root / "crosscheck.json"
            args = SimpleNamespace(root182_proof=r182p, root182_report=r182r, root182_receipt=r182q, root178_proof=r178p, root178_report=r178r, root178_receipt=r178q, output=output, max_report_bytes=subject.MAX_FULL_REPORT_BYTES)
            result = subject.run_audit(args)
            self.assertEqual(result["comparison"]["classification_counts"]["MATCH"], 1)
            self.assertEqual(result["comparison"]["classification_counts"]["UNKNOWN"], 511)
            self.assertLessEqual(output.stat().st_size, subject.MAX_OUTPUT_BYTES)
            self.assertEqual(result["scientific_qualification"]["QI"], "UNKNOWN")

    def test_final_manifest_and_request_defer_full_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            r182p, r182r, r182q, r178p, r178r, r178q = _sources(root)
            manifest_path = root / "final-manifest.json"
            subject.build_final_manifest(SimpleNamespace(root182_proof=r182p, root182_report=r182r, root182_receipt=r182q, root178_proof=r178p, root178_report=r178r, root178_receipt=r178q, output=manifest_path))
            worker = root / "worker.py"
            python = root / "python"
            runtime_v2 = root / "runtime-v2.py"
            runtime_v6 = root / "runtime-v6.py"
            runtime_v8 = root / "runtime-v8.py"
            dispatch = root / "dispatch-v8.py"
            strict = root / "strict-v8.py"
            for path in (worker, python, runtime_v2, runtime_v6, runtime_v8, dispatch, strict):
                path.write_text("# fixture\n", encoding="utf-8")
            request_path = root / "request.json"
            subject.build_request(SimpleNamespace(manifest=manifest_path, output=request_path, worker=worker, python=python, runtime_v2=runtime_v2, runtime_v6=runtime_v6, runtime_v8=runtime_v8, dispatch_v8=dispatch, strict_v8=strict, cwd=root, worktree_root=root))
            request = json.loads(request_path.read_text())
            self.assertEqual(request["estimated_hdf5_read_bytes"], 0)
            self.assertIn(str(r178r.resolve()), request["deferred_input_files"])
            self.assertNotIn(str(r178r.resolve()), request["input_files"])
            self.assertEqual(request["max_memory_bytes"], 4 * 1024 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
