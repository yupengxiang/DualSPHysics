from __future__ import annotations

from scripts.ds_data02_f1_normal_attribution_v2 import FACE_SPECS


def test_complete_separator_face_set_includes_finite_top() -> None:
    names = [str(spec["name"]) for spec in FACE_SPECS]
    assert len(names) == 10
    assert names[-1] == "separator_z_high"
    top = FACE_SPECS[-1]
    assert top["axis"] == 2
    assert top["target"] == 0.7
    assert top["low"] == (1.25, 0.34)
    assert top["high"] == (2.05, 0.4)
