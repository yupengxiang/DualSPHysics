from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_typed_native_first_missing_v4 as subject


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> str:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return digest(path)


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> str:
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    return digest(path)


def fixture(root: Path) -> dict[str, Path | str]:
    case_id = subject.CASE_ID
    trajectory = root / "deferred-trajectory.h5"
    # The fixture never opens this file.  Its path is only an immutable source
    # declaration, which mirrors prepare's H5/stat-only policy.
    trajectory.write_bytes(b"deferred fixture payload")
    trajectory_sha = "a" * 64
    current_path = root / "CURRENT336.json"
    cases: list[dict[str, object]] = [{
        "family_id": "F2", "physical_case_id": case_id, "frames": 4, "particles": 5,
        "trajectory": {"path": str(trajectory), "producer_declared_sha256": trajectory_sha, "bytes": trajectory.stat().st_size},
    }]
    for index in range(335):
        cases.append({
            "family_id": "F2" if index < 47 else ("F4" if index < 69 else "F6"),
            "physical_case_id": f"DUMMY_{index:03d}", "frames": 1, "particles": 1,
            "trajectory": {"path": str(root / f"dummy-{index}.h5"), "producer_declared_sha256": "b" * 64, "bytes": 1},
        })
    current_sha = write_json(current_path, {"schema": subject.CURRENT_SCHEMA, "cases": cases})

    native_path = root / "native-omission.json"
    native_rows = []
    for idp, frame, bracket in ((10, 2, [0.1, 0.2]), (11, 3, [0.2, 0.3])):
        native_rows.append({
            "zone": 0, "idp": idp, "type_code": 3, "initial_mass_kg": 0.001,
            "first_missing_frame": frame, "first_missing_bracket_s": bracket,
            "native_exit_cause": "NUMERICAL_POSITION_EXCLUSION", "physical_fate": "UNKNOWN",
        })
    native = {
        "schema": subject.OMISSION_SCHEMA, "status": "CAUSES_RECONCILED", "family_id": "F2", "physical_case_id": case_id,
        "trajectory": {"path": str(trajectory), "sha256": trajectory_sha},
        "typed_identity": {"identity_key": "(Zone,Idp)", "missing_fluid_count": 2, "ids": [{"zone": 0, "idp": 10, "first_missing_frame": 2}, {"zone": 0, "idp": 11, "first_missing_frame": 3}]},
        "excluded_particles": native_rows, "physical_fate": "UNKNOWN; native numerical exclusion is not proof of physical spill",
    }
    native_sha = write_json(native_path, native)

    records_path = root / "typed-records.jsonl"
    record_header = {
        "schema": subject.RECORD_SCHEMA, "status": "COMPLETED_TYPED_LIFECYCLE_RECORDS_NO_PHYSICAL_CREDIT",
        "family_id": "F2", "physical_case_id": case_id, "source_trajectory_sha256": trajectory_sha,
    }
    record_header["record_fields"] = subject.EXPECTED_RECORD_FIELDS
    record_header["record_population"] = 5
    records_sha = write_jsonl(records_path, [record_header,
        {"zone": 0, "idp": 10, "first_disappeared_frame": 2, "first_disappeared_time_s": 0.2, "first_disappeared_bracket_s": [0.1, 0.2]},
        {"zone": 0, "idp": 11, "first_disappeared_frame": 3, "first_disappeared_time_s": 0.3, "first_disappeared_bracket_s": [0.2, 0.3]},
        # Representative unaffected identities from fixed, moving, and fluid
        # roles.  The production ROOT192 stream has 421,566 rows; this small
        # fixture preserves the whole-stream identity contract without opening
        # that production JSONL in tests.
        {"zone": 0, "idp": 100, "particle_role": "fixed", "initial_type_code": 1, "initial_mass_kg": 0.002},
        {"zone": 0, "idp": 101, "particle_role": "moving", "initial_type_code": 2, "initial_mass_kg": 0.002},
        {"zone": 0, "idp": 102, "particle_role": "fluid", "initial_type_code": 0, "initial_mass_kg": 0.001},
    ])
    records_bytes = records_path.stat().st_size

    summary_path = root / "typed-summary.json"
    summary_sha = write_json(summary_path, {
        "schema": subject.SUMMARY_SCHEMA, "status": "COMPLETED_TYPED_LIFECYCLE_NO_PHYSICAL_CREDIT", "family_id": "F2", "physical_case_id": case_id,
        "source": {"current336_sha256": current_sha, "trajectory_h5": {"path": str(trajectory), "known_sha256": trajectory_sha}},
        "timeline": {"frames": 4, "particles": 5, "time_s": [0.0, 0.1, 0.2, 0.3]},
        "records": {"path": str(records_path), "bytes": records_bytes, "rows": 5, "sha256": records_sha},
    })
    proof_path = root / "proof.json"
    proof_sha = write_json(proof_path, {
        "schema": subject.PROOF_SCHEMA, "status": "VERIFIED_ACTUAL_TYPED_LIFECYCLE_V4_SINGLE_CASE_118_SAVED_MASK_DISAPPEARANCES_NO_PHYSICAL_CREDIT",
        "physical_case_id": case_id, "report": str(summary_path), "report_sha256": summary_sha,
        "source_H5_prepost_known_SHA_and_current_stat_equal": True, "H5_or_large_records_content_read_by_root": False,
        "fresh_small_inputs": [{"path": str(current_path), "sha256": current_sha}],
        "records_stat_only": [{"path": str(records_path), "sha256": records_sha, "bytes": records_bytes, "rows": 5}],
    })
    union_path = root / "union.json"
    evidence = [{"family_id": "F2", "physical_case_id": case_id, "report": {"path": str(native_path), "sha256": native_sha}}]
    evidence.extend({"family_id": "F2", "physical_case_id": f"F2_DUMMY_{i:02d}", "report": {"path": str(native_path), "sha256": native_sha}} for i in range(47))
    evidence.extend({"family_id": "F4", "physical_case_id": f"F4_DUMMY_{i:02d}", "report": {"path": str(native_path), "sha256": native_sha}} for i in range(22))
    evidence.extend({"family_id": "F6", "physical_case_id": f"F6_DUMMY_{i:02d}", "report": {"path": str(native_path), "sha256": native_sha}} for i in range(48))
    union_sha = write_json(union_path, {"schema": subject.UNION_SCHEMA, "status": "PASS_EXACT_118_OF118_SOURCE_CASE_UNION", "native_evidence": evidence})
    return {
        "current": current_path, "current_sha": current_sha, "union": union_path, "union_sha": union_sha,
        "proof": proof_path, "proof_sha": proof_sha, "summary": summary_path, "summary_sha": summary_sha,
        "native": native_path, "native_sha": native_sha, "records": records_path, "records_sha": records_sha,
    }


