from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np

from scripts.f4_tallwall120_cadence_terminal_diagnosis_v1 import _event_semantics


def test_positive_residence_can_be_prior_to_final_unknown(tmp_path: Path) -> None:
    trace = tmp_path / "material.h5"
    with h5py.File(trace, "w") as handle:
        handle.attrs["committed"] = 1
        handle.create_dataset("time", data=np.asarray([0.0, 0.02]))
        handle.create_dataset("weight", data=np.asarray([0.5, 0.5]))
        handle.create_dataset("source_label", data=np.asarray([1, 1], dtype=np.int8))
        handle.create_dataset("reliable", data=np.asarray([[True, True], [False, False]]))
        handle.create_dataset("contacted", data=np.asarray([[False, False], [True, True]]))
        handle.create_dataset("upward", data=np.zeros((2, 2), dtype=bool))
        handle.create_dataset("returned", data=np.zeros((2, 2), dtype=bool))
        handle.create_dataset("residence", data=np.asarray([[0.0, 0.0], [0.1, 0.2]]))
    summary = tmp_path / "material.json"
    summary.write_text(json.dumps({"by_source": [{
        "source": 1, "contact_fraction": 0.0, "residence_mean_s": 0.15,
        "residence_cdf": {"time_s": []},
    }]}))

    result = _event_semantics(trace, summary)
    row = result["by_source"][0]
    assert row["final_contacted_count"] == 2
    assert row["final_reliable_contacted_count"] == 0
    assert row["final_residence_positive_unreliable_count"] == 2
    assert "partial pre-unknown residence" in result["semantic_interpretation"]["contact_fraction_zero_with_positive_residence"]
