from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_portable_executor_v43.py"
BASE_CANDIDATES = [
    Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/")
    / "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v41-full-chain-root-082/"
    / "f2-s1-portable-executor-request-v41-root-082.json",
    ROOT / "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v41-full-chain-root-081/"
    / "f2-s1-portable-executor-request-v41-root-081.json",
]
BASE = next((path for path in BASE_CANDIDATES if path.is_file()), None)


def _load(path: Path):
    spec = importlib.util.spec_from_file_location("portable_executor_v43_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V43 = _load(SCRIPT)


@pytest.mark.skipif(BASE is None, reason="ROOT V41/V42 metadata fixture is not present in this worktree")
def test_v43_refreshes_only_small_sha_verified_stat_and_preserves_payloads(tmp_path: Path) -> None:
    original = json.loads(BASE.read_text(encoding="utf-8"))
    mutated = copy.deepcopy(original)
    small = next(item for item in mutated["source_entries"]
                 if item.get("role") == "immutable_base_v2_request")
    old_mtime = int(small["mtime_ns"])
    small["mtime_ns"] = old_mtime + 123456789
    base = tmp_path / "base-stale-stat.json"
    mutated["sha256"] = V43.canonical_sha(mutated)
    base.write_text(json.dumps(mutated, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    output = tmp_path / "v43-request.json"
    token = tmp_path.name
    result = V43.build_forward(
        base_request=base, output=output,
        target_root=Path("/var/tmp/ds02-stage2") / f"test-v43-target-{token}",
        output_root=Path("/var/tmp/ds02-stage2") / f"test-v43-output-{token}",
        parent_attempt_id=f"f2-s1-v43-pytest-{token}",
        ledger_path=Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json"),
        external_filesystem=Path("/var/tmp/ds02-stage2"),
        deadline_utc="2026-10-14T07:23:48+00:00",
        home_min_free_bytes=536870912000,
    )
    value = json.loads(output.read_text(encoding="utf-8"))
    refreshes = value["forward_v43"]["stat_refreshes"]
    assert any(item["role"] == "immutable_base_v2_request" for item in refreshes)
    assert value["forward_v43"]["stat_refresh_policy"]["content_sha_required_before_stat_refresh"] is True
    assert value["forward_v43"]["frozen_raw_tree"]["tree_sha256"] == V43.RAW_TREE_SHA
    assert value["execution"]["evaluator_stage"].startswith("DISABLED_UNTIL_NEW_V16")
    assert result["raw_h5_sha_during_build"] is False


@pytest.mark.skipif(BASE is None, reason="ROOT V41/V42 metadata fixture is not present in this worktree")
def test_v43_rejects_payload_stat_mismatch(tmp_path: Path) -> None:
    original = json.loads(BASE.read_text(encoding="utf-8"))
    mutated = copy.deepcopy(original)
    raw = next(item for item in mutated["source_entries"] if item.get("role") == "raw_frame_input")
    raw["mtime_ns"] = int(raw["mtime_ns"]) + 1
    base = tmp_path / "base-raw-stat.json"
    mutated["sha256"] = V43.canonical_sha(mutated)
    base.write_text(json.dumps(mutated, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(V43.PortableV43Error, match="protected scientific payload"):
        V43._validate_metadata(base)

