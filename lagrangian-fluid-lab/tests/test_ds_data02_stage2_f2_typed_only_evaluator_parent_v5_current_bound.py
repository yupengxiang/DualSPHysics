from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_typed_only_evaluator_parent_v5_current_bound.py"
BASE_REQUEST = ROOT / "campaigns/ds-data-02/stage2/evaluator/v2/f2-s1-typed-evaluator-parent-v2-current-root-061-001.json"
CURRENT_BINDING = ROOT / "campaigns/ds-data-02/stage2/evaluator/v2/f2-s1-current-catalog-binding-v1-001.json"


def _load(path: Path):
    spec = importlib.util.spec_from_file_location("typed_parent_v5_current_bound_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V5 = _load(SCRIPT)


def test_v5_registers_parent_and_runtime_transitive_closure(tmp_path: Path) -> None:
    output = tmp_path / "v5-request.json"
    result = V5.build_forward_request(
        base_request=BASE_REQUEST, current_binding=CURRENT_BINDING, output=output,
        parent_attempt_id="typed-v5-closure-test",
        supervisor_output_root=Path("/var/tmp/ds02-stage2") / "typed-v5-closure-test",
        home_receipt=tmp_path / "home-receipt.json", max_wall_seconds=30.0,
        allow_missing_parent=False)
    value = json.loads(output.read_text(encoding="utf-8"))
    assert result["hdf5_or_bi4_read"] is False
    assert value["sha256"] == V5.canonical_sha(value)
    roles = {item["role"]: item for item in value["static_bindings"]}
    expected = {
        "typed_only_parent_v5_current_bound": "ds_data02_stage2_f2_typed_only_evaluator_parent_v5_current_bound.py",
        "typed_only_parent_v4_current_bound": "ds_data02_stage2_f2_typed_only_evaluator_parent_v4_current_bound.py",
        "typed_only_parent_v3_current_bound": "ds_data02_stage2_f2_typed_only_evaluator_parent_v3_current_bound.py",
        "typed_only_parent_v2_current_bound": "ds_data02_stage2_f2_typed_only_evaluator_parent_v2_current_bound.py",
        "shared_runtime_v6": "ds_data02_runtime_v6.py",
        "shared_runtime_v2": "ds_data02_runtime_v2.py",
        "shared_batch_runner_v6": "ds_data02_batch_runner_v6.py",
        "shared_batch_runner_base": "ds_data02_batch_runner.py",
        "shared_dispatch_v6": "ds_data02_stage2_dispatch_v6.py",
        "shared_strict_dispatch_v6": "ds_data02_strict_dispatch_v6.py",
    }
    for role, filename in expected.items():
        assert role in roles
        assert Path(roles[role]["path"]).name == filename
    assert value["parent_resource_binding"]["allow_missing_parent"] is False
    assert value["execution"]["import_closure"]["static_roles_are_literal_paths"] is True
    assert value["v5_current_forward"]["runtime_import_closure"]


def test_v5_rejects_existing_request_without_touching_it(tmp_path: Path) -> None:
    output = tmp_path / "existing.json"
    output.write_text("sentinel\n", encoding="utf-8")
    with pytest.raises(V5.TypedParentV5CurrentError, match="existing V5 request"):
        V5.build_forward_request(
            base_request=BASE_REQUEST, current_binding=CURRENT_BINDING, output=output,
            parent_attempt_id="typed-v5-existing-test",
            supervisor_output_root=Path("/var/tmp/ds02-stage2") / "typed-v5-existing-test",
            home_receipt=tmp_path / "home-receipt.json", max_wall_seconds=30.0)
    assert output.read_text(encoding="utf-8") == "sentinel\n"
