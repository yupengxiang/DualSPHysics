from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_portable_executor_v44.py"
ROOT_V43 = Path(
    "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/"
    "raw-to-label-v43-full-chain-root-082/f2-s1-portable-executor-request-v43-root-082.json"
)


def _load():
    spec = importlib.util.spec_from_file_location("portable_executor_v44_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V44 = _load()


def test_v44_bound_v34_copy_preserves_decoder_execute_mode_and_distinct_inode(tmp_path: Path) -> None:
    source = tmp_path / "decoder.py"
    source.write_bytes(b"#!/usr/bin/env python3\n")
    os.chmod(source, 0o755)
    target = tmp_path / "bundle" / "decoder.py"
    v34 = V44._load_mode_bound_v34()
    copied = v34._copy_one(source, target, V44.sha256_file(source), source.stat().st_size)
    assert copied["target_inode_distinct"] is True
    assert copied["mode_bits"] & 0o111
    assert target.stat().st_mode & 0o111
    assert copied["sha256"] == V44.sha256_file(target)


def test_v44_deadline_adapter_converts_remaining_duration_once(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, float | None] = {}

    def original(*args, deadline=None, **kwargs):
        observed["deadline"] = deadline
        return "ok"

    monkeypatch.setattr(V44, "_ORIGINAL_EVALUATOR", original)
    monkeypatch.setattr(V44.time, "monotonic", lambda: 100.0)
    assert V44._run_evaluator_with_one_deadline("evaluator", deadline=5.0) == "ok"
    assert observed["deadline"] == pytest.approx(105.0)


@pytest.mark.skipif(not ROOT_V43.is_file(), reason="ROOT V43 metadata fixture is not present")
def test_v44_refreshes_nested_stat_contracts_and_rebinds_runtime(tmp_path: Path) -> None:
    output = tmp_path / "v44-request.json"
    result = V44.build_from_v43(
        base_request=ROOT_V43, output=output,
        target_root=Path("/var/tmp/ds02-stage2") / f"v44-target-{tmp_path.name}",
        output_root=Path("/var/tmp/ds02-stage2") / f"v44-output-{tmp_path.name}",
        parent_attempt_id=f"f2-s1-v44-pytest-{tmp_path.name}",
    )
    value = json.loads(output.read_text(encoding="utf-8"))
    assert result["nested_stat_refresh_count"] >= 1
    assert value["forward_v44"]["mode_copy_policy"].startswith("preserve_source_mode")
    assert value["execution"]["deadline_contract"]["subtractions"] == 1
    assert all(
        not isinstance(item.get("source_stat_expected"), dict)
        or int(item["mtime_ns"]) == int(item["source_stat_expected"]["st_mtime_ns"])
        for key in ("source_entries", "runtime_sources")
        for item in value[key]
    )
    executor = next(item for item in value["runtime_sources"] if item.get("role") == "executor_v41")
    assert executor["path"].endswith("ds_data02_stage2_f2_portable_executor_v44.py")
    assert value["qualification"] == V44.UNKNOWN


def test_v44_protected_payload_nested_stat_mismatch_is_rejected(tmp_path: Path) -> None:
    payload = tmp_path / "Part_0000.bi4"
    payload.write_bytes(b"payload")
    value = {"source_entries": [{
        "role": "raw_frame_input", "path": str(payload), "sha256": V44.sha256_file(payload),
        "bytes": payload.stat().st_size, "mtime_ns": payload.stat().st_mtime_ns,
        "mode_bits": payload.stat().st_mode & 0o777,
        "source_stat_expected": {"st_size": payload.stat().st_size, "st_mtime_ns": payload.stat().st_mtime_ns - 1,
                                  "st_ctime_ns": payload.stat().st_ctime_ns, "st_dev": payload.stat().st_dev,
                                  "st_ino": payload.stat().st_ino, "st_mode": payload.stat().st_mode,
                                  "mode_bits": payload.stat().st_mode & 0o777, "st_nlink": payload.stat().st_nlink,
                                  "st_uid": payload.stat().st_uid, "st_gid": payload.stat().st_gid}
    }]}
    with pytest.raises(V44.PortableV44Error, match="protected/non-small"):
        V44._synchronize_nested_stat_contract(copy.deepcopy(value))
