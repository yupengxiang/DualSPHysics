"""Strict provenance closure tests for the forward ROOT213 executor."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_root213_portable_typed_executor_v2.py"


def _load():
    spec = importlib.util.spec_from_file_location("root213_executor_v2_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_unknown_provenance_field_is_actionable_but_exact_legacy_field_is_not():
    module = _load()
    value = {
        "source_metadata_provenance": {
            "path": "/tmp/source-contract.json",
            "schema": "ds02.stage2.f2-fresh-v16-source-contract.v66",
            "sha256": "a" * 64,
        },
        "source_provenance": {"path": "/tmp/old-source.json"},
        "custom_provenance": {"path": "/tmp/custom-source.json", "sha256": "b" * 64},
    }
    records = module._strict_path_records(value)
    paths = {path for path, _parent, _parts in records}
    assert "/tmp/source-contract.json" in paths
    assert "/tmp/custom-source.json" in paths
    assert "/tmp/old-source.json" not in paths


def test_root213_failure_inner_request_requires_the_source_contract_role():
    """Exercise the actual 23-KiB ROOT213 inner request when present.

    This is source-only: it reads the small copied request and never opens the
    deferred V16 result, HDF5, BI4, raw, or typed output.  The production
    request is optional for a clean checkout, while the manufactured test
    above remains unconditional.
    """
    module = _load()
    actual = Path(
        "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/"
        "STAGE2_F2_ROOT213_PORTABLE_TYPED_PARENT_001/"
        "f2-s1-root213-portable-typed-parent-root-forward-030-001/portable/"
        "evidence/root200/inner.json"
    )
    if not actual.is_file() or actual.stat().st_size > 10 * 1024 * 1024:
        return
    request = json.loads(actual.read_text(encoding="utf-8"))
    records = module._strict_path_records(request)
    matches = [item for item in records if item[0].endswith("root190-source-contract.json")]
    assert len(matches) == 1
    source, parent, parts = matches[0]
    assert parts == ("source_metadata_provenance", "path")
    assert parent["schema"] == "ds02.stage2.f2-fresh-v16-source-contract.v66"
    assert parent["sha256"] == "25aaa8c8f56c763fd77d1985216e8923bfa93623d66772302083a2523e1e26e4"
