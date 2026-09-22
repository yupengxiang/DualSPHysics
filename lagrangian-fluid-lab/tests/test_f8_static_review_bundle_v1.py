from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from scripts.f8_static_review_bundle_v1 import (
    OUTPUT,
    build_bundle,
    validate_observation_payload,
)


ROOT = Path(__file__).resolve().parents[1]


def _payload(time_count=4, profile_count=3):
    return {
        "time_s": np.arange(time_count, dtype=float),
        "center_velocity_mps": np.zeros(time_count),
        "profile_z_m": np.linspace(-0.045, 0.045, profile_count),
        "profile_velocity_mps": np.zeros((time_count, profile_count)),
        "mean_flux_m3_s_per_m": np.zeros(time_count),
    }


def test_bundle_freezes_13_plus_2_and_preserves_no_execution_state() -> None:
    bundle = build_bundle()
    assert bundle["schema"] == "core.cfd.f8.static_review_bundle.v1"
    assert bundle["status"] == "static_review_bundle_pending_root_decision"
    assert bundle["qualification_credit"] == 0
    matrix = bundle["qualification_matrix"]
    assert matrix["planned_row_count"] == 15
    assert matrix["physical_spatial_row_count"] == 13
    assert matrix["control_row_count"] == 2
    assert len(matrix["rows"]) == 15
    assert bundle["scope_interpretation"]["decision"] == "pending_root_decision"
    assert bundle["definition_semantics"]["materialization"]["definition_written"] is False
    assert bundle["transient_boundary"]["steady_oracle_supports_startup_decay"] is False
    controls = bundle["execution_controls"]
    assert all(value is False for value in controls.values() if isinstance(value, bool))
    assert all(value == 0 for key, value in controls.items() if key.endswith("_mutation"))


def test_bundle_artifact_is_current_and_hash_bound() -> None:
    assert OUTPUT.is_file()
    bundle = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert bundle["schema"] == "core.cfd.f8.static_review_bundle.v1"
    assert len(bundle["bindings"]) == 6
    for row in bundle["bindings"]:
        path = ROOT / row["path"]
        assert path.is_file(), row["path"]
        assert path.stat().st_size == row["bytes"]


def test_observation_payload_contract_validates_shapes_and_order() -> None:
    assert validate_observation_payload(_payload()) == {"time_count": 4, "profile_count": 3}
    bad = _payload()
    bad["time_s"] = np.array([0.0, 1.0, 1.0, 2.0])
    with pytest.raises(ValueError, match="strictly increasing"):
        validate_observation_payload(bad)
    bad = _payload()
    bad["profile_velocity_mps"] = np.zeros((4, 2))
    with pytest.raises(ValueError, match="shape"):
        validate_observation_payload(bad)
