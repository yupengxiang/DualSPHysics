import importlib.util
from pathlib import Path


ROOT = Path(__file__).parents[1]


def load_module():
    path = ROOT / "experiments/r3_g4_causality_audit.py"
    spec = importlib.util.spec_from_file_location("r3_g4_causality_audit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_synthetic_cpu_audit_covers_prefix_time_control_body_and_clipping():
    report = load_module().run_audit()
    assert report["execution_status"] == "complete"
    assert all(check["pass"] for check in report["checks"].values())
    assert report["checks"]["prefix_invariance"]["max_feature_abs_diff"] == 0.0
    assert report["checks"]["time_endpoint_invariance"]["max_feature_abs_diff"] == 0.0
    assert report["checks"]["prescribed_control_causality"]["frame_zero_control_velocity"] == [0.0, 0.0, 0.0]
    clipping = report["checks"]["clipping_disclosure"]
    assert clipping["clipped_component_count"] > 0
    assert clipping["clipping_component_count"] > 0
    assert clipping["clipped_component_fraction"] == 1.0
    assert clipping["clipping_trigger_rate"] == clipping["clipped_component_fraction"]
    assert clipping["clipped_component_fraction"] == (
        clipping["clipped_component_count"] / clipping["clipping_component_count"]
    )


def test_audit_explicitly_keeps_constant_velocity_out_of_admission_gate():
    report = load_module().run_audit()
    policy = report["checks"]["constant_velocity_not_admission_gate"]
    assert policy["constant_velocity_gate"] is False
    assert "never a physical-scene admission gate" in policy["policy"]
