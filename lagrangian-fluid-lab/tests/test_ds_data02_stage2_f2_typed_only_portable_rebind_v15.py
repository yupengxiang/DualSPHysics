from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_stage2_f2_typed_only_portable_rebind_v15.py"
SPEC = importlib.util.spec_from_file_location("ds02_portable_rebind_v15_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
V15 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V15)

BUILDER_SCRIPT = (Path(__file__).parents[1] / "scripts" /
                  "ds_data02_stage2_f2_root242_v15_recursive_source_request.py")
BUILDER_SPEC = importlib.util.spec_from_file_location(
    "ds02_root242_v15_builder_test", BUILDER_SCRIPT)
assert BUILDER_SPEC is not None and BUILDER_SPEC.loader is not None
BUILDER = importlib.util.module_from_spec(BUILDER_SPEC)
BUILDER_SPEC.loader.exec_module(BUILDER)


CURRENT_SOURCE = (
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/infra/"
    "STAGE2_CURRENT336_CATALOG/catalog-003/CURRENT336.json"
)


def _role(target: Path) -> dict[str, object]:
    return {
        "logical_role": "current336_actionable_metadata",
        "source_path_provenance": CURRENT_SOURCE,
        "source_sha256": "0" * 64,
        "source_stat_provenance": {"bytes": 2, "mode_bits": 0o664},
        "target_relative_path": str(target.relative_to(target.parents[2])),
    }


def test_v15_rewrites_bare_current_input_file_and_path(tmp_path: Path) -> None:
    target = tmp_path / "evidence" / "current" / "CURRENT336.json"
    target.parent.mkdir(parents=True)
    target.write_text("{}\n", encoding="utf-8")
    role = _role(target)
    bindings: list[dict[str, object]] = []

    value = V15._rewrite_request_v15(
        {
            "schema": "fixture.request.v1",
            "input_files": [CURRENT_SOURCE],
            "current_catalog": {"path": CURRENT_SOURCE},
        },
        root=tmp_path,
        source_map={CURRENT_SOURCE: (role, target)},
        role_by_target={},
        bindings=bindings,
    )

    assert value["input_files"] == [str(target)]
    assert value["current_catalog"]["path"] == str(target)
    assert any(item.get("list_string") is True for item in bindings)
    assert all(str(item.get("target_relative_path", "")).startswith("evidence/")
               for item in bindings)


def test_v15_rejects_unbound_bare_actionable_input(tmp_path: Path) -> None:
    with pytest.raises(V15.V2.PortableRebindV2Error, match="unbound actionable input-file"):
        V15._rewrite_request_v15(
            {"schema": "fixture.request.v1", "input_files": ["/outside/data.json"]},
            root=tmp_path, source_map={}, role_by_target={}, bindings=[],
        )


def test_v15_builder_rebinds_source_but_preserves_consumed_target(tmp_path: Path) -> None:
    target = "runtime/ds_data02_stage2_f2_typed_only_portable_rebind_v7.py"
    roles = [{
        "logical_role": "portable_rebind_v2_entrypoint",
        "source_path_provenance": str(tmp_path / "old-v5.py"),
        "target_relative_path": target,
        "source_sha256": "0" * 64,
        "source_stat_provenance": {"bytes": 1, "mode_bits": 0o644},
    }]

    BUILDER._replace_list_string_runtime_role(
        roles, Path(__file__).parents[2])

    rebound = roles[0]
    assert rebound["target_relative_path"] == target
    assert Path(str(rebound["source_path_provenance"])).name == (
        "ds_data02_stage2_f2_typed_only_portable_rebind_v15.py")
    assert len(str(rebound["source_sha256"])) == 64
    assert rebound["source_kind"] == "runtime_source_forward_v15_list_string_rebind"