def prepare_args(source: dict[str, Path | str], output: Path, request: Path | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        current=source["current"], current_sha256=source["current_sha"], union=source["union"], union_sha256=source["union_sha"],
        root192_proof=source["proof"], root192_proof_sha256=source["proof_sha"], root192_summary=source["summary"], root192_summary_sha256=source["summary_sha"],
        native_report=source["native"], native_report_sha256=source["native_sha"], output=output, request_output=request, worker=None, python=None,
    )


class TypedNativeFirstMissingV4Tests(unittest.TestCase):
    def test_prepare_is_metadata_only_for_jsonl_and_emits_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = fixture(root)
            # Deliberately make the deferred payload non-JSON.  prepare must
            # stat it only; audit is the sole command allowed to open it.
            source["records"].write_bytes(b"not-jsonl-content")
            output = root / "contract.json"
            # Rebind only the summary/proof declaration to the replacement
            # stat/hash, leaving prepare's metadata-only behavior observable.
            summary = json.loads(Path(source["summary"]).read_text())
            summary["records"].update({"bytes": source["records"].stat().st_size, "sha256": digest(Path(source["records"]))})
            source["summary_sha"] = write_json(Path(source["summary"]), summary)
            proof = json.loads(Path(source["proof"]).read_text())
            proof["report_sha256"] = source["summary_sha"]
            proof["records_stat_only"][0].update({"bytes": source["records"].stat().st_size, "sha256": digest(Path(source["records"]))})
            source["proof_sha"] = write_json(Path(source["proof"]), proof)
            result = subject.prepare(prepare_args(source, output))
            contract = json.loads(output.read_text())
            self.assertEqual(result["status"], "READY_PARENT_GUARDED_AUDIT_NOT_LAUNCHED")
            self.assertFalse(contract["deferred_records"]["content_opened"])
            self.assertEqual(contract["resource_policy"]["cpu_threads"], 1)
            self.assertEqual(contract["resource_policy"]["memory_max_bytes"], 1024 * 1024 * 1024)
            self.assertEqual(contract["resource_policy"]["output_cap_bytes"], 8 * 1024 * 1024)

    def test_real_prepare_cli_has_subcommand_and_rejects_wrong_summary_sha(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = fixture(root)
            output = root / "contract.json"
            completed = subprocess.run([
                sys.executable, str(subject.SCRIPT), "prepare", "--current", str(source["current"]), "--current-sha256", str(source["current_sha"]),
                "--union", str(source["union"]), "--union-sha256", str(source["union_sha"]), "--root192-proof", str(source["proof"]), "--root192-proof-sha256", str(source["proof_sha"]),
                "--root192-summary", str(source["summary"]), "--root192-summary-sha256", str(source["summary_sha"]), "--native-report", str(source["native"]), "--native-report-sha256", str(source["native_sha"]), "--output", str(output),
            ], capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
            self.assertTrue(output.is_file())
            bad = subprocess.run([
                sys.executable, str(subject.SCRIPT), "prepare", "--current", str(source["current"]), "--current-sha256", str(source["current_sha"]),
                "--union", str(source["union"]), "--union-sha256", str(source["union_sha"]), "--root192-proof", str(source["proof"]), "--root192-proof-sha256", str(source["proof_sha"]),
                "--root192-summary", str(source["summary"]), "--root192-summary-sha256", "0" * 64, "--native-report", str(source["native"]), "--native-report-sha256", str(source["native_sha"]), "--output", str(root / "bad.json"),
            ], capture_output=True, text=True)
            self.assertNotEqual(bad.returncode, 0)

    def test_audit_streams_and_matches_exact_zone_idp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = fixture(root)
            contract_path = root / "contract.json"
            subject.prepare(prepare_args(source, contract_path))
            output = root / "crosscheck.json"
            result = subject.audit(contract_path, output)
            report = json.loads(output.read_text())
            self.assertEqual(result["record_count"], 5)
            self.assertEqual(report["typed_evidence"]["non_target_record_count"], 3)
            self.assertEqual(report["typed_evidence"]["native_key_join_count"], 2)
            self.assertEqual(report["comparison_counts"]["saved_frame_matches"], 2)
            self.assertEqual(report["claim_boundary"]["physical_fate"], "UNKNOWN")
            self.assertTrue(report["records"]["single_pass"])

    def test_wrong_zone_or_id_is_rejected_even_with_valid_row_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = fixture(root)
            contract_path = root / "contract.json"
            subject.prepare(prepare_args(source, contract_path))
            records = Path(source["records"])
            lines = records.read_text().splitlines()
            wrong = json.loads(lines[1])
            wrong["zone"] = 9
            lines[1] = json.dumps(wrong, sort_keys=True, separators=(",", ":"))
            records.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaises(subject.CrosscheckError):
                subject.audit(contract_path, root / "wrong-zone.json")

    def test_nonfinite_time_is_rejected_but_valid_time_mismatch_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = fixture(root)
            contract_path = root / "contract.json"
            subject.prepare(prepare_args(source, contract_path))
            records = Path(source["records"])
            lines = records.read_text().splitlines()
            row = json.loads(lines[1])
            row["first_disappeared_time_s"] = 0.25
            lines[1] = json.dumps(row, sort_keys=True, separators=(",", ":"))
            records.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaises(subject.CrosscheckError):
                subject.audit(contract_path, root / "changed-time.json")

    def test_missing_native_first_frame_is_unknown_not_count_inferred(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = fixture(root)
            native = json.loads(Path(source["native"]).read_text())
            native["excluded_particles"][0].pop("first_missing_frame")
            native["typed_identity"]["ids"][0].pop("first_missing_frame")
            source["native_sha"] = write_json(Path(source["native"]), native)
            union = json.loads(Path(source["union"]).read_text())
            union["native_evidence"][0]["report"]["sha256"] = source["native_sha"]
            source["union_sha"] = write_json(Path(source["union"]), union)
            # The contract must preserve the missing native evidence as
            # UNKNOWN; it must not reconstruct a frame from the count.
            contract_path = root / "contract.json"
            subject.prepare(prepare_args(source, contract_path))
            output = root / "unknown-native-frame.json"
            subject.audit(contract_path, output)
            report = json.loads(output.read_text())
            self.assertEqual(report["native_evidence"]["first_missing_frame_count"], 1)
            first = next(row for row in report["rows"] if row["idp"] == 10)
            self.assertIsNone(first["native_first_missing_frame"])
            self.assertIsNone(first["saved_frame_match"])

    def test_duplicate_unaffected_identity_is_rejected_after_whole_stream_counting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = fixture(root)
            contract_path = root / "contract.json"
            subject.prepare(prepare_args(source, contract_path))
            records = Path(source["records"])
            lines = records.read_text().splitlines()
            duplicate = json.loads(lines[-1])
            lines.append(json.dumps(duplicate, sort_keys=True, separators=(",", ":")))
            records.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaises(subject.CrosscheckError):
                subject.audit(contract_path, root / "duplicate-unaffected.json")

    def test_v4_header_requires_real_producer_record_fields_string(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = fixture(root)
            contract_path = root / "contract.json"
            subject.prepare(prepare_args(source, contract_path))
            records = Path(source["records"])
            lines = records.read_text().splitlines()
            header = json.loads(lines[0])
            header.pop("record_fields")
            lines[0] = json.dumps(header, sort_keys=True, separators=(",", ":"))
            records.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaises(subject.CrosscheckError):
                subject.audit(contract_path, root / "missing-header-contract.json")

    def test_v4_header_population_cannot_be_a_nonmatching_whole_stream_proxy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = fixture(root)
            contract_path = root / "contract.json"
            subject.prepare(prepare_args(source, contract_path))
            records = Path(source["records"])
            lines = records.read_text().splitlines()
            header = json.loads(lines[0])
            header["record_population"] = 421566
            lines[0] = json.dumps(header, sort_keys=True, separators=(",", ":"))
            records.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaises(subject.CrosscheckError):
                subject.audit(contract_path, root / "population-mismatch.json")

    def test_same_content_replacement_is_rejected_by_deferred_stat_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = fixture(root)
            contract_path = root / "contract.json"
            subject.prepare(prepare_args(source, contract_path))
            records = Path(source["records"])
            replacement = root / "replacement.jsonl"
            replacement.write_bytes(records.read_bytes())
            os.replace(replacement, records)
            with self.assertRaises(subject.CrosscheckError):
                subject.audit(contract_path, root / "replaced-same-content.json")

    def test_wrong_frame_time_pair_is_rejected_against_summary_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = fixture(root)
            contract_path = root / "contract.json"
            subject.prepare(prepare_args(source, contract_path))
            records = Path(source["records"])
            lines = records.read_text().splitlines()
            row = json.loads(lines[1])
            row["first_disappeared_frame"] = 3
            # Keep the old 0.2 s value: it is inside the row's own bracket but
            # is not the summary's time_s[3] (0.3 s).
            lines[1] = json.dumps(row, sort_keys=True, separators=(",", ":"))
            records.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaises(subject.CrosscheckError):
                subject.audit(contract_path, root / "wrong-frame-time.json")

    def test_real_audit_cli_consumes_whole_stream_and_writes_only_native_join(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = fixture(root)
            contract_path = root / "contract.json"
            subject.prepare(prepare_args(source, contract_path))
            output = root / "cli-crosscheck.json"
            completed = subprocess.run([
                sys.executable, str(subject.SCRIPT), "audit", "--contract", str(contract_path), "--output", str(output),
            ], capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
            report = json.loads(output.read_text())
            self.assertEqual(report["records"]["rows"], 5)
            self.assertEqual(report["typed_evidence"]["non_target_record_count"], 3)
            self.assertEqual(len(report["rows"]), 2)


if __name__ == "__main__":
    unittest.main()
