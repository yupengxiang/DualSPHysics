from pathlib import Path

import pytest

from scripts import f3_revision075_score as score


def test_score_requires_authorization_before_reading_sources(monkeypatch):
    called = []

    def blocked(*args, **kwargs):
        called.append(True)
        raise PermissionError("authorization required")

    monkeypatch.setattr(score.launch_gate, "verify_authorization", blocked)
    with pytest.raises(PermissionError, match="authorization required"):
        score.score()
    assert called == [True]


def test_revision_score_uses_the_prospective_recipe_identity():
    assert score.RECIPE == "F3_CELL3_NS_visco1_native_nopen_revision075"
    assert score.EXISTING_CASES["REF-0075"].endswith("dp0p0075_a1p000_noslip_visco1_nopen")
    gate = score.OUT / "F3-075-REVISION-GATE.json"
    if gate.exists():
        # A completed scoring checkpoint may be present in the shared worktree;
        # importing the scorer must not rewrite or reinterpret it.
        assert gate.read_text().startswith("{")
