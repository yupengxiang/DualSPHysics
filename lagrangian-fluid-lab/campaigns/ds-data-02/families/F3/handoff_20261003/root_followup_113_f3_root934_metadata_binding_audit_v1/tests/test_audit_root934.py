import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve()
SCRIPT = HERE.parents[1] / "scripts" / "audit_root934.py"
spec = importlib.util.spec_from_file_location("audit_root934", SCRIPT)
audit_root934 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(audit_root934)


class Fresh113MetadataAuditTests(unittest.TestCase):
    def test_reservation_id_uses_full_case_attempt_identity(self):
        outer = {
            "family_id": "F5",
            "case_id": "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1",
            "physical_case_id": "F5_COMPACT_RUNUP_RECOVERY_C082S1_M085_T090",
            "attempt_id": "root-stage1-f5-case-full801-root934",
            "physical_condition_sha256": "a" * 64,
            "actual_converter_scope_sha256": "b" * 64,
        }
        wrapper = {
            "canonical_source_scope_sha256": "a" * 64,
            "actual_converter_scope_sha256": "b" * 64,
        }
        failures = []
        reservation = f"{outer['family_id']}/{outer['case_id']}/{outer['attempt_id']}"
        self.assertEqual(reservation, "F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1/root-stage1-f5-case-full801-root934")
        record = audit_root934._scope_record(outer, wrapper, {}, failures, "toy")
        self.assertEqual(record["scope_semantics"], "separate_distinct_values")
        self.assertEqual(failures, [])

    def test_manifest_n3_metadata_contract_is_not_science_io(self):
        outer = {"expected_frames": 7, "expected_particles": 11}
        wrapper = {"family_id": "F2", "case_id": "C", "physical_case_id": "P"}
        manifest = {
            "schema": audit_root934.MANIFEST_SCHEMA,
            "family_id": "F2",
            "case_id": "C",
            "physical_case_id": "P",
            "frames": 7,
            "particles": 11,
            "actual_geometry": {"dimension": 3},
            "fields": {
                "position": {"shape": [7, 11, 3]},
                "velocity": {"shape": [7, 11, 3]},
            },
            "xmf_shape_contract": "full7 position and velocity N3 vectors",
            "xdmf": str(Path(tempfile.gettempdir()) / "toy.xmf"),
        }
        failures = []
        with tempfile.TemporaryDirectory() as tmp:
            xmf = Path(tmp) / "toy.xmf"
            xmf.write_text("<Xdmf/>", encoding="utf-8")
            manifest["xdmf"] = str(xmf)
            record = audit_root934._manifest_contract(outer, wrapper, manifest, failures, "toy")
        self.assertTrue(record["n3_position_velocity"])
        self.assertEqual(failures, [])

    def test_payload_paths_are_never_loaded(self):
        with self.assertRaises(audit_root934.AuditError):
            audit_root934.load_json(Path("/tmp/scientific.h5"))

    def test_registered_entry_static_success_gate(self):
        root932 = Path(
            "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
            "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
            "root_stage1_delegated112_NVMe3GiB_renderer_library_adoption_"
            "registered_exit_contract_932"
        )
        entry = audit_root934._entry_contract(root932 / "registered_render_entry.py")
        self.assertTrue(entry["success_gate_pass"])


if __name__ == "__main__":
    unittest.main()
