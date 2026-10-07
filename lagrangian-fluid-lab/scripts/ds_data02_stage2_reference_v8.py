#!/usr/bin/env python3
"""Small additive v8 hardening layer over the consumed v6/v7 interfaces."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from ds_data02_stage2_observer_v6 import (  # noqa: E402
    ObserverBindingError,
    adapt_v4_label_payload,
)
from ds_data02_stage2_reference_v7 import (  # noqa: E402
    evaluate_manual_predictions_v7,
    load_frozen_observer_config,
)


STRICT_EVALUATION_V8_SCHEMA = "ds02.stage2.manual-observation-evaluation.v8"
V4_EVENT_ADAPTER_V8_SCHEMA = "ds02.stage2.v4-label-event-adapter.v2"


def adapt_v4_label_event_axis(payload: Mapping[str, Any], *, event_index: int = 0,
                              initial_inside: Sequence[bool] | None = None,
                              failed_before_observation: Sequence[bool] | None = None,
                              crossing_candidates_s: Sequence[Sequence[float]] | None = None,
                              hidden_recross_status: str = "UNRESOLVED") -> dict[str, Any]:
    """Select a real v4 ``(particle,event)`` axis before applying v6 rules."""
    if not isinstance(event_index, int) or isinstance(event_index, bool) or event_index < 0:
        raise ObserverBindingError("event_index must be a nonnegative integer")
    if not isinstance(payload, Mapping):
        raise ObserverBindingError("v4 label payload must be an object")
    intervals = np.asarray(payload.get("first_passage_interval"))
    if intervals.ndim != 3 or intervals.shape[2] != 2 or event_index >= intervals.shape[1]:
        raise ObserverBindingError("v4 first_passage_interval must have shape (n,event,2)")
    selected: dict[str, Any] = {
        "schema": payload.get("schema", "ds02.stage2.observation-labels.v2"),
        "first_passage_interval": intervals,
    }
    for name in ("first_passage_censor", "first_passage_chord_time", "crossing_count"):
        if name not in payload:
            raise ObserverBindingError(f"v4 payload is missing {name}")
        array = np.asarray(payload[name])
        if array.ndim != 2 or array.shape[0] != intervals.shape[0] or event_index >= array.shape[1]:
            raise ObserverBindingError(f"v4 {name} must have shape (n,event)")
        selected[name] = array[:, event_index]
    adapted = adapt_v4_label_payload(
        selected, event_index=event_index, initial_inside=initial_inside,
        failed_before_observation=failed_before_observation,
        crossing_candidates_s=crossing_candidates_s,
        hidden_recross_status=hidden_recross_status,
    )
    adapted["schema"] = V4_EVENT_ADAPTER_V8_SCHEMA
    adapted["selected_event_axis"] = {"event_index": event_index, "source_shape": list(intervals.shape)}
    return adapted


def _event_map(bundle: Mapping[str, Any], name: str) -> dict[tuple[str, str], Mapping[str, Any]]:
    events = bundle.get("events")
    if not isinstance(events, list):
        raise ObserverBindingError(f"{name}.events is required")
    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    for index, record in enumerate(events):
        if not isinstance(record, Mapping):
            raise ObserverBindingError(f"{name}.events[{index}] is not an object")
        event_id, region = record.get("event_id"), record.get("source_region_id")
        if not isinstance(event_id, str) or not event_id or not isinstance(region, str) or not region:
            raise ObserverBindingError(f"{name}.events[{index}] needs event_id/source_region_id")
        key = (event_id, region)
        if key in result:
            raise ObserverBindingError(f"{name} has duplicate source-region event identity")
        brackets = record.get("saved_brackets", [])
        if not isinstance(brackets, list):
            raise ObserverBindingError(f"{name}.events[{index}].saved_brackets is required")
        for pair in brackets:
            if (not isinstance(pair, list) or len(pair) != 2
                    or not isinstance(pair[0], (int, float)) or not isinstance(pair[1], (int, float))
                    or not float(pair[1]) > float(pair[0])):
                raise ObserverBindingError(f"{name}.events[{index}] has an invalid saved bracket")
        result[key] = record
    return result


def evaluate_manual_predictions_v8(reference: Mapping[str, Any], prediction: Mapping[str, Any],
                                   frozen_config_path: Path | str) -> dict[str, Any]:
    """Run v7 after enforcing exact config path and event-bracket semantics."""
    for name, bundle in (("reference", reference), ("prediction", prediction)):
        config_binding = bundle.get("config_binding") if isinstance(bundle, Mapping) else None
        if not isinstance(config_binding, Mapping):
            raise ObserverBindingError(f"{name}.config_binding is required")
        bound_path = str(Path(str(config_binding.get("path", ""))).expanduser().resolve())
        if bound_path != str(Path(frozen_config_path).expanduser().resolve()):
            raise ObserverBindingError(f"{name}.config_binding.path differs from compare config")
    config = load_frozen_observer_config(frozen_config_path,
                                         str(reference["config_binding"]["sha256"]))
    ref_events = _event_map(reference, "reference")
    pred_events = _event_map(prediction, "prediction")
    if set(ref_events) != set(pred_events):
        raise ObserverBindingError("reference and prediction source-region event axes differ")
    for key in sorted(ref_events):
        expected, actual = ref_events[key], pred_events[key]
        if expected.get("saved_brackets") != actual.get("saved_brackets"):
            # Bracket geometry is part of the saved-frame observation and must
            # remain visible to a reviewer even when event times are close.
            raise ObserverBindingError(f"event {key} saved brackets differ")
        if expected.get("status") == "observed":
            feature = expected.get("feature_time_s")
            if not isinstance(feature, (int, float)) or isinstance(feature, bool) or not float(feature) > 0:
                raise ObserverBindingError(f"event {key} needs positive feature_time_s")
            for name, record in (("reference", expected), ("prediction", actual)):
                time = record.get("event_time_s")
                if not isinstance(time, (int, float)) or isinstance(time, bool):
                    raise ObserverBindingError(f"{name} event {key} needs numeric event_time_s")
                if not any(float(pair[0]) <= float(time) <= float(pair[1]) for pair in expected["saved_brackets"]):
                    raise ObserverBindingError(f"{name} event {key} time is outside saved bracket")
    report = evaluate_manual_predictions_v7(reference, prediction, frozen_config_path)
    report["schema"] = STRICT_EVALUATION_V8_SCHEMA
    report["status"] = report["status"].replace("_V7", "_V8")
    report["saved_bracket_binding"] = "exact_reference_prediction_match"
    report["frozen_config_path_binding"] = "exact_path_and_sha256"
    return report
