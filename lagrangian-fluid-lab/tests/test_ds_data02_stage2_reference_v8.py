"""v8 axis-selection and event binding checks."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ds_data02_stage2_observer_v6 import ObserverBindingError  # noqa: E402
from ds_data02_stage2_reference_v8 import (  # noqa: E402
    V4_EVENT_ADAPTER_V8_SCHEMA,
    adapt_v4_label_event_axis,
    evaluate_manual_predictions_v8,
)
from test_ds_data02_stage2_reference_v7 import _bundles  # noqa: E402


def test_v4_event_axis_adapter_selects_particle_event_axis_and_retains_pending_states():
    payload = {
        "schema": "ds02.stage2.observation-labels.v2",
        "first_passage_censor": [[1, 0], [1, 1]],
        "first_passage_interval": [[[0.0, 1.0], [1.0, 2.0]], [[0.0, 1.0], [1.0, 2.0]]],
        "first_passage_chord_time": [[float("nan"), 1.5], [float("nan"), float("nan")]],
        "crossing_count": [[0, 1], [0, 0]],
    }
    result = adapt_v4_label_event_axis(payload, event_index=1,
                                       initial_inside=[False, True],
                                       failed_before_observation=[False, False])
    assert result["schema"] == V4_EVENT_ADAPTER_V8_SCHEMA
    assert result["selected_event_axis"] == {"event_index": 1, "source_shape": [2, 2, 2]}
    assert [row["status"] for row in result["records"]] == ["observed", "initially_inside"]


def test_v8_rejects_config_path_or_saved_bracket_mismatch(tmp_path):
    reference, prediction, config_path, _ = _bundles(tmp_path)
    report = evaluate_manual_predictions_v8(reference, prediction, config_path)
    assert report["schema"] == "ds02.stage2.manual-observation-evaluation.v8"
    assert report["status"] == "PASS_DEVELOPMENT_OBSERVABLES_V8"
    prediction["events"][0]["saved_brackets"] = [[0.1, 1.0]]
    with pytest.raises(ObserverBindingError, match="saved brackets"):
        evaluate_manual_predictions_v8(reference, prediction, config_path)
    reference, prediction, config_path, _ = _bundles(tmp_path)
    prediction["config_binding"]["path"] = str(tmp_path / "other.json")
    with pytest.raises(ObserverBindingError, match="config_binding.path"):
        evaluate_manual_predictions_v8(reference, prediction, config_path)
