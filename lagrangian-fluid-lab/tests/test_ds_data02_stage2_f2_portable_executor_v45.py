from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_portable_executor_v45.py"
ROOT_V43 = Path(
    "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/"
    "raw-to-label-v43-full-chain-root-082/f2-s1-portable-executor-request-v43-root-082.json"
)


def _load():
    spec = importlib.util.spec_from_file_location("portable_executor_v45_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V45 = _load()


def test_v45_bound_v34_copy_preserves_decoder_execute_mode_and_distinct_inode(tmp_path: Path) -> None:
    source = tmp_path / "decoder.py"
    source.write_bytes(b"#!/usr/bin/env python3\n")
    os.chmod(source, 0o755)
    target = tmp_path / "bundle" / "decoder.py"
    v34 = V45._load_mode_bound_v34()
    copied = v34._copy_one(source, target, V45.sha256_file(source), source.stat().st_size)
    assert copied["target_inode_distinct"] is True
    assert copied["mode_bits"] & 0o111
    assert target.stat().st_mode & 0o111
    assert copied["sha256"] == V45.sha256_file(target)


def test_v45_run_hook_uses_captured_loader_and_reaches_stub_v34_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise the run-installed hook, not just the hook function directly.

    The bottom V34 ``run`` is a tiny stub, but V41.run is real: it validates
    through the patched request hook, asks V38 for V34, installs the worker
    hook, and invokes the stub.  This catches the V44 self-recursive loader
    that direct ``_load_mode_bound_v34()`` tests could not observe.
    """
    source = tmp_path / "decoder.py"
    source.write_bytes(b"#!/usr/bin/env python3\n")
    os.chmod(source, 0o755)
    output_root = tmp_path / "output"

    class StubV34:
        def __init__(self) -> None:
            self._run_private_worker = lambda *args, **kwargs: {"status": "UNUSED"}

        def run(self, request_path, *, io_slot_approved, parent_pid=None,
                evaluator_proof=None, max_wall_seconds=None):
            return self._run_private_worker(
                Path("/venv/bin/python"), Path("worker.py"), Path(request_path),
                output_root / "worker", deadline=None)

    stub = StubV34()
    monkeypatch.setattr(V45, "_ORIGINAL_V34_LOADER", lambda: stub)
    monkeypatch.setattr(
        V45.V41, "_validate_request",
        lambda _path: {"fresh_roots": {"output_root": str(output_root)}},
    )

    def worker_hook(v34, _request, state):
        def wrapped(python, worker, request, output, *, deadline):
            copied = v34._copy_one(source, tmp_path / "bundle" / "decoder.py",
                                    V45.sha256_file(source), source.stat().st_size)
            state["integration"] = {"schema": "test.v45", "copy": copied}
            return {"status": "COMPLETE"}
        return wrapped

    monkeypatch.setattr(V45.V41, "_v41_worker_hook", worker_hook)
    original = V45.V41.V38._load_v34
    result = V45.run(tmp_path / "request.json", io_slot_approved=True)
    assert result["status"] == "COMPLETE"
    assert result["v40_engine_report"]
    assert (tmp_path / "bundle" / "decoder.py").stat().st_mode & 0o111
    assert V45.V41.V38._load_v34 is original


def test_v45_deadline_adapter_converts_remaining_duration_once(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, float | None] = {}

    def original(*args, deadline=None, **kwargs):
        observed["deadline"] = deadline
        return "ok"

    monkeypatch.setattr(V45, "_ORIGINAL_EVALUATOR", original)
    monkeypatch.setattr(V45.time, "monotonic", lambda: 100.0)
    assert V45._run_evaluator_with_one_deadline("evaluator", deadline=5.0) == "ok"
    assert observed["deadline"] == pytest.approx(105.0)


@pytest.mark.skipif(not ROOT_V43.is_file(), reason="ROOT V43 metadata fixture is not present")
def test_v45_refreshes_nested_stat_contracts_and_rebinds_runtime(tmp_path: Path) -> None:
    output = tmp_path / "v45-request.json"
    result = V45.build_from_v43(
        base_request=ROOT_V43, output=output,
        target_root=Path("/var/tmp/ds02-stage2") / f"v45-target-{tmp_path.name}",
        output_root=Path("/var/tmp/ds02-stage2") / f"v45-output-{tmp_path.name}",
        parent_attempt_id=f"f2-s1-v45-pytest-{tmp_path.name}",
    )
    value = json.loads(output.read_text(encoding="utf-8"))
    assert result["nested_stat_refresh_count"] >= 1
    assert value["forward_v45"]["mode_copy_policy"].startswith("preserve_source_mode")
    assert value["execution"]["deadline_contract"]["subtractions"] == 1
    roles = {item["role"]: item for item in value["runtime_sources"]}
    assert roles["executor_v41_compat"]["target_relative_path"].endswith(
        "ds_data02_stage2_f2_portable_executor_v41.py")
    assert roles["executor_v43_builder"]["target_relative_path"].endswith(
        "ds_data02_stage2_f2_portable_executor_v43.py")
    assert roles["executor_v41_compat"]["sha256"] == V45.sha256_file(V45.V41_SCRIPT)
    assert roles["executor_v43_builder"]["sha256"] == V45.sha256_file(V45.V43_SCRIPT)
    assert all(
        not isinstance(item.get("source_stat_expected"), dict)
        or int(item["mtime_ns"]) == int(item["source_stat_expected"]["st_mtime_ns"])
        for key in ("source_entries", "runtime_sources")
        for item in value[key]
    )
    executor = next(item for item in value["runtime_sources"] if item.get("role") == "executor_v41")
    assert executor["path"].endswith("ds_data02_stage2_f2_portable_executor_v45.py")
    assert value["qualification"] == V45.UNKNOWN


def test_v45_protected_payload_nested_stat_mismatch_is_rejected(tmp_path: Path) -> None:
    payload = tmp_path / "Part_0000.bi4"
    payload.write_bytes(b"payload")
    value = {"source_entries": [{
        "role": "raw_frame_input", "path": str(payload), "sha256": V45.sha256_file(payload),
        "bytes": payload.stat().st_size, "mtime_ns": payload.stat().st_mtime_ns,
        "mode_bits": payload.stat().st_mode & 0o777,
        "source_stat_expected": {"st_size": payload.stat().st_size, "st_mtime_ns": payload.stat().st_mtime_ns - 1,
                                  "st_ctime_ns": payload.stat().st_ctime_ns, "st_dev": payload.stat().st_dev,
                                  "st_ino": payload.stat().st_ino, "st_mode": payload.stat().st_mode,
                                  "mode_bits": payload.stat().st_mode & 0o777, "st_nlink": payload.stat().st_nlink,
                                  "st_uid": payload.stat().st_uid, "st_gid": payload.stat().st_gid}
    }]}
    with pytest.raises(V45.PortableV45Error, match="protected/non-small"):
        V45._synchronize_nested_stat_contract(copy.deepcopy(value))
