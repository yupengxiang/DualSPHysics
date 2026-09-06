from __future__ import annotations

import h5py
import numpy as np

from scripts import audit_quality


def write_valid_h5(path):
    valid = np.ones((2, 2), dtype=bool)
    with h5py.File(path, "w") as h5:
        h5.create_dataset("time", data=[0.0, 1.0])
        h5.create_dataset("particle_id", data=[10, 11])
        h5.create_dataset("particle_zone", data=[0, 0])
        h5.create_dataset("valid", data=valid)
        h5.create_dataset("position", data=np.zeros((2, 2, 3)))
        h5.create_dataset("velocity", data=np.zeros((2, 2, 3)))
        for name, value in (("density", 1000.0), ("mass", 1.0), ("pressure", 0.0)):
            h5.create_dataset(name, data=np.full((2, 2), value))
        h5.create_dataset("type", data=np.full((2, 2), 3))
        h5.create_dataset("mk", data=np.zeros((2, 2)))


def valid_audit():
    return {
        "mechanism": "closed-test", "hdf5": "case.h5", "frames": 2,
        "time_end": 1.0, "density_min": 999.0, "density_max": 1001.0,
        "particles_initial": 2, "particles_final": 2, "ids_common_first_last": 2,
        "identity_retention": 1.0, "excluded_particles": 0,
        "identity_key": "idp",
    }


def test_missing_audit_is_unknown():
    result = audit_quality.assess(None, 1.0, "completed")
    assert result["observed_status"] == "unknown"
    assert result["excluded_particles"] is None


def test_unknown_excluded_count_cannot_pass(tmp_path, monkeypatch):
    write_valid_h5(tmp_path / "case.h5")
    monkeypatch.setattr(audit_quality, "ROOT", tmp_path)
    audit = valid_audit()
    audit["excluded_particles"] = None
    result = audit_quality.assess(audit, 1.0, "completed")
    assert result["observed_status"] == "quality_failed"
    assert "excluded particle evidence is unknown" in result["issues"]


def test_reconcile_uses_registry_as_universe():
    registry = {"cases": [{"id": "planned", "origin": "custom",
                            "expected_outcome": "usable_probe"}]}
    evidence = {
        "custom": {"prepared": {}, "runs": {}, "audits": {}},
        "official": {"prepared": {}, "runs": {}, "audits": {}},
    }
    results, extra = audit_quality.reconcile(registry, evidence)
    assert extra == []
    assert results[0]["disposition"] == "missing_evidence"
    assert results[0]["missing_stages"] == ["prepare", "run", "audit"]


def test_expected_failure_is_explicit_not_silently_accepted():
    registry = {"cases": [{"id": "known_bad", "origin": "custom",
                            "expected_outcome": "quality_failed"}]}
    evidence = {
        "custom": {
            "prepared": {"known_bad": {"time_max": 1.0}},
            "runs": {"known_bad": {"status": "completed"}},
            "audits": {"known_bad": {"mechanism": "closed", "frames": 1,
                                        "excluded_particles": 4}},
        },
        "official": {"prepared": {}, "runs": {}, "audits": {}},
    }
    results, _ = audit_quality.reconcile(registry, evidence)
    assert results[0]["observed_status"] == "quality_failed"
    assert results[0]["disposition"] == "expected_failure"


def test_unplanned_evidence_is_reported():
    registry = {"cases": []}
    evidence = {
        "custom": {"prepared": {"surprise": {}}, "runs": {}, "audits": {}},
        "official": {"prepared": {}, "runs": {}, "audits": {}},
    }
    _, extra = audit_quality.reconcile(registry, evidence)
    assert extra == ["surprise"]
