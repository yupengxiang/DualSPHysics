from scripts.w12_freeze_audit import learning_gate_policy


def test_learning_degradation_is_diagnostic_not_scene_admission():
    policy = learning_gate_policy()
    assert policy["status"] == "diagnostic_only"
    assert policy["scene_admission_independent"] is True
    assert "report degradation relative to constant velocity" in policy["requirements"]
    assert "never a physical-scene admission gate" in policy["policy"]
