#!/usr/bin/env python3
"""CLI tests for the manufactured official MassFluid writer/reader chain.

The subprocess exercises the real C++ JBinaryData writer and the pinned
``bi4_dump`` decoder on a temporary BI4 fixture.  It never opens a
DS-DATA-02 production payload and the resulting evidence is explicitly
non-production calibration only.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("ds_data02_native_massfluid_official_tiny_chain_v1.py")
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")


class NativeMassFluidOfficialTinyChainTests(unittest.TestCase):
    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [str(VENV), "-B", str(SCRIPT), *args],
            cwd=SCRIPT.parents[2],
            text=True,
            capture_output=True,
            check=False,
        )
        if check and result.returncode != 0:
            self.fail(f"CLI failed ({result.returncode}): {result.stderr}\n{result.stdout}")
        return result

    def _chain(self, root: Path) -> tuple[Path, Path, Path]:
        prepared = root / "prepared"
        attempt = root / "attempt"
        report = root / "report.json"
        verification = root / "verification.json"
        self._run("prepare", "--output-dir", str(prepared))
        manifest = prepared / "native-massfluid-official-tiny-chain-manifest.json"
        self._run(
            "run", "--manifest", str(manifest), "--attempt-root", str(attempt),
            "--output", str(report),
        )
        self._run(
            "verify", "--manifest", str(manifest), "--report", str(report),
            "--output", str(verification),
        )
        return manifest, report, verification

    def test_real_writer_reader_decoder_cli_is_manufactured_only(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, report, verification = self._chain(Path(directory))
            value = json.loads(report.read_text(encoding="utf-8"))
            checked = json.loads(verification.read_text(encoding="utf-8"))
            self.assertEqual(value["status"], "COMPLETED_MANUFACTURED_SERIALIZATION_CALIBRATION_ONLY")
            self.assertFalse(value["production_eligible"])
            self.assertEqual(value["scientific_credit"], 0)
            self.assertEqual(value["writer_reader"]["observed"]["idp_count"], 2)
            self.assertEqual(value["decoder"]["array_types"]["Mass"], "float")
            self.assertEqual(checked["status"], "VERIFIED_MANUFACTURED_SERIALIZATION_ONLY")
            self.assertFalse(checked["production_eligible"])
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["read_policy"]["production_payload_opened"], False)

    def test_verifier_rejects_boundary_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, report, _ = self._chain(Path(directory))
            value = json.loads(report.read_text(encoding="utf-8"))
            value["production_eligible"] = True
            report.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            result = self._run(
                "verify", "--manifest", str(manifest), "--report", str(report),
                "--output", str(Path(directory) / "rejected.json"), check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("manufactured calibration boundary", result.stderr)


if __name__ == "__main__":
    unittest.main()
