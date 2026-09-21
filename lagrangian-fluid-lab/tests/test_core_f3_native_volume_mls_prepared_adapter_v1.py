from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.core_f3_native_volume_mls_prepared_adapter_v1 import normalize_prepared


ROOT = Path(__file__).resolve().parents[1]
PREPARED = ROOT / (
    "campaigns/core-v1/runtime/attempts/"
    "cfd-f3_production_amp0p95_native010-v1/20260920T035702-dc9c237466a0/"
    "product/prepared.json"
)


def test_adapter_normalizes_nested_core_prepared_shape_without_mutating_source(tmp_path: Path) -> None:
    before = hashlib.sha256(PREPARED.read_bytes()).hexdigest()
    original = json.loads(PREPARED.read_text())
    assert "dp_m" not in original
    assert original["case"]["dp_m"] == original["config"]["dp_m"]

    normalized_path = tmp_path / "row16.normalized-prepared.json"
    normalized = normalize_prepared(PREPARED, normalized_path)

    assert normalized["schema"] == "core.f3.cfd.native_volume_mls.source.v1.adapter_normalized"
    assert normalized["dp_m"] == 0.0075
    assert normalized["candidate_definition"].endswith("F3_CELL3_plain_0p0075.xml")
    assert normalized["case_id"] == "F3_REV075_MATERIAL-AMP0P95-0075"
    assert normalized["adapter_binding"]["original_prepared_sha256"] == before
    assert normalized["adapter_binding"]["numerical_backend_change"] is False
    assert normalized["adapter_binding"]["future_state_access"] is False
    assert hashlib.sha256(PREPARED.read_bytes()).hexdigest() == before


def test_adapter_rejects_disagreeing_nested_dp(tmp_path: Path) -> None:
    source = json.loads(PREPARED.read_text())
    source["config"]["dp_m"] = 0.006
    changed = tmp_path / "bad-prepared.json"
    changed.write_text(json.dumps(source))
    try:
        normalize_prepared(changed, tmp_path / "normalized.json")
    except ValueError as exc:
        assert "dp_m disagrees" in str(exc)
    else:  # pragma: no cover - explicit failure branch
        raise AssertionError("adapter accepted inconsistent nested dp_m")


def test_adapter_rejects_nonfinite_dp(tmp_path: Path) -> None:
    source = json.loads(PREPARED.read_text())
    source["case"]["dp_m"] = "NaN"
    source["config"]["dp_m"] = "NaN"
    changed = tmp_path / "nonfinite-prepared.json"
    changed.write_text(json.dumps(source))
    try:
        normalize_prepared(changed, tmp_path / "normalized.json")
    except ValueError as exc:
        assert "finite and positive" in str(exc)
    else:  # pragma: no cover - explicit failure branch
        raise AssertionError("adapter accepted nonfinite dp_m")
