#!/usr/bin/env python3
"""Toy-only tests for the fresh168 full-time CSV contract.

These tests synthesize small temporary CSVs and never open a DS-DATA-02
scientific file or invoke FloatingInfo.
"""
from __future__ import annotations

import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
WORKER_PATH = HERE / "workers" / "run_fulltime_floatinginfo_fresh168.py"
SPEC = importlib.util.spec_from_file_location("fresh168_worker", WORKER_PATH)
assert SPEC is not None and SPEC.loader is not None
WORKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORKER)


HEADERS = [
    "part",
    "time [s]",
    "fvel.x [m/s]",
    "fvel.y [m/s]",
    "fvel.z [m/s]",
    "fomega.x [rad/s]",
    "fomega.y [rad/s]",
    "fomega.z [rad/s]",
    "center.x [m]",
    "center.y [m]",
    "center.z [m]",
    "surge [m]",
    "sway [m]",
    "heave [m]",
    "roll [deg]",
    "pitch [deg]",
    "yaw [deg]",
]


def _rows(count: int = 241) -> list[list[str]]:
    result: list[list[str]] = []
    for index in range(count):
        values = ["60", f"{index * 0.05:.12g}"] + ["0"] * (len(HEADERS) - 2)
        result.append(values)
    return result


def _write_csv(path: Path, rows: list[list[str]], headers: list[str] | None = None) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter=";")
        writer.writerow(headers or HEADERS)
        writer.writerows(rows)


EXPECTED = {
    "delimiter": ";",
    "expected_rows": 241,
    "first_frame": 0,
    "last_frame": 240,
    "only_mk": 60,
    "expected_start_s": 0.0,
    "expected_end_s": 12.0,
    "terminal_tolerance_s": 0.2,
    "nominal_tout_s": 0.05,
    "native_time_tolerance_s": 1e-6,
    "native_times_s": [index * 0.05 for index in range(241)],
    "native_time_source": "toy",
    "require_native_times": True,
    "part_contract": {"pilot_required": True, "mode": "constant_marker", "expected_values": [60]},
}


class FulltimeFloatingInfoToyTests(unittest.TestCase):
    def test_valid_full_contract_with_preamble(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "valid.csv"
            with path.open("w", encoding="utf-8", newline="") as stream:
                stream.write("official preamble\n")
                writer = csv.writer(stream, delimiter=";")
                writer.writerow(HEADERS)
                writer.writerows(_rows())
            parsed = WORKER._parse_full_csv(path, EXPECTED)
            self.assertEqual(parsed["rows_examined"], 241)
            self.assertEqual(parsed["row_ordinals"], list(range(241)))
            self.assertEqual(parsed["part_values_observed"], [60])
            self.assertTrue(parsed["strictly_increasing_time"])
            self.assertAlmostEqual(parsed["last_time_s"], 12.0)

    def test_native_time_shift_beyond_six_decimal_tolerance_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "native-time-shift.csv"
            rows = _rows()
            rows[80][1] = f"{80 * 0.05 + 2e-6:.12g}"
            _write_csv(path, rows)
            with self.assertRaises(WORKER.WorkerError):
                WORKER._parse_full_csv(path, EXPECTED)

    def test_truncated_output_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "truncated.csv"
            _write_csv(path, _rows(240))
            with self.assertRaises(WORKER.WorkerError):
                WORKER._parse_full_csv(path, EXPECTED)

    def test_nonfinite_value_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nonfinite.csv"
            rows = _rows()
            rows[17][5] = "nan"
            _write_csv(path, rows)
            with self.assertRaises(WORKER.WorkerError):
                WORKER._parse_full_csv(path, EXPECTED)

    def test_nonmonotonic_time_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nonmonotonic.csv"
            rows = _rows()
            rows[20][1] = rows[19][1]
            _write_csv(path, rows)
            with self.assertRaises(WORKER.WorkerError):
                WORKER._parse_full_csv(path, EXPECTED)

    def test_missing_or_wrong_units_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wrong-units.csv"
            headers = list(HEADERS)
            headers[2] = "fvel.x [m]"
            _write_csv(path, _rows(), headers)
            with self.assertRaises(WORKER.WorkerError):
                WORKER._parse_full_csv(path, EXPECTED)

    def test_wrong_part_marker_is_rejected_after_pilot_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wrong-part.csv"
            rows = _rows()
            rows[0][0] = "61"
            _write_csv(path, rows)
            with self.assertRaises(WORKER.WorkerError):
                WORKER._parse_full_csv(path, EXPECTED)

    def test_duplicate_frame_part_is_rejected_when_pilot_binds_frame_indices(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate-frame-part.csv"
            rows = _rows()
            for index, row in enumerate(rows):
                row[0] = str(index)
            rows[100][0] = "99"
            expected = dict(EXPECTED)
            expected["part_contract"] = {"pilot_required": True, "mode": "frame_index", "expected_values": list(range(241))}
            _write_csv(path, rows)
            with self.assertRaises(WORKER.WorkerError):
                WORKER._parse_full_csv(path, expected)


if __name__ == "__main__":
    unittest.main()
