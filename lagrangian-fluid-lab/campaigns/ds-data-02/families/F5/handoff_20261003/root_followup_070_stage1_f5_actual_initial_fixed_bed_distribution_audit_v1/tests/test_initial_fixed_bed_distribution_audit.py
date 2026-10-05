import importlib.util
from pathlib import Path

MODULE = Path(__file__).parents[1] / "scripts" / "initial_fixed_bed_distribution_audit.py"
spec = importlib.util.spec_from_file_location("fresh070_audit", MODULE)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def test_synthetic_source_only_audit():
    module._check()


def test_actual_metadata_binding_without_h5_digest():
    binding = Path(__file__).parents[1] / "binding.json"
    metadata = module.validate_binding(binding)
    assert metadata["actual_counts"] == {
        "total_particles": 214385,
        "fluid_particles": 40710,
        "frames": 51,
        "solver_dimension": 3,
    }
    assert metadata["h5_digest_declarations"]["digest_computed_by_worker"] is False


def test_request_is_disabled_and_has_no_expected_fluid_override():
    request = __import__("json").loads(
        (Path(__file__).parents[1] / "initial-fixed-bed-distribution-audit-request.json").read_text()
    )
    assert request["launch_allowed"] is False
    assert request["actual_inputs"]["trajectory_h5_sha256_declared_only"]
    assert "--expected-fluid" not in request["command"]
    assert request["diagnostic_contract"]["no_dynamic_acceptance"] is True
