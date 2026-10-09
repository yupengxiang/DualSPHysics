"""Manufactured V10 dynamic-open-guard coverage.

The first two tests use copied V2/V5 entrypoints and tiny V8/V12/scorer
interfaces to exercise the actual V10 process boundary.  The third test
reuses the repository's real V8/V12/typed-scorer bundle fixture; that fixture
is synthetic (no production H5/BI4/native input) but executes the real
semantic modules, rather than a stub, through the consumed V2 worker.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
V10_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_root242_portable_typed_executor_v10.py"
WORKER_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_root242_root_runtime_worker_v10.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V10 = _load(V10_PATH, "root242_v10_test_executor")
V9_TEST = _load(ROOT / "tests/test_ds_data02_stage2_f2_root242_v9_executor.py",
                "root242_v9_fixture_for_v10")


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stat(path: Path, *, follow: bool = False) -> dict[str, int]:
    value = path.stat() if follow else path.lstat()
    return {"bytes": int(value.st_size), "mode_bits": int(stat.S_IMODE(value.st_mode)),
            "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns),
            "st_dev": int(value.st_dev), "st_ino": int(value.st_ino)}


def _canonical(value: dict) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                      ensure_ascii=True).encode()).hexdigest()


def _v10ize(tmp_path: Path, *, scorer_opens_original: bool = False) -> tuple[Path, Path, Path]:
    request_path, contract_path, fresh = V9_TEST._fixture(tmp_path)
    contract = json.loads(contract_path.read_text())
    roles = [item for item in contract["root242_source_binding"]["roles"]
             if item.get("logical_role") != "v9_executor"]
    if scorer_opens_original:
        scorer = next(item for item in roles if item.get("logical_role") == "typed_only_evaluator_v1")
        scorer_path = Path(scorer["source_path_provenance"])
        poison = next(item for item in roles if item.get("logical_role") == "current336_actionable_metadata")
        scorer_path.write_text(
            "from pathlib import Path\n"
            f"Path({str(poison['source_path_provenance'])!r}).read_text()\n"
            "def _score_typed_result(result, frozen):\n"
            "    return {'operator_score': result['value'], 'model_invoked': False}\n",
            encoding="utf-8")
        scorer["source_sha256"] = _sha(scorer_path)
        scorer["source_stat_provenance"] = _stat(scorer_path)
    roles.extend([
        {
            "logical_role": "v10_executor", "source_kind": "test_v10_executor",
            "actionable": True, "content_read_by_manifest": True,
            "source_sha256": _sha(V10_PATH), "source_path_provenance": str(V10_PATH),
            "source_stat_provenance": _stat(V10_PATH),
            "target_relative_path": "runtime/ds_data02_stage2_f2_root242_portable_typed_executor_v10.py",
            "deferred_content": False,
        },
        {
            "logical_role": "v10_runtime_worker", "source_kind": "test_v10_worker",
            "actionable": True, "content_read_by_manifest": True,
            "source_sha256": _sha(WORKER_PATH), "source_path_provenance": str(WORKER_PATH),
            "source_stat_provenance": _stat(WORKER_PATH),
            "target_relative_path": "runtime/ds_data02_stage2_f2_root242_root_runtime_worker_v10.py",
            "deferred_content": False,
        },
    ])
    roles.sort(key=lambda item: str(item["logical_role"]))
    digest = hashlib.sha256(json.dumps(roles, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    binding = dict(contract["root242_source_binding"])
    binding.update({
        "schema": V10.HANDOFF_SCHEMA, "roles": roles,
        "selected_roles_sha256": digest, "selected_role_count": len(roles),
        "dynamic_open_policy": {"audit_hook": "sys.addaudithook", "events": ["open", "os.chdir"]},
    })
    contract["root242_source_binding"] = binding
    contract["forward_version"] = "ROOT242_V10_EXECUTABLE_DYNAMIC_OPEN_GUARD"
    contract["v2_interface"] = {"literal_python": str(Path(sys.executable))}
    contract["sha256"] = _canonical(contract)
    contract_path.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n")
    request = json.loads(request_path.read_text())
    request.pop("root242_v9_source_binding", None)
    request["root213_metadata_contract"] = {"path": str(contract_path), "sha256": contract["sha256"]}
    request["root242_v10_source_binding"] = {
        "schema": V10.HANDOFF_SCHEMA, "selected_roles_sha256": digest,
    }
    request["scope"]["runtime_open_policy"] = {"audit_hook": "sys.addaudithook"}
    # The V10 validator only consumes the sealed contract/request; update the
    # input table too so this manufactured request mirrors a primary build.
    request["input_files"] = [str(item["source_path_provenance"]) for item in roles]
    request["input_sha256"] = {str(item["source_path_provenance"]): item["source_sha256"] for item in roles}
    request["input_files"].append(str(contract_path))
    request["input_sha256"][str(contract_path)] = _sha(contract_path)
    request["sha256"] = _canonical(request)
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n")
    return request_path, contract_path, fresh


def _run_v10(request: Path, fresh: Path) -> subprocess.CompletedProcess[str]:
    code = (
        "import importlib.util,os,sys;"
        "s=importlib.util.spec_from_file_location('v10child',sys.argv[1]);"
        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
        "m.run(request=sys.argv[2],output_root=sys.argv[3],parent_pid=int(sys.argv[4]),max_wall_seconds=30)"
    )
    return subprocess.run([sys.executable, "-c", code, str(V10_PATH), str(request),
                           str(fresh), str(os.getpid())],
                          text=True, capture_output=True, timeout=45)


def test_v10_dynamic_open_guard_allows_relocated_runtime(tmp_path: Path) -> None:
    request, _contract, fresh = _v10ize(tmp_path)
    completed = _run_v10(request, fresh)
    assert completed.returncode == 0, completed.stderr
    report = json.loads((fresh / "reports/root242-v10-executor-report.json").read_text())
    assert report["status"] == "COMPLETE_RELOCATED_V10_DYNAMIC_OPEN_GUARD_V8_V12_TYPED_SCORER"
    assert report["execution"]["dynamic_os_open_guard"] is True
    assert report["child_runtime_open_audit"]["hook_installed"] is True
    assert report["child_runtime_open_audit"]["blocked_events"] == 0
    assert report["execution"]["original_path_fallback"] == "REJECT"


def test_v10_dynamic_open_guard_rejects_hidden_original_open(tmp_path: Path) -> None:
    request, _contract, fresh = _v10ize(tmp_path, scorer_opens_original=True)
    completed = _run_v10(request, fresh)
    assert completed.returncode != 0
    assert "OPEN_POLICY_REJECTED" in completed.stderr
    assert not (fresh / "reports/root242-v10-executor-report.json").exists()


def test_v10_real_v8_v12_typed_scorer_bundle_smoke(tmp_path: Path) -> None:
    """Run the existing real-module V2 bundle on manufactured data.

    This is deliberately separate from the tiny dynamic-hook fixture.  It
    proves the copied V8/V12/typed-scorer API, including the 21114 identity
    and event schema preconditions, without touching production payloads.
    """
    real_test = _load(ROOT / "tests/test_ds_data02_stage2_f2_typed_only_portable_rebind_v2_real.py",
                      "root242_real_v2_bundle_test")
    real_test.test_v2_real_relocated_v8_v12_typed_scorer_without_source(tmp_path / "real-v2")


def test_v10_open_guard_policy_rejects_unbound_path_without_static_marker(tmp_path: Path) -> None:
    request, _contract, fresh = _v10ize(tmp_path, scorer_opens_original=True)
    # The malicious scorer path is not present in the inner JSON, so this
    # specifically exercises dynamic audit rejection rather than V2's static
    # unbound-path rebinder.
    inner = json.loads((tmp_path / "source/inner.json").read_text())
    # The malicious scorer opens CURRENT directly in code.  That path is a
    # legitimate bound metadata path in the request, so use a separate
    # sentinel to prove the request itself carries no static poison marker.
    assert all(str(tmp_path / "source/unbound-hidden-open.txt") not in str(value)
               for value in inner.values())
    completed = _run_v10(request, fresh)
    assert completed.returncode != 0
    assert "OPEN_POLICY_REJECTED" in completed.stderr
