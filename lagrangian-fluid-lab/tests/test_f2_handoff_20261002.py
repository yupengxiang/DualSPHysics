"""Static and evidence-bound checks for the isolated F2 Gem handoff.

These tests never launch GenCase or a solver.  The six completed GenCase and
the structural audit are external evidence; the tests only check their frozen
manifest semantics and, when the evidence tree is present, its bound report.
They deliberately do not turn the structural report into QI, QN, or a
production verdict.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import unittest


LAB_ROOT = Path(__file__).resolve().parents[1]
FAMILY_ROOT = LAB_ROOT / "campaigns/ds-data-02/families/F2"
HANDOFF_ROOT = FAMILY_ROOT / "handoff_20261002"
V2_ROOT = HANDOFF_ROOT / "gridphase_v2"
MANIFEST_PATH = V2_ROOT / "manifest.json"
SIDECAR_PATH = HANDOFF_ROOT / "audits/mass-semantics-correction-20261002.json"
EXTERNAL_REPORT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/"
    "F2H10V2_INITIAL_AUDIT/f2h10v2-initial-audit-20261002-001/report/"
    "gem-handoff-initial-structure-audit.json"
)


def load_generator_module():
    path = FAMILY_ROOT / "f2_handoff_20261002_v2.py"
    spec = importlib.util.spec_from_file_location("f2_handoff_20261002_v2", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class F2Handoff20261002Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generator = load_generator_module()
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.sidecar = json.loads(SIDECAR_PATH.read_text(encoding="utf-8"))

    def test_manifest_is_two_physical_mothers_with_three_resolution_views(self) -> None:
        self.assertEqual(self.manifest["schema"], "ds-data-02.f2.gem-handoff-20261002-manifest.v1")
        self.assertEqual(self.manifest["qualification_claim"], "none")
        self.assertEqual(self.manifest["production_claim"], "none")
        self.assertEqual(self.manifest["registry_role"], "new_scope_new_physical_mothers_outside_original_F2_48_registry")
        cases = self.manifest["cases"]
        self.assertEqual(len(cases), 6)
        by_physical: dict[str, list[dict]] = {}
        for case in cases:
            by_physical.setdefault(case["physical_case_id"], []).append(case)
        self.assertEqual(set(by_physical), {"F2H10V2_CENTER_V1", "F2H10V2_OFFSET_V1"})
        self.assertEqual({case["background"] for case in by_physical["F2H10V2_CENTER_V1"]}, {"center_catch"})
        self.assertEqual({case["background"] for case in by_physical["F2H10V2_OFFSET_V1"]}, {"offset_spill"})
        for physical_cases in by_physical.values():
            self.assertEqual({case["resolution"] for case in physical_cases}, {"coarse", "medium", "fine"})

    def test_cell_center_geometry_is_commensurate_without_rescaling(self) -> None:
        generator = self.generator
        self.assertAlmostEqual(generator.LIQUID_VOLUME_M3, 0.32 * 0.24 * 0.32, places=15)
        self.assertEqual(generator.SOURCE_BAND_COUNT, 3)
        self.assertAlmostEqual(generator.SOURCE_BAND_WIDTH * 3, generator.FLUID_SIZE[1], places=15)
        expected_counts = {"coarse": 384, "medium": 3072, "fine": 24576}
        for resolution, dp in generator.RESOLUTIONS.items():
            expected = generator.expected_population(dp)
            self.assertEqual(expected["total_particle_count"], expected_counts[resolution])
            self.assertLessEqual(abs(expected["relative_mass_error"]), generator.MASS_BUDGET_FRACTION)
            origin = generator.GRID_ORIGINS[resolution]
            for coordinate, low in zip(origin, (-1.2, -1.0, -0.2)):
                self.assertLessEqual(coordinate, low)
            for axis, (low, origin_coordinate) in enumerate(zip(generator.FLUID_LOW, origin)):
                index = (low + dp / 2.0 - origin_coordinate) / dp
                self.assertAlmostEqual(index, round(index), places=10, msg=f"{resolution} axis {axis}")

    def test_frozen_source_assets_are_exact_integration_bytes(self) -> None:
        expected = {
            "F2_GEM_CENTER_P01_Def.xml": "9e499e5e988d50aecf3ac2765f3222e784cc7aa305f0f19d38414ffa061a9840",
            "F2_GEM_OFFSET_P01_Def.xml": "a408d8df645f496ddfeaaa4ff3b021673bf29958883817239c708dd2ec7d65b2",
            "F2_GEM_CENTER_P01_motion.dat": "ff966330e01e565987ebf182a7dfd7401d76577ae1c266894fc7db4aa34c5b70",
            "F2_GEM_OFFSET_P01_motion.dat": "ff966330e01e565987ebf182a7dfd7401d76577ae1c266894fc7db4aa34c5b70",
        }
        for name, digest in expected.items():
            path = HANDOFF_ROOT / "source_assets" / name
            self.assertEqual(sha256(path), digest, name)
        for definition in HANDOFF_ROOT.joinpath("source_assets").glob("*_Def.xml"):
            text = definition.read_text(encoding="utf-8")
            self.assertIn("<motion", text)
            self.assertIn("<setmkbound", text)
            self.assertIn("TimeMax", text)

    def test_physical_hashes_are_resolution_invariant_and_background_specific(self) -> None:
        metadata = {}
        for path in V2_ROOT.joinpath("definitions").glob("*/*.metadata.json"):
            metadata[path] = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(metadata), 6)
        by_background: dict[str, list[dict]] = {"center_catch": [], "offset_spill": []}
        for value in metadata.values():
            by_background[value["background"]].append(value)
        self.assertEqual({len(items) for items in by_background.values()}, {3})
        for items in by_background.values():
            self.assertEqual({item["physical_geometry_control_hash"] for item in items}, {items[0]["physical_geometry_control_hash"]})
            self.assertEqual(len({item["numerical_recipe_hash"] for item in items}), 3)
        self.assertNotEqual(
            by_background["center_catch"][0]["physical_geometry_control_hash"],
            by_background["offset_spill"][0]["physical_geometry_control_hash"],
        )

    def test_mass_sidecar_keeps_strict_budget_semantics_explicit(self) -> None:
        self.assertEqual(self.sidecar["status"], "EVIDENCE_BOUND_CORRECTION_NO_QUALIFICATION")
        self.assertEqual(self.sidecar["frozen_geometry"]["frozen_mass_budget_fraction"], 1e-12)
        self.assertEqual(len(self.sidecar["observed_cases"]), 6)
        self.assertTrue(self.sidecar["interpretation"]["no_normalization"])
        coarse_or_medium = [
            item for item in self.sidecar["observed_cases"] if item["resolution"] in {"coarse", "medium"}
        ]
        self.assertTrue(all("FAILS_1E-12" in item["native_or_csv_strict_budget_result"] for item in coarse_or_medium))
        fine = [item for item in self.sidecar["observed_cases"] if item["resolution"] == "fine"]
        self.assertTrue(all("WITHIN_1E-12" in item["native_or_csv_strict_budget_result"] for item in fine))
        self.assertEqual(self.sidecar["interpretation"]["qualification_decision"], "PENDING_SEPARATE_QI_AND_NUMERICAL_MASS_REVIEW")

    @unittest.skipUnless(EXTERNAL_REPORT.is_file(), "shared-runner evidence tree is not present")
    def test_actual_v2_report_has_six_structural_3d_cases_only(self) -> None:
        report = json.loads(EXTERNAL_REPORT.read_text(encoding="utf-8"))
        self.assertEqual(sha256(EXTERNAL_REPORT), self.sidecar["source_report"]["sha256"])
        self.assertEqual(report["status"], "PASS_INITIAL_STRUCTURE")
        self.assertEqual(report["qualification_claim"], "none")
        self.assertEqual(report["production_claim"], "none")
        self.assertEqual(len(report["cases"]), 6)
        for case in report["cases"]:
            self.assertEqual(case["status"], "PASS_INITIAL_STRUCTURE")
            self.assertEqual(case["receipt"]["dimension"], 3)
            self.assertEqual(case["fluid_mks"], [1, 2, 3])
            self.assertEqual(case["fluid_boundary_overlap_count"], 0)
            self.assertEqual(case["typed_id_duplicates"], 0)
            self.assertEqual(case["fluid_position_duplicates"], 0)
            self.assertTrue(all(case["wall_evidence"][wall]["finite_faces_pass"] for wall in ("cup", "receiver", "tray")))

    def test_legacy_root_cause_remains_immutable_negative_evidence(self) -> None:
        path = HANDOFF_ROOT / "audits/legacy-root-cause-20261002.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "ROOT_CAUSE_CONFIRMED")
        self.assertTrue(all(case["checks"]["not_a_denominator_typo"] for case in report["cases"]))
        self.assertTrue(all(case["checks"]["inclusive_lattice_mismatch_is_reproduced"] for case in report["cases"]))
        self.assertTrue(all(case["receipt_consistency_label_ignored"] for case in report["cases"]))


if __name__ == "__main__":
    unittest.main()
