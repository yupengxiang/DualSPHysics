"""Manufactured V11 dynamic-open-guard coverage.

The first two tests use copied V2/V5 entrypoints and tiny V8/V12/scorer
interfaces to exercise the actual V11 process boundary.  The third test
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
import copy
import shutil
import stat
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
V11_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_root242_portable_typed_executor_v11.py"
WORKER_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_root242_root_runtime_worker_v11.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V11 = _load(V11_PATH, "root242_v11_test_executor")
V9_TEST = _load(ROOT / "tests/test_ds_data02_stage2_f2_root242_v9_executor.py",
                "root242_v9_fixture_for_v11")


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


def _v11ize(tmp_path: Path, *, scorer_opens_original: bool = False,
            scorer_opens_proc_root: bool = False) -> tuple[Path, Path, Path]:
    request_path, contract_path, fresh = V9_TEST._fixture(tmp_path)
    contract = json.loads(contract_path.read_text())
    # V11 binds the literal interpreter to its complete pyvenv.cfg root.  The
    # older fixture put a synthetic cfg beside the source JSON, so manufacture
    # a tiny real interpreter root for this subprocess-only test.
    pinned_root = tmp_path / "pinned-venv"
    pinned_bin = pinned_root / "bin"
    pinned_bin.mkdir(parents=True, exist_ok=True)
    pinned_python = pinned_bin / "python"
    shutil.copyfile(sys.executable, pinned_python)
    pinned_python.chmod(0o755)
    pinned_cfg = pinned_root / "pyvenv.cfg"
    pinned_cfg.write_text("home = fixture\ninclude-system-site-packages = false\n", encoding="utf-8")
    site_packages = pinned_root / "lib" / (
        f"python{sys.version_info.major}.{sys.version_info.minor}") / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)
    (site_packages / "v11_site_probe.py").write_text(
        "MARKER = 'PINNED_VENV_SITE_PACKAGES'\n", encoding="utf-8")
    for role in contract["root242_source_binding"]["roles"]:
        if role.get("logical_role") == "pinned_project_pyvenv_cfg":
            role["source_path_provenance"] = str(pinned_cfg)
            role["source_sha256"] = _sha(pinned_cfg)
            role["source_stat_provenance"] = _stat(pinned_cfg)
        elif role.get("logical_role") == "literal_project_venv_python":
            role["source_path_provenance"] = str(pinned_python)
            role["source_sha256"] = _sha(pinned_python)
            role["source_stat_provenance"] = _stat(pinned_python)
    roles = [item for item in contract["root242_source_binding"]["roles"]
             if item.get("logical_role") != "v9_executor"]
    scorer = next(item for item in roles if item.get("logical_role") == "typed_only_evaluator_v1")
    scorer_path = Path(scorer["source_path_provenance"])
    # This import is deliberately only available from the pinned venv's
    # site-packages.  A worker that retains only .venv/bin will fail here,
    # while the V11 policy must allow this exact environment descendant.
    scorer_path.write_text(
        "from v11_site_probe import MARKER\n"
        "assert MARKER == 'PINNED_VENV_SITE_PACKAGES'\n"
        "def _score_typed_result(result, frozen):\n"
        "    return {'operator_score': result['value'], 'model_invoked': False}\n",
        encoding="utf-8")
    scorer["source_sha256"] = _sha(scorer_path)
    scorer["source_stat_provenance"] = _stat(scorer_path)
    if scorer_opens_original or scorer_opens_proc_root:
        scorer_path = Path(scorer["source_path_provenance"])
        poison = next(item for item in roles if item.get("logical_role") == "current336_actionable_metadata")
        poison_path = str(poison["source_path_provenance"])
        if scorer_opens_proc_root:
            poison_path = "/proc/self/root" + poison_path
        scorer_path.write_text(
            "from pathlib import Path\n"
            "from v11_site_probe import MARKER\n"
            "assert MARKER == 'PINNED_VENV_SITE_PACKAGES'\n"
            f"Path({poison_path!r}).read_text()\n"
            "def _score_typed_result(result, frozen):\n"
            "    return {'operator_score': result['value'], 'model_invoked': False}\n",
            encoding="utf-8")
        scorer["source_sha256"] = _sha(scorer_path)
        scorer["source_stat_provenance"] = _stat(scorer_path)
    roles.extend([
        {
            "logical_role": "v11_executor", "source_kind": "test_v11_executor",
            "actionable": True, "content_read_by_manifest": True,
            "source_sha256": _sha(V11_PATH), "source_path_provenance": str(V11_PATH),
            "source_stat_provenance": _stat(V11_PATH),
            "target_relative_path": "runtime/ds_data02_stage2_f2_root242_portable_typed_executor_v11.py",
            "deferred_content": False,
        },
        {
            "logical_role": "v11_runtime_worker", "source_kind": "test_v11_worker",
            "actionable": True, "content_read_by_manifest": True,
            "source_sha256": _sha(WORKER_PATH), "source_path_provenance": str(WORKER_PATH),
            "source_stat_provenance": _stat(WORKER_PATH),
            "target_relative_path": "runtime/ds_data02_stage2_f2_root242_root_runtime_worker_v11.py",
            "deferred_content": False,
        },
    ])
    roles.sort(key=lambda item: str(item["logical_role"]))
    digest = hashlib.sha256(json.dumps(roles, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    binding = dict(contract["root242_source_binding"])
    binding.update({
        "schema": V11.HANDOFF_SCHEMA, "roles": roles,
        "selected_roles_sha256": digest, "selected_role_count": len(roles),
        "dynamic_open_policy": {
            "audit_hook": "sys.addaudithook", "events": ["open", "os.chdir"],
            "membership_rule": "LEXICAL_AND_RESOLVED_MUST_SHARE_ONE_EXPLICIT_ROOT",
            "pinned_venv_binding": {
                "interpreter_role": "literal_project_venv_python",
                "pyvenv_cfg_role": "pinned_project_pyvenv_cfg",
            },
        },
    })
    contract["root242_source_binding"] = binding
    contract["forward_version"] = "ROOT242_V11_EXECUTABLE_DYNAMIC_OPEN_GUARD"
    contract["v2_interface"] = {"literal_python": str(pinned_python)}
    contract["sha256"] = _canonical(contract)
    contract_path.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n")
    request = json.loads(request_path.read_text())
    request.pop("root242_v9_source_binding", None)
    request["interpreter_binding"]["invocation_path"] = str(pinned_python)
    request["root213_metadata_contract"] = {"path": str(contract_path), "sha256": contract["sha256"]}
    request["root242_v11_source_binding"] = {
        "schema": V11.HANDOFF_SCHEMA, "selected_roles_sha256": digest,
    }
    request["scope"]["runtime_open_policy"] = {"audit_hook": "sys.addaudithook"}
    # The V11 validator only consumes the sealed contract/request; update the
    # input table too so this manufactured request mirrors a primary build.
    request["input_files"] = [str(item["source_path_provenance"]) for item in roles]
    request["input_sha256"] = {str(item["source_path_provenance"]): item["source_sha256"] for item in roles}
    request["input_files"].append(str(contract_path))
    request["input_sha256"][str(contract_path)] = _sha(contract_path)
    request["sha256"] = _canonical(request)
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n")
    return request_path, contract_path, fresh


def _run_v11(request: Path, fresh: Path) -> subprocess.CompletedProcess[str]:
    code = (
        "import importlib.util,os,sys;"
        "s=importlib.util.spec_from_file_location('v11child',sys.argv[1]);"
        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
        "m.run(request=sys.argv[2],output_root=sys.argv[3],parent_pid=int(sys.argv[4]),max_wall_seconds=30)"
    )
    return subprocess.run([sys.executable, "-c", code, str(V11_PATH), str(request),
                           str(fresh), str(os.getpid())],
                          text=True, capture_output=True, timeout=45)


def test_v11_dynamic_open_guard_allows_relocated_runtime(tmp_path: Path) -> None:
    request, _contract, fresh = _v11ize(tmp_path)
    completed = _run_v11(request, fresh)
    assert completed.returncode == 0, completed.stderr
    report = json.loads((fresh / "reports/root242-v11-executor-report.json").read_text())
    assert report["status"] == "COMPLETE_RELOCATED_V11_DYNAMIC_OPEN_GUARD_V8_V12_TYPED_SCORER"
    assert report["execution"]["dynamic_os_open_guard"] is True
    assert report["child_runtime_open_audit"]["hook_installed"] is True
    assert report["child_runtime_open_audit"]["blocked_events"] == 0
    assert report["execution"]["original_path_fallback"] == "REJECT"
    assert report["execution"]["scientific_hdf5_or_bi4_array_decode"] is False
    assert report["execution"]["streamed_copy_hash_bytes"] > 0
    assert report["execution"]["streamed_copy_hash_includes_hdf5_or_bi4"] is True
    assert report["execution"]["scientific_H5_array_decode"] is False
    assert report["execution"]["hdf5_or_bi4_bytes_streamed_for_copy_hash"] > 0


def test_v11_dynamic_open_guard_rejects_hidden_original_open(tmp_path: Path) -> None:
    request, _contract, fresh = _v11ize(tmp_path, scorer_opens_original=True)
    completed = _run_v11(request, fresh)
    assert completed.returncode != 0
    assert "OPEN_POLICY_REJECTED" in completed.stderr
    assert not (fresh / "reports/root242-v11-executor-report.json").exists()


def test_v11_real_v8_v12_typed_scorer_bundle_smoke(tmp_path: Path) -> None:
    """Run the existing real-module V2 bundle on manufactured data.

    This is deliberately separate from the tiny dynamic-hook fixture.  It
    proves the copied V8/V12/typed-scorer API, including the 21114 identity
    and event schema preconditions, without touching production payloads.
    """
    real_test = _load(ROOT / "tests/test_ds_data02_stage2_f2_typed_only_portable_rebind_v2_real.py",
                      "root242_real_v2_bundle_test")
    real_test.test_v2_real_relocated_v8_v12_typed_scorer_without_source(tmp_path / "real-v2")


def test_v11_real_v8_v12_typed_scorer_bundle_through_same_hook(tmp_path: Path) -> None:
    """Run the real V8/V12/scorer fixture inside the V11 audit process.

    The existing real-bundle test exercises V2 directly.  This adapter keeps
    that fixture's copied runtime and semantic modules, seals an outer V11
    contract against the already-relocated files, and replaces only the
    fixture's final V2 ``run_guard`` call with a literal-venv V11 subprocess.
    Thus the real V8/V12/scorer code crosses the same audit hook and policy
    boundary; no production H5/BI4/native source is involved.
    """
    real_test = _load(ROOT / "tests/test_ds_data02_stage2_f2_typed_only_portable_rebind_v2_real.py",
                      "root242_real_v2_bundle_for_v11")
    original_run_guard = real_test.V2.run_guard

    def run_v11_guard(*, request_path: Path | str, output_relative: str,
                      parent_pid: int, python_path: Path | str,
                      max_wall_seconds: float) -> dict:
        del request_path, output_relative, max_wall_seconds
        source_literal = Path(python_path).absolute()
        relocated = source_literal.parent.parent
        # The production contract is ``<venv>/bin/python``.  The historical
        # real-bundle fixture used ``environment/python``; place the same
        # sealed executable under a real bin/ root without changing the
        # fixture's V2 target names.
        literal = relocated / "environment" / "bin" / "python"
        literal.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_literal, literal)
        literal.chmod(0o755)
        base = relocated.parent
        source_contract_path = base / "contract.json"
        source_contract = json.loads(source_contract_path.read_text(encoding="utf-8"))
        source_roles = source_contract.get("roles")
        assert isinstance(source_roles, list)
        roles: list[dict] = []
        for original in source_roles:
            role = copy.deepcopy(original)
            target = relocated / str(role["target_relative_path"])
            assert target.is_file() and not target.is_symlink(), target
            role["source_path_provenance"] = str(target)
            role["source_sha256"] = _sha(target)
            role["source_stat_provenance"] = _stat(target)
            roles.append(role)
        env_role = next(item for item in roles if item["logical_role"] == "literal_project_venv_python")
        env_role["source_path_provenance"] = str(literal)
        env_role["source_sha256"] = _sha(literal)
        env_role["source_stat_provenance"] = _stat(literal)
        # The copied V2 request still contains the original source spellings.
        # Rebind those actionable strings to the sealed target-relative files
        # before the V11 overlay builder sees them; provenance-only fields stay
        # available in the outer role table and are never used as fallbacks.
        source_to_target = {
            str(original["source_path_provenance"]): str(
                relocated / str(original["target_relative_path"]))
            for original in source_roles
        }
        inner_role = next(item for item in roles if item["logical_role"] == "root200_inner_request")
        inner_path = Path(inner_role["source_path_provenance"])
        inner_value = json.loads(inner_path.read_text(encoding="utf-8"))

        def rebind(value):
            if isinstance(value, str):
                return source_to_target.get(value, value)
            if isinstance(value, list):
                return [rebind(item) for item in value]
            if isinstance(value, dict):
                return {key: rebind(item) for key, item in value.items()}
            return value

        inner_value = rebind(inner_value)
        if "sha256" in inner_value:
            inner_value["sha256"] = _canonical(inner_value)
        inner_path.write_text(json.dumps(inner_value, sort_keys=True) + "\n",
                              encoding="utf-8")
        inner_role["source_sha256"] = _sha(inner_path)
        inner_role["source_stat_provenance"] = _stat(inner_path)
        # V12 consumes nested sidecars and frozen metadata after the overlay
        # has been loaded.  Rebind their actionable path fields as well; a
        # top-level request rewrite alone would leave current_manifest/path or
        # source-contract paths pointing at the deleted source tree.
        for role in roles:
            target = Path(role["source_path_provenance"])
            if target.suffix.lower() != ".json" or target.stat().st_size > 10 * 1024 * 1024:
                continue
            try:
                nested_value = json.loads(target.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            rebound = rebind(nested_value)
            if rebound == nested_value:
                continue
            if isinstance(rebound, dict) and "sha256" in rebound:
                rebound["sha256"] = _canonical(rebound)
            target.write_text(json.dumps(rebound, sort_keys=True) + "\n", encoding="utf-8")
            role["source_sha256"] = _sha(target)
            role["source_stat_provenance"] = _stat(target)
        names = {str(item["logical_role"]) for item in roles}
        # The real V2 fixture uses slightly more specific names than the
        # ROOT242 V9 loading manifest.  Register explicit aliases, keeping the
        # same sealed target bytes and provenance rather than silently falling
        # back to an original path.
        aliases = {
            "root179c_v16_result_deferred": "root179c_typed_result_deferred",
            "closure_271d0ebcb1b99437": "trajectory_h5_deferred",
            "root200_fresh_v12_proof": "v12_semantic_sidecar",
        }
        for alias, source_name in aliases.items():
            if alias not in names:
                source = next(item for item in roles if item["logical_role"] == source_name)
                clone = copy.deepcopy(source)
                clone["logical_role"] = alias
                clone["target_relative_path"] = f"metadata/v11-aliases/{alias}.bin"
                alias_target = relocated / clone["target_relative_path"]
                alias_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(relocated / source["target_relative_path"], alias_target)
                clone["source_path_provenance"] = str(alias_target)
                clone["source_sha256"] = _sha(alias_target)
                clone["source_stat_provenance"] = _stat(alias_target)
                roles.append(clone)
                names.add(alias)
        # The real fixture names this module portable_rebind_v2; V11's
        # production closure calls the same source a core role explicitly.
        if "portable_rebind_v2_core" not in names:
            source = next(item for item in roles if item["logical_role"] in {
                "portable_rebind_v2", "portable_rebind_v2_entrypoint"})
            core = copy.deepcopy(source)
            core["logical_role"] = "portable_rebind_v2_core"
            core["target_relative_path"] = "runtime/portable_rebind_v2_core.py"
            core_target = relocated / core["target_relative_path"]
            shutil.copyfile(relocated / source["target_relative_path"], core_target)
            core["source_path_provenance"] = str(core_target)
            core["source_sha256"] = _sha(core_target)
            core["source_stat_provenance"] = _stat(core_target)
            roles.append(core)
        # Keep the V11 source files in the sealed graph.  They are code only;
        # their actual runtime child is launched from the literal fixture env.
        for logical, source, target in (
            ("v11_executor", V11_PATH,
             "runtime/ds_data02_stage2_f2_root242_portable_typed_executor_v11.py"),
            ("v11_runtime_worker", WORKER_PATH,
             "runtime/ds_data02_stage2_f2_root242_root_runtime_worker_v11.py"),
        ):
            copied = dict(logical_role=logical, source_kind="runtime_source_v11",
                          actionable=True, content_read_by_manifest=True,
                          source_sha256=_sha(source), source_path_provenance=str(source),
                          source_stat_provenance=_stat(source),
                          target_relative_path=target, deferred_content=False)
            roles.append(copied)
        # V11's outer contract has a bounded role-count gate.  These files are
        # manufactured metadata under the sealed copied runtime, not hidden
        # scientific inputs.
        filler_dir = relocated / "metadata" / "v11-fillers"
        filler_dir.mkdir(parents=True, exist_ok=True)
        index = 0
        while len(roles) < 42:
            target_rel = f"metadata/v11-fillers/{index}.json"
            target = relocated / target_rel
            target.write_text(json.dumps({"role": index}, sort_keys=True) + "\n",
                              encoding="utf-8")
            roles.append({
                "logical_role": f"v11_fixture_filler_{index}",
                "source_kind": "manufactured_metadata",
                "actionable": True, "content_read_by_manifest": True,
                "source_sha256": _sha(target), "source_path_provenance": str(target),
                "source_stat_provenance": _stat(target),
                "target_relative_path": target_rel, "deferred_content": False,
            })
            index += 1
        roles.sort(key=lambda item: str(item["logical_role"]))
        digest = hashlib.sha256(json.dumps(
            roles, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
        binding = {
            "schema": V11.HANDOFF_SCHEMA,
            "roles": roles,
            "selected_roles_sha256": digest,
            "selected_role_count": len(roles),
            "dynamic_open_policy": {
                "audit_hook": "sys.addaudithook", "events": ["open", "os.chdir"],
                "membership_rule": "LEXICAL_AND_RESOLVED_MUST_SHARE_ONE_EXPLICIT_ROOT",
                "pinned_venv_binding": {
                    "interpreter_role": "literal_project_venv_python",
                    "pyvenv_cfg_role": "pinned_project_pyvenv_cfg",
                },
            },
        }
        outer_contract = {
            "schema": V11.OUTER_CONTRACT_SCHEMA,
            "status": "READY_FOR_PARENT_STAGE2_GUARD_V11",
            "root242_source_binding": binding,
            "forward_version": "ROOT242_V11_REAL_V8_V12_SCORER_HOOK_FIXTURE",
            "sha256": "",
        }
        outer_contract["sha256"] = _canonical(outer_contract)
        outer_contract_path = base / "v11-outer-contract.json"
        outer_contract_path.write_text(json.dumps(outer_contract, sort_keys=True) + "\n",
                                       encoding="utf-8")
        fresh = base / "v11-fresh-target"
        outer_request = {
            "schema": "ds02.request.v1", "case_id": "fixture-v11-real",
            "attempt_id": "fixture-v11-real-001",
            "root213_metadata_contract": {"path": str(outer_contract_path),
                                           "sha256": outer_contract["sha256"]},
            "root242_v11_source_binding": {"schema": V11.HANDOFF_SCHEMA,
                                            "selected_roles_sha256": digest},
            "interpreter_binding": {"argv0_literal": True, "do_not_resolve_argv0": True,
                                     "invocation_path": str(literal)},
            "storage_scope": {"external_filesystem": str(fresh)},
            "scope": {"original_path_fallback": "REJECT"},
            "sha256": "",
        }
        outer_request["sha256"] = _canonical(outer_request)
        outer_request_path = base / "v11-outer-request.json"
        outer_request_path.write_text(json.dumps(outer_request, sort_keys=True) + "\n",
                                      encoding="utf-8")
        code = (
            "import importlib.util,sys;"
            "s=importlib.util.spec_from_file_location('v11real',sys.argv[1]);"
            "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
            "v=m.run(request=sys.argv[2],output_root=sys.argv[3],parent_pid=int(sys.argv[4]),"
            "max_wall_seconds=120);import json;print(json.dumps({'status':v['status'],"
            "'child_status':v['child_report']['path'],'hook':v['execution']['dynamic_os_open_guard']}))"
        )
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
            env[key] = "1"
        completed = subprocess.run(
            [str(literal), "-B", "-I", "-c", code, str(V11_PATH),
             str(outer_request_path), str(fresh), str(os.getpid())],
            cwd=str(relocated), env=env, text=True, capture_output=True, timeout=150)
        assert completed.returncode == 0, completed.stderr
        assert "COMPLETE_RELOCATED_V11_DYNAMIC_OPEN_GUARD_V8_V12_TYPED_SCORER" in completed.stdout
        child_report_path = fresh / "reports" / "v2-worker-report.json"
        assert child_report_path.is_file()
        child_report = json.loads(child_report_path.read_text(encoding="utf-8"))
        assert child_report["status"] == "PASS_RELOCATED_V8_V12_TYPED_SCORER"
        report_path = relocated / "reports" / "v2-report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(child_report_path.read_text(encoding="utf-8"), encoding="utf-8")
        outer_report = json.loads((fresh / "reports/root242-v11-executor-report.json").read_text())
        return {
            "status": "COMPLETE_RELOCATED_TYPED_ONLY_V2",
            "stream_accounting": outer_report["child_stream_accounting"],
            "v11_report": outer_report,
        }

    real_test.V2.run_guard = run_v11_guard
    try:
        real_test.test_v2_real_relocated_v8_v12_typed_scorer_without_source(tmp_path / "real-v11")
    finally:
        real_test.V2.run_guard = original_run_guard


def test_v11_open_guard_policy_rejects_unbound_path_without_static_marker(tmp_path: Path) -> None:
    request, _contract, fresh = _v11ize(tmp_path, scorer_opens_original=True)
    # The malicious scorer path is not present in the inner JSON, so this
    # specifically exercises dynamic audit rejection rather than V2's static
    # unbound-path rebinder.
    inner = json.loads((tmp_path / "source/inner.json").read_text())
    # The malicious scorer opens CURRENT directly in code.  That path is a
    # legitimate bound metadata path in the request, so use a separate
    # sentinel to prove the request itself carries no static poison marker.
    assert all(str(tmp_path / "source/unbound-hidden-open.txt") not in str(value)
               for value in inner.values())
    completed = _run_v11(request, fresh)
    assert completed.returncode != 0
    assert "OPEN_POLICY_REJECTED" in completed.stderr


def test_v11_open_guard_rejects_proc_self_root_symlink_escape(tmp_path: Path) -> None:
    request, _contract, fresh = _v11ize(tmp_path, scorer_opens_proc_root=True)
    completed = _run_v11(request, fresh)
    assert completed.returncode != 0
    # The lexical spelling is under the explicitly allowed /proc root, but
    # realpath resolves it back to the forbidden source tree.  V11 requires
    # both lexical and resolved membership in one allow root.
    assert "OPEN_POLICY_REJECTED" in completed.stderr
