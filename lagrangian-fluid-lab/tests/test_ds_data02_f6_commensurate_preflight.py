import json
import unittest
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
MOTHER = LAB / "campaigns/ds-data-02/families/F6/handoff_20261002/commensurate_mother"
AUDIT_ROOT = MOTHER / "partvtk_002"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class CommensuratePreflightTests(unittest.TestCase):
    def test_all_six_initial_typed_audits_are_strict(self):
        audit = read_json(AUDIT_ROOT / "strict_partvtk_audit.json")
        self.assertEqual(audit["status"], "all_three_dp_preflight_pass")
        self.assertEqual(len(audit["cases"]), 6)
        for case in audit["cases"]:
            self.assertTrue(all(case["checks"].values()), case["case_id"])
            self.assertEqual(case["gencase"]["solver_dimension_from_gencase"], 3)
            self.assertEqual(case["actual_type_counts"]["fluid"], case["expected"]["fluid_particles"])
            self.assertLess(abs(case["mass_error_relative_to_frozen_continuous_domain"]), 0.01)

    def test_rigid_preflight_keeps_massbody_and_massbound_separate(self):
        result = read_json(AUDIT_ROOT / "rigid_state_preflight.json")
        self.assertEqual(result["status"], "all_six_typed_initial_rigid_preflight_pass")
        self.assertEqual(len(result["records"]), 6)
        for record in result["records"]:
            particle = record["type2_massbound_particle_audit"]
            native = record["native_aggregate_contract"]
            geometry = record["initial_geometry_audit"]
            self.assertTrue(particle["nonzero_inertia"])
            self.assertTrue(particle["is_not_native_aggregate_mass"])
            self.assertEqual(native["massbody_kg"], 128.0)
            self.assertGreater(geometry["body_fluid_gap_m"], 0.0)
            self.assertTrue(geometry["no_type3_body_overlap_by_z"])

    def test_solver_requests_are_root_only_and_use_completed_gencase_cwd(self):
        manifest = read_json(AUDIT_ROOT / "qualification_request_manifest.json")
        self.assertEqual(manifest["status"], "root_dispatch_pending")
        self.assertEqual(len(manifest["requests"]), 6)
        for row in manifest["requests"]:
            request = read_json(Path(row["path"]))
            self.assertEqual(request["solver_launch_authority"].split()[0], "root")
            self.assertTrue(request["cwd"].endswith("_GENCASE_001"), request["cwd"])
            self.assertEqual(request["complete_event_window_s"], [0.0, 12.0])
            self.assertEqual(request["output_interval_s"], 0.05)
            self.assertEqual(request["q_n_status"], "pending")
            self.assertEqual(request["command"][-2:], ["-tmax:12", "-tout:0.05"])


if __name__ == "__main__":
    unittest.main()
