from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_f6_s0625_source_gap_v2 as subject


CASE_ID = subject.CASE_ID
H5_SHA = "a" * 64


def _write_json(path: Path, value: object) -> str:
    raw = (json.dumps(value, sort_keys=True) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _fixture(root: Path) -> tuple[argparse.Namespace, dict[str, object], Path]:
    records = root / "typed-records.jsonl"
    records.write_bytes(b'{"zone":0,"idp":10}\n')
    record_stat = subject._stat(records, "records", allow_deferred=True)
    record_sha = hashlib.sha256(records.read_bytes()).hexdigest()
    record_ref = {"path": str(records), "bytes": record_stat["bytes"], "rows": 1, "sha256": record_sha}
    verification = {
        "physical_case_id": CASE_ID,
        "family_id": "F6",
        "status": "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY",
        "summary": str(root / "summary.json"),
        "summary_sha256": "0" * 64,
        "source_H5_prepost_known_SHA_and_current_stat_equal": True,
        "source_trajectory": {"path": "/deferred/trajectory.h5", "known_sha256": H5_SHA, "pre_sha256": H5_SHA, "post_sha256": H5_SHA},
        "records_stat_only": {key: record_stat[key] for key in ("path", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino")} | {"rows": 1, "sha256": record_sha},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    summary = {
        "schema": subject.ROOT210_SUMMARY_SCHEMA,
        "status": subject.ROOT210_SUMMARY_STATUS,
        "physical_case_id": CASE_ID,
        "family_id": "F6",
        "records": record_ref,
        "timeline": {"frames": 241, "particles": 417505, "time_s": [0.0, 1.0]},
        "metadata": {"identity_key": "(Zone,Idp)", "identity_unique": True, "units_status": "EXPLICIT_SI"},
        "role_ledgers": {"fluid": {"first_disappearance_count": 3, "initial_count": 1, "initial_mass_kg": 1.0, "unknown_active_id_count": 0, "unknown_type_count": 0, "inactive_type_sentinel_count": 1}},
    }
    summary_path = root / "summary.json"
    summary_sha = _write_json(summary_path, summary)
    verification["summary_sha256"] = summary_sha
    proof = {"schema": subject.ROOT210_PROOF_SCHEMA, "status": subject.ROOT210_PROOF_STATUS, "case_verifications": [verification]}
    proof_path = root / "proof.json"
    _write_json(proof_path, proof)
    args = argparse.Namespace(root210_proof=proof_path, root210_summary=summary_path)
    current = {"path": "/deferred/trajectory.h5", "producer_declared_sha256": H5_SHA}
    return args, current, records


class F6S0625SourceGapV2Tests(unittest.TestCase):
    def test_root210_summary_binds_without_opening_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args, current, records = _fixture(Path(directory))
            result = subject._root210_bridge(args, current)
            self.assertEqual(result["summary"]["fluid"]["first_disappearance_count"], 3)
            self.assertEqual(result["records_deferred"]["rows"], 1)
            self.assertFalse(result["records_deferred"]["content_opened"])
            self.assertEqual(records.read_bytes(), b'{"zone":0,"idp":10}\n')

    def test_root210_rejects_same_content_replacement_by_stat(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args, current, records = _fixture(Path(directory))
            original = records.read_bytes()
            records.unlink()
            records.write_bytes(original)
            records.touch()
            records.chmod(0o644)
            import os
            os.utime(records, ns=(1_700_000_000_000_001_000, 1_700_000_000_000_001_000))
            with self.assertRaises(subject.SourceGapError):
                subject._root210_bridge(args, current)


if __name__ == "__main__":
    unittest.main()
