import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from ds_data02_f6_terminal_floating_request_v1 import native_window, register


class SourceClosure(unittest.TestCase):
    def test_running_receipt_rejected_before_reading_native_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'receipt.json'
            source.write_text(json.dumps({'status': 'running', 'returncode': 0}))
            with self.assertRaisesRegex(ValueError, 'terminal'):
                register(source, Path(tmp) / 'output', 'test')
            self.assertFalse((Path(tmp) / 'output').exists())

    def test_failed_solver_rejected_before_reading_native_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'receipt.json'
            source.write_text(json.dumps({'status': 'completed', 'returncode': 1}))
            with self.assertRaisesRegex(ValueError, 'terminal'):
                register(source, Path(tmp) / 'output', 'test')

    def test_runtime_column_cannot_substitute_for_simulation_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'RunPARTs.csv'
            path.write_text('Part;TimeStep [s];SimRuntime [s];NpOut\n' +
                            ''.join(f'{i};{i * .01};{i * 100};0\n' for i in range(241)))
            with self.assertRaisesRegex(ValueError, '0..12'):
                native_window(path)

    def test_missing_native_part_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'RunPARTs.csv'
            path.write_text('Part;TimeStep [s];NpOut\n' +
                            ''.join(f'{i if i != 100 else 99};{i * .05};0\n' for i in range(241)))
            with self.assertRaisesRegex(ValueError, 'consecutive'):
                native_window(path)


if __name__ == '__main__':
    unittest.main()
