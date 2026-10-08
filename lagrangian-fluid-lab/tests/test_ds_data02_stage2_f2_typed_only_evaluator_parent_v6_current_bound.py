from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_typed_only_evaluator_parent_v6_current_bound.py"
BASE_REQUEST = ROOT / "campaigns/ds-data-02/stage2/evaluator/v2/f2-s1-typed-evaluator-parent-v2-current-root-061-001.json"
CURRENT_BINDING = ROOT / "campaigns/ds-data-02/stage2/evaluator/v2/f2-s1-current-catalog-binding-v1-001.json"


def _load(path: Path):
    spec = importlib.util.spec_from_file_location("typed_parent_v6_current_bound_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V6 = _load(SCRIPT)


def test_v6_builder_registers_actual_v2_callback_and_keeps_build_metadata_only(tmp_path: Path) -> None:
    output = tmp_path / "v6-request.json"
    result = V6.build_forward_request(
        base_request=BASE_REQUEST, current_binding=CURRENT_BINDING, output=output,
        parent_attempt_id="typed-v6-callback-test",
        supervisor_output_root=Path("/var/tmp/ds02-stage2") / "typed-v6-callback-test",
        home_receipt=tmp_path / "home-receipt.json", max_wall_seconds=30.0,
        allow_missing_parent=False)
    value = json.loads(output.read_text(encoding="utf-8"))
    roles = {item["role"]: item for item in value["static_bindings"]}
    assert "typed_only_parent_v6_current_bound" in roles
    assert Path(roles["typed_only_parent_v6_current_bound"]["path"]).resolve() == SCRIPT.resolve()
    assert value["v6_current_forward"]["corrected_callback"] == "V4.BASE.BASE._current_item"
    assert value["execution"]["current_adapter"]["source_callback_is_not_mocked"] is True
    assert value["sha256"] == V6.canonical_sha(value)
    assert result["hdf5_or_bi4_read"] is False


def test_v6_post_reservation_callback_uses_real_v2_adapter(tmp_path: Path) -> None:
    request_path = tmp_path / "v6-request.json"
    V6.build_forward_request(
        base_request=BASE_REQUEST, current_binding=CURRENT_BINDING, output=request_path,
        parent_attempt_id="typed-v6-real-current-callback-test",
        supervisor_output_root=Path("/var/tmp/ds02-stage2") / "typed-v6-real-current-callback-test",
        home_receipt=tmp_path / "home-receipt.json", max_wall_seconds=30.0,
        allow_missing_parent=False)
    bound = V6._validate_request(request_path, verify_static_content=False)
    sidecar, info = V6._current_after_reservation(bound)
    assert sidecar.is_file()
    assert info["current_catalog_sha256"] == bound["request"]["current_catalog_binding"]["current_catalog_sha256"]
    assert hasattr(V6.V4.BASE.BASE, "_current_item")


def test_v6_does_not_silently_fallback_to_v3_callback() -> None:
    assert not hasattr(V6.V4.BASE, "_current_item")
    assert callable(V6._current_after_reservation)
