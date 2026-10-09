"""Independent primary-venv V11 integration coverage.

This file intentionally does not modify or re-use the consumed V11 test.  It
runs the existing manufactured real V8/V12/typed-scorer bundle through the
same V11 hook while invoking the literal primary project interpreter.  The
real pyvenv.cfg and installed numpy/h5py site-packages are bound as external
runtime roles; the semantic data remain manufactured test files.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

_DYNAMIC_PATH = Path(__file__).with_name("test_ds_data02_stage2_f2_root242_v11_dynamic_open.py")
_spec = importlib.util.spec_from_file_location("root242_v11_dynamic_source_for_primary", _DYNAMIC_PATH)
assert _spec is not None and _spec.loader is not None
_dynamic = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _dynamic
_spec.loader.exec_module(_dynamic)

ROOT = _dynamic.ROOT
V11_PATH = _dynamic.V11_PATH
WORKER_PATH = _dynamic.WORKER_PATH
V11 = _dynamic.V11
_load = _dynamic._load
_sha = _dynamic._sha
_stat = _dynamic._stat
_canonical = _dynamic._canonical

PRIMARY_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab")
PRIMARY_PYTHON = PRIMARY_ROOT / ".venv" / "bin" / "python"
PRIMARY_PYVENVCFG = PRIMARY_ROOT / ".venv" / "pyvenv.cfg"

def test_v11_real_v8_v12_typed_scorer_bundle_through_primary_venv_hook(tmp_path: Path) -> None:
    """Run the real V8/V12/scorer fixture inside the V11 audit process.

    The existing real-bundle test exercises V2 directly.  This adapter keeps
    that fixture's copied runtime and semantic modules, seals an outer V11
    contract against the already-relocated files, and replaces only the
    fixture's final V2 ``run_guard`` call with a primary project venv V11 subprocess.
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
        # Use the actual primary project environment as argv[0].  The old
        # dynamic-open test copied the fixture interpreter into a synthetic
        # environment; this test deliberately binds the real venv, including
        # its pyvenv.cfg and site-packages, without resolving the symlink.
        primary_root = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab")
        literal = primary_root / ".venv" / "bin" / "python"
        pyvenv_cfg = primary_root / ".venv" / "pyvenv.cfg"
        assert literal == PRIMARY_PYTHON
        assert pyvenv_cfg == PRIMARY_PYVENVCFG
        assert literal.is_file() and not literal.is_dir()
        assert pyvenv_cfg.is_file() and not pyvenv_cfg.is_symlink()
        primary_import = subprocess.run(
            [str(literal), "-B", "-I", "-c",
             "import sys,numpy,h5py; print(sys.executable); print(numpy.__version__,h5py.__version__)"],
            text=True, capture_output=True, check=False, timeout=30,
        )
        assert primary_import.returncode == 0, primary_import.stderr
        assert primary_import.stdout.splitlines()[0] == str(literal)
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
        # V11 permits the pinned interpreter symlink as the sole environment
        # exception; bind content/mode stat to its executable target because
        # the copier intentionally hashes/follows that role.
        env_role["source_stat_provenance"] = _stat(literal, follow=True)
        cfg_role = next(item for item in roles
                         if item["logical_role"] == "pinned_project_pyvenv_cfg")
        cfg_role["source_path_provenance"] = str(pyvenv_cfg)
        cfg_role["source_sha256"] = _sha(pyvenv_cfg)
        cfg_role["source_stat_provenance"] = _stat(pyvenv_cfg)
        scorer_role = next(item for item in roles
                           if item["logical_role"] == "typed_only_evaluator_v1")
        scorer_target = Path(scorer_role["source_path_provenance"])
        scorer_text = scorer_target.read_text(encoding="utf-8")
        primary_probe = (
            "\nimport json as _v11_primary_json\n"
            "import sys as _v11_primary_sys\n"
            "from pathlib import Path as _v11_primary_Path\n"
            "import numpy as _v11_primary_numpy\n"
            "import h5py as _v11_primary_h5py\n"
            "_v11_primary_marker = _v11_primary_Path(__file__).resolve().parents[1] / "
            "'metadata' / 'primary-venv-import-probe.json'\n"
            "_v11_primary_marker.parent.mkdir(parents=True, exist_ok=True)\n"
            "_v11_primary_marker.write_text(_v11_primary_json.dumps({"
            "'argv0': _v11_primary_sys.executable, "
            "'numpy': _v11_primary_numpy.__version__, "
            "'h5py': _v11_primary_h5py.__version__}, sort_keys=True) + '\\n', "
            "encoding='utf-8')\n"
        )
        future = "from __future__ import annotations\n"
        if future in scorer_text:
            scorer_text = scorer_text.replace(future, future + primary_probe, 1)
        else:
            scorer_text = primary_probe.lstrip("\n") + scorer_text
        scorer_target.write_text(scorer_text, encoding="utf-8")
        scorer_role["source_sha256"] = _sha(scorer_target)
        scorer_role["source_stat_provenance"] = _stat(scorer_target)
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
        primary_probe_path = fresh / "metadata" / "primary-venv-import-probe.json"
        assert primary_probe_path.is_file()
        primary_probe = json.loads(primary_probe_path.read_text(encoding="utf-8"))
        assert primary_probe["argv0"] == str(PRIMARY_PYTHON)
        assert isinstance(primary_probe["numpy"], str) and primary_probe["numpy"]
        assert isinstance(primary_probe["h5py"], str) and primary_probe["h5py"]
        assert str(literal) == str(PRIMARY_PYTHON)
        assert str(pyvenv_cfg) == str(PRIMARY_PYVENVCFG)
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
