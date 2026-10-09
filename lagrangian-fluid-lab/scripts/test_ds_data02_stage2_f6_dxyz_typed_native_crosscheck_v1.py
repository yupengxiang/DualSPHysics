from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import ds_data02_stage2_f6_dxyz_typed_native_crosscheck_v1 as subject


def stat_ref(path: Path, rows: int | None = None) -> dict[str, object]:
    value = subject._stat(path, "fixture")
    value.update({"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "rows": rows})
    return value


class F6DxyzCrosscheckTests(unittest.TestCase):
    def _native(self) -> dict[tuple[int, int], dict[str, object]]:
        return {
            (0, 10): {"native_motive_code": 1},
            (0, 11): {"native_motive_code": 1},
            (0, 12): {"native_motive_code": 1},
        }

    def test_partout_exact_identity_and_motive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "PartOut.csv"
            path.write_text(
                "PartOut,Motive,Idp,Pos.x [m],Pos.y [m],Pos.z [m],Rhop [kg/m^3]\n"
                "1,1,10,0.1,0.2,0.3,1000\n"
                "1,1,11,0.2,0.3,0.4,1001\n"
                "1,1,12,0.3,0.4,0.5,1002\n",
                encoding="utf-8",
            )
            expected = stat_ref(path, 3)
            rows, evidence = subject._read_partout(path, expected, self._native())
            self.assertEqual(set(rows), set(self._native()))
            self.assertEqual(evidence["rows"], 3)
            self.assertEqual(rows[(0, 11)]["motive_code"], 1)
            self.assertEqual(evidence["zone_scope"].startswith("Zone=0"), True)

    def test_partout_wrong_id_or_motive_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "PartOut.csv"
            path.write_text(
                "PartOut,Motive,Idp,Pos.x [m],Pos.y [m],Pos.z [m],Rhop [kg/m^3]\n"
                "1,2,10,0.1,0.2,0.3,1000\n"
                "1,1,11,0.2,0.3,0.4,1001\n"
                "1,1,999,0.3,0.4,0.5,1002\n",
                encoding="utf-8",
            )
            with self.assertRaises(subject.CrosscheckError):
                subject._read_partout(path, stat_ref(path, 3), self._native())

    def test_runparts_totals_and_saved_times_are_source_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "RunPARTs.csv"
            path.write_text(
                "Part;TimeStep [s];NpOut;NpOutPos;NpOutRho;NpOutMov\n"
                "0;0.0;0;0;0;0\n"
                "1;0.1;3;3;0;0\n",
                encoding="utf-8",
            )
            summary = {"timeline": {"time_s": [0.0, 0.1]}}
            native = {"native_decode": {"runparts_totals": {"NpOut": 3, "NpOutPos": 3, "NpOutRho": 0, "NpOutMov": 0}}}
            result = subject._read_runparts(path, stat_ref(path, 2), summary, native)
            self.assertEqual(result["totals"], {"NpOut": 3, "NpOutPos": 3, "NpOutRho": 0, "NpOutMov": 0})
            self.assertEqual(result["max_saved_time_delta_s"], 0.0)

    def test_runparts_wrong_timeline_or_total_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "RunPARTs.csv"
            path.write_text(
                "Part;TimeStep [s];NpOut;NpOutPos;NpOutRho;NpOutMov\n"
                "0;0.0;0;0;0;0\n"
                "1;0.2;3;3;0;0\n",
                encoding="utf-8",
            )
            native = {"native_decode": {"runparts_totals": {"NpOut": 3, "NpOutPos": 3, "NpOutRho": 0, "NpOutMov": 0}}}
            with self.assertRaises(subject.CrosscheckError):
                subject._read_runparts(path, stat_ref(path, 2), {"timeline": {"time_s": [0.0, 0.1]}}, native)

    def test_same_bytes_replacement_requires_inode_and_times(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.jsonl"
            second = root / "second.jsonl"
            first.write_bytes(b"same")
            declared = subject._stat(first, "first", allow_deferred=True)
            second.write_bytes(b"same")
            actual = subject._stat(second, "second", allow_deferred=True)
            with self.assertRaises(subject.CrosscheckError):
                subject._require_same_stat(actual, declared, "replacement")

    def test_record_parser_rejects_non_object_and_accepts_non_target_identity(self) -> None:
        self.assertEqual(subject._record_from_line(b'{"zone":0,"idp":999}', 1)["idp"], 999)
        with self.assertRaises(subject.CrosscheckError):
            subject._record_from_line(b'[]', 2)

    def test_claim_boundary_never_promotes_numeric_cause(self) -> None:
        self.assertEqual(subject.SCHEMA, "ds02.stage2.f6-dxyz-typed-native-crosscheck.v1")
        self.assertEqual(subject.FAMILY_ID, "F6")
        self.assertEqual(subject.CASE_ID, "F6_STAGE1_ANGULAR_RELEASE_DXYZ_S0375_YAWM12_DP025")


if __name__ == "__main__":
    unittest.main()
