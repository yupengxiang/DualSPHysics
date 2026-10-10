#!/usr/bin/env python3
"""Bounded tests for the source-only native MassFluid contract.

The tests use JSON fixtures only.  They do not import h5py, open HDF5/BI4
payloads, or rely on a production receipt.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("ds_data02_stage2_native_massfluid_contract_v1.py")
SPEC = importlib.util.spec_from_file_location("native_massfluid_contract_v1", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class NativeMassFluidContractTests(unittest.TestCase):
    def test_nontrivial_calibration_preserves_float32_widening_and_units_boundary(self):
        fixture = MODULE.calibration_fixture()
        mass = fixture["massfluid_xml"]
        self.assertNotEqual(mass["value"], mass["float32_widened_value"])
        self.assertEqual(mass["binary64_little_hex"], "000000009a54463f")
        self.assertEqual(fixture["arrays"]["position"]["unit"], "m")
        self.assertEqual(fixture["arrays"]["pressure"]["authority"], "H5_protocol_declaration_only")
        self.assertEqual(fixture["h5_units_attr_authority"], "DECLARATION_ONLY")

    def _contract(self):
        return {
            "schema": MODULE.CONTRACT_SCHEMA,
            "physical_case_id": "TINY_NATIVE_CASE",
            "producer_binding": {"proof": {"sha256": "a" * 64}, "raw_massfluid_comparison": {"raw_bytes_hex": "000000009a54463f"}},
        }

    def _observation(self, contract_sha: str, **overrides):
        value = {
            "schema": MODULE.OBSERVATION_SCHEMA,
            "contract_sha256": contract_sha,
            "physical_case_id": "TINY_NATIVE_CASE",
            "status": "INITIAL_FLUID_SCALAR_BOUND",
            "massfluid_value_kg": 0.000681472010910511,
            "massfluid_bits_hex": "000000009a54463f",
            "source_kind": "single_header_scalar",
            "aggregation": "none",
            "mass_estimator": "single_header_scalar",
            "initial_fluid_identity": {"status": "EXPLICIT_FLUID_ROLE_IDENTITY", "identity_key": "(Zone,Idp)", "fluid_id_count": 3},
            "producer_refs": {"proof_sha256": "a" * 64},
        }
        value.update(overrides)
        return value

    def test_bound_scalar_requires_exact_bits_and_explicit_fluid_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract_path = root / "contract.json"
            MODULE.atomic_json(contract_path, self._contract())
            contract_sha = MODULE.sha256_file(contract_path)
            obs_path = root / "observation.json"
            out_path = root / "out.json"
            MODULE.atomic_json(obs_path, self._observation(contract_sha))
            result = MODULE.verify_observation(contract_path, obs_path, out_path)
            self.assertEqual(result["status"], "COMPLETED_INITIAL_FLUID_MASSFLUID_SOURCE_BOUND_NO_SCIENTIFIC_CREDIT")
            self.assertEqual(result["native_massfluid"]["bits_hex"], "000000009a54463f")

    def test_dynamic_mass_is_explicit_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract_path = root / "contract.json"
            MODULE.atomic_json(contract_path, self._contract())
            observation = self._observation(MODULE.sha256_file(contract_path), status="DYNAMIC_MASS_NO_INITIAL_IDENTITY")
            obs_path = root / "observation.json"
            out_path = root / "out.json"
            MODULE.atomic_json(obs_path, observation)
            result = MODULE.verify_observation(contract_path, obs_path, out_path)
            self.assertEqual(result["native_massfluid"]["value_kg"], None)
            self.assertEqual(result["native_massfluid"]["status"], "DYNAMIC_MASS_NO_INITIAL_IDENTITY")

    def test_average_or_wrong_bits_cannot_be_credited(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract_path = root / "contract.json"
            MODULE.atomic_json(contract_path, self._contract())
            contract_sha = MODULE.sha256_file(contract_path)
            for index, overrides in enumerate(({"mass_estimator": "role_average"}, {"massfluid_bits_hex": "6a7b00fa9954463f"})):
                obs_path = root / ("observation-" + str(index) + ".json")
                out_path = root / ("out-" + str(index) + ".json")
                MODULE.atomic_json(obs_path, self._observation(contract_sha, **overrides))
                with self.assertRaises(MODULE.MassFluidContractError):
                    MODULE.verify_observation(contract_path, obs_path, out_path)

    def test_missing_fluid_identity_is_rejected_even_for_correct_scalar(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract_path = root / "contract.json"
            MODULE.atomic_json(contract_path, self._contract())
            contract_sha = MODULE.sha256_file(contract_path)
            observation = self._observation(contract_sha, initial_fluid_identity={"status": "UNKNOWN"})
            obs_path = root / "observation.json"
            out_path = root / "out.json"
            MODULE.atomic_json(obs_path, observation)
            with self.assertRaises(MODULE.MassFluidContractError):
                MODULE.verify_observation(contract_path, obs_path, out_path)


if __name__ == "__main__":
    unittest.main()
